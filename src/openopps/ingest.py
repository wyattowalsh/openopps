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
                    metrics.error(source.provider_id)
                    metrics.skipped += 1
                    async with progress_lock:
                        completed_sources += 1
                        _report_source_progress(
                            report,
                            completed_sources,
                            source_total,
                            _unique_board_count(store, source_key, unique_board_keys),
                            _source_detail(source.key, "skipped: error"),
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
    metrics.skipped = (
        summary.route_ready_skipped
        + summary.duplicate_routes_skipped
        + len(summary.unknown)
    )
    metrics.provider_errors.update(summary.errors)
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
                    "skipped",
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
                    metrics.error(route.provider_id)
                    async with progress_lock:
                        completed_routes += 1
                        _report_job_progress(
                            report,
                            completed_routes,
                            route_total,
                            metrics.jobs,
                            _job_detail(board.key, "skipped: error"),
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
                        store.sync_jobs_for_route(
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
                        store.sync_jobs_for_route(
                            board.key,
                            route.provider_id,
                            jobs,
                            close_missing=True,
                        )
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
