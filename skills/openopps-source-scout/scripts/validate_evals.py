#!/usr/bin/env python3
"""Read-only structural validation for the source-scout eval manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
EVALS_PATH = SKILL_ROOT / "evals" / "evals.json"
REQUIRED_EVAL_IDS = frozenset(
    {
        "arbitrary-link-unresolved",
        "bounded-probe-context",
        "codex-structural-smoke",
        "cursor-structural-smoke",
        "empty-context-stops",
        "explicit-captured-suggest",
        "fabricated-approval-rejected",
        "fabricated-evidence-rejected",
        "fabricated-parser-rejected",
        "fabricated-provider-rejected",
        "grok-structural-smoke",
        "harness-validator-equivalence",
        "known-bad-authority-shape",
        "known-bad-parser",
        "known-bad-provider",
        "known-bad-unadmitted-provenance",
        "known-good-fixture",
        "negative-control-catalog-mutation",
        "prompt-injection-inert",
        "secret-content-redacted",
        "unbounded-query-refused",
        "validate-dry-run-projection",
        "validate-evals-structure",
        "validate-frontmatter-portable",
        "independent-review-no-authority",
        "resolve-docs-steward-absent",
    }
)
CASE_FIELDS = frozenset({"id", "prompt", "expected_output", "files", "assertions"})


def _receipt(
    *, ok: bool, reason_code: str | None, eval_count: int | None = None
) -> dict[str, object]:
    return {
        "evalCount": eval_count,
        "ok": ok,
        "reasonCode": reason_code,
        "requiredIds": sorted(REQUIRED_EVAL_IDS),
        "skillName": "openopps-source-scout",
        "validator": "skills/openopps-source-scout/scripts/validate_evals.py",
    }


def _string_list(value: object, *, allow_empty: bool) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if not value and not allow_empty:
        return None
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        items.append(item)
    return items


def validate() -> tuple[int, dict[str, object]]:
    try:
        payload = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1, _receipt(ok=False, reason_code="evals_unreadable")

    if (
        not isinstance(payload, dict)
        or payload.get("skill_name") != "openopps-source-scout"
    ):
        return 1, _receipt(ok=False, reason_code="evals_skill_name")
    cases = payload.get("evals")
    if not isinstance(cases, list) or not cases:
        return 1, _receipt(ok=False, reason_code="evals_missing")

    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            return 1, _receipt(
                ok=False, reason_code="evals_case_fields", eval_count=len(cases)
            )
        case_id = case["id"]
        prompt = case["prompt"]
        expected = case["expected_output"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen_ids
            or not isinstance(prompt, str)
            or not prompt
            or prompt in seen_prompts
            or not isinstance(expected, str)
            or not expected
        ):
            return 1, _receipt(
                ok=False, reason_code="evals_identity", eval_count=len(cases)
            )
        assertions = _string_list(case["assertions"], allow_empty=False)
        files = _string_list(case["files"], allow_empty=True)
        if assertions is None or files is None:
            return 1, _receipt(
                ok=False, reason_code="evals_lists", eval_count=len(cases)
            )
        for relative in files:
            path = (REPOSITORY_ROOT / relative).resolve()
            if not path.is_file() or not path.is_relative_to(REPOSITORY_ROOT.resolve()):
                return 1, _receipt(
                    ok=False, reason_code="evals_missing_file", eval_count=len(cases)
                )
        seen_ids.add(case_id)
        seen_prompts.add(prompt)

    if not REQUIRED_EVAL_IDS <= seen_ids:
        return 1, _receipt(
            ok=False, reason_code="evals_required_ids", eval_count=len(cases)
        )
    return 0, _receipt(ok=True, reason_code=None, eval_count=len(cases))


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only structural validation of the committed source-scout "
            "evals manifest. No network, install, or fixture replay."
        )
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        exit_code, receipt = validate()
    except (OSError, TypeError, ValueError):
        exit_code = 2
        receipt = _receipt(ok=False, reason_code="evals_contract")
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
