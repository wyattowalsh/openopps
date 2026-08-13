import asyncio
import importlib
from datetime import datetime, timezone
import socket
import sqlite3

import httpx
import pytest
import respx

from openopps.cache import HttpCache
from openopps.http import (
    build_async_client,
    request_with_public_redirect_validation,
    retrying_json_request,
    retrying_json_response,
    retrying_text_request,
)
from openopps.metrics import SyncMetrics, bind_http_retry_metrics, reset_http_retry_metrics
from openopps.settings import OpenOppsSettings


def _cache_for(settings: OpenOppsSettings) -> HttpCache:
    assert settings.sqlite_path is not None
    return HttpCache(settings.sqlite_path)


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
async def test_retrying_json_request_records_http_retries_for_bound_metrics():
    settings = OpenOppsSettings(retry_attempts=3, cache_enabled=False)
    route = respx.get("https://api.example.test/data").mock(
        side_effect=[
            httpx.Response(500, json={"error": "temporary"}),
            httpx.Response(500, json={"error": "temporary"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    metrics = SyncMetrics(name="http.test")
    token = bind_http_retry_metrics(metrics)

    try:
        async with build_async_client(settings) as client:
            data = await retrying_json_request(settings)(
                client, "GET", "https://api.example.test/data"
            )
    finally:
        reset_http_retry_metrics(token)

    assert data == {"ok": True}
    assert route.call_count == 3
    assert metrics.retries == 2


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_ignores_client_attribute_metrics():
    """Retry accounting is ContextVar-only; client attrs are not dual-written."""
    settings = OpenOppsSettings(retry_attempts=2, cache_enabled=False)
    route = respx.get("https://api.example.test/data").mock(
        side_effect=[
            httpx.Response(503, json={"error": "temporary"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    metrics = SyncMetrics(name="http.client")

    async with build_async_client(settings) as client:
        setattr(client, "_openopps_sync_metrics", metrics)
        data = await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/data"
        )

    assert data == {"ok": True}
    assert route.call_count == 2
    # Without bind_http_retry_metrics, retries stay at zero even if client attr is set.
    assert metrics.retries == 0


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_retries_rate_limit_reset_header():
    settings = OpenOppsSettings(retry_attempts=2, cache_enabled=False)
    route = respx.get("https://api.example.test/data").mock(
        side_effect=[
            httpx.Response(
                429,
                json={"error": "rate limit"},
                headers={"x-rate-limit-reset": "0"},
            ),
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
    assert _cache_for(settings).status()["total"] == 1
    assert not (tmp_path / "openopps.cache.db").exists()


@pytest.mark.asyncio
async def test_retrying_json_request_cache_separates_credentialed_requests(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        credential = {
            "Bearer credential-one-secret": "one",
            "Bearer credential-two-secret": "two",
        }[request.headers["authorization"]]
        return httpx.Response(200, json={"credential": credential}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        request_json = retrying_json_request(settings)
        first = await request_json(
            client,
            "GET",
            "https://api.example.test/credentialed",
            headers={"Authorization": "Bearer credential-one-secret"},
        )
        second = await request_json(
            client,
            "GET",
            "https://api.example.test/credentialed",
            headers={"Authorization": "Bearer credential-two-secret"},
        )
        cached_first = await request_json(
            client,
            "GET",
            "https://api.example.test/credentialed",
            headers={"Authorization": "Bearer credential-one-secret"},
        )

    assert first == {"credential": "one"}
    assert second == {"credential": "two"}
    assert cached_first == {"credential": "one"}
    assert len(requests) == 2
    assert _cache_for(settings).status()["total"] == 2
    assert settings.sqlite_path is not None
    with sqlite3.connect(settings.sqlite_path) as conn:
        stored_identity = "\n".join(
            row[0] for row in conn.execute("select request_identity from http_cache")
        )
    assert "credential-one-secret" not in stored_identity
    assert "credential-two-secret" not in stored_identity
    assert "sha256:" in stored_identity


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
    assert _cache_for(settings).status()["total"] == 1


@pytest.mark.asyncio
async def test_cancelling_one_coalesced_waiter_does_not_cancel_shared_request(
    tmp_path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json={"ok": True}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        request_json = retrying_json_request(settings)
        first = asyncio.create_task(
            request_json(client, "GET", "https://api.example.test/cancel")
        )
        second = asyncio.create_task(
            request_json(client, "GET", "https://api.example.test/cancel")
        )
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == {"ok": True}

    assert requests == 1
    assert _cache_for(settings).status()["total"] == 1


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
    cache = _cache_for(settings)
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
    assert _cache_for(settings).status()["staleOnErrorEligible"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_does_not_return_ineligible_stale_record(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_stale_on_error=True,
    )
    cache = _cache_for(settings)
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
    cache = _cache_for(settings)
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


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_revalidates_with_etag(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
    )
    cache = _cache_for(settings)
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


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_response_preserves_headers_from_cache(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    route = respx.get("https://api.example.test/with-total").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"x-wp-total": "7", "x-wp-totalpages": "2"},
        )
    )

    async with build_async_client(settings) as client:
        request_json = retrying_json_response(settings)
        first = await request_json(client, "GET", "https://api.example.test/with-total")
        second = await request_json(
            client, "GET", "https://api.example.test/with-total"
        )

    assert first.body == [{"id": 1}]
    assert first.headers["x-wp-total"] == "7"
    assert first.headers["x-wp-totalpages"] == "2"
    assert second.body == [{"id": 1}]
    assert second.headers["x-wp-total"] == "7"
    assert second.headers["x-wp-totalpages"] == "2"
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_response_does_not_persist_sensitive_response_headers(
    tmp_path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
    )
    respx.get("https://api.example.test/sensitive-header").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"set-cookie": "session=response-secret; Secure"},
        )
    )

    async with build_async_client(settings) as client:
        await retrying_json_request(settings)(
            client, "GET", "https://api.example.test/sensitive-header"
        )

    assert settings.sqlite_path is not None
    with sqlite3.connect(settings.sqlite_path) as conn:
        persisted = "\n".join(
            str(value)
            for row in conn.execute(
                "SELECT response_headers, payload FROM http_cache"
            )
            for value in row
        )
    assert "response-secret" not in persisted
    assert "set-cookie" not in persisted


@pytest.mark.asyncio
@respx.mock
async def test_retrying_text_request_retries_and_caches(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=2,
        cache_ttl_seconds=60,
    )
    route = respx.get("https://text.example.test/feed.txt").mock(
        side_effect=[
            httpx.Response(500, text="temporary"),
            httpx.Response(200, text="one,two\n"),
        ]
    )

    async with build_async_client(settings) as client:
        request_text = retrying_text_request(settings)
        first = await request_text(client, "GET", "https://text.example.test/feed.txt")
        second = await request_text(client, "GET", "https://text.example.test/feed.txt")

    assert first == "one,two\n"
    assert second == "one,two\n"
    assert route.call_count == 2
    assert _cache_for(settings).status()["byNamespace"] == {"http-text": 1}


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_rejects_private_dns_resolution(
    tmp_path, monkeypatch
):
    def private_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.5", 443),
            )
        ]

    monkeypatch.setattr("openopps.http.socket.getaddrinfo", private_dns)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_enabled=False,
    )
    route = respx.get("https://private.example.test/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="global-routable"):
            await retrying_json_request(settings)(
                client, "GET", "https://private.example.test/data"
            )

    assert route.call_count == 0


def test_safe_exception_message_does_not_persist_arbitrary_exception_text():
    from openopps.http import safe_exception_message

    rendered = safe_exception_message(
        RuntimeError("provider payload contained password=plaintext-secret")
    )

    assert rendered == "RuntimeError"
    assert "plaintext-secret" not in rendered


@pytest.mark.asyncio
@respx.mock
async def test_retrying_json_request_rejects_scoped_ipv6_dns(tmp_path, monkeypatch):
    def scoped_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("fe80::1%eth0", 443, 0, 2),
            )
        ]

    monkeypatch.setattr("openopps.http.socket.getaddrinfo", scoped_dns)
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_enabled=False,
    )
    route = respx.get("https://scoped.example.test/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="global-routable"):
            await retrying_json_request(settings)(
                client, "GET", "https://scoped.example.test/data"
            )

    assert route.call_count == 0


@pytest.mark.asyncio
async def test_retrying_json_request_rejects_ip_literal_with_plain_client():
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True}, request=request)

    settings = OpenOppsSettings(retry_attempts=1, cache_enabled=False)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="IP literal"):
            await retrying_json_request(settings)(
                client,
                "GET",
                "https://127.0.0.1/private",
            )

    assert not called


@pytest.mark.asyncio
async def test_retrying_json_request_strips_sensitive_headers_on_cross_origin_redirect():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "start.example.test":
            return httpx.Response(
                302,
                headers={"location": "https://end.example.test/data"},
                request=request,
            )
        return httpx.Response(200, json={"ok": True}, request=request)

    settings = OpenOppsSettings(retry_attempts=1, cache_enabled=False)
    headers = {
        "Authorization": "Bearer secret",
        "Cookie": "session=secret",
        "Proxy-Authorization": "Basic secret",
        "X-Api-Key": "secret",
        "X-Auth-Token": "secret",
        "X-Trace-Id": "trace-1",
    }

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await retrying_json_request(settings)(
            client,
            "GET",
            "https://start.example.test/data",
            headers=headers,
            follow_redirects=True,
        )

    assert data == {"ok": True}
    assert [request.url.host for request in requests] == [
        "start.example.test",
        "end.example.test",
    ]
    redirected_headers = requests[1].headers
    assert "authorization" not in redirected_headers
    assert "cookie" not in redirected_headers
    assert "proxy-authorization" not in redirected_headers
    assert "x-api-key" not in redirected_headers
    assert "x-auth-token" not in redirected_headers
    assert redirected_headers["x-trace-id"] == "trace-1"


@pytest.mark.asyncio
async def test_retrying_json_request_strips_client_credentials_on_cross_origin_redirect():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "start.example.test":
            return httpx.Response(
                302,
                headers={"location": "https://end.example.test/data"},
                request=request,
            )
        return httpx.Response(200, json={"ok": True}, request=request)

    settings = OpenOppsSettings(retry_attempts=1, cache_enabled=False)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        auth=("user", "client-secret"),
        cookies={"client_session": "secret"},
    ) as client:
        data = await retrying_json_request(settings)(
            client,
            "GET",
            "https://start.example.test/data",
            follow_redirects=True,
        )

    assert data == {"ok": True}
    assert [request.url.host for request in requests] == [
        "start.example.test",
        "end.example.test",
    ]
    assert "authorization" in requests[0].headers
    assert "cookie" in requests[0].headers
    redirected_headers = requests[1].headers
    assert "authorization" not in redirected_headers
    assert "cookie" not in redirected_headers


@pytest.mark.asyncio
@respx.mock
async def test_retrying_text_request_rejects_unsafe_redirect():
    settings = OpenOppsSettings(retry_attempts=1, cache_enabled=False)
    route = respx.get("https://redirect.example.test/start").mock(
        return_value=httpx.Response(
            302, headers={"location": "https://127.0.0.1/private"}
        )
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="IP literal"):
            await retrying_text_request(settings)(
                client,
                "GET",
                "https://redirect.example.test/start",
                follow_redirects=True,
            )

    assert route.call_count == 1


def test_http_public_redirect_validation_export():
    import openopps.http as http_module

    exported = importlib.import_module("openopps.http")
    assert (
        exported.request_with_public_redirect_validation
        is http_module.request_with_public_redirect_validation
    )
    assert (
        request_with_public_redirect_validation
        is http_module.request_with_public_redirect_validation
    )
    assert "request_with_public_redirect_validation" in http_module.__all__
    assert "_request_with_public_redirect_validation" not in http_module.__all__
