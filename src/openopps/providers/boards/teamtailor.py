from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

from openopps.http import retrying_text_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JsonDict,
    JobRecord,
    normalize_remote_level,
    strip_html,
    validate_provider_host,
    validate_public_https_url,
)
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.normalize import string as _string
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


_TT = "{https://teamtailor.com/locations}"


class TeamtailorProvider:
    provider_id = "teamtailor"
    provider_label = "Teamtailor"
    provider_description = "Public Teamtailor jobs RSS feed."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_text = retrying_text_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        validate_public_https_url(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host.endswith(".teamtailor.com"):
            return None
        return ProviderRouteMatch(token=host.removesuffix(".teamtailor.com"), host=host)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        feed = await self._fetch_feed(client, route)
        return JobFetchResult(
            jobs=[self._normalize(board, item) for item in _rss_items(feed)],
            authoritative=True,
        )

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        feed = await self._fetch_feed(client, route)
        return len(_rss_items(feed))

    async def _fetch_feed(
        self, client: httpx.AsyncClient, route: BoardProviderRecord
    ) -> ET.Element:
        host = teamtailor_host(route)
        if not host:
            raise ValueError("Teamtailor route is missing a public board host")
        text = await self._request_text(
            client,
            "GET",
            f"https://{host}/jobs.rss",
            headers={"accept": "application/rss+xml, application/xml, text/xml"},
        )
        return ET.fromstring(text)

    def _normalize(self, board: BoardRecord, item: ET.Element) -> JobRecord:
        raw = _item_payload(item)
        remote_id = str(
            first_present(raw.get("guid"), raw.get("link"), raw.get("title"))
        )
        description_html = _string(raw.get("description"))
        raw_locations = cast(list[object], raw.get("locations", []))
        locations = [
            location for location in raw_locations if isinstance(location, str)
        ]
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(raw.get("title")) or remote_id,
            locations=locations,
            department=_string(raw.get("department")),
            team=_string(raw.get("role")),
            workplace_type=_string(raw.get("remoteStatus")),
            company=board.name,
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(raw.get("remoteStatus"), locations),
            posting_url=_string(raw.get("link")),
            apply_url=_string(raw.get("link")),
            posted_at=_rss_date(raw.get("pubDate")),
            raw_listing=raw,
        )


def teamtailor_host(route: BoardProviderRecord) -> str | None:
    if route.host:
        try:
            return validate_provider_host(route.host, "teamtailor.com")
        except ValueError:
            return None
    if route.board_url:
        parsed = urlparse(route.board_url)
        try:
            return validate_provider_host(parsed.hostname or "", "teamtailor.com")
        except ValueError:
            return None
    if route.token:
        try:
            return validate_provider_host(
                f"{route.token.strip().lower()}.teamtailor.com",
                "teamtailor.com",
            )
        except ValueError:
            return None
    return None


def _rss_items(root: ET.Element) -> list[ET.Element]:
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Teamtailor RSS feed is missing a channel")
    return list(channel.findall("item"))


def _item_payload(item: ET.Element) -> JsonDict:
    payload: dict[str, Any] = {
        "title": _text(item, "title"),
        "description": _text(item, "description"),
        "pubDate": _text(item, "pubDate"),
        "link": _text(item, "link"),
        "remoteStatus": _text(item, "remoteStatus"),
        "guid": _text(item, "guid"),
        "department": _text(item, f"{_TT}department"),
        "role": _text(item, f"{_TT}role"),
        "locations": [],
    }
    locations = item.find(f"{_TT}locations")
    if locations is not None:
        for location in locations.findall(f"{_TT}location"):
            name = _text(location, f"{_TT}name")
            if name:
                payload["locations"].append(name)
    return payload


def _text(item: ET.Element, name: str) -> str | None:
    value = item.findtext(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rss_date(value: object) -> str | None:
    text = _string(value)
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return text
