from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEARCH_INDEX_VERSION = 4
DESCRIPTION_SNIPPET_LEN = 200
SKILL_TOKENS_MAX_LEN = 96
DETAIL_BUCKET_COUNT = 256
DETAIL_IDS_FILE = "jobs-detail-ids.json"
JOB_CHUNK_SIZE = 1000
INITIAL_JOB_LIMIT = 250
MAX_DETAIL_PAYLOAD_CHARS = 20_000
TOP_DASHBOARD_LIMIT = 20

PROVIDER_COLUMNS = [
    "id",
    "sourceKey",
    "boardKey",
    "providerId",
    "label",
    "supportLevel",
    "countHint",
    "boardUrl",
    "lastStatus",
]
BOARD_COLUMNS = [
    "key",
    "sourceKey",
    "name",
    "domain",
    "websiteUrl",
    "staffCount",
    "numJobsHint",
]
JOB_COLUMNS = [
    "id",
    "sourceKey",
    "boardKey",
    "providerId",
    "status",
    "title",
    "company",
    "department",
    "team",
    "workplaceType",
    "remote",
    "employmentType",
    "locations",
    "salaryMin",
    "salaryMax",
    "salaryCurrency",
    "postingUrl",
    "postedAt",
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
]

FILTER_SPEC = {
    "sourceKey": "boards.source_keys merged with source_key",
    "location": "substring match on locations labels",
    "department": "substring match",
    "team": "substring match",
    "workplaceType": "substring match",
    "remote": "case-insensitive equality",
    "employmentType": "substring match",
    "salaryMin": "range overlap with job salary_min/max",
    "salaryMax": "range overlap with job salary_min/max",
    "skill": "substring match on skillTokens",
    "query": "title, company, descriptionSnippet (wide adds dept/team/locations/provider/board)",
    "postedAfter": "posted_at >= date",
    "postedBefore": "posted_at <= date",
    "status": "exact match",
}

CHUNK_FILES = {
    "providers": "providers.json",
    "boards": "boards.json",
}


def build_search_index(db_path: Path, output_dir: Path) -> dict[str, Any]:
    """Write a compact static docs search index from an OpenOpps SQLite DB."""

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_root = output_dir / "jobs-details"
    jobs_root = output_dir / "jobs"
    if detail_root.exists():
        shutil.rmtree(detail_root)
    if jobs_root.exists():
        shutil.rmtree(jobs_root)
    stale_jobs_file = output_dir / "jobs.json"
    if stale_jobs_file.exists():
        stale_jobs_file.unlink()

    with sqlite3.connect(db_path) as conn:
        providers = _fetch_rows(conn, _PROVIDERS_SQL)
        boards = _fetch_rows(conn, _BOARDS_SQL)
        jobs = _normalize_job_timestamp_rows(_fetch_rows(conn, _jobs_sql(conn)))
        source_count = _table_count(conn, "sources")
        snapshot_at = _snapshot_at(conn)
        detail_records = _fetch_job_details(conn)
        payload_snapshots = _fetch_payload_snapshots(conn)
        board_source_keys = _fetch_board_source_keys(conn)
        version_locations = _fetch_version_locations(conn)
        version_skill_tokens = _fetch_version_skill_tokens(conn)
        job_version_ids = _fetch_job_version_ids(conn)
        source_tables = _source_tables(conn)

    jobs = _enrich_job_rows(
        jobs,
        board_source_keys,
        job_version_ids=job_version_ids,
        version_locations=version_locations,
        version_skill_tokens=version_skill_tokens,
    )
    _attach_payload_snapshots(detail_records, payload_snapshots)
    jobs = _sort_job_rows(jobs)
    detail_shards = _write_detail_shards(detail_root, detail_records)

    chunks: dict[str, tuple[list[str], list[list[Any]]]] = {
        "providers": (PROVIDER_COLUMNS, providers),
        "boards": (BOARD_COLUMNS, boards),
    }

    for entity, (columns, rows) in chunks.items():
        _write_search_chunk(output_dir / CHUNK_FILES[entity], entity, columns, rows)

    job_chunks = _write_job_chunks(jobs_root, jobs)
    initial_jobs = [row for row in jobs if row[JOB_COLUMNS.index("status")] == "open"][
        :INITIAL_JOB_LIMIT
    ]
    _write_search_chunk(jobs_root / "latest.json", "jobs", JOB_COLUMNS, initial_jobs)

    open_job_count = sum(
        1 for row in jobs if row[JOB_COLUMNS.index("status")] == "open"
    )
    manifest = _build_manifest(
        db_path=db_path,
        output_dir=output_dir,
        snapshot_at=snapshot_at,
        providers=providers,
        boards=boards,
        jobs=jobs,
        source_count=source_count,
        open_job_count=open_job_count,
        detail_shards=detail_shards,
        job_chunks=job_chunks,
        source_tables=source_tables,
    )
    _write_json(output_dir / "manifest.json", manifest, compact=False)
    return manifest


def _fetch_rows(conn: sqlite3.Connection, sql: str) -> list[list[Any]]:
    return [list(row) for row in conn.execute(sql)]


def _fetch_board_source_keys(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute("SELECT key, source_key, source_keys FROM boards").fetchall()
    result: dict[str, list[str]] = {}
    for key, source_key, source_keys_json in rows:
        keys: list[str] = []
        if source_key and str(source_key).strip():
            keys.append(str(source_key).strip())
        if source_keys_json:
            try:
                parsed = json.loads(source_keys_json)
                if isinstance(parsed, list):
                    for item in parsed:
                        text = str(item).strip()
                        if text and text not in keys:
                            keys.append(text)
            except (TypeError, json.JSONDecodeError):
                pass
        result[str(key)] = keys
    return result


def _fetch_job_version_ids(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, current_version_id FROM jobs WHERE current_version_id IS NOT NULL"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _fetch_version_locations(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT job_version_id, json_group_array(label ORDER BY ordinal)
        FROM job_version_locations
        GROUP BY job_version_id
        """
    ).fetchall()
    return {str(row[0]): row[1] for row in rows if row[1]}


def _fetch_version_skill_tokens(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT
            ordered_tokens.job_version_id,
            group_concat(ordered_tokens.token)
        FROM (
            SELECT DISTINCT job_version_id, token
            FROM (
                SELECT job_version_id, lower(trim(name)) AS token
                FROM job_version_skills
                WHERE name IS NOT NULL AND trim(name) != ''
                UNION ALL
                SELECT job_version_id, lower(trim(level)) AS token
                FROM job_version_skills
                WHERE level IS NOT NULL AND trim(level) != ''
                UNION ALL
                SELECT s.job_version_id, lower(trim(k.keyword)) AS token
                FROM job_version_skills AS s
                JOIN job_version_skill_keywords AS k ON k.skill_id = s.id
                WHERE k.keyword IS NOT NULL AND trim(k.keyword) != ''
            ) AS candidate_tokens
            WHERE token IS NOT NULL AND trim(token) != ''
            ORDER BY job_version_id, token
        ) AS ordered_tokens
        GROUP BY ordered_tokens.job_version_id
        """
    ).fetchall()
    return {str(row[0]): row[1] for row in rows if row[1]}


def _enrich_job_rows(
    jobs: list[list[Any]],
    board_source_keys: dict[str, list[str]],
    *,
    job_version_ids: dict[str, str],
    version_locations: dict[str, str],
    version_skill_tokens: dict[str, str],
) -> list[list[Any]]:
    source_keys_index = JOB_COLUMNS.index("sourceKeys")
    snippet_index = JOB_COLUMNS.index("descriptionSnippet")
    locations_index = JOB_COLUMNS.index("locations")
    skill_tokens_index = JOB_COLUMNS.index("skillTokens")
    board_index = JOB_COLUMNS.index("boardKey")
    source_index = JOB_COLUMNS.index("sourceKey")
    id_index = JOB_COLUMNS.index("id")

    enriched: list[list[Any]] = []
    for row in jobs:
        next_row = list(row)
        job_id = str(next_row[id_index])
        board_key = str(next_row[board_index] or "")
        fallback_source = str(next_row[source_index] or "").strip()
        keys = board_source_keys.get(board_key) or (
            [fallback_source] if fallback_source else []
        )
        next_row[source_keys_index] = json.dumps(
            keys, ensure_ascii=False, separators=(",", ":")
        )
        snippet = next_row[snippet_index]
        if isinstance(snippet, str):
            next_row[snippet_index] = _plain_snippet(snippet)
        version_id = job_version_ids.get(job_id, "")
        location_override = version_locations.get(version_id)
        if location_override:
            next_row[locations_index] = location_override
        skill_tokens = version_skill_tokens.get(version_id)
        if skill_tokens:
            next_row[skill_tokens_index] = skill_tokens[:SKILL_TOKENS_MAX_LEN]
        enriched.append(next_row)
    return enriched


def _normalize_job_timestamp_rows(jobs: list[list[Any]]) -> list[list[Any]]:
    observed_index = JOB_COLUMNS.index("latestObservedAt")
    normalized: list[list[Any]] = []
    for row in jobs:
        next_row = list(row[: len(JOB_COLUMNS)])
        next_row[observed_index] = _latest_timestamp_value(row[len(JOB_COLUMNS) :])
        normalized.append(next_row)
    return normalized


def _sort_job_rows(jobs: list[list[Any]]) -> list[list[Any]]:
    status_index = JOB_COLUMNS.index("status")
    observed_index = JOB_COLUMNS.index("latestObservedAt")
    company_index = JOB_COLUMNS.index("company")
    title_index = JOB_COLUMNS.index("title")
    id_index = JOB_COLUMNS.index("id")

    def sort_key(row: list[Any]) -> tuple[int, str, float, str, str, str]:
        status = str(row[status_index] or "").strip()
        observed_at = _parse_timestamp(row[observed_index])
        observed_key = observed_at.timestamp() if observed_at else float("-inf")
        return (
            0 if status == "open" else 1,
            status,
            -observed_key,
            str(row[company_index] or "").casefold(),
            str(row[title_index] or "").casefold(),
            str(row[id_index] or ""),
        )

    return sorted(jobs, key=sort_key)


def _plain_snippet(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:DESCRIPTION_SNIPPET_LEN]


def _fetch_job_details(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(_job_details_sql(conn)).fetchall()
    details: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = str(row[0])
        details[job_id] = {
            "id": job_id,
            "status": row[1],
            "sourceKey": row[2],
            "boardKey": row[3],
            "providerId": row[4],
            "remoteId": row[5],
            "title": row[6],
            "company": row[7],
            "department": row[8],
            "team": row[9],
            "workplaceType": row[10],
            "remote": row[11],
            "employmentType": row[12],
            "locations": _parse_json_list(row[13]),
            "salaryMin": row[14],
            "salaryMax": row[15],
            "salaryCurrency": row[16],
            "description": row[17],
            "descriptionHtml": row[18],
            "responsibilities": _parse_json_list(row[19]),
            "qualifications": _parse_json_list(row[20]),
            "skills": _parse_json_list(row[21]),
            "jobDescription": _parse_json_object(row[22]),
            "compensation": _parse_json_object(row[23]),
            "experience": row[24],
            "salary": row[25],
            "postingUrl": row[26],
            "applyUrl": row[27],
            "postedAt": row[28],
            "updatedAt": row[29],
            "versionCreatedAt": row[30],
            "firstSeenAt": row[31],
            "lastSeenAt": row[32],
            "closedAt": row[33],
            "syncedAt": row[34],
            "version": row[35],
            "contentHash": row[36] or row[38],
            "payloadHash": row[37] or row[39],
            "jobExtra": _parse_json_object(row[40]),
            "versionExtra": _parse_json_object(row[41]),
        }
    return details


def _job_details_sql(conn: sqlite3.Connection) -> str:
    job_closed_at = _column_expr(conn, "jobs", "j", "closed_at")
    job_current_content_hash = _column_expr(
        conn, "jobs", "j", "current_content_hash"
    )
    job_current_payload_hash = _column_expr(conn, "jobs", "j", "current_payload_hash")
    job_extra = _column_expr(conn, "jobs", "j", "extra_payload")
    version_number = _column_expr(conn, "job_versions", "v", "version")
    version_content_hash = _column_expr(conn, "job_versions", "v", "content_hash")
    version_payload_hash = _column_expr(conn, "job_versions", "v", "payload_hash")
    version_extra = _column_expr(conn, "job_versions", "v", "extra_payload")
    return f"""
    SELECT
        j.id,
        j.status,
        b.source_key,
        j.board_key,
        j.provider_id,
        j.remote_id,
        v.title,
        v.company,
        v.department,
        v.team,
        v.workplace_type,
        v.remote,
        v.employment_type,
        v.locations,
        v.salary_min,
        v.salary_max,
        v.salary_currency,
        v.description,
        v.description_html,
        v.responsibilities,
        v.qualifications,
        v.skills,
        v.job_description,
        v.compensation,
        v.experience,
        v.salary,
        v.posting_url,
        v.apply_url,
        v.posted_at,
        v.updated_at,
        v.created_at,
        j.first_seen_at,
        j.last_seen_at,
        {job_closed_at},
        j.synced_at,
        {version_number},
        {version_content_hash},
        {version_payload_hash},
        {job_current_content_hash},
        {job_current_payload_hash},
        {job_extra},
        {version_extra}
    FROM jobs AS j
    JOIN job_versions AS v ON v.id = j.current_version_id
    LEFT JOIN boards AS b ON b.key = j.board_key
    ORDER BY j.id
    """


def _parse_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _fetch_payload_snapshots(
    conn: sqlite3.Connection,
) -> dict[str, list[dict[str, Any]]]:
    if not _has_table(conn, "job_payload_snapshots"):
        return {}
    rows = conn.execute(
        """
        SELECT job_id, payload_kind, payload_hash, payload, observed_at
        FROM job_payload_snapshots
        ORDER BY job_id, payload_kind, observed_at DESC, id
        """
    ).fetchall()
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for job_id, kind, payload_hash, payload, observed_at in rows:
        snapshots.setdefault(str(job_id), []).append(
            {
                "kind": kind,
                "payloadHash": payload_hash,
                "observedAt": observed_at,
                **_bounded_payload(payload),
            }
        )
    return snapshots


def _attach_payload_snapshots(
    details: dict[str, dict[str, Any]],
    snapshots: dict[str, list[dict[str, Any]]],
) -> None:
    for job_id, records in snapshots.items():
        if job_id in details and records:
            details[job_id]["payloadSnapshots"] = records


def _bounded_payload(value: Any) -> dict[str, Any]:
    parsed = _parse_json_object(value)
    if parsed is None:
        parsed = {"value": value} if value not in (None, "") else {}
    serialized = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    if len(serialized) <= MAX_DETAIL_PAYLOAD_CHARS:
        return {"payload": parsed, "truncated": False}
    preview = serialized[:MAX_DETAIL_PAYLOAD_CHARS]
    return {
        "payload": {"preview": preview},
        "truncated": True,
        "originalChars": len(serialized),
    }


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _has_table(conn, table_name):
        return 0
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {_sqlite_identifier(table_name)}"
        ).fetchone()[0]
    )


def _source_tables(conn: sqlite3.Connection) -> list[str]:
    table_names = [
        "sources",
        "board_providers",
        "boards",
        "jobs",
        "job_versions",
        "job_version_locations",
        "job_version_skills",
        "job_version_skill_keywords",
        "job_payload_snapshots",
    ]
    return [table_name for table_name in table_names if _has_table(conn, table_name)]


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _has_table(conn, table_name):
        return False
    return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({_sqlite_identifier(table_name)})"))


def _column_expr(
    conn: sqlite3.Connection,
    table_name: str,
    alias: str,
    column_name: str,
    fallback: str = "NULL",
) -> str:
    if _has_column(conn, table_name, column_name):
        return f"{alias}.{_sqlite_identifier(column_name)}"
    return fallback


def _sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _detail_bucket(job_id: str) -> str:
    hash_value = 0
    for char in job_id:
        hash_value = ((hash_value * 31) + ord(char)) & 0xFFFFFFFF
    return f"{hash_value % DETAIL_BUCKET_COUNT:02x}"


def _write_detail_shards(
    detail_root: Path, records: dict[str, dict[str, Any]], *, open_only: bool = True
) -> dict[str, Any]:
    if open_only:
        records = {
            job_id: payload
            for job_id, payload in records.items()
            if payload.get("status") == "open"
        }
    detail_root.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for job_id, payload in sorted(records.items()):
        bucket = _detail_bucket(job_id)
        shard_payload = {
            key: value
            for key, value in payload.items()
            if key != "status" and value not in (None, "", [], {})
        }
        buckets.setdefault(bucket, {})[job_id] = shard_payload

    for bucket, bucket_payload in sorted(buckets.items()):
        path = detail_root / f"{bucket}.json"
        path.write_text(
            json.dumps(bucket_payload, ensure_ascii=False, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )

    _write_json(
        detail_root.parent / DETAIL_IDS_FILE,
        {
            "version": SEARCH_INDEX_VERSION,
            "count": len(records),
            "ids": sorted(records),
        },
        compact=True,
    )

    return {
        "root": "/data/openopps-search/jobs-details",
        "format": "bucket-map",
        "idIndexPath": f"/data/openopps-search/{DETAIL_IDS_FILE}",
        "idIndexFile": DETAIL_IDS_FILE,
        "bucketCount": DETAIL_BUCKET_COUNT,
        "count": len(records),
        "buckets": {
            bucket: {
                "path": f"/data/openopps-search/jobs-details/{bucket}.json",
                "count": len(bucket_payload),
            }
            for bucket, bucket_payload in sorted(buckets.items())
        },
    }


def _write_job_chunks(
    jobs_root: Path, jobs: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, start in enumerate(range(0, len(jobs), JOB_CHUNK_SIZE)):
        rows = jobs[start : start + JOB_CHUNK_SIZE]
        filename = f"chunks/{index:04d}.json"
        path = jobs_root / filename
        _write_search_chunk(path, "jobs", JOB_COLUMNS, rows)
        chunks.append(
            {
                "index": index,
                "path": f"/data/openopps-search/jobs/{filename}",
                "file": f"jobs/{filename}",
                "count": len(rows),
            }
        )
    return chunks


def _build_manifest(
    *,
    db_path: Path,
    output_dir: Path,
    snapshot_at: str | None,
    providers: Sequence[Sequence[Any]],
    boards: Sequence[Sequence[Any]],
    jobs: Sequence[Sequence[Any]],
    source_count: int,
    open_job_count: int,
    detail_shards: dict[str, Any],
    job_chunks: Sequence[dict[str, Any]],
    source_tables: Sequence[str],
) -> dict[str, Any]:
    counters = _manifest_counters(providers=providers, boards=boards, jobs=jobs)

    jobs_manifest = {
        "path": "/data/openopps-search/jobs/latest.json",
        "file": "jobs/latest.json",
        "initialPath": "/data/openopps-search/jobs/latest.json",
        "chunkSize": JOB_CHUNK_SIZE,
        "columns": JOB_COLUMNS,
        "count": len(jobs),
        "chunks": list(job_chunks),
    }
    jobs_manifest["detailPath"] = "/data/openopps-search/jobs-details/{bucket}.json"

    return {
        "version": SEARCH_INDEX_VERSION,
        "snapshotAt": snapshot_at,
        "openJobCount": open_job_count,
        "counts": {
            "catalog": {
                "source": "/data/openopps-data.json",
                "note": "Package catalog counts are generated by scripts/generate_docs_data.py.",
            },
            "snapshot": {
                "database": _stable_path(db_path),
                "sourceRows": source_count,
                "providerRoutes": len(providers),
                "boards": len(boards),
                "jobs": len(jobs),
                "openJobs": open_job_count,
            },
        },
        "kaggleDatasetId": "wyattowalsh/openoppsdb",
        "source": {
            "database": _stable_path(db_path),
            "tables": list(source_tables),
        },
        "defaultEntity": "jobs",
        "defaultFilters": {"jobs": {"status": "open"}},
        "filterSpec": FILTER_SPEC,
        "detailShards": detail_shards,
        "entities": {
            "providers": _entity_manifest(
                output_dir, "providers", PROVIDER_COLUMNS, len(providers)
            ),
            "boards": _entity_manifest(
                output_dir, "boards", BOARD_COLUMNS, len(boards)
            ),
            "jobs": jobs_manifest,
        },
        "facets": {
            key: _facet_values(counter)
            for key, counter in counters["facets"].items()
        },
        "suggestions": {
            key: _suggestion_values(counter)
            for key, counter in counters["suggestions"].items()
        },
        "dashboard": _dashboard_payload(
            snapshot_at=snapshot_at,
            source_count=source_count,
            providers=providers,
            boards=boards,
            jobs=jobs,
            open_job_count=open_job_count,
            detail_shards=detail_shards,
            job_chunks=job_chunks,
            counters=counters,
        ),
    }


def _entity_manifest(
    output_dir: Path, entity: str, columns: list[str], count: int
) -> dict[str, Any]:
    return {
        "path": f"/data/openopps-search/{CHUNK_FILES[entity]}",
        "file": str((output_dir / CHUNK_FILES[entity]).name),
        "columns": columns,
        "count": count,
    }


def _manifest_counters(
    *,
    providers: Sequence[Sequence[Any]],
    boards: Sequence[Sequence[Any]],
    jobs: Sequence[Sequence[Any]],
) -> dict[str, dict[str, Counter[str]]]:
    source_counter: Counter[str] = Counter()
    job_source_counter: Counter[str] = Counter()
    provider_counter: Counter[str] = Counter()
    location_counter: Counter[str] = Counter()
    skill_counter: Counter[str] = Counter()

    for row in providers:
        _add_value(source_counter, row[PROVIDER_COLUMNS.index("sourceKey")])
        _add_value(provider_counter, row[PROVIDER_COLUMNS.index("providerId")])
    for row in boards:
        _add_value(source_counter, row[BOARD_COLUMNS.index("sourceKey")])
    for row in jobs:
        source_values = _source_values_from_job(row)
        for value in source_values:
            _add_value(source_counter, value)
            _add_value(job_source_counter, value)
        _add_value(provider_counter, row[JOB_COLUMNS.index("providerId")])
        for value in _json_array_values(row[JOB_COLUMNS.index("locations")]):
            _add_value(location_counter, value)
        for value in _skill_token_values(row[JOB_COLUMNS.index("skillTokens")]):
            _add_value(skill_counter, value)

    facets = {
        "sources": source_counter,
        "providerIds": provider_counter,
        "jobStatuses": _counter_from_rows(jobs, JOB_COLUMNS, "status"),
        "supportLevels": _counter_from_rows(
            providers, PROVIDER_COLUMNS, "supportLevel"
        ),
        "routeStatuses": _counter_from_rows(
            providers, PROVIDER_COLUMNS, "lastStatus"
        ),
        "workplaces": _combined_counter(
            _counter_from_rows(jobs, JOB_COLUMNS, "workplaceType"),
            _counter_from_rows(jobs, JOB_COLUMNS, "remote"),
        ),
        "employmentTypes": _counter_from_rows(jobs, JOB_COLUMNS, "employmentType"),
        "locations": location_counter,
        "departments": _counter_from_rows(jobs, JOB_COLUMNS, "department"),
        "teams": _counter_from_rows(jobs, JOB_COLUMNS, "team"),
        "companies": _counter_from_rows(jobs, JOB_COLUMNS, "company"),
        "skills": skill_counter,
        "salaryCurrencies": _counter_from_rows(jobs, JOB_COLUMNS, "salaryCurrency"),
    }
    suggestions = {
        "sources": source_counter,
        "providers": provider_counter,
        "locations": location_counter,
        "departments": facets["departments"],
        "teams": facets["teams"],
        "companies": facets["companies"],
        "skills": skill_counter,
        "workplaces": facets["workplaces"],
        "employmentTypes": facets["employmentTypes"],
        "jobStatuses": facets["jobStatuses"],
        "salaryCurrencies": facets["salaryCurrencies"],
    }
    return {
        "facets": facets,
        "suggestions": suggestions,
        "dashboard": {
            "jobSources": job_source_counter,
            "providers": provider_counter,
            "locations": location_counter,
            "departments": facets["departments"],
            "teams": facets["teams"],
            "companies": facets["companies"],
            "skills": skill_counter,
            "supportLevels": facets["supportLevels"],
            "routeStatuses": facets["routeStatuses"],
        },
    }


def _dashboard_payload(
    *,
    snapshot_at: str | None,
    source_count: int,
    providers: Sequence[Sequence[Any]],
    boards: Sequence[Sequence[Any]],
    jobs: Sequence[Sequence[Any]],
    open_job_count: int,
    detail_shards: dict[str, Any],
    job_chunks: Sequence[dict[str, Any]],
    counters: dict[str, dict[str, Counter[str]]],
) -> dict[str, Any]:
    dashboard = counters["dashboard"]
    return {
        "snapshotAt": snapshot_at,
        "totals": {
            "sourceRows": source_count,
            "providerRoutes": len(providers),
            "boards": len(boards),
            "jobs": len(jobs),
            "openJobs": open_job_count,
        },
        "top": {
            "sourcesByJobs": _top_values(dashboard["jobSources"]),
            "providersByJobs": _top_values(dashboard["providers"]),
            "locations": _top_values(dashboard["locations"]),
            "departments": _top_values(dashboard["departments"]),
            "teams": _top_values(dashboard["teams"]),
            "companies": _top_values(dashboard["companies"]),
            "skills": _top_values(dashboard["skills"]),
        },
        "dataQuality": _job_quality_metrics(jobs),
        "routeHealth": {
            "supportLevels": _top_values(dashboard["supportLevels"], limit=None),
            "routeStatuses": _top_values(dashboard["routeStatuses"], limit=None),
        },
        "artifacts": {
            "jobChunks": len(job_chunks),
            "detailShardBuckets": len(detail_shards.get("buckets", {})),
            "detailShardRecords": detail_shards.get("count", 0),
        },
    }


def _job_quality_metrics(jobs: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    checks = [
        ("postingUrl", lambda row: _has_text(row[JOB_COLUMNS.index("postingUrl")])),
        (
            "description",
            lambda row: _has_text(row[JOB_COLUMNS.index("descriptionSnippet")]),
        ),
        (
            "locations",
            lambda row: bool(_json_array_values(row[JOB_COLUMNS.index("locations")])),
        ),
        ("department", lambda row: _has_text(row[JOB_COLUMNS.index("department")])),
        (
            "compensation",
            lambda row: any(
                _has_text(row[JOB_COLUMNS.index(column)])
                for column in ("salaryMin", "salaryMax", "salaryCurrency")
            ),
        ),
        ("skills", lambda row: bool(_skill_token_values(row[JOB_COLUMNS.index("skillTokens")]))),
    ]
    total = len(jobs)
    metrics: list[dict[str, Any]] = []
    for key, predicate in checks:
        count = sum(1 for row in jobs if predicate(row))
        metrics.append(
            {
                "key": key,
                "count": count,
                "total": total,
                "percentage": round((count / total) * 100, 2) if total else 0,
            }
        )
    return metrics


def _counter_from_rows(
    rows: Sequence[Sequence[Any]], columns: Sequence[str], column: str
) -> Counter[str]:
    counter: Counter[str] = Counter()
    index = columns.index(column)
    for row in rows:
        _add_value(counter, row[index])
    return counter


def _combined_counter(*counters: Counter[str]) -> Counter[str]:
    combined: Counter[str] = Counter()
    for counter in counters:
        combined.update(counter)
    return combined


def _add_value(counter: Counter[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        counter[text] += 1


def _source_values_from_job(row: Sequence[Any]) -> list[str]:
    parsed = _json_array_values(row[JOB_COLUMNS.index("sourceKeys")])
    if parsed:
        return parsed
    source = str(row[JOB_COLUMNS.index("sourceKey")] or "").strip()
    return [source] if source else []


def _json_array_values(value: Any) -> list[str]:
    values = _parse_json_list(value)
    return [str(item).strip() for item in values if str(item).strip()]


def _skill_token_values(value: Any) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _facet_values(counter: Counter[str]) -> list[str]:
    return sorted(counter, key=lambda value: value.casefold())


def _suggestion_values(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {
            "value": value,
            "label": value,
            "count": count,
            "normalized": _normalized_suggestion(value),
        }
        for value, count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]


def _top_values(
    counter: Counter[str], *, limit: int | None = TOP_DASHBOARD_LIMIT
) -> list[dict[str, Any]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))
    if limit is not None:
        items = items[:limit]
    return [{"value": value, "count": count} for value, count in items]


def _normalized_suggestion(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _has_text(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _write_search_chunk(
    path: Path, entity: str, columns: list[str], rows: Sequence[Sequence[Any]]
) -> None:
    _write_json(
        path,
        {
            "version": SEARCH_INDEX_VERSION,
            "entity": entity,
            "columns": columns,
            "count": len(rows),
            "rows": rows,
        },
        compact=True,
    )


def _nonblank_values(*groups: Sequence[Any]) -> set[str]:
    values: set[str] = set()
    for group in groups:
        for value in group:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                values.add(text)
    return values


def _snapshot_at(conn: sqlite3.Connection) -> str | None:
    rows = conn.execute(
        """
        SELECT value
        FROM (
            SELECT detected_at AS value FROM board_providers
            UNION ALL
            SELECT synced_at AS value FROM boards
            UNION ALL
            SELECT synced_at AS value FROM jobs
            UNION ALL
            SELECT last_seen_at AS value FROM jobs
            UNION ALL
            SELECT first_seen_at AS value FROM jobs
            UNION ALL
            SELECT updated_at AS value FROM job_versions
            UNION ALL
            SELECT created_at AS value FROM job_versions
        )
        WHERE value IS NOT NULL AND value != ''
        """
    ).fetchall()
    return _latest_timestamp_value(row[0] for row in rows)


def _latest_timestamp_value(values: Iterable[Any]) -> str | None:
    parsed = [_parse_timestamp(value) for value in values]
    timestamps = [value for value in parsed if value is not None]
    if not timestamps:
        return None
    return _format_utc_timestamp(max(timestamps))


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc_timestamp(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stable_path(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return path.name


def _write_json(path: Path, data: Any, *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        content = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Generate the docs static search index from OpenOpps SQLite data."
    )
    parser.add_argument(
        "--data-db",
        type=Path,
        default=repo_root / "kaggle" / "openoppsdb.sqlite",
        help="Path to the SQLite database snapshot.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "docs" / "public" / "data" / "openopps-search",
        help="Directory for generated static search-index JSON files.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    manifest = build_search_index(
        db_path=args.data_db.expanduser(),
        output_dir=args.output_dir.expanduser(),
    )
    counts = {
        entity: details["count"] for entity, details in manifest["entities"].items()
    }
    print(
        "Generated docs search index: "
        f"{counts['providers']} providers, {counts['boards']} boards, "
        f"{counts['jobs']} jobs ({manifest.get('openJobCount', 0)} open)"
    )


_PROVIDERS_SQL = """
SELECT
    id,
    source_key,
    board_key,
    provider_id,
    label,
    support_level,
    count_hint,
    board_url,
    last_status
FROM board_providers
ORDER BY provider_id, source_key, board_key, id
"""

_BOARDS_SQL = """
SELECT
    key,
    source_key,
    name,
    domain,
    website_url,
    staff_count,
    num_jobs_hint
FROM boards
ORDER BY lower(coalesce(name, '')), key
"""

def _jobs_sql(conn: sqlite3.Connection) -> str:
    job_closed_at = _column_expr(conn, "jobs", "j", "closed_at")
    job_current_content_hash = _column_expr(
        conn, "jobs", "j", "current_content_hash"
    )
    job_current_payload_hash = _column_expr(conn, "jobs", "j", "current_payload_hash")
    version_content_hash = _column_expr(conn, "job_versions", "v", "content_hash")
    version_payload_hash = _column_expr(conn, "job_versions", "v", "payload_hash")
    return f"""
    SELECT
        j.id,
        b.source_key,
        j.board_key,
        j.provider_id,
        j.status,
        v.title,
        v.company,
        v.department,
        v.team,
        v.workplace_type,
        v.remote,
        v.employment_type,
        v.locations,
        v.salary_min,
        v.salary_max,
        v.salary_currency,
        v.posting_url,
        v.posted_at,
        NULL,
        NULL,
        coalesce(v.description, v.description_html, ''),
        '',
        j.synced_at,
        j.first_seen_at,
        j.last_seen_at,
        {job_closed_at},
        coalesce({version_content_hash}, {job_current_content_hash}),
        coalesce({version_payload_hash}, {job_current_payload_hash}),
        v.updated_at,
        v.created_at,
        j.synced_at,
        j.last_seen_at,
        j.first_seen_at,
        {job_closed_at}
    FROM jobs AS j
    JOIN job_versions AS v ON v.id = j.current_version_id
    LEFT JOIN boards AS b ON b.key = j.board_key
    ORDER BY
        CASE j.status WHEN 'open' THEN 0 ELSE 1 END,
        j.status,
        lower(coalesce(v.company, '')),
        lower(coalesce(v.title, '')),
        j.id
    """

if __name__ == "__main__":
    main()
