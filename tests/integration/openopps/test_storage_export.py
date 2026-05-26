import json
from pathlib import Path
import sqlite3

import polars as pl

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
from openopps.storage import BoardFilters, JobFilters
from openopps.storage import OpenOppsStore


def seeded_filter_store(tmp_path: Path) -> OpenOppsStore:
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
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme AI",
                domain="acme.ai",
                markets=["Artificial Intelligence", "Developer Tools"],
                locations=["San Francisco", "Remote"],
                staff_count=42,
                num_jobs_hint=3,
            ),
            BoardRecord(
                key="bravo",
                source_key="yc",
                remote_id="bravo",
                name="Bravo Health",
                domain="bravo.health",
                markets=["Healthcare"],
                locations=["Boston"],
                staff_count=12,
                num_jobs_hint=0,
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:ashbyhq",
                source_key="a16z",
                board_key="acme",
                provider_id="ashbyhq",
                support_level=ProviderSupport.JOBS,
                count_hint=3,
                token="acme",
            ),
            BoardProviderRecord(
                id="yc:bravo:lever",
                source_key="yc",
                board_key="bravo",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                count_hint=0,
                token="bravo",
            ),
        ]
    )
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": "acme:ashbyhq:1",
                    "board_key": "acme",
                    "provider_id": "ashbyhq",
                    "remote_id": "1",
                    "title": "Senior Platform Engineer",
                    "company": "Acme AI",
                    "locations": ["Remote", "San Francisco"],
                    "department": "Engineering",
                    "team": "Platform",
                    "workplace_type": "Remote",
                    "employment_type": "Full-time",
                    "description": "Build reliable AI developer infrastructure.",
                    "remote": "Full",
                    "salary_min": 120000,
                    "salary_max": 180000,
                    "skills": [
                        {"name": "Backend", "level": "Senior", "keywords": ["Python"]}
                    ],
                    "posted_at": "2026-05-10T12:00:00Z",
                }
            ),
            JobRecord.model_validate(
                {
                    "id": "bravo:lever:1",
                    "board_key": "bravo",
                    "provider_id": "lever",
                    "remote_id": "1",
                    "title": "Care Designer",
                    "company": "Bravo Health",
                    "locations": ["Boston"],
                    "department": "Design",
                    "team": "Care",
                    "workplace_type": "Onsite",
                    "employment_type": "Contract",
                    "description": "Design patient care workflows.",
                    "remote": "None",
                    "salary_min": 70000,
                    "salary_max": 90000,
                    "skills": [
                        {"name": "Design", "level": "Mid", "keywords": ["Figma"]}
                    ],
                    "posted_at": "2026-04-01",
                }
            ),
        ]
    )
    return store


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


def test_job_sync_dedupes_duplicate_jobs_in_one_route_run(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    store.init_db()
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
    store.upsert_boards(
        [
            BoardRecord(
                key="a16z:acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme AI",
                domain="acme.ai",
            ),
            BoardRecord(
                key="yc:acme-ai",
                source_key="yc",
                remote_id="31503",
                name="Acme AI",
                domain="acme.ai",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="yc:yc-acme-ai:lever",
                source_key="yc",
                board_key="yc:acme-ai",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
            )
        ]
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

    def counting_job_from_row(session, row, version):
        nonlocal converted
        converted += 1
        return original(session, row, version)

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
