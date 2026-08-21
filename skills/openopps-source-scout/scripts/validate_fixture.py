#!/usr/bin/env python3
"""Replay one committed source-scout fixture through the isolated validator."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import hashlib
from pathlib import Path, PurePosixPath
import sys
from typing import Any

from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.isolation import (
    ApplicationFilesystem,
    IsolationError,
    ScoutLaunchRequest,
    ScoutProcessLimits,
    launch_isolated_scout,
    validate_data_only_suggestion,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "discovery"
SCENARIO_PATH = FIXTURE_ROOT / "skill" / "scenarios.json"
SUPPORTED_HARNESSES = ("codex", "cursor", "grok")
ISOLATED_VALIDATOR = "openopps.discovery.isolation.launch_isolated_scout"


def _read_canonical_object(path: Path) -> dict[str, Any]:
    payload = decode_canonical_json(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("fixture must be a canonical JSON object")
    return payload


def _scenario_registry() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    registry = _read_canonical_object(SCENARIO_PATH)
    if set(registry) != {
        "admittedParserIds",
        "admittedProviderIds",
        "admittedResourceIds",
        "scenarios",
        "schemaVersion",
    }:
        raise ValueError("fixture registry fields are not exact")
    if registry["schemaVersion"] != "openopps.discovery.skill-fixtures.v1":
        raise ValueError("fixture registry version is unsupported")
    scenarios = registry["scenarios"]
    if not isinstance(scenarios, list):
        raise ValueError("fixture scenarios must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("fixture scenario must be an object")
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id or scenario_id in by_id:
            raise ValueError("fixture scenario identity is invalid")
        by_id[scenario_id] = scenario
    return registry, by_id


def _fixture_path(relative: object) -> Path:
    if not isinstance(relative, str):
        raise ValueError("fixture path must be a string")
    posix = PurePosixPath(relative)
    if (
        posix.is_absolute()
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ValueError("fixture path is not repository relative")
    path = FIXTURE_ROOT.joinpath(*posix.parts).resolve(strict=True)
    fixture_root = FIXTURE_ROOT.resolve(strict=True)
    if not path.is_relative_to(fixture_root) or not path.is_file():
        raise ValueError("fixture path escapes the committed fixture root")
    return path


def _string_set(registry: Mapping[str, object], field: str) -> frozenset[str]:
    value = registry.get(field)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("fixture admission inventory is invalid")
    return frozenset(value)


def _preflight_reason(
    suggestion: object,
    *,
    admitted_resource_ids: frozenset[str],
    allowed_parser_ids: frozenset[str],
    allowed_provider_ids: frozenset[str],
) -> str | None:
    try:
        validate_data_only_suggestion(
            suggestion,
            admitted_resource_ids=admitted_resource_ids,
            allowed_parser_ids=allowed_parser_ids,
            allowed_provider_ids=allowed_provider_ids,
        )
    except IsolationError as error:
        return error.reason_code
    return None


async def _replay(
    *,
    harness: str,
    scenario_id: str,
    quarantine_root: Path,
) -> tuple[int, dict[str, object]]:
    registry, scenarios = _scenario_registry()
    if scenario_id not in scenarios:
        raise ValueError("unknown committed fixture scenario")
    if not quarantine_root.is_absolute() or quarantine_root.exists():
        raise ValueError("quarantine root must be one new absolute path")

    scenario = scenarios[scenario_id]
    suggestion = _read_canonical_object(_fixture_path(scenario.get("inputPath")))
    admitted_resource_ids = _string_set(registry, "admittedResourceIds")
    allowed_parser_ids = _string_set(registry, "admittedParserIds")
    allowed_provider_ids = _string_set(registry, "admittedProviderIds")
    preflight_reason = _preflight_reason(
        suggestion,
        admitted_resource_ids=admitted_resource_ids,
        allowed_parser_ids=allowed_parser_ids,
        allowed_provider_ids=allowed_provider_ids,
    )
    expected_acceptance = scenario.get("expectedOutcome") == "accepted-data-only"
    expected_reason = scenario.get("expectedReason")
    request = ScoutLaunchRequest(
        input_bytes=canonical_json_bytes({"suggestions": [suggestion]}),
        quarantine_root=quarantine_root,
        parent_environment={},
        environment_allowlist=frozenset(),
        trusted_profile_id="skill-fixture",
        trusted_seed=0,
        admitted_resource_ids=admitted_resource_ids,
        allowed_parser_ids=allowed_parser_ids,
        allowed_provider_ids=allowed_provider_ids,
    )
    accepted = False
    isolated_reason: str | None = None
    semantic_sha256: str | None = None
    try:
        result = await launch_isolated_scout(
            request,
            executable=sys.executable,
            filesystem=ApplicationFilesystem(root=quarantine_root),
            limits=ScoutProcessLimits(timeout_seconds=30),
        )
        accepted = True
        semantic_sha256 = hashlib.sha256(result.stdout).hexdigest()
    except IsolationError as error:
        isolated_reason = error.reason_code

    if expected_acceptance:
        ok = accepted and preflight_reason is None and isolated_reason is None
    else:
        ok = (
            not accepted
            and isinstance(expected_reason, str)
            and preflight_reason == expected_reason
            and isolated_reason == "isolated_process_output"
        )
    receipt: dict[str, object] = {
        "accepted": accepted,
        "expectedAcceptance": expected_acceptance,
        "harness": harness,
        "isolatedReasonCode": isolated_reason,
        "isolatedValidator": ISOLATED_VALIDATOR,
        "ok": ok,
        "reasonCode": preflight_reason,
        "scenarioId": scenario_id,
        "semanticSha256": semantic_sha256,
    }
    return (0 if ok else 1), receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one named committed source-scout fixture through the fixed "
            "credential-free isolated validator."
        )
    )
    parser.add_argument("--harness", choices=SUPPORTED_HARNESSES, required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--quarantine-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code, receipt = asyncio.run(
            _replay(
                harness=args.harness,
                scenario_id=args.scenario,
                quarantine_root=args.quarantine_root,
            )
        )
    except (OSError, TypeError, ValueError):
        receipt = {
            "accepted": False,
            "expectedAcceptance": None,
            "harness": args.harness,
            "isolatedReasonCode": "fixture_contract",
            "isolatedValidator": ISOLATED_VALIDATOR,
            "ok": False,
            "reasonCode": "fixture_contract",
            "scenarioId": args.scenario,
            "semanticSha256": None,
        }
        exit_code = 2
    sys.stdout.buffer.write(canonical_json_bytes(receipt))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
