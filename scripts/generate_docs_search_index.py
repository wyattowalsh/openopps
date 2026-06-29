from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEARCH_INDEX_VERSION = 3
DESCRIPTION_SNIPPET_LEN = 200
SKILL_TOKENS_MAX_LEN = 96
DETAIL_BUCKET_COUNT = 256
JOB_CHUNK_SIZE = 1000
INITIAL_JOB_LIMIT = 250

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
        jobs = _normalize_job_timestamp_rows(_fetch_rows(conn, _JOBS_SQL))
        snapshot_at = _snapshot_at(conn)
        detail_records = _fetch_job_details(conn)
        board_source_keys = _fetch_board_source_keys(conn)
        version_locations = _fetch_version_locations(conn)
        version_skill_tokens = _fetch_version_skill_tokens(conn)
        job_version_ids = _fetch_job_version_ids(conn)

    jobs = _enrich_job_rows(
        jobs,
        board_source_keys,
        job_version_ids=job_version_ids,
        version_locations=version_locations,
        version_skill_tokens=version_skill_tokens,
    )
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
        open_job_count=open_job_count,
        detail_shards=detail_shards,
        job_chunks=job_chunks,
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
            s.job_version_id,
            group_concat(DISTINCT token)
        FROM (
            SELECT job_version_id, lower(trim(name)) AS token
            FROM job_version_skills
            WHERE name IS NOT NULL AND trim(name) != ''
            UNION
            SELECT job_version_id, lower(trim(level)) AS token
            FROM job_version_skills
            WHERE level IS NOT NULL AND trim(level) != ''
            UNION
            SELECT s.job_version_id, lower(trim(k.keyword)) AS token
            FROM job_version_skills AS s
            JOIN job_version_skill_keywords AS k ON k.skill_id = s.id
            WHERE k.keyword IS NOT NULL AND trim(k.keyword) != ''
        ) AS s
        WHERE token IS NOT NULL AND trim(token) != ''
        GROUP BY s.job_version_id
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
    rows = conn.execute(_JOB_DETAILS_SQL).fetchall()
    details: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = str(row[0])
        details[job_id] = {
            "id": job_id,
            "status": row[1],
            "description": row[2],
            "descriptionHtml": row[3],
            "responsibilities": _parse_json_list(row[4]),
            "qualifications": _parse_json_list(row[5]),
            "skills": _parse_json_list(row[6]),
            "jobDescription": _parse_json_object(row[7]),
            "compensation": _parse_json_object(row[8]),
            "experience": row[9],
            "salary": row[10],
            "applyUrl": row[11],
            "postingUrl": row[12],
        }
    return details


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
    for job_id, payload in records.items():
        bucket = _detail_bucket(job_id)
        shard_payload = {
            key: value
            for key, value in payload.items()
            if key != "status" and value not in (None, "", [], {})
        }
        buckets.setdefault(bucket, {})[job_id] = shard_payload

    for bucket, bucket_payload in buckets.items():
        path = detail_root / f"{bucket}.json"
        path.write_text(
            json.dumps(bucket_payload, ensure_ascii=False, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )

    return {
        "root": "/data/openopps-search/jobs-details",
        "format": "bucket-map",
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
    open_job_count: int,
    detail_shards: dict[str, Any],
    job_chunks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    provider_ids = sorted(
        _nonblank_values(
            [row[PROVIDER_COLUMNS.index("providerId")] for row in providers],
            [row[JOB_COLUMNS.index("providerId")] for row in jobs],
        )
    )
    sources = sorted(
        _nonblank_values(
            [row[PROVIDER_COLUMNS.index("sourceKey")] for row in providers],
            [row[BOARD_COLUMNS.index("sourceKey")] for row in boards],
            [row[JOB_COLUMNS.index("sourceKey")] for row in jobs],
        )
    )
    workplaces = sorted(
        _nonblank_values(
            [row[JOB_COLUMNS.index("workplaceType")] for row in jobs],
            [row[JOB_COLUMNS.index("remote")] for row in jobs],
        )
    )

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
        "kaggleDatasetId": "wyattowalsh/openoppsdb",
        "source": {
            "database": _stable_path(db_path),
            "tables": [
                "board_providers",
                "boards",
                "jobs",
                "job_versions",
                "job_version_locations",
                "job_version_skills",
            ],
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
            "sources": sources,
            "providerIds": provider_ids,
            "jobStatuses": sorted(
                _nonblank_values([row[JOB_COLUMNS.index("status")] for row in jobs])
            ),
            "supportLevels": sorted(
                _nonblank_values(
                    [row[PROVIDER_COLUMNS.index("supportLevel")] for row in providers]
                )
            ),
            "routeStatuses": sorted(
                _nonblank_values(
                    [row[PROVIDER_COLUMNS.index("lastStatus")] for row in providers]
                )
            ),
            "workplaces": workplaces,
            "employmentTypes": sorted(
                _nonblank_values(
                    [row[JOB_COLUMNS.index("employmentType")] for row in jobs]
                )
            ),
        },
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

_JOBS_SQL = """
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
    v.updated_at,
    v.created_at,
    j.synced_at,
    j.last_seen_at,
    j.first_seen_at
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

_JOB_DETAILS_SQL = """
SELECT
    j.id,
    j.status,
    v.description,
    v.description_html,
    v.responsibilities,
    v.qualifications,
    v.skills,
    v.job_description,
    v.compensation,
    v.experience,
    v.salary,
    v.apply_url,
    v.posting_url
FROM jobs AS j
JOIN job_versions AS v ON v.id = j.current_version_id
"""


if __name__ == "__main__":
    main()
