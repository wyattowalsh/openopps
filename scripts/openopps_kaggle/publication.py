"""Fail-closed Kaggle publication planning, execution, and readback.

The default mode is a local dry run.  Live execution is available only through
an explicit ``--execute`` flag after an exact stage, tool version, prior
version, and rollback command have been recorded.  Commands are always passed
to ``subprocess`` as validated argv; this module never invokes a shell.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence, cast

from openopps_kaggle.constants import (
    DATASET_ID,
    DEFAULT_DATASET_DIR,
    NB_FILE,
    PUBLIC_UPLOAD_CONTROL_FILES,
    PUBLIC_UPLOAD_DATA_FILES,
    RUNTIME_GENERATOR_DATASET_ID,
    RUNTIME_GENERATOR_PACKAGE_DIR,
    RUNTIME_MANIFEST_FILE,
)

KAGGLE_CLI_VERSION = "2.2.4"
IMMUTABLE_PACKAGE_SPEC_PLACEHOLDER = "__OPENOPPS_IMMUTABLE_PACKAGE_SPEC_REQUIRED__"
IMMUTABLE_PACKAGE_SPEC_PREFIX = "git+https://github.com/wyattowalsh/openopps.git@"
IMMUTABLE_PACKAGE_SPEC_DEFAULT_SNIPPET = f'"{IMMUTABLE_PACKAGE_SPEC_PLACEHOLDER}",'
IMMUTABLE_PACKAGE_SPEC_IPYNB_DEFAULT_SNIPPET = (
    f'\\"{IMMUTABLE_PACKAGE_SPEC_PLACEHOLDER}\\",'
)
MANAGER_KERNEL_FILES = ("kernel-metadata.json", NB_FILE)
LEDGER_SCHEMA_VERSION = 1
MAX_LEDGER_ENTRIES = 100
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_CONTROL_JSON_BYTES = 16 * 1024 * 1024
MAX_KAGGLE_FILES = 200
# Kaggle consumes these at upload time and does not list or download them as files.
KAGGLE_DATASETS_UNLISTED_FILES = frozenset(PUBLIC_UPLOAD_CONTROL_FILES)
DEFAULT_LEDGER_PATH = Path("var/kaggle-publication-ledger.json")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}/[a-z0-9][a-z0-9_-]{0,49}$")
_ALLOWED_KINDS = {"public", "runtime"}
_ALLOWED_ACTIONS = {"create", "version"}
_READY_STATUSES = {"active", "complete", "ready"}
def kernel_paths() -> dict[str, tuple[Path, ...]]:
    from openopps_kaggle.generator import PUBLIC_EXAMPLE_NOTEBOOKS

    return {
        "manager": (Path("kaggle"),),
        "starter": (Path("kaggle/starter"),),
        "examples": (
            Path("kaggle/starter"),
            *(Path("kaggle/examples") / spec.slug for spec in PUBLIC_EXAMPLE_NOTEBOOKS),
        ),
    }
_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "KAGGLE_API_TOKEN",
    "KAGGLE_API_V1_TOKEN",
    "KAGGLE_API_V1_TOKEN_PATH",
    "KAGGLE_CONFIG_DIR",
    "KAGGLE_IAP_TOKEN",
    "KAGGLE_KEY",
    "KAGGLE_URL_BASE",
    "KAGGLE_USERNAME",
    "KAGGLE_USER_SECRETS_TOKEN",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TMPDIR",
    "USER",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
}


class PublicationError(RuntimeError):
    """Raised when a publication plan or proof is unsafe or incomplete."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical bytes used for publication identities."""

    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    """Hash a regular file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_publication_stage(stage_dir: Path, *, kind: str) -> dict[str, Any]:
    """Verify an exact public/runtime upload tree and return its identity."""

    kind = _validated_choice(kind, _ALLOWED_KINDS, "publication kind")
    raw_stage = stage_dir.expanduser()
    if raw_stage.is_symlink():
        raise PublicationError("publication stage must not be a symlink")
    stage = raw_stage.resolve()
    if not stage.is_dir():
        raise PublicationError(f"publication stage is not a directory: {stage}")

    expected_files = _expected_stage_files(stage, kind=kind)
    expected_dirs = {
        parent.as_posix()
        for relative_path in expected_files
        for parent in PurePosixPath(relative_path).parents
        if parent.as_posix() != "."
    }
    actual_files: dict[str, Path] = {}
    unexpected_dirs: list[str] = []
    casefolded: dict[str, str] = {}
    for path in stage.rglob("*"):
        relative_path = path.relative_to(stage).as_posix()
        _validate_relative_path(relative_path)
        prior = casefolded.get(relative_path.casefold())
        if prior is not None and prior != relative_path:
            raise PublicationError(
                f"publication stage contains case-colliding paths: {prior!r} and "
                f"{relative_path!r}"
            )
        casefolded[relative_path.casefold()] = relative_path
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise PublicationError(
                f"publication stage must not contain symlinks: {relative_path}"
            )
        if stat.S_ISREG(mode):
            actual_files[relative_path] = path
        elif stat.S_ISDIR(mode):
            if relative_path not in expected_dirs:
                unexpected_dirs.append(relative_path)
        else:
            raise PublicationError(
                "publication stage contains unsupported filesystem entry: "
                f"{relative_path}"
            )

    actual_set = set(actual_files)
    missing = sorted(expected_files - actual_set)
    extra = sorted(actual_set - expected_files)
    if missing or extra or unexpected_dirs:
        raise PublicationError(
            "publication stage file set mismatch: "
            f"missing={missing} extra={extra} "
            f"unexpected_dirs={sorted(unexpected_dirs)}"
        )

    files: list[dict[str, Any]] = []
    for relative_path, path in sorted(actual_files.items()):
        size = path.stat().st_size
        files.append(
            {
                "path": relative_path,
                "bytes": size,
                "sha256": sha256_file(path),
            }
        )

    _verify_control_metadata(stage, kind=kind)
    if kind == "runtime":
        from openopps_kaggle.runtime_manifest import verify_runtime_package

        try:
            verify_runtime_package(stage)
        except (FileNotFoundError, RuntimeError) as exc:
            raise PublicationError(str(exc)) from exc
    return {
        "sha256": hashlib.sha256(canonical_json_bytes({"files": files})).hexdigest(),
        "fileCount": len(files),
        "totalBytes": sum(int(item["bytes"]) for item in files),
        "files": files,
    }


def stage_publication(
    stage_dir: Path,
    *,
    kind: str,
    data_db: Path | None = None,
    allow_stale: bool = False,
    existing_stage: bool = False,
) -> dict[str, Any]:
    """Build or validate one exact stage without contacting Kaggle."""

    kind = _validated_choice(kind, _ALLOWED_KINDS, "publication kind")
    if existing_stage:
        if data_db is not None or allow_stale:
            raise PublicationError(
                "--existing-stage cannot be combined with --data-db or --allow-stale"
            )
        return verify_publication_stage(stage_dir, kind=kind)

    if kind == "runtime":
        if data_db is not None or allow_stale:
            raise PublicationError(
                "runtime publication does not accept --data-db or --allow-stale"
            )
        from openopps_kaggle.runtime_manifest import stage_runtime_package

        stage_runtime_package(stage_dir)
        return verify_publication_stage(stage_dir, kind=kind)

    if data_db is None and not allow_stale:
        raise PublicationError(
            "public publication requires --data-db; --allow-stale is an explicit "
            "dry-run/maintenance override"
        )
    if data_db is not None and allow_stale:
        raise PublicationError("--data-db and --allow-stale are mutually exclusive")
    if data_db is None:
        from openopps_kaggle._core import _stage_public_upload_dir

        _stage_public_upload_dir(DEFAULT_DATASET_DIR, stage_dir)
    else:
        _stage_fresh_public_bundle(data_db, stage_dir)
    return verify_publication_stage(stage_dir, kind=kind)


def prepare_publication(
    stage_dir: Path,
    ledger_path: Path,
    *,
    kind: str,
    action: str,
    message: str,
    expected_current_version: int | None,
    recorded_at: str,
    execute: bool = False,
    allow_no_rollback: bool = False,
    timeout_seconds: int = 1800,
    poll_seconds: int = 15,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Record a staged plan and optionally perform one mutation plus readback."""

    kind = _validated_choice(kind, _ALLOWED_KINDS, "publication kind")
    action = _validated_choice(action, _ALLOWED_ACTIONS, "publication action")
    message = _validated_message(message)
    expected_current_version = _validated_expected_version(
        expected_current_version, action=action
    )
    if timeout_seconds < 30 or timeout_seconds > 7200:
        raise PublicationError("timeout seconds must be between 30 and 7200")
    if poll_seconds < 1 or poll_seconds > min(timeout_seconds, 300):
        raise PublicationError("poll seconds must be between 1 and 300")
    if execute and action == "version" and expected_current_version is None:
        raise PublicationError(
            "live version publication requires --expected-current-version"
        )
    if execute and action == "create" and not allow_no_rollback:
        raise PublicationError(
            "live create has no prior rollback target; pass --allow-no-rollback "
            "only for an intentional first publication"
        )

    stage_identity = verify_publication_stage(stage_dir, kind=kind)
    kaggle_version = require_kaggle_cli_version()
    dataset_id = _dataset_id_for_kind(kind)
    published_version = (
        1 if action == "create" else _required_int(expected_current_version) + 1
    )
    commands = _publication_commands(
        kind=kind,
        action=action,
        dataset_id=dataset_id,
        expected_current_version=expected_current_version,
        published_version=published_version,
    )
    plan_identity = {
        "kind": kind,
        "action": action,
        "datasetId": dataset_id,
        "expectedBundleSha256": stage_identity["sha256"],
        "expectedCurrentVersion": expected_current_version,
        "expectedPublishedVersion": published_version,
        "kaggleCliVersion": kaggle_version,
        "messageSha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
    }
    plan_id = hashlib.sha256(canonical_json_bytes(plan_identity)).hexdigest()
    entry: dict[str, Any] = {
        "planId": plan_id,
        "recordedAt": canonical_utc_timestamp(recorded_at),
        **plan_identity,
        "messageBytes": len(message.encode("utf-8")),
        "expectedFiles": stage_identity["files"],
        "phase": "staged",
        "commands": commands,
        "readback": None,
        "error": None,
    }
    _upsert_ledger_entry(ledger_path, entry)
    if not execute:
        return {"ok": True, "dryRun": True, **entry}

    env = kaggle_subprocess_environment(environ)
    require_kaggle_credentials(env)
    try:
        with _immutable_publication_candidate(
            stage_dir,
            kind=kind,
            expected_identity=stage_identity,
        ) as mutation_stage:
            if action == "version":
                status = _read_status(
                    dataset_id, env=env, timeout_seconds=timeout_seconds
                )
                _require_status(
                    status,
                    expected_version=_required_int(expected_current_version),
                    label="preflight",
                )
                entry["phase"] = "preflight-verified"
                _upsert_ledger_entry(ledger_path, entry)

            mutation_argv = _mutation_argv(
                action=action,
                kind=kind,
                stage_dir=mutation_stage,
                message=message,
            )
            completed = _run_kaggle(
                mutation_argv,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            if completed.returncode != 0:
                raise PublicationError(
                    f"Kaggle mutation failed with exit code {completed.returncode}"
                )
            entry["phase"] = "mutated"
            _upsert_ledger_entry(ledger_path, entry)

            _wait_for_version(
                dataset_id,
                expected_version=published_version,
                env=env,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )
            readback = verify_remote_readback(
                mutation_stage,
                kind=kind,
                dataset_id=dataset_id,
                version_number=published_version,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            entry["phase"] = "readback-verified"
            entry["readback"] = {
                "version": published_version,
                "bundleSha256": readback["sha256"],
                "fileCount": readback["fileCount"],
                "totalBytes": readback["totalBytes"],
                "verifiedAt": canonical_utc_timestamp(datetime.now(UTC).isoformat()),
            }
            _upsert_ledger_entry(ledger_path, entry)
            return {"ok": True, "dryRun": False, **entry}
    except Exception as exc:
        entry["phase"] = (
            "readback-failed" if entry["phase"] == "mutated" else "preflight-failed"
        )
        entry["error"] = {"type": type(exc).__name__}
        _upsert_ledger_entry(ledger_path, entry)
        raise


@contextmanager
def _immutable_publication_candidate(
    stage_dir: Path,
    *,
    kind: str,
    expected_identity: Mapping[str, Any],
) -> Iterator[Path]:
    """Copy verified bytes into a private, read-only tree used for mutation."""

    source_root = stage_dir.expanduser().resolve()
    temporary_root = Path(tempfile.mkdtemp(prefix="openopps-kaggle-publication-"))
    candidate = temporary_root / "stage"
    candidate.mkdir(mode=0o700)
    try:
        raw_files = expected_identity.get("files")
        if not isinstance(raw_files, list):
            raise PublicationError("verified publication identity is missing files")
        for raw_entry in raw_files:
            if not isinstance(raw_entry, dict):
                raise PublicationError("verified publication file identity is invalid")
            relative_path = raw_entry.get("path")
            expected_bytes = raw_entry.get("bytes")
            expected_sha256 = raw_entry.get("sha256")
            if (
                not isinstance(relative_path, str)
                or type(expected_bytes) is not int
                or expected_bytes < 0
                or not isinstance(expected_sha256, str)
                or _SHA256_RE.fullmatch(expected_sha256) is None
            ):
                raise PublicationError("verified publication file identity is invalid")
            _validate_relative_path(relative_path)
            source = source_root / relative_path
            destination = candidate / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                source_fd = os.open(source, flags)
            except OSError as exc:
                raise PublicationError(
                    f"verified publication source cannot be opened safely: {relative_path}"
                ) from exc
            digest = hashlib.sha256()
            copied_bytes = 0
            try:
                source_stat = os.fstat(source_fd)
                if not stat.S_ISREG(source_stat.st_mode):
                    raise PublicationError(
                        f"verified publication source is not a regular file: {relative_path}"
                    )
                with os.fdopen(source_fd, "rb", closefd=False) as source_handle:
                    with destination.open("xb") as destination_handle:
                        while chunk := source_handle.read(1024 * 1024):
                            destination_handle.write(chunk)
                            digest.update(chunk)
                            copied_bytes += len(chunk)
            finally:
                os.close(source_fd)
            if copied_bytes != expected_bytes or digest.hexdigest() != expected_sha256:
                raise PublicationError(
                    f"publication stage changed while snapshotting: {relative_path}"
                )
            destination.chmod(0o400)

        candidate_identity = verify_publication_stage(candidate, kind=kind)
        if candidate_identity != expected_identity:
            raise PublicationError(
                "publication stage changed while creating the immutable candidate"
            )
        for path in sorted(candidate.rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o500)
        candidate.chmod(0o500)
        yield candidate
    finally:
        if temporary_root.exists():
            for path in temporary_root.rglob("*"):
                if path.is_dir():
                    path.chmod(0o700)
                elif path.is_file():
                    path.chmod(0o600)
            shutil.rmtree(temporary_root)


def verify_remote_readback(
    expected_stage: Path,
    *,
    kind: str,
    dataset_id: str,
    version_number: int,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Download and hash every immutable-version file using bounded disk."""

    expected = verify_publication_stage(expected_stage, kind=kind)
    expected_files = {item["path"]: item for item in expected["files"]}
    expected_listed = listed_publication_files(expected_files)
    version_handle = kaggle_cli_versioned_dataset(dataset_id, version_number)
    listing = _run_kaggle(
        [
            "datasets",
            "files",
            version_handle,
            "--format",
            "json",
            "--page-size",
            str(MAX_KAGGLE_FILES),
        ],
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if listing.returncode != 0:
        raise PublicationError(
            f"Kaggle file-list readback failed with exit code {listing.returncode}"
        )
    remote_files = _parse_file_listing(listing.stdout)
    remote_map = {item["name"]: item for item in remote_files}
    if set(remote_map) != set(expected_listed):
        raise PublicationError(
            "Kaggle readback file set mismatch: "
            f"missing={sorted(set(expected_listed) - set(remote_map))} "
            f"extra={sorted(set(remote_map) - set(expected_listed))}"
        )
    for relative_path, item in expected_listed.items():
        if int(remote_map[relative_path]["size"]) != int(item["bytes"]):
            raise PublicationError(
                f"Kaggle readback size mismatch for {relative_path}: "
                f"expected={item['bytes']} actual={remote_map[relative_path]['size']}"
            )

    read_files: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="openopps-kaggle-readback-") as raw_tmp:
        readback_root = Path(raw_tmp)
        for relative_path, expected_item in sorted(expected_files.items()):
            if relative_path in KAGGLE_DATASETS_UNLISTED_FILES:
                read_files.append(dict(expected_item))
                continue
            _clear_directory(readback_root)
            completed = _run_kaggle(
                [
                    "datasets",
                    "download",
                    version_handle,
                    "--file",
                    relative_path,
                    "--path",
                    str(readback_root),
                    "--force",
                    "--quiet",
                ],
                env=env,
                timeout_seconds=timeout_seconds,
            )
            if completed.returncode != 0:
                raise PublicationError(
                    "Kaggle file readback failed for "
                    f"{relative_path} with exit code {completed.returncode}"
                )
            downloaded = _single_downloaded_file(readback_root)
            actual_size = downloaded.stat().st_size
            actual_sha256 = sha256_file(downloaded)
            if actual_size != int(expected_item["bytes"]):
                raise PublicationError(
                    f"Kaggle readback size mismatch for {relative_path}"
                )
            if actual_sha256 != expected_item["sha256"]:
                raise PublicationError(
                    f"Kaggle readback SHA-256 mismatch for {relative_path}"
                )
            read_files.append(dict(expected_item))
    identity = {
        "sha256": hashlib.sha256(
            canonical_json_bytes({"files": read_files})
        ).hexdigest(),
        "fileCount": len(read_files),
        "totalBytes": sum(int(item["bytes"]) for item in read_files),
        "files": read_files,
    }
    if identity["sha256"] != expected["sha256"]:
        raise PublicationError("Kaggle readback bundle digest mismatch")
    return identity


def resolve_immutable_package_spec(*, repo: Path | None = None) -> str:
    """Return the exact git+SHA package spec for a manager kernel push."""

    revision = _git_head_sha(repo)
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise PublicationError(
            "manager kernel push requires a 40-character HEAD commit SHA"
        )
    return f"{IMMUTABLE_PACKAGE_SPEC_PREFIX}{revision}"


def _git_head_sha(repo: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=None if repo is None else str(repo),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise PublicationError("unable to resolve git HEAD for manager kernel push")
    return completed.stdout.strip().lower()


def _require_manager_push_git_state(*, repo: Path | None = None) -> None:
    porcelain = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "kaggle/openoppsdb-manager.ipynb",
            "kaggle/kernel-metadata.json",
        ],
        cwd=None if repo is None else str(repo),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if porcelain.returncode != 0:
        raise PublicationError("unable to inspect manager notebook git state")
    if porcelain.stdout.strip():
        raise PublicationError(
            "manager kernel execute requires a clean generated notebook"
        )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        cwd=None if repo is None else str(repo),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if ancestor.returncode != 0:
        raise PublicationError(
            "manager kernel execute requires HEAD to be an ancestor of origin/main"
        )


def _stage_manager_kernel_bundle(stage_dir: Path, package_spec: str) -> None:
    source_dir = Path("kaggle")
    stage_dir.mkdir(parents=True, exist_ok=True)
    for name in MANAGER_KERNEL_FILES:
        source = source_dir / name
        if not source.is_file():
            raise PublicationError(f"manager kernel file is missing: {name}")
        shutil.copy2(source, stage_dir / name)
    notebook_path = stage_dir / NB_FILE
    rendered = notebook_path.read_text(encoding="utf-8")
    default_hits = rendered.count(IMMUTABLE_PACKAGE_SPEC_IPYNB_DEFAULT_SNIPPET)
    placeholder_hits = rendered.count(IMMUTABLE_PACKAGE_SPEC_PLACEHOLDER)
    if default_hits != 1 or placeholder_hits < 3:
        raise PublicationError(
            "manager notebook must contain exactly one package-spec default "
            "assignment and keep the load-secret sentinels as the placeholder"
        )
    baked = rendered.replace(
        IMMUTABLE_PACKAGE_SPEC_IPYNB_DEFAULT_SNIPPET,
        f'\\"{package_spec}\\",',
        1,
    )
    if (
        baked.count(IMMUTABLE_PACKAGE_SPEC_PLACEHOLDER) != placeholder_hits - 1
        or package_spec not in baked
        or IMMUTABLE_PACKAGE_SPEC_IPYNB_DEFAULT_SNIPPET in baked
    ):
        raise PublicationError(
            "manager kernel bake must replace only the package-spec default"
        )
    notebook_path.write_text(baked, encoding="utf-8")


def run_kernel_push(
    bundle: str,
    *,
    timeout_seconds: int,
    execute: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Render or execute allowlisted kernel pushes without a shell."""

    paths = kernel_paths()
    if bundle not in paths:
        raise PublicationError(f"unsupported Kaggle kernel bundle: {bundle!r}")
    if timeout_seconds < 30 or timeout_seconds > 7200:
        raise PublicationError("kernel timeout must be between 30 and 7200 seconds")
    require_kaggle_cli_version()
    if bundle != "manager":
        commands = [
            [
                "kaggle",
                "kernels",
                "push",
                "--path",
                path.as_posix(),
                "--timeout",
                str(timeout_seconds),
            ]
            for path in paths[bundle]
        ]
        payload: dict[str, Any] = {
            "ok": True,
            "dryRun": not execute,
            "bundle": bundle,
            "kaggleCliVersion": KAGGLE_CLI_VERSION,
            "commands": commands,
        }
        if not execute:
            return payload
        env = kaggle_subprocess_environment(environ)
        require_kaggle_credentials(env)
        for command in commands:
            completed = _run_kaggle(
                command[1:], env=env, timeout_seconds=timeout_seconds
            )
            if completed.returncode != 0:
                raise PublicationError(
                    f"Kaggle kernel push failed with exit code {completed.returncode}"
                )
        payload["dryRun"] = False
        return payload

    package_spec = resolve_immutable_package_spec()
    if execute:
        _require_manager_push_git_state()
    with tempfile.TemporaryDirectory(prefix="openopps-kaggle-manager-kernel-") as raw:
        staged = Path(raw) / "manager"
        _stage_manager_kernel_bundle(staged, package_spec)
        commands = [
            [
                "kaggle",
                "kernels",
                "push",
                "--path",
                staged.as_posix(),
                "--timeout",
                str(timeout_seconds),
            ]
        ]
        payload = {
            "ok": True,
            "dryRun": not execute,
            "bundle": bundle,
            "kaggleCliVersion": KAGGLE_CLI_VERSION,
            "commands": commands,
            "packageSpec": package_spec,
        }
        if not execute:
            return payload
        env = kaggle_subprocess_environment(environ)
        require_kaggle_credentials(env)
        completed = _run_kaggle(commands[0][1:], env=env, timeout_seconds=timeout_seconds)
        if completed.returncode != 0:
            raise PublicationError(
                f"Kaggle kernel push failed with exit code {completed.returncode}"
            )
        payload["dryRun"] = False
        return payload


def kaggle_subprocess_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the explicit environment passed to Kaggle subprocesses."""

    source = os.environ if environ is None else environ
    result: dict[str, str] = {}
    for key in sorted(_ENV_ALLOWLIST):
        value = source.get(key)
        if value is None:
            continue
        if "\x00" in key or "\x00" in value:
            raise PublicationError(f"environment value for {key} contains NUL")
        result[key] = value
    if not result.get("PATH"):
        raise PublicationError("PATH is required to invoke the pinned Kaggle CLI")
    return result


def require_kaggle_cli_version() -> str:
    """Require the lock-controlled exact Kaggle CLI version."""

    try:
        installed = version("kaggle")
    except PackageNotFoundError as exc:
        raise PublicationError("the pinned Kaggle CLI is not installed") from exc
    if installed != KAGGLE_CLI_VERSION:
        raise PublicationError(
            f"Kaggle CLI must be exactly {KAGGLE_CLI_VERSION}; found {installed}"
        )
    return installed


def require_kaggle_credentials(environ: Mapping[str, str]) -> None:
    """Require credential presence without reading or serializing secret values."""

    if environ.get("KAGGLE_API_TOKEN") or (
        environ.get("KAGGLE_USERNAME") and environ.get("KAGGLE_KEY")
    ):
        return
    candidates: list[Path] = []
    for key in ("KAGGLE_API_V1_TOKEN", "KAGGLE_API_V1_TOKEN_PATH"):
        if raw_path := environ.get(key):
            candidates.append(Path(raw_path).expanduser())
    if raw_config := environ.get("KAGGLE_CONFIG_DIR"):
        candidates.append(Path(raw_config).expanduser() / "kaggle.json")
    if raw_home := environ.get("HOME"):
        kaggle_home = Path(raw_home).expanduser() / ".kaggle"
        candidates.extend(
            (
                kaggle_home / "access_token",
                kaggle_home / "access_token.txt",
                kaggle_home / "kaggle.json",
            )
        )
    for candidate in candidates:
        if (
            not candidate.is_symlink()
            and candidate.is_file()
            and candidate.stat().st_size > 0
        ):
            return
    raise PublicationError(
        "Kaggle credentials are required for --execute; configure an access "
        "token or a regular credential file without placing it in the ledger"
    )


def canonical_utc_timestamp(value: str) -> str:
    """Validate and normalize an aware timestamp to seconds in UTC."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError("recorded timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PublicationError("recorded timestamp must include a timezone")
    return (
        parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _stage_fresh_public_bundle(data_db: Path, stage_dir: Path) -> None:
    raw_db = data_db.expanduser()
    if raw_db.is_symlink():
        raise PublicationError("public publication database must not be a symlink")
    db_path = raw_db.resolve()
    if not db_path.is_file():
        raise PublicationError(f"public publication database is missing: {db_path}")
    if not stat.S_ISREG(db_path.lstat().st_mode):
        raise PublicationError("public publication database must be a regular file")
    from openopps_kaggle._core import (
        _prune_private_upload_files,
        _stage_public_upload_dir,
        _write_data_artifacts,
        _write_dataset_image,
        _write_json,
        dataset_metadata,
    )

    with tempfile.TemporaryDirectory(prefix="openopps-kaggle-bundle-") as raw_tmp:
        bundle_dir = Path(raw_tmp) / "bundle"
        bundle_dir.mkdir()
        _write_data_artifacts(bundle_dir, db_path)
        _write_dataset_image(bundle_dir)
        _prune_private_upload_files(bundle_dir)
        _write_json(bundle_dir / "dataset-metadata.json", dataset_metadata())
        _stage_public_upload_dir(bundle_dir, stage_dir)


def _expected_stage_files(stage: Path, *, kind: str) -> set[str]:
    if kind == "public":
        return set(PUBLIC_UPLOAD_CONTROL_FILES + PUBLIC_UPLOAD_DATA_FILES)
    manifest_path = stage / RUNTIME_MANIFEST_FILE
    manifest = _read_json_object(manifest_path, label=RUNTIME_MANIFEST_FILE)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PublicationError("runtime manifest must contain a non-empty files map")
    expected = {"dataset-metadata.json", RUNTIME_MANIFEST_FILE}
    for raw_path in files:
        if not isinstance(raw_path, str):
            raise PublicationError("runtime manifest file paths must be strings")
        _validate_relative_path(raw_path)
        if PurePosixPath(raw_path).parts[0] != RUNTIME_GENERATOR_PACKAGE_DIR:
            raise PublicationError("runtime manifest file is outside package root")
        expected.add(raw_path)
    return expected


def _verify_control_metadata(stage: Path, *, kind: str) -> None:
    metadata = _read_json_object(
        stage / "dataset-metadata.json", label="dataset-metadata.json"
    )
    expected_id = _dataset_id_for_kind(kind)
    if metadata.get("id") != expected_id:
        raise PublicationError(
            f"dataset-metadata.json id must be exactly {expected_id!r}"
        )
    expected_private = kind == "runtime"
    if metadata.get("isPrivate") is not expected_private:
        raise PublicationError(
            "dataset-metadata.json privacy must match publication kind: "
            f"expected isPrivate={expected_private}"
        )
    if kind == "public":
        db_path = stage / "openoppsdb.sqlite"
        with db_path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise PublicationError("public stage SQLite header is invalid")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PublicationError(f"{label} must be a regular file")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    if path.stat().st_size > MAX_CONTROL_JSON_BYTES:
        raise PublicationError(f"{label} exceeds the bounded JSON size limit")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PublicationError(f"{label} must contain a JSON object")
    return value


def _validate_relative_path(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if (
        not relative_path
        or len(relative_path.encode("utf-8")) > 1024
        or "\\" in relative_path
        or "\x00" in relative_path
        or "%" in relative_path
        or ":" in relative_path
        or path.is_absolute()
        or path.as_posix() != relative_path
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(not part.isascii() for part in path.parts)
    ):
        raise PublicationError(f"unsafe publication relative path: {relative_path!r}")


def _dataset_id_for_kind(kind: str) -> str:
    return DATASET_ID if kind == "public" else RUNTIME_GENERATOR_DATASET_ID


def _validated_dataset_id(value: str) -> str:
    if _DATASET_ID_RE.fullmatch(value) is None:
        raise PublicationError(f"invalid Kaggle dataset ID: {value!r}")
    return value


def listed_publication_files(expected_files: Mapping[str, Any]) -> dict[str, Any]:
    """Return staged files that Kaggle exposes through `datasets files`."""

    return {
        path: item
        for path, item in expected_files.items()
        if path not in KAGGLE_DATASETS_UNLISTED_FILES
    }


def kaggle_cli_versioned_dataset(dataset_id: str, version_number: int) -> str:
    """Return the pinned-CLI handle `{owner}/{slug}/{version}` (not `/versions/N`)."""

    validated = _validated_dataset_id(dataset_id)
    try:
        version = int(version_number)
    except (TypeError, ValueError) as exc:
        raise PublicationError("dataset version must be a positive integer") from exc
    if version < 1:
        raise PublicationError("dataset version must be a positive integer")
    return f"{validated}/{version}"


def _validated_choice(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise PublicationError(f"{label} must be one of {sorted(allowed)!r}")
    return value


def _validated_message(message: str) -> str:
    encoded = message.encode("utf-8")
    if not message.strip() or len(encoded) > 200:
        raise PublicationError("publication message must contain 1-200 UTF-8 bytes")
    if any(ord(character) < 32 or ord(character) == 127 for character in message):
        raise PublicationError(
            "publication message must not contain control characters"
        )
    return message


def _validated_expected_version(value: int | None, *, action: str) -> int | None:
    if value is None:
        return None
    if action == "create":
        raise PublicationError("create publication does not accept a prior version")
    if value < 1:
        raise PublicationError("expected current version must be a positive integer")
    return value


def _required_int(value: int | None) -> int:
    if value is None:
        raise PublicationError("required integer is missing")
    return value


def _dataset_version_handle(
    dataset_id: str, version_number: int, *, style: str = "cli"
) -> str:
    if style == "legacy-url":
        validated = _validated_dataset_id(dataset_id)
        try:
            version = int(version_number)
        except (TypeError, ValueError) as exc:
            raise PublicationError("dataset version must be a positive integer") from exc
        if version < 1:
            raise PublicationError("dataset version must be a positive integer")
        return f"{validated}/versions/{version}"
    if style != "cli":
        raise PublicationError(f"unsupported dataset version handle style: {style!r}")
    return kaggle_cli_versioned_dataset(dataset_id, version_number)


def _publication_commands(
    *,
    kind: str,
    action: str,
    dataset_id: str,
    expected_current_version: int | None,
    published_version: int,
    handle_style: str = "cli",
) -> dict[str, Any]:
    mutation = ["kaggle", "datasets", action, "--path", "{STAGE_DIR}"]
    if action == "create" and kind == "public":
        mutation.extend(["--public"])
    else:
        mutation.extend(["--message", "{MESSAGE}"])
    mutation.extend(["--quiet", "--keep-tabular", "--dir-mode", "zip"])
    readback_handle = _dataset_version_handle(
        dataset_id, published_version, style=handle_style
    )
    rollback: dict[str, Any] | None = None
    if expected_current_version is not None:
        rollback_handle = _dataset_version_handle(
            dataset_id, expected_current_version, style=handle_style
        )
        rollback = {
            "targetVersion": expected_current_version,
            "downloadArgv": [
                "kaggle",
                "datasets",
                "download",
                rollback_handle,
                "--path",
                "{ROLLBACK_STAGE_DIR}",
                "--unzip",
                "--force",
                "--quiet",
            ],
            "publishArgv": [
                "kaggle",
                "datasets",
                "version",
                "--path",
                "{ROLLBACK_STAGE_DIR}",
                "--message",
                f"Rollback to immutable Kaggle version {expected_current_version}",
                "--quiet",
                "--keep-tabular",
                "--dir-mode",
                "zip",
            ],
        }
    return {
        "preflightArgv": [
            "kaggle",
            "datasets",
            "status",
            dataset_id,
            "--format",
            "json",
        ],
        "mutationArgv": mutation,
        "readbackListArgv": [
            "kaggle",
            "datasets",
            "files",
            readback_handle,
            "--format",
            "json",
            "--page-size",
            str(MAX_KAGGLE_FILES),
        ],
        "readbackFileArgv": [
            "kaggle",
            "datasets",
            "download",
            readback_handle,
            "--file",
            "{RELATIVE_PATH}",
            "--path",
            "{READBACK_DIR}",
            "--force",
            "--quiet",
        ],
        "rollback": rollback,
    }


def _mutation_argv(
    *, kind: str, action: str, stage_dir: Path, message: str
) -> list[str]:
    argv = ["datasets", action, "--path", str(stage_dir.resolve())]
    if action == "create" and kind == "public":
        argv.append("--public")
    else:
        argv.extend(["--message", message])
    argv.extend(["--quiet", "--keep-tabular", "--dir-mode", "zip"])
    return argv


def _run_kaggle(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise PublicationError("Kaggle argv must contain non-NUL strings")
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *argv],
        check=False,
        capture_output=True,
        text=True,
        env=dict(env),
        timeout=timeout_seconds,
        shell=False,
    )


def _read_status(
    dataset_id: str, *, env: Mapping[str, str], timeout_seconds: int
) -> dict[str, Any]:
    completed = _run_kaggle(
        ["datasets", "status", dataset_id, "--format", "json"],
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0:
        raise PublicationError(
            f"Kaggle status failed with exit code {completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationError("Kaggle status did not return exact JSON") from exc
    if not isinstance(payload, dict):
        raise PublicationError("Kaggle status must return a JSON object")
    return payload


def _require_status(
    status: Mapping[str, Any], *, expected_version: int, label: str
) -> None:
    actual_version = _normalized_version_or_none(status.get("current_version_number"))
    if actual_version is None or actual_version < 1:
        raise PublicationError(f"{label} Kaggle version is invalid")
    if actual_version != expected_version:
        raise PublicationError(
            f"{label} Kaggle version mismatch: expected={expected_version} "
            f"actual={actual_version}"
        )
    raw_status = status.get("status")
    if not isinstance(raw_status, str) or raw_status.casefold() not in _READY_STATUSES:
        raise PublicationError(f"{label} Kaggle dataset is not ready")


def _wait_for_version(
    dataset_id: str,
    *,
    expected_version: int,
    env: Mapping[str, str],
    timeout_seconds: int,
    poll_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = _read_status(dataset_id, env=env, timeout_seconds=timeout_seconds)
        try:
            _require_status(status, expected_version=expected_version, label="readback")
            return
        except PublicationError:
            raw_version = _normalized_version_or_none(
                status.get("current_version_number")
            )
            if raw_version is not None and raw_version > expected_version:
                raise PublicationError(
                    "Kaggle advanced past the expected publication version"
                )
            if time.monotonic() >= deadline:
                raise PublicationError(
                    f"Kaggle version {expected_version} did not become ready in time"
                )
            time.sleep(poll_seconds)


def _parse_file_listing(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublicationError("Kaggle file listing did not return exact JSON") from exc
    if not isinstance(value, list) or len(value) > MAX_KAGGLE_FILES:
        raise PublicationError("Kaggle file listing has an invalid shape")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"name", "size", "creationDate"}:
            raise PublicationError("Kaggle file listing entry has an invalid shape")
        name = item.get("name")
        size = item.get("size")
        if not isinstance(name, str):
            raise PublicationError("Kaggle file listing name is invalid")
        _validate_relative_path(name)
        if name in seen:
            raise PublicationError(f"Kaggle file listing repeats {name!r}")
        seen.add(name)
        if isinstance(size, bool) or not isinstance(size, (int, str)):
            raise PublicationError("Kaggle file listing size is invalid")
        if isinstance(size, str) and not size.isdecimal():
            raise PublicationError("Kaggle file listing size is invalid")
        try:
            normalized_size = int(size)
        except (TypeError, ValueError) as exc:
            raise PublicationError("Kaggle file listing size is invalid") from exc
        if normalized_size < 0:
            raise PublicationError("Kaggle file listing size must not be negative")
        files.append({"name": name, "size": normalized_size})
    return files


def _single_downloaded_file(root: Path) -> Path:
    files: list[Path] = []
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise PublicationError("Kaggle readback produced a symlink")
        if stat.S_ISREG(mode):
            files.append(path)
        elif not stat.S_ISDIR(mode):
            raise PublicationError("Kaggle readback produced a special file")
    if len(files) != 1:
        raise PublicationError(f"Kaggle readback expected one file, found {len(files)}")
    return files[0]


def _clear_directory(root: Path) -> None:
    for entry in root.iterdir():
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)
        else:
            raise PublicationError("readback directory contains a special file")


def _upsert_ledger_entry(ledger_path: Path, entry: Mapping[str, Any]) -> None:
    _validate_ledger_entry(entry)
    ledger = _load_ledger(ledger_path)
    entries = [
        existing
        for existing in ledger["entries"]
        if existing["planId"] != entry["planId"]
    ]
    entries.append(dict(entry))
    if len(entries) > MAX_LEDGER_ENTRIES:
        entries = entries[-MAX_LEDGER_ENTRIES:]
    _atomic_write_json(
        ledger_path,
        {"schemaVersion": LEDGER_SCHEMA_VERSION, "entries": entries},
    )


def _load_ledger(ledger_path: Path) -> dict[str, Any]:
    ledger_path = _validated_ledger_path(ledger_path)
    if not ledger_path.exists():
        return {"schemaVersion": LEDGER_SCHEMA_VERSION, "entries": []}
    if ledger_path.stat().st_size > MAX_LEDGER_BYTES:
        raise PublicationError("publication ledger exceeds the bounded size limit")
    value = _read_json_object(ledger_path, label="publication ledger")
    if set(value) != {"schemaVersion", "entries"}:
        raise PublicationError("publication ledger schema is invalid")
    if value.get("schemaVersion") != LEDGER_SCHEMA_VERSION:
        raise PublicationError("publication ledger version is unsupported")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_LEDGER_ENTRIES:
        raise PublicationError("publication ledger entries are invalid")
    seen: set[str] = set()
    for entry in entries:
        _validate_ledger_entry(entry)
        plan_id = entry["planId"]
        if plan_id in seen:
            raise PublicationError("publication ledger repeats a plan ID")
        seen.add(plan_id)
    return value


def _validate_ledger_entry(entry: object) -> None:
    expected_keys = {
        "planId",
        "recordedAt",
        "kind",
        "action",
        "datasetId",
        "expectedBundleSha256",
        "expectedCurrentVersion",
        "expectedPublishedVersion",
        "kaggleCliVersion",
        "messageSha256",
        "messageBytes",
        "expectedFiles",
        "phase",
        "commands",
        "readback",
        "error",
    }
    if not isinstance(entry, dict) or set(entry) != expected_keys:
        raise PublicationError("publication ledger entry schema is invalid")
    entry_map = cast(dict[str, Any], entry)
    for key in ("planId", "expectedBundleSha256", "messageSha256"):
        value = entry_map.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise PublicationError(f"publication ledger {key} is invalid")
    if canonical_utc_timestamp(str(entry_map.get("recordedAt"))) != entry_map.get(
        "recordedAt"
    ):
        raise PublicationError("publication ledger timestamp is not canonical")
    kind = _validated_choice(str(entry_map.get("kind")), _ALLOWED_KINDS, "ledger kind")
    action = _validated_choice(
        str(entry_map.get("action")), _ALLOWED_ACTIONS, "ledger action"
    )
    dataset_id = _validated_dataset_id(str(entry_map.get("datasetId")))
    if dataset_id != _dataset_id_for_kind(kind):
        raise PublicationError("publication ledger dataset does not match its kind")
    if entry_map.get("kaggleCliVersion") != KAGGLE_CLI_VERSION:
        raise PublicationError("publication ledger Kaggle version is invalid")
    files = entry_map.get("expectedFiles")
    if not isinstance(files, list) or not files or len(files) > MAX_KAGGLE_FILES:
        raise PublicationError("publication ledger expected files are invalid")
    normalized_files: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for raw_item in files:
        if not isinstance(raw_item, dict) or set(raw_item) != {
            "path",
            "bytes",
            "sha256",
        }:
            raise PublicationError("publication ledger file entry is invalid")
        item = cast(dict[str, Any], raw_item)
        _validate_relative_path(str(item.get("path")))
        if item["path"] in seen_files:
            raise PublicationError("publication ledger repeats an expected file")
        seen_files.add(item["path"])
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise PublicationError("publication ledger file size is invalid")
        if (
            not isinstance(item.get("sha256"), str)
            or _SHA256_RE.fullmatch(item["sha256"]) is None
        ):
            raise PublicationError("publication ledger file digest is invalid")
        normalized_files.append(dict(item))
    if normalized_files != sorted(normalized_files, key=lambda item: item["path"]):
        raise PublicationError("publication ledger files must be sorted")
    bundle_sha = hashlib.sha256(
        canonical_json_bytes({"files": normalized_files})
    ).hexdigest()
    if bundle_sha != entry_map["expectedBundleSha256"]:
        raise PublicationError("publication ledger bundle digest is inconsistent")
    expected_current = entry_map.get("expectedCurrentVersion")
    if expected_current is not None and (
        isinstance(expected_current, bool)
        or not isinstance(expected_current, int)
        or expected_current < 1
    ):
        raise PublicationError("publication ledger prior version is invalid")
    expected_published = entry_map.get("expectedPublishedVersion")
    if (
        isinstance(expected_published, bool)
        or not isinstance(expected_published, int)
        or expected_published < 1
        or expected_published
        != (1 if action == "create" else _required_int(expected_current) + 1)
    ):
        raise PublicationError("publication ledger published version is inconsistent")
    if action == "create" and expected_current is not None:
        raise PublicationError(
            "publication create ledger must not have a prior version"
        )
    message_bytes = entry_map.get("messageBytes")
    if (
        isinstance(message_bytes, bool)
        or not isinstance(message_bytes, int)
        or not 1 <= message_bytes <= 200
    ):
        raise PublicationError("publication ledger message length is invalid")
    allowed_commands = (
        _publication_commands(
            kind=kind,
            action=action,
            dataset_id=dataset_id,
            expected_current_version=expected_current,
            published_version=expected_published,
        ),
        _publication_commands(
            kind=kind,
            action=action,
            dataset_id=dataset_id,
            expected_current_version=expected_current,
            published_version=expected_published,
            handle_style="legacy-url",
        ),
    )
    if entry_map.get("commands") not in allowed_commands:
        raise PublicationError("publication ledger commands are inconsistent")
    if entry_map.get("phase") not in {
        "staged",
        "preflight-verified",
        "mutated",
        "readback-verified",
        "preflight-failed",
        "readback-failed",
    }:
        raise PublicationError("publication ledger phase is invalid")
    readback = entry_map.get("readback")
    if readback is not None:
        if (
            not isinstance(readback, dict)
            or set(readback)
            != {
                "version",
                "bundleSha256",
                "fileCount",
                "totalBytes",
                "verifiedAt",
            }
            or readback.get("version") != expected_published
            or readback.get("bundleSha256") != bundle_sha
            or readback.get("fileCount") != len(normalized_files)
            or readback.get("totalBytes")
            != sum(int(item["bytes"]) for item in normalized_files)
            or canonical_utc_timestamp(str(readback.get("verifiedAt")))
            != readback.get("verifiedAt")
        ):
            raise PublicationError("publication ledger readback is invalid")
    error = entry_map.get("error")
    if error is not None:
        if not isinstance(error, dict) or set(error) != {"type"}:
            raise PublicationError("publication ledger error is invalid")
        error_map = cast(dict[str, Any], error)
        error_type = error_map.get("type")
        if (
            not isinstance(error_type, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_type) is None
        ):
            raise PublicationError("publication ledger error is invalid")
    phase = cast(str, entry_map["phase"])
    if (phase == "readback-verified") != (readback is not None):
        raise PublicationError("publication ledger readback does not match its phase")
    if phase.endswith("failed") != (error is not None):
        raise PublicationError("publication ledger error does not match its phase")
    plan_identity = {
        "kind": kind,
        "action": action,
        "datasetId": dataset_id,
        "expectedBundleSha256": bundle_sha,
        "expectedCurrentVersion": expected_current,
        "expectedPublishedVersion": expected_published,
        "kaggleCliVersion": KAGGLE_CLI_VERSION,
        "messageSha256": entry_map["messageSha256"],
    }
    if (
        hashlib.sha256(canonical_json_bytes(plan_identity)).hexdigest()
        != entry_map["planId"]
    ):
        raise PublicationError("publication ledger plan ID is inconsistent")


def _normalized_version_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _atomic_write_json(path: Path, value: object) -> None:
    path = _validated_ledger_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True).encode(
                    "utf-8"
                )
                + b"\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _validated_ledger_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise PublicationError("publication ledger must not be a symlink")
    for parent in path.parents:
        if parent.is_symlink():
            raise PublicationError("publication ledger parent must not be a symlink")
    if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
        raise PublicationError("publication ledger must be a regular file")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--kind", choices=sorted(_ALLOWED_KINDS), required=True)
    publish.add_argument("--action", choices=sorted(_ALLOWED_ACTIONS), required=True)
    publish.add_argument("--message", required=True)
    publish.add_argument("--data-db", type=Path)
    publish.add_argument("--allow-stale", action="store_true")
    publish.add_argument("--stage-dir", type=Path)
    publish.add_argument("--existing-stage", action="store_true")
    publish.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    publish.add_argument("--expected-current-version", type=int)
    publish.add_argument("--recorded-at")
    publish.add_argument("--execute", action="store_true")
    publish.add_argument("--allow-no-rollback", action="store_true")
    publish.add_argument("--timeout-seconds", type=int, default=1800)
    publish.add_argument("--poll-seconds", type=int, default=15)
    kernel = subparsers.add_parser("kernel-push")
    kernel.add_argument("--bundle", choices=sorted(kernel_paths()), required=True)
    kernel.add_argument("--timeout-seconds", type=int, default=3600)
    kernel.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run local planning by default; live calls require explicit flags."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "kernel-push":
            payload = run_kernel_push(
                args.bundle,
                timeout_seconds=args.timeout_seconds,
                execute=args.execute,
            )
        else:
            recorded_at = args.recorded_at or datetime.now(UTC).isoformat()
            if args.stage_dir is None:
                with tempfile.TemporaryDirectory(
                    prefix="openopps-kaggle-publication-"
                ) as raw_stage:
                    payload = _stage_and_prepare(args, Path(raw_stage), recorded_at)
            else:
                payload = _stage_and_prepare(args, args.stage_dir, recorded_at)
    except (OSError, PublicationError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0


def _stage_and_prepare(
    args: argparse.Namespace, stage_dir: Path, recorded_at: str
) -> dict[str, Any]:
    stage_publication(
        stage_dir,
        kind=args.kind,
        data_db=args.data_db,
        allow_stale=args.allow_stale,
        existing_stage=args.existing_stage,
    )
    return prepare_publication(
        stage_dir,
        args.ledger,
        kind=args.kind,
        action=args.action,
        message=args.message,
        expected_current_version=args.expected_current_version,
        recorded_at=recorded_at,
        execute=args.execute,
        allow_no_rollback=args.allow_no_rollback,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
