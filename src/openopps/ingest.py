from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger
from pydantic import ValidationError

from openopps.discovery.accounting import (
    ROUTE_DISPOSITIONS,
    SOURCE_DISPOSITIONS,
    build_route_accounting,
    build_source_accounting,
    classify_typed_degraded,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.models import (
    RouteDisposition,
    RouteOutcome,
    SourceDisposition,
    SourceOutcome,
)
from openopps.discovery.transport import OperationLedger
from openopps.enrichment import enrich_metadata
from openopps.http import build_async_client, safe_exception_message
from openopps.metrics import (
    ProgressReporter,
    ProgressUpdate,
    SyncMetrics,
    bind_http_retry_metrics,
    combine_sync_metrics,
    reset_http_retry_metrics,
    route_conservation_payload,
    source_conservation_payload,
)
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.boards import build_job_provider
from openopps.providers.base import JobFetchResult
from openopps.providers.sources import BOARD_SOURCE_CATALOG, build_source_adapter
from openopps.route_probe import probe_routes
from openopps.route_registry import BoardRouteRegistry
from openopps.route_select import normalize_provider_filter, route_request_key
from openopps.settings import OpenOppsSettings
from openopps.source_resolution import resolve_effective_sources
from openopps.source_policy import (
    load_source_policy_evidence,
    match_source_policy_denials,
)
from openopps.storage import OpenOppsStore, append_jsonl
from openopps.utils import stable_id

_BUILTIN_ROUTE_ABSENT_STATUSES = {
    provider_id: frozenset({404, 410})
    for provider_id in (
        "ashbyhq",
        "bamboohr",
        "consider_jobs",
        "greenhouse",
        "lever",
        "rippling",
        "teamtailor",
        "workable",
        "workday",
        "wpjobmanager",
    )
}
_RETAINED_ROUTE_HTTP_REASONS = {
    400: "invalid_request",
    401: "authentication_required",
    403: "access_forbidden",
}


@dataclass(frozen=True)
class _RouteFailureDisposition:
    status_code: int
    deactivate: bool
    close_missing: bool
    error_reason: str


def _ingest_freshness_digest(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _source_disposition_for_error(exc: Exception) -> SourceDisposition:
    reason = _error_reason(exc, "source_fetch")
    if reason == "timeout":
        return "timed_out"
    if reason == "rate_limited":
        return "rate_limited"
    return "failed"


def _route_disposition_for_error(exc: Exception) -> RouteDisposition:
    reason = _error_reason(exc, "job_fetch")
    if reason == "timeout":
        return "timed_out"
    if reason == "rate_limited":
        return "rate_limited"
    return "failed"


def _source_run_state(outcomes: Sequence[SourceOutcome], *, interrupted: bool) -> str:
    del outcomes
    if interrupted:
        return "cancelled"
    return "succeeded"


def _route_run_state(outcomes: Sequence[RouteOutcome], *, interrupted: bool) -> str:
    del outcomes
    if interrupted:
        return "cancelled"
    return "succeeded"


def _source_conservation_from_accounting(accounting) -> dict[str, bool | int]:
    terminals = {name: getattr(accounting, name) for name in SOURCE_DISPOSITIONS}
    return source_conservation_payload(
        planned=accounting.planned,
        terminals=terminals,
        terminal=accounting.terminal,
        complete=accounting.complete,
    )


def _route_conservation_from_accounting(accounting) -> dict[str, bool | int]:
    terminals = {name: getattr(accounting, name) for name in ROUTE_DISPOSITIONS}
    return route_conservation_payload(
        planned=accounting.planned,
        terminals=terminals,
        terminal=accounting.terminal,
        complete=accounting.complete,
        authoritative_succeeded=accounting.authoritative_succeeded,
    )


@dataclass
class _SourcePin:
    planned_ids: tuple[str, ...]
    freshness_digest: str
    launched: set[str] = field(default_factory=set)
    outcomes: dict[str, SourceOutcome] = field(default_factory=dict)
    accounting: object | None = field(default=None, init=False, repr=False)

    def mark_launched(self, source_id: str) -> None:
        self.launched.add(source_id)

    def record(
        self,
        source_id: str,
        disposition: SourceDisposition,
        *,
        authoritative: bool | None = None,
        freshness_context_digest: str | None = None,
    ) -> None:
        if source_id in self.outcomes:
            raise ValueError("planned source denominator is not conserved")
        if disposition not in SOURCE_DISPOSITIONS:
            raise ValueError("source disposition is not a terminal class")
        if authoritative is None:
            authoritative = disposition in {"succeeded", "fresh_skipped"}
        self.outcomes[source_id] = SourceOutcome(
            source_id=source_id,
            disposition=disposition,
            started=disposition != "unstarted",
            authoritative=authoritative,
            freshness_context_digest=freshness_context_digest,
        )

    def interrupt(self, source_id: str) -> None:
        if source_id in self.outcomes:
            return
        if source_id in self.launched:
            self.record(source_id, "cancelled")

    def close(self, *, interrupted: bool) -> dict[str, bool | int]:
        if not self.planned_ids:
            self.accounting = build_source_accounting(
                planned_source_ids=(),
                outcomes=(),
                run_state=_source_run_state((), interrupted=interrupted),
                freshness_context_digest=self.freshness_digest,
            )
            return _source_conservation_from_accounting(self.accounting)
        for source_id in self.planned_ids:
            if source_id in self.outcomes:
                continue
            if interrupted:
                if source_id in self.launched:
                    self.record(source_id, "cancelled")
                else:
                    self.record(source_id, "unstarted")
            else:
                raise ValueError("planned source denominator is not conserved")
        ordered = tuple(self.outcomes[source_id] for source_id in self.planned_ids)
        self.accounting = build_source_accounting(
            planned_source_ids=self.planned_ids,
            outcomes=ordered,
            run_state=_source_run_state(ordered, interrupted=interrupted),
            freshness_context_digest=self.freshness_digest,
        )
        return _source_conservation_from_accounting(self.accounting)


@dataclass
class _PendingDuplicate:
    route_id: str
    representative_id: str | None
    request_key: str


@dataclass
class _RoutePin:
    planned_ids: tuple[str, ...]
    freshness_digest: str
    launched: set[str] = field(default_factory=set)
    outcomes: dict[str, RouteOutcome] = field(default_factory=dict)
    pending_duplicates: list[_PendingDuplicate] = field(default_factory=list)
    accounting: object | None = field(default=None, init=False, repr=False)

    def mark_launched(self, route_id: str) -> None:
        self.launched.add(route_id)

    def record(
        self,
        route_id: str,
        disposition: RouteDisposition,
        *,
        authoritative: bool | None = None,
        freshness_context_digest: str | None = None,
        representative_id: str | None = None,
    ) -> None:
        if route_id in self.outcomes:
            raise ValueError("planned route denominator is not conserved")
        if disposition not in ROUTE_DISPOSITIONS:
            raise ValueError("route disposition is not a terminal class")
        if authoritative is None:
            authoritative = disposition in {"succeeded", "fresh_skipped"}
        self.outcomes[route_id] = RouteOutcome(
            route_id=route_id,
            disposition=disposition,
            representative_id=representative_id,
            started=disposition != "unstarted",
            authoritative=authoritative,
            freshness_context_digest=freshness_context_digest,
        )

    def interrupt(self, route_id: str) -> None:
        if route_id in self.outcomes:
            return
        if route_id in self.launched:
            self.record(route_id, "cancelled")

    def close(self, *, interrupted: bool) -> dict[str, bool | int]:
        if not self.planned_ids:
            self.accounting = build_route_accounting(
                planned_route_ids=(),
                outcomes=(),
                run_state=_route_run_state((), interrupted=interrupted),
                freshness_context_digest=self.freshness_digest,
            )
            return _route_conservation_from_accounting(self.accounting)
        self._close_duplicates(interrupted=interrupted)
        missing = [route_id for route_id in self.planned_ids if route_id not in self.outcomes]
        if missing:
            if interrupted:
                for route_id in missing:
                    if route_id in self.launched:
                        self.record(route_id, "cancelled")
                    else:
                        self.record(route_id, "unstarted")
            else:
                raise ValueError("planned route denominator is not conserved")
        ordered = tuple(self.outcomes[route_id] for route_id in self.planned_ids)
        self.accounting = build_route_accounting(
            planned_route_ids=self.planned_ids,
            outcomes=ordered,
            run_state=_route_run_state(ordered, interrupted=interrupted),
            freshness_context_digest=self.freshness_digest,
        )
        return _route_conservation_from_accounting(self.accounting)

    def _close_duplicates(self, *, interrupted: bool) -> None:
        for pending in self.pending_duplicates:
            if pending.route_id in self.outcomes:
                continue
            representative = self.outcomes.get(pending.representative_id or "")
            if (
                representative is not None
                and representative.disposition in {"succeeded", "fresh_skipped"}
                and representative.authoritative
            ):
                self.record(
                    pending.route_id,
                    "duplicate_skipped",
                    representative_id=representative.route_id,
                    authoritative=False,
                )
                continue
            if representative is not None and representative.disposition == "deferred":
                self.record(pending.route_id, "deferred", authoritative=False)
                continue
            if interrupted or representative is None:
                if pending.route_id in self.launched:
                    self.record(pending.route_id, "cancelled")
                else:
                    self.record(pending.route_id, "unstarted")
                continue
            self.record(pending.route_id, "unstarted")



@dataclass(frozen=True)
class ApprovedIngestionPin:
    """Frozen scheduled-ingest selector: envelope keys plus deny-only policy overlay."""

    frozen_source_ids: tuple[str, ...]
    denied_source_keys: frozenset[str]
    envelope_id: str
    catalog_content_digest: str
    catalog_tree_digest: str
    selector_digest: str
    policy_digest: str
    promotion_digest: str
    checkout_sha: str


def prepare_ingest_pin(
    repository_root: Path,
    *,
    catalog: dict[str, SourceRecord] | None = None,
) -> ApprovedIngestionPin:
    """Validate the packaged envelope before scheduled ingest network work."""

    from openopps.discovery.diagnostics import prepare_selector_bound_scout

    scout = prepare_selector_bound_scout(repository_root)
    catalog_map = BOARD_SOURCE_CATALOG if catalog is None else catalog
    missing = any(key not in catalog_map for key in scout.frozen_source_ids)
    if missing:
        raise ValueError("approved-ingestion pin does not match catalog")
    denials = match_source_policy_denials(
        source_keys=scout.frozen_source_ids,
        evidence=load_source_policy_evidence(),
        catalog=catalog_map,
    )
    envelope = scout.envelope
    policy_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "code": envelope.v7_policy_code_digest,
                "corpus": envelope.v7_policy_corpus_digest,
                "evidence": envelope.v7_policy_evidence_digest,
                "schema": envelope.v7_policy_schema_digest,
                "supplementary": envelope.supplementary_policy_digest,
            }
        )
    ).hexdigest()
    return ApprovedIngestionPin(
        frozen_source_ids=scout.frozen_source_ids,
        denied_source_keys=frozenset(denials),
        envelope_id=envelope.envelope_id,
        catalog_content_digest=envelope.catalog_content_digest,
        catalog_tree_digest=envelope.catalog_tree_digest,
        selector_digest=envelope.source_key_digest,
        policy_digest=policy_digest,
        promotion_digest=envelope.promotion_digest,
        checkout_sha=scout.checkout_sha,
    )


def _scoped_source_keys(
    source_key: str | None,
    source_keys: Sequence[str] | None,
) -> tuple[str, ...] | None:
    if source_key:
        return (source_key,)
    if source_keys:
        return tuple(source_keys)
    return None


def _ingest_evidence_digest(
    *,
    pin: ApprovedIngestionPin,
    attestation: str,
    degraded_class: str | None,
    source_conservation: dict[str, bool | int],
    route_conservation: dict[str, bool | int],
) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "attestation": attestation,
                "catalogContentDigest": pin.catalog_content_digest,
                "conservation": {
                    "routes": route_conservation,
                    "sources": source_conservation,
                },
                "degradedClass": degraded_class,
                "envelopeId": pin.envelope_id,
                "policyDigest": pin.policy_digest,
                "promotionDigest": pin.promotion_digest,
                "selectorDigest": pin.selector_digest,
            }
        )
    ).hexdigest()
    return f"sha256:{digest}"


def _attach_scheduled_attestation(
    metrics: SyncMetrics,
    *,
    pin: ApprovedIngestionPin,
) -> SyncMetrics:
    source = metrics.source_accounting
    route = metrics.route_accounting
    if source is None or route is None:
        raise ValueError("scheduled ingest did not close source and route accounting")
    ledger = OperationLedger(
        planned_operation_ids=("ingest-sources", "ingest-boards", "ingest-jobs")
    )
    for operation_id in ("ingest-sources", "ingest-boards", "ingest-jobs"):
        ledger.start(operation_id)
        ledger.finish(operation_id, outcome="succeeded")
    channel_state = "complete" if source.complete and route.complete else "partial"
    operations = ledger.close(channel_state=channel_state)
    attestation, degraded_class = classify_typed_degraded(
        source=source,
        route=route,
        operation_terminals=operations.terminals,
        operation_channel_state=operations.channel_state,
        run_state="succeeded",
    )
    metrics.schema_version = 1
    metrics.run_id = stable_id("ingest", pin.envelope_id, pin.checkout_sha)
    metrics.attestation = attestation
    metrics.degraded_class = degraded_class
    if metrics.source_conservation is None or metrics.route_conservation is None:
        raise ValueError("scheduled ingest did not emit conservation payloads")
    metrics.evidence_digest = _ingest_evidence_digest(
        pin=pin,
        attestation=attestation,
        degraded_class=degraded_class,
        source_conservation=metrics.source_conservation,
        route_conservation=metrics.route_conservation,
    )
    return metrics


async def sync_all(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    output: Path | None = None,
    page_size: int = 100,
    max_candidates: int = 12,
    limit: int | None = None,
    verbose: bool = False,
    report: ProgressReporter | None = None,
    pin: ApprovedIngestionPin | None = None,
    repository_root: Path | None = None,
    catalog: dict[str, SourceRecord] | None = None,
) -> SyncMetrics:
    """Run sources, boards, and jobs. Unscoped runs pin the approved envelope."""

    scheduled = source_key is None
    pinned_source_ids: tuple[str, ...] | None = None
    denied_source_keys: frozenset[str] | None = None
    scheduled_pin = pin
    if scheduled:
        catalog_map = BOARD_SOURCE_CATALOG if catalog is None else catalog
        if scheduled_pin is None:
            root = repository_root if repository_root is not None else Path.cwd()
            scheduled_pin = prepare_ingest_pin(root, catalog=catalog_map)
        missing = any(key not in catalog_map for key in scheduled_pin.frozen_source_ids)
        if missing:
            raise ValueError("approved-ingestion pin does not match catalog")
        pinned_source_ids = scheduled_pin.frozen_source_ids
        denied_source_keys = scheduled_pin.denied_source_keys
    source_metrics = await sync_sources(
        settings=settings,
        store=store,
        source_key=source_key,
        page_size=page_size,
        verbose=verbose,
        report=report,
        pinned_source_ids=pinned_source_ids,
        denied_source_keys=denied_source_keys,
    )
    board_metrics = await sync_boards(
        settings=settings,
        store=store,
        source_key=source_key,
        source_keys=pinned_source_ids,
        board_key=board_key,
        provider_id=provider_id,
        max_candidates=max_candidates,
        limit=limit,
        verbose=verbose,
        report=report,
    )
    job_metrics = await sync_jobs(
        settings=settings,
        store=store,
        source_key=source_key,
        source_keys=pinned_source_ids,
        board_key=board_key,
        provider_id=provider_id,
        output=output,
        freshness_seconds=settings.job_route_freshness_seconds,
        limit=settings.job_route_limit,
        verbose=verbose,
        report=report,
    )
    combined = combine_sync_metrics("sync", source_metrics, board_metrics, job_metrics)
    if scheduled:
        if scheduled_pin is None:
            raise ValueError("scheduled ingest pin is required")
        return _attach_scheduled_attestation(combined, pin=scheduled_pin)
    return combined


def all_board_sources() -> list[SourceRecord]:
    return list(BOARD_SOURCE_CATALOG.values())


async def sync_sources(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore | None,
    source_key: str | None = None,
    output: Path | None = None,
    page_size: int = 100,
    verbose: bool = False,
    report: ProgressReporter | None = None,
    metrics: SyncMetrics | None = None,
    pinned_source_ids: Sequence[str] | None = None,
    denied_source_keys: frozenset[str] | None = None,
) -> SyncMetrics:
    metrics = metrics if metrics is not None else SyncMetrics(name="sources.sync")
    retry_token = bind_http_retry_metrics(metrics)
    try:
        return await _sync_sources_bound(
            settings=settings,
            store=store,
            source_key=source_key,
            output=output,
            page_size=page_size,
            verbose=verbose,
            report=report,
            metrics=metrics,
            pinned_source_ids=pinned_source_ids,
            denied_source_keys=denied_source_keys,
        )
    finally:
        reset_http_retry_metrics(retry_token)


async def _sync_sources_bound(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore | None,
    source_key: str | None,
    output: Path | None,
    page_size: int,
    verbose: bool,
    report: ProgressReporter | None,
    metrics: SyncMetrics,
    pinned_source_ids: Sequence[str] | None,
    denied_source_keys: frozenset[str] | None,
) -> SyncMetrics:
    selected_sources = _select_sources(
        store, source_key, pinned_source_ids=pinned_source_ids
    )
    planned_ids = (
        tuple(dict.fromkeys(pinned_source_ids))
        if pinned_source_ids is not None
        else tuple(dict.fromkeys(source.key for source in selected_sources))
    )
    if pinned_source_ids is not None:
        selected_keys = {source.key for source in selected_sources}
        if any(key not in selected_keys for key in pinned_source_ids):
            raise ValueError("approved-ingestion pin does not match catalog")
    freshness_digest = _ingest_freshness_digest(
        "openopps.ingest.source",
        f"freshness-seconds:{settings.source_freshness_seconds}",
    )
    source_pin = _SourcePin(
        planned_ids=planned_ids,
        freshness_digest=freshness_digest,
    )
    denied = denied_source_keys or frozenset()
    blocked_sources = [source for source in selected_sources if source.key in denied]
    selected_sources = [
        source for source in selected_sources if source.key not in denied
    ]
    for source in blocked_sources:
        source_pin.record(source.key, "policy_blocked", authoritative=False)
    fresh_sources, sources = _partition_fresh_sources(
        selected_sources,
        freshness_seconds=settings.source_freshness_seconds,
        source_key=source_key,
    )
    for source in fresh_sources:
        source_pin.record(
            source.key,
            "fresh_skipped",
            authoritative=True,
            freshness_context_digest=freshness_digest,
        )
    metrics.skipped += len(fresh_sources)
    source_total = len(sources)
    completed_sources = 0
    unique_board_keys: set[str] = set()
    progress_lock = asyncio.Lock()
    _report(
        report,
        "sources",
        _source_progress_message(
            0,
            source_total,
            0,
            _phase_detail("queue", "waiting for adapters"),
        ),
        completed=0,
        total=source_total,
    )
    if store:
        for source in sources:
            store.upsert_source(source)
    write_lock = asyncio.Lock()
    async with build_async_client(settings) as client:
        semaphore = asyncio.Semaphore(settings.source_concurrency)

        async def run_source(source: SourceRecord) -> None:
            nonlocal completed_sources
            try:
                async with semaphore:
                    source_pin.mark_launched(source.key)
                    adapter = build_source_adapter(source.provider_id, settings)
                    if not adapter:
                        source_pin.record(source.key, "failed", authoritative=False)
                        if verbose:
                            logger.warning("No source adapter for {}", source.provider_id)
                        metrics.skipped += 1
                        async with progress_lock:
                            completed_sources += 1
                            _report_source_progress(
                                report,
                                completed_sources,
                                source_total,
                                _unique_board_count(store, source_key, unique_board_keys),
                                _source_detail(source.key, "skipped: no adapter"),
                            )
                        return
                    _report(
                        report,
                        "sources",
                        _source_progress_message(
                            completed_sources,
                            source_total,
                            _unique_board_count(store, source_key, unique_board_keys),
                            _source_detail(source.key, "discovering boards"),
                        ),
                        completed=completed_sources,
                        total=source_total,
                    )
                    logger.trace(
                        "Starting source sync source={} provider={}",
                        source.key,
                        source.provider_id,
                    )
                    source_route_ids: set[str] = set()
                    saw_provider_route_hints = False
                    latest_source = source
                    try:
                        async with asyncio.timeout(settings.source_timeout_seconds):
                            async for boards, providers, page_meta in adapter.iter_boards(
                                client, source, page_size=page_size
                            ):
                                compact_meta = _compact_page_meta(page_meta)
                                metrics.pages += 1
                                metrics.boards += len(boards)
                                metrics.board_providers += len(providers)
                                logger.trace(
                                    "Source page synced source={} boards={} provider_hints={} page_meta={}",
                                    source.key,
                                    len(boards),
                                    len(providers),
                                    compact_meta,
                                )
                                latest_source = source.model_copy(
                                    update={
                                        "version": page_meta.get("version") or {},
                                        "raw_metadata": source.raw_metadata
                                        | {"lastPage": compact_meta},
                                        "synced_at": source.synced_at,
                                    }
                                )
                                if store or output:
                                    async with write_lock:
                                        if store:
                                            store.upsert_source(latest_source)
                                            store.upsert_boards(boards)
                                            if providers:
                                                saw_provider_route_hints = True
                                            source_route_ids.update(
                                                store.upsert_board_providers(
                                                    providers, boards=boards
                                                )
                                            )
                                            unique_count = store.count_boards(
                                                source_key=source_key
                                            )
                                        else:
                                            _track_unique_boards(unique_board_keys, boards)
                                            unique_count = len(unique_board_keys)
                                        if output:
                                            append_jsonl(output, boards)
                                        _report_source_progress(
                                            report,
                                            completed_sources,
                                            source_total,
                                            unique_count,
                                            _source_detail(
                                                source.key,
                                                (
                                                    f"+{_format_count(len(boards))} boards "
                                                    f"+{_format_count(len(providers))} routes"
                                                ),
                                            ),
                                        )
                        if store and saw_provider_route_hints:
                            async with write_lock:
                                store.reconcile_source_board_provider_routes(
                                    source.key, source_route_ids
                                )
                        if store:
                            async with write_lock:
                                store.upsert_source(
                                    latest_source.model_copy(
                                        update={"synced_at": utc_now()}
                                    )
                                )
                        source_pin.record(source.key, "succeeded", authoritative=True)
                        async with progress_lock:
                            completed_sources += 1
                            _report_source_progress(
                                report,
                                completed_sources,
                                source_total,
                                _unique_board_count(store, source_key, unique_board_keys),
                                _source_detail(source.key, "complete"),
                            )
                    except Exception as exc:
                        source_pin.record(
                            source.key,
                            _source_disposition_for_error(exc),
                            authoritative=False,
                        )
                        error_reason = _error_reason(exc, "source_fetch")
                        metrics.error(source.provider_id, error_reason)
                        metrics.skipped += 1
                        async with progress_lock:
                            completed_sources += 1
                            _report_source_progress(
                                report,
                                completed_sources,
                                source_total,
                                _unique_board_count(store, source_key, unique_board_keys),
                                _source_detail(
                                    source.key,
                                    "skipped: timeout"
                                    if error_reason == "timeout"
                                    else "skipped: error",
                                ),
                            )
                        if verbose:
                            logger.warning(
                                "Failed to sync source={} provider={}: {}",
                                source.key,
                                source.provider_id,
                                _format_exception(exc),
                            )
            except asyncio.CancelledError:
                source_pin.interrupt(source.key)
                raise

        interrupted = False
        try:
            await asyncio.gather(*(run_source(source) for source in sources))
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            metrics.source_conservation = source_pin.close(interrupted=interrupted)
            metrics.source_accounting = getattr(source_pin, "accounting", None)
    return metrics.finish()


async def sync_boards(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    source_keys: Sequence[str] | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    max_candidates: int = 12,
    limit: int | None = None,
    verbose: bool = False,
    report: ProgressReporter | None = None,
) -> SyncMetrics:
    metrics = SyncMetrics(name="boards.sync")
    retry_token = bind_http_retry_metrics(metrics)
    try:
        return await _sync_boards_bound(
            settings=settings,
            store=store,
            source_key=source_key,
            source_keys=source_keys,
            board_key=board_key,
            provider_id=provider_id,
            max_candidates=max_candidates,
            limit=limit,
            verbose=verbose,
            report=report,
            metrics=metrics,
        )
    finally:
        reset_http_retry_metrics(retry_token)


async def _sync_boards_bound(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None,
    source_keys: Sequence[str] | None,
    board_key: str | None,
    provider_id: str | None,
    max_candidates: int,
    limit: int | None,
    verbose: bool,
    report: ProgressReporter | None,
    metrics: SyncMetrics,
) -> SyncMetrics:
    scoped_keys = _scoped_source_keys(source_key, source_keys)
    if scoped_keys is None:
        board_total = len(
            store.list_boards(source_key=source_key, board_key=board_key, limit=limit)
        )
    else:
        board_total = sum(
            len(store.list_boards(source_key=key, board_key=board_key, limit=limit))
            for key in scoped_keys
        )
    _report(
        report,
        "boards",
        _board_progress_message(
            0,
            max(board_total, 1),
            _board_detail("enrich", _chunk("event", "scanning metadata", "white")),
        ),
        completed=0,
        total=max(board_total, 1),
    )
    scope_keys = scoped_keys if scoped_keys is not None else (source_key,)
    enrichment_checked = 0
    board_changes = 0
    route_changes = 0
    probe_checked = 0
    probe_matched = 0
    probe_unknown = 0
    probe_ready_skipped = 0
    probe_duplicate_skipped = 0
    for scope_key in scope_keys:
        enrichment = enrich_metadata(
            store,
            source_key=scope_key,
            board_key=board_key,
            limit=limit,
            apply=True,
        )
        enrichment_checked += enrichment.checked_boards
        board_changes += len(enrichment.board_changes)
        route_changes += len(enrichment.route_changes)
        summary = await probe_routes(
            settings=settings,
            store=store,
            source_key=scope_key,
            board_key=board_key,
            provider_id=provider_id,
            only_missing=True,
            apply=True,
            max_candidates=max_candidates,
            limit=limit,
        )
        probe_checked += summary.checked
        probe_matched += len(summary.matched)
        probe_unknown += len(summary.unknown)
        probe_ready_skipped += summary.route_ready_skipped
        probe_duplicate_skipped += summary.duplicate_routes_skipped
        metrics.duplicate_routes_skipped += summary.duplicate_routes_skipped
        for unknown in summary.unknown:
            if unknown.reason in {"probe_error", "rate_limited"}:
                metrics.error(unknown.provider_id, unknown.reason)
    metrics.boards = enrichment_checked
    _report(
        report,
        "boards",
        _board_progress_message(
            enrichment_checked,
            max(board_total, 1),
            _board_detail(
                "enrich",
                _chunk("board-upd", _format_count(board_changes), "green"),
                _chunk("route-upd", _format_count(route_changes), "green"),
            ),
        ),
        completed=enrichment_checked,
        total=max(board_total, 1),
    )
    metrics.board_providers = probe_checked
    _report(
        report,
        "boards",
        _board_progress_message(
            max(board_total, 1),
            max(board_total, 1),
            _board_detail(
                "routes",
                _chunk("checked", _format_count(probe_checked), "cyan"),
                _chunk("ready", _format_count(probe_matched), "green"),
                _chunk("unresolved", _format_count(probe_unknown), "yellow"),
                _chunk(
                    "not-probed",
                    _format_count(probe_ready_skipped + probe_duplicate_skipped),
                    "yellow",
                ),
            ),
        ),
        completed=max(board_total, 1),
        total=max(board_total, 1),
    )
    return metrics.finish()


def _select_sources(
    store: OpenOppsStore | None,
    source_key: str | None,
    *,
    pinned_source_ids: Sequence[str] | None = None,
) -> list[SourceRecord]:
    sources = resolve_effective_sources(
        all_board_sources(), store.list_sources() if store else []
    )
    if source_key:
        for source in sources:
            if source.key == source_key:
                return [source]
        raise ValueError(f"Unknown source: {source_key}")
    if pinned_source_ids is not None:
        by_key = {source.key: source for source in sources}
        return [by_key[key] for key in pinned_source_ids if key in by_key]
    return sources


def _partition_fresh_sources(
    sources: Sequence[SourceRecord],
    *,
    freshness_seconds: float,
    source_key: str | None,
) -> tuple[list[SourceRecord], list[SourceRecord]]:
    if source_key or freshness_seconds <= 0:
        return [], list(sources)
    cutoff = utc_now() - timedelta(seconds=freshness_seconds)
    fresh_sources: list[SourceRecord] = []
    stale_sources: list[SourceRecord] = []
    for source in sources:
        synced_at = source.synced_at
        if synced_at and synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        if synced_at and synced_at >= cutoff:
            fresh_sources.append(source)
        else:
            stale_sources.append(source)
    return fresh_sources, stale_sources


def _compact_page_meta(page_meta: dict) -> dict:
    return {
        key: value
        for key, value in page_meta.items()
        if key != "rawResponse" and key.lower() not in {"raw", "payload"}
    }


async def sync_jobs(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    source_keys: Sequence[str] | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    output: Path | None = None,
    freshness_seconds: float | None = None,
    limit: int | None = None,
    verbose: bool = False,
    report: ProgressReporter | None = None,
    metrics: SyncMetrics | None = None,
) -> SyncMetrics:
    metrics = metrics if metrics is not None else SyncMetrics(name="jobs.sync")
    retry_token = bind_http_retry_metrics(metrics)
    try:
        return await _sync_jobs_bound(
            settings=settings,
            store=store,
            source_key=source_key,
            source_keys=source_keys,
            board_key=board_key,
            provider_id=provider_id,
            output=output,
            freshness_seconds=freshness_seconds,
            limit=limit,
            verbose=verbose,
            report=report,
            metrics=metrics,
        )
    finally:
        reset_http_retry_metrics(retry_token)


async def _sync_jobs_bound(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None,
    source_keys: Sequence[str] | None,
    board_key: str | None,
    provider_id: str | None,
    output: Path | None,
    freshness_seconds: float | None,
    limit: int | None,
    verbose: bool,
    report: ProgressReporter | None,
    metrics: SyncMetrics,
) -> SyncMetrics:
    provider_filter = normalize_provider_filter(provider_id)
    scoped_keys = _scoped_source_keys(source_key, source_keys)
    route_selection = BoardRouteRegistry(store).select(
        source_key=source_key if scoped_keys is None or source_key else None,
        source_keys=None if source_key or scoped_keys is None else scoped_keys,
        board_key=board_key,
        provider_id=provider_filter,
        ready_only=True,
    )
    effective_freshness_seconds = (
        settings.job_route_freshness_seconds
        if freshness_seconds is None
        else freshness_seconds
    )
    effective_limit = settings.job_route_limit if limit is None else limit
    latest_syncs = (
        store.latest_job_syncs()
        if effective_freshness_seconds > 0 or effective_limit
        else {}
    )
    route_entries, fresh_entries, deferred_entries = _select_job_route_entries(
        route_selection.entries,
        latest_syncs=latest_syncs,
        freshness_seconds=effective_freshness_seconds,
        limit=effective_limit,
    )
    duplicate_routes_by_request_key = _duplicate_routes_by_request_key(
        store, route_selection.duplicate_routes
    )
    freshness_digest = _ingest_freshness_digest(
        "openopps.ingest.route",
        f"freshness-seconds:{effective_freshness_seconds}",
        f"limit:{effective_limit}",
    )
    planned_route_ids: list[str] = []
    seen_route_ids: set[str] = set()

    def _plan_route(route_id: str) -> None:
        if route_id and route_id not in seen_route_ids:
            seen_route_ids.add(route_id)
            planned_route_ids.append(route_id)

    for route in route_selection.missing_route_metadata:
        _plan_route(route.id)
    for entry in route_selection.entries:
        _plan_route(entry.route.id)
    for route in route_selection.duplicate_routes:
        _plan_route(route.id)
    route_pin = _RoutePin(
        planned_ids=tuple(planned_route_ids),
        freshness_digest=freshness_digest,
    )
    for route in route_selection.missing_route_metadata:
        route_pin.record(route.id, "missing_metadata", authoritative=False)
    for entry in fresh_entries:
        route_pin.record(
            entry.route.id,
            "fresh_skipped",
            authoritative=True,
            freshness_context_digest=freshness_digest,
        )
    for entry in deferred_entries:
        route_pin.record(entry.route.id, "deferred", authoritative=False)
    representative_by_request_key = {
        entry.request_key: entry.route.id for entry in route_selection.entries
    }
    for route in route_selection.duplicate_routes:
        board = store.get_board(route.board_key)
        request_key = route_request_key(board, route) if board is not None else ""
        route_pin.pending_duplicates.append(
            _PendingDuplicate(
                route_id=route.id,
                representative_id=representative_by_request_key.get(request_key),
                request_key=request_key,
            )
        )
    metrics.duplicate_routes_skipped += len(route_selection.duplicate_routes)
    metrics.skipped += len(fresh_entries) + len(deferred_entries)
    route_total = len(route_entries)
    completed_routes = 0
    progress_lock = asyncio.Lock()
    _report(
        report,
        "jobs",
        _job_progress_message(
            0,
            route_total,
            0,
            _phase_detail(
                "queue",
                (
                    f"{_format_count(route_total)} routes, "
                    f"{_format_count(len(route_selection.duplicate_routes))} dupes, "
                    f"{_format_count(len(route_selection.missing_route_metadata))} no-meta, "
                    f"{_format_count(len(fresh_entries))} fresh, "
                    f"{_format_count(len(deferred_entries))} deferred"
                ),
            ),
        ),
        completed=0,
        total=max(route_total, 1),
    )
    logger.trace(
        "Starting jobs sync executable_routes={} missing_route_metadata_skipped={} duplicates_skipped={} source={} board={} provider={}",
        len(route_entries),
        len(route_selection.missing_route_metadata),
        len(route_selection.duplicate_routes),
        source_key or "all",
        board_key or "all",
        provider_filter or "all",
    )
    semaphore = asyncio.Semaphore(settings.board_concurrency)
    provider_semaphores: dict[str, asyncio.Semaphore] = {}
    write_lock = asyncio.Lock()
    async with build_async_client(settings) as client:

        async def run_route(
            route: BoardProviderRecord, board: BoardRecord, request_key: str
        ) -> None:
            nonlocal completed_routes
            try:
                async with AsyncExitStack() as stack:
                    provider = build_job_provider(route.provider_id, settings)
                    route_concurrency = getattr(provider, "route_concurrency", None)
                    if (
                        isinstance(route_concurrency, int)
                        and not isinstance(route_concurrency, bool)
                        and route_concurrency > 0
                    ):
                        provider_semaphore = provider_semaphores.setdefault(
                            route.provider_id, asyncio.Semaphore(route_concurrency)
                        )
                        await stack.enter_async_context(provider_semaphore)
                    await stack.enter_async_context(semaphore)
                    route_pin.mark_launched(route.id)
                    if not provider:
                        route_pin.record(route.id, "failed", authoritative=False)
                        metrics.skipped += 1
                        async with progress_lock:
                            completed_routes += 1
                            _report_job_progress(
                                report,
                                completed_routes,
                                route_total,
                                metrics.jobs,
                                _job_detail(route.board_key, "skipped: missing provider"),
                            )
                        if verbose:
                            logger.warning(
                                "Skipping job route board={} provider={} missing_provider",
                                route.board_key,
                                route.provider_id,
                            )
                        return
                    if route.support_level != ProviderSupport.JOBS:
                        route_pin.record(route.id, "failed", authoritative=False)
                        metrics.skipped += 1
                        async with progress_lock:
                            completed_routes += 1
                            _report_job_progress(
                                report,
                                completed_routes,
                                route_total,
                                metrics.jobs,
                                _job_detail(route.board_key, "skipped: non-job route"),
                            )
                        if verbose:
                            logger.warning(
                                "Skipping non-job-capable route board={} provider={}",
                                route.board_key,
                                route.provider_id,
                            )
                        return
                    _report(
                        report,
                        "jobs",
                        _job_progress_message(
                            completed_routes,
                            route_total,
                            metrics.jobs,
                            _job_detail(board.key, f"fetching {route.provider_id}"),
                        ),
                        completed=completed_routes,
                        total=max(route_total, 1),
                    )
                    async with write_lock:
                        pending_run = store.begin_job_sync_run(
                            board.key,
                            route.provider_id,
                        )
                    metrics.job_sync_attempts += 1
                    try:
                        async with asyncio.timeout(settings.job_route_timeout_seconds):
                            fetch_result = await provider.fetch_jobs(client, board, route)
                    except asyncio.CancelledError:
                        route_pin.record(route.id, "cancelled")
                        async with write_lock:
                            store.fail_job_sync_run(
                                pending_run.id,
                                error_kind="cancelled",
                                error="Provider job fetch was cancelled.",
                            )
                        raise
                    except Exception as exc:
                        disposition = _route_failure_disposition(route.provider_id, exc)
                        failure_reason = (
                            disposition.error_reason
                            if disposition
                            else _error_reason(exc, "job_fetch")
                        )
                        if disposition and disposition.deactivate:
                            status = f"job_sync_unavailable_{disposition.status_code}"
                            unavailable_routes = [
                                route,
                                *duplicate_routes_by_request_key.get(request_key, []),
                            ]
                            async with write_lock:
                                completed_run_count = _remove_unavailable_routes(
                                    store,
                                    unavailable_routes,
                                    status=status,
                                    close_missing=disposition.close_missing,
                                    selected_route=route,
                                    selected_run_id=pending_run.id,
                                )
                            metrics.job_sync_attempts += max(0, completed_run_count - 1)
                            metrics.job_sync_runs += completed_run_count
                            route_pin.record(route.id, "succeeded", authoritative=True)
                            async with progress_lock:
                                completed_routes += 1
                                _report_job_progress(
                                    report,
                                    completed_routes,
                                    route_total,
                                    metrics.jobs,
                                    _job_detail(board.key, f"removed: {status}"),
                                )
                            if verbose:
                                logger.warning(
                                    "Removed unavailable job route board={} provider={} status={}",
                                    board.key,
                                    route.provider_id,
                                    disposition.status_code,
                                )
                            return
                        error_reason = failure_reason
                        async with write_lock:
                            store.fail_job_sync_run(
                                pending_run.id,
                                error_kind=error_reason,
                                error=_format_exception(exc),
                            )
                        route_pin.record(
                            route.id,
                            _route_disposition_for_error(exc),
                            authoritative=False,
                        )
                        metrics.error(route.provider_id, error_reason)
                        async with progress_lock:
                            completed_routes += 1
                            _report_job_progress(
                                report,
                                completed_routes,
                                route_total,
                                metrics.jobs,
                                _job_detail(
                                    board.key,
                                    "skipped: rate limited"
                                    if error_reason == "rate_limited"
                                    else "skipped: error",
                                ),
                            )
                        if verbose:
                            logger.warning(
                                "Failed to sync jobs for board={} provider={}: {}",
                                board.key,
                                route.provider_id,
                                _format_exception(exc),
                            )
                        return
                    if not isinstance(fetch_result, JobFetchResult):
                        jobs: list[JobRecord] = []
                        async with write_lock:
                            run = store.fail_job_sync_run(
                                pending_run.id,
                                error_kind="invalid_provider_result",
                                error=(
                                    "Provider returned an untyped job collection; "
                                    "JobFetchResult is required."
                                ),
                            )
                    else:
                        jobs = list(fetch_result.jobs)
                        async with write_lock:
                            run = store.complete_job_sync_run(
                                pending_run.id,
                                jobs,
                                authoritative=fetch_result.authoritative,
                                close_missing=fetch_result.authoritative,
                            )
                            if jobs and run.success and output:
                                append_jsonl(output, jobs)
                    if run.success:
                        route_pin.record(route.id, "succeeded", authoritative=True)
                        metrics.job_sync_runs += 1
                        metrics.jobs += len(jobs)
                    if not run.success:
                        route_pin.record(route.id, "failed", authoritative=False)
                        metrics.error(
                            route.provider_id,
                            run.error_kind or "non_authoritative_snapshot",
                        )
                    metrics.jobs_persisted += run.job_count
                    if run.success:
                        metrics.jobs_deduped += max(0, len(jobs) - run.job_count)
                    async with progress_lock:
                        completed_routes += 1
                        _report_job_progress(
                            report,
                            completed_routes,
                            route_total,
                            metrics.jobs,
                            _job_detail(
                                board.key,
                                _job_sync_result_detail(
                                    route.provider_id,
                                    len(jobs),
                                    success=run.success,
                                    error_kind=run.error_kind,
                                ),
                            ),
                        )
                    if run.success:
                        logger.trace(
                            "Jobs route synced board={} provider={} jobs={}",
                            board.key,
                            route.provider_id,
                            len(jobs),
                        )
                    else:
                        logger.warning(
                            "Jobs route rejected board={} provider={} error_kind={}",
                            board.key,
                            route.provider_id,
                            run.error_kind,
                        )

            except asyncio.CancelledError:
                route_pin.interrupt(route.id)
                raise

        interrupted = False
        try:
            await asyncio.gather(
                *(
                    run_route(entry.route, entry.board, entry.request_key)
                    for entry in route_entries
                )
            )
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            metrics.route_conservation = route_pin.close(interrupted=interrupted)
            metrics.route_accounting = getattr(route_pin, "accounting", None)
    return metrics.finish()


def _select_job_route_entries(
    entries: Sequence,
    *,
    latest_syncs: dict[tuple[str, str], datetime],
    freshness_seconds: float,
    limit: int | None,
):
    cutoff = (
        utc_now() - timedelta(seconds=freshness_seconds)
        if freshness_seconds > 0
        else None
    )
    stale_entries = []
    fresh_entries = []
    for index, entry in enumerate(entries):
        synced_at = latest_syncs.get(_job_route_sync_key(entry))
        if synced_at and synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        if cutoff and synced_at and synced_at >= cutoff:
            fresh_entries.append(entry)
            continue
        stale_entries.append((index, entry, synced_at))

    if latest_syncs:
        stale_entries.sort(key=_job_route_priority)

    selected = stale_entries
    if limit is not None:
        selected = stale_entries[:limit]
    deferred_entries = [entry for _, entry, _ in stale_entries[len(selected) :]]
    return [entry for _, entry, _ in selected], fresh_entries, deferred_entries


def _job_route_sync_key(entry) -> tuple[str, str]:
    return (entry.route.board_key, entry.route.provider_id)


def _job_route_priority(item):
    index, entry, synced_at = item
    never_synced = synced_at is None
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return (
        0 if never_synced else 1,
        synced_at or earliest,
        entry.route.provider_id,
        entry.board.key,
        index,
    )


def _duplicate_routes_by_request_key(
    store: OpenOppsStore, routes: Sequence[BoardProviderRecord]
) -> dict[str, list[BoardProviderRecord]]:
    grouped: dict[str, list[BoardProviderRecord]] = {}
    for route in routes:
        board = store.get_board(route.board_key)
        if board is None:
            continue
        grouped.setdefault(route_request_key(board, route), []).append(route)
    return grouped


def _remove_unavailable_routes(
    store: OpenOppsStore,
    routes: Sequence[BoardProviderRecord],
    *,
    status: str,
    close_missing: bool,
    selected_route: BoardProviderRecord,
    selected_run_id: str,
) -> int:
    selected_route_key = (selected_route.board_key, selected_route.provider_id)
    completed_route_keys: set[tuple[str, str]] = set()
    for route in routes:
        route_key = (route.board_key, route.provider_id)
        if route_key not in completed_route_keys:
            run_id = (
                selected_run_id
                if route_key == selected_route_key
                else store.begin_job_sync_run(
                    route.board_key,
                    route.provider_id,
                ).id
            )
            store.complete_job_sync_run(
                run_id,
                [],
                authoritative=True,
                close_missing=close_missing,
            )
            completed_route_keys.add(route_key)
        store.deactivate_board_provider_route(route, status=status)
    return len(completed_route_keys)


def _route_failure_disposition(
    provider_id: str, exc: Exception
) -> _RouteFailureDisposition | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    status_code = exc.response.status_code
    if status_code in _BUILTIN_ROUTE_ABSENT_STATUSES.get(
        provider_id, frozenset()
    ) and _is_provider_snapshot_request(provider_id, exc.request):
        return _RouteFailureDisposition(
            status_code=status_code,
            deactivate=True,
            close_missing=True,
            error_reason="route_absent",
        )
    if reason := _RETAINED_ROUTE_HTTP_REASONS.get(status_code):
        return _RouteFailureDisposition(
            status_code=status_code,
            deactivate=False,
            close_missing=False,
            error_reason=reason,
        )
    return None


def _is_provider_snapshot_request(provider_id: str, request: httpx.Request) -> bool:
    path = request.url.path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    host = (request.url.host or "").lower()
    if provider_id == "greenhouse":
        return host == "boards-api.greenhouse.io" and (
            len(segments) == 4
            and segments[:2] == ["v1", "boards"]
            and segments[-1] == "jobs"
        )
    if provider_id == "lever":
        return (
            host == "api.lever.co"
            and len(segments) == 3
            and segments[:2]
            == [
                "v0",
                "postings",
            ]
        )
    if provider_id == "ashbyhq":
        return (
            host == "api.ashbyhq.com"
            and len(segments) == 3
            and segments[:2] == ["posting-api", "job-board"]
        )
    if provider_id == "workable":
        return (
            host == "apply.workable.com"
            and len(segments) == 5
            and segments[:3] == ["api", "v3", "accounts"]
            and segments[-1] == "jobs"
            and "token" not in _request_json_body(request)
        )
    if provider_id == "teamtailor":
        return path == "/jobs.rss"
    if provider_id == "consider_jobs":
        body = _request_json_body(request)
        meta = body.get("meta")
        return path == "/api-boards/search-jobs" and (
            not isinstance(meta, dict) or not meta.get("sequence")
        )
    if provider_id == "bamboohr":
        return path == "/careers/list"
    if provider_id == "rippling":
        return (
            host == "ats.rippling.com"
            and len(segments) == 5
            and segments[:3] == ["api", "v2", "board"]
            and segments[-1] == "jobs"
            and request.url.params.get("page", "0") == "0"
        )
    if provider_id == "workday":
        body = _request_json_body(request)
        return (
            host.endswith(".myworkdayjobs.com")
            and len(segments) == 5
            and segments[:2] == ["wday", "cxs"]
            and segments[-1] == "jobs"
            and body.get("offset", 0) == 0
        )
    if provider_id == "wpjobmanager":
        is_listing = len(segments) == 4 and segments == [
            "wp-json",
            "wp",
            "v2",
            "job-listings",
        ]
        is_ajax = len(segments) == 2 and segments == ["jm-ajax", "get_listings"]
        return (is_listing or is_ajax) and request.url.params.get("page", "1") == "1"
    return False


def _request_json_body(request: httpx.Request) -> dict[str, object]:
    try:
        payload = json.loads(request.content)
    except (json.JSONDecodeError, UnicodeDecodeError, httpx.RequestNotRead):
        return {}
    return payload if isinstance(payload, dict) else {}


def _report(
    report: ProgressReporter | None,
    stage: str,
    message: str,
    *,
    completed: int | None = None,
    total: int | None = None,
) -> None:
    if report:
        report(
            ProgressUpdate(
                stage=stage,
                message=message,
                completed=completed,
                total=total,
            )
        )


def _report_source_progress(
    report: ProgressReporter | None,
    completed_sources: int,
    source_total: int,
    unique_boards: int,
    detail: str,
) -> None:
    _report(
        report,
        "sources",
        _source_progress_message(
            completed_sources, source_total, unique_boards, detail
        ),
        completed=completed_sources,
        total=max(source_total, 1),
    )


def _report_job_progress(
    report: ProgressReporter | None,
    completed_routes: int,
    route_total: int,
    synced_jobs: int,
    detail: str,
) -> None:
    _report(
        report,
        "jobs",
        _job_progress_message(completed_routes, route_total, synced_jobs, detail),
        completed=completed_routes,
        total=max(route_total, 1),
    )


def _job_sync_result_detail(
    provider_id: str,
    job_count: int,
    *,
    success: bool,
    error_kind: str | None,
) -> str:
    if success:
        return f"{_format_count(job_count)} jobs synced via {provider_id}"
    if error_kind == "invalid_provider_result":
        return "rejected: invalid provider result"
    if error_kind == "non_authoritative_snapshot":
        return "rejected: non-authoritative snapshot"
    return f"failed: {error_kind or 'unknown'}"


def _source_progress_message(
    completed_sources: int,
    source_total: int,
    unique_boards: int,
    detail: str,
) -> str:
    return _progress_message(
        _stage_label("SRC", "cyan"),
        _chunk(
            "done",
            f"{_format_count(completed_sources)}/{_format_count(source_total)} sources",
        ),
        _chunk("boards", _format_count(unique_boards), "green"),
        detail,
    )


def _board_progress_message(
    completed_boards: int, board_total: int, detail: str
) -> str:
    return _progress_message(
        _stage_label("BRD", "magenta"),
        _chunk(
            "done",
            f"{_format_count(completed_boards)}/{_format_count(board_total)} boards",
        ),
        detail,
    )


def _job_progress_message(
    completed_routes: int,
    route_total: int,
    synced_jobs: int,
    detail: str,
) -> str:
    return _progress_message(
        _stage_label("JOB", "green"),
        _chunk(
            "done",
            f"{_format_count(completed_routes)}/{_format_count(route_total)} routes",
        ),
        _chunk("jobs", _format_count(synced_jobs), "green"),
        detail,
    )


def _phase_detail(phase: str, event: str) -> str:
    return " ".join(
        [
            _chunk("phase", phase, "cyan"),
            _chunk("event", event, "white"),
        ]
    )


def _board_detail(phase: str, *segments: str) -> str:
    return " ".join([_chunk("phase", phase, "magenta"), *segments])


def _source_detail(source_key: str, detail: str) -> str:
    return " ".join(
        [
            _chunk("source", source_key, "yellow"),
            _chunk("event", detail, "white"),
        ]
    )


def _job_detail(board_key: str, detail: str) -> str:
    return " ".join(
        [
            _chunk("board", board_key, "yellow"),
            _chunk("event", detail, "white"),
        ]
    )


def _progress_message(prefix: str, *segments: str) -> str:
    return f"{prefix} [dim]|[/] " + " [dim]|[/] ".join(
        segment for segment in segments if segment
    )


def _stage_label(label: str, color: str) -> str:
    return f"[bold {color} on grey11] {label} [/]"


def _chunk(label: str, value: str, value_style: str = "bold") -> str:
    return f"[dim]{label}[/] [{value_style}]{value}[/]"


def _format_count(value: int) -> str:
    return f"{value:,}"


def _error_reason(exc: Exception, default: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "rate_limited"
        if exc.response.status_code in {404, 410}:
            return "unavailable"
        return default
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (ValidationError, ValueError)):
        return "validation"
    return default


def _format_exception(exc: Exception) -> str:
    return safe_exception_message(exc)


def _track_unique_boards(
    unique_board_keys: set[str], boards: Sequence[BoardRecord]
) -> None:
    for board in boards:
        unique_board_keys.add((board.domain or board.key).strip().casefold())


def _unique_board_count(
    store: OpenOppsStore | None,
    source_key: str | None,
    unique_board_keys: set[str],
) -> int:
    if store:
        return store.count_boards(source_key=source_key)
    return len(unique_board_keys)
