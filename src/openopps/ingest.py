from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from loguru import logger

from openopps.http import build_async_client
from openopps.metrics import SyncMetrics
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.boards import build_job_provider
from openopps.providers.sources import BOARD_SOURCE_CATALOG, build_source_adapter
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
) -> SyncMetrics:
    metrics = SyncMetrics(name="sources.sync")
    sources = _select_sources(store, source_key)
    if store:
        for source in sources:
            store.upsert_source(source)
    write_lock = asyncio.Lock()
    async with build_async_client(settings) as client:
        semaphore = asyncio.Semaphore(settings.source_concurrency)

        async def run_source(source: SourceRecord) -> None:
            async with semaphore:
                adapter = build_source_adapter(source.provider_id, settings)
                if not adapter:
                    logger.warning("No source adapter for {}", source.provider_id)
                    metrics.skipped += 1
                    return
                logger.info(
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
                        logger.info(
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
                                if output:
                                    append_jsonl(output, boards)
                except Exception:
                    metrics.error(source.provider_id)
                    metrics.skipped += 1
                    logger.exception(
                        "Failed to sync source={} provider={}",
                        source.key,
                        source.provider_id,
                    )

        await asyncio.gather(*(run_source(source) for source in sources))
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
    logger.info(
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
            async with semaphore:
                provider = build_job_provider(route.provider_id, settings)
                if not provider:
                    metrics.skipped += 1
                    logger.warning(
                        "Skipping job route board={} provider={} missing_provider",
                        route.board_key,
                        route.provider_id,
                    )
                    return
                if route.support_level != ProviderSupport.JOBS:
                    metrics.skipped += 1
                    logger.warning(
                        "Skipping non-job-capable route board={} provider={}",
                        route.board_key,
                        route.provider_id,
                    )
                    return
                try:
                    jobs = await provider.fetch_jobs(client, board, route)
                except Exception:
                    metrics.error(route.provider_id)
                    logger.exception(
                        "Failed to sync jobs for board={} provider={}",
                        board.key,
                        route.provider_id,
                    )
                    return
                if jobs:
                    async with write_lock:
                        store.upsert_jobs(jobs)
                        if output:
                            append_jsonl(output, jobs)
                    metrics.jobs += len(jobs)
                logger.info(
                    "Jobs route synced board={} provider={} jobs={}",
                    board.key,
                    route.provider_id,
                    len(jobs),
                )

        await asyncio.gather(
            *(run_route(entry.route, entry.board) for entry in route_selection.entries)
        )
    return metrics.finish()


def add_detected_provider(
    *,
    store: OpenOppsStore,
    board: BoardRecord,
    provider: BoardProviderRecord,
) -> BoardProviderRecord:
    record = provider.model_copy(
        update={"board_key": board.key, "source_key": board.source_key}
    )
    store.upsert_board_providers([record])
    return record


def eligible_job_routes(
    routes: Iterable[BoardProviderRecord],
) -> list[BoardProviderRecord]:
    return [route for route in routes if route.support_level == ProviderSupport.JOBS]
