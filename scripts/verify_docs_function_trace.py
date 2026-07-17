"""Validate docs app server-function traces stay deployable."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any


DEFAULT_TRACE = Path("web/.next/server/app/api/jobs/search/route.js.nft.json")
DEFAULT_FORBIDDEN_ROOT = Path("web/public/data/openopps-search")
DEFAULT_MAX_BYTES = 250 * 1024 * 1024


@dataclass(frozen=True)
class TraceReport:
    trace_path: Path
    file_count: int
    total_bytes: int
    forbidden_count: int
    forbidden_bytes: int
    missing_count: int
    forbidden_examples: tuple[str, ...]
    missing_examples: tuple[str, ...]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace",
        type=Path,
        default=DEFAULT_TRACE,
        help="Next.js NFT trace file to inspect.",
    )
    parser.add_argument(
        "--forbidden-root",
        type=Path,
        action="append",
        default=None,
        help="Path that must not be included in the function trace.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="Maximum allowed resolved trace bytes.",
    )
    args = parser.parse_args(argv)
    forbidden_roots = args.forbidden_root or [DEFAULT_FORBIDDEN_ROOT]
    errors, report = validate_function_trace(
        args.trace,
        forbidden_roots=forbidden_roots,
        max_bytes=args.max_bytes,
    )
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if report:
            _print_report(report, file=sys.stderr)
        return 1
    assert report is not None
    _print_report(report)
    return 0


def validate_function_trace(
    trace_path: Path,
    *,
    forbidden_roots: list[Path],
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> tuple[list[str], TraceReport | None]:
    trace_path = trace_path.resolve()
    if not trace_path.is_file():
        return [f"missing function trace: {trace_path}; run docs build first"], None

    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid function trace JSON: {trace_path}: {exc}"], None
    files = payload.get("files")
    if not isinstance(files, list):
        return [f"function trace is missing a files array: {trace_path}"], None

    normalized_forbidden_roots = [root.resolve() for root in forbidden_roots]
    trace_dir = trace_path.parent
    total_bytes = 0
    forbidden_bytes = 0
    forbidden: list[str] = []
    missing: list[str] = []

    for value in files:
        if not isinstance(value, str):
            missing.append(repr(value))
            continue
        resolved = (trace_dir / value).resolve()
        try:
            size = resolved.stat().st_size
        except OSError:
            missing.append(value)
            continue
        total_bytes += size
        if any(_is_relative_to(resolved, root) for root in normalized_forbidden_roots):
            forbidden.append(value)
            forbidden_bytes += size

    report = TraceReport(
        trace_path=trace_path,
        file_count=len(files),
        total_bytes=total_bytes,
        forbidden_count=len(forbidden),
        forbidden_bytes=forbidden_bytes,
        missing_count=len(missing),
        forbidden_examples=tuple(forbidden[:10]),
        missing_examples=tuple(missing[:10]),
    )
    errors: list[str] = []
    if forbidden:
        errors.append(
            "function trace includes forbidden files under "
            f"{', '.join(root.as_posix() for root in normalized_forbidden_roots)} "
            f"({len(forbidden)} files, {_format_bytes(forbidden_bytes)})"
        )
    if missing:
        errors.append(f"function trace references missing files ({len(missing)} entries)")
    if max_bytes is not None and total_bytes > max_bytes:
        errors.append(
            "function trace exceeds max bytes "
            f"({_format_bytes(total_bytes)} > {_format_bytes(max_bytes)})"
        )
    return errors, report


def _print_report(report: TraceReport, *, file: Any = sys.stdout) -> None:
    print(
        "docs function trace: "
        f"files={report.file_count} "
        f"bytes={report.total_bytes} ({_format_bytes(report.total_bytes)}) "
        f"forbidden={report.forbidden_count} "
        f"forbiddenBytes={report.forbidden_bytes} "
        f"missing={report.missing_count}",
        file=file,
    )
    if report.forbidden_examples:
        print("forbidden examples:", file=file)
        for example in report.forbidden_examples:
            print(f"  {example}", file=file)
    if report.missing_examples:
        print("missing examples:", file=file)
        for example in report.missing_examples:
            print(f"  {example}", file=file)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _format_bytes(value: int) -> str:
    return f"{value / 1024 / 1024:.1f} MiB"


if __name__ == "__main__":
    raise SystemExit(main())
