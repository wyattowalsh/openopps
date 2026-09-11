from __future__ import annotations

import re
from urllib.parse import quote, unquote_to_bytes, urlparse

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
from openopps.providers.boards.tokens import ashby_token_from_url
from openopps.providers.boards.url_targets import synthetic_url_pull_board
from openopps.providers.normalize import salary_components, salary_display
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id

ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")


class AshbyProvider:
    provider_id = "ashbyhq"
    provider_label = "Ashby"
    provider_description = "Public Ashby job posting API."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        board_scan_get_supported=True,
        exact_unlisted_get_supported=True,
        enumerate_unlisted_supported=True,
        interface_stability="documented",
    )

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

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        """Parse one exact hosted Ashby board/posting or posting-API board URL."""

        if len(url.strip()) > 2_000:
            return None
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            if parsed.fragment or parsed.params or parsed.port is not None:
                return None
            host = (parsed.hostname or "").lower()
            parts = _strict_url_parts(parsed.path)
        except ValueError:
            return None

        if host == "api.ashbyhq.com":
            if len(parts) != 3 or parts[:2] != ["posting-api", "job-board"]:
                return None
            if parsed.query not in {
                "",
                "includeCompensation=true",
                "includeCompensation=false",
            }:
                return None
            token = _decode_identity(parts[2])
            if token is None:
                return None
            return ProviderUrlTarget(
                provider_id=AshbyProvider.provider_id,
                target_kind=ProviderTargetKind.BOARD,
                url=url,
                board_identity=token,
                route=ProviderRouteIdentity(token=token, host=host),
            )

        if host != "jobs.ashbyhq.com":
            return None
        if len(parts) == 2 and parts[1] == "embed":
            if parsed.query != "version=2":
                return None
            token = _decode_identity(parts[0])
            if token is None:
                return None
            return ProviderUrlTarget(
                provider_id=AshbyProvider.provider_id,
                target_kind=ProviderTargetKind.BOARD,
                url=f"https://jobs.ashbyhq.com/{quote(token, safe='-._~')}",
                board_identity=token,
                route=ProviderRouteIdentity(token=token, host=host),
            )
        if parsed.query:
            return None
        if len(parts) not in {1, 2, 3}:
            return None
        if len(parts) == 3 and parts[2] != "application":
            return None
        token = _decode_identity(parts[0])
        posting_identity = _decode_identity(parts[1]) if len(parts) >= 2 else None
        if token is None or (len(parts) >= 2 and posting_identity is None):
            return None
        return ProviderUrlTarget(
            provider_id=AshbyProvider.provider_id,
            target_kind=(
                ProviderTargetKind.POSTING
                if posting_identity is not None
                else ProviderTargetKind.BOARD
            ),
            url=url,
            board_identity=token,
            posting_identity=posting_identity,
            route=ProviderRouteIdentity(token=token, host=host),
        )

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        token = quote(slug.strip(), safe="-._~")
        return (f"https://jobs.ashbyhq.com/{token}",) if token else ()

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        token = _require_ashby_board_target(target)
        kernel = await self._list_public_membership(
            client,
            token,
            identity_mode="pull",
            include_unlisted=include_unlisted,
            cache_identity={"role": "membership"},
        )
        return kernel.to_provider_list_result(target)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        token = ashby_token(route)
        if not token:
            raise ValueError("Ashby route is missing a public board token")
        kernel = await self._list_public_membership(
            client,
            token,
            identity_mode="ingest",
            include_unlisted=False,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
        cache_identity: dict[str, str] | None = None,
    ) -> BoardListingKernelResult:
        encoded_token = quote(token, safe="-._~")
        request_kwargs: dict[str, object] = {}
        if cache_identity is not None:
            request_kwargs["cache_identity"] = dict(cache_identity)
        data = await self._request_json(
            client,
            "GET",
            f"https://api.ashbyhq.com/posting-api/job-board/{encoded_token}",
            params={"includeCompensation": "true"},
            **request_kwargs,
        )
        if not isinstance(data, dict):
            raise ValueError("Ashby posting API returned invalid JSON")
        response = AshbyJobBoardResponse.model_validate(data)
        selected = [
            posting
            for posting in response.jobs
            if include_unlisted or posting.is_listed is not False
        ]
        native_board = _pull_board(token)
        postings: list[ListingPosting] = []
        for posting in selected:
            remote_id_override = None
            if identity_mode == "pull":
                remote_id_override = _pull_posting_identity(posting, token)
            job = self._normalize(
                native_board,
                posting,
                remote_id_override=remote_id_override,
            )
            postings.append(
                ListingPosting(job=job, listing=job.raw_listing, detail=None)
            )
        return BoardListingKernelResult(
            native_board_identity=token,
            postings=tuple(postings),
            membership=MembershipEvidence(
                scope=(
                    MembershipScope.ALL_PUBLIC
                    if include_unlisted
                    else MembershipScope.LISTED
                ),
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=1,
                observed_count=len(postings),
            ),
            detail_coverage=DetailCoverageEvidence(),
        )

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

    def _normalize(
        self,
        board: BoardRecord,
        posting: AshbyJobPosting,
        *,
        remote_id_override: str | None = None,
    ) -> JobRecord:
        remote_id = str(
            first_present(
                remote_id_override,
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
            posting_kind=("unlisted" if posting.is_listed is False else "standard"),
            raw_listing=posting.as_raw_payload(),
        )


def ashby_token(route: BoardProviderRecord) -> str | None:
    if route.token:
        return route.token.strip()
    if route.board_url:
        return ashby_token_from_url(route.board_url)
    return None


def _locations(posting: AshbyJobPosting) -> list[str]:
    values: list[str] = []
    if posting.location:
        values.append(posting.location)
    for secondary in posting.secondary_locations:
        if secondary.location:
            values.append(secondary.location)
    return list(dict.fromkeys(values))


def _require_ashby_board_target(target: ProviderUrlTarget) -> str:
    if target.provider_id != AshbyProvider.provider_id:
        raise ValueError("Ashby pull target has the wrong provider")
    if target.target_kind != ProviderTargetKind.BOARD:
        raise ValueError("Ashby list requires a board target")
    token = target.route.token
    if not token or token != target.board_identity:
        raise ValueError("Ashby pull target has inconsistent board identity")
    return token


def _pull_board(token: str) -> BoardRecord:
    return synthetic_url_pull_board(token, remote_slug=token)


def _pull_posting_identity(posting: AshbyJobPosting, token: str) -> str | None:
    if posting.job_url:
        target = AshbyProvider.parse_url_target(posting.job_url)
        if (
            target is not None
            and target.target_kind == ProviderTargetKind.POSTING
            and target.board_identity == token
        ):
            return target.posting_identity
    return posting.id


def _strict_url_parts(path: str) -> list[str]:
    normalized = path[:-1] if path.endswith("/") and path != "/" else path
    if not normalized.startswith("/"):
        raise ValueError("Ashby URL path must be absolute")
    raw = normalized[1:]
    if not raw or any(not part for part in raw.split("/")):
        raise ValueError("Ashby URL path contains an empty segment")
    return raw.split("/")


def _decode_identity(value: str) -> str | None:
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return None
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        not decoded
        or len(decoded) > 500
        or decoded in {".", ".."}
        or "/" in decoded
        or "\\" in decoded
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in decoded
        )
    ):
        return None
    return decoded
