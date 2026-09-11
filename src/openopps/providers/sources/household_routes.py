"""Attach packaged public ATS routes onto household index boards by name.

Locators come from the packaged portfolio catalog and from packaged overlay
rows whose URLs already match a jobs-capable ATS host. Imported by packaged
source discovery. Do not define SOURCE_RECORDS, live-fetch, or invent an ATS
token from a ticker or company domain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from openopps.models import BoardProviderRecord, BoardRecord, SourceRecord
from openopps.providers.sources.overlay import load_packaged_overlay_entries
from openopps.providers.sources.source_utils import load_packaged_portfolio_source_records
from openopps.utils import slugify

if TYPE_CHECKING:
    from openopps.providers.registry import ProviderRegistry

_ATS_HOST_SUFFIXES = frozenset(
    {
        "apply.workable.com",
        "ashbyhq.com",
        "ats.rippling.com",
        "bamboohr.com",
        "careers.rippling.com",
        "greenhouse.io",
        "lever.co",
        "myworkdayjobs.com",
        "teamtailor.com",
    }
)
_BLOCKED_HOST_LABELS = frozenset(
    {
        "angel",
        "angellist",
        "consider",
        "getro",
        "linkedin",
        "wellfound",
        "workatastartup",
        "indeed",
        "glassdoor",
    }
)
_LEGAL_SUFFIX_TOKENS = frozenset(
    {
        "ag",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "limited",
        "llc",
        "lp",
        "ltd",
        "nv",
        "plc",
        "sa",
        "se",
    }
)
_TRAILING_DESCRIPTOR_TOKENS = frozenset(
    {
        "communications",
        "electronics",
        "global",
        "group",
        "holding",
        "holdings",
        "interactive",
        "international",
        "laboratories",
        "labs",
        "markets",
        "network",
        "networks",
        "partners",
        "platforms",
        "software",
        "systems",
        "technologies",
        "technology",
    }
)
_SHARE_CLASS_RE = re.compile(
    r"\(\s*(?:class|series)\s+[a-z0-9]+\s*\)|\b(?:class|series)\s+[a-z0-9]+\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_MIN_NAME_KEY_LENGTH = 2


@dataclass(frozen=True, slots=True)
class PackagedAtsLocator:
    """A packaged catalog or overlay row whose URL is a public ATS board."""

    catalog_key: str
    name: str
    url: str


def household_index_provider_records(
    source: SourceRecord,
    boards: Sequence[BoardRecord],
) -> list[BoardProviderRecord]:
    """Return jobs-capable routes for index boards with a clear packaged ATS name match."""

    lookup = _locator_lookup()
    registry = _board_registry()
    providers: list[BoardProviderRecord] = []
    for board in boards:
        if _board_host_is_blocked(board):
            continue
        locator = _unique_locator_for_name(board.name, lookup)
        if locator is None:
            continue
        route = _jobs_capable_route(
            registry,
            locator.url,
            source_key=source.key,
            board_key=board.key,
        )
        if route is None:
            continue
        providers.append(route)
    return providers


def _unique_locator_for_name(
    name: str,
    lookup: Mapping[str, tuple[PackagedAtsLocator, ...]],
) -> PackagedAtsLocator | None:
    found = _locators_for_name_keys(_company_name_keys(name), lookup)
    if len(found) == 1:
        return next(iter(found.values()))
    if len(found) > 1:
        return None
    tokens = _core_company_name(name).split()
    while len(tokens) > 1 and tokens[-1] in _TRAILING_DESCRIPTOR_TOKENS:
        tokens.pop()
        found = _locators_for_name_keys(
            _company_name_keys(" ".join(tokens)), lookup
        )
        if len(found) == 1:
            return next(iter(found.values()))
        if len(found) > 1:
            return None
    return None


def _locators_for_name_keys(
    keys: frozenset[str],
    lookup: Mapping[str, tuple[PackagedAtsLocator, ...]],
) -> dict[str, PackagedAtsLocator]:
    found: dict[str, PackagedAtsLocator] = {}
    for key in keys:
        for locator in lookup.get(key, ()):
            found[locator.url] = locator
    return found


def _company_name_keys(*values: str) -> frozenset[str]:
    keys: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        keys.add(text.casefold())
        slug = slugify(text)
        keys.add(slug)
        keys.add(slug.replace("-", ""))
        core = _core_company_name(text)
        if core:
            keys.add(core)
            core_slug = slugify(core)
            keys.add(core_slug)
            keys.add(core_slug.replace("-", ""))
    return frozenset(key for key in keys if len(key) >= _MIN_NAME_KEY_LENGTH)


def _core_company_name(name: str) -> str:
    text = name.casefold().replace("&", " and ")
    text = _SHARE_CLASS_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    tokens = [token for token in text.split() if token]
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _jobs_capable_route(
    registry: ProviderRegistry,
    url: str,
    *,
    source_key: str,
    board_key: str,
) -> BoardProviderRecord | None:
    if not _is_packaged_public_ats_url(url):
        return None
    from openopps.providers.sources.overlay import jobs_capable_routes_from_locator

    for match in jobs_capable_routes_from_locator(
        url,
        source_key=source_key,
        board_key=board_key,
        registry=registry,
    ):
        if not match.token and not (match.host and match.tenant):
            continue
        return match
    return None


def _board_host_is_blocked(board: BoardRecord) -> bool:
    hosts = []
    if board.website_url:
        hosts.append(
            (urlsplit(board.website_url).hostname or "")
            .casefold()
            .removeprefix("www.")
        )
    if board.domain:
        hosts.append(board.domain.casefold().removeprefix("www."))
    return any(host and _host_is_blocked(host) for host in hosts)


def _is_packaged_public_ats_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    if not host or _host_is_blocked(host):
        return False
    return _host_matches(host, _ATS_HOST_SUFFIXES)


def _host_is_blocked(host: str) -> bool:
    return any(label in _BLOCKED_HOST_LABELS for label in host.split("."))


def _host_matches(host: str, suffixes: frozenset[str]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


@lru_cache(maxsize=1)
def _packaged_ats_locators() -> tuple[PackagedAtsLocator, ...]:
    locators: dict[str, PackagedAtsLocator] = {}
    for record in load_packaged_portfolio_source_records():
        if not _is_packaged_public_ats_url(record.url):
            continue
        label = record.raw_metadata.get("label")
        name = (
            label.strip()
            if isinstance(label, str) and label.strip()
            else record.key
        )
        locators[record.url] = PackagedAtsLocator(
            catalog_key=record.key, name=name, url=record.url
        )
    for entry in load_packaged_overlay_entries():
        url = entry["locator"]
        if url in locators or not _is_packaged_public_ats_url(url):
            continue
        locators[url] = PackagedAtsLocator(
            catalog_key=entry["id"], name=entry["name"], url=url
        )
    return tuple(locators.values())


@lru_cache(maxsize=1)
def _locator_lookup() -> dict[str, tuple[PackagedAtsLocator, ...]]:
    buckets: dict[str, dict[str, PackagedAtsLocator]] = {}
    for locator in _packaged_ats_locators():
        for key in _company_name_keys(locator.name, locator.catalog_key):
            bucket = buckets.setdefault(key, {})
            bucket[locator.catalog_key] = locator
    return {key: tuple(bucket.values()) for key, bucket in buckets.items()}


@lru_cache(maxsize=1)
def _board_registry() -> ProviderRegistry:
    from openopps.providers.boards import board_provider_definitions
    from openopps.providers.registry import ProviderRegistry

    return ProviderRegistry(list(board_provider_definitions()))


__all__ = [
    "PackagedAtsLocator",
    "household_index_provider_records",
]
