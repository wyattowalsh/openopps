"""V541-V547 evaluation join, conservation, quarantine bundle, and isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openopps.discovery.bundle import BundleVerificationPolicy, verify_bundle
from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.evaluation import (
    EVALUATION_BUNDLE_PROFILE,
    FabricatedEvaluationError,
    evaluate_disposition,
    evaluate_occurrences,
    reject_fabricated_evaluation_payload,
    write_evaluation_bundle,
)
from openopps.discovery.identity import RawOccurrenceInput, normalize_candidate_identity
from openopps.discovery.liveness import (
    InjectedTransportResult,
    PERMANENT_ABSENCE_ENABLED,
)
from openopps.discovery.models import (
    EvaluationAxes,
    EvaluationDisposition,
    PolicyAxisSet,
)
from openopps.discovery.policy import bind_v7_policy_digests


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
TAXONOMY = {
    "providerType": "job_board",
    "coverageMode": "portfolio_jobs",
    "accessType": "public_json_api",
    "licenseStatus": "official_public",
    "refreshCadence": "daily",
    "sourceCategory": "employer",
    "sourceAttribution": "Example public careers site.",
    "inclusionReason": "Verified generic public route.",
}
ALLOWED = PolicyAxisSet(
    access="allowed",
    license="allowed",
    redistribution="allowed",
    sync="allowed",
    publication="allowed",
)
GREENHOUSE_JOBS = b'{"jobs":[{"id":1,"title":"Engineer","absolute_url":"https://boards.greenhouse.io/acme/jobs/1"}]}'
LISTING = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
DENY_EVIDENCE = (
    b'{"decisions":[{"id":"consider-terms","axes":{"access":"permission_required",'
    b'"license":"unknown","publication":"blocked","redistribution":"permission_required",'
    b'"sync":"blocked"},"scope":{"providerIds":["consider"]}}]}'
)


def _v7(*, evidence: bytes = b'{"decisions":[]}'):
    return bind_v7_policy_digests(
        policy_code=b"policy-code\n",
        policy_schema=b"{}\n",
        policy_evidence=evidence,
        policy_corpus=b'{"sourceKeys":[]}\n',
        public_selector=None,
    )


def _raw(**updates: object) -> RawOccurrenceInput:
    values: dict[str, object] = {
        "occurrence_id": "occ-acme",
        "channel": "targeted_ats",
        "key": "acme",
        "url": LISTING,
        "provider_id": "greenhouse",
        "owner": "targeted-ats",
        "provenance_ids": ("resource-acme",),
        "provider_token": "acme",
        "candidate_kind": "board_route",
        "adapter_id": "greenhouse",
    }
    values.update(updates)
    return RawOccurrenceInput(**values)


def _obs(locator: str = LISTING, **updates: object) -> CapturedObservation:
    values: dict[str, object] = {
        "locator": locator,
        "transport_state": "response",
        "status_code": 200,
        "body": GREENHOUSE_JOBS,
        "media_type": "application/json",
    }
    values.update(updates)
    return CapturedObservation(**values)


def test_evaluate_disposition_uses_models_evaluation_disposition() -> None:
    axes = EvaluationAxes(
        liveness="live",
        support="supported",
        policy="allowed",
        taxonomy="complete",
    )
    result = evaluate_disposition(axes)
    assert isinstance(result, EvaluationDisposition)
    assert result is EvaluationDisposition.PROMOTABLE


def test_join_promotable_requires_live_supported_allowed_complete() -> None:
    result = evaluate_occurrences(
        (_raw(),),
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={LISTING: _obs()},
        positive_policy_axes=ALLOWED,
    )
    evaluation = result.candidates[0].evaluation
    assert evaluation.disposition == "promotable"
    assert evaluation.eligible_for_review is True
    assert evaluation.axes.liveness == "live"
    assert evaluation.axes.support == "supported"
    assert evaluation.axes.policy == "allowed"
    assert evaluation.axes.taxonomy == "complete"
    assert result.accounting.promotable == 1
    assert result.candidates[0].liveness.receipt_id is not None
    assert result.candidates[0].liveness.permanent_absence is False


def test_policy_block_dominates_otherwise_positive_axes() -> None:
    raw = _raw(
        key="consider-board",
        provider_id="consider",
        url="https://jobs.consider.test/board",
    )
    result = evaluate_occurrences(
        (raw,),
        approved_catalog=(),
        taxonomies={"consider-board": TAXONOMY},
        v7_binding=_v7(evidence=DENY_EVIDENCE),
        evidence_bytes=DENY_EVIDENCE,
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={
            "https://jobs.consider.test/board": _obs(
                locator="https://jobs.consider.test/board",
                body=b'{"jobs":[{"id":1,"title":"Role"}]}',
            )
        },
        positive_policy_axes=ALLOWED,
    )
    assert result.candidates[0].evaluation.disposition == "blocked"
    assert result.accounting.blocked == 1


def test_incomplete_unresolved_dominates_unsupported() -> None:
    result = evaluate_occurrences(
        (_raw(),),
        approved_catalog=(),
        taxonomies={},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={LISTING: _obs()},
        positive_policy_axes=ALLOWED,
    )
    assert result.candidates[0].evaluation.disposition == "inconclusive"
    assert result.accounting.inconclusive == 1


def test_unsupported_when_rights_closed_without_executable_route() -> None:
    raw = _raw(
        url="https://careers.example.test/acme",
        provider_id="unknown",
        provider_token=None,
        candidate_kind="source",
        adapter_id=None,
    )
    result = evaluate_occurrences(
        (raw,),
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={
            "https://careers.example.test/acme": _obs(
                locator="https://careers.example.test/acme",
                body=b'{"jobs":[{"id":1,"title":"Role"}]}',
            )
        },
        positive_policy_axes=ALLOWED,
    )
    assert result.candidates[0].evaluation.disposition == "unsupported"


def test_scout_conservation_holds_across_terminal_dispositions() -> None:
    approved = normalize_candidate_identity(
        key="kept",
        url="https://boards-api.greenhouse.io/v1/boards/kept/jobs",
        provider_id="greenhouse",
        provider_token="kept",
        owner="official",
        candidate_kind="board_route",
    )
    result = evaluate_occurrences(
        (
            _raw(),
            _raw(occurrence_id="occ-dup", provenance_ids=("resource-dup",)),
            _raw(
                occurrence_id="occ-kept",
                key="kept",
                url="https://boards-api.greenhouse.io/v1/boards/kept/jobs",
                provider_token="kept",
                provenance_ids=("resource-kept",),
            ),
            _raw(
                occurrence_id="occ-bad",
                key="local",
                url="http://127.0.0.1/jobs",
                provenance_ids=("resource-bad",),
            ),
        ),
        approved_catalog=(approved,),
        taxonomies={"acme": TAXONOMY, "kept": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={
            LISTING: _obs(),
            "https://boards-api.greenhouse.io/v1/boards/kept/jobs": _obs(
                locator="https://boards-api.greenhouse.io/v1/boards/kept/jobs"
            ),
        },
        positive_policy_axes=ALLOWED,
    )
    accounting = result.accounting
    assert accounting.observed_candidate_occurrences == (
        accounting.invalid_occurrences + accounting.normalized_occurrences
    )
    assert accounting.normalized_occurrences == (
        accounting.duplicate_occurrences + accounting.unique_candidates
    )
    assert accounting.unique_candidates == (
        accounting.already_approved + accounting.quarantined_candidates
    )
    assert accounting.quarantined_candidates == (
        accounting.promotable
        + accounting.blocked
        + accounting.unsupported
        + accounting.inconclusive
    )


def test_identical_inputs_reproduce_identical_join_bytes() -> None:
    kwargs = dict(
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY, "beta": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={
            LISTING: _obs(),
            "https://boards-api.greenhouse.io/v1/boards/beta/jobs": _obs(
                locator="https://boards-api.greenhouse.io/v1/boards/beta/jobs"
            ),
        },
        positive_policy_axes=ALLOWED,
    )
    first = evaluate_occurrences(
        (
            _raw(),
            _raw(
                occurrence_id="occ-beta",
                key="beta",
                url="https://boards-api.greenhouse.io/v1/boards/beta/jobs",
                provider_token="beta",
                provenance_ids=("resource-beta",),
            ),
        ),
        **kwargs,
    )
    second = evaluate_occurrences(
        (
            _raw(
                occurrence_id="occ-beta",
                key="beta",
                url="https://boards-api.greenhouse.io/v1/boards/beta/jobs",
                provider_token="beta",
                provenance_ids=("resource-beta",),
            ),
            _raw(),
        ),
        **kwargs,
    )
    assert first.bytes == second.bytes


@pytest.mark.parametrize(
    ("kind", "observation_updates", "transport_error"),
    [
        ("success", {"status_code": 200, "body": GREENHOUSE_JOBS}, None),
        ("timeout", {}, "timeout"),
        (
            "failure",
            {
                "status_code": 200,
                "body": b"<html>careers</html>",
                "media_type": "text/html",
            },
            None,
        ),
        ("cancellation", {}, "cancelled"),
    ],
)
def test_outcome_classes_are_byte_identical_on_replay(
    kind: str,
    observation_updates: dict[str, object],
    transport_error: str | None,
) -> None:
    class _Client:
        def get_uncached(self, url: str) -> InjectedTransportResult:
            del url
            return InjectedTransportResult(
                status_code=None,
                body=None,
                media_type=None,
                cached=False,
                transport_error=transport_error,
                redirect_loop=False,
                elapsed_ms=3,
                request_id=f"{kind}-receipt",
            )

    observations = None if transport_error else {LISTING: _obs(**observation_updates)}
    client = _Client() if transport_error else None
    kwargs = dict(
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations=observations,
        transport_client=client,
        positive_policy_axes=ALLOWED,
    )
    first = evaluate_occurrences((_raw(),), **kwargs)
    second = evaluate_occurrences((_raw(),), **kwargs)
    assert first.bytes == second.bytes
    if kind == "success":
        assert first.candidates[0].evaluation.disposition == "promotable"
    else:
        assert first.candidates[0].evaluation.disposition == "inconclusive"
    assert PERMANENT_ABSENCE_ENABLED is False


def test_write_evaluation_bundle_is_exact_and_non_mutating(tmp_path: Path) -> None:
    catalog = ROOT_PROVIDERS = Path(__file__).resolve().parents[4] / (
        "src/openopps/providers/sources/data/portfolio_source_catalog.json"
    )
    before = catalog.read_bytes()
    result = evaluate_occurrences(
        (_raw(),),
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={LISTING: _obs()},
        positive_policy_axes=ALLOWED,
    )
    published = write_evaluation_bundle(
        tmp_path / "quarantine",
        result,
        v7_binding=_v7(),
        observed_at=NOW,
        configuration_sha256="c" * 64,
        execution_id="eval-1",
        now=NOW,
    )
    policy = BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=48),
        now=NOW,
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({EVALUATION_BUNDLE_PROFILE}),
        supported_schema_versions=frozenset({"openopps.discovery.bundle.v1"}),
        required_member_roles=frozenset({"evidence"}),
        supported_member_roles=frozenset({"evidence"}),
        canonical_json_roles=frozenset(),
    )
    verified = verify_bundle(published, policy=policy)
    assert verified.profile_id == EVALUATION_BUNDLE_PROFILE[0]
    assert "evaluations/join.json" in verified.member_paths
    assert catalog.read_bytes() == before
    replayed = write_evaluation_bundle(
        tmp_path / "quarantine-replay",
        result,
        v7_binding=_v7(),
        observed_at=NOW,
        configuration_sha256="c" * 64,
        execution_id="eval-1",
        now=NOW,
    )
    assert (replayed / "evaluations/join.json").read_bytes() == (
        published / "evaluations/join.json"
    ).read_bytes()
    del ROOT_PROVIDERS


def test_partial_mixed_outcomes_conserve_and_replay_identically() -> None:
    timeout_listing = "https://boards-api.greenhouse.io/v1/boards/beta/jobs"

    class _Client:
        def get_uncached(self, url: str) -> InjectedTransportResult:
            if "beta" in url:
                return InjectedTransportResult(
                    status_code=None,
                    body=None,
                    media_type=None,
                    cached=False,
                    transport_error="timeout",
                    redirect_loop=False,
                    elapsed_ms=9,
                    request_id="timeout-beta",
                )
            return InjectedTransportResult(
                status_code=200,
                body=GREENHOUSE_JOBS,
                media_type="application/json",
                cached=False,
                transport_error=None,
                redirect_loop=False,
                elapsed_ms=4,
                request_id="ok-acme",
            )

    kwargs = dict(
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY, "beta": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        transport_client=_Client(),
        positive_policy_axes=ALLOWED,
    )
    first = evaluate_occurrences(
        (
            _raw(),
            _raw(
                occurrence_id="occ-beta",
                key="beta",
                url=timeout_listing,
                provider_token="beta",
                provenance_ids=("resource-beta",),
            ),
        ),
        **kwargs,
    )
    second = evaluate_occurrences(
        (
            _raw(
                occurrence_id="occ-beta",
                key="beta",
                url=timeout_listing,
                provider_token="beta",
                provenance_ids=("resource-beta",),
            ),
            _raw(),
        ),
        **kwargs,
    )
    assert first.bytes == second.bytes
    dispositions = sorted(item.evaluation.disposition for item in first.candidates)
    assert dispositions == ["inconclusive", "promotable"]
    assert first.accounting.unique_candidates == 2


def test_fabricated_agent_authority_fields_are_rejected() -> None:
    with pytest.raises(FabricatedEvaluationError):
        reject_fabricated_evaluation_payload(
            {
                "candidateLocator": "https://jobs.example.test",
                "disposition": "promotable",
            }
        )
    with pytest.raises(FabricatedEvaluationError):
        evaluate_occurrences(
            (_raw(),),
            approved_catalog=(),
            taxonomies={"acme": TAXONOMY},
            v7_binding=_v7(),
            evidence_bytes=b'{"decisions":[]}',
            observed_at=NOW,
            source_adapter_ids=("greenhouse",),
            untrusted_payloads=({"approved": True, "reviewer": "agent"},),
        )


def test_default_join_without_positive_policy_axes_is_not_promotable() -> None:
    result = evaluate_occurrences(
        (_raw(),),
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={LISTING: _obs()},
    )
    assert result.candidates[0].evaluation.disposition == "inconclusive"
    assert result.candidates[0].evaluation.axes.policy == "unresolved"
    assert result.accounting.promotable == 0


def test_exact_catalog_match_is_already_approved_when_axes_close() -> None:
    approved = normalize_candidate_identity(
        key="acme",
        url=LISTING,
        provider_id="greenhouse",
        provider_token="acme",
        owner="targeted-ats",
        candidate_kind="board_route",
        adapter_id="greenhouse",
    )
    result = evaluate_occurrences(
        (_raw(),),
        approved_catalog=(approved,),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(),
        evidence_bytes=b'{"decisions":[]}',
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={LISTING: _obs()},
        positive_policy_axes=ALLOWED,
    )
    assert result.candidates[0].evaluation.disposition == "already_approved"
    assert result.accounting.already_approved == 1
    assert result.accounting.promotable == 0


def test_url_derived_provider_deny_and_claimed_mismatch_fail_closed() -> None:
    raw = _raw(
        provider_id="greenhouse",
        url="https://acme.icims.com/jobs",
        candidate_kind="board_route",
    )
    evidence = (
        b'{"decisions":[{"id":"icims-terms","axes":{"access":"permission_required",'
        b'"license":"unknown","publication":"blocked","redistribution":"permission_required",'
        b'"sync":"blocked"},"scope":{"providerIds":["icims"]}}]}'
    )
    result = evaluate_occurrences(
        (raw,),
        approved_catalog=(),
        taxonomies={"acme": TAXONOMY},
        v7_binding=_v7(evidence=evidence),
        evidence_bytes=evidence,
        observed_at=NOW,
        source_adapter_ids=("greenhouse",),
        observations={
            "https://acme.icims.com/jobs": _obs(
                locator="https://acme.icims.com/jobs",
                body=b'{"jobs":[{"id":1,"title":"Role"}]}',
            )
        },
        positive_policy_axes=ALLOWED,
    )
    evaluation = result.candidates[0].evaluation
    assert evaluation.disposition == "blocked"
    assert evaluation.axes.taxonomy == "incomplete"
    assert "icims-terms" in result.candidates[0].policy.deny_matches
