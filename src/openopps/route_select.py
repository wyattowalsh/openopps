from __future__ import annotations

from urllib.parse import urlparse

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    validate_provider_host,
    validate_public_host,
)
from openopps.providers.boards.tokens import (
    ashby_token_from_url,
    greenhouse_token_from_url,
    lever_token_from_url,
    workable_token_from_url,
)
from openopps.providers.boards.consider import consider_jobs_token
from openopps.utils import slugify


PROVIDER_FILTER_ALL = {"any", "all", "*"}


def normalize_provider_filter(provider_id: str | None) -> str | None:
    if provider_id and provider_id.strip().lower() in PROVIDER_FILTER_ALL:
        return None
    return provider_id


def route_ready(route: BoardProviderRecord) -> bool:
    """Return whether a persisted provider route has enough metadata to execute."""

    if route.provider_id == "workday":
        return bool(
            route.board_url
            or (_provider_host(route, "myworkdayjobs.com") and route.tenant and route.site)
        )
    if route.provider_id == "bamboohr":
        return bool(
            route.token or route.board_url or (_bamboohr_host(route) and route.tenant)
        )
    if route.provider_id in {"teamtailor", "wpjobmanager"}:
        if route.provider_id == "teamtailor":
            return bool(_teamtailor_host(route))
        return bool(route.token or route.board_url or _host(route.host))
    if route.provider_id in {"greenhouse", "lever", "ashbyhq", "workable", "rippling"}:
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
    if provider == "consider_jobs":
        token = consider_jobs_token(route)
        if token:
            return f"consider_jobs:token:{token}"
    if provider == "teamtailor":
        host = _teamtailor_host(route)
        if host:
            return f"teamtailor:host:{host}"
    if provider == "bamboohr":
        host = _bamboohr_host(route)
        if host:
            return f"bamboohr:host:{host}"
    if provider == "rippling":
        key = _rippling_route_key(route)
        if key:
            return f"rippling:host:{key}"
    if provider == "wpjobmanager":
        key = _wpjobmanager_route_key(route)
        if key:
            return key
    token = _route_token(route)
    if provider in {"greenhouse", "lever", "ashbyhq", "workable"} and token:
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


_BOARD_TOKEN_PARSERS = {
    "greenhouse": greenhouse_token_from_url,
    "lever": lever_token_from_url,
    "workable": workable_token_from_url,
    "ashbyhq": ashby_token_from_url,
}


def _route_token(route: BoardProviderRecord) -> str | None:
    if route.token:
        return route.token.strip().lower()
    if route.board_url:
        parser = _BOARD_TOKEN_PARSERS.get(route.provider_id.lower())
        if parser:
            token = parser(route.board_url)
            return token.strip().lower() if token else None
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


def _host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return validate_public_host(value)
    except ValueError:
        return None


def _provider_host(route: BoardProviderRecord, domain: str) -> str | None:
    if not route.host:
        return None
    try:
        return validate_provider_host(route.host, domain)
    except ValueError:
        return None


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return _host(parsed.hostname)


def _origin_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower().rstrip("/")
    return f"{scheme}://{netloc}"


def _teamtailor_host(route: BoardProviderRecord) -> str | None:
    if route.host:
        return _provider_host(route, "teamtailor.com")
    host = _host_from_url(route.board_url)
    if host:
        try:
            return validate_provider_host(host, "teamtailor.com")
        except ValueError:
            pass
    if route.token:
        token = route.token.strip().lower()
        if token:
            try:
                return validate_provider_host(
                    f"{token}.teamtailor.com", "teamtailor.com"
                )
            except ValueError:
                return None
    return None


def _bamboohr_host(route: BoardProviderRecord) -> str | None:
    if route.host:
        return _provider_host(route, "bamboohr.com")
    host = _host_from_url(route.board_url)
    if host:
        try:
            return validate_provider_host(host, "bamboohr.com")
        except ValueError:
            pass
    tenant = (route.tenant or route.token or "").strip().lower()
    if tenant:
        try:
            return validate_provider_host(f"{tenant}.bamboohr.com", "bamboohr.com")
        except ValueError:
            return None
    return None


def _rippling_route_key(route: BoardProviderRecord) -> str | None:
    slug = _rippling_slug(route)
    host = _host(route.host) or _host_from_url(route.board_url)
    if not host and slug:
        host = "ats.rippling.com"
    if host and slug:
        return f"{host}:{slug}"
    return None


def _rippling_slug(route: BoardProviderRecord) -> str | None:
    for value in (route.tenant, route.token):
        if value and value.strip():
            return value.strip().lower()
    if not route.board_url:
        return None
    parsed = urlparse(route.board_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts[:3] == ["api", "v2", "board"] and len(parts) > 3:
        return parts[3].strip().lower()
    if len(parts) >= 2 and parts[1] == "jobs":
        return parts[0].strip().lower()
    return None


def _wpjobmanager_route_key(route: BoardProviderRecord) -> str | None:
    for value in (route.board_url, route.token):
        if value and value.strip().lower().startswith("https://"):
            key = _wpjobmanager_url_key(value)
            if key:
                return key
    host = _host(route.host)
    if host:
        return f"wpjobmanager:rest:https://{host}/wp-json/wp/v2/job-listings"
    return None


def _wpjobmanager_url_key(url: str) -> str | None:
    origin = _origin_from_url(url)
    if not origin:
        return None
    if _wpjobmanager_is_ajax_endpoint(url):
        return f"wpjobmanager:ajax:{origin}/jm-ajax/get_listings"
    return f"wpjobmanager:rest:{origin}/wp-json/wp/v2/job-listings"


def _wpjobmanager_is_ajax_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parsed.scheme == "https" and parts[:2] == ["jm-ajax", "get_listings"]
