from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

import pytest

from openopps.discovery.canonical import decode_canonical_json
from openopps.discovery.isolation import IsolationError, validate_data_only_suggestion
from openopps.discovery.liveness import LivenessProbeRecord
from openopps.discovery.models import BoundedReason


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


def _unquote_frontmatter_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_portable_frontmatter(raw: str) -> dict[str, object]:
    """Parse the closed SKILL.md YAML subset without PyYAML (ops-only extra)."""
    data: dict[str, object] = {}
    folded_key: str | None = None
    folded: list[str] = []
    nested_key: str | None = None
    nested: dict[str, str] = {}
    pending = list(raw.splitlines())

    def flush_folded() -> None:
        nonlocal folded_key, folded
        if folded_key is not None:
            data[folded_key] = " ".join(folded).strip()
            folded_key = None
            folded = []

    def flush_nested() -> None:
        nonlocal nested_key, nested
        if nested_key is not None:
            data[nested_key] = nested
            nested_key = None
            nested = {}

    while pending:
        line = pending.pop(0)
        if folded_key is not None:
            if line.startswith("  "):
                folded.append(line.strip())
                continue
            flush_folded()
            pending.insert(0, line)
            continue
        if nested_key is not None:
            if line.startswith("  ") and ":" in line:
                child_key, child_val = line.strip().split(":", 1)
                nested[child_key] = _unquote_frontmatter_scalar(child_val.strip())
                continue
            flush_nested()
            pending.insert(0, line)
            continue
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        assert sep, f"unexpected frontmatter line: {line!r}"
        key = key.strip()
        value = value.strip()
        if value in {">-", ">"}:
            folded_key = key
            folded = []
            continue
        if value == "":
            nested_key = key
            nested = {}
            continue
        data[key] = _unquote_frontmatter_scalar(value)
    flush_folded()
    flush_nested()
    return data


def _skill_parts() -> tuple[dict[str, object], str]:
    raw = SKILL_FILE.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    _, frontmatter_raw, body = raw.split("---\n", maxsplit=2)
    frontmatter = _parse_portable_frontmatter(frontmatter_raw)
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
        "PYTHONDONTWRITEBYTECODE": "1",
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
    tracked = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    assert tracked == {
        "SKILL.md",
        "evals/evals.json",
        "references/context-contract.md",
        "scripts/dry_run_projection.py",
        "scripts/resolve_docs_steward.py",
        "scripts/validate_evals.py",
        "scripts/validate_fixture.py",
        "scripts/validate_frontmatter.py",
    }
    for projection in (
        ROOT / ".agents" / "skills" / "openopps-source-scout",
        ROOT / ".cursor" / "skills" / "openopps-source-scout",
    ):
        assert not projection.exists()
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
        "S706 is closed against V515",
        "S707 is closed",
        "S714 is closed against B599",
        "S715 is closed",
        "S716 is closed",
        "S717 is closed",
        "S718 is closed",
    ):
        assert phrase in body
    assert "Calling a model" in body
    assert "is not an\n   acceptance path" in body
    assert body.count("scripts/validate_fixture.py` → `launch_isolated_scout`") == 3


def test_context_contract_names_exact_channels_budgets_and_read_only_surfaces() -> None:
    context = CONTEXT_FILE.read_text(encoding="utf-8")
    schema_root = ROOT / "src" / "openopps" / "discovery" / "data"
    manifest = _canonical_object(schema_root / "manifest.json")
    generated_names = {row["path"] for row in manifest["schemas"]}
    named_in_contract = {
        token
        for index, token in enumerate(context.split("`"))
        if index % 2 == 1 and token.endswith(".schema.json")
    }
    assert "promotion-selection.schema.json" in generated_names
    assert named_in_contract <= generated_names

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
        "channel-replay-receipt.schema.json",
        "liveness-evidence.schema.json",
        "provenance-claim.schema.json",
        "candidate-taxonomy.schema.json",
        "terminal-evaluation.schema.json",
        "scout-candidate.schema.json",
        "promotion-selection.schema.json",
    ):
        assert schema_name in generated_names
        assert (schema_root / schema_name).is_file()
        assert f"`{schema_name}`" in context
    for inventory_surface in (
        "ApprovedRuntimeCatalogInventory",
        "PackagedCatalogReadback",
        "adapterProviderIds",
        "read_default_repository_projection",
        "project_read_only_identities",
        "portfolio_source_catalog.json",
    ):
        assert inventory_surface in context
    assert "access, license, redistribution, sync, and publication" in context
    for probe_field in (
        "observedAt",
        "responseClass",
        "structuralMarkers",
        "receiptId",
        "permanentAbsence",
    ):
        assert f"`{probe_field}`" in context
    assert "LivenessProbeRecord" in context
    assert "never authorizes a new probe" in context


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
        "bounded-probe-context",
        "codex-structural-smoke",
        "cursor-structural-smoke",
        "grok-structural-smoke",
        "harness-validator-equivalence",
        "validate-evals-structure",
        "validate-frontmatter-portable",
        "validate-dry-run-projection",
        "resolve-docs-steward-absent",
        "independent-review-no-authority",
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


def _run_structural_validator(
    script: Path,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, os.fspath(script)],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert isinstance(receipt, dict)
    return result, receipt


def test_skill_states_selected_ssot_and_uninstalled_projections() -> None:
    _, body = _skill_parts()

    assert "S701 selection is read-only" in body
    assert "`skills/openopps-source-scout/`" in body
    assert "`.agents/skills/openopps-source-scout/`" in body
    assert "`.cursor/skills/openopps-source-scout/`" in body
    assert "no repository projection; read this SSOT" in body


def test_structural_validators_are_read_only_and_pass() -> None:
    evals_script = SKILL_ROOT / "scripts" / "validate_evals.py"
    frontmatter_script = SKILL_ROOT / "scripts" / "validate_frontmatter.py"
    dry_run_script = SKILL_ROOT / "scripts" / "dry_run_projection.py"
    docs_steward_script = SKILL_ROOT / "scripts" / "resolve_docs_steward.py"

    evals_help = subprocess.run(
        [sys.executable, os.fspath(evals_script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    frontmatter_help = subprocess.run(
        [sys.executable, os.fspath(frontmatter_script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    dry_run_help = subprocess.run(
        [sys.executable, os.fspath(dry_run_script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    docs_help = subprocess.run(
        [sys.executable, os.fspath(docs_steward_script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert evals_help.returncode == 0
    assert frontmatter_help.returncode == 0
    assert dry_run_help.returncode == 0
    assert docs_help.returncode == 0
    for help_text in (
        evals_help.stdout,
        frontmatter_help.stdout,
        dry_run_help.stdout,
        docs_help.stdout,
    ):
        for forbidden in ("--input", "--network", "--install", "--apply"):
            assert forbidden not in help_text

    evals_result, evals_receipt = _run_structural_validator(evals_script)
    frontmatter_result, frontmatter_receipt = _run_structural_validator(
        frontmatter_script
    )
    dry_run_result, dry_run_receipt = _run_structural_validator(dry_run_script)
    docs_result, docs_receipt = _run_structural_validator(docs_steward_script)
    assert evals_result.returncode == 0, evals_result.stderr
    assert frontmatter_result.returncode == 0, frontmatter_result.stderr
    assert dry_run_result.returncode == 0, dry_run_result.stderr
    assert docs_result.returncode == 0, docs_result.stderr
    assert evals_receipt["ok"] is True
    assert evals_receipt["reasonCode"] is None
    assert evals_receipt["skillName"] == "openopps-source-scout"
    assert dry_run_receipt["ok"] is True
    assert dry_run_receipt["apply"] is False
    assert dry_run_receipt["homeSync"] == "not-planned"
    assert dry_run_receipt["projectionsInstalled"] is False
    assert dry_run_receipt["reasonCode"] is None
    assert dry_run_receipt["selectedRepositoryProjectionsOnly"] is True
    assert dry_run_receipt["ssot"] == "skills/openopps-source-scout/"
    assert dry_run_receipt["syncTool"] == "in-repo-dry-run-projection"
    assert dry_run_receipt["wagentsInvoked"] is False
    harnesses = {row["id"]: row for row in dry_run_receipt["harnesses"]}
    assert set(harnesses) == {"codex", "cursor", "grok"}
    assert harnesses["codex"]["status"] == "planned-absent"
    assert harnesses["cursor"]["status"] == "planned-absent"
    assert harnesses["grok"]["status"] == "no-repository-projection"
    assert harnesses["grok"]["files"] == []
    assert harnesses["grok"]["selectedPath"] is None
    planned = [row["relative"] for row in harnesses["codex"]["files"]]
    assert planned == sorted(planned)
    assert "SKILL.md" in planned
    assert harnesses["codex"]["files"] == harnesses["cursor"]["files"]
    assert docs_receipt["ok"] is True
    assert docs_receipt["present"] is False
    assert docs_receipt["invoked"] is False
    assert docs_receipt["install"] is False
    assert docs_receipt["inRepoProcess"] is False
    assert docs_receipt["command"] == [
        "uv",
        "run",
        "wagents",
        "skills",
        "search",
        "docs-steward",
        "--json",
    ]
    assert docs_receipt["reasonCode"] in {
        "docs_steward_absent",
        "uv_absent",
        "wagents_absent",
        "wagents_error",
        "wagents_timeout",
    }
    for projection in (
        ROOT / ".agents" / "skills" / "openopps-source-scout",
        ROOT / ".cursor" / "skills" / "openopps-source-scout",
        ROOT / ".grok" / "skills" / "openopps-source-scout",
    ):
        assert not projection.exists()
    assert frontmatter_receipt == {
        "closedIds": [
            "S706",
            "S707",
            "S714",
            "S715",
            "S716",
            "S717",
            "S718",
        ],
        "deferredIds": [],
        "name": "openopps-source-scout",
        "ok": True,
        "projectionsInstalled": False,
        "reasonCode": None,
        "ssot": "skills/openopps-source-scout/",
        "validator": "skills/openopps-source-scout/scripts/validate_frontmatter.py",
    }

    evals_source = evals_script.read_text(encoding="utf-8")
    frontmatter_source = frontmatter_script.read_text(encoding="utf-8")
    dry_run_source = dry_run_script.read_text(encoding="utf-8")
    docs_source = docs_steward_script.read_text(encoding="utf-8")
    for source in (evals_source, frontmatter_source, dry_run_source, docs_source):
        assert "launch_isolated_scout(" not in source
        for forbidden_import in (
            "openopps.cache",
            "openopps.cli",
            "openopps.discovery",
            "openopps.plugins",
            "openopps.providers",
            "openopps.storage",
            "urllib",
            "httpx",
            "requests",
        ):
            assert forbidden_import not in source
    for forbidden in ("pip install", "uv pip", "uv tool install", "uvx "):
        assert forbidden not in dry_run_source
        assert forbidden not in docs_source


def test_skill_consumes_v515_probe_record_without_live_access() -> None:
    _, body = _skill_parts()
    context = CONTEXT_FILE.read_text(encoding="utf-8")
    probe = LivenessProbeRecord(
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
        response_class="expected_payload",
        structural_markers=("json_job_array",),
        expected_structure=True,
        listing_endpoint="https://public.example.test/jobs",
        cached=False,
        receipt_id="admitted-receipt-id",
        reason_code=BoundedReason.NONE,
    )
    payload = probe.as_dict()

    assert payload["permanentAbsence"] is False
    for key in payload:
        assert f"`{key}`" in context
    assert "openopps.discovery.liveness.LivenessProbeRecord" in context
    assert "never authorizes a new probe" in context
    assert "Never replace it with live" in body
    assert "never probe, fetch, or echo a payload" in body
    for forbidden in (
        "openopps.health",
        "check_provider_health",
        "probe_liveness(",
    ):
        assert forbidden not in body
