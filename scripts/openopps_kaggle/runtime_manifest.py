"""Runtime package manifest for Kaggle manager-runtime dataset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openopps_kaggle.constants import (
    RUNTIME_GENERATOR_PACKAGE_DIR,
    RUNTIME_MANIFEST_FILE,
)

_PACKAGE_ROOT = Path(__file__).resolve().parent


def _iter_package_files() -> dict[str, str]:
    files: dict[str, str] = {}
    scripts_root = _PACKAGE_ROOT.parent
    pkg_dir = _PACKAGE_ROOT
    for path in sorted(pkg_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(scripts_root).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def runtime_package_manifest() -> dict[str, object]:
    files = _iter_package_files()
    sha = hashlib.sha256(
        json.dumps(files, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "package": RUNTIME_GENERATOR_PACKAGE_DIR,
        "sha256": sha,
        "files": files,
    }


def runtime_package_sha256() -> str:
    return str(runtime_package_manifest()["sha256"])


def runtime_generator_script_sha256() -> str:
    return runtime_package_sha256()


def verify_runtime_package(manifest_root: Path) -> str:
    manifest_path = manifest_root / RUNTIME_MANIFEST_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing runtime manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict):
        raise RuntimeError("runtime-manifest.json missing files map")
    scripts_root = manifest_root.parent
    for rel, digest in sorted(expected_files.items()):
        path = scripts_root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Missing runtime package file: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError(
                f"Runtime package checksum mismatch for {rel}: "
                f"expected={digest} actual={actual}"
            )
    return str(manifest.get("sha256") or runtime_package_sha256())


def stage_runtime_package(upload_dir: Path) -> None:
    import shutil

    from openopps_kaggle.constants import DEFAULT_DATASET_DIR
    from openopps_kaggle._core import (
        _write_json,
        runtime_generator_dataset_metadata,
    )

    upload_dir = upload_dir.expanduser().resolve()
    protected = {
        _PACKAGE_ROOT,
        _PACKAGE_ROOT.parent,
        DEFAULT_DATASET_DIR.resolve(),
    }
    if upload_dir in protected:
        raise ValueError(
            "Runtime generator staging directory must be a temporary upload dir"
        )
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    upload_dir.mkdir(parents=True)

    target_pkg = upload_dir / RUNTIME_GENERATOR_PACKAGE_DIR
    shutil.copytree(
        _PACKAGE_ROOT,
        target_pkg,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    manifest = runtime_package_manifest()
    (upload_dir / RUNTIME_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(upload_dir / "dataset-metadata.json", runtime_generator_dataset_metadata())
