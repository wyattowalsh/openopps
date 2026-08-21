from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import stat
from typing import Any
import unicodedata

import pytest

from openopps.discovery.bundle import (
    BundleAlreadyExistsError,
    BundleFileIdentity,
    BundleManifestError,
    BundleResource,
    BundleVerificationError,
    BundleVerificationPolicy,
    BundleWriteError,
    canonical_manifest_bytes,
    compute_manifest_id,
    compute_member_set_sha256,
    parse_manifest_bytes,
    validate_file_identity,
    validate_member_path,
    validate_member_paths,
    verify_bundle,
    write_bundle,
)
from openopps.discovery.canonical import (
    CanonicalJSONError,
    MAX_CANONICAL_JSON_DEPTH,
    canonical_json_bytes,
    decode_canonical_json,
)


JsonObject = dict[str, Any]

BUNDLE_SCHEMA_VERSION = "openopps.discovery.bundle.v1"
PROFILE_ID = "unit-fixture"
PROFILE_VERSION = "1"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
MAX_EVIDENCE_AGE = timedelta(hours=48)
SHA256_ZERO = "0" * 64


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _member(path: str, data: bytes) -> JsonObject:
    digest = _sha256(data)
    return {
        "mediaType": "application/json",
        "path": path,
        "provenanceId": f"sha256:{digest}",
        "role": "evidence",
        "sha256": digest,
        "sizeBytes": len(data),
    }


def _manifest(
    resources: Mapping[str, bytes],
    *,
    execution_id: str = "execution-a",
    observed_at: datetime = NOW,
    profile_id: str = PROFILE_ID,
    profile_version: str = PROFILE_VERSION,
) -> JsonObject:
    members = [_member(path, data) for path, data in resources.items()]
    manifest: JsonObject = {
        "configurationSha256": "c" * 64,
        "executionId": execution_id,
        "manifestId": "",
        "memberCount": len(members),
        "members": members,
        "memberSetSha256": compute_member_set_sha256(members),
        "observedAt": _utc_text(observed_at),
        "profileId": profile_id,
        "profileVersion": profile_version,
        "runState": "complete",
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "toolVersion": "0.1.0",
    }
    manifest["manifestId"] = compute_manifest_id(manifest)
    return manifest


def _set_manifest_id(manifest: JsonObject) -> None:
    manifest["manifestId"] = compute_manifest_id(manifest)


def _set_member_set_digest(manifest: JsonObject) -> None:
    manifest["memberSetSha256"] = compute_member_set_sha256(manifest["members"])


def _materialize_bundle(
    root: Path,
    resources: Mapping[str, bytes],
    *,
    manifest: JsonObject | None = None,
) -> JsonObject:
    resolved_manifest = manifest or _manifest(resources)
    root.mkdir(parents=True)
    root.chmod(0o700)
    for relative_path, data in resources.items():
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.chmod(0o700)
        destination.write_bytes(data)
        destination.chmod(0o600)
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(canonical_manifest_bytes(resolved_manifest))
    manifest_path.chmod(0o600)
    return resolved_manifest


def _rewrite_manifest_without_prevalidation(root: Path, manifest: JsonObject) -> None:
    (root / "manifest.json").write_bytes(canonical_json_bytes(manifest))


def _policy(**overrides: object) -> BundleVerificationPolicy:
    values: dict[str, object] = {
        "max_evidence_age": MAX_EVIDENCE_AGE,
        "now": NOW,
        "replayed_manifest_ids": frozenset(),
        "revoked_manifest_ids": frozenset(),
        "supported_profiles": frozenset({(PROFILE_ID, PROFILE_VERSION)}),
        "supported_schema_versions": frozenset({BUNDLE_SCHEMA_VERSION}),
        "required_member_roles": frozenset(),
        "supported_member_roles": frozenset({"evidence"}),
        "canonical_json_roles": frozenset(),
    }
    values.update(overrides)
    return BundleVerificationPolicy(**values)


def _bundle_resources(resources: Mapping[str, bytes]) -> list[BundleResource]:
    return [
        BundleResource(
            data=data,
            media_type="application/json",
            path=path,
            provenance_id=f"sha256:{_sha256(data)}",
            role="evidence",
        )
        for path, data in resources.items()
    ]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# T101: canonical bytes are exact, compact UTF-8 with one trailing LF.
def test_canonical_json_bytes_are_sorted_compact_utf8_and_lf_terminated() -> None:
    value = {"z": True, "a": "café", "nested": {"z": 2, "a": 1}}

    encoded = canonical_json_bytes(value)

    assert encoded == b'{"a":"caf\xc3\xa9","nested":{"a":1,"z":2},"z":true}\n'
    assert not encoded.startswith(b"\xef\xbb\xbf")
    assert decode_canonical_json(encoded) == value


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'\xef\xbb\xbf{"a":1}\n', id="utf8-bom"),
        pytest.param(b'{"z":1,"a":2}\n', id="unsorted-keys"),
        pytest.param(b'{"a": 1}\n', id="noncompact-separator"),
        pytest.param(b'{"a":1}', id="missing-trailing-lf"),
        pytest.param(b'{"a":1}\n\n', id="multiple-trailing-lfs"),
        pytest.param(b'{"a":"\xff"}\n', id="invalid-utf8"),
    ],
)
def test_canonical_decoder_rejects_noncanonical_wire_bytes(payload: bytes) -> None:
    with pytest.raises(CanonicalJSONError):
        decode_canonical_json(payload)


# T102: lexical number constraints and strict manifest schemas fail closed.
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'{"a":1,"a":2}\n', id="duplicate-key"),
        pytest.param(b'{"value":1.25}\n', id="float"),
        pytest.param(b'{"value":1.0}\n', id="fractional-integer-spelling"),
        pytest.param(b'{"value":-0}\n', id="negative-zero"),
        pytest.param(b'{"value":NaN}\n', id="nan"),
        pytest.param(b'{"value":Infinity}\n', id="infinity"),
        pytest.param(b'{"value":-Infinity}\n', id="negative-infinity"),
    ],
)
def test_canonical_decoder_rejects_ambiguous_or_nonfinite_numbers(
    payload: bytes,
) -> None:
    with pytest.raises(CanonicalJSONError):
        decode_canonical_json(payload)


def test_canonical_duplicate_key_diagnostic_does_not_echo_untrusted_key() -> None:
    marker = "synthetic-secret-field"
    payload = f'{{"{marker}":1,"{marker}":2}}\n'.encode()

    with pytest.raises(CanonicalJSONError) as exc_info:
        decode_canonical_json(payload)

    assert marker not in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(0.0, id="zero-float"),
        pytest.param(-0.0, id="negative-zero-float"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_canonical_encoder_rejects_all_float_values(value: float) -> None:
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes({"value": value})


def test_canonical_encoder_rejects_unpaired_unicode_surrogates() -> None:
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes({"value": "\ud800"})


def test_canonical_encoder_rejects_hostile_nesting_with_a_bounded_error() -> None:
    value: object = None
    for _ in range(MAX_CANONICAL_JSON_DEPTH + 2):
        value = [value]

    with pytest.raises(CanonicalJSONError, match="nesting limit"):
        canonical_json_bytes(value)


def test_canonical_decoder_rejects_hostile_nesting_with_a_bounded_error() -> None:
    depth = MAX_CANONICAL_JSON_DEPTH + 2
    payload = b"[" * depth + b"null" + b"]" * depth + b"\n"

    with pytest.raises(CanonicalJSONError, match="nesting limit"):
        decode_canonical_json(payload)


@pytest.mark.parametrize(
    "mutation",
    ["unknown-field", "unknown-schema", "numeric-coercion"],
)
def test_manifest_parser_rejects_unknown_contracts_and_numeric_coercion(
    mutation: str,
) -> None:
    resources = {f"resources/{_sha256(b'{}')}.json": b"{}"}
    manifest = _manifest(resources)
    if mutation == "unknown-field":
        manifest["unexpected"] = True
    elif mutation == "unknown-schema":
        manifest["schemaVersion"] = "openopps.discovery.bundle.v999"
    else:
        manifest["memberCount"] = "1"
    _set_manifest_id(manifest)

    with pytest.raises(BundleManifestError):
        parse_manifest_bytes(canonical_json_bytes(manifest))


# T103: semantic identity excludes self-reference and execution identity only.
def test_manifest_id_excludes_manifest_and_execution_ids() -> None:
    resources = {f"resources/{_sha256(b'{}')}.json": b"{}"}
    first = _manifest(resources, execution_id="execution-a")
    second = _manifest(resources, execution_id="execution-b")
    semantic = deepcopy(first)
    semantic.pop("manifestId")
    semantic.pop("executionId")

    expected = _sha256(canonical_json_bytes(semantic))

    assert compute_manifest_id(first) == expected
    assert compute_manifest_id(second) == expected
    assert first["manifestId"] == second["manifestId"] == expected
    assert canonical_manifest_bytes(first) != canonical_manifest_bytes(second)


def test_manifest_id_changes_when_semantic_content_changes() -> None:
    resources = {f"resources/{_sha256(b'{}')}.json": b"{}"}
    first = _manifest(resources)
    second = deepcopy(first)
    second["profileId"] = "different-profile"

    assert compute_manifest_id(first) != compute_manifest_id(second)


def test_manifest_parser_rejects_a_mismatched_manifest_id() -> None:
    resources = {f"resources/{_sha256(b'{}')}.json": b"{}"}
    manifest = _manifest(resources)
    manifest["manifestId"] = SHA256_ZERO

    with pytest.raises(BundleManifestError):
        parse_manifest_bytes(canonical_json_bytes(manifest))


# T104: semantic arrays have deterministic ordering and unique identities.
def test_manifest_member_order_does_not_change_semantic_bytes() -> None:
    first_data = b'{"first":1}'
    second_data = b'{"second":2}'
    resources = {
        f"resources/{_sha256(first_data)}.json": first_data,
        f"resources/{_sha256(second_data)}.json": second_data,
    }
    first = _manifest(resources)
    second = deepcopy(first)
    second["members"] = list(reversed(second["members"]))
    second["memberSetSha256"] = compute_member_set_sha256(second["members"])
    _set_manifest_id(second)

    assert first["manifestId"] == second["manifestId"]
    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)


def test_manifest_rejects_duplicate_member_identities() -> None:
    data = b"{}"
    resources = {f"resources/{_sha256(data)}.json": data}
    manifest = _manifest(resources)
    manifest["members"].append(deepcopy(manifest["members"][0]))
    manifest["memberCount"] = 2

    with pytest.raises(BundleManifestError):
        _set_member_set_digest(manifest)
        _set_manifest_id(manifest)
        canonical_manifest_bytes(manifest)


# T105: member set, sizes, counts, and aggregate digest close exactly.
def test_member_set_digest_is_canonical_and_order_independent() -> None:
    first = _member("resources/b.json", b"b")
    second = _member("resources/a.json", b"a")
    expected = _sha256(canonical_json_bytes([second, first]))

    assert compute_member_set_sha256([first, second]) == expected
    assert compute_member_set_sha256([second, first]) == expected


def test_verify_bundle_accepts_one_exact_canonical_member_set(tmp_path: Path) -> None:
    first_data = b'{"first":1}'
    second_data = b'{"second":2}'
    resources = {
        f"resources/{_sha256(first_data)}.json": first_data,
        f"resources/{_sha256(second_data)}.json": second_data,
    }
    root = tmp_path / "bundle"
    manifest = _materialize_bundle(root, resources)

    verified = verify_bundle(root, policy=_policy())

    assert verified.manifest_id == manifest["manifestId"]
    assert tuple(verified.member_paths) == tuple(sorted(resources))


@pytest.mark.parametrize(
    "corruption",
    ["missing", "extra", "size", "sha256", "count", "aggregate"],
)
def test_verify_bundle_rejects_any_member_set_or_digest_mismatch(
    tmp_path: Path,
    corruption: str,
) -> None:
    data = b'{"candidate":1}'
    member_path = f"resources/{_sha256(data)}.json"
    resources = {member_path: data}
    root = tmp_path / "bundle"
    manifest = _materialize_bundle(root, resources)

    if corruption == "missing":
        (root / member_path).unlink()
    elif corruption == "extra":
        (root / "extra.json").write_bytes(b"{}")
    elif corruption == "size":
        manifest["members"][0]["sizeBytes"] += 1
        _set_member_set_digest(manifest)
        _set_manifest_id(manifest)
        _rewrite_manifest_without_prevalidation(root, manifest)
    elif corruption == "sha256":
        manifest["members"][0]["sha256"] = SHA256_ZERO
        _set_member_set_digest(manifest)
        _set_manifest_id(manifest)
        _rewrite_manifest_without_prevalidation(root, manifest)
    elif corruption == "count":
        manifest["memberCount"] += 1
        _set_manifest_id(manifest)
        _rewrite_manifest_without_prevalidation(root, manifest)
    else:
        manifest["memberSetSha256"] = SHA256_ZERO
        _set_manifest_id(manifest)
        _rewrite_manifest_without_prevalidation(root, manifest)

    with pytest.raises(BundleVerificationError):
        verify_bundle(root, policy=_policy())


# T106: only unambiguous relative POSIX paths are legal manifest members.
@pytest.mark.parametrize(
    "member_path",
    [
        pytest.param("/absolute.json", id="absolute"),
        pytest.param("../escape.json", id="leading-traversal"),
        pytest.param("resources/../escape.json", id="nested-traversal"),
        pytest.param(r"resources\escape.json", id="backslash"),
        pytest.param("resources/%2fescape.json", id="encoded-forward-slash"),
        pytest.param("resources/%5Cescape.json", id="encoded-backslash"),
        pytest.param("resources//empty.json", id="empty-component"),
        pytest.param("resources/", id="trailing-empty-component"),
        pytest.param("resources/./member.json", id="dot-component"),
    ],
)
def test_validate_member_path_rejects_unsafe_or_ambiguous_paths(
    member_path: str,
) -> None:
    with pytest.raises(BundleManifestError):
        validate_member_path(member_path)


def test_validate_member_path_accepts_a_safe_relative_posix_path() -> None:
    member_path = f"resources/{'a' * 64}.json"

    assert validate_member_path(member_path).as_posix() == member_path


# T107: exact paths must also be unique after NFC normalization and case folding.
@pytest.mark.parametrize("collision", ["unicode-normalization", "case-fold"])
def test_validate_member_paths_rejects_portable_name_collisions(
    collision: str,
) -> None:
    if collision == "unicode-normalization":
        first = "resources/café.json"
        second = f"resources/{unicodedata.normalize('NFD', 'café')}.json"
    else:
        first = "resources/Candidate.json"
        second = "resources/candidate.json"

    with pytest.raises(BundleManifestError):
        validate_member_paths([first, second])


# T108: file kind, hard-link count, and before/after identity are deterministic.
def _file_identity(
    mode: int,
    *,
    device: int = 7,
    inode: int = 11,
    link_count: int = 1,
    size_bytes: int = 2,
    owner_uid: int | None = None,
) -> BundleFileIdentity:
    return BundleFileIdentity(
        device=device,
        inode=inode,
        link_count=link_count,
        mode=mode,
        size_bytes=size_bytes,
        owner_uid=os.geteuid() if owner_uid is None else owner_uid,
    )


@pytest.mark.parametrize(
    "special_type",
    [
        pytest.param(stat.S_IFLNK, id="symlink"),
        pytest.param(stat.S_IFIFO, id="fifo"),
        pytest.param(stat.S_IFCHR, id="character-device"),
        pytest.param(stat.S_IFBLK, id="block-device"),
        pytest.param(stat.S_IFSOCK, id="socket"),
    ],
)
def test_validate_file_identity_rejects_non_regular_files(special_type: int) -> None:
    identity = _file_identity(special_type | 0o600)

    with pytest.raises(BundleVerificationError):
        validate_file_identity(identity, identity)


def test_validate_file_identity_rejects_hard_links() -> None:
    identity = _file_identity(stat.S_IFREG | 0o600, link_count=2)

    with pytest.raises(BundleVerificationError):
        validate_file_identity(identity, identity)


def test_validate_file_identity_rejects_a_foreign_owner() -> None:
    identity = _file_identity(stat.S_IFREG | 0o600, owner_uid=os.geteuid() + 1)

    with pytest.raises(BundleVerificationError, match="owned by this process"):
        validate_file_identity(identity, identity)


@pytest.mark.parametrize("permissions", [0o620, 0o602, 0o666])
def test_validate_file_identity_rejects_group_or_world_writable_files(
    permissions: int,
) -> None:
    identity = _file_identity(stat.S_IFREG | permissions)

    with pytest.raises(BundleVerificationError):
        validate_file_identity(identity, identity)


def test_validate_file_identity_accepts_one_stable_restrictive_regular_file() -> None:
    identity = _file_identity(stat.S_IFREG | 0o600)

    validate_file_identity(identity, identity)


@pytest.mark.parametrize("changed_field", ["device", "inode", "mode", "size"])
def test_validate_file_identity_rejects_before_after_changes(
    changed_field: str,
) -> None:
    before = _file_identity(stat.S_IFREG | 0o600)
    after = {
        "device": _file_identity(stat.S_IFREG | 0o600, device=before.device + 1),
        "inode": _file_identity(stat.S_IFREG | 0o600, inode=before.inode + 1),
        "mode": _file_identity(stat.S_IFREG | 0o400),
        "size": _file_identity(stat.S_IFREG | 0o600, size_bytes=before.size_bytes + 1),
    }[changed_field]

    with pytest.raises(BundleVerificationError):
        validate_file_identity(before, after)


def test_verify_bundle_rejects_a_symlinked_member(tmp_path: Path) -> None:
    data = b"{}"
    member_path = f"resources/{_sha256(data)}.json"
    root = tmp_path / "bundle"
    _materialize_bundle(root, {member_path: data})
    target = tmp_path / "outside.json"
    target.write_bytes(data)
    (root / member_path).unlink()
    (root / member_path).symlink_to(target)

    with pytest.raises(BundleVerificationError):
        verify_bundle(root, policy=_policy())


def test_verify_bundle_rejects_a_hard_linked_member(tmp_path: Path) -> None:
    data = b"{}"
    member_path = f"resources/{_sha256(data)}.json"
    root = tmp_path / "bundle"
    _materialize_bundle(root, {member_path: data})
    target = tmp_path / "outside.json"
    target.write_bytes(data)
    (root / member_path).unlink()
    os.link(target, root / member_path)

    with pytest.raises(BundleVerificationError):
        verify_bundle(root, policy=_policy())


# T109: time and trusted profile policy are explicit and injectable.
@pytest.mark.parametrize(
    "rejection",
    ["future", "stale", "unsupported-profile"],
)
def test_verify_bundle_rejects_future_stale_or_unsupported(
    tmp_path: Path,
    rejection: str,
) -> None:
    data = b"{}"
    resources = {f"resources/{_sha256(data)}.json": data}
    observed_at = NOW
    profile_id = PROFILE_ID
    if rejection == "future":
        observed_at = NOW + timedelta(seconds=1)
    elif rejection == "stale":
        observed_at = NOW - MAX_EVIDENCE_AGE - timedelta(seconds=1)
    elif rejection == "unsupported-profile":
        profile_id = "unsupported-profile"
    manifest = _manifest(resources, observed_at=observed_at, profile_id=profile_id)
    root = tmp_path / "bundle"
    _materialize_bundle(root, resources, manifest=manifest)
    with pytest.raises(BundleVerificationError):
        verify_bundle(root, policy=_policy())


@pytest.mark.parametrize(
    "policy_overrides",
    [
        pytest.param({"max_manifest_bytes": 10}, id="manifest-bytes"),
        pytest.param({"max_member_count": 1}, id="member-count"),
        pytest.param({"max_member_bytes": 3}, id="member-bytes"),
        pytest.param({"max_total_member_bytes": 7}, id="aggregate-bytes"),
    ],
)
def test_verify_bundle_enforces_trusted_structural_and_byte_limits(
    tmp_path: Path,
    policy_overrides: Mapping[str, object],
) -> None:
    resources = {
        f"resources/{_sha256(b'aaaa')}.json": b"aaaa",
        f"resources/{_sha256(b'bbbb')}.json": b"bbbb",
    }
    root = tmp_path / "bundle"
    _materialize_bundle(root, resources)

    with pytest.raises(BundleVerificationError):
        verify_bundle(root, policy=_policy(**policy_overrides))


# T110: interrupted candidates never publish, and completed bundles are immutable.
def test_interrupted_bundle_write_never_exposes_a_completed_bundle(
    tmp_path: Path,
) -> None:
    first_data = b'{"first":1}'
    second_data = b'{"second":2}'
    resources = {
        f"resources/{_sha256(first_data)}.json": first_data,
        f"resources/{_sha256(second_data)}.json": second_data,
    }
    manifest = _manifest(resources)
    inputs = _bundle_resources(resources)
    output_root = tmp_path / "quarantine"

    def interrupted_resources() -> Iterable[BundleResource]:
        yield inputs[0]
        raise OSError("simulated resource-stream interruption")

    with pytest.raises(BundleWriteError):
        write_bundle(
            output_root,
            manifest=manifest,
            resources=interrupted_resources(),
            verification_policy=_policy(),
        )

    assert not (output_root / manifest["manifestId"]).exists()
    if output_root.exists():
        assert all(
            not (candidate / "manifest.json").exists()
            for candidate in output_root.iterdir()
            if candidate.is_dir()
        )


def test_bundle_write_never_overwrites_an_existing_completed_bundle(
    tmp_path: Path,
) -> None:
    data = b"{}"
    resources = {f"resources/{_sha256(data)}.json": data}
    manifest = _manifest(resources)
    output_root = tmp_path / "quarantine"
    completed = output_root / manifest["manifestId"]
    _materialize_bundle(completed, resources, manifest=manifest)
    output_root.chmod(0o700)
    before = _tree_bytes(completed)

    with pytest.raises(BundleAlreadyExistsError):
        write_bundle(
            output_root,
            manifest=manifest,
            resources=_bundle_resources(resources),
            verification_policy=_policy(),
        )

    assert _tree_bytes(completed) == before
