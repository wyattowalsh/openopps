"""Atomic quarantine-bundle writing and hostile offline verification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import ctypes
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime, timedelta
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
from types import MappingProxyType
from typing import Any, Self, TypeAlias
import unicodedata

from pydantic import ValidationError

from openopps.discovery.canonical import (
    CanonicalJSONError,
    canonical_json_bytes,
    decode_canonical_json,
)
from openopps.discovery.secrets import SecretDetectedError, admit_scanned_content


BUNDLE_SCHEMA_VERSION = "openopps.discovery.bundle.v1"
MANIFEST_NAME = "manifest.json"
SHA256_LENGTH = 64
SemanticVersion: TypeAlias = int | str
_TERMINAL_ACCOUNTING_MODELS = frozenset(
    {"ChannelOperationAccounting", "ScoutCandidateAccounting"}
)
_MANIFEST_FIELDS = frozenset(
    {
        "configurationSha256",
        "executionId",
        "manifestId",
        "memberCount",
        "members",
        "memberSetSha256",
        "observedAt",
        "profileId",
        "profileVersion",
        "runState",
        "schemaVersion",
        "toolVersion",
    }
)
_MEMBER_FIELDS = frozenset(
    {"mediaType", "path", "provenanceId", "role", "sha256", "sizeBytes"}
)


class BundleVerificationError(ValueError):
    """Raised when an offline bundle cannot be proven exact and immutable."""


class BundleManifestError(BundleVerificationError):
    """Raised when a bundle manifest violates its strict schema."""


class BundleWriteError(OSError):
    """Raised when an incomplete candidate bundle cannot be published."""


class BundleAlreadyExistsError(BundleWriteError):
    """Raised when a completed content-addressed bundle already exists."""


@dataclass(frozen=True, slots=True)
class BundleResource:
    """One trusted in-memory resource selected for a quarantine bundle."""

    data: bytes
    media_type: str
    path: str
    provenance_id: str
    role: str


@dataclass(frozen=True, slots=True)
class BundleFileIdentity:
    """Stable identity fields sampled before and after one no-follow read."""

    device: int
    inode: int
    link_count: int
    mode: int
    size_bytes: int
    owner_uid: int = dataclass_field(default_factory=os.geteuid)
    modified_ns: int = 0
    changed_ns: int = 0


@dataclass(frozen=True, slots=True)
class BundleMemberSemanticContract:
    """Trusted role-specific model and version contract for canonical JSON bytes."""

    model_name: str
    schema_version_field: str | None = None
    supported_schema_versions: frozenset[SemanticVersion] = frozenset()
    parser_version_field: str | None = None
    supported_parser_versions: frozenset[str] = frozenset()
    require_terminal_accounting_closure: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name:
            raise BundleVerificationError("semantic model name must be explicit")
        if (self.schema_version_field is None) != (not self.supported_schema_versions):
            raise BundleVerificationError(
                "semantic schema version field and allowlist must be configured together"
            )
        if self.schema_version_field is not None and (
            not isinstance(self.schema_version_field, str)
            or not self.schema_version_field
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, str))
                or (isinstance(value, str) and not value)
                for value in self.supported_schema_versions
            )
        ):
            raise BundleVerificationError("semantic schema version policy is invalid")
        if (self.parser_version_field is None) != (not self.supported_parser_versions):
            raise BundleVerificationError(
                "semantic parser version field and allowlist must be configured together"
            )
        if self.parser_version_field is not None and (
            not isinstance(self.parser_version_field, str)
            or not self.parser_version_field
            or any(
                not isinstance(value, str) or not value
                for value in self.supported_parser_versions
            )
        ):
            raise BundleVerificationError("semantic parser version policy is invalid")
        if (
            self.require_terminal_accounting_closure
            and self.model_name not in _TERMINAL_ACCOUNTING_MODELS
        ):
            raise BundleVerificationError(
                "terminal accounting closure requires an accounting model"
            )


@dataclass(frozen=True, slots=True)
class BundleVerificationPolicy:
    """Trusted freshness, format, role, and structural verification policy."""

    max_evidence_age: timedelta
    now: datetime
    replayed_manifest_ids: frozenset[str]
    revoked_manifest_ids: frozenset[str]
    supported_profiles: frozenset[tuple[str, str]]
    supported_schema_versions: frozenset[str]
    required_member_roles: frozenset[str]
    supported_member_roles: frozenset[str]
    canonical_json_roles: frozenset[str]
    semantic_member_contracts: Mapping[str, BundleMemberSemanticContract] = (
        dataclass_field(default_factory=lambda: MappingProxyType({}))
    )
    max_manifest_bytes: int = 1_048_576
    max_member_count: int = 1_024
    max_directory_count: int = 16_384
    max_member_bytes: int = 4_194_304
    max_total_member_bytes: int = 67_108_864

    def __post_init__(self) -> None:
        limits = (
            self.max_manifest_bytes,
            self.max_member_count,
            self.max_directory_count,
            self.max_member_bytes,
            self.max_total_member_bytes,
        )
        if any(
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
            for limit in limits
        ):
            raise BundleVerificationError("bundle verification limits must be positive")

        # These fields predate the promotion-intent ledger. They remain accepted so
        # callers can migrate without an API flag day, but a semantic manifest digest
        # is reusable content identity and is never a global replay or revocation key.
        # Replay enforcement belongs to decisionId and promotionIntentDigest.
        for legacy_values in (
            self.replayed_manifest_ids,
            self.revoked_manifest_ids,
        ):
            if not isinstance(legacy_values, frozenset) or any(
                not _is_sha256(value) for value in legacy_values
            ):
                raise BundleVerificationError(
                    "legacy manifest identity policy values must be lowercase SHA-256"
                )

        role_sets = (
            self.required_member_roles,
            self.supported_member_roles,
            self.canonical_json_roles,
        )
        if any(not isinstance(values, frozenset) for values in role_sets) or any(
            not isinstance(value, str) or not value or value != value.strip()
            for values in role_sets
            for value in values
        ):
            raise BundleVerificationError(
                "trusted member-role policies must contain trimmed strings"
            )
        if not self.required_member_roles <= self.supported_member_roles:
            raise BundleVerificationError(
                "required member roles must be a subset of supported roles"
            )
        if not self.canonical_json_roles <= self.supported_member_roles:
            raise BundleVerificationError(
                "canonical JSON roles must be a subset of supported roles"
            )
        if not isinstance(self.semantic_member_contracts, Mapping):
            raise BundleVerificationError(
                "semantic member contracts must be an explicit role mapping"
            )
        contracts = dict(self.semantic_member_contracts)
        if set(contracts) != set(self.canonical_json_roles) or any(
            not isinstance(role, str)
            or not role
            or not isinstance(contract, BundleMemberSemanticContract)
            for role, contract in contracts.items()
        ):
            raise BundleVerificationError(
                "every canonical JSON role requires one explicit semantic contract"
            )
        from openopps.discovery.schemas import discovery_schema_models

        known_models = discovery_schema_models()
        if any(
            contract.model_name not in known_models for contract in contracts.values()
        ):
            raise BundleVerificationError("semantic member model is unknown")
        object.__setattr__(
            self,
            "semantic_member_contracts",
            MappingProxyType(dict(sorted(contracts.items()))),
        )


@dataclass(frozen=True, slots=True)
class VerifiedProfileBinding:
    """Exact schema-validated profile evidence retained by the verifier."""

    member_path: str
    member_sha256: str
    profile_id: str
    profile_version: str
    profile_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedResourceBinding:
    """One verified semantic observation linked to its exact raw member bytes."""

    manifest_id: str
    profile_id: str
    profile_version: str
    profile_digest: str
    configuration_sha256: str
    observed_resource_member_path: str
    observed_resource_member_sha256: str
    resource_id: str
    raw_member_path: str
    raw_member_provenance_id: str
    raw_member_role: str
    raw_member_media_type: str
    raw_member_sha256: str
    raw_member_size_bytes: int
    final_locator: str = dataclass_field(repr=False)
    validated_address: str = dataclass_field(repr=False)
    observed_at: datetime
    etag: str | None = dataclass_field(repr=False)
    last_modified: str | None = dataclass_field(repr=False)
    content: bytes = dataclass_field(repr=False)
    secret_detector_version: str


_VERIFIED_BUNDLE_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedBundle:
    """Sealed verifier result; callers cannot assert their own provenance graph."""

    manifest_id: str
    member_paths: tuple[str, ...]
    profile_id: str
    profile_version: str
    configuration_sha256: str
    manifest_observed_at: datetime
    profile_binding: VerifiedProfileBinding | None
    resource_bindings: tuple[VerifiedResourceBinding, ...] = dataclass_field(repr=False)
    _seal: object = dataclass_field(repr=False, compare=False)

    def __new__(cls) -> Self:
        del cls
        raise TypeError("VerifiedBundle can only be created by verify_bundle")

    def _is_verifier_sealed(self) -> bool:
        return getattr(self, "_seal", None) is _VERIFIED_BUNDLE_SEAL


def _seal_verified_bundle(
    *,
    manifest_id: str,
    member_paths: tuple[str, ...],
    profile_id: str,
    profile_version: str,
    configuration_sha256: str,
    manifest_observed_at: datetime,
    profile_binding: VerifiedProfileBinding | None,
    resource_bindings: tuple[VerifiedResourceBinding, ...],
) -> VerifiedBundle:
    verified = object.__new__(VerifiedBundle)
    values: tuple[tuple[str, object], ...] = (
        ("manifest_id", manifest_id),
        ("member_paths", member_paths),
        ("profile_id", profile_id),
        ("profile_version", profile_version),
        ("configuration_sha256", configuration_sha256),
        ("manifest_observed_at", manifest_observed_at),
        ("profile_binding", profile_binding),
        ("resource_bindings", resource_bindings),
        ("_seal", _VERIFIED_BUNDLE_SEAL),
    )
    for field_name, value in values:
        object.__setattr__(verified, field_name, value)
    return verified


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise BundleManifestError(f"{field} must be a non-empty trimmed string")
    return value


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BundleManifestError(f"{field} must be a non-negative integer")
    return value


def _parse_observed_at(value: object) -> datetime:
    """Parse the sole accepted UTC wire spelling for an observation instant."""

    observed_text = _require_string(value, "observedAt")
    if not observed_text.endswith("Z"):
        raise BundleManifestError("observedAt must use canonical UTC spelling")
    try:
        observed_at = datetime.fromisoformat(observed_text.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise BundleManifestError("observedAt is not a valid UTC instant") from error
    canonical_text = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if observed_text != canonical_text:
        raise BundleManifestError("observedAt must use canonical UTC spelling")
    return observed_at.astimezone(UTC)


def validate_member_path(value: str) -> PurePosixPath:
    """Validate a relative, unambiguous POSIX bundle member path."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise BundleManifestError("member path must be a non-empty trimmed string")
    lowered = value.lower()
    if "\\" in value or "%2f" in lowered or "%5c" in lowered:
        raise BundleManifestError("member path contains an encoded or native separator")
    if value.startswith("/") or value.endswith("/") or "//" in value:
        raise BundleManifestError("member path must be a relative POSIX file path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise BundleManifestError("member path contains an unsafe component")
    if path.as_posix() == MANIFEST_NAME:
        raise BundleManifestError("manifest.json is a reserved bundle path")
    return path


def validate_member_paths(values: Iterable[str]) -> tuple[PurePosixPath, ...]:
    """Validate exact paths and reject portable case/Unicode collisions."""

    paths: list[PurePosixPath] = []
    portable_names: set[str] = set()
    for value in values:
        path = validate_member_path(value)
        portable = unicodedata.normalize("NFC", path.as_posix()).casefold()
        if portable in portable_names:
            raise BundleManifestError("bundle member paths collide portably")
        portable_names.add(portable)
        paths.append(path)
    return tuple(paths)


def _normalize_member(member: Mapping[str, Any]) -> dict[str, Any]:
    if set(member) != _MEMBER_FIELDS:
        raise BundleManifestError("bundle member fields do not match the v1 schema")
    path = validate_member_path(_require_string(member.get("path"), "member.path"))
    digest = member.get("sha256")
    if not _is_sha256(digest):
        raise BundleManifestError("member.sha256 must be lowercase SHA-256")
    return {
        "mediaType": _require_string(member.get("mediaType"), "member.mediaType"),
        "path": path.as_posix(),
        "provenanceId": _require_string(
            member.get("provenanceId"), "member.provenanceId"
        ),
        "role": _require_string(member.get("role"), "member.role"),
        "sha256": digest,
        "sizeBytes": _require_non_negative_int(
            member.get("sizeBytes"), "member.sizeBytes"
        ),
    }


def _normalize_members(members: object) -> list[dict[str, Any]]:
    if not isinstance(members, list):
        raise BundleManifestError("members must be an array")
    normalized: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, Mapping):
            raise BundleManifestError("every member must be an object")
        normalized.append(_normalize_member(member))
    validate_member_paths(member["path"] for member in normalized)
    return sorted(normalized, key=lambda member: member["path"])


def compute_member_set_sha256(members: Sequence[Mapping[str, Any]]) -> str:
    """Hash the complete path-sorted canonical member array."""

    normalized = _normalize_members(list(members))
    return _sha256(canonical_json_bytes(normalized))


def _semantic_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    semantic = dict(manifest)
    semantic.pop("manifestId", None)
    semantic.pop("executionId", None)
    if "members" in semantic:
        semantic["members"] = _normalize_members(semantic["members"])
    return semantic


def compute_manifest_id(manifest: Mapping[str, Any]) -> str:
    """Compute a non-self-referential semantic manifest identity."""

    return _sha256(canonical_json_bytes(_semantic_manifest(manifest)))


def _normalize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if set(manifest) != _MANIFEST_FIELDS:
        raise BundleManifestError("manifest fields do not match the v1 schema")
    schema_version = _require_string(manifest.get("schemaVersion"), "schemaVersion")
    if schema_version != BUNDLE_SCHEMA_VERSION:
        raise BundleManifestError("unsupported bundle schema version")
    members = _normalize_members(manifest.get("members"))
    member_count = _require_non_negative_int(manifest.get("memberCount"), "memberCount")
    if member_count != len(members):
        raise BundleManifestError("memberCount does not match members")
    member_set_sha256 = manifest.get("memberSetSha256")
    if not _is_sha256(member_set_sha256):
        raise BundleManifestError("memberSetSha256 must be lowercase SHA-256")
    if member_set_sha256 != compute_member_set_sha256(members):
        raise BundleManifestError("memberSetSha256 does not match members")
    for field in ("configurationSha256", "manifestId"):
        if not _is_sha256(manifest.get(field)):
            raise BundleManifestError(f"{field} must be lowercase SHA-256")
    if manifest.get("runState") != "complete":
        raise BundleManifestError("only a complete terminal manifest is valid")
    observed_at = _parse_observed_at(manifest.get("observedAt"))
    normalized = {
        "configurationSha256": manifest["configurationSha256"],
        "executionId": _require_string(manifest.get("executionId"), "executionId"),
        "manifestId": manifest["manifestId"],
        "memberCount": member_count,
        "members": members,
        "memberSetSha256": member_set_sha256,
        "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "profileId": _require_string(manifest.get("profileId"), "profileId"),
        "profileVersion": _require_string(
            manifest.get("profileVersion"), "profileVersion"
        ),
        "runState": "complete",
        "schemaVersion": schema_version,
        "toolVersion": _require_string(manifest.get("toolVersion"), "toolVersion"),
    }
    if compute_manifest_id(normalized) != normalized["manifestId"]:
        raise BundleManifestError("manifestId does not match semantic content")
    return normalized


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Validate and encode a canonical manifest with sorted semantic arrays."""

    return canonical_json_bytes(_normalize_manifest(manifest))


def parse_manifest_bytes(raw: bytes) -> dict[str, Any]:
    """Parse one exact canonical v1 bundle manifest."""

    try:
        value = decode_canonical_json(raw)
    except CanonicalJSONError as error:
        raise BundleManifestError("manifest is not canonical JSON") from error
    if not isinstance(value, Mapping):
        raise BundleManifestError("manifest root must be an object")
    normalized = _normalize_manifest(value)
    if canonical_json_bytes(normalized) != raw:
        raise BundleManifestError("manifest semantic arrays are not canonical")
    return normalized


def _identity_from_stat(result: os.stat_result) -> BundleFileIdentity:
    return BundleFileIdentity(
        device=result.st_dev,
        inode=result.st_ino,
        link_count=result.st_nlink,
        mode=result.st_mode,
        size_bytes=result.st_size,
        owner_uid=result.st_uid,
        modified_ns=result.st_mtime_ns,
        changed_ns=result.st_ctime_ns,
    )


def validate_file_identity(
    before: BundleFileIdentity, after: BundleFileIdentity
) -> None:
    """Require one stable regular file with the exact private file mode."""

    for identity in (before, after):
        if not stat.S_ISREG(identity.mode):
            raise BundleVerificationError("bundle member is not a regular file")
        if identity.link_count != 1:
            raise BundleVerificationError("bundle member must have one hard link")
        if identity.owner_uid != os.geteuid():
            raise BundleVerificationError("bundle member must be owned by this process")
        if stat.S_IMODE(identity.mode) != 0o600:
            raise BundleVerificationError(
                "bundle member must use exact private mode 0o600"
            )
    if before != after:
        raise BundleVerificationError("bundle member identity changed while reading")


def _validate_directory_identity(
    before: BundleFileIdentity, after: BundleFileIdentity
) -> None:
    """Require one stable real directory with the exact private mode."""

    for identity in (before, after):
        if not stat.S_ISDIR(identity.mode):
            raise BundleVerificationError("bundle directory is not a real directory")
        if identity.owner_uid != os.geteuid():
            raise BundleVerificationError(
                "bundle directory must be owned by this process"
            )
        if stat.S_IMODE(identity.mode) != 0o700:
            raise BundleVerificationError(
                "bundle directories must use exact private mode 0o700"
            )
    if before != after:
        raise BundleVerificationError("bundle directory identity changed while reading")


def _validate_opened_identity(
    path_identity: BundleFileIdentity,
    opened_identity: BundleFileIdentity,
    *,
    kind: str,
) -> None:
    if path_identity != opened_identity:
        raise BundleVerificationError(
            f"bundle {kind} path identity changed while opening"
        )


def _no_follow_flags(*, directory: bool = False) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise BundleVerificationError("no-follow file opens are unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if directory:
        if not hasattr(os, "O_DIRECTORY"):
            raise BundleVerificationError("directory-only opens are unavailable")
        flags |= os.O_DIRECTORY
    return flags


def _read_open_file(
    descriptor: int,
    before: BundleFileIdentity,
    *,
    max_bytes: int,
) -> tuple[bytes, BundleFileIdentity]:
    validate_file_identity(before, before)
    if before.size_bytes > max_bytes:
        raise BundleVerificationError("bundle member exceeds its trusted byte limit")
    chunks: list[bytes] = []
    remaining = before.size_bytes
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    extra = os.read(descriptor, 1)
    after = _identity_from_stat(os.fstat(descriptor))
    validate_file_identity(before, after)
    data = b"".join(chunks)
    if remaining or extra or len(data) != before.size_bytes:
        raise BundleVerificationError("bundle member size changed while reading")
    return data, after


def _read_regular_file(path: Path, *, max_bytes: int | None = None) -> bytes:
    """Read one path without links and prove its path identity stayed stable."""

    try:
        path_before = _identity_from_stat(path.lstat())
        descriptor = os.open(path, _no_follow_flags())
    except OSError as error:
        raise BundleVerificationError(
            f"cannot safely open bundle member {path.name}"
        ) from error
    try:
        opened_before = _identity_from_stat(os.fstat(descriptor))
        _validate_opened_identity(path_before, opened_before, kind="member")
        data, opened_after = _read_open_file(
            descriptor,
            opened_before,
            max_bytes=max_bytes if max_bytes is not None else opened_before.size_bytes,
        )
    finally:
        os.close(descriptor)
    try:
        path_after = _identity_from_stat(path.lstat())
    except OSError as error:
        raise BundleVerificationError(
            f"bundle member path disappeared after reading {path.name}"
        ) from error
    _validate_opened_identity(path_after, opened_after, kind="member")
    return data


@dataclass(frozen=True, slots=True)
class _BundleTreeSnapshot:
    files: Mapping[str, bytes]
    file_identities: Mapping[str, BundleFileIdentity]
    directories: frozenset[str]
    directory_identities: Mapping[str, BundleFileIdentity]


def _stat_at(directory_descriptor: int, name: str) -> BundleFileIdentity:
    try:
        result = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise BundleVerificationError("bundle entry identity is unavailable") from error
    return _identity_from_stat(result)


def _read_regular_file_at(
    directory_descriptor: int,
    name: str,
    *,
    path_identity: BundleFileIdentity,
    max_bytes: int,
) -> tuple[bytes, BundleFileIdentity]:
    try:
        descriptor = os.open(
            name,
            _no_follow_flags(),
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        raise BundleVerificationError("cannot safely open bundle member") from error
    try:
        opened_before = _identity_from_stat(os.fstat(descriptor))
        _validate_opened_identity(path_identity, opened_before, kind="member")
        data, opened_after = _read_open_file(
            descriptor,
            opened_before,
            max_bytes=max_bytes,
        )
    finally:
        os.close(descriptor)
    path_after = _stat_at(directory_descriptor, name)
    _validate_opened_identity(path_after, opened_after, kind="member")
    return data, opened_after


def _walk_open_bundle(
    directory_descriptor: int,
    *,
    policy: BundleVerificationPolicy,
) -> _BundleTreeSnapshot:
    files: dict[str, bytes] = {}
    file_identities: dict[str, BundleFileIdentity] = {}
    directories: set[str] = set()
    directory_identities: dict[str, BundleFileIdentity] = {}
    admitted_member_bytes = 0
    max_directory_count = policy.max_directory_count

    def walk(current_descriptor: int, relative_directory: PurePosixPath) -> None:
        nonlocal admitted_member_bytes
        current_before = _identity_from_stat(os.fstat(current_descriptor))
        _validate_directory_identity(current_before, current_before)
        try:
            names_before = tuple(sorted(os.listdir(current_descriptor)))
        except OSError as error:
            raise BundleVerificationError(
                "bundle directory cannot be enumerated safely"
            ) from error
        for name in names_before:
            relative = (
                PurePosixPath(name)
                if relative_directory == PurePosixPath(".")
                else relative_directory / name
            )
            relative_text = relative.as_posix()
            if relative_text != MANIFEST_NAME:
                validate_member_path(relative_text)
            path_identity = _stat_at(current_descriptor, name)
            if stat.S_ISDIR(path_identity.mode):
                _validate_directory_identity(path_identity, path_identity)
                directories.add(relative_text)
                if len(directories) > max_directory_count:
                    raise BundleVerificationError(
                        "bundle exceeds its trusted directory-count limit"
                    )
                try:
                    child_descriptor = os.open(
                        name,
                        _no_follow_flags(directory=True),
                        dir_fd=current_descriptor,
                    )
                except OSError as error:
                    raise BundleVerificationError(
                        "cannot safely open bundle directory"
                    ) from error
                try:
                    child_before = _identity_from_stat(os.fstat(child_descriptor))
                    _validate_opened_identity(
                        path_identity,
                        child_before,
                        kind="directory",
                    )
                    walk(child_descriptor, relative)
                    child_after = _identity_from_stat(os.fstat(child_descriptor))
                    _validate_directory_identity(child_before, child_after)
                finally:
                    os.close(child_descriptor)
                path_after = _stat_at(current_descriptor, name)
                _validate_opened_identity(
                    path_after,
                    child_after,
                    kind="directory",
                )
                directory_identities[relative_text] = child_after
                continue
            if not stat.S_ISREG(path_identity.mode):
                raise BundleVerificationError(
                    "bundle contains a symlinked or special entry"
                )
            if len(files) >= policy.max_member_count + 1:
                raise BundleVerificationError(
                    "bundle exceeds its trusted member-count limit"
                )
            byte_limit = (
                policy.max_manifest_bytes
                if relative_text == MANIFEST_NAME
                else policy.max_member_bytes
            )
            data, opened_identity = _read_regular_file_at(
                current_descriptor,
                name,
                path_identity=path_identity,
                max_bytes=byte_limit,
            )
            if relative_text in files:
                raise BundleVerificationError("bundle contains a duplicate member path")
            files[relative_text] = data
            file_identities[relative_text] = opened_identity
            if relative_text != MANIFEST_NAME:
                admitted_member_bytes += len(data)
                if admitted_member_bytes > policy.max_total_member_bytes:
                    raise BundleVerificationError(
                        "bundle exceeds its trusted aggregate byte limit"
                    )
        try:
            names_after = tuple(sorted(os.listdir(current_descriptor)))
        except OSError as error:
            raise BundleVerificationError(
                "bundle directory cannot be re-enumerated safely"
            ) from error
        if names_before != names_after:
            raise BundleVerificationError(
                "bundle directory entries changed while reading"
            )
        current_after = _identity_from_stat(os.fstat(current_descriptor))
        _validate_directory_identity(current_before, current_after)

    walk(directory_descriptor, PurePosixPath("."))
    return _BundleTreeSnapshot(
        files=files,
        file_identities=file_identities,
        directories=frozenset(directories),
        directory_identities=directory_identities,
    )


def _read_stable_bundle_tree(
    root: Path,
    *,
    policy: BundleVerificationPolicy,
) -> _BundleTreeSnapshot:
    try:
        path_before = _identity_from_stat(root.lstat())
        root_descriptor = os.open(root, _no_follow_flags(directory=True))
    except OSError as error:
        raise BundleVerificationError("bundle root is unavailable") from error
    try:
        root_before = _identity_from_stat(os.fstat(root_descriptor))
        _validate_directory_identity(path_before, path_before)
        _validate_opened_identity(path_before, root_before, kind="root")
        first = _walk_open_bundle(root_descriptor, policy=policy)
        second = _walk_open_bundle(root_descriptor, policy=policy)
        if first != second:
            raise BundleVerificationError(
                "bundle tree identity or bytes changed while verifying"
            )
        root_after = _identity_from_stat(os.fstat(root_descriptor))
        _validate_directory_identity(root_before, root_after)
    finally:
        os.close(root_descriptor)
    try:
        path_after = _identity_from_stat(root.lstat())
    except OSError as error:
        raise BundleVerificationError(
            "bundle root path disappeared while verifying"
        ) from error
    _validate_opened_identity(path_after, root_after, kind="root")
    return second


def _expected_directories(paths: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for value in paths:
        parts = validate_member_path(value).parts[:-1]
        for length in range(1, len(parts) + 1):
            directories.add(PurePosixPath(*parts[:length]).as_posix())
    return directories


def _validate_policy(
    manifest: Mapping[str, Any], policy: BundleVerificationPolicy
) -> None:
    if policy.now.tzinfo is None:
        raise BundleVerificationError("verification clock must be timezone-aware")
    if policy.max_evidence_age < timedelta(0):
        raise BundleVerificationError("maximum evidence age cannot be negative")
    if manifest["schemaVersion"] not in policy.supported_schema_versions:
        raise BundleVerificationError("bundle schema is not supported by policy")
    profile = (manifest["profileId"], manifest["profileVersion"])
    if profile not in policy.supported_profiles:
        raise BundleVerificationError("bundle profile is not supported by policy")
    observed_at = _parse_observed_at(manifest["observedAt"])
    now = policy.now.astimezone(UTC)
    if observed_at > now:
        raise BundleVerificationError("bundle evidence is future-dated")
    if now - observed_at > policy.max_evidence_age:
        raise BundleVerificationError("bundle evidence is stale")


def _version_is_admitted(
    value: object,
    admitted: frozenset[SemanticVersion],
) -> bool:
    return any(
        type(value) is type(expected) and value == expected for expected in admitted
    )


def _validate_semantic_member(
    data: bytes,
    *,
    contract: BundleMemberSemanticContract,
) -> Any:
    """Validate exact canonical bytes against one trusted generated-model contract."""

    from openopps.discovery.schemas import discovery_schema_models

    try:
        payload = decode_canonical_json(data)
        if not isinstance(payload, dict):
            raise BundleVerificationError("semantic bundle member must be an object")
        if contract.schema_version_field is not None:
            if contract.schema_version_field not in payload or not _version_is_admitted(
                payload[contract.schema_version_field],
                contract.supported_schema_versions,
            ):
                raise BundleVerificationError(
                    "semantic bundle member schema version is missing or unsupported"
                )
        if contract.parser_version_field is not None:
            parser_version = payload.get(contract.parser_version_field)
            if (
                not isinstance(parser_version, str)
                or parser_version not in contract.supported_parser_versions
            ):
                raise BundleVerificationError(
                    "semantic bundle member parser version is missing or unsupported"
                )
        model_type = discovery_schema_models()[contract.model_name]
        validated = model_type.model_validate_json(data, strict=True)
        expected_bytes = canonical_json_bytes(
            validated.model_dump(mode="json", by_alias=True, round_trip=True)
        )
        if expected_bytes != data:
            raise BundleVerificationError(
                "semantic bundle member does not use its exact schema encoding"
            )
        if contract.require_terminal_accounting_closure:
            if contract.model_name == "ChannelOperationAccounting" and (
                getattr(validated, "channel_state", None) == "nonterminal"
                or bool(getattr(validated, "request_in_flight", 0))
                or bool(getattr(validated, "unfinished_operation_ids", ()))
            ):
                raise BundleVerificationError(
                    "terminal operation accounting denominator is not closed"
                )
        return validated
    except BundleVerificationError:
        raise
    except CanonicalJSONError:
        raise BundleVerificationError(
            "trusted canonical JSON member role contains noncanonical bytes"
        ) from None
    except (RecursionError, TypeError, ValueError, ValidationError):
        raise BundleVerificationError(
            "semantic bundle member does not match its trusted schema"
        ) from None


@dataclass(frozen=True, slots=True)
class _ValidatedSemanticMember:
    manifest_member: Mapping[str, Any]
    contract: BundleMemberSemanticContract
    validated: Any


def _validate_member_role_policy(
    manifest: Mapping[str, Any],
    snapshot: _BundleTreeSnapshot,
    policy: BundleVerificationPolicy,
) -> tuple[_ValidatedSemanticMember, ...]:
    observed_roles = frozenset(member["role"] for member in manifest["members"])
    unsupported_roles = observed_roles - policy.supported_member_roles
    if unsupported_roles:
        raise BundleVerificationError(
            "bundle declares a member role unsupported by trusted policy"
        )
    missing_roles = policy.required_member_roles - observed_roles
    if missing_roles:
        raise BundleVerificationError(
            "bundle is missing a member role required by trusted policy"
        )
    validated_members: list[_ValidatedSemanticMember] = []
    for member in manifest["members"]:
        if member["role"] not in policy.canonical_json_roles:
            continue
        contract = policy.semantic_member_contracts[member["role"]]
        validated = _validate_semantic_member(
            snapshot.files[member["path"]],
            contract=contract,
        )
        validated_members.append(
            _ValidatedSemanticMember(
                manifest_member=MappingProxyType(dict(member)),
                contract=contract,
                validated=validated,
            )
        )
    return tuple(validated_members)


def _derive_verified_resource_graph(
    manifest: Mapping[str, Any],
    snapshot: _BundleTreeSnapshot,
    policy: BundleVerificationPolicy,
    semantic_members: tuple[_ValidatedSemanticMember, ...],
) -> tuple[VerifiedProfileBinding | None, tuple[VerifiedResourceBinding, ...]]:
    """Derive reusable evidence only from one closed, verifier-observed graph."""

    profile_members = tuple(
        member
        for member in semantic_members
        if member.contract.model_name == "TrustedDiscoveryProfile"
    )
    resource_members = tuple(
        member
        for member in semantic_members
        if member.contract.model_name == "ObservedResource"
    )
    if len(profile_members) > 1:
        raise BundleVerificationError("bundle profile evidence is ambiguous")
    if not profile_members:
        return None, ()

    profile_member = profile_members[0]
    profile = profile_member.validated
    if (
        profile.profile_id != manifest["profileId"]
        or profile.profile_version != manifest["profileVersion"]
    ):
        raise BundleVerificationError(
            "bundle profile evidence does not match manifest identity"
        )
    profile_provenance = profile_member.manifest_member["provenanceId"]
    if profile_provenance not in {
        profile.profile_digest,
        f"sha256:{profile.profile_digest}",
    }:
        raise BundleVerificationError(
            "bundle profile evidence provenance does not match profile digest"
        )
    profile_binding = VerifiedProfileBinding(
        member_path=profile_member.manifest_member["path"],
        member_sha256=profile_member.manifest_member["sha256"],
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_digest=profile.profile_digest,
    )
    if not resource_members:
        return profile_binding, ()

    manifest_observed_at = _parse_observed_at(manifest["observedAt"])
    manifest_members = tuple(manifest["members"])
    semantic_paths = frozenset(
        member.manifest_member["path"] for member in semantic_members
    )
    resource_ids: set[str] = set()
    bindings: list[VerifiedResourceBinding] = []
    for semantic_resource in resource_members:
        resource = semantic_resource.validated
        if resource.resource_id in resource_ids:
            raise BundleVerificationError(
                "bundle observed resource identity is duplicated"
            )
        resource_ids.add(resource.resource_id)
        if semantic_resource.manifest_member["provenanceId"] != resource.resource_id:
            raise BundleVerificationError(
                "observed resource provenance does not match resource identity"
            )
        raw_candidates = tuple(
            member
            for member in manifest_members
            if member["path"] not in semantic_paths
            and member["provenanceId"] == resource.resource_id
            and member["role"] == resource.role
            and member["mediaType"] == resource.media_type
            and member["sha256"] == resource.content_sha256
            and member["sizeBytes"] == resource.size_bytes
            and member["role"] not in policy.canonical_json_roles
        )
        if len(raw_candidates) > 1:
            raise BundleVerificationError(
                "observed resource raw-member binding is ambiguous"
            )
        if not raw_candidates:
            continue
        raw_member = raw_candidates[0]
        try:
            from openopps.discovery.transport import validate_public_locator

            locator = validate_public_locator(resource.final_locator)
        except Exception:
            raise BundleVerificationError(
                "observed resource locator is not canonical public HTTPS"
            ) from None
        if locator.url != resource.final_locator:
            raise BundleVerificationError(
                "observed resource locator is not canonical public HTTPS"
            )
        if resource.observed_at > manifest_observed_at:
            raise BundleVerificationError(
                "observed resource is newer than its containing manifest"
            )
        raw_content = snapshot.files[raw_member["path"]]
        try:
            scanned = admit_scanned_content(
                (raw_content,),
                max_bytes=policy.max_member_bytes,
                write=lambda admitted: None,
                digest=_sha256,
            )
        except SecretDetectedError as error:
            raise BundleVerificationError(error.reason_code) from None
        if (
            scanned.content_sha256 != raw_member["sha256"]
            or scanned.size_bytes != raw_member["sizeBytes"]
        ):
            raise BundleVerificationError(
                "verified resource scan does not match raw member"
            )
        bindings.append(
            VerifiedResourceBinding(
                manifest_id=manifest["manifestId"],
                profile_id=profile_binding.profile_id,
                profile_version=profile_binding.profile_version,
                profile_digest=profile_binding.profile_digest,
                configuration_sha256=manifest["configurationSha256"],
                observed_resource_member_path=(
                    semantic_resource.manifest_member["path"]
                ),
                observed_resource_member_sha256=(
                    semantic_resource.manifest_member["sha256"]
                ),
                resource_id=resource.resource_id,
                raw_member_path=raw_member["path"],
                raw_member_provenance_id=raw_member["provenanceId"],
                raw_member_role=raw_member["role"],
                raw_member_media_type=raw_member["mediaType"],
                raw_member_sha256=raw_member["sha256"],
                raw_member_size_bytes=raw_member["sizeBytes"],
                final_locator=locator.url,
                validated_address=resource.validated_address,
                observed_at=resource.observed_at,
                etag=resource.etag,
                last_modified=resource.last_modified,
                content=raw_content,
                secret_detector_version=scanned.detector_version,
            )
        )
    return profile_binding, tuple(
        sorted(
            bindings,
            key=lambda binding: (
                binding.final_locator,
                binding.resource_id,
                binding.raw_member_path,
            ),
        )
    )


def verify_bundle(root: Path, *, policy: BundleVerificationPolicy) -> VerifiedBundle:
    """Verify an exact, closed bundle without following links or using network I/O."""

    root = Path(root)
    snapshot = _read_stable_bundle_tree(root, policy=policy)
    try:
        manifest_bytes = snapshot.files[MANIFEST_NAME]
    except KeyError as error:
        raise BundleVerificationError("bundle manifest is missing") from error
    manifest = parse_manifest_bytes(manifest_bytes)
    expected_paths = {member["path"] for member in manifest["members"]}
    if len(manifest["members"]) > policy.max_member_count:
        raise BundleVerificationError("bundle exceeds its trusted member-count limit")
    declared_sizes = tuple(member["sizeBytes"] for member in manifest["members"])
    if any(size > policy.max_member_bytes for size in declared_sizes):
        raise BundleVerificationError("bundle member exceeds its trusted byte limit")
    if sum(declared_sizes) > policy.max_total_member_bytes:
        raise BundleVerificationError("bundle exceeds its trusted aggregate byte limit")
    actual_paths = set(snapshot.files)
    actual_directories = set(snapshot.directories)
    if actual_paths != expected_paths | {MANIFEST_NAME}:
        raise BundleVerificationError("bundle member set is not exact")
    if actual_directories != _expected_directories(expected_paths):
        raise BundleVerificationError("bundle directory set is not exact")
    for member in manifest["members"]:
        data = snapshot.files[member["path"]]
        if len(data) != member["sizeBytes"]:
            raise BundleVerificationError("bundle member size does not match manifest")
        if _sha256(data) != member["sha256"]:
            raise BundleVerificationError(
                "bundle member digest does not match manifest"
            )
    semantic_members = _validate_member_role_policy(manifest, snapshot, policy)
    _validate_policy(manifest, policy)
    profile_binding, resource_bindings = _derive_verified_resource_graph(
        manifest,
        snapshot,
        policy,
        semantic_members,
    )
    return _seal_verified_bundle(
        manifest_id=manifest["manifestId"],
        member_paths=tuple(sorted(expected_paths)),
        profile_id=manifest["profileId"],
        profile_version=manifest["profileVersion"],
        configuration_sha256=manifest["configurationSha256"],
        manifest_observed_at=_parse_observed_at(manifest["observedAt"]),
        profile_binding=profile_binding,
        resource_bindings=resource_bindings,
    )


def _resource_member(
    resource: BundleResource,
    *,
    content_sha256: str,
    size_bytes: int,
) -> dict[str, Any]:
    if not isinstance(resource.data, bytes):
        raise BundleManifestError("bundle resource data must be bytes")
    return _normalize_member(
        {
            "mediaType": resource.media_type,
            "path": resource.path,
            "provenanceId": resource.provenance_id,
            "role": resource.role,
            "sha256": content_sha256,
            "sizeBytes": size_bytes,
        }
    )


@dataclass(frozen=True, slots=True)
class _ScannedBundleResource:
    resource: BundleResource
    member: Mapping[str, Any]


def _preflight_manifest_limits(
    manifest: Mapping[str, Any],
    policy: BundleVerificationPolicy,
) -> None:
    members = manifest.get("members")
    if not isinstance(members, list):
        raise BundleManifestError("members must be an array")
    if len(members) > policy.max_member_count:
        raise BundleVerificationError("bundle exceeds its trusted member-count limit")
    total_bytes = 0
    for member in members:
        if not isinstance(member, Mapping):
            raise BundleManifestError("every member must be an object")
        size_bytes = _require_non_negative_int(
            member.get("sizeBytes"), "member.sizeBytes"
        )
        if size_bytes > policy.max_member_bytes:
            raise BundleVerificationError(
                "bundle member exceeds its trusted byte limit"
            )
        total_bytes += size_bytes
        if total_bytes > policy.max_total_member_bytes:
            raise BundleVerificationError(
                "bundle exceeds its trusted aggregate byte limit"
            )


def _scan_and_validate_resources(
    resources: Iterable[BundleResource],
    *,
    manifest: Mapping[str, Any],
    policy: BundleVerificationPolicy,
) -> tuple[_ScannedBundleResource, ...]:
    """Fully bound and secret-scan every resource before any filesystem mutation."""

    expected_members = _normalize_members(manifest["members"])
    expected_by_path = {member["path"]: member for member in expected_members}
    scanned: list[_ScannedBundleResource] = []
    observed_paths: set[str] = set()
    aggregate_bytes = 0
    for resource in resources:
        if len(scanned) >= policy.max_member_count:
            raise BundleVerificationError(
                "bundle exceeds its trusted member-count limit"
            )
        if not isinstance(resource, BundleResource):
            raise BundleManifestError("resources must contain BundleResource values")
        if not isinstance(resource.data, bytes):
            raise BundleManifestError("bundle resource data must be bytes")
        path = validate_member_path(resource.path).as_posix()
        if path in observed_paths:
            raise BundleManifestError(
                "resource stream contains a duplicate member path"
            )
        observed_paths.add(path)
        if path not in expected_by_path:
            raise BundleManifestError("resource stream does not match manifest members")
        size_bytes = len(resource.data)
        if size_bytes > policy.max_member_bytes:
            raise BundleVerificationError(
                "bundle member exceeds its trusted byte limit"
            )
        aggregate_bytes += size_bytes
        if aggregate_bytes > policy.max_total_member_bytes:
            raise BundleVerificationError(
                "bundle exceeds its trusted aggregate byte limit"
            )
        captured: list[bytes] = []
        try:
            admitted = admit_scanned_content(
                (resource.data,),
                max_bytes=policy.max_member_bytes,
                write=captured.append,
                digest=_sha256,
            )
        except SecretDetectedError as error:
            raise BundleWriteError(error.reason_code) from None
        if captured != [resource.data]:
            raise BundleWriteError("bundle resource scan did not close")
        member = _resource_member(
            resource,
            content_sha256=admitted.content_sha256,
            size_bytes=admitted.size_bytes,
        )
        if member != expected_by_path[path]:
            raise BundleManifestError("resource stream does not match manifest members")
        if member["role"] in policy.canonical_json_roles:
            _validate_semantic_member(
                resource.data,
                contract=policy.semantic_member_contracts[member["role"]],
            )
        scanned.append(_ScannedBundleResource(resource=resource, member=member))
    if len(scanned) != len(expected_members) or observed_paths != set(expected_by_path):
        raise BundleManifestError("resource stream does not match manifest members")
    return tuple(sorted(scanned, key=lambda item: str(item.member["path"])))


def _write_file_at(directory_descriptor: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_descriptor,
    )
    try:
        os.fchmod(descriptor, 0o600)
        before = _identity_from_stat(os.fstat(descriptor))
        validate_file_identity(before, before)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise BundleWriteError("bundle member write did not advance")
            view = view[written:]
        os.fsync(descriptor)
        after = _identity_from_stat(os.fstat(descriptor))
        validate_file_identity(after, after)
        path_after = _stat_at(directory_descriptor, name)
        _validate_opened_identity(path_after, after, kind="member")
    finally:
        os.close(descriptor)


def _open_or_create_private_directory_at(parent_descriptor: int, name: str) -> int:
    try:
        descriptor = os.open(
            name,
            _no_follow_flags(directory=True),
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        descriptor = os.open(
            name,
            _no_follow_flags(directory=True),
            dir_fd=parent_descriptor,
        )
    try:
        os.fchmod(descriptor, 0o700)
        opened = _identity_from_stat(os.fstat(descriptor))
        _validate_directory_identity(opened, opened)
        path_identity = _stat_at(parent_descriptor, name)
        _validate_opened_identity(path_identity, opened, kind="directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_output_root(path: Path) -> tuple[Path, int]:
    absolute = path if path.is_absolute() else path.absolute()
    if any(component in {"", ".", ".."} for component in absolute.parts[1:]):
        raise BundleWriteError("quarantine output root is ambiguous")
    descriptor = os.open(os.path.sep, _no_follow_flags(directory=True))
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(
                    component,
                    _no_follow_flags(directory=True),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(
                    component,
                    _no_follow_flags(directory=True),
                    dir_fd=descriptor,
                )
                os.fchmod(child, 0o700)
            path_identity = _stat_at(descriptor, component)
            opened_identity = _identity_from_stat(os.fstat(child))
            _validate_opened_identity(path_identity, opened_identity, kind="directory")
            os.close(descriptor)
            descriptor = child
        root_identity = _identity_from_stat(os.fstat(descriptor))
        _validate_directory_identity(root_identity, root_identity)
        return absolute, descriptor
    except Exception:
        os.close(descriptor)
        raise


def _create_candidate_directory(
    output_descriptor: int,
    *,
    manifest_id: str,
) -> tuple[str, int]:
    for _ in range(128):
        name = f".{manifest_id}.{os.urandom(12).hex()}.tmp"
        try:
            os.mkdir(name, 0o700, dir_fd=output_descriptor)
        except FileExistsError:
            continue
        os.fsync(output_descriptor)
        descriptor = os.open(
            name,
            _no_follow_flags(directory=True),
            dir_fd=output_descriptor,
        )
        os.fchmod(descriptor, 0o700)
        path_identity = _stat_at(output_descriptor, name)
        opened_identity = _identity_from_stat(os.fstat(descriptor))
        _validate_opened_identity(path_identity, opened_identity, kind="directory")
        _validate_directory_identity(opened_identity, opened_identity)
        return name, descriptor
    raise BundleWriteError("exclusive bundle candidate directory is unavailable")


def _write_resource_at(candidate_descriptor: int, resource: BundleResource) -> None:
    relative = validate_member_path(resource.path)
    descriptors = [os.dup(candidate_descriptor)]
    try:
        for component in relative.parts[:-1]:
            descriptors.append(
                _open_or_create_private_directory_at(descriptors[-1], component)
            )
        _write_file_at(descriptors[-1], relative.parts[-1], resource.data)
        for descriptor in reversed(descriptors):
            os.fsync(descriptor)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _rename_noreplace_at(
    directory_descriptor: int,
    source_name: str,
    target_name: str,
) -> None:
    """Atomically publish one directory without ever replacing a target."""

    library = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    target = os.fsencode(target_name)
    if sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        flags = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flags = 0x00000004  # RENAME_EXCL
    else:
        function = None
        flags = 0
    if function is None:
        raise BundleWriteError("atomic no-replace publication is unavailable")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(directory_descriptor, source, directory_descriptor, target, flags) != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise BundleAlreadyExistsError(f"bundle {target_name} already exists")
        raise OSError(error_number, os.strerror(error_number))


def _remove_candidate_if_unchanged(
    output_descriptor: int,
    candidate_name: str,
    expected: BundleFileIdentity,
) -> None:
    try:
        observed = _identity_from_stat(
            os.stat(
                candidate_name,
                dir_fd=output_descriptor,
                follow_symlinks=False,
            )
        )
    except FileNotFoundError:
        return
    if (
        observed.device != expected.device
        or observed.inode != expected.inode
        or not stat.S_ISDIR(observed.mode)
    ):
        return
    shutil.rmtree(candidate_name, dir_fd=output_descriptor)
    os.fsync(output_descriptor)


def write_bundle(
    output_root: Path,
    *,
    manifest: Mapping[str, Any],
    resources: Iterable[BundleResource],
    verification_policy: BundleVerificationPolicy,
) -> Path:
    """Scan, write, exact-verify, then atomically publish without replacement."""

    if not isinstance(verification_policy, BundleVerificationPolicy):
        raise BundleWriteError("trusted bundle verification policy is required")
    _preflight_manifest_limits(manifest, verification_policy)
    normalized_manifest = _normalize_manifest(manifest)
    manifest_id = normalized_manifest["manifestId"]
    manifest_bytes = canonical_json_bytes(normalized_manifest)
    if len(manifest_bytes) > verification_policy.max_manifest_bytes:
        raise BundleVerificationError("bundle manifest exceeds its trusted byte limit")
    _validate_policy(normalized_manifest, verification_policy)
    try:
        scanned_resources = _scan_and_validate_resources(
            resources,
            manifest=normalized_manifest,
            policy=verification_policy,
        )
    except (BundleManifestError, BundleVerificationError, BundleWriteError):
        raise
    except Exception as error:
        raise BundleWriteError("bundle resource scan did not complete") from error
    try:
        output_root, output_descriptor = _open_output_root(Path(output_root))
    except BundleWriteError:
        raise
    except Exception as error:
        raise BundleWriteError("quarantine output root is unsafe") from error
    target = output_root / manifest_id
    candidate_name = ""
    candidate_descriptor = -1
    candidate_identity: BundleFileIdentity | None = None
    try:
        candidate_name, candidate_descriptor = _create_candidate_directory(
            output_descriptor,
            manifest_id=manifest_id,
        )
        candidate = output_root / candidate_name
        candidate_identity = _identity_from_stat(os.fstat(candidate_descriptor))
        for scanned in scanned_resources:
            _write_resource_at(candidate_descriptor, scanned.resource)
        _write_file_at(candidate_descriptor, MANIFEST_NAME, manifest_bytes)
        os.fsync(candidate_descriptor)
        candidate_identity = _identity_from_stat(os.fstat(candidate_descriptor))
        verify_bundle(
            candidate,
            policy=verification_policy,
        )
        path_identity = _stat_at(output_descriptor, candidate_name)
        opened_identity = _identity_from_stat(os.fstat(candidate_descriptor))
        _validate_opened_identity(path_identity, opened_identity, kind="candidate")
        _rename_noreplace_at(output_descriptor, candidate_name, manifest_id)
        published_identity = _stat_at(output_descriptor, manifest_id)
        _validate_opened_identity(
            published_identity,
            _identity_from_stat(os.fstat(candidate_descriptor)),
            kind="published bundle",
        )
        os.fsync(output_descriptor)
        return target
    except BundleAlreadyExistsError:
        raise
    except Exception as error:
        raise BundleWriteError("bundle publication did not complete") from error
    finally:
        if candidate_descriptor >= 0:
            os.close(candidate_descriptor)
        if candidate_name and candidate_identity is not None:
            _remove_candidate_if_unchanged(
                output_descriptor,
                candidate_name,
                candidate_identity,
            )
        os.close(output_descriptor)
