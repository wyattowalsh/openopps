#!/usr/bin/env python3
"""Repository-only offline source-policy validation and selector rendering."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from openopps.source_policy import (
    DEFAULT_EVIDENCE_PATH,
    DEFAULT_SCHEMA_PATH,
    SourcePolicyValidationError,
    canonical_json_bytes,
    render_repository_source_selector,
    validate_repository_source_policy,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_PATH = (
    REPOSITORY_ROOT / "deployment" / "openopps-data" / "source-corpus-v6.json"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "web" / "public" / "data" / "openopps-search" / "manifest.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the committed source-policy evidence without network access or "
            "catalog mutation."
        )
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE_PATH,
        help="canonical source-policy evidence JSON",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help="canonical source-corpus snapshot JSON",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="exact committed v6 search manifest",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help="canonical model-derived source-policy JSON Schema",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "validate",
        help="validate canonical bytes, complete evidence, and v6 artifact identity",
    )
    subparsers.add_parser(
        "audit",
        help="validate, report counts and digests, then fail if any source is blocked",
    )
    subparsers.add_parser(
        "render-selector",
        help="write a canonical selector to stdout only when every source is eligible",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "render-selector":
            sys.stdout.buffer.write(
                render_repository_source_selector(
                    corpus_path=args.corpus,
                    evidence_path=args.evidence,
                    manifest_path=args.manifest,
                    schema_path=args.schema,
                )
            )
            return 0
        audit = validate_repository_source_policy(
            evidence_path=args.evidence,
            corpus_path=args.corpus,
            manifest_path=args.manifest,
            schema_path=args.schema,
        )
        summary = {
            "allowedCount": audit.allowed_count,
            "allowedEvidenceBasis": audit.allowed_evidence_basis,
            "blockedCount": audit.blocked_count,
            "blockedSourceKeysSha256": audit.blocked_source_keys_sha256,
            "catalogDeclaredAllowedCount": audit.catalog_declared_allowed_count,
            "corpusId": audit.corpus_id,
            "independentlyVerifiedAllowedCount": (
                audit.independently_verified_allowed_count
            ),
            "policyId": audit.policy_id,
            "schemaVersion": audit.schema_version,
            "sourceCount": audit.source_count,
            "sourceKeysSha256": audit.source_keys_sha256,
        }
        sys.stdout.buffer.write(canonical_json_bytes(summary))
        if args.command == "audit" and audit.blocked_count:
            print(
                f"source policy blocks {audit.blocked_count} sources "
                f"({audit.blocked_source_keys_sha256})",
                file=sys.stderr,
            )
            return 2
        return 0
    except (
        OSError,
        ValidationError,
        SourcePolicyValidationError,
    ) as exc:
        print(f"source policy error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
