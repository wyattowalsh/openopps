"""Red tests for the isolated coverage-quality reporter (T009 / W-QUALITY).

Assumed T070 API in ``openopps.coverage_quality`` (do not implement it here):

- ``QUALITY_REPORT_SCHEMA_VERSION``: int
- ``build_coverage_quality_report(...)`` -> dict

Keyword arguments for ``build_coverage_quality_report``:

- ``job_details``: T2-shaped job dicts. Indexability MUST reuse
  ``scripts/generate_docs_search_index.py`` ``_is_indexable_job_detail``:
  open status (empty or ``open``), title+company+description, a date
  (``postedAt`` / ``firstSeenAt`` / ``versionCreatedAt``), and an external URL
  (``postingUrl`` / ``applyUrl``).
- ``provider_field_outcomes``: provider -> field ->
  ``{null, parsed, conflict, total}`` integer counts (listing/detail conflict
  plus null/parse success).
- ``advertised_capabilities`` / ``implemented_capabilities``: provider ->
  ``{list, get}`` bools for advertised versus implemented hooks.
- ``qualified_additions`` / ``min_qualified_additions``: diminishing-yield
  inputs. Too few qualified additions => stop.
- ``demand_tiers_met``: prioritized demand tiers already met.
- ``extra_source_rows``: padded catalog/source counts; MUST NOT reset the stop.

Report dict keys include ``schemaVersion``, ``perProvider`` (null/parse/conflict
rates), ``t2IndexabilityRate``, ``capabilityGaps``, and
``diminishingYieldStop`` (bool or ``{"stop": bool, ...}``).

This reporter is not ``SyncMetrics``, not ``PullTerminalObservability``, and is
not a shared ``RunMetrics`` envelope. Do not attach it to ``--metrics-json`` or
``--metrics-file``.
"""

from __future__ import annotations

import ast
import json
import runpy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from openopps.coverage_quality import (
    QUALITY_REPORT_SCHEMA_VERSION,
    build_coverage_quality_report,
)
from openopps.metrics import SyncMetrics
from openopps.pull_models import PullTerminalObservability

ROOT = Path(__file__).resolve().parents[3]
_COVERAGE_QUALITY_PATH = ROOT / "src" / "openopps" / "coverage_quality.py"
_INDEXABLE_VECTORS_PATH = (
    ROOT / "tests" / "fixtures" / "job_detail_indexable_vectors.json"
)
_SEARCH_INDEX_SCRIPT = ROOT / "scripts" / "generate_docs_search_index.py"
_SEARCH_INDEX_NAMESPACE = runpy.run_path(str(_SEARCH_INDEX_SCRIPT))
is_indexable_job_detail = cast(
    "Callable[[dict[str, Any]], bool]",
    _SEARCH_INDEX_NAMESPACE["_is_indexable_job_detail"],
)
_INDEXABLE_VECTORS = json.loads(
    _INDEXABLE_VECTORS_PATH.read_text(encoding="utf-8")
)["vectors"]

QUALITY_ENVELOPE_KEYS = frozenset(
    {
        "schemaVersion",
        "perProvider",
        "t2IndexabilityRate",
        "capabilityGaps",
        "diminishingYieldStop",
    }
)
SYNC_METRICS_IDENTITY_KEYS = frozenset(
    {
        "stages",
        "jobsPersisted",
        "elapsedSeconds",
        "boardsPerSecond",
        "jobsPerSecond",
        "pages",
        "boardProviders",
        "duplicateRoutesSkipped",
    }
)
PULL_COVERAGE_ENVELOPE_KEYS = frozenset(
    {
        "coverageClass",
        "coverage_class",
        "terminalState",
        "terminal_state",
        "requestedOperation",
        "requested_operation",
    }
)

_GREENHOUSE_FIELD_OUTCOMES = {
    "title": {"null": 0, "parsed": 4, "conflict": 0, "total": 4},
    "location": {"null": 2, "parsed": 2, "conflict": 1, "total": 4},
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _diminishing_yield_stop(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and isinstance(value.get("stop"), bool):
        return value["stop"]
    raise AssertionError(
        "diminishingYieldStop must be a bool or an object with bool 'stop', "
        f"got {value!r}"
    )


def _expected_rates(counts: Mapping[str, int]) -> dict[str, float]:
    total = counts["total"]
    if total == 0:
        return {"nullRate": 0.0, "parseRate": 0.0, "conflictRate": 0.0}
    return {
        "nullRate": counts["null"] / total,
        "parseRate": counts["parsed"] / total,
        "conflictRate": counts["conflict"] / total,
    }


def _sum_field_counts(
    fields: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    summed = {"null": 0, "parsed": 0, "conflict": 0, "total": 0}
    for counts in fields.values():
        for key in summed:
            summed[key] += counts[key]
    return summed


def _assert_rate_block(
    actual: Mapping[str, object], expected: Mapping[str, float]
) -> None:
    for key, value in expected.items():
        assert key in actual, f"missing {key} in {sorted(actual)}"
        assert actual[key] == pytest.approx(value)


def _capability_gap_pairs(gaps: object) -> set[tuple[str, str]]:
    assert isinstance(gaps, list)
    found: set[tuple[str, str]] = set()
    for item in gaps:
        assert isinstance(item, dict)
        if item.get("advertised") and not item.get("implemented"):
            found.add((str(item["provider"]), str(item["hook"])))
    return found


def _quality_report(**kwargs: Any) -> dict[str, Any]:
    report = build_coverage_quality_report(**kwargs)
    assert type(report) is dict
    return report


def test_quality_report_schema_version_is_int() -> None:
    assert type(QUALITY_REPORT_SCHEMA_VERSION) is int
    assert QUALITY_REPORT_SCHEMA_VERSION >= 1


def test_quality_report_uses_isolated_envelope_not_sync_or_pull() -> None:
    report = _quality_report(
        job_details=[_INDEXABLE_VECTORS[0]["detail"]],
        provider_field_outcomes={"greenhouse": _GREENHOUSE_FIELD_OUTCOMES},
        advertised_capabilities={"greenhouse": {"list": True, "get": True}},
        implemented_capabilities={"greenhouse": {"list": True, "get": True}},
        qualified_additions=8,
        min_qualified_additions=1,
        demand_tiers_met=True,
    )

    assert QUALITY_ENVELOPE_KEYS <= set(report)
    assert report["schemaVersion"] == QUALITY_REPORT_SCHEMA_VERSION
    assert not isinstance(report, SyncMetrics)
    assert not isinstance(report, PullTerminalObservability)
    assert "RunMetrics" not in type(report).__name__

    # Identity is quality floors, not SyncMetrics v2 stages.sources.
    assert "stages" not in report
    assert not SYNC_METRICS_IDENTITY_KEYS & set(report)

    # Identity is not pull coverage_class / coverageClass.
    assert not PULL_COVERAGE_ENVELOPE_KEYS & set(report)


def test_quality_report_is_not_sync_metrics_stages_sources_envelope() -> None:
    report = _quality_report(qualified_additions=4, min_qualified_additions=1)
    stages = report.get("stages")
    assert stages is None
    assert "t2IndexabilityRate" in report
    assert "perProvider" in report


def test_quality_report_is_not_pull_terminal_observability_envelope() -> None:
    report = _quality_report(qualified_additions=4, min_qualified_additions=1)
    assert "coverageClass" not in report
    assert "coverage_class" not in report
    assert report.get("terminalState") is None
    assert "t2IndexabilityRate" in report
    assert "capabilityGaps" in report


@pytest.mark.parametrize(
    ("vector_id", "detail", "expected_indexable"),
    [
        (item["id"], item["detail"], item["indexable"])
        for item in _INDEXABLE_VECTORS
    ],
    ids=[item["id"] for item in _INDEXABLE_VECTORS],
)
def test_t2_indexability_reuses_docs_search_predicate(
    vector_id: str, detail: dict[str, Any], expected_indexable: bool
) -> None:
    """Open status, title+company+description, a date, and an external URL."""

    assert is_indexable_job_detail(detail) is expected_indexable, vector_id
    report = _quality_report(job_details=[detail])
    expected_rate = 1.0 if expected_indexable else 0.0
    assert report["t2IndexabilityRate"] == pytest.approx(expected_rate)


def test_t2_indexability_rate_is_share_matching_docs_search_predicate() -> None:
    details = [item["detail"] for item in _INDEXABLE_VECTORS]
    indexable = sum(1 for detail in details if is_indexable_job_detail(detail))
    expected = indexable / len(details)

    report = _quality_report(job_details=details)

    assert report["t2IndexabilityRate"] == pytest.approx(expected)
    assert expected == pytest.approx(
        sum(1 for item in _INDEXABLE_VECTORS if item["indexable"]) / len(details)
    )


def test_per_provider_null_parse_conflict_rates_include_fields() -> None:
    report = _quality_report(
        provider_field_outcomes={"greenhouse": _GREENHOUSE_FIELD_OUTCOMES}
    )

    per_provider = report["perProvider"]
    assert "greenhouse" in per_provider
    greenhouse = per_provider["greenhouse"]
    _assert_rate_block(
        greenhouse,
        _expected_rates(_sum_field_counts(_GREENHOUSE_FIELD_OUTCOMES)),
    )

    fields = greenhouse["fields"]
    assert set(fields) == {"title", "location"}
    for field_name, counts in _GREENHOUSE_FIELD_OUTCOMES.items():
        _assert_rate_block(fields[field_name], _expected_rates(counts))


def test_capability_gaps_list_advertised_versus_implemented_hooks() -> None:
    report = _quality_report(
        advertised_capabilities={
            "greenhouse": {"list": True, "get": True},
            "consider": {"list": True, "get": True},
        },
        implemented_capabilities={
            "greenhouse": {"list": True, "get": True},
            "consider": {"list": True, "get": False},
        },
    )

    gaps = _capability_gap_pairs(report["capabilityGaps"])
    assert ("consider", "get") in gaps
    assert ("greenhouse", "list") not in gaps
    assert ("greenhouse", "get") not in gaps
    assert ("consider", "list") not in gaps


def test_diminishing_yield_stop_when_too_few_qualified_additions() -> None:
    stopped = _quality_report(
        qualified_additions=1,
        min_qualified_additions=5,
        demand_tiers_met=True,
    )
    continuing = _quality_report(
        qualified_additions=12,
        min_qualified_additions=5,
        demand_tiers_met=True,
    )

    assert _diminishing_yield_stop(stopped["diminishingYieldStop"]) is True
    assert _diminishing_yield_stop(continuing["diminishingYieldStop"]) is False


def test_unmet_demand_tiers_cause_diminishing_yield_stop() -> None:
    report = _quality_report(
        qualified_additions=12,
        min_qualified_additions=5,
        demand_tiers_met=False,
    )
    block = report["diminishingYieldStop"]

    assert _diminishing_yield_stop(block) is True
    assert isinstance(block, dict)
    assert block["demandTiersMet"] is False
    assert block["stop"] is True


def test_unspecified_demand_tiers_are_not_reported_as_unmet() -> None:
    """None must not coerce to demandTiersMet=False while stop stays False."""

    report = _quality_report(
        qualified_additions=12,
        min_qualified_additions=5,
    )
    block = report["diminishingYieldStop"]

    assert isinstance(block, dict)
    assert block["demandTiersMet"] is None
    assert block["stop"] is False


def test_extra_source_rows_do_not_reset_diminishing_yield_stop() -> None:
    report = _quality_report(
        qualified_additions=0,
        min_qualified_additions=3,
        demand_tiers_met=True,
        extra_source_rows=400,
    )

    assert _diminishing_yield_stop(report["diminishingYieldStop"]) is True


def test_coverage_quality_does_not_import_discovery() -> None:
    if not _COVERAGE_QUALITY_PATH.is_file():
        pytest.skip("coverage_quality.py is not implemented yet")
    names = _imported_modules(_COVERAGE_QUALITY_PATH)
    assert not any(
        name == "openopps.discovery" or name.startswith("openopps.discovery.")
        for name in names
    )
