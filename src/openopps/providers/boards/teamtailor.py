from __future__ import annotations

from email.utils import parsedate_to_datetime
import re
from typing import Any, cast
from urllib.parse import unquote, urlparse
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
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    ListingIdentityMode,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    optional_pull_attr,
    optional_pull_capabilities,
)
from openopps.providers.boards.url_targets import synthetic_url_pull_board
from openopps.providers.normalize import string as _string
from openopps.settings import OpenOppsSettings
from openopps.utils import first_present, stable_id


ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")

_TT = "{https://teamtailor.com/locations}"
_TEAMTAILOR_PAGE_SIZE = 100
_TEAMTAILOR_MAX_PAGES = 1_000


class TeamtailorProvider:
    provider_id = "teamtailor"
    provider_label = "Teamtailor"
    provider_description = "Public Teamtailor jobs RSS feed."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        board_scan_get_supported=True,
        interface_stability="best_effort",
    )

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
        if not host.endswith(".teamtailor.com") or host == "teamtailor.com":
            return None
        board_identity = host.removesuffix(".teamtailor.com")
        if not board_identity:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        posting_identity: str | None = None
        if not parts or parts in (["jobs"], ["jobs.rss"]):
            pass
        elif len(parts) == 2 and parts[0] == "jobs":
            posting_identity = _url_identity_segment(parts[1])
            if posting_identity is None:
                return None
        else:
            return None
        return ProviderUrlTarget(
            provider_id=TeamtailorProvider.provider_id,
            target_kind=(
                ProviderTargetKind.POSTING
                if posting_identity is not None
                else ProviderTargetKind.BOARD
            ),
            url=url,
            board_identity=board_identity,
            posting_identity=posting_identity,
            route=ProviderRouteIdentity(host=host, token=board_identity),
        )

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        label = slug.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label):
            return ()
        return (f"https://{label}.teamtailor.com/jobs",)

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        target = _validated_pull_target(target)
        host = target.route.host
        if host is None:
            raise ValueError("Teamtailor target is missing its board host")
        kernel = await self._list_public_membership(
            client,
            host=host,
            board_identity=target.board_identity,
            identity_mode="pull",
            include_unlisted=include_unlisted,
            cache_identity={"role": "membership_page"},
        )
        return kernel.to_provider_list_result(target)

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        host = teamtailor_host(route)
        if not host:
            raise ValueError("Teamtailor route is missing a public board host")
        kernel = await self._list_public_membership(
            client,
            host=host,
            board_identity=(route.token or "").strip() or host.split(".", 1)[0],
            identity_mode="ingest",
            include_unlisted=False,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        *,
        host: str,
        board_identity: str,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
        cache_identity: dict[str, str] | None = None,
    ) -> BoardListingKernelResult:
        if include_unlisted:
            raise ValueError("Teamtailor does not support unlisted enumeration")
        prefer_link_identity = identity_mode == "pull"
        native_board = _pull_board(board_identity)
        postings: list[ListingPosting] = []
        identities: set[str] = set()
        guid_identities: set[str] = set()
        page_signatures: set[tuple[tuple[str, str, str], ...]] = set()
        pages_fetched = 0
        offset = 0
        terminal_page_seen = False

        for _page_number in range(1, _TEAMTAILOR_MAX_PAGES + 1):
            request_kwargs: dict[str, object] = {}
            if cache_identity is not None:
                request_kwargs["cache_identity"] = dict(cache_identity)
            text = await self._request_text(
                client,
                "GET",
                f"https://{host}/jobs.rss",
                params={"offset": offset, "per_page": _TEAMTAILOR_PAGE_SIZE},
                headers={"accept": "application/rss+xml, application/xml, text/xml"},
                **request_kwargs,
            )
            pages_fetched += 1
            items = _rss_items(ET.fromstring(text))
            if len(items) > _TEAMTAILOR_PAGE_SIZE:
                raise ValueError(
                    "Teamtailor returned more jobs than the requested page size"
                )
            if not items:
                terminal_page_seen = True
                break

            raw_items = [_item_payload(item) for item in items]
            page_signature = tuple(_teamtailor_page_identity(raw) for raw in raw_items)
            if page_signature in page_signatures:
                raise ValueError("Teamtailor returned a repeated RSS page")
            page_signatures.add(page_signature)

            page_jobs: list[JobRecord] = []
            for item, raw in zip(items, raw_items, strict=True):
                link_identity = _teamtailor_link_identity(raw, board_identity)
                guid_identity = _string(raw.get("guid"))
                if link_identity is None and guid_identity is None:
                    raise ValueError(
                        "Teamtailor RSS item is missing a stable provider identity"
                    )
                job = self._normalize(
                    native_board,
                    item,
                    prefer_link_identity=prefer_link_identity,
                )
                if job.remote_id in identities:
                    raise ValueError("Teamtailor returned duplicate posting identities")
                if guid_identity is not None and guid_identity in guid_identities:
                    raise ValueError("Teamtailor returned duplicate posting GUIDs")
                identities.add(job.remote_id)
                if guid_identity is not None:
                    guid_identities.add(guid_identity)
                page_jobs.append(job)

            postings.extend(
                ListingPosting(job=job, listing=job.raw_listing, detail=None)
                for job in page_jobs
            )
            if len(items) < _TEAMTAILOR_PAGE_SIZE:
                terminal_page_seen = True
                break
            offset += len(items)

        if not terminal_page_seen:
            raise ValueError("Teamtailor pagination exhausted its finite page budget")
        return BoardListingKernelResult(
            native_board_identity=board_identity,
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

    def _normalize(
        self,
        board: BoardRecord,
        item: ET.Element,
        *,
        prefer_link_identity: bool = False,
    ) -> JobRecord:
        raw = _item_payload(item)
        remote_id = str(
            first_present(
                _teamtailor_link_identity(raw, board.key)
                if prefer_link_identity
                else None,
                raw.get("guid"),
                raw.get("link"),
                raw.get("title"),
            )
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


def _validated_pull_target(target: ProviderUrlTarget) -> ProviderUrlTarget:
    reparsed = TeamtailorProvider.parse_url_target(target.url)
    if reparsed is None:
        raise ValueError("Teamtailor pull target is not a canonical provider URL")
    if target.target_kind != ProviderTargetKind.BOARD:
        raise ValueError("Teamtailor list pull requires a board target")
    if (
        target.provider_id != reparsed.provider_id
        or target.board_identity != reparsed.board_identity
        or target.route != reparsed.route
        or target.posting_identity is not None
    ):
        raise ValueError("Teamtailor pull target is not a canonical provider URL")
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


def _pull_board(board_identity: str) -> BoardRecord:
    return synthetic_url_pull_board(board_identity)


def _teamtailor_link_identity(raw: JsonDict, board_identity: str) -> str | None:
    link = _string(raw.get("link"))
    if link is None:
        return None
    try:
        target = TeamtailorProvider.parse_url_target(link)
    except ValueError:
        return None
    if (
        target is None
        or target.target_kind != ProviderTargetKind.POSTING
        or target.board_identity != board_identity
    ):
        return None
    return target.posting_identity


def _teamtailor_page_identity(raw: JsonDict) -> tuple[str, str, str]:
    guid = _string(raw.get("guid")) or ""
    link = _string(raw.get("link")) or ""
    title = _string(raw.get("title")) or ""
    if not any((guid, link, title)):
        raise ValueError("Teamtailor RSS item is missing a stable identity")
    return guid, link, title
