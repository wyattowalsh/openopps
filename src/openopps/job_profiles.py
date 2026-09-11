"""Versioned public job projections: core, search, full, and raw."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from openopps.models import JobRecord
from openopps.observations import build_companion_observations, origin_tag

JobProfileName = Literal["core", "search", "full", "raw"]
PROFILE_NAMES: Final[tuple[JobProfileName, ...]] = ("core", "search", "full", "raw")
SCHEMA_VERSION: Final[int] = 1
DEFAULT_CLI_PROFILE: Final[JobProfileName] = "full"
DEFAULT_WEB_PROFILE: Final[JobProfileName] = "search"
FIELD_PROMOTION_RUBRIC: Final[tuple[str, ...]] = (
    "documented_semantics",
    "distinguishable_origin",
    "identifiable_source_evidence",
    "deterministic_parser",
    "explicit_listing_detail_conflicts",
    "measured_quality",
    "python_typescript_agreement",
    "tested_export_hash_history",
    "demonstrated_downstream_utility",
)

_CORE_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "provider_id",
    "board_key",
    "remote_id",
    "title",
    "company",
    "status",
    "posting_url",
    "apply_url",
    "posted_at",
    "first_seen_at",
    "synced_at",
)
_SEARCH_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "provider_id",
    "board_key",
    "remote_id",
    "title",
    "company",
    "status",
    "posting_url",
    "locations",
    "remote",
    "employment_type",
    "department",
    "skills",
    "seniority",
    "posted_at",
)
_RAW_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "provider_id",
    "board_key",
    "remote_id",
    "raw_listing",
    "raw_detail",
)
SEARCH_PROFILE_FIELDS: Final[frozenset[str]] = frozenset(_SEARCH_FIELDS)


def project_job(record: JobRecord, profile: str) -> dict[str, object]:
    """Project a job record into a JSON-ready named profile envelope."""

    dumped = record.model_dump(mode="json")
    match profile:
        case "full":
            projected: dict[str, object] = dict(dumped)
        case "core":
            projected = {key: dumped[key] for key in _CORE_FIELDS}
        case "search":
            projected = {key: dumped[key] for key in _SEARCH_FIELDS}
        case "raw":
            projected = {key: dumped[key] for key in _RAW_FIELDS}
        case _:
            raise ValueError(f"unknown profile: {profile!r}")
    projected["profile"] = profile
    projected["schemaVersion"] = SCHEMA_VERSION
    projected["origins"] = _origin_tags(record, projected)
    return projected


def _origin_tags(
    record: JobRecord,
    projected: Mapping[str, object],
) -> dict[str, str]:
    tags: dict[str, str] = {}
    for observation in build_companion_observations(record):
        field_name = observation.field_name
        if field_name in projected:
            tags[field_name] = origin_tag(observation.origin)
    return tags


__all__ = [
    "DEFAULT_CLI_PROFILE",
    "DEFAULT_WEB_PROFILE",
    "FIELD_PROMOTION_RUBRIC",
    "JobProfileName",
    "PROFILE_NAMES",
    "SCHEMA_VERSION",
    "SEARCH_PROFILE_FIELDS",
    "project_job",
]
