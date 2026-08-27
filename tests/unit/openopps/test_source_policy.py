from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

import openopps.source_policy as source_policy_module
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.source_policy import (
    DEFAULT_EVIDENCE_PATH,
    DEFAULT_SCHEMA_PATH,
    SourcePolicyBlockedError,
    SourcePolicyEvidence,
    SourcePolicyValidationError,
    audit_source_policy,
    canonical_json_bytes,
    compute_source_keys_sha256,
    load_source_corpus,
    load_source_policy_evidence,
    match_source_policy_denials,
    render_repository_source_selector,
    render_source_selector,
    validate_repository_source_policy,
    validate_source_policy_schema,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_PATH = (
    REPOSITORY_ROOT / "deployment" / "openopps-data" / "source-corpus-v6.json"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "web" / "public" / "data" / "openopps-search" / "manifest.json"
)
EXPECTED_SOURCE_DIGEST = (
    "2de3d0f9907ca56be1767888d84de7499b6b65acbcbe3c6ce026784f9c25a5e6"
)
EXPECTED_BLOCKED_DIGEST = (
    "4075848b08163cd9a6e8a757efa36a73eff30e95e0ac91d31a39a1903b28e865"
)
EXPECTED_GETRO_DIGEST = (
    "44b0d2cf74c93c571794dcd694088930f75f92aa8be41223bbed10ac3c646989"
)
EXPECTED_CONSIDER_DIGEST = (
    "0a1cfd4830715a05aa972fc8b1e4a03f97650fbec3686f7ed507655d15c4d338"
)
EXPECTED_UNREVIEWED_DIGEST = (
    "d157e8cf7e6b4042e02a1366d7e95bb480c2ef120985dd824c691e76678505ca"
)
EXPECTED_UNREVIEWED_SAMPLE = ("1011vcportfolio", "10xteam")
EXPECTED_ALLOWED = {
    "1871",
    "cncf-landscape",
    "forumventures",
    "pearvc",
    "southparkcommons",
    "venturecapitalcareers",
    "yc",
}


def _payload(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_committed_policy_is_canonical_complete_and_fail_closed() -> None:
    corpus = load_source_corpus(DEFAULT_CORPUS_PATH)
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)
    audit = audit_source_policy(corpus=corpus, evidence=evidence)

    assert len(corpus.source_keys) == 1787
    assert compute_source_keys_sha256(corpus.source_keys) == EXPECTED_SOURCE_DIGEST
    assert audit.source_count == 1787
    assert audit.allowed_count == 7
    assert audit.catalog_declared_allowed_count == 7
    assert audit.independently_verified_allowed_count == 0
    assert audit.allowed_evidence_basis == (
        "repository_catalog_declarations_not_independent_legal_review"
    )
    assert audit.blocked_count == 1780
    assert audit.blocked_source_keys_sha256 == EXPECTED_BLOCKED_DIGEST
    assert set(audit.allowed_source_keys) == EXPECTED_ALLOWED
    assert DEFAULT_CORPUS_PATH.read_bytes() == canonical_json_bytes(
        _payload(DEFAULT_CORPUS_PATH)
    )
    assert DEFAULT_EVIDENCE_PATH.read_bytes() == canonical_json_bytes(
        _payload(DEFAULT_EVIDENCE_PATH)
    )


def test_platform_terms_and_historical_blocks_are_explicit() -> None:
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)
    corpus = load_source_corpus(DEFAULT_CORPUS_PATH)
    decisions = {decision.id: decision for decision in evidence.decisions}

    getro = decisions["getro-terms-v3-1"]
    assert getro.scope.source_count == 426
    assert getro.scope.source_keys_sha256 == EXPECTED_GETRO_DIGEST
    assert getro.axes.access == "permission_required"
    assert getro.axes.redistribution == "permission_required"
    assert getro.axes.sync == "blocked"
    assert getro.axes.publication == "blocked"
    assert getro.evidence[0].version == "3.1"
    assert getro.evidence[0].last_updated == "June 2025"
    assert getro.evidence[0].sections == ("7.2.8", "8.2")

    consider = decisions["consider-terms-observed-2026-08-13"]
    assert consider.scope.source_count == 945
    assert consider.scope.source_keys_sha256 == EXPECTED_CONSIDER_DIGEST
    assert consider.axes.access == "permission_required"
    assert consider.axes.redistribution == "permission_required"
    assert consider.axes.sync == "blocked"
    assert consider.axes.publication == "blocked"
    assert consider.evidence[0].sections == ("1.4(l)",)

    unreviewed = decisions["historical-snapshot-sources-unreviewed"]
    assert unreviewed.scope.source_count == 409
    assert unreviewed.scope.source_keys_sha256 == EXPECTED_UNREVIEWED_DIGEST
    assert unreviewed.scope.source_keys[:2] == EXPECTED_UNREVIEWED_SAMPLE
    assert unreviewed.axes.access == "unavailable"
    assert unreviewed.axes.sync == "blocked"
    assert unreviewed.axes.publication == "blocked"

    audit = audit_source_policy(corpus=corpus, evidence=evidence)
    platform_keys = {
        key
        for key in corpus.source_keys
        if key in BOARD_SOURCE_CATALOG
        and BOARD_SOURCE_CATALOG[key].provider_id
        in {"getro", "consider", "consider_a16z"}
    }
    assert len(platform_keys) == 1371
    assert platform_keys <= set(audit.blocked_source_keys)


def test_allowed_decisions_mirror_catalog_without_overriding_it() -> None:
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)
    allowed_decisions = [
        decision
        for decision in evidence.decisions
        if decision.axes.publication == "allowed"
    ]

    assert {decision.scope.source_keys[0] for decision in allowed_decisions} == (
        EXPECTED_ALLOWED
    )
    for decision in allowed_decisions:
        key = decision.scope.source_keys[0]
        record = BOARD_SOURCE_CATALOG[key]
        assert decision.decision_type == "repository_status"
        assert decision.catalog_license_status == record.raw_metadata["licenseStatus"]
        assert decision.source_attribution == record.raw_metadata["sourceAttribution"]
        assert decision.evidence[0].kind == "repository_catalog"


def test_deny_overlay_matches_platform_scopes_for_arbitrary_subset() -> None:
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)
    getro_key = next(
        key
        for key, record in BOARD_SOURCE_CATALOG.items()
        if record.provider_id == "getro"
    )
    consider_key = next(
        key
        for key, record in BOARD_SOURCE_CATALOG.items()
        if record.provider_id == "consider"
    )

    matches = match_source_policy_denials(
        source_keys=(consider_key, getro_key), evidence=evidence
    )

    assert tuple(matches) == tuple(sorted((consider_key, getro_key)))
    assert [decision.id for decision in matches[getro_key]] == ["getro-terms-v3-1"]
    assert [decision.id for decision in matches[consider_key]] == [
        "consider-terms-observed-2026-08-13"
    ]


def test_deny_overlay_never_grants_and_preserves_exact_historical_blocks() -> None:
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)

    allowed_matches = match_source_policy_denials(
        source_keys=tuple(sorted(EXPECTED_ALLOWED)), evidence=evidence
    )
    unknown_matches = match_source_policy_denials(
        source_keys=("uncovered-future-source",), evidence=evidence
    )
    historical_matches = match_source_policy_denials(
        source_keys=EXPECTED_UNREVIEWED_SAMPLE, evidence=evidence
    )

    assert allowed_matches == {}
    assert unknown_matches == {}
    assert set(historical_matches) == set(EXPECTED_UNREVIEWED_SAMPLE)
    assert {
        decision.id
        for decisions in historical_matches.values()
        for decision in decisions
    } == {"historical-snapshot-sources-unreviewed"}


def test_schema_is_model_derived_and_committed_canonically() -> None:
    schema = SourcePolicyEvidence.model_json_schema()
    assert DEFAULT_SCHEMA_PATH.read_bytes() == canonical_json_bytes(schema)
    validate_source_policy_schema()


def test_schema_drift_is_rejected(tmp_path: Path) -> None:
    drifted = tmp_path / "schema.json"
    drifted.write_bytes(b"{}\n")

    with pytest.raises(SourcePolicyValidationError, match="canonical.*JSON Schema"):
        validate_source_policy_schema(drifted)


def test_repository_snapshot_validation_closes_over_v6_manifest() -> None:
    audit = validate_repository_source_policy(
        corpus_path=DEFAULT_CORPUS_PATH,
        manifest_path=DEFAULT_MANIFEST_PATH,
    )
    assert audit.blocked_count == 1780
    assert audit.blocked_source_keys_sha256 == EXPECTED_BLOCKED_DIGEST


def test_current_corpus_cannot_render_a_sync_selector() -> None:
    corpus = load_source_corpus(DEFAULT_CORPUS_PATH)
    evidence = load_source_policy_evidence(DEFAULT_EVIDENCE_PATH)

    with pytest.raises(SourcePolicyBlockedError, match=r"1780.*4075848b"):
        render_source_selector(corpus=corpus, evidence=evidence)


def test_repository_selector_renders_from_single_loaded_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"corpus": 0, "evidence": 0}
    original_corpus_loader = source_policy_module.load_source_corpus
    original_evidence_loader = source_policy_module.load_source_policy_evidence

    def load_corpus_once(path: Path):  # type annotation inferred from wrapped API
        calls["corpus"] += 1
        return original_corpus_loader(path)

    def load_evidence_once(path: Path):  # type annotation inferred from wrapped API
        calls["evidence"] += 1
        return original_evidence_loader(path)

    monkeypatch.setattr(source_policy_module, "load_source_corpus", load_corpus_once)
    monkeypatch.setattr(
        source_policy_module, "load_source_policy_evidence", load_evidence_once
    )

    with pytest.raises(SourcePolicyBlockedError, match=r"1780.*4075848b"):
        render_repository_source_selector(
            corpus_path=DEFAULT_CORPUS_PATH,
            evidence_path=DEFAULT_EVIDENCE_PATH,
            manifest_path=DEFAULT_MANIFEST_PATH,
        )

    assert calls == {"corpus": 1, "evidence": 1}


def test_missing_or_overlapping_decisions_fail_closed(tmp_path: Path) -> None:
    payload = _payload(DEFAULT_EVIDENCE_PATH)
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decisions.pop()
    path = tmp_path / "missing.json"
    path.write_bytes(canonical_json_bytes(payload))

    evidence = load_source_policy_evidence(path)
    corpus = load_source_corpus(DEFAULT_CORPUS_PATH)
    with pytest.raises(SourcePolicyValidationError, match="uncovered source keys"):
        audit_source_policy(corpus=corpus, evidence=evidence)

    payload = _payload(DEFAULT_EVIDENCE_PATH)
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    duplicate = copy.deepcopy(decisions[-1])
    assert isinstance(duplicate, dict)
    duplicate["id"] = "duplicate-scope"
    decisions.append(duplicate)
    decisions.sort(key=lambda item: str(item["id"]))
    path = tmp_path / "overlap.json"
    path.write_bytes(canonical_json_bytes(payload))

    evidence = load_source_policy_evidence(path)
    with pytest.raises(SourcePolicyValidationError, match="multiple decisions"):
        audit_source_policy(corpus=corpus, evidence=evidence)


def test_axis_invariants_reject_permission_bypass() -> None:
    payload = _payload(DEFAULT_EVIDENCE_PATH)
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decision = decisions[0]
    assert isinstance(decision, dict)
    axes = decision["axes"]
    assert isinstance(axes, dict)
    axes["publication"] = "allowed"

    with pytest.raises(ValidationError, match="publication cannot be allowed"):
        SourcePolicyEvidence.model_validate(payload)


def test_unresolved_catalog_states_are_representable_but_blocked() -> None:
    payload = _payload(DEFAULT_EVIDENCE_PATH)
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decision = copy.deepcopy(decisions[-1])
    assert isinstance(decision, dict)
    decision["id"] = "repository-status-unresolved-fixture"
    decision["catalogLicenseStatus"] = "needs_review"
    decision.pop("sourceAttribution")
    axes = decision["axes"]
    assert isinstance(axes, dict)
    axes.update(
        {
            "access": "permission_required",
            "license": "needs_review",
            "publication": "blocked",
            "redistribution": "prohibited",
            "sync": "blocked",
        }
    )
    decisions[-1] = decision
    decisions.sort(key=lambda item: str(item["id"]))

    model = SourcePolicyEvidence.model_validate(payload)
    unresolved = next(
        item
        for item in model.decisions
        if item.id == "repository-status-unresolved-fixture"
    )
    assert unresolved.axes.license == "needs_review"
    assert unresolved.axes.redistribution == "prohibited"


@pytest.mark.parametrize(
    ("command", "expected_code", "stdout_fragment", "stderr_fragment"),
    [
        ("validate", 0, '"blockedCount":1780', ""),
        ("audit", 2, '"blockedCount":1780', "blocks 1780 sources"),
        ("render-selector", 2, "", "selector blocked by 1780"),
    ],
)
def test_cli_commands_are_deterministic_and_fail_closed(
    command: str,
    expected_code: int,
    stdout_fragment: str,
    stderr_fragment: str,
) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/source_policy_review.py", command],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_code
    assert stdout_fragment in result.stdout
    assert stderr_fragment in result.stderr


def test_noncanonical_evidence_and_manifest_drift_are_rejected(tmp_path: Path) -> None:
    payload = _payload(DEFAULT_EVIDENCE_PATH)
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(SourcePolicyValidationError, match="canonical JSON"):
        load_source_policy_evidence(noncanonical)

    manifest = _payload(Path("web/public/data/openopps-search/manifest.json"))
    facets = manifest["facets"]
    assert isinstance(facets, dict)
    sources = facets["sources"]
    assert isinstance(sources, list)
    sources.pop()
    drifted = tmp_path / "manifest.json"
    drifted.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(SourcePolicyValidationError, match="artifact SHA-256"):
        validate_repository_source_policy(
            corpus_path=DEFAULT_CORPUS_PATH,
            manifest_path=drifted,
        )


def test_digest_is_newline_delimited_and_order_sensitive() -> None:
    expected = hashlib.sha256(b"a\nb\n").hexdigest()
    assert compute_source_keys_sha256(("a", "b")) == expected
    assert compute_source_keys_sha256(("b", "a")) != expected
