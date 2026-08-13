from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

import openopps_kaggle._core as core
from openopps_kaggle.constants import (
    DEFAULT_DATASET_DIR,
    RUNTIME_GENERATOR_PACKAGE_DIR,
    RUNTIME_MANIFEST_FILE,
)
from openopps_kaggle.runtime_manifest import (
    canonical_runtime_package_sha256,
    stage_runtime_package,
    verify_runtime_package,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / RUNTIME_GENERATOR_PACKAGE_DIR


def _read_manifest(runtime_root: Path) -> dict[str, object]:
    return json.loads(
        (runtime_root / RUNTIME_MANIFEST_FILE).read_text(encoding="utf-8")
    )


def _write_manifest(runtime_root: Path, manifest: dict[str, object]) -> None:
    (runtime_root / RUNTIME_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _notebook_setup_namespace(
    tmp_path: Path,
    *,
    runtime_input: Path | None = None,
) -> dict[str, object]:
    output_dir = tmp_path / "notebook-output"
    source = core._notebook_setup_source()
    setup_definitions = source.split("\nrequire_kaggle_credentials()\n", 1)[0]
    namespace: dict[str, object] = {
        "__name__": "openopps_kaggle_runtime_test",
    }
    old_output = core.os.environ.get("OPENOPPS_KAGGLE_OUTPUT_DIR")
    core.os.environ["OPENOPPS_KAGGLE_OUTPUT_DIR"] = str(output_dir)
    try:
        exec(setup_definitions, namespace)
    finally:
        if old_output is None:
            core.os.environ.pop("OPENOPPS_KAGGLE_OUTPUT_DIR", None)
        else:
            core.os.environ["OPENOPPS_KAGGLE_OUTPUT_DIR"] = old_output
    if runtime_input is not None:
        namespace["KAGGLE_INPUT_DIR"] = runtime_input.parent
    return namespace


def test_runtime_stage_rejects_non_empty_unowned_dir_without_deleting_it(
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "runtime-upload"
    upload_dir.mkdir()
    existing = upload_dir / "keep.txt"
    existing.write_text("do not delete\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to overwrite non-empty"):
        stage_runtime_package(upload_dir)

    assert existing.read_text(encoding="utf-8") == "do not delete\n"


def test_runtime_stage_replaces_only_prior_tool_owned_contents(tmp_path: Path) -> None:
    upload_dir = tmp_path / "runtime-upload"
    stage_runtime_package(upload_dir)
    staged_module = upload_dir / RUNTIME_GENERATOR_PACKAGE_DIR / "cli.py"
    staged_module.write_text("# stale tool-owned copy\n", encoding="utf-8")

    stage_runtime_package(upload_dir)

    assert staged_module.read_bytes() == (PACKAGE_ROOT / "cli.py").read_bytes()
    assert verify_runtime_package(upload_dir) == _read_manifest(upload_dir)["sha256"]


def test_runtime_stage_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    existing = target / "keep.txt"
    existing.write_text("keep\n", encoding="utf-8")
    upload_link = tmp_path / "runtime-upload"
    upload_link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        stage_runtime_package(upload_link)

    assert existing.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize(
    "target",
    [
        Path.cwd(),
        Path.home(),
        REPO_ROOT,
        REPO_ROOT.parent,
        REPO_ROOT / "scripts",
        PACKAGE_ROOT,
        DEFAULT_DATASET_DIR,
    ],
    ids=["cwd", "home", "repo", "repo-ancestor", "scripts", "package", "dataset"],
)
def test_runtime_stage_rejects_protected_roots_and_ancestors(
    target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_delete_reached(path: Path) -> None:
        raise AssertionError(f"unsafe delete attempted: {path}")

    monkeypatch.setattr(shutil, "rmtree", fail_if_delete_reached)

    with pytest.raises(ValueError, match="protected directory"):
        stage_runtime_package(target)


@pytest.mark.parametrize(
    "target",
    [
        REPO_ROOT / ".runtime-upload-must-not-exist",
        PACKAGE_ROOT / ".runtime-upload-must-not-exist",
        DEFAULT_DATASET_DIR / ".runtime-upload-must-not-exist",
    ],
    ids=["repo-descendant", "package-descendant", "dataset-descendant"],
)
def test_runtime_stage_rejects_unsafe_protected_descendants(target: Path) -> None:
    assert not target.exists()

    with pytest.raises(ValueError, match="protected directory"):
        stage_runtime_package(target)

    assert not target.exists()


def test_runtime_verifier_recomputes_root_instead_of_trusting_manifest_field(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    manifest = _read_manifest(runtime_root)
    declared = str(manifest["sha256"])
    manifest["sha256"] = "0" * 64
    _write_manifest(runtime_root, manifest)

    with pytest.raises(RuntimeError, match="root checksum mismatch"):
        verify_runtime_package(runtime_root)

    assert declared != manifest["sha256"]


def test_runtime_verifier_rejects_whole_manifest_substitution(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    original_root = str(_read_manifest(runtime_root)["sha256"])
    changed_path = runtime_root / RUNTIME_GENERATOR_PACKAGE_DIR / "cli.py"
    changed_path.write_text("# substituted package\n", encoding="utf-8")
    manifest = _read_manifest(runtime_root)
    files = manifest["files"]
    assert isinstance(files, dict)
    relative_path = f"{RUNTIME_GENERATOR_PACKAGE_DIR}/cli.py"
    files[relative_path] = hashlib.sha256(changed_path.read_bytes()).hexdigest()
    manifest["sha256"] = canonical_runtime_package_sha256(files)
    _write_manifest(runtime_root, manifest)

    with pytest.raises(RuntimeError, match="expected root checksum mismatch"):
        verify_runtime_package(runtime_root, expected_sha256=original_root)


def test_runtime_verifier_rejects_unsafe_manifest_path(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    manifest = _read_manifest(runtime_root)
    files = manifest["files"]
    assert isinstance(files, dict)
    files["../outside.py"] = hashlib.sha256(b"outside").hexdigest()
    manifest["sha256"] = canonical_runtime_package_sha256(files)
    _write_manifest(runtime_root, manifest)

    with pytest.raises(RuntimeError, match="unsafe relative path"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_missing_manifest_entry(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    manifest = _read_manifest(runtime_root)
    files = manifest["files"]
    assert isinstance(files, dict)
    files.pop(f"{RUNTIME_GENERATOR_PACKAGE_DIR}/cli.py")
    manifest["sha256"] = canonical_runtime_package_sha256(files)
    _write_manifest(runtime_root, manifest)

    with pytest.raises(RuntimeError, match="file set mismatch"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_missing_package_file(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    (runtime_root / RUNTIME_GENERATOR_PACKAGE_DIR / "cli.py").unlink()

    with pytest.raises(RuntimeError, match="file set mismatch"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_extra_package_file(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    (runtime_root / RUNTIME_GENERATOR_PACKAGE_DIR / "extra.py").write_text(
        "# extra\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="file set mismatch"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_package_symlink(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    package_root = runtime_root / RUNTIME_GENERATOR_PACKAGE_DIR
    (package_root / "linked.py").symlink_to(package_root / "cli.py")

    with pytest.raises(RuntimeError, match="must not contain symlinks"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_case_colliding_paths(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    manifest = _read_manifest(runtime_root)
    files = manifest["files"]
    assert isinstance(files, dict)
    original_path = f"{RUNTIME_GENERATOR_PACKAGE_DIR}/cli.py"
    files[f"{RUNTIME_GENERATOR_PACKAGE_DIR}/CLI.py"] = files[original_path]
    manifest["sha256"] = canonical_runtime_package_sha256(files)
    _write_manifest(runtime_root, manifest)

    with pytest.raises(RuntimeError, match="case-colliding"):
        verify_runtime_package(runtime_root)


def test_runtime_verifier_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    stage_runtime_package(runtime_root)
    manifest_path = runtime_root / RUNTIME_MANIFEST_FILE
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace('"package":', '"package": "duplicate",\n  "package":', 1)
    )

    with pytest.raises(RuntimeError, match="duplicate key"):
        verify_runtime_package(runtime_root)


def test_notebook_runtime_verifier_rejects_manifest_map_substitution(
    tmp_path: Path,
) -> None:
    runtime_input = tmp_path / "openoppsdb-manager-runtime"
    stage_runtime_package(runtime_input)
    manifest = _read_manifest(runtime_input)
    original_root = str(manifest["sha256"])
    changed_path = runtime_input / RUNTIME_GENERATOR_PACKAGE_DIR / "cli.py"
    changed_path.write_text("# substituted package\n", encoding="utf-8")
    files = manifest["files"]
    assert isinstance(files, dict)
    files[f"{RUNTIME_GENERATOR_PACKAGE_DIR}/cli.py"] = hashlib.sha256(
        changed_path.read_bytes()
    ).hexdigest()
    # Preserve the trusted-looking top-level field: the verifier must derive the root.
    manifest["sha256"] = original_root
    _write_manifest(runtime_input, manifest)
    namespace = _notebook_setup_namespace(tmp_path, runtime_input=runtime_input)
    namespace["RUNTIME_PACKAGE_SHA256"] = original_root
    namespace["GENERATOR_SCRIPT_SHA256"] = original_root

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        namespace["download_runtime_package"]()


@pytest.mark.parametrize(
    "package_spec",
    [
        "",
        "__OPENOPPS_IMMUTABLE_PACKAGE_SPEC_REQUIRED__",
        "openopps",
        "openopps>=0.1.0",
        "git+https://github.com/wyattowalsh/openopps.git@main",
        "git+https://github.com/wyattowalsh/openopps.git@v0.1.0",
    ],
)
def test_manager_install_rejects_missing_or_mutable_package_specs(
    tmp_path: Path,
    package_spec: str,
) -> None:
    namespace = _notebook_setup_namespace(tmp_path)
    namespace["PACKAGE_SPEC"] = package_spec

    def fail_run(*args, **kwargs) -> None:
        del args, kwargs
        raise AssertionError("pip must not run for a mutable package spec")

    namespace["run"] = fail_run

    with pytest.raises(RuntimeError, match="immutable exact Git commit"):
        namespace["install_openopps"]()


def test_manager_install_accepts_exact_git_sha_and_pins_kaggle_client(
    tmp_path: Path,
) -> None:
    namespace = _notebook_setup_namespace(tmp_path)
    package_spec = (
        "git+https://github.com/wyattowalsh/openopps.git@"
        "0123456789abcdef0123456789abcdef01234567"
    )
    namespace["PACKAGE_SPEC"] = package_spec
    seen: list[list[str]] = []
    namespace["run"] = lambda command: seen.append(command)

    namespace["install_openopps"]()

    assert seen == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--upgrade",
            package_spec,
            "kaggle==2.2.4",
        ]
    ]
