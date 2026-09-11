"""Isolated coverage-quality floors. Not SyncMetrics or pull observability."""

from __future__ import annotations

import runpy
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

QUALITY_REPORT_SCHEMA_VERSION = 1
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEARCH_INDEX_SCRIPT = _REPO_ROOT / "scripts" / "generate_docs_search_index.py"


def build_coverage_quality_report(
    *,
    job_details: Sequence[Mapping[str, Any]] | None = None,
    provider_field_outcomes: Mapping[str, Mapping[str, Mapping[str, int]]] | None = None,
    advertised_capabilities: Mapping[str, Mapping[str, bool]] | None = None,
    implemented_capabilities: Mapping[str, Mapping[str, bool]] | None = None,
    qualified_additions: int | None = None,
    min_qualified_additions: int | None = None,
    demand_tiers_met: bool | None = None,
    extra_source_rows: int | None = None,
) -> dict[str, Any]:
    """Build an isolated quality-floor report from projection-time inputs."""

    details = tuple(dict(item) for item in (job_details or ()))
    return {
        "schemaVersion": QUALITY_REPORT_SCHEMA_VERSION,
        "perProvider": _per_provider_rates(provider_field_outcomes or {}),
        "t2IndexabilityRate": _t2_indexability_rate(details),
        "capabilityGaps": _capability_gaps(
            advertised_capabilities or {},
            implemented_capabilities or {},
        ),
        "diminishingYieldStop": _diminishing_yield_stop(
            qualified_additions=qualified_additions,
            min_qualified_additions=min_qualified_additions,
            demand_tiers_met=demand_tiers_met,
            extra_source_rows=extra_source_rows,
        ),
    }


def _t2_indexability_rate(details: Sequence[Mapping[str, Any]]) -> float:
    if not details:
        return 0.0
    indexable = _is_indexable_job_detail()
    hits = sum(1 for detail in details if indexable(dict(detail)))
    return hits / len(details)


@lru_cache(maxsize=1)
def _is_indexable_job_detail() -> Callable[[dict[str, Any]], bool]:
    namespace = runpy.run_path(str(_SEARCH_INDEX_SCRIPT))
    return cast(
        "Callable[[dict[str, Any]], bool]",
        namespace["_is_indexable_job_detail"],
    )


def _per_provider_rates(
    outcomes: Mapping[str, Mapping[str, Mapping[str, int]]],
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for provider, fields in outcomes.items():
        field_rates = {
            field_name: _rate_block(counts) for field_name, counts in fields.items()
        }
        summed = {"null": 0, "parsed": 0, "conflict": 0, "total": 0}
        for counts in fields.values():
            for key in summed:
                summed[key] += int(counts.get(key, 0))
        provider_block = _rate_block(summed)
        provider_block["fields"] = field_rates
        report[provider] = provider_block
    return report


def _rate_block(counts: Mapping[str, int]) -> dict[str, Any]:
    total = int(counts.get("total", 0))
    if total <= 0:
        return {"nullRate": 0.0, "parseRate": 0.0, "conflictRate": 0.0}
    return {
        "nullRate": int(counts.get("null", 0)) / total,
        "parseRate": int(counts.get("parsed", 0)) / total,
        "conflictRate": int(counts.get("conflict", 0)) / total,
    }


def _capability_gaps(
    advertised: Mapping[str, Mapping[str, bool]],
    implemented: Mapping[str, Mapping[str, bool]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    providers = sorted(set(advertised) | set(implemented))
    for provider in providers:
        advertised_hooks = advertised.get(provider) or {}
        implemented_hooks = implemented.get(provider) or {}
        hooks = sorted(set(advertised_hooks) | set(implemented_hooks))
        for hook in hooks:
            advertised_flag = bool(advertised_hooks.get(hook))
            implemented_flag = bool(implemented_hooks.get(hook))
            if advertised_flag and not implemented_flag:
                gaps.append(
                    {
                        "provider": provider,
                        "hook": hook,
                        "advertised": True,
                        "implemented": False,
                    }
                )
    return gaps


def _diminishing_yield_stop(
    *,
    qualified_additions: int | None,
    min_qualified_additions: int | None,
    demand_tiers_met: bool | None,
    extra_source_rows: int | None,
) -> dict[str, Any]:
    qualified = 0 if qualified_additions is None else int(qualified_additions)
    minimum = 0 if min_qualified_additions is None else int(min_qualified_additions)
    extra_rows = 0 if extra_source_rows is None else int(extra_source_rows)
    stop = False
    if min_qualified_additions is not None:
        stop = qualified < minimum
    if demand_tiers_met is None:
        tiers_met: bool | None = None
    else:
        tiers_met = bool(demand_tiers_met)
    if tiers_met is False:
        stop = True
    return {
        "stop": stop,
        "qualifiedAdditions": qualified,
        "minQualifiedAdditions": minimum,
        "demandTiersMet": tiers_met,
        "extraSourceRows": extra_rows,
    }


__all__ = [
    "QUALITY_REPORT_SCHEMA_VERSION",
    "build_coverage_quality_report",
]
