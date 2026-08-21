"""Read-only approved-catalog inventory and repository identity projection.

This module intentionally accepts runtime records and adapter identities from a
caller.  It never imports the operational provider registry, plugin loader,
storage, cache, or CLI.  Repository and wheel helpers perform bounded in-memory
reads for hashing and never extract archives or write to the inspected surfaces;
the resulting projections expose only counts and digests.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Any, Final, NoReturn
from zipfile import BadZipFile, ZipFile

from openopps.discovery.canonical import canonical_json_bytes


MAX_IDENTITY_RESOURCE_BYTES: Final = 64 * 1024 * 1024
MAX_IDENTITY_TOTAL_BYTES: Final = 256 * 1024 * 1024
MAX_IDENTITY_RESOURCE_COUNT: Final = 1_024
MAX_WHEEL_MEMBER_COUNT: Final = 10_000
MAX_PACKAGED_CATALOG_BYTES: Final = 16 * 1024 * 1024
MAX_RUNTIME_SOURCE_COUNT: Final = 100_000
MAX_RUNTIME_ADAPTER_COUNT: Final = 1_024

V7_POLICY_INPUT_NAMES: Final = (
    "policy_code",
    "policy_corpus",
    "policy_evidence",
    "policy_schema",
)
DISCOVERY_OWNED_IDENTITY_NAMES: Final = ("decision", "envelope", "ledger")

DEFAULT_V7_POLICY_PATHS: Mapping[str, str] = MappingProxyType(
    {
        "policy_code": "src/openopps/source_policy.py",
        "policy_corpus": "deployment/openopps-data/source-corpus-v6.json",
        "policy_evidence": (
            "src/openopps/providers/sources/data/source_policy_evidence.json"
        ),
        "policy_schema": (
            "src/openopps/providers/sources/data/source_policy_evidence.schema.json"
        ),
    }
)
DEFAULT_SHARED_GENERATED_PATHS: Mapping[str, str] = MappingProxyType(
    {"web_openopps_data": "web/lib/generated/openopps-data.json"}
)
DEFAULT_PACKAGED_CATALOG_PATH: Final = (
    "src/openopps/providers/sources/data/portfolio_source_catalog.json"
)

_LOGICAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class InventoryError(ValueError):
    """Raised when an approved inventory or identity projection is ambiguous."""


@dataclass(frozen=True, slots=True)
class PackagedCatalogReadback:
    """Verified identity of the packaged portfolio catalog."""

    version: int
    count: int
    fingerprint: str
    file_sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "count": self.count,
            "fileSha256": self.file_sha256,
            "fingerprint": self.fingerprint,
            "sizeBytes": self.size_bytes,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class ApprovedRuntimeCatalogInventory:
    """Digest-only readback of one collision-free approved runtime catalog."""

    schema_version: str
    source_count: int
    unique_source_count: int
    source_keys_sha256: str
    runtime_semantic_sha256: str
    owner_map_sha256: str
    adapter_count: int
    adapter_identity_map_sha256: str
    adapter_provider_ids: tuple[str, ...]
    packaged_catalog: PackagedCatalogReadback

    def as_dict(self) -> dict[str, object]:
        return {
            "adapterCount": self.adapter_count,
            "adapterIdentityMapSha256": self.adapter_identity_map_sha256,
            "adapterProviderIds": list(self.adapter_provider_ids),
            "ownerMapSha256": self.owner_map_sha256,
            "packagedCatalog": self.packaged_catalog.as_dict(),
            "runtimeSemanticSha256": self.runtime_semantic_sha256,
            "schemaVersion": self.schema_version,
            "sourceCount": self.source_count,
            "sourceKeysSha256": self.source_keys_sha256,
            "uniqueSourceCount": self.unique_source_count,
        }


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    """Bounded identity for one present or deliberately absent resource."""

    name: str
    present: bool
    sha256: str | None
    size_bytes: int

    def as_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "name": self.name,
            "present": self.present,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class RepositoryIdentityProjection:
    """Digest-only projection over frozen v7 and discovery-owned surfaces."""

    schema_version: str
    v7_policy_inputs: tuple[ResourceIdentity, ...]
    public_selector: ResourceIdentity
    shared_generated_data: tuple[ResourceIdentity, ...]
    embedded_wheel_resources: tuple[ResourceIdentity, ...]
    discovery_owned: tuple[ResourceIdentity, ...]
    projection_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            **_projection_body(
                v7_policy_inputs=self.v7_policy_inputs,
                public_selector=self.public_selector,
                shared_generated_data=self.shared_generated_data,
                embedded_wheel_resources=self.embedded_wheel_resources,
                discovery_owned=self.discovery_owned,
            ),
            "projectionSha256": self.projection_sha256,
        }


def _reject_constant(value: str) -> NoReturn:
    del value
    raise InventoryError("non-finite catalog numbers are forbidden")


def _reject_float(value: str) -> NoReturn:
    del value
    raise InventoryError("floating-point catalog numbers are forbidden")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError("duplicate catalog object keys are forbidden")
        result[key] = value
    return result


def _existing_json_hash(value: object) -> str:
    """Reproduce the existing runtime/catalog semantic fingerprint contract."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _read_record_field(record: object, field: str) -> object:
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None)


def _runtime_entry(record: object) -> dict[str, object]:
    key = _read_record_field(record, "key")
    url = _read_record_field(record, "url")
    provider_id = _read_record_field(record, "provider_id")
    version = _read_record_field(record, "version")
    raw_metadata = _read_record_field(record, "raw_metadata")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (key, url, provider_id)
    ):
        raise InventoryError("runtime source identity fields must be non-empty strings")
    if not isinstance(version, Mapping) or not isinstance(raw_metadata, Mapping):
        raise InventoryError("runtime source version and metadata must be mappings")
    return {
        "key": key,
        "provider_id": provider_id,
        "raw_metadata": dict(raw_metadata),
        "url": url,
        "version": dict(version),
    }


def read_packaged_catalog_bytes(raw: bytes) -> PackagedCatalogReadback:
    """Validate packaged catalog bytes and return identities without retaining rows."""

    if not isinstance(raw, bytes):
        raise InventoryError("packaged catalog input must be bytes")
    if len(raw) > MAX_PACKAGED_CATALOG_BYTES:
        raise InventoryError("packaged catalog exceeds the readback byte limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise InventoryError("packaged catalog must not contain a UTF-8 BOM")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except InventoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise InventoryError("packaged catalog is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "count",
        "entries",
        "fingerprint",
        "version",
    }:
        raise InventoryError("packaged catalog fields do not match the approved format")
    version = payload["version"]
    count = payload["count"]
    entries = payload["entries"]
    fingerprint = payload["fingerprint"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 2:
        raise InventoryError("packaged catalog version is unsupported")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise InventoryError("packaged catalog count is invalid")
    if count > MAX_RUNTIME_SOURCE_COUNT:
        raise InventoryError("packaged catalog exceeds its source count limit")
    if not isinstance(entries, list) or count != len(entries):
        raise InventoryError("packaged catalog count does not close over entries")
    if any(
        not isinstance(entry, dict)
        or set(entry) != {"key", "provider_id", "raw_metadata", "url", "version"}
        for entry in entries
    ):
        raise InventoryError(
            "packaged catalog entries do not match the approved format"
        )
    normalized = [_runtime_entry(entry) for entry in entries]
    keys = [str(entry["key"]) for entry in normalized]
    if len(set(keys)) != len(keys):
        raise InventoryError("packaged catalog keys are not unique")
    if keys != sorted(keys):
        raise InventoryError("packaged catalog entries must be key-sorted")
    computed = _existing_json_hash(normalized)
    if not isinstance(fingerprint, str) or fingerprint != computed:
        raise InventoryError("packaged catalog fingerprint does not match entries")
    return PackagedCatalogReadback(
        version=version,
        count=count,
        fingerprint=fingerprint,
        file_sha256=sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def build_approved_runtime_catalog_inventory(
    *,
    source_records: Iterable[object],
    source_owner_rows: Iterable[Sequence[str]],
    adapter_identity_rows: Iterable[Sequence[str]],
    packaged_catalog: PackagedCatalogReadback,
) -> ApprovedRuntimeCatalogInventory:
    """Compute the frozen runtime inventory without importing operational modules."""

    if not isinstance(packaged_catalog, PackagedCatalogReadback):
        raise InventoryError("packaged catalog readback is required")
    entries: list[dict[str, object]] = []
    for record in source_records:
        if len(entries) >= MAX_RUNTIME_SOURCE_COUNT:
            raise InventoryError("runtime source inventory exceeds its count limit")
        entries.append(_runtime_entry(record))
    entries.sort(key=lambda entry: str(entry["key"]))
    keys = [str(entry["key"]) for entry in entries]
    if not entries or len(set(keys)) != len(keys):
        raise InventoryError(
            "approved runtime source keys must be non-empty and unique"
        )

    owner_rows: list[list[str]] = []
    for row in source_owner_rows:
        if len(owner_rows) >= MAX_RUNTIME_SOURCE_COUNT:
            raise InventoryError("runtime source ownership exceeds its count limit")
        if len(row) != 2 or any(
            not isinstance(value, str) or not value for value in row
        ):
            raise InventoryError("source owner rows must contain key and module")
        owner_rows.append([row[0], row[1]])
    owner_rows.sort()
    owner_keys = [row[0] for row in owner_rows]
    if owner_keys != keys or len(set(owner_keys)) != len(owner_keys):
        raise InventoryError("runtime source ownership is incomplete or ambiguous")

    adapter_rows: list[list[str]] = []
    for row in adapter_identity_rows:
        if len(adapter_rows) >= MAX_RUNTIME_ADAPTER_COUNT:
            raise InventoryError("runtime adapter inventory exceeds its count limit")
        if len(row) != 3 or any(
            not isinstance(value, str) or not value for value in row
        ):
            raise InventoryError(
                "adapter identity rows must contain provider, module, and qualname"
            )
        adapter_rows.append([row[0], row[1], row[2]])
    adapter_rows.sort()
    provider_ids = tuple(row[0] for row in adapter_rows)
    if not adapter_rows or len(set(provider_ids)) != len(provider_ids):
        raise InventoryError(
            "approved adapter provider IDs must be non-empty and unique"
        )

    return ApprovedRuntimeCatalogInventory(
        schema_version="openopps.discovery.runtime-inventory.v1",
        source_count=len(entries),
        unique_source_count=len(keys),
        source_keys_sha256=_existing_json_hash(keys),
        runtime_semantic_sha256=_existing_json_hash(entries),
        owner_map_sha256=sha256(canonical_json_bytes(owner_rows)).hexdigest(),
        adapter_count=len(adapter_rows),
        adapter_identity_map_sha256=sha256(
            canonical_json_bytes(adapter_rows)
        ).hexdigest(),
        adapter_provider_ids=provider_ids,
        packaged_catalog=packaged_catalog,
    )


def _validate_logical_name(name: str) -> str:
    if not isinstance(name, str) or _LOGICAL_NAME_RE.fullmatch(name) is None:
        raise InventoryError("resource name must be a bounded logical identifier")
    return name


def _resource_identity(name: str, content: bytes | None) -> ResourceIdentity:
    normalized_name = _validate_logical_name(name)
    if content is None:
        return ResourceIdentity(
            name=normalized_name, present=False, sha256=None, size_bytes=0
        )
    if not isinstance(content, bytes):
        raise InventoryError("identity resources must be immutable bytes")
    if len(content) > MAX_IDENTITY_RESOURCE_BYTES:
        raise InventoryError("identity resource exceeds its byte limit")
    return ResourceIdentity(
        name=normalized_name,
        present=True,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def _resource_group(
    values: Mapping[str, bytes | None],
    *,
    exact_names: tuple[str, ...] | None = None,
) -> tuple[ResourceIdentity, ...]:
    if len(values) > MAX_IDENTITY_RESOURCE_COUNT:
        raise InventoryError("identity resource group exceeds its count limit")
    if exact_names is not None and set(values) != set(exact_names):
        raise InventoryError("identity resource group does not match its exact roles")
    resources = tuple(_resource_identity(name, values[name]) for name in sorted(values))
    if sum(resource.size_bytes for resource in resources) > MAX_IDENTITY_TOTAL_BYTES:
        raise InventoryError("identity resource group exceeds its aggregate byte limit")
    return resources


def _projection_body(
    *,
    v7_policy_inputs: tuple[ResourceIdentity, ...],
    public_selector: ResourceIdentity,
    shared_generated_data: tuple[ResourceIdentity, ...],
    embedded_wheel_resources: tuple[ResourceIdentity, ...],
    discovery_owned: tuple[ResourceIdentity, ...],
) -> dict[str, object]:
    return {
        "discoveryOwned": [item.as_dict() for item in discovery_owned],
        "embeddedWheelResources": [item.as_dict() for item in embedded_wheel_resources],
        "publicSelector": public_selector.as_dict(),
        "schemaVersion": "openopps.discovery.identity-projection.v1",
        "sharedGeneratedData": [item.as_dict() for item in shared_generated_data],
        "v7PolicyInputs": [item.as_dict() for item in v7_policy_inputs],
    }


def project_repository_identities(
    *,
    v7_policy_inputs: Mapping[str, bytes | None],
    public_selector: bytes | None,
    shared_generated_data: Mapping[str, bytes | None],
    embedded_wheel_resources: Mapping[str, bytes | None],
    discovery_owned: Mapping[str, bytes | None],
) -> RepositoryIdentityProjection:
    """Project exact resource identities without returning or mutating raw bytes."""

    if any(v7_policy_inputs.get(name) is None for name in V7_POLICY_INPUT_NAMES):
        raise InventoryError("every v7 policy input must be present")
    policy = _resource_group(v7_policy_inputs, exact_names=V7_POLICY_INPUT_NAMES)
    selector = _resource_identity("public_selector", public_selector)
    generated = _resource_group(shared_generated_data)
    wheel = _resource_group(embedded_wheel_resources)
    owned = _resource_group(discovery_owned, exact_names=DISCOVERY_OWNED_IDENTITY_NAMES)
    total_bytes = sum(
        item.size_bytes
        for group in (policy, (selector,), generated, wheel, owned)
        for item in group
    )
    if total_bytes > MAX_IDENTITY_TOTAL_BYTES:
        raise InventoryError("identity projection exceeds its aggregate byte limit")
    total_resources = sum(
        len(group) for group in (policy, (selector,), generated, wheel, owned)
    )
    if total_resources > MAX_IDENTITY_RESOURCE_COUNT:
        raise InventoryError("identity projection exceeds its resource count limit")
    body = _projection_body(
        v7_policy_inputs=policy,
        public_selector=selector,
        shared_generated_data=generated,
        embedded_wheel_resources=wheel,
        discovery_owned=owned,
    )
    return RepositoryIdentityProjection(
        schema_version="openopps.discovery.identity-projection.v1",
        v7_policy_inputs=policy,
        public_selector=selector,
        shared_generated_data=generated,
        embedded_wheel_resources=wheel,
        discovery_owned=owned,
        projection_sha256=sha256(canonical_json_bytes(body)).hexdigest(),
    )


def _validate_relative_path(value: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or "%" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise InventoryError("identity path must be an unambiguous relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise InventoryError("identity path must be repository-relative")
    return path


def _read_stable_file(path: Path, *, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise InventoryError("identity resource must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise InventoryError("identity resource cannot be opened safely") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InventoryError("identity resource must be a regular file")
        if before.st_size > max_bytes:
            raise InventoryError("identity resource exceeds its byte limit")
        chunks: list[bytes] = []
        admitted = 0
        while True:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - admitted))
            if not chunk:
                break
            admitted += len(chunk)
            if admitted > max_bytes:
                raise InventoryError("identity resource exceeds its byte limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or admitted != after.st_size:
            raise InventoryError("identity resource changed during readback")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_repository_resources(
    repository_root: Path,
    paths: Mapping[str, str],
) -> dict[str, bytes]:
    """Read an explicit repository resource set without following symlinks."""

    root = repository_root.resolve(strict=True)
    if not root.is_dir():
        raise InventoryError("repository root must be a directory")
    resources: dict[str, bytes] = {}
    if len(paths) > MAX_IDENTITY_RESOURCE_COUNT:
        raise InventoryError("repository identity set exceeds its count limit")
    for name, relative in sorted(paths.items()):
        _validate_logical_name(name)
        path = _validate_relative_path(relative)
        candidate = root.joinpath(*path.parts)
        resolved = candidate.resolve(strict=True)
        if resolved != root and root not in resolved.parents:
            raise InventoryError("identity resource escapes the repository root")
        current = root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise InventoryError("identity resource path contains a symlink")
        resources[name] = _read_stable_file(
            candidate, max_bytes=MAX_IDENTITY_RESOURCE_BYTES
        )
    if sum(len(content) for content in resources.values()) > MAX_IDENTITY_TOTAL_BYTES:
        raise InventoryError("repository identity resources exceed the aggregate limit")
    return resources


def read_wheel_resources(
    wheel_path: Path,
    members: Mapping[str, str],
) -> dict[str, bytes]:
    """Read exact embedded wheel members in memory without extracting files."""

    if wheel_path.is_symlink():
        raise InventoryError("wheel path must not be a symlink")
    try:
        wheel_bytes = _read_stable_file(wheel_path, max_bytes=MAX_IDENTITY_TOTAL_BYTES)
        with ZipFile(BytesIO(wheel_bytes), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_WHEEL_MEMBER_COUNT:
                raise InventoryError("wheel member inventory exceeds its count limit")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise InventoryError("wheel contains duplicate member names")
            by_name = {info.filename: info for info in infos}
            resources: dict[str, bytes] = {}
            if len(members) > MAX_IDENTITY_RESOURCE_COUNT:
                raise InventoryError(
                    "requested wheel resource set exceeds its count limit"
                )
            projected_bytes = 0
            for logical_name, member_name in sorted(members.items()):
                _validate_logical_name(logical_name)
                validated = _validate_relative_path(member_name).as_posix()
                info = by_name.get(validated)
                if info is None or info.is_dir():
                    raise InventoryError("required wheel resource is absent")
                member_mode = info.external_attr >> 16
                member_type = stat.S_IFMT(member_mode)
                if member_type not in {0, stat.S_IFREG}:
                    raise InventoryError("wheel resource must be a regular file")
                if info.file_size > MAX_IDENTITY_RESOURCE_BYTES:
                    raise InventoryError("wheel resource exceeds its byte limit")
                projected_bytes += info.file_size
                if projected_bytes > MAX_IDENTITY_TOTAL_BYTES:
                    raise InventoryError(
                        "wheel resources exceed the aggregate byte limit"
                    )
                content = archive.read(info)
                if len(content) != info.file_size:
                    raise InventoryError("wheel resource size does not match metadata")
                resources[logical_name] = content
    except InventoryError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as error:
        raise InventoryError("wheel resources cannot be read safely") from error
    if sum(len(content) for content in resources.values()) > MAX_IDENTITY_TOTAL_BYTES:
        raise InventoryError("wheel resources exceed the aggregate byte limit")
    return resources


def read_default_repository_projection(
    repository_root: Path,
    *,
    public_selector_path: str | None = None,
    embedded_wheel_resources: Mapping[str, bytes | None] | None = None,
    discovery_owned_paths: Mapping[str, str | None] | None = None,
) -> RepositoryIdentityProjection:
    """Read the current frozen repository surfaces and return their identities."""

    policy = read_repository_resources(repository_root, DEFAULT_V7_POLICY_PATHS)
    generated = read_repository_resources(
        repository_root, DEFAULT_SHARED_GENERATED_PATHS
    )
    selector: bytes | None = None
    if public_selector_path is not None:
        selector = read_repository_resources(
            repository_root, {"public_selector": public_selector_path}
        )["public_selector"]

    owned_paths = (
        {name: None for name in DISCOVERY_OWNED_IDENTITY_NAMES}
        if discovery_owned_paths is None
        else discovery_owned_paths
    )
    if set(owned_paths) != set(DISCOVERY_OWNED_IDENTITY_NAMES):
        raise InventoryError("discovery-owned path roles are incomplete")
    owned: dict[str, bytes | None] = {}
    for name in DISCOVERY_OWNED_IDENTITY_NAMES:
        relative = owned_paths[name]
        owned[name] = (
            None
            if relative is None
            else read_repository_resources(repository_root, {name: relative})[name]
        )
    return project_repository_identities(
        v7_policy_inputs=policy,
        public_selector=selector,
        shared_generated_data=generated,
        embedded_wheel_resources=embedded_wheel_resources or {},
        discovery_owned=owned,
    )
