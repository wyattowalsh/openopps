from __future__ import annotations

import json
import runpy
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

_SEARCH_INDEX_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "generate_docs_search_index.py"
)
_SEARCH_INDEX_NAMESPACE = runpy.run_path(str(_SEARCH_INDEX_SCRIPT))
build_search_index = cast(
    "Callable[[Path, Path], dict[str, Any]]",
    _SEARCH_INDEX_NAMESPACE["build_search_index"],
)
SEARCH_INDEX_VERSION = cast(int, _SEARCH_INDEX_NAMESPACE["SEARCH_INDEX_VERSION"])
DETAIL_DESCRIPTION_MAX_LEN = cast(
    int, _SEARCH_INDEX_NAMESPACE["DETAIL_DESCRIPTION_MAX_LEN"]
)
INITIAL_JOB_LIMIT = cast(int, _SEARCH_INDEX_NAMESPACE["INITIAL_JOB_LIMIT"])
PROVIDER_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["PROVIDER_COLUMNS"])
BOARD_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["BOARD_COLUMNS"])
JOB_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["JOB_COLUMNS"])
LEGACY_JOB_COLUMNS = JOB_COLUMNS[:23]
DETAIL_IDS_FILE = cast(str, _SEARCH_INDEX_NAMESPACE["DETAIL_IDS_FILE"])
INDEXABLE_IDS_FILE = cast(str, _SEARCH_INDEX_NAMESPACE["INDEXABLE_IDS_FILE"])
is_indexable_job_detail = cast(
    "Callable[[dict[str, Any]], bool]",
    _SEARCH_INDEX_NAMESPACE["_is_indexable_job_detail"],
)
safe_job_external_url = cast(
    "Callable[[Any], str | None]",
    _SEARCH_INDEX_NAMESPACE["_safe_job_external_url"],
)
detail_bucket = cast(
    "Callable[[str], str]",
    _SEARCH_INDEX_NAMESPACE["_detail_bucket"],
)


def test_detail_shards_use_tiered_payloads(tmp_path: Path) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    detail_root = output_dir / "jobs-details"
    records: dict[str, dict[str, Any]] = {}
    for bucket_path in detail_root.glob("*.json"):
        records.update(_read_json(bucket_path))
    rich = records["job-rich"]
    thin = records["job-thin"]
    assert rich["detailTier"] == "T2"
    assert thin["detailTier"] == "T1"
    assert rich["description"]
    assert len(rich["description"]) <= DETAIL_DESCRIPTION_MAX_LEN
    assert "<" not in rich["description"]
    assert "descriptionHtml" not in rich
    assert "description" not in thin
    assert "descriptionHtml" not in thin
    assert "payloadSnapshots" not in rich
    assert thin["status"] == "open"
    assert rich["status"] == "open"

    manifest = _read_json(output_dir / "manifest.json")
    assert manifest["detailShards"]["tierCounts"] == {"T1": 1, "T2": 1}


def test_build_search_index_writes_manifest_and_chunks(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "public" / "data" / "openopps-search"

    manifest = build_search_index(db_path, output_dir)

    assert manifest["version"] == SEARCH_INDEX_VERSION
    assert manifest["snapshotAt"] == "2026-02-03T04:05:06.123456Z"
    assert manifest["openJobCount"] == 1
    assert "filterSpec" in manifest
    assert "detailShards" in manifest
    assert manifest["detailShards"]["idIndexPath"] == (
        "/data/openopps-search/jobs-detail-ids.json"
    )
    assert (output_dir / DETAIL_IDS_FILE).exists()
    assert (output_dir / INDEXABLE_IDS_FILE).exists()
    indexable_ids = _read_json(output_dir / INDEXABLE_IDS_FILE)
    assert indexable_ids["version"] == SEARCH_INDEX_VERSION
    assert indexable_ids["count"] == len(indexable_ids["ids"]) == 1
    assert indexable_ids["ids"] == ["job-1"]
    assert manifest["detailShards"]["indexableIdIndexPath"] == (
        "/data/openopps-search/jobs-indexable-ids.json"
    )
    assert manifest["detailShards"]["indexableCount"] == 1
    assert manifest["entities"]["jobs"]["detailPath"]
    assert manifest["defaultEntity"] == "jobs"
    assert manifest["defaultFilters"] == {"jobs": {"status": "open"}}
    assert manifest["source"]["tables"] == [
        "board_providers",
        "boards",
        "jobs",
        "job_versions",
        "job_version_locations",
        "job_version_skills",
        "job_version_skill_keywords",
    ]
    assert manifest["counts"]["snapshot"] == {
        "database": db_path.name,
        "sourceRows": 0,
        "providerRoutes": 2,
        "boards": 2,
        "jobs": 2,
        "openJobs": 1,
    }
    assert "suggestions" in manifest
    assert "dashboard" in manifest
    assert {
        entity: details["count"] for entity, details in manifest["entities"].items()
    } == {"providers": 2, "boards": 2, "jobs": 2}
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "providers.json").exists()
    assert (output_dir / "boards.json").exists()
    assert not (output_dir / "jobs.json").exists()
    assert manifest["entities"]["jobs"]["initialPath"] == (
        "/data/openopps-search/jobs/latest.json"
    )
    assert manifest["entities"]["jobs"]["chunks"]
    assert (output_dir / "jobs" / "latest.json").exists()
    jobs = _read_json(output_dir / "jobs" / "latest.json")
    for column in (
        "latestObservedAt",
        "sourceKeys",
        "descriptionSnippet",
        "skillTokens",
        "syncedAt",
        "firstSeenAt",
        "lastSeenAt",
        "closedAt",
        "contentHash",
        "payloadHash",
    ):
        assert column in jobs["columns"]
    for row in jobs["rows"]:
        assert len(row) == len(JOB_COLUMNS)
    assert jobs["count"] <= INITIAL_JOB_LIMIT
    assert len(_read_job_rows(output_dir, manifest)) == 2


def test_search_index_uses_current_job_versions(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    manifest = _read_json(output_dir / "manifest.json")
    columns = manifest["entities"]["jobs"]["columns"]
    title_index = columns.index("title")
    remote_index = columns.index("remote")
    observed_index = columns.index("latestObservedAt")
    first_seen_index = columns.index("firstSeenAt")
    last_seen_index = columns.index("lastSeenAt")
    closed_index = columns.index("closedAt")
    content_hash_index = columns.index("contentHash")
    payload_hash_index = columns.index("payloadHash")
    rows = _read_job_rows(output_dir, manifest)

    assert [row[title_index] for row in rows] == [
        "Current Staff Engineer",
        "Closed Designer",
    ]
    assert [row[remote_index] for row in rows] == ["Full", "Hybrid"]
    assert [row[observed_index] for row in rows] == [
        "2026-02-03T04:05:06.123456Z",
        "2026-01-14T00:00:00.000000Z",
    ]
    assert [row[first_seen_index] for row in rows] == [
        "2026-01-01T00:00:00Z",
        "2026-01-10T00:00:00Z",
    ]
    assert [row[last_seen_index] for row in rows] == [
        "2026-02-03 04:05:06.123456",
        "2026-01-14T00:00:00Z",
    ]
    assert [row[closed_index] for row in rows] == [None, None]
    assert [row[content_hash_index] for row in rows] == [None, None]
    assert [row[payload_hash_index] for row in rows] == [None, None]


def test_search_index_preserves_nullable_board_counts(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    boards = json.loads((output_dir / "boards.json").read_text(encoding="utf-8"))
    columns = boards["columns"]
    by_key = {row[columns.index("key")]: row for row in boards["rows"]}

    beta = by_key["yc:beta"]
    assert beta[columns.index("staffCount")] is None
    assert beta[columns.index("numJobsHint")] is None


def test_search_index_manifest_facets_are_nonblank_and_sorted(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    assert manifest["facets"]["sources"] == ["a16z", "portfolio", "yc"]
    assert manifest["facets"]["providerIds"] == ["ashbyhq", "greenhouse"]
    assert manifest["facets"]["jobStatuses"] == ["closed", "open"]
    assert manifest["facets"]["supportLevels"] == ["detect", "jobs"]
    assert manifest["facets"]["routeStatuses"] == ["active", "missing_route"]
    assert manifest["facets"]["workplaces"] == ["Full", "Hybrid", "Remote"]
    assert manifest["facets"]["employmentTypes"] == ["Contract", "Full-time"]
    assert manifest["facets"]["locations"] == ["Canada", "New York", "Remote"]
    assert manifest["facets"]["departments"] == ["Design", "Engineering"]
    assert manifest["facets"]["teams"] == ["Platform", "Product"]
    assert manifest["facets"]["companies"] == ["Acme", "Beta Labs"]
    assert manifest["facets"]["salaryCurrencies"] == ["USD"]
    assert manifest["suggestions"]["locations"][0] == {
        "value": "Canada",
        "label": "Canada",
        "count": 1,
        "normalized": "canada",
    }
    assert manifest["dashboard"]["dataQuality"]


def test_search_index_derives_seniority_when_extra_payload_missing(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    columns = manifest["entities"]["jobs"]["columns"]
    seniority_index = columns.index("seniority")
    rows = _read_job_rows(output_dir, manifest)
    open_row = next(row for row in rows if row[columns.index("status")] == "open")
    assert open_row[seniority_index] == "Principal"
    assert "Principal" in manifest["facets"]["seniorities"]


def test_is_indexable_job_detail_matches_docs_runtime_rules() -> None:
    assert is_indexable_job_detail(
        {
            "status": "open",
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "postingUrl": "https://acme.example/jobs/1",
        }
    )
    assert is_indexable_job_detail(
        {
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "postingUrl": "https://acme.example/jobs/1",
        }
    )
    assert not is_indexable_job_detail(
        {
            "status": "closed",
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "postingUrl": "https://acme.example/jobs/1",
        }
    )
    assert not is_indexable_job_detail(
        {
            "status": "open",
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "applyUrl": "javascript:alert(1)",
        }
    )
    assert not is_indexable_job_detail(
        {
            "status": "open",
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "postingUrl": "https://user:pass@acme.example/jobs/1",
        }
    )
    assert not is_indexable_job_detail(
        {
            "status": "open",
            "title": "Staff Engineer",
            "company": "Acme",
            "description": "Build platform systems.",
            "postedAt": "2026-01-01T00:00:00Z",
            "applyUrl": "https://user@acme.example/jobs/1",
        }
    )


def test_safe_job_external_url_requires_absolute_hostless_free_urls() -> None:
    assert safe_job_external_url("https://acme.example/jobs/1") == (
        "https://acme.example/jobs/1"
    )
    assert safe_job_external_url("/jobs/1") is None
    assert safe_job_external_url("//acme.example/jobs/1") is None
    assert safe_job_external_url("http:///jobs/1") is None
    assert safe_job_external_url("https://user:pass@acme.example/jobs/1") is None


def test_committed_search_index_artifacts_have_runtime_schema() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    artifact_dir = repo_root / "docs" / "public" / "data" / "openopps-search"

    manifest = _read_json(artifact_dir / "manifest.json")

    artifact_version = manifest["version"]
    assert artifact_version in {3, 4, SEARCH_INDEX_VERSION}
    assert manifest["defaultEntity"] == "jobs"
    assert "detailShards" in manifest
    job_columns = (
        JOB_COLUMNS
        if artifact_version == SEARCH_INDEX_VERSION
        else LEGACY_JOB_COLUMNS
        if artifact_version < SEARCH_INDEX_VERSION
        else JOB_COLUMNS[:28]
    )

    expected_columns = {
        "providers": PROVIDER_COLUMNS,
        "boards": BOARD_COLUMNS,
        "jobs": job_columns,
    }
    for entity, columns in expected_columns.items():
        if entity == "jobs":
            continue
        chunk = _read_json(artifact_dir / f"{entity}.json")
        assert chunk["version"] == artifact_version
        assert chunk["entity"] == entity
        assert chunk["columns"] == columns
        assert chunk["count"] == len(chunk["rows"])
        assert manifest["entities"][entity]["columns"] == columns
        assert manifest["entities"][entity]["count"] == chunk["count"]
        assert all(len(row) == len(columns) for row in chunk["rows"])

    providers_chunk = _read_json(artifact_dir / "providers.json")
    provider_id_index = PROVIDER_COLUMNS.index("providerId")
    support_level_index = PROVIDER_COLUMNS.index("supportLevel")
    unsupported_with_provider_ids = [
        row
        for row in providers_chunk["rows"]
        if row[support_level_index] == "unsupported" and row[provider_id_index]
    ]
    assert unsupported_with_provider_ids

    job_entity = manifest["entities"]["jobs"]
    assert not (artifact_dir / "jobs.json").exists()
    assert job_entity["initialPath"] == "/data/openopps-search/jobs/latest.json"
    assert (artifact_dir / job_entity["file"]).is_file()
    assert job_entity["chunks"]
    latest_jobs = _read_json(artifact_dir / "jobs" / "latest.json")
    assert latest_jobs["version"] == artifact_version
    assert latest_jobs["entity"] == "jobs"
    assert latest_jobs["columns"] == job_columns
    assert latest_jobs["count"] <= INITIAL_JOB_LIMIT
    jobs = {"rows": _read_job_rows(artifact_dir, manifest)}
    assert job_entity["count"] == len(jobs["rows"])
    assert all(len(row) == len(job_columns) for row in jobs["rows"])
    id_index = job_columns.index("id")
    status_index = job_columns.index("status")
    open_job_ids = [
        str(row[id_index]) for row in jobs["rows"] if row[status_index] == "open"
    ]
    detail_shards = manifest["detailShards"]
    detail_root = artifact_dir / "jobs-details"
    assert detail_shards["root"] == "/data/openopps-search/jobs-details"
    assert detail_shards["format"] == "bucket-map"
    assert detail_shards["idIndexPath"] == "/data/openopps-search/jobs-detail-ids.json"
    detail_id_index = _read_json(artifact_dir / detail_shards["idIndexFile"])
    assert detail_id_index.get("version", artifact_version) == artifact_version
    assert detail_id_index["count"] == len(detail_id_index["ids"])
    indexable_ids: list[str] = []
    if artifact_version == SEARCH_INDEX_VERSION:
        indexable_id_index = _read_json(
            artifact_dir / detail_shards["indexableIdIndexFile"]
        )
        assert indexable_id_index.get("version", artifact_version) == artifact_version
        assert indexable_id_index["count"] == len(indexable_id_index["ids"])
        indexable_ids = [str(job_id) for job_id in indexable_id_index["ids"]]
    assert detail_shards["count"] == len(open_job_ids) == manifest["openJobCount"]
    assert (
        sum(bucket["count"] for bucket in detail_shards["buckets"].values())
        == (detail_shards["count"])
    )
    manifest_bucket_names = set(detail_shards["buckets"])
    disk_bucket_names = {path.stem for path in detail_root.glob("*.json")}
    assert disk_bucket_names == manifest_bucket_names
    detail_ids: set[str] = set()
    detail_records: dict[str, dict[str, Any]] = {}
    for bucket, details in detail_shards["buckets"].items():
        bucket_path = detail_root / f"{bucket}.json"
        assert bucket_path.is_file()
        bucket_payload = _read_json(bucket_path)
        assert len(bucket_payload) == details["count"]
        for job_id, detail in bucket_payload.items():
            assert detail["id"] == job_id
            assert detail_bucket(job_id) == bucket
            detail_ids.add(job_id)
            detail_records[job_id] = detail
    assert not any(detail_root.glob("*/*.json"))
    assert detail_ids == set(open_job_ids)
    assert set(detail_id_index["ids"]) == detail_ids
    assert set(indexable_ids) <= detail_ids
    assert all("status" in detail for detail in detail_records.values())
    assert all(
        is_indexable_job_detail(detail_records[job_id])
        for job_id in indexable_ids
    )
    assert len(_artifact_files(artifact_dir)) <= 400


def test_generated_search_index_artifact_matches_local_db_when_available(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    db_path = repo_root / "kaggle" / "openoppsdb.sqlite"
    artifact_dir = repo_root / "docs" / "public" / "data" / "openopps-search"
    if not db_path.exists() or not (artifact_dir / "manifest.json").exists():
        pytest.skip("local SQLite DB or generated docs search index is unavailable")

    output_dir = tmp_path / "openopps-search"
    build_search_index(db_path, output_dir)

    artifact_files = _artifact_files(artifact_dir)
    output_files = _artifact_files(output_dir)
    assert artifact_files == output_files
    for filename in artifact_files:
        assert (artifact_dir / filename).read_bytes() == (
            output_dir / filename
        ).read_bytes()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_job_rows(artifact_dir: Path, manifest: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for chunk in manifest["entities"]["jobs"]["chunks"]:
        assert (artifact_dir / chunk["file"]).is_file()
        payload = _read_json(artifact_dir / chunk["file"])
        assert payload["count"] == len(payload["rows"])
        rows.extend(payload["rows"])
    return rows


def _artifact_files(artifact_dir: Path) -> set[Path]:
    return {
        path.relative_to(artifact_dir)
        for path in artifact_dir.rglob("*")
        if path.is_file()
    }


def _write_search_index_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "openopps.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE job_version_locations (
                id TEXT PRIMARY KEY,
                job_version_id TEXT,
                ordinal INTEGER,
                label TEXT
            );

            CREATE TABLE job_version_skills (
                id TEXT PRIMARY KEY,
                job_version_id TEXT,
                ordinal INTEGER,
                name TEXT,
                level TEXT
            );

            CREATE TABLE job_version_skill_keywords (
                id TEXT PRIMARY KEY,
                skill_id TEXT,
                ordinal INTEGER,
                keyword TEXT
            );

            CREATE TABLE boards (
                key TEXT PRIMARY KEY,
                source_key TEXT,
                source_keys TEXT,
                name TEXT,
                domain TEXT,
                website_url TEXT,
                staff_count INTEGER,
                num_jobs_hint INTEGER,
                synced_at TEXT
            );

            CREATE TABLE board_providers (
                id TEXT PRIMARY KEY,
                source_key TEXT,
                board_key TEXT,
                provider_id TEXT,
                label TEXT,
                support_level TEXT,
                count_hint INTEGER,
                board_url TEXT,
                last_status TEXT,
                detected_at TEXT
            );

            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                board_key TEXT,
                provider_id TEXT,
                remote_id TEXT,
                status TEXT,
                current_version_id TEXT,
                first_seen_at TEXT,
                last_seen_at TEXT,
                synced_at TEXT
            );

            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                title TEXT,
                locations TEXT,
                department TEXT,
                team TEXT,
                workplace_type TEXT,
                company TEXT,
                employment_type TEXT,
                remote TEXT,
                description TEXT,
                description_html TEXT,
                responsibilities TEXT,
                qualifications TEXT,
                skills TEXT,
                job_description TEXT,
                compensation TEXT,
                experience TEXT,
                salary TEXT,
                salary_min REAL,
                salary_max REAL,
                salary_currency TEXT,
                posting_url TEXT,
                apply_url TEXT,
                posted_at TEXT,
                updated_at TEXT,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO boards (
                key, source_key, source_keys, name, domain, website_url, staff_count,
                num_jobs_hint, synced_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "a16z:acme",
                    "a16z",
                    '["a16z","portfolio"]',
                    "Acme",
                    "acme.example",
                    "https://acme.example/jobs",
                    120,
                    3,
                    "2026-02-01T00:00:00Z",
                ),
                (
                    "yc:beta",
                    "yc",
                    None,
                    "Beta Labs",
                    "beta.example",
                    "https://beta.example/careers",
                    None,
                    None,
                    "2026-01-15T00:00:00Z",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO board_providers (
                id, source_key, board_key, provider_id, label, support_level,
                count_hint, board_url, last_status, detected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "route-1",
                    "a16z",
                    "a16z:acme",
                    "greenhouse",
                    "Greenhouse",
                    "jobs",
                    3,
                    "https://boards.greenhouse.io/acme",
                    "active",
                    "2026-02-02T00:00:00Z",
                ),
                (
                    "route-2",
                    "yc",
                    "yc:beta",
                    "ashbyhq",
                    "Ashby",
                    "detect",
                    None,
                    "https://jobs.ashbyhq.com/beta",
                    "missing_route",
                    "2026-01-16T00:00:00Z",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, status,
                current_version_id, first_seen_at, last_seen_at, synced_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "job-1",
                    "a16z:acme",
                    "greenhouse",
                    "remote-1",
                    "open",
                    "version-current",
                    "2026-01-01T00:00:00Z",
                    "2026-02-03 04:05:06.123456",
                    "2026-02-03T00:00:00Z",
                ),
                (
                    "job-2",
                    "yc:beta",
                    "ashbyhq",
                    "remote-2",
                    "closed",
                    "version-closed",
                    "2026-01-10T00:00:00Z",
                    "2026-01-14T00:00:00Z",
                    "2026-01-14T00:00:00Z",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO job_versions (
                id, job_id, title, locations, department, team, workplace_type,
                company, employment_type, remote, description, description_html,
                responsibilities, qualifications, skills, job_description,
                compensation, experience, salary, salary_min, salary_max,
                salary_currency, posting_url, apply_url, posted_at, updated_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "version-old",
                    "job-1",
                    "Old Staff Engineer",
                    '["New York"]',
                    "Engineering",
                    "Platform",
                    "Remote",
                    "Acme",
                    "Full-time",
                    "Full",
                    "Old description",
                    None,
                    '["Ship platform"]',
                    '["5+ years"]',
                    None,
                    None,
                    None,
                    None,
                    None,
                    170000,
                    220000,
                    "USD",
                    "https://acme.example/jobs/1",
                    "https://acme.example/apply/1",
                    "2026-01-01T00:00:00Z",
                    "2026-01-02T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
                (
                    "version-current",
                    "job-1",
                    "Current Staff Engineer",
                    '["New York", "Remote"]',
                    "Engineering",
                    "Platform",
                    "Remote",
                    "Acme",
                    "Full-time",
                    "Full",
                    "Build platform systems for Acme portfolio companies.",
                    None,
                    '["Own platform roadmap"]',
                    '["Staff-level experience"]',
                    None,
                    None,
                    None,
                    "Staff",
                    None,
                    180000,
                    230000,
                    "USD",
                    "https://acme.example/jobs/1",
                    "https://acme.example/apply/1",
                    "2026-01-01T00:00:00Z",
                    "2026-01-02T00:00:00-05:00",
                    "2026-02-01T00:00:00Z",
                ),
                (
                    "version-closed",
                    "job-2",
                    "Closed Designer",
                    '["Canada"]',
                    "Design",
                    "Product",
                    "Hybrid",
                    "Beta Labs",
                    "Contract",
                    "Hybrid",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "https://beta.example/jobs/2",
                    None,
                    "2026-01-10T00:00:00Z",
                    "2026-01-14T00:00:00Z",
                    "2026-01-10T00:00:00Z",
                ),
            ],
        )
    return db_path


def _write_tiered_shard_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "tiered.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE job_version_locations (
                id TEXT PRIMARY KEY,
                job_version_id TEXT,
                ordinal INTEGER,
                label TEXT
            );
            CREATE TABLE job_version_skills (
                id TEXT PRIMARY KEY,
                job_version_id TEXT,
                ordinal INTEGER,
                name TEXT,
                level TEXT
            );
            CREATE TABLE job_version_skill_keywords (
                id TEXT PRIMARY KEY,
                skill_id TEXT,
                ordinal INTEGER,
                keyword TEXT
            );
            CREATE TABLE boards (
                key TEXT PRIMARY KEY,
                source_key TEXT,
                source_keys TEXT,
                name TEXT,
                domain TEXT,
                website_url TEXT,
                staff_count INTEGER,
                num_jobs_hint INTEGER,
                synced_at TEXT
            );
            CREATE TABLE board_providers (
                id TEXT PRIMARY KEY,
                source_key TEXT,
                board_key TEXT,
                provider_id TEXT,
                label TEXT,
                support_level TEXT,
                count_hint INTEGER,
                board_url TEXT,
                last_status TEXT,
                detected_at TEXT
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                board_key TEXT,
                provider_id TEXT,
                remote_id TEXT,
                status TEXT,
                current_version_id TEXT,
                first_seen_at TEXT,
                last_seen_at TEXT,
                synced_at TEXT
            );
            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                title TEXT,
                locations TEXT,
                department TEXT,
                team TEXT,
                workplace_type TEXT,
                company TEXT,
                employment_type TEXT,
                remote TEXT,
                description TEXT,
                description_html TEXT,
                responsibilities TEXT,
                qualifications TEXT,
                skills TEXT,
                job_description TEXT,
                compensation TEXT,
                experience TEXT,
                salary TEXT,
                salary_min REAL,
                salary_max REAL,
                salary_currency TEXT,
                posting_url TEXT,
                apply_url TEXT,
                posted_at TEXT,
                updated_at TEXT,
                created_at TEXT,
                extra_payload TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO boards (
                key, source_key, name, domain, website_url, staff_count,
                num_jobs_hint, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "a16z:acme",
                "a16z",
                "Acme",
                "acme.example",
                "https://acme.example/jobs",
                10,
                2,
                "2026-02-03T04:05:06.123456Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO board_providers (
                id, source_key, board_key, provider_id, label, support_level,
                count_hint, board_url, last_status, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "route-1",
                "a16z",
                "a16z:acme",
                "greenhouse",
                "Greenhouse",
                "jobs",
                2,
                "https://boards.greenhouse.io/acme",
                "active",
                "2026-02-02T00:00:00Z",
            ),
        )
        conn.executemany(
            """
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, status,
                current_version_id, first_seen_at, last_seen_at, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "job-rich",
                    "a16z:acme",
                    "greenhouse",
                    "rich-1",
                    "open",
                    "version-rich",
                    "2026-01-01T00:00:00Z",
                    "2026-02-03T04:05:06.123456Z",
                    "2026-02-03T00:00:00Z",
                ),
                (
                    "job-thin",
                    "a16z:acme",
                    "greenhouse",
                    "thin-1",
                    "open",
                    "version-thin",
                    "2026-01-15T00:00:00Z",
                    "2026-02-03T04:05:06.123456Z",
                    "2026-02-03T00:00:00Z",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO job_versions (
                id, job_id, title, locations, department, team, workplace_type,
                company, employment_type, remote, description, description_html,
                responsibilities, qualifications, skills, job_description,
                compensation, experience, salary, salary_min, salary_max,
                salary_currency, posting_url, apply_url, posted_at, updated_at,
                created_at, extra_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "version-rich",
                    "job-rich",
                    "Staff Engineer",
                    '["Remote"]',
                    "Engineering",
                    None,
                    "Remote",
                    "Acme",
                    "Full-time",
                    "Full",
                    "<p>" + ("Build platform systems. " * 300) + "</p>",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "https://acme.example/jobs/rich",
                    None,
                    "2026-01-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    None,
                ),
                (
                    "version-thin",
                    "job-thin",
                    "Untitled",
                    '[]',
                    None,
                    None,
                    None,
                    "Acme",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2026-01-15T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    None,
                ),
            ],
        )
    return db_path
