from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from openopps.export import export_records
from openopps.job_profiles import DEFAULT_CLI_PROFILE, SCHEMA_VERSION, project_job
from openopps.models import ExportFormat, JobRecord, job_content_hash, job_payload_hash


def _job() -> JobRecord:
    record = JobRecord(
        id="acme:greenhouse:12345",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="12345",
        title="Senior Software Engineer",
        company="Acme",
        status="open",
        posting_url="https://boards.greenhouse.io/acme/jobs/12345",
        posted_at="2026-05-16T12:34:56Z",
        first_seen_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        synced_at=datetime(2026, 6, 2, 8, 30, tzinfo=timezone.utc),
        raw_listing={"id": 12345},
        raw_detail={"content": "details"},
    )
    return record.model_copy(
        update={
            "content_hash": job_content_hash(record),
            "payload_hash": job_payload_hash(record),
        }
    )


def test_jsonl_export_identifies_profile_and_schema_version(tmp_path: Path) -> None:
    output = tmp_path / "jobs.jsonl"
    record = _job()

    count = export_records([record], output, ExportFormat.JSONL)

    assert count == 1
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row == project_job(record, DEFAULT_CLI_PROFILE)
    assert row["profile"] == DEFAULT_CLI_PROFILE
    assert row["schemaVersion"] == SCHEMA_VERSION
    assert row["id"] == record.id


def test_jsonl_export_honors_named_profile(tmp_path: Path) -> None:
    output = tmp_path / "jobs.jsonl"
    record = _job()

    count = export_records([record], output, ExportFormat.JSONL, profile="core")

    assert count == 1
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row == project_job(record, "core")
    assert row["profile"] == "core"
    assert "raw_listing" not in row
    assert "raw_detail" not in row
