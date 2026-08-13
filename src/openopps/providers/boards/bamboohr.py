from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.normalize import (
    salary_components,
    salary_display,
    string as _string,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


@dataclass(frozen=True)
class BambooHRRoute:
    host: str
    tenant: str


class BambooHRProvider:
    provider_id = "bamboohr"
    provider_label = "BambooHR"
    provider_description = "Public BambooHR careers board JSON endpoints."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        try:
            route = parse_bamboohr_board_url(url)
        except ValueError:
            return None
        return ProviderRouteMatch(
            token=route.tenant, host=route.host, tenant=route.tenant
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        bamboohr = bamboohr_route(route)
        if not bamboohr:
            return JobFetchResult(jobs=[], authoritative=False)
        listings = await self._fetch_listings(client, bamboohr)
        semaphore = asyncio.Semaphore(self.settings.board_concurrency)

        async def detail_for(listing: dict[str, Any]) -> dict[str, Any]:
            raw_job_id = listing.get("id")
            job_id = str(raw_job_id) if raw_job_id is not None else None
            if not job_id:
                return {}
            async with semaphore:
                return await self._fetch_detail(client, bamboohr, job_id)

        details = await asyncio.gather(*(detail_for(listing) for listing in listings))
        return JobFetchResult(
            jobs=[
                self._normalize(board, bamboohr, listing, detail)
                for listing, detail in zip(listings, details, strict=True)
            ],
            authoritative=True,
        )

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        bamboohr = bamboohr_route(route)
        if not bamboohr:
            return 0
        data = await self._request_json(
            client, "GET", f"https://{bamboohr.host}/careers/list"
        )
        if not isinstance(data, dict):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        meta = data.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("totalCount"), int):
            return int(meta["totalCount"])
        result = data.get("result")
        if not isinstance(result, list):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        return len(result)

    async def _fetch_listings(
        self, client: httpx.AsyncClient, route: BambooHRRoute
    ) -> list[dict[str, Any]]:
        data = await self._request_json(
            client, "GET", f"https://{route.host}/careers/list"
        )
        if not isinstance(data, dict):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        result = data.get("result")
        if not isinstance(result, list):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        if any(not isinstance(item, dict) for item in result):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        listings = cast(list[dict[str, Any]], result)
        meta = data.get("meta")
        total = meta.get("totalCount") if isinstance(meta, dict) else None
        if total is not None:
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise ValueError("BambooHR totalCount must be a non-negative integer")
            if len(listings) != total:
                raise ValueError("BambooHR advertised total does not match jobs")
        listing_ids = [
            str(first_present(item.get("id"), item.get("jobOpeningName")))
            for item in listings
        ]
        if len(listing_ids) != len(set(listing_ids)):
            raise ValueError("BambooHR careers list returned duplicate jobs")
        return listings

    async def _fetch_detail(
        self, client: httpx.AsyncClient, route: BambooHRRoute, job_id: str
    ) -> dict[str, Any]:
        data = await self._request_json(
            client, "GET", f"https://{route.host}/careers/{job_id}/detail"
        )
        result = data.get("result") if isinstance(data, dict) else None
        job_opening = result.get("jobOpening") if isinstance(result, dict) else None
        if not isinstance(job_opening, dict):
            raise ValueError("BambooHR careers detail endpoint returned invalid JSON")
        return job_opening

    def _normalize(
        self,
        board: BoardRecord,
        route: BambooHRRoute,
        listing: dict[str, Any],
        detail: dict[str, Any],
    ) -> JobRecord:
        remote_id = str(
            first_present(
                listing.get("id"), detail.get("id"), listing.get("jobOpeningName")
            )
        )
        merged = listing | detail
        description_html = _string(merged.get("description"))
        locations = _locations(merged)
        compensation = _json_dict(merged.get("compensation"))
        salary_min, salary_max, salary_currency = salary_components(
            compensation,
            min_keys=("minValue", "minimum"),
            max_keys=("maxValue", "maximum"),
        )
        posting_url = (
            _string(merged.get("jobOpeningShareUrl"))
            or f"https://{route.host}/careers/{remote_id}"
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(merged.get("jobOpeningName")) or remote_id,
            locations=locations,
            department=_string(merged.get("departmentLabel")),
            workplace_type=_string(merged.get("locationType")),
            company=board.name,
            employment_type=_string(merged.get("employmentStatusLabel")),
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(
                locations, is_remote=_bool(merged.get("isRemote"))
            ),
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            experience=_string(merged.get("minimumExperience")),
            posting_url=posting_url,
            apply_url=posting_url,
            posted_at=_string(merged.get("datePosted")),
            raw_listing=_raw(listing),
            raw_detail=_raw(detail),
        )


def parse_bamboohr_board_url(url: str) -> BambooHRRoute:
    validate_public_https_url(url)
    parsed = urlparse(url)
    host = validate_provider_host(parsed.hostname or "", "bamboohr.com")
    if not host.endswith(".bamboohr.com"):
        raise ValueError(f"BambooHR URL is missing tenant subdomain: {url}")
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] != "careers":
        raise ValueError(f"BambooHR URL is not a careers board URL: {url}")
    tenant = host.removesuffix(".bamboohr.com")
    return BambooHRRoute(host=host, tenant=tenant)


def bamboohr_route(route: BoardProviderRecord) -> BambooHRRoute | None:
    if route.host:
        host = validate_provider_host(route.host, "bamboohr.com")
        return BambooHRRoute(host=host, tenant=route.tenant or host.split(".", 1)[0])
    if route.board_url:
        return parse_bamboohr_board_url(route.board_url)
    if route.tenant:
        tenant = route.tenant.strip().lower()
        return BambooHRRoute(host=f"{tenant}.bamboohr.com", tenant=tenant)
    if route.token:
        token = route.token.strip().lower()
        return BambooHRRoute(host=f"{token}.bamboohr.com", tenant=token)
    return None


def _locations(value: dict[str, Any]) -> list[str]:
    location = (
        value.get("atsLocation")
        if isinstance(value.get("atsLocation"), dict)
        else value.get("location")
    )
    if not isinstance(location, dict):
        return []
    label = ", ".join(
        part
        for part in (
            _string(location.get("city")),
            _string(location.get("state") or location.get("province")),
            _string(location.get("country") or location.get("addressCountry")),
        )
        if part
    )
    return [label] if label else []


def _json_dict(value: object) -> JsonDict | None:
    return cast(JsonDict, value) if isinstance(value, dict) else None


def _raw(value: dict[str, Any]) -> JsonDict:
    return cast(JsonDict, dict(value))


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
