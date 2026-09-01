from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
import json
from pathlib import Path
import sys
from typing import Any

import openopps_kaggle.generator as generator

FORBIDDEN_SOURCE_TERMS = (
    "KAGGLE_KEY",
    "KAGGLE_USERNAME",
    "KAGGLE_API_TOKEN",
    "kaggle datasets create",
    "kaggle datasets version",
    "kaggle kernels push",
)
REQUIRED_SOURCE_TERMS = ("/kaggle/input", "openoppsdb.sqlite", "mode=ro&immutable=1")
STARTER_PULL_CODE_FILE_ALIAS = "openoppsdb-starter-notebook.ipynb"


@dataclass(frozen=True)
class ExpectedKernel:
    kernel_id: str
    slug: str
    metadata: dict[str, Any]
    notebook: dict[str, Any]
    code_file_aliases: frozenset[str] = frozenset()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify pulled Kaggle OpenOppsDB public notebook bundles."
    )
    parser.add_argument(
        "pull_root",
        type=Path,
        help="Directory containing one pulled Kaggle kernel directory per slug.",
    )
    args = parser.parse_args(argv)

    errors: list[str] = []
    summaries: list[str] = []
    for expected in expected_kernels():
        kernel_dir = args.pull_root / expected.slug
        metadata_path = kernel_dir / "kernel-metadata.json"
        if not metadata_path.is_file():
            errors.append(f"{expected.kernel_id}: missing kernel-metadata.json")
            continue

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{expected.kernel_id}: invalid kernel-metadata.json: {exc}")
            continue

        code_file = metadata.get("code_file")
        if not isinstance(code_file, str):
            errors.append(f"{expected.kernel_id}: code_file is not a string")
            continue
        expected_code_file = expected.metadata["code_file"]
        allowed_code_files = {expected_code_file, *expected.code_file_aliases}
        if code_file not in allowed_code_files:
            errors.append(f"{expected.kernel_id}: unexpected code_file {code_file!r}")
            continue

        notebook_path = kernel_dir / code_file
        if not notebook_path.is_file():
            errors.append(f"{expected.kernel_id}: missing notebook file {code_file!r}")
            continue

        actual_metadata = _canonical_metadata(metadata, expected_code_file)
        if actual_metadata != expected.metadata:
            errors.append(
                _diff_error(
                    expected.kernel_id,
                    "kernel-metadata.json does not match generated metadata",
                    expected.metadata,
                    actual_metadata,
                )
            )

        try:
            notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{expected.kernel_id}: invalid notebook JSON: {exc}")
            continue

        actual_notebook = _canonical_notebook(notebook)
        expected_notebook = _canonical_notebook(expected.notebook)
        if actual_notebook != expected_notebook:
            errors.append(
                _diff_error(
                    expected.kernel_id,
                    "notebook does not match generated source",
                    expected_notebook,
                    actual_notebook,
                )
            )

        _check_notebook_safety(expected.kernel_id, actual_notebook, errors)
        cells = actual_notebook.get("cells", [])
        cell_count = len(cells) if isinstance(cells, list) else 0
        summaries.append(
            f"{expected.kernel_id}: ok code_file={code_file} cells={cell_count}"
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for summary in summaries:
        print(summary)
    return 0


def expected_kernels() -> list[ExpectedKernel]:
    kernels = [
        ExpectedKernel(
            kernel_id=generator.STARTER_NB_ID,
            slug=generator.STARTER_NB_ID.split("/", 1)[1],
            metadata=generator.starter_kernel_metadata(),
            notebook=generator.starter_notebook(),
            code_file_aliases=frozenset({STARTER_PULL_CODE_FILE_ALIAS}),
        )
    ]
    for spec in generator.PUBLIC_EXAMPLE_NOTEBOOKS:
        kernels.append(
            ExpectedKernel(
                kernel_id=spec.notebook_id,
                slug=spec.notebook_id.split("/", 1)[1],
                metadata=generator.kernel_metadata_for_spec(spec),
                notebook=spec.notebook_factory(),
            )
        )
    return kernels


def _canonical_metadata(
    metadata: dict[str, Any], expected_code_file: str
) -> dict[str, Any]:
    canonical = _json_clone(metadata)
    canonical.pop("id_no", None)
    if "docker_image" in canonical:
        canonical["docker_image"] = ""
    if canonical.get("code_file") == STARTER_PULL_CODE_FILE_ALIAS:
        canonical["code_file"] = expected_code_file
    return canonical


def _canonical_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    canonical = _json_clone(notebook)
    cells = canonical.get("cells")
    if not isinstance(cells, list):
        return canonical
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if "source" in cell:
            cell["source"] = _canonical_source(cell["source"])
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
    return canonical


def _canonical_source(source: object) -> list[str]:
    if isinstance(source, list):
        text = "".join(str(line) for line in source)
    else:
        text = str(source)
    if not text:
        return []
    return [f"{line}\n" for line in text.rstrip("\n").split("\n")]


def _check_notebook_safety(
    kernel_id: str, notebook: dict[str, Any], errors: list[str]
) -> None:
    cells = notebook.get("cells")
    if notebook.get("nbformat") != 4:
        errors.append(f"{kernel_id}: nbformat is {notebook.get('nbformat')!r}")
    if not isinstance(cells, list) or not cells:
        errors.append(f"{kernel_id}: notebook has no cells")
        return

    source = _notebook_source(notebook)
    for term in REQUIRED_SOURCE_TERMS:
        if term not in source:
            errors.append(f"{kernel_id}: notebook source missing {term!r}")
    for term in FORBIDDEN_SOURCE_TERMS:
        if term in source:
            errors.append(f"{kernel_id}: notebook source contains {term!r}")


def _notebook_source(notebook: dict[str, Any]) -> str:
    parts: list[str] = []
    for cell in notebook.get("cells", []):
        if not isinstance(cell, dict):
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            parts.extend(str(line) for line in source)
        else:
            parts.append(str(source))
    return "\n".join(parts)


def _diff_error(
    kernel_id: str, message: str, expected: dict[str, Any], actual: dict[str, Any]
) -> str:
    diff = "\n".join(
        difflib.unified_diff(
            _json_lines(expected),
            _json_lines(actual),
            fromfile="expected",
            tofile="actual",
            lineterm="",
            n=5,
        )
    )
    return f"{kernel_id}: {message}\n{diff}"


def _json_lines(data: dict[str, Any]) -> list[str]:
    return json.dumps(data, indent=2, sort_keys=True).splitlines()


def _json_clone(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data))


if __name__ == "__main__":
    raise SystemExit(main())
