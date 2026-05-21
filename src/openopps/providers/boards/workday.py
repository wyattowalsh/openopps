from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderNamedValue,
    WorkdayJobDetail,
    WorkdayJobPosting,
    WorkdayJobsResponse,
    normalize_remote_level,
    strip_html,
)
from openopps.settings import OpenOppsSettings
from openopps.url_validation import validate_provider_host, validate_public_https_url
from openopps.utils import first_present, stable_id


_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")


@dataclass(frozen=True)
class WorkdayRoute:
    host: str
    tenant: str
    site: str


def parse_workday_board_url(url: str) -> WorkdayRoute:
    validate_public_https_url(url)
    parsed = urlparse(url)
    host = validate_provider_host(parsed.hostname or "", "myworkdayjobs.com")
    if not host:
        raise ValueError(f"Workday URL is missing host: {url}")
    tenant = host.split(".", 1)[0]
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        raise ValueError(f"Workday URL is missing site path: {url}")
    site_index = 1 if _LOCALE_RE.match(path_parts[0]) and len(path_parts) > 1 else 0
    site = path_parts[site_index]
    return WorkdayRoute(host=host, tenant=tenant, site=site)


class WorkdayProvider:
    provider_id = "workday"

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        workday = self._route(route)
        if not workday:
            return []
        listings = await self._fetch_listings(client, workday)
        semaphore = asyncio.Semaphore(self.settings.workday_concurrency)

        async def detail_for(listing: WorkdayJobPosting) -> WorkdayJobDetail:
            external_path = listing.external_path
            if not external_path:
                return WorkdayJobDetail()
            async with semaphore:
                return await self._fetch_detail(client, workday, external_path)

        details = await asyncio.gather(*(detail_for(listing) for listing in listings))
        return [
            self._normalize(board, workday, listing, detail)
            for listing, detail in zip(listings, details, strict=False)
        ]

    def _route(self, route: BoardProviderRecord) -> WorkdayRoute | None:
        if route.host and route.tenant and route.site:
            return WorkdayRoute(
                host=validate_provider_host(route.host, "myworkdayjobs.com"),
                tenant=route.tenant,
                site=route.site,
            )
        if route.board_url:
            return parse_workday_board_url(route.board_url)
        return None

    async def _fetch_listings(
        self, client: httpx.AsyncClient, route: WorkdayRoute
    ) -> list[WorkdayJobPosting]:
        url = f"https://{route.host}/wday/cxs/{route.tenant}/{route.site}/jobs"
        listings: list[WorkdayJobPosting] = []
        offset = 0
        limit = 20
        total: int | None = None
        while total is None or offset < total:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }
            data = await self._request_json(
                client,
                "POST",
                url,
                json=payload,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "referer": f"https://{route.host}/{route.site}",
                },
            )
            if not isinstance(data, dict):
                raise ValueError("Workday listings endpoint returned invalid JSON")
            response = WorkdayJobsResponse.model_validate(data)
            total = response.total or len(response.job_postings)
            listings.extend(response.job_postings)
            if not response.job_postings:
                break
            offset += limit
        return listings

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        workday = self._route(route)
        if not workday:
            return 0
        url = f"https://{workday.host}/wday/cxs/{workday.tenant}/{workday.site}/jobs"
        data = await self._request_json(
            client,
            "POST",
            url,
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "referer": f"https://{workday.host}/{workday.site}",
            },
        )
        if not isinstance(data, dict):
            raise ValueError("Workday listings endpoint returned invalid JSON")
        response = WorkdayJobsResponse.model_validate(data)
        return int(response.total or len(response.job_postings))

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        route: WorkdayRoute,
        external_path: str,
    ) -> WorkdayJobDetail:
        url = f"https://{route.host}/wday/cxs/{route.tenant}/{route.site}/job/{external_path}"
        data = await self._request_json(
            client,
            "GET",
            url,
            headers={
                "accept": "application/json",
                "referer": f"https://{route.host}/{route.site}/job/{external_path}",
            },
        )
        if not isinstance(data, dict):
            raise ValueError("Workday detail endpoint returned invalid JSON")
        return WorkdayJobDetail.model_validate(data)

    def _normalize(
        self,
        board: BoardRecord,
        route: WorkdayRoute,
        listing: WorkdayJobPosting,
        detail: WorkdayJobDetail,
    ) -> JobRecord:
        remote_id = str(
            first_present(
                listing.id,
                listing.external_path,
                listing.title,
            )
        )
        title = first_present(listing.title, detail.title, remote_id)
        locations = []
        location = first_present(
            listing.locations_text, listing.location, detail.location
        )
        location_label = _location_label(location)
        if location_label:
            locations.append(location_label)
        posting_url = None
        external_path = listing.external_path
        if external_path:
            posting_url = f"https://{route.host}/{route.site}/job/{external_path}"
        description_html = detail.job_description
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=str(title),
            locations=locations,
            department=first_present(listing.job_family, detail.job_family),
            workplace_type=first_present(
                detail.time_type,
                detail.worker_sub_type,
            ),
            company=board.name,
            employment_type=detail.time_type,
            description=detail.description or strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(locations),
            posting_url=posting_url,
            posted_at=first_present(listing.posted_on, detail.posted_on),
            raw_listing=listing.as_raw_payload(),
            raw_detail=detail.as_raw_payload(),
        )


def _location_label(value: ProviderNamedValue | str | None) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, ProviderNamedValue):
        return value.display_name or value.name
    return None
