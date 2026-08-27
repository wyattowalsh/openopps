#!/usr/bin/env python3
"""Read-only dry-run of selected Codex/Cursor repository projections.

This is the in-repo S715 projection/sync check. It is not `wagents skills
sync` and it never writes, installs, applies, or contacts a network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SKILL_NAME = "openopps-source-scout"
SSOT = "skills/openopps-source-scout/"
TOOL = "skills/openopps-source-scout/scripts/dry_run_projection.py"
CODEX_PATH = REPOSITORY_ROOT / ".agents" / "skills" / SKILL_NAME
CURSOR_PATH = REPOSITORY_ROOT / ".cursor" / "skills" / SKILL_NAME
GROK_PATH = REPOSITORY_ROOT / ".grok" / "skills" / SKILL_NAME
SKIP_DIR_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc"}


def _relative_posix(path: Path) -> str:
    return path.relative_to(SKILL_ROOT).as_posix()


def _ssot_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(SKILL_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def _file_plan(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "bytes": len(payload),
        "relative": _relative_posix(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _harness(
    *,
    harness_id: str,
    selected_path: str | None,
    destination: Path | None,
    files: list[dict[str, object]],
    status: str,
) -> dict[str, object]:
    exists = destination.exists() if destination is not None else False
    return {
        "exists": exists,
        "files": files,
        "id": harness_id,
        "selectedPath": selected_path,
        "status": status,
    }


def _receipt(
    *,
    ok: bool,
    reason_code: str | None,
    harnesses: list[dict[str, object]],
) -> dict[str, object]:
    installed = any(path.exists() for path in (CODEX_PATH, CURSOR_PATH, GROK_PATH))
    return {
        "apply": False,
        "harnesses": harnesses,
        "homeSync": "not-planned",
        "ok": ok,
        "projectionsInstalled": installed,
        "reasonCode": reason_code,
        "selectedRepositoryProjectionsOnly": True,
        "ssot": SSOT,
        "syncTool": "in-repo-dry-run-projection",
        "tool": TOOL,
        "wagentsInvoked": False,
    }


def validate() -> tuple[int, dict[str, object]]:
    if not (SKILL_ROOT / "SKILL.md").is_file():
        return 1, _receipt(ok=False, reason_code="ssot_missing", harnesses=[])
    sources = _ssot_files()
    if not sources:
        return 1, _receipt(ok=False, reason_code="ssot_empty", harnesses=[])
    for path in sources:
        if path.is_symlink():
            return 1, _receipt(ok=False, reason_code="ssot_symlink", harnesses=[])
        try:
            path.resolve().relative_to(SKILL_ROOT.resolve())
        except ValueError:
            return 1, _receipt(ok=False, reason_code="ssot_escape", harnesses=[])

    planned_files = [_file_plan(path) for path in sources]
    if GROK_PATH.exists():
        grok_status = "unexpected-repository-projection"
        grok_ok = False
        grok_reason: str | None = "grok_projection_installed"
    else:
        grok_status = "no-repository-projection"
        grok_ok = True
        grok_reason = None
    harnesses = [
        _harness(
            harness_id="codex",
            selected_path=".agents/skills/openopps-source-scout/",
            destination=CODEX_PATH,
            files=planned_files,
            status=(
                "projection-installed" if CODEX_PATH.exists() else "planned-absent"
            ),
        ),
        _harness(
            harness_id="cursor",
            selected_path=".cursor/skills/openopps-source-scout/",
            destination=CURSOR_PATH,
            files=planned_files,
            status=(
                "projection-installed" if CURSOR_PATH.exists() else "planned-absent"
            ),
        ),
        _harness(
            harness_id="grok",
            selected_path=None,
            destination=GROK_PATH,
            files=[],
            status=grok_status,
        ),
    ]
    if CODEX_PATH.exists() or CURSOR_PATH.exists():
        return 1, _receipt(
            ok=False,
            reason_code="projection_installed",
            harnesses=harnesses,
        )
    if not grok_ok:
        return 1, _receipt(
            ok=False,
            reason_code=grok_reason,
            harnesses=harnesses,
        )
    return 0, _receipt(ok=True, reason_code=None, harnesses=harnesses)


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only dry-run of selected Codex/Cursor repository "
            "projections. Does not apply, install, or invoke wagents."
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
            reason_code="projection_contract",
            harnesses=[],
        )
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
