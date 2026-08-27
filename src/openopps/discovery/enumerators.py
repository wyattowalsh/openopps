"""Shared replay kernel for finite quarantined discovery channels.

Enumerators consume maintainer-owned seeds plus captured observations. They
do not open sockets, resolve DNS, import ``openopps.http``, or mutate
operational state. Sitemap locators stay untrusted until
``admit_public_sitemap_locators`` / ``validate_public_locator``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from typing import Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree

from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.identity import normalize_candidate_identity
from openopps.discovery.models import (
    BoundedReason,
    CandidateOccurrence,
    ChannelBudget,
    ChannelOperationAccounting,
    ChannelProfile,
    ChannelReplayReceipt,
    ObservedResource,
    ProvenanceClaim,
    RequestReceipt,
)
from openopps.discovery.secrets import SecretDetectedError, admit_scanned_content
from openopps.discovery.transport import (
    DiscoveryTransportError,
    SafeLocator,
    validate_public_locator,
)


ChannelName = Literal["official", "public_code", "search", "targeted_ats"]
OperationOutcome = Literal[
    "succeeded",
    "blocked",
    "rate_limited",
    "timed_out",
    "failed",
    "cancelled",
    "unstarted",
]
RequestOutcome = Literal[
    "succeeded",
    "blocked",
    "rate_limited",
    "timed_out",
    "failed",
    "cancelled",
]
AttemptKind = Literal["initial", "pagination", "redirect", "retry"]
TransportState = Literal[
    "response",
    "network_unreachable",
    "security_rejected_redirect",
    "verified_cache",
    "not_modified",
    "missing",
]
CHANNEL_ORDER: tuple[ChannelName, ...] = (
    "official",
    "public_code",
    "search",
    "targeted_ats",
)
_REMOTE_PARSER_KEYS = frozenset(
    {
        "callable",
        "entryPoint",
        "parser",
        "parserClass",
        "parserId",
        "parserModule",
        "parser_id",
    }
)
_ARCHIVE_MEDIA_TYPES = frozenset(
    {
        "application/gzip",
        "application/java-archive",
        "application/vnd.rar",
        "application/x-7z-compressed",
        "application/x-bzip2",
        "application/x-executable",
        "application/x-gtar",
        "application/x-tar",
        "application/zip",
        "multipart/x-zip",
    }
)
_EXECUTABLE_MEDIA_TYPES = frozenset(
    {
        "application/javascript",
        "application/wasm",
        "application/x-elf",
        "application/x-mach-binary",
        "application/x-msdownload",
        "application/x-sh",
        "text/javascript",
        "text/x-sh",
    }
)
_ARCHIVE_SUFFIXES = (".7z", ".bz2", ".exe", ".gz", ".jar", ".tar", ".tgz", ".zip")
_EXECUTABLE_SUFFIXES = (".dylib", ".exe", ".js", ".mjs", ".so", ".wasm")
_DEPENDENCY_NAMES = frozenset(
    {
        "cargo.toml",
        "go.mod",
        "package-lock.json",
        "package.json",
        "pipfile",
        "poetry.lock",
        "pyproject.toml",
        "requirements.txt",
    }
)


class EnumeratorError(ValueError):
    """Fail-closed enumerator contract error with a bounded reason code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    """One captured network observation. Bodies remain hostile evidence."""

    locator: str
    transport_state: TransportState = "response"
    status_code: int | None = None
    body: bytes | None = None
    media_type: str | None = None
    validated_address: str = "192.0.2.1"
    etag: str | None = None
    last_modified: str | None = None
    elapsed_ms: int = 1
    cached_age_seconds: int | None = None


@dataclass(slots=True)
class ChannelRunBuilder:
    """Accumulate one finite channel run into a closed replay receipt."""

    channel: ChannelName
    enumerator_version: str
    input_set_sha256: str
    budget: ChannelBudget
    observed_at: datetime
    _planned: list[str] = field(default_factory=list)
    _outcomes: dict[str, OperationOutcome] = field(default_factory=dict)
    _operation_requests: dict[str, list[str]] = field(default_factory=dict)
    _receipts: dict[str, RequestReceipt] = field(default_factory=dict)
    _resources: dict[str, ObservedResource] = field(default_factory=dict)
    _claims: dict[str, ProvenanceClaim] = field(default_factory=dict)
    _occurrences: dict[str, CandidateOccurrence] = field(default_factory=dict)
    _origins: set[str] = field(default_factory=set)
    _request_consumed: int = 0
    _admitted_bytes: int = 0
    _request_serial: int = 0
    exhausted: bool = False
    exhausted_reason: BoundedReason = BoundedReason.NONE

    def plan(self, operation_id: str) -> None:
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or len(operation_id) > 500
            or operation_id in self._operation_requests
        ):
            raise EnumeratorError("operation_plan")
        self._planned.append(operation_id)
        self._operation_requests[operation_id] = []

    @property
    def planned_ids(self) -> tuple[str, ...]:
        return tuple(self._planned)

    def remaining_requests(self) -> int:
        remaining = self.budget.request_limit - self._request_consumed
        return remaining if remaining > 0 else 0

    def remaining_bytes(self) -> int:
        remaining = self.budget.aggregate_byte_limit - self._admitted_bytes
        return remaining if remaining > 0 else 0

    def can_admit_candidate(self) -> bool:
        return len(self._occurrences) < self.budget.candidate_limit

    def can_admit_origin(self, origin: str) -> bool:
        if origin in self._origins:
            return True
        return len(self._origins) < self.budget.origin_limit

    def mark_exhausted(self, reason: BoundedReason) -> None:
        self.exhausted = True
        if self.exhausted_reason is BoundedReason.NONE:
            self.exhausted_reason = reason

    def can_start(self) -> bool:
        if self.exhausted:
            return False
        if self.remaining_requests() <= 0:
            self.mark_exhausted(BoundedReason.BUDGET_EXHAUSTED)
            return False
        if self.remaining_bytes() <= 0:
            self.mark_exhausted(BoundedReason.BUDGET_EXHAUSTED)
            return False
        return True

    def finish(self, operation_id: str, outcome: OperationOutcome) -> None:
        if operation_id not in self._operation_requests:
            raise EnumeratorError("operation_unknown")
        if operation_id in self._outcomes:
            raise EnumeratorError("operation_transition")
        self._outcomes[operation_id] = outcome

    def add_request(
        self,
        operation_id: str,
        *,
        attempt_kind: AttemptKind,
        outcome: RequestOutcome,
        locator: SafeLocator,
        resource_id: str | None,
        response_status: int | None,
        admitted_bytes: int,
        elapsed_ms: int,
        reason_code: BoundedReason,
        validated_address: str | None = None,
    ) -> RequestReceipt:
        if operation_id not in self._operation_requests:
            raise EnumeratorError("operation_unknown")
        if admitted_bytes < 0 or elapsed_ms < 0:
            raise EnumeratorError("request_receipt")
        self._request_serial += 1
        request_id = f"req-{self._request_serial:04d}"
        addresses = (validated_address,) if validated_address else ()
        receipt = RequestReceipt(
            request_id=request_id,
            attempt_kind=attempt_kind,
            outcome=outcome,
            locator_id=locator.url,
            resource_id=resource_id,
            response_status=response_status,
            admitted_bytes=admitted_bytes,
            elapsed_ms=elapsed_ms,
            validated_addresses=addresses,
            redirect_hops=(),
            reason_code=reason_code,
        )
        self._operation_requests[operation_id].append(request_id)
        self._receipts[request_id] = receipt
        self._request_consumed += 1
        self._admitted_bytes += admitted_bytes
        self._origins.add(locator.origin)
        if self.remaining_requests() <= 0 or self.remaining_bytes() <= 0:
            self.mark_exhausted(BoundedReason.BUDGET_EXHAUSTED)
        return receipt

    def add_resource(self, resource: ObservedResource) -> None:
        if resource.resource_id in self._resources:
            existing = self._resources[resource.resource_id]
            if existing.content_sha256 != resource.content_sha256:
                raise EnumeratorError("provenance_conflict")
            return
        if resource.resource_id in self._claims:
            raise EnumeratorError("provenance_conflict")
        self._resources[resource.resource_id] = resource

    def add_claim(self, claim: ProvenanceClaim) -> None:
        if claim.claim_id in self._claims:
            existing = self._claims[claim.claim_id]
            if existing != claim:
                raise EnumeratorError("provenance_conflict")
            return
        if claim.claim_id in self._resources:
            raise EnumeratorError("provenance_conflict")
        self._claims[claim.claim_id] = claim

    def add_occurrence(self, occurrence: CandidateOccurrence) -> None:
        if occurrence.channel != self.channel:
            raise EnumeratorError("occurrence_channel")
        if occurrence.occurrence_id in self._occurrences:
            raise EnumeratorError("occurrence_duplicate")
        if not self.can_admit_candidate():
            self.mark_exhausted(BoundedReason.CANDIDATE_LIMIT)
            return
        self._occurrences[occurrence.occurrence_id] = occurrence

    def close(self) -> ChannelReplayReceipt:
        for operation_id in self._planned:
            if operation_id not in self._outcomes:
                self._outcomes[operation_id] = "unstarted"
        operation_ids = tuple(sorted(self._planned))
        outcomes = tuple(self._outcomes[item] for item in operation_ids)
        request_ids = tuple(
            tuple(sorted(set(self._operation_requests[item]))) for item in operation_ids
        )
        succeeded = outcomes.count("succeeded")
        blocked = outcomes.count("blocked")
        rate_limited = outcomes.count("rate_limited")
        timed_out = outcomes.count("timed_out")
        failed = outcomes.count("failed")
        cancelled = outcomes.count("cancelled")
        unstarted = outcomes.count("unstarted")
        unfinished = tuple(
            item
            for item, outcome in zip(operation_ids, outcomes, strict=True)
            if outcome == "unstarted"
        )
        if unstarted or self.exhausted or failed or timed_out or cancelled:
            if succeeded or blocked or rate_limited or unstarted or self.exhausted:
                channel_state: Literal["complete", "partial", "failed", "cancelled"] = (
                    "partial"
                )
            else:
                channel_state = "failed"
        else:
            channel_state = "complete"
        accounting = ChannelOperationAccounting(
            channel=self.channel,
            channel_state=channel_state,
            planned_operations=len(operation_ids),
            succeeded=succeeded,
            blocked=blocked,
            rate_limited=rate_limited,
            timed_out=timed_out,
            failed=failed,
            cancelled=cancelled,
            unstarted=unstarted,
            request_limit=self.budget.request_limit,
            request_consumed=self._request_consumed,
            request_in_flight=0,
            request_remaining=self.budget.request_limit - self._request_consumed,
            byte_limit=self.budget.aggregate_byte_limit,
            admitted_bytes=self._admitted_bytes,
            remaining_bytes=self.budget.aggregate_byte_limit - self._admitted_bytes,
            unfinished_operation_ids=unfinished,
        )
        return ChannelReplayReceipt(
            schema_version=1,
            enumerator_version=self.enumerator_version,
            channel=self.channel,
            input_set_sha256=self.input_set_sha256,
            operation_ids=operation_ids,
            operation_outcomes=outcomes,
            operation_request_ids=request_ids,
            occurrences=tuple(
                self._occurrences[item] for item in sorted(self._occurrences)
            ),
            resources=tuple(self._resources[item] for item in sorted(self._resources)),
            request_receipts=tuple(
                self._receipts[item] for item in sorted(self._receipts)
            ),
            provenance_claims=tuple(
                self._claims[item] for item in sorted(self._claims)
            ),
            accounting=accounting,
        )


def digest_input_set(payload: object) -> str:
    """SHA-256 of canonical enumerator input, excluding raw observation bodies."""

    return sha256(canonical_json_bytes(payload)).hexdigest()


def observation_digest(observation: CapturedObservation) -> dict[str, object]:
    body = observation.body
    return {
        "bodySha256": sha256(body).hexdigest() if isinstance(body, bytes) else None,
        "cachedAgeSeconds": observation.cached_age_seconds,
        "elapsedMs": observation.elapsed_ms,
        "etag": observation.etag,
        "lastModified": observation.last_modified,
        "locator": observation.locator,
        "mediaType": observation.media_type,
        "sizeBytes": len(body) if isinstance(body, bytes) else 0,
        "statusCode": observation.status_code,
        "transportState": observation.transport_state,
        "validatedAddress": observation.validated_address,
    }


def require_channel_profile(
    profile: ChannelProfile,
    channel: ChannelName,
) -> ChannelProfile:
    if profile.channel != channel:
        raise EnumeratorError("channel_profile")
    return profile


def require_observed_at(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EnumeratorError("observed_at")
    return value.astimezone(UTC)


def canonical_locator(locator: str) -> SafeLocator:
    try:
        return validate_public_locator(locator)
    except DiscoveryTransportError as error:
        raise EnumeratorError(error.reason_code) from error


def lookup_observation(
    observations: Mapping[str, CapturedObservation],
    locator: SafeLocator,
) -> CapturedObservation | None:
    direct = observations.get(locator.url)
    if direct is not None:
        return direct
    for observation in observations.values():
        try:
            if canonical_locator(observation.locator).url == locator.url:
                return observation
        except EnumeratorError:
            continue
    return None


def observation_map(
    values: Iterable[CapturedObservation] | Mapping[str, CapturedObservation],
) -> dict[str, CapturedObservation]:
    if isinstance(values, Mapping):
        iterable = values.values()
    else:
        iterable = values
    mapping: dict[str, CapturedObservation] = {}
    for observation in iterable:
        if not isinstance(observation, CapturedObservation):
            raise EnumeratorError("observation_type")
        locator = canonical_locator(observation.locator)
        mapping[locator.url] = observation
    return mapping


def origin_allowed(profile: ChannelProfile, locator: SafeLocator) -> bool:
    return locator.origin in profile.allowed_origins


def request_outcome_from_observation(
    observation: CapturedObservation,
) -> tuple[RequestOutcome, BoundedReason]:
    state = observation.transport_state
    if state == "missing":
        return "failed", BoundedReason.EVIDENCE_INCOMPLETE
    if state == "network_unreachable":
        return "failed", BoundedReason.TRANSPORT_REJECTED
    if state == "security_rejected_redirect":
        return "blocked", BoundedReason.REDIRECT_REJECTED
    if state in {"not_modified", "verified_cache"}:
        return "succeeded", BoundedReason.NONE
    status = observation.status_code
    if status is None or isinstance(status, bool):
        return "failed", BoundedReason.TRANSPORT_REJECTED
    if status == 429:
        return "rate_limited", BoundedReason.RATE_LIMITED
    if status in {401, 403, 407}:
        return "blocked", BoundedReason.AUTH_REQUIRED
    if 300 <= status <= 399:
        return "blocked", BoundedReason.REDIRECT_REJECTED
    if status in {408, 504}:
        return "timed_out", BoundedReason.TIMED_OUT
    if 500 <= status <= 599:
        return "failed", BoundedReason.ACCESS_BLOCKED
    if 400 <= status <= 499:
        return "failed", BoundedReason.EVIDENCE_INCOMPLETE
    if 200 <= status <= 299:
        return "succeeded", BoundedReason.NONE
    return "failed", BoundedReason.TRANSPORT_REJECTED


def resource_id_for(locator: SafeLocator, *, role: str) -> str:
    digest = sha256(f"{role}:{locator.url}".encode("utf-8")).hexdigest()
    return f"res-{digest}"


def claim_id_for(resource_id: str, field_name: str) -> str:
    digest = sha256(f"{resource_id}:{field_name}".encode("utf-8")).hexdigest()
    return f"claim-{digest}"


def admit_observation_resource(
    builder: ChannelRunBuilder,
    observation: CapturedObservation,
    locator: SafeLocator,
    *,
    role: str,
    media_type: str,
) -> ObservedResource | None:
    body = observation.body
    if not isinstance(body, bytes):
        return None
    if len(body) > builder.budget.response_byte_limit:
        return None
    if len(body) > builder.remaining_bytes():
        builder.mark_exhausted(BoundedReason.BUDGET_EXHAUSTED)
        return None
    held: list[bytes] = []
    try:
        admitted = admit_scanned_content(
            (body,),
            max_bytes=builder.budget.response_byte_limit,
            write=held.append,
            digest=lambda data: sha256(data).hexdigest(),
        )
    except SecretDetectedError:
        return None
    resource = ObservedResource(
        resource_id=resource_id_for(locator, role=role),
        role=role,
        media_type=media_type,
        content_sha256=admitted.content_sha256,
        size_bytes=admitted.size_bytes,
        observed_at=builder.observed_at,
        final_locator=locator.url,
        validated_address=observation.validated_address,
        etag=observation.etag,
        last_modified=observation.last_modified,
    )
    builder.add_resource(resource)
    return resource


def add_local_claim(
    builder: ChannelRunBuilder,
    *,
    resource_id: str,
    field_name: str,
    value: str | None,
    accepted: bool = True,
) -> ProvenanceClaim:
    claim = ProvenanceClaim(
        claim_id=claim_id_for(resource_id, field_name),
        resource_id=resource_id,
        field_name=field_name,
        value=value,
        source="local_observation",
        accepted=accepted,
    )
    builder.add_claim(claim)
    return claim


def add_remote_claim(
    builder: ChannelRunBuilder,
    *,
    resource_id: str,
    field_name: str,
    value: str | None,
) -> ProvenanceClaim:
    claim = ProvenanceClaim(
        claim_id=claim_id_for(resource_id, f"remote:{field_name}"),
        resource_id=resource_id,
        field_name=field_name,
        value=value,
        source="remote_assertion",
        accepted=False,
    )
    builder.add_claim(claim)
    return claim


def occurrence_from_locator(
    *,
    occurrence_id: str,
    channel: ChannelName,
    locator: SafeLocator,
    provider_id: str,
    owner: str,
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"],
    provenance_ids: Sequence[str],
    provider_token: str | None = None,
    adapter_id: str | None = None,
    key: str | None = None,
) -> CandidateOccurrence:
    identity = normalize_candidate_identity(
        key=key or _stable_key(locator),
        url=locator.url,
        provider_id=provider_id,
        provider_token=provider_token,
        owner=owner,
        candidate_kind=candidate_kind,
        adapter_id=adapter_id,
    )
    return CandidateOccurrence(
        occurrence_id=occurrence_id,
        channel=channel,
        identity=identity,
        provenance_ids=tuple(provenance_ids),
    )


def _stable_key(locator: SafeLocator) -> str:
    parsed = urlsplit(locator.url)
    path = parsed.path.strip("/") or "root"
    raw = f"{locator.hostname}-{path}".replace("/", "-").casefold()
    return raw[:200] or locator.hostname


def json_contains_remote_parser_identifier(value: object) -> bool:
    pending: list[object] = [value]
    seen = 0
    while pending:
        seen += 1
        if seen > 10_000:
            return True
        item = pending.pop()
        if isinstance(item, Mapping):
            if any(key in _REMOTE_PARSER_KEYS for key in item):
                return True
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def parse_bounded_json(body: bytes, *, depth_limit: int) -> object:
    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, item in pairs:
            if key in decoded:
                raise EnumeratorError("parser_rejected")
            decoded[key] = item
        return decoded

    try:
        text = body.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=reject_duplicate)
    except EnumeratorError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise EnumeratorError("parser_rejected") from error
    if _json_depth(value) > depth_limit:
        raise EnumeratorError("parser_rejected")
    return value


def _json_depth(value: object) -> int:
    maximum = 0
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        item, parent = pending.pop()
        if isinstance(item, dict):
            depth = parent + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item.values())
        elif isinstance(item, list):
            depth = parent + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item)
    return maximum


def parse_bounded_xml(body: bytes, *, depth_limit: int) -> ElementTree.Element:
    upper = body.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise EnumeratorError("parser_rejected")
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, RecursionError, ValueError) as error:
        raise EnumeratorError("parser_rejected") from error
    pending: list[tuple[ElementTree.Element, int]] = [(root, 1)]
    while pending:
        element, depth = pending.pop()
        if depth > depth_limit:
            raise EnumeratorError("parser_rejected")
        pending.extend((child, depth + 1) for child in element)
    return root


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class _BoundedLinkParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.nodes = 0
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > self.limit:
            raise EnumeratorError("parser_rejected")
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def parse_html_locators(body: bytes, *, node_limit: int) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8", errors="strict")
        parser = _BoundedLinkParser(node_limit)
        parser.feed(text)
        parser.close()
    except EnumeratorError:
        raise
    except Exception as error:
        raise EnumeratorError("parser_rejected") from error
    return tuple(parser.hrefs)


def path_is_dependency_manifest(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].casefold()
    return name in _DEPENDENCY_NAMES


def media_is_archive(media_type: str | None, path: str) -> bool:
    lowered = (media_type or "").casefold().split(";", 1)[0].strip()
    name = path.rsplit("/", 1)[-1].casefold()
    return lowered in _ARCHIVE_MEDIA_TYPES or name.endswith(_ARCHIVE_SUFFIXES)


def media_is_executable(media_type: str | None, path: str) -> bool:
    lowered = (media_type or "").casefold().split(";", 1)[0].strip()
    name = path.rsplit("/", 1)[-1].casefold()
    return lowered in _EXECUTABLE_MEDIA_TYPES or name.endswith(_EXECUTABLE_SUFFIXES)


def sitemap_entries(
    root: ElementTree.Element,
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    kind = xml_local_name(root.tag)
    if kind not in {"sitemapindex", "urlset"}:
        raise EnumeratorError("parser_rejected")
    tag = "sitemap" if kind == "sitemapindex" else "url"
    entries: list[tuple[str, str | None]] = []
    for child in root:
        if xml_local_name(child.tag) != tag:
            continue
        locator = None
        lastmod = None
        for nested in child:
            local = xml_local_name(nested.tag)
            if local == "loc" and nested.text:
                locator = nested.text.strip()
            elif local == "lastmod" and nested.text:
                lastmod = nested.text.strip()
        if locator:
            entries.append((locator, lastmod))
    return kind, tuple(entries)
