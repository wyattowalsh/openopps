"""Runtime package manifest for Kaggle manager-runtime dataset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from openopps_kaggle.constants import (
    RUNTIME_GENERATOR_PACKAGE_DIR,
    RUNTIME_MANIFEST_FILE,
)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parents[1]
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def canonical_runtime_package_sha256(files: Mapping[str, object]) -> str:
    payload = json.dumps(
        files,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _iter_package_files() -> dict[str, str]:
    files: dict[str, str] = {}
    scripts_root = _PACKAGE_ROOT.parent
    pkg_dir = _PACKAGE_ROOT
    for path in sorted(pkg_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(
                f"Runtime source package must not contain symlinks: {path}"
            )
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(scripts_root).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def runtime_package_manifest() -> dict[str, object]:
    files = _iter_package_files()
    sha = canonical_runtime_package_sha256(files)
    return {
        "package": RUNTIME_GENERATOR_PACKAGE_DIR,
        "sha256": sha,
        "files": files,
    }


def runtime_package_sha256() -> str:
    return str(runtime_package_manifest()["sha256"])


def runtime_generator_script_sha256() -> str:
    return runtime_package_sha256()


def _load_runtime_manifest(manifest_path: Path) -> dict[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(
                    f"runtime-manifest.json contains duplicate key: {key}"
                )
            result[key] = value
        return result

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid runtime-manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("runtime-manifest.json must contain a JSON object")
    return manifest


def _validated_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _validated_runtime_file_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError("runtime-manifest.json missing files map")
    files: dict[str, str] = {}
    casefolded_paths: dict[str, str] = {}
    for raw_relative_path, raw_digest in value.items():
        if not isinstance(raw_relative_path, str):
            raise RuntimeError("Runtime manifest file paths must be strings")
        relative_path = PurePosixPath(raw_relative_path)
        if (
            not raw_relative_path
            or "\\" in raw_relative_path
            or "\x00" in raw_relative_path
            or relative_path.is_absolute()
            or relative_path.as_posix() != raw_relative_path
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or len(relative_path.parts) < 2
            or relative_path.parts[0] != RUNTIME_GENERATOR_PACKAGE_DIR
        ):
            raise RuntimeError(
                f"Runtime manifest contains unsafe relative path: {raw_relative_path!r}"
            )
        folded = raw_relative_path.casefold()
        prior = casefolded_paths.get(folded)
        if prior is not None and prior != raw_relative_path:
            raise RuntimeError(
                "Runtime manifest contains case-colliding paths: "
                f"{prior!r} and {raw_relative_path!r}"
            )
        casefolded_paths[folded] = raw_relative_path
        files[raw_relative_path] = _validated_sha256(
            raw_digest,
            label=f"Runtime manifest checksum for {raw_relative_path}",
        )
    return files


def _runtime_package_inventory(
    manifest_root: Path,
    *,
    expected_files: set[str],
) -> dict[str, Path]:
    package_root = manifest_root / RUNTIME_GENERATOR_PACKAGE_DIR
    if package_root.is_symlink():
        raise RuntimeError("Runtime package directory must not be a symlink")
    if not package_root.is_dir():
        raise FileNotFoundError(f"Missing runtime package directory: {package_root}")
    expected_dirs = {
        parent.as_posix()
        for relative_path in expected_files
        for parent in PurePosixPath(relative_path).parents
        if parent.as_posix() != "."
    }
    inventory: dict[str, Path] = {}
    unexpected_dirs: list[str] = []
    for path in package_root.rglob("*"):
        relative_path = path.relative_to(manifest_root).as_posix()
        if path.is_symlink():
            raise RuntimeError(
                f"Runtime package must not contain symlinks: {relative_path}"
            )
        if path.is_file():
            inventory[relative_path] = path
        elif path.is_dir():
            if relative_path not in expected_dirs:
                unexpected_dirs.append(relative_path)
        else:
            raise RuntimeError(
                f"Runtime package contains unsupported filesystem entry: {relative_path}"
            )
    actual_files = set(inventory)
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    if missing or extra or unexpected_dirs:
        raise RuntimeError(
            "Runtime package file set mismatch: "
            f"missing={missing} extra={extra} unexpected_dirs={sorted(unexpected_dirs)}"
        )
    return inventory


def verify_runtime_package(
    manifest_root: Path,
    *,
    expected_sha256: str | None = None,
) -> str:
    raw_manifest_root = manifest_root.expanduser()
    if raw_manifest_root.is_symlink():
        raise RuntimeError("Runtime package root must not be a symlink")
    manifest_root = raw_manifest_root.resolve()
    manifest_path = manifest_root / RUNTIME_MANIFEST_FILE
    if manifest_path.is_symlink():
        raise RuntimeError("Runtime manifest must not be a symlink")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing runtime manifest: {manifest_path}")
    manifest = _load_runtime_manifest(manifest_path)
    if manifest.get("package") != RUNTIME_GENERATOR_PACKAGE_DIR:
        raise RuntimeError(
            f"runtime-manifest.json package must be {RUNTIME_GENERATOR_PACKAGE_DIR!r}"
        )
    declared_root = _validated_sha256(
        manifest.get("sha256"),
        label="Runtime manifest root checksum",
    )
    expected_files = _validated_runtime_file_map(manifest.get("files"))
    inventory = _runtime_package_inventory(
        manifest_root,
        expected_files=set(expected_files),
    )
    verified_files: dict[str, str] = {}
    for relative_path, expected_digest in sorted(expected_files.items()):
        actual_digest = hashlib.sha256(
            inventory[relative_path].read_bytes()
        ).hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError(
                f"Runtime package checksum mismatch for {relative_path}: "
                f"expected={expected_digest} actual={actual_digest}"
            )
        verified_files[relative_path] = actual_digest
    actual_root = canonical_runtime_package_sha256(verified_files)
    if actual_root != declared_root:
        raise RuntimeError(
            "Runtime package root checksum mismatch: "
            f"declared={declared_root} actual={actual_root}"
        )
    if expected_sha256 is not None:
        trusted_root = _validated_sha256(
            expected_sha256,
            label="Expected runtime package root checksum",
        )
        if actual_root != trusted_root:
            raise RuntimeError(
                "Runtime package expected root checksum mismatch: "
                f"expected={trusted_root} actual={actual_root}"
            )
    return actual_root


def stage_runtime_package(upload_dir: Path) -> None:
    import shutil

    from openopps_kaggle.constants import DEFAULT_DATASET_DIR
    from openopps_kaggle._core import (
        _prepare_owned_staging_dir,
        _write_json,
        runtime_generator_dataset_metadata,
    )

    manifest = runtime_package_manifest()
    package_files = manifest["files"]
    if not isinstance(package_files, dict):
        raise RuntimeError("Runtime package manifest generation failed")
    allowed_files = {
        "dataset-metadata.json",
        RUNTIME_MANIFEST_FILE,
        *package_files,
    }
    protected_roots = {
        Path.cwd(),
        Path.home(),
        _REPO_ROOT,
        _PACKAGE_ROOT.parent,
        _PACKAGE_ROOT,
        DEFAULT_DATASET_DIR,
    }
    upload_dir = _prepare_owned_staging_dir(
        upload_dir,
        allowed_files=allowed_files,
        protected_roots=protected_roots,
        forbidden_descendant_roots={
            Path.cwd(),
            _REPO_ROOT,
            _PACKAGE_ROOT.parent,
            _PACKAGE_ROOT,
            DEFAULT_DATASET_DIR,
        },
        label="Runtime generator",
        ownership_description="prior OpenOpps runtime-generator contents",
    )

    target_pkg = upload_dir / RUNTIME_GENERATOR_PACKAGE_DIR
    shutil.copytree(
        _PACKAGE_ROOT,
        target_pkg,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    (upload_dir / RUNTIME_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(
        upload_dir / "dataset-metadata.json", runtime_generator_dataset_metadata()
    )
