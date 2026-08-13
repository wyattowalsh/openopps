from __future__ import annotations

from datetime import datetime, timezone

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
from openopps.providers.boards.tokens import lever_token_from_url
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class LeverProvider:
    provider_id = "lever"
    provider_label = "Lever"
    provider_description = "Public Lever postings JSON API."

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
            raise ValueError("Lever route is missing a public board token")
        url = f"https://api.lever.co/v0/postings/{token}"
        data = await self._request_json(client, "GET", url, params={"mode": "json"})
        if not isinstance(data, list):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        if any(not isinstance(posting, dict) for posting in data):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        postings = [LeverPosting.model_validate(posting) for posting in data]
        return JobFetchResult(
            jobs=[self._normalize(board, posting) for posting in postings],
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
        data = await self._request_json(
            client,
            "GET",
            f"https://api.lever.co/v0/postings/{token}",
            params={"mode": "json"},
        )
        if not isinstance(data, list):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        return len(data)

    def _normalize(self, board: BoardRecord, posting: LeverPosting) -> JobRecord:
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
            raw_listing=posting.as_raw_payload(),
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
