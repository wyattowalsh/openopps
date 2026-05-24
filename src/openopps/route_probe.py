from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from openopps.http import build_async_client, retrying_json_request
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport, utc_now
from openopps.models import host_matches, validate_provider_host
from openopps.providers.boards.workday import parse_workday_board_url
from openopps.providers.boards.wpjobmanager import (
    wpjobmanager_is_ajax_endpoint,
    wpjobmanager_is_rest_endpoint,
)
from openopps.route_select import dedupe_routes, normalize_provider_filter, route_ready
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import slugify


_TOKEN_SUFFIXES = (
    "-inc",
    "-incorporated",
    "-company",
    "-technologies",
    "-technology",
    "-labs",
    "-ai",
    "-hq",
    "-health",
    "-software",
    "-systems",
)
_STOP_TOKENS = {
    "com",
    "io",
    "ai",
    "co",
    "www",
    "careers",
    "jobs",
    "workdayjobs",
    "myworkdayjobs",
}
_MISS_STATUS_CODES = {400, 401, 403, 404}
_ROUTE_PROBE_CACHE_NAMESPACE = "route_probe"

JsonRequester = Callable[..., Awaitable[dict[str, Any] | list[Any]]]


@dataclass(frozen=True)
class ProbeMatch:
    board_key: str
    provider_id: str
    token: str | None = None
    board_url: str | None = None
    host: str | None = None
    tenant: str | None = None
    site: str | None = None
    observed_jobs: int | None = None


@dataclass(frozen=True)
class ProbeUnknown:
    board_key: str
    provider_id: str
    name: str
    reason: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class ProbeSummary:
    discovered: int = 0
    route_ready_skipped: int = 0
    duplicate_routes_skipped: int = 0
    checked: int = 0
    matched: list[ProbeMatch] = field(default_factory=list)
    unknown: list[ProbeUnknown] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)
    selected_by_provider: dict[str, int] = field(default_factory=dict)
    matched_by_provider: dict[str, int] = field(default_factory=dict)
    unknown_by_reason: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "routeReadySkipped": self.route_ready_skipped,
            "duplicateRoutesSkipped": self.duplicate_routes_skipped,
            "checked": self.checked,
            "matched": [match.__dict__ for match in self.matched],
            "unknown": [unknown.__dict__ for unknown in self.unknown],
            "errors": self.errors,
            "selectedByProvider": self.selected_by_provider,
            "matchedByProvider": self.matched_by_provider,
            "unknownByReason": self.unknown_by_reason,
            "matchedCount": len(self.matched),
            "unknownCount": len(self.unknown),
        }


def token_candidates(board: BoardRecord, *, max_candidates: int = 12) -> list[str]:
    values = [
        board.remote_slug,
        board.remote_id,
        board.name,
        board.domain,
        board.website_url,
    ]
    output: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        token = value.strip().lower()
        if not token:
            return
        parsed = urlparse(token)
        if parsed.netloc:
            token = parsed.netloc
        token = token.removeprefix("www.")
        if "." in token and "/" not in token:
            parts = [
                part for part in token.split(".") if part and part not in _STOP_TOKENS
            ]
            if parts:
                add(parts[0])
                for part in parts[1:2]:
                    add(part)
        slug = slugify(token)
        variants = [slug, slug.replace("-", "")]
        variants.append(re.sub(r"[^a-z0-9]", "", token))
        for suffix in _TOKEN_SUFFIXES:
            if slug.endswith(suffix):
                variants.extend(
                    [slug[: -len(suffix)], slug[: -len(suffix)].replace("-", "")]
                )
        if slug.startswith("the-"):
            variants.extend(
                [slug.removeprefix("the-"), slug.removeprefix("the-").replace("-", "")]
            )
        for variant in variants:
            if variant and variant not in _STOP_TOKENS and variant not in output:
                output.append(variant)

    for value in values:
        add(str(value) if value is not None else None)
    return output[:max_candidates]


async def probe_routes(
    *,
    settings: OpenOppsSettings,
    store: OpenOppsStore,
    source_key: str | None = None,
    board_key: str | None = None,
    provider_id: str | None = None,
    only_missing: bool = True,
    apply: bool = False,
    max_candidates: int = 12,
    limit: int | None = None,
) -> ProbeSummary:
    summary = ProbeSummary()
    provider_filter = normalize_provider_filter(provider_id)
    routes = store.list_board_providers(
        source_key=source_key,
        board_key=board_key,
        provider_id=provider_filter,
        job_capable_only=True,
    )
    summary.discovered = len(routes)
    if only_missing:
        ready_routes = [route for route in routes if route_ready(route)]
        summary.route_ready_skipped = len(ready_routes)
        routes = [route for route in routes if not route_ready(route)]
    boards = {
        board.key: board
        for board in store.list_boards(source_key=source_key, board_key=board_key)
    }
    routes, duplicate_routes = dedupe_routes(routes, boards)
    summary.duplicate_routes_skipped = len(duplicate_routes)
    if limit:
        routes = routes[:limit]
    for route in routes:
        _increment(summary.selected_by_provider, route.provider_id)
    logger.info(
        "Route probe selected {} routes from {} discovered job-capable provider hints; skipped_ready={} duplicates_skipped={}",
        len(routes),
        summary.discovered,
        summary.route_ready_skipped,
        summary.duplicate_routes_skipped,
    )
    route_by_key = {(route.board_key, route.provider_id): route for route in routes}
    semaphore = asyncio.Semaphore(settings.provider_concurrency)
    async with build_async_client(settings) as client:
        request_json = retrying_json_request(settings)

        async def run(route: BoardProviderRecord) -> None:
            board = boards.get(route.board_key)
            if not board:
                return
            async with semaphore:
                summary.checked += 1
                try:
                    match, unknown = await _probe_route(
                        client,
                        request_json,
                        board,
                        route,
                        max_candidates=max_candidates,
                    )
                except Exception:
                    summary.errors[route.provider_id] = (
                        summary.errors.get(route.provider_id, 0) + 1
                    )
                    _increment(summary.unknown_by_reason, "probe_error")
                    summary.unknown.append(
                        ProbeUnknown(
                            board_key=route.board_key,
                            provider_id=route.provider_id,
                            name=board.name,
                            reason="probe_error",
                            candidates=token_candidates(
                                board, max_candidates=max_candidates
                            ),
                        )
                    )
                    return
                if match:
                    summary.matched.append(match)
                    _increment(summary.matched_by_provider, match.provider_id)
                    logger.info(
                        "Route probe matched board={} provider={} route={} observed_jobs={}",
                        match.board_key,
                        match.provider_id,
                        match.token or match.site or match.board_url,
                        match.observed_jobs,
                    )
                elif unknown:
                    summary.unknown.append(unknown)
                    _increment(summary.unknown_by_reason, unknown.reason)
                    logger.info(
                        "Route probe unresolved board={} provider={} reason={} candidates={}",
                        unknown.board_key,
                        unknown.provider_id,
                        unknown.reason,
                        len(unknown.candidates),
                    )

        await asyncio.gather(*(run(route) for route in routes))
    if apply and summary.matched:
        updates_to_persist: list[BoardProviderRecord] = []
        for match in summary.matched:
            route = route_by_key.get((match.board_key, match.provider_id))
            if not route:
                continue
            updates: dict[str, Any] = {
                "last_status": "route_ready",
                "detected_at": utc_now(),
                "support_level": ProviderSupport.JOBS,
            }
            for field_name in ("token", "board_url", "host", "tenant", "site"):
                value = getattr(match, field_name)
                if value:
                    updates[field_name] = value
            updates_to_persist.append(route.model_copy(update=updates))
        store.upsert_board_providers(updates_to_persist)
        logger.info(
            "Route probe persisted {} matched route updates", len(updates_to_persist)
        )
    logger.info(
        "Route probe finished checked={} matched={} unknown={} errors={}",
        summary.checked,
        len(summary.matched),
        len(summary.unknown),
        summary.errors,
    )
    return summary


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


async def _probe_route(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    board: BoardRecord,
    route: BoardProviderRecord,
    *,
    max_candidates: int,
) -> tuple[ProbeMatch | None, ProbeUnknown | None]:
    if route.provider_id in {
        "greenhouse",
        "lever",
        "ashbyhq",
        "workable",
        "teamtailor",
        "bamboohr",
        "rippling",
    }:
        return await _probe_token_provider(
            client,
            request_json,
            board,
            route,
            max_candidates=max_candidates,
            provider_id=route.provider_id,
        )
    if route.provider_id == "workday":
        return await _probe_workday(client, request_json, board, route)
    if route.provider_id == "wpjobmanager":
        return await _probe_wpjobmanager(client, request_json, board, route)
    return None, ProbeUnknown(
        board_key=board.key,
        provider_id=route.provider_id,
        name=board.name,
        reason="provider_not_probeable",
    )


async def _probe_token_provider(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    board: BoardRecord,
    route: BoardProviderRecord,
    *,
    max_candidates: int,
    provider_id: str,
) -> tuple[ProbeMatch | None, ProbeUnknown | None]:
    candidates = token_candidates(board, max_candidates=max_candidates)
    for token in candidates:
        if provider_id == "greenhouse":
            result = await _try_greenhouse(client, request_json, token)
        elif provider_id == "lever":
            result = await _try_lever(client, request_json, token)
        elif provider_id == "ashbyhq":
            result = await _try_ashby(client, request_json, token)
        elif provider_id == "workable":
            result = await _try_workable(client, request_json, token)
        elif provider_id == "teamtailor":
            result = await _try_teamtailor(client, token)
        elif provider_id == "bamboohr":
            result = await _try_bamboohr(client, request_json, token)
        elif provider_id == "rippling":
            result = await _try_rippling(client, request_json, token)
        else:
            result = None
        if result is not None:
            board_url = _candidate_board_url(provider_id, token)
            host = _candidate_host(provider_id, token)
            return (
                ProbeMatch(
                    board_key=board.key,
                    provider_id=provider_id,
                    token=token,
                    board_url=board_url,
                    host=host,
                    tenant=token if provider_id in {"bamboohr", "rippling"} else None,
                    observed_jobs=result,
                ),
                None,
            )
    return None, ProbeUnknown(
        board_key=board.key,
        provider_id=route.provider_id,
        name=board.name,
        reason="no_candidate_token_matched",
        candidates=candidates,
    )


def _candidate_board_url(provider_id: str, token: str) -> str:
    if provider_id == "greenhouse":
        return f"https://boards.greenhouse.io/{token}"
    if provider_id == "lever":
        return f"https://jobs.lever.co/{token}"
    if provider_id == "ashbyhq":
        return f"https://jobs.ashbyhq.com/{token}"
    if provider_id == "workable":
        return f"https://apply.workable.com/{token}"
    if provider_id == "teamtailor":
        return f"https://{token}.teamtailor.com/"
    if provider_id == "bamboohr":
        return f"https://{token}.bamboohr.com/careers"
    if provider_id == "rippling":
        return f"https://ats.rippling.com/{token}/jobs"
    return token


def _candidate_host(provider_id: str, token: str) -> str | None:
    if provider_id == "teamtailor":
        return f"{token}.teamtailor.com"
    if provider_id == "bamboohr":
        return f"{token}.bamboohr.com"
    if provider_id == "rippling":
        return "ats.rippling.com"
    return None


async def _try_greenhouse(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        params={"content": "false"},
        provider_id="greenhouse",
        route_key=token,
    )
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(data["jobs"])
    return None


async def _try_lever(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://api.lever.co/v0/postings/{token}",
        params={"mode": "json"},
        provider_id="lever",
        route_key=token,
    )
    if isinstance(data, list):
        return len(data)
    return None


async def _try_ashby(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        params={"includeCompensation": "false"},
        provider_id="ashbyhq",
        route_key=token,
    )
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(
            [
                job
                for job in data["jobs"]
                if isinstance(job, dict) and job.get("isListed") is not False
            ]
        )
    return None


async def _try_workable(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://www.workable.com/api/accounts/{token}",
        params={"details": "false"},
        provider_id="workable",
        route_key=token,
    )
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(data["jobs"])
    return None


async def _try_teamtailor(client: httpx.AsyncClient, token: str) -> int | None:
    try:
        response = await client.get(
            f"https://{token}.teamtailor.com/jobs.rss",
            headers={"accept": "application/rss+xml, application/xml, text/xml"},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in _MISS_STATUS_CODES:
            return None
        raise
    root = ET.fromstring(response.text)
    channel = root.find("channel")
    return len(channel.findall("item")) if channel is not None else 0


async def _try_bamboohr(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://{token}.bamboohr.com/careers/list",
        provider_id="bamboohr",
        route_key=token,
    )
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("totalCount"), int):
        return int(meta["totalCount"])
    result = data.get("result")
    if isinstance(result, list):
        return len(result)
    return None


async def _try_rippling(
    client: httpx.AsyncClient, request_json: JsonRequester, token: str
) -> int | None:
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        f"https://ats.rippling.com/api/v2/board/{token}/jobs",
        params={"page": 0, "pageSize": 1},
        provider_id="rippling",
        route_key=token,
    )
    if not isinstance(data, dict):
        return None
    total = data.get("totalItems")
    if isinstance(total, int):
        return total
    items = data.get("items")
    return len(items) if isinstance(items, list) else None


async def _probe_workday(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    board: BoardRecord,
    route: BoardProviderRecord,
) -> tuple[ProbeMatch | None, ProbeUnknown | None]:
    urls = [route.board_url, board.website_url]
    url_hints: list[str] = []
    for url in urls:
        parsed_url = urlparse(url or "")
        if not url or not host_matches(parsed_url.hostname, "myworkdayjobs.com"):
            continue
        url_hints.append(url)
        try:
            parsed = parse_workday_board_url(url)
        except ValueError:
            continue
        count = await _try_workday(
            client, request_json, parsed.host, parsed.tenant, parsed.site
        )
        if count is not None:
            return (
                ProbeMatch(
                    board_key=board.key,
                    provider_id="workday",
                    board_url=url,
                    host=parsed.host,
                    tenant=parsed.tenant,
                    site=parsed.site,
                    observed_jobs=count,
                ),
                None,
            )
    if route.host and route.tenant and route.site:
        try:
            host = validate_provider_host(route.host, "myworkdayjobs.com")
        except ValueError:
            host = ""
        count = (
            await _try_workday(client, request_json, host, route.tenant, route.site)
            if host
            else None
        )
        if count is not None:
            return (
                ProbeMatch(
                    board_key=board.key,
                    provider_id="workday",
                    host=host,
                    tenant=route.tenant,
                    site=route.site,
                    observed_jobs=count,
                ),
                None,
            )
    return None, ProbeUnknown(
        board_key=board.key,
        provider_id="workday",
        name=board.name,
        reason="needs_public_workday_board_url",
        candidates=url_hints,
    )


async def _try_workday(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    host: str,
    tenant: str,
    site: str,
) -> int | None:
    host = validate_provider_host(host, "myworkdayjobs.com")
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "POST",
        f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
        json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "referer": f"https://{host}/{site}",
        },
        provider_id="workday",
        route_key=f"{host}:{tenant}:{site}",
    )
    if isinstance(data, dict) and isinstance(data.get("jobPostings"), list):
        return int(data.get("total") or len(data["jobPostings"]))
    return None


async def _probe_wpjobmanager(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    board: BoardRecord,
    route: BoardProviderRecord,
) -> tuple[ProbeMatch | None, ProbeUnknown | None]:
    endpoints = _wpjobmanager_endpoint_candidates(route, board)
    for endpoint in endpoints:
        count = await _try_wpjobmanager(client, request_json, endpoint)
        if count is None:
            continue
        parsed = urlparse(endpoint)
        origin = f"https://{parsed.netloc.lower()}"
        return (
            ProbeMatch(
                board_key=board.key,
                provider_id="wpjobmanager",
                token=origin,
                board_url=endpoint,
                host=parsed.netloc.lower(),
                observed_jobs=count,
            ),
            None,
        )
    return None, ProbeUnknown(
        board_key=board.key,
        provider_id="wpjobmanager",
        name=board.name,
        reason="needs_explicit_wpjobmanager_endpoint",
        candidates=endpoints,
    )


def _wpjobmanager_endpoint_candidates(
    route: BoardProviderRecord, board: BoardRecord
) -> list[str]:
    endpoints: list[str] = []
    for url in (route.board_url, board.website_url):
        parsed = urlparse(url or "")
        if not url or not (
            wpjobmanager_is_rest_endpoint(url) or wpjobmanager_is_ajax_endpoint(url)
        ):
            continue
        if wpjobmanager_is_ajax_endpoint(url):
            endpoint = f"https://{parsed.netloc.lower()}/jm-ajax/get_listings/"
        else:
            endpoint = f"https://{parsed.netloc.lower()}/wp-json/wp/v2/job-listings"
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


async def _try_wpjobmanager(
    client: httpx.AsyncClient, request_json: JsonRequester, endpoint: str
) -> int | None:
    if wpjobmanager_is_ajax_endpoint(endpoint):
        data = await _route_probe_json_or_none(
            client,
            request_json,
            "GET",
            endpoint,
            params={"page": 1, "per_page": 1},
            provider_id="wpjobmanager",
            route_key=endpoint,
        )
        if not isinstance(data, dict):
            return None
        if data.get("found_jobs") is False:
            return 0
        html = data.get("html")
        return 1 if isinstance(html, str) and "job_listing" in html else 0
    data = await _route_probe_json_or_none(
        client,
        request_json,
        "GET",
        endpoint,
        params={"per_page": 1},
        provider_id="wpjobmanager",
        route_key=endpoint,
    )
    return len(data) if isinstance(data, list) else None


async def _route_probe_json_or_none(
    client: httpx.AsyncClient,
    request_json: JsonRequester,
    method: str,
    url: str,
    *,
    provider_id: str,
    route_key: str,
    **kwargs: Any,
) -> dict[str, Any] | list[Any] | None:
    try:
        return await request_json(
            client,
            method,
            url,
            **kwargs,
            cache_namespace=_ROUTE_PROBE_CACHE_NAMESPACE,
            cache_identity={"provider": provider_id, "route": route_key},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in _MISS_STATUS_CODES:
            return None
        raise
