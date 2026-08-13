from __future__ import annotations

from typing import cast
from urllib.parse import quote, urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    GreenhouseJobsResponse,
    GreenhouseJobPosting,
    JsonDict,
    JobRecord,
    normalize_public_website_url,
    normalize_remote_level,
    strip_html,
    host_matches,
    validate_public_https_url,
)
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.boards.tokens import greenhouse_token_from_url
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
        token = _token_from_url(url)
        return ProviderRouteMatch(token=token) if token else None

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        token = _token_from_route(route)
        if not token:
            raise ValueError("Greenhouse route is missing a public board token")
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        data = await self._request_json(client, "GET", url, params={"content": "true"})
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        response = GreenhouseJobsResponse.model_validate(data)
        return JobFetchResult(
            jobs=[self._normalize(board, posting, token) for posting in response.jobs],
            authoritative=True,
        )

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
        self, board: BoardRecord, posting: GreenhouseJobPosting, token: str
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
        posting_url = _greenhouse_public_url(
            posting.absolute_url,
            token=token,
            public_job_id=posting.id,
        )
        departments = [
            entry.model_dump(mode="python", by_alias=True, exclude_none=True)
            for entry in posting.departments
        ]
        offices = [
            entry.model_dump(mode="python", by_alias=True, exclude_none=True)
            for entry in posting.offices
        ]
        provider_extras = cast(
            JsonDict,
            {
                "greenhouse": {
                    key: value
                    for key, value in {
                        "requisitionId": posting.requisition_id,
                        "language": posting.language,
                        "metadata": posting.metadata or None,
                        "departments": departments or None,
                        "offices": offices or None,
                    }.items()
                    if value not in (None, [], {})
                }
            },
        )
        posting_kind = "prospect" if posting.internal_job_id is None else "standard"
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
            posting_kind=posting_kind,
            provider_extras=provider_extras,
            raw_listing=posting.as_raw_payload(),
        )


def _locations(posting: GreenhouseJobPosting) -> list[str]:
    locations: list[str] = []
    if posting.location and posting.location.name:
        locations.append(posting.location.name)
    locations.extend(office.name for office in posting.offices if office.name)
    return list(dict.fromkeys(locations))


def _greenhouse_public_url(
    value: object,
    *,
    token: str | None = None,
    public_job_id: object = None,
) -> str | None:
    url = normalize_public_website_url(value)
    if url:
        parsed = urlparse(url)
        return url if host_matches(parsed.hostname, "greenhouse.io") else None
    if isinstance(value, str) and value.strip():
        return None
    if token and public_job_id is not None:
        job_id = str(public_job_id).strip()
        if job_id:
            fallback = (
                "https://boards.greenhouse.io/"
                f"{quote(token.strip(), safe='')}/jobs/{quote(job_id, safe='')}"
            )
            parsed = urlparse(fallback)
            if host_matches(parsed.hostname, "greenhouse.io"):
                return fallback
    return None


def _token_from_route(route: BoardProviderRecord) -> str | None:
    token = route.token
    if token:
        return token.strip()
    if route.board_url:
        return _token_from_url(route.board_url)
    return None


def _token_from_url(url: str) -> str | None:
    return greenhouse_token_from_url(url)
