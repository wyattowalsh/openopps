from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from openopps.http import build_async_client, safe_exception_message
from openopps.ingest import all_board_sources
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.route_select import dedupe_routes, normalize_provider_filter, route_ready
from openopps.settings import OpenOppsSettings
from openopps.source_resolution import resolve_effective_sources
from openopps.storage import OpenOppsStore
from openopps.providers.boards import BOARD_JOB_PROVIDERS, build_job_provider
from openopps.providers.sources import build_source_adapter


HEALTH_ACTIVE = "active"
HEALTH_EMPTY = "empty"
HEALTH_ERROR = "error"
HEALTH_MISSING_ROUTE = "missing_route"
HEALTH_NOT_COVERED = "not_covered"


@dataclass(frozen=True)
class SourceHealth:
    source_key: str
    provider_id: str
    status: str
    boards: int = 0
    board_providers: int = 0
    error: str | None = None


@dataclass(frozen=True)
class RouteHealth:
    board_key: str
    source_key: str
    provider_id: str
    status: str
    jobs: int = 0
    error: str | None = None


@dataclass
class NotCoveredProvider:
    provider_id: str
    support_level: str
    discovered: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class HealthSummary:
    sources: list[SourceHealth] = field(default_factory=list)
    routes: list[RouteHealth] = field(default_factory=list)
    not_covered: dict[str, NotCoveredProvider] = field(default_factory=dict)
    not_covered_seen: set[tuple[str, str]] = field(default_factory=set)
    duplicate_routes_skipped: int = 0
    applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources": [source.__dict__ for source in self.sources],
            "routes": [route.__dict__ for route in self.routes],
            "notCovered": [
                item.__dict__
                for item in sorted(
                    self.not_covered.values(), key=lambda item: item.provider_id
                )
            ],
            "sourceStatus": _count_statuses(source.status for source in self.sources),
            "routeStatus": _count_statuses(route.status for route in self.routes),
            "duplicateRoutesSkipped": self.duplicate_routes_skipped,
            "sourceCount": len(self.sources),
            "routeCount": len(self.routes),
            "notCoveredCount": sum(
                item.discovered for item in self.not_covered.values()
            ),
            "applied": self.applied,
        }


async def check_provider_health(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    page_size: int = 5,
    limit: int | None = None,
    apply: bool = False,
) -> HealthSummary:
    summary = HealthSummary(applied=apply)
    provider_filter = normalize_provider_filter(provider_id)
    sources = _select_sources(store, source_key, provider_filter)
    boards = {
        board.key: board
        for board in store.list_boards(source_key=source_key, board_key=board_key)
    }
    all_routes = store.list_board_providers(
        source_key=source_key,
        board_key=board_key,
        provider_id=provider_filter,
    )

    for route in all_routes:
        if _is_not_covered(route):
            _record_not_covered(summary, route)

    source_updates: list[SourceRecord] = []
    route_updates: list[BoardProviderRecord] = []
    async with build_async_client(settings) as client:
        source_semaphore = asyncio.Semaphore(settings.source_concurrency)
        route_semaphore = asyncio.Semaphore(settings.board_concurrency)

        async def check_source(source: SourceRecord) -> None:
            async with source_semaphore:
                result, discovered = await _check_source(
                    client, settings, source, page_size=page_size
                )
                summary.sources.append(result)
                for provider in discovered:
                    if _is_not_covered(provider):
                        _record_not_covered(summary, provider)
                if apply:
                    source_updates.append(_with_source_health(source, result))

        job_routes = [
            route for route in all_routes if route.support_level == ProviderSupport.JOBS
        ]
        job_routes, duplicate_routes = dedupe_routes(job_routes, boards)
        summary.duplicate_routes_skipped = len(duplicate_routes)
        if limit:
            job_routes = job_routes[:limit]

        async def check_route(route: BoardProviderRecord) -> None:
            async with route_semaphore:
                result = await _check_route(client, settings, boards, route)
                summary.routes.append(result)
                if apply:
                    route_updates.append(
                        route.model_copy(
                            update={
                                "last_status": result.status,
                                "detected_at": utc_now(),
                            }
                        )
                    )

        await asyncio.gather(*(check_source(source) for source in sources))
        await asyncio.gather(*(check_route(route) for route in job_routes))

    if apply:
        for source in source_updates:
            store.upsert_source(source)
        if route_updates:
            store.upsert_board_providers(route_updates)
        not_covered_updates = [
            route.model_copy(
                update={"last_status": HEALTH_NOT_COVERED, "detected_at": utc_now()}
            )
            for route in all_routes
            if _is_not_covered(route)
        ]
        if not_covered_updates:
            store.upsert_board_providers(not_covered_updates)

    return summary


def _select_sources(
    store: OpenOppsStore,
    source_key: str | None,
    provider_filter: str | None,
) -> list[SourceRecord]:
    source_catalog = {source.key: source for source in all_board_sources()}
    sources = resolve_effective_sources(
        list(source_catalog.values()), store.list_sources()
    )
    if source_key:
        sources = [source for source in sources if source.key == source_key]
        if not sources and source_key in source_catalog:
            sources = [source_catalog[source_key]]
    if provider_filter:
        sources = [
            source for source in sources if source.provider_id == provider_filter
        ]
    return sources


async def _check_source(
    client, settings: OpenOppsSettings, source: SourceRecord, *, page_size: int
) -> tuple[SourceHealth, list[BoardProviderRecord]]:
    adapter = build_source_adapter(source.provider_id, settings)
    if not adapter:
        return SourceHealth(source.key, source.provider_id, HEALTH_NOT_COVERED), []
    try:
        async for boards, providers, _page_meta in adapter.iter_boards(
            client, source, page_size=page_size
        ):
            status = HEALTH_ACTIVE if boards or providers else HEALTH_EMPTY
            return SourceHealth(
                source.key, source.provider_id, status, len(boards), len(providers)
            ), providers
    except Exception as exc:
        error = safe_exception_message(exc)
        logger.warning(
            "Provider health source check failed source={} provider={} error={}",
            source.key,
            source.provider_id,
            error,
        )
        return SourceHealth(
            source.key, source.provider_id, HEALTH_ERROR, error=error
        ), []
    return SourceHealth(source.key, source.provider_id, HEALTH_EMPTY), []


async def _check_route(
    client,
    settings: OpenOppsSettings,
    boards: dict[str, BoardRecord],
    route: BoardProviderRecord,
) -> RouteHealth:
    board = boards.get(route.board_key)
    provider = build_job_provider(route.provider_id, settings)
    if not board or not provider:
        return RouteHealth(
            route.board_key, route.source_key, route.provider_id, HEALTH_NOT_COVERED
        )
    if not route_ready(route):
        return RouteHealth(
            route.board_key, route.source_key, route.provider_id, HEALTH_MISSING_ROUTE
        )
    try:
        job_count = await provider.check_jobs(client, board, route)
    except Exception as exc:
        error = safe_exception_message(exc)
        logger.warning(
            "Provider health job check failed board={} provider={} error={}",
            route.board_key,
            route.provider_id,
            error,
        )
        return RouteHealth(
            route.board_key,
            route.source_key,
            route.provider_id,
            HEALTH_ERROR,
            error=error,
        )
    status = HEALTH_ACTIVE if job_count else HEALTH_EMPTY
    return RouteHealth(
        route.board_key, route.source_key, route.provider_id, status, jobs=job_count
    )


def _with_source_health(source: SourceRecord, result: SourceHealth) -> SourceRecord:
    health = {
        "status": result.status,
        "boards": result.boards,
        "boardProviders": result.board_providers,
        "error": result.error,
        "checkedAt": utc_now().isoformat(),
    }
    return source.model_copy(
        update={"raw_metadata": source.raw_metadata | {"health": health}}
    )


def _is_not_covered(route: BoardProviderRecord) -> bool:
    return (
        route.support_level != ProviderSupport.JOBS
        or route.provider_id not in BOARD_JOB_PROVIDERS
    )


def _record_not_covered(summary: HealthSummary, route: BoardProviderRecord) -> None:
    seen_key = (route.provider_id, route.board_key)
    if seen_key in summary.not_covered_seen:
        return
    summary.not_covered_seen.add(seen_key)
    item = summary.not_covered.get(route.provider_id)
    if not item:
        item = NotCoveredProvider(route.provider_id, route.support_level.value)
        summary.not_covered[route.provider_id] = item
    item.discovered += 1
    if len(item.examples) < 5 and route.board_key not in item.examples:
        item.examples.append(route.board_key)


def _count_statuses(statuses) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return counts
