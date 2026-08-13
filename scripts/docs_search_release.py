"""Deterministic manifests and validation for immutable docs-search releases.

Version 7 deliberately excludes ``manifest.json`` from its own ``files`` list.
The root digest is calculated over the canonical manifest body before
``releaseId`` and ``rootDigest`` are attached, avoiding a self-referential hash
while still closing over every payload file and all release metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit

RELEASE_SCHEMA_VERSION = 7
CHANNEL_SCHEMA_VERSION = 2
MANIFEST_FILE = "manifest.json"
SEARCH_MANIFEST_FILE = "search-manifest.json"
PUBLICATION_POLICY_FILE = "publication-policy.json"
DEFAULT_PRODUCTION_MAX_SNAPSHOT_AGE = timedelta(hours=48)
MAX_RELEASE_FILES = 18_000
MAX_RELEASE_FILE_BYTES = 24 * 1024 * 1024
FORBIDDEN_PRIVATE_KEYS = frozenset({"payloadSnapshots", "descriptionHtml"})
FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "credential",
        "password",
        "passwd",
        "refreshtoken",
        "secret",
        "token",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHANNEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PORTABLE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MAX_PORTABLE_PATH_BYTES = 1_024
_MANIFEST_BODY_KEYS = frozenset(
    {
        "schemaVersion",
        "snapshotAt",
        "source",
        "generator",
        "fileCount",
        "totalBytes",
        "files",
    }
)
_MANIFEST_KEYS = _MANIFEST_BODY_KEYS | {"releaseId", "rootDigest"}
_PUBLICATION_ALLOWED_RIGHTS = frozenset(
    {
        "official_public",
        "oss_attribution_required",
        "public_attribution_required",
    }
)
_PUBLICATION_ATTRIBUTION_REQUIRED = frozenset(
    {"oss_attribution_required", "public_attribution_required"}
)
_PUBLICATION_POLICY_KEYS = frozenset(
    {
        "schemaVersion",
        "allowedLicenseStatuses",
        "attributionRequiredStatuses",
        "sourceCount",
        "sources",
        "quality",
    }
)
_PUBLICATION_QUALITY_KEYS = frozenset(
    {
        "snapshotAt",
        "sourceRows",
        "providerRoutes",
        "boards",
        "jobs",
        "openJobs",
        "detailTiers",
    }
)


@dataclass(frozen=True)
class PromotionPolicy:
    """Limits enforced before a release may become channel-visible."""

    max_snapshot_age: timedelta | None = None
    max_files: int = MAX_RELEASE_FILES
    max_file_bytes: int = MAX_RELEASE_FILE_BYTES


class DuplicateJsonKeyError(ValueError):
    """Raised when strict JSON decoding finds a duplicate object key."""


def canonical_utc_timestamp(value: str) -> str:
    """Return an ISO-8601 UTC timestamp with fixed microsecond precision."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("snapshotAt must be a non-empty timestamp string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"snapshotAt is not an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("snapshotAt must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    """Hash a file without loading a potentially large artifact into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_manifest(
    release_root: Path,
    *,
    snapshot_at: str,
    source: dict[str, Any],
    generator: dict[str, Any],
) -> dict[str, Any]:
    """Create a deterministic v7 manifest for an already-written payload tree."""

    release_root = release_root.resolve()
    if (release_root / MANIFEST_FILE).exists():
        raise ValueError(f"release payload must not already contain {MANIFEST_FILE}")
    file_paths, path_errors = _disk_file_paths(release_root)
    if path_errors:
        raise ValueError("invalid release payload: " + "; ".join(path_errors))
    entries = [_file_entry(release_root, path) for path in sorted(file_paths)]
    body: dict[str, Any] = {
        "schemaVersion": RELEASE_SCHEMA_VERSION,
        "snapshotAt": canonical_utc_timestamp(snapshot_at),
        "source": source,
        "generator": generator,
        "fileCount": len(entries),
        "totalBytes": sum(int(entry["bytes"]) for entry in entries),
        "files": entries,
    }
    digest = _manifest_digest(body)
    return {
        **body,
        "releaseId": digest,
        "rootDigest": {"algorithm": "sha256", "value": digest},
    }


def write_release_manifest(release_root: Path, manifest: dict[str, Any]) -> None:
    """Write canonical pretty JSON after the payload has been fully generated."""

    (release_root / MANIFEST_FILE).write_bytes(_canonical_json_bytes(manifest))


def validate_release(
    release_root: Path,
    *,
    policy: PromotionPolicy | None = None,
    now: datetime | None = None,
    require_publication_graph: bool = False,
) -> list[str]:
    """Validate v7 structure, content closure, integrity, and promotion policy."""

    policy = policy or PromotionPolicy()
    original_root = release_root
    if original_root.is_symlink():
        return [f"release root must not be a symlink: {original_root}"]
    release_root = original_root.resolve()
    manifest_path = release_root / MANIFEST_FILE
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return [f"missing regular manifest: {manifest_path}"]
    try:
        with manifest_path.open("rb") as manifest_file:
            manifest_bytes = manifest_file.read()
        manifest = _decode_json_strict(manifest_bytes)
    except (
        DuplicateJsonKeyError,
        json.JSONDecodeError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        return [f"manifest is invalid JSON: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

    errors: list[str] = []
    if manifest_bytes != _canonical_json_bytes(manifest):
        errors.append(
            "manifest must use canonical JSON bytes with one trailing newline"
        )
    errors.extend(_manifest_shape_errors(manifest))
    file_paths, disk_errors = _disk_file_paths(release_root)
    errors.extend(disk_errors)
    disk_paths = {Path(MANIFEST_FILE), *file_paths}
    if len(disk_paths) > policy.max_files:
        errors.append(
            f"release contains {len(disk_paths)} files; limit is {policy.max_files}"
        )
    for relative_path in sorted(disk_paths):
        file_path = release_root / relative_path
        if file_path.is_file() and not file_path.is_symlink():
            size = file_path.stat().st_size
            if size >= policy.max_file_bytes:
                errors.append(
                    f"file {relative_path.as_posix()} is {size} bytes; "
                    f"must be smaller than {policy.max_file_bytes}"
                )

    entries = manifest.get("files")
    expected_paths: set[Path] = {Path(MANIFEST_FILE)}
    seen_paths: set[str] = set()
    seen_casefolded: dict[str, str] = {}
    valid_entries: list[tuple[dict[str, Any], Path]] = []
    if not isinstance(entries, list):
        errors.append("manifest files must be an array")
        entries = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"manifest files[{index}] must be an object")
            continue
        path_value = entry.get("path")
        path_error = _safe_relative_path_error(path_value)
        if path_error:
            errors.append(f"manifest files[{index}].path {path_error}")
            continue
        assert isinstance(path_value, str)
        if path_value == MANIFEST_FILE:
            errors.append(
                "manifest.json is self-excluding and must not appear in files"
            )
            continue
        if path_value in seen_paths:
            errors.append(f"duplicate manifest path: {path_value}")
            continue
        casefolded = path_value.casefold()
        if casefolded in seen_casefolded:
            errors.append(
                "case-colliding manifest paths: "
                f"{seen_casefolded[casefolded]} and {path_value}"
            )
            continue
        seen_paths.add(path_value)
        seen_casefolded[casefolded] = path_value
        relative_path = Path(*PurePosixPath(path_value).parts)
        expected_paths.add(relative_path)
        valid_entries.append((entry, relative_path))

    missing = sorted(expected_paths - disk_paths)
    extra = sorted(disk_paths - expected_paths)
    errors.extend(
        f"manifest path missing on disk: {path.as_posix()}" for path in missing
    )
    errors.extend(
        f"unreferenced file exists on disk: {path.as_posix()}" for path in extra
    )

    total_bytes = 0
    for entry, relative_path in valid_entries:
        file_path = release_root / relative_path
        if not file_path.is_file() or file_path.is_symlink():
            continue
        data_size = file_path.stat().st_size
        total_bytes += data_size
        if entry.get("bytes") != data_size:
            errors.append(
                f"file {relative_path.as_posix()} byte size {data_size} "
                f"does not match manifest {entry.get('bytes')!r}"
            )
        if entry.get("sha256") != sha256_file(file_path):
            errors.append(
                f"file {relative_path.as_posix()} SHA-256 does not match manifest"
            )
        expected_media_type = _media_type(relative_path)
        if entry.get("mediaType") != expected_media_type:
            errors.append(
                f"file {relative_path.as_posix()} media type "
                f"{entry.get('mediaType')!r} does not match {expected_media_type!r}"
            )
        expected_role = _semantic_role(relative_path)
        if entry.get("role") != expected_role:
            errors.append(
                f"file {relative_path.as_posix()} role {entry.get('role')!r} "
                f"does not match {expected_role!r}"
            )
        if expected_media_type == "application/json":
            try:
                payload = _read_json_strict(file_path)
            except (
                DuplicateJsonKeyError,
                json.JSONDecodeError,
                OSError,
                UnicodeDecodeError,
            ) as exc:
                errors.append(f"file {relative_path.as_posix()} is invalid JSON: {exc}")
                continue
            expected_count = _semantic_count(payload, expected_role)
            if entry.get("count") != expected_count:
                errors.append(
                    f"file {relative_path.as_posix()} count {entry.get('count')!r} "
                    f"does not match {expected_count}"
                )
            errors.extend(_forbidden_key_errors(relative_path, payload))
            errors.extend(_secret_value_errors(relative_path, payload))

    if manifest.get("fileCount") != len(entries):
        errors.append(
            f"manifest fileCount {manifest.get('fileCount')!r} "
            f"does not match {len(entries)} entries"
        )
    if manifest.get("totalBytes") != total_bytes:
        errors.append(
            f"manifest totalBytes {manifest.get('totalBytes')!r} "
            f"does not match {total_bytes} bytes"
        )
    errors.extend(_snapshot_errors(manifest, policy=policy, now=now))
    if require_publication_graph:
        errors.extend(_publication_graph_errors(release_root, manifest))
    errors.extend(_root_digest_errors(manifest))
    if release_root.parent.name == "releases" and isinstance(
        manifest.get("releaseId"), str
    ):
        if release_root.name != manifest["releaseId"]:
            errors.append(
                f"release directory {release_root.name!r} does not match "
                f"releaseId {manifest['releaseId']!r}"
            )
    return errors


def channel_pointer(
    manifest: dict[str, Any],
    *,
    channel: str,
    prior_release_id: str | None = None,
    degraded_reason: str | None = None,
    promoted_at: str | None = None,
    snapshot_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Create the mutable pointer to an immutable release."""

    _validate_channel_name(channel)
    release_id = manifest["releaseId"]
    if prior_release_id is not None and (
        not isinstance(prior_release_id, str)
        or not _SHA256_RE.fullmatch(prior_release_id)
        or prior_release_id == release_id
    ):
        raise ValueError("prior release ID must be a distinct lowercase SHA-256 digest")
    if degraded_reason is not None and (
        not isinstance(degraded_reason, str)
        or not degraded_reason.strip()
        or len(degraded_reason.strip()) > 500
    ):
        raise ValueError("degraded reason must be 1-500 non-whitespace characters")
    promoted_at = canonical_utc_timestamp(promoted_at or manifest["snapshotAt"])
    if snapshot_age_seconds is None:
        promoted = datetime.fromisoformat(promoted_at.replace("Z", "+00:00"))
        snapshot = datetime.fromisoformat(
            canonical_utc_timestamp(manifest["snapshotAt"]).replace("Z", "+00:00")
        )
        snapshot_age_seconds = max(0, int((promoted - snapshot).total_seconds()))
    if not isinstance(snapshot_age_seconds, int) or snapshot_age_seconds < 0:
        raise ValueError("snapshot age seconds must be a non-negative integer")
    return {
        "schemaVersion": CHANNEL_SCHEMA_VERSION,
        "channel": channel,
        "releaseId": release_id,
        "rootDigest": manifest["rootDigest"],
        "snapshotAt": manifest["snapshotAt"],
        "manifestPath": f"releases/{release_id}/{MANIFEST_FILE}",
        "priorReleaseId": prior_release_id,
        "degradedReason": degraded_reason.strip()
        if degraded_reason is not None
        else None,
        "promotedAt": promoted_at,
        "snapshotAgeSeconds": snapshot_age_seconds,
    }


def atomic_write_channel_pointer(
    publication_root: Path,
    manifest: dict[str, Any],
    *,
    channel: str,
    prior_release_id: str | None = None,
    degraded_reason: str | None = None,
    promoted_at: str | None = None,
    snapshot_age_seconds: int | None = None,
) -> Path:
    """Replace a channel pointer atomically without rewriting release content."""

    _validate_channel_name(channel)
    channels_root = publication_root / "channels"
    channels_root.mkdir(parents=True, exist_ok=True)
    destination = channels_root / f"{channel}.json"
    content = _canonical_json_bytes(
        channel_pointer(
            manifest,
            channel=channel,
            prior_release_id=prior_release_id,
            degraded_reason=degraded_reason,
            promoted_at=promoted_at,
            snapshot_age_seconds=snapshot_age_seconds,
        ),
    ).decode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=channels_root, prefix=f".{channel}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def validate_publication(
    publication_root: Path,
    *,
    channel: str,
    policy: PromotionPolicy | None = None,
    now: datetime | None = None,
    require_publication_graph: bool | None = None,
) -> list[str]:
    """Validate a channel pointer and its selected immutable release."""

    try:
        _validate_channel_name(channel)
    except ValueError as exc:
        return [str(exc)]
    production_contract = channel == "production"
    if policy is None:
        policy = PromotionPolicy(
            max_snapshot_age=(
                DEFAULT_PRODUCTION_MAX_SNAPSHOT_AGE if production_contract else None
            )
        )
    elif production_contract and (
        policy.max_snapshot_age is None
        or policy.max_snapshot_age > DEFAULT_PRODUCTION_MAX_SNAPSHOT_AGE
    ):
        policy = PromotionPolicy(
            max_snapshot_age=DEFAULT_PRODUCTION_MAX_SNAPSHOT_AGE,
            max_files=policy.max_files,
            max_file_bytes=policy.max_file_bytes,
        )
    if require_publication_graph is None:
        require_publication_graph = production_contract
    pointer_path = publication_root / "channels" / f"{channel}.json"
    if not pointer_path.is_file() or pointer_path.is_symlink():
        return [f"missing regular channel pointer: {pointer_path}"]
    try:
        with pointer_path.open("rb") as pointer_file:
            pointer_bytes = pointer_file.read()
        pointer = _decode_json_strict(pointer_bytes)
    except (
        DuplicateJsonKeyError,
        json.JSONDecodeError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        return [f"channel pointer is invalid JSON: {exc}"]
    if not isinstance(pointer, dict):
        return ["channel pointer must be a JSON object"]
    errors: list[str] = []
    if pointer_bytes != _canonical_json_bytes(pointer):
        errors.append(
            "channel pointer must use canonical JSON bytes with one trailing newline"
        )
    expected_pointer_keys = {
        "schemaVersion",
        "channel",
        "releaseId",
        "rootDigest",
        "snapshotAt",
        "manifestPath",
        "priorReleaseId",
        "degradedReason",
        "promotedAt",
        "snapshotAgeSeconds",
    }
    if set(pointer) != expected_pointer_keys:
        errors.append("channel pointer has unexpected or missing fields")
    if pointer.get("schemaVersion") != CHANNEL_SCHEMA_VERSION:
        errors.append(f"channel pointer schemaVersion must be {CHANNEL_SCHEMA_VERSION}")
    if pointer.get("channel") != channel:
        errors.append(f"channel pointer channel must be {channel!r}")
    release_id = pointer.get("releaseId")
    if not isinstance(release_id, str) or not _SHA256_RE.fullmatch(release_id):
        errors.append("channel pointer releaseId must be a lowercase SHA-256 digest")
        return errors
    expected_manifest_path = f"releases/{release_id}/{MANIFEST_FILE}"
    if pointer.get("manifestPath") != expected_manifest_path:
        errors.append(
            f"channel pointer manifestPath must be {expected_manifest_path!r}"
        )
    prior_release_id = pointer.get("priorReleaseId")
    if prior_release_id is not None and (
        not isinstance(prior_release_id, str)
        or not _SHA256_RE.fullmatch(prior_release_id)
        or prior_release_id == release_id
    ):
        errors.append(
            "channel pointer priorReleaseId must be a distinct SHA-256 digest"
        )
    degraded_reason = pointer.get("degradedReason")
    if degraded_reason is not None and (
        not isinstance(degraded_reason, str)
        or not degraded_reason.strip()
        or degraded_reason != degraded_reason.strip()
        or len(degraded_reason) > 500
    ):
        errors.append("channel pointer degradedReason is invalid")
    promoted_at = pointer.get("promotedAt")
    try:
        canonical_promoted_at = canonical_utc_timestamp(promoted_at)
    except (TypeError, ValueError):
        errors.append("channel pointer promotedAt is invalid")
    else:
        if promoted_at != canonical_promoted_at:
            errors.append("channel pointer promotedAt is not canonical UTC")
    snapshot_age_seconds = pointer.get("snapshotAgeSeconds")
    if not isinstance(snapshot_age_seconds, int) or snapshot_age_seconds < 0:
        errors.append("channel pointer snapshotAgeSeconds is invalid")
    elif isinstance(promoted_at, str) and isinstance(pointer.get("snapshotAt"), str):
        try:
            promoted = datetime.fromisoformat(
                canonical_utc_timestamp(promoted_at).replace("Z", "+00:00")
            )
            snapshot = datetime.fromisoformat(
                canonical_utc_timestamp(pointer["snapshotAt"]).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            pass
        else:
            expected_age = int((promoted - snapshot).total_seconds())
            if expected_age < 0 or snapshot_age_seconds != expected_age:
                errors.append(
                    "channel pointer snapshotAgeSeconds does not match "
                    "promotedAt minus snapshotAt"
                )
    release_root = publication_root / "releases" / release_id
    current_policy = policy
    if _valid_degraded_reason(degraded_reason):
        current_policy = PromotionPolicy(
            max_snapshot_age=None,
            max_files=policy.max_files,
            max_file_bytes=policy.max_file_bytes,
        )
    errors.extend(
        validate_release(
            release_root,
            policy=current_policy,
            now=now,
            require_publication_graph=require_publication_graph,
        )
    )
    if isinstance(prior_release_id, str) and _SHA256_RE.fullmatch(prior_release_id):
        prior_policy = PromotionPolicy(
            max_snapshot_age=None,
            max_files=policy.max_files,
            max_file_bytes=policy.max_file_bytes,
        )
        prior_root = publication_root / "releases" / prior_release_id
        prior_errors = validate_release(
            prior_root,
            policy=prior_policy,
            now=now,
            require_publication_graph=require_publication_graph,
        )
        errors.extend(f"prior release: {error}" for error in prior_errors)
    manifest_path = release_root / MANIFEST_FILE
    if manifest_path.is_file():
        try:
            manifest = _read_json_strict(manifest_path)
        except (
            DuplicateJsonKeyError,
            json.JSONDecodeError,
            OSError,
            UnicodeDecodeError,
        ):
            manifest = None
        if isinstance(manifest, dict):
            for key in ("releaseId", "rootDigest", "snapshotAt"):
                if pointer.get(key) != manifest.get(key):
                    errors.append(
                        f"channel pointer {key} does not match release manifest"
                    )
    return errors


def _publication_graph_errors(
    release_root: Path, manifest: dict[str, Any]
) -> list[str]:
    """Validate the non-bypassable source-rights graph for a public release."""

    errors: list[str] = []
    search_path = release_root / SEARCH_MANIFEST_FILE
    policy_path = release_root / PUBLICATION_POLICY_FILE
    if not search_path.is_file() or search_path.is_symlink():
        errors.append(f"missing required {SEARCH_MANIFEST_FILE} regular file")
    if not policy_path.is_file() or policy_path.is_symlink():
        errors.append(f"missing required {PUBLICATION_POLICY_FILE} regular file")
    if errors:
        return errors
    try:
        search_manifest = _read_json_strict(search_path)
    except (
        DuplicateJsonKeyError,
        json.JSONDecodeError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        errors.append(f"{SEARCH_MANIFEST_FILE} is invalid JSON: {exc}")
        search_manifest = None
    try:
        publication_policy = _read_json_strict(policy_path)
    except (
        DuplicateJsonKeyError,
        json.JSONDecodeError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        errors.append(f"{PUBLICATION_POLICY_FILE} is invalid JSON: {exc}")
        publication_policy = None
    if not isinstance(search_manifest, dict):
        errors.append(f"{SEARCH_MANIFEST_FILE} must be a JSON object")
    if not isinstance(publication_policy, dict):
        errors.append(f"{PUBLICATION_POLICY_FILE} must be a JSON object")
    if not isinstance(search_manifest, dict) or not isinstance(
        publication_policy, dict
    ):
        return errors

    search_snapshot = search_manifest.get("snapshotAt")
    if search_snapshot != manifest.get("snapshotAt"):
        errors.append(
            f"{SEARCH_MANIFEST_FILE} snapshotAt does not match release manifest"
        )
    facets = search_manifest.get("facets")
    source_values = facets.get("sources") if isinstance(facets, dict) else None
    if not isinstance(source_values, list) or any(
        not isinstance(value, str) or not value.strip() or value != value.strip()
        for value in source_values
    ):
        errors.append(
            f"{SEARCH_MANIFEST_FILE} facets.sources must be an array of "
            "non-empty canonical strings"
        )
        search_sources: list[str] = []
    else:
        search_sources = list(source_values)
        if len({value.casefold() for value in search_sources}) != len(search_sources):
            errors.append(f"{SEARCH_MANIFEST_FILE} facets.sources contains duplicates")
        if search_sources != sorted(search_sources, key=str.casefold):
            errors.append(f"{SEARCH_MANIFEST_FILE} facets.sources must be sorted")

    if set(publication_policy) != _PUBLICATION_POLICY_KEYS:
        errors.append(
            f"{PUBLICATION_POLICY_FILE} has unexpected or missing top-level fields"
        )
    if publication_policy.get("schemaVersion") != 1:
        errors.append(f"{PUBLICATION_POLICY_FILE} schemaVersion must be 1")
    expected_allowed = sorted(_PUBLICATION_ALLOWED_RIGHTS)
    if publication_policy.get("allowedLicenseStatuses") != expected_allowed:
        errors.append(
            f"{PUBLICATION_POLICY_FILE} allowedLicenseStatuses does not match "
            "the release contract"
        )
    expected_attribution = sorted(_PUBLICATION_ATTRIBUTION_REQUIRED)
    if publication_policy.get("attributionRequiredStatuses") != expected_attribution:
        errors.append(
            f"{PUBLICATION_POLICY_FILE} attributionRequiredStatuses does not match "
            "the release contract"
        )

    source_entries = publication_policy.get("sources")
    if not isinstance(source_entries, list):
        errors.append(f"{PUBLICATION_POLICY_FILE} sources must be an array")
        source_entries = []
    source_count = publication_policy.get("sourceCount")
    if type(source_count) is not int or source_count < 0:
        errors.append(
            f"{PUBLICATION_POLICY_FILE} sourceCount must be a non-negative integer"
        )
    elif source_count != len(source_entries):
        errors.append(
            f"{PUBLICATION_POLICY_FILE} sourceCount does not match sources length"
        )

    policy_sources: list[str] = []
    for index, entry in enumerate(source_entries):
        label = f"{PUBLICATION_POLICY_FILE} sources[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        required = {
            "key",
            "licenseStatus",
            "sourceAttribution",
            "publicationAllowed",
        }
        if set(entry) not in (required, required | {"sourceUrl"}):
            errors.append(f"{label} has unexpected or missing fields")
        key = entry.get("key")
        if (
            not isinstance(key, str)
            or not key.strip()
            or key != key.strip()
            or len(key) > 200
        ):
            errors.append(f"{label}.key must be a canonical non-empty string")
        else:
            policy_sources.append(key)
        status = entry.get("licenseStatus")
        if status not in _PUBLICATION_ALLOWED_RIGHTS:
            errors.append(f"{label}.licenseStatus must be an allowed status")
        if entry.get("publicationAllowed") is not True:
            errors.append(f"{label}.publicationAllowed must be true")
        attribution = entry.get("sourceAttribution")
        if attribution is not None and (
            not isinstance(attribution, str)
            or not attribution.strip()
            or attribution != attribution.strip()
            or len(attribution) > 2_000
        ):
            errors.append(
                f"{label}.sourceAttribution must be null or a bounded canonical string"
            )
        if status in _PUBLICATION_ATTRIBUTION_REQUIRED and (
            not isinstance(attribution, str) or not attribution.strip()
        ):
            errors.append(
                f"{label} requires non-empty sourceAttribution for {status!r}"
            )
        if "sourceUrl" in entry and not _is_safe_public_source_url(entry["sourceUrl"]):
            errors.append(f"{label}.sourceUrl must be a safe public HTTP(S) URL")

    if len({value.casefold() for value in policy_sources}) != len(policy_sources):
        errors.append(f"{PUBLICATION_POLICY_FILE} sources contains duplicate keys")
    if policy_sources != sorted(policy_sources, key=str.casefold):
        errors.append(f"{PUBLICATION_POLICY_FILE} sources must be sorted by key")
    if set(policy_sources) != set(search_sources):
        errors.append(
            "source set does not match search-manifest facets.sources in "
            f"{PUBLICATION_POLICY_FILE}"
        )
    if type(source_count) is int and source_count != len(search_sources):
        errors.append(
            f"{PUBLICATION_POLICY_FILE} sourceCount does not match "
            f"{SEARCH_MANIFEST_FILE} facets.sources"
        )

    errors.extend(
        _publication_quality_errors(
            publication_policy.get("quality"),
            search_manifest=search_manifest,
            release_snapshot=manifest.get("snapshotAt"),
        )
    )
    return errors


def _publication_quality_errors(
    value: object,
    *,
    search_manifest: dict[str, Any],
    release_snapshot: object,
) -> list[str]:
    label = f"{PUBLICATION_POLICY_FILE} quality"
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    if set(value) != _PUBLICATION_QUALITY_KEYS:
        errors.append(f"{label} has unexpected or missing fields")
    if value.get("snapshotAt") != release_snapshot:
        errors.append(f"{label}.snapshotAt does not match release manifest")
    counts = search_manifest.get("counts")
    snapshot_counts = counts.get("snapshot") if isinstance(counts, dict) else None
    for key in ("sourceRows", "providerRoutes", "boards", "jobs", "openJobs"):
        count = value.get(key)
        if type(count) is not int or count < 0:
            errors.append(f"{label}.{key} must be a non-negative integer")
        if not isinstance(snapshot_counts, dict) or count != snapshot_counts.get(key):
            errors.append(
                f"{label}.{key} does not match {SEARCH_MANIFEST_FILE} counts.snapshot"
            )
    detail_tiers = value.get("detailTiers")
    if not isinstance(detail_tiers, dict) or any(
        not isinstance(key, str) or not key or type(count) is not int or count < 0
        for key, count in (
            detail_tiers.items() if isinstance(detail_tiers, dict) else []
        )
    ):
        errors.append(f"{label}.detailTiers must contain non-negative integer counts")
    detail_shards = search_manifest.get("detailShards")
    expected_tiers = (
        detail_shards.get("tierCounts") if isinstance(detail_shards, dict) else None
    )
    if detail_tiers != expected_tiers:
        errors.append(
            f"{label}.detailTiers does not match {SEARCH_MANIFEST_FILE} "
            "detailShards.tierCounts"
        )
    return errors


def _is_safe_public_source_url(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _valid_degraded_reason(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and len(value) <= 500
    )


def _manifest_shape_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(manifest) != _MANIFEST_KEYS:
        errors.append("manifest has unexpected or missing top-level fields")
    if manifest.get("schemaVersion") != RELEASE_SCHEMA_VERSION:
        errors.append(f"manifest schemaVersion must be {RELEASE_SCHEMA_VERSION}")
    release_id = manifest.get("releaseId")
    if not isinstance(release_id, str) or not _SHA256_RE.fullmatch(release_id):
        errors.append("manifest releaseId must be a lowercase SHA-256 digest")
    root_digest = manifest.get("rootDigest")
    if not isinstance(root_digest, dict) or set(root_digest) != {"algorithm", "value"}:
        errors.append("manifest rootDigest must contain algorithm and value")
    elif (
        root_digest.get("algorithm") != "sha256"
        or not isinstance(root_digest.get("value"), str)
        or not _SHA256_RE.fullmatch(root_digest["value"])
    ):
        errors.append("manifest rootDigest must be a lowercase SHA-256 digest")
    source = manifest.get("source")
    if not isinstance(source, dict) or set(source) != {
        "kind",
        "path",
        "bytes",
        "sha256",
    }:
        errors.append("manifest source provenance has unexpected or missing fields")
    elif (
        source.get("kind") != "sqlite"
        or not isinstance(source.get("path"), str)
        or _safe_relative_path_error(source.get("path")) is not None
        or not isinstance(source.get("bytes"), int)
        or source["bytes"] < 0
        or not isinstance(source.get("sha256"), str)
        or not _SHA256_RE.fullmatch(source["sha256"])
    ):
        errors.append("manifest source provenance is invalid")
    generator = manifest.get("generator")
    if not isinstance(generator, dict) or set(generator) != {
        "name",
        "entrypoint",
        "components",
        "payloadSchemaVersion",
    }:
        errors.append("manifest generator provenance has unexpected or missing fields")
    elif (
        not isinstance(generator.get("name"), str)
        or not isinstance(generator.get("entrypoint"), str)
        or _safe_relative_path_error(generator.get("entrypoint")) is not None
        or not isinstance(generator.get("payloadSchemaVersion"), int)
        or not _valid_components(generator.get("components"))
    ):
        errors.append("manifest generator provenance is invalid")
    return errors


def _valid_components(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    paths: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            return False
        path = item.get("path")
        digest = item.get("sha256")
        if (
            _safe_relative_path_error(path) is not None
            or path in paths
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
        ):
            return False
        assert isinstance(path, str)
        paths.add(path)
    return True


def _snapshot_errors(
    manifest: dict[str, Any],
    *,
    policy: PromotionPolicy,
    now: datetime | None,
) -> list[str]:
    value = manifest.get("snapshotAt")
    if not isinstance(value, str):
        return ["manifest snapshotAt must be a canonical UTC timestamp"]
    try:
        canonical = canonical_utc_timestamp(value)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    if value != canonical:
        errors.append(f"manifest snapshotAt must use canonical UTC form {canonical!r}")
    if policy.max_snapshot_age is not None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        snapshot = datetime.fromisoformat(canonical.replace("Z", "+00:00"))
        age = current - snapshot
        if age > policy.max_snapshot_age:
            errors.append(
                f"snapshot is stale by policy: age {age} exceeds "
                f"{policy.max_snapshot_age}"
            )
    return errors


def _root_digest_errors(manifest: dict[str, Any]) -> list[str]:
    if not _MANIFEST_BODY_KEYS <= set(manifest):
        return []
    body = {key: manifest[key] for key in _MANIFEST_BODY_KEYS}
    expected = _manifest_digest(body)
    errors: list[str] = []
    if manifest.get("releaseId") != expected:
        errors.append("manifest releaseId does not match the canonical root digest")
    root_digest = manifest.get("rootDigest")
    if not isinstance(root_digest, dict) or root_digest.get("value") != expected:
        errors.append("manifest rootDigest does not match the canonical manifest body")
    return errors


def _manifest_digest(body: dict[str, Any]) -> str:
    canonical = json.dumps(
        body, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _file_entry(release_root: Path, relative_path: Path) -> dict[str, Any]:
    file_path = release_root / relative_path
    media_type = _media_type(relative_path)
    role = _semantic_role(relative_path)
    count = 0
    if media_type == "application/json":
        count = _semantic_count(_read_json_strict(file_path), role)
    return {
        "path": relative_path.as_posix(),
        "bytes": file_path.stat().st_size,
        "mediaType": media_type,
        "sha256": sha256_file(file_path),
        "role": role,
        "count": count,
    }


def _media_type(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "application/json"
    return "application/octet-stream"


def _semantic_role(path: Path) -> str:
    value = path.as_posix()
    if value == "search-manifest.json":
        return "search-manifest"
    if value == "publication-policy.json":
        return "publication-policy"
    if value == "providers.json":
        return "providers"
    if value == "boards.json":
        return "boards"
    if value == "jobs/latest.json":
        return "jobs-bootstrap"
    if value.startswith("jobs/chunks/"):
        return "jobs-chunk"
    if value.startswith("jobs-details/"):
        return "job-details"
    if value == "jobs-detail-ids.json":
        return "job-detail-ids"
    if value == "jobs-indexable-ids.json":
        return "job-indexable-ids"
    if value == "lineage-aggregate.json":
        return "lineage-aggregate"
    return "artifact"


def _semantic_count(payload: Any, role: str) -> int:
    if isinstance(payload, dict):
        if role == "publication-policy" and isinstance(payload.get("sourceCount"), int):
            return payload["sourceCount"]
        if role == "lineage-aggregate":
            counts = payload.get("counts")
            if isinstance(counts, dict) and isinstance(counts.get("jobs"), int):
                return counts["jobs"]
        for key in ("rows", "ids"):
            values = payload.get(key)
            if isinstance(values, list):
                return len(values)
        if isinstance(payload.get("count"), int):
            return payload["count"]
        return len(payload)
    if isinstance(payload, list):
        return len(payload)
    return 1


def _disk_file_paths(root: Path) -> tuple[set[Path], list[str]]:
    paths: set[Path] = set()
    errors: list[str] = []
    if not root.is_dir():
        return paths, [f"release root is not a directory: {root}"]
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*dirnames, *filenames]:
            child = directory_path / name
            relative = child.relative_to(root)
            if child.is_symlink():
                errors.append(
                    f"release must not contain symlink: {relative.as_posix()}"
                )
        for filename in filenames:
            file_path = directory_path / filename
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                errors.append(
                    "release must contain regular files only: "
                    f"{file_path.relative_to(root).as_posix()}"
                )
            else:
                paths.add(file_path.relative_to(root))
    paths.discard(Path(MANIFEST_FILE))
    return paths, errors


def _safe_relative_path_error(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return "must be a non-empty string"
    if "\\" in value or "\x00" in value:
        return "must use safe POSIX separators"
    if len(value.encode("utf-8")) > _MAX_PORTABLE_PATH_BYTES:
        return f"must be at most {_MAX_PORTABLE_PATH_BYTES} UTF-8 bytes"
    if "%" in value or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return "must be a portable relative path"
    pure = PurePosixPath(value)
    if pure.is_absolute() or value.startswith("/"):
        return "must be relative"
    if any(part in {"", ".", ".."} for part in pure.parts):
        return "must not contain empty, dot, or traversal components"
    if pure.as_posix() != value:
        return "must be normalized"
    if any(not _PORTABLE_PATH_SEGMENT_RE.fullmatch(part) for part in pure.parts):
        return "must use portable ASCII path segments"
    return None


def _read_json_strict(path: Path) -> Any:
    with path.open("rb") as json_file:
        return _decode_json_strict(json_file.read())


def _decode_json_strict(content: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKeyError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), object_pairs_hook=object_pairs)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _forbidden_key_errors(path: Path, payload: Any) -> list[str]:
    errors: list[str] = []

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                nested_location = f"{location}.{key}" if location else key
                if key in FORBIDDEN_PRIVATE_KEYS:
                    errors.append(
                        f"file {path.as_posix()} contains forbidden private field "
                        f"{key!r} at {nested_location}"
                    )
                walk(nested, nested_location)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{location}[{index}]")

    walk(payload, "")
    return errors


def _secret_value_errors(path: Path, payload: Any) -> list[str]:
    errors: list[str] = []

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                nested_location = f"{location}.{key}" if location else key
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
                if _is_secret_key(normalized_key):
                    errors.append(
                        f"file {path.as_posix()} contains secret-like field "
                        f"{key!r} at {nested_location}"
                    )
                walk(nested, nested_location)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{location}[{index}]")
        elif isinstance(value, str) and value.casefold().startswith(
            ("http://", "https://")
        ):
            try:
                parsed = urlsplit(value)
            except ValueError:
                return
            if parsed.username or parsed.password:
                errors.append(
                    f"file {path.as_posix()} contains credential-bearing URL at {location}"
                )
            for key, _query_value in parse_qsl(parsed.query, keep_blank_values=True):
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
                if _is_secret_key(normalized_key, query=True):
                    errors.append(
                        f"file {path.as_posix()} contains secret-like URL query key "
                        f"{key!r} at {location}"
                    )

    walk(payload, "")
    return errors


def _is_secret_key(normalized_key: str, *, query: bool = False) -> bool:
    if normalized_key in FORBIDDEN_SECRET_KEYS:
        return True
    # Credential-bearing systems commonly namespace a sensitive parameter
    # (for example ``x-algolia-api-key``). Avoid suffix matching the generic
    # word ``token`` so legitimate public fields such as ``skillTokens`` stay
    # publishable.
    sensitive_suffixes = (
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "credential",
        "password",
        "passwd",
        "refreshtoken",
        "secret",
    )
    if normalized_key.endswith(sensitive_suffixes):
        return True
    return query and normalized_key.endswith("token")


def _validate_channel_name(channel: str) -> None:
    if not isinstance(channel, str) or not _CHANNEL_RE.fullmatch(channel):
        raise ValueError(
            "channel must be 1-63 lowercase alphanumeric/hyphen characters"
        )
