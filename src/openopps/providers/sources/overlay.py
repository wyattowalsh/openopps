"""Packaged job-seeker overlay boards and jobs-capable ATS routes.

Reads maintainer-owned locators from packaged JSON. A BoardProviderRecord is
emitted only when detect_url_matches returns a jobs-capable provider.
Careers-only rows stay boards without providers. Never fetches locators or
invents an ATS token from a company domain.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING

import httpx

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.providers.sources.source_utils import (
    index_board_record,
    source_taxonomy_metadata,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify

if TYPE_CHECKING:
    from openopps.providers.registry import ProviderRegistry

PACKAGED_OVERLAY_FILENAME = "job_seeker_overlay.json"
JOB_SEEKER_OVERLAY_SOURCE_KEY = "job-seeker-overlay"
_OVERLAY_TIERS = ("core", "expand", "growth")

JOB_SEEKER_OVERLAY_SOURCE = SourceRecord(
    key=JOB_SEEKER_OVERLAY_SOURCE_KEY,
    url="manual://job-seeker-overlay",
    provider_id="job_seeker_overlay",
    raw_metadata=source_taxonomy_metadata(
        provider_type="employer_overlay",
        coverage_mode="named_employers",
        access_type="packaged_json",
        license_status="needs_review",
        refresh_cadence="manual",
        source_category="job_seeker_coverage",
        source_attribution=(
            "Maintainer-owned public careers and ATS locators for job-seeker "
            "overlay employers; packaged JSON is not independently licensed."
        ),
        inclusion_reason=(
            "Global knowledge-work overlay of recognizable employers with public "
            "locators. Acquisition order is work-order only across AI, software, "
            "data, product, security, finance, biotech, and other professional "
            "roles: not US-HQ-weighted and not a Jobs/Explorer ranker. ATS routes "
            "attach only when detect_url_matches returns a jobs-capable provider."
        ),
        indexName="Job seeker overlay",
    ),
)


@lru_cache(maxsize=1)
def load_packaged_overlay_entries() -> tuple[Mapping[str, str], ...]:
    """Load overlay rows from packaged JSON. Core, then expand, then growth."""

    package = "openopps.providers.sources.data"
    resource = resources.files(package).joinpath(PACKAGED_OVERLAY_FILENAME)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{PACKAGED_OVERLAY_FILENAME} must be an object")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for tier in _OVERLAY_TIERS:
        rows = payload.get(tier, [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"{PACKAGED_OVERLAY_FILENAME} {tier} must be a list")
        for row in rows:
            entry = _entry_from_packaged_row(row, tier=tier)
            overlay_id = entry["id"]
            if overlay_id in seen:
                raise ValueError(f"duplicate overlay id {overlay_id!r}")
            seen.add(overlay_id)
            entries.append(entry)
    return tuple(entries)


class JobSeekerOverlaySourceAdapter:
    provider_id = "job_seeker_overlay"
    provider_label = "Job Seeker Overlay"
    provider_description = (
        "Packaged overlay of public employer locators. Emits boards for every "
        "row and jobs-capable ATS routes only when detect_url_matches returns a "
        "jobs-capable provider."
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        del client, page_size
        boards, providers = boards_from_overlay_entries(
            source, load_packaged_overlay_entries()
        )
        yield (
            boards,
            providers,
            {
                "total": len(boards),
                "sourceUrl": source.url,
                "indexName": source.raw_metadata.get("indexName"),
            },
        )


def boards_from_overlay_entries(
    source: SourceRecord,
    entries: tuple[Mapping[str, str], ...] | list[Mapping[str, str]],
) -> tuple[list[BoardRecord], list[BoardProviderRecord]]:
    """Turn overlay locator rows into boards plus jobs-capable provider routes."""

    from openopps.providers.boards import board_provider_definitions
    from openopps.providers.registry import ProviderRegistry as LiveRegistry

    registry = LiveRegistry(list(board_provider_definitions()))
    boards: list[BoardRecord] = []
    providers: list[BoardProviderRecord] = []
    for entry in entries:
        overlay_id = entry["id"]
        name = entry["name"]
        locator = entry["locator"]
        tier = entry.get("tier") or ""
        remote_slug = slugify(overlay_id)
        board = index_board_record(
            source=source,
            name=name,
            remote_id=overlay_id,
            remote_slug=remote_slug,
            website_url=locator,
            raw_payload={
                "overlayId": overlay_id,
                "overlayName": name,
                "locator": locator,
                "tier": tier or None,
                "sourceReferenceUrl": source.url,
                "sourceProvider": source.provider_id,
            },
        )
        boards.append(board)
        route = _jobs_capable_route(
            locator,
            source_key=source.key,
            board_key=board.key,
            overlay_id=overlay_id,
            registry=registry,
        )
        if route is not None:
            providers.append(route)
    return boards, providers


def _entry_from_packaged_row(row: object, *, tier: str) -> dict[str, str]:
    if not isinstance(row, dict):
        raise ValueError(f"{PACKAGED_OVERLAY_FILENAME} entries must be objects")
    overlay_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    locator = str(row.get("locator") or "").strip()
    if not overlay_id or not name or not locator:
        raise ValueError(
            f"{PACKAGED_OVERLAY_FILENAME} entries require id, name, and locator"
        )
    return {
        "id": overlay_id,
        "name": name,
        "locator": locator,
        "tier": tier,
    }


def jobs_capable_routes_from_locator(
    locator: str,
    *,
    source_key: str,
    board_key: str,
    registry: ProviderRegistry | None = None,
) -> tuple[BoardProviderRecord, ...]:
    """Return jobs-capable ``detect_url_matches`` for one public locator."""

    from openopps.providers.boards import board_provider_definitions
    from openopps.providers.registry import ProviderRegistry as LiveRegistry

    board_registry = registry or LiveRegistry(list(board_provider_definitions()))
    detect_matches = getattr(board_registry, "detect_url_matches", None)
    if callable(detect_matches):
        detected = detect_matches(
            locator,
            board_key=board_key,
            source_key=source_key,
        )
    else:
        single = board_registry.detect_url(
            locator,
            board_key=board_key,
            source_key=source_key,
        )
        detected = (single,) if single is not None else ()
    matches: list[BoardProviderRecord] = []
    for match in detected:
        definition = board_registry.get(match.provider_id)
        if definition is not None and definition.job_capable:
            jobs_capable = True
        else:
            jobs_capable = match.support_level == ProviderSupport.JOBS
        if jobs_capable:
            matches.append(match)
    return tuple(matches)


def _jobs_capable_route(
    locator: str,
    *,
    source_key: str,
    board_key: str,
    overlay_id: str,
    registry: ProviderRegistry | None = None,
) -> BoardProviderRecord | None:
    """Attach a route only when detect_url_matches returns a jobs-capable ATS match."""

    matches = jobs_capable_routes_from_locator(
        locator,
        source_key=source_key,
        board_key=board_key,
        registry=registry,
    )
    if not matches:
        return None
    match = matches[0]
    return match.model_copy(
        update={"raw_payload": {"locator": locator, "overlayId": overlay_id}}
    )


SOURCE_RECORDS: tuple[SourceRecord, ...] = (JOB_SEEKER_OVERLAY_SOURCE,)

__all__ = [
    "JOB_SEEKER_OVERLAY_SOURCE",
    "JOB_SEEKER_OVERLAY_SOURCE_KEY",
    "JobSeekerOverlaySourceAdapter",
    "PACKAGED_OVERLAY_FILENAME",
    "SOURCE_RECORDS",
    "boards_from_overlay_entries",
    "jobs_capable_routes_from_locator",
    "load_packaged_overlay_entries",
]
