from __future__ import annotations

import re
from hashlib import sha1
from typing import Any


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or sha1(value.encode("utf-8")).hexdigest()[:12]


def stable_id(*parts: Any) -> str:
    visible = ":".join(
        slugify(str(part)) for part in parts if part is not None and str(part) != ""
    )
    if len(visible) <= 180:
        return visible
    return f"{visible[:120]}-{sha1(visible.encode('utf-8')).hexdigest()[:16]}"


def source_board_key(source_key: str, remote_key: Any) -> str:
    return stable_id(source_key, remote_key)


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None
