"""V531-V536 read-only v7 policy binding and discovery-owned requirements."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from openopps.discovery.evaluation import evaluate_policy
from openopps.discovery.models import PolicyAxisSet
from openopps.discovery.policy import (
    REQUIRED_OPERATIONS,
    attribution_requirements,
    bind_candidate_policy,
    bind_v7_policy_digests,
    encode_discovery_policy_binding,
    match_deny_overlay,
)


ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = (
    ROOT / "src/openopps/providers/sources/data/source_policy_evidence.json"
).read_bytes()
SCHEMA = (
    ROOT / "src/openopps/providers/sources/data/source_policy_evidence.schema.json"
).read_bytes()
CODE = (ROOT / "src/openopps/source_policy.py").read_bytes()
CORPUS = (ROOT / "deployment/openopps-data/source-corpus-v6.json").read_bytes()


def test_bind_exact_v7_policy_digests_without_mutation() -> None:
    before = sha256(CODE).hexdigest()
    binding = bind_v7_policy_digests(
        policy_code=CODE,
        policy_schema=SCHEMA,
        policy_evidence=EVIDENCE,
        policy_corpus=CORPUS,
        public_selector=None,
    )
    after = sha256((ROOT / "src/openopps/source_policy.py").read_bytes()).hexdigest()
    assert binding.policy_code_sha256 == before == after
    assert binding.policy_evidence_sha256 == sha256(EVIDENCE).hexdigest()
    assert binding.public_selector_sha256 is None


def test_provider_denial_is_fail_closed_and_not_broadened() -> None:
    matches = match_deny_overlay(
        provider_id="consider",
        source_key="unrelated-source",
        evidence_bytes=EVIDENCE,
    )
    assert any(
        item.decision_id == "consider-terms-observed-2026-08-13" for item in matches
    )
    nonmatch = match_deny_overlay(
        provider_id="greenhouse",
        source_key="unrelated-source",
        evidence_bytes=EVIDENCE,
    )
    assert nonmatch == ()


def test_uncovered_candidates_stay_unresolved() -> None:
    binding = bind_v7_policy_digests(
        policy_code=CODE,
        policy_schema=SCHEMA,
        policy_evidence=EVIDENCE,
        policy_corpus=CORPUS,
        public_selector=None,
    )
    policy = bind_candidate_policy(
        provider_id="greenhouse",
        source_key="acme",
        taxonomy={"sourceAttribution": "Acme careers."},
        v7=binding,
        evidence_bytes=EVIDENCE,
        untrusted_observations=("http_200", "robots_allowed"),
    )
    assert (
        evaluate_policy(
            policy.axes,
            deny_overlay_matches=policy.deny_matches,
            untrusted_observations=policy.untrusted_observations,
        ).value
        == "unresolved"
    )
    assert policy.axes.access == "unresolved"
    assert policy.axes.publication == "unresolved"


def test_deny_overlay_keeps_independent_axes() -> None:
    binding = bind_v7_policy_digests(
        policy_code=b"code",
        policy_schema=b"schema",
        policy_evidence=EVIDENCE,
        policy_corpus=b"corpus",
        public_selector=None,
    )
    policy = bind_candidate_policy(
        provider_id="consider",
        source_key="consider-board",
        taxonomy={},
        v7=binding,
        evidence_bytes=EVIDENCE,
    )
    assert policy.axes.publication == "blocked"
    assert policy.axes.sync == "blocked"
    assert policy.axes.license == "unresolved"
    assert (
        evaluate_policy(policy.axes, deny_overlay_matches=policy.deny_matches).value
        == "blocked"
    )


def test_promotion_requirement_is_discovery_owned_and_not_v7_evidence() -> None:
    binding = bind_v7_policy_digests(
        policy_code=b"code",
        policy_schema=b"schema",
        policy_evidence=b'{"decisions":[]}',
        policy_corpus=b"corpus",
        public_selector=b'{"selector":1}',
    )
    policy = bind_candidate_policy(
        provider_id="greenhouse",
        source_key="acme",
        taxonomy={"sourceAttribution": "Keep attribution as requirement."},
        v7=binding,
        evidence_bytes=b'{"decisions":[]}',
    )
    assert policy.promotion_requirement.required_operations == REQUIRED_OPERATIONS
    assert policy.promotion_requirement.decision_present is False
    assert policy.promotion_requirement.serializes_as_v7_policy_evidence is False
    assert policy.promotion_requirement.grants_authority is False
    encoded = encode_discovery_policy_binding(policy).decode("utf-8")
    assert "source_policy_evidence" not in encoded
    assert "grantsAuthority" in encoded
    assert attribution_requirements(
        {"sourceAttribution": "Keep attribution as requirement."}
    ) == ("Keep attribution as requirement.",)


def test_http_200_and_robots_never_allow() -> None:
    axes = PolicyAxisSet(
        access="allowed",
        license="allowed",
        redistribution="allowed",
        sync="allowed",
        publication="unresolved",
    )
    result = evaluate_policy(
        axes,
        deny_overlay_matches=(),
        untrusted_observations=("http_200", "robots_allowed", "model_confident"),
    )
    assert result.value == "unresolved"
