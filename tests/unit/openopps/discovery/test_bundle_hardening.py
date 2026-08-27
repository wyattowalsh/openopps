from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import shutil
import stat
from typing import Any

import pytest

from openopps.discovery import bundle
from openopps.discovery.bundle import (
    BUNDLE_SCHEMA_VERSION,
    BundleManifestError,
    BundleMemberSemanticContract,
    BundleResource,
    BundleVerificationError,
    BundleVerificationPolicy,
    BundleWriteError,
    canonical_manifest_bytes,
    compute_manifest_id,
    compute_member_set_sha256,
    parse_manifest_bytes,
    verify_bundle,
    write_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes


JsonObject = dict[str, Any]
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
PROFILE = ("hardening-fixture", "1")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
) -> JsonObject:
    members = [_member(path, data) for path, data in resources.items()]
    manifest: JsonObject = {
        "configurationSha256": "c" * 64,
        "executionId": execution_id,
        "manifestId": "",
        "memberCount": len(members),
        "members": members,
        "memberSetSha256": compute_member_set_sha256(members),
        "observedAt": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "profileId": PROFILE[0],
        "profileVersion": PROFILE[1],
        "runState": "complete",
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "toolVersion": "0.1.0",
    }
    manifest["manifestId"] = compute_manifest_id(manifest)
    return manifest


def _policy(
    manifest_id: str | None = None,
    *,
    required_member_roles: frozenset[str] = frozenset({"evidence"}),
    supported_member_roles: frozenset[str] = frozenset({"evidence"}),
    canonical_json_roles: frozenset[str] = frozenset({"evidence"}),
    semantic_member_contracts: Mapping[str, BundleMemberSemanticContract] | None = None,
) -> BundleVerificationPolicy:
    legacy_ids = frozenset({manifest_id}) if manifest_id is not None else frozenset()
    return BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=48),
        now=NOW,
        replayed_manifest_ids=legacy_ids,
        revoked_manifest_ids=legacy_ids,
        supported_profiles=frozenset({PROFILE}),
        supported_schema_versions=frozenset({BUNDLE_SCHEMA_VERSION}),
        required_member_roles=required_member_roles,
        supported_member_roles=supported_member_roles,
        canonical_json_roles=canonical_json_roles,
        semantic_member_contracts=(
            semantic_member_contracts
            if semantic_member_contracts is not None
            else {
                "evidence": BundleMemberSemanticContract(
                    model_name="EvidenceOnlyDecisionReceipt",
                    schema_version_field="schemaVersion",
                    supported_schema_versions=frozenset({1}),
                    parser_version_field="validatorVersion",
                    supported_parser_versions=frozenset({"validator-v1"}),
                )
            }
        ),
    )


def _resources() -> dict[str, bytes]:
    data = canonical_json_bytes(_receipt_payload())
    return {f"resources/{_sha256(data)}.json": data}


def _receipt_payload() -> JsonObject:
    return {
        "decisionDigest": "d" * 64,
        "decisionId": "decision-fixture",
        "grantsAuthority": False,
        "promotionIntentDigest": "a" * 64,
        "schemaVersion": 1,
        "validatedAt": "2026-08-21T12:00:00Z",
        "validatorVersion": "validator-v1",
    }


def _resources_for_payload(payload: Mapping[str, Any]) -> dict[str, bytes]:
    data = canonical_json_bytes(payload)
    return {f"resources/{_sha256(data)}.json": data}


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


def _materialize(
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


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param(0o700, id="owner-executable"),
        pytest.param(0o640, id="group-readable"),
        pytest.param(0o604, id="world-readable"),
        pytest.param(0o4600, id="setuid"),
        pytest.param(0o400, id="not-exact-private-mode"),
    ],
)
def test_verifier_rejects_every_nonexact_private_file_mode(
    tmp_path: Path,
    mode: int,
) -> None:
    resources = _resources()
    root = tmp_path / "bundle"
    _materialize(root, resources)
    (root / next(iter(resources))).chmod(mode)

    with pytest.raises(BundleVerificationError, match="exact private mode 0o600"):
        verify_bundle(root, policy=_policy())


@pytest.mark.parametrize(
    "target,mode",
    [
        pytest.param("root", 0o750, id="root-group-access"),
        pytest.param("root", 0o1700, id="root-sticky-bit"),
        pytest.param("member-parent", 0o701, id="member-parent-world-access"),
        pytest.param("member-parent", 0o1700, id="member-parent-sticky-bit"),
        pytest.param("member-parent", 0o600, id="member-parent-not-exact-mode"),
    ],
)
def test_verifier_rejects_every_nonexact_private_directory_mode(
    tmp_path: Path,
    target: str,
    mode: int,
) -> None:
    resources = _resources()
    root = tmp_path / "bundle"
    _materialize(root, resources)
    selected = root if target == "root" else root / "resources"
    selected.chmod(mode)

    try:
        with pytest.raises(BundleVerificationError, match="exact private mode 0o700"):
            verify_bundle(root, policy=_policy())
    finally:
        selected.chmod(0o700)


def test_verifier_rejects_a_bundle_tree_owned_by_another_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    root = tmp_path / "bundle"
    _materialize(root, resources)
    effective_uid = os.geteuid()
    monkeypatch.setattr(bundle.os, "geteuid", lambda: effective_uid + 1)

    with pytest.raises(BundleVerificationError, match="owned by this process"):
        verify_bundle(root, policy=_policy())


def test_verifier_applies_an_explicit_trusted_directory_count_limit(
    tmp_path: Path,
) -> None:
    resources = _resources()
    root = tmp_path / "bundle"
    _materialize(root, resources)
    extra_directory = root / "extra"
    extra_directory.mkdir(mode=0o700)
    extra_directory.chmod(0o700)

    with pytest.raises(BundleVerificationError, match="directory-count limit"):
        verify_bundle(root, policy=replace(_policy(), max_directory_count=1))


def test_verifier_rejects_member_parent_identity_swap_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    member_path, member_data = next(iter(resources.items()))
    root = tmp_path / "bundle"
    _materialize(root, resources)
    member_inode = (root / member_path).stat().st_ino
    original_read = os.read
    swapped = False

    def swapping_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        if not swapped and os.fstat(descriptor).st_ino == member_inode:
            swapped = True
            original_directory = root / "resources"
            original_directory.rename(root / "resources-held")
            replacement = root / "resources"
            replacement.mkdir(mode=0o700)
            replacement.chmod(0o700)
            replacement_member = replacement / Path(member_path).name
            replacement_member.write_bytes(member_data)
            replacement_member.chmod(0o600)
        return original_read(descriptor, count)

    monkeypatch.setattr(bundle.os, "read", swapping_read)

    with pytest.raises(BundleVerificationError, match="identity|entries changed"):
        verify_bundle(root, policy=_policy())
    assert swapped


def test_verifier_rejects_root_path_identity_swap_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    member_path = next(iter(resources))
    root = tmp_path / "bundle"
    _materialize(root, resources)
    member_inode = (root / member_path).stat().st_ino
    original_read = os.read
    swapped = False

    def swapping_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        if not swapped and os.fstat(descriptor).st_ino == member_inode:
            swapped = True
            held = tmp_path / "held-bundle"
            root.rename(held)
            shutil.copytree(held, root)
        return original_read(descriptor, count)

    monkeypatch.setattr(bundle.os, "read", swapping_read)

    with pytest.raises(BundleVerificationError, match="identity|changed"):
        verify_bundle(root, policy=_policy())
    assert swapped


def test_semantic_manifest_identity_may_recur_across_executions(
    tmp_path: Path,
) -> None:
    resources = _resources()
    first_manifest = _manifest(resources, execution_id="execution-a")
    second_manifest = _manifest(resources, execution_id="execution-b")
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _materialize(first_root, resources, manifest=first_manifest)
    _materialize(second_root, resources, manifest=second_manifest)

    assert first_manifest["manifestId"] == second_manifest["manifestId"]
    legacy_policy = _policy(str(first_manifest["manifestId"]))
    assert (
        verify_bundle(first_root, policy=legacy_policy).manifest_id
        == first_manifest["manifestId"]
    )
    assert (
        verify_bundle(second_root, policy=legacy_policy).manifest_id
        == second_manifest["manifestId"]
    )


@pytest.mark.parametrize(
    "observed_at",
    [
        pytest.param("2026-08-21 12:00:00Z", id="space-separator"),
        pytest.param("2026-08-21T12:00:00.0Z", id="noncanonical-fraction"),
        pytest.param("2026-08-21T12:00:00.000000Z", id="redundant-fraction"),
        pytest.param("2026-08-21T12:00:00+00:00", id="numeric-utc-offset"),
        pytest.param("2026-08-21T12:00:00z", id="lowercase-z"),
    ],
)
def test_manifest_rejects_alternate_spellings_of_the_same_utc_instant(
    observed_at: str,
) -> None:
    manifest = _manifest(_resources())
    manifest["observedAt"] = observed_at
    manifest["manifestId"] = compute_manifest_id(manifest)

    with pytest.raises(BundleManifestError, match="canonical UTC spelling"):
        parse_manifest_bytes(canonical_json_bytes(manifest))


def test_manifest_accepts_the_single_canonical_microsecond_spelling() -> None:
    manifest = _manifest(
        _resources(),
        observed_at=NOW.replace(microsecond=123456),
    )

    parsed = parse_manifest_bytes(canonical_manifest_bytes(manifest))

    assert parsed["observedAt"] == "2026-08-21T12:00:00.123456Z"


def test_trusted_policy_rejects_a_remote_declared_unsupported_role(
    tmp_path: Path,
) -> None:
    resources = _resources()
    manifest = _manifest(resources)
    manifest["members"][0]["role"] = "remote-approved"
    manifest["memberSetSha256"] = compute_member_set_sha256(manifest["members"])
    manifest["manifestId"] = compute_manifest_id(manifest)
    root = tmp_path / "bundle"
    _materialize(root, resources, manifest=manifest)

    with pytest.raises(BundleVerificationError, match="unsupported by trusted policy"):
        verify_bundle(root, policy=_policy())


def test_trusted_policy_requires_semantic_roles_without_guessing_payload_schema(
    tmp_path: Path,
) -> None:
    resources = _resources()
    root = tmp_path / "bundle"
    _materialize(root, resources)
    policy = _policy(
        required_member_roles=frozenset({"evidence", "terminal-accounting"}),
        supported_member_roles=frozenset({"evidence", "terminal-accounting"}),
    )

    with pytest.raises(BundleVerificationError, match="missing a member role"):
        verify_bundle(root, policy=policy)


def test_trusted_canonical_json_role_rejects_noncanonical_member_bytes(
    tmp_path: Path,
) -> None:
    canonical_data = next(iter(_resources().values()))
    noncanonical_data = canonical_data.replace(b'"decisionId":', b'"decisionId": ', 1)
    resources = {f"resources/{_sha256(noncanonical_data)}.json": noncanonical_data}
    root = tmp_path / "bundle"
    _materialize(root, resources)

    with pytest.raises(BundleVerificationError, match="noncanonical bytes"):
        verify_bundle(root, policy=_policy())


def test_role_policy_rejects_requirements_outside_the_supported_vocabulary() -> None:
    with pytest.raises(BundleVerificationError, match="subset of supported roles"):
        _policy(
            required_member_roles=frozenset({"terminal-accounting"}),
            supported_member_roles=frozenset({"evidence"}),
        )


def test_canonical_role_policy_requires_one_known_explicit_semantic_contract() -> None:
    with pytest.raises(BundleVerificationError, match="explicit semantic contract"):
        _policy(semantic_member_contracts={})

    with pytest.raises(BundleVerificationError, match="model is unknown"):
        _policy(
            semantic_member_contracts={
                "evidence": BundleMemberSemanticContract(model_name="UnknownModel")
            }
        )


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        pytest.param("missing-schema", "schema version", id="missing-schema"),
        pytest.param("unknown-schema", "schema version", id="unknown-schema"),
        pytest.param("wrong-schema-type", "schema version", id="wrong-schema-type"),
        pytest.param("missing-parser", "parser version", id="missing-parser"),
        pytest.param("unknown-parser", "parser version", id="unknown-parser"),
        pytest.param("missing-required-field", "trusted schema", id="strict-model"),
    ],
)
def test_semantic_member_versions_and_strict_model_fail_closed(
    tmp_path: Path,
    mutation: str,
    diagnostic: str,
) -> None:
    payload = _receipt_payload()
    if mutation == "missing-schema":
        payload.pop("schemaVersion")
    elif mutation == "unknown-schema":
        payload["schemaVersion"] = 2
    elif mutation == "wrong-schema-type":
        payload["schemaVersion"] = "1"
    elif mutation == "missing-parser":
        payload.pop("validatorVersion")
    elif mutation == "unknown-parser":
        payload["validatorVersion"] = "validator-v999"
    else:
        payload.pop("decisionDigest")
    resources = _resources_for_payload(payload)
    root = tmp_path / "bundle"
    _materialize(root, resources)

    with pytest.raises(BundleVerificationError, match=diagnostic):
        verify_bundle(root, policy=_policy())


@pytest.mark.parametrize(
    "channel_state,request_in_flight,unfinished_operation_ids,accepted",
    [
        pytest.param("complete", 0, [], True, id="closed"),
        pytest.param("nonterminal", 1, ["operation-1"], False, id="nonterminal"),
        pytest.param("partial", 0, ["operation-1"], False, id="unfinished"),
    ],
)
def test_terminal_accounting_contract_requires_an_exact_closed_denominator(
    tmp_path: Path,
    channel_state: str,
    request_in_flight: int,
    unfinished_operation_ids: list[str],
    accepted: bool,
) -> None:
    payload = {
        "admittedBytes": 1,
        "blocked": 0,
        "byteLimit": 1,
        "cancelled": 0,
        "channel": "official",
        "channelState": channel_state,
        "failed": 0,
        "plannedOperations": 1,
        "rateLimited": 0,
        "remainingBytes": 0,
        "requestConsumed": 1 - request_in_flight,
        "requestInFlight": request_in_flight,
        "requestLimit": 1,
        "requestRemaining": 0,
        "succeeded": 1,
        "timedOut": 0,
        "unfinishedOperationIds": unfinished_operation_ids,
        "unstarted": 0,
    }
    resources = _resources_for_payload(payload)
    manifest = _manifest(resources)
    manifest["members"][0]["role"] = "terminal-accounting"
    manifest["memberSetSha256"] = compute_member_set_sha256(manifest["members"])
    manifest["manifestId"] = compute_manifest_id(manifest)
    root = tmp_path / "bundle"
    _materialize(root, resources, manifest=manifest)
    policy = _policy(
        required_member_roles=frozenset({"terminal-accounting"}),
        supported_member_roles=frozenset({"terminal-accounting"}),
        canonical_json_roles=frozenset({"terminal-accounting"}),
        semantic_member_contracts={
            "terminal-accounting": BundleMemberSemanticContract(
                model_name="ChannelOperationAccounting",
                require_terminal_accounting_closure=True,
            )
        },
    )

    if accepted:
        assert verify_bundle(root, policy=policy).member_paths == tuple(resources)
    else:
        with pytest.raises(BundleVerificationError, match="denominator is not closed"):
            verify_bundle(root, policy=policy)


def test_writer_secret_scans_every_full_resource_before_filesystem_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b'{"authorization":"Bearer synthetic-token-value-123456"}\n'
    resources = {f"resources/{_sha256(data)}.json": data}
    output_root = tmp_path / "quarantine"
    write_calls: list[str] = []
    original_write = bundle._write_file_at

    def tracking_write(directory_descriptor: int, name: str, content: bytes) -> None:
        write_calls.append(name)
        original_write(directory_descriptor, name, content)

    monkeypatch.setattr(bundle, "_write_file_at", tracking_write)

    with pytest.raises(BundleWriteError, match="secret_detected"):
        write_bundle(
            output_root,
            manifest=_manifest(resources),
            resources=_bundle_resources(resources),
            verification_policy=_policy(
                canonical_json_roles=frozenset(),
                semantic_member_contracts={},
            ),
        )

    assert write_calls == []
    assert not output_root.exists()


@pytest.mark.parametrize(
    "policy_overrides,resources",
    [
        pytest.param(
            {"max_member_count": 1},
            {"resources/a.json": b"a", "resources/b.json": b"b"},
            id="member-count",
        ),
        pytest.param(
            {"max_member_bytes": 1},
            {"resources/a.json": b"aa"},
            id="member-bytes",
        ),
        pytest.param(
            {"max_total_member_bytes": 1},
            {"resources/a.json": b"a", "resources/b.json": b"b"},
            id="aggregate-bytes",
        ),
    ],
)
def test_writer_rejects_manifest_limits_before_resource_iteration_or_disk(
    tmp_path: Path,
    policy_overrides: Mapping[str, int],
    resources: Mapping[str, bytes],
) -> None:
    iterated = False

    def tracked_resources() -> Iterable[BundleResource]:
        nonlocal iterated
        iterated = True
        yield from _bundle_resources(resources)

    policy = replace(
        _policy(canonical_json_roles=frozenset(), semantic_member_contracts={}),
        **policy_overrides,
    )
    output_root = tmp_path / "quarantine"

    with pytest.raises(BundleVerificationError, match="trusted .* limit"):
        write_bundle(
            output_root,
            manifest=_manifest(resources),
            resources=tracked_resources(),
            verification_policy=policy,
        )

    assert not iterated
    assert not output_root.exists()


@pytest.mark.parametrize("limit_kind", ["member", "aggregate"])
def test_writer_incrementally_enforces_actual_resource_byte_limits_before_disk(
    tmp_path: Path,
    limit_kind: str,
) -> None:
    resources = {"resources/a.json": b"a"}
    inputs = _bundle_resources(resources)
    policy_overrides: dict[str, int]
    if limit_kind == "member":
        inputs[0] = replace(inputs[0], data=b"aa")
        policy_overrides = {"max_member_bytes": 1}
    else:
        resources["resources/b.json"] = b"b"
        inputs = _bundle_resources(resources)
        inputs[1] = replace(inputs[1], data=b"bb")
        policy_overrides = {"max_total_member_bytes": 2}
    policy = replace(
        _policy(canonical_json_roles=frozenset(), semantic_member_contracts={}),
        **policy_overrides,
    )
    output_root = tmp_path / "quarantine"

    with pytest.raises(BundleVerificationError, match="trusted .* limit"):
        write_bundle(
            output_root,
            manifest=_manifest(resources),
            resources=inputs,
            verification_policy=policy,
        )

    assert not output_root.exists()


def test_writer_uses_exact_private_modes_and_verifies_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    manifest = _manifest(resources)
    output_root = tmp_path / "quarantine"
    original_verify = bundle.verify_bundle
    candidate_calls: list[Path] = []

    def tracking_verify(
        root: Path,
        *,
        policy: BundleVerificationPolicy,
    ) -> bundle.VerifiedBundle:
        candidate_root = Path(root)
        candidate_calls.append(candidate_root)
        assert candidate_root.name.startswith(f".{manifest['manifestId']}.")
        assert not (output_root / str(manifest["manifestId"])).exists()
        return original_verify(candidate_root, policy=policy)

    monkeypatch.setattr(bundle, "verify_bundle", tracking_verify)

    published = write_bundle(
        output_root,
        manifest=manifest,
        resources=_bundle_resources(resources),
        verification_policy=_policy(),
    )

    assert len(candidate_calls) == 1
    for path in (output_root, published, published / "resources"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for path in (published / "manifest.json", published / next(iter(resources))):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_candidate_verification_failure_prevents_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    manifest = deepcopy(_manifest(resources))
    output_root = tmp_path / "quarantine"

    def reject_candidate(
        root: Path,
        *,
        policy: BundleVerificationPolicy,
    ) -> bundle.VerifiedBundle:
        del root, policy
        raise BundleVerificationError("simulated candidate verification failure")

    monkeypatch.setattr(bundle, "verify_bundle", reject_candidate)

    with pytest.raises(BundleWriteError, match="publication did not complete"):
        write_bundle(
            output_root,
            manifest=manifest,
            resources=_bundle_resources(resources),
            verification_policy=_policy(),
        )

    assert not (output_root / str(manifest["manifestId"])).exists()
    assert not tuple(output_root.glob(".*"))


def test_writer_rejects_a_symlinked_output_root_without_touching_its_target(
    tmp_path: Path,
) -> None:
    resources = _resources()
    real_root = tmp_path / "real"
    real_root.mkdir(mode=0o700)
    real_root.chmod(0o700)
    output_root = tmp_path / "quarantine"
    output_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(BundleWriteError, match="output root is unsafe"):
        write_bundle(
            output_root,
            manifest=_manifest(resources),
            resources=_bundle_resources(resources),
            verification_policy=_policy(),
        )

    assert tuple(real_root.iterdir()) == ()


def test_atomic_no_replace_keeps_a_racing_target_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _resources()
    manifest = _manifest(resources)
    output_root = tmp_path / "quarantine"
    original_publish = bundle._rename_noreplace_at
    sentinel = b"competitor-owned"

    def racing_publish(
        directory_descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        competitor = output_root / target_name
        competitor.mkdir(mode=0o700)
        competitor.chmod(0o700)
        marker = competitor / "sentinel"
        marker.write_bytes(sentinel)
        marker.chmod(0o600)
        original_publish(directory_descriptor, source_name, target_name)

    monkeypatch.setattr(bundle, "_rename_noreplace_at", racing_publish)

    with pytest.raises(bundle.BundleAlreadyExistsError):
        write_bundle(
            output_root,
            manifest=manifest,
            resources=_bundle_resources(resources),
            verification_policy=_policy(),
        )

    target = output_root / str(manifest["manifestId"])
    assert (target / "sentinel").read_bytes() == sentinel
    assert not tuple(output_root.glob(".*.tmp"))


def test_bundle_module_rejects_weaker_http_cache_and_plugin_seams() -> None:
    source_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "openopps"
        / "discovery"
        / "bundle.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "openopps.http",
        "openopps.cache",
        "openopps.plugins",
        "openopps.cli",
        "httpx",
        "httpcore",
    }
    assert imported.isdisjoint(forbidden)
    assert "openopps.discovery.http_client" not in imported
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "openopps.discovery.transport"
        and any(alias.name == "validate_public_locator" for alias in node.names)
        for node in ast.walk(tree)
    )
