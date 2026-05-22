from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from openopps.cache import DEFAULT_CACHE_NAMESPACE, HttpCache, cache_key
from openopps.settings import OpenOppsSettings


RetryableHttpError = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def build_async_client(settings: OpenOppsSettings) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=max(1, settings.max_connections // 2),
    )
    headers = {
        "accept": "application/json",
        "user-agent": settings.user_agent,
    }
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(settings.http_timeout),
        limits=limits,
        http2=True,
        follow_redirects=False,
    )


def retrying_json_request(
    settings: OpenOppsSettings,
) -> Callable[..., Awaitable[dict[str, Any] | list[Any]]]:
    cache = HttpCache(settings.cache_path) if settings.cache_enabled else None
    inflight: dict[str, asyncio.Task[dict[str, Any] | list[Any]]] = {}
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
    ) -> tuple[dict[str, Any] | list[Any] | None, httpx.Response]:
        response = await client.request(method, url, **kwargs)
        if response.status_code == 304:
            return None, response
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError(f"Expected JSON object or list from {url}")
        return data, response

    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        request_kwargs = dict(kwargs)
        namespace = str(request_kwargs.pop("cache_namespace", DEFAULT_CACHE_NAMESPACE))
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
                return hit.data
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

        async def fetch_and_store() -> dict[str, Any] | list[Any]:
            nonlocal stale_hit
            data, response = await _request_upstream(
                client, method, url, **request_kwargs
            )
            if data is None:
                if request_cache and stale_hit is not None:
                    request_cache.refresh_json(stale_hit.key, ttl_seconds=ttl_seconds)
                    return stale_hit.data
                raise ValueError(f"Received 304 without cached payload for {url}")
            if request_cache:
                request_cache.put_json(
                    method,
                    url,
                    data,
                    namespace=namespace,
                    params=params,
                    json_body=json_body,
                    request_headers=headers,
                    response_headers=dict(response.headers),
                    identity=identity,
                    ttl_seconds=ttl_seconds,
                    stale_on_error=stale_on_error,
                )
            return data

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
                    return eligible_stale_hit.data
            raise

    return _request


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, RetryableHttpError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


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
