"""Offline URL-pull coverage class: catalog SQLite vs packaged overlay vs ephemeral.

Classification uses overlay JSON (`lru_cache`) and an optional catalog route
lookup. It performs no HTTP and must not import `openopps.discovery`.
`url_pull_reserved` is true after the D712 OpenOppsStore persist join.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from typing import Protocol

from openopps.pull_models import PullCoverageClass, PullTerminalState

CatalogRoutePredicate = Callable[[str, str], bool]


class CatalogRouteStore(Protocol):
    """Narrow read of jobs-capable catalog routes for offline coverage class."""

    def list_board_providers(
        self,
        *,
        source_key: str | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        job_capable_only: bool = False,
    ) -> Sequence[object]: ...


def url_pull_reserved_enabled() -> bool:
    """Reserved URL-pull ledger class; true after the store persist join."""

    return True


def classify_pull_coverage(
    *,
    provider_id: str | None,
    board_identity: str | None,
    terminal_state: PullTerminalState,
    catalog_has_route: CatalogRoutePredicate | None = None,
) -> PullCoverageClass:
    """Return one closed coverage class without fetching or mutating catalogs."""

    if terminal_state != PullTerminalState.SUCCEEDED:
        return PullCoverageClass.NOT_APPLICABLE
    if not provider_id or not board_identity:
        return PullCoverageClass.EPHEMERAL_NEW
    if catalog_has_route is not None and catalog_has_route(provider_id, board_identity):
        return PullCoverageClass.CATALOG_ROUTE
    if overlay_route_is_packaged(provider_id, board_identity):
        return PullCoverageClass.OVERLAY_PACKAGED
    if url_pull_reserved_enabled():
        return PullCoverageClass.URL_PULL_RESERVED
    return PullCoverageClass.EPHEMERAL_NEW


def overlay_route_is_packaged(provider_id: str, board_identity: str) -> bool:
    """Return whether packaged overlay JSON already owns this provider token."""

    identity = (provider_id.casefold(), board_identity.casefold())
    return identity in _packaged_overlay_route_identities()


def catalog_store_has_route(
    store: CatalogRouteStore,
    provider_id: str,
    board_identity: str,
) -> bool:
    """Return whether SQLite already has a jobs-capable route for this identity."""

    provider = provider_id.casefold()
    identity = board_identity.casefold()
    if not provider or not identity:
        return False
    try:
        list_routes = getattr(
            store,
            "list_existing_board_providers",
            store.list_board_providers,
        )
        routes = list_routes(
            provider_id=provider_id,
            job_capable_only=True,
        )
    except Exception:
        return False
    for route in routes:
        source_key = str(getattr(route, "source_key", "") or "").casefold()
        if source_key == "url-pull":
            continue
        route_provider = str(getattr(route, "provider_id", "") or "").casefold()
        if route_provider != provider:
            continue
        token = str(getattr(route, "token", "") or "").strip().casefold()
        board_key = str(getattr(route, "board_key", "") or "").strip().casefold()
        if identity in {token, board_key}:
            return True
    return False


def catalog_lookup_from_store(
    store: CatalogRouteStore | None,
) -> CatalogRoutePredicate | None:
    """Bind an optional store into the classify predicate used by PullService.

    Prefers ``list_existing_board_providers`` so coverage class never Alembic
    bootstraps a missing or cache-only sqlite file.
    """

    if store is None:
        return None

    def has_route(provider_id: str, board_identity: str) -> bool:
        return catalog_store_has_route(store, provider_id, board_identity)

    return has_route


@lru_cache(maxsize=1)
def _packaged_overlay_route_identities() -> frozenset[tuple[str, str]]:
    from openopps.providers.sources.overlay import load_packaged_overlay_entries

    identities: set[tuple[str, str]] = set()
    for entry in load_packaged_overlay_entries():
        identities.update(_identities_for_overlay_entry(entry))
    return frozenset(identities)


def _identities_for_overlay_entry(
    entry: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    from openopps.providers.sources.overlay import (
        JOB_SEEKER_OVERLAY_SOURCE_KEY,
        jobs_capable_routes_from_locator,
    )

    locator = str(entry.get("locator") or "").strip()
    overlay_id = str(entry.get("id") or "").strip()
    if not locator:
        return ()
    try:
        routes = jobs_capable_routes_from_locator(
            locator,
            source_key=JOB_SEEKER_OVERLAY_SOURCE_KEY,
            board_key=overlay_id or "overlay",
        )
    except Exception:
        return ()
    identities: list[tuple[str, str]] = []
    for route in routes:
        provider_id = str(route.provider_id or "").strip().casefold()
        token = str(route.token or "").strip().casefold()
        if provider_id and token:
            identities.append((provider_id, token))
    return tuple(identities)


__all__ = [
    "CatalogRoutePredicate",
    "CatalogRouteStore",
    "catalog_lookup_from_store",
    "catalog_store_has_route",
    "classify_pull_coverage",
    "overlay_route_is_packaged",
    "url_pull_reserved_enabled",
]
