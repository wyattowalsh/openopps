import asyncio
import json
import re
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
    assert metrics.job_sync_runs == 0
    assert metrics.jobs == 0


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
