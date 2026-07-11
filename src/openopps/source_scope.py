"""Packaged source-scope constants and hygiene helpers for v0.1."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from openopps.models import BoardProviderRecord

# Keys that must never ship as packaged BOARD_SOURCE_CATALOG entries while YC covers
# startup-board discovery for v0.1.
OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS: frozenset[str] = frozenset(
    {
        "workatastartup",
        "work-at-a-startup",
        "work_at_a_startup",
    }
)

PREFERRED_STARTUP_BOARD_SOURCE_KEY = "yc"
PREFERRED_STARTUP_BOARD_ADAPTER_ID = "ycombinator"

EDITORIAL_PROVIDER_LABELS: frozenset[str] = frozenset({"Editorial", "Editiorial"})
EDITORIAL_PROVIDER_IDS: frozenset[str] = frozenset({"editorial", "editiorial"})

WELLFOUND_ANGEL_UNSUPPORTED_RATIONALE = (
    "Wellfound and Angel List startup discovery are unsupported for v0.1. "
    "Public company discovery requires session or anti-bot protected pages rather than "
    "stable static no-auth assets or approved search-index endpoints. OpenOpps does not "
    "package a Wellfound/Angel source adapter; use the YC (`yc`) source for startup-board "
    "discovery instead."
)

WORKATASTARTUP_OUT_OF_SCOPE_RATIONALE = (
    "WorkAtAStartup is intentionally excluded from the packaged source catalog for v0.1. "
    "YC (`yc` / `ycombinator`) is the preferred startup-board source and already exposes "
    "company discovery through a public Algolia-backed index."
)

UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES: dict[str, str] = {
    "workatastartup": WORKATASTARTUP_OUT_OF_SCOPE_RATIONALE,
    "wellfound": WELLFOUND_ANGEL_UNSUPPORTED_RATIONALE,
    "angel": WELLFOUND_ANGEL_UNSUPPORTED_RATIONALE,
}

EDITORIAL_LABEL_AUDIT_DECISION = (
    "Consider upstream `job_sources` may emit `Editorial` or misspelled `Editiorial` "
    "labels without a generic public ATS route. OpenOpps preserves those hints as "
    "detect-only metadata via `source_hint_support_level` and does not register an "
    "`editorial` job provider or route detector until route-probe evidence proves a "
    "repeatable public fetch path."
)


def validate_packaged_source_catalog(
    catalog: Mapping[str, object],
    *,
    preferred_startup_source_key: str = PREFERRED_STARTUP_BOARD_SOURCE_KEY,
) -> None:
    """Raise when out-of-scope source keys appear in the packaged catalog."""

    keys = set(catalog)
    blocked = keys & OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS
    if blocked:
        raise ValueError(
            "Packaged source catalog includes out-of-scope keys: "
            f"{', '.join(sorted(blocked))}"
        )
    if preferred_startup_source_key not in keys:
        raise ValueError(
            "Packaged source catalog is missing preferred startup-board source "
            f"{preferred_startup_source_key!r}"
        )


def audit_editorial_provider_hints(
    *,
    provider_rows: Sequence[Sequence[object]] | None = None,
    label_index: int | None = None,
    provider_id_index: int | None = None,
    routes: Iterable[BoardProviderRecord] | None = None,
) -> dict[str, Any]:
    """Summarize Editorial-labeled provider hints from persisted or exported rows."""

    labels: list[str] = []
    provider_ids: list[str] = []
    board_keys: list[str] = []

    if provider_rows is not None:
        if label_index is None or provider_id_index is None:
            raise ValueError("label_index and provider_id_index are required for rows")
        board_key_index = 2 if len(provider_rows[0]) > 2 else None
        for row in provider_rows:
            label = str(row[label_index] or "")
            provider_id = str(row[provider_id_index] or "")
            if _is_editorial_hint(label=label, provider_id=provider_id):
                labels.append(label)
                provider_ids.append(provider_id)
                if board_key_index is not None:
                    board_keys.append(str(row[board_key_index]))

    if routes is not None:
        for route in routes:
            if _is_editorial_hint(label=route.label, provider_id=route.provider_id):
                labels.append(route.label or "")
                provider_ids.append(route.provider_id)
                board_keys.append(route.board_key)

    return {
        "labelsObserved": dict(Counter(labels)),
        "providerIdsObserved": dict(Counter(provider_ids)),
        "boardCount": len(set(board_keys)),
        "exampleBoardKeys": sorted(set(board_keys))[:5],
        "decision": EDITORIAL_LABEL_AUDIT_DECISION,
        "registerProviderIdentity": False,
    }


def source_scope_summary() -> dict[str, Any]:
    """Compact release summary for coverage and audit surfaces."""

    return {
        "preferredStartupBoardSource": PREFERRED_STARTUP_BOARD_SOURCE_KEY,
        "preferredStartupBoardAdapter": PREFERRED_STARTUP_BOARD_ADAPTER_ID,
        "excludedPackagedSources": sorted(OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS),
        "unsupportedSourceDiscovery": UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES,
        "editorialLabelAudit": {
            "watchedLabels": sorted(EDITORIAL_PROVIDER_LABELS),
            "watchedProviderIds": sorted(EDITORIAL_PROVIDER_IDS),
            "decision": EDITORIAL_LABEL_AUDIT_DECISION,
            "registerProviderIdentity": False,
        },
    }


def _is_editorial_hint(*, label: str | None, provider_id: str | None) -> bool:
    normalized_label = (label or "").strip()
    normalized_id = (provider_id or "").strip().casefold()
    return (
        normalized_label in EDITORIAL_PROVIDER_LABELS
        or normalized_id in EDITORIAL_PROVIDER_IDS
    )