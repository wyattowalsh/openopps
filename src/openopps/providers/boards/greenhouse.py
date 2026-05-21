from __future__ import annotations

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    GreenhouseJobsResponse,
    GreenhouseJobPosting,
    JobRecord,
    normalize_remote_level,
    strip_html,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class GreenhouseProvider:
    provider_id = "greenhouse"

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

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
            posting_url=posting.absolute_url,
            apply_url=posting.absolute_url,
            updated_at=posting.updated_at,
            raw_listing=posting.as_raw_payload(),
        )


def _locations(posting: GreenhouseJobPosting) -> list[str]:
    locations: list[str] = []
    if posting.location and posting.location.name:
        locations.append(posting.location.name)
    locations.extend(office.name for office in posting.offices if office.name)
    return list(dict.fromkeys(locations))


def _token_from_route(route: BoardProviderRecord) -> str | None:
    token = route.token
    if not token and route.board_url:
        token = route.board_url.rstrip("/").split("/")[-1]
    return token
