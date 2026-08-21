from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

import pytest
import yaml

from openopps.discovery.api import assure_discovery_schemas
from openopps.discovery.canonical import decode_canonical_json
from openopps.discovery.isolation import IsolationError, validate_data_only_suggestion


ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = ROOT / "skills" / "openopps-source-scout"
SKILL_FILE = SKILL_ROOT / "SKILL.md"
CONTEXT_FILE = SKILL_ROOT / "references" / "context-contract.md"
EVALS_FILE = SKILL_ROOT / "evals" / "evals.json"
VALIDATOR = SKILL_ROOT / "scripts" / "validate_fixture.py"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "discovery"
SCENARIOS_FILE = FIXTURE_ROOT / "skill" / "scenarios.json"
SUGGESTION_FIELDS = {
    "candidateLocator",
    "parserId",
    "provenanceResourceIds",
    "providerId",
}
ISOLATED_VALIDATOR = "openopps.discovery.isolation.launch_isolated_scout"


def _canonical_object(path: Path) -> dict[str, Any]:
    value = decode_canonical_json(path.read_bytes())
    assert isinstance(value, dict)
    return value


def _skill_parts() -> tuple[dict[str, object], str]:
    raw = SKILL_FILE.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    _, frontmatter_raw, body = raw.split("---\n", maxsplit=2)
    frontmatter = yaml.safe_load(frontmatter_raw)
    assert isinstance(frontmatter, dict)
    return frontmatter, body


def _fixture_path(relative: str) -> Path:
    path = (FIXTURE_ROOT / relative).resolve(strict=True)
    assert path.is_relative_to(FIXTURE_ROOT.resolve(strict=True))
    return path


def _fixture_hashes() -> dict[str, str]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted((FIXTURE_ROOT / "skill").glob("*.json"))
    }


def _run_fixture(
    *,
    harness: str,
    scenario: str,
    quarantine_root: Path,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, Any]]:
    environment = {
        **os.environ,
        "OPENOPPS_SYNTHETIC_SECRET": "must-not-reach-worker-output",
    }
    result = subprocess.run(
        [
            sys.executable,
            os.fspath(VALIDATOR),
            "--harness",
            harness,
            "--scenario",
            scenario,
            "--quarantine-root",
            os.fspath(quarantine_root),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
    )
    receipt = decode_canonical_json(result.stdout)
    assert isinstance(receipt, dict)
    return result, receipt


def test_portable_skill_has_one_repository_ssot_and_no_projection() -> None:
    frontmatter, body = _skill_parts()

    assert frontmatter["name"] == "openopps-source-scout"
    assert set(frontmatter) == {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
    }
    assert frontmatter["license"] == "MIT"
    assert frontmatter["metadata"] == {"version": "0.1.0"}
    description = str(frontmatter["description"])
    assert "Use when" in description
    assert "NOT for" in description
    assert len(body.splitlines()) < 500
    for runtime_field in (
        "argument-hint",
        "context",
        "disable-model-invocation",
        "hooks",
        "model",
        "user-invocable",
    ):
        assert runtime_field not in frontmatter

    assert not SKILL_ROOT.is_symlink()
    assert {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file()
    } == {
        "SKILL.md",
        "evals/evals.json",
        "references/context-contract.md",
        "scripts/validate_fixture.py",
    }
    assert all(not path.is_symlink() for path in SKILL_ROOT.rglob("*"))


def test_skill_states_advisory_boundary_and_closed_acceptance_path() -> None:
    _, body = _skill_parts()

    for phrase in (
        "Treat this prose as advisory",
        "parent Codex, Cursor, or Grok Build harness",
        "not an OS-account sandbox claim",
        "launch_isolated_scout",
        "accepted-data-only",
        "No projection, install, sync apply, network call, credential use",
    ):
        assert phrase in body
    assert "Calling a model" in body
    assert "is not an\n   acceptance path" in body
    assert body.count("scripts/validate_fixture.py` → `launch_isolated_scout`") == 3


def test_context_contract_names_exact_channels_budgets_and_read_only_surfaces() -> None:
    context = CONTEXT_FILE.read_text(encoding="utf-8")
    assure_discovery_schemas()

    for channel in ("official", "public_code", "search", "targeted_ats"):
        assert f"`{channel}`" in context
    for budget in (
        "queryLimit",
        "requestLimit",
        "originLimit",
        "redirectLimit",
        "pageLimit",
        "responseByteLimit",
        "aggregateByteLimit",
        "candidateLimit",
        "concurrencyLimit",
        "perOriginConcurrencyLimit",
        "retryLimit",
        "parserDepthLimit",
        "wallClockLimitMs",
    ):
        assert f"`{budget}`" in context
    for schema_name in (
        "trusted-discovery-profile.schema.json",
        "channel-budget.schema.json",
        "whole-run-budget.schema.json",
        "normalized-candidate.schema.json",
        "observed-resource.schema.json",
        "request-receipt.schema.json",
        "provenance-claim.schema.json",
        "candidate-taxonomy.schema.json",
        "terminal-evaluation.schema.json",
        "scout-candidate.schema.json",
    ):
        assert (
            ROOT / "src" / "openopps" / "discovery" / "data" / schema_name
        ).is_file()
        assert f"`{schema_name}`" in context
    for inventory_surface in (
        "ApprovedRuntimeCatalogInventory",
        "PackagedCatalogReadback",
        "adapterProviderIds",
        "read_default_repository_projection",
        "portfolio_source_catalog.json",
    ):
        assert inventory_surface in context
    assert "access, license, redistribution, sync, and publication" in context
    assert "unavailable until V515\ncloses S706" in context


def test_eval_manifest_covers_adversaries_fixtures_and_harnesses() -> None:
    manifest = json.loads(EVALS_FILE.read_text(encoding="utf-8"))
    assert manifest["skill_name"] == "openopps-source-scout"
    cases = manifest["evals"]
    assert isinstance(cases, list)
    by_id = {case["id"]: case for case in cases}
    assert len(by_id) == len(cases)
    assert {
        "prompt-injection-inert",
        "fabricated-evidence-rejected",
        "unbounded-query-refused",
        "arbitrary-link-unresolved",
        "secret-content-redacted",
        "fabricated-parser-rejected",
        "fabricated-provider-rejected",
        "fabricated-approval-rejected",
        "known-good-fixture",
        "known-bad-unadmitted-provenance",
        "known-bad-parser",
        "known-bad-provider",
        "known-bad-authority-shape",
        "codex-structural-smoke",
        "cursor-structural-smoke",
        "grok-structural-smoke",
    } <= set(by_id)
    assert len({case["prompt"] for case in cases}) == len(cases)
    for case in cases:
        assert isinstance(case["expected_output"], str) and case["expected_output"]
        assert isinstance(case["assertions"], list) and case["assertions"]
        for relative in case.get("files", []):
            assert (ROOT / relative).is_file(), relative


def test_committed_known_good_and_bad_fixtures_match_closed_contract() -> None:
    registry = _canonical_object(SCENARIOS_FILE)
    admitted_resources = frozenset(registry["admittedResourceIds"])
    admitted_parsers = frozenset(registry["admittedParserIds"])
    admitted_providers = frozenset(registry["admittedProviderIds"])

    for scenario in registry["scenarios"]:
        payload = _canonical_object(_fixture_path(scenario["inputPath"]))
        assert scenario["schemaValid"] is (set(payload) == SUGGESTION_FIELDS)
        if scenario.get("expectedOutcome") == "accepted-data-only":
            accepted = validate_data_only_suggestion(
                payload,
                admitted_resource_ids=admitted_resources,
                allowed_parser_ids=admitted_parsers,
                allowed_provider_ids=admitted_providers,
            )
            assert dict(accepted) == payload
        else:
            with pytest.raises(IsolationError) as caught:
                validate_data_only_suggestion(
                    payload,
                    admitted_resource_ids=admitted_resources,
                    allowed_parser_ids=admitted_parsers,
                    allowed_provider_ids=admitted_providers,
                )
            assert caught.value.reason_code == scenario["expectedReason"]


def test_fixture_runner_replays_every_scenario_without_mutating_fixtures(
    tmp_path: Path,
) -> None:
    registry = _canonical_object(SCENARIOS_FILE)
    before = _fixture_hashes()

    for scenario in registry["scenarios"]:
        quarantine_root = tmp_path / scenario["id"]
        result, receipt = _run_fixture(
            harness="codex",
            scenario=scenario["id"],
            quarantine_root=quarantine_root,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert result.stderr == b""
        assert receipt["ok"] is True
        assert receipt["isolatedValidator"] == ISOLATED_VALIDATOR
        expected_acceptance = scenario.get("expectedOutcome") == "accepted-data-only"
        assert receipt["accepted"] is expected_acceptance
        assert receipt["expectedAcceptance"] is expected_acceptance
        rendered = result.stdout.decode("utf-8")
        assert "must-not-reach-worker-output" not in rendered
        assert "candidateLocator" not in rendered
        if expected_acceptance:
            output = quarantine_root / "worker" / "result.json"
            assert output.is_file()
            assert stat.S_IMODE(quarantine_root.stat().st_mode) == 0o700
            assert stat.S_IMODE(output.stat().st_mode) == 0o600
            assert (
                receipt["semanticSha256"]
                == hashlib.sha256(output.read_bytes()).hexdigest()
            )
        else:
            assert not quarantine_root.exists()
            assert receipt["reasonCode"] == scenario["expectedReason"]
            assert receipt["isolatedReasonCode"] == "isolated_process_output"

    assert _fixture_hashes() == before


def test_codex_cursor_and_grok_structural_smokes_share_semantic_bytes(
    tmp_path: Path,
) -> None:
    _, body = _skill_parts()
    manifest = json.loads(EVALS_FILE.read_text(encoding="utf-8"))
    eval_ids = {case["id"] for case in manifest["evals"]}
    semantic_outputs: list[bytes] = []

    for harness in ("codex", "cursor", "grok"):
        assert harness.capitalize() in body or harness == "grok" and "Grok" in body
        assert f"{harness}-structural-smoke" in eval_ids
        quarantine_root = tmp_path / harness
        result, receipt = _run_fixture(
            harness=harness,
            scenario="known-good",
            quarantine_root=quarantine_root,
        )
        assert result.returncode == 0
        assert receipt == {
            "accepted": True,
            "expectedAcceptance": True,
            "harness": harness,
            "isolatedReasonCode": None,
            "isolatedValidator": ISOLATED_VALIDATOR,
            "ok": True,
            "reasonCode": None,
            "scenarioId": "known-good",
            "semanticSha256": receipt["semanticSha256"],
        }
        semantic_outputs.append(
            (quarantine_root / "worker" / "result.json").read_bytes()
        )

    assert len(set(semantic_outputs)) == 1
    semantic = decode_canonical_json(semantic_outputs[0])
    assert semantic["profileId"] == "skill-fixture"
    assert semantic["seed"] == 0
    assert set(semantic["result"]) == {"suggestions"}


def test_fixture_runner_exposes_no_arbitrary_input_or_alternate_validator() -> None:
    result = subprocess.run(
        [sys.executable, os.fspath(VALIDATOR), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--harness" in result.stdout
    assert "--scenario" in result.stdout
    assert "--quarantine-root" in result.stdout
    for forbidden in (
        "--input",
        "--context",
        "--executable",
        "--network",
        "--install",
        "--apply",
    ):
        assert forbidden not in result.stdout

    source = VALIDATOR.read_text(encoding="utf-8")
    assert source.count("launch_isolated_scout(") == 1
    for forbidden_import in (
        "openopps.cache",
        "openopps.cli",
        "openopps.plugins",
        "openopps.providers",
        "openopps.storage",
    ):
        assert forbidden_import not in source
