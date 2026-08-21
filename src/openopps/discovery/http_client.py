"""Credential-free HTTP runtime for the quarantined discovery scout.

This module is intentionally independent from the application's runtime cache,
provider registry, and plugin loader.  It composes the policy-only primitives in
``openopps.discovery.transport`` with the documented HTTPX custom-transport and
HTTPCore custom-network-backend APIs.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
import ipaddress
import math
import re
import ssl
import time
from types import MappingProxyType
from types import TracebackType
from typing import Any, Literal, cast

import anyio
import certifi
import httpcore
import httpx

from openopps.discovery.transport import (
    AdmittedResponse,
    ByteBudget,
    ContentLimits,
    DiscoveryTransportError,
    RedirectPolicy,
    RequestBudgetLedger,
    RequestBudgetSnapshot,
    ResponseChunk,
    ResponseHead,
    SafeLocator,
    ScoutRequest,
    VerifiedObservation,
    bounded_retry_delay_ms,
    prepare_redirect,
    read_bounded_response,
    resolve_public_addresses,
    safe_transport_diagnostic,
    select_verified_reuse,
    validate_public_locator,
)


Resolver = Callable[[str], Awaitable[tuple[str, ...]]]
MonotonicClock = Callable[[], int]
WallClock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
SocketOption = (
    tuple[int, int, int]
    | tuple[int, int, bytes | bytearray]
    | tuple[int, int, None, int]
)

_CONDITIONAL_EXTENSION = "openopps.discovery.conditional"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ETAG_RE = re.compile(r'(?:W/)?"[\x21\x23-\x7e]*"')
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_ALLOWED_RESPONSE_HEADERS = frozenset(
    {
        b"content-disposition",
        b"content-encoding",
        b"content-length",
        b"content-type",
        b"etag",
        b"last-modified",
        b"location",
        b"ratelimit-limit",
        b"ratelimit-remaining",
        b"ratelimit-reset",
        b"retry-after",
        b"x-ratelimit-limit",
        b"x-ratelimit-remaining",
        b"x-ratelimit-reset",
    }
)
_MAX_RESPONSE_HEADER_VALUE_BYTES = 2_048
_MAX_RESPONSE_METADATA_BYTES = 8_192
_OUTGOING_HEADERS = (
    (b"Accept", b"application/json, application/xml, text/html, text/plain"),
    (b"Accept-Encoding", b"identity"),
    (b"User-Agent", b"OpenOpps-Discovery/1"),
)


def _strict_positive(value: int, reason_code: str, *, maximum: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise DiscoveryTransportError(reason_code)


def _strict_non_negative(value: int, reason_code: str, *, maximum: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > maximum
    ):
        raise DiscoveryTransportError(reason_code)


def _default_monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _default_wall_clock() -> datetime:
    return datetime.now(UTC)


def _strict_ssl_context() -> ssl.SSLContext:
    """Build a CA-verifying context without ambient certificate-path inputs."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=certifi.where())
    return context


def _safe_peer_address(value: object) -> tuple[str, int] | None:
    if isinstance(value, str):
        raw_address = value
        raw_port = 443
    elif (
        isinstance(value, tuple)
        and len(value) >= 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    ):
        raw_address = value[0]
        raw_port = value[1]
    else:
        return None
    if "%" in raw_address:
        return None
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError:
        return None
    return str(address), raw_port


class _PinnedNetworkStream(httpcore.AsyncNetworkStream):
    """Delegate I/O while enforcing peer identity and original-host TLS SNI."""

    def __init__(
        self,
        stream: httpcore.AsyncNetworkStream,
        *,
        expected_address: str,
        expected_port: int,
        expected_server_hostname: str,
    ) -> None:
        self._stream = stream
        self._expected_address = expected_address
        self._expected_port = expected_port
        self._expected_server_hostname = expected_server_hostname

    def peer_matches(self) -> bool:
        peer = _safe_peer_address(self._stream.get_extra_info("server_addr"))
        return peer == (self._expected_address, self._expected_port)

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(max_bytes, timeout=timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._stream.write(buffer, timeout=timeout)

    async def aclose(self) -> None:
        await self._stream.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if server_hostname != self._expected_server_hostname:
            await self._stream.aclose()
            raise DiscoveryTransportError("tls_server_hostname")
        upgraded = await self._stream.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            timeout=timeout,
        )
        wrapped = _PinnedNetworkStream(
            upgraded,
            expected_address=self._expected_address,
            expected_port=self._expected_port,
            expected_server_hostname=self._expected_server_hostname,
        )
        if not wrapped.peer_matches():
            await upgraded.aclose()
            raise DiscoveryTransportError("peer_address_mismatch")
        return wrapped

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)


class PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, connect by admitted IP, and preserve the original host."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        delegate: httpcore.AsyncNetworkBackend,
        sleeper: Sleeper = anyio.sleep,
    ) -> None:
        self._resolver = resolver
        self._delegate = delegate
        self._sleeper = sleeper

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if port != 443 or local_address is not None or socket_options is not None:
            raise DiscoveryTransportError("connect_configuration")
        locator = validate_public_locator(f"https://{host}/")
        if locator.hostname != host:
            raise DiscoveryTransportError("connect_hostname")
        address_set = await resolve_public_addresses(locator, resolver=self._resolver)
        selected_address = address_set.addresses[0]
        stream = await self._delegate.connect_tcp(
            selected_address,
            port,
            timeout=timeout,
            local_address=None,
            socket_options=None,
        )
        wrapped = _PinnedNetworkStream(
            stream,
            expected_address=selected_address,
            expected_port=port,
            expected_server_hostname=locator.hostname,
        )
        if not wrapped.peer_matches():
            await stream.aclose()
            raise DiscoveryTransportError("peer_address_mismatch")
        return wrapped

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise DiscoveryTransportError("unix_socket_forbidden")

    async def sleep(self, seconds: float) -> None:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise DiscoveryTransportError("backend_sleep")
        await self._sleeper(float(seconds))


@dataclass(frozen=True, slots=True)
class HttpTimeouts:
    connect_seconds: int = 10
    read_seconds: int = 15
    write_seconds: int = 10
    pool_seconds: int = 10

    def __post_init__(self) -> None:
        for value in (
            self.connect_seconds,
            self.read_seconds,
            self.write_seconds,
            self.pool_seconds,
        ):
            _strict_positive(value, "http_timeout", maximum=300)

    def as_httpcore_extension(self) -> dict[str, float]:
        return {
            "connect": float(self.connect_seconds),
            "read": float(self.read_seconds),
            "write": float(self.write_seconds),
            "pool": float(self.pool_seconds),
        }


@dataclass(frozen=True, slots=True)
class _VerifiedConditionalRequest:
    observation: VerifiedObservation
    requested_locator_url: str
    headers: tuple[tuple[bytes, bytes], ...]


def _translate_httpcore_error(error: Exception) -> DiscoveryTransportError:
    if isinstance(error, httpcore.TimeoutException):
        return DiscoveryTransportError("request_timeout")
    if isinstance(error, httpcore.NetworkError):
        return DiscoveryTransportError("network_failure")
    if isinstance(error, httpcore.ProtocolError):
        return DiscoveryTransportError("protocol_failure")
    if isinstance(error, httpcore.ProxyError):
        return DiscoveryTransportError("proxy_forbidden")
    if isinstance(error, DiscoveryTransportError):
        return error
    return DiscoveryTransportError("transport_failure")


class _CoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._stream:
                yield chunk
        except Exception as error:
            raise _translate_httpcore_error(error) from None

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


def _allowlisted_response_headers(
    headers: list[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    admitted: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()
    total_bytes = 0
    for raw_name, raw_value in headers:
        name = raw_name.lower()
        if name not in _ALLOWED_RESPONSE_HEADERS:
            continue
        if name in seen:
            raise DiscoveryTransportError("response_header_duplicate")
        if (
            len(raw_value) > _MAX_RESPONSE_HEADER_VALUE_BYTES
            or any(byte < 0x20 and byte != 0x09 for byte in raw_value)
            or b"\x7f" in raw_value
        ):
            raise DiscoveryTransportError("response_header_value")
        try:
            raw_value.decode("ascii")
        except UnicodeDecodeError:
            raise DiscoveryTransportError("response_header_value") from None
        total_bytes += len(name) + len(raw_value)
        if total_bytes > _MAX_RESPONSE_METADATA_BYTES:
            raise DiscoveryTransportError("response_metadata_limit")
        seen.add(name)
        admitted.append((name, raw_value))
    return admitted


class PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX transport backed only by a public HTTPCore connection pool API."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        sleeper: Sleeper = anyio.sleep,
        max_connections: int = 8,
        timeouts: HttpTimeouts = HttpTimeouts(),
    ) -> None:
        _strict_positive(max_connections, "connection_limit", maximum=128)
        delegate = cast(
            httpcore.AsyncNetworkBackend,
            network_backend if network_backend is not None else httpcore.AnyIOBackend(),
        )
        self._network_backend = PinnedAsyncNetworkBackend(
            resolver=resolver,
            delegate=delegate,
            sleeper=sleeper,
        )
        self._timeouts = timeouts
        self._connection_pool = httpcore.AsyncConnectionPool(
            ssl_context=_strict_ssl_context(),
            proxy=None,
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=15.0,
            http1=True,
            http2=False,
            retries=0,
            local_address=None,
            uds=None,
            network_backend=self._network_backend,
            socket_options=None,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise DiscoveryTransportError("request_method")
        locator = validate_public_locator(str(request.url))
        safe_url = httpx.URL(locator.url)
        headers = [(b"Host", locator.hostname.encode("ascii")), *_OUTGOING_HEADERS]
        conditional = request.extensions.get(_CONDITIONAL_EXTENSION)
        if conditional is not None:
            if not isinstance(conditional, _VerifiedConditionalRequest):
                raise DiscoveryTransportError("conditional_evidence")
            if conditional.requested_locator_url != locator.url:
                raise DiscoveryTransportError("conditional_locator_identity")
            headers.extend(conditional.headers)
        core_request = httpcore.Request(
            method=b"GET",
            url=httpcore.URL(
                scheme=b"https",
                host=locator.hostname.encode("ascii"),
                port=443,
                target=safe_url.raw_path,
            ),
            headers=headers,
            content=b"",
            extensions={"timeout": self._timeouts.as_httpcore_extension()},
        )
        try:
            response = await self._connection_pool.handle_async_request(core_request)
        except Exception as error:
            raise _translate_httpcore_error(error) from None
        try:
            admitted_headers = _allowlisted_response_headers(response.headers)
            if not 100 <= response.status <= 599:
                raise DiscoveryTransportError("response_status")
        except Exception:
            await response.aclose()
            raise
        if not isinstance(response.stream, AsyncIterable):
            await response.aclose()
            raise DiscoveryTransportError("response_stream")
        return httpx.Response(
            status_code=response.status,
            headers=admitted_headers,
            stream=_CoreResponseStream(response.stream),
            extensions={},
        )

    async def aclose(self) -> None:
        await self._connection_pool.aclose()


@dataclass(frozen=True, slots=True)
class DiscoveryHttpLimits:
    """Finite trusted limits shared by one discovery HTTP runtime."""

    request_limit: int = 100
    origin_limit: int = 25
    concurrency_limit: int = 8
    per_origin_concurrency_limit: int = 2
    retry_limit: int = 20
    redirect_limit: int = 5
    pagination_limit: int = 20
    wall_clock_limit_ms: int = 120_000
    aggregate_byte_limit: int = 67_108_864
    max_attempts_per_resource: int = 3
    retry_base_delay_ms: int = 250
    max_retry_delay_ms: int = 5_000
    min_origin_interval_ms: int = 100
    circuit_failure_threshold: int = 3
    circuit_cooldown_ms: int = 30_000
    verified_evidence_max_age_ms: int = 86_400_000

    def __post_init__(self) -> None:
        bounded_values = (
            (self.request_limit, "request_limit", 20_000),
            (self.origin_limit, "origin_limit", 500),
            (self.concurrency_limit, "concurrency_limit", 128),
            (
                self.per_origin_concurrency_limit,
                "origin_concurrency_limit",
                16,
            ),
            (self.retry_limit, "retry_limit", 20_000),
            (self.redirect_limit, "redirect_limit", 10),
            (self.pagination_limit, "pagination_limit", 1_000),
            (self.wall_clock_limit_ms, "wall_clock_limit", 3_600_000),
            (self.aggregate_byte_limit, "aggregate_byte_limit", 1_073_741_824),
            (self.max_attempts_per_resource, "attempt_limit", 10),
            (self.retry_base_delay_ms, "retry_base_delay", 60_000),
            (self.max_retry_delay_ms, "retry_delay_limit", 300_000),
            (self.circuit_failure_threshold, "circuit_threshold", 100),
            (self.circuit_cooldown_ms, "circuit_cooldown", 3_600_000),
            (
                self.verified_evidence_max_age_ms,
                "verified_evidence_age",
                604_800_000,
            ),
        )
        for value, reason_code, maximum in bounded_values:
            _strict_positive(value, reason_code, maximum=maximum)
        _strict_non_negative(
            self.min_origin_interval_ms,
            "origin_interval",
            maximum=60_000,
        )
        if self.concurrency_limit > self.request_limit:
            raise DiscoveryTransportError("concurrency_limit")
        if self.per_origin_concurrency_limit > self.concurrency_limit:
            raise DiscoveryTransportError("origin_concurrency_limit")
        if self.retry_base_delay_ms > self.max_retry_delay_ms:
            raise DiscoveryTransportError("retry_delay_limit")


@dataclass(frozen=True, slots=True)
class HttpAttemptReceipt:
    attempt_number: int
    attempt_kind: Literal["initial", "pagination", "redirect", "retry"]
    outcome: Literal[
        "blocked",
        "cancelled",
        "failed",
        "rate_limited",
        "succeeded",
        "timed_out",
    ]
    status_code: int | None
    admitted_bytes: int


@dataclass(frozen=True, slots=True)
class HttpFailureReceipt:
    reason_code: str
    status_code: int | None
    attempts: tuple[HttpAttemptReceipt, ...]
    request_budget: RequestBudgetSnapshot


class DiscoveryHttpRuntimeError(DiscoveryTransportError):
    """Bounded runtime failure carrying a value-safe accounting receipt."""

    def __init__(self, receipt: HttpFailureReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.reason_code)


@dataclass(frozen=True, slots=True)
class DiscoveryHttpResult:
    status_code: int
    final_locator: SafeLocator
    redirect_history: tuple[str, ...]
    body: bytes
    encoded_bytes: int
    decoded_bytes: int
    media_type: str | None
    content_sha256: str
    secret_detector_version: str
    evidence_state: Literal["fetched", "not_modified"]
    response_metadata: Mapping[str, str]
    attempts: tuple[HttpAttemptReceipt, ...]
    request_budget: RequestBudgetSnapshot


@dataclass(slots=True)
class _CircuitState:
    consecutive_failures: int = 0
    open_until_ms: int = 0


def _normalized_metadata(response: httpx.Response) -> Mapping[str, str]:
    values = {key.lower(): value for key, value in response.headers.items()}
    return MappingProxyType(dict(sorted(values.items())))


def _conditional_request(
    observation: VerifiedObservation,
    *,
    requested_locator: SafeLocator,
    profile_id: str,
    profile_version: str,
    profile_digest: str,
    configuration_sha256: str,
    now: datetime,
    max_age: timedelta,
) -> _VerifiedConditionalRequest | None:
    if (
        observation.requested_locator_url != requested_locator.url
        or observation.profile_id != profile_id
        or observation.profile_version != profile_version
        or observation.profile_digest != profile_digest
        or observation.configuration_sha256 != configuration_sha256
    ):
        return None
    if _SHA256_RE.fullmatch(observation.manifest_id) is None:
        raise DiscoveryTransportError("verified_manifest_id")
    admitted = select_verified_reuse(observation, now=now, max_age=max_age)
    if admitted is None:
        raise DiscoveryTransportError("verified_evidence_stale")
    headers: list[tuple[bytes, bytes]] = []
    if admitted.etag is not None:
        if _ETAG_RE.fullmatch(admitted.etag) is None or len(admitted.etag) > 512:
            raise DiscoveryTransportError("verified_etag")
        headers.append((b"If-None-Match", admitted.etag.encode("ascii")))
    if admitted.last_modified is not None:
        if len(admitted.last_modified) > 128:
            raise DiscoveryTransportError("verified_last_modified")
        try:
            parsed = parsedate_to_datetime(admitted.last_modified)
        except (TypeError, ValueError, OverflowError):
            raise DiscoveryTransportError("verified_last_modified") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DiscoveryTransportError("verified_last_modified")
        canonical = format_datetime(parsed.astimezone(UTC), usegmt=True)
        headers.append((b"If-Modified-Since", canonical.encode("ascii")))
    if not headers:
        raise DiscoveryTransportError("conditional_validator_missing")
    return _VerifiedConditionalRequest(admitted, requested_locator.url, tuple(headers))


class DiscoveryHttpRuntime:
    """Manual redirect/retry runtime with one shared immutable-limit ledger."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        content_limits: ContentLimits,
        redirect_policy: RedirectPolicy,
        profile_id: str,
        profile_version: str,
        profile_digest: str,
        configuration_sha256: str,
        limits: DiscoveryHttpLimits = DiscoveryHttpLimits(),
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        monotonic_clock: MonotonicClock = _default_monotonic_ms,
        wall_clock: WallClock = _default_wall_clock,
        sleeper: Sleeper = anyio.sleep,
        timeouts: HttpTimeouts = HttpTimeouts(),
    ) -> None:
        if redirect_policy.max_hops != limits.redirect_limit:
            raise DiscoveryTransportError("redirect_limit_mismatch")
        if (
            not isinstance(profile_id, str)
            or not profile_id
            or profile_id != profile_id.strip()
            or len(profile_id) > 200
        ):
            raise DiscoveryTransportError("profile_identity")
        if (
            not isinstance(profile_version, str)
            or not profile_version
            or profile_version != profile_version.strip()
            or len(profile_version) > 100
        ):
            raise DiscoveryTransportError("profile_identity")
        if (
            not isinstance(profile_digest, str)
            or _SHA256_RE.fullmatch(profile_digest) is None
        ):
            raise DiscoveryTransportError("profile_identity")
        if (
            not isinstance(configuration_sha256, str)
            or _SHA256_RE.fullmatch(configuration_sha256) is None
        ):
            raise DiscoveryTransportError("configuration_identity")
        self._limits = limits
        self._content_limits = content_limits
        self._redirect_policy = redirect_policy
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper
        self._profile_id = profile_id
        self._profile_version = profile_version
        self._profile_digest = profile_digest
        self._configuration_sha256 = configuration_sha256
        started_ms = self._now_ms()
        self._deadline_ms = started_ms + limits.wall_clock_limit_ms
        self._request_budget = RequestBudgetLedger(
            request_limit=limits.request_limit,
            origin_limit=limits.origin_limit,
            max_in_flight=limits.concurrency_limit,
            per_origin_in_flight_limit=limits.per_origin_concurrency_limit,
            retry_limit=limits.retry_limit,
            redirect_limit=limits.redirect_limit,
            pagination_limit=limits.pagination_limit,
            deadline_ms=self._deadline_ms,
        )
        self._byte_budget = ByteBudget(limit=limits.aggregate_byte_limit)
        self._transport = PinnedAsyncHTTPTransport(
            resolver=resolver,
            network_backend=network_backend,
            sleeper=sleeper,
            max_connections=limits.concurrency_limit,
            timeouts=timeouts,
        )
        self._client = httpx.AsyncClient(
            auth=None,
            cookies=None,
            headers={},
            follow_redirects=False,
            transport=self._transport,
            trust_env=False,
        )
        self._client.headers.clear()
        self._client.cookies.clear()
        self._state_lock = anyio.Lock()
        self._global_concurrency = anyio.Semaphore(limits.concurrency_limit)
        self._origin_concurrency: dict[str, anyio.Semaphore] = {}
        self._next_origin_at_ms: dict[str, int] = {}
        self._circuits: dict[str, _CircuitState] = {}

    def _now_ms(self) -> int:
        value = self._monotonic_clock()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DiscoveryTransportError("monotonic_clock")
        return value

    def budget_snapshot(self) -> RequestBudgetSnapshot:
        return self._request_budget.snapshot()

    async def _acquire_concurrency(self, origin: str) -> anyio.Semaphore:
        """Acquire the stricter per-origin and global slots without leaking either."""

        async with self._state_lock:
            origin_semaphore = self._origin_concurrency.get(origin)
            if origin_semaphore is None:
                origin_semaphore = anyio.Semaphore(
                    self._limits.per_origin_concurrency_limit
                )
                self._origin_concurrency[origin] = origin_semaphore
        try:
            with anyio.fail_after(self._remaining_seconds()):
                await origin_semaphore.acquire()
                try:
                    await self._global_concurrency.acquire()
                except BaseException:
                    origin_semaphore.release()
                    raise
        except TimeoutError:
            raise DiscoveryTransportError("deadline_exhausted") from None
        return origin_semaphore

    def _release_concurrency(self, origin_semaphore: anyio.Semaphore) -> None:
        self._global_concurrency.release()
        origin_semaphore.release()

    def _remaining_seconds(self) -> float:
        remaining_ms = self._deadline_ms - self._now_ms()
        if remaining_ms <= 0:
            raise DiscoveryTransportError("deadline_exhausted")
        return remaining_ms / 1_000

    async def __aenter__(self) -> DiscoveryHttpRuntime:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_value, traceback)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _failure(
        self,
        reason_code: str,
        *,
        status_code: int | None,
        attempts: list[HttpAttemptReceipt],
    ) -> DiscoveryHttpRuntimeError:
        return DiscoveryHttpRuntimeError(
            HttpFailureReceipt(
                reason_code=reason_code,
                status_code=status_code,
                attempts=tuple(attempts),
                request_budget=self._request_budget.snapshot(),
            )
        )

    async def _wait_for_origin(self, origin: str) -> None:
        while True:
            async with self._state_lock:
                now_ms = self._now_ms()
                if now_ms >= self._deadline_ms:
                    raise DiscoveryTransportError("deadline_exhausted")
                if (
                    origin not in self._circuits
                    and len(self._circuits) >= self._limits.origin_limit
                ):
                    raise DiscoveryTransportError("origin_budget")
                circuit = self._circuits.setdefault(origin, _CircuitState())
                if circuit.open_until_ms > now_ms:
                    raise DiscoveryTransportError("circuit_open")
                if circuit.open_until_ms:
                    circuit.open_until_ms = 0
                    circuit.consecutive_failures = 0
                next_allowed = self._next_origin_at_ms.get(origin, now_ms)
                delay_ms = max(0, next_allowed - now_ms)
                if delay_ms == 0:
                    self._next_origin_at_ms[origin] = (
                        now_ms + self._limits.min_origin_interval_ms
                    )
                    return
                if now_ms + delay_ms >= self._deadline_ms:
                    raise DiscoveryTransportError("origin_pacing_deadline")
            await self._sleeper(delay_ms / 1_000)

    async def _record_transient_failure(self, origin: str) -> None:
        async with self._state_lock:
            circuit = self._circuits.setdefault(origin, _CircuitState())
            circuit.consecutive_failures += 1
            if circuit.consecutive_failures >= self._limits.circuit_failure_threshold:
                circuit.open_until_ms = (
                    self._now_ms() + self._limits.circuit_cooldown_ms
                )

    async def _record_success(self, origin: str) -> None:
        async with self._state_lock:
            circuit = self._circuits.setdefault(origin, _CircuitState())
            circuit.consecutive_failures = 0
            circuit.open_until_ms = 0

    async def _sleep_retry(self, retry_after: str | None, retry: int) -> None:
        now_ms = self._now_ms()
        if retry_after is not None:
            delay_ms = bounded_retry_delay_ms(
                retry_after,
                now_ms=now_ms,
                deadline_ms=self._deadline_ms,
                max_delay_ms=self._limits.max_retry_delay_ms,
            )
        else:
            delay_ms = min(
                self._limits.retry_base_delay_ms * (2 ** (retry - 1)),
                self._limits.max_retry_delay_ms,
            )
            if now_ms + delay_ms >= self._deadline_ms:
                raise DiscoveryTransportError("retry_after_deadline")
        await self._sleeper(delay_ms / 1_000)

    async def _empty_response_body(self, response: httpx.Response) -> None:
        try:
            with anyio.fail_after(self._remaining_seconds()):
                async for chunk in response.aiter_raw():
                    if chunk:
                        raise DiscoveryTransportError("not_modified_body")
        except TimeoutError:
            raise DiscoveryTransportError("deadline_exhausted") from None

    async def _admit_response(self, response: httpx.Response) -> AdmittedResponse:
        async def chunks() -> AsyncIterator[ResponseChunk]:
            async for chunk in response.aiter_raw():
                yield ResponseChunk(encoded=chunk, decoded=chunk)

        try:
            with anyio.fail_after(self._remaining_seconds()):
                return await read_bounded_response(
                    ResponseHead(
                        status_code=response.status_code,
                        headers=dict(response.headers),
                    ),
                    chunks(),
                    limits=self._content_limits,
                    aggregate_budget=self._byte_budget,
                )
        except TimeoutError:
            raise DiscoveryTransportError("deadline_exhausted") from None

    async def fetch(
        self,
        locator: SafeLocator,
        *,
        attempt_kind: Literal["initial", "pagination"] = "initial",
        conditional_observation: VerifiedObservation | None = None,
    ) -> DiscoveryHttpResult:
        """Fetch one bounded resource without automatic redirects or cache reuse."""

        if not isinstance(attempt_kind, str) or attempt_kind not in (
            "initial",
            "pagination",
        ):
            raise self._failure(
                "attempt_kind",
                status_code=None,
                attempts=[],
            )
        if validate_public_locator(locator.url) != locator:
            raise self._failure(
                "locator_identity",
                status_code=None,
                attempts=[],
            )
        conditional: _VerifiedConditionalRequest | None = None
        if conditional_observation is not None:
            try:
                conditional = _conditional_request(
                    conditional_observation,
                    requested_locator=locator,
                    profile_id=self._profile_id,
                    profile_version=self._profile_version,
                    profile_digest=self._profile_digest,
                    configuration_sha256=self._configuration_sha256,
                    now=self._wall_clock(),
                    max_age=timedelta(
                        milliseconds=self._limits.verified_evidence_max_age_ms
                    ),
                )
            except Exception as error:
                reason = safe_transport_diagnostic(error)["reasonCode"]
                raise self._failure(
                    reason,
                    status_code=None,
                    attempts=[],
                ) from None

        current = locator
        history = [current.url]
        attempts: list[HttpAttemptReceipt] = []
        first_kind: Literal["initial", "pagination", "redirect"] = attempt_kind
        while True:
            for resource_attempt in range(
                1, self._limits.max_attempts_per_resource + 1
            ):
                current_attempt_kind: Literal[
                    "initial", "pagination", "redirect", "retry"
                ] = first_kind if resource_attempt == 1 else "retry"
                origin_semaphore: anyio.Semaphore | None = None
                try:
                    await self._wait_for_origin(current.origin)
                    origin_semaphore = await self._acquire_concurrency(current.origin)
                    reservation = self._request_budget.reserve(
                        kind=current_attempt_kind,
                        origin=current.origin,
                        now_ms=self._now_ms(),
                    )
                except BaseException as error:
                    if origin_semaphore is not None:
                        self._release_concurrency(origin_semaphore)
                        origin_semaphore = None
                    if not isinstance(error, Exception):
                        raise
                    reason = safe_transport_diagnostic(error)["reasonCode"]
                    raise self._failure(
                        reason,
                        status_code=None,
                        attempts=attempts,
                    ) from None

                response: httpx.Response | None = None
                reservation_active = True
                try:
                    request_extensions: dict[str, object] = {}
                    if conditional is not None:
                        request_extensions[_CONDITIONAL_EXTENSION] = conditional
                    request = self._client.build_request(
                        "GET",
                        current.url,
                        content=None,
                        headers={},
                        cookies=None,
                        extensions=request_extensions,
                    )
                    try:
                        with anyio.fail_after(self._remaining_seconds()):
                            response = await self._client.send(
                                request,
                                stream=True,
                                auth=None,
                                follow_redirects=False,
                            )
                    except TimeoutError:
                        raise DiscoveryTransportError("deadline_exhausted") from None
                    status_code = response.status_code

                    if status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        await response.aclose()
                        if location is None:
                            raise DiscoveryTransportError("redirect_location")
                        try:
                            redirected = prepare_redirect(
                                ScoutRequest(
                                    method="GET",
                                    locator=current,
                                    headers={},
                                    body=None,
                                ),
                                location=location,
                                history=tuple(history),
                                policy=self._redirect_policy,
                            )
                        except Exception:
                            self._request_budget.finish(
                                reservation,
                                outcome="blocked",
                                admitted_bytes=0,
                            )
                            reservation_active = False
                            attempts.append(
                                HttpAttemptReceipt(
                                    len(attempts) + 1,
                                    current_attempt_kind,
                                    "blocked",
                                    status_code,
                                    0,
                                )
                            )
                            raise
                        self._request_budget.finish(
                            reservation,
                            outcome="succeeded",
                            admitted_bytes=0,
                        )
                        reservation_active = False
                        attempts.append(
                            HttpAttemptReceipt(
                                len(attempts) + 1,
                                current_attempt_kind,
                                "succeeded",
                                status_code,
                                0,
                            )
                        )
                        await self._record_success(current.origin)
                        current = redirected.locator
                        history.append(current.url)
                        conditional = None
                        first_kind = "redirect"
                        break

                    if status_code in _TRANSIENT_STATUSES:
                        outcome: Literal["failed", "rate_limited"] = (
                            "rate_limited" if status_code == 429 else "failed"
                        )
                        self._request_budget.finish(
                            reservation,
                            outcome=outcome,
                            admitted_bytes=0,
                        )
                        reservation_active = False
                        attempts.append(
                            HttpAttemptReceipt(
                                len(attempts) + 1,
                                current_attempt_kind,
                                outcome,
                                status_code,
                                0,
                            )
                        )
                        await self._record_transient_failure(current.origin)
                        if resource_attempt >= self._limits.max_attempts_per_resource:
                            await response.aclose()
                            reason = (
                                "rate_limited"
                                if status_code == 429
                                else "upstream_failure"
                            )
                            raise self._failure(
                                reason,
                                status_code=status_code,
                                attempts=attempts,
                            )
                        retry_after = response.headers.get("retry-after")
                        await response.aclose()
                        if origin_semaphore is not None:
                            self._release_concurrency(origin_semaphore)
                            origin_semaphore = None
                        await self._sleep_retry(retry_after, resource_attempt)
                        continue

                    if status_code == 304:
                        if conditional is None:
                            raise DiscoveryTransportError("unexpected_not_modified")
                        await self._empty_response_body(response)
                        self._request_budget.finish(
                            reservation,
                            outcome="succeeded",
                            admitted_bytes=0,
                        )
                        reservation_active = False
                        attempts.append(
                            HttpAttemptReceipt(
                                len(attempts) + 1,
                                current_attempt_kind,
                                "succeeded",
                                status_code,
                                0,
                            )
                        )
                        await self._record_success(current.origin)
                        return DiscoveryHttpResult(
                            status_code=status_code,
                            final_locator=current,
                            redirect_history=tuple(history),
                            body=conditional.observation.content,
                            encoded_bytes=0,
                            decoded_bytes=0,
                            media_type=None,
                            content_sha256=conditional.observation.content_sha256,
                            secret_detector_version=(
                                conditional.observation.secret_detector_version
                            ),
                            evidence_state="not_modified",
                            response_metadata=_normalized_metadata(response),
                            attempts=tuple(attempts),
                            request_budget=self._request_budget.snapshot(),
                        )

                    if not 200 <= status_code <= 299:
                        outcome = "blocked" if status_code in {401, 403} else "failed"
                        self._request_budget.finish(
                            reservation,
                            outcome=outcome,
                            admitted_bytes=0,
                        )
                        reservation_active = False
                        attempts.append(
                            HttpAttemptReceipt(
                                len(attempts) + 1,
                                current_attempt_kind,
                                outcome,
                                status_code,
                                0,
                            )
                        )
                        reason = (
                            "access_blocked"
                            if status_code in {401, 403}
                            else "upstream_status"
                        )
                        raise self._failure(
                            reason,
                            status_code=status_code,
                            attempts=attempts,
                        )

                    admitted = await self._admit_response(response)
                    self._request_budget.finish(
                        reservation,
                        outcome="succeeded",
                        admitted_bytes=admitted.decoded_bytes,
                    )
                    reservation_active = False
                    attempts.append(
                        HttpAttemptReceipt(
                            len(attempts) + 1,
                            current_attempt_kind,
                            "succeeded",
                            status_code,
                            admitted.decoded_bytes,
                        )
                    )
                    await self._record_success(current.origin)
                    return DiscoveryHttpResult(
                        status_code=status_code,
                        final_locator=current,
                        redirect_history=tuple(history),
                        body=admitted.body,
                        encoded_bytes=admitted.encoded_bytes,
                        decoded_bytes=admitted.decoded_bytes,
                        media_type=admitted.media_type,
                        content_sha256=admitted.content_sha256,
                        secret_detector_version=admitted.secret_detector_version,
                        evidence_state="fetched",
                        response_metadata=_normalized_metadata(response),
                        attempts=tuple(attempts),
                        request_budget=self._request_budget.snapshot(),
                    )
                except DiscoveryHttpRuntimeError:
                    raise
                except BaseException as error:
                    cancelled_class = anyio.get_cancelled_exc_class()
                    if isinstance(error, cancelled_class):
                        if reservation_active:
                            self._request_budget.finish(
                                reservation,
                                outcome="cancelled",
                                admitted_bytes=0,
                            )
                            attempts.append(
                                HttpAttemptReceipt(
                                    len(attempts) + 1,
                                    current_attempt_kind,
                                    "cancelled",
                                    response.status_code
                                    if response is not None
                                    else None,
                                    0,
                                )
                            )
                        raise
                    if not isinstance(error, Exception):
                        if reservation_active:
                            self._request_budget.finish(
                                reservation,
                                outcome="cancelled",
                                admitted_bytes=0,
                            )
                        raise
                    reason = safe_transport_diagnostic(error)["reasonCode"]
                    if reservation_active:
                        terminal_outcome: Literal["timed_out", "failed"] = (
                            "timed_out" if reason == "request_timeout" else "failed"
                        )
                        self._request_budget.finish(
                            reservation,
                            outcome=terminal_outcome,
                            admitted_bytes=0,
                        )
                        attempts.append(
                            HttpAttemptReceipt(
                                len(attempts) + 1,
                                current_attempt_kind,
                                terminal_outcome,
                                response.status_code if response is not None else None,
                                0,
                            )
                        )
                    if reason in {"network_failure", "request_timeout"}:
                        await self._record_transient_failure(current.origin)
                        if resource_attempt < self._limits.max_attempts_per_resource:
                            if origin_semaphore is not None:
                                self._release_concurrency(origin_semaphore)
                                origin_semaphore = None
                            try:
                                await self._sleep_retry(None, resource_attempt)
                            except Exception as retry_error:
                                retry_reason = safe_transport_diagnostic(retry_error)[
                                    "reasonCode"
                                ]
                                raise self._failure(
                                    retry_reason,
                                    status_code=(
                                        response.status_code
                                        if response is not None
                                        else None
                                    ),
                                    attempts=attempts,
                                ) from None
                            continue
                    raise self._failure(
                        reason,
                        status_code=(
                            response.status_code if response is not None else None
                        ),
                        attempts=attempts,
                    ) from None
                finally:
                    if origin_semaphore is not None:
                        self._release_concurrency(origin_semaphore)
                    if response is not None:
                        with anyio.CancelScope(shield=True):
                            await response.aclose()
            else:  # pragma: no cover - every terminal branch returns or raises.
                raise self._failure(
                    "attempt_budget",
                    status_code=None,
                    attempts=attempts,
                )
            continue
