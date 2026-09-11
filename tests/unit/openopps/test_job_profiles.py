from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from openopps.job_profiles import (
    DEFAULT_CLI_PROFILE,
    DEFAULT_WEB_PROFILE,
    FIELD_PROMOTION_RUBRIC,
    PROFILE_NAMES,
    SCHEMA_VERSION,
    SEARCH_PROFILE_FIELDS,
    project_job,
)
from openopps.models import JobDescriptionSkill, JobRecord, job_content_hash, job_payload_hash

ENVELOPE_KEYS = frozenset({"profile", "schemaVersion", "origins"})
IDENTITY_KEYS = frozenset({"id", "provider_id", "board_key", "remote_id"})
CORE_BODY_KEYS = frozenset(
    {
        "title",
        "company",
        "status",
        "posting_url",
        "apply_url",
        "posted_at",
        "first_seen_at",
        "synced_at",
    }
)
SEARCH_FILTER_KEYS = frozenset(
    {
        "locations",
        "remote",
        "employment_type",
        "department",
        "skills",
        "seniority",
        "posted_at",
    }
)
UNRESTRICTED_JOB_KEYS = frozenset(
    {
        "raw_listing",
        "raw_detail",
        "description_html",
        "provider_extras",
        "job_description",
        "compensation",
        "responsibilities",
        "qualifications",
    }
)
NORMALIZED_FULL_KEYS = frozenset(
    {
        "description",
        "team",
        "workplace_type",
        "content_hash",
        "payload_hash",
    }
)
SEEN_AT = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
SYNCED_AT = datetime(2026, 6, 2, 8, 30, tzinfo=timezone.utc)


def _job() -> JobRecord:
    record = JobRecord(
        id="acme:greenhouse:12345",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="12345",
        title="Senior Software Engineer",
        company="Acme",
        status="open",
        department="Engineering",
        team="Platform",
        workplace_type="Remote",
        employment_type="Full-time",
        remote="Full",
        locations=["New York, NY", "Remote"],
        seniority="Senior",
        skills=[
            JobDescriptionSkill(name="Python", level="expert", keywords=["FastAPI"]),
        ],
        description="Build reliable systems for customers.",
        description_html="<p>Build reliable systems for customers.</p>",
        posting_url="https://boards.greenhouse.io/acme/jobs/12345",
        apply_url="https://boards.greenhouse.io/acme/jobs/12345/apply",
        posted_at="2026-05-16T12:34:56Z",
        first_seen_at=SEEN_AT,
        synced_at=SYNCED_AT,
        raw_listing={"id": 12345, "title": "Senior Software Engineer"},
        raw_detail={"content": "Build reliable systems for customers."},
        provider_extras={"greenhouse": {"requisitionId": "50"}},
        compensation={"currency": "USD", "minValue": 160000, "maxValue": 210000},
        responsibilities=["Own the listing kernel."],
        qualifications=["Python"],
    )
    return record.model_copy(
        update={
            "content_hash": job_content_hash(record),
            "payload_hash": job_payload_hash(record),
        }
    )


def _project(profile: str) -> dict[str, object]:
    projected = project_job(_job(), profile)
    assert type(projected) is dict
    return projected


def test_profile_names_are_core_search_full_raw() -> None:
    assert PROFILE_NAMES == ("core", "search", "full", "raw")


def test_schema_version_starts_at_one() -> None:
    assert type(SCHEMA_VERSION) is int
    assert SCHEMA_VERSION == 1


def test_default_cli_profile_is_full() -> None:
    assert DEFAULT_CLI_PROFILE == "full"
    assert DEFAULT_CLI_PROFILE in PROFILE_NAMES


def test_default_web_profile_is_search() -> None:
    assert DEFAULT_WEB_PROFILE == "search"
    assert DEFAULT_WEB_PROFILE in PROFILE_NAMES
    assert DEFAULT_WEB_PROFILE != DEFAULT_CLI_PROFILE


@pytest.mark.parametrize("profile", ("core", "search", "full", "raw"))
def test_project_job_identifies_profile_and_schema_version(profile: str) -> None:
    projected = _project(profile)

    assert projected["profile"] == profile
    assert projected["schemaVersion"] == SCHEMA_VERSION
    assert type(projected["schemaVersion"]) is int
    assert "schema_version" not in projected
    assert ENVELOPE_KEYS <= projected.keys()


@pytest.mark.parametrize("profile", ("core", "search", "full", "raw"))
def test_projected_jobs_are_json_ready(profile: str) -> None:
    projected = _project(profile)

    encoded = json.dumps(projected)
    restored = json.loads(encoded)

    assert restored["profile"] == profile
    assert restored["schemaVersion"] == SCHEMA_VERSION
    assert restored["id"] == "acme:greenhouse:12345"


def test_core_profile_carries_identity_title_company_status_urls_and_dates() -> None:
    projected = _project("core")

    assert IDENTITY_KEYS | CORE_BODY_KEYS | ENVELOPE_KEYS <= projected.keys()
    assert projected["id"] == "acme:greenhouse:12345"
    assert projected["provider_id"] == "greenhouse"
    assert projected["board_key"] == "acme"
    assert projected["remote_id"] == "12345"
    assert projected["title"] == "Senior Software Engineer"
    assert projected["company"] == "Acme"
    assert projected["status"] == "open"
    assert projected["posting_url"] == "https://boards.greenhouse.io/acme/jobs/12345"
    assert projected["apply_url"] == "https://boards.greenhouse.io/acme/jobs/12345/apply"
    assert projected["posted_at"] == "2026-05-16T12:34:56Z"
    assert isinstance(projected["first_seen_at"], str)
    assert isinstance(projected["synced_at"], str)
    assert "postingUrl" not in projected


def test_core_profile_omits_raw_payloads_and_search_extras() -> None:
    projected = _project("core")

    assert UNRESTRICTED_JOB_KEYS.isdisjoint(projected)
    assert {"locations", "remote", "employment_type", "department", "skills", "seniority"}.isdisjoint(
        projected
    )


def test_search_profile_carries_governed_filter_rank_fields() -> None:
    projected = _project("search")

    assert IDENTITY_KEYS | SEARCH_FILTER_KEYS | ENVELOPE_KEYS <= projected.keys()
    assert projected["title"] == "Senior Software Engineer"
    assert projected["company"] == "Acme"
    assert projected["status"] == "open"
    assert projected["posting_url"] == "https://boards.greenhouse.io/acme/jobs/12345"
    assert projected["locations"] == ["New York, NY", "Remote"]
    assert projected["remote"] == "Full"
    assert projected["employment_type"] == "Full-time"
    assert projected["department"] == "Engineering"
    assert projected["seniority"] == "Senior"
    assert projected["posted_at"] == "2026-05-16T12:34:56Z"
    assert isinstance(projected["skills"], list)
    assert projected["skills"]


def test_search_profile_does_not_dump_unrestricted_job_record() -> None:
    record = _job()
    projected = project_job(record, "search")
    dumped = record.model_dump(mode="json")

    assert UNRESTRICTED_JOB_KEYS.isdisjoint(projected)
    assert set(projected) != set(dumped)
    assert set(projected) - ENVELOPE_KEYS < set(dumped)
    assert "payloadSnapshots" not in projected


def test_full_profile_carries_normalized_record_and_provenance() -> None:
    record = _job()
    projected = project_job(record, "full")

    assert IDENTITY_KEYS | NORMALIZED_FULL_KEYS | ENVELOPE_KEYS <= projected.keys()
    assert projected["provider_id"] == "greenhouse"
    assert projected["description"] == "Build reliable systems for customers."
    assert projected["team"] == "Platform"
    assert projected["workplace_type"] == "Remote"
    assert projected["content_hash"] == record.content_hash
    assert projected["payload_hash"] == record.payload_hash
    assert projected["profile"] == "full"
    assert projected["schemaVersion"] == SCHEMA_VERSION


def test_raw_profile_carries_listing_and_detail_evidence() -> None:
    projected = _project("raw")

    assert IDENTITY_KEYS | ENVELOPE_KEYS <= projected.keys()
    assert projected["raw_listing"] == {"id": 12345, "title": "Senior Software Engineer"}
    assert projected["raw_detail"] == {"content": "Build reliable systems for customers."}
    assert projected["raw_listing"] != projected["raw_detail"]
    assert "description" not in projected
    assert "skills" not in projected
    assert "description_html" not in projected
    assert "provider_extras" not in projected


def test_named_profiles_have_distinct_field_sets() -> None:
    record = _job()
    field_sets = {
        name: frozenset(project_job(record, name)) for name in PROFILE_NAMES
    }

    assert tuple(field_sets) == PROFILE_NAMES
    assert len(set(field_sets.values())) == len(PROFILE_NAMES)
    assert field_sets["core"].isdisjoint(UNRESTRICTED_JOB_KEYS)
    assert field_sets["search"].isdisjoint(UNRESTRICTED_JOB_KEYS)
    assert {"raw_listing", "raw_detail"} <= field_sets["raw"]
    assert {"description", "content_hash", "payload_hash"} <= field_sets["full"]
    assert not {"description", "content_hash", "payload_hash"} <= field_sets["raw"]
    assert SEARCH_FILTER_KEYS <= field_sets["search"]
    assert not SEARCH_FILTER_KEYS <= field_sets["core"]


def test_project_job_does_not_mutate_record() -> None:
    record = _job()
    before = record.model_dump(mode="json")

    project_job(record, "core")
    project_job(record, "search")
    project_job(record, "full")
    project_job(record, "raw")

    assert record.model_dump(mode="json") == before


@pytest.mark.parametrize("profile", ("", "all", "json", "Core", "search "))
def test_project_job_rejects_unknown_profile(profile: str) -> None:
    with pytest.raises(ValueError, match="profile"):
        project_job(_job(), profile)


def test_projection_origin_tags_distinguish_derived_from_observed() -> None:
    record = JobRecord(
        id="acme:greenhouse:1",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="1",
        title="Senior Platform Engineer",
        company="Acme",
        status="open",
        description=(
            "Build Python and TypeScript services with Kubernetes, "
            "PostgreSQL, React, and machine learning workflows."
        ),
        posting_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    projected = project_job(record, "search")
    origins = projected["origins"]

    assert isinstance(origins, dict)
    assert origins["title"] == "provider_observed"
    assert origins["company"] == "provider_observed"
    assert origins["status"] == "provider_observed"
    assert origins["skills"] == "openopps_derived"
    assert origins["seniority"] == "openopps_derived"
    assert "confidence" not in projected
    assert origins["skills"] != origins["title"]


def test_search_fields_require_documented_promotion_gate() -> None:
    assert SEARCH_PROFILE_FIELDS == frozenset(
        {
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
        }
    )
    assert "postedAt" not in SEARCH_PROFILE_FIELDS
    assert "postingUrl" not in SEARCH_PROFILE_FIELDS
    assert "payloadSnapshots" not in SEARCH_PROFILE_FIELDS
    assert set(FIELD_PROMOTION_RUBRIC) == {
        "documented_semantics",
        "distinguishable_origin",
        "identifiable_source_evidence",
        "deterministic_parser",
        "explicit_listing_detail_conflicts",
        "measured_quality",
        "python_typescript_agreement",
        "tested_export_hash_history",
        "demonstrated_downstream_utility",
    }
    proposed = SEARCH_PROFILE_FIELDS | {"compensation"}
    assert proposed != SEARCH_PROFILE_FIELDS
