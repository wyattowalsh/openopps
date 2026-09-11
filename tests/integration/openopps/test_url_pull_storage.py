from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from sqlmodel import Session, select

from openopps.ingest import sync_jobs
from openopps.models import (
    BoardProviderRecord,
    BoardProviderRow,
    BoardRecord,
    JobRecord,
    JobRow,
    PostingKind,
    ProviderSupport,
    SourceRecord,
)
from openopps.providers.boards.url_targets import URL_PULL_SOURCE_KEY
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.pull_models import (
    DiscoveryMethod,
    PullDetailCoverageEvidence,
    PullExecutionEvidence,
    PullMembershipEvidence,
    PullMembershipScope,
    PullOperation,
    PullProvenance,
    PullRawPosting,
    PullResult,
    PullRetrievalMechanism,
)
from openopps.pull_service import NullPullPersistence
from openopps.route_registry import BoardRouteRegistry
from openopps.route_select import route_ready
from openopps.settings import OpenOppsSettings
from openopps.source_resolution import resolve_effective_sources
from openopps.storage import (
    JobFilters,
    OpenOppsStore,
    UrlPullPersistenceError,
)
import openopps.storage as storage_module
from openopps.url_pull_identity import (
    JOB_MEMBERSHIP_DIRECT_ONLY,
    JOB_MEMBERSHIP_LISTED,
    URL_PULL_RESERVED_SOURCE_KEY,
    canonical_board_material,
    url_pull_board_digest,
    url_pull_board_key,
    url_pull_job_id,
)
from openopps.utils import slugify, stable_id


def _job(
    remote_id: str,
    *,
    board_key: str = "acme",
    provider_id: str = "greenhouse",
    posting_kind: PostingKind = "standard",
    title: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=f"{board_key}:{provider_id}:{remote_id}",
        board_key=board_key,
        provider_id=provider_id,
        remote_id=remote_id,
        title=title or f"Engineer {remote_id}",
        posting_kind=posting_kind,
        posting_url=f"https://boards.greenhouse.io/{board_key}/jobs/{remote_id}",
        raw_listing={"id": remote_id, "title": title or f"Engineer {remote_id}"},
        raw_detail={"content": "Build reliable systems."},
    )


def _raw(job: JobRecord) -> PullRawPosting:
    return PullRawPosting(
        job_id=job.id,
        listing=job.raw_listing,
        detail=job.raw_detail,
    )


def _list_execution(
    *,
    jobs: tuple[JobRecord, ...],
    scope: PullMembershipScope = PullMembershipScope.LISTED,
) -> PullExecutionEvidence:
    return PullExecutionEvidence(
        mechanism=PullRetrievalMechanism.LIST,
        membership=PullMembershipEvidence(
            scope=scope,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=len(jobs),
            advertised_count=len(jobs),
        ),
        detail_coverage=PullDetailCoverageEvidence(
            required=False,
            requested_count=0,
            completed_count=0,
            failed_count=0,
        ),
    )


def _provenance(
    *,
    board_identity: str = "acme",
    provider_id: str = "greenhouse",
    requested_url: str = "https://careers.example.com/acme",
    resolved_url: str = "https://boards.greenhouse.io/acme",
    requested_operation: PullOperation = PullOperation.AUTO,
    resolved_operation: PullOperation = PullOperation.LIST,
    posting_identity: str | None = None,
) -> PullProvenance:
    return PullProvenance(
        requested_url=requested_url,
        resolved_url=resolved_url,
        discovery_method=DiscoveryMethod.NATIVE_URL,
        provider_id=provider_id,
        requested_operation=requested_operation,
        resolved_operation=resolved_operation,
        board_identity=board_identity,
        posting_identity=posting_identity,
    )


def _list_result(
    jobs: tuple[JobRecord, ...],
    *,
    board_identity: str = "acme",
    provider_id: str = "greenhouse",
    requested_url: str = "https://careers.example.com/acme",
    resolved_url: str = "https://boards.greenhouse.io/acme",
    scope: PullMembershipScope = PullMembershipScope.LISTED,
) -> PullResult:
    return PullResult(
        provenance=_provenance(
            board_identity=board_identity,
            provider_id=provider_id,
            requested_url=requested_url,
            resolved_url=resolved_url,
            resolved_operation=PullOperation.LIST,
        ),
        execution=_list_execution(jobs=jobs, scope=scope),
        jobs=jobs,
        raw_postings=tuple(_raw(job) for job in jobs),
    )


def _get_result(
    job: JobRecord,
    *,
    requested_url: str | None = None,
    resolved_url: str | None = None,
) -> PullResult:
    posting_url = (
        requested_url or job.posting_url or "https://boards.greenhouse.io/acme/jobs/1"
    )
    return PullResult(
        provenance=_provenance(
            board_identity=job.board_key,
            provider_id=job.provider_id,
            requested_url=posting_url,
            resolved_url=resolved_url or posting_url,
            requested_operation=PullOperation.GET,
            resolved_operation=PullOperation.GET,
            posting_identity=job.remote_id,
        ),
        execution=PullExecutionEvidence(mechanism=PullRetrievalMechanism.NATIVE_GET),
        jobs=(job,),
        raw_postings=(_raw(job),),
    )


def _store(tmp_path: Path) -> tuple[OpenOppsStore, Path]:
    db_path = tmp_path / "openopps.db"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    store.init_db()
    return store, db_path


def _digest_key(provider_id: str, native: str) -> str:
    return url_pull_board_key(
        url_pull_board_digest(
            provider_id=provider_id,
            native_board_identity=native,
            canonical_board_material=canonical_board_material(
                provider_id=provider_id,
                native_board_identity=native,
            ),
        )
    )


def _count(db_path: Path, table: str, where: str = "1=1") -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


def _job_row(db_path: Path, job_id: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    return row


def test_url_pull_identity_preserves_punctuation_and_excludes_selectors() -> None:
    dotted = _digest_key("greenhouse", "acme.co")
    dashed = _digest_key("greenhouse", "acme-co")
    assert dotted != dashed
    assert slugify("acme.co") == slugify("acme-co") == "acme-co"
    assert dotted != f"url-pull:{stable_id('greenhouse', 'acme.co')}"
    assert "acme-co" not in dotted
    assert url_pull_board_digest(
        provider_id="greenhouse",
        native_board_identity="acme.co",
        canonical_board_material=canonical_board_material(
            provider_id="greenhouse",
            native_board_identity="acme.co",
        ),
    ) != stable_id("greenhouse", "acme.co")
    assert URL_PULL_RESERVED_SOURCE_KEY not in BOARD_SOURCE_CATALOG
    reserved = SourceRecord(
        key=URL_PULL_RESERVED_SOURCE_KEY,
        url="manual://url-pull",
        provider_id="url-pull",
        raw_metadata={"owned_by": "url-pull"},
    )
    catalog = SourceRecord(
        key="yc",
        url="https://www.ycombinator.com/companies",
        provider_id="ycombinator",
    )
    assert resolve_effective_sources([catalog], [reserved, catalog]) == [catalog]
    assert resolve_effective_sources([], [reserved]) == []


def test_equivalent_urls_converge_and_keep_domain_null(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    first = _list_result(
        (_job("1"),),
        requested_url="https://careers.example.com/acme",
        resolved_url="https://boards.greenhouse.io/acme",
    )
    second = _list_result(
        (_job("1"), _job("2")),
        requested_url="https://jobs.example.net/acme",
        resolved_url="https://boards.greenhouse.io/acme/jobs",
    )

    first_run = store.apply_url_pull_list(first)
    second_run = store.apply_url_pull_list(second)

    board_key = _digest_key("greenhouse", "acme")
    assert first_run.board_key == second_run.board_key == board_key
    assert first_run.job_sync_run_id != second_run.job_sync_run_id
    with sqlite3.connect(db_path) as conn:
        board = conn.execute(
            "SELECT key, source_key, remote_id, domain FROM boards WHERE key = ?",
            (board_key,),
        ).fetchone()
        jobs = conn.execute(
            "SELECT id, board_key FROM jobs ORDER BY remote_id"
        ).fetchall()
    assert board == (board_key, URL_PULL_RESERVED_SOURCE_KEY, "greenhouse:acme", None)
    assert [row[1] for row in jobs] == [board_key, board_key]
    assert all(not row[0].startswith("acme:") for row in jobs)
    persisted = store.list_jobs(filters=JobFilters(status="all"))
    assert {job.board_key for job in persisted} == {board_key}
    assert {job.id for job in persisted} == {
        url_pull_job_id(board_key=board_key, provider_id="greenhouse", remote_id="1"),
        url_pull_job_id(board_key=board_key, provider_id="greenhouse", remote_id="2"),
    }


def test_unowned_reserved_source_is_zero_mutation_collision(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    store.upsert_source(
        SourceRecord(
            key=URL_PULL_RESERVED_SOURCE_KEY,
            url="https://example.com/jobs",
            provider_id="manual",
        )
    )
    before = (
        _count(db_path, "sources"),
        _count(db_path, "boards"),
        _count(db_path, "jobs"),
        _count(db_path, "job_sync_runs"),
        _count(db_path, "url_pull_runs"),
    )

    with pytest.raises(UrlPullPersistenceError, match="not owned") as exc_info:
        store.apply_url_pull_list(_list_result((_job("1"),)))

    assert exc_info.value.error_kind == "namespace_collision"
    assert before == (
        _count(db_path, "sources"),
        _count(db_path, "boards"),
        _count(db_path, "jobs"),
        _count(db_path, "job_sync_runs"),
        _count(db_path, "url_pull_runs"),
    )
    assert _count(db_path, "url_pull_runs") == 0


def test_colliding_board_key_is_zero_mutation_collision(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    board_key = _digest_key("greenhouse", "acme")
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key=board_key,
                source_key="manual",
                remote_id="planted",
                name="Colliding",
                domain="evil.example",
            )
        ]
    )
    before = (
        _count(db_path, "boards"),
        _count(db_path, "jobs"),
        _count(db_path, "job_sync_runs"),
        _count(db_path, "url_pull_runs"),
    )

    with pytest.raises(UrlPullPersistenceError, match="collides") as exc_info:
        store.apply_url_pull_list(_list_result((_job("1"),)))

    assert exc_info.value.error_kind == "namespace_collision"
    assert before == (
        _count(db_path, "boards"),
        _count(db_path, "jobs"),
        _count(db_path, "job_sync_runs"),
        _count(db_path, "url_pull_runs"),
    )
    with sqlite3.connect(db_path) as conn:
        planted = conn.execute(
            "SELECT source_key, domain FROM boards WHERE key = ?",
            (board_key,),
        ).fetchone()
    assert planted == ("manual", "evil.example")


def test_incomplete_pull_result_is_rejected_before_txn(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    job = _job("1")
    incomplete = PullResult.model_construct(
        provenance=_provenance(resolved_operation=PullOperation.LIST),
        execution=PullExecutionEvidence.model_construct(
            mechanism=PullRetrievalMechanism.LIST,
            membership=PullMembershipEvidence.model_construct(
                scope=PullMembershipScope.LISTED,
                authoritative=False,
                complete=False,
                terminal_page_seen=False,
                pages_fetched=1,
                observed_count=1,
            ),
            detail_coverage=PullDetailCoverageEvidence(required=False),
        ),
        jobs=(job,),
        raw_postings=(_raw(job),),
        persisted=False,
        observability=None,
    )

    with pytest.raises(ValueError, match="authoritative membership"):
        store.apply_url_pull_list(incomplete)

    assert _count(db_path, "url_pull_runs") == 0
    assert _count(db_path, "jobs") == 0
    assert _count(db_path, "boards") == 0
    assert _count(db_path, "job_sync_runs") == 0


@pytest.mark.parametrize(
    ("hook_name", "fail_on"),
    [
        ("_sync_job_record", "after_first_job"),
        ("_close_missing_jobs", "before_close"),
        ("commit", "on_commit"),
    ],
)
def test_injected_list_failures_leave_only_sanitized_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_name: str,
    fail_on: str,
) -> None:
    store, db_path = _store(tmp_path)
    jobs = (_job("1"), _job("2"))
    result = _list_result(jobs)

    if hook_name == "_sync_job_record":
        real = storage_module._sync_job_record
        calls = {"n": 0}

        def fail_after_first(session, job, observed_at):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("injected-after-first-job secret")
            return real(session, job, observed_at)

        monkeypatch.setattr(storage_module, "_sync_job_record", fail_after_first)
    elif hook_name == "_close_missing_jobs":
        def fail_before_close(*args, **kwargs):
            raise RuntimeError("injected-before-close secret")

        monkeypatch.setattr(storage_module, "_close_missing_jobs", fail_before_close)
    else:
        real_commit = Session.commit
        commits = {"n": 0}

        def fail_on_apply_commit(self, *args, **kwargs):
            commits["n"] += 1
            if commits["n"] == 2:
                raise RuntimeError("injected-commit secret")
            return real_commit(self, *args, **kwargs)

        monkeypatch.setattr(storage_module.Session, "commit", fail_on_apply_commit)

    with pytest.raises(RuntimeError, match="injected"):
        store.apply_url_pull_list(result)

    assert _count(db_path, "jobs") == 0
    assert _count(db_path, "job_versions") == 0
    assert _count(db_path, "job_sync_runs") == 0
    assert _count(db_path, "url_pull_runs") == 1
    with sqlite3.connect(db_path) as conn:
        audit = conn.execute(
            "SELECT status, error_kind, error, board_key, job_sync_run_id "
            "FROM url_pull_runs"
        ).fetchone()
        boards = conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
    assert audit == ("failed", "persistence", "URL-pull persistence failed: RuntimeError.", None, None)
    assert "secret" not in (audit[2] or "")
    assert "injected" not in (audit[2] or "")
    assert boards == 0
    del fail_on


def test_listed_snapshot_closes_only_listed_and_promotes_direct_only(
    tmp_path: Path,
) -> None:
    store, db_path = _store(tmp_path)
    board_key = _digest_key("greenhouse", "acme")
    listed_one = _job("listed-1")
    listed_two = _job("listed-2")
    unlisted = _job("direct-1", posting_kind="unlisted")

    store.apply_url_pull_list(_list_result((listed_one, listed_two)))
    store.apply_url_pull_get(_get_result(unlisted))

    listed_id = url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="listed-1"
    )
    missing_id = url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="listed-2"
    )
    direct_id = url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="direct-1"
    )
    assert _job_row(db_path, direct_id)["membership"] == JOB_MEMBERSHIP_DIRECT_ONLY
    assert _job_row(db_path, listed_id)["status"] == "open"

    store.apply_url_pull_list(_list_result((listed_one,)))
    assert _job_row(db_path, listed_id)["status"] == "open"
    assert _job_row(db_path, missing_id)["status"] == "closed"
    assert _job_row(db_path, direct_id)["status"] == "open"
    assert _job_row(db_path, direct_id)["membership"] == JOB_MEMBERSHIP_DIRECT_ONLY

    promoted = _job("direct-1", posting_kind="standard", title="Engineer direct-1")
    store.apply_url_pull_list(_list_result((listed_one, promoted)))
    assert _job_row(db_path, direct_id)["membership"] == JOB_MEMBERSHIP_LISTED
    assert _job_row(db_path, direct_id)["status"] == "open"

    store.apply_url_pull_list(_list_result((listed_one,)))
    assert _job_row(db_path, direct_id)["status"] == "closed"

    unlisted_again = _job("direct-2", posting_kind="unlisted")
    store.apply_url_pull_get(_get_result(unlisted_again))
    direct_two = url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="direct-2"
    )
    store.apply_url_pull_list(
        _list_result((listed_one,), scope=PullMembershipScope.ALL_PUBLIC)
    )
    assert _job_row(db_path, listed_id)["status"] == "open"
    assert _job_row(db_path, direct_two)["status"] == "closed"


def test_catalog_sync_jobs_for_route_is_listed_default_close(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
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
    listed = JobRecord(
        id="acme:lever:listed",
        board_key="acme",
        provider_id="lever",
        remote_id="listed",
        title="Listed",
        membership=JOB_MEMBERSHIP_LISTED,
    )
    direct = JobRecord(
        id="acme:lever:direct",
        board_key="acme",
        provider_id="lever",
        remote_id="direct",
        title="Direct",
        membership=JOB_MEMBERSHIP_DIRECT_ONLY,
        posting_kind="unlisted",
    )
    first = store.sync_jobs_for_route("acme", "lever", [listed, direct])
    assert first.membership_scope == "listed"
    empty = store.sync_jobs_for_route("acme", "lever", [])
    assert empty.closed_count == 1
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT remote_id, status, membership FROM jobs ORDER BY remote_id"
        ).fetchall()
    assert rows == [
        ("direct", "open", JOB_MEMBERSHIP_DIRECT_ONLY),
        ("listed", "closed", JOB_MEMBERSHIP_LISTED),
    ]


def test_url_pull_get_persists_one_posting_without_sync_run(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    listed = _list_result((_job("1"), _job("2")))
    store.apply_url_pull_list(listed)
    extra_id = "url-pull-extra-route"
    board_key = _digest_key("greenhouse", "acme")
    with Session(store.engine) as session:
        session.add(
            BoardProviderRow(
                id=extra_id,
                source_key=URL_PULL_RESERVED_SOURCE_KEY,
                board_key=board_key,
                provider_id="lever",
                support_level=ProviderSupport.JOBS.value,
                token="planted",
            )
        )
        session.commit()
    sync_runs_before = _count(db_path, "job_sync_runs")
    routes_before = _count(db_path, "board_providers")
    sibling_id = url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="2"
    )

    run = store.apply_url_pull_get(_get_result(_job("9", posting_kind="unlisted")))

    assert run.status == "succeeded"
    assert run.job_sync_run_id is None
    assert run.job_id == url_pull_job_id(
        board_key=board_key, provider_id="greenhouse", remote_id="9"
    )
    assert _count(db_path, "job_sync_runs") == sync_runs_before
    assert _count(db_path, "board_providers") == routes_before
    assert _job_row(db_path, sibling_id)["status"] == "open"
    with Session(store.engine) as session:
        extra = session.get(BoardProviderRow, extra_id)
        assert extra is not None
        jobs = session.exec(select(JobRow).where(JobRow.status == "open")).all()
    assert {job.remote_id for job in jobs} == {"1", "2", "9"}


def test_no_save_port_does_not_call_store_apply(tmp_path: Path) -> None:
    store, db_path = _store(tmp_path)
    result = _list_result((_job("1"),))
    called: list[str] = []

    def _list(payload: PullResult) -> object:
        called.append("list")
        return OpenOppsStore.apply_url_pull_list(store, payload)

    def _get(payload: PullResult) -> object:
        called.append("get")
        return OpenOppsStore.apply_url_pull_get(store, payload)

    store.apply_url_pull_list = _list  # type: ignore[method-assign]
    store.apply_url_pull_get = _get  # type: ignore[method-assign]

    asyncio.run(NullPullPersistence().persist(result))

    assert called == []
    assert _count(db_path, "url_pull_runs") == 0
    assert _count(db_path, "jobs") == 0
    assert _count(db_path, "boards") == 0
    assert _count(db_path, "job_sync_runs") == 0


def _plant_catalog_greenhouse_route(store: OpenOppsStore) -> None:
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="catalog-acme",
                source_key="manual",
                remote_id="catalog-acme",
                name="Catalog Acme",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:catalog-acme:greenhouse",
                source_key="manual",
                board_key="catalog-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="catalog-acme",
            )
        ]
    )


def test_unscoped_job_route_select_excludes_url_pull_after_persist(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    store.apply_url_pull_list(_list_result((_job("1"),)))
    _plant_catalog_greenhouse_route(store)

    persisted_routes = store.list_board_providers(job_capable_only=True)
    assert any(route.source_key == URL_PULL_SOURCE_KEY for route in persisted_routes)
    assert any(
        route.source_key == URL_PULL_SOURCE_KEY and route_ready(route)
        for route in persisted_routes
    )
    assert any(
        board.source_key == URL_PULL_SOURCE_KEY
        for board in store.list_boards(with_providers=False)
    )

    selection = BoardRouteRegistry(store).select(ready_only=True)
    assert [entry.route.source_key for entry in selection.entries] == ["manual"]
    assert all(
        entry.route.source_key != URL_PULL_SOURCE_KEY for entry in selection.entries
    )
    assert all(
        entry.board.source_key != URL_PULL_SOURCE_KEY for entry in selection.entries
    )
    assert all(
        route.source_key != URL_PULL_SOURCE_KEY
        for route in selection.missing_route_metadata
    )
    assert all(
        route.source_key != URL_PULL_SOURCE_KEY for route in selection.duplicate_routes
    )


def test_reserved_url_pull_source_pin_fail_closes_job_route_select(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    store.apply_url_pull_list(_list_result((_job("1"),)))
    registry = BoardRouteRegistry(store)

    with pytest.raises(ValueError, match=r"^Unknown source: url-pull$"):
        registry.select(source_key=URL_PULL_SOURCE_KEY, ready_only=True)
    with pytest.raises(ValueError, match=r"^Unknown source: url-pull$"):
        registry.select(source_keys=[URL_PULL_SOURCE_KEY], ready_only=True)
    with pytest.raises(ValueError, match=r"^Unknown source: url-pull$"):
        registry.select(source_keys=["manual", URL_PULL_SOURCE_KEY], ready_only=True)


async def test_unscoped_sync_jobs_does_not_ingest_url_pull_routes(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    store.apply_url_pull_list(_list_result((_job("1"),)))

    metrics = await sync_jobs(settings=store.settings, store=store)

    assert metrics.job_sync_attempts == 0
    assert metrics.jobs == 0


async def test_sync_jobs_fail_closes_reserved_url_pull_source_pin(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    store.apply_url_pull_list(_list_result((_job("1"),)))

    with pytest.raises(ValueError, match=r"^Unknown source: url-pull$"):
        await sync_jobs(
            settings=store.settings,
            store=store,
            source_key=URL_PULL_SOURCE_KEY,
        )


def test_list_existing_board_providers_does_not_create_missing_sqlite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    assert store.catalog_schema_ready() is False
    assert store.list_existing_board_providers(job_capable_only=True) == []
    assert not db_path.exists()


def test_list_existing_board_providers_reads_initialized_catalog(
    tmp_path: Path,
) -> None:
    store, db_path = _store(tmp_path)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:greenhouse",
                source_key="manual",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            )
        ]
    )
    alembic_before = _count(db_path, "alembic_version")
    url_pull_before = _count(db_path, "url_pull_runs")

    routes = store.list_existing_board_providers(
        provider_id="greenhouse",
        job_capable_only=True,
    )

    assert [route.token for route in routes] == ["acme"]
    assert _count(db_path, "alembic_version") == alembic_before
    assert _count(db_path, "url_pull_runs") == url_pull_before == 0
