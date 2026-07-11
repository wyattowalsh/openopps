from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

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
from openopps.providers.base import ProviderRouteMatch
from openopps.providers.boards.tokens import workable_token_from_url
from openopps.providers.normalize import (
    salary_components,
    salary_display,
    string as _string,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id

__all__ = ["WorkableProvider", "workable_token", "workable_token_from_url"]


_WORKABLE_RATE_LIMITER = AsyncSlidingWindowRateLimiter(limit=10, window_seconds=10.0)
_WORKABLE_LISTING_CACHE_NAMESPACE = "route_probe"


async def wait_for_workable_rate_limit() -> None:
    await _WORKABLE_RATE_LIMITER.wait()


class WorkableProvider:
    provider_id = "workable"
    provider_label = "Workable"
    provider_description = "Public Workable hosted-board JSON endpoint."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

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
    ) -> list[JobRecord]:
        token = workable_token(route)
        if not token:
            return []
        data = await self._fetch_jobs(client, token)
        jobs = data.get("results") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("Workable jobs endpoint returned invalid JSON")
        listings = [item for item in jobs if isinstance(item, dict)]
        semaphore = asyncio.Semaphore(self.settings.board_concurrency)

        async def detail_for(listing: dict[str, Any]) -> dict[str, Any]:
            shortcode = _string(listing.get("shortcode"))
            if not shortcode:
                return {}
            async with semaphore:
                return await self._fetch_detail(client, token, shortcode)

        details = await asyncio.gather(*(detail_for(listing) for listing in listings))
        return [
            self._normalize(board, token, listing, detail)
            for listing, detail in zip(listings, details, strict=False)
        ]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        token = workable_token(route)
        if not token:
            return 0
        data = await self._fetch_jobs(client, token)
        total = data.get("total") if isinstance(data, dict) else None
        if isinstance(total, int):
            return total
        jobs = data.get("results") if isinstance(data, dict) else None
        if isinstance(jobs, list):
            return len(jobs)
        raise ValueError("Workable jobs endpoint returned invalid JSON")

    async def _fetch_jobs(
        self, client: httpx.AsyncClient, token: str
    ) -> dict[str, Any]:
        await wait_for_workable_rate_limit()
        data = await self._request_json(
            client,
            "POST",
            f"https://apply.workable.com/api/v3/accounts/{token}/jobs",
            json={},
            cache_namespace=_WORKABLE_LISTING_CACHE_NAMESPACE,
            cache_identity={"provider": self.provider_id, "route": token},
        )
        if not isinstance(data, dict):
            raise ValueError("Workable jobs endpoint returned invalid JSON")
        return data

    async def _fetch_detail(
        self, client: httpx.AsyncClient, token: str, shortcode: str | None
    ) -> dict[str, Any]:
        if not shortcode:
            return {}
        await wait_for_workable_rate_limit()
        data = await self._request_json(
            client,
            "GET",
            f"https://apply.workable.com/api/v2/accounts/{token}/jobs/{shortcode}",
        )
        if not isinstance(data, dict):
            raise ValueError("Workable job detail endpoint returned invalid JSON")
        return data

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
