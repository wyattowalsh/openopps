from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

import openopps.http as http_module


def test_safe_request_error_messages_redact_credentials_and_raw_failures() -> None:
    request = httpx.Request(
        "GET",
        "https://user:password@example.com/jobs?api_key=secret&team=infra",
    )
    request_error = httpx.ConnectError("credential=raw-secret", request=request)
    missing_request_error = httpx.ConnectError("credential=raw-secret")

    rendered = http_module.safe_exception_message(request_error)
    requestless = http_module.safe_exception_message(missing_request_error)

    assert rendered == "ConnectError: request failed"
    assert "password" not in rendered
    assert "secret" not in rendered
    assert "/jobs" not in rendered
    assert "infra" not in rendered
    assert requestless == "ConnectError: request failed"


@pytest.mark.asyncio
async def test_redirect_without_location_is_returned_to_the_caller(monkeypatch) -> None:
    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request)

    monkeypatch.setattr(http_module, "assert_public_fetch_url", allow_public_url)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await http_module.request_with_public_redirect_validation(
            client,
            "GET",
            "https://example.com/start",
            follow_redirects=True,
        )

    assert response.status_code == 302
    assert "location" not in response.headers


@pytest.mark.asyncio
async def test_redirect_limit_fails_closed_before_following_an_extra_hop(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "/next"},
            request=request,
        )

    monkeypatch.setattr(http_module, "assert_public_fetch_url", allow_public_url)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.TooManyRedirects, match="Exceeded 0 redirects"):
            await http_module.request_with_public_redirect_validation(
                client,
                "GET",
                "https://example.com/start",
                follow_redirects=True,
                max_redirects=0,
            )

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_post_redirect_switches_to_get_and_drops_request_body(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/result"},
                request=request,
            )
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(http_module, "assert_public_fetch_url", allow_public_url)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await http_module.request_with_public_redirect_validation(
            client,
            "POST",
            "https://example.com/start",
            json={"secret": "body"},
            follow_redirects=True,
        )

    assert response.json() == {"ok": True}
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/start"),
        ("GET", "/result"),
    ]
    assert requests[1].content == b""


def test_request_origin_normalizes_defaults_and_rejects_incomplete_urls() -> None:
    assert http_module._request_origin("not-a-url") is None
    assert http_module._request_origin("http://Example.COM/path") == (
        "http",
        "example.com",
        80,
    )
    assert http_module._request_origin("https://Example.COM/path") == (
        "https",
        "example.com",
        443,
    )


def test_cached_body_validators_reject_wrong_scalar_types() -> None:
    with pytest.raises(ValueError, match="Cached JSON payload"):
        http_module._validate_json_body("not-json-data", "https://example.com")
    with pytest.raises(ValueError, match="Cached text payload"):
        http_module._validate_text_body({"not": "text"}, "https://example.com")


def test_cache_metadata_parsers_use_safe_defaults() -> None:
    assert http_module._string_dict("not-a-mapping") == {}
    assert http_module._int_or_default(True, 418) == 418
    assert http_module._int_or_default(201, 418) == 201
    assert http_module._int_or_default("202", 418) == 202
    assert http_module._int_or_default("invalid", 418) == 418
    assert http_module._int_or_default(None, 418) == 418


@pytest.mark.asyncio
async def test_retry_after_sleep_is_bounded(monkeypatch) -> None:
    delays: list[float] = []

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(http_module.asyncio, "sleep", capture_sleep)
    response = httpx.Response(429, headers={"retry-after": "120"})

    await http_module._sleep_for_retry_after(response)

    assert delays == [http_module.MAX_RETRY_AFTER_SECONDS]


def test_retry_header_parser_supports_dates_epochs_durations_and_bad_input(
    monkeypatch,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(http_module, "time", lambda: now)

    assert http_module._retry_header_seconds("Wed, 01 Jan 2026 00:00:05 GMT") == 5.0
    assert http_module._retry_header_seconds(str(now + 10)) == 10.0
    assert http_module._retry_header_seconds("2.5") == 2.5
    assert http_module._retry_header_seconds("-1") == 0.0
    assert http_module._retry_header_seconds("not-a-date") is None


def test_cache_identity_normalizes_mappings_and_opaque_values() -> None:
    assert http_module._cache_identity(None) is None
    assert http_module._cache_identity({1: "one"}) == {"1": "one"}
    assert http_module._cache_identity(("opaque", 2)) == {"value": "('opaque', 2)"}


def test_credential_cache_identity_fingerprints_every_credential_surface() -> None:
    with httpx.Client(
        auth=("client-user", "client-password"),
        cookies={"client-session": "client-cookie"},
    ) as client:
        credentials = http_module._credential_cache_identity(
            client,
            {
                "headers": {"Authorization": "Bearer header-secret"},
                "auth": ("request-user", "request-password"),
                "cookies": {"request-session": "request-cookie"},
            },
        )

    assert credentials is not None
    assert set(credentials) == {
        "headers",
        "requestAuthSha256",
        "requestCookiesSha256",
        "clientCookies",
    }
    persisted = repr(credentials)
    for secret in (
        "header-secret",
        "request-password",
        "request-cookie",
        "client-cookie",
    ):
        assert secret not in persisted
    assert persisted.count("sha256:") >= 4


def test_credential_cache_identity_fingerprints_client_auth_when_not_overridden() -> (
    None
):
    client = SimpleNamespace(auth=("client-user", "client-password"), cookies=None)

    credentials = http_module._credential_cache_identity(client, {})

    assert credentials is not None
    assert set(credentials) == {"clientAuthSha256"}
    assert credentials["clientAuthSha256"].startswith("sha256:")
    assert "client-password" not in repr(credentials)


def test_conditional_headers_preserve_callers_and_add_missing_validators() -> None:
    headers = http_module._conditional_headers(
        {"if-none-match": "caller-etag"},
        "cache-etag",
        "Wed, 01 Jan 2026 00:00:00 GMT",
    )

    assert headers == {
        "if-none-match": "caller-etag",
        "if-modified-since": "Wed, 01 Jan 2026 00:00:00 GMT",
    }
