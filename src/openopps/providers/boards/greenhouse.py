from __future__ import annotations

from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    GreenhouseJobsResponse,
    GreenhouseJobPosting,
    JobRecord,
    normalize_public_website_url,
    normalize_remote_level,
    strip_html,
    host_matches,
    validate_public_https_url,
)
from openopps.providers.base import ProviderRouteMatch
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class GreenhouseProvider:
    provider_id = "greenhouse"
    provider_label = "Greenhouse"
    provider_description = "Public Greenhouse job board API."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host_matches(host, "greenhouse.io"):
            return None
        path_parts = [part for part in parsed.path.split("/") if part]
        return ProviderRouteMatch(token=path_parts[0] if path_parts else None)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        token = _token_from_route(route)
        if not token:
            return []
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        data = await self._request_json(client, "GET", url, params={"content": "true"})
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        response = GreenhouseJobsResponse.model_validate(data)
        return [self._normalize(board, posting) for posting in response.jobs]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        token = _token_from_route(route)
        if not token:
            return 0
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        data = await self._request_json(client, "GET", url, params={"content": "false"})
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        response = GreenhouseJobsResponse.model_validate(data)
        return len(response.jobs)

    def _normalize(
        self, board: BoardRecord, posting: GreenhouseJobPosting
    ) -> JobRecord:
        remote_id = str(
            first_present(
                posting.id,
                posting.internal_job_id,
                posting.absolute_url,
            )
        )
        locations = _locations(posting)
        department = posting.departments[0].name if posting.departments else None
        posting_url = _greenhouse_public_url(posting.absolute_url)
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=posting.title or remote_id,
            locations=locations,
            department=department,
            company=board.name,
            description=strip_html(posting.content),
            description_html=posting.content,
            remote=normalize_remote_level(locations),
            posting_url=posting_url,
            apply_url=posting_url,
            updated_at=posting.updated_at,
            raw_listing=posting.as_raw_payload(),
        )


def _locations(posting: GreenhouseJobPosting) -> list[str]:
    locations: list[str] = []
    if posting.location and posting.location.name:
        locations.append(posting.location.name)
    locations.extend(office.name for office in posting.offices if office.name)
    return list(dict.fromkeys(locations))


def _greenhouse_public_url(value: object) -> str | None:
    url = normalize_public_website_url(value)
    if not url:
        return None
    parsed = urlparse(url)
    return url if host_matches(parsed.hostname, "greenhouse.io") else None


def _token_from_route(route: BoardProviderRecord) -> str | None:
    token = route.token
    if not token and route.board_url:
        token = route.board_url.rstrip("/").split("/")[-1]
    return token
