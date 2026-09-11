from __future__ import annotations

import re
from urllib.parse import unquote_to_bytes

from openopps.models import BoardRecord

URL_PULL_SOURCE_KEY = "url-pull"
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def decode_url_identity_segment(value: str) -> str | None:
    """Decode one bounded path identity without admitting path/query delimiters.

    Byte-identical to ``openopps.providers.pull.decode_url_identity_segment``.
    """

    if not value or _INVALID_PERCENT_ESCAPE_RE.search(value):
        return None
    try:
        identity = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        not identity
        or identity in {".", ".."}
        or len(identity) > 500
        or "%" in identity
        or any(character in identity for character in "/\\?#")
        or any(character.isspace() for character in identity)
        or any(ord(character) < 32 or ord(character) == 127 for character in identity)
    ):
        return None
    return identity


def strict_decoded_path_parts(path: str) -> tuple[str, ...] | None:
    """Split an absolute URL path into decoded identity segments, or reject it.

    Byte-identical to the former Rippling/Workable/Workday ``_strict_path_parts``.
    Greenhouse, Lever, Teamtailor, Ashby, and BambooHR keep their own decoders.
    """

    normalized = path[:-1] if path.endswith("/") and path != "/" else path
    if not normalized.startswith("/"):
        return None
    raw = normalized[1:]
    if not raw or any(not part for part in raw.split("/")):
        return None
    parts: list[str] = []
    for raw_part in raw.split("/"):
        part = decode_url_identity_segment(raw_part)
        if part is None:
            return None
        parts.append(part)
    return tuple(parts)


def synthetic_url_pull_board(
    board_identity: str,
    *,
    name: str | None = None,
    remote_slug: str | None = None,
) -> BoardRecord:
    """Board identity used by URL-list until catalog bind is intentionally applied."""

    return BoardRecord(
        key=board_identity,
        source_key=URL_PULL_SOURCE_KEY,
        remote_id=board_identity,
        remote_slug=remote_slug,
        name=name or board_identity,
    )
