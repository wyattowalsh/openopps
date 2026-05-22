from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from openopps.models import BoardProviderRecord, BoardRecord
from openopps.route_select import (
    dedupe_routes,
    normalize_provider_filter,
    route_ready,
    route_request_key,
)
from openopps.storage import OpenOppsStore


PROBE_READY_STATUS = "route_ready"


@dataclass(frozen=True)
class BoardRouteEntry:
    """Executable board/provider route selected from the durable route registry."""

    board: BoardRecord
    route: BoardProviderRecord
    request_key: str
    verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "board": self.board.model_dump(mode="json"),
            "route": self.route.model_dump(mode="json"),
            "requestKey": self.request_key,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class BoardRouteSelection:
    """Selected routes plus skipped route accounting."""

    entries: list[BoardRouteEntry] = field(default_factory=list)
    duplicate_routes: list[BoardProviderRecord] = field(default_factory=list)
    missing_route_metadata: list[BoardProviderRecord] = field(default_factory=list)
    unverified_routes: list[BoardProviderRecord] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "routes": [entry.as_dict() for entry in self.entries],
            "routeCount": len(self.entries),
            "duplicateRoutesSkipped": len(self.duplicate_routes),
            "missingRouteMetadataSkipped": len(self.missing_route_metadata),
            "unverifiedRoutesSkipped": len(self.unverified_routes),
        }


class BoardRouteRegistry:
    """Programmatic selector for board routes that are safe to execute."""

    def __init__(self, store: OpenOppsStore):
        self.store = store

    def select(
        self,
        *,
        source_key: str | None = None,
        source_keys: Sequence[str] | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        ready_only: bool = True,
        verified_only: bool = False,
        dedupe: bool = True,
        limit: int | None = None,
    ) -> BoardRouteSelection:
        provider_filter = normalize_provider_filter(provider_id)
        selected_source_keys = _selected_source_keys(source_key, source_keys)
        boards = _list_boards_for_sources(
            self.store, selected_source_keys, board_key=board_key
        )
        routes = _list_routes_for_sources(
            self.store,
            selected_source_keys,
            board_key=board_key,
            provider_id=provider_filter,
        )
        return select_routes_from_records(
            boards=boards,
            routes=routes,
            ready_only=ready_only,
            verified_only=verified_only,
            dedupe=dedupe,
            limit=limit,
        )


def _selected_source_keys(
    source_key: str | None, source_keys: Sequence[str] | None
) -> tuple[str, ...]:
    if source_key:
        return (source_key,)
    return tuple(dict.fromkeys(source_keys or ()))


def _list_boards_for_sources(
    store: OpenOppsStore, source_keys: Iterable[str], *, board_key: str | None
) -> list[BoardRecord]:
    source_keys = tuple(source_keys)
    if not source_keys:
        return store.list_boards(board_key=board_key, with_providers=False)
    boards: list[BoardRecord] = []
    for selected_source_key in source_keys:
        boards.extend(
            store.list_boards(
                source_key=selected_source_key,
                board_key=board_key,
                with_providers=False,
            )
        )
    return boards


def _list_routes_for_sources(
    store: OpenOppsStore,
    source_keys: Iterable[str],
    *,
    board_key: str | None,
    provider_id: str | None,
) -> list[BoardProviderRecord]:
    source_keys = tuple(source_keys)
    if not source_keys:
        return store.list_board_providers(
            board_key=board_key,
            provider_id=provider_id,
            job_capable_only=True,
        )
    routes: list[BoardProviderRecord] = []
    for selected_source_key in source_keys:
        routes.extend(
            store.list_board_providers(
                source_key=selected_source_key,
                board_key=board_key,
                provider_id=provider_id,
                job_capable_only=True,
            )
        )
    return routes


def select_routes_from_records(
    *,
    boards: Sequence[BoardRecord],
    routes: Sequence[BoardProviderRecord],
    ready_only: bool = True,
    verified_only: bool = False,
    dedupe: bool = True,
    limit: int | None = None,
) -> BoardRouteSelection:
    boards_by_key = {board.key: board for board in boards}
    selected_routes = list(routes)

    missing_route_metadata: list[BoardProviderRecord] = []
    unverified_routes: list[BoardProviderRecord] = []
    if ready_only:
        ready_routes: list[BoardProviderRecord] = []
        for route in selected_routes:
            if route_ready(route):
                ready_routes.append(route)
            else:
                missing_route_metadata.append(route)
        selected_routes = ready_routes
    if verified_only:
        unverified_routes = [
            route
            for route in selected_routes
            if route.last_status != PROBE_READY_STATUS
        ]
        selected_routes = [
            route
            for route in selected_routes
            if route.last_status == PROBE_READY_STATUS
        ]
    duplicate_routes: list[BoardProviderRecord] = []
    if dedupe:
        selected_routes, duplicate_routes = dedupe_routes(
            selected_routes, boards_by_key
        )
    if limit:
        selected_routes = selected_routes[:limit]
    entries = [
        BoardRouteEntry(
            board=board,
            route=route,
            request_key=route_request_key(board, route),
            verified=route.last_status == PROBE_READY_STATUS,
        )
        for route in selected_routes
        if (board := boards_by_key.get(route.board_key)) is not None
    ]
    return BoardRouteSelection(
        entries=entries,
        duplicate_routes=duplicate_routes,
        missing_route_metadata=missing_route_metadata,
        unverified_routes=unverified_routes,
    )
