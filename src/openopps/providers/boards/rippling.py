from __future__ import annotations

import asyncio
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JsonDict,
    JobRecord,
    normalize_remote_level,
    strip_html,
    validate_provider_host,
    validate_public_https_url,
)
from openopps.providers.base import ProviderRouteMatch
from openopps.providers.normalize import (
    salary_components,
    salary_display,
    string as _string,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class RipplingProvider:
    provider_id = "rippling"
    provider_label = "Rippling"
    provider_description = "Public Rippling ATS board JSON endpoints."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        parsed = urlparse(url)
        try:
            host = validate_provider_host(parsed.hostname or "", "rippling.com")
        except ValueError:
            return None
        if host != "ats.rippling.com":
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if parts[:3] == ["api", "v2", "board"] and len(parts) > 3:
            return ProviderRouteMatch(token=parts[3], host=host, tenant=parts[3])
        if len(parts) >= 2 and parts[1] == "jobs":
            return ProviderRouteMatch(token=parts[0], host=host, tenant=parts[0])
        return None

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        slug = rippling_slug(route)
        if not slug:
            return []
        listings = await self._fetch_listings(client, slug)
        semaphore = asyncio.Semaphore(self.settings.board_concurrency)

        async def detail_for(listing: dict[str, Any]) -> dict[str, Any]:
            job_id = _string(first_present(listing.get("id"), listing.get("uuid")))
            if not job_id:
                return {}
            async with semaphore:
                return await self._fetch_detail(client, slug, job_id)

        details = await asyncio.gather(*(detail_for(listing) for listing in listings))
        return [
            self._normalize(board, slug, listing, detail)
            for listing, detail in zip(listings, details, strict=False)
        ]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        slug = rippling_slug(route)
        if not slug:
            return 0
        data = await self._request_json(
            client,
            "GET",
            f"https://ats.rippling.com/api/v2/board/{slug}/jobs",
            params={"page": 0, "pageSize": 1},
        )
        if not isinstance(data, dict):
            raise ValueError("Rippling board jobs endpoint returned invalid JSON")
        total = data.get("totalItems")
        if isinstance(total, int):
            return total
        items = data.get("items")
        if isinstance(items, list):
            return len(items)
        raise ValueError("Rippling board jobs endpoint returned invalid JSON")

    async def _fetch_listings(
        self, client: httpx.AsyncClient, slug: str
    ) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        page = 0
        page_size = 100
        total_pages: int | None = None
        while total_pages is None or page < total_pages:
            data = await self._request_json(
                client,
                "GET",
                f"https://ats.rippling.com/api/v2/board/{slug}/jobs",
                params={"page": page, "pageSize": page_size},
            )
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("Rippling board jobs endpoint returned invalid JSON")
            listings.extend(item for item in data["items"] if isinstance(item, dict))
            total_pages = int(data.get("totalPages") or page + 1)
            if not data["items"]:
                break
            page += 1
        return listings

    async def _fetch_detail(
        self, client: httpx.AsyncClient, slug: str, job_id: str
    ) -> dict[str, Any]:
        data = await self._request_json(
            client,
            "GET",
            f"https://ats.rippling.com/api/v2/board/{slug}/jobs/{job_id}",
        )
        if not isinstance(data, dict):
            raise ValueError("Rippling board detail endpoint returned invalid JSON")
        return data

    def _normalize(
        self,
        board: BoardRecord,
        slug: str,
        listing: dict[str, Any],
        detail: dict[str, Any],
    ) -> JobRecord:
        merged = listing | detail
        remote_id = str(
            first_present(
                merged.get("uuid"),
                merged.get("id"),
                merged.get("url"),
                merged.get("name"),
            )
        )
        locations = _locations(merged)
        description_html = _description_html(merged.get("description"))
        employment_type = _employment_type(merged.get("employmentType"))
        department = _name(merged.get("department"))
        compensation = _pay_range(merged.get("payRangeDetails"))
        salary_min, salary_max, salary_currency = salary_components(
            compensation,
            min_keys=("min", "minValue"),
            max_keys=("max", "maxValue"),
        )
        posting_url = (
            _string(merged.get("url"))
            or f"https://ats.rippling.com/{slug}/jobs/{remote_id}"
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(merged.get("name")) or remote_id,
            locations=locations,
            department=department,
            workplace_type=_workplace_type(merged),
            company=_string(merged.get("companyName")) or board.name,
            employment_type=employment_type,
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(_workplace_type(merged), locations),
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            posting_url=posting_url,
            apply_url=posting_url,
            posted_at=_string(merged.get("createdOn")),
            raw_listing=_raw(listing),
            raw_detail=_raw(detail),
        )


def rippling_slug(route: BoardProviderRecord) -> str | None:
    if route.tenant:
        return route.tenant.strip()
    if route.token:
        return route.token.strip()
    if not route.board_url:
        return None
    parsed = urlparse(route.board_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts[:3] == ["api", "v2", "board"] and len(parts) > 3:
        return parts[3]
    if len(parts) >= 2 and parts[1] == "jobs":
        return parts[0]
    return None


def _locations(value: dict[str, Any]) -> list[str]:
    raw_locations = value.get("locations") or value.get("workLocations")
    locations: list[str] = []
    if isinstance(raw_locations, list):
        for location in raw_locations:
            if isinstance(location, dict):
                locations.append(_location_label(location))
            elif isinstance(location, str):
                locations.append(location)
    return [location for location in dict.fromkeys(locations) if location]


def _location_label(location: dict[str, Any]) -> str:
    return (
        ", ".join(
            part
            for part in (
                _string(location.get("city")),
                _string(location.get("state") or location.get("stateCode")),
                _string(location.get("country") or location.get("countryCode")),
            )
            if part
        )
        or _string(location.get("name"))
        or ""
    )


def _description_html(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [
            part for part in value.values() if isinstance(part, str) and part.strip()
        ]
        return "\n".join(parts) or None
    return None


def _employment_type(value: object) -> str | None:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        return _string(data.get("label") or data.get("id"))
    return _string(value)


def _workplace_type(value: dict[str, Any]) -> str | None:
    for location in value.get("locations") or []:
        if isinstance(location, dict) and _string(location.get("workplaceType")):
            return _string(location.get("workplaceType"))
    return None


def _name(value: object) -> str | None:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        return _string(data.get("name"))
    return _string(value)


def _pay_range(value: object) -> JsonDict | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return cast(JsonDict, dict(value[0]))
    if isinstance(value, dict):
        return cast(JsonDict, value)
    return None


def _raw(value: dict[str, Any]) -> JsonDict:
    return cast(JsonDict, dict(value))
