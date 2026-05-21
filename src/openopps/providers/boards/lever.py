from __future__ import annotations

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    LeverPosting,
    normalize_remote_level,
    strip_html,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


class LeverProvider:
    provider_id = "lever"

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
        url = f"https://api.lever.co/v0/postings/{token}"
        data = await self._request_json(client, "GET", url, params={"mode": "json"})
        if not isinstance(data, list):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        postings = [
            LeverPosting.model_validate(posting)
            for posting in data
            if isinstance(posting, dict)
        ]
        return [self._normalize(board, posting) for posting in postings]

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
            workplace_type=posting.categories.commitment,
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
        heading = (section.text or "").lower()
        bullets = _bullets(section.content)
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


def _bullets(value: str | None) -> list[str]:
    text = strip_html(value)
    if not text:
        return []
    lines = [line.strip(" -•\t") for line in text.splitlines()]
    return [line for line in lines if line]


def _lever_timestamp(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    return value


def _token_from_route(route: BoardProviderRecord) -> str | None:
    token = route.token
    if not token and route.board_url:
        token = route.board_url.rstrip("/").split("/")[-1]
    return token
