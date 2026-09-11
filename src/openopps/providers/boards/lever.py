from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal
from urllib.parse import quote, unquote, urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    LeverPosting,
    normalize_remote_level,
    strip_html,
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
from openopps.providers.boards.tokens import lever_token_from_url
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

_LEVER_PAGE_SIZE = 100
_LEVER_MAX_PAGES = 1_000


class LeverProvider:
    provider_id = "lever"
    provider_label = "Lever"
    provider_description = "Public Lever postings JSON API."
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
        if host == "api.lever.co":
            if len(parts) not in {3, 4} or parts[:2] != ["v0", "postings"]:
                return None
            token = _url_identity_segment(parts[2])
            if len(parts) == 4:
                posting_identity = _url_identity_segment(parts[3])
        elif host == "jobs.lever.co":
            if len(parts) == 1:
                token = _url_identity_segment(parts[0])
            elif len(parts) in {2, 3}:
                if len(parts) == 3 and parts[2] != "apply":
                    return None
                token = _url_identity_segment(parts[0])
                posting_identity = _url_identity_segment(parts[1])
            else:
                return None
        else:
            return None
        posting_was_expected = (host == "api.lever.co" and len(parts) == 4) or (
            host == "jobs.lever.co" and len(parts) >= 2
        )
        if token is None or (posting_was_expected and posting_identity is None):
            return None
        return ProviderUrlTarget(
            provider_id=LeverProvider.provider_id,
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
        return (f"https://jobs.lever.co/{quote(identity, safe='')}",)

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
            cache_identity={"role": "membership_page"},
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
            raise ValueError("Lever posting target is missing a posting id")
        token = target.board_identity
        data = await self._request_json(
            client,
            "GET",
            f"https://api.lever.co/v0/postings/{quote(token, safe='')}/{quote(posting_identity, safe='')}",
            params={"mode": "json"},
            cache_identity={"role": "detail"},
        )
        if not isinstance(data, dict):
            raise ValueError("Lever posting endpoint returned invalid JSON")
        posting = LeverPosting.model_validate(data)
        if _lever_posting_identity(posting) != posting_identity:
            raise ValueError("Lever posting endpoint returned a different posting id")
        job = self._normalize(
            _pull_board(token),
            posting,
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
            raise ValueError("Lever route is missing a public board token")
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
        del identity_mode
        if include_unlisted:
            raise ValueError("Lever does not support unlisted enumeration")
        native_board = _pull_board(token)
        postings: list[ListingPosting] = []
        identities: set[str] = set()
        page_signatures: set[tuple[str, ...]] = set()
        pages_fetched = 0
        offset = 0
        terminal_page_seen = False

        for _page_number in range(1, _LEVER_MAX_PAGES + 1):
            request_kwargs: dict[str, object] = {}
            if cache_identity is not None:
                request_kwargs["cache_identity"] = dict(cache_identity)
            data = await self._request_json(
                client,
                "GET",
                f"https://api.lever.co/v0/postings/{quote(token, safe='')}",
                params={
                    "mode": "json",
                    "skip": offset,
                    "limit": _LEVER_PAGE_SIZE,
                },
                **request_kwargs,
            )
            pages_fetched += 1
            payloads = _lever_page_payloads(data)
            if len(payloads) > _LEVER_PAGE_SIZE:
                raise ValueError(
                    "Lever returned more jobs than the requested page size"
                )
            if not payloads:
                terminal_page_seen = True
                break
            typed_postings = [LeverPosting.model_validate(item) for item in payloads]
            page_identities = tuple(
                _lever_posting_identity(posting) for posting in typed_postings
            )
            if page_identities in page_signatures:
                raise ValueError("Lever returned a repeated postings page")
            page_signatures.add(page_identities)
            if len(set(page_identities)) != len(page_identities) or any(
                identity in identities for identity in page_identities
            ):
                raise ValueError("Lever returned duplicate posting ids")
            identities.update(page_identities)
            for posting in typed_postings:
                job = self._normalize(native_board, posting)
                postings.append(
                    ListingPosting(job=job, listing=job.raw_listing, detail=None)
                )
            if len(payloads) < _LEVER_PAGE_SIZE:
                terminal_page_seen = True
                break
            offset += len(payloads)

        if not terminal_page_seen:
            raise ValueError("Lever pagination exhausted its finite page budget")
        return BoardListingKernelResult(
            native_board_identity=token,
            postings=tuple(postings),
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=pages_fetched,
                observed_count=len(postings),
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
        data = await self._request_json(
            client,
            "GET",
            f"https://api.lever.co/v0/postings/{token}",
            params={"mode": "json"},
        )
        if not isinstance(data, list):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        return len(data)

    def _normalize(
        self,
        board: BoardRecord,
        posting: LeverPosting,
        *,
        evidence_role: Literal["listing", "detail"] = "listing",
    ) -> JobRecord:
        remote_id = str(
            first_present(
                posting.id,
                posting.hosted_url,
                posting.text,
            )
        )
        location = posting.categories.location
        locations = [str(location)] if location else []
        responsibilities, qualifications = _structured_sections(posting)
        description_html = _description_html(posting)
        raw_payload = posting.as_raw_payload()
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=posting.text or remote_id,
            locations=locations,
            department=posting.categories.department,
            team=posting.categories.team,
            workplace_type=None,
            company=board.name,
            employment_type=posting.categories.commitment,
            description=posting.description_plain or strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(posting.categories.location),
            responsibilities=responsibilities,
            qualifications=qualifications,
            posting_url=posting.hosted_url,
            apply_url=posting.apply_url,
            posted_at=_lever_timestamp(posting.created_at),
            updated_at=_lever_timestamp(posting.updated_at),
            raw_listing=raw_payload if evidence_role == "listing" else {},
            raw_detail=raw_payload if evidence_role == "detail" else {},
        )


def _description_html(posting: LeverPosting) -> str | None:
    parts = [posting.description]
    parts.extend(section.content for section in posting.lists if section.content)
    parts.append(posting.additional)
    joined = "\n".join(part for part in parts if part)
    return joined or None


def _structured_sections(posting: LeverPosting) -> tuple[list[str], list[str]]:
    responsibilities: list[str] = []
    qualifications: list[str] = []
    for section in posting.lists:
        heading = _section_heading(section)
        bullets = _bullets(
            section.content, heading=heading if not section.text else None
        )
        if any(
            term in heading
            for term in ("responsibil", "duties", "what you'll do", "impact")
        ):
            responsibilities.extend(bullets)
        if any(
            term in heading
            for term in (
                "qualification",
                "requirement",
                "you have",
                "about you",
                "skill",
            )
        ):
            qualifications.extend(bullets)
    return list(dict.fromkeys(responsibilities)), list(dict.fromkeys(qualifications))


def _section_heading(section: object) -> str:
    text = getattr(section, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip().lower()
    content = getattr(section, "content", None)
    lines = _plain_lines(content if isinstance(content, str) else None)
    if not lines:
        return ""
    candidate = lines[0].strip(":").lower()
    heading_terms = (
        "responsibil",
        "duties",
        "what you'll do",
        "impact",
        "qualification",
        "requirement",
        "you have",
        "about you",
        "skill",
    )
    return candidate if any(term in candidate for term in heading_terms) else ""


def _bullets(value: str | None, *, heading: str | None = None) -> list[str]:
    lines = _plain_lines(value)
    if heading and lines:
        normalized_heading = heading.strip(":").lower()
        lines = [
            line for line in lines if line.strip(":").lower() != normalized_heading
        ]
    return lines


def _plain_lines(value: str | None) -> list[str]:
    text = strip_html(value)
    if not text:
        return []
    lines = [line.strip(" -•\t") for line in text.splitlines()]
    return [line for line in lines if line]


def _lever_timestamp(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value.isdigit() and len(value) >= 11:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    return value


def _token_from_route(route: BoardProviderRecord) -> str | None:
    token = route.token
    if token:
        return token.strip()
    if route.board_url:
        return _token_from_url(route.board_url)
    return None


def _token_from_url(url: str) -> str | None:
    return lever_token_from_url(url)


def _validated_pull_target(
    target: ProviderUrlTarget,
    target_kind: ProviderTargetKind,
) -> ProviderUrlTarget:
    reparsed = LeverProvider.parse_url_target(target.url)
    if reparsed is None or reparsed != target:
        raise ValueError("Lever pull target is not a canonical provider URL")
    if target.target_kind != target_kind:
        raise ValueError(f"Lever pull requires a {target_kind.value} target")
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


def _lever_page_payloads(data: object) -> list[dict[str, object]]:
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("Lever postings endpoint returned invalid JSON")
    return data


def _lever_posting_identity(posting: LeverPosting) -> str:
    if posting.id is None:
        raise ValueError("Lever posting is missing a posting id")
    identity = posting.id.strip()
    if not identity:
        raise ValueError("Lever posting is missing a posting id")
    return identity
