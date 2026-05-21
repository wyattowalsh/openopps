from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from openopps.models import BoardProviderRecord, BoardRecord, JobRecord, utc_now
from openopps.storage import OpenOppsStore


@dataclass(frozen=True)
class MetadataEnrichmentChange:
    record_type: str
    key: str
    updates: dict[str, Any]
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recordType": self.record_type,
            "key": self.key,
            "updates": self.updates,
            "sources": self.sources,
        }


@dataclass(frozen=True)
class MetadataEnrichmentSummary:
    checked_boards: int
    board_changes: list[MetadataEnrichmentChange]
    route_changes: list[MetadataEnrichmentChange]
    applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkedBoards": self.checked_boards,
            "boardChanges": [change.as_dict() for change in self.board_changes],
            "routeChanges": [change.as_dict() for change in self.route_changes],
            "boardChangeCount": len(self.board_changes),
            "routeChangeCount": len(self.route_changes),
            "applied": self.applied,
        }


def enrich_metadata(
    store: OpenOppsStore,
    *,
    source_key: str | None = None,
    board_key: str | None = None,
    limit: int | None = None,
    apply: bool = False,
) -> MetadataEnrichmentSummary:
    """Promote reusable metadata from preserved payloads into normalized fields."""

    boards = store.list_boards(source_key=source_key, board_key=board_key, limit=limit)
    jobs_by_board = _jobs_by_board(
        store.list_jobs(source_key=source_key, board_key=board_key)
    )
    board_changes: list[MetadataEnrichmentChange] = []
    route_changes: list[MetadataEnrichmentChange] = []
    updated_boards: list[BoardRecord] = []
    updated_routes: list[BoardProviderRecord] = []

    for board in boards:
        board_updates, board_sources = _board_updates(
            board, board.providers, jobs_by_board.get(board.key, [])
        )
        if board_updates:
            board_updates["synced_at"] = utc_now()
            board_changes.append(
                MetadataEnrichmentChange(
                    record_type="board",
                    key=board.key,
                    updates=_json_safe_updates(board_updates),
                    sources=board_sources,
                )
            )
            updated_boards.append(board.model_copy(update=board_updates))
        for route in board.providers:
            route_updates, route_sources = _route_updates(route)
            if not route_updates:
                continue
            route_updates["detected_at"] = utc_now()
            route_changes.append(
                MetadataEnrichmentChange(
                    record_type="board_provider",
                    key=route.id,
                    updates=_json_safe_updates(route_updates),
                    sources=route_sources,
                )
            )
            updated_routes.append(route.model_copy(update=route_updates))

    if apply:
        store.upsert_boards(updated_boards)
        store.upsert_board_providers(updated_routes)

    return MetadataEnrichmentSummary(
        checked_boards=len(boards),
        board_changes=board_changes,
        route_changes=route_changes,
        applied=apply,
    )


def _board_updates(
    board: BoardRecord,
    routes: list[BoardProviderRecord],
    jobs: list[JobRecord],
) -> tuple[dict[str, Any], list[str]]:
    payload = board.raw_payload
    updates: dict[str, Any] = {}
    sources: list[str] = []

    website_url = _first_string(payload, "website_url", "websiteUrl", "url")
    website_url = website_url or _nested_string(payload, "website", "url")
    if not board.website_url and website_url:
        updates["website_url"] = website_url
        sources.append("board.raw_payload.website")

    domain = _first_string(payload, "domain", "websiteDomain")
    domain = domain or _domain_from_url(updates.get("website_url") or board.website_url)
    if not board.domain and domain:
        updates["domain"] = domain
        sources.append("board.raw_payload.domain")

    description = _first_string(
        payload, "description", "shortDescription", "oneLiner", "bio"
    )
    if not board.description and description:
        updates["description"] = description
        sources.append("board.raw_payload.description")

    markets = _first_string_list(payload, "markets", "industries", "categories", "tags")
    if not board.markets and markets:
        updates["markets"] = markets
        sources.append("board.raw_payload.markets")

    locations = _first_string_list(
        payload, "locations", "officeLocations", "office_locations"
    )
    if not locations:
        locations = _job_locations(jobs)
    if not board.locations and locations:
        updates["locations"] = locations
        sources.append("job.locations" if jobs else "board.raw_payload.locations")

    staff_count = _first_int(payload, "staffCount", "staff_count", "employeeCount")
    if board.staff_count is None and staff_count is not None:
        updates["staff_count"] = staff_count
        sources.append("board.raw_payload.staffCount")

    jobs_hint = _first_int(payload, "numJobs", "num_jobs", "jobCount", "jobsCount")
    if jobs_hint is None:
        route_counts = [
            route_count
            for route in routes
            if (
                route_count := route.count_hint
                or _first_int(
                    route.raw_payload, "count", "jobCount", "numJobs", "jobsCount"
                )
            )
        ]
        jobs_hint = max(route_counts) if route_counts else (len(jobs) or None)
    if board.num_jobs_hint is None and jobs_hint is not None:
        updates["num_jobs_hint"] = jobs_hint
        sources.append("route.count_hint" if routes else "job.count")

    return updates, sources


def _route_updates(
    route: BoardProviderRecord,
) -> tuple[dict[str, Any], list[str]]:
    payload = route.raw_payload
    updates: dict[str, Any] = {}
    sources: list[str] = []

    label = _first_string(payload, "label", "name", "provider", "value")
    if not route.label and label:
        updates["label"] = label
        sources.append("route.raw_payload.label")

    count_hint = _first_int(payload, "count", "jobCount", "numJobs", "jobsCount")
    if route.count_hint is None and count_hint is not None:
        updates["count_hint"] = count_hint
        sources.append("route.raw_payload.count")

    board_url = _first_string(payload, "url", "boardUrl", "careersUrl", "jobsUrl")
    if not route.board_url and board_url:
        updates["board_url"] = board_url
        sources.append("route.raw_payload.url")

    token = _first_string(payload, "token", "slug", "boardToken")
    if not route.token and token:
        updates["token"] = token
        sources.append("route.raw_payload.token")

    return updates, sources


def _jobs_by_board(jobs: Iterable[JobRecord]) -> dict[str, list[JobRecord]]:
    grouped: dict[str, list[JobRecord]] = {}
    for job in jobs:
        grouped.setdefault(job.board_key, []).append(job)
    return grouped


def _job_locations(jobs: list[JobRecord]) -> list[str]:
    output: list[str] = []
    for job in jobs:
        for location in job.locations:
            if location not in output:
                output.append(location)
    return output


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _nested_string(payload: dict[str, Any], key: str, nested_key: str) -> str | None:
    nested = payload.get(key)
    if isinstance(nested, dict):
        value = nested.get(nested_key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_string_list(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        values = _string_list(payload.get(key))
        if values:
            return values
    return []


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        candidate = None
        if isinstance(item, str):
            candidate = item.strip()
        elif isinstance(item, dict):
            item_payload = {str(key): value for key, value in item.items()}
            candidate = _first_string(item_payload, "name", "label", "value", "title")
        if candidate and candidate not in output:
            output.append(candidate)
    return output


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, float) and value >= 0:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _domain_from_url(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    parsed = urlparse(url)
    host = parsed.hostname
    return host.removeprefix("www.") if host else None


def _json_safe_updates(updates: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in updates.items()
    }
