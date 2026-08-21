"""Fail-closed transport primitives for bounded source discovery.

The module contains policy and accounting seams only.  DNS resolution and
socket connection are injected so tests and offline replay never require live
network access, and the runtime HTTP cache is intentionally unreachable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import math
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Self, TypeVar
import unicodedata
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ElementTree

import idna

from openopps.discovery.secrets import (
    SECRET_DETECTOR_VERSION,
    SecretDetectedError,
    admit_scanned_content,
)


if TYPE_CHECKING:
    from openopps.discovery.bundle import VerifiedBundle


_SECRET_QUERY_TOKENS = (
    "access_token",
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-signature",
)
_SIGNED_QUERY_KEYS = frozenset(
    {
        "awsaccesskeyid",
        "googleaccessid",
        "sig",
        "signature",
        "x_amz_credential",
        "x_amz_signature",
        "x_goog_credential",
        "x_goog_signature",
    }
)
_ALLOWED_QUERY_KEYS = frozenset(
    {
        "after",
        "before",
        "category",
        "content",
        "cursor",
        "details",
        "filter",
        "format",
        "include",
        "include_compensation",
        "language",
        "limit",
        "mode",
        "offset",
        "order",
        "page",
        "per_page",
        "q",
        "query",
        "search",
        "sort",
        "tag",
        "team",
        "topic",
        "type",
    }
)
_QUERY_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_MAX_QUERY_FIELDS = 32
_ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/ld+json",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)
_OPERATION_OUTCOMES = (
    "blocked",
    "cancelled",
    "failed",
    "rate_limited",
    "succeeded",
    "timed_out",
    "unstarted",
)
_CHANNEL_STATES = frozenset({"complete", "failed", "partial", "cancelled"})
_ATTEMPT_KINDS = frozenset({"initial", "pagination", "redirect", "retry"})
_REQUEST_OUTCOMES = frozenset(
    {
        "blocked",
        "cancelled",
        "failed",
        "rate_limited",
        "succeeded",
        "timed_out",
    }
)


class DiscoveryTransportError(ValueError):
    """A bounded reason code safe for logs, metrics, and artifact receipts."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class SafeLocator:
    """Canonical public HTTPS locator validated before DNS resolution."""

    url: str
    hostname: str
    port: int
    origin: str


@dataclass(frozen=True, slots=True)
class ValidatedAddressSet:
    """The exact sorted public address set admitted for one connection."""

    hostname: str
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoutRequest:
    method: str
    locator: SafeLocator
    headers: Mapping[str, str]
    body: bytes | None


@dataclass(frozen=True, slots=True)
class RedirectPolicy:
    max_hops: int
    allowed_cross_origin: frozenset[tuple[str, str]]

    def __post_init__(self) -> None:
        _positive_int(self.max_hops, "redirect_policy")


@dataclass(frozen=True, slots=True)
class ContentLimits:
    max_encoded_bytes: int
    max_decoded_bytes: int
    max_json_depth: int
    max_xml_depth: int
    max_html_nodes: int

    def __post_init__(self) -> None:
        for value in (
            self.max_encoded_bytes,
            self.max_decoded_bytes,
            self.max_json_depth,
            self.max_xml_depth,
            self.max_html_nodes,
        ):
            _positive_int(value, "content_limit")


@dataclass(frozen=True, slots=True)
class ResponseChunk:
    encoded: bytes
    decoded: bytes


@dataclass(frozen=True, slots=True)
class ResponseHead:
    status_code: int
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AdmittedResponse:
    body: bytes
    encoded_bytes: int
    decoded_bytes: int
    media_type: str
    content_sha256: str
    secret_detector_version: str


@dataclass(slots=True)
class ByteBudget:
    limit: int
    consumed: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        _positive_int(self.limit, "aggregate_byte_budget")

    @property
    def remaining(self) -> int:
        return self.limit - self.consumed

    def admit(self, size_bytes: int) -> None:
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise DiscoveryTransportError("aggregate_byte_budget")
        if size_bytes < 0 or size_bytes > self.remaining:
            raise DiscoveryTransportError("aggregate_byte_budget")
        self.consumed += size_bytes


@dataclass(frozen=True, slots=True, init=False)
class VerifiedObservation:
    """Secret-scanned bytes bound to one exact verified bundle member."""

    content: bytes
    content_sha256: str
    manifest_id: str
    observed_resource_member_path: str
    observed_resource_member_sha256: str
    resource_id: str
    member_path: str
    member_sha256: str
    member_size_bytes: int
    member_media_type: str
    member_role: str
    member_provenance_id: str
    requested_locator_url: str
    profile_id: str
    profile_version: str
    profile_digest: str
    configuration_sha256: str
    secret_detector_version: str
    observed_at: datetime
    etag: str | None
    last_modified: str | None

    def __new__(cls) -> Self:
        del cls
        raise TypeError(
            "VerifiedObservation must be created from exact verified bundle evidence"
        )

    @classmethod
    def from_verified_bundle(
        cls,
        *,
        verified_bundle: VerifiedBundle,
        expected_locator: SafeLocator,
        expected_profile_id: str,
        expected_profile_version: str,
        expected_profile_digest: str,
        expected_configuration_sha256: str,
    ) -> Self | None:
        """Select one reusable observation from a sealed verifier-derived graph."""

        # Local imports keep the policy-only transport primitives independent from
        # bundle I/O until a caller explicitly asks to construct reusable evidence.
        from openopps.discovery.bundle import VerifiedBundle

        if (
            type(verified_bundle) is not VerifiedBundle
            or not verified_bundle._is_verifier_sealed()
        ):
            raise DiscoveryTransportError("verified_bundle")
        if not isinstance(expected_locator, SafeLocator):
            raise DiscoveryTransportError("verified_evidence_locator")
        if validate_public_locator(expected_locator.url) != expected_locator:
            raise DiscoveryTransportError("verified_evidence_locator")
        if (
            not isinstance(expected_profile_id, str)
            or not expected_profile_id
            or expected_profile_id != expected_profile_id.strip()
            or not isinstance(expected_profile_version, str)
            or not expected_profile_version
            or expected_profile_version != expected_profile_version.strip()
        ):
            raise DiscoveryTransportError("verified_profile_identity")
        if (
            not isinstance(expected_profile_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_profile_digest) is None
        ):
            raise DiscoveryTransportError("verified_profile_digest")
        if (
            not isinstance(expected_configuration_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_configuration_sha256) is None
        ):
            raise DiscoveryTransportError("verified_configuration_identity")

        profile = verified_bundle.profile_binding
        if profile is None:
            return None
        if (
            verified_bundle.profile_id != expected_profile_id
            or verified_bundle.profile_version != expected_profile_version
            or verified_bundle.configuration_sha256 != expected_configuration_sha256
            or profile.profile_id != expected_profile_id
            or profile.profile_version != expected_profile_version
            or profile.profile_digest != expected_profile_digest
        ):
            return None
        matches = tuple(
            binding
            for binding in verified_bundle.resource_bindings
            if binding.final_locator == expected_locator.url
        )
        if len(matches) != 1:
            return None
        binding = matches[0]
        if (
            binding.manifest_id != verified_bundle.manifest_id
            or binding.profile_id != profile.profile_id
            or binding.profile_version != profile.profile_version
            or binding.profile_digest != profile.profile_digest
            or binding.configuration_sha256 != verified_bundle.configuration_sha256
            or binding.observed_resource_member_path not in verified_bundle.member_paths
            or binding.raw_member_path not in verified_bundle.member_paths
        ):
            raise DiscoveryTransportError("verified_resource_binding")

        observation = object.__new__(cls)
        values: tuple[tuple[str, object], ...] = (
            ("content", binding.content),
            ("content_sha256", binding.raw_member_sha256),
            ("manifest_id", verified_bundle.manifest_id),
            (
                "observed_resource_member_path",
                binding.observed_resource_member_path,
            ),
            (
                "observed_resource_member_sha256",
                binding.observed_resource_member_sha256,
            ),
            ("resource_id", binding.resource_id),
            ("member_path", binding.raw_member_path),
            ("member_sha256", binding.raw_member_sha256),
            ("member_size_bytes", binding.raw_member_size_bytes),
            ("member_media_type", binding.raw_member_media_type),
            ("member_role", binding.raw_member_role),
            ("member_provenance_id", binding.raw_member_provenance_id),
            ("requested_locator_url", binding.final_locator),
            ("profile_id", binding.profile_id),
            ("profile_version", binding.profile_version),
            ("profile_digest", binding.profile_digest),
            ("configuration_sha256", binding.configuration_sha256),
            ("secret_detector_version", binding.secret_detector_version),
            ("observed_at", binding.observed_at),
            ("etag", binding.etag),
            ("last_modified", binding.last_modified),
        )
        for field_name, value in values:
            object.__setattr__(observation, field_name, value)
        return observation


@dataclass(frozen=True, slots=True)
class RequestReservation:
    reservation_id: int
    kind: str
    origin: str


@dataclass(frozen=True, slots=True)
class RequestBudgetSnapshot:
    limit: int
    consumed: int
    in_flight: int
    per_origin_in_flight_limit: int
    remaining: int
    outcomes: Mapping[str, int]
    attempt_kinds: Mapping[str, int]
    admitted_bytes: int


class RequestBudgetLedger:
    """One immutable-limit request ledger shared by all attempt kinds."""

    def __init__(
        self,
        *,
        request_limit: int,
        origin_limit: int,
        max_in_flight: int,
        per_origin_in_flight_limit: int,
        retry_limit: int,
        redirect_limit: int,
        pagination_limit: int,
        deadline_ms: int,
    ) -> None:
        for value in (
            request_limit,
            origin_limit,
            max_in_flight,
            per_origin_in_flight_limit,
            retry_limit,
            redirect_limit,
            pagination_limit,
            deadline_ms,
        ):
            _positive_int(value, "request_budget")
        self._request_limit = request_limit
        self._origin_limit = origin_limit
        self._max_in_flight = max_in_flight
        self._per_origin_in_flight_limit = per_origin_in_flight_limit
        self._kind_limits = {
            "retry": retry_limit,
            "redirect": redirect_limit,
            "pagination": pagination_limit,
        }
        self._deadline_ms = deadline_ms
        self._next_id = 1
        self._consumed = 0
        self._admitted_bytes = 0
        self._origins: set[str] = set()
        self._in_flight: dict[int, RequestReservation] = {}
        self._in_flight_by_origin: Counter[str] = Counter()
        self._outcomes: Counter[str] = Counter()
        self._attempt_kinds: Counter[str] = Counter()

    def reserve(self, *, kind: str, origin: str, now_ms: int) -> RequestReservation:
        if kind not in _ATTEMPT_KINDS:
            raise DiscoveryTransportError("attempt_kind")
        if isinstance(now_ms, bool) or not isinstance(now_ms, int):
            raise DiscoveryTransportError("deadline_exhausted")
        if now_ms >= self._deadline_ms:
            raise DiscoveryTransportError("deadline_exhausted")
        if self._consumed + len(self._in_flight) >= self._request_limit:
            raise DiscoveryTransportError("request_budget")
        if len(self._in_flight) >= self._max_in_flight:
            raise DiscoveryTransportError("concurrency_budget")
        if self._in_flight_by_origin[origin] >= self._per_origin_in_flight_limit:
            raise DiscoveryTransportError("origin_concurrency_budget")
        if origin not in self._origins and len(self._origins) >= self._origin_limit:
            raise DiscoveryTransportError("origin_budget")
        limit = self._kind_limits.get(kind)
        if limit is not None and self._attempt_kinds[kind] >= limit:
            raise DiscoveryTransportError(f"{kind}_budget")
        reservation = RequestReservation(self._next_id, kind, origin)
        self._next_id += 1
        self._origins.add(origin)
        self._in_flight[reservation.reservation_id] = reservation
        self._in_flight_by_origin[origin] += 1
        self._attempt_kinds[kind] += 1
        return reservation

    def finish(
        self,
        reservation: RequestReservation,
        *,
        outcome: str,
        admitted_bytes: int,
    ) -> None:
        if outcome not in _REQUEST_OUTCOMES:
            raise DiscoveryTransportError("request_outcome")
        active = self._in_flight.get(reservation.reservation_id)
        if active != reservation:
            raise DiscoveryTransportError("request_reservation")
        if (
            isinstance(admitted_bytes, bool)
            or not isinstance(admitted_bytes, int)
            or admitted_bytes < 0
        ):
            raise DiscoveryTransportError("request_admitted_bytes")
        del self._in_flight[reservation.reservation_id]
        self._in_flight_by_origin[reservation.origin] -= 1
        if self._in_flight_by_origin[reservation.origin] == 0:
            del self._in_flight_by_origin[reservation.origin]
        self._consumed += 1
        self._admitted_bytes += admitted_bytes
        self._outcomes[outcome] += 1

    def snapshot(self) -> RequestBudgetSnapshot:
        in_flight = len(self._in_flight)
        return RequestBudgetSnapshot(
            limit=self._request_limit,
            consumed=self._consumed,
            in_flight=in_flight,
            per_origin_in_flight_limit=self._per_origin_in_flight_limit,
            remaining=self._request_limit - self._consumed - in_flight,
            outcomes=MappingProxyType(dict(sorted(self._outcomes.items()))),
            attempt_kinds=MappingProxyType(dict(sorted(self._attempt_kinds.items()))),
            admitted_bytes=self._admitted_bytes,
        )


@dataclass(frozen=True, slots=True)
class OperationLedgerSnapshot:
    planned: int
    terminals: Mapping[str, int]
    channel_state: str


class OperationLedger:
    """Close every planned operation into one of seven terminal classes."""

    def __init__(self, *, planned_operation_ids: tuple[str, ...]) -> None:
        if (
            not planned_operation_ids
            or any(not item for item in planned_operation_ids)
            or len(set(planned_operation_ids)) != len(planned_operation_ids)
        ):
            raise DiscoveryTransportError("operation_plan")
        self._states = dict.fromkeys(planned_operation_ids, "planned")
        self._closed = False

    def start(self, operation_id: str) -> None:
        if self._closed or self._states.get(operation_id) != "planned":
            raise DiscoveryTransportError("operation_transition")
        self._states[operation_id] = "started"

    def finish(self, operation_id: str, *, outcome: str) -> None:
        if outcome not in _OPERATION_OUTCOMES:
            raise DiscoveryTransportError("operation_outcome")
        state = self._states.get(operation_id)
        if self._closed or state is None or state in _OPERATION_OUTCOMES:
            raise DiscoveryTransportError("operation_transition")
        if outcome == "unstarted":
            if state != "planned":
                raise DiscoveryTransportError("operation_transition")
        elif state != "started":
            raise DiscoveryTransportError("operation_transition")
        self._states[operation_id] = outcome

    def close(self, *, channel_state: str) -> OperationLedgerSnapshot:
        if self._closed or channel_state not in _CHANNEL_STATES:
            raise DiscoveryTransportError("channel_state")
        if any(state not in _OPERATION_OUTCOMES for state in self._states.values()):
            raise DiscoveryTransportError("operation_incomplete")
        self._closed = True
        counts = Counter(self._states.values())
        terminals = {outcome: counts[outcome] for outcome in _OPERATION_OUTCOMES}
        return OperationLedgerSnapshot(
            planned=len(self._states),
            terminals=MappingProxyType(terminals),
            channel_state=channel_state,
        )


def _positive_int(value: int, reason_code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DiscoveryTransportError(reason_code)


def _reject_numeric_hostname(hostname: str) -> None:
    lowered = hostname.lower()
    if (
        re.fullmatch(r"[0-9.]+", lowered)
        or lowered.startswith("0x")
        or (":" in lowered and re.fullmatch(r"[0-9a-f:]+", lowered))
    ):
        raise DiscoveryTransportError("locator_ip_literal")


def _is_secret_query_key(key: str) -> bool:
    if key in _SIGNED_QUERY_KEYS:
        return True
    normalized_tokens = (token.replace("-", "_") for token in _SECRET_QUERY_TOKENS)
    return any(token in key for token in normalized_tokens)


def _validate_query(query: str) -> None:
    if not query:
        return
    raw_fields = query.split("&")
    if len(raw_fields) > _MAX_QUERY_FIELDS or any(
        not field or "=" not in field for field in raw_fields
    ):
        raise DiscoveryTransportError("locator_ambiguous")
    try:
        query_items = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=_MAX_QUERY_FIELDS,
            separator="&",
        )
    except (UnicodeError, ValueError):
        raise DiscoveryTransportError("locator_ambiguous") from None
    if len(query_items) != len(raw_fields):
        raise DiscoveryTransportError("locator_ambiguous")
    seen: set[str] = set()
    for raw_field, (key, _) in zip(raw_fields, query_items, strict=True):
        raw_key = raw_field.partition("=")[0]
        normalized_key = key.casefold().replace("-", "_")
        if _is_secret_query_key(normalized_key):
            raise DiscoveryTransportError("locator_secret_query")
        if "%" in raw_key or "+" in raw_key:
            raise DiscoveryTransportError("locator_ambiguous")
        if (
            key != normalized_key
            or _QUERY_KEY_PATTERN.fullmatch(key) is None
            or key not in _ALLOWED_QUERY_KEYS
            or key in seen
        ):
            raise DiscoveryTransportError("locator_query_key")
        seen.add(key)


def validate_public_locator(locator: str) -> SafeLocator:
    """Validate and canonicalize one credential-free public HTTPS locator."""

    if (
        not isinstance(locator, str)
        or not locator
        or locator != locator.strip()
        or "\\" in locator
    ):
        raise DiscoveryTransportError("locator_ambiguous")
    if any(ord(character) < 0x20 for character in locator):
        raise DiscoveryTransportError("locator_ambiguous")
    try:
        parsed = urlsplit(locator)
    except ValueError:
        raise DiscoveryTransportError("locator_ambiguous") from None
    if parsed.username is not None or parsed.password is not None:
        raise DiscoveryTransportError("locator_userinfo")
    if parsed.fragment:
        raise DiscoveryTransportError("locator_fragment")
    if parsed.scheme.lower() != "https":
        raise DiscoveryTransportError("locator_scheme")
    if not parsed.netloc or parsed.hostname is None:
        raise DiscoveryTransportError("locator_authority")
    if "%" in parsed.netloc:
        raise DiscoveryTransportError("locator_ambiguous")
    try:
        port = parsed.port or 443
    except ValueError:
        raise DiscoveryTransportError("locator_port") from None
    if port != 443:
        raise DiscoveryTransportError("locator_port")
    raw_hostname = parsed.hostname
    if any(unicodedata.category(character) == "Cf" for character in raw_hostname):
        raise DiscoveryTransportError("locator_idna")
    try:
        ipaddress.ip_address(raw_hostname)
    except ValueError:
        pass
    else:
        raise DiscoveryTransportError("locator_ip_literal")
    try:
        hostname = idna.encode(
            raw_hostname,
            uts46=True,
            transitional=False,
            std3_rules=True,
        ).decode("ascii")
    except (idna.IDNAError, UnicodeError):
        raise DiscoveryTransportError("locator_idna") from None
    hostname = hostname.lower()
    if (
        not hostname
        or hostname != hostname.strip()
        or ".." in hostname
        or hostname.endswith(".")
    ):
        raise DiscoveryTransportError("locator_idna")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        _reject_numeric_hostname(hostname)
    else:
        raise DiscoveryTransportError("locator_ip_literal")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise DiscoveryTransportError("locator_localhost")
    _validate_query(parsed.query)
    path = parsed.path or "/"
    netloc = hostname
    canonical = urlunsplit(("https", netloc, path, parsed.query, ""))
    return SafeLocator(
        url=canonical,
        hostname=hostname,
        port=443,
        origin=f"https://{hostname}:443",
    )


async def resolve_public_addresses(
    locator: SafeLocator,
    *,
    resolver: Callable[[str], Awaitable[tuple[str, ...]]],
) -> ValidatedAddressSet:
    """Resolve once and require a non-empty set containing only global addresses."""

    try:
        answers = await resolver(locator.hostname)
    except Exception:
        raise DiscoveryTransportError("dns_failure") from None
    if not answers:
        raise DiscoveryTransportError("dns_empty")
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    non_global = False
    for answer in answers:
        if "%" in answer:
            raise DiscoveryTransportError("dns_zone_identifier")
        try:
            address = ipaddress.ip_address(answer)
        except ValueError:
            raise DiscoveryTransportError("dns_invalid") from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            raise DiscoveryTransportError("dns_ipv4_mapped")
        if not address.is_global:
            non_global = True
        parsed.append(address)
    if non_global and any(address.is_global for address in parsed):
        raise DiscoveryTransportError("dns_mixed_scope")
    if non_global:
        raise DiscoveryTransportError("dns_non_global")
    unique = sorted(set(parsed), key=lambda address: (address.version, int(address)))
    return ValidatedAddressSet(
        hostname=locator.hostname,
        addresses=tuple(str(address) for address in unique),
    )


_ConnectionT = TypeVar("_ConnectionT")


async def connect_pinned(
    locator: SafeLocator,
    *,
    resolver: Callable[[str], Awaitable[tuple[str, ...]]],
    connector: Callable[..., Awaitable[_ConnectionT]],
) -> _ConnectionT:
    """Connect to one vetted address while retaining the original TLS hostname."""

    address_set = await resolve_public_addresses(locator, resolver=resolver)
    try:
        connection = await connector(
            address=address_set.addresses[0],
            port=locator.port,
            server_hostname=locator.hostname,
        )
    except DiscoveryTransportError:
        raise
    except Exception:
        raise DiscoveryTransportError("connect_failure") from None
    peer_address = getattr(connection, "peer_address", None)
    if peer_address not in address_set.addresses:
        close = getattr(connection, "aclose", None)
        if close is not None:
            await close()
        raise DiscoveryTransportError("peer_address_mismatch")
    return connection


def prepare_redirect(
    request: ScoutRequest,
    *,
    location: str,
    history: tuple[str, ...],
    policy: RedirectPolicy,
) -> ScoutRequest:
    """Resolve and validate one redirect, stripping all caller-controlled data."""

    if len(history) > policy.max_hops:
        raise DiscoveryTransportError("redirect_limit")
    if not isinstance(location, str) or "\\" in location:
        raise DiscoveryTransportError("locator_ambiguous")
    target = validate_public_locator(urljoin(request.locator.url, location))
    if target.url in history:
        raise DiscoveryTransportError("redirect_loop")
    if target.origin != request.locator.origin:
        transition = (request.locator.hostname, target.hostname)
        if transition not in policy.allowed_cross_origin:
            raise DiscoveryTransportError("redirect_origin")
    return ScoutRequest(method="GET", locator=target, headers={}, body=None)


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def _media_type(headers: Mapping[str, str]) -> str:
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type or (
        content_type not in _ALLOWED_MEDIA_TYPES and not content_type.endswith("+json")
    ):
        raise DiscoveryTransportError("unsupported_media_type")
    return content_type


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DiscoveryTransportError("json_duplicate_key")
        value[key] = item
    return value


def _reject_nonfinite_json_constant(value: str) -> Any:
    del value
    raise DiscoveryTransportError("json_nonfinite")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DiscoveryTransportError("json_nonfinite")
    return parsed


def _json_depth(value: Any) -> int:
    maximum = 0
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, parent_depth = pending.pop()
        if isinstance(item, dict):
            depth = parent_depth + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item.values())
        elif isinstance(item, list):
            depth = parent_depth + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item)
    return maximum


def _validate_xml_depth(root: ElementTree.Element, *, maximum: int) -> None:
    """Validate XML depth iteratively so hostile nesting cannot consume Python stack."""

    pending: list[tuple[ElementTree.Element, int]] = [(root, 1)]
    while pending:
        element, depth = pending.pop()
        if depth > maximum:
            raise DiscoveryTransportError("parser_depth")
        try:
            pending.extend((child, depth + 1) for child in element)
        except Exception:
            raise DiscoveryTransportError("xml_invalid") from None


class _BoundedHTMLParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.nodes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs
        self.nodes += 1
        if self.nodes > self.limit:
            raise DiscoveryTransportError("html_node_limit")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _validate_structure(body: bytes, media_type: str, limits: ContentLimits) -> None:
    if media_type.endswith("json") or media_type.endswith("+json"):
        try:
            value = json.loads(
                body,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_parse_finite_json_float,
            )
        except DiscoveryTransportError:
            raise
        except RecursionError:
            raise DiscoveryTransportError("parser_depth") from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise DiscoveryTransportError("json_invalid") from None
        try:
            depth = _json_depth(value)
        except RecursionError:
            raise DiscoveryTransportError("parser_depth") from None
        if depth > limits.max_json_depth:
            raise DiscoveryTransportError("parser_depth")
    elif media_type in {"application/xml", "text/xml"}:
        upper = body.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise DiscoveryTransportError("xml_entity")
        try:
            root = ElementTree.fromstring(body)
        except (ElementTree.ParseError, RecursionError, ValueError):
            raise DiscoveryTransportError("xml_invalid") from None
        except Exception:
            raise DiscoveryTransportError("xml_invalid") from None
        _validate_xml_depth(root, maximum=limits.max_xml_depth)
    elif media_type == "text/html":
        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise DiscoveryTransportError("html_invalid") from None
        parser = _BoundedHTMLParser(limits.max_html_nodes)
        try:
            parser.feed(text)
            parser.close()
        except DiscoveryTransportError:
            raise
        except Exception:
            raise DiscoveryTransportError("html_invalid") from None


async def read_bounded_response(
    head: ResponseHead,
    chunks: AsyncIterator[ResponseChunk],
    *,
    limits: ContentLimits,
    aggregate_budget: ByteBudget,
) -> AdmittedResponse:
    """Admit one identity-encoded response under exact streaming limits."""

    headers = _normalized_headers(head.headers)
    encoding = headers.get("content-encoding", "identity").lower()
    if encoding != "identity":
        raise DiscoveryTransportError("unsupported_content_encoding")
    if "filename" in headers.get("content-disposition", "").lower():
        raise DiscoveryTransportError("server_selected_filename")
    media_type = _media_type(headers)
    declared_length: int | None = None
    if "content-length" in headers:
        raw_length = headers["content-length"]
        if not raw_length.isdecimal():
            raise DiscoveryTransportError("content_length_invalid")
        declared_length = int(raw_length)
        if declared_length > limits.max_encoded_bytes:
            raise DiscoveryTransportError("response_too_large")
        if declared_length > aggregate_budget.remaining:
            raise DiscoveryTransportError("aggregate_byte_budget")
    encoded_size = 0
    decoded_size = 0
    body_parts: list[bytes] = []
    async for chunk in chunks:
        if not isinstance(chunk.encoded, bytes) or not isinstance(chunk.decoded, bytes):
            raise DiscoveryTransportError("response_chunk")
        encoded_size += len(chunk.encoded)
        decoded_size += len(chunk.decoded)
        if encoded_size > limits.max_encoded_bytes:
            raise DiscoveryTransportError("response_too_large")
        if decoded_size > limits.max_decoded_bytes:
            raise DiscoveryTransportError("decoded_body_too_large")
        if decoded_size > aggregate_budget.remaining:
            raise DiscoveryTransportError("aggregate_byte_budget")
        if chunk.encoded != chunk.decoded:
            raise DiscoveryTransportError("identity_body_mismatch")
        body_parts.append(chunk.decoded)
    if declared_length is not None and declared_length != encoded_size:
        raise DiscoveryTransportError("content_length_mismatch")
    body = b"".join(body_parts)
    try:
        scanned = admit_scanned_content(
            body_parts,
            max_bytes=limits.max_decoded_bytes,
            write=lambda admitted: None,
            digest=lambda admitted: hashlib.sha256(admitted).hexdigest(),
        )
    except SecretDetectedError as error:
        raise DiscoveryTransportError(error.reason_code) from None
    _validate_structure(body, media_type, limits)
    aggregate_budget.admit(decoded_size)
    return AdmittedResponse(
        body=body,
        encoded_bytes=encoded_size,
        decoded_bytes=decoded_size,
        media_type=media_type,
        content_sha256=scanned.content_sha256,
        secret_detector_version=scanned.detector_version,
    )


def bounded_retry_delay_ms(
    retry_after: str,
    *,
    now_ms: int,
    deadline_ms: int,
    max_delay_ms: int,
) -> int:
    """Parse a delta-seconds Retry-After without exceeding trusted deadlines."""

    if not isinstance(retry_after, str) or not retry_after.isdecimal():
        raise DiscoveryTransportError("retry_after_invalid")
    delay_ms = int(retry_after) * 1_000
    if delay_ms > max_delay_ms:
        raise DiscoveryTransportError("retry_after_limit")
    if now_ms + delay_ms >= deadline_ms:
        raise DiscoveryTransportError("retry_after_deadline")
    return delay_ms


def safe_transport_diagnostic(error: Exception) -> dict[str, str]:
    """Return a bounded diagnostic containing no upstream-controlled values."""

    reason_code = (
        error.reason_code
        if isinstance(error, DiscoveryTransportError)
        else "transport_failure"
    )
    return {"reasonCode": reason_code}


def select_verified_reuse(
    observation: VerifiedObservation,
    *,
    now: datetime,
    max_age: timedelta,
) -> VerifiedObservation | None:
    """Reuse only exact verified, fresh quarantine bytes."""

    if hashlib.sha256(observation.content).hexdigest() != observation.content_sha256:
        raise DiscoveryTransportError("verified_evidence_digest")
    if (
        observation.content_sha256 != observation.member_sha256
        or len(observation.content) != observation.member_size_bytes
    ):
        raise DiscoveryTransportError("verified_member_content")
    if (
        observation.member_provenance_id != observation.resource_id
        or observation.member_path == observation.observed_resource_member_path
        or re.fullmatch(r"[0-9a-f]{64}", observation.observed_resource_member_sha256)
        is None
    ):
        raise DiscoveryTransportError("verified_resource_binding")
    if observation.secret_detector_version != SECRET_DETECTOR_VERSION:
        raise DiscoveryTransportError("verified_secret_detector")
    if validate_public_locator(observation.requested_locator_url).url != (
        observation.requested_locator_url
    ):
        raise DiscoveryTransportError("verified_evidence_locator")
    if observation.observed_at.tzinfo is None or now.tzinfo is None:
        raise DiscoveryTransportError("verified_evidence_time")
    age = now.astimezone(UTC) - observation.observed_at.astimezone(UTC)
    if age < timedelta(0):
        raise DiscoveryTransportError("verified_evidence_time")
    if max_age < timedelta(0):
        raise DiscoveryTransportError("verified_evidence_time")
    return observation if age <= max_age else None
