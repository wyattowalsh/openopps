from __future__ import annotations

import hashlib
import json
import os
import runpy
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from openopps.models import SourceRecord


class _LoadedScriptFunction(Protocol):
    __globals__: dict[str, Any]

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


_SEARCH_INDEX_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "generate_docs_search_index.py"
)
_SEARCH_INDEX_NAMESPACE = runpy.run_path(str(_SEARCH_INDEX_SCRIPT))
build_search_index = cast(
    "Callable[[Path, Path], dict[str, Any]]",
    _SEARCH_INDEX_NAMESPACE["build_search_index"],
)
build_search_release = cast(
    _LoadedScriptFunction,
    _SEARCH_INDEX_NAMESPACE["build_search_release"],
)
SEARCH_INDEX_VERSION = cast(int, _SEARCH_INDEX_NAMESPACE["SEARCH_INDEX_VERSION"])
INITIAL_JOB_LIMIT = cast(int, _SEARCH_INDEX_NAMESPACE["INITIAL_JOB_LIMIT"])
DETAIL_DESCRIPTION_TEXT_MAX_LEN = cast(
    int, _SEARCH_INDEX_NAMESPACE["DETAIL_DESCRIPTION_TEXT_MAX_LEN"]
)
PROVIDER_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["PROVIDER_COLUMNS"])
BOARD_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["BOARD_COLUMNS"])
JOB_COLUMNS = cast(list[str], _SEARCH_INDEX_NAMESPACE["JOB_COLUMNS"])
LEGACY_JOB_COLUMNS = JOB_COLUMNS[:23]
DETAIL_IDS_FILE = cast(str, _SEARCH_INDEX_NAMESPACE["DETAIL_IDS_FILE"])
INDEXABLE_IDS_FILE = cast(str, _SEARCH_INDEX_NAMESPACE["INDEXABLE_IDS_FILE"])
LINEAGE_AGGREGATE_FILE = cast(str, _SEARCH_INDEX_NAMESPACE["LINEAGE_AGGREGATE_FILE"])
is_indexable_job_detail = cast(
    "Callable[[dict[str, Any]], bool]",
    _SEARCH_INDEX_NAMESPACE["_is_indexable_job_detail"],
)
safe_job_external_url = cast(
    "Callable[[Any], str | None]",
    _SEARCH_INDEX_NAMESPACE["_safe_job_external_url"],
)
source_policy_denial_errors = cast(
    "Callable[[dict[str, Any]], list[str]]",
    _SEARCH_INDEX_NAMESPACE["_source_policy_denial_errors"],
)
read_source_policy_inputs = cast(
    _LoadedScriptFunction,
    _SEARCH_INDEX_NAMESPACE["_read_source_policy_inputs"],
)
detail_bucket = cast(
    "Callable[[str], str]",
    _SEARCH_INDEX_NAMESPACE["_detail_bucket"],
)
_FRESH_RELEASE_NOW = datetime(2026, 2, 4, tzinfo=timezone.utc)


def test_detail_shards_use_tiered_full_public_posting_payloads(
    tmp_path: Path,
) -> None:
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
    assert rich["description"] == "Build platform systems."
    assert "descriptionHtml" not in rich
    assert rich["responsibilities"] == ["Build platform systems"]
    assert rich["qualifications"] == ["Operate reliable services"]
    assert rich["skills"] == [{"name": "Python", "level": "advanced"}]
    assert rich["jobDescription"] == {"summary": "Build"}
    assert rich["compensation"] == {"currency": "USD"}
    assert rich["experience"] == "Senior"
    assert rich["salary"] == "$140k-$180k"
    assert rich["versionExtra"] == {"seniority": "Senior"}
    assert "payloadSnapshots" not in rich
    assert thin["status"] == "open"
    assert "description" not in thin
    assert "descriptionHtml" not in thin
    assert rich["status"] == "open"

    manifest = _read_json(output_dir / "manifest.json")
    assert manifest["detailShards"]["tierCounts"] == {"T1": 1, "T2": 1}


def test_detail_shards_clean_full_html_before_bounding(tmp_path: Path) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    html = "<span></span>" * 300 + (" " * 100) + "<p>Build platform systems.</p>"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = NULL, description_html = ?
            WHERE id = 'version-rich'
            """,
            (html,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    records = _read_detail_records(output_dir)
    indexable_ids = _read_json(output_dir / INDEXABLE_IDS_FILE)
    assert indexable_ids["ids"] == ["job-rich"]
    assert records["job-rich"]["detailTier"] == "T2"
    assert records["job-rich"]["description"] == "Build platform systems."
    assert "descriptionHtml" not in records["job-rich"]


def test_detail_shards_decode_html_entities_before_writing_plain_text(
    tmp_path: Path,
) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    html = (
        "&amp;lt;p&amp;gt;Build&nbsp;R&amp;amp;D tools for latency &amp;lt;60 ms "
        "and memory &amp;gt;1GB. &amp;#39;Ship&amp;#39; "
        "&amp;#x27;fast&amp;#x27;.&amp;lt;/p&amp;gt;"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = NULL, description_html = ?
            WHERE id = 'version-rich'
            """,
            (html,),
        )
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    expected = "Build R&D tools for latency <60 ms and memory >1GB. 'Ship' 'fast'."
    records = _read_detail_records(output_dir)
    assert records["job-rich"]["description"] == expected
    assert "descriptionHtml" not in records["job-rich"]

    columns = manifest["entities"]["jobs"]["columns"]
    snippet_index = columns.index("descriptionSnippet")
    id_index = columns.index("id")
    rows = _read_job_rows(output_dir, manifest)
    rich_row = next(row for row in rows if row[id_index] == "job-rich")
    assert rich_row[snippet_index] == expected


def test_detail_shards_decode_plain_description_entities_without_stripping_comparisons(
    tmp_path: Path,
) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    description = 'Latency &lt;60 ms &amp; memory &gt;1GB. <div class="title'
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = ?, description_html = NULL
            WHERE id = 'version-rich'
            """,
            (description,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["description"] == "Latency <60 ms & memory >1GB."


def test_detail_shards_do_not_emit_partial_html_fragments(tmp_path: Path) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    html = "<span></span>" * 400 + "<p>Build platform systems.</p>"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = NULL, description_html = ?
            WHERE id = 'version-rich'
            """,
            (html,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["detailTier"] == "T2"
    assert rich["description"] == "Build platform systems."
    assert "descriptionHtml" not in rich


def test_detail_shards_strip_provider_surplus_from_version_extra(
    tmp_path: Path,
) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    provider_blob = {
        "greenhouse": {
            "metadata": [
                {"name": f"field-{index}", "value": "x" * 200} for index in range(40)
            ],
            "offices": [{"id": index, "name": "Office " * 30} for index in range(40)],
        }
    }
    extra_payload = json.dumps(
        {
            "seniority": "Senior",
            "posting_kind": "standard",
            "provider_extras": provider_blob,
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET extra_payload = ?
            WHERE id = 'version-rich'
            """,
            (extra_payload,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["versionExtra"] == {
        "seniority": "Senior",
        "posting_kind": "standard",
    }
    assert "provider_extras" not in rich["versionExtra"]


def test_detail_shards_bound_public_description_text(tmp_path: Path) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    description = "A" * (DETAIL_DESCRIPTION_TEXT_MAX_LEN + 500)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = ?, description_html = NULL
            WHERE id = 'version-rich'
            """,
            (description,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["description"] == "A" * DETAIL_DESCRIPTION_TEXT_MAX_LEN


def test_detail_shards_strip_dangling_source_html_tags(tmp_path: Path) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    description = 'Build platform systems. <span data-sheets-value="{"1":2,"2":"At <b"'
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = ?, description_html = NULL
            WHERE id = 'version-rich'
            """,
            (description,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["description"] == "Build platform systems."


def test_detail_shards_strip_raw_tags_before_decoding_attribute_entities(
    tmp_path: Path,
) -> None:
    db_path = _write_tiered_shard_db(tmp_path)
    description = (
        'Build platform systems. <span data-sheets-value="{&quot;2&quot;:'
        '&quot;Use <insert base pay range> &gt;95% uptime&quot;}" '
        'data-sheets-userformat="{&quot;2&quot;:769}">attribute body</span>'
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET description = ?, description_html = NULL
            WHERE id = 'version-rich'
            """,
            (description,),
        )
    output_dir = tmp_path / "index"

    build_search_index(db_path, output_dir)

    rich = _read_detail_records(output_dir)["job-rich"]
    assert rich["description"] == "Build platform systems. attribute body"


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
        "sources",
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
        "sourceRows": 3,
        "providerRoutes": 2,
        "boards": 2,
        "jobs": 2,
        "openJobs": 1,
    }
    assert "suggestions" in manifest
    assert "dashboard" in manifest
    assert manifest["lineageAggregate"]["path"] == (
        "/data/openopps-search/lineage-aggregate.json"
    )
    lineage = _read_json(output_dir / LINEAGE_AGGREGATE_FILE)
    assert lineage["version"] == SEARCH_INDEX_VERSION
    assert lineage["counts"] == {
        "sourceRows": 3,
        "sources": 3,
        "providerRoutes": 2,
        "providers": 2,
        "boards": 2,
        "jobs": 2,
        "openJobs": 1,
    }
    assert lineage["nodes"]["sources"]
    assert lineage["nodes"]["providers"]
    assert lineage["nodes"]["boards"]
    assert lineage["edges"]["sourceProviders"]
    assert lineage["edges"]["sourceBoards"]
    assert lineage["edges"]["providerBoards"]
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


def test_search_index_synthesizes_missing_greenhouse_posting_urls(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET posting_url = NULL, apply_url = NULL
            WHERE id = 'version-current'
            """
        )
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    expected_url = "https://boards.greenhouse.io/acme/jobs/remote-1"
    detail = _read_detail_records(output_dir)["job-1"]
    assert detail["postingUrl"] == expected_url
    assert detail["applyUrl"] == expected_url

    columns = manifest["entities"]["jobs"]["columns"]
    id_index = columns.index("id")
    posting_url_index = columns.index("postingUrl")
    rows = _read_job_rows(output_dir, manifest)
    open_row = next(row for row in rows if row[id_index] == "job-1")
    assert open_row[posting_url_index] == expected_url


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

    assert manifest["facets"]["sources"] == ["fixture-a16z", "portfolio", "yc"]
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


def test_search_index_derives_seniority_when_extra_payload_missing(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    columns = manifest["entities"]["jobs"]["columns"]
    seniority_index = columns.index("seniority")
    rows = _read_job_rows(output_dir, manifest)
    open_row = next(row for row in rows if row[columns.index("status")] == "open")
    assert open_row[seniority_index] == "Principal"
    assert "Principal" in manifest["facets"]["seniorities"]


def test_snapshot_at_includes_current_version_timestamps(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET updated_at = '2026-05-01T00:00:00Z'
            WHERE id = 'version-current'
            """
        )
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    assert manifest["snapshotAt"] == "2026-05-01T00:00:00.000000Z"


def test_snapshot_at_ignores_newer_historical_versions(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE job_versions
            SET updated_at = '2026-08-01T00:00:00Z'
            WHERE id = 'version-old'
            """
        )
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    assert manifest["snapshotAt"] == "2026-02-03T04:05:06.123456Z"


_INDEXABLE_VECTORS_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "job_detail_indexable_vectors.json"
)
_INDEXABLE_VECTOR_CASES = json.loads(
    _INDEXABLE_VECTORS_PATH.read_text(encoding="utf-8")
)["vectors"]


@pytest.mark.parametrize(
    ("vector_id", "detail", "expected"),
    [
        (item["id"], item["detail"], item["indexable"])
        for item in _INDEXABLE_VECTOR_CASES
    ],
    ids=[item["id"] for item in _INDEXABLE_VECTOR_CASES],
)
def test_is_indexable_job_detail_matches_shared_golden_vectors(
    vector_id: str, detail: dict[str, Any], expected: bool
) -> None:
    assert is_indexable_job_detail(detail) is expected, vector_id


def test_search_index_child_tables_ignore_stale_job_versions(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO job_version_locations (
                id, job_version_id, ordinal, label
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                ("loc-stale", "version-old", 0, "Stale City"),
                ("loc-current", "version-current", 0, "Current City"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO job_version_skills (
                id, job_version_id, ordinal, name, level
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("skill-stale", "version-old", 0, "Rust", "expert"),
                ("skill-current", "version-current", 0, "Python", "staff"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO job_version_skill_keywords (
                id, skill_id, ordinal, keyword
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                ("kw-stale", "skill-stale", 0, "systems"),
                ("kw-current", "skill-current", 0, "platform"),
            ],
        )
    output_dir = tmp_path / "index"

    manifest = build_search_index(db_path, output_dir)

    columns = manifest["entities"]["jobs"]["columns"]
    locations_index = columns.index("locations")
    skill_tokens_index = columns.index("skillTokens")
    id_index = columns.index("id")
    rows = _read_job_rows(output_dir, manifest)
    open_row = next(row for row in rows if row[id_index] == "job-1")
    assert json.loads(open_row[locations_index]) == ["Current City"]
    assert open_row[skill_tokens_index] == "platform,python,staff"
    assert "Stale City" not in manifest["facets"]["locations"]


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
    artifact_dir = repo_root / "web" / "public" / "data" / "openopps-search"

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
    if artifact_version == SEARCH_INDEX_VERSION:
        assert manifest["lineageAggregate"]["path"] == (
            "/data/openopps-search/lineage-aggregate.json"
        )
        lineage = _read_json(artifact_dir / manifest["lineageAggregate"]["file"])
        assert lineage["version"] == artifact_version
        assert lineage["counts"]["jobs"] == manifest["counts"]["snapshot"]["jobs"]
        assert lineage["counts"]["openJobs"] == manifest["openJobCount"]
        assert len(lineage["nodes"]["sources"]) == lineage["counts"]["sources"]
        assert len(lineage["nodes"]["providers"]) == lineage["counts"]["providers"]
        assert len(lineage["nodes"]["boards"]) == lineage["counts"]["boards"]
        assert "sourceProviders" in lineage["edges"]
        assert "providerBoards" in lineage["edges"]
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
        is_indexable_job_detail(detail_records[job_id]) for job_id in indexable_ids
    )
    assert {
        Path("manifest.json"),
        Path(detail_shards["idIndexFile"]),
        Path(detail_shards["indexableIdIndexFile"]),
    } <= _artifact_files(artifact_dir)
    assert len(disk_bucket_names) == detail_shards["bucketCount"]


def test_generated_search_index_artifact_matches_local_db_when_available(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    db_path = repo_root / "kaggle" / "openoppsdb.sqlite"
    artifact_dir = repo_root / "web" / "public" / "data" / "openopps-search"
    if not db_path.exists() or not (artifact_dir / "manifest.json").exists():
        pytest.skip("local SQLite DB or generated docs search index is unavailable")
    if os.environ.get("OPENOPPS_WEB_SEARCH_INDEX_CHECK") != "1":
        pytest.skip(
            "local sqlite is not CI evidence; regen is maintainer-only "
            "(OPENOPPS_WEB_SEARCH_INDEX_CHECK=1)"
        )

    output_dir = tmp_path / "openopps-search"
    build_search_index(db_path, output_dir)

    artifact_files = _artifact_files(artifact_dir)
    output_files = _artifact_files(output_dir)
    assert artifact_files == output_files
    for filename in artifact_files:
        assert (artifact_dir / filename).read_bytes() == (
            output_dir / filename
        ).read_bytes()


def test_v7_release_generation_is_deterministic_and_additive(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    legacy_root = tmp_path / "legacy-v6"
    legacy_root.mkdir()
    legacy_sentinel = legacy_root / "sentinel.json"
    legacy_sentinel.write_text('{"version":6}\n', encoding="utf-8")
    publication_root = tmp_path / "publication-v7"

    first = build_search_release(
        db_path, publication_root, channel="staging", now=_FRESH_RELEASE_NOW
    )
    first_manifest_path = (
        publication_root / "releases" / first["releaseId"] / "manifest.json"
    )
    search_manifest_path = first_manifest_path.with_name("search-manifest.json")
    publication_policy_path = first_manifest_path.with_name("publication-policy.json")
    first_manifest_bytes = first_manifest_path.read_bytes()
    second = build_search_release(
        db_path, publication_root, channel="staging", now=_FRESH_RELEASE_NOW
    )

    assert second == first
    assert first_manifest_path.read_bytes() == first_manifest_bytes
    assert _read_json(search_manifest_path)["version"] == SEARCH_INDEX_VERSION
    publication_policy = _read_json(publication_policy_path)
    assert publication_policy["sourceCount"] == 3
    assert all(source["publicationAllowed"] for source in publication_policy["sources"])
    assert publication_policy["quality"]["jobs"] == 2
    policy_identity = publication_policy["sourcePolicy"]
    assert policy_identity["policyId"] == "source-policy-review-2026-08-13"
    assert policy_identity["reviewedAt"] == "2026-08-13"
    component_digests = {
        component["path"]: component["sha256"]
        for component in first["generator"]["components"]
    }
    assert (
        policy_identity["moduleSha256"]
        == component_digests["src/openopps/source_policy.py"]
    )
    assert (
        policy_identity["evidenceSha256"]
        == component_digests[
            "src/openopps/providers/sources/data/source_policy_evidence.json"
        ]
    )
    assert (
        policy_identity["schemaSha256"]
        == component_digests[
            "src/openopps/providers/sources/data/source_policy_evidence.schema.json"
        ]
    )
    assert (
        policy_identity["corpusSha256"]
        == component_digests["deployment/openopps-data/source-corpus-v6.json"]
    )
    assert any(
        entry["path"] == "search-manifest.json" and entry["role"] == "search-manifest"
        for entry in first["files"]
    )
    assert any(
        entry["path"] == "publication-policy.json"
        and entry["role"] == "publication-policy"
        and entry["count"] == 3
        for entry in first["files"]
    )
    assert legacy_sentinel.read_text(encoding="utf-8") == '{"version":6}\n'
    assert len(list((publication_root / "releases").iterdir())) == 1
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_release_rejects_reviewed_platform_denial_after_positive_rights_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    catalog = build_search_release.__globals__["BOARD_SOURCE_CATALOG"]
    monkeypatch.setitem(
        catalog,
        "fixture-a16z",
        SourceRecord(
            key="fixture-a16z",
            url="https://example.test/fixture-a16z",
            provider_id="getro",
            raw_metadata={
                "licenseStatus": "official_public",
                "sourceAttribution": "Positive-rights fixture.",
            },
        ),
    )

    with pytest.raises(
        ValueError,
        match="getro-terms-v3-1",
    ):
        build_search_release(
            db_path,
            publication_root,
            channel="staging",
            now=_FRESH_RELEASE_NOW,
        )

    assert not publication_root.exists()
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_release_validates_policy_graph_before_immutable_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    function_globals = build_search_release.__globals__
    original_report = function_globals["_build_publication_policy_report"]

    def tampered_report(
        *args: object, **kwargs: object
    ) -> tuple[dict[str, Any], list[str]]:
        report, errors = original_report(*args, **kwargs)
        report["sourcePolicy"]["evidenceSha256"] = "b" * 64
        return report, errors

    monkeypatch.setitem(
        function_globals,
        "_build_publication_policy_report",
        tampered_report,
    )

    with pytest.raises(ValueError, match="does not match generator component"):
        build_search_release(
            db_path,
            publication_root,
            channel="staging",
            now=_FRESH_RELEASE_NOW,
        )

    assert not (publication_root / "channels" / "staging.json").exists()
    assert not (publication_root / "releases").exists()
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_release_rejects_misresolved_source_policy_module_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = read_source_policy_inputs.__globals__["source_policy_module"]
    monkeypatch.setattr(module, "__file__", "/tmp/misresolved/source_policy.py")

    with pytest.raises(ValueError, match="module provenance"):
        read_source_policy_inputs()


def test_v7_release_reads_source_policy_corpus_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_globals = read_source_policy_inputs.__globals__
    original_read_bytes = Path.read_bytes
    corpus_suffix = Path("deployment/openopps-data/source-corpus-v6.json")
    corpus_reads = 0

    def count_corpus_reads(path: Path) -> bytes:
        nonlocal corpus_reads
        if path.as_posix().endswith(corpus_suffix.as_posix()):
            corpus_reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_corpus_reads)

    function_globals["_read_source_policy_inputs"]()

    assert corpus_reads == 1


def test_v7_release_freezes_one_sidecar_free_sqlite_state_for_all_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    function_globals = build_search_release.__globals__
    original_build = function_globals["_build_search_index_unlocked"]
    state_after_concurrent_commit: dict[str, bytes] = {}

    with sqlite3.connect(db_path) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "UPDATE job_versions SET title = ? WHERE id = ?",
            ("WAL-visible title", "version-current"),
        )
        writer.commit()
        assert Path(f"{db_path}-wal").is_file()

        def mutate_source_after_artifact_queries(
            query_path: Path, output_dir: Path, **kwargs: Any
        ) -> dict[str, Any]:
            artifact = original_build(query_path, output_dir, **kwargs)
            with sqlite3.connect(db_path) as concurrent_writer:
                concurrent_writer.execute("PRAGMA wal_autocheckpoint=0")
                concurrent_writer.execute(
                    "UPDATE sources SET raw_metadata = ? WHERE key = ?",
                    ('{"licenseStatus":"needs_review"}', "portfolio"),
                )
                concurrent_writer.commit()
            state_after_concurrent_commit["database"] = db_path.read_bytes()
            state_after_concurrent_commit["wal"] = Path(f"{db_path}-wal").read_bytes()
            return artifact

        monkeypatch.setitem(
            function_globals,
            "_build_search_index_unlocked",
            mutate_source_after_artifact_queries,
        )

        manifest = build_search_release(
            db_path,
            publication_root,
            channel="staging",
            now=_FRESH_RELEASE_NOW,
        )

        assert db_path.read_bytes() == state_after_concurrent_commit["database"]
        assert (
            Path(f"{db_path}-wal").read_bytes() == state_after_concurrent_commit["wal"]
        )

    release_root = publication_root / "releases" / manifest["releaseId"]
    search_manifest = _read_json(release_root / "search-manifest.json")
    job_rows = _read_job_rows(release_root, search_manifest)
    title_index = search_manifest["entities"]["jobs"]["columns"].index("title")

    assert any(row[title_index] == "WAL-visible title" for row in job_rows)
    assert manifest["source"]["path"] == db_path.name
    assert (
        manifest["source"]["sha256"] != hashlib.sha256(db_path.read_bytes()).hexdigest()
    )
    assert not list(tmp_path.glob("openopps-sqlite-snapshot-*"))


def test_v7_release_fails_closed_for_unreviewed_source_rights(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET raw_metadata = ? WHERE key = ?",
            ('{"licenseStatus":"needs_review"}', "portfolio"),
        )

    with pytest.raises(
        ValueError,
        match=r"(?s)rights policy:.*portfolio.*needs_review",
    ):
        build_search_release(
            db_path, tmp_path / "publication-v7", now=_FRESH_RELEASE_NOW
        )

    assert not (tmp_path / "publication-v7" / "channels" / "production.json").exists()
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_release_applies_platform_terms_as_a_non_bypassable_deny_overlay(
    tmp_path: Path,
) -> None:
    getro_key = next(
        key
        for key, record in _SEARCH_INDEX_NAMESPACE["BOARD_SOURCE_CATALOG"].items()
        if record.provider_id == "getro"
    )
    errors = source_policy_denial_errors({"facets": {"sources": [getro_key]}})

    assert errors == [
        f"source {getro_key!r} is blocked by source-policy decision 'getro-terms-v3-1'"
    ]


def test_v7_release_deny_overlay_does_not_grant_unknown_sources() -> None:
    assert (
        source_policy_denial_errors(
            {"facets": {"sources": ["uncovered-future-source"]}}
        )
        == []
    )


def test_v7_release_does_not_let_stored_metadata_grant_packaged_source_rights(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET key = ?, raw_metadata = ? WHERE key = ?",
            (
                "a16z",
                '{"licenseStatus":"official_public",'
                '"sourceAttribution":"unreviewed persisted claim"}',
                "fixture-a16z",
            ),
        )
        conn.execute(
            """
            UPDATE boards
            SET key = ?, source_key = ?, source_keys = ?
            WHERE key = ?
            """,
            ("a16z:acme", "a16z", '["a16z","portfolio"]', "fixture-a16z:acme"),
        )
        conn.execute(
            """
            UPDATE board_providers
            SET source_key = ?, board_key = ?
            WHERE board_key = ?
            """,
            ("a16z", "a16z:acme", "fixture-a16z:acme"),
        )
        conn.execute(
            "UPDATE jobs SET board_key = ? WHERE board_key = ?",
            ("a16z:acme", "fixture-a16z:acme"),
        )

    with pytest.raises(
        ValueError,
        match=r"(?s)rights policy:.*source 'a16z' has no licenseStatus",
    ):
        build_search_release(
            db_path, tmp_path / "publication-v7", now=_FRESH_RELEASE_NOW
        )


def test_v7_release_blocks_stale_by_default_and_records_degraded_override(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    stale_now = datetime(2026, 3, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="snapshot is stale by policy"):
        build_search_release(db_path, publication_root, now=stale_now)

    manifest = build_search_release(
        db_path,
        publication_root,
        now=stale_now,
        allow_stale_reason="Upstream maintenance window; operator approved degraded data.",
    )
    pointer = _read_json(publication_root / "channels" / "production.json")
    assert pointer["schemaVersion"] == 2
    assert pointer["releaseId"] == manifest["releaseId"]
    assert pointer["degradedReason"] == (
        "Upstream maintenance window; operator approved degraded data."
    )
    assert pointer["priorReleaseId"] is None
    assert pointer["promotedAt"] == "2026-03-01T00:00:00.000000Z"
    assert pointer["snapshotAgeSeconds"] > 48 * 60 * 60


def test_v7_production_release_rejects_relaxed_freshness_threshold(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"

    with pytest.raises(
        ValueError,
        match=r"production max snapshot age cannot exceed 48 hours",
    ):
        build_search_release(
            db_path,
            publication_root,
            channel="production",
            max_snapshot_age=timedelta(hours=49),
            now=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

    assert not publication_root.exists()


def test_v7_cli_rejects_relaxed_production_freshness_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SEARCH_INDEX_SCRIPT),
            "--data-db",
            str(db_path),
            "--release-root",
            str(publication_root),
            "--channel",
            "production",
            "--max-snapshot-age-hours",
            "49",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        _SEARCH_INDEX_NAMESPACE["main"]()

    assert caught.value.code == 2
    assert (
        "production max snapshot age cannot exceed 48 hours" in capsys.readouterr().err
    )
    assert not publication_root.exists()


def test_v7_channel_records_previous_release_for_rollback(tmp_path: Path) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    first = build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
            ("2026-02-04T01:00:00Z", "job-1"),
        )
    second = build_search_release(
        db_path,
        publication_root,
        now=datetime(2026, 2, 4, 2, tzinfo=timezone.utc),
    )

    pointer = _read_json(publication_root / "channels" / "production.json")
    assert second["releaseId"] != first["releaseId"]
    assert pointer["releaseId"] == second["releaseId"]
    assert pointer["priorReleaseId"] == first["releaseId"]

    repeated = build_search_release(
        db_path,
        publication_root,
        now=datetime(2026, 2, 4, 2, tzinfo=timezone.utc),
    )
    repeated_pointer = _read_json(publication_root / "channels" / "production.json")
    assert repeated["releaseId"] == second["releaseId"]
    assert repeated_pointer["priorReleaseId"] == first["releaseId"]


def test_v7_fresh_release_can_replace_a_channel_that_aged_past_48h(
    tmp_path: Path,
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    first = build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
            ("2026-03-01T00:00:00Z", "job-1"),
        )

    second = build_search_release(
        db_path,
        publication_root,
        now=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
    )

    pointer = _read_json(publication_root / "channels" / "production.json")
    assert second["releaseId"] != first["releaseId"]
    assert pointer["releaseId"] == second["releaseId"]
    assert pointer["priorReleaseId"] == first["releaseId"]
    assert pointer["degradedReason"] is None


def test_v7_mid_write_failure_preserves_live_channel_and_cleans_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    initial = build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)
    pointer = publication_root / "channels" / "production.json"
    pointer_before = pointer.read_bytes()
    releases_before = {path.name for path in (publication_root / "releases").iterdir()}
    function_globals = build_search_release.__globals__
    original_write_json = function_globals["_write_json"]

    def fail_after_writing_provider(path: Path, data: Any, *, compact: bool) -> None:
        original_write_json(path, data, compact=compact)
        if path.name == "providers.json":
            raise RuntimeError("injected staged-write failure")

    monkeypatch.setitem(function_globals, "_write_json", fail_after_writing_provider)

    with pytest.raises(RuntimeError, match="injected staged-write failure"):
        build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)

    assert pointer.read_bytes() == pointer_before
    assert (
        {path.name for path in (publication_root / "releases").iterdir()}
        == {initial["releaseId"]}
        == releases_before
    )
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_channel_write_failure_preserves_previous_release_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    initial = build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)
    pointer = publication_root / "channels" / "production.json"
    pointer_before = pointer.read_bytes()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
            ("2026-03-01T00:00:00Z", "job-1"),
        )

    function_globals = build_search_release.__globals__

    def fail_channel_write(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected channel-write failure")

    monkeypatch.setitem(
        function_globals, "atomic_write_channel_pointer", fail_channel_write
    )

    with pytest.raises(RuntimeError, match="injected channel-write failure"):
        build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)

    assert pointer.read_bytes() == pointer_before
    pointer_payload = _read_json(pointer)
    assert pointer_payload["releaseId"] == initial["releaseId"]
    assert len(list((publication_root / "releases").iterdir())) == 2
    assert not list(tmp_path.glob(".publication-v7.openopps-stage-*"))


def test_v7_post_swap_validation_failure_restores_previous_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _write_search_index_db(tmp_path)
    publication_root = tmp_path / "publication-v7"
    initial = build_search_release(db_path, publication_root, now=_FRESH_RELEASE_NOW)
    pointer = publication_root / "channels" / "production.json"
    pointer_before = pointer.read_bytes()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
            ("2026-02-04T01:00:00Z", "job-1"),
        )

    function_globals = build_search_release.__globals__
    original_validate = function_globals["validate_publication"]
    call_count = 0

    def fail_post_swap(*args: object, **kwargs: object) -> list[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_validate(*args, **kwargs)
        return ["injected post-swap failure"]

    monkeypatch.setitem(function_globals, "validate_publication", fail_post_swap)

    with pytest.raises(ValueError, match="injected post-swap failure"):
        build_search_release(
            db_path,
            publication_root,
            now=datetime(2026, 2, 4, 2, tzinfo=timezone.utc),
        )

    assert pointer.read_bytes() == pointer_before
    assert _read_json(pointer)["releaseId"] == initial["releaseId"]
    assert len(list((publication_root / "releases").iterdir())) == 2


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


def _read_detail_records(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    detail_root = artifact_dir / "jobs-details"
    records: dict[str, dict[str, Any]] = {}
    for bucket_path in detail_root.glob("*.json"):
        records.update(_read_json(bucket_path))
    return records


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

            CREATE TABLE sources (
                key TEXT PRIMARY KEY,
                url TEXT,
                raw_metadata TEXT
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
            "INSERT INTO sources (key, url, raw_metadata) VALUES (?, ?, ?)",
            [
                (
                    "fixture-a16z",
                    "https://a16z.com/portfolio/",
                    '{"licenseStatus":"official_public","sourceAttribution":"Andreessen Horowitz public portfolio."}',
                ),
                (
                    "portfolio",
                    "https://example.com/portfolio/",
                    '{"licenseStatus":"public_attribution_required","sourceAttribution":"Fixture public portfolio."}',
                ),
                (
                    "yc",
                    "https://www.ycombinator.com/companies",
                    '{"licenseStatus":"public_attribution_required","sourceAttribution":"Y Combinator public companies page."}',
                ),
            ],
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
                    "fixture-a16z:acme",
                    "fixture-a16z",
                    '["fixture-a16z","portfolio"]',
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
                    "fixture-a16z",
                    "fixture-a16z:acme",
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
                    "fixture-a16z:acme",
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
                "fixture-a16z:acme",
                "fixture-a16z",
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
                "fixture-a16z",
                "fixture-a16z:acme",
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
                    "fixture-a16z:acme",
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
                    "fixture-a16z:acme",
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
                    "Build platform systems.",
                    "<p>Build platform systems.</p>",
                    '["Build platform systems"]',
                    '["Operate reliable services"]',
                    '[{"name":"Python","level":"advanced"}]',
                    '{"summary":"Build","description":"Build platform systems."}',
                    '{"currency":"USD"}',
                    "Senior",
                    "$140k-$180k",
                    140000,
                    180000,
                    "USD",
                    "https://acme.example/jobs/rich",
                    None,
                    "2026-01-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                    '{"seniority":"Senior"}',
                ),
                (
                    "version-thin",
                    "job-thin",
                    "Untitled",
                    "[]",
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
