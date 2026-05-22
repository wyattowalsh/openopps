from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

from sqlalchemy import func, or_, text
from sqlalchemy.engine import Connection
from sqlmodel import Session, SQLModel, col, create_engine, select

from openopps.models import (
    BoardProviderRecord,
    BoardProviderRow,
    BoardRecord,
    BoardRow,
    JobRecord,
    JobRow,
    SourceRecord,
    SourceRow,
    board_from_row,
    board_provider_from_row,
    board_provider_to_row,
    board_to_row,
    job_from_row,
    job_to_row,
    source_from_row,
    source_to_row,
)
from openopps.migrations import upgrade_sqlite_database
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify, source_board_key, stable_id


@dataclass(frozen=True)
class BoardFilters:
    source_key: str | None = None
    board_key: str | None = None
    provider_id: str | None = None
    market: str | None = None
    location: str | None = None
    domain: str | None = None
    has_jobs: bool = False
    min_staff: int | None = None
    max_staff: int | None = None
    limit: int | None = None


@dataclass(frozen=True)
class JobFilters:
    source_key: str | None = None
    board_key: str | None = None
    provider_id: str | None = None
    location: str | None = None
    department: str | None = None
    team: str | None = None
    workplace_type: str | None = None
    remote: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    skill: str | None = None
    query: str | None = None
    posted_after: str | None = None
    posted_before: str | None = None
    limit: int | None = None


@runtime_checkable
class JsonDumpable(Protocol):
    def model_dump_json(self) -> str: ...


class OpenOppsStore:
    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        connect_args = (
            {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
        )
        self.engine = create_engine(settings.db_url, connect_args=connect_args)
        self._initialized = False

    def init_db(self) -> None:
        if self._initialized:
            return
        if self.settings.db_url.startswith("sqlite"):
            upgrade_sqlite_database(
                self.settings, prepare_legacy_schema=_prepare_legacy_sqlite_schema
            )
            with self.engine.connect() as conn:
                _ensure_sqlite_source_scoped_board_keys(conn)
                _ensure_sqlite_job_columns(conn)
                conn.commit()
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA synchronous=NORMAL"))
                conn.commit()
        else:
            SQLModel.metadata.create_all(self.engine)
        self._initialized = True

    def vacuum(self) -> None:
        if self.settings.db_url.startswith("sqlite"):
            with self.engine.connect() as conn:
                conn.execute(text("VACUUM"))

    def status(self) -> dict[str, int]:
        self.init_db()
        with Session(self.engine) as session:
            return {
                "sources": _count_rows(session, SourceRow),
                "boards": _count_rows(session, BoardRow),
                "boardProviders": _count_rows(session, BoardProviderRow),
                "jobs": _count_rows(session, JobRow),
            }

    def upsert_source(self, record: SourceRecord) -> None:
        self.init_db()
        with Session(self.engine) as session:
            session.merge(source_to_row(record))
            session.commit()

    def upsert_boards(self, boards: Sequence[BoardRecord]) -> None:
        self.init_db()
        self._merge_batches([board_to_row(board) for board in boards])

    def upsert_board_providers(self, providers: Sequence[BoardProviderRecord]) -> None:
        self.init_db()
        self._merge_batches([board_provider_to_row(provider) for provider in providers])

    def upsert_jobs(self, jobs: Sequence[JobRecord]) -> None:
        self.init_db()
        self._merge_batches([job_to_row(job) for job in jobs])

    def _merge_batches(self, rows: Sequence[SQLModel]) -> None:
        if not rows:
            return
        batch_size = self.settings.db_batch_size
        with Session(self.engine) as session:
            for offset in range(0, len(rows), batch_size):
                for row in rows[offset : offset + batch_size]:
                    session.merge(row)
                session.commit()

    def list_sources(self, enabled_only: bool = False) -> list[SourceRecord]:
        self.init_db()
        with Session(self.engine) as session:
            statement = select(SourceRow)
            if enabled_only:
                statement = statement.where(SourceRow.enabled == True)  # noqa: E712
            return [source_from_row(row) for row in session.exec(statement).all()]

    def get_source(self, key: str) -> SourceRecord | None:
        self.init_db()
        with Session(self.engine) as session:
            row = session.get(SourceRow, key)
            return source_from_row(row) if row else None

    def list_boards(
        self,
        *,
        source_key: str | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        market: str | None = None,
        location: str | None = None,
        domain: str | None = None,
        has_jobs: bool = False,
        min_staff: int | None = None,
        max_staff: int | None = None,
        limit: int | None = None,
        with_providers: bool = True,
        filters: BoardFilters | None = None,
    ) -> list[BoardRecord]:
        filters = filters or BoardFilters(
            source_key=source_key,
            board_key=board_key,
            provider_id=provider_id,
            market=market,
            location=location,
            domain=domain,
            has_jobs=has_jobs,
            min_staff=min_staff,
            max_staff=max_staff,
            limit=limit,
        )
        provider_id = _normalize_provider_alias(filters.provider_id)
        self.init_db()
        with Session(self.engine) as session:
            statement = _apply_board_sql_filters(select(BoardRow), filters, provider_id)
            statement = statement.order_by(BoardRow.name)
            if filters.limit and not _board_needs_python_filter(filters):
                statement = statement.limit(filters.limit)
            rows = list(session.exec(statement).all())
            if _board_needs_python_filter(filters):
                rows = _filter_board_rows(rows, filters)
            if filters.limit and _board_needs_python_filter(filters):
                rows = rows[: filters.limit]
            providers_by_board: dict[str, list[BoardProviderRecord]] = {}
            if with_providers and rows:
                board_keys = [row.key for row in rows]
                provider_rows = session.exec(
                    select(BoardProviderRow).where(
                        col(BoardProviderRow.board_key).in_(board_keys)
                    )
                ).all()
                for provider_row in provider_rows:
                    providers_by_board.setdefault(provider_row.board_key, []).append(
                        board_provider_from_row(provider_row)
                    )
            return [
                board_from_row(row, providers_by_board.get(row.key, [])) for row in rows
            ]

    def get_board(self, board_key: str) -> BoardRecord | None:
        boards = self.list_boards(board_key=board_key, limit=1)
        return boards[0] if boards else None

    def list_board_providers(
        self,
        *,
        source_key: str | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        job_capable_only: bool = False,
    ) -> list[BoardProviderRecord]:
        self.init_db()
        with Session(self.engine) as session:
            statement = select(BoardProviderRow)
            if source_key:
                statement = statement.where(BoardProviderRow.source_key == source_key)
            if board_key:
                statement = statement.where(BoardProviderRow.board_key == board_key)
            if provider_id:
                statement = statement.where(BoardProviderRow.provider_id == provider_id)
            if job_capable_only:
                statement = statement.where(BoardProviderRow.support_level == "jobs")
            rows = session.exec(statement).all()
            return [board_provider_from_row(row) for row in rows]

    def list_jobs(
        self,
        *,
        source_key: str | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        location: str | None = None,
        department: str | None = None,
        team: str | None = None,
        workplace_type: str | None = None,
        remote: str | None = None,
        employment_type: str | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        skill: str | None = None,
        query: str | None = None,
        posted_after: str | None = None,
        posted_before: str | None = None,
        limit: int | None = None,
        filters: JobFilters | None = None,
    ) -> list[JobRecord]:
        filters = filters or JobFilters(
            source_key=source_key,
            board_key=board_key,
            provider_id=provider_id,
            location=location,
            department=department,
            team=team,
            workplace_type=workplace_type,
            remote=remote,
            employment_type=employment_type,
            salary_min=salary_min,
            salary_max=salary_max,
            skill=skill,
            query=query,
            posted_after=posted_after,
            posted_before=posted_before,
            limit=limit,
        )
        provider_id = _normalize_provider_alias(filters.provider_id)
        self.init_db()
        with Session(self.engine) as session:
            statement = _apply_job_sql_filters(select(JobRow), filters, provider_id)
            statement = statement.order_by(col(JobRow.synced_at).desc(), JobRow.title)
            if filters.limit and not _job_needs_python_filter(filters):
                statement = statement.limit(filters.limit)
            jobs = [job_from_row(row) for row in session.exec(statement).all()]
            if _job_needs_python_filter(filters):
                jobs = [job for job in jobs if _job_matches_filters(job, filters)]
            if filters.limit and _job_needs_python_filter(filters):
                jobs = jobs[: filters.limit]
            return jobs

    def get_job(self, job_id: str) -> JobRecord | None:
        self.init_db()
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            return job_from_row(row) if row else None


def append_jsonl(path: Path, records: Iterable[object]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            if isinstance(record, JsonDumpable):
                handle.write(record.model_dump_json() + "\n")
            else:
                handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _count_rows(session: Session, row_type: type[SQLModel]) -> int:
    value = session.exec(select(func.count()).select_from(row_type)).one()
    return int(value or 0)


def _prepare_legacy_sqlite_schema(engine) -> None:
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        _ensure_sqlite_source_columns(conn)
        _ensure_sqlite_board_columns(conn)
        _ensure_sqlite_board_provider_columns(conn)
        _ensure_sqlite_job_columns(conn)
        _ensure_sqlite_source_scoped_board_keys(conn)
        conn.commit()


def _normalize_provider_alias(provider_id: str | None) -> str | None:
    if provider_id and provider_id.lower() in {"any", "all"}:
        return None
    return provider_id


def _apply_board_sql_filters(statement, filters: BoardFilters, provider_id: str | None):
    if filters.source_key:
        statement = statement.where(BoardRow.source_key == filters.source_key)
    if filters.board_key:
        statement = statement.where(BoardRow.key == filters.board_key)
    if filters.min_staff is not None:
        statement = statement.where(col(BoardRow.staff_count) >= filters.min_staff)
    if filters.max_staff is not None:
        statement = statement.where(col(BoardRow.staff_count) <= filters.max_staff)
    if filters.domain:
        statement = statement.where(_contains_clause(BoardRow.domain, filters.domain))
    if provider_id:
        provider_board_keys = select(BoardProviderRow.board_key).where(
            BoardProviderRow.provider_id == provider_id
        )
        statement = statement.where(col(BoardRow.key).in_(provider_board_keys))
    if filters.has_jobs:
        provider_count_board_keys = select(BoardProviderRow.board_key).where(
            col(BoardProviderRow.count_hint) > 0
        )
        actual_job_board_keys = select(JobRow.board_key).distinct()
        statement = statement.where(
            or_(
                col(BoardRow.num_jobs_hint) > 0,
                col(BoardRow.key).in_(provider_count_board_keys),
                col(BoardRow.key).in_(actual_job_board_keys),
            )
        )
    return statement


def _board_needs_python_filter(filters: BoardFilters) -> bool:
    return bool(filters.market or filters.location)


def _filter_board_rows(rows: list[BoardRow], filters: BoardFilters) -> list[BoardRow]:
    filtered: list[BoardRow] = []
    for row in rows:
        if filters.market and not _list_contains(row.markets, filters.market):
            continue
        if filters.location and not _list_contains(row.locations, filters.location):
            continue
        filtered.append(row)
    return filtered


def _apply_job_sql_filters(statement, filters: JobFilters, provider_id: str | None):
    if filters.source_key:
        board_keys = select(BoardRow.key).where(
            BoardRow.source_key == filters.source_key
        )
        statement = statement.where(col(JobRow.board_key).in_(board_keys))
    if filters.board_key:
        statement = statement.where(JobRow.board_key == filters.board_key)
    if provider_id:
        statement = statement.where(JobRow.provider_id == provider_id)
    if filters.department:
        statement = statement.where(
            _contains_clause(JobRow.department, filters.department)
        )
    if filters.team:
        statement = statement.where(_contains_clause(JobRow.team, filters.team))
    if filters.workplace_type:
        statement = statement.where(
            _contains_clause(JobRow.workplace_type, filters.workplace_type)
        )
    if filters.remote:
        statement = statement.where(
            func.lower(JobRow.remote) == _casefold(filters.remote)
        )
    if filters.employment_type:
        statement = statement.where(
            _contains_clause(JobRow.employment_type, filters.employment_type)
        )
    if filters.salary_min is not None:
        statement = statement.where(
            or_(
                col(JobRow.salary_max) >= filters.salary_min,
                (col(JobRow.salary_max).is_(None))
                & (col(JobRow.salary_min) >= filters.salary_min),
            )
        )
    if filters.salary_max is not None:
        statement = statement.where(
            or_(
                col(JobRow.salary_min) <= filters.salary_max,
                (col(JobRow.salary_min).is_(None))
                & (col(JobRow.salary_max) <= filters.salary_max),
            )
        )
    if filters.query:
        statement = statement.where(
            or_(
                _contains_clause(JobRow.title, filters.query),
                _contains_clause(JobRow.company, filters.query),
                _contains_clause(JobRow.description, filters.query),
            )
        )
    return statement


def _job_needs_python_filter(filters: JobFilters) -> bool:
    return bool(
        filters.location
        or filters.skill
        or filters.posted_after
        or filters.posted_before
    )


def _contains_clause(column, needle: str):
    return func.lower(column).contains(_casefold(needle))


def _job_matches_filters(job: JobRecord, filters: JobFilters) -> bool:
    if filters.location and not _list_contains(job.locations, filters.location):
        return False
    if filters.department and not _text_contains(job.department, filters.department):
        return False
    if filters.team and not _text_contains(job.team, filters.team):
        return False
    if filters.workplace_type and not _text_contains(
        job.workplace_type, filters.workplace_type
    ):
        return False
    if filters.remote and not _text_equals(job.remote, filters.remote):
        return False
    if filters.employment_type and not _text_contains(
        job.employment_type, filters.employment_type
    ):
        return False
    if not _salary_overlaps(job, filters.salary_min, filters.salary_max):
        return False
    if filters.skill and not _skills_contain(job, filters.skill):
        return False
    if filters.query and not _query_matches(job, filters.query):
        return False
    if not _posted_at_matches(
        job.posted_at, filters.posted_after, filters.posted_before
    ):
        return False
    return True


def _list_contains(values: Sequence[str], needle: str) -> bool:
    return any(_text_contains(value, needle) for value in values)


def _text_contains(value: str | None, needle: str) -> bool:
    return _casefold(needle) in _casefold(value)


def _text_equals(value: str | None, needle: str) -> bool:
    return _casefold(value) == _casefold(needle)


def _casefold(value: str | None) -> str:
    return (value or "").casefold()


def _salary_overlaps(
    job: JobRecord,
    requested_min: float | None,
    requested_max: float | None,
) -> bool:
    if requested_min is None and requested_max is None:
        return True
    job_min = job.salary_min
    job_max = job.salary_max
    if job_min is None and job_max is None:
        return False
    if requested_min is not None:
        candidate_max = job_max if job_max is not None else job_min
        if candidate_max is None or candidate_max < requested_min:
            return False
    if requested_max is not None:
        candidate_min = job_min if job_min is not None else job_max
        if candidate_min is None or candidate_min > requested_max:
            return False
    return True


def _skills_contain(job: JobRecord, needle: str) -> bool:
    for skill in job.skills:
        if _text_contains(skill.name, needle) or _text_contains(skill.level, needle):
            return True
        if _list_contains(skill.keywords, needle):
            return True
    return False


def _query_matches(job: JobRecord, needle: str) -> bool:
    return any(
        _text_contains(value, needle)
        for value in (job.title, job.company, job.description)
    )


def _posted_at_matches(
    posted_at: str | None,
    posted_after: str | None,
    posted_before: str | None,
) -> bool:
    if posted_after is None and posted_before is None:
        return True
    posted_key = _date_key(posted_at)
    if posted_key is None:
        return False
    after_key = _date_key(posted_after)
    before_key = _date_key(posted_before)
    if after_key is not None and posted_key < after_key:
        return False
    if before_key is not None and posted_key > before_key:
        return False
    return True


def _date_key(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"^([1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9])", value)
    return match.group(1) if match else None


def _ensure_sqlite_source_scoped_board_keys(conn: Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }
    if not {"boards", "board_providers", "jobs"}.issubset(tables):
        return
    rows = conn.execute(
        text("SELECT key, source_key, remote_id, remote_slug FROM boards")
    ).fetchall()
    for key, source_key, remote_id, remote_slug in rows:
        if not key or not source_key or source_key == "manual":
            continue
        remote_key = remote_slug or remote_id
        if not remote_key or key != slugify(str(remote_key)):
            continue
        new_key = source_board_key(str(source_key), remote_key)
        if new_key == key:
            continue
        conflict = conn.execute(
            text("SELECT 1 FROM boards WHERE key = :key"), {"key": new_key}
        ).first()
        if conflict:
            continue
        _migrate_board_references(conn, old_key=str(key), new_key=new_key)


def _migrate_board_references(conn: Connection, *, old_key: str, new_key: str) -> None:
    provider_rows = conn.execute(
        text(
            "SELECT id, source_key, provider_id FROM board_providers WHERE board_key = :key"
        ),
        {"key": old_key},
    ).fetchall()
    for provider_id, source_key, route_provider_id in provider_rows:
        new_id = stable_id(source_key, new_key, route_provider_id)
        if conn.execute(
            text("SELECT 1 FROM board_providers WHERE id = :id"), {"id": new_id}
        ).first():
            continue
        conn.execute(
            text(
                "UPDATE board_providers SET id = :new_id, board_key = :new_key WHERE id = :old_id"
            ),
            {"new_id": new_id, "new_key": new_key, "old_id": provider_id},
        )
    job_rows = conn.execute(
        text("SELECT id, provider_id, remote_id FROM jobs WHERE board_key = :key"),
        {"key": old_key},
    ).fetchall()
    for job_id, provider_id, remote_id in job_rows:
        new_id = stable_id(new_key, provider_id, remote_id)
        if conn.execute(
            text("SELECT 1 FROM jobs WHERE id = :id"), {"id": new_id}
        ).first():
            continue
        conn.execute(
            text(
                "UPDATE jobs SET id = :new_id, board_key = :new_key WHERE id = :old_id"
            ),
            {"new_id": new_id, "new_key": new_key, "old_id": job_id},
        )
    conn.execute(
        text("UPDATE boards SET key = :new_key WHERE key = :old_key"),
        {"new_key": new_key, "old_key": old_key},
    )


def _ensure_sqlite_source_columns(conn: Connection) -> None:
    _ensure_sqlite_columns(
        conn,
        "sources",
        {
            "enabled": "BOOLEAN DEFAULT 1",
            "version": "JSON DEFAULT '{}'",
            "raw_metadata": "JSON DEFAULT '{}'",
            "extra_payload": "JSON DEFAULT '{}'",
            "synced_at": "DATETIME",
        },
    )


def _ensure_sqlite_board_columns(conn: Connection) -> None:
    _ensure_sqlite_columns(
        conn,
        "boards",
        {
            "remote_slug": "VARCHAR",
            "domain": "VARCHAR",
            "website_url": "VARCHAR",
            "description": "VARCHAR",
            "markets": "JSON DEFAULT '[]'",
            "locations": "JSON DEFAULT '[]'",
            "staff_count": "INTEGER",
            "num_jobs_hint": "INTEGER",
            "raw_payload": "JSON DEFAULT '{}'",
            "extra_payload": "JSON DEFAULT '{}'",
            "synced_at": "DATETIME",
        },
    )


def _ensure_sqlite_board_provider_columns(conn: Connection) -> None:
    _ensure_sqlite_columns(
        conn,
        "board_providers",
        {
            "label": "VARCHAR",
            "count_hint": "INTEGER",
            "board_url": "VARCHAR",
            "token": "VARCHAR",
            "host": "VARCHAR",
            "tenant": "VARCHAR",
            "site": "VARCHAR",
            "last_status": "VARCHAR",
            "raw_payload": "JSON DEFAULT '{}'",
            "extra_payload": "JSON DEFAULT '{}'",
            "detected_at": "DATETIME",
        },
    )


def _ensure_sqlite_job_columns(conn: Connection) -> None:
    _ensure_sqlite_columns(
        conn,
        "jobs",
        {
            "company": "VARCHAR",
            "employment_type": "VARCHAR",
            "description": "VARCHAR",
            "description_html": "VARCHAR",
            "remote": "VARCHAR",
            "compensation": "JSON",
            "salary": "VARCHAR",
            "salary_min": "REAL",
            "salary_max": "REAL",
            "salary_currency": "VARCHAR",
            "experience": "VARCHAR",
            "responsibilities": "JSON DEFAULT '[]'",
            "qualifications": "JSON DEFAULT '[]'",
            "skills": "JSON DEFAULT '[]'",
            "job_description": "JSON",
        },
    )


def _ensure_sqlite_columns(
    conn: Connection, table_name: str, additions: dict[str, str]
) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }
    if table_name not in tables:
        return
    columns = {
        row[1]
        for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }
    for name, column_type in additions.items():
        if name not in columns:
            conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}")
            )  # noqa: S608
