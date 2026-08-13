from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
from loguru import logger

from openopps.http import AsyncSlidingWindowRateLimiter, retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JsonDict,
    JobRecord,
    normalize_remote_level,
    strip_html,
    validate_public_https_url,
)
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.boards.tokens import workable_token_from_url
from openopps.providers.normalize import (
    salary_components,
    salary_display,
    string as _string,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id

__all__ = [
    "WorkableListingSnapshot",
    "WorkableProvider",
    "WorkablePublicClient",
    "WorkableSnapshotError",
    "workable_page_budget",
    "workable_token",
    "workable_token_from_url",
]


_WORKABLE_RATE_LIMITER = AsyncSlidingWindowRateLimiter(limit=10, window_seconds=10.0)
_WORKABLE_LISTING_CACHE_NAMESPACE = "route_probe"
_WORKABLE_DETAILS_CACHE_NAMESPACE = "workable_details"
_WORKABLE_DEFAULT_PAGE_LIMIT = 150
_WORKABLE_HARD_PAGE_LIMIT = 500
_WORKABLE_TIMEOUT_RESERVE_SECONDS = 30.0

JsonRequester = Callable[..., Awaitable[dict[str, Any] | list[Any]]]


class WorkableSnapshotError(ValueError):
    """Raised when Workable cannot provide one complete listing generation."""


@dataclass(frozen=True, slots=True)
class WorkableListingSnapshot:
    listings: tuple[dict[str, Any], ...]
    total: int
    page_count: int


class WorkablePublicClient:
    def __init__(
        self,
        request_json: JsonRequester,
        *,
        max_pages: int = _WORKABLE_DEFAULT_PAGE_LIMIT,
        refresh: bool = False,
    ) -> None:
        self._request_json = request_json
        self._max_pages = max(1, min(max_pages, _WORKABLE_HARD_PAGE_LIMIT))
        self._refresh = refresh

    async def fetch_listing_snapshot(
        self, client: httpx.AsyncClient, token: str
    ) -> WorkableListingSnapshot:
        try:
            return await self._fetch_listing_generation(
                client, token, refresh=self._refresh
            )
        except WorkableSnapshotError:
            if self._refresh:
                raise
            return await self._fetch_listing_generation(client, token, refresh=True)

    async def fetch_details_by_shortcode(
        self, client: httpx.AsyncClient, token: str
    ) -> dict[str, dict[str, Any]]:
        await wait_for_workable_rate_limit()
        data = await self._request_json(
            client,
            "GET",
            f"https://www.workable.com/api/accounts/{token}?details=true",
            cache_namespace=_WORKABLE_DETAILS_CACHE_NAMESPACE,
            cache_identity={"provider": "workable", "route": token},
        )
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError(
                "Workable aggregate details endpoint returned invalid JSON"
            )
        jobs = data["jobs"]
        if any(not isinstance(item, dict) for item in jobs):
            raise ValueError(
                "Workable aggregate details endpoint returned invalid JSON"
            )
        return {
            shortcode: item
            for item in jobs
            if (shortcode := _string(item.get("shortcode"))) is not None
        }

    async def _fetch_listing_generation(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        refresh: bool,
    ) -> WorkableListingSnapshot:
        url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
        listings: list[dict[str, Any]] = []
        seen_shortcodes: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        expected_total: int | None = None
        page_count = 0

        while True:
            page_count += 1
            if page_count > self._max_pages:
                raise WorkableSnapshotError(
                    f"Workable listing traversal exceeded {self._max_pages} pages"
                )
            body = {"token": cursor} if cursor is not None else {}
            await wait_for_workable_rate_limit()
            try:
                data = await self._request_json(
                    client,
                    "POST",
                    url,
                    json=body,
                    cache_namespace=_WORKABLE_LISTING_CACHE_NAMESPACE,
                    cache_identity={"provider": "workable", "route": token},
                    cache_refresh=refresh,
                    cache_stale_on_error=False if refresh else True,
                )
            except httpx.HTTPStatusError as exc:
                if page_count > 1:
                    raise WorkableSnapshotError(
                        "Workable listing traversal failed after the first page"
                    ) from exc
                raise

            page_total, page_results, next_cursor = _validate_listing_page(data)
            if expected_total is None:
                expected_total = page_total
                _validate_page_budget(
                    total=page_total,
                    first_page_size=len(page_results),
                    has_next=next_cursor is not None,
                    max_pages=self._max_pages,
                )
            elif page_total != expected_total:
                raise WorkableSnapshotError(
                    "Workable listing total changed during pagination"
                )

            for item in page_results:
                shortcode = _string(item.get("shortcode"))
                if shortcode is None:
                    raise WorkableSnapshotError(
                        "Workable listing page omitted a job shortcode"
                    )
                if shortcode in seen_shortcodes:
                    raise WorkableSnapshotError(
                        "Workable listing pagination returned a duplicate job"
                    )
                seen_shortcodes.add(shortcode)
                listings.append(item)

            if len(listings) > expected_total:
                raise WorkableSnapshotError(
                    "Workable listing traversal exceeded the advertised total"
                )
            if next_cursor is None:
                if len(listings) != expected_total:
                    raise WorkableSnapshotError(
                        "Workable listing traversal ended before the advertised total"
                    )
                return WorkableListingSnapshot(
                    listings=tuple(listings),
                    total=expected_total,
                    page_count=page_count,
                )
            if not page_results:
                raise WorkableSnapshotError(
                    "Workable listing traversal returned an empty continuation page"
                )
            if next_cursor in seen_cursors:
                raise WorkableSnapshotError(
                    "Workable listing traversal repeated a continuation token"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor


async def wait_for_workable_rate_limit() -> None:
    await _WORKABLE_RATE_LIMITER.wait()


def workable_page_budget(timeout_seconds: float) -> int:
    usable_seconds = max(1.0, timeout_seconds - _WORKABLE_TIMEOUT_RESERVE_SECONDS)
    return min(_WORKABLE_HARD_PAGE_LIMIT, int(usable_seconds))


class WorkableProvider:
    provider_id = "workable"
    provider_label = "Workable"
    provider_description = "Public Workable hosted-board JSON endpoint."
    route_concurrency = 1

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)
        self._public_client = WorkablePublicClient(
            self._request_json,
            max_pages=workable_page_budget(settings.job_route_timeout_seconds),
            refresh=settings.cache_refresh,
        )

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        token = _token_from_url(url)
        return ProviderRouteMatch(token=token) if token else None

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        token = workable_token(route)
        if not token:
            raise ValueError("Workable route is missing a public board token")
        snapshot = await self._public_client.fetch_listing_snapshot(client, token)
        try:
            details_by_shortcode = await self._public_client.fetch_details_by_shortcode(
                client, token
            )
        except Exception as exc:
            logger.warning(
                "Workable aggregate detail enrichment failed route={} error={}",
                token,
                type(exc).__name__,
            )
            details_by_shortcode = {}
        return JobFetchResult(
            jobs=[
                self._normalize(
                    board,
                    token,
                    listing,
                    details_by_shortcode.get(
                        _string(listing.get("shortcode")) or "", {}
                    ),
                )
                for listing in snapshot.listings
            ],
            authoritative=True,
        )

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        token = workable_token(route)
        if not token:
            return 0
        snapshot = await self._public_client.fetch_listing_snapshot(client, token)
        return snapshot.total

    def _normalize(
        self,
        board: BoardRecord,
        token: str,
        listing: dict[str, Any],
        detail: dict[str, Any],
    ) -> JobRecord:
        posting = {**listing, **detail}
        remote_id = str(
            first_present(
                posting.get("shortcode"),
                posting.get("id"),
                posting.get("url"),
                posting.get("title"),
            )
        )
        description_html = _string(posting.get("description"))
        locations = _locations(posting)
        compensation = _json_dict(posting.get("salary")) or _json_dict(
            posting.get("compensation")
        )
        salary_min, salary_max, salary_currency = salary_components(
            compensation,
            min_keys=("minValue", "min"),
            max_keys=("maxValue", "max"),
        )
        posting_url = _posting_url(
            token, remote_id, posting.get("url"), posting.get("shortlink")
        )
        apply_url = _posting_url(
            token,
            remote_id,
            posting.get("application_url"),
            posting.get("url"),
            posting.get("shortlink"),
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(posting.get("title")) or remote_id,
            locations=locations,
            department=_string_or_first(posting.get("department")),
            team=_string(posting.get("function")),
            workplace_type=_string(
                first_present(posting.get("employment_type"), posting.get("type"))
            ),
            company=board.name,
            employment_type=_string(
                first_present(posting.get("employment_type"), posting.get("type"))
            ),
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(
                locations,
                is_remote=posting.get("remote")
                if isinstance(posting.get("remote"), bool)
                else posting.get("telecommuting")
                if isinstance(posting.get("telecommuting"), bool)
                else None,
            ),
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            experience=_string(posting.get("experience")),
            posting_url=posting_url,
            apply_url=apply_url,
            posted_at=_string(
                first_present(
                    posting.get("published_on"),
                    posting.get("published"),
                    posting.get("created_at"),
                )
            ),
            raw_listing=_raw(listing),
            raw_detail=_raw(detail) if detail else {},
        )


def _validate_listing_page(
    data: dict[str, Any] | list[Any],
) -> tuple[int, list[dict[str, Any]], str | None]:
    if not isinstance(data, dict):
        raise WorkableSnapshotError("Workable jobs endpoint returned invalid JSON")
    total = data.get("total")
    results = data.get("results")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(results, list)
        or any(not isinstance(item, dict) for item in results)
    ):
        raise WorkableSnapshotError("Workable jobs endpoint returned invalid JSON")
    next_cursor = data.get("nextPage")
    if next_cursor is not None and (
        not isinstance(next_cursor, str)
        or not next_cursor
        or next_cursor != next_cursor.strip()
    ):
        raise WorkableSnapshotError(
            "Workable jobs endpoint returned an invalid continuation token"
        )
    return total, cast(list[dict[str, Any]], results), next_cursor


def _validate_page_budget(
    *,
    total: int,
    first_page_size: int,
    has_next: bool,
    max_pages: int,
) -> None:
    if total == 0:
        expected_requests = 1
    elif first_page_size == 0:
        raise WorkableSnapshotError(
            "Workable listing traversal started with an incomplete empty page"
        )
    else:
        expected_requests = (total + first_page_size - 1) // first_page_size
        if has_next and total % first_page_size == 0:
            expected_requests += 1
    if expected_requests > max_pages:
        raise WorkableSnapshotError(
            "Workable advertised total exceeds the route page budget"
        )


def workable_token(route: BoardProviderRecord) -> str | None:
    if route.token:
        return route.token.strip()
    if not route.board_url:
        return None
    return workable_token_from_url(route.board_url)


def _token_from_url(url: str) -> str | None:
    return workable_token_from_url(url)


def _locations(posting: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw_locations = posting.get("locations")
    if isinstance(raw_locations, list):
        for location in raw_locations:
            if isinstance(location, dict) and location.get("hidden") is not True:
                values.append(_location_label(location))
            elif isinstance(location, str):
                values.append(location)
    if not values:
        values.append(_location_label(posting))
    return [value for value in dict.fromkeys(values) if value]


def _location_label(value: dict[str, Any]) -> str:
    parts = [
        _string(value.get("city")),
        _string(value.get("region") or value.get("state")),
        _string(value.get("country")),
    ]
    return ", ".join(part for part in parts if part)


def _json_dict(value: object) -> JsonDict | None:
    return cast(JsonDict, value) if isinstance(value, dict) else None


def _raw(value: dict[str, Any]) -> JsonDict:
    return cast(JsonDict, dict(value))


def _string_or_first(value: object) -> str | None:
    if isinstance(value, list):
        return next((_string(item) for item in value if _string(item)), None)
    return _string(value)


def _posting_url(token: str, remote_id: str, *values: object) -> str:
    return (
        _string(first_present(*values))
        or f"https://apply.workable.com/{token}/j/{remote_id}"
    )
