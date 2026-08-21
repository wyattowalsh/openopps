"""Generate or byte-check committed source-discovery JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openopps.discovery.schemas import (
    DEFAULT_SCHEMA_ROOT,
    check_discovery_schema_files,
    write_discovery_schema_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate canonical JSON Schemas for every strict OpenOpps discovery "
            "model, or verify that the committed files are byte-identical."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="perform a read-only byte-equality check instead of writing schemas",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SCHEMA_ROOT,
        help="schema directory (defaults to the package discovery data directory)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = (
        check_discovery_schema_files(args.output)
        if args.check
        else write_discovery_schema_files(args.output)
    )
    receipt = {**result.as_dict(), "output": str(args.output)}
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
