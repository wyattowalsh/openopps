import json
from pathlib import Path
import sqlite3

import polars as pl
from pydantic import ValidationError
import pytest
from sqlalchemy import event

import openopps.storage as storage_module
from openopps.export import export_records
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ExportFormat,
    JobRecord,
    ProviderSupport,
    SourceRecord,
    job_payload_hash,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import BoardFilters, JobFilters, OpenOppsStore, append_jsonl
from openopps.storage import report_job_version_dual_write_mismatches

from _fixtures.store import seeded_filter_store


def test_board_provider_upsert_preserves_executable_route_metadata(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="manual://a16z", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="a16z", remote_id="acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:greenhouse",
                source_key="a16z",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                count_hint=1,
                token="acme",
                board_url="https://boards.greenhouse.io/acme",
                last_status="route_ready",
            )
        ]
    )

    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:greenhouse",
                source_key="a16z",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                count_hint=3,
                raw_payload={"id": "greenhouse", "count": 3},
            )
        ]
    )

    stored = store.list_board_providers(provider_id="greenhouse")[0]
    assert stored.token == "acme"
    assert stored.board_url == "https://boards.greenhouse.io/acme"
    assert stored.last_status == "route_ready"
    assert stored.count_hint == 3
    assert stored.raw_payload == {"id": "greenhouse", "count": 3}


def test_deactivated_provider_route_survives_hint_only_refresh(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="manual://a16z", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="a16z", remote_id="acme", name="Acme")]
    )
    route = BoardProviderRecord(
        id="a16z:acme:greenhouse",
        source_key="a16z",
        board_key="acme",
        provider_id="greenhouse",
        support_level=ProviderSupport.JOBS,
        token="acme",
        last_status="route_ready",
    )
    store.upsert_board_providers([route])
    stored_route = store.list_board_providers(provider_id="greenhouse")[0]

    store.deactivate_board_provider_route(
        stored_route, status="job_sync_unavailable_404"
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:greenhouse",
                source_key="a16z",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )

    stored = store.list_board_providers(provider_id="greenhouse")[0]
    assert stored.support_level == ProviderSupport.DETECT
    assert stored.last_status == "job_sync_unavailable_404"
    assert stored.token == "acme"


def test_storage_roundtrip_and_export(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:lever",
                source_key="manual",
                board_key="acme",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                token="acme",
            )
        ]
    )
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": "acme:lever:1",
                    "board_key": "acme",
                    "provider_id": "lever",
                    "remote_id": "1",
                    "title": "Engineer",
                    "company": "Acme",
                    "employment_type": "Full-time",
                    "description": "Build reliable data systems.",
                    "remote": "Hybrid",
                    "compensation": {"currency": "USD", "min": 100000, "max": 160000},
                    "salary": "USD 100000 - 160000",
                    "salary_min": 100000,
                    "salary_max": 160000,
                    "salary_currency": "USD",
                    "responsibilities": ["Build pipelines"],
                    "qualifications": ["Know Python"],
                    "upstream_score": 0.98,
                }
            )
        ]
    )

    assert store.status() == {"sources": 1, "boards": 1, "boardProviders": 1, "jobs": 1}
    assert store.list_boards()[0].providers[0].provider_id == "lever"
    stored_job = store.get_job("acme:lever:1")
    assert stored_job is not None
    assert stored_job.model_dump()["compensation"] == {
        "currency": "USD",
        "min": 100000,
        "max": 160000,
    }
    assert stored_job.company == "Acme"
    assert stored_job.remote == "Hybrid"
    assert stored_job.salary_min == 100000
    assert stored_job.job_description is not None
    assert stored_job.job_description.type == "Full-time"
    assert stored_job.job_description.responsibilities == ["Build pipelines"]
    assert stored_job.model_dump()["upstream_score"] == 0.98

    jsonl_output = tmp_path / "jobs.jsonl"
    assert export_records(store.list_jobs(), jsonl_output, ExportFormat.JSONL) == 1
    jsonl_row = json.loads(jsonl_output.read_text().strip())
    assert jsonl_row["job_description"]["title"] == "Engineer"
    assert jsonl_row["job_description"]["type"] == "Full-time"

    csv_output = tmp_path / "jobs.csv"
    assert export_records(store.list_jobs(), csv_output, ExportFormat.CSV) == 1
    assert "job_description" in csv_output.read_text()
    assert "Build pipelines" in csv_output.read_text()

    parquet_output = tmp_path / "jobs.parquet"
    assert export_records(store.list_jobs(), parquet_output, ExportFormat.PARQUET) == 1
    parquet_rows = pl.read_parquet(parquet_output).to_dicts()
    assert parquet_rows[0]["salary_currency"] == "USD"
    assert json.loads(parquet_rows[0]["job_description"])["company"] == "Acme"

    sqlite_output = tmp_path / "jobs.sqlite"
    assert (
        export_records(
            store.list_jobs(),
            sqlite_output,
            ExportFormat.SQLITE,
            sqlite_table="jobs",
            metadata={"filters": {"status": "open"}},
        )
        == 1
    )
    with sqlite3.connect(sqlite_output) as conn:
        conn.row_factory = sqlite3.Row
        exported = conn.execute("SELECT * FROM jobs").fetchone()
        metadata = {
            row["key"]: json.loads(row["value"])
            for row in conn.execute("SELECT key, value FROM _openopps_export_metadata")
        }
    assert exported is not None
    assert exported["salary_currency"] == "USD"
    assert json.loads(exported["job_description"])["company"] == "Acme"
    assert metadata["entity"] == "jobs"
    assert metadata["row_count"] == 1
    assert metadata["filters"] == {"status": "open"}
    assert metadata["export_format"] == "sqlite"


@pytest.mark.parametrize("field_name", ["enabled", "disabled"])
@pytest.mark.parametrize("payload_wrapper", ["top-level", "extra-payload"])
def test_source_enablement_extras_are_rejected(field_name: str, payload_wrapper: str):
    payload = (
        {field_name: True}
        if payload_wrapper == "top-level"
        else {"extra_payload": {field_name: True}}
    )
    with pytest.raises(ValidationError, match="do not support enablement"):
        SourceRecord(
            key="legacy",
            url="https://jobs.example.com/companies",
            provider_id="getro",
            **payload,
        )


def test_job_sync_tracks_versions_raw_drift_and_lifecycle(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    store.init_db()
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:lever",
                source_key="manual",
                board_key="acme",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )
    original = JobRecord.model_validate(
        {
            "id": "acme:lever:1",
            "board_key": "acme",
            "provider_id": "lever",
            "remote_id": "1",
            "title": "Engineer",
            "company": "Acme",
            "description": "Build reliable data systems.",
            "raw_listing": {"id": "1", "title": "Engineer", "token": "a"},
        }
    )
    raw_drift = original.model_copy(
        update={"raw_listing": {"token": "b", "title": "Engineer", "id": "1"}}
    )
    changed = raw_drift.model_copy(
        update={
            "description": "Build reliable data systems and tools.",
            "raw_listing": {"id": "1", "title": "Engineer", "token": "c"},
        }
    )

    first_run = store.sync_jobs_for_route("acme", "lever", [original])
    repeat_run = store.sync_jobs_for_route("acme", "lever", [raw_drift])
    changed_run = store.sync_jobs_for_route("acme", "lever", [changed])
    closed_run = store.sync_jobs_for_route("acme", "lever", [])

    assert first_run.new_count == 1
    assert repeat_run.unchanged_count == 1
    assert changed_run.changed_count == 1
    assert closed_run.closed_count == 1
    assert [job.version for job in store.list_job_versions("acme:lever:1")] == [1, 2]
    assert store.list_jobs() == []
    closed_jobs = store.list_jobs(filters=JobFilters(status="all"))
    assert [job.status for job in closed_jobs] == ["closed"]
    assert closed_jobs[0].payload_hash == job_payload_hash(changed)

    with sqlite3.connect(db_path) as conn:
        payload_snapshots = conn.execute(
            "SELECT COUNT(*) FROM job_payload_snapshots WHERE job_id = ?",
            ("acme:lever:1",),
        ).fetchone()[0]
        observations = conn.execute(
            "SELECT observation_kind FROM job_sync_observations ORDER BY rowid"
        ).fetchall()

    assert payload_snapshots == 3
    assert [row[0] for row in observations] == [
        "new",
        "unchanged",
        "changed",
        "closed",
    ]


def test_job_sync_commits_progress_in_configured_batches_and_closes_once(
    tmp_path: Path,
):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{db_path}",
        db_batch_size=2,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    stale = JobRecord(
        id="acme:lever:stale",
        board_key="acme",
        provider_id="lever",
        remote_id="stale",
        title="Stale",
    )
    store.sync_jobs_for_route("acme", "lever", [stale])
    jobs = [
        JobRecord(
            id=f"acme:lever:{index}",
            board_key="acme",
            provider_id="lever",
            remote_id=str(index),
            title=f"Engineer {index}",
        )
        for index in range(5)
    ]

    pending = store.begin_job_sync_run("acme", "lever")
    completed = store.complete_job_sync_run(
        pending.id,
        jobs,
        authoritative=True,
        close_missing=True,
    )

    assert completed.status == "succeeded"
    assert completed.success is True
    assert completed.authoritative is True
    assert completed.committed_batch_count == 3
    assert completed.job_count == 5
    assert completed.new_count == 5
    assert completed.closed_count == 1
    assert completed.finished_at is not None
    with sqlite3.connect(db_path) as conn:
        closed_observations = conn.execute(
            """
            SELECT COUNT(*)
            FROM job_sync_observations
            WHERE sync_run_id = ? AND observation_kind = 'closed'
            """,
            (pending.id,),
        ).fetchone()[0]
    assert closed_observations == 1


def test_job_sync_batch_failure_preserves_progress_without_authoritative_closure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{db_path}",
        db_batch_size=2,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    stale = JobRecord(
        id="acme:lever:stale",
        board_key="acme",
        provider_id="lever",
        remote_id="stale",
        title="Stale",
    )
    store.sync_jobs_for_route("acme", "lever", [stale])
    jobs = [
        JobRecord(
            id=f"acme:lever:{index}",
            board_key="acme",
            provider_id="lever",
            remote_id=str(index),
            title=f"Engineer {index}",
        )
        for index in range(4)
    ]
    original_sync_job_record = storage_module._sync_job_record

    def fail_in_second_batch(session, job, observed_at):
        if job.remote_id == "2":
            raise RuntimeError("simulated persistence failure")
        return original_sync_job_record(session, job, observed_at)

    monkeypatch.setattr(storage_module, "_sync_job_record", fail_in_second_batch)
    pending = store.begin_job_sync_run("acme", "lever")

    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        store.complete_job_sync_run(
            pending.id,
            jobs,
            authoritative=True,
            close_missing=True,
        )

    with sqlite3.connect(db_path) as conn:
        run = conn.execute(
            """
            SELECT status, success, error_kind, job_count,
                   committed_batch_count, closed_count, finished_at, authoritative,
                   error
            FROM job_sync_runs
            WHERE id = ?
            """,
            (pending.id,),
        ).fetchone()
        stored_jobs = conn.execute(
            "SELECT remote_id, status FROM jobs ORDER BY remote_id"
        ).fetchall()

    assert run is not None
    assert run[:6] == ("failed", 0, "persistence", 2, 1, 0)
    assert run[6] is not None
    assert run[7] == 1
    assert run[8] == (
        "Persistence failed while committing normalized job batches: RuntimeError."
    )
    assert "simulated persistence failure" not in run[8]
    assert stored_jobs == [("0", "open"), ("1", "open"), ("stale", "open")]


def test_job_sync_failure_metadata_is_bounded(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    pending = store.begin_job_sync_run("acme", "lever")

    failed = store.fail_job_sync_run(
        pending.id,
        error_kind="k" * 256,
        error="e" * 4096,
    )

    assert failed.status == "failed"
    assert failed.success is False
    assert failed.authoritative is False
    assert len(failed.error_kind or "") == 128
    assert len(failed.error or "") == 2048


def test_current_job_hydration_uses_latest_payload_hash_without_mutating_version(
    tmp_path: Path,
):
    store = seeded_filter_store(tmp_path)
    original = JobRecord(
        id="acme:ashbyhq:payload-drift",
        board_key="acme",
        provider_id="ashbyhq",
        remote_id="payload-drift",
        title="Engineer",
        raw_listing={"id": "payload-drift", "revision": "original"},
    )
    raw_drift = original.model_copy(
        update={"raw_listing": {"id": "payload-drift", "revision": "latest"}}
    )

    store.sync_jobs_for_route("acme", "ashbyhq", [original], close_missing=False)
    store.sync_jobs_for_route("acme", "ashbyhq", [raw_drift], close_missing=False)

    current = store.get_job(original.id)
    listed = [
        job
        for job in store.list_jobs(
            filters=JobFilters(board_key="acme", provider_id="ashbyhq")
        )
        if job.id == original.id
    ]
    versions = store.list_job_versions(original.id)
    assert current is not None
    assert current.payload_hash == job_payload_hash(raw_drift)
    assert listed[0].payload_hash == job_payload_hash(raw_drift)
    assert versions[0].payload_hash == job_payload_hash(original)


def test_list_jobs_bulk_hydration_query_count_is_not_per_record(tmp_path: Path):
    store = seeded_filter_store(tmp_path)
    store.upsert_jobs(
        [
            JobRecord(
                id=f"acme:ashbyhq:bulk-{index}",
                board_key="acme",
                provider_id="ashbyhq",
                remote_id=f"bulk-{index}",
                title=f"Engineer {index}",
                locations=["Remote"],
                responsibilities=["Build"],
                qualifications=["Test"],
                skills=[{"name": "Backend", "keywords": ["Python"]}],
                raw_listing={"id": f"bulk-{index}"},
            )
            for index in range(12)
        ]
    )
    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(store.engine, "before_cursor_execute", count_selects)
    try:
        store.list_jobs(filters=JobFilters(limit=1))
        one_record_queries = select_count
        select_count = 0
        jobs = store.list_jobs()
        many_record_queries = select_count
    finally:
        event.remove(store.engine, "before_cursor_execute", count_selects)

    assert len(jobs) >= 12
    assert many_record_queries <= one_record_queries + 1
    assert many_record_queries < len(jobs)


def test_job_sync_dedupes_duplicate_jobs_in_one_route_run(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="manual",
                remote_id="acme",
                name="Acme",
            )
        ]
    )

    job = JobRecord.model_validate(
        {
            "id": "acme:lever:1",
            "board_key": "acme",
            "provider_id": "lever",
            "remote_id": "1",
            "title": "Engineer",
            "company": "Acme",
        }
    )

    run = store.sync_jobs_for_route("acme", "lever", [job, job])

    assert run.job_count == 1
    assert run.new_count == 1
    with sqlite3.connect(db_path) as conn:
        observations = conn.execute(
            "SELECT COUNT(*) FROM job_sync_observations"
        ).fetchone()[0]
    assert observations == 1


def test_boards_merge_cross_source_duplicates_by_domain(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(key="a16z", url="https://a16z.com/jobs", provider_id="consider")
    )
    store.upsert_source(
        SourceRecord(
            key="yc",
            url="https://www.ycombinator.com/companies",
            provider_id="ycombinator",
        )
    )
    a16z_board = BoardRecord(
        key="a16z:acme",
        source_key="a16z",
        remote_id="acme",
        name="Acme AI",
        domain="acme.ai",
    )
    yc_board = BoardRecord(
        key="yc:acme-ai",
        source_key="yc",
        remote_id="31503",
        name="Acme AI",
        domain="acme.ai",
    )
    store.upsert_boards([a16z_board, yc_board])
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="yc:yc-acme-ai:lever",
                source_key="yc",
                board_key="yc:acme-ai",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
            )
        ],
        boards=[yc_board],
    )

    boards = store.list_boards(domain="acme.ai")
    yc_boards = store.list_boards(source_key="yc")
    providers = store.list_board_providers(source_key="yc")

    assert store.status()["boards"] == 1
    assert [board.key for board in boards] == ["a16z:acme"]
    assert boards[0].source_keys == ["a16z", "yc"]
    assert boards[0].source_board_keys == {
        "a16z": "a16z:acme",
        "yc": "yc:acme-ai",
    }
    assert [board.key for board in yc_boards] == ["a16z:acme"]
    assert [(provider.source_key, provider.board_key) for provider in providers] == [
        ("yc", "a16z:acme")
    ]


def test_csv_export_neutralizes_spreadsheet_formulas_only(tmp_path: Path):
    dangerous = JobRecord(
        id="acme:greenhouse:formula",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="formula",
        title="=cmd|' /C calc'!A0",
        company="+Acme",
        employment_type="Full-time",
    )
    csv_output = tmp_path / "jobs.csv"
    jsonl_output = tmp_path / "jobs.jsonl"

    assert export_records([dangerous], csv_output, ExportFormat.CSV) == 1
    assert export_records([dangerous], jsonl_output, ExportFormat.JSONL) == 1

    csv_text = csv_output.read_text()
    jsonl_row = json.loads(jsonl_output.read_text())
    assert "'=cmd|'" in csv_text
    assert "'+Acme" in csv_text
    assert jsonl_row["title"] == "=cmd|' /C calc'!A0"


def test_jsonl_export_streams_iterable_records(tmp_path: Path):
    output = tmp_path / "records.jsonl"
    records = ({"id": str(index), "title": f"Job {index}"} for index in range(2))

    assert export_records(records, output, ExportFormat.JSONL) == 2
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert rows == [
        {"id": "0", "title": "Job 0"},
        {"id": "1", "title": "Job 1"},
    ]


def test_export_failure_preserves_existing_destination_and_removes_temp_file(
    tmp_path: Path,
):
    output = tmp_path / "records.jsonl"
    output.write_text("existing\n", encoding="utf-8")

    def failing_records():
        yield {"id": "1"}
        raise RuntimeError("simulated export failure")

    with pytest.raises(RuntimeError, match="simulated export failure"):
        export_records(failing_records(), output, ExportFormat.JSONL)

    assert output.read_text(encoding="utf-8") == "existing\n"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_sqlite_export_refuses_to_delete_existing_sidecars(tmp_path: Path) -> None:
    output = tmp_path / "records.sqlite"
    output.write_bytes(b"existing database sentinel")
    wal = output.with_name(f"{output.name}-wal")
    wal.write_bytes(b"existing wal sentinel")

    with pytest.raises(RuntimeError, match="SQLite export.*sidecars"):
        export_records([{"id": "1"}], output, ExportFormat.SQLITE)

    assert output.read_bytes() == b"existing database sentinel"
    assert wal.read_bytes() == b"existing wal sentinel"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_exports_sort_record_keys_and_nested_json(tmp_path: Path):
    records = [
        {
            "zeta": {"b": 2, "a": 1},
            "alpha": "first",
            "items": [{"b": 2, "a": 1}],
        }
    ]
    jsonl_output = tmp_path / "records.jsonl"
    csv_output = tmp_path / "records.csv"
    parquet_output = tmp_path / "records.parquet"

    assert export_records(records, jsonl_output, ExportFormat.JSONL) == 1
    assert export_records(records, csv_output, ExportFormat.CSV) == 1
    assert export_records(records, parquet_output, ExportFormat.PARQUET) == 1

    assert jsonl_output.read_text().splitlines() == [
        '{"alpha": "first", "items": [{"a": 1, "b": 2}], "zeta": {"a": 1, "b": 2}}'
    ]
    assert csv_output.read_text().splitlines()[0] == "alpha,items,zeta"
    assert pl.read_parquet(parquet_output).columns == ["alpha", "items", "zeta"]


def test_empty_exports_have_deterministic_outputs(tmp_path: Path):
    jsonl_output = tmp_path / "empty.jsonl"
    csv_output = tmp_path / "empty.csv"
    parquet_output = tmp_path / "empty.parquet"

    assert export_records([], jsonl_output, ExportFormat.JSONL) == 0
    assert export_records([], csv_output, ExportFormat.CSV) == 0
    assert export_records([], parquet_output, ExportFormat.PARQUET) == 0

    assert jsonl_output.read_text() == ""
    assert csv_output.read_text() == ""
    assert pl.read_parquet(parquet_output).height == 0


def test_storage_board_filters(tmp_path: Path):
    store = seeded_filter_store(tmp_path)

    boards = store.list_boards(
        filters=BoardFilters(
            source_key="a16z",
            provider_id="ashbyhq",
            market="artificial",
            location="remote",
            domain="acme",
            has_jobs=True,
            min_staff=10,
            max_staff=50,
        )
    )

    assert [board.key for board in boards] == ["acme"]
    lever_boards = store.list_boards(
        filters=BoardFilters(provider_id="lever", has_jobs=True)
    )
    assert [board.key for board in lever_boards] == ["bravo"]


def test_storage_job_filters_use_enriched_normalized_fields(tmp_path: Path):
    store = seeded_filter_store(tmp_path)

    jobs = store.list_jobs(
        filters=JobFilters(
            source_key="a16z",
            provider_id="ashbyhq",
            location="remote",
            department="engineer",
            team="platform",
            workplace_type="remote",
            remote="Full",
            employment_type="full",
            salary_min=150000,
            salary_max=200000,
            skill="python",
            query="developer infrastructure",
            posted_after="2026-05-01",
            posted_before="2026-05-31",
        )
    )

    assert [job.id for job in jobs] == ["acme:ashbyhq:1"]
    assert store.list_jobs(filters=JobFilters(skill="go")) == []


def test_storage_pushes_sql_limit_before_job_materialization(
    tmp_path: Path, monkeypatch
):
    store = seeded_filter_store(tmp_path)
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": "acme:ashbyhq:2",
                    "board_key": "acme",
                    "provider_id": "ashbyhq",
                    "remote_id": "2",
                    "title": "Platform Engineer",
                    "company": "Acme AI",
                    "remote": "Full",
                }
            )
        ]
    )
    original = storage_module._job_from_identity_and_version
    converted = 0

    def counting_job_from_row(session, row, version, **kwargs):
        nonlocal converted
        converted += 1
        return original(session, row, version, **kwargs)

    monkeypatch.setattr(
        storage_module, "_job_from_identity_and_version", counting_job_from_row
    )

    jobs = store.list_jobs(filters=JobFilters(remote="Full", limit=1))

    assert len(jobs) == 1
    assert converted == 1


def test_storage_provider_any_all_aliases(tmp_path: Path):
    store = seeded_filter_store(tmp_path)

    any_jobs = store.list_jobs(filters=JobFilters(provider_id="any"))
    all_jobs = store.list_jobs(filters=JobFilters(provider_id="all"))

    assert {job.id for job in any_jobs} == {"acme:ashbyhq:1", "bravo:lever:1"}
    assert {job.id for job in all_jobs} == {"acme:ashbyhq:1", "bravo:lever:1"}


def test_board_exports_use_same_filters_as_board_list(tmp_path: Path):
    store = seeded_filter_store(tmp_path)
    output = tmp_path / "boards.jsonl"
    filters = BoardFilters(provider_id="ashbyhq", market="developer", has_jobs=True)

    listed = store.list_boards(filters=filters)
    count = export_records(listed, output, ExportFormat.JSONL)
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert count == 1
    assert [row["key"] for row in rows] == [board.key for board in listed]


def test_job_exports_use_same_filters_as_job_list(tmp_path: Path):
    store = seeded_filter_store(tmp_path)
    output = tmp_path / "jobs.jsonl"
    filters = JobFilters(remote="Full", salary_min=150000, skill="python")

    listed = store.list_jobs(filters=filters)
    count = export_records(listed, output, ExportFormat.JSONL)
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert count == 1
    assert [row["id"] for row in rows] == [job.id for job in listed]


def test_append_jsonl_uses_sorted_keys_like_export_records(tmp_path: Path):
    output = tmp_path / "stream.jsonl"
    record = JobRecord(
        id="acme:greenhouse:1",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="1",
        title="Engineer",
        company="Acme",
        skills=[{"name": "Backend", "level": "Senior", "keywords": ["Python"]}],
    )

    assert append_jsonl(output, [record]) == 1

    assert output.read_text().splitlines() == [
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    ]


def test_report_job_version_dual_write_mismatches_is_clean_after_sync(
    tmp_path: Path,
):
    store = seeded_filter_store(tmp_path)

    report = report_job_version_dual_write_mismatches(store.engine)

    assert report["mismatchCount"] == 0
    assert report["mismatches"] == []
    assert report["checkedVersions"] >= 2
