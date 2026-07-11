from __future__ import annotations

from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    AshbyJobBoardResponse,
    AshbyJobPosting,
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    normalize_remote_level,
    strip_html,
    validate_public_https_url,
)
from openopps.providers.base import ProviderRouteMatch
from openopps.providers.normalize import salary_components, salary_display
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class AshbyProvider:
    provider_id = "ashbyhq"
    provider_label = "Ashby"
    provider_description = "Public Ashby job posting API."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() != "jobs.ashbyhq.com":
            return None
        path_parts = [part for part in parsed.path.split("/") if part]
        return ProviderRouteMatch(token=path_parts[0] if path_parts else None)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        token = ashby_token(route)
        if not token:
            return []
        data = await self._request_json(
            client,
            "GET",
            f"https://api.ashbyhq.com/posting-api/job-board/{token}",
            params={"includeCompensation": "true"},
        )
        if not isinstance(data, dict):
            raise ValueError("Ashby posting API returned invalid JSON")
        response = AshbyJobBoardResponse.model_validate(data)
        return [
            self._normalize(board, posting)
            for posting in response.jobs
            if posting.is_listed is not False
        ]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        token = ashby_token(route)
        if not token:
            return 0
        data = await self._request_json(
            client,
            "GET",
            f"https://api.ashbyhq.com/posting-api/job-board/{token}",
            params={"includeCompensation": "false"},
        )
        if not isinstance(data, dict):
            raise ValueError("Ashby posting API returned invalid JSON")
        response = AshbyJobBoardResponse.model_validate(data)
        return len([job for job in response.jobs if job.is_listed is not False])

    def _normalize(self, board: BoardRecord, posting: AshbyJobPosting) -> JobRecord:
        remote_id = str(
            first_present(
                posting.id,
                posting.job_url,
                posting.title,
            )
        )
        locations = _locations(posting)
        salary_min, salary_max, salary_currency = salary_components(
            posting.compensation,
            min_keys=("minValue", "min"),
            max_keys=("maxValue", "max"),
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=posting.title or remote_id,
            locations=locations,
            department=posting.department,
            team=posting.team,
            workplace_type=posting.workplace_type,
            company=board.name,
            employment_type=posting.employment_type,
            description=posting.description_plain
            or strip_html(posting.description_html),
            description_html=posting.description_html,
            remote=normalize_remote_level(
                posting.workplace_type,
                locations,
                is_remote=posting.is_remote,
            ),
            compensation=posting.compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            posting_url=posting.job_url,
            apply_url=posting.apply_url,
            posted_at=posting.published_at,
            raw_listing=posting.as_raw_payload(),
        )


def ashby_token(route: BoardProviderRecord) -> str | None:
    if route.token:
        return route.token.strip()
    if route.board_url:
        parsed = urlparse(route.board_url)
        parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.netloc.lower() == "api.ashbyhq.com"
            and parts[:2] == ["posting-api", "job-board"]
            and len(parts) > 2
        ):
            return parts[2]
        if parts:
            return parts[0]
    return None


def _locations(posting: AshbyJobPosting) -> list[str]:
    values: list[str] = []
    if posting.location:
        values.append(posting.location)
    for secondary in posting.secondary_locations:
        if secondary.location:
            values.append(secondary.location)
    return list(dict.fromkeys(values))



