from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest
from pydantic import ValidationError

from openopps.discovery.identity import (
    normalize_candidate_identity,
    resolve_candidate_identities,
)
from openopps.discovery.models import (
    ApprovedIngestionSelectorEnvelope,
    CandidateIdentity,
    CandidateOccurrence,
    ChannelBudget,
    ChannelOperationAccounting,
    ChannelProfile,
    DiscoveryBundleManifest,
    DiscoveryPromotionPolicyDecision,
    EvaluationAxes,
    LivenessEvidence,
    NormalizedCandidate,
    RouteOutcome,
    ScoutCandidateAccounting,
    SourceOutcome,
    TerminalEvaluation,
    TrustedDiscoveryProfile,
    WholeRunBudget,
)


SHA = "a" * 64


def _channel_budget(**updates: int) -> ChannelBudget:
    values = {
        "query_limit": 2,
        "request_limit": 10,
        "origin_limit": 3,
        "redirect_limit": 2,
        "page_limit": 3,
        "response_byte_limit": 1_000,
        "aggregate_byte_limit": 5_000,
        "candidate_limit": 20,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 16,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(updates)
    return ChannelBudget(**values)


def _identity(
    *, token: str | None = "CaseSensitive", key: str = "acme"
) -> CandidateIdentity:
    return normalize_candidate_identity(
        key=key,
        url=f"https://jobs.example.test/{key}",
        provider_id="greenhouse",
        provider_token=token,
        owner="official",
        candidate_kind="board_route",
        adapter_id="greenhouse_source",
    )


def test_strict_models_reject_coercion_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _channel_budget(request_limit="10")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ChannelBudget(**{**_channel_budget().model_dump(), "unknown": 1})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("redirect_limit", 11),
        ("retry_limit", 11),
        ("parser_depth_limit", 129),
        ("concurrency_limit", 65),
    ),
)
def test_channel_budget_rejects_values_above_trusted_ceilings(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        _channel_budget(**{field: value})


def test_channel_budget_rejects_impossible_concurrency_relationships() -> None:
    with pytest.raises(ValidationError, match="concurrency"):
        _channel_budget(request_limit=1, concurrency_limit=2)
    with pytest.raises(ValidationError, match="per-origin"):
        _channel_budget(concurrency_limit=1, per_origin_concurrency_limit=2)


def test_trusted_profile_is_versioned_frozen_and_channel_sorted() -> None:
    budget = _channel_budget()
    channel = ChannelProfile(
        channel="official",
        budget=budget,
        seed_ids=("seed-a",),
        allowed_origins=("https://example.test:443",),
        allowed_query_keys=("page",),
        parser_ids=("official-json-v1",),
    )
    profile = TrustedDiscoveryProfile(
        profile_id="bounded-default",
        profile_version="1",
        whole_run_budget=WholeRunBudget(
            request_limit=10,
            aggregate_byte_limit=5_000,
            candidate_limit=20,
            concurrency_limit=2,
            wall_clock_limit_ms=5_000,
        ),
        channels=(channel,),
        profile_digest=SHA,
    )

    with pytest.raises(ValidationError):
        profile.profile_id = "changed"


def test_candidate_identity_factory_preserves_case_sensitive_provider_token() -> None:
    identity = _identity(token="BoardTokenAa")

    assert identity.provider_token == "BoardTokenAa"
    assert identity.candidate_kind == "board_route"
    assert identity.adapter_id == "greenhouse_source"


def test_candidate_identity_direct_construction_rejects_noncanonical_boundary() -> None:
    values = _identity().model_dump()
    values["canonical_url"] = "https://other.example.test/"

    with pytest.raises(ValidationError, match="canonical"):
        CandidateIdentity(**values)


def test_shared_host_with_distinct_provider_tokens_is_not_an_automatic_collision() -> (
    None
):
    left = _identity(token="left", key="left")
    right = _identity(token="right", key="right")
    occurrences = (
        CandidateOccurrence(
            occurrence_id="left",
            channel="official",
            identity=left,
            provenance_ids=("p-left",),
        ),
        CandidateOccurrence(
            occurrence_id="right",
            channel="official",
            identity=right,
            provenance_ids=("p-right",),
        ),
    )

    result = resolve_candidate_identities(occurrences, approved_catalog=())

    assert result.collisions == ()
    assert result.promotable_candidates == (left, right)


def test_unresolved_shared_domain_without_stable_tokens_remains_a_collision() -> None:
    left = _identity(token=None, key="left")
    right = _identity(token=None, key="right")
    result = resolve_candidate_identities(
        (
            CandidateOccurrence(
                occurrence_id="left",
                channel="official",
                identity=left,
                provenance_ids=("p-left",),
            ),
            CandidateOccurrence(
                occurrence_id="right",
                channel="official",
                identity=right,
                provenance_ids=("p-right",),
            ),
        ),
        approved_catalog=(),
    )

    assert result.collisions[0].reasons == ("domain",)
    assert result.promotable_candidates == ()


def test_occurrence_provenance_is_sorted_and_merged_without_losing_edges() -> None:
    identity = _identity()
    first = CandidateOccurrence(
        occurrence_id="b",
        channel="official",
        identity=identity,
        provenance_ids=("p-z", "p-a"),
    )
    second = CandidateOccurrence(
        occurrence_id="a",
        channel="search",
        identity=identity,
        provenance_ids=("p-b",),
    )

    result = resolve_candidate_identities((first, second), approved_catalog=())

    assert first.provenance_ids == ("p-a", "p-z")
    assert result.candidates[0].occurrence_ids == ("a", "b")
    assert result.candidates[0].provenance_ids == ("p-a", "p-b", "p-z")


def test_liveness_time_requires_timezone_and_normalizes_to_utc() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        LivenessEvidence(
            response_class="expected_payload",
            expected_structure=True,
            observed_at=datetime(2026, 8, 21, 12, 0),
        )

    evidence = LivenessEvidence(
        response_class="expected_payload",
        expected_structure=True,
        observed_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC) + timedelta(hours=4),
    )
    assert evidence.observed_at.tzinfo is UTC


@pytest.mark.parametrize("model", (SourceOutcome, RouteOutcome))
def test_fresh_skip_requires_authority_and_digest_and_other_states_forbid_it(
    model: type[SourceOutcome] | type[RouteOutcome],
) -> None:
    id_field = "source_id" if model is SourceOutcome else "route_id"
    with pytest.raises(ValidationError, match="fresh"):
        model(
            **{
                id_field: "item",
                "disposition": "fresh_skipped",
                "started": True,
                "authoritative": False,
                "freshness_context_digest": SHA,
            }
        )
    with pytest.raises(ValidationError, match="fresh"):
        model(
            **{
                id_field: "item",
                "disposition": "succeeded",
                "started": True,
                "authoritative": True,
                "freshness_context_digest": SHA,
            }
        )


def test_terminal_evaluation_derives_disposition_and_review_eligibility() -> None:
    axes = EvaluationAxes(
        liveness="live",
        support="supported",
        policy="allowed",
        taxonomy="complete",
    )
    evaluation = TerminalEvaluation(
        candidate_id="candidate-a",
        axes=axes,
        disposition="promotable",
        eligible_for_review=True,
        reason_codes=(),
    )
    assert evaluation.disposition == "promotable"

    with pytest.raises(ValidationError, match="eligibility"):
        TerminalEvaluation(
            candidate_id="candidate-a",
            axes=axes,
            disposition="promotable",
            eligible_for_review=False,
            reason_codes=(),
        )


def test_normalized_candidate_requires_canonical_semantic_arrays() -> None:
    with pytest.raises(ValidationError, match="canonically sorted"):
        NormalizedCandidate(
            candidate_id="candidate-a",
            identity=_identity(),
            occurrence_ids=("b", "a"),
            provenance_ids=("p",),
        )


def test_channel_operation_accounting_conserves_operations_requests_and_bytes() -> None:
    accounting = ChannelOperationAccounting(
        channel="official",
        channel_state="complete",
        planned_operations=2,
        succeeded=1,
        blocked=0,
        rate_limited=0,
        timed_out=0,
        failed=0,
        cancelled=0,
        unstarted=1,
        request_limit=5,
        request_consumed=2,
        request_in_flight=0,
        request_remaining=3,
        byte_limit=100,
        admitted_bytes=40,
        remaining_bytes=60,
    )
    assert accounting.planned_operations == 2

    with pytest.raises(ValidationError, match="denominator"):
        ChannelOperationAccounting(
            **{**accounting.model_dump(), "planned_operations": 3}
        )


def test_scout_candidate_accounting_conserves_every_declared_denominator() -> None:
    accounting = ScoutCandidateAccounting(
        observed_candidate_occurrences=5,
        invalid_occurrences=1,
        normalized_occurrences=4,
        duplicate_occurrences=1,
        unique_candidates=3,
        already_approved=1,
        quarantined_candidates=2,
        promotable=1,
        blocked=0,
        unsupported=0,
        inconclusive=1,
    )
    assert accounting.quarantined_candidates == 2


def test_bundle_manifest_requires_one_canonical_utc_lexical_form() -> None:
    values = {
        "schemaVersion": "openopps.discovery.bundle.v1",
        "profileId": "default",
        "profileVersion": "1",
        "toolVersion": "0.1.0",
        "executionId": "run-a",
        "manifestId": SHA,
        "configurationSha256": SHA,
        "observedAt": "2026-08-21T12:00:00Z",
        "runState": "complete",
        "members": (),
        "memberCount": 0,
        "memberSetSha256": SHA,
    }
    assert DiscoveryBundleManifest(**values).observed_at.endswith("Z")
    for alternate in (
        "2026-08-21T12:00Z",
        "2026-08-21 12:00:00Z",
        "2026-08-21T12:00:00+00:00",
    ):
        with pytest.raises(ValidationError):
            DiscoveryBundleManifest(**{**values, "observedAt": alternate})


def test_candidate_and_decision_contracts_forbid_authority_shape_confusion() -> None:
    decision = {
        "schema_version": 1,
        "decision_id": "decision-a",
        "promotion_intent_digest": SHA,
        "head_sha": "a" * 40,
        "manifest_digest": SHA,
        "selection_digest": SHA,
        "resources_digest": SHA,
        "profile_digest": SHA,
        "policy_inputs_digest": SHA,
        "catalog_before_digest": SHA,
        "catalog_after_digest": SHA,
        "promotion_digest": SHA,
        "required_operations": ("access", "license", "publication"),
    }
    model = DiscoveryPromotionPolicyDecision(**decision)
    assert model.decision_id == "decision-a"
    assert model.model_dump(mode="json", by_alias=True) == {
        "schemaVersion": 1,
        "decisionId": "decision-a",
        "promotionIntentDigest": SHA,
        "headSha": "a" * 40,
        "manifestDigest": SHA,
        "selectionDigest": SHA,
        "resourcesDigest": SHA,
        "profileDigest": SHA,
        "policyInputsDigest": SHA,
        "catalogBeforeDigest": SHA,
        "catalogAfterDigest": SHA,
        "promotionDigest": SHA,
        "requiredOperations": ["access", "license", "publication"],
    }
    with pytest.raises(ValidationError):
        DiscoveryPromotionPolicyDecision(**{**decision, "approved": True})
    with pytest.raises(ValidationError, match="sorted and unique"):
        DiscoveryPromotionPolicyDecision(
            **{**decision, "required_operations": ("license", "access")}
        )


def test_private_envelope_is_distinct_and_source_set_is_exact() -> None:
    values = {
        "source_keys": ("a", "b"),
        "source_count": 2,
        "source_key_digest": SHA,
        "packaged_catalog_fingerprint": SHA,
        "catalog_content_digest": SHA,
        "catalog_tree_digest": SHA,
        "v7_policy_code_digest": SHA,
        "v7_policy_schema_digest": SHA,
        "v7_policy_evidence_digest": SHA,
        "v7_policy_corpus_digest": SHA,
        "supplementary_policy_digest": SHA,
        "promotion_digest": SHA,
        "envelope_id": SHA,
    }
    envelope = ApprovedIngestionSelectorEnvelope(**values)
    assert envelope.source_count == 2
    assert "public_selector" not in json.dumps(envelope.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="sorted"):
        ApprovedIngestionSelectorEnvelope(**{**values, "source_keys": ("b", "a")})
