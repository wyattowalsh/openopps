from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

import openopps.ingest as ingest_module
from openopps.ingest import sync_jobs, sync_sources
from openopps.metrics import SyncMetrics
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.base import JobFetchResult
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


SOURCE_JSON_TERMINALS = (
    "succeeded",
    "failed",
    "timedOut",
    "freshSkipped",
    "policyBlocked",
    "rateLimited",
    "cancelled",
    "unstarted",
)
ROUTE_JSON_TERMINALS = SOURCE_JSON_TERMINALS + (
    "deferred",
    "duplicateSkipped",
    "missingMetadata",
)


def _assert_conserved(payload: dict[str, object], terminals: tuple[str, ...]) -> None:
    planned = int(payload["planned"])
    assert planned == sum(int(payload[name]) for name in terminals)
    rendered = json.dumps(payload)
    assert "https://" not in rendered
    assert "http://" not in rendered
    assert "unaccounted" not in rendered
    assert "://source" not in rendered


def _patch_catalog(
    monkeypatch: pytest.MonkeyPatch, sources: dict[str, SourceRecord]
) -> None:
    monkeypatch.setattr(ingest_module, "BOARD_SOURCE_CATALOG", sources)
    monkeypatch.setattr(
        ingest_module,
        "all_board_sources",
        lambda: list(sources.values()),
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/source")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("bounded", request=request, response=response)


def _route(
    board_key: str,
    provider_id: str,
    *,
    token: str | None = "token",
) -> BoardProviderRecord:
    return BoardProviderRecord(
        id=f"manual:{board_key}:{provider_id}",
        source_key="manual",
        board_key=board_key,
        provider_id=provider_id,
        support_level=ProviderSupport.JOBS,
        token=token,
        last_status="route_ready",
    )


@pytest.mark.asyncio
async def test_sync_sources_conserves_mixed_terminals_with_mocked_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class OkAdapter:
        async def iter_boards(self, _client, source, *, page_size: int):
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

    class FailAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            raise RuntimeError("adapter failed")
            yield ([], [], {"version": {"pageSize": page_size}})

    class SlowAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            await asyncio.sleep(0.05)
            yield [], [], {"version": {"pageSize": page_size}}

    class LimitedAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            raise _http_status_error(429)
            yield ([], [], {"version": {"pageSize": page_size}})

    def build_adapter(provider_id: str, _settings: OpenOppsSettings):
        if provider_id == "ok":
            return OkAdapter()
        if provider_id == "fail":
            return FailAdapter()
        if provider_id == "slow":
            return SlowAdapter()
        if provider_id == "limited":
            return LimitedAdapter()
        return None

    now = utc_now()
    sources = {
        "ok": SourceRecord(key="ok", url="ok://source", provider_id="ok"),
        "fail": SourceRecord(key="fail", url="fail://source", provider_id="fail"),
        "slow": SourceRecord(key="slow", url="slow://source", provider_id="slow"),
        "fresh": SourceRecord(
            key="fresh",
            url="fresh://source",
            provider_id="ok",
            synced_at=now,
        ),
        "blocked": SourceRecord(
            key="blocked", url="blocked://source", provider_id="ok"
        ),
        "limited": SourceRecord(
            key="limited", url="limited://source", provider_id="limited"
        ),
    }
    _patch_catalog(monkeypatch, sources)
    monkeypatch.setattr(ingest_module, "build_source_adapter", build_adapter)

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=4,
        source_timeout_seconds=0.01,
        source_freshness_seconds=3600,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    for source in sources.values():
        store.upsert_source(source)

    metrics = await sync_sources(
        settings=settings,
        store=store,
        page_size=10,
        denied_source_keys=frozenset({"blocked"}),
    )
    conservation = metrics.as_dict()["conservation"]["sources"]

    _assert_conserved(conservation, SOURCE_JSON_TERMINALS)
    assert conservation["planned"] == 6
    assert conservation["succeeded"] == 1
    assert conservation["failed"] == 1
    assert conservation["timedOut"] == 1
    assert conservation["freshSkipped"] == 1
    assert conservation["policyBlocked"] == 1
    assert conservation["rateLimited"] == 1
    assert conservation["cancelled"] == 0
    assert conservation["unstarted"] == 0
    assert conservation["complete"] is False
    assert conservation["terminal"] is True


@pytest.mark.asyncio
async def test_sync_sources_conserves_cancelled_and_unstarted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = asyncio.Event()

    class HangAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            started.set()
            await asyncio.Event().wait()
            yield [], [], {"version": {"pageSize": page_size}}

    class QueuedAdapter:
        async def iter_boards(self, _client, _source, *, page_size: int):
            yield [], [], {"version": {"pageSize": page_size}}

    def build_adapter(provider_id: str, _settings: OpenOppsSettings):
        if provider_id == "hang":
            return HangAdapter()
        return QueuedAdapter()

    sources = {
        "hang": SourceRecord(key="hang", url="hang://source", provider_id="hang"),
        "queued": SourceRecord(
            key="queued", url="queued://source", provider_id="queued"
        ),
    }
    _patch_catalog(monkeypatch, sources)
    monkeypatch.setattr(ingest_module, "build_source_adapter", build_adapter)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        source_timeout_seconds=30,
        source_freshness_seconds=0,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    metrics = SyncMetrics(name="sources.sync")
    task = asyncio.create_task(
        sync_sources(settings=settings, store=store, page_size=10, metrics=metrics)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    conservation = metrics.source_conservation
    assert conservation is not None
    _assert_conserved(conservation, SOURCE_JSON_TERMINALS)
    assert conservation["planned"] == 2
    assert conservation["cancelled"] == 1
    assert conservation["unstarted"] == 1
    assert conservation["complete"] is False


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_conserves_prededup_route_terminals_with_mocked_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        board_concurrency=8,
        job_route_timeout_seconds=0.2,
        job_route_freshness_seconds=3600,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(key=key, source_key="manual", remote_id=key, name=key)
            for key in (
                "ok",
                "fail",
                "slow",
                "fresh",
                "zzz",
                "dup",
                "gh-ok",
                "missing",
                "blocked",
                "limited",
            )
        ]
    )
    store.upsert_board_providers(
        [
            _route("ok", "fake", token="ok"),
            _route("fail", "fake", token="fail"),
            _route("slow", "fake", token="slow"),
            _route("fresh", "fake", token="fresh"),
            _route("zzz", "zzz", token="zzz"),
            _route("dup", "greenhouse", token="shared"),
            _route("gh-ok", "greenhouse", token="shared"),
            _route("missing", "greenhouse", token=None),
            _route("blocked", "missing-provider", token="blocked"),
            _route("limited", "fake", token="limited"),
        ]
    )
    store.sync_jobs_for_route(
        "fresh",
        "fake",
        [
            JobRecord(
                id="fresh:fake:1",
                board_key="fresh",
                provider_id="fake",
                remote_id="1",
                title="Existing",
            )
        ],
    )

    respx.get("https://boards-api.greenhouse.io/v1/boards/shared/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    respx.get("https://boards-api.greenhouse.io/v1/boards/limited/jobs").mock(
        return_value=httpx.Response(429, json={"error": "limited"})
    )

    class FakeProvider:
        async def fetch_jobs(self, _client, board, _route):
            if board.key == "fail":
                raise RuntimeError("route failed")
            if board.key == "slow":
                await asyncio.sleep(0.6)
                return JobFetchResult(jobs=[], authoritative=True)
            if board.key == "limited":
                request = httpx.Request("GET", "https://example.test/jobs")
                response = httpx.Response(429, request=request)
                raise httpx.HTTPStatusError(
                    "bounded", request=request, response=response
                )
            return JobFetchResult(jobs=[], authoritative=True)

    real_build = ingest_module.build_job_provider

    def build_job_provider(provider_id: str, provider_settings: OpenOppsSettings):
        if provider_id in {"fake", "greenhouse"}:
            return FakeProvider()
        return real_build(provider_id, provider_settings)

    monkeypatch.setattr(ingest_module, "build_job_provider", build_job_provider)

    # Unique ready stale routes: ok, fail, slow, zzz, one shared greenhouse,
    # limited, blocked. Fresh is skipped. Limit 6 defers zzz (sorts last).
    metrics = await sync_jobs(settings=settings, store=store, limit=6)
    conservation = metrics.as_dict()["conservation"]["routes"]
    _assert_conserved(conservation, ROUTE_JSON_TERMINALS)
    assert conservation["planned"] == 10
    assert conservation["succeeded"] == 2
    assert conservation["failed"] == 2  # explicit fail + missing provider
    assert conservation["timedOut"] == 1
    assert conservation["freshSkipped"] == 1
    assert conservation["deferred"] == 1
    assert conservation["duplicateSkipped"] == 1
    assert conservation["missingMetadata"] == 1
    assert conservation["rateLimited"] == 1
    assert conservation["complete"] is False
    assert conservation["terminal"] is True
    assert "https://boards-api.greenhouse.io" not in json.dumps(metrics.as_dict())


@pytest.mark.asyncio
async def test_sync_jobs_conserves_cancelled_and_unstarted_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = asyncio.Event()

    class HangProvider:
        async def fetch_jobs(self, *_args: object):
            started.set()
            await asyncio.Event().wait()
            return JobFetchResult(jobs=[], authoritative=True)

    class QuickProvider:
        async def fetch_jobs(self, *_args: object):
            return JobFetchResult(jobs=[], authoritative=True)

    def build_job_provider(provider_id: str, _settings: OpenOppsSettings):
        if provider_id == "hang":
            return HangProvider()
        return QuickProvider()

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        board_concurrency=1,
        job_route_timeout_seconds=30,
        job_route_freshness_seconds=0,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(key="hang", source_key="manual", remote_id="hang", name="Hang"),
            BoardRecord(
                key="queued", source_key="manual", remote_id="queued", name="Queued"
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:hang:hang",
                source_key="manual",
                board_key="hang",
                provider_id="hang",
                support_level=ProviderSupport.JOBS,
                token="hang",
                last_status="route_ready",
            ),
            BoardProviderRecord(
                id="manual:queued:queued",
                source_key="manual",
                board_key="queued",
                provider_id="queued",
                support_level=ProviderSupport.JOBS,
                token="queued",
                last_status="route_ready",
            ),
        ]
    )
    monkeypatch.setattr(ingest_module, "build_job_provider", build_job_provider)
    metrics = SyncMetrics(name="jobs.sync")
    task = asyncio.create_task(
        sync_jobs(settings=settings, store=store, metrics=metrics)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    conservation = metrics.route_conservation
    assert conservation is not None
    _assert_conserved(conservation, ROUTE_JSON_TERMINALS)
    assert conservation["planned"] == 2
    assert conservation["cancelled"] == 1
    assert conservation["unstarted"] == 1
