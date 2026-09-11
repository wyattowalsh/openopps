from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Literal, cast
from urllib.parse import quote, unquote, urlparse

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
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    ListingIdentityMode,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    optional_pull_attr,
    optional_pull_capabilities,
)
from openopps.providers.boards.tokens import greenhouse_token_from_url
from openopps.providers.boards.url_targets import synthetic_url_pull_board
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


ProviderGetMethod = optional_pull_attr("ProviderGetMethod")
ProviderGetResult = optional_pull_attr("ProviderGetResult")
ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")


class GreenhouseProvider:
    provider_id = "greenhouse"
    provider_label = "Greenhouse"
    provider_description = "Public Greenhouse job board API."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        native_get_supported=True,
        interface_stability="documented",
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        token = _token_from_url(url)
        return ProviderRouteMatch(token=token) if token else None

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        if len(url.strip()) > 2_000:
            return None
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            if parsed.params or parsed.port is not None:
                return None
        except ValueError:
            return None
        host = (parsed.hostname or "").lower()
        if "//" in parsed.path:
            return None
        parts = [part for part in parsed.path.split("/") if part]

        token: str | None = None
        posting_identity: str | None = None
        if host == "boards-api.greenhouse.io":
            if len(parts) not in {4, 5} or parts[:2] != ["v1", "boards"]:
                return None
            if parts[3] != "jobs":
                return None
            token = _url_identity_segment(parts[2])
            if len(parts) == 5:
                posting_identity = _url_identity_segment(parts[4])
        elif host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
            if len(parts) == 1:
                token = _url_identity_segment(parts[0])
            elif len(parts) == 3 and parts[1] == "jobs":
                token = _url_identity_segment(parts[0])
                posting_identity = _url_identity_segment(parts[2])
            else:
                return None
        else:
            return None
        if token is None or (len(parts) in {3, 5} and posting_identity is None):
            return None
        return ProviderUrlTarget(
            provider_id=GreenhouseProvider.provider_id,
            target_kind=(
                ProviderTargetKind.POSTING
                if posting_identity is not None
                else ProviderTargetKind.BOARD
            ),
            url=url,
            board_identity=token,
            posting_identity=posting_identity,
            route=ProviderRouteIdentity(token=token),
        )

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        identity = _probe_identity(slug)
        if identity is None:
            return ()
        return (f"https://boards.greenhouse.io/{quote(identity, safe='')}",)

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        target = _validated_pull_target(target, ProviderTargetKind.BOARD)
        kernel = await self._list_public_membership(
            client,
            target.board_identity,
            identity_mode="pull",
            include_unlisted=include_unlisted,
            cache_identity={"role": "membership"},
        )
        return kernel.to_provider_list_result(target)

    async def pull_get(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        target = _validated_pull_target(target, ProviderTargetKind.POSTING)
        posting_identity = target.posting_identity
        if posting_identity is None:  # Defensive after typed target validation.
            raise ValueError("Greenhouse posting target is missing a job id")
        token = target.board_identity
        data = await self._request_json(
            client,
            "GET",
            f"https://boards-api.greenhouse.io/v1/boards/{quote(token, safe='')}/jobs/{quote(posting_identity, safe='')}",
            params={"content": "true"},
            cache_identity={"role": "detail"},
        )
        if not isinstance(data, dict):
            raise ValueError("Greenhouse job endpoint returned invalid JSON")
        if isinstance(data.get("id"), bool):
            raise ValueError("Greenhouse job has a malformed public job id")
        posting = GreenhouseJobPosting.model_validate(data)
        if _greenhouse_posting_identity(posting) != posting_identity:
            raise ValueError("Greenhouse job endpoint returned a different job id")
        job = self._normalize(
            _pull_board(token),
            posting,
            token,
            evidence_role="detail",
        )
        return ProviderGetResult(
            posting=ProviderPosting(job=job, listing=None, detail=job.raw_detail),
            method=ProviderGetMethod.NATIVE,
            matched_identity=posting_identity,
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        token = _token_from_route(route)
        if not token:
            raise ValueError("Greenhouse route is missing a public board token")
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
        cache_identity: Mapping[str, str] | None = None,
    ) -> BoardListingKernelResult:
        del identity_mode
        if include_unlisted:
            raise ValueError("Greenhouse does not support unlisted enumeration")
        request_kwargs: dict[str, object] = {}
        if cache_identity is not None:
            request_kwargs["cache_identity"] = dict(cache_identity)
        data = await self._request_json(
            client,
            "GET",
            f"https://boards-api.greenhouse.io/v1/boards/{quote(token, safe='')}/jobs",
            params={"content": "true"},
            **request_kwargs,
        )
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        raw_jobs = data.get("jobs")
        if not isinstance(raw_jobs, list) or any(
            not isinstance(posting, dict) for posting in raw_jobs
        ):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        response = GreenhouseJobsResponse.model_validate(data)
        native_board = _pull_board(token)
        postings: list[ListingPosting] = []
        identities: set[str] = set()
        for raw_posting, posting in zip(raw_jobs, response.jobs, strict=True):
            if isinstance(raw_posting.get("id"), bool):
                raise ValueError("Greenhouse job has a malformed public job id")
            identity = _greenhouse_posting_identity(posting)
            if identity in identities:
                raise ValueError("Greenhouse jobs endpoint returned duplicate job ids")
            identities.add(identity)
            job = self._normalize(native_board, posting, token)
            postings.append(
                ListingPosting(job=job, listing=job.raw_listing, detail=None)
            )
        advertised_count = _greenhouse_advertised_count(data)
        if advertised_count is not None and advertised_count != len(postings):
            raise ValueError("Greenhouse advertised count does not match returned jobs")
        return BoardListingKernelResult(
            native_board_identity=token,
            postings=tuple(postings),
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=1,
                observed_count=len(postings),
                advertised_count=advertised_count,
            ),
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
        self,
        board: BoardRecord,
        posting: GreenhouseJobPosting,
        token: str,
        *,
        evidence_role: Literal["listing", "detail"] = "listing",
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
        raw_payload = posting.as_raw_payload()
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
            raw_listing=raw_payload if evidence_role == "listing" else {},
            raw_detail=raw_payload if evidence_role == "detail" else {},
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


def _validated_pull_target(
    target: ProviderUrlTarget,
    target_kind: ProviderTargetKind,
) -> ProviderUrlTarget:
    reparsed = GreenhouseProvider.parse_url_target(target.url)
    if reparsed is None or reparsed != target:
        raise ValueError("Greenhouse pull target is not a canonical provider URL")
    if target.target_kind != target_kind:
        raise ValueError(f"Greenhouse pull requires a {target_kind.value} target")
    return target


def _url_identity_segment(value: str) -> str | None:
    if not value or re.search(r"%(?![0-9A-Fa-f]{2})", value):
        return None
    try:
        identity = unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if (
        not identity
        or identity in {".", ".."}
        or len(identity) > 500
        or any(character in identity for character in "/\\?#")
        or any(character.isspace() for character in identity)
        or any(ord(character) < 32 or ord(character) == 127 for character in identity)
    ):
        return None
    return identity


def _probe_identity(value: str) -> str | None:
    identity = value.strip()
    if (
        not identity
        or len(identity) > 500
        or any(character in identity for character in "/\\?#")
        or any(character.isspace() for character in identity)
    ):
        return None
    return identity


def _pull_board(board_identity: str) -> BoardRecord:
    return synthetic_url_pull_board(board_identity)


def _greenhouse_posting_identity(posting: GreenhouseJobPosting) -> str:
    if posting.id is None or isinstance(posting.id, bool):
        raise ValueError("Greenhouse job is missing a public job id")
    identity = str(posting.id).strip()
    if not identity:
        raise ValueError("Greenhouse job is missing a public job id")
    return identity


def _greenhouse_advertised_count(data: Mapping[str, object]) -> int | None:
    values: list[int] = []
    containers: list[Mapping[str, object]] = [data]
    meta = data.get("meta")
    if meta is not None:
        if not isinstance(meta, dict):
            raise ValueError("Greenhouse jobs metadata is malformed")
        containers.append(meta)
    for container in containers:
        for key in ("count", "total", "total_count"):
            if key not in container:
                continue
            value = container[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Greenhouse advertised count is malformed")
            values.append(value)
    if len(set(values)) > 1:
        raise ValueError("Greenhouse advertised counts are inconsistent")
    return values[0] if values else None
