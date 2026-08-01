from __future__ import annotations

import httpx

from openopps.http import retrying_json_request, retrying_text_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    RemoteLevel,
)
from openopps.providers.base import ProviderRouteMatch
from openopps.providers.consider import (
    ConsiderJob,
    ConsiderJobsResponse,
    ConsiderRoute,
    ConsiderRouteMode,
    consider_next_sequence,
    consider_search_payload,
    detect_consider_company_route,
    parse_consider_route,
    raise_for_consider_errors,
    safe_consider_job_url,
    validate_consider_empty_board_html,
)
from openopps.providers.normalize import salary_display
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id


CONSIDER_JOBS_PAGE_SIZE = 100


class ConsiderJobsProvider:
    provider_id = "consider_jobs"
    provider_label = "Consider Jobs"
    provider_description = "Public Consider company job-board API."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)
        self._request_text = retrying_text_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        route = detect_consider_company_route(url)
        if route is None:
            return None
        return ProviderRouteMatch(token=route.token, host="consider.com")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> list[JobRecord]:
        consider_route = consider_jobs_route(board, route)
        postings = await self._fetch_all(client, consider_route)
        return [self._normalize(board, posting) for posting in postings]

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        consider_route = consider_jobs_route(board, route)
        return len(await self._fetch_all(client, consider_route))

    async def _fetch_all(
        self,
        client: httpx.AsyncClient,
        route: ConsiderRoute,
    ) -> list[ConsiderJob]:
        postings: list[ConsiderJob] = []
        remote_ids: set[str] = set()
        seen_sequences: set[str] = set()
        sequence: str | None = None

        while True:
            response = await self._request_json(
                client,
                "POST",
                route.endpoint,
                json=consider_search_payload(
                    route,
                    page_size=CONSIDER_JOBS_PAGE_SIZE,
                    sequence=sequence,
                ),
                headers={
                    "content-type": "application/json",
                    "origin": route.origin,
                    "referer": route.board_url,
                },
            )
            if not isinstance(response, dict):
                raise ValueError("Consider jobs endpoint returned a non-object payload")
            page = ConsiderJobsResponse.model_validate(response)
            raise_for_consider_errors(page.errors, endpoint="jobs")
            next_sequence = consider_next_sequence(page.meta)
            if next_sequence is not None and not page.jobs:
                raise ValueError(
                    "Consider jobs endpoint returned an empty page with continuation"
                )
            if next_sequence is not None and (
                next_sequence == sequence or next_sequence in seen_sequences
            ):
                raise ValueError("Consider jobs endpoint repeated a sequence cursor")
            for posting in page.jobs:
                if posting.job_id in remote_ids:
                    raise ValueError(
                        "Consider jobs endpoint repeated a job across pages"
                    )
                remote_ids.add(posting.job_id)
                postings.append(posting)
            if next_sequence is None:
                break
            seen_sequences.add(next_sequence)
            sequence = next_sequence

        if not postings:
            html = await self._request_text(
                client,
                "GET",
                route.board_url,
                headers={"accept": "text/html,application/xhtml+xml"},
            )
            validate_consider_empty_board_html(html)
        return postings

    def _normalize(self, board: BoardRecord, posting: ConsiderJob) -> JobRecord:
        salary_min = posting.salary.min_value if posting.salary else None
        salary_max = posting.salary.max_value if posting.salary else None
        salary_currency = None
        if posting.salary and posting.salary.currency:
            salary_currency = (
                posting.salary.currency.value or posting.salary.currency.label
            )
        workplace_type = (
            "Hybrid" if posting.hybrid else "Remote" if posting.remote else None
        )
        remote = (
            RemoteLevel.HYBRID.value
            if posting.hybrid
            else RemoteLevel.FULL.value
            if posting.remote
            else None
        )
        department = _first_label(posting.departments) or _first_label(
            posting.job_functions
        )
        compensation = (
            posting.salary.as_raw_payload() if posting.salary is not None else None
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, posting.job_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=posting.job_id,
            title=posting.title,
            locations=posting.locations,
            department=department,
            workplace_type=workplace_type,
            company=posting.company_name or board.name,
            remote=remote,
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            posting_url=safe_consider_job_url(posting.url),
            apply_url=safe_consider_job_url(posting.apply_url),
            posted_at=posting.timestamp,
            raw_listing=posting.as_raw_payload(),
        )


def consider_jobs_route(
    board: BoardRecord,
    route: BoardProviderRecord,
) -> ConsiderRoute:
    if route.board_url:
        parsed = parse_consider_route(route.board_url)
        if parsed.mode != ConsiderRouteMode.COMPANY_JOBS:
            raise ValueError("Consider jobs route must use a company board URL")
        return parsed
    token = route.token or board.remote_slug or board.remote_id
    parsed = parse_consider_route(f"https://consider.com/boards/co/{token}")
    if parsed.mode != ConsiderRouteMode.COMPANY_JOBS:
        raise ValueError("Consider jobs route must use a company board URL")
    return parsed


def consider_jobs_token(route: BoardProviderRecord) -> str | None:
    if route.board_url:
        detected = detect_consider_company_route(route.board_url)
        return detected.token if detected else None
    if route.token:
        detected = detect_consider_company_route(
            f"https://consider.com/boards/co/{route.token}"
        )
        return detected.token if detected else None
    return None


def _first_label(values: list) -> str | None:
    for value in values:
        if value.label:
            return value.label
        if value.value:
            return value.value
    return None
