from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx

from openopps.http import (
    HttpResponseData,
    retrying_json_request,
    retrying_json_response,
)
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JsonDict,
    JobRecord,
    normalize_public_website_url,
    normalize_remote_level,
    strip_html,
    validate_public_host,
    validate_public_https_url,
)
from openopps.providers.base import ProviderRouteMatch
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class WPJobManagerProvider:
    provider_id = "wpjobmanager"
    provider_label = "WP Job Manager"
    provider_description = "Public WordPress WP Job Manager REST or AJAX endpoint."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)
        self._request_json_response = retrying_json_response(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        parsed = urlparse(url)
        if not (
            wpjobmanager_is_rest_endpoint(url) or wpjobmanager_is_ajax_endpoint(url)
        ):
            return None
        origin = f"https://{parsed.netloc.lower()}"
        return ProviderRouteMatch(token=origin, host=parsed.netloc.lower())

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        endpoint = wpjobmanager_endpoint(route)
        if not endpoint:
            return []
        if wpjobmanager_is_ajax_endpoint(endpoint):
            listings = await self._fetch_ajax_listings(client, endpoint)
            return [self._normalize_ajax(board, item) for item in listings]
        listings = await self._fetch_listings(client, endpoint)
        return [self._normalize(board, item) for item in listings]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        endpoint = wpjobmanager_endpoint(route)
        if not endpoint:
            return 0
        if wpjobmanager_is_ajax_endpoint(endpoint):
            data = await self._request_json(
                client, "GET", endpoint, params=_ajax_params(page=1, per_page=1)
            )
            if not isinstance(data, dict):
                raise ValueError("WP Job Manager AJAX endpoint returned invalid JSON")
            return _ajax_count(data)
        response = await self._request_json_response(
            client, "GET", endpoint, params={"per_page": 1}
        )
        data = response.body
        if not isinstance(data, list):
            raise ValueError("WP Job Manager listings endpoint returned invalid JSON")
        return _wp_total(response) or len(data)

    async def _fetch_listings(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        total: int | None = None
        while True:
            response = await self._request_json_response(
                client,
                "GET",
                endpoint,
                params={"per_page": per_page, "page": page},
            )
            data = response.body
            if not isinstance(data, list):
                raise ValueError(
                    "WP Job Manager listings endpoint returned invalid JSON"
                )
            total = total if total is not None else _wp_total(response)
            listings.extend(item for item in data if isinstance(item, dict))
            if (total is not None and len(listings) >= total) or len(data) < per_page:
                break
            page += 1
        return listings

    async def _fetch_ajax_listings(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        while True:
            data = await self._request_json(
                client,
                "GET",
                endpoint,
                params=_ajax_params(page=page, per_page=per_page),
            )
            if not isinstance(data, dict):
                raise ValueError("WP Job Manager AJAX endpoint returned invalid JSON")
            page_listings = _ajax_listings(endpoint, data)
            listings.extend(page_listings)
            if not _ajax_has_next_page(data, page) or not page_listings:
                break
            page += 1
        return listings

    def _normalize(self, board: BoardRecord, posting: dict[str, Any]) -> JobRecord:
        remote_id = str(
            first_present(
                posting.get("id"), posting.get("link"), _rendered(posting.get("title"))
            )
        )
        meta = (
            cast(dict[str, Any], posting.get("meta"))
            if isinstance(posting.get("meta"), dict)
            else {}
        )
        title = _rendered(posting.get("title")) or remote_id
        description_html = _rendered(posting.get("content")) or _rendered(
            posting.get("excerpt")
        )
        location = _string(
            first_present(
                meta.get("_job_location"), meta.get("geolocation_formatted_address")
            )
        )
        company = _string(first_present(meta.get("_company_name"), board.name))
        apply_url = normalize_public_website_url(
            first_present(meta.get("_application"), posting.get("link"))
        )
        posting_url = normalize_public_website_url(posting.get("link"))
        employment_type = _string(
            first_present(meta.get("_job_type"), posting.get("type"))
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=title,
            locations=[location] if location else [],
            workplace_type=employment_type,
            company=company,
            employment_type=employment_type,
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(location),
            posting_url=posting_url,
            apply_url=apply_url,
            posted_at=_string(posting.get("date")),
            updated_at=_string(posting.get("modified")),
            raw_listing=cast(JsonDict, dict(posting)),
        )

    def _normalize_ajax(self, board: BoardRecord, posting: dict[str, Any]) -> JobRecord:
        posting_url = normalize_public_website_url(posting.get("link"))
        title = _string(posting.get("title")) or posting_url or "WP Job Manager posting"
        location = _string(posting.get("location"))
        company = _string(first_present(posting.get("company"), board.name))
        remote_id = posting_url or title
        description_html = _string(posting.get("html"))
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=title,
            locations=[location] if location else [],
            company=company,
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(location),
            posting_url=posting_url,
            apply_url=posting_url,
            raw_listing=cast(JsonDict, dict(posting)),
        )


def wpjobmanager_endpoint(route: BoardProviderRecord) -> str | None:
    if route.board_url:
        parsed = urlparse(route.board_url)
        if wpjobmanager_is_rest_endpoint(
            route.board_url
        ) or wpjobmanager_is_ajax_endpoint(route.board_url):
            return route.board_url
        return urljoin(f"https://{parsed.netloc}", "/wp-json/wp/v2/job-listings")
    if route.token and route.token.startswith("https://"):
        return urljoin(route.token.rstrip("/") + "/", "wp-json/wp/v2/job-listings")
    if route.host:
        try:
            host = validate_public_host(route.host)
        except ValueError:
            return None
        return f"https://{host}/wp-json/wp/v2/job-listings"
    return None


def wpjobmanager_is_rest_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parsed.scheme == "https" and parts[:4] == [
        "wp-json",
        "wp",
        "v2",
        "job-listings",
    ]


def wpjobmanager_is_ajax_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parsed.scheme == "https" and parts[:2] == ["jm-ajax", "get_listings"]


def _ajax_params(*, page: int, per_page: int) -> dict[str, int]:
    return {"page": page, "per_page": per_page}


def _ajax_count(data: dict[str, Any]) -> int:
    if data.get("found_jobs") is False:
        return 0
    total = _int(data.get("total") or data.get("total_found") or data.get("found"))
    if total is not None:
        return total
    return len(_ajax_listings("", data))


def _wp_total(response: HttpResponseData) -> int | None:
    return _int(response.headers.get("x-wp-total"))


def _ajax_has_next_page(data: dict[str, Any], page: int) -> bool:
    max_pages = _int(data.get("max_num_pages"))
    return bool(max_pages and page < max_pages)


def _ajax_listings(endpoint: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    html = _string(data.get("html"))
    if not html:
        return []
    return [
        {
            "source": "jm-ajax/get_listings",
            "endpoint": endpoint,
            "html": fragment,
            "title": _html_text(fragment, r"<h[1-6][^>]*>(.*?)</h[1-6]>")
            or _html_text(fragment, r"<a[^>]*>(.*?)</a>"),
            "link": _html_attr(fragment, "href"),
            "location": _html_class_text(fragment, "location"),
            "company": _html_class_text(fragment, "company"),
        }
        for fragment in _ajax_listing_fragments(html)
    ]


def _ajax_listing_fragments(html: str) -> list[str]:
    matches = re.finditer(
        r"<li\b(?=[^>]*\bjob_listing\b)[\s\S]*?(?=<li\b(?=[^>]*\bjob_listing\b)|</ul>|$)",
        html,
        flags=re.IGNORECASE,
    )
    return [match.group(0) for match in matches]


def _html_class_text(fragment: str, class_name: str) -> str | None:
    return _html_text(
        fragment,
        rf"<[^>]+class=['\"][^'\"]*\b{re.escape(class_name)}\b[^'\"]*['\"][^>]*>(.*?)</[^>]+>",
    )


def _html_text(fragment: str, pattern: str) -> str | None:
    match = re.search(pattern, fragment, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return strip_html(match.group(1))


def _html_attr(fragment: str, attr: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(attr)}=['\"]([^'\"]+)['\"]",
        fragment,
        flags=re.IGNORECASE,
    )
    return _string(match.group(1)) if match else None


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _rendered(value: object) -> str | None:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        return _string(data.get("rendered"))
    return _string(value)


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
