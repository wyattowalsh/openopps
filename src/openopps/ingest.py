from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

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
from openopps.route_select import normalize_provider_filter
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore, append_jsonl


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
    sources = _select_sources(store, source_key)
    source_total = len(sources)
    completed_sources = 0
    unique_board_keys: set[str] = set()
    progress_lock = asyncio.Lock()
    _report(
        report,
        "sources",
        f"sources: 0/{source_total} complete, 0 unique boards",
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
                            f"{source.key}: skipped, no adapter",
                        )
                    return
                _report(
                    report,
                    "sources",
                    f"{source.key}: discovering boards",
                    completed=completed_sources,
                    total=source_total,
                )
                logger.trace(
                    "Starting source sync source={} provider={}",
                    source.key,
                    source.provider_id,
                )
                try:
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
                                    store.upsert_board_providers(providers)
                                    unique_count = len(
                                        store.list_boards(source_key=source_key)
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
                                    f"{source.key}: {unique_count} unique boards discovered",
                                )
                    async with progress_lock:
                        completed_sources += 1
                        _report_source_progress(
                            report,
                            completed_sources,
                            source_total,
                            _unique_board_count(store, source_key, unique_board_keys),
                            f"{source.key}: complete",
                        )
                except Exception as exc:
                    metrics.error(source.provider_id)
                    metrics.skipped += 1
                    async with progress_lock:
                        completed_sources += 1
                        _report_source_progress(
                            report,
                            completed_sources,
                            source_total,
                            _unique_board_count(store, source_key, unique_board_keys),
                            f"{source.key}: skipped after error",
                        )
                    if verbose:
                        logger.warning(
                            "Failed to sync source={} provider={}: {}",
                            source.key,
                            source.provider_id,
                            exc,
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
        f"boards: enriching 0/{board_total} unique boards",
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
        (
            f"boards: enriched {enrichment.checked_boards} unique boards "
            f"({len(enrichment.board_changes)} board updates, "
            f"{len(enrichment.route_changes)} route updates)"
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
    metrics.skipped = (
        summary.route_ready_skipped
        + summary.duplicate_routes_skipped
        + len(summary.unknown)
    )
    metrics.provider_errors.update(summary.errors)
    _report(
        report,
        "boards",
        (
            f"boards: {summary.checked} routes checked, "
            f"{len(summary.matched)} ready, {len(summary.unknown)} unresolved"
        ),
        completed=max(board_total, 1),
        total=max(board_total, 1),
    )
    return metrics.finish()


def _select_sources(
    store: OpenOppsStore | None, source_key: str | None
) -> list[SourceRecord]:
    source_catalog = {source.key: source for source in all_board_sources()}
    if store:
        source_catalog.update({source.key: source for source in store.list_sources()})
    sources = list(source_catalog.values())
    if source_key:
        selected = [source for source in sources if source.key == source_key]
        if selected:
            return selected
        if source_key in BOARD_SOURCE_CATALOG:
            return [BOARD_SOURCE_CATALOG[source_key]]
        raise ValueError(f"Unknown source: {source_key}")
    return [source for source in sources if source.enabled]


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
    metrics.duplicate_routes_skipped += len(route_selection.duplicate_routes)
    metrics.skipped += len(route_selection.missing_route_metadata)
    route_total = len(route_selection.entries)
    completed_routes = 0
    progress_lock = asyncio.Lock()
    _report(
        report,
        "jobs",
        f"jobs: 0/{route_total} ready routes checked, 0 jobs synced",
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

        async def run_route(route: BoardProviderRecord, board: BoardRecord) -> None:
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
                            f"{route.board_key}: skipped, missing provider",
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
                            f"{route.board_key}: skipped, non-job route",
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
                    f"{board.key}: fetching {route.provider_id} jobs",
                    completed=completed_routes,
                    total=max(route_total, 1),
                )
                try:
                    jobs = await provider.fetch_jobs(client, board, route)
                except Exception as exc:
                    metrics.error(route.provider_id)
                    async with progress_lock:
                        completed_routes += 1
                        _report_job_progress(
                            report,
                            completed_routes,
                            route_total,
                            metrics.jobs,
                            f"{board.key}: skipped after error",
                        )
                    if verbose:
                        logger.warning(
                            "Failed to sync jobs for board={} provider={}: {}",
                            board.key,
                            route.provider_id,
                            exc,
                        )
                    return
                if jobs:
                    async with write_lock:
                        store.upsert_jobs(jobs)
                        if output:
                            append_jsonl(output, jobs)
                    metrics.jobs += len(jobs)
                async with progress_lock:
                    completed_routes += 1
                    _report_job_progress(
                        report,
                        completed_routes,
                        route_total,
                        metrics.jobs,
                        f"{board.key}: {len(jobs)} jobs synced",
                    )
                logger.trace(
                    "Jobs route synced board={} provider={} jobs={}",
                    board.key,
                    route.provider_id,
                    len(jobs),
                )

        await asyncio.gather(
            *(run_route(entry.route, entry.board) for entry in route_selection.entries)
        )
    return metrics.finish()


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
        (
            f"sources: {completed_sources}/{source_total} complete, "
            f"{unique_boards} unique boards - {detail}"
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
        (
            f"jobs: {completed_routes}/{route_total} routes checked, "
            f"{synced_jobs} jobs synced - {detail}"
        ),
        completed=completed_routes,
        total=max(route_total, 1),
    )


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
        return len(store.list_boards(source_key=source_key))
    return len(unique_board_keys)
