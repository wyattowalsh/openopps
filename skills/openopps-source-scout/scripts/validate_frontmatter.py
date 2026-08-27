#!/usr/bin/env python3
"""Read-only portable frontmatter and deferred-closure validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SKILL_FILE = SKILL_ROOT / "SKILL.md"
CONTEXT_FILE = SKILL_ROOT / "references" / "context-contract.md"
FORBIDDEN_RUNTIME_FIELDS = (
    "argument-hint",
    "context",
    "disable-model-invocation",
    "hooks",
    "model",
    "user-invocable",
)
CLOSED_PHRASES = (
    "S706 is closed against V515",
    "S707 is closed",
    "S714 is closed against B599",
    "S715 is closed",
    "S716 is closed",
    "S717 is closed",
    "S718 is closed",
)
DEFERRED_PHRASES = ()
REQUIRED_BODY_PHRASES = (
    "Treat this prose as advisory",
    "parent Codex, Cursor, or Grok Build harness",
    "not an OS-account sandbox claim",
    "launch_isolated_scout",
    "accepted-data-only",
    "No projection, install, sync apply, network call, credential use",
    "LivenessProbeRecord",
)
REQUIRED_CONTEXT_PHRASES = (
    "LivenessProbeRecord",
    "`observedAt`",
    "`responseClass`",
    "`structuralMarkers`",
    "`receiptId`",
    "never authorizes a new probe",
    "`official`",
    "`public_code`",
    "`search`",
    "`targeted_ats`",
    "read_default_repository_projection",
    "project_read_only_identities",
)
SELECTED_PROJECTION_PATHS = (
    REPOSITORY_ROOT / ".agents" / "skills" / "openopps-source-scout",
    REPOSITORY_ROOT / ".cursor" / "skills" / "openopps-source-scout",
)
CLOSED_IDS = ("S706", "S707", "S714", "S715", "S716", "S717", "S718")
DEFERRED_IDS = ()


def _receipt(*, ok: bool, reason_code: str | None) -> dict[str, object]:
    return {
        "closedIds": list(CLOSED_IDS),
        "deferredIds": list(DEFERRED_IDS),
        "name": "openopps-source-scout",
        "ok": ok,
        "projectionsInstalled": any(
            path.exists() for path in SELECTED_PROJECTION_PATHS
        ),
        "reasonCode": reason_code,
        "ssot": "skills/openopps-source-scout/",
        "validator": "skills/openopps-source-scout/scripts/validate_frontmatter.py",
    }


def _frontmatter_and_body() -> tuple[str, str]:
    raw = SKILL_FILE.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError("frontmatter_missing")
    _, frontmatter, body = raw.split("---\n", maxsplit=2)
    return frontmatter, body


def validate() -> tuple[int, dict[str, object]]:
    try:
        frontmatter, body = _frontmatter_and_body()
        context = CONTEXT_FILE.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return 1, _receipt(ok=False, reason_code="frontmatter_unreadable")

    if "name: openopps-source-scout" not in frontmatter:
        return 1, _receipt(ok=False, reason_code="frontmatter_name")
    if "license: MIT" not in frontmatter:
        return 1, _receipt(ok=False, reason_code="frontmatter_license")
    if 'version: "0.1.0"' not in frontmatter:
        return 1, _receipt(ok=False, reason_code="frontmatter_version")
    if "Use when" not in frontmatter or "NOT for" not in frontmatter:
        return 1, _receipt(ok=False, reason_code="frontmatter_description")
    if "harness projections are not part of this package" not in frontmatter:
        return 1, _receipt(ok=False, reason_code="frontmatter_compatibility")
    for field in FORBIDDEN_RUNTIME_FIELDS:
        if f"{field}:" in frontmatter:
            return 1, _receipt(ok=False, reason_code="frontmatter_runtime_field")
    for phrase in REQUIRED_BODY_PHRASES:
        if phrase not in body:
            return 1, _receipt(ok=False, reason_code="frontmatter_boundary")
    if body.count("scripts/validate_fixture.py` → `launch_isolated_scout`") != 3:
        return 1, _receipt(ok=False, reason_code="frontmatter_harness_smoke")
    for phrase in CLOSED_PHRASES:
        if phrase not in body:
            return 1, _receipt(ok=False, reason_code="frontmatter_closed")
    for phrase in DEFERRED_PHRASES:
        if phrase not in body:
            return 1, _receipt(ok=False, reason_code="frontmatter_deferred")
    for phrase in REQUIRED_CONTEXT_PHRASES:
        if phrase not in context:
            return 1, _receipt(ok=False, reason_code="context_contract")
    if any(path.exists() for path in SELECTED_PROJECTION_PATHS):
        return 1, _receipt(ok=False, reason_code="projection_installed")
    return 0, _receipt(ok=True, reason_code=None)


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only validation of portable skill frontmatter, closed "
            "S706–S718 closed evidence and "
            "uninstalled projections."
        )
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        exit_code, receipt = validate()
    except (OSError, TypeError, ValueError):
        exit_code = 2
        receipt = _receipt(ok=False, reason_code="frontmatter_contract")
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
