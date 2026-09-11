"""Offline overlay worklist outcome histograms. No HTTP and no catalog writes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from openopps.providers.sources.overlay_outcomes import (
    OverlayOutcome,
    OverlayWorklistEntry,
    YcPublicAtsBoard,
    load_overlay_worklist,
    overlay_worklist_outcomes,
)

if TYPE_CHECKING:
    from openopps.providers.registry import ProviderRegistry

OVERLAY_OUTCOMES_SCHEMA_VERSION = 1
PACKAGED_GAIN_EXCLUSIONS = frozenset({"url-pull", "url_pull", "scout", "discovery"})
_TIERS = ("core", "expand", "growth")
_FAMILY_HOST_MARKERS: tuple[tuple[str, str], ...] = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashbyhq"),
    ("workable.com", "workable"),
    ("myworkdayjobs.com", "workday"),
    ("rippling.com", "rippling"),
    ("teamtailor.com", "teamtailor"),
    ("bamboohr.com", "bamboohr"),
    ("consider.com", "consider_jobs"),
    ("wpjobmanager", "wpjobmanager"),
)


def overlay_outcomes_report(
    entries: Sequence[OverlayWorklistEntry] | None = None,
    *,
    registry: ProviderRegistry | None = None,
    yc_boards: Sequence[YcPublicAtsBoard] = (),
) -> dict[str, Any]:
    """Return conserved overlay outcome counts plus per-tier histograms."""

    worklist = tuple(entries) if entries is not None else load_overlay_worklist()
    outcomes = overlay_worklist_outcomes(
        worklist,
        registry=registry,
        yc_boards=yc_boards,
    )
    empty = {item.value: 0 for item in OverlayOutcome}
    totals = dict(empty)
    by_tier = {tier: dict(empty) for tier in _TIERS}
    for entry in worklist:
        outcome = outcomes[entry.overlay_id]
        totals[outcome.value] += 1
        if entry.tier in by_tier:
            by_tier[entry.tier][outcome.value] += 1
    if sum(totals.values()) != len(worklist):
        raise ValueError("overlay outcomes are not conserved per id")
    if len(outcomes) != len(worklist):
        raise ValueError("overlay outcomes must be one closed value per overlay id")
    by_family: dict[str, dict[str, int]] = {}
    for entry in worklist:
        family = _family_from_locator(entry.locator)
        bucket = by_family.setdefault(family, dict(empty))
        bucket[outcomes[entry.overlay_id].value] += 1
    return {
        "schemaVersion": OVERLAY_OUTCOMES_SCHEMA_VERSION,
        "entryCount": len(worklist),
        "outcomes": totals,
        "byTier": by_tier,
        "byFamily": by_family,
    }


def packaged_overlay_gain(
    entries: Sequence[OverlayWorklistEntry] | None = None,
    *,
    extra_sources: Sequence[object] = (),
    registry: ProviderRegistry | None = None,
    yc_boards: Sequence[YcPublicAtsBoard] = (),
) -> dict[str, Any]:
    """Return packaged overlay histograms, ignoring url-pull and scout extras."""

    for source in extra_sources:
        if not _is_packaged_gain_exclusion(source):
            raise ValueError(
                "packaged overlay gain excludes url-pull and scout; "
                f"refusing extra source {source!r}"
            )
    return overlay_outcomes_report(
        entries,
        registry=registry,
        yc_boards=yc_boards,
    )


def _is_packaged_gain_exclusion(source: object) -> bool:
    if not isinstance(source, Mapping):
        return False
    labels = {
        str(source.get("kind") or "").casefold().replace("_", "-"),
        str(source.get("source_key") or "").casefold().replace("_", "-"),
        str(source.get("kind") or "").casefold().replace("-", "_"),
        str(source.get("source_key") or "").casefold().replace("-", "_"),
    }
    excluded = {item.casefold() for item in PACKAGED_GAIN_EXCLUSIONS}
    return bool(labels & excluded)


def _family_from_locator(locator: str) -> str:
    host = (urlsplit(locator).hostname or "").casefold().removeprefix("www.")
    for marker, family in _FAMILY_HOST_MARKERS:
        if host == marker or host.endswith(f".{marker}") or marker in host:
            return family
    return "other"


__all__ = [
    "OVERLAY_OUTCOMES_SCHEMA_VERSION",
    "PACKAGED_GAIN_EXCLUSIONS",
    "overlay_outcomes_report",
    "packaged_overlay_gain",
]
