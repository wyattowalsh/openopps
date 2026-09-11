"""Offline overlay-name outcomes for job-seeker coverage intake.

Imported by packaged source discovery. Do not define SOURCE_RECORDS, live-fetch,
or invent an ATS token from a company domain.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from openopps.models import ProviderSupport
from openopps.utils import slugify

if TYPE_CHECKING:
    from openopps.providers.registry import ProviderRegistry

OverlayTier = Literal["core", "expand", "growth"]

_POLICY_BLOCKED_HOST_LABELS = frozenset(
    {
        "wellfound",
        "angel",
        "angellist",
        "linkedin",
        "workatastartup",
        "indeed",
        "glassdoor",
    }
)
_OVERLAY_JSON_TIERS: tuple[OverlayTier, ...] = ("core", "expand", "growth")
_FACTS_NAME_IDS = {
    "anysphere/cursor": "anysphere",
    "blue origin": "blue-origin",
    "bytedance/tiktok": "bytedance",
    "cockroach labs": "cockroach-labs",
    "epic games": "epic-games",
    "figure ai": "figure-ai",
    "fly.io": "fly-io",
    "grafana labs": "grafana",
    "hugging face": "huggingface",
    "jane street": "jane-street",
    "riot games": "riot-games",
    "scale ai": "scale-ai",
    "shield ai": "shield-ai",
    "together ai": "together-ai",
    "weights & biases": "weights-biases",
    "weights and biases": "weights-biases",
}
_FACTS_CORE_PREFIX = "Overlay core names are "
_FACTS_EXPAND_PREFIX = "Overlay B-tier names are "
_LIST_AND_RE = re.compile(r",?\s+and\s+")
_IDENTITY_SPLIT_RE = re.compile(r"[/,]+")


class OverlayOutcome(StrEnum):
    """Closed per-overlay-id outcome. One value per name."""

    FETCHABLE_PACKAGED = "fetchable_packaged"
    NO_PUBLIC_ATS = "no_public_ats"
    DUPLICATE = "duplicate"
    POLICY_BLOCKED = "policy_blocked"


@dataclass(frozen=True, slots=True)
class OverlayWorklistEntry:
    overlay_id: str
    name: str
    locator: str
    tier: OverlayTier


@dataclass(frozen=True, slots=True)
class YcPublicAtsBoard:
    """Offline YC board identity plus a public ATS token. No live fetch."""

    company_id: str
    token: str
    name: str = ""


def load_overlay_worklist(
    *,
    overlay_json: Path | None = None,
    facts_path: Path | None = None,
) -> tuple[OverlayWorklistEntry, ...]:
    """Load overlay.json when present; otherwise parse facts.md names."""

    json_path = overlay_json if overlay_json is not None else _first_existing(
        _overlay_json_candidates()
    )
    if json_path is not None and json_path.is_file():
        return _entries_from_overlay_json(json_path)
    path = facts_path if facts_path is not None else _first_existing(_facts_candidates())
    if path is None or not path.is_file():
        return ()
    return _entries_from_facts_markdown(path)


def overlay_worklist_outcomes(
    entries: Sequence[OverlayWorklistEntry] | None = None,
    *,
    registry: ProviderRegistry | None = None,
    yc_boards: Sequence[YcPublicAtsBoard] = (),
) -> dict[str, OverlayOutcome]:
    """Return exactly one closed outcome per overlay id. No HTTP."""

    worklist = tuple(entries) if entries is not None else load_overlay_worklist()
    outcomes: dict[str, OverlayOutcome] = {}
    for entry in worklist:
        if entry.overlay_id in outcomes:
            raise ValueError(f"duplicate overlay id {entry.overlay_id!r}")
        outcomes[entry.overlay_id] = classify_overlay_locator(
            entry.locator,
            overlay_id=entry.overlay_id,
            overlay_name=entry.name,
            registry=registry,
            yc_boards=yc_boards,
        )
    return outcomes


def classify_overlay_locator(
    locator: str,
    *,
    overlay_id: str = "",
    overlay_name: str = "",
    registry: ProviderRegistry | None = None,
    yc_boards: Sequence[YcPublicAtsBoard] = (),
) -> OverlayOutcome:
    """Classify one public locator. Never invents an ATS token from a domain."""

    if _locator_host_is_policy_blocked(locator):
        return OverlayOutcome.POLICY_BLOCKED
    active_registry = registry if registry is not None else _board_registry()
    match = _jobs_capable_match(active_registry, locator)
    token = (match.token or "").strip() if match is not None else ""
    if token and _is_yc_duplicate(
        overlay_id=overlay_id,
        overlay_name=overlay_name,
        token=token,
        yc_boards=yc_boards,
    ):
        return OverlayOutcome.DUPLICATE
    if match is not None:
        return OverlayOutcome.FETCHABLE_PACKAGED
    return OverlayOutcome.NO_PUBLIC_ATS


def _overlay_json_candidates() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    repo_root = here.parents[4]
    return (
        repo_root / "goals" / "expand-job-seeker-coverage" / "overlay.json",
        here.parent / "data" / "job_seeker_overlay.json",
        Path.cwd() / "goals" / "expand-job-seeker-coverage" / "overlay.json",
    )


def _facts_candidates() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    return (
        here.parents[4] / "goals" / "expand-job-seeker-coverage" / "facts.md",
        Path.cwd() / "goals" / "expand-job-seeker-coverage" / "facts.md",
    )


def _first_existing(paths: Sequence[Path]) -> Path | None:
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


def _entries_from_overlay_json(path: Path) -> tuple[OverlayWorklistEntry, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("overlay.json must be an object")
    entries: list[OverlayWorklistEntry] = []
    seen: set[str] = set()
    for tier in _OVERLAY_JSON_TIERS:
        rows = payload.get(tier, [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"overlay.json {tier} must be a list")
        for row in rows:
            entry = _entry_from_json_row(row, tier=tier)
            if entry.overlay_id in seen:
                raise ValueError(f"duplicate overlay id {entry.overlay_id!r}")
            seen.add(entry.overlay_id)
            entries.append(entry)
    return tuple(entries)


def _entry_from_json_row(row: object, *, tier: OverlayTier) -> OverlayWorklistEntry:
    if not isinstance(row, dict):
        raise ValueError("overlay.json entries must be objects")
    overlay_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    locator = str(row.get("locator") or row.get("public_page_locator") or "").strip()
    if not overlay_id or not name:
        raise ValueError("overlay.json entries require id and name")
    return OverlayWorklistEntry(
        overlay_id=overlay_id,
        name=name,
        locator=locator,
        tier=tier,
    )


def _entries_from_facts_markdown(path: Path) -> tuple[OverlayWorklistEntry, ...]:
    core_names: tuple[str, ...] | None = None
    expand_names: tuple[str, ...] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.lstrip("- ").strip()
        if line.startswith(_FACTS_CORE_PREFIX):
            core_names = _split_employer_names(line[len(_FACTS_CORE_PREFIX) :])
        elif line.startswith(_FACTS_EXPAND_PREFIX):
            expand_names = _split_employer_names(line[len(_FACTS_EXPAND_PREFIX) :])
    if not core_names or not expand_names:
        raise ValueError("facts.md is missing overlay core or B-tier names")
    entries = [
        OverlayWorklistEntry(
            overlay_id=_overlay_id_for_name(name),
            name=name,
            locator="",
            tier="core",
        )
        for name in core_names
    ]
    entries.extend(
        OverlayWorklistEntry(
            overlay_id=_overlay_id_for_name(name),
            name=name,
            locator="",
            tier="expand",
        )
        for name in expand_names
    )
    seen: set[str] = set()
    for entry in entries:
        if entry.overlay_id in seen:
            raise ValueError(f"duplicate overlay id {entry.overlay_id!r}")
        seen.add(entry.overlay_id)
    return tuple(entries)


def _split_employer_names(blob: str) -> tuple[str, ...]:
    cleaned = _LIST_AND_RE.sub(", ", re.sub(r"\s+", " ", blob).strip().rstrip("."))
    return tuple(part.strip() for part in cleaned.split(",") if part.strip())


def _overlay_id_for_name(name: str) -> str:
    key = name.casefold().strip()
    if key in _FACTS_NAME_IDS:
        return _FACTS_NAME_IDS[key]
    head = name.split("/", 1)[0].strip()
    return slugify(head)


def _locator_host_is_policy_blocked(locator: str) -> bool:
    host = (urlsplit(locator).hostname or "").strip(".").lower()
    if not host:
        return False
    return any(label in _POLICY_BLOCKED_HOST_LABELS for label in host.split("."))


def _jobs_capable_match(registry: ProviderRegistry, locator: str):
    for match in registry.detect_url_matches(locator):
        definition = registry.get(match.provider_id)
        if definition is not None and definition.job_capable:
            return match
        if match.support_level == ProviderSupport.JOBS:
            return match
    return None


def _is_yc_duplicate(
    *,
    overlay_id: str,
    overlay_name: str,
    token: str,
    yc_boards: Sequence[YcPublicAtsBoard],
) -> bool:
    if not overlay_id and not overlay_name:
        return False
    token_key = token.casefold().strip()
    if not token_key:
        return False
    overlay_keys = _company_identity_keys(overlay_id, overlay_name)
    if not overlay_keys:
        return False
    for board in yc_boards:
        board_token = (board.token or "").casefold().strip()
        if board_token != token_key:
            continue
        if overlay_keys & _company_identity_keys(board.company_id, board.name):
            return True
    return False


def _company_identity_keys(*values: str) -> set[str]:
    keys: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        keys.add(text.casefold())
        keys.add(slugify(text))
        keys.add(slugify(text).replace("-", ""))
        for part in _IDENTITY_SPLIT_RE.split(text):
            piece = part.strip()
            if not piece or piece == text:
                continue
            keys.add(piece.casefold())
            keys.add(slugify(piece))
            keys.add(slugify(piece).replace("-", ""))
    keys.discard("")
    return keys


@lru_cache(maxsize=1)
def _board_registry() -> ProviderRegistry:
    from openopps.providers.boards import board_provider_definitions
    from openopps.providers.registry import ProviderRegistry

    return ProviderRegistry(list(board_provider_definitions()))


__all__ = [
    "OverlayOutcome",
    "OverlayWorklistEntry",
    "YcPublicAtsBoard",
    "classify_overlay_locator",
    "load_overlay_worklist",
    "overlay_worklist_outcomes",
]
