from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger
from pydantic import ValidationError

from openopps.enrichment import enrich_metadata
from openopps.http import build_async_client
from openopps.metrics import ProgressReporter, ProgressUpdate, SyncMetrics
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.boards import build_job_provider
from openopps.providers.sources import BOARD_SOURCE_CATALOG, build_source_adapter
from openopps.route_probe import probe_routes
from openopps.route_registry import BoardRouteRegistry
from openopps.route_select import normalize_provider_filter, route_request_key
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore, append_jsonl

_ROUTE_UNAVAILABLE_STATUSES = {400, 401, 403, 404, 410}
_ROUTE_CLOSE_MISSING_STATUSES = {400, 404, 410}


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
) -> SyncMetrics:
    metrics = SyncMetrics(name="sources.sync")
    selected_sources = _select_sources(store, source_key)
    fresh_sources, sources = _partition_fresh_sources(
        selected_sources,
        freshness_seconds=settings.source_freshness_seconds,
        source_key=source_key,
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
            async with semaphore:
                adapter = build_source_adapter(source.provider_id, settings)
                if not adapter:
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
                            updated_source = source.model_copy(
                                update={
                                    "version": page_meta.get("version") or {},
                                    "raw_metadata": source.raw_metadata
                                    | {"lastPage": compact_meta},
                                    "synced_at": utc_now(),
                                }
                            )
                            if store or output:
                                async with write_lock:
                                    if store:
                                        store.upsert_source(updated_source)
                                        store.upsert_boards(boards)
                                        store.upsert_board_providers(
                                            providers, boards=boards
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

        await asyncio.gather(*(run_source(source) for source in sources))
    return metrics.finish()


async def sync_boards(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    max_candidates: int = 12,
    limit: int | None = None,
    verbose: bool = False,
    report: ProgressReporter | None = None,
) -> SyncMetrics:
    metrics = SyncMetrics(name="boards.sync")
    board_total = len(
        store.list_boards(source_key=source_key, board_key=board_key, limit=limit)
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
    enrichment = enrich_metadata(
        store,
        source_key=source_key,
        board_key=board_key,
        limit=limit,
        apply=True,
    )
    metrics.boards = enrichment.checked_boards
    _report(
        report,
        "boards",
        _board_progress_message(
            enrichment.checked_boards,
            max(board_total, 1),
            _board_detail(
                "enrich",
                _chunk(
                    "board-upd", _format_count(len(enrichment.board_changes)), "green"
                ),
                _chunk(
                    "route-upd", _format_count(len(enrichment.route_changes)), "green"
                ),
            ),
        ),
        completed=enrichment.checked_boards,
        total=max(board_total, 1),
    )
    summary = await probe_routes(
        settings=settings,
        store=store,
        source_key=source_key,
        board_key=board_key,
        provider_id=provider_id,
        only_missing=True,
        apply=True,
        max_candidates=max_candidates,
        limit=limit,
    )
    metrics.board_providers = summary.checked
    metrics.duplicate_routes_skipped = summary.duplicate_routes_skipped
    for unknown in summary.unknown:
        if unknown.reason in {"probe_error", "rate_limited"}:
            metrics.error(unknown.provider_id, unknown.reason)
    _report(
        report,
        "boards",
        _board_progress_message(
            max(board_total, 1),
            max(board_total, 1),
            _board_detail(
                "routes",
                _chunk("checked", _format_count(summary.checked), "cyan"),
                _chunk("ready", _format_count(len(summary.matched)), "green"),
                _chunk("unresolved", _format_count(len(summary.unknown)), "yellow"),
                _chunk(
                    "not-probed",
                    _format_count(
                        summary.route_ready_skipped + summary.duplicate_routes_skipped
                    ),
                    "yellow",
                ),
            ),
        ),
        completed=max(board_total, 1),
        total=max(board_total, 1),
    )
    return metrics.finish()


def _select_sources(
    store: OpenOppsStore | None, source_key: str | None
) -> list[SourceRecord]:
    source_catalog = {source.key: source for source in all_board_sources()}
    stored_sources = (
        {source.key: source for source in store.list_sources()} if store else {}
    )
    sources = [
        _unscoped_source(catalog_source, stored_sources.get(key))
        for key, catalog_source in source_catalog.items()
    ]
    sources.extend(
        source for key, source in stored_sources.items() if key not in source_catalog
    )
    if source_key:
        if source_key in stored_sources:
            return [stored_sources[source_key]]
        if source_key in BOARD_SOURCE_CATALOG:
            return [BOARD_SOURCE_CATALOG[source_key]]
        raise ValueError(f"Unknown source: {source_key}")
    return [source for source in sources if source.enabled]


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


def _unscoped_source(
    catalog_source: SourceRecord, stored_source: SourceRecord | None
) -> SourceRecord:
    if stored_source is None:
        return catalog_source
    if (
        stored_source.url != catalog_source.url
        or stored_source.provider_id != catalog_source.provider_id
    ):
        return stored_source
    if not catalog_source.enabled:
        return catalog_source
    return catalog_source.model_copy(
        update={
            "enabled": stored_source.enabled,
            "version": stored_source.version,
            "raw_metadata": catalog_source.raw_metadata | stored_source.raw_metadata,
            "synced_at": stored_source.synced_at,
        }
    )


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
    board_key: str | None = None,
    provider_id: str | None = None,
    output: Path | None = None,
    verbose: bool = False,
    report: ProgressReporter | None = None,
) -> SyncMetrics:
    metrics = SyncMetrics(name="jobs.sync")
    provider_filter = normalize_provider_filter(provider_id)
    route_selection = BoardRouteRegistry(store).select(
        source_key=source_key,
        board_key=board_key,
        provider_id=provider_filter,
        ready_only=True,
    )
    duplicate_routes_by_request_key = _duplicate_routes_by_request_key(
        store, route_selection.duplicate_routes
    )
    metrics.duplicate_routes_skipped += len(route_selection.duplicate_routes)
    route_total = len(route_selection.entries)
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
                    f"{_format_count(len(route_selection.missing_route_metadata))} no-meta"
                ),
            ),
        ),
        completed=0,
        total=max(route_total, 1),
    )
    logger.trace(
        "Starting jobs sync executable_routes={} missing_route_metadata_skipped={} duplicates_skipped={} source={} board={} provider={}",
        len(route_selection.entries),
        len(route_selection.missing_route_metadata),
        len(route_selection.duplicate_routes),
        source_key or "all",
        board_key or "all",
        provider_filter or "all",
    )
    semaphore = asyncio.Semaphore(settings.board_concurrency)
    write_lock = asyncio.Lock()
    async with build_async_client(settings) as client:

        async def run_route(
            route: BoardProviderRecord, board: BoardRecord, request_key: str
        ) -> None:
            nonlocal completed_routes
            async with semaphore:
                provider = build_job_provider(route.provider_id, settings)
                if not provider:
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
                try:
                    jobs = await provider.fetch_jobs(client, board, route)
                except Exception as exc:
                    unavailable_status = _route_unavailable_status(exc)
                    if unavailable_status is not None:
                        status = f"job_sync_unavailable_{unavailable_status}"
                        unavailable_routes = [
                            route,
                            *duplicate_routes_by_request_key.get(request_key, []),
                        ]
                        async with write_lock:
                            _remove_unavailable_routes(
                                store,
                                unavailable_routes,
                                status=status,
                                close_missing=(
                                    unavailable_status in _ROUTE_CLOSE_MISSING_STATUSES
                                ),
                            )
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
                                unavailable_status,
                            )
                        return
                    error_reason = _error_reason(exc, "job_fetch")
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
                if jobs:
                    async with write_lock:
                        run = store.sync_jobs_for_route(
                            board.key,
                            route.provider_id,
                            jobs,
                            close_missing=True,
                        )
                        if output:
                            append_jsonl(output, jobs)
                    metrics.jobs += len(jobs)
                else:
                    async with write_lock:
                        run = store.sync_jobs_for_route(
                            board.key,
                            route.provider_id,
                            jobs,
                            close_missing=True,
                        )
                metrics.job_sync_runs += 1
                metrics.jobs_persisted += run.job_count
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
                            (
                                f"{_format_count(len(jobs))} jobs synced "
                                f"via {route.provider_id}"
                            ),
                        ),
                    )
                logger.trace(
                    "Jobs route synced board={} provider={} jobs={}",
                    board.key,
                    route.provider_id,
                    len(jobs),
                )

        await asyncio.gather(
            *(
                run_route(entry.route, entry.board, entry.request_key)
                for entry in route_selection.entries
            )
        )
    return metrics.finish()


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
) -> None:
    closed_route_keys: set[tuple[str, str]] = set()
    for route in routes:
        if close_missing:
            route_key = (route.board_key, route.provider_id)
            if route_key not in closed_route_keys:
                store.sync_jobs_for_route(
                    route.board_key,
                    route.provider_id,
                    [],
                    close_missing=True,
                )
                closed_route_keys.add(route_key)
        store.deactivate_board_provider_route(route, status=status)


def _route_unavailable_status(exc: Exception) -> int | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    status_code = exc.response.status_code
    if status_code in _ROUTE_UNAVAILABLE_STATUSES:
        return status_code
    return None


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
        if exc.response.status_code in _ROUTE_UNAVAILABLE_STATUSES:
            return "unavailable"
        return default
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (ValidationError, ValueError)):
        return "validation"
    return default


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


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
