from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlparse

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
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    ListingIdentityMode,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    optional_pull_attr,
    optional_pull_capabilities,
)
from openopps.providers.boards.url_targets import synthetic_url_pull_board
from openopps.providers.normalize import string as _string
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


ProviderGetMethod = optional_pull_attr("ProviderGetMethod")
ProviderGetResult = optional_pull_attr("ProviderGetResult")
ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")

_WPJOBMANAGER_MAX_PAGES = 500


@dataclass(frozen=True, slots=True)
class WPJobManagerListingSnapshot:
    listings: tuple[dict[str, Any], ...]
    pages_fetched: int
    advertised_count: int | None
    ajax: bool


class WPJobManagerProvider:
    provider_id = "wpjobmanager"
    provider_label = "WP Job Manager"
    provider_description = "Public WordPress WP Job Manager REST or AJAX endpoint."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        native_get_supported=True,
        interface_stability="best_effort",
    )

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

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            host = validate_public_host(parsed.hostname or "")
            if (
                parsed.netloc.casefold() != host.casefold()
                or parsed.query
                or parsed.fragment
                or parsed.params
            ):
                return None
            raw_parts = tuple(part for part in parsed.path.split("/") if part)
            parts = tuple(unquote(part) for part in raw_parts)
            if any(not part or "/" in part or part != part.strip() for part in parts):
                return None
            posting_id: str | None = None
            if parts == ("wp-json", "wp", "v2", "job-listings"):
                endpoint = f"https://{host}/wp-json/wp/v2/job-listings"
            elif (
                len(parts) == 5
                and parts[:4] == ("wp-json", "wp", "v2", "job-listings")
                and parts[4].isdecimal()
            ):
                endpoint = f"https://{host}/wp-json/wp/v2/job-listings"
                posting_id = parts[4]
            elif parts == ("jm-ajax", "get_listings"):
                endpoint = f"https://{host}/jm-ajax/get_listings"
            else:
                return None
            return ProviderUrlTarget(
                provider_id=WPJobManagerProvider.provider_id,
                target_kind=(
                    ProviderTargetKind.POSTING
                    if posting_id is not None
                    else ProviderTargetKind.BOARD
                ),
                url=url,
                board_identity=endpoint,
                posting_identity=posting_id,
                route=ProviderRouteIdentity(token=endpoint, host=host),
            )
        except (TypeError, ValueError):
            return None

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        endpoint = _require_wpjobmanager_target(target, ProviderTargetKind.BOARD)
        kernel = await self._list_public_membership(
            client,
            endpoint,
            board_name=target.route.host or target.board_identity,
            identity_mode="pull",
            include_unlisted=include_unlisted,
        )
        return kernel.to_provider_list_result(target)

    async def pull_get(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        endpoint = _require_wpjobmanager_target(target, ProviderTargetKind.POSTING)
        posting_id = target.posting_identity
        assert posting_id is not None
        if not wpjobmanager_is_rest_endpoint(endpoint):
            raise ValueError("WP Job Manager native get requires a REST target")
        data = await self._request_json(
            client,
            "GET",
            f"{endpoint}/{posting_id}",
            cache_identity={"role": "detail"},
        )
        if not isinstance(data, dict):
            raise ValueError("WP Job Manager detail endpoint returned invalid JSON")
        payload_id = data.get("id")
        if (
            isinstance(payload_id, bool)
            or payload_id is None
            or str(payload_id) != posting_id
        ):
            raise ValueError("WP Job Manager detail identity did not match the request")
        job = self._normalize(
            _pull_board(target),
            data,
            evidence_role="detail",
        )
        return ProviderGetResult(
            posting=ProviderPosting(job=job, listing=None, detail=job.raw_detail),
            method=ProviderGetMethod.NATIVE,
            matched_identity=posting_id,
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        endpoint = wpjobmanager_endpoint(route)
        if not endpoint:
            return JobFetchResult(jobs=[], authoritative=False)
        parsed = urlparse(endpoint)
        kernel = await self._list_public_membership(
            client,
            endpoint,
            board_name=parsed.netloc.lower() or endpoint,
            identity_mode="ingest",
            include_unlisted=False,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        *,
        board_name: str,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
    ) -> BoardListingKernelResult:
        del identity_mode
        if include_unlisted:
            raise ValueError("WP Job Manager cannot enumerate unlisted postings")
        if wpjobmanager_is_ajax_endpoint(endpoint):
            snapshot = await self._fetch_ajax_listing_snapshot(client, endpoint)
        else:
            snapshot = await self._fetch_listing_snapshot(client, endpoint)
        native_board = synthetic_url_pull_board(endpoint, name=board_name)
        postings: list[ListingPosting] = []
        for item in snapshot.listings:
            job = (
                self._normalize_ajax(native_board, item)
                if snapshot.ajax
                else self._normalize(native_board, item)
            )
            postings.append(
                ListingPosting(job=job, listing=job.raw_listing, detail=None)
            )
        return BoardListingKernelResult(
            native_board_identity=endpoint,
            postings=tuple(postings),
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=snapshot.pages_fetched,
                observed_count=len(postings),
                advertised_count=snapshot.advertised_count,
            ),
        )

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
        return list((await self._fetch_listing_snapshot(client, endpoint)).listings)

    async def _fetch_listing_snapshot(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> WPJobManagerListingSnapshot:
        listings: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        total: int | None = None
        total_pages: int | None = None
        seen_pages: set[tuple[str, ...]] = set()
        seen_listing_ids: set[str] = set()
        while True:
            if page > _WPJOBMANAGER_MAX_PAGES:
                raise ValueError("WP Job Manager pagination exceeded its page budget")
            response = await self._request_json_response(
                client,
                "GET",
                endpoint,
                params={"per_page": per_page, "page": page},
                cache_identity={"role": "membership_page"},
            )
            data = response.body
            if not isinstance(data, list):
                raise ValueError(
                    "WP Job Manager listings endpoint returned invalid JSON"
                )
            if any(not isinstance(item, dict) for item in data):
                raise ValueError(
                    "WP Job Manager listings endpoint returned invalid JSON"
                )
            page_listings = cast(list[dict[str, Any]], data)
            total = _consistent_total(total, _wp_total(response), label="total")
            total_pages = _consistent_total(
                total_pages, _wp_total_pages(response), label="total pages"
            )
            if total is not None and total_pages is not None:
                expected_total_pages = (total + per_page - 1) // per_page
                if total_pages != expected_total_pages:
                    raise ValueError(
                        "WP Job Manager advertised page count does not match total"
                    )
            page_signature = tuple(_rest_public_id(item) for item in page_listings)
            if page_listings and page_signature in seen_pages:
                raise ValueError("WP Job Manager repeated pagination page")
            seen_pages.add(page_signature)
            for listing_id in page_signature:
                if listing_id in seen_listing_ids:
                    raise ValueError("WP Job Manager repeated pagination listing")
                seen_listing_ids.add(listing_id)
            if not page_listings and (
                (total is not None and len(listings) < total)
                or (total_pages is not None and page < total_pages)
            ):
                raise ValueError(
                    "WP Job Manager incomplete pagination returned empty page"
                )
            listings.extend(page_listings)
            if total is not None and len(listings) > total:
                raise ValueError("WP Job Manager advertised total does not match jobs")
            if (
                total is not None
                and len(listings) == total
                and (total_pages is None or page >= total_pages)
            ):
                break
            if total_pages is not None:
                if page >= total_pages:
                    if total is not None and len(listings) != total:
                        raise ValueError(
                            "WP Job Manager advertised total does not match jobs"
                        )
                    break
            elif len(page_listings) < per_page:
                if total is not None:
                    raise ValueError(
                        "WP Job Manager advertised total does not match jobs"
                    )
                break
            page += 1
        if total is not None and len(listings) != total:
            raise ValueError("WP Job Manager advertised total does not match jobs")
        if (
            total_pages is not None
            and page != total_pages
            and not (total_pages == 0 and not listings and page == 1)
        ):
            raise ValueError(
                "WP Job Manager advertised page count does not match pages"
            )
        return WPJobManagerListingSnapshot(
            listings=tuple(listings),
            pages_fetched=page,
            advertised_count=total,
            ajax=False,
        )

    async def _fetch_ajax_listings(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[dict[str, Any]]:
        return list(
            (await self._fetch_ajax_listing_snapshot(client, endpoint)).listings
        )

    async def _fetch_ajax_listing_snapshot(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> WPJobManagerListingSnapshot:
        listings: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        expected_pages: int | None = None
        expected_total: int | None = None
        seen_pages: set[tuple[str, ...]] = set()
        seen_listing_ids: set[str] = set()
        while True:
            if page > _WPJOBMANAGER_MAX_PAGES:
                raise ValueError(
                    "WP Job Manager AJAX pagination exceeded its page budget"
                )
            data = await self._request_json(
                client,
                "GET",
                endpoint,
                params=_ajax_params(page=page, per_page=per_page),
                cache_identity={"role": "membership_page"},
            )
            if not isinstance(data, dict):
                raise ValueError("WP Job Manager AJAX endpoint returned invalid JSON")
            page_listings = _ajax_listings(endpoint, data)
            if len(page_listings) > per_page:
                raise ValueError(
                    "WP Job Manager AJAX page exceeded the requested per_page limit"
                )
            expected_pages = _consistent_total(
                expected_pages,
                _ajax_optional_int(
                    data,
                    "max_num_pages",
                    label="AJAX total pages",
                ),
                label="AJAX total pages",
            )
            expected_total = _consistent_total(
                expected_total, _ajax_reported_total(data), label="AJAX total"
            )
            page_signature = tuple(
                str(item.get("link") or item.get("title") or item)
                for item in page_listings
            )
            if page_listings and page_signature in seen_pages:
                raise ValueError("WP Job Manager repeated AJAX pagination page")
            seen_pages.add(page_signature)
            for listing_id in page_signature:
                if listing_id in seen_listing_ids:
                    raise ValueError("WP Job Manager repeated AJAX pagination listing")
                seen_listing_ids.add(listing_id)
            if not page_listings and (
                (expected_pages is not None and page < expected_pages)
                or (expected_total is not None and len(listings) < expected_total)
            ):
                raise ValueError(
                    "WP Job Manager incomplete pagination returned empty AJAX page"
                )
            listings.extend(page_listings)
            if expected_total is not None and len(listings) > expected_total:
                raise ValueError("WP Job Manager advertised total does not match jobs")
            if expected_pages is not None:
                if expected_pages == 0:
                    if listings:
                        raise ValueError(
                            "WP Job Manager advertised page count does not match jobs"
                        )
                    break
                if page > expected_pages:
                    raise ValueError(
                        "WP Job Manager pagination exceeded advertised AJAX pages"
                    )
                if page >= expected_pages:
                    break
            elif expected_total is not None:
                if len(listings) == expected_total:
                    break
                if len(page_listings) < per_page:
                    raise ValueError(
                        "WP Job Manager advertised total does not match jobs"
                    )
            elif len(page_listings) < per_page:
                break
            page += 1
        if (
            expected_pages is not None
            and page != expected_pages
            and not (expected_pages == 0 and not listings)
        ):
            raise ValueError(
                "WP Job Manager advertised page count does not match pages"
            )
        if expected_total is not None and len(listings) != expected_total:
            raise ValueError("WP Job Manager advertised total does not match jobs")
        return WPJobManagerListingSnapshot(
            listings=tuple(listings),
            pages_fetched=page,
            advertised_count=expected_total,
            ajax=True,
        )

    def _normalize(
        self,
        board: BoardRecord,
        posting: dict[str, Any],
        *,
        evidence_role: str = "listing",
    ) -> JobRecord:
        remote_id = _rest_public_id(posting)
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
            raw_listing=(
                cast(JsonDict, dict(posting)) if evidence_role == "listing" else {}
            ),
            raw_detail=(
                cast(JsonDict, dict(posting)) if evidence_role == "detail" else {}
            ),
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
    return parsed.scheme == "https" and parts == [
        "wp-json",
        "wp",
        "v2",
        "job-listings",
    ]


def wpjobmanager_is_ajax_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parsed.scheme == "https" and parts == ["jm-ajax", "get_listings"]


def _ajax_params(*, page: int, per_page: int) -> dict[str, int]:
    return {"page": page, "per_page": per_page}


def _ajax_count(data: dict[str, Any]) -> int:
    if data.get("found_jobs") is False:
        return 0
    total = _int(data.get("total") or data.get("total_found") or data.get("found"))
    if total is not None:
        return total
    return len(_ajax_listings("", data))


def _ajax_reported_total(data: dict[str, Any]) -> int | None:
    reported: int | None = None
    for key in ("total", "total_found", "found"):
        value = _ajax_optional_int(data, key, label="AJAX total")
        reported = _consistent_total(reported, value, label="AJAX total")
    if data.get("found_jobs") is False:
        if reported not in (None, 0):
            raise ValueError("WP Job Manager advertised total does not match jobs")
        return 0
    return reported


def _wp_total(response: HttpResponseData) -> int | None:
    return _wp_header_int(response, "x-wp-total", label="total")


def _wp_total_pages(response: HttpResponseData) -> int | None:
    return _wp_header_int(response, "x-wp-totalpages", label="total pages")


def _wp_header_int(
    response: HttpResponseData, header: str, *, label: str
) -> int | None:
    if header not in response.headers:
        return None
    value = _int(response.headers[header])
    if value is None:
        raise ValueError(f"WP Job Manager {label} must be an integer")
    if value < 0:
        raise ValueError(f"WP Job Manager {label} must be non-negative")
    return value


def _rest_public_id(posting: dict[str, Any]) -> str:
    listing_id = posting.get("id")
    if isinstance(listing_id, bool):
        raise ValueError("WP Job Manager listing has a malformed public job id")
    if listing_id is None:
        raise ValueError("WP Job Manager listing missing a public job id")
    text = str(listing_id)
    if not text.isdecimal():
        raise ValueError("WP Job Manager listing has a malformed public job id")
    return text


def _consistent_total(
    expected: int | None, reported: int | None, *, label: str
) -> int | None:
    if reported is None:
        return expected
    if reported < 0:
        raise ValueError(f"WP Job Manager {label} must be non-negative")
    if expected is not None and reported != expected:
        raise ValueError(f"WP Job Manager advertised {label} changed during pagination")
    return reported


def _ajax_optional_int(data: dict[str, Any], key: str, *, label: str) -> int | None:
    if key not in data:
        return None
    value = _int(data[key])
    if value is None:
        raise ValueError(f"WP Job Manager {label} must be an integer")
    if value < 0:
        raise ValueError(f"WP Job Manager {label} must be non-negative")
    return value


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


def _require_wpjobmanager_target(
    target: ProviderUrlTarget,
    kind: ProviderTargetKind,
) -> str:
    if (
        target.provider_id != WPJobManagerProvider.provider_id
        or target.target_kind != kind
    ):
        raise ValueError("WP Job Manager pull received an incompatible target")
    endpoint = target.route.token or target.board_identity
    if endpoint != target.board_identity:
        raise ValueError(
            "WP Job Manager target route does not match its board identity"
        )
    if not (
        wpjobmanager_is_rest_endpoint(endpoint)
        or wpjobmanager_is_ajax_endpoint(endpoint)
    ):
        raise ValueError("WP Job Manager target omitted a supported endpoint")
    return endpoint


def _pull_board(target: ProviderUrlTarget) -> BoardRecord:
    return synthetic_url_pull_board(
        target.board_identity,
        name=target.route.host or target.board_identity,
    )
