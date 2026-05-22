import asyncio
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest
import respx

from openopps.cache import HttpCache
from openopps.http import build_async_client, retrying_json_request
from openopps.settings import OpenOppsSettings


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_retries_transient_status():
    settings = OpenOppsSettings(retry_attempts=2, cache_enabled=False)
    route = respx.get("https://api.example.test/data").mock(
        side_effect=[
            httpx.Response(500, json={"error": "temporary"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    async with build_async_client(settings) as client:
        data = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/data"
        )

    assert data == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_does_not_retry_not_found():
    settings = OpenOppsSettings(retry_attempts=2, cache_enabled=False)
    route = respx.get("https://api.example.test/missing").mock(
        return_value=httpx.Response(404, json={"error": "missing"})
    )

    async with build_async_client(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await retrying_json_request(settings)(
                client, "GET", "https://api.example.test/missing"
            )

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_rejects_scalar_json():
    settings = OpenOppsSettings(retry_attempts=1, cache_enabled=False)
    respx.get("https://api.example.test/scalar").mock(
        return_value=httpx.Response(200, json="bad")
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError):
            await retrying_json_request(settings)(
                client, "GET", "https://api.example.test/scalar"
            )


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_caches_successful_json(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    route = respx.get("https://api.example.test/cacheable").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with build_async_client(settings) as client:
        first = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/cacheable"
        )
        second = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/cacheable"
        )

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert route.call_count == 1
    assert HttpCache(settings.cache_path).status()["total"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_coalesces_duplicate_inflight_cache_misses(
    tmp_path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )

    async def response(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"ok": True})

    route = respx.get("https://api.example.test/inflight").mock(side_effect=response)

    async with build_async_client(settings) as client:
        request_json = retrying_json_request(settings)
        first, second = await asyncio.gather(
            request_json(client, "GET", "https://api.example.test/inflight"),
            request_json(client, "GET", "https://api.example.test/inflight"),
        )

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert route.call_count == 1
    assert HttpCache(settings.cache_path).status()["total"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_refresh_bypasses_cache(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    route = respx.get("https://api.example.test/refresh").mock(
        side_effect=[
            httpx.Response(200, json={"value": 1}),
            httpx.Response(200, json={"value": 2}),
        ]
    )

    async with build_async_client(settings) as client:
        first = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/refresh"
        )
        second = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/refresh", cache_refresh=True
        )

    assert first == {"value": 1}
    assert second == {"value": 2}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_returns_stale_on_retryable_error(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_stale_on_error=True,
    )
    cache = HttpCache(settings.cache_path)
    cache.put_json(
        "GET",
        "https://api.example.test/stale",
        {"cached": True},
        ttl_seconds=1,
        stale_on_error=True,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    route = respx.get("https://api.example.test/stale").mock(
        return_value=httpx.Response(500, json={"error": "temporary"})
    )

    async with build_async_client(settings) as client:
        data = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/stale"
        )

    assert data == {"cached": True}
    assert route.call_count == 1
    assert HttpCache(settings.cache_path).status()["staleOnErrorEligible"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_does_not_return_ineligible_stale_record(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_stale_on_error=True,
    )
    cache = HttpCache(settings.cache_path)
    cache.put_json(
        "GET",
        "https://api.example.test/ineligible-stale",
        {"cached": True},
        ttl_seconds=1,
        stale_on_error=False,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    respx.get("https://api.example.test/ineligible-stale").mock(
        return_value=httpx.Response(500, json={"error": "temporary"})
    )

    async with build_async_client(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await retrying_json_request(settings)(
                client, "GET", "https://api.example.test/ineligible-stale"
            )


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_refresh_does_not_return_stale_on_error(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_stale_on_error=True,
    )
    cache = HttpCache(settings.cache_path)
    cache.put_json(
        "GET",
        "https://api.example.test/refresh-stale",
        {"cached": True},
        ttl_seconds=1,
        stale_on_error=True,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    respx.get("https://api.example.test/refresh-stale").mock(
        return_value=httpx.Response(500, json={"error": "temporary"})
    )

    async with build_async_client(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await retrying_json_request(settings)(
                client,
                "GET",
                "https://api.example.test/refresh-stale",
                cache_refresh=True,
            )


def test_http_cache_migrates_existing_schema_without_stale_on_error(tmp_path):
    cache_path = tmp_path / "openopps.cache.db"
    with sqlite3.connect(cache_path) as conn:
        conn.execute(
            """
            create table http_cache (
                key text primary key,
                namespace text not null,
                method text not null,
                url text not null,
                request_identity text not null,
                status_code integer not null,
                response_headers text not null,
                etag text,
                last_modified text,
                content_hash text not null,
                fetched_at text not null,
                expires_at text not null,
                request_duration_ms integer,
                payload text not null
            )
            """
        )

    status = HttpCache(cache_path).status()

    assert status["total"] == 0
    with sqlite3.connect(cache_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(http_cache)")}
    assert "stale_on_error" in columns


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_revalidates_with_etag(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
    )
    cache = HttpCache(settings.cache_path)
    cache.put_json(
        "GET",
        "https://api.example.test/revalidate",
        {"cached": True},
        response_headers={"etag": '"abc"'},
        ttl_seconds=1,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    route = respx.get("https://api.example.test/revalidate").mock(
        return_value=httpx.Response(304)
    )

    async with build_async_client(settings) as client:
        data = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/revalidate"
        )

    assert data == {"cached": True}
    assert route.call_count == 1
    assert route.calls[0].request.headers["if-none-match"] == '"abc"'
