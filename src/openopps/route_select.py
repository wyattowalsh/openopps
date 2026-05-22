from __future__ import annotations

from urllib.parse import urlparse

from openopps.models import BoardProviderRecord, BoardRecord
from openopps.utils import slugify


PROVIDER_FILTER_ALL = {"any", "all", "*"}


def normalize_provider_filter(provider_id: str | None) -> str | None:
    if provider_id and provider_id.strip().lower() in PROVIDER_FILTER_ALL:
        return None
    return provider_id


def route_ready(route: BoardProviderRecord) -> bool:
    """Return whether a persisted provider route has enough metadata to execute."""

    if route.provider_id == "workday":
        return bool(route.board_url or (route.host and route.tenant and route.site))
    if route.provider_id in {"greenhouse", "lever", "ashbyhq"}:
        return bool(route.token or route.board_url)
    return bool(
        route.token or route.board_url or (route.host and route.tenant and route.site)
    )


def dedupe_routes(
    routes: list[BoardProviderRecord],
    boards_by_key: dict[str, BoardRecord],
) -> tuple[list[BoardProviderRecord], list[BoardProviderRecord]]:
    seen: set[str] = set()
    unique: list[BoardProviderRecord] = []
    duplicates: list[BoardProviderRecord] = []
    for route in routes:
        board = boards_by_key.get(route.board_key)
        if not board:
            unique.append(route)
            continue
        key = route_request_key(board, route)
        if key in seen:
            duplicates.append(route)
            continue
        seen.add(key)
        unique.append(route)
    return unique, duplicates


def route_request_key(board: BoardRecord, route: BoardProviderRecord) -> str:
    provider = route.provider_id.lower()
    token = _route_token(route)
    if provider in {"greenhouse", "lever", "ashbyhq"} and token:
        return f"{provider}:token:{token}"
    if provider == "workday":
        if route.host and route.tenant and route.site:
            return f"workday:cxs:{route.host.lower()}:{route.tenant.lower()}:{route.site.lower()}"
        if route.board_url:
            return f"workday:url:{_normalize_url(route.board_url)}"
    if route.board_url:
        return f"{provider}:url:{_normalize_url(route.board_url)}"
    domain = _domain(board)
    if domain:
        return f"{provider}:domain:{domain}"
    fallback = slugify(
        str(board.remote_slug or board.remote_id or board.name or board.key)
    )
    return f"{provider}:board:{fallback}"


def _route_token(route: BoardProviderRecord) -> str | None:
    if route.token:
        return route.token.strip().lower()
    if route.board_url:
        parsed = urlparse(route.board_url)
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[0].strip().lower()
    return None


def _domain(board: BoardRecord) -> str | None:
    value = board.domain
    if not value and board.website_url:
        value = urlparse(board.website_url).netloc
    if not value:
        return None
    value = value.strip().lower().removeprefix("www.")
    return value or None


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}".lower()
