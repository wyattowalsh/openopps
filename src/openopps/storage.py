from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

from sqlalchemy import func, or_, text
from sqlmodel import Session, SQLModel, col, create_engine, select

from openopps.models import (
    BoardProviderRecord,
    BoardProviderRow,
    BoardRecord,
    BoardRow,
    JobRecord,
    JobPayloadSnapshotRow,
    JobRow,
    JobSyncObservationRow,
    JobSyncRunRow,
    JobVersionBulletRow,
    JobVersionLocationRow,
    JobVersionRow,
    JobVersionSkillKeywordRow,
    JobVersionSkillRow,
    SourceRecord,
    SourceRow,
    board_from_row,
    board_provider_from_row,
    board_provider_to_row,
    board_to_row,
    canonical_json_hash,
    job_content_hash,
    job_payload_hash,
    source_from_row,
    source_to_row,
    utc_now,
)
from openopps.migrations import upgrade_sqlite_database
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id


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
    status: str = "open"
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
            upgrade_sqlite_database(self.settings)
            with self.engine.connect() as conn:
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
        if not boards:
            return
        batch_size = self.settings.db_batch_size
        with Session(self.engine) as session:
            for offset in range(0, len(boards), batch_size):
                for board in boards[offset : offset + batch_size]:
                    _merge_board(session, board)
                session.commit()

    def upsert_board_providers(self, providers: Sequence[BoardProviderRecord]) -> None:
        self.init_db()
        if not providers:
            return
        batch_size = self.settings.db_batch_size
        with Session(self.engine) as session:
            board_key_aliases = _board_key_aliases(session)
            for offset in range(0, len(providers), batch_size):
                for provider in providers[offset : offset + batch_size]:
                    canonical_board_key = board_key_aliases.get(
                        (provider.source_key, provider.board_key), provider.board_key
                    )
                    record = provider.model_copy(
                        update={
                            "id": stable_id(
                                provider.source_key,
                                canonical_board_key,
                                provider.provider_id,
                            ),
                            "board_key": canonical_board_key,
                        }
                    )
                    session.merge(board_provider_to_row(record))
                session.commit()

    def upsert_jobs(self, jobs: Sequence[JobRecord]) -> None:
        self.init_db()
        jobs_by_route: dict[tuple[str, str], list[JobRecord]] = {}
        for job in jobs:
            jobs_by_route.setdefault((job.board_key, job.provider_id), []).append(job)
        for (board_key, provider_id), route_jobs in jobs_by_route.items():
            self.sync_jobs_for_route(
                board_key,
                provider_id,
                route_jobs,
                close_missing=False,
            )

    def sync_jobs_for_route(
        self,
        board_key: str,
        provider_id: str,
        jobs: Sequence[JobRecord],
        *,
        synced_at: datetime | None = None,
        close_missing: bool = True,
    ) -> JobSyncRunRow:
        """Record one successful provider-route sync with versions and observations."""

        self.init_db()
        observed_at = synced_at or utc_now()
        unique_jobs = _unique_jobs_by_id(jobs)
        run = JobSyncRunRow(
            id=stable_id(board_key, provider_id, observed_at.isoformat()),
            board_key=board_key,
            provider_id=provider_id,
            synced_at=observed_at,
            success=True,
            job_count=len(unique_jobs),
        )
        seen_job_ids: set[str] = set()
        with Session(self.engine) as session:
            session.add(run)
            for job in unique_jobs:
                seen_job_ids.add(job.id)
                observation_kind, version_row = _sync_job_record(
                    session,
                    job,
                    observed_at,
                )
                _increment_sync_count(run, observation_kind)
                _add_job_observation(
                    session,
                    run.id,
                    job.id,
                    version_row.id if version_row else None,
                    observation_kind,
                    job_content_hash(job),
                    job_payload_hash(job),
                    observed_at,
                )
            if close_missing:
                closed_rows = _close_missing_jobs(
                    session,
                    run.id,
                    board_key,
                    provider_id,
                    seen_job_ids,
                    observed_at,
                )
                run.closed_count += closed_rows
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

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
                _board_with_source_keys(
                    row,
                    providers_by_board.get(row.key, []),
                )
                for row in rows
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
        status: str = "open",
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
            status=status,
            limit=limit,
        )
        provider_id = _normalize_provider_alias(filters.provider_id)
        self.init_db()
        with Session(self.engine) as session:
            statement = _apply_job_sql_filters(
                select(JobRow, JobVersionRow).where(
                    JobRow.current_version_id == JobVersionRow.id
                ),
                filters,
                provider_id,
            )
            statement = statement.order_by(
                col(JobRow.synced_at).desc(), JobVersionRow.title
            )
            if filters.limit and not _job_needs_python_filter(filters):
                statement = statement.limit(filters.limit)
            jobs = [
                _job_from_identity_and_version(session, row, version)
                for row, version in session.exec(statement).all()
            ]
            if _job_needs_python_filter(filters):
                board_source_keys = _board_source_keys_by_key(session, jobs)
                jobs = [
                    job
                    for job in jobs
                    if _job_matches_filters(job, filters, board_source_keys)
                ]
            if filters.limit and _job_needs_python_filter(filters):
                jobs = jobs[: filters.limit]
            return jobs

    def get_job(self, job_id: str) -> JobRecord | None:
        self.init_db()
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            if not row or not row.current_version_id:
                return None
            version = session.get(JobVersionRow, row.current_version_id)
            return (
                _job_from_identity_and_version(session, row, version)
                if version
                else None
            )

    def list_job_versions(self, job_id: str) -> list[JobRecord]:
        self.init_db()
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            if not row:
                return []
            versions = session.exec(
                select(JobVersionRow)
                .where(JobVersionRow.job_id == job_id)
                .order_by(col(JobVersionRow.version))
            ).all()
            return [
                _job_from_identity_and_version(session, row, version)
                for version in versions
            ]


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


def _count_rows(session: Session, row_type: type[SQLModel]) -> int:
    value = session.exec(select(func.count()).select_from(row_type)).one()
    return int(value or 0)


def _merge_board(session: Session, board: BoardRecord) -> None:
    incoming = _board_row_with_source_keys(board)
    existing = _find_merge_target(session, incoming)
    if existing is None:
        session.merge(incoming)
        return

    session.merge(_merged_board_row(existing, incoming))


def _find_merge_target(session: Session, incoming: BoardRow) -> BoardRow | None:
    if incoming.domain:
        existing = session.exec(
            select(BoardRow).where(
                func.lower(BoardRow.domain) == incoming.domain.lower()
            )
        ).first()
        if existing:
            return existing
    return session.get(BoardRow, incoming.key)


def _board_row_with_source_keys(board: BoardRecord) -> BoardRow:
    row = board_to_row(board)
    row.source_keys = _merged_unique(row.source_keys, [row.source_key])
    row.source_board_keys = {**row.source_board_keys, row.source_key: row.key}
    return row


def _merged_board_row(existing: BoardRow, incoming: BoardRow) -> BoardRow:
    data = existing.model_dump()
    data.update(
        {
            "remote_slug": data.get("remote_slug") or incoming.remote_slug,
            "domain": data.get("domain") or incoming.domain,
            "website_url": data.get("website_url") or incoming.website_url,
            "description": data.get("description") or incoming.description,
            "markets": _merged_unique(existing.markets, incoming.markets),
            "locations": _merged_unique(existing.locations, incoming.locations),
            "staff_count": _max_optional(existing.staff_count, incoming.staff_count),
            "num_jobs_hint": _max_optional(
                existing.num_jobs_hint, incoming.num_jobs_hint
            ),
            "source_keys": _merged_unique(existing.source_keys, incoming.source_keys),
            "source_board_keys": {
                **(existing.source_board_keys or {}),
                **(incoming.source_board_keys or {}),
            },
            "synced_at": incoming.synced_at or existing.synced_at,
        }
    )
    if incoming.raw_payload:
        data["raw_payload"] = _merged_raw_payloads(
            existing.raw_payload,
            incoming.raw_payload,
            incoming.source_key,
        )
    return BoardRow(**data)


def _merged_unique(left: Sequence[str], right: Sequence[str]) -> list[str]:
    return sorted({*left, *right})


def _max_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def _merged_raw_payloads(
    existing: dict,
    incoming: dict,
    source_key: str,
) -> dict:
    if "sourcePayloads" in existing and isinstance(existing["sourcePayloads"], dict):
        source_payloads = dict(existing["sourcePayloads"])
    else:
        source_payloads = {"primary": existing} if existing else {}
    source_payloads[source_key] = incoming
    return {**existing, "sourcePayloads": source_payloads}


def _board_key_aliases(session: Session) -> dict[tuple[str, str], str]:
    aliases: dict[tuple[str, str], str] = {}
    for row in session.exec(select(BoardRow)).all():
        aliases[(row.source_key, row.key)] = row.key
        for source_key, emitted_key in (row.source_board_keys or {}).items():
            aliases[(source_key, emitted_key)] = row.key
    return aliases


def _board_source_keys(row: BoardRow) -> list[str]:
    return _merged_unique(row.source_keys or [], [row.source_key])


def _board_source_keys_by_key(
    session: Session,
    jobs: Sequence[JobRecord],
) -> dict[str, list[str]]:
    board_keys = sorted({job.board_key for job in jobs})
    if not board_keys:
        return {}
    rows = session.exec(select(BoardRow).where(col(BoardRow.key).in_(board_keys))).all()
    return {row.key: _board_source_keys(row) for row in rows}


def _board_with_source_keys(
    row: BoardRow,
    providers: list[BoardProviderRecord],
) -> BoardRecord:
    return board_from_row(row, providers).model_copy(
        update={"source_keys": _board_source_keys(row)}
    )


def _sync_job_record(
    session: Session,
    job: JobRecord,
    observed_at: datetime,
) -> tuple[str, JobVersionRow]:
    content_hash = job.content_hash or job_content_hash(job)
    payload_hash = job.payload_hash or job_payload_hash(job)
    existing = session.get(JobRow, job.id)
    observation_kind = _job_observation_kind(existing, content_hash)

    if existing is None:
        existing = JobRow(
            id=job.id,
            board_key=job.board_key,
            provider_id=job.provider_id,
            remote_id=job.remote_id,
            status="open",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            synced_at=observed_at,
        )

    _add_payload_snapshot(session, job.id, "listing", job.raw_listing, observed_at)
    _add_payload_snapshot(session, job.id, "detail", job.raw_detail, observed_at)

    version = _get_or_create_job_version(
        session,
        job,
        content_hash,
        payload_hash,
        observed_at,
    )
    version.last_seen_at = observed_at

    existing.status = "open"
    existing.current_version_id = version.id
    existing.current_content_hash = content_hash
    existing.current_payload_hash = payload_hash
    existing.last_seen_at = observed_at
    existing.closed_at = None
    existing.synced_at = observed_at
    session.add(existing)
    session.add(version)
    return observation_kind, version


def _unique_jobs_by_id(jobs: Sequence[JobRecord]) -> list[JobRecord]:
    unique_jobs: list[JobRecord] = []
    seen_ids: set[str] = set()
    for job in jobs:
        if job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        unique_jobs.append(job)
    return unique_jobs


def _job_observation_kind(existing: JobRow | None, content_hash: str) -> str:
    if existing is None:
        return "new"
    if existing.status == "closed":
        return "reopened"
    if existing.current_content_hash == content_hash:
        return "unchanged"
    return "changed"


def _get_or_create_job_version(
    session: Session,
    job: JobRecord,
    content_hash: str,
    payload_hash: str,
    observed_at: datetime,
) -> JobVersionRow:
    existing = session.exec(
        select(JobVersionRow).where(
            JobVersionRow.job_id == job.id,
            JobVersionRow.content_hash == content_hash,
        )
    ).first()
    if existing:
        return existing

    next_version = _next_job_version_number(session, job.id)
    version = JobVersionRow(
        **_job_version_row_data(
            job,
            content_hash,
            payload_hash,
            next_version,
            observed_at,
        )
    )
    session.add(version)
    session.flush()
    _add_job_version_children(session, version.id, job)
    return version


def _job_version_row_data(
    job: JobRecord,
    content_hash: str,
    payload_hash: str,
    version: int,
    observed_at: datetime,
) -> dict:
    data = job.model_dump(
        mode="python",
        exclude={
            "id",
            "board_key",
            "provider_id",
            "remote_id",
            "status",
            "version",
            "content_hash",
            "payload_hash",
            "first_seen_at",
            "last_seen_at",
            "closed_at",
            "raw_listing",
            "raw_detail",
            "synced_at",
        },
    )
    row_fields = set(JobVersionRow.model_fields)
    row_data = {key: value for key, value in data.items() if key in row_fields}
    row_data["extra_payload"] = {
        key: value for key, value in data.items() if key not in row_fields
    }
    row_data.update(
        {
            "id": stable_id(job.id, "version", str(version)),
            "job_id": job.id,
            "version": version,
            "content_hash": content_hash,
            "payload_hash": payload_hash,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "created_at": observed_at,
        }
    )
    row_data["skills"] = [skill.model_dump(mode="python") for skill in job.skills]
    row_data["job_description"] = (
        job.job_description.model_dump(mode="python", by_alias=True)
        if job.job_description
        else None
    )
    return row_data


def _next_job_version_number(session: Session, job_id: str) -> int:
    value = session.exec(
        select(func.max(JobVersionRow.version)).where(JobVersionRow.job_id == job_id)
    ).one()
    return int(value or 0) + 1


def _add_job_version_children(
    session: Session,
    version_id: str,
    job: JobRecord,
) -> None:
    for ordinal, label in enumerate(job.locations):
        session.add(
            JobVersionLocationRow(
                id=stable_id(version_id, "location", str(ordinal), label),
                job_version_id=version_id,
                ordinal=ordinal,
                label=label,
            )
        )
    for kind, values in (
        ("responsibility", job.responsibilities),
        ("qualification", job.qualifications),
    ):
        for ordinal, text_value in enumerate(values):
            session.add(
                JobVersionBulletRow(
                    id=stable_id(version_id, kind, str(ordinal), text_value),
                    job_version_id=version_id,
                    kind=kind,
                    ordinal=ordinal,
                    text=text_value,
                )
            )
    for ordinal, skill in enumerate(job.skills):
        skill_id = stable_id(version_id, "skill", str(ordinal))
        session.add(
            JobVersionSkillRow(
                id=skill_id,
                job_version_id=version_id,
                ordinal=ordinal,
                name=skill.name,
                level=skill.level,
            )
        )
        for keyword_ordinal, keyword in enumerate(skill.keywords):
            session.add(
                JobVersionSkillKeywordRow(
                    id=stable_id(skill_id, "keyword", str(keyword_ordinal), keyword),
                    skill_id=skill_id,
                    ordinal=keyword_ordinal,
                    keyword=keyword,
                )
            )


def _add_payload_snapshot(
    session: Session,
    job_id: str,
    payload_kind: str,
    payload: dict,
    observed_at: datetime,
) -> None:
    if not payload:
        return
    payload_hash = canonical_json_hash(payload)
    snapshot_id = stable_id(job_id, payload_kind, payload_hash)
    if session.get(JobPayloadSnapshotRow, snapshot_id):
        return
    session.add(
        JobPayloadSnapshotRow(
            id=snapshot_id,
            job_id=job_id,
            payload_kind=payload_kind,
            payload_hash=payload_hash,
            payload=payload,
            observed_at=observed_at,
        )
    )


def _increment_sync_count(run: JobSyncRunRow, observation_kind: str) -> None:
    if observation_kind == "new":
        run.new_count += 1
    elif observation_kind == "changed":
        run.changed_count += 1
    elif observation_kind == "reopened":
        run.reopened_count += 1
    else:
        run.unchanged_count += 1


def _add_job_observation(
    session: Session,
    sync_run_id: str,
    job_id: str,
    job_version_id: str | None,
    observation_kind: str,
    content_hash: str | None,
    payload_hash: str | None,
    observed_at: datetime,
) -> None:
    session.add(
        JobSyncObservationRow(
            id=stable_id(sync_run_id, job_id, observation_kind),
            sync_run_id=sync_run_id,
            job_id=job_id,
            job_version_id=job_version_id,
            observation_kind=observation_kind,
            content_hash=content_hash,
            payload_hash=payload_hash,
            observed_at=observed_at,
        )
    )


def _close_missing_jobs(
    session: Session,
    sync_run_id: str,
    board_key: str,
    provider_id: str,
    seen_job_ids: set[str],
    observed_at: datetime,
) -> int:
    rows = session.exec(
        select(JobRow).where(
            JobRow.board_key == board_key,
            JobRow.provider_id == provider_id,
            JobRow.status == "open",
        )
    ).all()
    closed_count = 0
    for row in rows:
        if row.id in seen_job_ids:
            continue
        row.status = "closed"
        row.closed_at = observed_at
        row.synced_at = observed_at
        session.add(row)
        closed_count += 1
        _add_job_observation(
            session,
            sync_run_id,
            row.id,
            row.current_version_id,
            "closed",
            row.current_content_hash,
            row.current_payload_hash,
            observed_at,
        )
    return closed_count


def _job_from_identity_and_version(
    session: Session,
    row: JobRow,
    version: JobVersionRow,
) -> JobRecord:
    data = version.model_dump()
    extra_payload = data.pop("extra_payload", {}) or {}
    data.update(extra_payload if isinstance(extra_payload, dict) else {})
    data.pop("created_at", None)
    data.pop("job_id", None)
    data.update(
        {
            "id": row.id,
            "board_key": row.board_key,
            "provider_id": row.provider_id,
            "remote_id": row.remote_id,
            "status": row.status,
            "version": version.version,
            "content_hash": version.content_hash,
            "payload_hash": version.payload_hash,
            "first_seen_at": _ensure_aware(version.first_seen_at),
            "last_seen_at": _ensure_aware(version.last_seen_at),
            "closed_at": _ensure_aware(row.closed_at),
            "synced_at": _ensure_aware(version.last_seen_at),
            "locations": _version_locations(session, version),
            "responsibilities": _version_bullets(session, version, "responsibility"),
            "qualifications": _version_bullets(session, version, "qualification"),
            "skills": _version_skills(session, version),
            "raw_listing": _latest_payload(session, row.id, "listing"),
            "raw_detail": _latest_payload(session, row.id, "detail"),
        }
    )
    return JobRecord.model_validate(data)


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _version_locations(session: Session, version: JobVersionRow) -> list[str]:
    rows = session.exec(
        select(JobVersionLocationRow)
        .where(JobVersionLocationRow.job_version_id == version.id)
        .order_by(col(JobVersionLocationRow.ordinal))
    ).all()
    return [row.label for row in rows] or list(version.locations or [])


def _version_bullets(
    session: Session,
    version: JobVersionRow,
    kind: str,
) -> list[str]:
    rows = session.exec(
        select(JobVersionBulletRow)
        .where(
            JobVersionBulletRow.job_version_id == version.id,
            JobVersionBulletRow.kind == kind,
        )
        .order_by(col(JobVersionBulletRow.ordinal))
    ).all()
    if rows:
        return [row.text for row in rows]
    return list(
        version.responsibilities if kind == "responsibility" else version.qualifications
    )


def _version_skills(session: Session, version: JobVersionRow) -> list[dict]:
    rows = session.exec(
        select(JobVersionSkillRow)
        .where(JobVersionSkillRow.job_version_id == version.id)
        .order_by(col(JobVersionSkillRow.ordinal))
    ).all()
    if not rows:
        return list(version.skills or [])
    skills: list[dict] = []
    for row in rows:
        keywords = session.exec(
            select(JobVersionSkillKeywordRow)
            .where(JobVersionSkillKeywordRow.skill_id == row.id)
            .order_by(col(JobVersionSkillKeywordRow.ordinal))
        ).all()
        skills.append(
            {
                "name": row.name,
                "level": row.level,
                "keywords": [keyword.keyword for keyword in keywords],
            }
        )
    return skills


def _latest_payload(session: Session, job_id: str, payload_kind: str) -> dict:
    row = session.exec(
        select(JobPayloadSnapshotRow)
        .where(
            JobPayloadSnapshotRow.job_id == job_id,
            JobPayloadSnapshotRow.payload_kind == payload_kind,
        )
        .order_by(col(JobPayloadSnapshotRow.observed_at).desc())
    ).first()
    return dict(row.payload) if row else {}


def _normalize_provider_alias(provider_id: str | None) -> str | None:
    if provider_id and provider_id.lower() in {"any", "all"}:
        return None
    return provider_id


def _apply_board_sql_filters(statement, filters: BoardFilters, provider_id: str | None):
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
        actual_job_board_keys = (
            select(JobRow.board_key).where(JobRow.status == "open").distinct()
        )
        statement = statement.where(
            or_(
                col(BoardRow.num_jobs_hint) > 0,
                col(BoardRow.key).in_(provider_count_board_keys),
                col(BoardRow.key).in_(actual_job_board_keys),
            )
        )
    return statement


def _board_needs_python_filter(filters: BoardFilters) -> bool:
    return bool(filters.source_key or filters.market or filters.location)


def _filter_board_rows(rows: list[BoardRow], filters: BoardFilters) -> list[BoardRow]:
    filtered: list[BoardRow] = []
    for row in rows:
        if filters.source_key and filters.source_key not in _board_source_keys(row):
            continue
        if filters.market and not _list_contains(row.markets, filters.market):
            continue
        if filters.location and not _list_contains(row.locations, filters.location):
            continue
        filtered.append(row)
    return filtered


def _apply_job_sql_filters(statement, filters: JobFilters, provider_id: str | None):
    if filters.status != "all":
        statement = statement.where(JobRow.status == filters.status)
    if filters.board_key:
        statement = statement.where(JobRow.board_key == filters.board_key)
    if provider_id:
        statement = statement.where(JobRow.provider_id == provider_id)
    if filters.department:
        statement = statement.where(
            _contains_clause(JobVersionRow.department, filters.department)
        )
    if filters.team:
        statement = statement.where(_contains_clause(JobVersionRow.team, filters.team))
    if filters.workplace_type:
        statement = statement.where(
            _contains_clause(JobVersionRow.workplace_type, filters.workplace_type)
        )
    if filters.remote:
        statement = statement.where(
            func.lower(JobVersionRow.remote) == _casefold(filters.remote)
        )
    if filters.employment_type:
        statement = statement.where(
            _contains_clause(JobVersionRow.employment_type, filters.employment_type)
        )
    if filters.salary_min is not None:
        statement = statement.where(
            or_(
                col(JobVersionRow.salary_max) >= filters.salary_min,
                (col(JobVersionRow.salary_max).is_(None))
                & (col(JobVersionRow.salary_min) >= filters.salary_min),
            )
        )
    if filters.salary_max is not None:
        statement = statement.where(
            or_(
                col(JobVersionRow.salary_min) <= filters.salary_max,
                (col(JobVersionRow.salary_min).is_(None))
                & (col(JobVersionRow.salary_max) <= filters.salary_max),
            )
        )
    if filters.query:
        statement = statement.where(
            or_(
                _contains_clause(JobVersionRow.title, filters.query),
                _contains_clause(JobVersionRow.company, filters.query),
                _contains_clause(JobVersionRow.description, filters.query),
            )
        )
    return statement


def _job_needs_python_filter(filters: JobFilters) -> bool:
    return bool(
        filters.source_key
        or filters.location
        or filters.skill
        or filters.posted_after
        or filters.posted_before
    )


def _contains_clause(column, needle: str):
    return func.lower(column).contains(_casefold(needle))


def _job_matches_filters(
    job: JobRecord,
    filters: JobFilters,
    board_source_keys: dict[str, list[str]] | None = None,
) -> bool:
    if filters.source_key and filters.source_key not in (board_source_keys or {}).get(
        job.board_key, []
    ):
        return False
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
