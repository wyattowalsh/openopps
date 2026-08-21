"""Bounded, fully redacted discovery diagnostics and metric attributes.

Arbitrary upstream text is never rendered.  Callers receive a fixed summary for
one repository-owned reason code plus, when supplied, a digest of only the
bounded admitted prefix.  Metric attributes accept only finite enums, booleans,
and an optional canonical digest identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from types import MappingProxyType
from typing import Final, Literal, Mapping

from openopps.discovery.models import BoundedReason, DiscoveryChannel


MAX_DIAGNOSTIC_INPUT_BYTES: Final = 4_096
MAX_DIAGNOSTIC_SUMMARY_CHARS: Final = 96
MAX_METRIC_ATTRIBUTES: Final = 6

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset(
    {"complete", "partial", "failed", "cancelled", "aborted", "nonterminal"}
)


class DiagnosticRenderingError(ValueError):
    """Raised when a diagnostic would escape the bounded rendering contract."""


@dataclass(frozen=True, slots=True)
class BoundedDiagnostic:
    """One redacted diagnostic containing no caller-controlled text."""

    reason_code: BoundedReason
    summary: str
    detail_prefix_sha256: str | None
    admitted_detail_bytes: int
    detail_truncated: bool

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible diagnostic mapping."""

        return {
            "admittedDetailBytes": self.admitted_detail_bytes,
            "detailPrefixSha256": self.detail_prefix_sha256,
            "detailTruncated": self.detail_truncated,
            "reasonCode": self.reason_code.value,
            "summary": self.summary,
        }


def _bounded_utf8_prefix(detail: str | bytes) -> tuple[bytes, bool]:
    if isinstance(detail, bytes):
        admitted = detail[:MAX_DIAGNOSTIC_INPUT_BYTES]
        return admitted, len(detail) > len(admitted)
    if not isinstance(detail, str):
        raise DiagnosticRenderingError("diagnostic detail must be text or bytes")

    admitted = bytearray()
    truncated = False
    for character in detail:
        encoded = character.encode("utf-8", errors="replace")
        if len(admitted) + len(encoded) > MAX_DIAGNOSTIC_INPUT_BYTES:
            truncated = True
            break
        admitted.extend(encoded)
    return bytes(admitted), truncated


def _fixed_summary(reason_code: BoundedReason) -> str:
    if reason_code is BoundedReason.NONE:
        return "No discovery failure was recorded."
    label = reason_code.value.replace("_", " ")
    summary = f"Discovery stopped with bounded reason: {label}."
    if len(summary) > MAX_DIAGNOSTIC_SUMMARY_CHARS:  # Defensive enum evolution.
        raise DiagnosticRenderingError("bounded reason summary exceeds its limit")
    return summary


def render_bounded_diagnostic(
    reason_code: BoundedReason,
    *,
    detail: str | bytes | None = None,
) -> BoundedDiagnostic:
    """Render a fixed diagnostic without exposing raw URLs, queries, or secrets."""

    if not isinstance(reason_code, BoundedReason):
        raise DiagnosticRenderingError("reason code must use the bounded enum")
    if detail is None:
        admitted = b""
        truncated = False
        digest = None
    else:
        admitted, truncated = _bounded_utf8_prefix(detail)
        digest = sha256(admitted).hexdigest()
    return BoundedDiagnostic(
        reason_code=reason_code,
        summary=_fixed_summary(reason_code),
        detail_prefix_sha256=digest,
        admitted_detail_bytes=len(admitted),
        detail_truncated=truncated,
    )


def render_metric_attributes(
    *,
    channel: DiscoveryChannel | None,
    terminal_state: Literal[
        "complete", "partial", "failed", "cancelled", "aborted", "nonterminal"
    ],
    reason_code: BoundedReason,
    complete: bool,
    identity_digest: str | None = None,
) -> Mapping[str, bool | str]:
    """Return a small immutable OpenTelemetry-style discovery attribute set."""

    if channel is not None and not isinstance(channel, DiscoveryChannel):
        raise DiagnosticRenderingError("metric channel must use the bounded enum")
    if terminal_state not in _TERMINAL_STATES:
        raise DiagnosticRenderingError("metric terminal state is unsupported")
    if not isinstance(reason_code, BoundedReason):
        raise DiagnosticRenderingError("metric reason must use the bounded enum")
    if not isinstance(complete, bool):
        raise DiagnosticRenderingError("metric completeness must be boolean")
    if identity_digest is not None and _SHA256_RE.fullmatch(identity_digest) is None:
        raise DiagnosticRenderingError("metric identity must be canonical SHA-256")

    if channel is not None and terminal_state == "aborted":
        raise DiagnosticRenderingError("aborted is a whole-run state only")
    if complete != (terminal_state == "complete"):
        raise DiagnosticRenderingError("metric completeness conflicts with state")
    if terminal_state == "complete" and reason_code is not BoundedReason.NONE:
        raise DiagnosticRenderingError("complete metric cannot carry a failure reason")
    if terminal_state in {"partial", "failed", "cancelled", "aborted"} and (
        reason_code is BoundedReason.NONE
    ):
        raise DiagnosticRenderingError("terminal failure metric needs a bounded reason")

    attributes: dict[str, bool | str] = {
        "openopps.discovery.complete": complete,
        "openopps.discovery.reason": reason_code.value,
        "openopps.discovery.scope": "channel" if channel is not None else "run",
        "openopps.discovery.state": terminal_state,
    }
    if channel is not None:
        attributes["openopps.discovery.channel"] = channel.value
    if identity_digest is not None:
        attributes["openopps.discovery.identity.sha256"] = identity_digest
    if len(attributes) > MAX_METRIC_ATTRIBUTES:  # Defensive contract assertion.
        raise DiagnosticRenderingError("metric attribute set exceeds its limit")
    return MappingProxyType(attributes)
