"""Offline discovery/promotion benchmark harness (O907–O914).

The T135 corpus binds the frozen 2,870-source / 16-adapter inventory by digest.
This module measures the six named CPU stages without SQLite, HTTP, or ingest.
Evidence is counts and digests only: no raw URLs, queries, secrets, or payloads.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path
import platform
import resource
import sqlite3
import sys
import time
from types import MappingProxyType
from typing import Final

from openopps.discovery.accounting import (
    OPERATION_TERMINALS,
    validate_operation_conservation,
)
from openopps.discovery.api import decode_discovery_model, encode_discovery_model
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.diagnostics import (
    BoundedDiagnostic,
    render_bounded_diagnostic,
    render_metric_attributes,
)
from openopps.discovery.identity import RawOccurrenceInput, admit_raw_occurrences
from openopps.discovery.inventory import (
    ApprovedRuntimeCatalogInventory,
    build_approved_runtime_catalog_inventory,
    read_packaged_catalog_bytes,
)
from openopps.discovery.models import (
    BoundedReason,
    CandidateIdentity,
    CandidateOccurrence,
)
from openopps.discovery.policy import (
    V7PolicyDigestBinding,
    bind_candidate_policy,
    bind_v7_policy_digests,
    evaluate_policy,
)
from openopps.discovery.promotion import preview_promotion
from openopps.discovery.schemas import validate_discovery_schema_files
from openopps.discovery.transport import OperationLedger, OperationLedgerSnapshot


BENCHMARK_OPERATIONS: Final[tuple[str, ...]] = (
    "normalization",
    "schema_validation",
    "deduplication",
    "catalog_collision_audit",
    "policy_evaluation",
    "promotion_rendering",
)
CORPUS_SCHEMA_VERSION: Final = "openopps.discovery.benchmark-corpus.v1"
ADR_SCHEMA_VERSION: Final = "openopps.discovery.benchmark-adr.v1"
RECEIPT_SCHEMA_VERSION: Final = (
    "openopps.discovery.benchmark-implementation-receipt.v1"
)
DEFAULT_REPEAT_COUNT: Final = 5
DEFAULT_ADR_PATH: Final = Path(__file__).with_name("data") / "benchmark-adr.json"
DEFAULT_RECEIPT_PATH: Final = (
    Path(__file__).with_name("data") / "benchmark-implementation-receipt.json"
)
_ADOPT: Final = "adopt"
_DEFER: Final = "defer"


class BenchmarkError(ValueError):
    """The offline benchmark cannot close under its recorded contract."""


class BenchmarkSqliteError(RuntimeError):
    """The offline benchmark must not open SQLite."""


@dataclass(frozen=True, slots=True)
class BenchmarkInputs:
    """Caller-supplied runtime inventory. This module never imports providers."""

    source_records: tuple[object, ...]
    source_owner_rows: tuple[tuple[str, str], ...]
    adapter_identity_rows: tuple[tuple[str, str, str], ...]
    packaged_catalog: bytes
    v7_policy_code: bytes
    v7_policy_schema: bytes
    v7_policy_evidence: bytes
    v7_policy_corpus: bytes
    public_selector: bytes | None = None


@dataclass(frozen=True, slots=True)
class StageTiming:
    samples_us: tuple[int, ...]
    median_us: int
    p95_us: int
    range_us: int

    def as_dict(self) -> dict[str, object]:
        return {
            "medianUs": self.median_us,
            "p95Us": self.p95_us,
            "rangeUs": self.range_us,
            "samplesUs": list(self.samples_us),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema_version: str
    corpus_sha256: str
    repeat_count: int
    sqlite_statement_count: int
    http_request_count: int
    peak_rss_bytes: int
    artifact_bytes: int
    invalid_occurrences: int
    unique_candidates: int
    duplicate_occurrences: int
    collision_groups: Mapping[str, int]
    policy_counts: Mapping[str, int]
    inventory: Mapping[str, object]
    promotion: Mapping[str, object]
    operations: OperationLedgerSnapshot
    diagnostic: BoundedDiagnostic
    metric_attributes: Mapping[str, bool | str]
    environment: Mapping[str, object]
    stage_timings: Mapping[str, StageTiming]
    whole_run: StageTiming

    def as_dict(self) -> dict[str, object]:
        return {
            "artifactBytes": self.artifact_bytes,
            "collisionGroups": dict(self.collision_groups),
            "corpusSha256": self.corpus_sha256,
            "diagnostic": self.diagnostic.as_dict(),
            "duplicateOccurrences": self.duplicate_occurrences,
            "environment": dict(self.environment),
            "httpRequestCount": self.http_request_count,
            "invalidOccurrences": self.invalid_occurrences,
            "inventory": dict(self.inventory),
            "metrics": dict(self.metric_attributes),
            "operations": {
                "channelState": self.operations.channel_state,
                "planned": self.operations.planned,
                "terminals": {
                    name: self.operations.terminals[name]
                    for name in OPERATION_TERMINALS
                },
            },
            "peakRssBytes": self.peak_rss_bytes,
            "policyCounts": dict(self.policy_counts),
            "promotion": dict(self.promotion),
            "repeatCount": self.repeat_count,
            "schemaVersion": self.schema_version,
            "sqliteStatementCount": self.sqlite_statement_count,
            "stageTimings": {
                name: self.stage_timings[name].as_dict()
                for name in BENCHMARK_OPERATIONS
            },
            "uniqueCandidates": self.unique_candidates,
            "wholeRun": self.whole_run.as_dict(),
        }


def median_int(samples: Sequence[int]) -> int:
    """Return the upper-middle sample so the median stays an integer."""

    if not samples:
        raise BenchmarkError("median requires at least one sample")
    ordered = sorted(samples)
    return ordered[len(ordered) // 2]


def nearest_rank_percentile(samples: Sequence[int], percentile: int) -> int:
    """Nearest-rank percentile over integer microsecond samples."""

    if not samples:
        raise BenchmarkError("percentile requires at least one sample")
    if isinstance(percentile, bool) or percentile < 0 or percentile > 100:
        raise BenchmarkError("percentile must be an integer 0..100")
    ordered = sorted(samples)
    if percentile == 0:
        return ordered[0]
    rank = math.ceil(percentile / 100 * len(ordered))
    return ordered[rank - 1]


def peak_rss_bytes() -> int:
    """Return the process high-water RSS in bytes (Linux reports KiB)."""

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if usage < 0:
        raise BenchmarkError("peak RSS is negative")
    if sys.platform == "linux":
        return usage * 1024
    return usage


def load_benchmark_adr(path: Path = DEFAULT_ADR_PATH) -> Mapping[str, object]:
    """Load the committed machine-readable ADR (O911/O912)."""

    return _load_verdict_document(path, ADR_SCHEMA_VERSION)


def load_benchmark_implementation_receipt(
    path: Path = DEFAULT_RECEIPT_PATH,
) -> Mapping[str, object]:
    """Load the committed defer/adopt implementation receipt (O913/O914)."""

    return _load_verdict_document(path, RECEIPT_SCHEMA_VERSION)


def assert_receipt_matches_adr(
    *,
    adr: Mapping[str, object] | None = None,
    receipt: Mapping[str, object] | None = None,
) -> None:
    """O914: one verdict, no artifacts from the opposite branch."""

    adr_doc = dict(adr) if adr is not None else dict(load_benchmark_adr())
    receipt_doc = (
        dict(receipt)
        if receipt is not None
        else dict(load_benchmark_implementation_receipt())
    )
    verdict = adr_doc.get("verdict")
    if verdict not in {_ADOPT, _DEFER}:
        raise BenchmarkError("ADR verdict must be adopt or defer")
    if receipt_doc.get("verdict") != verdict:
        raise BenchmarkError("implementation receipt verdict does not match the ADR")
    if verdict == _DEFER:
        if adr_doc.get("numericRegressionThreshold") is not None:
            raise BenchmarkError("defer ADR cannot carry a numeric threshold")
        if receipt_doc.get("numericRegressionThreshold") is not None:
            raise BenchmarkError("defer receipt cannot carry a numeric threshold")
        adopt_artifacts = receipt_doc.get("adoptArtifacts")
        if adopt_artifacts not in ((), [], None):
            raise BenchmarkError("defer receipt must not list adopt artifacts")
        return
    if not receipt_doc.get("adoptArtifacts"):
        raise BenchmarkError("adopt receipt must list reviewed threshold artifacts")


@contextmanager
def sqlite_statement_guard() -> Iterator[dict[str, int]]:
    """Count and reject every SQLite connect for the offline benchmark."""

    statements = {"count": 0}
    original_connect = sqlite3.connect

    def _blocked(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        statements["count"] += 1
        raise BenchmarkSqliteError("benchmark must not open SQLite")

    setattr(sqlite3, "connect", _blocked)
    try:
        yield statements
    finally:
        sqlite3.connect = original_connect


def bind_benchmark_corpus(
    corpus: Mapping[str, object],
    inventory: ApprovedRuntimeCatalogInventory,
) -> None:
    """Require the T135 corpus and live inventory to share one digest bind."""

    if corpus.get("schemaVersion") != CORPUS_SCHEMA_VERSION:
        raise BenchmarkError("benchmark corpus schemaVersion is unsupported")
    operations = corpus.get("operations")
    if operations != list(BENCHMARK_OPERATIONS):
        raise BenchmarkError("benchmark corpus operations do not match the harness")
    runtime = corpus.get("runtimeSources")
    adapters = corpus.get("adapterIdentities")
    if not isinstance(runtime, Mapping) or not isinstance(adapters, Mapping):
        raise BenchmarkError("benchmark corpus inventory maps are required")
    if runtime.get("count") != inventory.source_count:
        raise BenchmarkError("corpus source count does not match runtime inventory")
    if runtime.get("uniqueKeyCount") != inventory.unique_source_count:
        raise BenchmarkError("corpus unique keys do not match runtime inventory")
    if runtime.get("ownershipCollisionCount") != 0:
        raise BenchmarkError("corpus ownershipCollisionCount must be zero")
    if runtime.get("ownerMapSha256") != inventory.owner_map_sha256:
        raise BenchmarkError("corpus owner map digest does not match inventory")
    if runtime.get("semanticSha256") != inventory.runtime_semantic_sha256:
        raise BenchmarkError("corpus semantic digest does not match inventory")
    if adapters.get("count") != inventory.adapter_count:
        raise BenchmarkError("corpus adapter count does not match inventory")
    if adapters.get("identityMapSha256") != inventory.adapter_identity_map_sha256:
        raise BenchmarkError("corpus adapter digest does not match inventory")
    threshold = corpus.get("thresholdPolicy")
    if not isinstance(threshold, Mapping):
        raise BenchmarkError("corpus thresholdPolicy is required")
    if threshold.get("numericRegressionThreshold") is not None:
        raise BenchmarkError("T136 corpus must not carry a numeric regression threshold")


def run_offline_promotion_benchmark(
    *,
    corpus_bytes: bytes,
    inputs: BenchmarkInputs,
    repeat_count: int = DEFAULT_REPEAT_COUNT,
) -> BenchmarkReport:
    """Run the six offline stages in a recorded SQLite-free environment."""

    if (
        isinstance(repeat_count, bool)
        or not isinstance(repeat_count, int)
        or repeat_count < 1
        or repeat_count % 2 == 0
    ):
        raise BenchmarkError("repeat_count must be a positive odd integer")
    corpus = decode_canonical_json(corpus_bytes)
    if not isinstance(corpus, dict):
        raise BenchmarkError("benchmark corpus must be a JSON object")
    corpus_sha256 = sha256(corpus_bytes).hexdigest()
    with sqlite_statement_guard() as sqlite_statements:
        report = _run_repeats(
            corpus=corpus,
            corpus_sha256=corpus_sha256,
            inputs=inputs,
            repeat_count=repeat_count,
        )
    if sqlite_statements["count"] != 0 or report.sqlite_statement_count != 0:
        raise BenchmarkError("benchmark emitted SQLite statements")
    if report.http_request_count != 0:
        raise BenchmarkError("benchmark emitted HTTP requests")
    return report


@dataclass(frozen=True, slots=True)
class _StageSnapshot:
    elapsed_us: Mapping[str, int]
    artifact_bytes: int
    invalid_occurrences: int
    unique_candidates: int
    duplicate_occurrences: int
    collision_groups: Mapping[str, int]
    policy_counts: Mapping[str, int]
    inventory: Mapping[str, object]
    promotion: Mapping[str, object]
    operations: OperationLedgerSnapshot
    fingerprint: str


def _run_repeats(
    *,
    corpus: Mapping[str, object],
    corpus_sha256: str,
    inputs: BenchmarkInputs,
    repeat_count: int,
) -> BenchmarkReport:
    owner_by_key = _owner_by_key(inputs.source_owner_rows)
    v7 = bind_v7_policy_digests(
        policy_code=inputs.v7_policy_code,
        policy_schema=inputs.v7_policy_schema,
        policy_evidence=inputs.v7_policy_evidence,
        policy_corpus=inputs.v7_policy_corpus,
        public_selector=inputs.public_selector,
    )
    stage_samples: dict[str, list[int]] = {name: [] for name in BENCHMARK_OPERATIONS}
    whole_samples: list[int] = []
    last: _StageSnapshot | None = None
    peak_rss = peak_rss_bytes()
    for _ in range(repeat_count):
        started = time.perf_counter_ns()
        snapshot = _run_once(
            inputs=inputs,
            owner_by_key=owner_by_key,
            v7=v7,
            corpus=corpus,
            corpus_sha256=corpus_sha256,
        )
        whole_samples.append(_ns_to_us(time.perf_counter_ns() - started))
        for name, elapsed_us in snapshot.elapsed_us.items():
            stage_samples[name].append(elapsed_us)
        peak_rss = max(peak_rss, peak_rss_bytes())
        if last is None:
            last = snapshot
        elif snapshot.fingerprint != last.fingerprint:
            raise BenchmarkError("repeated benchmark runs are not byte-deterministic")
    if last is None:
        raise BenchmarkError("benchmark produced no samples")
    validate_operation_conservation(last.operations.planned, last.operations.terminals)
    diagnostic = render_bounded_diagnostic(BoundedReason.NONE)
    metrics = render_metric_attributes(
        channel=None,
        terminal_state="complete",
        reason_code=BoundedReason.NONE,
        complete=True,
        identity_digest=corpus_sha256,
    )
    return BenchmarkReport(
        schema_version="openopps.discovery.benchmark-evidence.v1",
        corpus_sha256=corpus_sha256,
        repeat_count=repeat_count,
        sqlite_statement_count=0,
        http_request_count=0,
        peak_rss_bytes=peak_rss,
        artifact_bytes=last.artifact_bytes,
        invalid_occurrences=last.invalid_occurrences,
        unique_candidates=last.unique_candidates,
        duplicate_occurrences=last.duplicate_occurrences,
        collision_groups=last.collision_groups,
        policy_counts=last.policy_counts,
        inventory=last.inventory,
        promotion=last.promotion,
        operations=last.operations,
        diagnostic=diagnostic,
        metric_attributes=metrics,
        environment=_environment(),
        stage_timings={
            name: _timing(tuple(stage_samples[name])) for name in BENCHMARK_OPERATIONS
        },
        whole_run=_timing(tuple(whole_samples)),
    )


def _run_once(
    *,
    inputs: BenchmarkInputs,
    owner_by_key: Mapping[str, str],
    v7: V7PolicyDigestBinding,
    corpus: Mapping[str, object],
    corpus_sha256: str,
) -> _StageSnapshot:
    ledger = OperationLedger(planned_operation_ids=BENCHMARK_OPERATIONS)
    elapsed: dict[str, int] = {}

    ledger.start("normalization")
    started = time.perf_counter_ns()
    occurrences, invalid_ids = _normalize(inputs.source_records, owner_by_key)
    elapsed["normalization"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("normalization", outcome="succeeded")

    ledger.start("schema_validation")
    started = time.perf_counter_ns()
    identity_bytes = _validate_schemas(occurrences)
    elapsed["schema_validation"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("schema_validation", outcome="succeeded")

    ledger.start("deduplication")
    started = time.perf_counter_ns()
    unique, duplicate_occurrences = _dedupe(occurrences)
    elapsed["deduplication"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("deduplication", outcome="succeeded")

    ledger.start("catalog_collision_audit")
    started = time.perf_counter_ns()
    inventory, collision_groups = _collision_audit(inputs, unique)
    bind_benchmark_corpus(corpus, inventory)
    elapsed["catalog_collision_audit"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("catalog_collision_audit", outcome="succeeded")

    ledger.start("policy_evaluation")
    started = time.perf_counter_ns()
    policy_counts = _evaluate_policies(inputs, v7)
    elapsed["policy_evaluation"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("policy_evaluation", outcome="succeeded")

    ledger.start("promotion_rendering")
    started = time.perf_counter_ns()
    promotion, catalog_after_bytes, delta_bytes = _render_promotion(
        inputs, v7, corpus_sha256
    )
    elapsed["promotion_rendering"] = _ns_to_us(time.perf_counter_ns() - started)
    ledger.finish("promotion_rendering", outcome="succeeded")

    operations = ledger.close(channel_state="complete")
    artifact_bytes = identity_bytes + catalog_after_bytes + delta_bytes
    inventory_payload = inventory.as_dict()
    fingerprint = sha256(
        canonical_json_bytes(
            {
                "artifactBytes": artifact_bytes,
                "collisionGroups": dict(collision_groups),
                "duplicateOccurrences": duplicate_occurrences,
                "invalidOccurrences": len(invalid_ids),
                "inventory": inventory_payload,
                "policyCounts": dict(policy_counts),
                "promotion": dict(promotion),
                "uniqueCandidates": len(unique),
            }
        )
    ).hexdigest()
    return _StageSnapshot(
        elapsed_us=elapsed,
        artifact_bytes=artifact_bytes,
        invalid_occurrences=len(invalid_ids),
        unique_candidates=len(unique),
        duplicate_occurrences=duplicate_occurrences,
        collision_groups=collision_groups,
        policy_counts=policy_counts,
        inventory=inventory_payload,
        promotion=promotion,
        operations=operations,
        fingerprint=fingerprint,
    )


def _normalize(
    source_records: Sequence[object],
    owner_by_key: Mapping[str, str],
) -> tuple[tuple[CandidateOccurrence, ...], tuple[str, ...]]:
    raw: list[RawOccurrenceInput] = []
    for record in source_records:
        key = str(_field(record, "key"))
        raw.append(
            RawOccurrenceInput(
                occurrence_id=f"occ-{key}",
                channel="official",
                key=key,
                url=str(_field(record, "url")),
                provider_id=str(_field(record, "provider_id")),
                owner=owner_by_key[key],
                provenance_ids=(f"inventory-{key}",),
            )
        )
    return admit_raw_occurrences(raw)


def _validate_schemas(occurrences: Sequence[CandidateOccurrence]) -> int:
    validate_discovery_schema_files()
    total = 0
    for item in occurrences:
        identity = item.identity
        encoded = encode_discovery_model(identity)
        round_trip = decode_discovery_model(CandidateIdentity, encoded)
        if round_trip != identity:
            raise BenchmarkError("identity schema round-trip drifted")
        total += len(encoded)
    return total


def _dedupe(
    occurrences: Sequence[CandidateOccurrence],
) -> tuple[tuple[CandidateIdentity, ...], int]:
    unique: dict[CandidateIdentity, None] = {}
    duplicates = 0
    for item in occurrences:
        identity = item.identity
        if identity in unique:
            duplicates += 1
            continue
        unique[identity] = None
    return tuple(unique), duplicates


def _collision_audit(
    inputs: BenchmarkInputs,
    unique: Sequence[CandidateIdentity],
) -> tuple[ApprovedRuntimeCatalogInventory, Mapping[str, int]]:
    packaged = read_packaged_catalog_bytes(inputs.packaged_catalog)
    inventory = build_approved_runtime_catalog_inventory(
        source_records=inputs.source_records,
        source_owner_rows=inputs.source_owner_rows,
        adapter_identity_rows=inputs.adapter_identity_rows,
        packaged_catalog=packaged,
    )
    keys = [_field(record, "key") for record in inputs.source_records]
    urls = [_field(record, "url") for record in inputs.source_records]
    canonical = [identity.canonical_url for identity in unique]
    tokens = [
        f"{identity.provider_id}\0{identity.provider_token}"
        for identity in unique
        if identity.provider_token is not None
    ]
    groups = MappingProxyType(
        {
            "canonicalUrl": _duplicate_group_count(canonical),
            "exactKey": _duplicate_group_count(str(key) for key in keys),
            "exactUrl": _duplicate_group_count(str(url) for url in urls),
            "providerToken": _duplicate_group_count(tokens),
        }
    )
    if groups["exactKey"] != 0:
        raise BenchmarkError("catalog source keys are not unique")
    return inventory, groups


def _evaluate_policies(
    inputs: BenchmarkInputs, v7: V7PolicyDigestBinding
) -> Mapping[str, int]:
    counts: Counter[str] = Counter()
    evidence = inputs.v7_policy_evidence
    for record in inputs.source_records:
        binding = bind_candidate_policy(
            provider_id=str(_field(record, "provider_id")),
            source_key=str(_field(record, "key")),
            taxonomy={},
            v7=v7,
            evidence_bytes=evidence,
        )
        disposition = evaluate_policy(
            binding.axes, deny_overlay_matches=binding.deny_matches
        )
        counts[disposition.value] += 1
    return MappingProxyType(
        {
            "allowed": counts["allowed"],
            "blocked": counts["blocked"],
            "evaluated": len(inputs.source_records),
            "unresolved": counts["unresolved"],
        }
    )


def _render_promotion(
    inputs: BenchmarkInputs,
    v7: V7PolicyDigestBinding,
    corpus_sha256: str,
) -> tuple[Mapping[str, object], int, int]:
    resources_digest = sha256(canonical_json_bytes(v7.as_dict())).hexdigest()
    preview = preview_promotion(
        manifest_digest=corpus_sha256,
        candidates=(),
        catalog_before=inputs.packaged_catalog,
        v7=v7,
        head_sha=corpus_sha256[:40],
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=resources_digest,
        profile_digest=sha256(b"openopps.discovery.benchmark").hexdigest(),
    )
    if preview.catalog_after != inputs.packaged_catalog:
        raise BenchmarkError("identity preview must preserve catalog bytes")
    if preview.catalog_before_digest != preview.catalog_after_digest:
        raise BenchmarkError("identity preview catalog digests must match")
    if preview.proposed_records:
        raise BenchmarkError("identity preview must not propose catalog records")
    payload = MappingProxyType(
        {
            "catalogAfterDigest": preview.catalog_after_digest,
            "catalogBeforeDigest": preview.catalog_before_digest,
            "deltaBytes": len(preview.delta),
            "proposedRecords": 0,
            "promotionDigest": preview.promotion_digest,
        }
    )
    return payload, len(preview.catalog_after), len(preview.delta)


def _owner_by_key(rows: Sequence[Sequence[str]]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for row in rows:
        if len(row) != 2:
            raise BenchmarkError("owner rows must contain key and module")
        key, module = row
        owner = module.rsplit(".", 1)[-1].strip().casefold()
        if not key or not owner:
            raise BenchmarkError("owner rows must be non-empty")
        if key in owners and owners[key] != owner:
            raise BenchmarkError("source ownership is ambiguous")
        owners[key] = owner
    return owners


def _field(record: object, name: str) -> object:
    if isinstance(record, Mapping):
        return record[name]
    return getattr(record, name)


def _duplicate_group_count(values: Iterable[str]) -> int:
    counts: Counter[str] = Counter(values)
    return sum(1 for count in counts.values() if count > 1)


def _timing(samples: tuple[int, ...]) -> StageTiming:
    return StageTiming(
        samples_us=samples,
        median_us=median_int(samples),
        p95_us=nearest_rank_percentile(samples, 95),
        range_us=max(samples) - min(samples),
    )


def _ns_to_us(elapsed_ns: int) -> int:
    if elapsed_ns < 0:
        raise BenchmarkError("elapsed time is negative")
    return elapsed_ns // 1_000


def _environment() -> Mapping[str, object]:
    return MappingProxyType(
        {
            "clock": "perf_counter_ns",
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "network": "disabled",
            "platform": platform.platform(),
            "processorCount": os.cpu_count() or 0,
            "python": sys.version.split()[0],
            "sqlite": "blocked",
            "timezone": "UTC",
        }
    )


def _load_verdict_document(path: Path, schema_version: str) -> Mapping[str, object]:
    payload = decode_canonical_json(path.read_bytes())
    if not isinstance(payload, dict):
        raise BenchmarkError("verdict document must be a JSON object")
    if payload.get("schemaVersion") != schema_version:
        raise BenchmarkError("verdict document schemaVersion is unsupported")
    verdict = payload.get("verdict")
    if verdict not in {_ADOPT, _DEFER}:
        raise BenchmarkError("verdict must be adopt or defer")
    if verdict == _DEFER and payload.get("numericRegressionThreshold") is not None:
        raise BenchmarkError("defer document cannot carry a numeric threshold")
    return MappingProxyType(payload)
