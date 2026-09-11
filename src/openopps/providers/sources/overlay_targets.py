"""Load overlay.json into discovery EmployerTarget rows.

Locators stay maintainer-owned. A company domain never invents an ATS token.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openopps.discovery.targeted_ats import EmployerTarget

GOAL_OVERLAY_RELATIVE = Path("goals") / "expand-job-seeker-coverage" / "overlay.json"
PACKAGED_OVERLAY_FILENAME = "job_seeker_overlay.json"
_TARGET_BUCKETS = (
    "core",
    "expand",
    "b_tier",
    "b-tier",
    "bTier",
    "growth",
    "targets",
)
_ID_FIELDS = ("id", "target_id", "targetId")
_LOCATOR_FIELDS = ("locator", "public_page_locator", "publicPageLocator")
_HINT_FIELDS = ("claimed_provider_hint", "claimedProviderHint")


def overlay_json_path(*, start: Path | None = None) -> Path | None:
    """Return the goal overlay.json via Path.parents, else a packaged copy."""

    anchor = (start or Path(__file__)).resolve()
    roots = anchor.parents if anchor.is_file() else (anchor, *anchor.parents)
    for parent in roots:
        candidate = parent / GOAL_OVERLAY_RELATIVE
        if candidate.is_file():
            return candidate
    packaged = Path(__file__).resolve().parent / "data" / PACKAGED_OVERLAY_FILENAME
    if packaged.is_file():
        return packaged
    return None


def load_overlay_targets(
    *,
    overlay_path: Path | None = None,
) -> tuple[EmployerTarget, ...]:
    """Build sorted unique EmployerTarget rows from overlay.json."""

    from openopps.discovery.targeted_ats import EmployerTarget
    from openopps.discovery.transport import (
        DiscoveryTransportError,
        validate_public_locator,
    )

    path = overlay_path if overlay_path is not None else overlay_json_path()
    if path is None:
        raise FileNotFoundError(GOAL_OVERLAY_RELATIVE.as_posix())
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    targets: list[EmployerTarget] = []
    seen: set[str] = set()
    for row in _overlay_rows(payload):
        locator = _text_field(row, _LOCATOR_FIELDS)
        if locator is None:
            continue
        target_id = _text_field(row, _ID_FIELDS)
        if target_id is None:
            raise ValueError("overlay target requires id")
        if target_id in seen:
            raise ValueError("overlay target ids must be unique")
        seen.add(target_id)
        try:
            public_page = validate_public_locator(locator).url
        except DiscoveryTransportError as error:
            raise ValueError(
                f"overlay target {target_id} locator is not a public page"
            ) from error
        targets.append(
            EmployerTarget(
                target_id=target_id,
                public_page_locator=public_page,
                claimed_provider_hint=_text_field(row, _HINT_FIELDS),
            )
        )
    ordered = tuple(sorted(targets, key=lambda item: item.target_id))
    identities = tuple(item.target_id for item in ordered)
    if identities != tuple(sorted(set(identities))):
        raise ValueError("overlay target ids must be sorted and unique")
    return ordered


def _overlay_rows(payload: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(payload, list):
        buckets: list[object] = [payload]
    elif isinstance(payload, Mapping):
        buckets = [payload[key] for key in _TARGET_BUCKETS if key in payload]
        if not buckets and any(key in payload for key in (*_ID_FIELDS, *_LOCATOR_FIELDS)):
            buckets = [[payload]]
    else:
        raise ValueError("overlay.json must be a JSON object")
    rows: list[Mapping[str, object]] = []
    for bucket in buckets:
        if bucket is None:
            continue
        if not isinstance(bucket, list):
            raise ValueError("overlay.json target lists must be arrays")
        for item in bucket:
            if isinstance(item, Mapping):
                rows.append(item)
            elif isinstance(item, str):
                continue
            else:
                raise ValueError("overlay.json target rows must be objects")
    return tuple(rows)


def _text_field(row: Mapping[str, object], names: Sequence[str]) -> str | None:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None:
            continue
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"overlay field {name} must be a non-empty string")
        return value
    return None
