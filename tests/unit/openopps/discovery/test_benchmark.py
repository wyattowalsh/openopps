"""O907-O914 offline discovery/promotion benchmark evidence."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import pkgutil
import re
import sqlite3

import pytest

from openopps.discovery.benchmark import (
    BENCHMARK_OPERATIONS,
    DEFAULT_ADR_PATH,
    DEFAULT_RECEIPT_PATH,
    DEFAULT_REPEAT_COUNT,
    BenchmarkError,
    BenchmarkInputs,
    BenchmarkSqliteError,
    assert_receipt_matches_adr,
    load_benchmark_adr,
    load_benchmark_implementation_receipt,
    median_int,
    nearest_rank_percentile,
    run_offline_promotion_benchmark,
    sqlite_statement_guard,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.inventory import (
    DEFAULT_PACKAGED_CATALOG_PATH,
    DEFAULT_V7_POLICY_PATHS,
    read_repository_resources,
)
from openopps.discovery.models import BoundedReason


ROOT = Path(__file__).resolve().parents[4]
DISCOVERY = ROOT / "src" / "openopps" / "discovery"
CORPUS_PATH = ROOT / "tests" / "fixtures" / "discovery" / "benchmark" / "corpus.json"
FORBIDDEN = (
    "openopps.cache",
    "openopps.cli",
    "openopps.http",
    "openopps.ingest",
    "openopps.plugins",
    "openopps.providers",
    "openopps.storage",
    "openopps.source_policy",
    "openopps.discovery.http_client",
    "socket",
    "httpx",
    "httpcore",
)
URL_RE = re.compile(rb"https?://|manual://", re.IGNORECASE)


def _runtime_inputs() -> BenchmarkInputs:
    from openopps.models import SourceRecord
    from openopps.providers import sources as source_package
    from openopps.providers.sources import BOARD_SOURCE_ADAPTERS, BOARD_SOURCE_RECORDS

    owner_rows: list[tuple[str, str]] = []
    for module_info in pkgutil.iter_modules(
        source_package.__path__, f"{source_package.__name__}."
    ):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        owner_rows.extend(
            (record.key, module.__name__)
            for record in getattr(module, "SOURCE_RECORDS", ())
            if isinstance(record, SourceRecord)
        )
    adapter_rows = tuple(
        (provider_id, adapter.__module__, adapter.__qualname__)
        for provider_id, adapter in BOARD_SOURCE_ADAPTERS.items()
    )
    resources = read_repository_resources(ROOT, DEFAULT_V7_POLICY_PATHS)
    return BenchmarkInputs(
        source_records=tuple(BOARD_SOURCE_RECORDS),
        source_owner_rows=tuple(owner_rows),
        adapter_identity_rows=adapter_rows,
        packaged_catalog=(ROOT / DEFAULT_PACKAGED_CATALOG_PATH).read_bytes(),
        v7_policy_code=resources["policy_code"],
        v7_policy_schema=resources["policy_schema"],
        v7_policy_evidence=resources["policy_evidence"],
        v7_policy_corpus=resources["policy_corpus"],
        public_selector=None,
    )


@pytest.fixture(scope="module")
def benchmark_report():
    return run_offline_promotion_benchmark(
        corpus_bytes=CORPUS_PATH.read_bytes(),
        inputs=_runtime_inputs(),
        repeat_count=DEFAULT_REPEAT_COUNT,
    )


def test_median_and_nearest_rank_percentile_stay_integers() -> None:
    samples = (10, 20, 30, 40, 50)
    assert median_int(samples) == 30
    assert nearest_rank_percentile(samples, 95) == 50
    assert nearest_rank_percentile(samples, 0) == 10
    with pytest.raises(BenchmarkError):
        median_int(())
    with pytest.raises(BenchmarkError):
        nearest_rank_percentile(samples, -1)


def test_sqlite_guard_counts_and_rejects_connect() -> None:
    with sqlite_statement_guard() as statements:
        with pytest.raises(BenchmarkSqliteError, match="SQLite"):
            sqlite3.connect(":memory:")
        assert statements["count"] == 1


def test_benchmark_module_does_not_import_operational_or_live_http_seams() -> None:
    source = (DISCOVERY / "benchmark.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        item
        for item in imported
        if item in FORBIDDEN
        or any(item.startswith(f"{prefix}.") for prefix in FORBIDDEN)
    }
    assert not forbidden
    assert "resolve_candidate_identities" not in source


def test_offline_benchmark_binds_corpus_and_conserves_zero_sqlite(
    benchmark_report,
) -> None:
    report = benchmark_report
    payload = report.as_dict()
    assert report.repeat_count == DEFAULT_REPEAT_COUNT == 5
    assert report.sqlite_statement_count == 0
    assert report.http_request_count == 0
    assert report.invalid_occurrences == 2
    assert report.unique_candidates == 2_868
    assert report.duplicate_occurrences == 0
    assert report.inventory["sourceCount"] == 2_870
    assert report.inventory["adapterCount"] == 16
    assert report.collision_groups["exactKey"] == 0
    assert report.policy_counts["evaluated"] == 2_870
    assert report.policy_counts["allowed"] == 0
    assert (
        report.policy_counts["blocked"] + report.policy_counts["unresolved"] == 2_870
    )
    assert report.promotion["proposedRecords"] == 0
    assert (
        report.promotion["catalogAfterDigest"] == report.promotion["catalogBeforeDigest"]
    )
    assert report.operations.planned == len(BENCHMARK_OPERATIONS)
    assert report.operations.channel_state == "complete"
    assert report.operations.terminals["succeeded"] == 6
    assert sum(report.operations.terminals.values()) == 6
    assert report.diagnostic.reason_code is BoundedReason.NONE
    assert report.metric_attributes["openopps.discovery.complete"] is True
    assert report.metric_attributes["openopps.discovery.scope"] == "run"
    assert report.environment["network"] == "disabled"
    assert report.environment["sqlite"] == "blocked"
    assert report.peak_rss_bytes > 0
    assert report.artifact_bytes > 0
    for name in BENCHMARK_OPERATIONS:
        timing = report.stage_timings[name]
        assert len(timing.samples_us) == 5
        assert timing.p95_us >= timing.median_us >= 0
        assert timing.range_us == max(timing.samples_us) - min(timing.samples_us)
    assert len(report.whole_run.samples_us) == 5
    encoded = canonical_json_bytes(payload)
    assert URL_RE.search(encoded) is None
    from openopps.providers.sources import BOARD_SOURCE_RECORDS

    serialized = encoded.decode("utf-8")
    assert all(record.url not in serialized for record in BOARD_SOURCE_RECORDS)


def test_adr_verdict_is_defer_and_receipt_has_no_adopt_artifacts() -> None:
    adr = load_benchmark_adr()
    receipt = load_benchmark_implementation_receipt()
    assert adr["verdict"] == receipt["verdict"] == "defer"
    assert adr["numericRegressionThreshold"] is None
    assert receipt["numericRegressionThreshold"] is None
    assert receipt["adoptArtifacts"] == []
    assert_receipt_matches_adr(adr=adr, receipt=receipt)
    assert DEFAULT_ADR_PATH.is_file()
    assert DEFAULT_RECEIPT_PATH.is_file()
    siblings = {path.name for path in DEFAULT_ADR_PATH.parent.iterdir()}
    assert not any("slo" in name.lower() for name in siblings)
    assert not any("threshold" in name.lower() and name.endswith(".json") for name in siblings if name not in {
        "benchmark-adr.json",
        "benchmark-implementation-receipt.json",
    })
    adopt = dict(receipt)
    adopt["verdict"] = "adopt"
    with pytest.raises(BenchmarkError, match="match"):
        assert_receipt_matches_adr(adr=adr, receipt=adopt)
    thresholded = dict(adr)
    thresholded["numericRegressionThreshold"] = 1
    with pytest.raises(BenchmarkError):
        assert_receipt_matches_adr(adr=thresholded, receipt=receipt)


def test_metric_catalog_does_not_adopt_numeric_slo() -> None:
    from openopps.discovery.observability import METRIC_NAMES, METRIC_STAGES

    adr = load_benchmark_adr()
    receipt = load_benchmark_implementation_receipt()
    assert adr["verdict"] == "defer"
    assert receipt["numericRegressionThreshold"] is None
    assert len(METRIC_NAMES) == len(METRIC_STAGES) == 8
    blob = " ".join(METRIC_NAMES.values()).lower()
    assert "slo" not in blob
    assert "threshold" not in blob

