"""Bounded high-confidence secret detection before persistence or digesting."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import re


SECRET_DETECTOR_VERSION = "openopps.discovery.secrets.v1"


_SECRET_PATTERNS = (
    re.compile(rb"authorization\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
    re.compile(
        rb"[\"']authorization[\"']\s*:\s*[\"']bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        re.I,
    ),
    re.compile(rb"cookie\s*[:=]\s*[^\r\n]{12,}", re.I),
    re.compile(rb"x-amz-(?:credential|signature)=[^&\s\"']{12,}", re.I),
    re.compile(
        rb"(?:api[-_ ]?key|secret|token)\s*[\"']?\s*(?:content\s*=|[:=])\s*[\"']?[^\s\"'<>&]{12,}",
        re.I,
    ),
    re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.I),
)


class SecretDetectedError(ValueError):
    """A safe bounded failure that never retains or renders scanned bytes."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class AdmittedContent:
    detector_version: str
    size_bytes: int
    content_sha256: str


def admit_scanned_content(
    chunks: Iterable[bytes],
    *,
    max_bytes: int,
    write: Callable[[bytes], None],
    digest: Callable[[bytes], str],
) -> AdmittedContent:
    """Scan the complete bounded content before invoking either side effect."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise SecretDetectedError("secret_scan_budget")
    parts: list[bytes] = []
    size_bytes = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise SecretDetectedError("secret_scan_input")
        size_bytes += len(chunk)
        if size_bytes > max_bytes:
            raise SecretDetectedError("secret_scan_budget")
        parts.append(chunk)
    content = b"".join(parts)
    if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
        raise SecretDetectedError("secret_detected")
    content_sha256 = digest(content)
    write(content)
    return AdmittedContent(
        detector_version=SECRET_DETECTOR_VERSION,
        size_bytes=size_bytes,
        content_sha256=content_sha256,
    )
