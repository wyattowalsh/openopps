"""Safe, deterministic delivery tooling for immutable docs-search assets.

This module prepares assets-only Cloudflare Worker versions, verifies the exact
local and remote byte set, records Wrangler's machine output, and renders
rollout commands. It intentionally never executes Wrangler or GitHub commands.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path, PurePosixPath
from typing import IO, Any, Callable, Mapping, Sequence, cast
from urllib.parse import quote, urlsplit

import docs_search_release as release

WRANGLER_VERSION = "4.122.0"
DELIVERY_SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
ROLLOUT_SCHEMA_VERSION = 1
MAX_WORKER_FILES = 20_000
MAX_WORKER_FILE_BYTES = 24 * 1024 * 1024
MAX_ARCHIVE_METADATA_BYTES = 64 * 1024 * 1024
CONFIG_ENVIRONMENTS = ("staging", "production")
CONFIG_FILE = "wrangler.jsonc"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DELIVERY_ROOT = REPOSITORY_ROOT / "deployment" / "openopps-data"
CONFIG_ROOT = REPOSITORY_ROOT / "deployment" / "openopps-data"
HEADERS_CONTENT = """/*
  Access-Control-Allow-Origin: *
  X-Content-Type-Options: nosniff
  X-Robots-Tag: noindex, nofollow

/channels/*
  Cache-Control: public, max-age=0, must-revalidate

/releases/*
  Cache-Control: public, max-age=31536000, immutable
"""

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_CONFIG_KEYS = {
    "$schema",
    "name",
    "compatibility_date",
    "workers_dev",
    "preview_urls",
    "send_metrics",
    "assets",
}
_EXPECTED_ASSET_KEYS = {"directory", "html_handling", "not_found_handling"}


class DeliveryError(ValueError):
    """Raised when delivery input is unsafe, incomplete, or inconsistent."""


@dataclass(frozen=True)
class StageResult:
    """Identity and size of one verified staged Worker asset tree."""

    destination: Path
    current_release_id: str
    previous_release_id: str
    file_count: int
    total_bytes: int
    root_digest: str


@dataclass(frozen=True)
class RemoteResponse:
    """Minimal response surface required for remote readback verification."""

    status: int
    body: bytes
    headers: Mapping[str, str]
    final_url: str | None = None


@dataclass(frozen=True)
class RemoteReport:
    """Complete result of checking all served files and a missing-path probe."""

    checked_files: int
    missing_path: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class Invocation:
    """A shell-free subprocess contract for an operator or CI runner."""

    argv: list[str]
    env: dict[str, str]
    upload_candidate_root: Path
    upload_candidate_digest: str
    stage_root_digest: str
    current_release_id: str
    previous_release_id: str


@dataclass(frozen=True)
class RolloutAction:
    """The next validated rollout state and its exact Wrangler argv."""

    state: dict[str, Any]
    argv: list[str]


@dataclass(frozen=True)
class ArchiveResult:
    """Digest and size of a deterministic single-file recovery bundle."""

    path: Path
    asset_name: str
    sha256: str
    bytes: int
    stage_root_digest: str


@dataclass(frozen=True)
class _ArchiveFile:
    """Bounded metadata for one streamed archive member."""

    name: str
    path: Path
    bytes: int
    sha256: str


def validate_configs(config_root: Path) -> list[str]:
    """Return all drift from the two exact assets-only Worker configurations."""

    errors: list[str] = []
    for environment in CONFIG_ENVIRONMENTS:
        path = config_root / environment / CONFIG_FILE
        if not path.is_file() or path.is_symlink():
            errors.append(f"{environment}: missing regular config {path}")
            continue
        try:
            value = _read_json(path)
        except (json.JSONDecodeError, OSError, DeliveryError) as exc:
            errors.append(f"{environment}: invalid JSON config: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{environment}: config must be a JSON object")
            continue
        value = cast(dict[str, Any], value)
        unexpected = sorted(set(value) - _EXPECTED_CONFIG_KEYS)
        missing = sorted(_EXPECTED_CONFIG_KEYS - set(value))
        if unexpected:
            for key in unexpected:
                errors.append(
                    f"{environment}: forbidden or unexpected config key {key!r}"
                )
        if missing:
            errors.append(f"{environment}: missing config keys {missing!r}")
        expected_name = f"openopps-data-{environment}"
        if value.get("name") != expected_name:
            errors.append(f"{environment}: name must be {expected_name!r}")
        expected_schema = "../../../web/node_modules/wrangler/config-schema.json"
        if value.get("$schema") != expected_schema:
            errors.append(f"{environment}: $schema must be {expected_schema!r}")
        if value.get("compatibility_date") != "2026-08-12":
            errors.append(f"{environment}: compatibility_date drifted")
        for key, expected in (
            ("workers_dev", True),
            ("preview_urls", False),
            ("send_metrics", False),
        ):
            if value.get(key) is not expected:
                errors.append(f"{environment}: {key} must be {expected!r}")
        assets = value.get("assets")
        if not isinstance(assets, dict):
            errors.append(f"{environment}: assets must be an object")
            continue
        if set(assets) != _EXPECTED_ASSET_KEYS:
            errors.append(
                f"{environment}: assets must contain exactly "
                f"{sorted(_EXPECTED_ASSET_KEYS)!r}"
            )
        if assets.get("directory") != "./assets":
            errors.append(f"{environment}: assets.directory must be './assets'")
        if assets.get("html_handling") != "none":
            errors.append(f"{environment}: assets.html_handling must be 'none'")
        if assets.get("not_found_handling") != "none":
            errors.append(f"{environment}: assets.not_found_handling must be 'none'")
        if "binding" in assets or "run_worker_first" in assets:
            errors.append(
                f"{environment}: assets binding and run_worker_first are forbidden"
            )
    return errors


def stage_publication(publication_root: Path, destination: Path) -> StageResult:
    """Atomically stage exactly current + previous releases and one pointer."""

    publication_root = publication_root.resolve()
    destination = destination.absolute()
    _validate_owned_destination(destination)
    source_errors = _production_publication_errors(publication_root)
    if source_errors:
        raise DeliveryError(
            "source publication is invalid: " + "; ".join(source_errors)
        )
    pointer = _read_pointer(publication_root)
    current = _require_release_id(pointer.get("releaseId"), "current release ID")
    previous = _require_release_id(pointer.get("priorReleaseId"), "prior release ID")
    if current == previous:
        raise DeliveryError("current and prior releases must be distinct")

    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.candidate-", dir=destination.parent
        )
    )
    try:
        for release_id in (current, previous):
            source = publication_root / "releases" / release_id
            shutil.copytree(
                source,
                candidate / "releases" / release_id,
                copy_function=shutil.copy2,
            )
        channel_root = candidate / "channels"
        channel_root.mkdir(parents=True)
        shutil.copy2(
            publication_root / "channels" / "production.json",
            channel_root / "production.json",
        )
        (candidate / "_headers").write_text(HEADERS_CONTENT, encoding="utf-8")
        errors = verify_stage(candidate)
        if errors:
            raise DeliveryError("staged publication is invalid: " + "; ".join(errors))
        result = _stage_result(candidate, destination=destination)
        _atomic_replace_directory(candidate, destination)
        candidate = Path()
        return result
    finally:
        if candidate != Path() and candidate.exists():
            shutil.rmtree(candidate)


def verify_stage(stage_root: Path) -> list[str]:
    """Verify closure, hashes, platform limits, headers, and dual-release scope."""

    if stage_root.is_symlink():
        return [f"stage root must not be a symlink: {stage_root}"]
    if not stage_root.is_dir():
        return [f"stage root is not a directory: {stage_root}"]
    root = stage_root.resolve()
    errors: list[str] = []
    disk_files, disk_dirs, walk_errors = _walk_tree(root)
    errors.extend(walk_errors)
    expected_root_entries = {"_headers", "channels", "releases"}
    actual_root_entries = {path.name for path in root.iterdir()}
    for name in sorted(actual_root_entries - expected_root_entries):
        errors.append(f"unexpected stage root entry: {name}")
    for name in sorted(expected_root_entries - actual_root_entries):
        errors.append(f"missing stage root entry: {name}")
    header_path = root / "_headers"
    if not header_path.is_file() or header_path.is_symlink():
        errors.append("missing regular _headers control file")
    elif header_path.read_text(encoding="utf-8") != HEADERS_CONTENT:
        errors.append("_headers content drifted from the delivery policy")

    pointer_path = root / "channels" / "production.json"
    pointer: dict[str, Any] | None = None
    if pointer_path.is_file() and not pointer_path.is_symlink():
        try:
            candidate = _read_json(pointer_path)
        except (json.JSONDecodeError, OSError, DeliveryError) as exc:
            errors.append(f"production channel pointer is invalid: {exc}")
        else:
            if isinstance(candidate, dict):
                pointer = candidate
            else:
                errors.append("production channel pointer must be an object")
    else:
        errors.append("missing regular channels/production.json")
    channel_entries = _immediate_entries(root / "channels")
    if channel_entries != {"production.json"}:
        errors.append(
            "channels must contain exactly production.json; "
            f"found {sorted(channel_entries)!r}"
        )

    expected_release_ids: set[str] = set()
    if pointer is not None:
        try:
            current = _require_release_id(
                pointer.get("releaseId"), "current release ID"
            )
            previous = _require_release_id(
                pointer.get("priorReleaseId"), "prior release ID"
            )
        except DeliveryError as exc:
            errors.append(str(exc))
        else:
            if current == previous:
                errors.append("current and prior releases must be distinct")
            expected_release_ids = {current, previous}
    release_entries = _immediate_entries(root / "releases")
    if release_entries != expected_release_ids:
        errors.append(
            "releases must contain exactly current and prior release trees; "
            f"expected {sorted(expected_release_ids)!r}, found {sorted(release_entries)!r}"
        )
    for release_id in sorted(expected_release_ids):
        release_errors = release.validate_release(root / "releases" / release_id)
        errors.extend(f"release {release_id}: {error}" for error in release_errors)
    if pointer is not None and expected_release_ids:
        publication_errors = _production_publication_errors(root)
        errors.extend(f"publication: {error}" for error in publication_errors)

    if len(disk_files) > MAX_WORKER_FILES:
        errors.append(
            f"Worker asset tree contains {len(disk_files)} files; "
            f"limit is {MAX_WORKER_FILES}"
        )
    for relative in sorted(disk_files):
        file_path = root / relative
        size = file_path.stat().st_size
        if size >= MAX_WORKER_FILE_BYTES:
            errors.append(
                f"Worker asset {relative.as_posix()} is {size} bytes; must be smaller "
                f"than {MAX_WORKER_FILE_BYTES}"
            )
    expected_dirs = {Path("channels"), Path("releases")}
    for release_id in expected_release_ids:
        expected_dirs.add(Path("releases") / release_id)
    if not expected_dirs <= disk_dirs:
        errors.append("staged directory topology is incomplete")
    return _deduplicate(errors)


def served_files(stage_root: Path) -> tuple[Path, ...]:
    """Return every remotely served data path; `_headers` is consumed by Workers."""

    errors = verify_stage(stage_root)
    if errors:
        raise DeliveryError("stage is invalid: " + "; ".join(errors))
    files, _dirs, _errors = _walk_tree(stage_root.resolve())
    return tuple(sorted(path for path in files if path != Path("_headers")))


def verify_remote(
    stage_root: Path,
    base_url: str,
    *,
    fetch: Callable[[str], RemoteResponse] | None = None,
) -> RemoteReport:
    """Read back every asset and require bytes, digest, headers, ETag, and 404."""

    try:
        normalized_base = _validate_base_url(base_url)
        paths = served_files(stage_root)
    except DeliveryError as exc:
        return RemoteReport(checked_files=0, missing_path="", errors=(str(exc),))
    root = stage_root.resolve()
    fetcher = fetch or _fetch_remote
    errors: list[str] = []
    for relative in paths:
        encoded_path = "/".join(quote(part, safe="") for part in relative.parts)
        url = f"{normalized_base}/{encoded_path}"
        try:
            response = fetcher(url)
        except Exception as exc:  # pragma: no cover - network seam
            errors.append(f"{relative.as_posix()}: request failed: {exc}")
            continue
        label = relative.as_posix()
        if response.final_url is not None and response.final_url != url:
            errors.append(f"{label}: unexpected redirect to {response.final_url}")
        if response.status != 200:
            errors.append(f"{label}: expected HTTP 200, got {response.status}")
            continue
        local = root / relative
        expected_bytes = local.stat().st_size
        if len(response.body) != expected_bytes:
            errors.append(
                f"{label}: remote bytes {len(response.body)} do not match {expected_bytes}"
            )
        expected_digest = release.sha256_file(local)
        actual_digest = hashlib.sha256(response.body).hexdigest()
        if actual_digest != expected_digest:
            errors.append(f"{label}: remote SHA-256 does not match local asset")
        headers = {
            key.casefold(): value.strip() for key, value in response.headers.items()
        }
        if headers.get("access-control-allow-origin") != "*":
            errors.append(f"{label}: CORS header must be '*'")
        if headers.get("x-content-type-options", "").casefold() != "nosniff":
            errors.append(f"{label}: X-Content-Type-Options must be nosniff")
        if "noindex" not in headers.get("x-robots-tag", "").casefold():
            errors.append(f"{label}: X-Robots-Tag must include noindex")
        expected_cache = _expected_cache_control(relative)
        if headers.get("cache-control") != expected_cache:
            errors.append(
                f"{label}: Cache-Control must be {expected_cache!r}, got "
                f"{headers.get('cache-control')!r}"
            )
        if headers.get("etag") in {None, "", '""', 'W/""'}:
            errors.append(f"{label}: ETag is missing")

    missing_token = _tree_digest(root)[:32]
    missing_path = f"__openopps_missing__/{missing_token}.json"
    missing_url = f"{normalized_base}/{missing_path}"
    try:
        missing_response = fetcher(missing_url)
    except Exception as exc:  # pragma: no cover - network seam
        errors.append(f"missing-path probe failed: {exc}")
    else:
        if missing_response.status != 404:
            errors.append(
                f"missing-path probe returned {missing_response.status}; expected 404"
            )
    return RemoteReport(
        checked_files=len(paths),
        missing_path=missing_path,
        errors=tuple(errors),
    )


def build_upload_invocation(
    *, config: Path, output_file: Path, stage_root: Path
) -> Invocation:
    """Freeze a verified stage and bind Wrangler to its digest-addressed copy."""

    config = _validate_config_path(config)
    environment = config.parent.name
    stage_root = stage_root.absolute()
    expected_stage_root = (DELIVERY_ROOT / environment / "assets").absolute()
    if stage_root != expected_stage_root:
        raise DeliveryError(
            "upload stage must be the owned assets directory for the config environment"
        )
    stage_errors = verify_stage(stage_root)
    if stage_errors:
        raise DeliveryError("upload stage is invalid: " + "; ".join(stage_errors))
    stage = _stage_result(stage_root.resolve(), destination=stage_root)
    output_file = output_file.absolute()
    if output_file.is_symlink():
        raise DeliveryError("Wrangler output file must not be a symlink")
    if output_file.exists():
        raise DeliveryError(
            "Wrangler output file must be absent so stale records cannot be reused"
        )
    upload_candidate_root, upload_candidate_digest = _prepare_upload_candidate(
        config=config,
        stage_root=stage_root,
        output_parent=output_file.parent,
        expected_stage_root_digest=stage.root_digest,
    )
    # Wrangler 4.122.0 rejects `versions upload --json`. Its supported durable
    # machine interface is a JSONL record at WRANGLER_OUTPUT_FILE_PATH.
    return Invocation(
        argv=[
            *_wrangler_prefix(),
            "versions",
            "upload",
            "--config",
            str(upload_candidate_root / CONFIG_FILE),
            "--strict",
        ],
        env={"WRANGLER_OUTPUT_FILE_PATH": str(output_file)},
        upload_candidate_root=upload_candidate_root,
        upload_candidate_digest=upload_candidate_digest,
        stage_root_digest=stage.root_digest,
        current_release_id=stage.current_release_id,
        previous_release_id=stage.previous_release_id,
    )


def _prepare_upload_candidate(
    *,
    config: Path,
    stage_root: Path,
    output_parent: Path,
    expected_stage_root_digest: str,
) -> tuple[Path, str]:
    """Copy upload inputs once, address them by digest, and remove write bits."""

    environment = config.parent.name
    output_parent = output_parent.absolute()
    if os.path.lexists(output_parent) and output_parent.is_symlink():
        raise DeliveryError("Wrangler output directory must not be a symlink")
    output_parent.mkdir(parents=True, exist_ok=True)
    if not output_parent.is_dir():
        raise DeliveryError("Wrangler output directory must be a directory")
    candidate_parent = output_parent / "upload-candidates" / environment
    _reject_symlink_path(output_parent, candidate_parent)
    candidate_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".candidate-", dir=candidate_parent)
    )
    try:
        shutil.copytree(
            stage_root,
            temporary / "assets",
            copy_function=shutil.copy2,
        )
        shutil.copy2(config, temporary / CONFIG_FILE)
        candidate_errors = _upload_candidate_errors(
            temporary,
            environment=environment,
            expected_stage_root_digest=expected_stage_root_digest,
            expected_candidate_digest=None,
            require_read_only=False,
        )
        if candidate_errors:
            raise DeliveryError(
                "prepared upload candidate is invalid: "
                + "; ".join(candidate_errors)
            )
        candidate_digest = _tree_digest(temporary)
        destination = candidate_parent / candidate_digest
        if destination.exists():
            existing_errors = _upload_candidate_errors(
                destination,
                environment=environment,
                expected_stage_root_digest=expected_stage_root_digest,
                expected_candidate_digest=candidate_digest,
                require_read_only=True,
            )
            if existing_errors:
                raise DeliveryError(
                    "existing digest-addressed upload candidate is invalid: "
                    + "; ".join(existing_errors)
                )
            _force_remove_tree(temporary)
            temporary = Path()
            return destination, candidate_digest

        _make_tree_read_only(temporary)
        os.replace(temporary, destination)
        temporary = Path()
        _fsync_directory(candidate_parent)
        final_errors = _upload_candidate_errors(
            destination,
            environment=environment,
            expected_stage_root_digest=expected_stage_root_digest,
            expected_candidate_digest=candidate_digest,
            require_read_only=True,
        )
        if final_errors:
            raise DeliveryError(
                "frozen upload candidate is invalid: " + "; ".join(final_errors)
            )
        return destination, candidate_digest
    finally:
        if temporary != Path() and temporary.exists():
            _force_remove_tree(temporary)


def _upload_candidate_errors(
    candidate_root: Path,
    *,
    environment: str,
    expected_stage_root_digest: str,
    expected_candidate_digest: str | None,
    require_read_only: bool,
) -> list[str]:
    """Validate the complete config-plus-assets input consumed by Wrangler."""

    errors: list[str] = []
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        return ["upload candidate root must be a regular directory"]
    root = candidate_root.absolute()
    expected_parent = root.parent
    if (
        root.name != (expected_candidate_digest or root.name)
        or expected_parent.name != environment
        or expected_parent.parent.name != "upload-candidates"
    ):
        errors.append("upload candidate path does not match the owned digest layout")
    files, dirs, walk_errors = _walk_tree(root)
    errors.extend(walk_errors)
    if _immediate_entries(root) != {CONFIG_FILE, "assets"}:
        errors.append(
            f"upload candidate must contain exactly {CONFIG_FILE!r} and 'assets'"
        )
    config_path = root / CONFIG_FILE
    canonical_config = CONFIG_ROOT / environment / CONFIG_FILE
    if (
        not config_path.is_file()
        or config_path.is_symlink()
        or not canonical_config.is_file()
        or canonical_config.is_symlink()
    ):
        errors.append("upload candidate config is missing or unsafe")
    else:
        try:
            if config_path.read_bytes() != canonical_config.read_bytes():
                errors.append("upload candidate config drifted from the validated config")
        except OSError as exc:
            errors.append(f"upload candidate config could not be read: {exc}")

    assets_root = root / "assets"
    stage_errors = verify_stage(assets_root)
    errors.extend(f"assets: {error}" for error in stage_errors)
    if not stage_errors:
        actual_stage_digest = _tree_digest(assets_root)
        if actual_stage_digest != expected_stage_root_digest:
            errors.append(
                "stage root digest changed: "
                f"expected {expected_stage_root_digest}, got {actual_stage_digest}"
            )

    if expected_candidate_digest is not None:
        if root.name != expected_candidate_digest:
            errors.append(
                "upload candidate path is not addressed by the expected digest"
            )
        actual_candidate_digest = _tree_digest(root)
        if actual_candidate_digest != expected_candidate_digest:
            errors.append(
                "upload candidate digest changed: "
                f"expected {expected_candidate_digest}, got {actual_candidate_digest}"
            )

    if require_read_only:
        for relative in sorted({Path(), *files, *dirs}):
            path = root if relative == Path() else root / relative
            mode = path.stat(follow_symlinks=False).st_mode
            if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                errors.append(
                    "upload candidate contains writable path: "
                    f"{relative.as_posix() or '.'}"
                )
            if relative in files and path.stat(follow_symlinks=False).st_nlink != 1:
                errors.append(
                    "upload candidate file must not be hard-linked: "
                    f"{relative.as_posix()}"
                )
    return _deduplicate(errors)


def _make_tree_read_only(root: Path) -> None:
    files, dirs, errors = _walk_tree(root)
    if errors:
        raise DeliveryError("cannot freeze unsafe upload candidate: " + "; ".join(errors))
    for relative in sorted(files):
        (root / relative).chmod(stat.S_IRUSR)
    for relative in sorted(dirs, key=lambda path: len(path.parts), reverse=True):
        (root / relative).chmod(stat.S_IRUSR | stat.S_IXUSR)
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)


def _force_remove_tree(root: Path) -> None:
    """Remove only a tool-created candidate after restoring owner write bits."""

    if root.is_symlink():
        root.unlink()
        return
    if not root.exists():
        return
    for directory, dirnames, filenames in os.walk(root, topdown=True):
        directory_path = Path(directory)
        directory_path.chmod(stat.S_IRWXU)
        for name in filenames:
            (directory_path / name).chmod(stat.S_IRUSR | stat.S_IWUSR)
        for name in dirnames:
            child = directory_path / name
            if not child.is_symlink():
                child.chmod(stat.S_IRWXU)
    shutil.rmtree(root)


def _reject_symlink_path(ancestor: Path, descendant: Path) -> None:
    """Reject existing symlinks from one trusted ancestor to a child path."""

    ancestor = ancestor.absolute()
    descendant = descendant.absolute()
    try:
        descendant.relative_to(ancestor)
    except ValueError as exc:
        raise DeliveryError("upload candidate path escaped its output directory") from exc
    current = descendant
    while current != ancestor:
        if os.path.lexists(current) and current.is_symlink():
            raise DeliveryError(f"upload candidate ancestor is a symlink: {current}")
        current = current.parent


def parse_upload_output(output: str | bytes) -> dict[str, Any]:
    """Parse one Wrangler `version-upload` JSONL record with strict identity."""

    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DeliveryError("Wrangler machine output is not UTF-8") from exc
    records: list[Any] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise DeliveryError(
                f"Wrangler machine output line {line_number} is invalid JSON"
            ) from exc
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get("type") == "version-upload"
    ]
    if len(matches) != 1:
        raise DeliveryError(
            "Wrangler machine output must contain exactly one version-upload record"
        )
    record = matches[0]
    if record.get("version") != 1:
        raise DeliveryError("unsupported Wrangler version-upload record schema")
    version_id = record.get("version_id")
    _require_worker_version_id(version_id, "Wrangler version_id")
    worker_name = record.get("worker_name")
    if not isinstance(worker_name, str) or not re.fullmatch(
        r"openopps-data-(?:staging|production)", worker_name
    ):
        raise DeliveryError("Wrangler worker_name is not an OpenOpps data Worker")
    worker_tag = record.get("worker_tag")
    if worker_tag is not None and (
        not isinstance(worker_tag, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", worker_tag)
    ):
        raise DeliveryError("Wrangler worker_tag has an invalid shape")
    return record


def record_upload(
    output: str | bytes,
    ledger_path: Path,
    *,
    environment: str,
    upload_candidate_root: Path,
    expected_upload_candidate_digest: str,
    expected_stage_root_digest: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Record an upload only against its frozen digest-addressed candidate."""

    if environment not in CONFIG_ENVIRONMENTS:
        raise DeliveryError(f"environment must be one of {CONFIG_ENVIRONMENTS!r}")
    expected_stage_root_digest = _require_release_id(
        expected_stage_root_digest, "expected stage root digest"
    )
    expected_upload_candidate_digest = _require_release_id(
        expected_upload_candidate_digest, "expected upload candidate digest"
    )
    upload_candidate_root = upload_candidate_root.absolute()
    candidate_errors = _upload_candidate_errors(
        upload_candidate_root,
        environment=environment,
        expected_stage_root_digest=expected_stage_root_digest,
        expected_candidate_digest=expected_upload_candidate_digest,
        require_read_only=True,
    )
    if candidate_errors:
        raise DeliveryError(
            "upload candidate is invalid: " + "; ".join(candidate_errors)
        )
    candidate_digest = _tree_digest(upload_candidate_root)
    stage_root = upload_candidate_root / "assets"
    stage = _stage_result(stage_root, destination=stage_root)
    record = parse_upload_output(output)
    expected_worker = f"openopps-data-{environment}"
    if record["worker_name"] != expected_worker:
        raise DeliveryError(
            f"Wrangler worker_name must be {expected_worker!r} for {environment}"
        )
    entry = {
        "recordedAt": release.canonical_utc_timestamp(recorded_at),
        "environment": environment,
        "workerName": expected_worker,
        "workerVersionId": record["version_id"],
        "workerTag": record.get("worker_tag"),
        "currentReleaseId": stage.current_release_id,
        "previousReleaseId": stage.previous_release_id,
        "stageRootDigest": stage.root_digest,
        "uploadExpectedStageRootDigest": expected_stage_root_digest,
        "uploadCandidateDigest": candidate_digest,
        "uploadExpectedCandidateDigest": expected_upload_candidate_digest,
        "wranglerVersion": WRANGLER_VERSION,
        "phase": "uploaded",
    }
    ledger_path = ledger_path.absolute()
    if ledger_path.is_symlink():
        raise DeliveryError("upload ledger must not be a symlink")
    ledger: dict[str, Any] = {"schemaVersion": LEDGER_SCHEMA_VERSION, "entries": []}
    if ledger_path.exists():
        existing = _read_json(ledger_path)
        if (
            not isinstance(existing, dict)
            or existing.get("schemaVersion") != LEDGER_SCHEMA_VERSION
            or not isinstance(existing.get("entries"), list)
            or set(existing) != {"schemaVersion", "entries"}
        ):
            raise DeliveryError("existing upload ledger has an invalid schema")
        ledger = existing
    if any(
        item.get("workerVersionId") == entry["workerVersionId"]
        for item in ledger["entries"]
        if isinstance(item, dict)
    ):
        raise DeliveryError("upload ledger already contains this Worker version ID")
    ledger["entries"].append(entry)
    _atomic_write_json(ledger_path, ledger)
    return entry


def new_rollout_state(*, current: str, previous: str) -> dict[str, Any]:
    """Create an uploaded rollout state with two validated Worker versions."""

    current = _require_worker_version_id(current, "current Worker version ID")
    previous = _require_worker_version_id(previous, "previous Worker version ID")
    if current == previous:
        raise DeliveryError("current and previous Worker versions must be distinct")
    return {
        "schemaVersion": ROLLOUT_SCHEMA_VERSION,
        "currentWorkerVersionId": current,
        "previousWorkerVersionId": previous,
        "phase": "uploaded",
        "history": [],
    }


def next_rollout_action(
    state: Mapping[str, Any],
    action: str,
    *,
    config: Path,
    dry_run: bool = True,
) -> RolloutAction:
    """Validate promote -> rollback -> re-promote and render a 100% command."""

    _validate_rollout_state(state)
    transitions = {
        ("uploaded", "promote"): ("promoted", "currentWorkerVersionId"),
        ("promoted", "rollback"): ("rolled-back", "previousWorkerVersionId"),
        ("rolled-back", "re-promote"): (
            "repromoted",
            "currentWorkerVersionId",
        ),
    }
    transition = transitions.get((state["phase"], action))
    if transition is None:
        raise DeliveryError(
            f"action {action!r} is invalid from rollout phase {state['phase']!r}"
        )
    next_phase, version_key = transition
    version_id = state[version_key]
    argv = build_deploy_command(
        config=config, worker_version_id=version_id, dry_run=dry_run
    )
    next_state = dict(state)
    history = list(state["history"])
    history.append({"action": action, "workerVersionId": version_id, "percentage": 100})
    next_state["history"] = history
    next_state["phase"] = next_phase
    return RolloutAction(state=next_state, argv=argv)


def build_deploy_command(
    *, config: Path, worker_version_id: str, dry_run: bool = True
) -> list[str]:
    """Build injection-safe argv for a single-version, 100% traffic deployment."""

    config = _validate_config_path(config)
    version_id = _require_worker_version_id(worker_version_id, "Worker version ID")
    argv = [
        *_wrangler_prefix(),
        "versions",
        "deploy",
        "--config",
        str(config),
        f"{version_id}@100%",
        "--yes",
    ]
    if dry_run:
        argv.append("--dry-run")
    return argv


def build_rollout_plan(
    *, current: str, previous: str, config: Path, dry_run: bool = True
) -> dict[str, Any]:
    """Render the complete promote/rollback/re-promote sequence without running it."""

    state = new_rollout_state(current=current, previous=previous)
    actions: list[dict[str, Any]] = []
    for action_name in ("promote", "rollback", "re-promote"):
        action = next_rollout_action(state, action_name, config=config, dry_run=dry_run)
        actions.append(
            {
                "action": action_name,
                "fromPhase": state["phase"],
                "toPhase": action.state["phase"],
                "argv": action.argv,
            }
        )
        state = action.state
    return {
        "schemaVersion": ROLLOUT_SCHEMA_VERSION,
        "initialState": "uploaded",
        "finalState": state["phase"],
        "actions": actions,
    }


def build_recovery_archive(
    stage_root: Path,
    output_path: Path,
    *,
    created_at: str,
    source_revision: str,
) -> ArchiveResult:
    """Create a deterministic tar.gz containing data, checksums, SBOM, provenance."""

    errors = verify_stage(stage_root)
    if errors:
        raise DeliveryError("stage is invalid: " + "; ".join(errors))
    if not _GIT_REVISION_RE.fullmatch(source_revision):
        raise DeliveryError("source revision must be a lowercase 40-character Git SHA")
    canonical_created_at = release.canonical_utc_timestamp(created_at)
    root = stage_root.resolve()
    pointer = _read_pointer(root)
    files, _dirs, _walk_errors = _walk_tree(root)
    staged_members = [
        _ArchiveFile(
            name=f"assets/{relative.as_posix()}",
            path=root / relative,
            bytes=(root / relative).stat().st_size,
            sha256=release.sha256_file(root / relative),
        )
        for relative in sorted(files)
    ]
    stage_digest = _tree_digest(root)
    sbom = _sbom_document(staged_members, stage_digest=stage_digest)
    bundle_manifest = {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "currentReleaseId": _require_release_id(
            pointer.get("releaseId"), "current release ID"
        ),
        "previousReleaseId": _require_release_id(
            pointer.get("priorReleaseId"), "prior release ID"
        ),
        "stageRootDigest": stage_digest,
        "fileCount": len(staged_members),
        "totalBytes": sum(member.bytes for member in staged_members),
        "files": [
            {
                "path": member.name,
                "bytes": member.bytes,
                "sha256": member.sha256,
            }
            for member in staged_members
        ],
    }
    provenance = {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "createdAt": canonical_created_at,
        "sourceRevision": source_revision,
        "currentReleaseId": _require_release_id(
            pointer.get("releaseId"), "current release ID"
        ),
        "previousReleaseId": _require_release_id(
            pointer.get("priorReleaseId"), "prior release ID"
        ),
        "stageRootDigest": stage_digest,
        "wranglerVersion": WRANGLER_VERSION,
        "materials": {
            "channelPointerSha256": release.sha256_file(
                root / "channels" / "production.json"
            ),
            "headersSha256": release.sha256_file(root / "_headers"),
            **_tool_materials(),
        },
    }
    metadata = {
        "bundle-manifest.json": _canonical_pretty_json(bundle_manifest),
        "sbom.spdx.json": _canonical_pretty_json(sbom),
        "provenance.json": _canonical_pretty_json(provenance),
    }
    checksums = {member.name: member.sha256 for member in staged_members}
    checksums.update(
        {
            name: hashlib.sha256(content).hexdigest()
            for name, content in metadata.items()
        }
    )
    checksum_lines = [f"{digest}  {name}" for name, digest in sorted(checksums.items())]
    metadata["SHA256SUMS"] = ("\n".join(checksum_lines) + "\n").encode("utf-8")
    output_path = output_path.absolute()
    asset_name = f"openopps-data-{stage_digest}.tar.gz"
    if output_path.name != asset_name:
        raise DeliveryError(
            f"archive output name must be content-addressed: {asset_name}"
        )
    if output_path.is_symlink():
        raise DeliveryError("archive output must not be a symlink")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
                ) as archive:
                    staged_by_name = {member.name: member for member in staged_members}
                    for name in sorted({*staged_by_name, *metadata}):
                        member = staged_by_name.get(name)
                        if member is not None:
                            with member.path.open("rb") as handle:
                                _add_archive_member(
                                    archive, name=name, size=member.bytes, handle=handle
                                )
                        else:
                            content = metadata[name]
                            _add_archive_member(
                                archive,
                                name=name,
                                size=len(content),
                                handle=io.BytesIO(content),
                            )
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary, output_path)
        _fsync_directory(output_path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return ArchiveResult(
        path=output_path,
        asset_name=asset_name,
        sha256=release.sha256_file(output_path),
        bytes=output_path.stat().st_size,
        stage_root_digest=stage_digest,
    )


def inspect_recovery_archive(path: Path) -> dict[str, bytes]:
    """Stream-verify a recovery archive and retain only its bounded metadata."""

    result: dict[str, bytes] = {}
    member_digests: dict[str, str] = {}
    metadata_names = {
        "SHA256SUMS",
        "bundle-manifest.json",
        "sbom.spdx.json",
        "provenance.json",
    }
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            pure = PurePosixPath(member.name)
            if (
                not member.isfile()
                or pure.is_absolute()
                or any(part in {"", ".", ".."} for part in pure.parts)
                or pure.as_posix() != member.name
            ):
                raise DeliveryError(f"unsafe recovery archive member: {member.name!r}")
            if member.name in member_digests:
                raise DeliveryError(f"duplicate recovery archive member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise DeliveryError(
                    f"unreadable recovery archive member: {member.name}"
                )
            digest = hashlib.sha256()
            retained = io.BytesIO() if member.name in metadata_names else None
            retained_bytes = 0
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if retained is not None:
                    retained_bytes += len(chunk)
                    if retained_bytes > MAX_ARCHIVE_METADATA_BYTES:
                        raise DeliveryError(
                            f"recovery archive metadata is too large: {member.name}"
                        )
                    retained.write(chunk)
            member_digests[member.name] = digest.hexdigest()
            result[member.name] = retained.getvalue() if retained is not None else b""
    if not metadata_names <= set(result):
        raise DeliveryError("recovery archive is missing required metadata")
    checksums: dict[str, str] = {}
    for line in result["SHA256SUMS"].decode("utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not _SHA256_RE.fullmatch(digest) or name in checksums:
            raise DeliveryError("recovery archive SHA256SUMS is invalid")
        checksums[name] = digest
    expected_names = set(result) - {"SHA256SUMS"}
    if set(checksums) != expected_names:
        raise DeliveryError("recovery archive SHA256SUMS does not close over members")
    for name, digest in checksums.items():
        if member_digests[name] != digest:
            raise DeliveryError(f"recovery archive member failed checksum: {name}")
    return result


def _stage_result(root: Path, *, destination: Path) -> StageResult:
    pointer = _read_pointer(root)
    files, _dirs, _errors = _walk_tree(root)
    return StageResult(
        destination=destination,
        current_release_id=_require_release_id(
            pointer.get("releaseId"), "current release ID"
        ),
        previous_release_id=_require_release_id(
            pointer.get("priorReleaseId"), "prior release ID"
        ),
        file_count=len(files),
        total_bytes=sum((root / path).stat().st_size for path in files),
        root_digest=_tree_digest(root),
    )


def _validate_owned_destination(destination: Path) -> None:
    destination = destination.absolute()
    allowed = {
        (DELIVERY_ROOT / environment / "assets").absolute()
        for environment in CONFIG_ENVIRONMENTS
    }
    if destination not in allowed:
        raise DeliveryError(
            "stage destination must be exactly deployment/openopps-data/"
            "{staging,production}/assets"
        )
    if destination.is_symlink():
        raise DeliveryError("stage destination must not be a symlink")
    current = destination.parent
    delivery_root = DELIVERY_ROOT.absolute()
    while current != delivery_root.parent:
        if current.is_symlink():
            raise DeliveryError(f"stage destination ancestor is a symlink: {current}")
        if current == delivery_root:
            break
        current = current.parent
    if current != delivery_root:
        raise DeliveryError("stage destination escaped the owned delivery root")
    if destination.exists() and not destination.is_dir():
        raise DeliveryError("stage destination must be a directory or absent")


def _atomic_replace_directory(candidate: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        backup = destination.parent / f".{destination.name}.previous-{os.getpid()}"
        if backup.exists():
            raise DeliveryError(f"stale delivery backup exists: {backup}")
        os.replace(destination, backup)
    try:
        os.replace(candidate, destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    _fsync_directory(destination.parent)
    if backup is not None:
        shutil.rmtree(backup)


def _walk_tree(root: Path) -> tuple[set[Path], set[Path], list[str]]:
    files: set[Path] = set()
    dirs: set[Path] = set()
    errors: list[str] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*dirnames, *filenames]:
            child = directory_path / name
            relative = child.relative_to(root)
            if child.is_symlink():
                errors.append(f"stage must not contain symlink: {relative.as_posix()}")
        for dirname in dirnames:
            child = directory_path / dirname
            if not child.is_symlink():
                dirs.add(child.relative_to(root))
        for filename in filenames:
            child = directory_path / filename
            if child.is_symlink():
                continue
            mode = child.stat(follow_symlinks=False).st_mode
            if stat.S_ISREG(mode):
                files.add(child.relative_to(root))
            else:
                errors.append(
                    "stage must contain only regular files and directories: "
                    f"{child.relative_to(root).as_posix()}"
                )
    casefolded: dict[str, str] = {}
    for path in sorted({*files, *dirs}):
        normalized = path.as_posix()
        folded = normalized.casefold()
        if folded in casefolded and casefolded[folded] != normalized:
            errors.append(
                f"stage contains case-colliding paths: {casefolded[folded]} and {normalized}"
            )
        casefolded[folded] = normalized
    return files, dirs, errors


def _immediate_entries(root: Path) -> set[str]:
    if not root.is_dir() or root.is_symlink():
        return set()
    return {path.name for path in root.iterdir()}


def _production_publication_errors(root: Path) -> list[str]:
    """Apply every non-bypassable production release gate before delivery."""

    return release.validate_publication(
        root,
        channel="production",
        policy=release.PromotionPolicy(
            max_snapshot_age=release.DEFAULT_PRODUCTION_MAX_SNAPSHOT_AGE
        ),
        require_publication_graph=True,
    )


def _read_pointer(root: Path) -> dict[str, Any]:
    value = _read_json(root / "channels" / "production.json")
    if not isinstance(value, dict):
        raise DeliveryError("production channel pointer must be a JSON object")
    return value


def _read_json(path: Path) -> Any:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DeliveryError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs_hook)


def _require_release_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DeliveryError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_worker_version_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise DeliveryError(f"{label} must be a lowercase UUID")
    return value


def _tree_digest(root: Path) -> str:
    files, _dirs, errors = _walk_tree(root)
    if errors:
        raise DeliveryError("cannot digest unsafe tree: " + "; ".join(errors))
    digest = hashlib.sha256()
    for relative in sorted(files):
        path_bytes = relative.as_posix().encode("utf-8")
        size = (root / relative).stat().st_size
        file_digest = bytes.fromhex(release.sha256_file(root / relative))
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(size.to_bytes(8, "big"))
        digest.update(file_digest)
    return digest.hexdigest()


def _expected_cache_control(path: Path) -> str:
    if path.parts and path.parts[0] == "releases":
        return "public, max-age=31536000, immutable"
    return "public, max-age=0, must-revalidate"


def _validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise DeliveryError("remote base URL is invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise DeliveryError("remote base URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.casefold().endswith(".workers.dev")
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise DeliveryError(
            "remote base URL must be a port-free HTTPS workers.dev origin without "
            "credentials, path, query, or fragment"
        )
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _fetch_remote(url: str) -> RemoteResponse:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, method="GET", headers={"Accept-Encoding": "identity"}
    )
    try:
        with opener.open(request, timeout=30) as response:
            return RemoteResponse(
                status=response.status,
                body=response.read(MAX_WORKER_FILE_BYTES + 1),
                headers=dict(response.headers.items()),
                final_url=response.geturl(),
            )
    except urllib.error.HTTPError as exc:
        return RemoteResponse(
            status=exc.code,
            body=exc.read(MAX_WORKER_FILE_BYTES + 1),
            headers=dict(exc.headers.items()),
            final_url=exc.url,
        )


def _validate_config_path(config: Path) -> Path:
    config = config.resolve()
    if not config.is_file() or config.is_symlink() or config.name != CONFIG_FILE:
        raise DeliveryError(f"config must be a regular {CONFIG_FILE} file")
    environment = config.parent.name
    if environment not in CONFIG_ENVIRONMENTS:
        raise DeliveryError("config parent must be staging or production")
    if config.parent.parent != CONFIG_ROOT.resolve():
        raise DeliveryError(
            "config must be the repository-owned deployment/openopps-data config"
        )
    errors = validate_configs(config.parent.parent)
    if errors:
        raise DeliveryError("delivery config drift: " + "; ".join(errors))
    return config


def _wrangler_prefix() -> list[str]:
    web_root = REPOSITORY_ROOT / "web"
    package_path = web_root / "package.json"
    package = _read_json(package_path)
    if not isinstance(package, dict):
        raise DeliveryError("web/package.json must be a JSON object")
    dependencies = package.get("devDependencies")
    if (
        not isinstance(dependencies, dict)
        or dependencies.get("wrangler") != WRANGLER_VERSION
    ):
        raise DeliveryError(f"web/package.json must pin wrangler {WRANGLER_VERSION}")
    return ["pnpm", "--dir", str(web_root.resolve()), "exec", "wrangler"]


def _validate_rollout_state(state: Mapping[str, Any]) -> None:
    expected = {
        "schemaVersion",
        "currentWorkerVersionId",
        "previousWorkerVersionId",
        "phase",
        "history",
    }
    if set(state) != expected or state.get("schemaVersion") != ROLLOUT_SCHEMA_VERSION:
        raise DeliveryError("rollout state schema is invalid")
    current = _require_worker_version_id(
        state.get("currentWorkerVersionId"), "current Worker version ID"
    )
    previous = _require_worker_version_id(
        state.get("previousWorkerVersionId"), "previous Worker version ID"
    )
    if current == previous:
        raise DeliveryError("current and previous Worker versions must be distinct")
    if state.get("phase") not in {"uploaded", "promoted", "rolled-back", "repromoted"}:
        raise DeliveryError("rollout phase is invalid")
    history = state.get("history")
    if not isinstance(history, list):
        raise DeliveryError("rollout history must be an array")
    expected_history = {
        "uploaded": [],
        "promoted": [
            {
                "action": "promote",
                "workerVersionId": current,
                "percentage": 100,
            }
        ],
        "rolled-back": [
            {
                "action": "promote",
                "workerVersionId": current,
                "percentage": 100,
            },
            {
                "action": "rollback",
                "workerVersionId": previous,
                "percentage": 100,
            },
        ],
        "repromoted": [
            {
                "action": "promote",
                "workerVersionId": current,
                "percentage": 100,
            },
            {
                "action": "rollback",
                "workerVersionId": previous,
                "percentage": 100,
            },
            {
                "action": "re-promote",
                "workerVersionId": current,
                "percentage": 100,
            },
        ],
    }[state["phase"]]
    if history != expected_history:
        raise DeliveryError("rollout history is inconsistent with its phase")


def _atomic_write_json(path: Path, value: object) -> None:
    content = _canonical_pretty_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Make a successful sibling rename durable on supported POSIX filesystems."""

    if os.name != "posix":  # pragma: no cover - Windows has no directory fsync
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _tool_materials() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[1]
    paths = {
        "deliveryScriptSha256": Path(__file__).resolve(),
        "webPackageSha256": repository_root / "web" / "package.json",
        "webLockSha256": repository_root / "web" / "pnpm-lock.yaml",
        "stagingConfigSha256": repository_root
        / "deployment"
        / "openopps-data"
        / "staging"
        / CONFIG_FILE,
        "productionConfigSha256": repository_root
        / "deployment"
        / "openopps-data"
        / "production"
        / CONFIG_FILE,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DeliveryError(f"archive provenance material is missing: {missing!r}")
    return {name: release.sha256_file(path) for name, path in paths.items()}


def _canonical_pretty_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _add_archive_member(
    archive: tarfile.TarFile,
    *,
    name: str,
    size: int,
    handle: IO[bytes],
) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    archive.addfile(info, handle)


def _sbom_document(
    staged_members: Sequence[_ArchiveFile], *, stage_digest: str
) -> dict[str, Any]:
    files = []
    for index, member in enumerate(staged_members, start=1):
        files.append(
            {
                "SPDXID": f"SPDXRef-File-{index}",
                "fileName": member.name,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": member.sha256,
                    }
                ],
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "openopps-data-recovery",
        "documentNamespace": f"https://openopps.dev/spdx/openopps-data/{stage_digest}",
        "creationInfo": {
            "created": "1970-01-01T00:00:00Z",
            "creators": ["Tool: scripts/docs_search_delivery.py"],
        },
        "files": files,
    }


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("config_root", type=Path)
    stage = subparsers.add_parser("stage")
    stage.add_argument("publication_root", type=Path)
    stage.add_argument("destination", type=Path)
    verify = subparsers.add_parser("verify-stage")
    verify.add_argument("stage_root", type=Path)
    remote = subparsers.add_parser("verify-remote")
    remote.add_argument("stage_root", type=Path)
    remote.add_argument("base_url")
    upload = subparsers.add_parser("upload-command")
    upload.add_argument("config", type=Path)
    upload.add_argument("output_file", type=Path)
    upload.add_argument("--stage-root", type=Path, required=True)
    record = subparsers.add_parser("record-upload")
    record.add_argument("machine_output", type=Path)
    record.add_argument("ledger", type=Path)
    record.add_argument("environment", choices=CONFIG_ENVIRONMENTS)
    record.add_argument("upload_candidate_root", type=Path)
    record.add_argument("--expected-upload-candidate-digest", required=True)
    record.add_argument("--expected-stage-root-digest", required=True)
    record.add_argument("--recorded-at", required=True)
    rollout = subparsers.add_parser("rollout-plan")
    rollout.add_argument("config", type=Path)
    rollout.add_argument("current_worker_version_id")
    rollout.add_argument("previous_worker_version_id")
    rollout.add_argument(
        "--live-command",
        action="store_true",
        help="Render live argv instead of --dry-run argv; commands are never executed.",
    )
    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("stage_root", type=Path)
    bundle.add_argument("output", type=Path)
    bundle.add_argument("--created-at", required=True)
    bundle.add_argument("--source-revision", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run local preparation/verification only; never execute deployment commands."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            errors = validate_configs(args.config_root)
            payload: object = {"ok": not errors, "errors": errors}
        elif args.command == "stage":
            payload = stage_publication(
                args.publication_root, args.destination
            ).__dict__
        elif args.command == "verify-stage":
            errors = verify_stage(args.stage_root)
            payload = {"ok": not errors, "errors": errors}
        elif args.command == "verify-remote":
            report = verify_remote(args.stage_root, args.base_url)
            payload = {"ok": not report.errors, **report.__dict__}
        elif args.command == "upload-command":
            payload = build_upload_invocation(
                config=args.config,
                output_file=args.output_file,
                stage_root=args.stage_root,
            ).__dict__
        elif args.command == "record-upload":
            payload = record_upload(
                args.machine_output.read_bytes(),
                args.ledger,
                environment=args.environment,
                upload_candidate_root=args.upload_candidate_root,
                expected_upload_candidate_digest=(
                    args.expected_upload_candidate_digest
                ),
                expected_stage_root_digest=args.expected_stage_root_digest,
                recorded_at=args.recorded_at,
            )
        elif args.command == "rollout-plan":
            payload = build_rollout_plan(
                current=args.current_worker_version_id,
                previous=args.previous_worker_version_id,
                config=args.config,
                dry_run=not args.live_command,
            )
        else:
            payload = build_recovery_archive(
                args.stage_root,
                args.output,
                created_at=args.created_at,
                source_revision=args.source_revision,
            ).__dict__
    except (DeliveryError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(payload, default=str, sort_keys=True))
    if isinstance(payload, dict) and payload.get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
