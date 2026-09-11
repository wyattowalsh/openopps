"""Companion observations computed at projection time.

These records distinguish provider-observed, derived, and editorial field
origins without a persistence table or Alembic revision. Callers project them
from an in-memory ``JobRecord``; nothing here writes SQLite.

``JobRecord._populate_enriched_fields`` still fills empty skills/seniority.
This module is the T066 seam: those filled values are tagged
``openopps_derived`` at projection time so they cannot look
``provider_observed``. ``models.py`` stays owned by the storage campaign.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openopps.models import JobRecord, derive_seniority, extract_job_skills


COMPANION_VERSION = "1"
PROVIDER_METHOD = "provider"

ListingVsDetail = Literal["listing", "detail"]
ConflictState = Literal["none", "listing_detail"]
ObservationEvidence = str | dict[str, object]


class Origin(StrEnum):
    """Closed origin tags for companion field observations."""

    PROVIDER_OBSERVED = "provider_observed"
    OPENOPPS_DERIVED = "openopps_derived"
    EDITORIAL = "editorial"


class Observation(BaseModel):
    """In-memory companion record for one projected job field."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    field_name: str = Field(min_length=1)
    origin: Origin
    source_path: str = Field(min_length=1)
    listing_vs_detail: ListingVsDetail
    method: str = Field(min_length=1)
    version: str = Field(min_length=1)
    conflict_state: ConflictState
    evidence: ObservationEvidence
    notes: str | None = None


def origin_tag(origin: Origin | str) -> str:
    """Return the compact closed origin tag for ``origin``."""

    try:
        return Origin(origin).value
    except ValueError as exc:
        raise ValueError(f"unknown origin: {origin!r}") from exc


def build_companion_observations(job: JobRecord) -> list[Observation]:
    """Return in-memory companion observations for a normalized job."""

    companions: list[Observation] = [
        _provider_field_observation(job, "title", job.title),
        _provider_field_observation(job, "status", job.status),
    ]
    if job.company:
        companions.append(_provider_field_observation(job, "company", job.company))
    skills_observation = _skills_observation(job)
    if skills_observation is not None:
        companions.append(skills_observation)
    seniority_observation = _seniority_observation(job)
    if seniority_observation is not None:
        companions.append(seniority_observation)
    return companions


def _provider_field_observation(
    job: JobRecord,
    field_name: str,
    current: str | None,
) -> Observation:
    listing_vs_detail = _choose_listing_vs_detail(job, field_name, current)
    conflict_state    = _conflict_state(job, field_name)
    return _companion(
        field_name=field_name,
        origin=Origin.PROVIDER_OBSERVED,
        source_path=_provider_source_path(field_name, listing_vs_detail),
        listing_vs_detail=listing_vs_detail,
        method=PROVIDER_METHOD,
        conflict_state=conflict_state,
        evidence=_provider_evidence(listing_vs_detail, conflict_state),
    )


def _skills_observation(job: JobRecord) -> Observation | None:
    if not job.skills:
        return None
    derived = extract_job_skills(job)
    if derived and job.skills == derived:
        source_path, listing_vs_detail, evidence = _derived_skill_source(job)
        return _companion(
            field_name="skills",
            origin=Origin.OPENOPPS_DERIVED,
            source_path=source_path,
            listing_vs_detail=listing_vs_detail,
            method="extract_job_skills",
            conflict_state="none",
            evidence=evidence,
        )
    listing_vs_detail = _choose_listing_vs_detail(job, "skills", None)
    conflict_state    = _conflict_state(job, "skills")
    return _companion(
        field_name="skills",
        origin=Origin.PROVIDER_OBSERVED,
        source_path=_provider_source_path("skills", listing_vs_detail),
        listing_vs_detail=listing_vs_detail,
        method=PROVIDER_METHOD,
        conflict_state=conflict_state,
        evidence=_provider_evidence(listing_vs_detail, conflict_state),
    )


def _seniority_observation(job: JobRecord) -> Observation | None:
    if not job.seniority:
        return None
    derived = derive_seniority(job)
    if derived and job.seniority == derived:
        return _companion(
            field_name="seniority",
            origin=Origin.OPENOPPS_DERIVED,
            source_path="title",
            listing_vs_detail="listing",
            method="derive_seniority",
            conflict_state="none",
            evidence="title",
        )
    listing_vs_detail = _choose_listing_vs_detail(job, "seniority", job.seniority)
    conflict_state    = _conflict_state(job, "seniority")
    return _companion(
        field_name="seniority",
        origin=Origin.PROVIDER_OBSERVED,
        source_path=_provider_source_path("seniority", listing_vs_detail),
        listing_vs_detail=listing_vs_detail,
        method=PROVIDER_METHOD,
        conflict_state=conflict_state,
        evidence=_provider_evidence(listing_vs_detail, conflict_state),
    )


def _derived_skill_source(
    job: JobRecord,
) -> tuple[str, ListingVsDetail, ObservationEvidence]:
    if job.description or job.description_html:
        return "description", "detail", "raw_detail"
    return "title", "listing", "raw_listing"


def _companion(
    *,
    field_name: str,
    origin: Origin,
    source_path: str,
    listing_vs_detail: ListingVsDetail,
    method: str,
    conflict_state: ConflictState,
    evidence: ObservationEvidence,
    notes: str | None = None,
) -> Observation:
    return Observation(
        field_name=field_name,
        origin=origin,
        source_path=source_path,
        listing_vs_detail=listing_vs_detail,
        method=method,
        version=COMPANION_VERSION,
        conflict_state=conflict_state,
        evidence=evidence,
        notes=notes,
    )


def _choose_listing_vs_detail(
    job: JobRecord,
    field_name: str,
    current: str | None,
) -> ListingVsDetail:
    listing_value = _raw_text(job.raw_listing, field_name)
    detail_value  = _raw_text(job.raw_detail, field_name)
    if current is not None:
        if listing_value == current:
            return "listing"
        if detail_value == current:
            return "detail"
    if listing_value is not None:
        return "listing"
    if detail_value is not None:
        return "detail"
    return "listing"


def _conflict_state(job: JobRecord, field_name: str) -> ConflictState:
    listing_value = _raw_text(job.raw_listing, field_name)
    detail_value  = _raw_text(job.raw_detail, field_name)
    if (
        listing_value is not None
        and detail_value is not None
        and listing_value != detail_value
    ):
        return "listing_detail"
    return "none"


def _provider_source_path(field_name: str, listing_vs_detail: ListingVsDetail) -> str:
    prefix = "raw_detail" if listing_vs_detail == "detail" else "raw_listing"
    return f"{prefix}.{field_name}"


def _provider_evidence(
    listing_vs_detail: ListingVsDetail,
    conflict_state: ConflictState,
) -> ObservationEvidence:
    if conflict_state == "listing_detail":
        return {"listing": "raw_listing", "detail": "raw_detail"}
    if listing_vs_detail == "detail":
        return "raw_detail"
    return "raw_listing"


def _raw_text(payload: object, field_name: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(field_name)
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "COMPANION_VERSION",
    "Observation",
    "Origin",
    "build_companion_observations",
    "origin_tag",
]
