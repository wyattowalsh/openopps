"""Provider-aware liveness evidence. Replay-first; never proves permanent absence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from openopps.discovery.enumerators import (
    CapturedObservation,
    EnumeratorError,
    parse_bounded_json,
)
from openopps.discovery.models import BoundedReason, LivenessEvidence
from openopps.discovery.secrets import SecretDetectedError, admit_scanned_content
from openopps.discovery.transport import (
    DiscoveryTransportError,
    validate_public_locator,
)


PERMANENT_ABSENCE_ENABLED: Literal[False] = False
LIVENESS_DETECTOR_MAX_BYTES = 4_194_304
JSON_ARRAY_JOB_PROVIDERS = frozenset({"lever"})
_JOB_ARRAY_KEYS = ("jobs", "jobPostings", "postings", "results", "items")
_JOB_FIELD_MARKERS = frozenset(
    {
        "absolute_url",
        "absoluteurl",
        "hostedurl",
        "id",
        "jobtitle",
        "text",
        "title",
        "url",
    }
)
_CHALLENGE_MARKERS = (
    b"cf-challenge",
    b"hcaptcha",
    b"g-recaptcha",
    b"just a moment",
    b"attention required",
)
_TRANSIENT_CLASSES = frozenset(
    {
        "timeout",
        "dns_error",
        "tls_error",
        "rate_limited",
        "http_5xx",
        "auth_required",
        "permission_required",
        "cancelled",
        "network_unreachable",
    }
)
_REJECTED_LIVE_CLASSES = frozenset(
    {
        "challenge",
        "redirect_loop",
        "http_200_unrelated",
        "generic_error",
        "cached_or_conditional",
        "not_modified",
        "landing_page",
        "evidence_incomplete",
    }
)


class LivenessDisposition(StrEnum):
    LIVE = "live"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class InjectedTransportResult:
    """Bounded injected-client result. Not a live ``openopps.http`` fetch."""

    status_code: int | None
    body: bytes | None
    media_type: str | None
    cached: bool
    transport_error: str | None
    redirect_loop: bool
    elapsed_ms: int
    request_id: str
    challenge: bool = False


class LivenessTransportClient:
    """Structural client protocol consumed by V512 tests and later adapters."""

    def get_uncached(self, url: str) -> InjectedTransportResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class LivenessProbeRecord:
    """V515 probe context: time, class, markers, and bounded receipt identity."""

    observed_at: datetime
    response_class: str
    structural_markers: tuple[str, ...]
    expected_structure: bool
    listing_endpoint: str
    cached: bool
    receipt_id: str | None
    reason_code: BoundedReason
    permanent_absence: Literal[False] = False

    def as_dict(self) -> dict[str, object]:
        observed = self.observed_at.astimezone(UTC)
        stamp = observed.strftime("%Y-%m-%dT%H:%M:%S")
        if observed.microsecond:
            stamp = observed.strftime("%Y-%m-%dT%H:%M:%S.%f")
        return {
            "cached": self.cached,
            "expectedStructure": self.expected_structure,
            "listingEndpoint": self.listing_endpoint,
            "observedAt": f"{stamp}Z",
            "permanentAbsence": False,
            "reasonCode": self.reason_code.value,
            "receiptId": self.receipt_id,
            "responseClass": self.response_class,
            "structuralMarkers": list(self.structural_markers),
        }


def classify_liveness(evidence: LivenessEvidence) -> LivenessDisposition:
    if evidence.response_class in _TRANSIENT_CLASSES | _REJECTED_LIVE_CLASSES:
        return LivenessDisposition.INCONCLUSIVE
    if evidence.response_class == "expected_payload" and evidence.expected_structure:
        return LivenessDisposition.LIVE
    return LivenessDisposition.INCONCLUSIVE


def jobs_capable_structure(
    *,
    provider_id: str,
    media_type: str | None,
    body: bytes | None,
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the body is a parseable jobs-capable listing/catalog."""

    if body is None:
        return False, ("missing_body",)
    try:
        admit_scanned_content(
            (body,),
            max_bytes=LIVENESS_DETECTOR_MAX_BYTES,
            write=lambda _: None,
            digest=lambda payload: sha256(payload).hexdigest(),
        )
    except SecretDetectedError:
        return False, ("secret_detected",)
    lowered = (media_type or "").casefold()
    if "json" in lowered:
        try:
            value = parse_bounded_json(body, depth_limit=8)
        except EnumeratorError:
            return False, ("parser_rejected",)
        return _json_jobs_capable(value, provider_id=provider_id.casefold())
    if "html" in lowered or "xml" in lowered:
        return _html_jobs_capable(body)
    return False, ("unsupported_media",)


def probe_liveness(
    locator: str,
    *,
    observed_at: datetime,
    provider_id: str,
    observation: CapturedObservation | None = None,
    transport_client: LivenessTransportClient | None = None,
) -> tuple[LivenessEvidence, LivenessProbeRecord]:
    """Classify one listing endpoint. Replay wins; injected client is optional."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("liveness observation time must be timezone-aware")
    observed = observed_at.astimezone(UTC)
    try:
        safe = validate_public_locator(locator)
        listing = safe.url
    except DiscoveryTransportError:
        return _record(
            observed_at=observed,
            response_class="generic_error",
            markers=("locator_rejected",),
            expected=False,
            listing=locator,
            cached=False,
            receipt_id=None,
            reason=BoundedReason.TRANSPORT_REJECTED,
        )
    if observation is not None:
        return _from_observation(
            observation,
            listing_endpoint=listing,
            observed_at=observed,
            provider_id=provider_id,
        )
    if transport_client is not None:
        result = transport_client.get_uncached(listing)
        return _from_injected(
            result,
            listing_endpoint=listing,
            observed_at=observed,
            provider_id=provider_id,
        )
    return _record(
        observed_at=observed,
        response_class="evidence_incomplete",
        markers=("replay_required",),
        expected=False,
        listing=listing,
        cached=False,
        receipt_id=None,
        reason=BoundedReason.EVIDENCE_INCOMPLETE,
    )


def _from_observation(
    observation: CapturedObservation,
    *,
    listing_endpoint: str,
    observed_at: datetime,
    provider_id: str,
) -> tuple[LivenessEvidence, LivenessProbeRecord]:
    cached = (
        observation.cached_age_seconds is not None
        or observation.transport_state in {"verified_cache", "not_modified"}
    )
    receipt_id = f"obs:{sha256(observation.locator.encode('utf-8')).hexdigest()[:16]}"
    try:
        observed_listing = validate_public_locator(observation.locator).url
    except DiscoveryTransportError:
        observed_listing = ""
    if observed_listing != listing_endpoint:
        return _record(
            observed_at=observed_at,
            response_class="evidence_incomplete",
            markers=("locator_mismatch",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.EVIDENCE_INCOMPLETE,
        )
    if observation.transport_state == "network_unreachable":
        return _record(
            observed_at=observed_at,
            response_class="dns_error",
            markers=("network_unreachable",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.DNS_REJECTED,
        )
    if observation.transport_state == "security_rejected_redirect":
        return _record(
            observed_at=observed_at,
            response_class="redirect_loop",
            markers=("security_rejected_redirect",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.REDIRECT_REJECTED,
        )
    if cached:
        return _record(
            observed_at=observed_at,
            response_class="cached_or_conditional",
            markers=("cached_observation", observation.transport_state),
            expected=False,
            listing=listing_endpoint,
            cached=True,
            receipt_id=receipt_id,
            reason=BoundedReason.EVIDENCE_STALE,
        )
    if observation.transport_state == "missing":
        return _record(
            observed_at=observed_at,
            response_class="evidence_incomplete",
            markers=("missing_observation",),
            expected=False,
            listing=listing_endpoint,
            cached=False,
            receipt_id=receipt_id,
            reason=BoundedReason.EVIDENCE_INCOMPLETE,
        )
    return _from_http_fields(
        status_code=observation.status_code,
        body=observation.body,
        media_type=observation.media_type,
        cached=False,
        redirect_loop=False,
        transport_error=None,
        challenge=_looks_like_challenge(observation.body),
        listing_endpoint=listing_endpoint,
        observed_at=observed_at,
        provider_id=provider_id,
        receipt_id=receipt_id,
    )


def _from_injected(
    result: InjectedTransportResult,
    *,
    listing_endpoint: str,
    observed_at: datetime,
    provider_id: str,
) -> tuple[LivenessEvidence, LivenessProbeRecord]:
    if result.cached:
        return _record(
            observed_at=observed_at,
            response_class="cached_or_conditional",
            markers=("injected_cache",),
            expected=False,
            listing=listing_endpoint,
            cached=True,
            receipt_id=result.request_id,
            reason=BoundedReason.EVIDENCE_STALE,
        )
    return _from_http_fields(
        status_code=result.status_code,
        body=result.body,
        media_type=result.media_type,
        cached=False,
        redirect_loop=result.redirect_loop,
        transport_error=result.transport_error,
        challenge=result.challenge or _looks_like_challenge(result.body),
        listing_endpoint=listing_endpoint,
        observed_at=observed_at,
        provider_id=provider_id,
        receipt_id=result.request_id,
    )


def _from_http_fields(
    *,
    status_code: int | None,
    body: bytes | None,
    media_type: str | None,
    cached: bool,
    redirect_loop: bool,
    transport_error: str | None,
    challenge: bool,
    listing_endpoint: str,
    observed_at: datetime,
    provider_id: str,
    receipt_id: str | None,
) -> tuple[LivenessEvidence, LivenessProbeRecord]:
    if transport_error in _TRANSIENT_CLASSES:
        reason = {
            "timeout": BoundedReason.TIMED_OUT,
            "dns_error": BoundedReason.DNS_REJECTED,
            "tls_error": BoundedReason.TRANSPORT_REJECTED,
            "rate_limited": BoundedReason.RATE_LIMITED,
            "auth_required": BoundedReason.AUTH_REQUIRED,
            "permission_required": BoundedReason.ACCESS_BLOCKED,
            "cancelled": BoundedReason.EVIDENCE_INCOMPLETE,
            "http_5xx": BoundedReason.TRANSPORT_REJECTED,
            "network_unreachable": BoundedReason.DNS_REJECTED,
        }[transport_error]
        return _record(
            observed_at=observed_at,
            response_class=transport_error,
            markers=(transport_error,),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=reason,
        )
    if redirect_loop:
        return _record(
            observed_at=observed_at,
            response_class="redirect_loop",
            markers=("redirect_loop",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.REDIRECT_REJECTED,
        )
    if challenge:
        return _record(
            observed_at=observed_at,
            response_class="challenge",
            markers=("challenge",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.CONTENT_REJECTED,
        )
    if status_code in {401, 403}:
        return _record(
            observed_at=observed_at,
            response_class="auth_required",
            markers=(f"http_{status_code}",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.AUTH_REQUIRED,
        )
    if status_code == 429:
        return _record(
            observed_at=observed_at,
            response_class="rate_limited",
            markers=("http_429",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.RATE_LIMITED,
        )
    if status_code is not None and status_code >= 500:
        return _record(
            observed_at=observed_at,
            response_class="http_5xx",
            markers=(f"http_{status_code}",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.TRANSPORT_REJECTED,
        )
    if status_code != 200:
        return _record(
            observed_at=observed_at,
            response_class="generic_error",
            markers=(f"http_{status_code}",),
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.CONTENT_REJECTED,
        )
    capable, markers = jobs_capable_structure(
        provider_id=provider_id,
        media_type=media_type,
        body=body,
    )
    if "secret_detected" in markers:
        return _record(
            observed_at=observed_at,
            response_class="generic_error",
            markers=markers,
            expected=False,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.SECRET_DETECTED,
        )
    if capable:
        return _record(
            observed_at=observed_at,
            response_class="expected_payload",
            markers=markers,
            expected=True,
            listing=listing_endpoint,
            cached=cached,
            receipt_id=receipt_id,
            reason=BoundedReason.NONE,
        )
    response_class = (
        "landing_page" if "html_unrelated" in markers else "http_200_unrelated"
    )
    return _record(
        observed_at=observed_at,
        response_class=response_class,
        markers=markers or ("unrelated_http_200",),
        expected=False,
        listing=listing_endpoint,
        cached=cached,
        receipt_id=receipt_id,
        reason=BoundedReason.CONTENT_REJECTED,
    )


def _record(
    *,
    observed_at: datetime,
    response_class: str,
    markers: tuple[str, ...],
    expected: bool,
    listing: str,
    cached: bool,
    receipt_id: str | None,
    reason: BoundedReason,
) -> tuple[LivenessEvidence, LivenessProbeRecord]:
    evidence = LivenessEvidence(
        response_class=response_class,
        expected_structure=expected,
        observed_at=observed_at,
    )
    probe = LivenessProbeRecord(
        observed_at=observed_at,
        response_class=response_class,
        structural_markers=markers,
        expected_structure=expected,
        listing_endpoint=listing,
        cached=cached,
        receipt_id=receipt_id,
        reason_code=reason,
        permanent_absence=False,
    )
    return evidence, probe


def _looks_like_challenge(body: bytes | None) -> bool:
    if not body:
        return False
    lowered = body[:12_000].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _json_jobs_capable(
    value: object, *, provider_id: str
) -> tuple[bool, tuple[str, ...]]:
    if isinstance(value, list):
        if provider_id not in JSON_ARRAY_JOB_PROVIDERS:
            return False, ("json_unrelated_array",)
        if not value:
            return True, ("json_job_array", "empty_job_array")
        if any(
            isinstance(item, Mapping) and _looks_like_job(item) for item in value[:8]
        ):
            return True, ("json_job_array",)
        return False, ("json_unrelated_array",)
    if not isinstance(value, Mapping):
        return False, ("json_unrelated",)
    if "sources" in value and isinstance(value["sources"], list):
        return True, ("json_catalog_sources",)
    for key in _JOB_ARRAY_KEYS:
        jobs = value.get(key)
        if not isinstance(jobs, list):
            continue
        if not jobs:
            return True, (f"json_{key}", "empty_job_array")
        if any(
            isinstance(item, Mapping) and _looks_like_job(item) for item in jobs[:8]
        ):
            return True, (f"json_{key}",)
        return False, (f"json_unrelated_{key}",)
    return False, ("json_unrelated",)


def _looks_like_job(item: Mapping[str, object]) -> bool:
    keys = {str(key).casefold() for key in item}
    return bool(keys & _JOB_FIELD_MARKERS)


def _html_jobs_capable(body: bytes) -> tuple[bool, tuple[str, ...]]:
    text = body[:200_000].lower()
    if _looks_like_challenge(body):
        return False, ("challenge",)
    if b"application/ld+json" in text and b"jobposting" in text:
        return True, ("jsonld_jobposting",)
    return False, ("html_unrelated",)
