import asyncio
import json
import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

import openopps.ingest as ingest_module
from openopps.ingest import sync_boards, sync_jobs, sync_sources
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.sources.consider import CONSIDER_SOURCE_CATALOG
from openopps.providers.sources.sec import SEC_COMPANY_TICKERS_SOURCE
from openopps.route_probe import probe_routes
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def _mock_greenhouse_jobs(token: str, jobs: list[dict[str, object]]) -> Any:
    return respx.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": jobs})
    )


def test_unscoped_source_selection_includes_every_catalog_source(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(SEC_COMPANY_TICKERS_SOURCE)

    selected = ingest_module._select_sources(store, None)
    explicit = ingest_module._select_sources(store, "sec-company-tickers")

    assert "sec-company-tickers" in {source.key for source in selected}
    assert explicit[0].key == "sec-company-tickers"


def test_unscoped_source_selection_preserves_custom_source_overrides(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(
            key="a16z",
            url="https://custom.example/companies",
            provider_id="consider",
        )
    )

    selected = ingest_module._select_sources(store, None)
    explicit = ingest_module._select_sources(store, "a16z")

    assert "a16z" in {source.key for source in selected}
    assert next(source for source in selected if source.key == "a16z").url == (
        "https://custom.example/companies"
    )
    assert explicit[0].url == "https://custom.example/companies"


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_dedupes_same_provider_route_across_sources(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}", board_concurrency=2
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="source-b", url="source-b://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a-acme",
                source_key="source-a",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
            BoardRecord(
                key="source-b-acme",
                source_key="source-b",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="source-a:source-a-acme:greenhouse",
                source_key="source-a",
                board_key="source-a-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="source-b:source-b-acme:greenhouse",
                source_key="source-b",
                board_key="source-b-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
        ]
    )
    route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="all")

    assert route.call_count == 1
    assert metrics.duplicate_routes_skipped == 1
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 1
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_reports_persisted_runs_and_deduped_jobs(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
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
    _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            },
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            },
        ],
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert metrics.jobs == 2
    assert metrics.jobs_persisted == 1
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 1
    assert metrics.jobs_deduped == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_refreshes_stale_routes_before_fresh_with_limit(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="fresh", source_key="manual", remote_id="Fresh", name="Fresh"
            ),
            BoardRecord(
                key="never", source_key="manual", remote_id="Never", name="Never"
            ),
            BoardRecord(
                key="stale", source_key="manual", remote_id="Stale", name="Stale"
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=f"manual:{key}:greenhouse",
                source_key="manual",
                board_key=key,
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token=key,
            )
            for key in ("fresh", "never", "stale")
        ]
    )
    now = utc_now()
    store.sync_jobs_for_route("fresh", "greenhouse", [], synced_at=now)
    store.sync_jobs_for_route(
        "stale", "greenhouse", [], synced_at=now - timedelta(hours=2)
    )
    fresh_route = _mock_greenhouse_jobs("fresh", [])
    never_route = _mock_greenhouse_jobs(
        "never",
        [
            {
                "id": 1,
                "title": "Never Synced Engineer",
                "absolute_url": "https://boards.greenhouse.io/never/jobs/1",
            }
        ],
    )
    stale_route = _mock_greenhouse_jobs(
        "stale",
        [
            {
                "id": 1,
                "title": "Stale Engineer",
                "absolute_url": "https://boards.greenhouse.io/stale/jobs/1",
            }
        ],
    )

    metrics = await sync_jobs(
        settings=settings,
        store=store,
        provider_id="greenhouse",
        freshness_seconds=3600,
        limit=2,
    )

    assert fresh_route.call_count == 0
    assert never_route.call_count == 1
    assert stale_route.call_count == 1
    assert metrics.skipped == 1
    assert metrics.job_sync_attempts == 2
    assert metrics.job_sync_runs == 2
    assert metrics.jobs_persisted == 2


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_excludes_route_hints_without_executable_metadata(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:greenhouse",
                source_key="manual",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )
    route = _mock_greenhouse_jobs("acme", [])

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert route.call_count == 0
    assert metrics.skipped == 0
    assert metrics.jobs == 0


@pytest.mark.asyncio
async def test_sync_boards_does_not_warn_on_unresolved_route_candidates(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:future-provider",
                source_key="manual",
                board_key="acme",
                provider_id="future-provider",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )

    metrics = await sync_boards(settings=settings, store=store)

    assert metrics.skipped == 0
    assert metrics.provider_errors == {}


@pytest.mark.asyncio
@respx.mock
async def test_sync_boards_reports_route_probe_error_details(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="manual",
                remote_id="Acme",
                name="Acme",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:greenhouse",
                source_key="manual",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "false"},
    ).mock(return_value=httpx.Response(429, json={"error": "rate limit"}))

    metrics = await sync_boards(
        settings=settings, store=store, provider_id="greenhouse", max_candidates=1
    )

    assert metrics.provider_errors == {"greenhouse": 1}
    assert metrics.provider_error_details == {"greenhouse": {"rate_limited": 1}}


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_removes_terminal_provider_routes(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
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
                last_status="route_ready",
            )
        ]
    )
    route = respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(404, json={"message": "board not found"})
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert route.call_count == 1
    assert metrics.provider_errors == {}
    assert metrics.skipped == 0
    stored = store.list_board_providers(provider_id="greenhouse")[0]
    assert stored.support_level == ProviderSupport.DETECT
    assert stored.last_status == "job_sync_unavailable_404"


@pytest.mark.asyncio
async def test_sync_jobs_classifies_stuck_provider_route_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        job_route_timeout_seconds=0.01,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
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

    class HangingProvider:
        async def fetch_jobs(self, *_args: object) -> list[object]:
            await asyncio.sleep(1)
            return []

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: HangingProvider(),
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert metrics.provider_errors == {"greenhouse": 1}
    assert metrics.provider_error_details == {"greenhouse": {"timeout": 1}}
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 0
    assert metrics.jobs == 0

    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        run = conn.execute(
            """
            SELECT status, success, error_kind, error, started_at, finished_at,
                   committed_batch_count
            FROM job_sync_runs
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()

    assert run is not None
    assert run[0:3] == ("failed", 0, "timeout")
    assert run[3] == "TimeoutError"
    assert run[4] is not None
    assert run[5] is not None
    assert run[6] == 0


@pytest.mark.asyncio
async def test_sync_jobs_persists_pending_run_before_provider_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="fake")
    observed_pending: tuple[str, int, str | None] | None = None

    class InspectingProvider:
        async def fetch_jobs(self, *_args: object):
            nonlocal observed_pending
            with sqlite3.connect(db_path) as conn:
                observed_pending = conn.execute(
                    """
                    SELECT status, success, finished_at
                    FROM job_sync_runs
                    ORDER BY rowid DESC
                    LIMIT 1
                    """
                ).fetchone()
            return []

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: InspectingProvider(),
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="fake")

    assert observed_pending == ("pending", 0, None)
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 0


@pytest.mark.asyncio
async def test_sync_jobs_finishes_cancelled_provider_fetch_as_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="fake")
    fetch_started = asyncio.Event()

    class CancelledProvider:
        async def fetch_jobs(self, *_args: object):
            fetch_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: CancelledProvider(),
    )

    sync_task = asyncio.create_task(
        sync_jobs(settings=settings, store=store, provider_id="fake")
    )
    await fetch_started.wait()
    sync_task.cancel("credential=plaintext-secret")

    with pytest.raises(asyncio.CancelledError):
        await sync_task

    with sqlite3.connect(db_path) as conn:
        run = conn.execute(
            """
            SELECT status, success, error_kind, error, started_at, finished_at,
                   committed_batch_count
            FROM job_sync_runs
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()

    assert run is not None
    assert run[0:3] == ("failed", 0, "cancelled")
    assert run[3] == "Provider job fetch was cancelled."
    assert "plaintext-secret" not in run[3]
    assert run[4] is not None
    assert run[5] is not None
    assert run[6] == 0


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_removes_duplicate_terminal_provider_routes(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="overlap", url="manual://overlap", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
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
                last_status="route_ready",
            ),
            BoardProviderRecord(
                id="overlap:acme:greenhouse",
                source_key="overlap",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
                last_status="route_ready",
            ),
        ]
    )
    route = respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(404, json={"message": "board not found"})
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert route.call_count == 1
    assert metrics.duplicate_routes_skipped == 1
    stored = store.list_board_providers(provider_id="greenhouse")
    assert {route.support_level for route in stored} == {ProviderSupport.DETECT}
    assert {route.last_status for route in stored} == {"job_sync_unavailable_404"}


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_unscoped_covers_all_persisted_ready_routes(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs("acme", [])
    source_b_route = _mock_greenhouse_jobs(
        "beta",
        [
            {
                "id": 2,
                "title": "Designer",
                "absolute_url": "https://boards.greenhouse.io/beta/jobs/2",
            }
        ],
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="all")

    assert source_a_route.call_count == 1
    assert source_b_route.call_count == 1
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_source_argument_filters_unscoped_route_set(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )
    source_b_route = _mock_greenhouse_jobs("beta", [])

    metrics = await sync_jobs(
        settings=settings, store=store, source_key="source-a", provider_id="all"
    )

    assert source_a_route.call_count == 1
    assert source_b_route.call_count == 0
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_board_argument_filters_unscoped_route_set(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )
    source_b_route = _mock_greenhouse_jobs("beta", [])

    metrics = await sync_jobs(
        settings=settings,
        store=store,
        board_key="source-a-acme",
        provider_id="all",
    )

    assert source_a_route.call_count == 1
    assert source_b_route.call_count == 0
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_sources_preserves_route_metadata_across_repeated_syncs(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(CONSIDER_SOURCE_CATALOG["lsvp"])
    route = respx.post("https://jobs.lsvp.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200, json={"companies": [], "total": 0, "meta": {"size": 1}}
        )
    )

    first_metrics = await sync_sources(
        settings=settings, store=store, source_key="lsvp", page_size=1
    )
    second_metrics = await sync_sources(
        settings=settings, store=store, source_key="lsvp", page_size=1
    )

    assert first_metrics.provider_errors == {}
    assert second_metrics.provider_errors == {}
    assert route.call_count == 2
    request_bodies = [json.loads(call.request.content) for call in route.calls]
    assert [body["query"]["parent"] for body in request_bodies] == [
        "lightspeed",
        "lightspeed",
    ]
    stored = store.get_source("lsvp")
    assert stored is not None
    assert stored.raw_metadata["board"] == "lightspeed"
    last_page = cast(dict[str, Any], stored.raw_metadata["lastPage"])
    assert last_page["total"] == 0
    assert "rawResponse" not in last_page


@pytest.mark.asyncio
async def test_sync_sources_progress_reports_unique_canonical_board_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeSourceAdapter:
        async def iter_boards(self, _client, source, *, page_size: int):
            yield (
                [
                    BoardRecord(
                        key=f"{source.key}:acme",
                        source_key=source.key,
                        remote_id="acme",
                        name="Acme",
                        domain="acme.com",
                    )
                ],
                [],
                {"version": {"pageSize": page_size}},
            )

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(SourceRecord(key="one", url="one://source", provider_id="fake"))
    store.upsert_source(SourceRecord(key="two", url="two://source", provider_id="fake"))
    reports: list[str] = []
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: FakeSourceAdapter(),
    )

    await sync_sources(
        settings=settings,
        store=store,
        page_size=10,
        report=lambda update: reports.append(update.message),
    )

    assert len(store.list_boards()) == 1
    assert any("[dim]boards[/] [green]1[/]" in message for message in reports)
    assert not any("[dim]boards[/] [green]2[/]" in message for message in reports)


@pytest.mark.asyncio
async def test_sync_sources_reconciles_stale_provider_routes_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    snapshots = [
        (
            [
                BoardRecord(
                    key="source-a:old-board",
                    source_key="source-a",
                    remote_id="old-board",
                    name="Old Board",
                    domain="old.example",
                )
            ],
            [
                BoardProviderRecord(
                    id="source-a:old-board:greenhouse",
                    source_key="source-a",
                    board_key="source-a:old-board",
                    provider_id="greenhouse",
                    support_level=ProviderSupport.JOBS,
                    token="old-board",
                )
            ],
        ),
        (
            [
                BoardRecord(
                    key="source-a:new-board",
                    source_key="source-a",
                    remote_id="new-board",
                    name="New Board",
                    domain="new.example",
                )
            ],
            [
                BoardProviderRecord(
                    id="source-a:new-board:greenhouse",
                    source_key="source-a",
                    board_key="source-a:new-board",
                    provider_id="greenhouse",
                    support_level=ProviderSupport.JOBS,
                    token="new-board",
                )
            ],
        ),
    ]

    class SnapshotAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            boards, providers = snapshots.pop(0)
            yield boards, providers, {"version": {"pageSize": page_size}}

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="fake")
    )
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: SnapshotAdapter(),
    )

    await sync_sources(
        settings=settings, store=store, source_key="source-a", page_size=10
    )
    assert [route.board_key for route in store.list_board_providers()] == [
        "source-a:old-board"
    ]

    await sync_sources(
        settings=settings, store=store, source_key="source-a", page_size=10
    )

    routes = store.list_board_providers(source_key="source-a")
    assert [(route.board_key, route.token) for route in routes] == [
        ("source-a:new-board", "new-board")
    ]


@pytest.mark.asyncio
async def test_sync_sources_preserves_existing_routes_for_boards_only_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class BoardsOnlyAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            yield (
                [
                    BoardRecord(
                        key="source-a:old-board",
                        source_key="source-a",
                        remote_id="old-board",
                        name="Old Board",
                        domain="old.example",
                    )
                ],
                [],
                {"version": {"pageSize": page_size}},
            )

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="fake")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a:old-board",
                source_key="source-a",
                remote_id="old-board",
                name="Old Board",
                domain="old.example",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="source-a:old-board:greenhouse",
                source_key="source-a",
                board_key="source-a:old-board",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="old-board",
            )
        ]
    )
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: BoardsOnlyAdapter(),
    )

    metrics = await sync_sources(
        settings=settings, store=store, source_key="source-a", page_size=10
    )

    assert metrics.board_providers == 0
    routes = store.list_board_providers(source_key="source-a")
    assert [(route.board_key, route.token) for route in routes] == [
        ("source-a:old-board", "old-board")
    ]


@pytest.mark.asyncio
async def test_sync_sources_preserves_routes_after_failed_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class SuccessfulAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            yield (
                [
                    BoardRecord(
                        key="source-a:old-board",
                        source_key="source-a",
                        remote_id="old-board",
                        name="Old Board",
                    )
                ],
                [
                    BoardProviderRecord(
                        id="source-a:old-board:greenhouse",
                        source_key="source-a",
                        board_key="source-a:old-board",
                        provider_id="greenhouse",
                        support_level=ProviderSupport.JOBS,
                        token="old-board",
                    )
                ],
                {"version": {"pageSize": page_size}},
            )

    class FailingAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            raise RuntimeError("source failed before a complete snapshot")
            yield [], [], {"version": {"pageSize": page_size}}

    adapters = [SuccessfulAdapter(), FailingAdapter()]
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="fake")
    )
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: adapters.pop(0),
    )

    await sync_sources(
        settings=settings, store=store, source_key="source-a", page_size=10
    )
    await sync_sources(
        settings=settings, store=store, source_key="source-a", page_size=10
    )

    routes = store.list_board_providers(source_key="source-a")
    assert [(route.board_key, route.token) for route in routes] == [
        ("source-a:old-board", "old-board")
    ]


@pytest.mark.asyncio
async def test_sync_sources_skips_recent_sources_with_freshness_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeSourceAdapter:
        async def iter_boards(self, _client, source, *, page_size: int):
            calls.append(source.key)
            yield (
                [
                    BoardRecord(
                        key=f"{source.key}:acme",
                        source_key=source.key,
                        remote_id="acme",
                        name="Acme",
                    )
                ],
                [],
                {"version": {"pageSize": page_size}},
            )

    now = utc_now()
    calls: list[str] = []
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        source_freshness_seconds=3600,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    sources = {
        "fresh": SourceRecord(
            key="fresh",
            url="fresh://source",
            provider_id="fake",
            synced_at=now,
        ),
        "stale": SourceRecord(
            key="stale",
            url="stale://source",
            provider_id="fake",
            synced_at=now - timedelta(hours=2),
        ),
    }
    for source in sources.values():
        store.upsert_source(source)
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", sources)
    monkeypatch.setattr(
        ingest_module,
        "all_board_sources",
        lambda: list(sources.values()),
    )
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: FakeSourceAdapter(),
    )

    metrics = await sync_sources(settings=settings, store=store, page_size=10)

    assert calls == ["stale"]
    assert metrics.skipped == 1
    assert [board.key for board in store.list_boards()] == ["stale:acme"]


@pytest.mark.asyncio
async def test_sync_sources_times_out_slow_source_and_continues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FastSourceAdapter:
        async def iter_boards(self, _client, source, *, page_size: int):
            yield (
                [
                    BoardRecord(
                        key=f"{source.key}:acme",
                        source_key=source.key,
                        remote_id="acme",
                        name="Acme",
                        domain="acme.com",
                    )
                ],
                [],
                {"version": {"pageSize": page_size}},
            )

    class SlowSourceAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            await asyncio.sleep(0.05)
            yield [], [], {"version": {"pageSize": page_size}}

    def build_fake_source_adapter(provider_id: str, _settings: OpenOppsSettings):
        if provider_id == "fast":
            return FastSourceAdapter()
        if provider_id == "slow":
            return SlowSourceAdapter()
        return None

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=2,
        source_timeout_seconds=0.01,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    sources = {
        "fast": SourceRecord(key="fast", url="fast://source", provider_id="fast"),
        "slow": SourceRecord(key="slow", url="slow://source", provider_id="slow"),
    }
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", sources)
    monkeypatch.setattr(
        ingest_module,
        "all_board_sources",
        lambda: list(sources.values()),
    )
    reports: list[str] = []
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        build_fake_source_adapter,
    )

    metrics = await sync_sources(
        settings=settings,
        store=store,
        page_size=10,
        report=lambda update: reports.append(update.message),
    )

    assert metrics.boards == 1
    assert metrics.skipped == 1
    assert metrics.provider_error_details == {"slow": {"timeout": 1}}
    assert [board.key for board in store.list_boards()] == ["fast:acme"]
    assert any("source[/] [yellow]slow[/]" in message for message in reports)
    assert any("skipped: timeout" in message for message in reports)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("source_key", "source_origin", "board_slug"),
    [
        ("battery", "https://jobs.battery.com", "battery-ventures"),
        ("costanoavc", "https://jobs.costanoavc.com", "costanoa-ventures"),
        (
            "forerunnerventures",
            "https://jobs.forerunnerventures.com",
            "forerunner-ventures",
        ),
        ("fincapital", "https://jobs.fin.capital", "fin-capital"),
        ("nextview", "https://jobs.nextview.vc", "nextview-ventures"),
        ("qedinvestors", "https://careers.qedinvestors.com", "qed-investors"),
        ("balderton", "https://careers.balderton.com", "balderton-capital"),
        ("creandum", "https://careers.creandum.com", "creandum"),
        (
            "amplifypartners",
            "https://talent.amplifypartners.com",
            "amplify-partners",
        ),
        ("gv", "https://jobs.gv.com", "gv"),
        ("nvp", "https://careers.nvp.com", "norwest-venture-partners"),
        ("anthemis", "https://jobs.anthemis.com", "anthemis-group"),
        ("fiftyyears", "https://jobs.fiftyyears.com", "fifty-years"),
        ("initialized", "https://jobs.initialized.com", "initialized"),
        ("crv", "https://jobs.crv.com", "crv"),
        ("zettavp", "https://careers.zettavp.com", "zetta-venture-partners"),
        ("contrary", "https://jobs.contrary.com", "contrary"),
        ("goldenventures", "https://jobs.golden.ventures", "golden-ventures"),
        ("necessary", "https://jobs.necessary.vc", "necessary-ventures"),
        ("5amventures", "https://jobs.5amventures.com", "5am-ventures"),
        (
            "illuminatefinancial",
            "https://jobs.illuminatefinancial.com",
            "illuminate-financial",
        ),
        ("xange", "https://jobs.xange.vc", "xange"),
        ("sosv", "https://techjobs.sosv.com", "sosv"),
        ("hardyaka", "https://jobs.hardyaka.com", "hard-yaka"),
        ("panteracapital", "https://jobs.panteracapital.com", "pantera-capital"),
        (
            "vuventurepartners",
            "https://jobs.vuventurepartners.com",
            "vu-venture-partners",
        ),
        ("linkventures", "https://jobs.linkventures.com", "link-ventures"),
        ("aixventures", "https://careers.aixventures.com", "aix-ventures"),
        ("woven", "https://portfoliojobs.woven.vc", "woven-capital"),
        ("playground", "https://careers.playground.global", "playground-global"),
        ("hoxtonventures", "https://jobs.hoxtonventures.com", "hoxton-ventures"),
        (
            "conversioncapital",
            "https://jobs.conversioncapital.com",
            "conversion-capital",
        ),
        ("alter", "https://careers.alter.vc", "alter-global"),
        ("iconventures", "https://jobs.iconventures.com", "icon-ventures"),
        ("gaingels", "https://jobs.gaingels.com", "gaingels"),
        ("nexusvp", "https://jobs.nexusvp.com", "nexus-venture-partners"),
        ("mvp", "https://talent.mvp-vc.com", "mvp-ventures"),
        ("offline", "https://jobs.offline.vc", "offline-ventures"),
        (
            "hitachiventures",
            "https://jobs.hitachi-ventures.com",
            "hitachi-ventures",
        ),
        ("atlasventure", "https://careers.atlasventure.com", "atlas-venture"),
        ("transition", "https://jobs.transition.vc", "transition-ventures"),
        ("age1", "https://careers.age1.com", "age1"),
        ("bakarlabs", "https://jobs.bakarlabs.org", "bakar-bio-labs"),
        ("startx", "https://jobs.startx.com", "startx"),
        ("e14", "https://jobs.e14.vc", "e14-fund"),
        ("notion", "https://jobs.notion.vc", "notion-capital"),
        ("notation", "https://consider.com", "notation-capital"),
        ("threshold", "https://jobs.threshold.vc", "threshold-ventures"),
        ("atoneventures", "https://jobs.atoneventures.com", "at-one-ventures"),
        ("mantisvc", "https://careers.mantisvc.com", "mantis"),
        (
            "fenbushicapital",
            "https://careers.fenbushicapital.vc",
            "fenbushi-capital",
        ),
        ("f2vc", "https://jobs.f2vc.com", "f2-venture-capital"),
        ("abstractvc", "https://jobs.abstractvc.com", "abstract-ventures"),
        (
            "urbaninnovationfund",
            "https://jobs.urbaninnovationfund.com",
            "urban-innovation-fund",
        ),
        ("extantia", "https://careers.extantia.com", "extantia"),
        ("oneragtime", "https://careers.oneragtime.com", "oneragtime"),
        ("adverb", "https://jobs.adverb.vc", "adverb-ventures"),
        ("expa", "https://jobs.expa.com", "expa"),
        ("01a", "https://jobs.01a.com", "01-advisors"),
        ("360cap", "https://jobs.360cap.vc", "360-capital"),
        ("adara", "https://talent.adara.vc", "adara-ventures"),
        ("aifund", "https://careers.aifund.ai", "ai-fund"),
        ("alven", "https://jobs.alven.co", "alven"),
        ("amplifyla", "https://jobs.amplify.la", "amplify-la"),
        ("congruentvc", "https://jobs.congruentvc.com", "congruent-ventures"),
        ("etherealventures", "https://consider.com", "ethereal-ventures"),
        ("foothillventures", "https://jobs.foothill.ventures", "foothill-ventures"),
        ("founderful", "https://jobs.founderful.com", "wingman"),
        ("galvanizeclimate", "https://consider.com", "galvanize-climate-solutions"),
        ("gradient", "https://careers.gradient.com", "gradient-ventures"),
        ("gtmfund", "https://jobs.gtmfund.com", "gtmfund"),
        ("istariglobal", "https://careers.istari-global.com", "istari"),
        ("lemniscap", "https://careers.lemniscap.com", "lemniscap"),
        (
            "oregonventurefund",
            "https://jobs.oregonventurefund.com",
            "oregon-venture-fund",
        ),
        ("peakxv", "https://careers.peakxv.com", "sequoia-capital-india"),
        ("radiancapital", "https://careers.radiancapital.com", "radian-capital"),
        ("serena", "https://careers.serena.vc", "serena"),
        ("setventures", "https://careers.setventures.com", "set-ventures"),
        ("skyvc", "https://careers.sky-vc.com", "jetblue-ventures"),
        ("sterlingpartners", "https://consider.com", "sterling-partners"),
        ("thomvest", "https://jobs.thomvest.com", "thomvest"),
        ("tidemarkcap", "https://careers.tidemarkcap.com", "tidemark-capital"),
        ("verdane", "https://consider.com", "verdane"),
    ],
)
async def test_catalog_consider_source_feeds_downstream_route_probe(
    tmp_path: Path,
    source_key: str,
    source_origin: str,
    board_slug: str,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        provider_concurrency=1,
        source_concurrency=1,
    )
    store = OpenOppsStore(settings)
    source_route = respx.post(f"{source_origin}/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "Acme",
                        "slug": "acme",
                        "name": "Acme",
                        "domain": "acme.com",
                        "numJobs": 2,
                        "jobSources": [
                            {"id": "greenhouse", "label": "Greenhouse", "count": 2}
                        ],
                        "website": {"url": "https://acme.com/"},
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
            },
        )
    )
    greenhouse_route = respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*")
    ).mock(return_value=httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}))

    source_metrics = await sync_sources(
        settings=settings, store=store, source_key=source_key, page_size=1
    )
    probe_summary = await probe_routes(
        settings=settings,
        store=store,
        source_key=source_key,
        provider_id="greenhouse",
        apply=True,
    )

    assert source_metrics.boards == 1
    assert source_metrics.board_providers == 1
    assert source_route.call_count == 1
    assert (
        json.loads(source_route.calls[0].request.content)["query"]["parent"]
        == board_slug
    )
    assert greenhouse_route.call_count == 1
    assert probe_summary.matched_by_provider == {"greenhouse": 1}
    persisted = store.list_board_providers(
        source_key=source_key, provider_id="greenhouse"
    )[0]
    assert persisted.token == "acme"
    assert persisted.board_url == "https://boards.greenhouse.io/acme"


def _seed_two_source_routes(store: OpenOppsStore) -> None:
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="source-b", url="source-b://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a-acme",
                source_key="source-a",
                remote_id="Acme",
                name="Acme",
            ),
            BoardRecord(
                key="source-b-beta",
                source_key="source-b",
                remote_id="Beta",
                name="Beta",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="source-a:source-a-acme:greenhouse",
                source_key="source-a",
                board_key="source-a-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="source-b:source-b-beta:greenhouse",
                source_key="source-b",
                board_key="source-b-beta",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="beta",
            ),
        ]
    )


def test_source_selection_uses_canonical_resolver_for_scoped_and_unscoped_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    synced_at = utc_now()
    catalog = SourceRecord(
        key="portfolio",
        url="https://consider.com/boards/co/portfolio",
        provider_id="consider",
        raw_metadata={"board": "new-token"},
    )
    store.upsert_source(
        catalog.model_copy(
            update={
                "raw_metadata": {"board": "old-token", "lastPage": {"page": 2}},
                "version": {"cursor": "next"},
                "synced_at": synced_at,
            }
        )
    )
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", {catalog.key: catalog})

    unscoped = ingest_module._select_sources(store, None)
    scoped = ingest_module._select_sources(store, catalog.key)

    for selected in (unscoped, scoped):
        assert len(selected) == 1
        assert selected[0].raw_metadata == {
            "board": "new-token",
            "lastPage": {"page": 2},
        }
        assert selected[0].version == {"cursor": "next"}
        assert selected[0].synced_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403])
@respx.mock
async def test_sync_jobs_retains_route_and_open_jobs_for_non_absence_http_errors(
    tmp_path: Path, status_code: int
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="greenhouse")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(status_code, json={"message": "not route proof"})
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    stored_route = store.list_board_providers(provider_id="greenhouse")[0]
    assert stored_route.support_level == ProviderSupport.JOBS
    assert stored_route.last_status == "route_ready"
    assert [job.id for job in store.list_jobs()] == ["acme:greenhouse:1"]
    assert metrics.provider_errors == {"greenhouse": 1}


@pytest.mark.asyncio
async def test_sync_jobs_does_not_close_missing_for_nonauthoritative_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from openopps.providers.base import JobFetchResult

    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="fake")

    class PartialProvider:
        async def fetch_jobs(self, *_args: object):
            return JobFetchResult(jobs=[], authoritative=False)

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: PartialProvider(),
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="fake")

    assert [job.id for job in store.list_jobs()] == ["acme:fake:1"]
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 0
    assert metrics.provider_error_details == {"fake": {"non_authoritative_snapshot": 1}}
    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        run = conn.execute(
            """
            SELECT status, success, authoritative, error_kind, committed_batch_count
            FROM job_sync_runs
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
    assert run == ("failed", 0, 0, "non_authoritative_snapshot", 0)


@pytest.mark.asyncio
async def test_sync_jobs_does_not_persist_partial_nonauthoritative_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from openopps.providers.base import JobFetchResult

    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="fake")
    partial = JobRecord(
        id="acme:fake:partial",
        board_key="acme",
        provider_id="fake",
        remote_id="partial",
        title="Partial",
    )

    class PartialProvider:
        async def fetch_jobs(self, *_args: object):
            return JobFetchResult(jobs=[partial], authoritative=False)

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: PartialProvider(),
    )

    reports: list[str] = []
    metrics = await sync_jobs(
        settings=settings,
        store=store,
        provider_id="fake",
        report=lambda update: reports.append(update.message),
    )

    assert [job.id for job in store.list_jobs()] == ["acme:fake:1"]
    assert metrics.jobs == 0
    assert metrics.jobs_persisted == 0
    assert metrics.jobs_deduped == 0
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 0
    assert metrics.provider_error_details == {"fake": {"non_authoritative_snapshot": 1}}
    assert any("rejected: non-authoritative snapshot" in message for message in reports)
    assert not any("jobs synced via fake" in message for message in reports)
    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        run = conn.execute(
            """
            SELECT status, job_count, committed_batch_count, authoritative
            FROM job_sync_runs
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
    assert run == ("failed", 0, 0, 0)


@pytest.mark.asyncio
async def test_sync_jobs_rejects_legacy_untyped_provider_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="fake")
    untyped = JobRecord(
        id="acme:fake:untyped",
        board_key="acme",
        provider_id="fake",
        remote_id="untyped",
        title="Untyped",
    )

    class LegacyProvider:
        async def fetch_jobs(self, *_args: object):
            return [untyped]

    monkeypatch.setattr(
        ingest_module,
        "build_job_provider",
        lambda _provider_id, _settings: LegacyProvider(),
    )
    reports: list[str] = []

    metrics = await sync_jobs(
        settings=settings,
        store=store,
        provider_id="fake",
        report=lambda update: reports.append(update.message),
    )

    assert [job.id for job in store.list_jobs()] == ["acme:fake:1"]
    assert metrics.jobs == 0
    assert metrics.jobs_persisted == 0
    assert metrics.job_sync_attempts == 1
    assert metrics.job_sync_runs == 0
    assert metrics.provider_error_details == {"fake": {"invalid_provider_result": 1}}
    assert any("rejected: invalid provider result" in message for message in reports)
    assert not any("jobs synced via fake" in message for message in reports)


@pytest.mark.asyncio
@respx.mock
async def test_terminal_listing_absence_closes_each_distinct_duplicate_board_once(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="source-b", url="source-b://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a:acme",
                source_key="source-a",
                remote_id="acme-a",
                name="Acme A",
            ),
            BoardRecord(
                key="source-b:acme",
                source_key="source-b",
                remote_id="acme-b",
                name="Acme B",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=f"{source}:{board_key}:greenhouse",
                source_key=source,
                board_key=board_key,
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="shared-token",
                last_status="route_ready",
            )
            for source, board_key in (
                ("source-a", "source-a:acme"),
                ("source-b", "source-b:acme"),
            )
        ]
    )
    for board_key in ("source-a:acme", "source-b:acme"):
        store.sync_jobs_for_route(
            board_key,
            "greenhouse",
            [
                JobRecord(
                    id=f"{board_key}:greenhouse:existing",
                    board_key=board_key,
                    provider_id="greenhouse",
                    remote_id="existing",
                    title="Existing",
                )
            ],
        )
    respx.get("https://boards-api.greenhouse.io/v1/boards/shared-token/jobs").mock(
        return_value=httpx.Response(404, json={"message": "board not found"})
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert metrics.job_sync_runs == 2
    assert metrics.job_sync_attempts == 2
    assert metrics.duplicate_routes_skipped == 1
    assert {route.support_level for route in store.list_board_providers()} == {
        ProviderSupport.DETECT
    }
    assert {job.status for job in store.list_jobs(status="closed")} == {"closed"}
    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        terminal_runs = conn.execute(
            """
            SELECT board_key, COUNT(*), MIN(status), MIN(success),
                   MIN(authoritative), MIN(closed_count)
            FROM job_sync_runs
            WHERE provider_id = 'greenhouse'
              AND started_at = (
                  SELECT MAX(started_at)
                  FROM job_sync_runs AS latest
                  WHERE latest.board_key = job_sync_runs.board_key
                    AND latest.provider_id = job_sync_runs.provider_id
              )
            GROUP BY board_key
            ORDER BY board_key
            """
        ).fetchall()
    assert terminal_runs == [
        ("source-a:acme", 1, "succeeded", 1, 1, 1),
        ("source-b:acme", 1, "succeeded", 1, 1, 1),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_does_not_deactivate_route_for_detail_404(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="rippling")
    respx.get(
        "https://ats.rippling.com/api/v2/board/acme/jobs",
        params={"page": 0, "pageSize": 100},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"totalPages": 1, "totalItems": 1, "items": [{"id": "new"}]},
        )
    )
    respx.get("https://ats.rippling.com/api/v2/board/acme/jobs/new").mock(
        return_value=httpx.Response(404, json={"message": "detail disappeared"})
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="rippling")

    stored_route = store.list_board_providers(provider_id="rippling")[0]
    assert stored_route.support_level == ProviderSupport.JOBS
    assert stored_route.last_status == "route_ready"
    assert [job.id for job in store.list_jobs()] == ["acme:rippling:1"]
    assert metrics.provider_errors == {"rippling": 1}


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_does_not_deactivate_route_for_continuation_404(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    store = OpenOppsStore(settings)
    _seed_existing_job_route(store, provider_id="rippling")
    respx.get(
        "https://ats.rippling.com/api/v2/board/acme/jobs",
        params={"page": 0, "pageSize": 100},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"totalPages": 2, "totalItems": 2, "items": [{"id": "new"}]},
        )
    )
    respx.get(
        "https://ats.rippling.com/api/v2/board/acme/jobs",
        params={"page": 1, "pageSize": 100},
    ).mock(return_value=httpx.Response(404, json={"message": "page disappeared"}))

    metrics = await sync_jobs(settings=settings, store=store, provider_id="rippling")

    stored_route = store.list_board_providers(provider_id="rippling")[0]
    assert stored_route.support_level == ProviderSupport.JOBS
    assert stored_route.last_status == "route_ready"
    assert [job.id for job in store.list_jobs()] == ["acme:rippling:1"]
    assert metrics.provider_errors == {"rippling": 1}


def test_wp_job_manager_detail_404_is_not_listing_absence() -> None:
    request = httpx.Request(
        "GET", "https://jobs.example.com/wp-json/wp/v2/job-listings/123"
    )
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("detail missing", request=request, response=response)

    assert ingest_module._route_failure_disposition("wpjobmanager", error) is None


def test_http_failure_text_redacts_query_credentials_and_userinfo() -> None:
    request = httpx.Request(
        "POST",
        "https://user:password@example.test/query?x-algolia-api-key=plaintext&tag=jobs",
    )
    response = httpx.Response(403, request=request)
    error = httpx.HTTPStatusError(
        "request rejected",
        request=request,
        response=response,
    )

    rendered = ingest_module._format_exception(error)

    assert rendered == "HTTPStatusError: HTTP 403"
    assert "plaintext" not in rendered
    assert "password" not in rendered
    assert "/query" not in rendered
    assert "jobs" not in rendered


@pytest.mark.asyncio
async def test_sync_sources_only_refreshes_freshness_after_normal_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    catalog = SourceRecord(key="source-a", url="source-a://source", provider_id="fake")
    stale_at = utc_now() - timedelta(hours=2)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        source_freshness_seconds=3600,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(catalog.model_copy(update={"synced_at": stale_at}))
    calls = 0

    class YieldThenFailAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            nonlocal calls
            calls += 1
            yield [], [], {"version": {"pageSize": page_size, "page": 1}}
            raise RuntimeError("failed after yielding a partial snapshot")

    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", {catalog.key: catalog})
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: YieldThenFailAdapter(),
    )

    await sync_sources(settings=settings, store=store, page_size=10)
    after_first = store.get_source(catalog.key)
    await sync_sources(settings=settings, store=store, page_size=10)

    assert after_first is not None
    assert after_first.synced_at == stale_at
    assert calls == 2


def _seed_existing_job_route(store: OpenOppsStore, *, provider_id: str) -> None:
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=f"manual:acme:{provider_id}",
                source_key="manual",
                board_key="acme",
                provider_id=provider_id,
                support_level=ProviderSupport.JOBS,
                token="acme",
                last_status="route_ready",
            )
        ]
    )
    store.sync_jobs_for_route(
        "acme",
        provider_id,
        [
            JobRecord(
                id=f"acme:{provider_id}:1",
                board_key="acme",
                provider_id=provider_id,
                remote_id="1",
                title="Existing",
            )
        ],
    )


def _sha(payload: object) -> str:
    from hashlib import sha256

    from openopps.discovery.canonical import canonical_json_bytes

    return sha256(canonical_json_bytes(payload)).hexdigest()


def _b899_pin(source_ids: tuple[str, ...], *, denied: frozenset[str] = frozenset()):
    from openopps.ingest import ApprovedIngestionPin

    return ApprovedIngestionPin(
        frozen_source_ids=source_ids,
        denied_source_keys=denied,
        envelope_id=_sha({"keys": list(source_ids)}),
        catalog_content_digest=_sha("b899-catalog"),
        catalog_tree_digest=_sha("b899-catalog"),
        selector_digest=_sha(list(source_ids)),
        policy_digest=_sha("b899-policy"),
        promotion_digest=_sha("b899-promotion"),
        checkout_sha="b" * 40,
    )


def _job_capable_provider(
    *,
    source_key: str,
    board_key: str,
    provider_id: str,
    token: str | None,
) -> BoardProviderRecord:
    return BoardProviderRecord(
        id=f"{source_key}:{board_key}:{provider_id}",
        source_key=source_key,
        board_key=board_key,
        provider_id=provider_id,
        support_level=ProviderSupport.JOBS,
        token=token,
        last_status="route_ready" if token else None,
    )


def _board(source_key: str, slug: str, name: str) -> BoardRecord:
    return BoardRecord(
        key=f"{source_key}:{slug}",
        source_key=source_key,
        remote_id=slug,
        name=name,
        domain=f"{slug}.example.test",
    )


class _PinCatalogAdapter:
    def __init__(
        self, pages: dict[str, tuple[list[BoardRecord], list[BoardProviderRecord]]]
    ):
        self._pages = pages
        self.fetched: list[str] = []

    async def iter_boards(self, _client, source, *, page_size: int):
        self.fetched.append(source.key)
        if source.provider_id == "getro":
            raise AssertionError("blocked getro source must not start network work")
        boards, providers = self._pages[source.key]
        yield boards, providers, {"version": {"pageSize": page_size}}


def _mock_lever_jobs(token: str, jobs: list[dict[str, object]]) -> Any:
    return respx.get(f"https://api.lever.co/v0/postings/{token}").mock(
        return_value=httpx.Response(200, json=jobs)
    )


def _assert_redacted_metrics(payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, default=str)
    assert "http://" not in rendered
    assert "https://" not in rendered
    assert "unaccounted" not in rendered
    assert "example.test" not in rendered


@pytest.mark.asyncio
@respx.mock
async def test_pinned_ingest_conserves_every_job_capable_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    catalog = {
        "pin-greenhouse": SourceRecord(
            key="pin-greenhouse",
            url="pin-greenhouse://source",
            provider_id="greenhouse_source",
        ),
        "pin-lever": SourceRecord(
            key="pin-lever",
            url="pin-lever://source",
            provider_id="lever_source",
        ),
        "pin-dup": SourceRecord(
            key="pin-dup",
            url="pin-dup://source",
            provider_id="greenhouse_source",
        ),
        "pin-missing": SourceRecord(
            key="pin-missing",
            url="pin-missing://source",
            provider_id="greenhouse_source",
        ),
        "pin-getro-blocked": SourceRecord(
            key="pin-getro-blocked",
            url="pin-getro-blocked://source",
            provider_id="getro",
        ),
    }
    stored_only = SourceRecord(
        key="local-custom-b899",
        url="https://custom.example.test/jobs",
        provider_id="manual",
    )
    pages = {
        "pin-greenhouse": (
            [
                _board("pin-greenhouse", "acme", "Acme"),
                _board("pin-greenhouse", "beta", "Beta"),
            ],
            [
                _job_capable_provider(
                    source_key="pin-greenhouse",
                    board_key="pin-greenhouse:acme",
                    provider_id="greenhouse",
                    token="acme",
                ),
                _job_capable_provider(
                    source_key="pin-greenhouse",
                    board_key="pin-greenhouse:beta",
                    provider_id="greenhouse",
                    token="beta",
                ),
            ],
        ),
        "pin-lever": (
            [_board("pin-lever", "leverco", "Lever Co")],
            [
                _job_capable_provider(
                    source_key="pin-lever",
                    board_key="pin-lever:leverco",
                    provider_id="lever",
                    token="leverco",
                )
            ],
        ),
        "pin-dup": (
            [_board("pin-dup", "acme", "Acme Duplicate")],
            [
                _job_capable_provider(
                    source_key="pin-dup",
                    board_key="pin-dup:acme",
                    provider_id="greenhouse",
                    token="acme",
                )
            ],
        ),
        "pin-missing": (
            [_board("pin-missing", "ghost", "Ghost")],
            [
                _job_capable_provider(
                    source_key="pin-missing",
                    board_key="pin-missing:ghost",
                    provider_id="greenhouse",
                    token=None,
                )
            ],
        ),
    }
    adapter = _PinCatalogAdapter(pages)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        board_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(stored_only)
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", catalog)
    monkeypatch.setattr(
        ingest_module, "all_board_sources", lambda: list(catalog.values())
    )

    def build_adapter(provider_id: str, _settings):
        if provider_id == "getro":
            raise AssertionError("blocked getro adapter must not be built")
        return adapter

    monkeypatch.setattr(ingest_module, "build_source_adapter", build_adapter)
    _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 11,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/11",
            }
        ],
    )
    _mock_greenhouse_jobs(
        "beta",
        [
            {
                "id": 12,
                "title": "Designer",
                "absolute_url": "https://boards.greenhouse.io/beta/jobs/12",
            }
        ],
    )
    _mock_lever_jobs("leverco", [])

    pin = _b899_pin(tuple(catalog), denied=frozenset({"pin-getro-blocked"}))
    metrics = await ingest_module.sync_all(
        settings=settings,
        store=store,
        pin=pin,
        catalog=catalog,
    )
    payload = metrics.as_dict()
    sources = payload["conservation"]["sources"]
    routes = payload["conservation"]["routes"]

    assert payload["name"] == "sync"
    assert payload["attestation"] == "degraded"
    assert payload["degradedClass"] in {"partial", "policy_blocked", "missing_metadata"}
    assert payload["attestation"] != payload["degradedClass"]
    assert sources["planned"] == 5
    assert sources["succeeded"] == 4
    assert sources["policyBlocked"] == 1
    assert sources["planned"] == sum(
        sources[name]
        for name in (
            "succeeded",
            "failed",
            "timedOut",
            "freshSkipped",
            "policyBlocked",
            "rateLimited",
            "cancelled",
            "unstarted",
        )
    )
    assert routes["planned"] == 5
    assert routes["succeeded"] == 3
    assert routes["duplicateSkipped"] == 1
    assert routes["missingMetadata"] == 1
    assert routes["planned"] == sum(
        routes[name]
        for name in (
            "succeeded",
            "failed",
            "timedOut",
            "freshSkipped",
            "deferred",
            "duplicateSkipped",
            "missingMetadata",
            "policyBlocked",
            "rateLimited",
            "cancelled",
            "unstarted",
        )
    )
    assert adapter.fetched == [
        "pin-greenhouse",
        "pin-lever",
        "pin-dup",
        "pin-missing",
    ]
    assert "pin-getro-blocked" not in adapter.fetched
    assert store.get_source("local-custom-b899") is not None
    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        runs = conn.execute(
            "SELECT board_key, provider_id, status FROM job_sync_runs ORDER BY board_key"
        ).fetchall()
    assert {(row[0], row[1]) for row in runs} == {
        ("pin-greenhouse:acme", "greenhouse"),
        ("pin-greenhouse:beta", "greenhouse"),
        ("pin-lever:leverco", "lever"),
    }
    assert all(row[2] == "succeeded" for row in runs)
    _assert_redacted_metrics(payload)


@pytest.mark.asyncio
@respx.mock
async def test_pinned_ingest_is_complete_when_every_pin_route_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    catalog = {
        "pin-greenhouse": SourceRecord(
            key="pin-greenhouse",
            url="pin-greenhouse://source",
            provider_id="greenhouse_source",
        ),
        "pin-lever": SourceRecord(
            key="pin-lever",
            url="pin-lever://source",
            provider_id="lever_source",
        ),
    }
    pages = {
        "pin-greenhouse": (
            [_board("pin-greenhouse", "acme", "Acme")],
            [
                _job_capable_provider(
                    source_key="pin-greenhouse",
                    board_key="pin-greenhouse:acme",
                    provider_id="greenhouse",
                    token="acme",
                )
            ],
        ),
        "pin-lever": (
            [_board("pin-lever", "leverco", "Lever Co")],
            [
                _job_capable_provider(
                    source_key="pin-lever",
                    board_key="pin-lever:leverco",
                    provider_id="lever",
                    token="leverco",
                )
            ],
        ),
    }
    adapter = _PinCatalogAdapter(pages)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        board_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", catalog)
    monkeypatch.setattr(
        ingest_module, "all_board_sources", lambda: list(catalog.values())
    )
    monkeypatch.setattr(
        ingest_module,
        "build_source_adapter",
        lambda _provider_id, _settings: adapter,
    )
    _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )
    _mock_lever_jobs("leverco", [])

    metrics = await ingest_module.sync_all(
        settings=settings,
        store=store,
        pin=_b899_pin(tuple(catalog)),
        catalog=catalog,
    )
    payload = metrics.as_dict()
    assert payload["attestation"] == "complete"
    assert payload["degradedClass"] is None
    assert payload["conservation"]["sources"]["planned"] == 2
    assert payload["conservation"]["sources"]["succeeded"] == 2
    assert payload["conservation"]["sources"]["complete"] is True
    assert payload["conservation"]["routes"]["planned"] == 2
    assert payload["conservation"]["routes"]["succeeded"] == 2
    assert payload["conservation"]["routes"]["complete"] is True
    _assert_redacted_metrics(payload)
