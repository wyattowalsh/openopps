from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx

from openopps.http import retrying_json_request, retrying_text_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    RemoteLevel,
    validate_public_https_url,
)
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    DetailCoverageEvidence,
    ListingIdentityMode,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    optional_pull_attr,
    optional_pull_capabilities,
)
from openopps.providers.boards.url_targets import (
    decode_url_identity_segment,
    synthetic_url_pull_board,
)
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

ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")

CONSIDER_JOBS_PAGE_SIZE = 100
CONSIDER_JOBS_MAX_PAGES = 100


class ConsiderJobsProvider:
    provider_id = "consider_jobs"
    provider_label = "Consider Jobs"
    provider_description = "Public Consider company job-board API."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        board_scan_get_supported=True,
        interface_stability="best_effort",
    )

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

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        if len(url.strip()) > 2_000:
            return None
        try:
            route = detect_consider_company_route(url)
            if route is not None:
                if len(route.token) > 500:
                    return None
                return ProviderUrlTarget(
                    provider_id=ConsiderJobsProvider.provider_id,
                    target_kind=ProviderTargetKind.BOARD,
                    url=url,
                    board_identity=route.token,
                    route=ProviderRouteIdentity(
                        token=route.token,
                        host="consider.com",
                    ),
                )
            return _parse_consider_posting_target(url)
        except ValueError:
            return None

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        token = quote(slug.strip(), safe="-._~")
        return (f"https://consider.com/boards/co/{token}",) if token else ()

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        route = _require_consider_board_target(target)
        kernel = await self._list_public_membership(
            client,
            route,
            identity_mode="pull",
            include_unlisted=include_unlisted,
        )
        return kernel.to_provider_list_result(target)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        consider_route = consider_jobs_route(board, route)
        kernel = await self._list_public_membership(
            client,
            consider_route,
            identity_mode="ingest",
            include_unlisted=False,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        route: ConsiderRoute,
        *,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
    ) -> BoardListingKernelResult:
        del identity_mode
        if include_unlisted:
            raise ValueError("Consider Jobs does not support unlisted enumeration")
        jobs, pages_fetched = await self._fetch_all_with_evidence(client, route)
        native_board = _pull_board(route.token)
        postings = tuple(
            ListingPosting(
                job=(job := self._normalize(native_board, posting)),
                listing=job.raw_listing,
                detail=None,
            )
            for posting in jobs
        )
        return BoardListingKernelResult(
            native_board_identity=route.token,
            postings=postings,
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=pages_fetched,
                observed_count=len(postings),
                advertised_count=None,
            ),
            detail_coverage=DetailCoverageEvidence(),
        )

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
        postings, _pages_fetched = await self._fetch_all_with_evidence(client, route)
        return postings

    async def _fetch_all_with_evidence(
        self,
        client: httpx.AsyncClient,
        route: ConsiderRoute,
    ) -> tuple[list[ConsiderJob], int]:
        postings: list[ConsiderJob] = []
        remote_ids: set[str] = set()
        seen_sequences: set[str] = set()
        sequence: str | None = None
        pages_fetched = 0

        while True:
            if pages_fetched >= CONSIDER_JOBS_MAX_PAGES:
                raise ValueError("Consider jobs endpoint exceeded the page limit")
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
                cache_identity={"role": "membership_page"},
            )
            pages_fetched += 1
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
                cache_identity={"role": "membership_terminal"},
            )
            validate_consider_empty_board_html(html)
        return postings, pages_fetched

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


def _parse_consider_posting_target(url: str) -> ProviderUrlTarget | None:
    try:
        validate_public_https_url(url)
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.query or parsed.fragment or parsed.params or parsed.port is not None:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != "consider.com":
        return None
    path = parsed.path
    if path.endswith("/") and path != "/":
        path = path[:-1]
    if not path.startswith("/"):
        return None
    raw = path[1:]
    if not raw or any(not segment for segment in raw.split("/")):
        return None
    segments = raw.split("/")
    if len(segments) != 4 or segments[:2] != ["boards", "co"]:
        return None
    try:
        route = parse_consider_route(f"https://consider.com/boards/co/{segments[2]}")
    except ValueError:
        return None
    if route.mode != ConsiderRouteMode.COMPANY_JOBS or len(route.token) > 500:
        return None
    posting_identity = decode_url_identity_segment(segments[3])
    if posting_identity is None:
        return None
    return ProviderUrlTarget(
        provider_id=ConsiderJobsProvider.provider_id,
        target_kind=ProviderTargetKind.POSTING,
        url=url,
        board_identity=route.token,
        posting_identity=posting_identity,
        route=ProviderRouteIdentity(token=route.token, host="consider.com"),
    )


def _require_consider_board_target(target: ProviderUrlTarget) -> ConsiderRoute:
    if target.provider_id != ConsiderJobsProvider.provider_id:
        raise ValueError("Consider Jobs pull target has the wrong provider")
    if target.target_kind != ProviderTargetKind.BOARD:
        raise ValueError("Consider Jobs list requires a board target")
    token = target.route.token
    if (
        not token
        or token != target.board_identity
        or target.route.host != "consider.com"
    ):
        raise ValueError("Consider Jobs pull target has inconsistent board identity")
    route = parse_consider_route(
        f"https://consider.com/boards/co/{quote(token, safe='-._~')}"
    )
    if route.mode != ConsiderRouteMode.COMPANY_JOBS:
        raise ValueError("Consider Jobs pull target is not a company board")
    return route


def _pull_board(token: str) -> BoardRecord:
    return synthetic_url_pull_board(token, remote_slug=token)
