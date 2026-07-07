from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "verify_docs_function_trace.py"
_SPEC = importlib.util.spec_from_file_location("verify_docs_function_trace", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
validate_function_trace = _MODULE.validate_function_trace


def test_trace_verifier_accepts_clean_trace(tmp_path: Path) -> None:
    trace_dir = tmp_path / "docs" / ".next" / "server" / "app" / "api" / "jobs" / "search"
    trace_path = trace_dir / "route.js.nft.json"
    forbidden_root = tmp_path / "docs" / "public" / "data" / "openopps-search"
    write_text(trace_dir / "route.js", "export {}")
    write_trace(trace_path, ["route.js"])

    errors, report = validate_function_trace(
        trace_path,
        forbidden_roots=[forbidden_root],
        max_bytes=1024,
    )

    assert errors == []
    assert report is not None
    assert report.file_count == 1
    assert report.forbidden_count == 0
    assert report.missing_count == 0


def test_trace_verifier_rejects_forbidden_public_search_artifacts(tmp_path: Path) -> None:
    trace_dir = tmp_path / "docs" / ".next" / "server" / "app" / "api" / "jobs" / "search"
    trace_path = trace_dir / "route.js.nft.json"
    forbidden_root = tmp_path / "docs" / "public" / "data" / "openopps-search"
    forbidden_file = forbidden_root / "jobs" / "chunks" / "0000.json"
    write_text(forbidden_file, "{}")
    write_trace(trace_path, [relative_to_trace(forbidden_file, trace_dir)])

    errors, report = validate_function_trace(
        trace_path,
        forbidden_roots=[forbidden_root],
        max_bytes=1024,
    )

    assert any("function trace includes forbidden files" in error for error in errors)
    assert report is not None
    assert report.forbidden_count == 1
    assert report.forbidden_bytes == 2
    assert report.forbidden_examples == (relative_to_trace(forbidden_file, trace_dir),)


def test_trace_verifier_rejects_missing_trace(tmp_path: Path) -> None:
    errors, report = validate_function_trace(
        tmp_path / "missing.nft.json",
        forbidden_roots=[tmp_path / "docs" / "public" / "data" / "openopps-search"],
        max_bytes=1024,
    )

    assert report is None
    assert any("run docs build first" in error for error in errors)


def test_trace_verifier_rejects_missing_trace_entries(tmp_path: Path) -> None:
    trace_dir = tmp_path / "docs" / ".next" / "server" / "app" / "api" / "jobs" / "search"
    trace_path = trace_dir / "route.js.nft.json"
    write_trace(trace_path, ["missing.js"])

    errors, report = validate_function_trace(
        trace_path,
        forbidden_roots=[tmp_path / "docs" / "public" / "data" / "openopps-search"],
        max_bytes=1024,
    )

    assert any("function trace references missing files" in error for error in errors)
    assert report is not None
    assert report.missing_count == 1
    assert report.missing_examples == ("missing.js",)


def test_trace_verifier_rejects_oversized_trace(tmp_path: Path) -> None:
    trace_dir = tmp_path / "docs" / ".next" / "server" / "app" / "api" / "jobs" / "search"
    trace_path = trace_dir / "route.js.nft.json"
    write_text(trace_dir / "route.js", "x" * 16)
    write_trace(trace_path, ["route.js"])

    errors, report = validate_function_trace(
        trace_path,
        forbidden_roots=[tmp_path / "docs" / "public" / "data" / "openopps-search"],
        max_bytes=8,
    )

    assert any("function trace exceeds max bytes" in error for error in errors)
    assert report is not None
    assert report.total_bytes == 16


def relative_to_trace(path: Path, trace_dir: Path) -> str:
    return Path(os.path.relpath(path, trace_dir)).as_posix()


def write_trace(path: Path, files: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "files": files}), encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
