from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from email.utils import parsedate_to_datetime
from hashlib import sha256
from ipaddress import ip_address
import json
import math
import socket
from time import monotonic, time
from typing import Any, Iterator, Literal, cast
from urllib.parse import urljoin, urlparse
import zlib

import httpx
from loguru import logger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from openopps.cache import (
    DEFAULT_CACHE_NAMESPACE,
    HttpCache,
    cache_key,
)
from openopps.metrics import record_http_retry
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
_CREDENTIAL_CACHE_IDENTITY_KEY = "__openopps_credentials__"
_SCOPED_CACHE_IDENTITY_KEY = "__openopps_scope__"
_RESPONSE_CACHE_MARKER = "__openopps_http_response_v1__"
_REDIRECT_URLS_EXTENSION = "openopps.redirect_urls"
_CACHEABLE_RESPONSE_HEADERS = {
    "content-type",
    "etag",
    "last-modified",
    "x-wp-total",
    "x-wp-totalpages",
}

JsonResponseData = dict[str, Any] | list[Any]
HttpResponseBody = JsonResponseData | str
HttpResponseLimitReason = Literal[
    "declared_encoded",
    "encoded",
    "decoded",
    "aggregate",
]
RequestBudgetGuard = Callable[[str, bool], Awaitable[None] | None]

__all__ = [
    "AsyncSlidingWindowRateLimiter",
    "HttpOperationClosedError",
    "HttpOperationBudget",
    "HttpOperationCounters",
    "HttpOperationSnapshot",
    "HttpRequestLimitError",
    "HttpResponseLimitError",
    "HttpResponseData",
    "PublicFetchSafetyError",
    "PublicFetchTransport",
    "ResponseByteBudget",
    "assert_public_fetch_url",
    "build_async_client",
    "http_cache_identity_scope",
    "http_operation_budget",
    "http_operation_observability",
    "request_with_public_redirect_validation",
    "retrying_json_request",
    "retrying_json_response",
    "retrying_text_request",
    "retrying_text_response",
    "safe_exception_message",
]


class HttpResponseLimitError(ValueError):
    """Bounded, payload-free failure for shared HTTP response admission."""

    def __init__(
        self,
        reason: HttpResponseLimitReason,
        *,
        limit_bytes: int,
        observed_bytes: int,
    ) -> None:
        self.reason = reason
        self.limit_bytes = limit_bytes
        self.observed_bytes = observed_bytes
        label = {
            "declared_encoded": "declared encoded",
            "encoded": "encoded",
            "decoded": "decoded",
            "aggregate": "aggregate decoded",
        }[reason]
        super().__init__(
            f"HTTP response exceeded {label} byte limit ({limit_bytes} bytes)"
        )


class HttpRequestLimitError(ValueError):
    """Bounded, URL-free failure for an exhausted operation request budget."""

    def __init__(self, *, limit_requests: int, observed_requests: int) -> None:
        self.limit_requests = limit_requests
        self.observed_requests = observed_requests
        super().__init__(
            f"HTTP operation exceeded request limit ({limit_requests} requests)"
        )


class HttpOperationClosedError(RuntimeError):
    """Bounded failure for work attempted after operation closure or expiry."""

    def __init__(self, *, expired: bool) -> None:
        self.expired = expired
        reason = "deadline expired" if expired else "scope is closed"
        super().__init__(f"HTTP operation {reason}")


class PublicFetchSafetyError(ValueError):
    """Payload-free rejection from the shared public-fetch safety boundary."""


@dataclass(frozen=True)
class HttpOperationSnapshot:
    """Immutable payload-free counters for one bounded logical HTTP operation."""

    logical_read_count: int = 0
    request_count: int = 0
    redirect_count: int = 0
    retry_count: int = 0
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_revalidation_count: int = 0
    cache_stale_fallback_count: int = 0
    cache_write_count: int = 0
    cache_bypass_count: int = 0
    encoded_bytes: int = 0
    decoded_bytes: int = 0

    def as_dict(self) -> dict[str, int]:
        """Serialize payload-free counters with camelCase keys and no URLs."""

        return {
            "logicalReadCount": self.logical_read_count,
            "requestCount": self.request_count,
            "redirectCount": self.redirect_count,
            "retryCount": self.retry_count,
            "cacheHitCount": self.cache_hit_count,
            "cacheMissCount": self.cache_miss_count,
            "cacheRevalidationCount": self.cache_revalidation_count,
            "cacheStaleFallbackCount": self.cache_stale_fallback_count,
            "cacheWriteCount": self.cache_write_count,
            "cacheBypassCount": self.cache_bypass_count,
            "encodedBytes": self.encoded_bytes,
            "decodedBytes": self.decoded_bytes,
        }

    @classmethod
    def merge(cls, *snapshots: HttpOperationSnapshot) -> HttpOperationSnapshot:
        """Sum payload-free counters from sequential stage collectors."""

        if not snapshots:
            return cls()
        if len(snapshots) == 1:
            return snapshots[0]
        return cls(
            **{
                item.name: sum(getattr(snapshot, item.name) for snapshot in snapshots)
                for item in fields(cls)
            }
        )


@dataclass
class HttpOperationCounters:
    """Mutable operation counters containing no URL, header, or payload labels."""

    logical_read_count: int = 0
    request_count: int = 0
    redirect_count: int = 0
    retry_count: int = 0
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_revalidation_count: int = 0
    cache_stale_fallback_count: int = 0
    cache_write_count: int = 0
    cache_bypass_count: int = 0
    encoded_bytes: int = 0
    decoded_bytes: int = 0
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Freeze the collector so inherited task contexts cannot mutate it later."""

        self._closed = True

    def increment(self, field_name: str, amount: int = 1) -> None:
        """Increment one declared counter while the operation remains active."""

        if self._closed:
            return
        current = getattr(self, field_name, None)
        if (
            not isinstance(current, int)
            or isinstance(current, bool)
            or not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount < 0
        ):
            raise ValueError(
                "HTTP observability counters require non-negative integers"
            )
        setattr(self, field_name, current + amount)

    def snapshot(self) -> HttpOperationSnapshot:
        """Freeze the current payload-free counts for terminal reporting."""

        return HttpOperationSnapshot(
            logical_read_count=self.logical_read_count,
            request_count=self.request_count,
            redirect_count=self.redirect_count,
            retry_count=self.retry_count,
            cache_hit_count=self.cache_hit_count,
            cache_miss_count=self.cache_miss_count,
            cache_revalidation_count=self.cache_revalidation_count,
            cache_stale_fallback_count=self.cache_stale_fallback_count,
            cache_write_count=self.cache_write_count,
            cache_bypass_count=self.cache_bypass_count,
            encoded_bytes=self.encoded_bytes,
            decoded_bytes=self.decoded_bytes,
        )


@dataclass
class ResponseByteBudget:
    """Mutable decoded-byte budget shared by a bounded group of HTTP reads."""

    maximum_bytes: int
    used_bytes: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_bytes, int)
            or isinstance(self.maximum_bytes, bool)
            or self.maximum_bytes < 1
        ):
            raise ValueError("maximum_bytes must be a positive integer")
        if (
            not isinstance(self.used_bytes, int)
            or isinstance(self.used_bytes, bool)
            or self.used_bytes < 0
            or self.used_bytes > self.maximum_bytes
        ):
            raise ValueError("used_bytes must be within the response byte budget")

    @property
    def remaining_bytes(self) -> int:
        return self.maximum_bytes - self.used_bytes

    def admit(self, decoded_bytes: int) -> None:
        if (
            not isinstance(decoded_bytes, int)
            or isinstance(decoded_bytes, bool)
            or decoded_bytes < 0
        ):
            raise ValueError("decoded_bytes must be a non-negative integer")
        observed = self.used_bytes + decoded_bytes
        if observed > self.maximum_bytes:
            raise HttpResponseLimitError(
                "aggregate",
                limit_bytes=self.maximum_bytes,
                observed_bytes=observed,
            )
        self.used_bytes = observed


@dataclass
class HttpOperationBudget:
    """Mutable request and decoded-byte budget shared by one logical operation."""

    maximum_requests: int
    maximum_response_bytes: int
    deadline_monotonic: float | None = None
    requests_used: int = field(default=0, init=False)
    response_byte_budget: ResponseByteBudget = field(init=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _expired: bool = field(default=False, init=False, repr=False)
    _terminal_limit_error: HttpRequestLimitError | HttpResponseLimitError | None = (
        field(default=None, init=False, repr=False)
    )
    _active_tasks: dict[asyncio.Task[Any], int] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _deadline_handle: asyncio.TimerHandle | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_requests, int)
            or isinstance(self.maximum_requests, bool)
            or self.maximum_requests < 1
        ):
            raise ValueError("maximum_requests must be a positive integer")
        if self.deadline_monotonic is not None:
            if (
                isinstance(self.deadline_monotonic, bool)
                or not isinstance(self.deadline_monotonic, (int, float))
                or not math.isfinite(self.deadline_monotonic)
            ):
                raise ValueError("deadline_monotonic must be a finite number")
            if self.deadline_monotonic <= monotonic():
                raise ValueError("deadline_monotonic must be in the future")
            self.deadline_monotonic = float(self.deadline_monotonic)
        self.response_byte_budget = ResponseByteBudget(
            maximum_bytes=self.maximum_response_bytes
        )
        self._arm_deadline_if_possible()

    @property
    def remaining_requests(self) -> int:
        return self.maximum_requests - self.requests_used

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def expired(self) -> bool:
        return self._expired

    @property
    def active_request_count(self) -> int:
        return len(self._active_tasks)

    @property
    def active_request_references(self) -> int:
        return sum(self._active_tasks.values())

    def begin_request(self) -> _HttpOperationRequestGuard:
        """Charge one logical read before cache lookup and return its retry guard."""

        self._admit_request()
        return _HttpOperationRequestGuard(operation=self)

    def ensure_open(self) -> None:
        """Reject work after normal closure or the absolute operation deadline."""

        if self._closed:
            raise self._closed_error()
        if (
            self.deadline_monotonic is not None
            and monotonic() >= self.deadline_monotonic
        ):
            self._mark_closed(
                expired=True,
                exclude_task=_current_asyncio_task(),
            )
            raise self._closed_error()

    def close(self) -> None:
        """Close the scope and cancel only request tasks still owned by it."""

        self._mark_closed(
            expired=False,
            exclude_task=_current_asyncio_task(),
        )

    def _latch_limit_error(
        self,
        error: HttpRequestLimitError | HttpResponseLimitError,
    ) -> None:
        """Make an admitted request/response limit failure terminal for the scope."""

        if self._closed:
            return
        self._terminal_limit_error = error
        self._mark_closed(
            expired=False,
            exclude_task=_current_asyncio_task(),
        )

    def _register_current_task(self) -> asyncio.Task[Any]:
        self.ensure_open()
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("HTTP operation requests require an asyncio task")
        self._active_tasks[task] = self._active_tasks.get(task, 0) + 1
        self._arm_deadline_if_possible()
        return task

    def _unregister_task(self, task: asyncio.Task[Any]) -> None:
        references = self._active_tasks.get(task)
        if references is None:
            return
        if references <= 1:
            self._active_tasks.pop(task, None)
            return
        self._active_tasks[task] = references - 1

    def _admit_request(self) -> None:
        self.ensure_open()
        observed = self.requests_used + 1
        if observed > self.maximum_requests:
            error = HttpRequestLimitError(
                limit_requests=self.maximum_requests,
                observed_requests=observed,
            )
            self._latch_limit_error(error)
            raise error
        self.requests_used = observed

    def _arm_deadline_if_possible(self) -> None:
        if (
            self.deadline_monotonic is None
            or self._closed
            or self._deadline_handle is not None
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        delay = max(self.deadline_monotonic - monotonic(), 0.0)
        self._deadline_handle = loop.call_later(delay, self._expire_from_timer)

    def _expire_from_timer(self) -> None:
        self._deadline_handle = None
        self._mark_closed(expired=True, exclude_task=None)

    def _mark_closed(
        self,
        *,
        expired: bool,
        exclude_task: asyncio.Task[Any] | None,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        self._expired = expired
        if self._deadline_handle is not None:
            self._deadline_handle.cancel()
            self._deadline_handle = None
        for task in tuple(self._active_tasks):
            if task is exclude_task or task.done():
                continue
            task.add_done_callback(_consume_closed_operation_task_outcome)
            task.cancel()

    def _closed_error(
        self,
    ) -> HttpOperationClosedError | HttpRequestLimitError | HttpResponseLimitError:
        if isinstance(self._terminal_limit_error, HttpRequestLimitError):
            return HttpRequestLimitError(
                limit_requests=self._terminal_limit_error.limit_requests,
                observed_requests=self._terminal_limit_error.observed_requests,
            )
        if isinstance(self._terminal_limit_error, HttpResponseLimitError):
            return HttpResponseLimitError(
                self._terminal_limit_error.reason,
                limit_bytes=self._terminal_limit_error.limit_bytes,
                observed_bytes=self._terminal_limit_error.observed_bytes,
            )
        return HttpOperationClosedError(expired=self._expired)


@dataclass
class _HttpOperationRequestGuard:
    operation: HttpOperationBudget
    initial_request_precharged: bool = True

    def __call__(self, _url: str, _is_redirect: bool) -> None:
        self.operation.ensure_open()
        if self.initial_request_precharged:
            self.initial_request_precharged = False
            return
        self.operation._admit_request()


@dataclass
class _CombinedRequestBudgetGuard:
    operation_guard: _HttpOperationRequestGuard
    explicit_guard: RequestBudgetGuard

    async def __call__(self, url: str, is_redirect: bool) -> None:
        for guard in (self.operation_guard, self.explicit_guard):
            guarded = guard(url, is_redirect)
            if guarded is not None:
                await guarded


def _current_asyncio_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def _consume_closed_operation_task_outcome(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return


_CURRENT_HTTP_OPERATION_COUNTERS: ContextVar[HttpOperationCounters | None] = ContextVar(
    "openopps_http_operation_counters",
    default=None,
)

_CURRENT_HTTP_CACHE_IDENTITY_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar(
    "openopps_http_cache_identity_scope",
    default=None,
)


@contextmanager
def http_cache_identity_scope(
    identity: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    """Bind deterministic semantic cache dimensions across nested HTTP reads."""

    supplied = {str(key): item for key, item in identity.items()}
    current = _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.get()
    merged = dict(current or {})
    conflicts = {
        key for key, value in supplied.items() if key in merged and merged[key] != value
    }
    if conflicts:
        labels = ", ".join(sorted(conflicts))
        raise ValueError(f"conflicting HTTP cache identity scope keys: {labels}")
    merged.update(supplied)
    token = _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.set(merged)
    try:
        yield dict(merged)
    finally:
        _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.reset(token)


@contextmanager
def http_operation_observability(
    *,
    replace_existing: bool = False,
) -> Iterator[HttpOperationCounters]:
    """Collect payload-free HTTP counters without changing enforcement budgets."""

    current = _CURRENT_HTTP_OPERATION_COUNTERS.get()
    if current is not None and not replace_existing:
        yield current
        return
    counters = HttpOperationCounters()
    token = _CURRENT_HTTP_OPERATION_COUNTERS.set(counters)
    try:
        yield counters
    finally:
        counters.close()
        _CURRENT_HTTP_OPERATION_COUNTERS.reset(token)


def _capture_http_operation_counters() -> HttpOperationCounters:
    """Capture the active collector for an internally bound HTTP facade."""

    counters = _CURRENT_HTTP_OPERATION_COUNTERS.get()
    if counters is None:
        raise RuntimeError("active HTTP operation observability is required")
    return counters


@contextmanager
def _bind_http_operation_counters(
    counters: HttpOperationCounters,
) -> Iterator[None]:
    """Bind one captured collector even when a caller changed task context."""

    token = _CURRENT_HTTP_OPERATION_COUNTERS.set(counters)
    try:
        yield
    finally:
        _CURRENT_HTTP_OPERATION_COUNTERS.reset(token)


def _capture_http_cache_identity_scope() -> dict[str, Any] | None:
    """Capture semantic cache dimensions for an internally bound HTTP facade."""

    current = _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.get()
    return dict(current) if current is not None else None


@contextmanager
def _bind_http_cache_identity_scope(
    identity: Mapping[str, Any] | None,
) -> Iterator[None]:
    """Bind captured semantic cache dimensions across a changed task context."""

    if identity is None:
        yield
        return
    token = _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.set(
        {str(key): item for key, item in identity.items()}
    )
    try:
        yield
    finally:
        _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.reset(token)


def _http_operation_counters() -> HttpOperationCounters | None:
    return _CURRENT_HTTP_OPERATION_COUNTERS.get()


def _record_http_response_bytes(*, encoded_bytes: int, decoded_bytes: int) -> None:
    counters = _http_operation_counters()
    if counters is None:
        return
    counters.increment("encoded_bytes", max(encoded_bytes, 0))
    counters.increment("decoded_bytes", max(decoded_bytes, 0))


@contextmanager
def _track_http_operation_task(
    operation: HttpOperationBudget,
) -> Iterator[None]:
    task = operation._register_current_task()
    try:
        yield
    except asyncio.CancelledError as exc:
        if operation.closed:
            raise operation._closed_error() from exc
        raise
    finally:
        operation._unregister_task(task)


_CURRENT_HTTP_OPERATION_BUDGET: ContextVar[HttpOperationBudget | None] = ContextVar(
    "openopps_http_operation_budget",
    default=None,
)


def _capture_http_operation_budget() -> HttpOperationBudget:
    """Capture the active operation for an internally bound HTTP facade."""

    operation = _CURRENT_HTTP_OPERATION_BUDGET.get()
    if operation is None:
        raise RuntimeError("an active HTTP operation budget is required")
    operation.ensure_open()
    return operation


@contextmanager
def _bind_http_operation_budget(
    operation: HttpOperationBudget,
) -> Iterator[None]:
    """Bind one captured operation even when a caller changed task context."""

    operation.ensure_open()
    token = _CURRENT_HTTP_OPERATION_BUDGET.set(operation)
    try:
        yield
    finally:
        _CURRENT_HTTP_OPERATION_BUDGET.reset(token)


@contextmanager
def http_operation_budget(
    *,
    maximum_requests: int,
    maximum_response_bytes: int,
    replace_existing: bool = False,
    deadline_monotonic: float | None = None,
) -> Iterator[HttpOperationBudget]:
    """Scope shared HTTP budgets across cache reads, child tasks, retries, and redirects."""

    current = _CURRENT_HTTP_OPERATION_BUDGET.get()
    if current is not None and not replace_existing:
        current.ensure_open()
        yield current
        return
    operation = HttpOperationBudget(
        maximum_requests=maximum_requests,
        maximum_response_bytes=maximum_response_bytes,
        deadline_monotonic=deadline_monotonic,
    )
    token = _CURRENT_HTTP_OPERATION_BUDGET.set(operation)
    try:
        yield operation
    finally:
        operation.close()
        _CURRENT_HTTP_OPERATION_BUDGET.reset(token)


@dataclass(frozen=True)
class HttpResponseData:
    body: HttpResponseBody
    headers: dict[str, str]
    status_code: int
    url: str = ""
    redirect_urls: tuple[str, ...] = ()
    encoded_bytes: int | None = None
    decoded_bytes: int | None = None


@dataclass(frozen=True)
class _AdmittedHttpResponse:
    response: httpx.Response
    encoded_bytes: int
    decoded_bytes: int


class _ResponseDecoder(ABC):
    @abstractmethod
    def decode(self, data: bytes, *, maximum_output_bytes: int) -> bytes: ...

    @abstractmethod
    def flush(self, *, maximum_output_bytes: int) -> bytes: ...


class _IdentityResponseDecoder(_ResponseDecoder):
    def decode(self, data: bytes, *, maximum_output_bytes: int) -> bytes:
        return data[: maximum_output_bytes + 1]

    def flush(self, *, maximum_output_bytes: int) -> bytes:
        del maximum_output_bytes
        return b""


class _ZlibResponseDecoder(_ResponseDecoder):
    def __init__(self, *, gzip_encoded: bool) -> None:
        self._gzip_encoded = gzip_encoded
        self._first_attempt = True
        self._decompressor = self._new_decompressor(raw_deflate=False)

    def _new_decompressor(self, *, raw_deflate: bool) -> Any:
        if self._gzip_encoded:
            return zlib.decompressobj(zlib.MAX_WBITS | 16)
        if raw_deflate:
            return zlib.decompressobj(-zlib.MAX_WBITS)
        return zlib.decompressobj()

    def decode(self, data: bytes, *, maximum_output_bytes: int) -> bytes:
        was_first_attempt = self._first_attempt
        self._first_attempt = False
        try:
            return self._decode_limited(data, maximum_output_bytes)
        except zlib.error as exc:
            if was_first_attempt and not self._gzip_encoded:
                self._decompressor = self._new_decompressor(raw_deflate=True)
                return self.decode(data, maximum_output_bytes=maximum_output_bytes)
            raise httpx.DecodingError("Invalid compressed HTTP response") from exc

    def _decode_limited(self, data: bytes, maximum_output_bytes: int) -> bytes:
        admitted: list[bytes] = []
        admitted_bytes = 0
        pending = data
        while pending:
            maximum_chunk = maximum_output_bytes - admitted_bytes + 1
            decoded = self._decompressor.decompress(pending, maximum_chunk)
            admitted.append(decoded)
            admitted_bytes += len(decoded)
            if admitted_bytes > maximum_output_bytes:
                break
            pending = self._decompressor.unconsumed_tail
        return b"".join(admitted)

    def flush(self, *, maximum_output_bytes: int) -> bytes:
        try:
            decoded = self._decompressor.flush(maximum_output_bytes + 1)
        except zlib.error as exc:
            raise httpx.DecodingError("Invalid compressed HTTP response") from exc
        if (
            not self._decompressor.eof
            or self._decompressor.unconsumed_tail
            or self._decompressor.unused_data
        ):
            raise httpx.DecodingError("Incomplete or trailing compressed HTTP response")
        return decoded


def safe_exception_message(exc: Exception) -> str:
    """Format an exception for durable diagnostics without persisting raw input."""

    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__}: request failed"
    # Arbitrary exception messages can contain provider payload fragments, SQL
    # values, filesystem paths, or credentials. The concrete type remains an
    # actionable durable diagnostic; detailed context belongs in ephemeral,
    # operator-controlled debugging rather than the database.
    return type(exc).__name__


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
        "accept-encoding": "gzip, deflate",
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
) -> Callable[..., Coroutine[Any, Any, JsonResponseData]]:
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
) -> Callable[..., Coroutine[Any, Any, HttpResponseData]]:
    return _retrying_response_request(
        settings,
        parser=_parse_json_body,
        validator=_validate_json_body,
        default_namespace=DEFAULT_CACHE_NAMESPACE,
    )


def retrying_text_request(
    settings: OpenOppsSettings,
) -> Callable[..., Coroutine[Any, Any, str]]:
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
) -> Callable[..., Coroutine[Any, Any, HttpResponseData]]:
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
) -> Callable[..., Coroutine[Any, Any, HttpResponseData]]:
    cache = (
        HttpCache(settings.sqlite_path)
        if settings.cache_enabled and settings.sqlite_path is not None
        else None
    )
    inflight: dict[str, asyncio.Task[HttpResponseData]] = {}
    inflight_lock = asyncio.Lock()

    def _clear_inflight(
        request_key: str,
        completed: asyncio.Task[HttpResponseData],
    ) -> None:
        if inflight.get(request_key) is completed:
            inflight.pop(request_key, None)
        if not completed.cancelled():
            completed.exception()

    @retry(
        retry=retry_if_exception(_is_retryable_http_error),
        wait=wait_exponential_jitter(initial=0.25, max=8),
        stop=stop_after_attempt(settings.retry_attempts),
        before_sleep=_record_http_retry_before_sleep,
        reraise=True,
    )
    async def _request_upstream(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        response_byte_budget: ResponseByteBudget | None,
        **kwargs: Any,
    ) -> tuple[HttpResponseData | None, httpx.Response]:
        response = await _request_with_public_redirect_validation(
            client,
            method,
            url,
            stream_response=True,
            **kwargs,
        )
        if response.status_code == 304:
            await response.aclose()
            return None, response
        if response.status_code == 429:
            delay = _retry_after_seconds(response)
            await response.aclose()
            if delay is not None and delay > 0:
                await asyncio.sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
        try:
            response.raise_for_status()
        except Exception:
            await response.aclose()
            raise
        admitted = await _read_bounded_response(
            response,
            maximum_encoded_bytes=settings.http_max_encoded_response_bytes,
            maximum_decoded_bytes=settings.http_max_decoded_response_bytes,
            aggregate_budget=response_byte_budget,
        )
        response = admitted.response
        final_url = _sanitized_http_url(str(response.url))
        body = parser(response, final_url)
        return (
            HttpResponseData(
                body=body,
                headers=_response_headers(response),
                status_code=response.status_code,
                url=final_url,
                redirect_urls=_redirect_urls(response),
                encoded_bytes=admitted.encoded_bytes,
                decoded_bytes=admitted.decoded_bytes,
            ),
            response,
        )

    async def _request_impl(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        operation_budget: HttpOperationBudget | None,
        **kwargs: Any,
    ) -> HttpResponseData:
        operation_counters = _http_operation_counters()
        if operation_counters is not None:
            operation_counters.increment("logical_read_count")
        request_kwargs = dict(kwargs)
        namespace = str(request_kwargs.pop("cache_namespace", default_namespace))
        identity = _cache_identity(request_kwargs.pop("cache_identity", None))
        identity = _with_scoped_cache_identity(
            identity,
            _CURRENT_HTTP_CACHE_IDENTITY_SCOPE.get(),
        )
        ttl_seconds = int(
            request_kwargs.pop("cache_ttl_seconds", settings.cache_ttl_seconds)
        )
        refresh = bool(request_kwargs.pop("cache_refresh", settings.cache_refresh))
        stale_on_error = bool(
            request_kwargs.pop("cache_stale_on_error", settings.cache_stale_on_error)
        )
        enabled = bool(request_kwargs.pop("cache_enabled", settings.cache_enabled))
        explicit_response_byte_budget = request_kwargs.pop("response_byte_budget", None)
        if explicit_response_byte_budget is not None and not isinstance(
            explicit_response_byte_budget, ResponseByteBudget
        ):
            raise TypeError("response_byte_budget must be a ResponseByteBudget")
        if operation_budget is not None and explicit_response_byte_budget is not None:
            raise ValueError(
                "explicit response byte budgets cannot override an HTTP operation scope"
            )
        response_byte_budget = (
            operation_budget.response_byte_budget
            if operation_budget is not None
            else explicit_response_byte_budget
        )
        explicit_request_guard = request_kwargs.get("request_budget_guard")
        if explicit_request_guard is not None and not callable(explicit_request_guard):
            raise TypeError("request_budget_guard must be callable")
        if operation_budget is not None:
            operation_request_guard = operation_budget.begin_request()
            request_kwargs["request_budget_guard"] = _combine_request_budget_guards(
                operation_request_guard,
                explicit_request_guard,
            )
        request_cache = cache if enabled else None
        if operation_counters is not None and (request_cache is None or refresh):
            operation_counters.increment("cache_bypass_count")
        params = _mapping_or_none(request_kwargs.get("params"))
        json_body = request_kwargs.get("json")
        headers = _mapping_or_none(request_kwargs.get("headers"))
        identity = _with_credential_cache_identity(
            identity,
            _credential_cache_identity(client, request_kwargs),
        )
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
            if request_cache and not refresh and response_byte_budget is None
            else None
        )

        stale_hit = None
        if request_cache:
            if operation_budget is not None:
                operation_budget.ensure_open()
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
                if operation_counters is not None:
                    operation_counters.increment("cache_hit_count")
                if operation_budget is not None:
                    operation_budget.ensure_open()
                cached_result = _cached_response(
                    hit,
                    validator,
                    url,
                    maximum_encoded_bytes=settings.http_max_encoded_response_bytes,
                    maximum_decoded_bytes=settings.http_max_decoded_response_bytes,
                    response_byte_budget=response_byte_budget,
                )
                if operation_budget is not None:
                    operation_budget.ensure_open()
                return cached_result
            if not refresh:
                if operation_counters is not None:
                    operation_counters.increment("cache_miss_count")
                if operation_budget is not None:
                    operation_budget.ensure_open()
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
                if operation_budget is not None:
                    operation_budget.ensure_open()
                if stale_hit:
                    request_kwargs["headers"] = _conditional_headers(
                        request_kwargs.get("headers"),
                        stale_hit.etag,
                        stale_hit.last_modified,
                    )

        async def fetch_and_store() -> HttpResponseData:
            nonlocal stale_hit
            result, response = await _request_upstream(
                client,
                method,
                url,
                response_byte_budget=response_byte_budget,
                **request_kwargs,
            )
            if operation_budget is not None:
                operation_budget.ensure_open()
            if result is None:
                if request_cache and stale_hit is not None:
                    if operation_budget is not None:
                        operation_budget.ensure_open()
                    request_cache.refresh_json(
                        stale_hit.key,
                        ttl_seconds=ttl_seconds,
                        commit_guard=(
                            operation_budget.ensure_open
                            if operation_budget is not None
                            else None
                        ),
                    )
                    if operation_counters is not None:
                        operation_counters.increment("cache_revalidation_count")
                    if operation_budget is not None:
                        operation_budget.ensure_open()
                    cached_result = _cached_response(
                        stale_hit,
                        validator,
                        url,
                        maximum_encoded_bytes=settings.http_max_encoded_response_bytes,
                        maximum_decoded_bytes=settings.http_max_decoded_response_bytes,
                        response_byte_budget=response_byte_budget,
                    )
                    if operation_budget is not None:
                        operation_budget.ensure_open()
                    return cached_result
                raise ValueError(f"Received 304 without cached payload for {url}")
            if request_cache:
                if operation_budget is not None:
                    operation_budget.ensure_open()
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
                    commit_guard=(
                        operation_budget.ensure_open
                        if operation_budget is not None
                        else None
                    ),
                )
                if operation_counters is not None:
                    operation_counters.increment("cache_write_count")
            if operation_budget is not None:
                operation_budget.ensure_open()
            return result

        try:
            if request_key is None:
                return await fetch_and_store()
            async with inflight_lock:
                task = inflight.get(request_key)
                if task is None:
                    task = asyncio.create_task(fetch_and_store())
                    inflight[request_key] = task
                    task.add_done_callback(
                        lambda completed, key=request_key: _clear_inflight(
                            key, completed
                        )
                    )
            return await asyncio.shield(task)
        except Exception as exc:
            if operation_budget is not None:
                operation_budget.ensure_open()
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
                if operation_budget is not None:
                    operation_budget.ensure_open()
                if eligible_stale_hit is not None:
                    if operation_budget is not None:
                        operation_budget.ensure_open()
                    logger.warning(
                        "Using stale cache payload namespace={} key={} url={}",
                        namespace,
                        eligible_stale_hit.key,
                        url,
                    )
                    cached_result = _cached_response(
                        eligible_stale_hit,
                        validator,
                        url,
                        maximum_encoded_bytes=settings.http_max_encoded_response_bytes,
                        maximum_decoded_bytes=settings.http_max_decoded_response_bytes,
                        response_byte_budget=response_byte_budget,
                    )
                    if operation_counters is not None:
                        operation_counters.increment("cache_stale_fallback_count")
                    if operation_budget is not None:
                        operation_budget.ensure_open()
                    return cached_result
            raise

    async def _request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> HttpResponseData:
        operation_budget = _CURRENT_HTTP_OPERATION_BUDGET.get()
        if operation_budget is None:
            return await _request_impl(
                client,
                method,
                url,
                None,
                **kwargs,
            )
        with _track_http_operation_task(operation_budget):
            try:
                return await _request_impl(
                    client,
                    method,
                    url,
                    operation_budget,
                    **kwargs,
                )
            except (HttpRequestLimitError, HttpResponseLimitError) as exc:
                operation_budget._latch_limit_error(exc)
                raise

    return _request


def _combine_request_budget_guards(
    operation_guard: _HttpOperationRequestGuard,
    explicit_guard: RequestBudgetGuard | None,
) -> RequestBudgetGuard:
    if explicit_guard is None:
        return operation_guard
    return _CombinedRequestBudgetGuard(
        operation_guard=operation_guard,
        explicit_guard=explicit_guard,
    )


def _request_guard_binds_operation(
    guard: object,
    operation: HttpOperationBudget,
) -> bool:
    if isinstance(guard, _HttpOperationRequestGuard):
        return guard.operation is operation
    if isinstance(guard, _CombinedRequestBudgetGuard):
        return guard.operation_guard.operation is operation
    return False


async def request_with_public_redirect_validation(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    stream_response: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    operation_budget = _CURRENT_HTTP_OPERATION_BUDGET.get()
    if operation_budget is None:
        return await _request_with_public_redirect_validation_impl(
            client,
            method,
            url,
            stream_response=stream_response,
            **kwargs,
        )

    with _track_http_operation_task(operation_budget):
        request_kwargs = dict(kwargs)
        explicit_guard = request_kwargs.get("request_budget_guard")
        if explicit_guard is not None and not callable(explicit_guard):
            raise TypeError("request_budget_guard must be callable")
        if _request_guard_binds_operation(explicit_guard, operation_budget):
            operation_budget.ensure_open()
        else:
            operation_guard = operation_budget.begin_request()
            request_kwargs["request_budget_guard"] = _combine_request_budget_guards(
                operation_guard,
                explicit_guard,
            )
        response = await _request_with_public_redirect_validation_impl(
            client,
            method,
            url,
            stream_response=stream_response,
            **request_kwargs,
        )
        try:
            operation_budget.ensure_open()
        except HttpOperationClosedError:
            await response.aclose()
            raise
        return response


async def _request_with_public_redirect_validation_impl(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    stream_response: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    request_kwargs = dict(kwargs)
    follow_redirects = bool(request_kwargs.pop("follow_redirects", False))
    max_redirects = int(request_kwargs.pop("max_redirects", MAX_PUBLIC_REDIRECTS))
    request_budget_guard = request_kwargs.pop("request_budget_guard", None)
    if request_budget_guard is not None and not callable(request_budget_guard):
        raise TypeError("request_budget_guard must be callable")
    current_method = method
    current_url = url
    strip_client_credentials = False
    redirect_history: list[httpx.Response] = []
    redirect_urls: list[str] = []
    for redirect_count in range(max_redirects + 1):
        if request_budget_guard is not None:
            guarded = request_budget_guard(current_url, redirect_count > 0)
            if guarded is not None:
                await guarded
        await assert_public_fetch_url(current_url)
        response = await _send_public_request(
            client,
            current_method,
            current_url,
            request_kwargs,
            strip_client_credentials=strip_client_credentials,
            stream_response=stream_response,
        )
        if not follow_redirects or not response.is_redirect:
            response.history = list(redirect_history)
            response.extensions[_REDIRECT_URLS_EXTENSION] = tuple(redirect_urls)
            return response
        location = response.headers.get("location")
        if not location:
            response.history = list(redirect_history)
            response.extensions[_REDIRECT_URLS_EXTENSION] = tuple(redirect_urls)
            return response
        if redirect_count >= max_redirects:
            await response.aclose()
            raise httpx.TooManyRedirects(
                f"Exceeded {max_redirects} redirects for {url}",
                request=response.request,
            )
        if stream_response:
            await response.aclose()
        next_url = urljoin(str(response.url), location)
        redirect_urls.append(_sanitized_http_url(next_url))
        operation_counters = _http_operation_counters()
        if operation_counters is not None:
            operation_counters.increment("redirect_count")
        if _request_origin(current_url) != _request_origin(next_url):
            request_kwargs = _request_kwargs_without_cross_origin_credentials(
                request_kwargs
            )
            strip_client_credentials = True
        redirect_history.append(response)
        current_url = next_url
        if response.status_code == 303 or (
            response.status_code in {301, 302}
            and current_method.upper() not in {"GET", "HEAD"}
        ):
            current_method = "GET"
            request_kwargs = _request_kwargs_without_body(request_kwargs)
    raise httpx.TooManyRedirects(f"Exceeded {max_redirects} redirects for {url}")


# Private alias for in-module callers; external code must use the public name.
_request_with_public_redirect_validation = request_with_public_redirect_validation


async def _send_public_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    request_kwargs: dict[str, Any],
    *,
    strip_client_credentials: bool,
    stream_response: bool,
) -> httpx.Response:
    if not strip_client_credentials and not stream_response:
        operation_counters = _http_operation_counters()
        if operation_counters is not None:
            operation_counters.increment("request_count")
        return await client.request(
            method,
            url,
            **request_kwargs,
            follow_redirects=False,
        )

    build_kwargs = dict(request_kwargs)
    request_auth_provided = "auth" in build_kwargs
    request_auth = build_kwargs.pop("auth", None)
    if strip_client_credentials:
        build_kwargs.pop("cookies", None)
    request = client.build_request(method, url, **build_kwargs)
    if strip_client_credentials:
        _strip_sensitive_headers(request.headers)
        operation_counters = _http_operation_counters()
        if operation_counters is not None:
            operation_counters.increment("request_count")
        return await client.send(
            request,
            follow_redirects=False,
            auth=None,
            stream=stream_response,
        )
    if request_auth_provided:
        operation_counters = _http_operation_counters()
        if operation_counters is not None:
            operation_counters.increment("request_count")
        return await client.send(
            request,
            follow_redirects=False,
            auth=request_auth,
            stream=stream_response,
        )
    operation_counters = _http_operation_counters()
    if operation_counters is not None:
        operation_counters.increment("request_count")
    return await client.send(
        request,
        follow_redirects=False,
        stream=stream_response,
    )


async def _read_bounded_response(
    response: httpx.Response,
    *,
    maximum_encoded_bytes: int,
    maximum_decoded_bytes: int,
    aggregate_budget: ResponseByteBudget | None,
) -> _AdmittedHttpResponse:
    """Read one HTTPX response under independent wire and decoded ceilings."""

    operation_budget = _CURRENT_HTTP_OPERATION_BUDGET.get()
    if operation_budget is not None:
        operation_budget.ensure_open()

    declared_length = _declared_content_length(response.headers)
    if declared_length is not None and declared_length > maximum_encoded_bytes:
        await response.aclose()
        raise HttpResponseLimitError(
            "declared_encoded",
            limit_bytes=maximum_encoded_bytes,
            observed_bytes=declared_length,
        )

    if response.is_stream_consumed:
        try:
            if operation_budget is not None:
                operation_budget.ensure_open()
            body = response.content
            encoded_bytes = (
                declared_length if declared_length is not None else len(body)
            )
            decoded_bytes = len(body)
            _record_http_response_bytes(
                encoded_bytes=encoded_bytes,
                decoded_bytes=decoded_bytes,
            )
            if encoded_bytes > maximum_encoded_bytes:
                raise HttpResponseLimitError(
                    "encoded",
                    limit_bytes=maximum_encoded_bytes,
                    observed_bytes=encoded_bytes,
                )
            if decoded_bytes > maximum_decoded_bytes:
                raise HttpResponseLimitError(
                    "decoded",
                    limit_bytes=maximum_decoded_bytes,
                    observed_bytes=decoded_bytes,
                )
            if aggregate_budget is not None:
                aggregate_budget.admit(decoded_bytes)
            if operation_budget is not None:
                operation_budget.ensure_open()
            buffered = _buffered_response(response, body)
            return _AdmittedHttpResponse(
                response=buffered,
                encoded_bytes=encoded_bytes,
                decoded_bytes=decoded_bytes,
            )
        finally:
            await response.aclose()

    try:
        decoder = _response_decoder(response)
    except Exception:
        await response.aclose()
        raise
    encoded_bytes = 0
    decoded_bytes = 0
    body_parts: list[bytes] = []

    def admit_decoded(data: bytes) -> None:
        nonlocal decoded_bytes
        observed = decoded_bytes + len(data)
        _record_http_response_bytes(encoded_bytes=0, decoded_bytes=len(data))
        if observed > maximum_decoded_bytes:
            raise HttpResponseLimitError(
                "decoded",
                limit_bytes=maximum_decoded_bytes,
                observed_bytes=observed,
            )
        if aggregate_budget is not None:
            aggregate_budget.admit(len(data))
        decoded_bytes = observed
        body_parts.append(data)

    try:
        async for chunk in response.aiter_raw():
            if operation_budget is not None:
                operation_budget.ensure_open()
            encoded_bytes += len(chunk)
            _record_http_response_bytes(encoded_bytes=len(chunk), decoded_bytes=0)
            if encoded_bytes > maximum_encoded_bytes:
                raise HttpResponseLimitError(
                    "encoded",
                    limit_bytes=maximum_encoded_bytes,
                    observed_bytes=encoded_bytes,
                )
            output_limit = maximum_decoded_bytes - decoded_bytes
            if aggregate_budget is not None:
                output_limit = min(output_limit, aggregate_budget.remaining_bytes)
            decoded = decoder.decode(chunk, maximum_output_bytes=output_limit)
            admit_decoded(decoded)

        if operation_budget is not None:
            operation_budget.ensure_open()
        output_limit = maximum_decoded_bytes - decoded_bytes
        if aggregate_budget is not None:
            output_limit = min(output_limit, aggregate_budget.remaining_bytes)
        admit_decoded(decoder.flush(maximum_output_bytes=output_limit))
        if operation_budget is not None:
            operation_budget.ensure_open()
    finally:
        await response.aclose()

    buffered = _buffered_response(response, b"".join(body_parts))
    return _AdmittedHttpResponse(
        response=buffered,
        encoded_bytes=encoded_bytes,
        decoded_bytes=decoded_bytes,
    )


def _buffered_response(response: httpx.Response, body: bytes) -> httpx.Response:
    wire_headers = httpx.Headers(response.headers)
    decoded_headers = httpx.Headers(wire_headers)
    decoded_headers.pop("content-encoding", None)
    decoded_headers["content-length"] = str(len(body))
    buffered = httpx.Response(
        response.status_code,
        headers=decoded_headers,
        content=body,
        request=response.request,
        extensions=dict(response.extensions),
        history=list(response.history),
    )
    buffered.headers.clear()
    buffered.headers.update(wire_headers)
    return buffered


def _declared_content_length(headers: httpx.Headers) -> int | None:
    raw_length = headers.get("content-length")
    if raw_length is None:
        return None
    stripped = raw_length.strip()
    if not stripped.isdecimal():
        return None
    return int(stripped)


def _response_decoder(response: httpx.Response) -> _ResponseDecoder:
    encodings = [
        item.strip().lower()
        for item in response.headers.get("content-encoding", "").split(",")
        if item.strip() and item.strip().lower() != "identity"
    ]
    if not encodings:
        return _IdentityResponseDecoder()
    if encodings == ["gzip"]:
        return _ZlibResponseDecoder(gzip_encoded=True)
    if encodings == ["deflate"]:
        return _ZlibResponseDecoder(gzip_encoded=False)
    raise httpx.DecodingError(
        "Unsupported HTTP response content encoding",
        request=response.request,
    )


def _sanitized_http_url(url: str) -> str:
    try:
        parsed = httpx.URL(url)
    except (TypeError, ValueError):
        return ""
    return str(
        parsed.copy_with(
            username=None,
            password=None,
            query=None,
            fragment=None,
        )
    )


def _redirect_urls(response: httpx.Response) -> tuple[str, ...]:
    raw_urls = response.extensions.get(_REDIRECT_URLS_EXTENSION, ())
    if not isinstance(raw_urls, (list, tuple)):
        return ()
    sanitized = (_sanitized_http_url(str(item)) for item in raw_urls)
    return tuple(item for item in sanitized if item)


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

    try:
        validate_public_https_url(url)
        parsed = urlparse(url)
        host = parsed.hostname
        if host is None:
            raise ValueError("URL must include a host")
        await _assert_global_routable_dns(host, parsed.port or 443)
    except PublicFetchSafetyError:
        raise
    except ValueError as exc:
        raise PublicFetchSafetyError(str(exc)) from exc
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


def _request_kwargs_without_cross_origin_credentials(
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    next_kwargs = _request_kwargs_without_sensitive_headers(kwargs)
    if next_kwargs is kwargs:
        next_kwargs = dict(kwargs)
    next_kwargs.pop("auth", None)
    next_kwargs.pop("cookies", None)
    return next_kwargs


def _strip_sensitive_headers(headers: httpx.Headers) -> None:
    for header in _CROSS_ORIGIN_SENSITIVE_HEADERS:
        headers.pop(header, None)


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
    return cast(JsonResponseData, value)


def _validate_text_body(value: object, url: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Cached text payload for {url} is invalid")
    return value


def _cache_response_payload(response: HttpResponseData) -> dict[str, Any]:
    return {
        _RESPONSE_CACHE_MARKER: {
            "body": response.body,
            "headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower() in _CACHEABLE_RESPONSE_HEADERS
            },
            "status_code": response.status_code,
            "url": response.url,
            "redirect_urls": list(response.redirect_urls),
            "encoded_bytes": response.encoded_bytes,
            "decoded_bytes": response.decoded_bytes,
        }
    }


def _cached_response(
    hit: Any,
    validator: Callable[[object, str], HttpResponseBody],
    url: str,
    *,
    maximum_encoded_bytes: int,
    maximum_decoded_bytes: int,
    response_byte_budget: ResponseByteBudget | None,
) -> HttpResponseData:
    data = hit.data
    response: HttpResponseData
    if isinstance(data, dict) and set(data) == {_RESPONSE_CACHE_MARKER}:
        wrapped = data.get(_RESPONSE_CACHE_MARKER)
        if isinstance(wrapped, dict) and "body" in wrapped:
            body = validator(wrapped.get("body"), url)
            headers = _string_dict(wrapped.get("headers"))
            status_code = _int_or_default(wrapped.get("status_code"), hit.status_code)
            response_url = _sanitized_http_url(str(wrapped.get("url") or url))
            response = HttpResponseData(
                body=body,
                headers=headers,
                status_code=status_code,
                url=response_url or _sanitized_http_url(url),
                redirect_urls=_sanitized_url_tuple(wrapped.get("redirect_urls")),
                encoded_bytes=_optional_non_negative_int(wrapped.get("encoded_bytes")),
                decoded_bytes=_optional_non_negative_int(wrapped.get("decoded_bytes")),
            )
        else:
            response = _legacy_cached_response(hit, validator, url)
    else:
        response = _legacy_cached_response(hit, validator, url)
    _admit_cached_response(
        response,
        maximum_encoded_bytes=maximum_encoded_bytes,
        maximum_decoded_bytes=maximum_decoded_bytes,
        response_byte_budget=response_byte_budget,
    )
    return response


def _legacy_cached_response(
    hit: Any,
    validator: Callable[[object, str], HttpResponseBody],
    url: str,
) -> HttpResponseData:
    headers = {
        key: value
        for key, value in {
            "etag": hit.etag,
            "last-modified": hit.last_modified,
        }.items()
        if value
    }
    return HttpResponseData(
        body=validator(hit.data, url),
        headers=headers,
        status_code=int(hit.status_code),
        url=_sanitized_http_url(url),
    )


def _admit_cached_response(
    response: HttpResponseData,
    *,
    maximum_encoded_bytes: int,
    maximum_decoded_bytes: int,
    response_byte_budget: ResponseByteBudget | None,
) -> None:
    measured_bytes = _cached_body_size(response.body)
    encoded_bytes = (
        response.encoded_bytes if response.encoded_bytes is not None else measured_bytes
    )
    decoded_bytes = max(response.decoded_bytes or 0, measured_bytes)
    _record_http_response_bytes(encoded_bytes=0, decoded_bytes=decoded_bytes)
    if encoded_bytes > maximum_encoded_bytes:
        raise HttpResponseLimitError(
            "encoded",
            limit_bytes=maximum_encoded_bytes,
            observed_bytes=encoded_bytes,
        )
    if decoded_bytes > maximum_decoded_bytes:
        raise HttpResponseLimitError(
            "decoded",
            limit_bytes=maximum_decoded_bytes,
            observed_bytes=decoded_bytes,
        )
    if response_byte_budget is not None:
        response_byte_budget.admit(decoded_bytes)


def _cached_body_size(body: HttpResponseBody) -> int:
    if isinstance(body, str):
        return len(body.encode("utf-8"))
    return len(json.dumps(body, ensure_ascii=True, sort_keys=True).encode("utf-8"))


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


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _sanitized_url_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    sanitized = (_sanitized_http_url(str(item)) for item in value)
    return tuple(item for item in sanitized if item)


def _record_http_retry_before_sleep(retry_state: RetryCallState) -> None:
    """Increment the bound HTTP snapshot, or SyncMetrics when no collector exists."""

    del retry_state
    operation_counters = _http_operation_counters()
    if operation_counters is not None:
        operation_counters.increment("retry_count")
        return
    record_http_retry()


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


def _with_credential_cache_identity(
    identity: dict[str, Any] | None,
    credentials: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not credentials:
        return identity
    merged = dict(identity or {})
    merged[_CREDENTIAL_CACHE_IDENTITY_KEY] = credentials
    return merged


def _with_scoped_cache_identity(
    identity: dict[str, Any] | None,
    scoped_identity: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not scoped_identity:
        return identity
    merged = dict(identity or {})
    if _SCOPED_CACHE_IDENTITY_KEY in merged:
        raise ValueError(
            f"cache_identity key {_SCOPED_CACHE_IDENTITY_KEY!r} is reserved"
        )
    merged[_SCOPED_CACHE_IDENTITY_KEY] = {
        str(key): item for key, item in scoped_identity.items()
    }
    return merged


def _credential_cache_identity(
    client: object,
    request_kwargs: dict[str, Any],
) -> dict[str, Any] | None:
    credentials: dict[str, Any] = {}
    headers = _mapping_or_none(request_kwargs.get("headers"))
    header_credentials = _credential_header_identity(headers)
    if header_credentials:
        credentials["headers"] = header_credentials
    if "auth" in request_kwargs:
        auth = request_kwargs.get("auth")
        if auth is not None:
            credentials["requestAuthSha256"] = _credential_fingerprint(auth)
    else:
        client_auth = getattr(client, "auth", None)
        if client_auth is not None:
            credentials["clientAuthSha256"] = _credential_fingerprint(client_auth)
    if request_kwargs.get("cookies"):
        credentials["requestCookiesSha256"] = _credential_fingerprint(
            request_kwargs["cookies"]
        )
    client_cookies = _client_cookie_identity(client)
    if client_cookies:
        credentials["clientCookies"] = client_cookies
    return credentials or None


def _credential_header_identity(
    headers: dict[str, Any] | None,
) -> dict[str, str]:
    if not headers:
        return {}
    return {
        key.lower(): _credential_fingerprint(value)
        for key, value in sorted(headers.items())
        if key.lower() in _CROSS_ORIGIN_SENSITIVE_HEADERS
    }


def _client_cookie_identity(client: object) -> list[dict[str, str]]:
    cookies = getattr(client, "cookies", None)
    jar = getattr(cookies, "jar", None)
    if jar is None:
        return []
    return sorted(
        (
            {
                "domain": str(cookie.domain or ""),
                "name": str(cookie.name),
                "path": str(cookie.path or ""),
                "valueSha256": _credential_fingerprint(cookie.value),
            }
            for cookie in jar
        ),
        key=lambda item: (item["domain"], item["path"], item["name"]),
    )


def _credential_fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


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
