from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from openopps.models import JobRecord, derive_seniority, extract_job_skills
from openopps.observations import (
    Origin,
    Observation,
    build_companion_observations,
    origin_tag,
)


CLOSED_ORIGINS = frozenset(
    {"provider_observed", "openopps_derived", "editorial"}
)
COMPANION_FIELDS = (
    "field_name",
    "origin",
    "source_path",
    "listing_vs_detail",
    "method",
    "version",
    "conflict_state",
    "evidence",
)


def _origin_values() -> set[str]:
    if isinstance(Origin, type) and issubclass(Origin, Enum):
        return {str(item.value) for item in Origin}
    args = get_args(Origin)
    if args:
        return {str(arg) for arg in args}
    raise AssertionError("Origin must be a StrEnum or Literal alias")


def _origin_str(origin: object) -> str:
    value = getattr(origin, "value", origin)
    return str(value)


def _observation(**overrides: Any) -> Observation:
    payload: dict[str, Any] = {
        "field_name": "title",
        "origin": "provider_observed",
        "source_path": "raw_listing.title",
        "listing_vs_detail": "listing",
        "method": "provider",
        "version": "1",
        "conflict_state": "none",
        "evidence": "raw_listing",
    }
    payload.update(overrides)
    return Observation(**payload)


def _job(
    *,
    title: str = "Senior Platform Engineer",
    company: str = "Acme",
    status: str = "open",
    description: str = (
        "Build Python and TypeScript services with Kubernetes, "
        "PostgreSQL, React, and machine learning workflows."
    ),
    listing_title: str | None = None,
    detail_title: str | None = None,
    skills: list[dict[str, object]] | None = None,
) -> JobRecord:
    listing_title = title if listing_title is None else listing_title
    detail_title = title if detail_title is None else detail_title
    payload: dict[str, object] = {
        "id": "acme:greenhouse:1",
        "board_key": "acme",
        "provider_id": "greenhouse",
        "remote_id": "1",
        "title": title,
        "company": company,
        "status": status,
        "description": description,
        "posting_url": "https://boards.greenhouse.io/acme/jobs/1",
        "raw_listing": {"id": "1", "title": listing_title, "company": company},
        "raw_detail": {
            "id": "1",
            "title": detail_title,
            "description": description,
        },
    }
    if skills is not None:
        payload["skills"] = skills
    return JobRecord.model_validate(payload)


def _by_field(observations: Sequence[Observation]) -> dict[str, list[Observation]]:
    grouped: dict[str, list[Observation]] = {}
    for item in observations:
        grouped.setdefault(item.field_name, []).append(item)
    return grouped


def _origins_for(observations: Sequence[Observation], field_name: str) -> set[str]:
    return {_origin_str(item.origin) for item in _by_field(observations)[field_name]}


def test_origin_is_closed_provider_observed_derived_editorial() -> None:
    assert _origin_values() == CLOSED_ORIGINS
    for origin in CLOSED_ORIGINS:
        tagged = origin_tag(origin)
        assert tagged == origin
        observed = _observation(origin=origin)
        assert _origin_str(observed.origin) == origin
        assert _origin_str(observed.origin) in CLOSED_ORIGINS

    with pytest.raises(ValidationError):
        _observation(origin="guessed")
    with pytest.raises((KeyError, ValueError, ValidationError)):
        origin_tag("guessed")


def test_provider_observed_observations_do_not_require_confidence() -> None:
    fields = Observation.model_fields
    confidence = fields.get("confidence")
    assert confidence is None or not confidence.is_required
    assert "confidence" not in (
        name for name, field in fields.items() if field.is_required
    )

    observed = _observation()
    assert _origin_str(observed.origin) == "provider_observed"
    assert getattr(observed, "confidence", None) is None

    derived = _observation(
        field_name="seniority",
        origin="openopps_derived",
        source_path="title",
        listing_vs_detail="listing",
        method="derive_seniority",
        notes="derived from title and experience",
    )
    assert _origin_str(derived.origin) == "openopps_derived"
    assert getattr(derived, "confidence", None) is None
    assert derived.notes == "derived from title and experience"

    editorial = _observation(
        field_name="company",
        origin="editorial",
        source_path="editorial.company",
        method="editorial",
        evidence="editorial",
    )
    assert _origin_str(editorial.origin) == "editorial"
    assert getattr(editorial, "confidence", None) is None


def test_companion_observations_exist_without_alembic() -> None:
    import openopps.observations as observations_mod

    job = _job()
    companions = build_companion_observations(job)

    assert Path(observations_mod.__file__).name == "observations.py"
    assert getattr(Observation, "__tablename__", None) is None
    assert getattr(Observation, "__table__", None) is None
    assert isinstance(companions, list)
    assert companions
    assert all(isinstance(item, Observation) for item in companions)

    tree = ast.parse(Path(observations_mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "alembic" not in imported
    assert "sqlalchemy" not in imported

    for item in companions:
        for name in COMPANION_FIELDS:
            assert hasattr(item, name)
        assert item.field_name
        assert _origin_str(item.origin) in CLOSED_ORIGINS
        assert item.source_path
        assert item.listing_vs_detail in {"listing", "detail"}
        assert item.method
        assert item.conflict_state in {"none", "listing_detail"}
        assert item.evidence
        if isinstance(item.evidence, str):
            assert item.evidence.strip()
        elif isinstance(item.evidence, Mapping):
            assert item.evidence

    grouped = _by_field(companions)
    title = grouped["title"][0]
    assert title.listing_vs_detail == "listing"
    assert "title" in title.source_path
    assert title.conflict_state == "none"

    conflicting = build_companion_observations(
        _job(listing_title="Senior Platform Engineer", detail_title="Staff Engineer")
    )
    conflict_title = _by_field(conflicting)["title"][0]
    assert conflict_title.conflict_state == "listing_detail"
    assert _origin_str(conflict_title.origin) == "provider_observed"


def test_derived_skills_and_seniority_are_not_provider_observed() -> None:
    job = _job()
    assert job.skills
    assert job.skills == extract_job_skills(job)
    assert job.seniority == derive_seniority(job) == "Senior"

    companions = build_companion_observations(job)
    grouped = _by_field(companions)

    assert _origins_for(companions, "title") == {"provider_observed"}
    assert _origins_for(companions, "company") == {"provider_observed"}
    assert _origins_for(companions, "status") == {"provider_observed"}
    assert _origins_for(companions, "skills") == {"openopps_derived"}
    assert _origins_for(companions, "seniority") == {"openopps_derived"}

    skills = grouped["skills"][0]
    seniority = grouped["seniority"][0]
    assert skills.method == "extract_job_skills"
    assert seniority.method == "derive_seniority"
    assert origin_tag(skills.origin) == "openopps_derived"
    assert origin_tag(seniority.origin) == "openopps_derived"
    assert origin_tag(grouped["title"][0].origin) == "provider_observed"

    supplied = _job(skills=[{"name": "Backend", "keywords": ["Python"]}])
    assert [skill.name for skill in supplied.skills] == ["Backend"]
    assert supplied.seniority == derive_seniority(supplied) == "Senior"
    supplied_companions = build_companion_observations(supplied)
    assert _origins_for(supplied_companions, "skills") == {"provider_observed"}
    assert _origins_for(supplied_companions, "seniority") == {"openopps_derived"}
    assert _origins_for(supplied_companions, "title") == {"provider_observed"}
