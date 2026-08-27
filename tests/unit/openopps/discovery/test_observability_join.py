"""I807-I814 scout observability join: conserved denominators and typed degraded."""

from __future__ import annotations

from hashlib import sha256
import json

import pytest

from openopps.discovery.accounting import (
    TYPED_DEGRADED_CLASSES,
    RouteAccounting,
    ScoutRunEvidence,
    SourceAccounting,
    build_route_accounting,
    build_source_accounting,
    classify_typed_degraded,
    validate_operation_conservation,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.diagnostics import (
    ScoutObservabilityJoin,
    join_scout_observability,
)
from openopps.discovery.models import BoundedReason, RouteOutcome, SourceOutcome
from openopps.discovery.transport import OperationLedger, OperationLedgerSnapshot

SECRET_MARKER = "https://jobs.example.test/secret-token"
FRESHNESS = sha256(b"freshness").hexdigest()


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return sha256(payload).hexdigest()


def _evidence(**overrides: str) -> ScoutRunEvidence:
    payload = {
        "catalog_content_digest": _sha256("catalog-content"),
        "catalog_tree_digest": _sha256("catalog-tree"),
        "selector_digest": _sha256("selector"),
        "policy_digest": _sha256("policy"),
        "promotion_digest": _sha256("promotion"),
        "invocation_digest": _sha256("invocation"),
    }
    payload.update(overrides)
    return ScoutRunEvidence(**payload)


def _source(
    source_id: str,
    disposition: str,
    *,
    authoritative: bool | None = None,
) -> SourceOutcome:
    if authoritative is None:
        authoritative = disposition in {"succeeded", "fresh_skipped"}
    return SourceOutcome(
        source_id=source_id,
        disposition=disposition,
        started=disposition != "unstarted",
        authoritative=authoritative,
        freshness_context_digest=(
            FRESHNESS if disposition == "fresh_skipped" else None
        ),
    )


def _route(
    route_id: str,
    disposition: str,
    *,
    representative_id: str | None = None,
    authoritative: bool | None = None,
    freshness_context_digest: str | None = None,
) -> RouteOutcome:
    if authoritative is None:
        authoritative = disposition in {"succeeded", "fresh_skipped"}
    return RouteOutcome(
        route_id=route_id,
        disposition=disposition,
        representative_id=representative_id,
        started=disposition != "unstarted",
        authoritative=authoritative,
        freshness_context_digest=freshness_context_digest,
    )


def _source_accounting(
    planned: tuple[str, ...],
    outcomes: tuple[SourceOutcome, ...],
    *,
    run_state: str = "succeeded",
) -> SourceAccounting:
    return build_source_accounting(
        planned_source_ids=planned,
        outcomes=outcomes,
        run_state=run_state,
        freshness_context_digest=FRESHNESS,
    )


def _route_accounting(
    planned: tuple[str, ...],
    outcomes: tuple[RouteOutcome, ...],
    *,
    run_state: str = "succeeded",
) -> RouteAccounting:
    return build_route_accounting(
        planned_route_ids=planned,
        outcomes=outcomes,
        run_state=run_state,
        freshness_context_digest=FRESHNESS,
    )


def _operations(
    planned: tuple[str, ...],
    outcomes: dict[str, str],
    *,
    channel_state: str,
) -> OperationLedgerSnapshot:
    ledger = OperationLedger(planned_operation_ids=planned)
    for operation_id, outcome in outcomes.items():
        if outcome != "unstarted":
            ledger.start(operation_id)
        ledger.finish(operation_id, outcome=outcome)
    return ledger.close(channel_state=channel_state)


def _join(
    *,
    planned_source_ids: tuple[str, ...],
    planned_route_ids: tuple[str, ...],
    planned_operation_ids: tuple[str, ...],
    source_outcomes: tuple[SourceOutcome, ...],
    route_outcomes: tuple[RouteOutcome, ...],
    operation_outcomes: dict[str, str],
    channel_state: str,
    run_state: str,
    evidence: ScoutRunEvidence | None = None,
) -> ScoutObservabilityJoin:
    return join_scout_observability(
        source=_source_accounting(
            planned_source_ids, source_outcomes, run_state=run_state
        ),
        route=_route_accounting(planned_route_ids, route_outcomes, run_state=run_state),
        operations=_operations(
            planned_operation_ids, operation_outcomes, channel_state=channel_state
        ),
        planned_source_ids=planned_source_ids,
        planned_route_ids=planned_route_ids,
        planned_operation_ids=planned_operation_ids,
        run_state=run_state,
        evidence=evidence or _evidence(),
    )


def _walk(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_complete_run_attests_complete_with_none_diagnostic() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="succeeded",
    )

    assert joined.attestation == "complete"
    assert joined.degraded_class is None
    assert joined.diagnostic.reason_code is BoundedReason.NONE
    assert joined.metric_attributes["openopps.discovery.complete"] is True
    assert joined.metric_attributes["openopps.discovery.state"] == "complete"
    assert joined.metric_attributes["openopps.discovery.reason"] == "none"
    assert joined.source.complete is True
    assert joined.route.complete is True


def test_source_cancelled_is_single_class_typed_degraded() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "cancelled"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="cancelled",
    )

    assert joined.attestation == "degraded"
    assert joined.degraded_class == "cancelled"
    assert joined.source.cancelled == 1
    assert joined.source.complete is False
    assert joined.metric_attributes["openopps.discovery.complete"] is False
    assert joined.metric_attributes["openopps.discovery.state"] == "cancelled"


def test_source_unstarted_is_single_class_typed_degraded() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "unstarted"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="cancelled",
    )

    assert joined.attestation == "degraded"
    assert joined.degraded_class == "unstarted"
    assert joined.source.unstarted == 1
    assert joined.source.cancelled == 0
    assert joined.metric_attributes["openopps.discovery.state"] == "partial"


def test_mixed_cancelled_and_unstarted_sources_are_partial() -> None:
    joined = _join(
        planned_source_ids=("source-started", "source-queued"),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(
            _source("source-started", "cancelled"),
            _source("source-queued", "unstarted"),
        ),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="cancelled",
    )

    assert joined.source.cancelled == 1
    assert joined.source.unstarted == 1
    assert (
        joined.source.cancelled
        + joined.source.unstarted
        + joined.source.succeeded
        + joined.source.failed
        + joined.source.timed_out
        + joined.source.fresh_skipped
        + joined.source.policy_blocked
        + joined.source.rate_limited
        == joined.source.planned
    )
    assert joined.attestation == "degraded"
    assert joined.degraded_class == "partial"


def test_route_conservation_with_missing_deferred_and_duplicate() -> None:
    planned = (
        "route-succeeded",
        "route-duplicate",
        "route-missing",
        "route-deferred",
    )
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=planned,
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded"),),
        route_outcomes=(
            _route("route-succeeded", "succeeded", authoritative=True),
            _route(
                "route-duplicate",
                "duplicate_skipped",
                representative_id="route-succeeded",
                authoritative=False,
            ),
            _route("route-missing", "missing_metadata", authoritative=False),
            _route("route-deferred", "deferred", authoritative=False),
        ),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="partial",
    )

    assert joined.route.planned == 4
    assert joined.route.succeeded == 1
    assert joined.route.duplicate_skipped == 1
    assert joined.route.missing_metadata == 1
    assert joined.route.deferred == 1
    assert joined.route.authoritative_succeeded == 1
    assert (
        joined.route.succeeded
        + joined.route.failed
        + joined.route.timed_out
        + joined.route.fresh_skipped
        + joined.route.deferred
        + joined.route.duplicate_skipped
        + joined.route.missing_metadata
        + joined.route.policy_blocked
        + joined.route.rate_limited
        + joined.route.cancelled
        + joined.route.unstarted
        == joined.route.planned
    )
    assert joined.route.complete is False
    assert joined.attestation == "degraded"
    assert joined.degraded_class == "partial"


def test_non_authoritative_success_cannot_be_complete() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded", authoritative=True),),
        route_outcomes=(_route("route-1", "succeeded", authoritative=False),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="succeeded",
    )

    assert joined.route.succeeded == 1
    assert joined.route.authoritative_succeeded == 0
    assert joined.route.complete is False
    assert joined.attestation == "degraded"
    assert joined.degraded_class == "partial"
    assert joined.degraded_class is not None


def test_operation_ledger_snapshot_is_reused_and_conserved() -> None:
    planned_ops = ("op-catalog", "op-retry")
    ledger = OperationLedger(planned_operation_ids=planned_ops)
    ledger.start("op-catalog")
    ledger.finish("op-catalog", outcome="succeeded")
    ledger.finish("op-retry", outcome="unstarted")
    snapshot = ledger.close(channel_state="partial")

    assert sum(snapshot.terminals.values()) == snapshot.planned == 2

    joined = join_scout_observability(
        source=_source_accounting(
            ("source-1",),
            (_source("source-1", "succeeded"),),
            run_state="partial",
        ),
        route=_route_accounting(
            ("route-1",),
            (_route("route-1", "succeeded"),),
            run_state="partial",
        ),
        operations=snapshot,
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=planned_ops,
        run_state="partial",
        evidence=_evidence(),
    )

    assert joined.operations is snapshot
    assert sum(joined.operations.terminals.values()) == joined.operations.planned
    assert joined.attestation == "degraded"
    assert joined.degraded_class == "unstarted"


def test_typed_degraded_is_never_complete_and_fields_stay_separate() -> None:
    complete = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="succeeded",
    )
    degraded = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "failed"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="failed",
    )

    assert complete.attestation == "complete"
    assert complete.degraded_class is None
    assert "attestation" in complete.as_dict()
    assert "degradedClass" in complete.as_dict()
    assert complete.as_dict()["degradedClass"] is None

    assert degraded.attestation == "degraded"
    assert degraded.degraded_class == "failed"
    assert degraded.degraded_class in TYPED_DEGRADED_CLASSES
    assert degraded.attestation != "complete"
    assert not (degraded.attestation == "complete" and degraded.degraded_class)
    assert degraded.metric_attributes["openopps.discovery.complete"] is False
    assert degraded.diagnostic.reason_code is BoundedReason.TRANSPORT_REJECTED


def test_blocked_operation_maps_to_policy_blocked() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "blocked"},
        channel_state="failed",
        run_state="failed",
    )

    assert joined.degraded_class == "policy_blocked"
    assert joined.diagnostic.reason_code is BoundedReason.POLICY_UNRESOLVED
    assert joined.operations.terminals["blocked"] == 1


def test_rendered_join_never_includes_raw_urls_secrets_or_planned_ids() -> None:
    planned = (SECRET_MARKER,)
    joined = _join(
        planned_source_ids=planned,
        planned_route_ids=planned,
        planned_operation_ids=planned,
        source_outcomes=(_source(SECRET_MARKER, "succeeded"),),
        route_outcomes=(_route(SECRET_MARKER, "succeeded"),),
        operation_outcomes={SECRET_MARKER: "succeeded"},
        channel_state="complete",
        run_state="succeeded",
    )
    rendered = _walk(joined.as_dict())
    diagnostic = _walk(joined.diagnostic.as_dict())
    metrics = _walk(dict(joined.metric_attributes))

    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in diagnostic
    assert SECRET_MARKER not in metrics
    assert "unaccounted_ids" not in rendered
    assert "unaccountedIds" not in rendered
    assert SECRET_MARKER not in joined.source_plan_digest
    assert "jobs.example.test" not in rendered


def test_i813_requires_six_canonical_evidence_digests() -> None:
    evidence = _evidence()
    dumped = evidence.as_dict()
    assert dumped == {
        "catalogContentDigest": evidence.catalog_content_digest,
        "catalogTreeDigest": evidence.catalog_tree_digest,
        "selectorDigest": evidence.selector_digest,
        "policyDigest": evidence.policy_digest,
        "promotionDigest": evidence.promotion_digest,
        "invocationDigest": evidence.invocation_digest,
    }
    assert all(len(value) == 64 for value in dumped.values())

    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "succeeded"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="succeeded",
        evidence=evidence,
    )
    assert joined.as_dict()["evidence"] == dumped
    assert (
        joined.metric_attributes["openopps.discovery.identity.sha256"]
        == evidence.invocation_digest
    )

    with pytest.raises(TypeError):
        ScoutRunEvidence(  # type: ignore[call-arg]
            catalog_content_digest=_sha256("catalog-content"),
            catalog_tree_digest=_sha256("catalog-tree"),
            selector_digest=_sha256("selector"),
            policy_digest=_sha256("policy"),
            promotion_digest=_sha256("promotion"),
        )

    with pytest.raises(ValueError) as caught:
        _evidence(catalog_content_digest=SECRET_MARKER)
    assert SECRET_MARKER not in str(caught.value)
    assert "sha256" in str(caught.value)


def test_i814_pinned_plan_digest_ignores_later_catalog_mutation() -> None:
    catalog = ["https://jobs.example.test/source-a"]
    pinned_sources = tuple(catalog)
    pinned_routes = ("route-1",)
    pinned_ops = ("op-1",)
    first = join_scout_observability(
        source=_source_accounting(
            pinned_sources, (_source(pinned_sources[0], "succeeded"),)
        ),
        route=_route_accounting(pinned_routes, (_route("route-1", "succeeded"),)),
        operations=_operations(
            pinned_ops, {"op-1": "succeeded"}, channel_state="complete"
        ),
        planned_source_ids=pinned_sources,
        planned_route_ids=pinned_routes,
        planned_operation_ids=pinned_ops,
        run_state="succeeded",
        evidence=_evidence(),
    )

    catalog.append(SECRET_MARKER)
    second = join_scout_observability(
        source=_source_accounting(
            pinned_sources, (_source(pinned_sources[0], "succeeded"),)
        ),
        route=_route_accounting(pinned_routes, (_route("route-1", "succeeded"),)),
        operations=_operations(
            pinned_ops, {"op-1": "succeeded"}, channel_state="complete"
        ),
        planned_source_ids=pinned_sources,
        planned_route_ids=pinned_routes,
        planned_operation_ids=pinned_ops,
        run_state="succeeded",
        evidence=_evidence(),
    )

    expected = sha256(canonical_json_bytes(list(pinned_sources))).hexdigest()
    mutated = sha256(canonical_json_bytes(list(catalog))).hexdigest()
    assert first.source_plan_digest == second.source_plan_digest == expected
    assert first.source_plan_digest != mutated
    assert SECRET_MARKER not in _walk(second.as_dict())
    assert len(catalog) == 2


def test_error_messages_do_not_echo_untrusted_ids() -> None:
    with pytest.raises(ValueError) as caught:
        join_scout_observability(
            source=_source_accounting(
                ("source-1",), (_source("source-1", "succeeded"),)
            ),
            route=_route_accounting(("route-1",), (_route("route-1", "succeeded"),)),
            operations=_operations(
                ("op-1",), {"op-1": "succeeded"}, channel_state="complete"
            ),
            planned_source_ids=(SECRET_MARKER, SECRET_MARKER),
            planned_route_ids=("route-1",),
            planned_operation_ids=("op-1",),
            run_state="succeeded",
            evidence=_evidence(),
        )

    message = str(caught.value)
    assert SECRET_MARKER not in message
    assert "jobs.example.test" not in message
    assert "unique" in message

    with pytest.raises(ValueError) as mismatch:
        join_scout_observability(
            source=_source_accounting(
                ("source-1",), (_source("source-1", "succeeded"),)
            ),
            route=_route_accounting(("route-1",), (_route("route-1", "succeeded"),)),
            operations=_operations(
                ("op-1",), {"op-1": "succeeded"}, channel_state="complete"
            ),
            planned_source_ids=(SECRET_MARKER, "source-1"),
            planned_route_ids=("route-1",),
            planned_operation_ids=("op-1",),
            run_state="succeeded",
            evidence=_evidence(),
        )
    assert SECRET_MARKER not in str(mismatch.value)
    assert "conserved" in str(mismatch.value)


def test_complete_and_degraded_class_remain_separate_fields() -> None:
    joined = _join(
        planned_source_ids=("source-1",),
        planned_route_ids=("route-1",),
        planned_operation_ids=("op-1",),
        source_outcomes=(_source("source-1", "timed_out"),),
        route_outcomes=(_route("route-1", "succeeded"),),
        operation_outcomes={"op-1": "succeeded"},
        channel_state="complete",
        run_state="failed",
    )
    payload = joined.as_dict()
    assert payload["attestation"] == "degraded"
    assert payload["degradedClass"] == "timed_out"
    assert payload["attestation"] != payload["degradedClass"]
    assert payload["metrics"]["openopps.discovery.complete"] is False
    assert payload["metrics"]["openopps.discovery.state"] == "failed"


def test_complete_accounting_rejects_non_succeeded_run_state() -> None:
    source = SourceAccounting(
        planned=1,
        succeeded=1,
        failed=0,
        timed_out=0,
        fresh_skipped=0,
        policy_blocked=0,
        rate_limited=0,
        cancelled=0,
        unstarted=0,
        terminal=True,
        complete=True,
        unaccounted_ids=(SECRET_MARKER,),
    )
    route = RouteAccounting(
        planned=1,
        succeeded=1,
        failed=0,
        timed_out=0,
        fresh_skipped=0,
        deferred=0,
        duplicate_skipped=0,
        missing_metadata=0,
        policy_blocked=0,
        rate_limited=0,
        cancelled=0,
        unstarted=0,
        authoritative_succeeded=1,
        terminal=True,
        complete=True,
        unaccounted_ids=(),
    )
    with pytest.raises(ValueError) as caught:
        classify_typed_degraded(
            source=source,
            route=route,
            operation_terminals={
                "blocked": 0,
                "cancelled": 0,
                "failed": 0,
                "rate_limited": 0,
                "succeeded": 1,
                "timed_out": 0,
                "unstarted": 0,
            },
            operation_channel_state="complete",
            run_state="failed",
        )
    assert SECRET_MARKER not in str(caught.value)


def test_operation_conservation_rejects_uncounted_terminals() -> None:
    with pytest.raises(
        ValueError, match="planned operation denominator is not conserved"
    ):
        validate_operation_conservation(
            2,
            {
                "blocked": 0,
                "cancelled": 0,
                "failed": 0,
                "rate_limited": 0,
                "succeeded": 1,
                "timed_out": 0,
                "unstarted": 0,
            },
        )


def test_nonterminal_run_uses_typed_nonterminal_not_opaque_incomplete() -> None:
    joined = join_scout_observability(
        source=_source_accounting(
            ("source-a", "source-b"),
            (_source("source-a", "cancelled"),),
            run_state="nonterminal",
        ),
        route=_route_accounting(
            ("route-a", "route-b"),
            (_route("route-a", "succeeded"),),
            run_state="nonterminal",
        ),
        operations=_operations(
            ("op-a", "op-b"),
            {"op-a": "succeeded", "op-b": "unstarted"},
            channel_state="partial",
        ),
        planned_source_ids=("source-a", "source-b"),
        planned_route_ids=("route-a", "route-b"),
        planned_operation_ids=("op-a", "op-b"),
        run_state="nonterminal",
        evidence=_evidence(),
    )

    assert joined.attestation == "degraded"
    assert joined.degraded_class == "nonterminal"
    assert joined.diagnostic.reason_code is BoundedReason.NONE
    assert joined.metric_attributes["openopps.discovery.state"] == "nonterminal"
    assert joined.as_dict()["degradedClass"] != "incomplete"
    assert "unaccountedIds" not in _walk(joined.as_dict())
    assert "source-b" not in _walk(joined.as_dict())


def test_uniform_unstarted_source_accounting_conserves_the_pin() -> None:
    from openopps.discovery.accounting import build_uniform_source_accounting

    planned = ("source-a", "source-b", "source-c")
    accounting = build_uniform_source_accounting(
        planned, disposition="unstarted", run_state="succeeded"
    )
    assert accounting.planned == 3
    assert accounting.unstarted == 3
    assert accounting.succeeded == 0
    assert accounting.complete is False
    assert accounting.terminal is True
    assert accounting.unaccounted_ids == ()


def test_prepare_selector_bound_scout_pins_packaged_envelope() -> None:
    from pathlib import Path

    from openopps.discovery.diagnostics import (
        attach_selector_bound_observability,
        prepare_selector_bound_scout,
    )

    repo = Path(__file__).resolve().parents[4]
    pin = prepare_selector_bound_scout(repo)
    frozen = pin.frozen_source_ids
    envelope = json.loads(
        (
            repo
            / "src/openopps/discovery/data/approved_ingestion_selector_envelope.json"
        ).read_text(encoding="utf-8")
    )
    assert frozen == tuple(envelope["sourceKeys"])
    catalog_path = (
        repo
        / "src"
        / "openopps"
        / "providers"
        / "sources"
        / "data"
        / "portfolio_source_catalog.json"
    )
    catalog_before = catalog_path.read_bytes()
    joined = attach_selector_bound_observability(
        {"command": "scout", "status": "complete"},
        pin=pin,
        invocation_identity="cli-test",
    )
    assert catalog_path.read_bytes() == catalog_before
    assert pin.frozen_source_ids == frozen
    observability = joined["observability"]
    assert observability["source"]["planned"] == len(frozen)
    assert observability["source"]["unstarted"] == len(frozen)
    assert observability["attestation"] == "degraded"
    assert observability["degradedClass"] == "unstarted"
    rendered = json.dumps(joined)
    assert frozen[0] not in rendered
    assert "https://" not in rendered
    assert "unaccountedIds" not in rendered
    checkout = joined["checkoutSha"]
    assert isinstance(checkout, str) and len(checkout) == 40


def test_prepare_selector_bound_scout_rejects_v7_public_selector() -> None:
    from pathlib import Path

    from openopps.discovery.diagnostics import (
        SelectorBoundError,
        prepare_selector_bound_scout,
    )

    repo = Path(__file__).resolve().parents[4]
    keys = ["a16z"]
    selector = {
        "schemaVersion": 1,
        "corpusId": "public",
        "sourceCount": 1,
        "sourceKeysSha256": sha256(
            "".join(f"{key}\n" for key in keys).encode()
        ).hexdigest(),
        "sourceKeys": keys,
    }
    with pytest.raises(SelectorBoundError, match="SourceSelector"):
        prepare_selector_bound_scout(
            repo, envelope_bytes=canonical_json_bytes(selector)
        )


def test_prepare_selector_bound_scout_rejects_persisted_only_keys() -> None:
    from pathlib import Path
    from openopps.discovery.diagnostics import (
        SelectorBoundError,
        prepare_selector_bound_scout,
    )

    repo = Path(__file__).resolve().parents[4]
    envelope = json.loads(
        (
            repo
            / "src/openopps/discovery/data/approved_ingestion_selector_envelope.json"
        ).read_text(encoding="utf-8")
    )
    forbidden = envelope["sourceKeys"][0]
    with pytest.raises(SelectorBoundError, match="forbidden"):
        prepare_selector_bound_scout(repo, key_classes={forbidden: "persisted_only"})


def test_prepare_selector_bound_scout_rejects_mismatched_catalog_digest() -> None:
    from pathlib import Path

    from openopps.discovery.diagnostics import (
        SelectorBoundError,
        prepare_selector_bound_scout,
    )

    repo = Path(__file__).resolve().parents[4]
    envelope = json.loads(
        (
            repo
            / "src/openopps/discovery/data/approved_ingestion_selector_envelope.json"
        ).read_text(encoding="utf-8")
    )
    from openopps.discovery.promotion import compute_envelope_id

    envelope["catalogContentDigest"] = sha256(b"mutated-catalog").hexdigest()
    envelope["envelopeId"] = compute_envelope_id(envelope)
    with pytest.raises(SelectorBoundError, match="catalog"):
        prepare_selector_bound_scout(
            repo, envelope_bytes=canonical_json_bytes(envelope)
        )
