"""O901-O906 / O915 bounded metric catalog: names, cardinality, nondisclosure."""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from openopps.discovery.accounting import (
    OPERATION_TERMINALS,
    RouteAccounting,
    ScoutRunEvidence,
    SourceAccounting,
)
from openopps.discovery.diagnostics import MAX_METRIC_ATTRIBUTES
from openopps.discovery.models import BoundedReason, ChannelOperationAccounting, DiscoveryChannel
from openopps.discovery.observability import (
    EVIDENCE_CLASSES,
    METRIC_NAMES,
    METRIC_STAGES,
    REASON_CODES,
    STAGE_TERMINALS,
    TERMINAL_STATES,
    ObservabilityError,
    assert_bounded_metric_payload,
    build_metric_catalog_report,
    classify_evidence_class,
    metric_name,
)
from openopps.discovery.transport import OperationLedger, OperationLedgerSnapshot


ROOT = Path(__file__).resolve().parents[4]
SECRET_MARKER = "https://jobs.example.test/secret-token?token=secret"
DISCOVERY = ROOT / "src" / "openopps" / "discovery"
ChannelName = Literal["official", "public_code", "search", "targeted_ats"]
ChannelState = Literal["complete", "partial", "failed", "cancelled", "nonterminal"]


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _evidence() -> ScoutRunEvidence:
    return ScoutRunEvidence(
        catalog_content_digest=_sha("catalog-content"),
        catalog_tree_digest=_sha("catalog-tree"),
        selector_digest=_sha("selector"),
        policy_digest=_sha("policy"),
        promotion_digest=_sha("promotion"),
        invocation_digest=_sha("invocation"),
    )


def _channel(
    name: ChannelName,
    *,
    succeeded: int = 0,
    blocked: int = 0,
    rate_limited: int = 0,
    timed_out: int = 0,
    failed: int = 0,
    cancelled: int = 0,
    unstarted: int = 0,
    state: ChannelState = "partial",
) -> ChannelOperationAccounting:
    planned = (
        succeeded
        + blocked
        + rate_limited
        + timed_out
        + failed
        + cancelled
        + unstarted
    )
    return ChannelOperationAccounting(
        channel=name,
        channel_state=state,
        planned_operations=planned,
        succeeded=succeeded,
        blocked=blocked,
        rate_limited=rate_limited,
        timed_out=timed_out,
        failed=failed,
        cancelled=cancelled,
        unstarted=unstarted,
        request_limit=10,
        request_consumed=min(planned, 10),
        request_in_flight=0,
        request_remaining=10 - min(planned, 10),
        byte_limit=1_000,
        admitted_bytes=planned,
        remaining_bytes=1_000 - planned,
    )


def _source(**counts: int) -> SourceAccounting:
    terminals = {name: 0 for name in STAGE_TERMINALS["source"]}
    terminals.update(counts)
    planned = sum(terminals.values())
    bad = {
        "failed",
        "timed_out",
        "policy_blocked",
        "rate_limited",
        "cancelled",
        "unstarted",
    }
    complete = planned > 0 and not any(terminals[name] for name in bad)
    return SourceAccounting(
        planned=planned,
        terminal=True,
        complete=complete,
        unaccounted_ids=(),
        **terminals,
    )


def _route(**counts: int) -> RouteAccounting:
    terminals = {name: 0 for name in STAGE_TERMINALS["route"]}
    terminals.update(counts)
    planned = sum(terminals.values())
    bad = {
        "failed",
        "timed_out",
        "deferred",
        "missing_metadata",
        "policy_blocked",
        "rate_limited",
        "cancelled",
        "unstarted",
    }
    complete = planned > 0 and not any(terminals[name] for name in bad)
    return RouteAccounting(
        planned=planned,
        authoritative_succeeded=terminals["succeeded"],
        terminal=True,
        complete=complete,
        unaccounted_ids=(),
        **terminals,
    )


def _scout() -> OperationLedgerSnapshot:
    ledger = OperationLedger(planned_operation_ids=("official-op", "search-op"))
    ledger.start("official-op")
    ledger.finish("official-op", outcome="succeeded")
    ledger.start("search-op")
    ledger.finish("search-op", outcome="rate_limited")
    return ledger.close(channel_state="partial")


def _report(**overrides: Any):
    payload: dict[str, Any] = {
        "evidence": _evidence(),
        "manifest_digest": _sha("manifest"),
        "scout": _scout(),
        "channels": (
            _channel("official", succeeded=2, state="complete"),
            _channel("search", succeeded=1, rate_limited=1, failed=1),
        ),
        "candidates": {"admitted": 4, "duplicate": 1, "invalid": 1, "unstarted": 0},
        "evaluations": {
            "already_approved": 1,
            "promotable": 2,
            "blocked": 1,
            "unsupported": 0,
            "inconclusive": 1,
        },
        "promotion": {
            "identity_closed": 1,
            "proposed": 0,
            "blocked": 0,
            "unstarted": 0,
        },
        "skill_handoff": {
            "projected": 0,
            "skipped": 1,
            "blocked": 0,
            "unstarted": 0,
        },
        "source": _source(succeeded=2, fresh_skipped=1, policy_blocked=1),
        "route": _route(succeeded=2, duplicate_skipped=1, missing_metadata=1),
        "run_state": "partial",
    }
    payload.update(overrides)
    return build_metric_catalog_report(**payload)


def _walk(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_walk(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(_walk(item) for item in value)
    return str(value)


def _payload_dict(report: Any) -> dict[str, Any]:
    return cast(dict[str, Any], report.as_dict())


def test_metric_names_cover_eight_bounded_stages() -> None:
    assert tuple(METRIC_NAMES) == METRIC_STAGES
    assert len(METRIC_NAMES) == 8
    assert METRIC_NAMES.keys() == set(STAGE_TERMINALS)
    for stage, name in METRIC_NAMES.items():
        assert metric_name(stage) == name
        assert name.startswith("openopps.discovery.")
        assert "slo" not in name
        assert "threshold" not in name
    with pytest.raises(ObservabilityError, match="unsupported"):
        metric_name("latency")


def test_reason_and_terminal_dimensions_are_closed() -> None:
    assert REASON_CODES == {item.value for item in BoundedReason}
    assert TERMINAL_STATES == {
        "complete",
        "partial",
        "failed",
        "cancelled",
        "aborted",
        "nonterminal",
    }
    assert STAGE_TERMINALS["scout"] == OPERATION_TERMINALS
    assert set(STAGE_TERMINALS["channel"]) == set(OPERATION_TERMINALS)


def test_payload_rejects_urls_queries_secrets_and_arbitrary_labels() -> None:
    payload = _payload_dict(_report())
    payload["note"] = SECRET_MARKER
    with pytest.raises(ObservabilityError, match="forbidden"):
        assert_bounded_metric_payload(payload)

    payload = _payload_dict(_report())
    metrics = cast(list[dict[str, Any]], payload["metrics"])
    cast(dict[str, Any], metrics[0]["reasons"])["ECONNRESET"] = 1
    with pytest.raises(ObservabilityError, match="reason"):
        assert_bounded_metric_payload(payload)

    payload = _payload_dict(_report())
    metrics = cast(list[dict[str, Any]], payload["metrics"])
    metrics[0]["name"] = "http.server.duration"
    with pytest.raises(ObservabilityError, match="name"):
        assert_bounded_metric_payload(payload)


def test_report_emits_conserved_totals_and_reason_distributions() -> None:
    payload = _payload_dict(_report())
    metrics = cast(list[dict[str, Any]], payload["metrics"])
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for item in metrics:
        by_stage.setdefault(str(item["stage"]), []).append(item)

    scout = by_stage["scout"][0]
    terminals = cast(dict[str, int], scout["terminals"])
    reasons = cast(dict[str, int], scout["reasons"])
    assert scout["planned"] == 2
    assert terminals["succeeded"] == 1
    assert terminals["rate_limited"] == 1
    assert reasons["none"] == 1
    assert reasons["rate_limited"] == 1
    assert sum(terminals[name] for name in OPERATION_TERMINALS) == 2

    official = next(
        item
        for item in by_stage["channel"]
        if cast(dict[str, Any], item["attributes"])["openopps.discovery.channel"]
        == "official"
    )
    search = next(
        item
        for item in by_stage["channel"]
        if cast(dict[str, Any], item["attributes"])["openopps.discovery.channel"]
        == "search"
    )
    assert official["planned"] == 2
    assert cast(dict[str, Any], official["attributes"])[
        "openopps.discovery.complete"
    ] is True
    assert search["planned"] == 3
    search_reasons = cast(dict[str, int], search["reasons"])
    assert search_reasons["rate_limited"] == 1
    assert search_reasons["transport_rejected"] == 1
    assert cast(dict[str, Any], search["attributes"])[
        "openopps.discovery.complete"
    ] is False

    source = by_stage["source"][0]
    source_terminals = cast(dict[str, int], source["terminals"])
    source_reasons = cast(dict[str, int], source["reasons"])
    assert source["planned"] == 4
    assert source_terminals["fresh_skipped"] == 1
    assert source_terminals["policy_blocked"] == 1
    assert source_reasons["policy_unresolved"] == 1

    route = by_stage["route"][0]
    route_terminals = cast(dict[str, int], route["terminals"])
    assert route["planned"] == 4
    assert route_terminals["duplicate_skipped"] == 1
    assert route_terminals["missing_metadata"] == 1


def test_report_correlates_manifest_catalog_selector_policy_promotion_digests() -> None:
    evidence = _evidence()
    report = _report(evidence=evidence, manifest_digest=_sha("manifest"))
    digests = cast(dict[str, str], _payload_dict(report)["digests"])
    assert digests == {
        "catalogSha256": evidence.catalog_content_digest,
        "catalogTreeSha256": evidence.catalog_tree_digest,
        "manifestSha256": _sha("manifest"),
        "policySha256": evidence.policy_digest,
        "promotionSha256": evidence.promotion_digest,
        "selectorSha256": evidence.selector_digest,
    }
    with pytest.raises(ObservabilityError, match="SHA-256"):
        build_metric_catalog_report(
            evidence=evidence,
            manifest_digest="not-a-digest",
        )


def test_evidence_classes_distinguish_fetch_reuse_and_completeness() -> None:
    assert classify_evidence_class(request_outcome="succeeded") == "fetched"
    assert (
        classify_evidence_class(request_outcome="succeeded", grain_complete=True)
        == "complete"
    )
    assert classify_evidence_class(transport_state="not_modified") == "not_modified"
    assert classify_evidence_class(reused=True) == "reused"
    assert classify_evidence_class(transport_state="verified_cache") == "reused"
    assert classify_evidence_class(request_outcome="blocked") == "blocked"
    assert classify_evidence_class(request_outcome="rate_limited") == "rate_limited"
    assert classify_evidence_class(request_outcome="failed") == "partial"
    report = _report()
    by_stage = {item.stage: item for item in report.metrics if item.stage != "channel"}
    official = next(
        item
        for item in report.metrics
        if item.attributes.get("openopps.discovery.channel") == "official"
    )
    search = next(
        item
        for item in report.metrics
        if item.attributes.get("openopps.discovery.channel") == "search"
    )
    assert official.evidence["complete"] == 2
    assert official.evidence["fetched"] == 0
    assert search.evidence["fetched"] == 1
    assert search.evidence["rate_limited"] == 1
    assert search.evidence["partial"] == 1
    assert by_stage["source"].evidence["reused"] == 1
    assert by_stage["source"].evidence["blocked"] == 1
    assert by_stage["skill_handoff"].evidence["reused"] == 1
    assert set(official.evidence) == set(EVIDENCE_CLASSES)
    with pytest.raises(ObservabilityError, match="unsupported"):
        classify_evidence_class(request_outcome=cast(Any, "open"))


def test_metric_cardinality_is_bounded() -> None:
    payload = _payload_dict(_report())
    metrics = cast(list[dict[str, Any]], payload["metrics"])
    names = {item["name"] for item in metrics}
    assert names == set(METRIC_NAMES.values())
    assert len(METRIC_NAMES) == 8
    channel_series = [item for item in metrics if item["stage"] == "channel"]
    assert len(channel_series) == len(DiscoveryChannel)
    for item in metrics:
        attributes = cast(dict[str, Any], item["attributes"])
        assert len(attributes) <= MAX_METRIC_ATTRIBUTES
        assert set(cast(dict[str, int], item["evidence"])) == set(EVIDENCE_CLASSES)
        assert set(cast(dict[str, int], item["reasons"])) <= REASON_CODES
        assert attributes["openopps.discovery.state"] in TERMINAL_STATES


def test_secret_nondisclosure_walks_nested_payload() -> None:
    report = _report()
    rendered = _walk(_payload_dict(report))
    assert SECRET_MARKER not in rendered
    assert "jobs.example.test" not in rendered
    assert "unaccounted" not in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered
    for item in report.metrics:
        assert SECRET_MARKER not in _walk(dict(item.attributes))


def test_empty_catalog_is_nonterminal_and_conserved() -> None:
    payload = _payload_dict(
        build_metric_catalog_report(
            evidence=_evidence(),
            manifest_digest=_sha("manifest"),
        )
    )
    metrics = cast(list[dict[str, Any]], payload["metrics"])
    assert {item["name"] for item in metrics} == set(METRIC_NAMES.values())
    for item in metrics:
        assert item["planned"] == 0
        attributes = cast(dict[str, Any], item["attributes"])
        assert attributes["openopps.discovery.complete"] is False
        assert attributes["openopps.discovery.state"] == "nonterminal"
        assert sum(cast(dict[str, int], item["evidence"]).values()) == 0


def test_skill_handoff_skip_does_not_reference_wagents() -> None:
    report = _report(
        skill_handoff={
            "projected": 0,
            "skipped": 1,
            "blocked": 0,
            "unstarted": 0,
        }
    )
    skill = next(item for item in report.metrics if item.stage == "skill_handoff")
    assert skill.planned == 1
    assert skill.terminals["skipped"] == 1
    assert skill.attributes["openopps.discovery.complete"] is True
    source = (DISCOVERY / "observability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    rendered = ast.dump(tree)
    assert "wagents" not in rendered
    assert "wagents" not in source


def test_ingest_source_and_route_conservation_join_the_catalog() -> None:
    source = _source(succeeded=1, cancelled=1, unstarted=1)
    route = _route(succeeded=1, cancelled=1, unstarted=1)
    report = _report(source=source, route=route, run_state="cancelled")
    source_series = next(item for item in report.metrics if item.stage == "source")
    route_series = next(item for item in report.metrics if item.stage == "route")
    assert source_series.planned == 3
    assert source_series.terminals["cancelled"] == 1
    assert source_series.terminals["unstarted"] == 1
    assert route_series.planned == 3
    assert route_series.attributes["openopps.discovery.state"] == "cancelled"
    assert source.unaccounted_ids == ()
    assert "unaccounted" not in _walk(_payload_dict(report))
