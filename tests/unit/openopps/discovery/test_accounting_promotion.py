"""Red contracts for discovery identity, evaluation, accounting, and promotion.

These tests intentionally describe APIs that do not exist at the B199 red-test
barrier.  They keep filesystem and process crashes behind explicit pure seams;
integration tests later exercise the real lock, fsync, rename, and kill points.

OpenSpec coverage: T111-T120, T138-T139, and T141-T142.  Transport, secret
scanning, and process-isolation contracts are owned by a separate test lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from importlib import import_module
from itertools import permutations, product
from types import ModuleType
from typing import Any, Callable, Mapping

import pytest

from openopps.discovery.canonical import canonical_json_bytes


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


@dataclass(frozen=True)
class _ContractApi:
    CandidateIdentity: type[Any]
    CandidateOccurrence: type[Any]
    EvaluationAxes: type[Any]
    PolicyAxisSet: type[Any]
    LivenessEvidence: type[Any]
    SupportEvidence: type[Any]
    SourceOutcome: type[Any]
    RouteOutcome: type[Any]
    DiscoveryPromotionPolicyDecision: type[Any]
    PromotionIntent: type[Any]
    PromotionLedgerEvent: type[Any]
    ApplyJournal: type[Any]
    normalize_candidate_identity: Callable[..., Any]
    resolve_candidate_identities: Callable[..., Any]
    validate_taxonomy: Callable[..., Any]
    evaluate_disposition: Callable[..., Any]
    evaluate_policy: Callable[..., Any]
    classify_liveness: Callable[..., Any]
    classify_support: Callable[..., Any]
    build_source_accounting: Callable[..., Any]
    build_route_accounting: Callable[..., Any]
    CandidateAuthorityError: type[Exception]
    PromotionDecisionError: type[Exception]
    PromotionLedgerError: type[Exception]
    validate_candidate_manifest_authority: Callable[..., Any]
    validate_promotion_decision: Callable[..., Any]
    compute_promotion_intent_digest: Callable[..., str]
    append_ledger_event: Callable[..., Any]
    validate_ledger_chain: Callable[..., Any]
    choose_recovery_action: Callable[..., Any]
    transition_journal: Callable[..., Any]
    validate_applied_commit: Callable[..., Any]


def _required(module: ModuleType, name: str) -> Any:
    try:
        return getattr(module, name)
    except AttributeError as exc:  # pragma: no cover - exercised by the red state
        raise ImportError(f"{module.__name__}.{name} is required") from exc


def _load_contract_api() -> _ContractApi:
    models = import_module("openopps.discovery.models")
    identity = import_module("openopps.discovery.identity")
    evaluation = import_module("openopps.discovery.evaluation")
    accounting = import_module("openopps.discovery.accounting")
    promotion = import_module("openopps.discovery.promotion")
    return _ContractApi(
        CandidateIdentity=_required(models, "CandidateIdentity"),
        CandidateOccurrence=_required(models, "CandidateOccurrence"),
        EvaluationAxes=_required(models, "EvaluationAxes"),
        PolicyAxisSet=_required(models, "PolicyAxisSet"),
        LivenessEvidence=_required(models, "LivenessEvidence"),
        SupportEvidence=_required(models, "SupportEvidence"),
        SourceOutcome=_required(models, "SourceOutcome"),
        RouteOutcome=_required(models, "RouteOutcome"),
        DiscoveryPromotionPolicyDecision=_required(
            models, "DiscoveryPromotionPolicyDecision"
        ),
        PromotionIntent=_required(models, "PromotionIntent"),
        PromotionLedgerEvent=_required(models, "PromotionLedgerEvent"),
        ApplyJournal=_required(models, "ApplyJournal"),
        normalize_candidate_identity=_required(
            identity, "normalize_candidate_identity"
        ),
        resolve_candidate_identities=_required(
            identity, "resolve_candidate_identities"
        ),
        validate_taxonomy=_required(identity, "validate_taxonomy"),
        evaluate_disposition=_required(evaluation, "evaluate_disposition"),
        evaluate_policy=_required(evaluation, "evaluate_policy"),
        classify_liveness=_required(evaluation, "classify_liveness"),
        classify_support=_required(evaluation, "classify_support"),
        build_source_accounting=_required(accounting, "build_source_accounting"),
        build_route_accounting=_required(accounting, "build_route_accounting"),
        CandidateAuthorityError=_required(promotion, "CandidateAuthorityError"),
        PromotionDecisionError=_required(promotion, "PromotionDecisionError"),
        PromotionLedgerError=_required(promotion, "PromotionLedgerError"),
        validate_candidate_manifest_authority=_required(
            promotion, "validate_candidate_manifest_authority"
        ),
        validate_promotion_decision=_required(promotion, "validate_promotion_decision"),
        compute_promotion_intent_digest=_required(
            promotion, "compute_promotion_intent_digest"
        ),
        append_ledger_event=_required(promotion, "append_ledger_event"),
        validate_ledger_chain=_required(promotion, "validate_ledger_chain"),
        choose_recovery_action=_required(promotion, "choose_recovery_action"),
        transition_journal=_required(promotion, "transition_journal"),
        validate_applied_commit=_required(promotion, "validate_applied_commit"),
    )


_API: _ContractApi | None = None
_API_ERROR: Exception | None = None


def _api() -> _ContractApi:
    global _API, _API_ERROR
    if _API is None and _API_ERROR is None:
        try:
            _API = _load_contract_api()
        except (ImportError, ModuleNotFoundError) as exc:
            _API_ERROR = exc
    if _API_ERROR is not None:
        pytest.fail(
            f"missing intended openopps.discovery red-test API: {_API_ERROR}",
            pytrace=False,
        )
    assert _API is not None
    return _API


def _identity(
    *,
    key: str = "acme",
    url: str = "https://jobs.example.test/acme",
    provider_id: str = "greenhouse",
    provider_token: str | None = "acme",
    owner: str = "official",
) -> Any:
    api = _api()
    return api.normalize_candidate_identity(
        key=key,
        url=url,
        provider_id=provider_id,
        provider_token=provider_token,
        owner=owner,
    )


def _occurrence(identity: Any, occurrence_id: str) -> Any:
    api = _api()
    return api.CandidateOccurrence(
        occurrence_id=occurrence_id,
        channel="official",
        identity=identity,
        provenance_ids=(f"resource-{occurrence_id}",),
    )


def _intent(**updates: object) -> Any:
    api = _api()
    values: dict[str, object] = {
        "head_sha": "a" * 40,
        "manifest_digest": _sha256("manifest"),
        "selection_digest": _sha256("selection"),
        "resources_digest": _sha256("resources"),
        "profile_digest": _sha256("profile"),
        "policy_inputs_digest": _sha256("policy-inputs"),
        "catalog_before_digest": _sha256("catalog-before"),
        "catalog_after_digest": _sha256("catalog-after"),
        "promotion_digest": _sha256("promotion"),
        "required_operations": (
            "access",
            "license",
            "publication",
            "redistribution",
            "sync",
        ),
    }
    values.update(updates)
    return api.PromotionIntent(**values)


def _decision_payload(api: _ContractApi, intent: Any) -> dict[str, object]:
    payload = intent.model_dump(mode="json", by_alias=True)
    payload.update(
        {
            "schemaVersion": 1,
            "decisionId": "maintainer-decision-1",
            "promotionIntentDigest": api.compute_promotion_intent_digest(intent),
        }
    )
    return payload


def _journal() -> Any:
    api = _api()
    before_catalog = b'{"sources":[]}\n'
    after_catalog = b'{"sources":["acme"]}\n'
    before_generated = b'{"sources":[]}\n'
    after_generated = b'{"sources":["acme"]}\n'
    entries = (
        {
            "path": "src/openopps/providers/sources/data/catalog.json",
            "before": {
                "exists": True,
                "mode": 0o644,
                "content": before_catalog,
                "sha256": _sha256(before_catalog),
            },
            "after": {
                "exists": True,
                "mode": 0o644,
                "content": after_catalog,
                "sha256": _sha256(after_catalog),
            },
        },
        {
            "path": "web/lib/generated/openopps-data.json",
            "before": {
                "exists": True,
                "mode": 0o644,
                "content": before_generated,
                "sha256": _sha256(before_generated),
            },
            "after": {
                "exists": True,
                "mode": 0o644,
                "content": after_generated,
                "sha256": _sha256(after_generated),
            },
        },
    )
    return api.ApplyJournal(
        schema_version=1,
        phase="prepared",
        promotion_intent_digest=_sha256("intent"),
        lock_nonce="nonce-1",
        head_sha="a" * 40,
        entries=entries,
    )


# T111: exact and canonical identity collisions remain explicit.
@pytest.mark.parametrize(
    ("first", "second", "reason"),
    [
        (
            {"key": "same", "url": "https://one.example.test"},
            {"key": "same", "url": "https://two.example.test"},
            "exact_key",
        ),
        (
            {"key": "one", "url": "https://same.example.test/jobs"},
            {"key": "two", "url": "https://same.example.test/jobs"},
            "exact_url",
        ),
        (
            {"key": "one", "url": "https://JOBS.example.test:443/acme"},
            {"key": "two", "url": "https://jobs.example.test/acme"},
            "canonical_url",
        ),
        (
            {
                "key": "one",
                "url": "https://one.example.test",
                "provider_token": "shared",
            },
            {
                "key": "two",
                "url": "https://two.example.test",
                "provider_token": "shared",
            },
            "provider_token",
        ),
    ],
)
def test_identity_collisions_are_not_silently_resolved(
    first: Mapping[str, object],
    second: Mapping[str, object],
    reason: str,
) -> None:
    api = _api()
    left = _identity(**first)
    right = _identity(**second)

    result = api.resolve_candidate_identities(
        (_occurrence(left, "left"), _occurrence(right, "right")),
        approved_catalog=(),
    )

    assert len(result.collisions) == 1
    assert reason in result.collisions[0].reasons
    assert result.collisions[0].resolved is False
    assert result.promotable_candidates == ()


def test_approved_catalog_identity_is_already_approved_not_promotable() -> None:
    api = _api()
    approved = _identity()

    result = api.resolve_candidate_identities(
        (_occurrence(_identity(), "candidate"),),
        approved_catalog=(approved,),
    )

    assert result.unique_candidates == 1
    assert result.already_approved == 1
    assert result.quarantined_candidates == 0
    assert result.promotable_candidates == ()


# T112: occurrence and unique-candidate denominators are both conserved.
def test_duplicate_occurrences_conserve_occurrence_and_candidate_counts() -> None:
    api = _api()
    repeated = _identity()
    distinct = _identity(
        key="beta",
        url="https://jobs.example.test/beta",
        provider_token="beta",
    )

    result = api.resolve_candidate_identities(
        (
            _occurrence(repeated, "first"),
            _occurrence(repeated, "repeat"),
            _occurrence(distinct, "distinct"),
        ),
        approved_catalog=(),
    )

    assert result.observed_occurrences == 3
    assert result.invalid_occurrences == 0
    assert result.normalized_occurrences == 3
    assert result.duplicate_occurrences == 1
    assert result.unique_candidates == 2
    assert result.normalized_occurrences == (
        result.duplicate_occurrences + result.unique_candidates
    )


# T113/T139: disposition is a total, monotonic, order-independent partition.
@pytest.mark.parametrize(
    ("axes", "expected"),
    [
        (
            {
                "liveness": "live",
                "support": "supported",
                "policy": "allowed",
                "taxonomy": "complete",
                "already_approved": True,
            },
            "already_approved",
        ),
        (
            {
                "liveness": "inconclusive",
                "support": "unsupported",
                "policy": "blocked",
                "taxonomy": "incomplete",
            },
            "blocked",
        ),
        (
            {
                "liveness": "inconclusive",
                "support": "unsupported",
                "policy": "allowed",
                "taxonomy": "incomplete",
            },
            "inconclusive",
        ),
        (
            {
                "liveness": "live",
                "support": "unsupported",
                "policy": "allowed",
                "taxonomy": "complete",
            },
            "unsupported",
        ),
        (
            {
                "liveness": "live",
                "support": "supported",
                "policy": "allowed",
                "taxonomy": "complete",
            },
            "promotable",
        ),
    ],
)
def test_disposition_partition_has_exact_expected_member(
    axes: Mapping[str, object], expected: str
) -> None:
    api = _api()
    assessment = api.EvaluationAxes(**axes)
    assert _enum_value(api.evaluate_disposition(assessment)) == expected


def test_disposition_cross_product_and_field_order_are_deterministic() -> None:
    api = _api()
    axis_values = {
        "liveness": ("live", "inconclusive"),
        "support": ("supported", "unsupported", "inconclusive"),
        "policy": ("allowed", "blocked", "unresolved"),
        "taxonomy": ("complete", "incomplete"),
    }
    field_names = tuple(axis_values)

    for values in product(*(axis_values[name] for name in field_names)):
        payload = dict(zip(field_names, values, strict=True))
        if payload["policy"] == "blocked":
            expected = "blocked"
        elif (
            payload["liveness"] == "inconclusive"
            or payload["support"] == "inconclusive"
            or payload["policy"] == "unresolved"
            or payload["taxonomy"] == "incomplete"
        ):
            expected = "inconclusive"
        elif payload["support"] == "unsupported":
            expected = "unsupported"
        else:
            expected = "promotable"

        observed: set[object] = set()
        for field_order in permutations(field_names):
            ordered = {name: payload[name] for name in field_order}
            observed.add(
                _enum_value(api.evaluate_disposition(api.EvaluationAxes(**ordered)))
            )
        assert observed == {expected}


# T114: all eight required taxonomy fields close promotion; sourceYear is optional.
REQUIRED_TAXONOMY = {
    "providerType": "job_board",
    "coverageMode": "portfolio_jobs",
    "accessType": "public_json_api",
    "licenseStatus": "official_public",
    "refreshCadence": "daily",
    "sourceCategory": "employer",
    "sourceAttribution": "Example public careers site.",
    "inclusionReason": "Verified generic public route.",
}


def test_taxonomy_requires_exactly_all_eight_fields_but_not_source_year() -> None:
    api = _api()

    complete = api.validate_taxonomy(REQUIRED_TAXONOMY)
    with_optional = api.validate_taxonomy({**REQUIRED_TAXONOMY, "sourceYear": 2026})

    assert complete.complete is True
    assert complete.missing_fields == ()
    assert with_optional.complete is True
    assert with_optional.source_year == 2026


@pytest.mark.parametrize("missing", tuple(REQUIRED_TAXONOMY))
def test_each_required_taxonomy_field_independently_blocks_completion(
    missing: str,
) -> None:
    api = _api()
    taxonomy = dict(REQUIRED_TAXONOMY)
    taxonomy.pop(missing)

    result = api.validate_taxonomy(taxonomy)

    assert result.complete is False
    assert result.missing_fields == (missing,)


# T115/T116: every positive policy axis is required; observations never grant.
POLICY_AXIS_NAMES = (
    "access",
    "license",
    "redistribution",
    "sync",
    "publication",
)


def _allowed_policy(api: _ContractApi, **updates: str) -> Any:
    values = {name: "allowed" for name in POLICY_AXIS_NAMES}
    values.update(updates)
    return api.PolicyAxisSet(**values)


@pytest.mark.parametrize("axis", POLICY_AXIS_NAMES)
@pytest.mark.parametrize("state", ("blocked", "unresolved"))
def test_every_policy_axis_must_close_positively(axis: str, state: str) -> None:
    api = _api()
    result = api.evaluate_policy(_allowed_policy(api, **{axis: state}))
    expected = "blocked" if state == "blocked" else "unresolved"
    assert _enum_value(result) == expected


@pytest.mark.parametrize(
    "observation",
    ("http_200", "robots_allowed", "upstream_official", "model_confident"),
)
def test_untrusted_positive_observations_and_deny_nonmatch_never_grant(
    observation: str,
) -> None:
    api = _api()
    unresolved = _allowed_policy(api, publication="unresolved")

    result = api.evaluate_policy(
        unresolved,
        deny_overlay_matches=(),
        untrusted_observations=(observation,),
    )

    assert _enum_value(result) == "unresolved"


def test_deny_overlay_dominates_otherwise_positive_policy() -> None:
    api = _api()
    result = api.evaluate_policy(
        _allowed_policy(api),
        deny_overlay_matches=("blocked-provider",),
        untrusted_observations=("http_200", "robots_allowed"),
    )
    assert _enum_value(result) == "blocked"


# T117/T118: transient observations are inconclusive, never permanent absence.
@pytest.mark.parametrize(
    "response_class",
    ("timeout", "dns_error", "tls_error", "rate_limited", "http_5xx"),
)
def test_transient_failure_is_inconclusive_liveness(
    response_class: str,
) -> None:
    api = _api()
    evidence = api.LivenessEvidence(
        response_class=response_class,
        expected_structure=False,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert _enum_value(api.classify_liveness(evidence)) == "inconclusive"


def test_only_expected_structure_is_live_evidence() -> None:
    api = _api()
    live = api.LivenessEvidence(
        response_class="expected_payload",
        expected_structure=True,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    unrelated = api.LivenessEvidence(
        response_class="http_200_unrelated",
        expected_structure=False,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert _enum_value(api.classify_liveness(live)) == "live"
    assert _enum_value(api.classify_liveness(unrelated)) == "inconclusive"


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({}, "supported"),
        ({"built_in_route": False}, "unsupported"),
        ({"access_required": True}, "unsupported"),
        ({"route_metadata_complete": False}, "inconclusive"),
        ({"job_fetch_validated": False}, "inconclusive"),
        ({"transient_failure": True}, "inconclusive"),
    ],
)
def test_support_requires_a_complete_builtin_executable_route(
    updates: Mapping[str, object], expected: str
) -> None:
    api = _api()
    values: dict[str, object] = {
        "provider_id": "greenhouse",
        "built_in_route": True,
        "route_metadata_complete": True,
        "job_fetch_validated": True,
        "access_required": False,
        "transient_failure": False,
    }
    values.update(updates)
    evidence = api.SupportEvidence(**values)
    assert _enum_value(api.classify_support(evidence)) == expected


# T119: exact source accounting includes cancellation, unstarted, and run state.
SOURCE_DISPOSITIONS = (
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
)


def _source_outcome(api: _ContractApi, source_id: str, disposition: str) -> Any:
    return api.SourceOutcome(
        source_id=source_id,
        disposition=disposition,
        started=disposition != "unstarted",
        authoritative=disposition in {"succeeded", "fresh_skipped"},
        freshness_context_digest=(
            _sha256("freshness") if disposition == "fresh_skipped" else None
        ),
    )


def test_source_terminal_classes_conserve_the_pinned_denominator() -> None:
    api = _api()
    planned = tuple(f"source-{index}" for index in range(len(SOURCE_DISPOSITIONS)))
    outcomes = tuple(
        _source_outcome(api, source_id, disposition)
        for source_id, disposition in zip(planned, SOURCE_DISPOSITIONS, strict=True)
    )

    result = api.build_source_accounting(
        planned_source_ids=planned,
        outcomes=outcomes,
        run_state="aborted",
        freshness_context_digest=_sha256("freshness"),
    )

    assert result.planned == len(SOURCE_DISPOSITIONS)
    assert sum(getattr(result, name) for name in SOURCE_DISPOSITIONS) == (
        result.planned
    )
    assert result.cancelled == 1
    assert result.unstarted == 1
    assert result.complete is False


def test_cancelled_was_started_and_unstarted_was_never_launched() -> None:
    api = _api()
    with pytest.raises(ValueError, match="unstarted|started"):
        api.SourceOutcome(
            source_id="not-started",
            disposition="unstarted",
            started=True,
        )
    with pytest.raises(ValueError, match="cancelled|started"):
        api.SourceOutcome(
            source_id="cancelled",
            disposition="cancelled",
            started=False,
        )


def test_aborted_is_run_level_only_and_terminal_runs_close_every_source() -> None:
    api = _api()
    with pytest.raises(ValueError, match="aborted|disposition"):
        api.SourceOutcome(
            source_id="source-a",
            disposition="aborted",
            started=True,
        )

    with pytest.raises(ValueError, match="unaccounted|terminal"):
        api.build_source_accounting(
            planned_source_ids=("source-a", "source-b"),
            outcomes=(_source_outcome(api, "source-a", "cancelled"),),
            run_state="aborted",
            freshness_context_digest=_sha256("freshness"),
        )


def test_terminal_accounting_diagnostic_does_not_echo_untrusted_identifier() -> None:
    api = _api()
    marker = "synthetic-secret-source-id"

    with pytest.raises(ValueError) as exc_info:
        api.build_source_accounting(
            planned_source_ids=("source-a", marker),
            outcomes=(_source_outcome(api, "source-a", "cancelled"),),
            run_state="aborted",
            freshness_context_digest=_sha256("freshness"),
        )

    assert marker not in str(exc_info.value)


def test_hard_process_death_remains_nonterminal_until_recovery_accounts_all() -> None:
    api = _api()
    result = api.build_source_accounting(
        planned_source_ids=("source-a", "source-b"),
        outcomes=(_source_outcome(api, "source-a", "cancelled"),),
        run_state="nonterminal",
        freshness_context_digest=_sha256("freshness"),
    )

    assert result.terminal is False
    assert result.complete is False
    assert result.unaccounted_ids == ("source-b",)


# T120: exact pre-dedup route accounting and representative authority.
ROUTE_DISPOSITIONS = (
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "deferred",
    "duplicate_skipped",
    "missing_metadata",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
)


def _route_outcome(
    api: _ContractApi,
    route_id: str,
    disposition: str,
    *,
    representative_id: str | None = None,
    authoritative: bool | None = None,
    freshness_context_digest: str | None = None,
) -> Any:
    if authoritative is None:
        authoritative = disposition in {"succeeded", "fresh_skipped"}
    return api.RouteOutcome(
        route_id=route_id,
        disposition=disposition,
        representative_id=representative_id,
        started=disposition != "unstarted",
        authoritative=authoritative,
        freshness_context_digest=freshness_context_digest,
    )


def test_route_terminal_classes_conserve_the_prededup_denominator() -> None:
    api = _api()
    context = _sha256("route-freshness-context")
    planned = tuple(f"route-{index}" for index in range(len(ROUTE_DISPOSITIONS)))
    outcomes = []
    for route_id, disposition in zip(planned, ROUTE_DISPOSITIONS, strict=True):
        outcomes.append(
            _route_outcome(
                api,
                route_id,
                disposition,
                representative_id=(
                    planned[0] if disposition == "duplicate_skipped" else None
                ),
                freshness_context_digest=(
                    context if disposition == "fresh_skipped" else None
                ),
            )
        )

    result = api.build_route_accounting(
        planned_route_ids=planned,
        outcomes=tuple(outcomes),
        run_state="aborted",
        freshness_context_digest=context,
    )

    assert result.planned == len(ROUTE_DISPOSITIONS)
    assert sum(getattr(result, name) for name in ROUTE_DISPOSITIONS) == result.planned
    assert result.duplicate_skipped == 1
    assert result.complete is False


def test_duplicate_route_requires_one_authoritative_nonduplicate_representative() -> (
    None
):
    api = _api()
    duplicate = _route_outcome(
        api,
        "duplicate",
        "duplicate_skipped",
        representative_id="missing",
        authoritative=False,
    )
    with pytest.raises(ValueError, match="representative|missing"):
        api.build_route_accounting(
            planned_route_ids=("duplicate",),
            outcomes=(duplicate,),
            run_state="succeeded",
            freshness_context_digest=_sha256("context"),
        )

    first = _route_outcome(
        api,
        "first",
        "duplicate_skipped",
        representative_id="second",
        authoritative=False,
    )
    second = _route_outcome(
        api,
        "second",
        "duplicate_skipped",
        representative_id="first",
        authoritative=False,
    )
    with pytest.raises(ValueError, match="representative|skipped|authoritative"):
        api.build_route_accounting(
            planned_route_ids=("first", "second"),
            outcomes=(first, second),
            run_state="succeeded",
            freshness_context_digest=_sha256("context"),
        )


def test_fresh_representative_requires_authority_and_exact_bound_context() -> None:
    api = _api()
    context = _sha256("expected-context")
    fresh = _route_outcome(
        api,
        "representative",
        "fresh_skipped",
        authoritative=True,
        freshness_context_digest=_sha256("wrong-context"),
    )
    duplicate = _route_outcome(
        api,
        "duplicate",
        "duplicate_skipped",
        representative_id="representative",
        authoritative=False,
    )
    with pytest.raises(ValueError, match="freshness|context|representative"):
        api.build_route_accounting(
            planned_route_ids=("representative", "duplicate"),
            outcomes=(fresh, duplicate),
            run_state="succeeded",
            freshness_context_digest=context,
        )


def test_non_authoritative_route_success_cannot_be_complete() -> None:
    api = _api()
    outcome = _route_outcome(
        api,
        "route-a",
        "succeeded",
        authoritative=False,
    )
    result = api.build_route_accounting(
        planned_route_ids=("route-a",),
        outcomes=(outcome,),
        run_state="succeeded",
        freshness_context_digest=_sha256("context"),
    )
    assert result.succeeded == 1
    assert result.authoritative_succeeded == 0
    assert result.complete is False


# T138: review authority is separate, exact-bound, and mode-restricted.
@pytest.mark.parametrize(
    "forbidden",
    ("approved", "reviewer", "signature", "reviewReceipt", "revocation"),
)
def test_candidate_manifest_cannot_supply_review_authority(forbidden: str) -> None:
    api = _api()
    payload = {
        "schemaVersion": 1,
        "candidateId": "candidate-1",
        forbidden: "attacker-controlled",
    }
    with pytest.raises(api.CandidateAuthorityError, match="authority field"):
        api.validate_candidate_manifest_authority(payload)


def test_candidate_manifest_cannot_hide_nested_review_authority() -> None:
    api = _api()

    with pytest.raises(api.CandidateAuthorityError, match="authority field"):
        api.validate_candidate_manifest_authority(
            {"candidate": {"evidence": [{"reviewer": "attacker-controlled"}]}}
        )


@pytest.mark.parametrize(
    "forbidden",
    ("review-receipt", "review receipt", "re-viewer", "REVIEW_RECEIPT"),
)
def test_candidate_manifest_authority_rejects_separator_and_case_bypasses(
    forbidden: str,
) -> None:
    api = _api()

    with pytest.raises(api.CandidateAuthorityError) as exc_info:
        api.validate_candidate_manifest_authority(
            {"candidate": [{forbidden: "synthetic-secret-value"}]}
        )

    assert forbidden not in str(exc_info.value)
    assert "synthetic-secret-value" not in str(exc_info.value)


def test_promotion_decision_has_one_canonical_model_and_validator_contract() -> None:
    api = _api()
    intent = _intent()
    payload = _decision_payload(api, intent)
    decision = api.DiscoveryPromotionPolicyDecision.model_validate_json(
        canonical_json_bytes(payload),
        strict=True,
        by_alias=True,
        by_name=False,
    )

    assert api.validate_promotion_decision(
        payload,
        expected_intent=intent,
        invocation_mode="maintainer",
    ) == decision.model_dump(mode="json", by_alias=True)
    assert decision.required_operations == (
        "access",
        "license",
        "publication",
        "redistribution",
        "sync",
    )


def test_promotion_intent_digest_is_non_self_referential_and_binds_operations() -> None:
    api = _api()
    intent = _intent()
    semantic_payload = intent.model_dump(mode="json", by_alias=True)

    assert "promotionIntentDigest" not in semantic_payload
    assert (
        api.compute_promotion_intent_digest(intent)
        == hashlib.sha256(canonical_json_bytes(semantic_payload)).hexdigest()
    )
    assert api.compute_promotion_intent_digest(
        _intent(required_operations=("access", "license"))
    ) != api.compute_promotion_intent_digest(intent)


def test_incompatible_legacy_decision_shapes_fail_closed() -> None:
    api = _api()
    intent = _intent()
    canonical = _decision_payload(api, intent)

    old_validator_shape = dict(canonical)
    old_validator_shape.pop("schemaVersion")
    old_validator_shape.pop("requiredOperations")
    with pytest.raises(api.PromotionDecisionError):
        api.validate_promotion_decision(
            old_validator_shape,
            expected_intent=intent,
            invocation_mode="maintainer",
        )

    old_model_shape = dict(canonical)
    old_model_shape.pop("headSha")
    old_model_shape.pop("catalogAfterDigest")
    old_model_shape.pop("promotionDigest")
    with pytest.raises(api.PromotionDecisionError):
        api.validate_promotion_decision(
            old_model_shape,
            expected_intent=intent,
            invocation_mode="maintainer",
        )


def test_promotion_decision_validator_rejects_internal_field_spellings() -> None:
    api = _api()
    intent = _intent()
    canonical = _decision_payload(api, intent)
    decision = api.DiscoveryPromotionPolicyDecision.model_validate_json(
        canonical_json_bytes(canonical),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    snake_case = decision.model_dump(mode="json", by_alias=False)

    with pytest.raises(api.PromotionDecisionError):
        api.validate_promotion_decision(
            snake_case,
            expected_intent=intent,
            invocation_mode="maintainer",
        )


@pytest.mark.parametrize(
    "invocation_mode", ("scout", "verify", "preview", "ci", "scheduled")
)
def test_nonmaintainer_modes_cannot_create_a_positive_decision(
    invocation_mode: str,
) -> None:
    api = _api()
    intent = _intent()
    with pytest.raises(api.PromotionDecisionError, match="maintainer invocation"):
        api.validate_promotion_decision(
            _decision_payload(api, intent),
            expected_intent=intent,
            invocation_mode=invocation_mode,
        )


def test_nonmaintainer_mode_diagnostic_does_not_echo_untrusted_mode() -> None:
    api = _api()
    marker = "synthetic-secret-mode"

    with pytest.raises(api.PromotionDecisionError) as exc_info:
        api.validate_promotion_decision(
            _decision_payload(api, _intent()),
            expected_intent=_intent(),
            invocation_mode=marker,
        )

    assert marker not in str(exc_info.value)


@pytest.mark.parametrize(
    "field",
    (
        "headSha",
        "manifestDigest",
        "selectionDigest",
        "resourcesDigest",
        "profileDigest",
        "policyInputsDigest",
        "catalogBeforeDigest",
        "catalogAfterDigest",
        "promotionDigest",
        "requiredOperations",
    ),
)
def test_missing_or_copied_review_decision_provenance_fails_closed(
    field: str,
) -> None:
    api = _api()
    intent = _intent()
    missing = _decision_payload(api, intent)
    missing.pop(field)
    with pytest.raises(api.PromotionDecisionError, match=field):
        api.validate_promotion_decision(
            missing,
            expected_intent=intent,
            invocation_mode="maintainer",
        )

    copied = _decision_payload(api, intent)
    copied[field] = (
        ["access"]
        if field == "requiredOperations"
        else "b" * 40
        if field == "headSha"
        else _sha256(f"copied-{field}")
    )
    with pytest.raises(api.PromotionDecisionError, match=field):
        api.validate_promotion_decision(
            copied,
            expected_intent=intent,
            invocation_mode="maintainer",
        )


# T141: ledger replay keys, chain closure, and history lookup are exact.
def _append(
    api: _ContractApi,
    current: tuple[Any, ...],
    *,
    intent: Any,
    decision_id: str,
    state: str,
    history: tuple[Any, ...] = (),
) -> tuple[Any, ...]:
    event = api.append_ledger_event(
        current_events=current,
        reachable_history=history,
        decision_id=decision_id,
        intent=intent,
        state=state,
    )
    return (*current, event)


def test_ledger_hash_chain_and_reserved_applied_revoked_order_close() -> None:
    api = _api()
    intent = _intent()
    events = _append(api, (), intent=intent, decision_id="decision-1", state="reserved")
    events = _append(
        api,
        events,
        intent=intent,
        decision_id="decision-1",
        state="applied",
    )
    events = _append(
        api,
        events,
        intent=intent,
        decision_id="decision-1",
        state="revoked",
    )

    api.validate_ledger_chain(events, reachable_history=())
    assert events[0].predecessor_digest is None
    assert events[1].predecessor_digest == events[0].event_digest
    assert events[2].predecessor_digest == events[1].event_digest
    assert [_enum_value(event.state) for event in events] == [
        "reserved",
        "applied",
        "revoked",
    ]


def test_ledger_rejects_reorder_deletion_and_mutation() -> None:
    api = _api()
    intent = _intent()
    events = _append(api, (), intent=intent, decision_id="decision-1", state="reserved")
    events = _append(
        api,
        events,
        intent=intent,
        decision_id="decision-1",
        state="applied",
    )

    with pytest.raises(api.PromotionLedgerError):
        api.validate_ledger_chain(tuple(reversed(events)), reachable_history=())
    with pytest.raises(api.PromotionLedgerError):
        api.validate_ledger_chain(events[1:], reachable_history=())
    mutated = events[1].model_copy(update={"catalog_after_digest": _sha256("mutated")})
    with pytest.raises(api.PromotionLedgerError):
        api.validate_ledger_chain((events[0], mutated), reachable_history=())


def test_ledger_rejects_component_mutation_even_with_recomputed_event_digest() -> None:
    api = _api()
    intent = _intent()
    events = _append(api, (), intent=intent, decision_id="decision-1", state="reserved")
    events = _append(
        api,
        events,
        intent=intent,
        decision_id="decision-1",
        state="applied",
    )
    mutated = events[1].model_copy(update={"catalog_after_digest": _sha256("mutated")})
    event_payload = mutated.model_dump(mode="json", by_alias=True)
    event_payload.pop("eventDigest")
    forged_digest = hashlib.sha256(canonical_json_bytes(event_payload)).hexdigest()
    forged = mutated.model_copy(update={"event_digest": forged_digest})

    with pytest.raises(api.PromotionLedgerError, match="intent|component"):
        api.validate_ledger_chain((events[0], forged), reachable_history=())


def test_replay_uses_decision_and_composite_intent_not_component_blacklist() -> None:
    api = _api()
    first = _intent()
    first_events = _append(
        api, (), intent=first, decision_id="decision-1", state="reserved"
    )
    first_events = _append(
        api,
        first_events,
        intent=first,
        decision_id="decision-1",
        state="applied",
    )

    with pytest.raises(api.PromotionLedgerError, match="decision|replay"):
        _append(
            api,
            (),
            intent=_intent(selection_digest=_sha256("selection-2")),
            decision_id="decision-1",
            state="reserved",
            history=first_events,
        )
    with pytest.raises(api.PromotionLedgerError, match="intent|replay"):
        _append(
            api,
            (),
            intent=first,
            decision_id="decision-2",
            state="reserved",
            history=first_events,
        )

    distinct = _intent(
        selection_digest=_sha256("selection-2"),
        promotion_digest=_sha256("promotion-2"),
    )
    second = _append(
        api,
        (),
        intent=distinct,
        decision_id="decision-2",
        state="reserved",
        history=first_events,
    )
    assert second[0].policy_inputs_digest == first.policy_inputs_digest
    assert second[0].catalog_before_digest == first.catalog_before_digest


@pytest.mark.parametrize(
    "intent_updates",
    (
        {},
        {
            "selection_digest": _sha256("selection-2"),
            "promotion_digest": _sha256("promotion-2"),
        },
    ),
    ids=("same-intent", "different-intent"),
)
def test_nonterminal_reservation_blocks_same_head_catalog_tuple(
    intent_updates: Mapping[str, object],
) -> None:
    api = _api()
    first = _intent()
    reserved = _append(
        api, (), intent=first, decision_id="decision-1", state="reserved"
    )
    contender = _intent(**intent_updates)

    with pytest.raises(api.PromotionLedgerError, match="reservation|HEAD|catalog"):
        _append(
            api,
            reserved,
            intent=contender,
            decision_id="decision-2",
            state="reserved",
        )


# T142: unit seams make crash recovery deterministic; process kills come later.
def _observed_after(journal: Any) -> dict[str, dict[str, object]]:
    return {
        entry.path: {
            "exists": entry.after.exists,
            "mode": entry.after.mode,
            "sha256": entry.after.sha256,
        }
        for entry in journal.entries
    }


@pytest.mark.parametrize("phase", ("prepared", "applying", "finalizing"))
def test_recovery_finalizes_only_the_exact_complete_after_tree(phase: str) -> None:
    api = _api()
    journal = _journal().model_copy(update={"phase": phase})
    observed = _observed_after(journal)

    assert _enum_value(api.choose_recovery_action(journal, observed)) == "finalize"

    first_path = journal.entries[0].path
    observed[first_path] = {**observed[first_path], "sha256": _sha256("mixed")}
    assert _enum_value(api.choose_recovery_action(journal, observed)) == (
        "restore_and_revoke"
    )


def test_journal_phase_transitions_cannot_skip_or_move_backward() -> None:
    api = _api()
    prepared = _journal()
    applying = api.transition_journal(prepared, "applying")
    finalizing = api.transition_journal(applying, "finalizing")

    assert _enum_value(applying.phase) == "applying"
    assert _enum_value(finalizing.phase) == "finalizing"
    with pytest.raises(ValueError, match="transition|phase"):
        api.transition_journal(prepared, "finalizing")
    with pytest.raises(ValueError, match="transition|phase"):
        api.transition_journal(finalizing, "applying")


@pytest.mark.parametrize("unsafe_path", ("a/..", "./x", "a//b", "a/%2e%2e/b"))
def test_journal_rejects_ambiguous_or_escaping_owned_paths(unsafe_path: str) -> None:
    api = _api()
    payload = _journal().model_dump()
    payload["entries"][0]["path"] = unsafe_path

    with pytest.raises(ValueError, match="path|relative"):
        api.ApplyJournal(**payload)


def test_applied_commit_requires_exact_journal_path_closure_and_reservation_parent() -> (
    None
):
    api = _api()
    journal = _journal()
    exact_paths = frozenset(entry.path for entry in journal.entries)

    api.validate_applied_commit(
        journal,
        changed_paths=exact_paths,
        reservation_parent_present=True,
    )
    with pytest.raises(ValueError, match="path|closure"):
        api.validate_applied_commit(
            journal,
            changed_paths=exact_paths - {journal.entries[0].path},
            reservation_parent_present=True,
        )
    with pytest.raises(ValueError, match="reservation|parent"):
        api.validate_applied_commit(
            journal,
            changed_paths=exact_paths,
            reservation_parent_present=False,
        )
