from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from openopps.models import derive_seniority_from_fields
from openopps.providers.boards.tokens import greenhouse_token_from_url

SEARCH_INDEX_VERSION = 6
DESCRIPTION_SNIPPET_LEN = 200
DESCRIPTION_SNIPPET_SOURCE_LEN = 2048
DETAIL_DESCRIPTION_TEXT_MAX_LEN = 4000
# Text projection matrix (see docs/content/docs/data-model.mdx):
# - Kaggle/SQLite export previews: 512 chars (SQLITE_PREVIEW_TEXT_MAX_CHARS)
# - Docs search T2 detail shards: 4000 chars plain text (HTML stripped)
# - Parquet/JSONL exports: full normalized fields from SQLite
SKILL_TOKENS_MAX_LEN = 96
DETAIL_BUCKET_COUNT = 1024
DETAIL_IDS_FILE = "jobs-detail-ids.json"
INDEXABLE_IDS_FILE = "jobs-indexable-ids.json"
LINEAGE_AGGREGATE_FILE = "lineage-aggregate.json"
JOB_CHUNK_SIZE = 1000
INITIAL_JOB_LIMIT = 250
TOP_DASHBOARD_LIMIT = 20
DESCRIPTION_CLEAN_INPUT_MAX_LEN = 16_000

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
    "seniority",
    "daysOpen",
]

DETAIL_TIER1_KEYS = frozenset(
    {
        "id",
        "status",
        "sourceKey",
        "boardKey",
        "providerId",
        "remoteId",
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
        "applyUrl",
        "postedAt",
        "updatedAt",
        "versionCreatedAt",
        "firstSeenAt",
        "lastSeenAt",
        "closedAt",
        "syncedAt",
        "version",
        "contentHash",
        "payloadHash",
        "detailTier",
    }
)
DETAIL_TIER2_BODY_KEYS = frozenset(
    {
        "description",
        "responsibilities",
        "qualifications",
        "skills",
        "jobDescription",
        "compensation",
        "experience",
        "salary",
        "jobExtra",
        "versionExtra",
    }
)
DETAIL_PUBLIC_KEYS = DETAIL_TIER1_KEYS | DETAIL_TIER2_BODY_KEYS
DETAIL_EXCLUDED_KEYS = frozenset({"payloadSnapshots"})

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

_WHITESPACE_RE = re.compile(r"\s+")
_SHEETS_SPAN_RE = re.compile(
    r'(?is)<span\b(?=[\s\S]{0,8000}?data-sheets-value=)[\s\S]{0,8000}?data-sheets-userformat="[\s\S]{0,2000}?">'
)
_HTML_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^>]*)?/?>")
_TRAILING_HTML_TAG_RE = re.compile(r"(?s)</?[A-Za-z][A-Za-z0-9:-]*(?:\s.*)?$")
_NORMALIZED_SUGGESTION_RE = re.compile(r"[^a-z0-9]+")


def build_search_index(db_path: Path, output_dir: Path) -> dict[str, Any]:
    """Write a compact static docs search index from an OpenOpps SQLite DB."""

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    with _search_index_build_lock(output_dir):
        return _build_search_index_unlocked(db_path, output_dir)


@contextmanager
def _search_index_build_lock(output_dir: Path) -> Iterable[None]:
    digest = hashlib.sha256(str(output_dir.resolve()).encode("utf-8")).hexdigest()[
        :16
    ]
    lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / (
        f"openopps-search-index-{digest}.lock"
    )
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _build_search_index_unlocked(db_path: Path, output_dir: Path) -> dict[str, Any]:
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
        _progress("fetch providers")
        providers = _fetch_rows(conn, _PROVIDERS_SQL)
        _progress("fetch boards")
        boards = _fetch_rows(conn, _BOARDS_SQL)
        _progress("count sources")
        source_count = _table_count(conn, "sources")
        _progress("compute snapshot timestamp")
        snapshot_at = _snapshot_at(conn)
        _progress("fetch job details")
        detail_records = _fetch_job_details(conn)
        _progress("fetch board source keys")
        board_source_keys = _fetch_board_source_keys(conn)
        _progress("fetch current version ids")
        job_version_ids = _fetch_job_version_ids(conn)
        current_version_ids = set(job_version_ids.values())
        _progress("fetch version locations")
        version_locations = _fetch_version_locations(conn, current_version_ids)
        _progress("fetch version skill tokens")
        version_skill_tokens = _fetch_version_skill_tokens(conn, current_version_ids)
        _progress("fetch version extras")
        version_extras = _fetch_version_extras(conn, current_version_ids)
        _progress("list source tables")
        source_tables = _source_tables(conn)
        _progress("fetch sync dashboard stats")
        sync_stats = _fetch_sync_dashboard_stats(conn, snapshot_at)

    version_experience = {
        job_version_ids[job_id]: detail.get("experience")
        for job_id, detail in detail_records.items()
        if job_id in job_version_ids
    }
    _progress("build jobs from details")
    jobs = _jobs_from_detail_records(detail_records)
    _progress("enrich jobs")
    jobs = _enrich_job_rows(
        jobs,
        board_source_keys,
        job_version_ids=job_version_ids,
        version_locations=version_locations,
        version_skill_tokens=version_skill_tokens,
        version_extras=version_extras,
        version_experience=version_experience,
        snapshot_at=snapshot_at,
    )
    _progress("sort jobs")
    jobs = _sort_job_rows(jobs)
    _progress("compute indexable job ids")
    indexable_job_ids = _indexable_job_detail_ids(detail_records)
    _progress("write indexable job ids")
    _write_indexable_job_ids(output_dir, indexable_job_ids)
    indexable_id_set = set(indexable_job_ids)
    _progress("write detail shards")
    detail_shards = _write_detail_shards(
        detail_root, detail_records, indexable_ids=indexable_id_set
    )
    detail_shards["indexableIdIndexPath"] = (
        f"/data/openopps-search/{INDEXABLE_IDS_FILE}"
    )
    detail_shards["indexableIdIndexFile"] = INDEXABLE_IDS_FILE
    detail_shards["indexableCount"] = len(indexable_job_ids)

    chunks: dict[str, tuple[list[str], list[list[Any]]]] = {
        "providers": (PROVIDER_COLUMNS, providers),
        "boards": (BOARD_COLUMNS, boards),
    }

    for entity, (columns, rows) in chunks.items():
        _progress(f"write {entity} chunk")
        _write_search_chunk(output_dir / CHUNK_FILES[entity], entity, columns, rows)

    _progress("write job chunks")
    job_chunks = _write_job_chunks(jobs_root, jobs)
    initial_jobs = [row for row in jobs if row[JOB_COLUMNS.index("status")] == "open"][
        :INITIAL_JOB_LIMIT
    ]
    _progress("write latest jobs chunk")
    _write_search_chunk(jobs_root / "latest.json", "jobs", JOB_COLUMNS, initial_jobs)

    open_job_count = sum(
        1 for row in jobs if row[JOB_COLUMNS.index("status")] == "open"
    )
    _progress("build manifest")
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
        sync_stats=sync_stats,
    )
    _progress("write lineage aggregate")
    lineage = _lineage_aggregate_payload(
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
    _write_json(output_dir / LINEAGE_AGGREGATE_FILE, lineage, compact=True)
    manifest["lineageAggregate"] = {
        "path": f"/data/openopps-search/{LINEAGE_AGGREGATE_FILE}",
        "file": LINEAGE_AGGREGATE_FILE,
        "count": lineage["counts"],
    }
    _progress("write manifest")
    _write_json(output_dir / "manifest.json", manifest, compact=False)
    return manifest


def _fetch_rows(conn: sqlite3.Connection, sql: str) -> list[list[Any]]:
    return [list(row) for row in conn.execute(sql)]


def _progress(message: str) -> None:
    if os.environ.get("OPENOPPS_SEARCH_INDEX_PROGRESS"):
        print(f"docs-search: {message}", flush=True)


def _jobs_from_detail_records(details: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for index, (job_id, detail) in enumerate(details.items(), start=1):
        rows.append(
            [
                job_id,
                detail.get("sourceKey"),
                detail.get("boardKey"),
                detail.get("providerId"),
                detail.get("status"),
                detail.get("title"),
                detail.get("company"),
                detail.get("department"),
                detail.get("team"),
                detail.get("workplaceType"),
                detail.get("remote"),
                detail.get("employmentType"),
                json.dumps(
                    detail.get("locations") or [],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                detail.get("salaryMin"),
                detail.get("salaryMax"),
                detail.get("salaryCurrency"),
                detail.get("postingUrl"),
                detail.get("postedAt"),
                _latest_timestamp_value(
                    (
                        detail.get("updatedAt"),
                        detail.get("versionCreatedAt"),
                        detail.get("syncedAt"),
                        detail.get("lastSeenAt"),
                        detail.get("firstSeenAt"),
                        detail.get("closedAt"),
                    )
                ),
                None,
                _snippet_source(detail),
                "",
                detail.get("syncedAt"),
                detail.get("firstSeenAt"),
                detail.get("lastSeenAt"),
                detail.get("closedAt"),
                detail.get("contentHash"),
                detail.get("payloadHash"),
                None,
                None,
            ]
        )
        if index % 10_000 == 0:
            _progress(f"build jobs from details: {index}")
    return rows


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


def _fetch_greenhouse_tokens(conn: sqlite3.Connection) -> dict[str, str]:
    token_column = _column_expr(conn, "board_providers", "bp", "token")
    board_url_column = _column_expr(conn, "board_providers", "bp", "board_url")
    rows = conn.execute(
        f"""
        SELECT bp.board_key, {token_column}, {board_url_column}
        FROM board_providers AS bp
        WHERE bp.provider_id = 'greenhouse'
        ORDER BY bp.source_key, bp.id
        """
    )
    tokens: dict[str, str] = {}
    for board_key, token, board_url in rows:
        key = str(board_key or "").strip()
        if not key or key in tokens:
            continue
        value = str(token or "").strip()
        if not value and board_url:
            value = greenhouse_token_from_url(str(board_url)) or ""
        if value:
            tokens[key] = value
    return tokens


def _snippet_source(detail: dict[str, Any]) -> str:
    return _job_detail_description_text(
        detail,
        clean_input_limit=DESCRIPTION_SNIPPET_SOURCE_LEN,
    )[:DESCRIPTION_SNIPPET_SOURCE_LEN]


def _fetch_job_version_ids(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, current_version_id FROM jobs WHERE current_version_id IS NOT NULL"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _current_version_id_values(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT current_version_id
        FROM jobs
        WHERE current_version_id IS NOT NULL
          AND current_version_id != ''
        """
    )
    return {str(row[0]) for row in rows}


def _ensure_current_versions_temp_table(
    conn: sqlite3.Connection, current_version_ids: set[str]
) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.openopps_current_versions")
    conn.execute(
        "CREATE TEMP TABLE openopps_current_versions (version_id TEXT PRIMARY KEY)"
    )
    if current_version_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO openopps_current_versions (version_id) VALUES (?)",
            ((version_id,) for version_id in current_version_ids),
        )


def _fetch_version_locations(
    conn: sqlite3.Connection, current_version_ids: set[str]
) -> dict[str, str]:
    if not current_version_ids or not _has_table(conn, "job_version_locations"):
        return {}

    _ensure_current_versions_temp_table(conn, current_version_ids)
    rows = conn.execute(
        """
        SELECT jvl.job_version_id, jvl.label, jvl.ordinal
        FROM job_version_locations AS jvl
        JOIN temp.openopps_current_versions AS cv
          ON cv.version_id = jvl.job_version_id
        """
    )
    grouped: dict[str, list[tuple[int, str | None]]] = {}
    for index, (version_id, label, ordinal) in enumerate(rows, start=1):
        key = str(version_id)
        ordinal_key = int(ordinal) if ordinal is not None else 0
        grouped.setdefault(key, []).append(
            (ordinal_key, str(label) if label is not None else None)
        )
        if index % 25_000 == 0:
            _progress(f"fetch version locations: {index}")

    return {
        version_id: json.dumps(
            [
                value
                for _, value in sorted(
                    values,
                    key=lambda item: (
                        item[0],
                        "" if item[1] is None else str(item[1]),
                    ),
                )
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for version_id, values in grouped.items()
        if values
    }


def _fetch_version_skill_tokens(
    conn: sqlite3.Connection, current_version_ids: set[str]
) -> dict[str, str]:
    if not current_version_ids:
        return {}

    _ensure_current_versions_temp_table(conn, current_version_ids)
    skills = conn.execute(
        """
        SELECT s.id, s.job_version_id, s.name, s.level
        FROM job_version_skills AS s
        JOIN temp.openopps_current_versions AS cv
          ON cv.version_id = s.job_version_id
        """
    )
    tokens_by_version: dict[str, set[str]] = {}
    current_skill_versions: dict[str, str] = {}
    for index, (skill_id, version_id, name, level) in enumerate(skills, start=1):
        version_key = str(version_id)
        current_skill_versions[str(skill_id)] = version_key
        tokens = tokens_by_version.setdefault(version_key, set())
        for value in (name, level):
            token = _clean_text(value).lower()
            if token:
                tokens.add(token)
        if index % 25_000 == 0:
            _progress(f"fetch version skill tokens: skills {index}")

    if not _has_table(conn, "job_version_skill_keywords"):
        return {
            version_id: ",".join(sorted(tokens))
            for version_id, tokens in tokens_by_version.items()
            if tokens
        }

    keywords = conn.execute(
        """
        SELECT k.skill_id, k.keyword
        FROM job_version_skill_keywords AS k
        JOIN job_version_skills AS s ON s.id = k.skill_id
        JOIN temp.openopps_current_versions AS cv
          ON cv.version_id = s.job_version_id
        """
    )
    for index, (skill_id, keyword) in enumerate(keywords, start=1):
        version_key = current_skill_versions.get(str(skill_id))
        if not version_key:
            continue
        token = _clean_text(keyword).lower()
        if token:
            tokens_by_version.setdefault(version_key, set()).add(token)
        if index % 50_000 == 0:
            _progress(f"fetch version skill tokens: keywords {index}")

    return {
        version_id: ",".join(sorted(tokens))
        for version_id, tokens in tokens_by_version.items()
        if tokens
    }


def _fetch_version_extras(
    conn: sqlite3.Connection, current_version_ids: set[str]
) -> dict[str, dict[str, Any]]:
    if not current_version_ids or not _has_column(conn, "job_versions", "extra_payload"):
        return {}

    rows = conn.execute(
        """
        SELECT id, extra_payload
        FROM job_versions
        WHERE extra_payload IS NOT NULL
        """
    )
    extras: dict[str, dict[str, Any]] = {}
    for index, (version_id, extra_payload) in enumerate(rows, start=1):
        key = str(version_id)
        if key not in current_version_ids:
            continue
        parsed = _parse_json_object(extra_payload)
        if parsed:
            extras[key] = parsed
        if index % 25_000 == 0:
            _progress(f"fetch version extras: {index}")
    return extras


def _enrich_job_rows(
    jobs: list[list[Any]],
    board_source_keys: dict[str, list[str]],
    *,
    job_version_ids: dict[str, str],
    version_locations: dict[str, str],
    version_skill_tokens: dict[str, str],
    version_extras: dict[str, dict[str, Any]],
    version_experience: dict[str, Any] | None = None,
    snapshot_at: str | None,
) -> list[list[Any]]:
    source_keys_index = JOB_COLUMNS.index("sourceKeys")
    snippet_index = JOB_COLUMNS.index("descriptionSnippet")
    locations_index = JOB_COLUMNS.index("locations")
    skill_tokens_index = JOB_COLUMNS.index("skillTokens")
    board_index = JOB_COLUMNS.index("boardKey")
    source_index = JOB_COLUMNS.index("sourceKey")
    id_index = JOB_COLUMNS.index("id")
    title_index = JOB_COLUMNS.index("title")
    seniority_index = JOB_COLUMNS.index("seniority")
    days_open_index = JOB_COLUMNS.index("daysOpen")
    first_seen_index = JOB_COLUMNS.index("firstSeenAt")
    snapshot_dt = _parse_timestamp(snapshot_at)
    experience_by_version = version_experience or {}

    enriched: list[list[Any]] = []
    for index, row in enumerate(jobs, start=1):
        next_row = list(row[: len(JOB_COLUMNS)])
        while len(next_row) < len(JOB_COLUMNS):
            next_row.append(None)
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
        version_extra = version_extras.get(version_id, {})
        seniority = version_extra.get("seniority")
        if not seniority:
            title = str(next_row[title_index] or "").strip()
            experience = experience_by_version.get(version_id)
            experience_text = str(experience).strip() if experience else None
            if title or experience_text:
                seniority = derive_seniority_from_fields(title, experience_text)
        if seniority:
            next_row[seniority_index] = str(seniority).strip()
        first_seen = _parse_timestamp(next_row[first_seen_index])
        if first_seen and snapshot_dt:
            next_row[days_open_index] = max((snapshot_dt - first_seen).days, 0)
        enriched.append(next_row)
        if index % 10_000 == 0:
            _progress(f"enrich jobs: {index}")
    return enriched


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
    return _description_source_text(
        value,
        clean_input_limit=DESCRIPTION_SNIPPET_SOURCE_LEN,
    )[:DESCRIPTION_SNIPPET_LEN]


def _fetch_job_details(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    job_closed_at = _column_expr(conn, "jobs", "j", "closed_at")
    job_current_content_hash = _column_expr(
        conn, "jobs", "j", "current_content_hash"
    )
    job_current_payload_hash = _column_expr(conn, "jobs", "j", "current_payload_hash")
    job_extra = "NULL"
    version_number = _column_expr(conn, "job_versions", "v", "version")
    version_content_hash = _column_expr(conn, "job_versions", "v", "content_hash")
    version_payload_hash = _column_expr(conn, "job_versions", "v", "payload_hash")
    version_responsibilities = _column_expr(
        conn, "job_versions", "v", "responsibilities"
    )
    version_qualifications = _column_expr(
        conn, "job_versions", "v", "qualifications"
    )
    version_skills = _column_expr(conn, "job_versions", "v", "skills")
    version_job_description = _column_expr(
        conn, "job_versions", "v", "job_description"
    )
    version_compensation = _column_expr(conn, "job_versions", "v", "compensation")
    version_extra = _column_expr(conn, "job_versions", "v", "extra_payload")

    _progress("fetch job details: jobs")
    job_rows = conn.execute(
        f"""
        SELECT
            j.id,
            j.status,
            j.board_key,
            j.provider_id,
            j.remote_id,
            j.current_version_id,
            j.first_seen_at,
            j.last_seen_at,
            {job_closed_at},
            j.synced_at,
            {job_current_content_hash},
            {job_current_payload_hash},
            {job_extra}
        FROM jobs AS j
        WHERE j.current_version_id IS NOT NULL
        """
    ).fetchall()
    current_version_ids = {str(row[5]) for row in job_rows if row[5]}
    _ensure_current_versions_temp_table(conn, current_version_ids)
    _progress("fetch job details: boards")
    board_sources = {
        str(key): source_key
        for key, source_key in conn.execute("SELECT key, source_key FROM boards")
    }
    greenhouse_tokens = _fetch_greenhouse_tokens(conn)

    _progress("fetch job details: versions")
    version_rows = conn.execute(
        f"""
        SELECT
            v.id,
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
            {version_responsibilities},
            {version_qualifications},
            {version_skills},
            {version_job_description},
            {version_compensation},
            v.experience,
            v.salary,
            v.posting_url,
            v.apply_url,
            v.posted_at,
            v.updated_at,
            v.created_at,
            {version_number},
            {version_content_hash},
            {version_payload_hash},
            {version_extra}
        FROM job_versions AS v
        JOIN temp.openopps_current_versions AS cv ON cv.version_id = v.id
        """
    )
    versions = {}
    for index, row in enumerate(version_rows, start=1):
        versions[str(row[0])] = row
        if index % 10_000 == 0:
            _progress(f"fetch job details: versions {index}")

    _progress("fetch job details: assemble")
    details: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(job_rows, start=1):
        (
            job_id,
            status,
            board_key,
            provider_id,
            remote_id,
            current_version_id,
            first_seen_at,
            last_seen_at,
            closed_at,
            synced_at,
            job_content_hash,
            job_payload_hash,
            job_extra_payload,
        ) = row
        version = versions.get(str(current_version_id))
        if not version:
            continue
        (
            _version_id,
            title,
            company,
            department,
            team,
            workplace_type,
            remote,
            employment_type,
            locations,
            salary_min,
            salary_max,
            salary_currency,
            description,
            description_html,
            responsibilities,
            qualifications,
            skills,
            job_description,
            compensation,
            experience,
            salary,
            posting_url,
            apply_url,
            posted_at,
            updated_at,
            version_created_at,
            version,
            version_content_hash_value,
            version_payload_hash_value,
            version_extra_payload,
        ) = version
        posting_url = _normalized_job_posting_url(
            provider_id=provider_id,
            board_key=board_key,
            remote_id=remote_id,
            posting_url=posting_url,
            greenhouse_tokens=greenhouse_tokens,
        )
        apply_url = _normalized_job_apply_url(
            provider_id=provider_id,
            apply_url=apply_url,
            posting_url=posting_url,
        )
        key = str(job_id)
        details[key] = {
            "id": key,
            "status": status,
            "sourceKey": board_sources.get(str(board_key)),
            "boardKey": board_key,
            "providerId": provider_id,
            "remoteId": remote_id,
            "title": title,
            "company": company,
            "department": department,
            "team": team,
            "workplaceType": workplace_type,
            "remote": remote,
            "employmentType": employment_type,
            "locations": _parse_json_list(locations),
            "salaryMin": salary_min,
            "salaryMax": salary_max,
            "salaryCurrency": salary_currency,
            "description": description,
            "descriptionHtml": description_html,
            "responsibilities": _parse_json_list(responsibilities),
            "qualifications": _parse_json_list(qualifications),
            "skills": _parse_json_list(skills),
            "jobDescription": _parse_json_object(job_description),
            "compensation": _parse_json_object(compensation),
            "experience": experience,
            "salary": salary,
            "postingUrl": posting_url,
            "applyUrl": apply_url,
            "postedAt": posted_at,
            "updatedAt": updated_at,
            "versionCreatedAt": version_created_at,
            "firstSeenAt": first_seen_at,
            "lastSeenAt": last_seen_at,
            "closedAt": closed_at,
            "syncedAt": synced_at,
            "version": version,
            "contentHash": version_content_hash_value or job_content_hash,
            "payloadHash": version_payload_hash_value or job_payload_hash,
            "jobExtra": _parse_json_object(job_extra_payload),
            "versionExtra": _parse_json_object(version_extra_payload),
        }
        if index % 10_000 == 0:
            _progress(f"fetch job details: assemble {index}")
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


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if "  " not in text and not any(char.isspace() and char != " " for char in text):
        return text
    return _WHITESPACE_RE.sub(" ", text).strip()


def _strip_html(value: str, *, clean_input_limit: int | None = None) -> str:
    value = _bounded_description_input(value, clean_input_limit)
    if "<" not in value:
        if "&" not in value:
            return value
        decoded = _decode_html_entities(value)
        if "<" not in decoded:
            return decoded
        return _remove_html_markup(decoded)
    text = _remove_html_markup(value)
    text = _decode_html_entities(text)
    return _remove_html_markup(text)


def _remove_html_markup(value: str) -> str:
    text = value
    text = _SHEETS_SPAN_RE.sub(" ", text)
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    return _TRAILING_HTML_TAG_RE.sub(" ", text)


def _decode_html_entities(value: str) -> str:
    text = value
    for _ in range(5):
        decoded = unescape(text)
        if decoded == text:
            return decoded
        text = decoded
    return text


def _bounded_description_input(value: str, limit: int | None) -> str:
    if limit is None:
        return value
    # Snippets and public detail bodies are bounded downstream. Keep enough raw
    # input to survive dense markup without running regex cleanup over full pages.
    max_len = max(DESCRIPTION_CLEAN_INPUT_MAX_LEN, limit * 4)
    if len(value) <= max_len:
        return value
    return value[:max_len]


def _description_source_text(
    value: Any, *, clean_input_limit: int | None = None
) -> str:
    if not isinstance(value, str):
        return ""
    return _clean_text(_strip_html(value, clean_input_limit=clean_input_limit))


def _job_detail_description_text(
    detail: dict[str, Any], *, clean_input_limit: int | None = None
) -> str:
    description = _description_source_text(
        detail.get("description"),
        clean_input_limit=clean_input_limit,
    )
    if description:
        return description
    return _description_source_text(
        detail.get("descriptionHtml"),
        clean_input_limit=clean_input_limit,
    )


def _safe_job_external_url(value: Any) -> str | None:
    raw = _clean_text(value)
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        if parsed.username or parsed.password:
            return None
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return parsed.geturl()
    except ValueError:
        return None
    return None


def _normalized_job_posting_url(
    *,
    provider_id: Any,
    board_key: Any,
    remote_id: Any,
    posting_url: Any,
    greenhouse_tokens: dict[str, str],
) -> str | None:
    safe_url = _safe_job_external_url(posting_url)
    if safe_url:
        return safe_url
    if _has_text(posting_url) or str(provider_id or "") != "greenhouse":
        return None
    token = greenhouse_tokens.get(str(board_key or "").strip())
    remote_text = str(remote_id or "").strip()
    if not token or not remote_text:
        return None
    fallback = (
        "https://boards.greenhouse.io/"
        f"{quote(token.strip(), safe='')}/jobs/{quote(remote_text, safe='')}"
    )
    return _safe_job_external_url(fallback)


def _normalized_job_apply_url(
    *,
    provider_id: Any,
    apply_url: Any,
    posting_url: str | None,
) -> str | None:
    safe_url = _safe_job_external_url(apply_url)
    if safe_url:
        return safe_url
    if _has_text(apply_url) or str(provider_id or "") != "greenhouse":
        return None
    return posting_url


def _primary_job_external_url(detail: dict[str, Any]) -> str | None:
    return _safe_job_external_url(detail.get("postingUrl")) or _safe_job_external_url(
        detail.get("applyUrl")
    )


def _is_indexable_job_detail(detail: dict[str, Any]) -> bool:
    """Mirror docs/lib/jobs-static-data.ts isIndexableJobDetail criteria."""

    status = _clean_text(detail.get("status")).lower()
    has_open_status = not status or status == "open"
    has_core_content = bool(
        _clean_text(detail.get("title"))
        and _clean_text(detail.get("company"))
        and _job_detail_description_text(
            detail,
            clean_input_limit=DESCRIPTION_SNIPPET_SOURCE_LEN,
        )
    )
    has_date = any(
        _parse_timestamp(value)
        for value in (
            detail.get("postedAt"),
            detail.get("firstSeenAt"),
            detail.get("versionCreatedAt"),
        )
    )
    return bool(
        has_open_status
        and has_core_content
        and has_date
        and _primary_job_external_url(detail)
    )


def _indexable_job_detail_ids(detail_records: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        job_id
        for job_id, detail in detail_records.items()
        if _is_indexable_job_detail(detail)
    )


def _write_indexable_job_ids(output_dir: Path, job_ids: Sequence[str]) -> None:
    _write_json(
        output_dir / INDEXABLE_IDS_FILE,
        {
            "version": SEARCH_INDEX_VERSION,
            "count": len(job_ids),
            "ids": list(job_ids),
        },
        compact=True,
    )


def _public_detail_description(payload: dict[str, Any]) -> str:
    return _bounded_public_text(
        _job_detail_description_text(payload),
        DETAIL_DESCRIPTION_TEXT_MAX_LEN,
    )


def _bounded_public_text(value: str, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _public_job_description(value: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if "description" not in value:
        return value
    has_canonical_description = bool(
        _description_source_text(payload.get("descriptionHtml"))
        or _public_detail_description(payload)
    )
    if not has_canonical_description:
        return value
    compact = dict(value)
    compact.pop("description", None)
    return compact or None


def _detail_bucket(job_id: str) -> str:
    hash_value = 0
    for char in job_id:
        hash_value = ((hash_value * 31) + ord(char)) & 0xFFFFFFFF
    return f"{hash_value % DETAIL_BUCKET_COUNT:02x}"


def _detail_shard_payload(
    payload: dict[str, Any], *, indexable: bool
) -> dict[str, Any]:
    shard_payload: dict[str, Any] = {
        "detailTier": "T2" if indexable else "T1",
    }
    for key, value in payload.items():
        if key in DETAIL_EXCLUDED_KEYS:
            continue
        if key not in DETAIL_PUBLIC_KEYS:
            continue
        if not indexable and key not in DETAIL_TIER1_KEYS:
            continue
        if key == "description":
            description = _public_detail_description(payload)
            if description:
                shard_payload[key] = description
            continue
        if key == "jobDescription":
            job_description = _public_job_description(value, payload)
            if job_description:
                shard_payload[key] = job_description
            continue
        if value not in (None, "", [], {}):
            shard_payload[key] = value
    return shard_payload


def _write_detail_shards(
    detail_root: Path,
    records: dict[str, dict[str, Any]],
    *,
    indexable_ids: set[str],
    open_only: bool = True,
) -> dict[str, Any]:
    if open_only:
        records = {
            job_id: payload
            for job_id, payload in records.items()
            if payload.get("status") == "open"
        }
    detail_root.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    tier_counts = {"T1": 0, "T2": 0}
    for index, (job_id, payload) in enumerate(sorted(records.items()), start=1):
        bucket = _detail_bucket(job_id)
        indexable = job_id in indexable_ids
        shard_payload = _detail_shard_payload(payload, indexable=indexable)
        tier_counts[shard_payload["detailTier"]] += 1
        buckets.setdefault(bucket, {})[job_id] = shard_payload
        if index % 10_000 == 0:
            _progress(f"write detail shards: bucket payloads {index}")

    for index, (bucket, bucket_payload) in enumerate(sorted(buckets.items()), start=1):
        path = detail_root / f"{bucket}.json"
        path.write_text(
            json.dumps(bucket_payload, ensure_ascii=False, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        if index % 32 == 0:
            _progress(f"write detail shards: files {index}")

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
        "tierCounts": tier_counts,
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
    sync_stats: dict[str, Any] | None = None,
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
            sync_stats=sync_stats,
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
        "seniorities": _counter_from_rows(jobs, JOB_COLUMNS, "seniority"),
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
    sync_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dashboard = counters["dashboard"]
    payload = {
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
            "detailShardTiers": detail_shards.get("tierCounts", {}),
        },
    }
    if sync_stats:
        payload["sync"] = sync_stats
    return payload


def _lineage_aggregate_payload(
    *,
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
    source_nodes: dict[str, dict[str, Any]] = {}
    provider_nodes: dict[str, dict[str, Any]] = {}
    board_nodes: dict[str, dict[str, Any]] = {}
    source_provider_edges: dict[tuple[str, str], dict[str, Any]] = {}
    source_board_edges: dict[tuple[str, str], dict[str, Any]] = {}
    provider_board_edges: dict[tuple[str, str], dict[str, Any]] = {}

    def source_node(source_key: str) -> dict[str, Any]:
        return source_nodes.setdefault(
            source_key,
            {
                "id": source_key,
                "label": source_key,
                "boards": set(),
                "providers": set(),
                "routes": 0,
                "jobs": 0,
                "openJobs": 0,
                "closedJobs": 0,
                "descriptionJobs": 0,
                "locationJobs": 0,
                "compensationJobs": 0,
                "latestObservedAt": None,
            },
        )

    def provider_node(provider_id: str) -> dict[str, Any]:
        return provider_nodes.setdefault(
            provider_id,
            {
                "id": provider_id,
                "label": provider_id,
                "sources": set(),
                "boards": set(),
                "routes": 0,
                "jobs": 0,
                "openJobs": 0,
                "closedJobs": 0,
                "descriptionJobs": 0,
                "locationJobs": 0,
                "compensationJobs": 0,
                "supportLevels": Counter(),
                "routeStatuses": Counter(),
                "latestObservedAt": None,
            },
        )

    def board_node(board_key: str) -> dict[str, Any]:
        return board_nodes.setdefault(
            board_key,
            {
                "id": board_key,
                "label": board_key,
                "sourceKey": None,
                "name": None,
                "domain": None,
                "providers": set(),
                "routes": 0,
                "jobs": 0,
                "openJobs": 0,
                "closedJobs": 0,
                "descriptionJobs": 0,
                "locationJobs": 0,
                "compensationJobs": 0,
                "supportLevels": Counter(),
                "routeStatuses": Counter(),
                "latestObservedAt": None,
            },
        )

    for row in boards:
        board_key = str(row[BOARD_COLUMNS.index("key")] or "").strip()
        if not board_key:
            continue
        source_key = str(row[BOARD_COLUMNS.index("sourceKey")] or "").strip()
        node = board_node(board_key)
        node["sourceKey"] = source_key or node["sourceKey"]
        node["name"] = row[BOARD_COLUMNS.index("name")] or node["name"]
        node["domain"] = row[BOARD_COLUMNS.index("domain")] or node["domain"]
        if source_key:
            source_node(source_key)["boards"].add(board_key)
            source_board_edges.setdefault(
                (source_key, board_key),
                {
                    "sourceKey": source_key,
                    "boardKey": board_key,
                    "jobs": 0,
                    "openJobs": 0,
                    "boards": 1,
                },
            )

    for row in providers:
        source_key = str(row[PROVIDER_COLUMNS.index("sourceKey")] or "").strip()
        board_key = str(row[PROVIDER_COLUMNS.index("boardKey")] or "").strip()
        provider_id = str(row[PROVIDER_COLUMNS.index("providerId")] or "").strip()
        support = str(row[PROVIDER_COLUMNS.index("supportLevel")] or "").strip()
        status = str(row[PROVIDER_COLUMNS.index("lastStatus")] or "").strip()
        if not provider_id:
            continue
        provider = provider_node(provider_id)
        provider["routes"] += 1
        if source_key:
            provider["sources"].add(source_key)
            source = source_node(source_key)
            source["providers"].add(provider_id)
            source["routes"] += 1
            edge = source_provider_edges.setdefault(
                (source_key, provider_id),
                {
                    "sourceKey": source_key,
                    "providerId": provider_id,
                    "routes": 0,
                    "jobs": 0,
                    "openJobs": 0,
                },
            )
            edge["routes"] += 1
        if support:
            provider["supportLevels"][support] += 1
        if status:
            provider["routeStatuses"][status] += 1
        if board_key:
            provider["boards"].add(board_key)
            board = board_node(board_key)
            board["providers"].add(provider_id)
            board["routes"] += 1
            if source_key and not board.get("sourceKey"):
                board["sourceKey"] = source_key
            if support:
                board["supportLevels"][support] += 1
            if status:
                board["routeStatuses"][status] += 1
            pb_edge = provider_board_edges.setdefault(
                (provider_id, board_key),
                {
                    "providerId": provider_id,
                    "boardKey": board_key,
                    "sourceKey": source_key,
                    "routes": 0,
                    "jobs": 0,
                    "openJobs": 0,
                    "supportLevels": Counter(),
                    "routeStatuses": Counter(),
                },
            )
            pb_edge["routes"] += 1
            if support:
                pb_edge["supportLevels"][support] += 1
            if status:
                pb_edge["routeStatuses"][status] += 1

    for row in jobs:
        board_key = str(row[JOB_COLUMNS.index("boardKey")] or "").strip()
        provider_id = str(row[JOB_COLUMNS.index("providerId")] or "").strip()
        status = str(row[JOB_COLUMNS.index("status")] or "").strip()
        is_open = status == "open"
        observed_at = row[JOB_COLUMNS.index("latestObservedAt")]
        has_description = _has_text(row[JOB_COLUMNS.index("descriptionSnippet")])
        has_location = bool(_json_array_values(row[JOB_COLUMNS.index("locations")]))
        has_compensation = any(
            _has_text(row[JOB_COLUMNS.index(column)])
            for column in ("salaryMin", "salaryMax", "salaryCurrency")
        )
        sources = _source_values_from_job(row)

        if provider_id:
            provider = provider_node(provider_id)
            _increment_lineage_job_metrics(
                provider,
                board_key=board_key,
                is_open=is_open,
                has_description=has_description,
                has_location=has_location,
                has_compensation=has_compensation,
                observed_at=observed_at,
            )
        if board_key:
            board = board_node(board_key)
            _increment_lineage_job_metrics(
                board,
                provider_id=provider_id,
                is_open=is_open,
                has_description=has_description,
                has_location=has_location,
                has_compensation=has_compensation,
                observed_at=observed_at,
            )
        if provider_id and board_key:
            pb_edge = provider_board_edges.setdefault(
                (provider_id, board_key),
                {
                    "providerId": provider_id,
                    "boardKey": board_key,
                    "sourceKey": sources[0] if sources else None,
                    "routes": 0,
                    "jobs": 0,
                    "openJobs": 0,
                    "supportLevels": Counter(),
                    "routeStatuses": Counter(),
                },
            )
            pb_edge["jobs"] += 1
            if is_open:
                pb_edge["openJobs"] += 1

        for source_key in sources:
            source = source_node(source_key)
            _increment_lineage_job_metrics(
                source,
                provider_id=provider_id,
                board_key=board_key,
                is_open=is_open,
                has_description=has_description,
                has_location=has_location,
                has_compensation=has_compensation,
                observed_at=observed_at,
            )
            if provider_id:
                edge = source_provider_edges.setdefault(
                    (source_key, provider_id),
                    {
                        "sourceKey": source_key,
                        "providerId": provider_id,
                        "routes": 0,
                        "jobs": 0,
                        "openJobs": 0,
                    },
                )
                edge["jobs"] += 1
                if is_open:
                    edge["openJobs"] += 1
            if board_key:
                edge = source_board_edges.setdefault(
                    (source_key, board_key),
                    {
                        "sourceKey": source_key,
                        "boardKey": board_key,
                        "jobs": 0,
                        "openJobs": 0,
                        "boards": 1,
                    },
                )
                edge["jobs"] += 1
                if is_open:
                    edge["openJobs"] += 1

    return {
        "version": SEARCH_INDEX_VERSION,
        "snapshotAt": snapshot_at,
        "source": {
            "database": "kaggle/openoppsdb.sqlite",
            "tables": list(source_tables),
        },
        "counts": {
            "sourceRows": source_count,
            "sources": len(source_nodes),
            "providerRoutes": len(providers),
            "providers": len(provider_nodes),
            "boards": len(board_nodes),
            "jobs": len(jobs),
            "openJobs": open_job_count,
        },
        "nodes": {
            "sources": _finalize_lineage_nodes(source_nodes.values()),
            "providers": _finalize_lineage_nodes(provider_nodes.values()),
            "boards": _finalize_lineage_nodes(board_nodes.values()),
        },
        "edges": {
            "sourceProviders": _finalize_lineage_edges(source_provider_edges.values()),
            "sourceBoards": _finalize_lineage_edges(source_board_edges.values()),
            "providerBoards": _finalize_lineage_edges(provider_board_edges.values()),
        },
        "artifacts": {
            "jobChunks": len(job_chunks),
            "detailShardBuckets": len(detail_shards.get("buckets", {})),
            "detailShardRecords": detail_shards.get("count", 0),
            "detailShardTiers": detail_shards.get("tierCounts", {}),
        },
    }


def _increment_lineage_job_metrics(
    node: dict[str, Any],
    *,
    is_open: bool,
    has_description: bool,
    has_location: bool,
    has_compensation: bool,
    observed_at: Any,
    provider_id: str | None = None,
    board_key: str | None = None,
) -> None:
    node["jobs"] += 1
    if is_open:
        node["openJobs"] += 1
    else:
        node["closedJobs"] += 1
    if has_description:
        node["descriptionJobs"] += 1
    if has_location:
        node["locationJobs"] += 1
    if has_compensation:
        node["compensationJobs"] += 1
    if provider_id:
        node.setdefault("providers", set()).add(provider_id)
    if board_key:
        node.setdefault("boards", set()).add(board_key)
    node["latestObservedAt"] = _latest_timestamp_value(
        (node.get("latestObservedAt"), observed_at)
    )


def _finalize_lineage_nodes(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for node in nodes:
        item = dict(node)
        for key in ("sources", "providers", "boards"):
            if isinstance(item.get(key), set):
                values = sorted(item[key])
                item[f"{key}Count"] = len(values)
                item[key] = values[:50]
        for key in ("supportLevels", "routeStatuses"):
            if isinstance(item.get(key), Counter):
                item[key] = _top_values(item[key], limit=None)
        total = int(item.get("jobs") or 0)
        item["quality"] = {
            "description": _lineage_percentage(item.get("descriptionJobs"), total),
            "locations": _lineage_percentage(item.get("locationJobs"), total),
            "compensation": _lineage_percentage(item.get("compensationJobs"), total),
        }
        finalized.append(item)
    return sorted(
        finalized,
        key=lambda item: (
            -int(item.get("jobs") or 0),
            str(item.get("label") or item.get("id") or "").casefold(),
        ),
    )


def _finalize_lineage_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for edge in edges:
        item = dict(edge)
        for key in ("supportLevels", "routeStatuses"):
            if isinstance(item.get(key), Counter):
                item[key] = _top_values(item[key], limit=None)
        finalized.append(item)
    return sorted(
        finalized,
        key=lambda item: (
            -int(item.get("jobs") or 0),
            str(item.get("sourceKey") or "").casefold(),
            str(item.get("providerId") or "").casefold(),
            str(item.get("boardKey") or "").casefold(),
        ),
    )


def _lineage_percentage(count: Any, total: int) -> float:
    return round((int(count or 0) / total) * 100, 2) if total else 0


def _fetch_sync_dashboard_stats(
    conn: sqlite3.Connection, snapshot_at: str | None
) -> dict[str, Any] | None:
    if not _has_table(conn, "job_sync_runs"):
        return None

    snapshot_dt = _parse_timestamp(snapshot_at)
    window_start = None
    if snapshot_dt:
        from datetime import timedelta

        window_start = _format_utc_timestamp(snapshot_dt - timedelta(days=7))

    window_clause = ""
    params: tuple[Any, ...] = ()
    if window_start:
        window_clause = "WHERE synced_at >= ?"
        params = (window_start,)

    totals_row = conn.execute(
        f"""
        SELECT
            coalesce(sum(new_count), 0),
            coalesce(sum(changed_count), 0),
            coalesce(sum(closed_count), 0),
            coalesce(sum(reopened_count), 0),
            count(*)
        FROM job_sync_runs
        {window_clause}
        """,
        params,
    ).fetchone()
    new_7d, changed_7d, closed_7d, reopened_7d, run_count = totals_row or (0, 0, 0, 0, 0)

    median_days_by_provider: list[dict[str, Any]] = []
    if _has_table(conn, "jobs"):
        provider_days: dict[str, list[int]] = {}
        reference = snapshot_at or _format_utc_timestamp(datetime.now(timezone.utc))
        day_rows = conn.execute(
            """
            SELECT provider_id, first_seen_at
            FROM jobs
            WHERE status = 'open' AND first_seen_at IS NOT NULL
            """
        ).fetchall()
        reference_dt = _parse_timestamp(reference)
        for provider_id, first_seen_at in day_rows:
            first_seen = _parse_timestamp(first_seen_at)
            if not first_seen or not reference_dt:
                continue
            days_open = max((reference_dt - first_seen).days, 0)
            provider_days.setdefault(str(provider_id), []).append(days_open)
        for provider_id, values in sorted(provider_days.items()):
            if not values:
                continue
            sorted_values = sorted(values)
            mid = len(sorted_values) // 2
            median = (
                sorted_values[mid]
                if len(sorted_values) % 2
                else (sorted_values[mid - 1] + sorted_values[mid]) / 2
            )
            median_days_by_provider.append(
                {"providerId": provider_id, "medianDaysOpen": median, "count": len(values)}
            )

    churn_rows = conn.execute(
        f"""
        SELECT board_key, provider_id, sum(closed_count) AS closed_total
        FROM job_sync_runs
        {window_clause}
        GROUP BY board_key, provider_id
        HAVING closed_total > 0
        ORDER BY closed_total DESC, board_key
        LIMIT {TOP_DASHBOARD_LIMIT}
        """,
        params,
    ).fetchall()
    top_boards_by_churn = [
        {
            "boardKey": str(row[0]),
            "providerId": str(row[1]),
            "closedCount": int(row[2]),
        }
        for row in churn_rows
    ]

    return {
        "windowDays": 7,
        "windowStart": window_start,
        "runCount": int(run_count),
        "totals7d": {
            "new": int(new_7d),
            "changed": int(changed_7d),
            "closed": int(closed_7d),
            "reopened": int(reopened_7d),
        },
        "medianDaysOpenByProvider": median_days_by_provider,
        "topBoardsByChurn": top_boards_by_churn,
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
    return _NORMALIZED_SUGGESTION_RE.sub(" ", value.casefold()).strip()


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
    candidates: list[Any] = []
    primary_columns = (
        ("board_providers", "detected_at"),
        ("boards", "synced_at"),
        ("jobs", "synced_at"),
        ("jobs", "last_seen_at"),
        ("jobs", "first_seen_at"),
    )
    fallback_columns = (
        ("job_versions", "updated_at"),
        ("job_versions", "created_at"),
    )
    current_version_columns = ("updated_at", "created_at")

    for table_name, column_name in primary_columns:
        if not _has_column(conn, table_name, column_name):
            continue
        _progress(f"compute snapshot timestamp: {table_name}.{column_name}")
        row = conn.execute(
            f"""
            SELECT max({_sqlite_identifier(column_name)})
            FROM {_sqlite_identifier(table_name)}
            WHERE {_sqlite_identifier(column_name)} IS NOT NULL
              AND {_sqlite_identifier(column_name)} != ''
            """
        ).fetchone()
        if row and row[0]:
            candidates.append(row[0])
    for column_name in current_version_columns:
        if not _has_column(conn, "job_versions", column_name):
            continue
        candidate = _current_version_snapshot_column_candidate(conn, column_name)
        if candidate:
            candidates.append(candidate)
    if candidates:
        return _latest_timestamp_value(candidates)

    for table_name, column_name in fallback_columns:
        if not _has_column(conn, table_name, column_name):
            continue
        _progress(f"compute snapshot timestamp: {table_name}.{column_name}")
        candidate = _snapshot_column_candidate(conn, table_name, column_name)
        if candidate:
            candidates.append(candidate)
    return _latest_timestamp_value(candidates)


def _current_version_snapshot_column_candidate(
    conn: sqlite3.Connection, column_name: str
) -> str | None:
    if not _has_column(conn, "jobs", "current_version_id"):
        return None
    current_version_ids = _current_version_id_values(conn)
    if not current_version_ids:
        return None
    column = _sqlite_identifier(column_name)
    latest: datetime | None = None
    scanned = 0
    _progress(f"compute snapshot timestamp: current job_versions.{column_name}")
    for version_id, value in conn.execute(
        f"""
        SELECT id, {column}
        FROM job_versions
        WHERE {column} IS NOT NULL
          AND {column} != ''
        """
    ):
        scanned += 1
        if str(version_id) in current_version_ids:
            parsed = _parse_timestamp(value)
            if parsed and (latest is None or parsed > latest):
                latest = parsed
        if scanned % 25_000 == 0:
            _progress(
                f"compute snapshot timestamp: current job_versions.{column_name} scanned {scanned}"
            )
    if scanned:
        _progress(
            f"compute snapshot timestamp: current job_versions.{column_name} scanned {scanned}"
        )
    return _format_utc_timestamp(latest) if latest else None


def _snapshot_column_candidate(
    conn: sqlite3.Connection, table_name: str, column_name: str
) -> str | None:
    column = _sqlite_identifier(column_name)
    table = _sqlite_identifier(table_name)
    if table_name != "job_versions":
        row = conn.execute(
            f"""
            SELECT max({column})
            FROM {table}
            WHERE {column} IS NOT NULL
              AND {column} != ''
            """
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    latest: datetime | None = None
    scanned = 0
    for (value,) in conn.execute(
        f"""
        SELECT {column}
        FROM {table}
        WHERE {column} IS NOT NULL
          AND {column} != ''
        """
    ):
        scanned += 1
        parsed = _parse_timestamp(value)
        if parsed and (latest is None or parsed > latest):
            latest = parsed
        if scanned % 25_000 == 0:
            _progress(
                f"compute snapshot timestamp: {table_name}.{column_name} scanned {scanned}"
            )
    if scanned:
        _progress(
            f"compute snapshot timestamp: {table_name}.{column_name} scanned {scanned}"
        )
    return _format_utc_timestamp(latest) if latest else None


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

if __name__ == "__main__":
    main()
