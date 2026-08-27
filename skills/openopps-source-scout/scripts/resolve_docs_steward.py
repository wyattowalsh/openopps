#!/usr/bin/env python3
"""Resolve docs-steward availability without installing anything.

Runs the exact S716 command `uv run wagents skills search docs-steward --json`
from this checkout. If wagents is absent or docs-steward is not an in-repo
process, emit the skip receipt. Never pip/uv-tool install, never apply.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
IN_REPO_SKILL = REPOSITORY_ROOT / "skills" / "docs-steward" / "SKILL.md"
COMMAND = (
    "uv",
    "run",
    "wagents",
    "skills",
    "search",
    "docs-steward",
    "--json",
)
RESOLVER = "skills/openopps-source-scout/scripts/resolve_docs_steward.py"
SEARCH_TIMEOUT_S = 30


def _receipt(
    *,
    ok: bool,
    reason_code: str | None,
    present: bool,
    invoked: bool,
    returncode: int | None,
    stdout: str,
    stderr: str,
) -> dict[str, object]:
    return {
        "command": list(COMMAND),
        "inRepoProcess": IN_REPO_SKILL.is_file(),
        "install": False,
        "invoked": invoked,
        "ok": ok,
        "present": present,
        "reasonCode": reason_code,
        "resolver": RESOLVER,
        "returncode": returncode,
        "skillName": "docs-steward",
        "stderr": stderr,
        "stdout": stdout,
    }


def _docs_steward_present(stdout: str) -> bool:
    text = stdout.strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "docs-steward" in text
    if isinstance(payload, dict):
        name = payload.get("name") or payload.get("id") or payload.get("skill")
        if name == "docs-steward":
            return True
        rows = payload.get("skills") or payload.get("results") or payload.get("items")
        if isinstance(rows, list):
            return _rows_include_docs_steward(rows)
        return False
    if isinstance(payload, list):
        return _rows_include_docs_steward(payload)
    return False


def _rows_include_docs_steward(rows: list[object]) -> bool:
    for row in rows:
        if row == "docs-steward":
            return True
        if isinstance(row, dict):
            identity = row.get("name") or row.get("id") or row.get("skill")
            if identity == "docs-steward":
                return True
    return False


def _spawn_reason(stderr: str) -> str:
    lowered = stderr.lower()
    if "failed to spawn" in lowered or "no such file or directory" in lowered:
        return "wagents_absent"
    if stderr.strip():
        return "wagents_error"
    return "wagents_absent"


def validate() -> tuple[int, dict[str, object]]:
    in_repo = IN_REPO_SKILL.is_file()
    try:
        result = subprocess.run(
            COMMAND,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=SEARCH_TIMEOUT_S,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except FileNotFoundError as exc:
        return 0, _receipt(
            ok=True,
            reason_code="uv_absent",
            present=False,
            invoked=False,
            returncode=None,
            stdout="",
            stderr=str(exc),
        )
    except subprocess.TimeoutExpired:
        return 0, _receipt(
            ok=True,
            reason_code="wagents_timeout",
            present=False,
            invoked=False,
            returncode=None,
            stdout="",
            stderr="uv run wagents skills search docs-steward --json timed out",
        )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    search_hit = result.returncode == 0 and _docs_steward_present(stdout)
    present = bool(in_repo and search_hit)
    if present:
        return 0, _receipt(
            ok=True,
            reason_code="docs_steward_present_uninvoked",
            present=True,
            invoked=False,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    if result.returncode != 0:
        return 0, _receipt(
            ok=True,
            reason_code=_spawn_reason(stderr),
            present=False,
            invoked=False,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    return 0, _receipt(
        ok=True,
        reason_code="docs_steward_absent",
        present=False,
        invoked=False,
        returncode=result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Resolve docs-steward with uv run wagents skills search only. "
            "Never install, apply, or invoke a hosted docs service."
        )
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        exit_code, receipt = validate()
    except (OSError, TypeError, ValueError):
        exit_code = 2
        receipt = _receipt(
            ok=False,
            reason_code="docs_steward_contract",
            present=False,
            invoked=False,
            returncode=None,
            stdout="",
            stderr="",
        )
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
