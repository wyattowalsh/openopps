from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
import socket
from time import monotonic, time
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from openopps.cache import DEFAULT_CACHE_NAMESPACE, HttpCache, cache_key
from openopps.models import validate_public_https_url
from openopps.settings import OpenOppsSettings


RetryableHttpError = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 60.0
DEFAULT_TEXT_CACHE_NAMESPACE = "http-text"
MAX_PUBLIC_REDIRECTS = 20
_CROSS_ORIGIN_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
}
_RESPONSE_CACHE_MARKER = "__openopps_http_response_v1__"

JsonResponseData = dict[str, Any] | list[Any]
HttpResponseBody = JsonResponseData | str


@dataclass(frozen=True)
class HttpResponseData:
    body: HttpResponseBody
    headers: dict[str, str]
    status_code: int


class PublicFetchTransport(httpx.AsyncBaseTransport):
    """HTTPX transport wrapper that validates every outbound public fetch."""

    def __init__(self, wrapped: httpx.AsyncBaseTransport):
        self._wrapped = wrapped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await assert_public_fetch_url(str(request.url))
        return await self._wrapped.handle_async_request(request)

    async def aclose(self) -> None:
        await self._wrapped.aclose()


class AsyncSlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = asyncio.Lock()
        self._calls: list[float] = []

    async def wait(self) -> None:
        async with self._lock:
            while True:
                now = monotonic()
                cutoff = now - self.window_seconds
                self._calls = [item for item in self._calls if item > cutoff]
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return
                delay = self.window_seconds - (now - self._calls[0])
                await asyncio.sleep(max(delay, 0.0))


def build_async_client(settings: OpenOppsSettings) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=max(1, settings.max_connections // 2),
    )
    headers = {
        "accept": "application/json",
        "user-agent": settings.user_agent,
    }
    transport = PublicFetchTransport(
        httpx.AsyncHTTPTransport(limits=limits, http2=True)
    )
    client = httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(settings.http_timeout),
        transport=transport,
        follow_redirects=False,
    )
    setattr(client, "_openopps_settings", settings)
    return client


def retrying_json_request(
    settings: OpenOppsSettings,
) -> Callable[..., Awaitable[JsonResponseData]]:
    request_response = retrying_json_response(settings)

    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> JsonResponseData:
        response = await request_response(client, method, url, **kwargs)
        return cast(JsonResponseData, response.body)

    return _request


def retrying_json_response(
    settings: OpenOppsSettings,
) -> Callable[..., Awaitable[HttpResponseData]]:
    return _retrying_response_request(
        settings,
        parser=_parse_json_body,
        validator=_validate_json_body,
        default_namespace=DEFAULT_CACHE_NAMESPACE,
    )


def retrying_text_request(
    settings: OpenOppsSettings,
) -> Callable[..., Awaitable[str]]:
    request_response = retrying_text_response(settings)

    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> str:
        response = await request_response(client, method, url, **kwargs)
        return cast(str, response.body)

    return _request


def retrying_text_response(
    settings: OpenOppsSettings,
) -> Callable[..., Awaitable[HttpResponseData]]:
    return _retrying_response_request(
        settings,
        parser=_parse_text_body,
        validator=_validate_text_body,
        default_namespace=DEFAULT_TEXT_CACHE_NAMESPACE,
    )


def _retrying_response_request(
    settings: OpenOppsSettings,
    *,
    parser: Callable[[httpx.Response, str], HttpResponseBody],
    validator: Callable[[object, str], HttpResponseBody],
    default_namespace: str,
) -> Callable[..., Awaitable[HttpResponseData]]:
    cache = (
        HttpCache(settings.sqlite_path)
        if settings.cache_enabled and settings.sqlite_path is not None
        else None
    )
    inflight: dict[str, asyncio.Task[HttpResponseData]] = {}
    inflight_lock = asyncio.Lock()

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        wait=wait_exponential_jitter(initial=0.25, max=8),
        stop=stop_after_attempt(settings.retry_attempts),
        reraise=True,
    )
    async def _request_upstream(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[HttpResponseData | None, httpx.Response]:
        response = await _request_with_public_redirect_validation(
            client, method, url, **kwargs
        )
        if response.status_code == 304:
            return None, response
        if response.status_code == 429:
            await _sleep_for_retry_after(response)
        response.raise_for_status()
        body = parser(response, url)
        return (
            HttpResponseData(
                body=body,
                headers=_response_headers(response),
                status_code=response.status_code,
            ),
            response,
        )

    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> HttpResponseData:
        request_kwargs = dict(kwargs)
        namespace = str(request_kwargs.pop("cache_namespace", default_namespace))
        identity = _cache_identity(request_kwargs.pop("cache_identity", None))
        ttl_seconds = int(
            request_kwargs.pop("cache_ttl_seconds", settings.cache_ttl_seconds)
        )
        refresh = bool(request_kwargs.pop("cache_refresh", settings.cache_refresh))
        stale_on_error = bool(
            request_kwargs.pop("cache_stale_on_error", settings.cache_stale_on_error)
        )
        enabled = bool(request_kwargs.pop("cache_enabled", settings.cache_enabled))
        request_cache = cache if enabled else None
        params = _mapping_or_none(request_kwargs.get("params"))
        json_body = request_kwargs.get("json")
        headers = _mapping_or_none(request_kwargs.get("headers"))
        request_key = (
            cache_key(
                method,
                url,
                namespace=namespace,
                params=params,
                json_body=json_body,
                headers=headers,
                identity=identity,
            )
            if request_cache and not refresh
            else None
        )

        stale_hit = None
        if request_cache:
            hit = request_cache.get_json(
                method,
                url,
                namespace=namespace,
                params=params,
                json_body=json_body,
                headers=headers,
                identity=identity,
                refresh=refresh,
            )
            if hit is not None:
                return _cached_response(hit, validator, url)
            if not refresh:
                stale_hit = request_cache.get_stale_json(
                    method,
                    url,
                    namespace=namespace,
                    params=params,
                    json_body=json_body,
                    headers=headers,
                    identity=identity,
                    stale_on_error_only=False,
                )
                if stale_hit:
                    request_kwargs["headers"] = _conditional_headers(
                        request_kwargs.get("headers"),
                        stale_hit.etag,
                        stale_hit.last_modified,
                    )

        async def fetch_and_store() -> HttpResponseData:
            nonlocal stale_hit
            result, response = await _request_upstream(
                client, method, url, **request_kwargs
            )
            if result is None:
                if request_cache and stale_hit is not None:
                    request_cache.refresh_json(stale_hit.key, ttl_seconds=ttl_seconds)
                    return _cached_response(stale_hit, validator, url)
                raise ValueError(f"Received 304 without cached payload for {url}")
            if request_cache:
                request_cache.put_json(
                    method,
                    url,
                    _cache_response_payload(result),
                    status_code=result.status_code,
                    namespace=namespace,
                    params=params,
                    json_body=json_body,
                    request_headers=headers,
                    response_headers=dict(response.headers),
                    identity=identity,
                    ttl_seconds=ttl_seconds,
                    stale_on_error=stale_on_error,
                )
            return result

        try:
            if request_key is None:
                return await fetch_and_store()
            async with inflight_lock:
                task = inflight.get(request_key)
                if task is None:
                    task = asyncio.create_task(fetch_and_store())
                    inflight[request_key] = task
            try:
                return await task
            finally:
                if task.done():
                    async with inflight_lock:
                        if inflight.get(request_key) is task:
                            inflight.pop(request_key, None)
        except Exception as exc:
            if (
                request_cache
                and not refresh
                and stale_on_error
                and _is_retryable_http_error(exc)
            ):
                eligible_stale_hit = (
                    stale_hit
                    if stale_hit is not None and stale_hit.stale_on_error
                    else request_cache.get_stale_json(
                        method,
                        url,
                        namespace=namespace,
                        params=params,
                        json_body=json_body,
                        headers=headers,
                        identity=identity,
                    )
                )
                if eligible_stale_hit is not None:
                    logger.warning(
                        "Using stale cache payload namespace={} key={} url={}",
                        namespace,
                        eligible_stale_hit.key,
                        url,
                    )
                    return _cached_response(eligible_stale_hit, validator, url)
            raise

    return _request


async def _request_with_public_redirect_validation(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    request_kwargs = dict(kwargs)
    follow_redirects = bool(request_kwargs.pop("follow_redirects", False))
    max_redirects = int(request_kwargs.pop("max_redirects", MAX_PUBLIC_REDIRECTS))
    current_method = method
    current_url = url
    for redirect_count in range(max_redirects + 1):
        await assert_public_fetch_url(current_url)
        response = await client.request(
            current_method,
            current_url,
            **request_kwargs,
            follow_redirects=False,
        )
        if not follow_redirects or not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        if redirect_count >= max_redirects:
            raise httpx.TooManyRedirects(
                f"Exceeded {max_redirects} redirects for {url}",
                request=response.request,
            )
        next_url = urljoin(str(response.url), location)
        if _request_origin(current_url) != _request_origin(next_url):
            request_kwargs = _request_kwargs_without_sensitive_headers(request_kwargs)
        current_url = next_url
        if response.status_code == 303 or (
            response.status_code in {301, 302}
            and current_method.upper() not in {"GET", "HEAD"}
        ):
            current_method = "GET"
            request_kwargs = _request_kwargs_without_body(request_kwargs)
    raise httpx.TooManyRedirects(f"Exceeded {max_redirects} redirects for {url}")


async def assert_public_fetch_url(url: str) -> str:
    """Validate HTTPS URL syntax and DNS resolution before an outbound fetch.

    Best-effort, defense-in-depth SSRF guard for the local-CLI threat model: it
    rejects URLs whose hostname currently resolves to a non-global-routable
    address. It is *not* rebinding-proof. httpx re-resolves DNS at connect time,
    so a TOCTOU/DNS-rebinding window remains between this check and the actual
    socket connect.

    Mitigations today are intentionally lightweight: validate URL shape, resolve
    once, and reject non-global addresses. They do **not** pin the vetted IP into
    the subsequent connection, so a hostile or compromised resolver could return
    a public address at check time and a private/metadata address when httpx
    connects. Redirect hops are origin-checked, but each hop still performs its
    own DNS lookup.

    Closing the rebinding gap would require connect-time pinning (for example,
    binding the client to the addresses observed here) or a trusted resolver
    policy. That is out of scope for the v0.1 local-CLI threat model unless an
    operator explicitly opts into stronger outbound controls later.
    """

    validate_public_https_url(url)
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        raise ValueError("URL must include a host")
    await _assert_global_routable_dns(host, parsed.port or 443)
    return url


async def _assert_global_routable_dns(host: str, port: int) -> None:
    """Reject hosts that resolve to any non-global-routable address.

    Defense-in-depth only (see ``assert_public_fetch_url``). DNS resolution
    failures (``socket.gaierror``) safe-fail by returning without raising: the
    subsequent real connection attempt will fail on its own, and blocking here
    would break legitimate transient-resolution cases under the local-CLI
    threat model. Each resolved address has its IPv6 zone id (``%zone``) and
    bracket literals stripped before parsing so scoped link-local addresses
    (for example ``fe80::1%eth0``) are still classified rather than crashing.
    """

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return
    addresses: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addresses.add(str(sockaddr[0]))
    non_global = sorted(
        address
        for address in addresses
        if not ip_address(address.split("%", 1)[0].strip("[]")).is_global
    )
    if non_global:
        raise ValueError(
            f"Host {host} resolved to non-global-routable address {non_global[0]}"
        )


def _request_kwargs_without_body(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in kwargs.items()
        if key not in {"content", "data", "files", "json"}
    }


def _request_origin(url: str) -> tuple[str, str, int | None] | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    port = parsed.port
    if port is None and scheme == "http":
        port = 80
    if port is None and scheme == "https":
        port = 443
    return (scheme, parsed.hostname.lower(), port)


def _request_kwargs_without_sensitive_headers(
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    headers = kwargs.get("headers")
    if not headers:
        return kwargs
    next_kwargs = dict(kwargs)
    next_kwargs["headers"] = {
        key: value
        for key, value in dict(headers).items()
        if key.lower() not in _CROSS_ORIGIN_SENSITIVE_HEADERS
    }
    return next_kwargs


def _parse_json_body(response: httpx.Response, url: str) -> JsonResponseData:
    data = response.json()
    if not isinstance(data, (dict, list)):
        raise ValueError(f"Expected JSON object or list from {url}")
    return data


def _parse_text_body(response: httpx.Response, _url: str) -> str:
    return response.text


def _validate_json_body(value: object, url: str) -> JsonResponseData:
    if not isinstance(value, (dict, list)):
        raise ValueError(f"Cached JSON payload for {url} is invalid")
    return value


def _validate_text_body(value: object, url: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Cached text payload for {url} is invalid")
    return value


def _cache_response_payload(response: HttpResponseData) -> dict[str, Any]:
    return {
        _RESPONSE_CACHE_MARKER: {
            "body": response.body,
            "headers": response.headers,
            "status_code": response.status_code,
        }
    }


def _cached_response(
    hit: Any,
    validator: Callable[[object, str], HttpResponseBody],
    url: str,
) -> HttpResponseData:
    data = hit.data
    if isinstance(data, dict) and set(data) == {_RESPONSE_CACHE_MARKER}:
        wrapped = data.get(_RESPONSE_CACHE_MARKER)
        if isinstance(wrapped, dict) and "body" in wrapped:
            body = validator(wrapped.get("body"), url)
            headers = _string_dict(wrapped.get("headers"))
            status_code = _int_or_default(wrapped.get("status_code"), hit.status_code)
            return HttpResponseData(
                body=body,
                headers=headers,
                status_code=status_code,
            )
    headers = {
        key: value
        for key, value in {
            "etag": hit.etag,
            "last-modified": hit.last_modified,
        }.items()
        if value
    }
    return HttpResponseData(
        body=validator(data, url),
        headers=headers,
        status_code=int(hit.status_code),
    )


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in response.headers.items()}


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key).lower(): str(item) for key, item in value.items()}


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, RetryableHttpError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


async def _sleep_for_retry_after(response: httpx.Response) -> None:
    delay = _retry_after_seconds(response)
    if delay is not None and delay > 0:
        await asyncio.sleep(min(delay, MAX_RETRY_AFTER_SECONDS))


def _retry_after_seconds(response: httpx.Response) -> float | None:
    for name in ("retry-after", "x-ratelimit-reset", "x-rate-limit-reset"):
        value = response.headers.get(name)
        if not value:
            continue
        parsed = _retry_header_seconds(value)
        if parsed is not None:
            return parsed
    return None


def _retry_header_seconds(value: str) -> float | None:
    stripped = value.strip()
    try:
        numeric = float(stripped)
    except ValueError:
        try:
            return max(parsedate_to_datetime(stripped).timestamp() - time(), 0.0)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    if numeric > 1_000_000_000:
        return max(numeric - time(), 0.0)
    return max(numeric, 0.0)


def _mapping_or_none(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return None


def _cache_identity(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {"value": str(value)}


def _conditional_headers(
    headers: object,
    etag: str | None,
    last_modified: str | None,
) -> dict[str, str]:
    merged = (
        {str(key): str(value) for key, value in headers.items()}
        if isinstance(headers, Mapping)
        else {}
    )
    if etag:
        merged.setdefault("if-none-match", etag)
    if last_modified:
        merged.setdefault("if-modified-since", last_modified)
    return merged
