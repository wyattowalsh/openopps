from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str, filename: str) -> object:
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _load_script("docs_search_release", "docs_search_release.py")
delivery = _load_script("docs_search_delivery", "docs_search_delivery.py")

_DIGEST = "a" * 64
_SOURCE = {
    "kind": "sqlite",
    "path": "kaggle/openoppsdb.sqlite",
    "bytes": 123,
    "sha256": _DIGEST,
}
_GENERATOR = {
    "name": "openopps-docs-search-index",
    "entrypoint": "scripts/generate_docs_search_index.py",
    "payloadSchemaVersion": 6,
    "components": [
        {"path": "scripts/generate_docs_search_index.py", "sha256": _DIGEST}
    ],
}


@pytest.fixture(autouse=True)
def _isolate_owned_delivery_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delivery, "DELIVERY_ROOT", tmp_path / "owned-delivery")


def _owned_assets() -> Path:
    return delivery.DELIVERY_ROOT / "staging" / "assets"


def test_configs_are_exact_assets_only_and_drift_is_rejected(tmp_path: Path) -> None:
    config_root = _ROOT / "deployment" / "openopps-data"
    assert delivery.validate_configs(config_root) == []

    copied = tmp_path / "deployment"
    _copy_config(config_root / "staging" / "wrangler.jsonc", copied / "staging")
    _copy_config(config_root / "production" / "wrangler.jsonc", copied / "production")
    path = copied / "production" / "wrangler.jsonc"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["main"] = "worker.js"
    path.write_text(json.dumps(config), encoding="utf-8")

    errors = delivery.validate_configs(copied)
    assert any("main" in error and "forbidden" in error for error in errors)


def test_stage_is_atomic_and_contains_exact_current_previous_and_headers(
    tmp_path: Path,
) -> None:
    publication, current, previous = _publication(tmp_path)
    destination = _owned_assets()

    result = delivery.stage_publication(publication, destination)

    assert result.current_release_id == current
    assert result.previous_release_id == previous
    assert {path.name for path in (destination / "releases").iterdir()} == {
        current,
        previous,
    }
    assert (destination / "channels" / "production.json").is_file()
    headers = (destination / "_headers").read_text(encoding="utf-8")
    assert "Access-Control-Allow-Origin: *" in headers
    assert "X-Content-Type-Options: nosniff" in headers
    assert "X-Robots-Tag: noindex, nofollow" in headers
    assert "/channels/*" in headers and "max-age=0, must-revalidate" in headers
    assert "/releases/*" in headers and "max-age=31536000, immutable" in headers
    assert delivery.verify_stage(destination) == []


@pytest.mark.parametrize("mutation", ["tamper", "missing", "extra", "symlink"])
def test_stage_verifier_rejects_tamper_missing_extra_and_symlink(
    tmp_path: Path, mutation: str
) -> None:
    publication, current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)
    target = destination / "releases" / current / "providers.json"
    if mutation == "tamper":
        target.write_bytes(target.read_bytes().replace(b"Current", b"Broken!"))
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (destination / "extra.json").write_text("{}\n", encoding="utf-8")
    else:
        outside = tmp_path / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        (destination / "escape.json").symlink_to(outside)

    assert delivery.verify_stage(destination)


def test_stage_rejects_missing_previous_without_replacing_existing_output(
    tmp_path: Path,
) -> None:
    publication, _current, previous = _publication(tmp_path)
    destination = _owned_assets()
    destination.mkdir(parents=True)
    sentinel = destination / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    _remove_tree(publication / "releases" / previous)

    with pytest.raises(delivery.DeliveryError, match="prior release"):
        delivery.stage_publication(publication, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing-search", "search-manifest.json"),
        ("missing-policy", "publication-policy.json"),
        ("publication-false", "publicationAllowed must be true"),
    ],
)
def test_stage_rejects_incomplete_or_non_publishable_governance_graph_atomically(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    destination.mkdir(parents=True)
    sentinel = destination / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    _rewrite_current_governance(publication, mutation=mutation)

    with pytest.raises(delivery.DeliveryError, match=expected):
        delivery.stage_publication(publication, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_stage_defaults_to_48h_freshness_and_allows_only_reasoned_degraded_data(
    tmp_path: Path,
) -> None:
    stale_snapshot = "2000-01-02T00:00:00Z"
    publication, _current, _previous = _publication(
        tmp_path / "ordinary", current_snapshot_at=stale_snapshot
    )

    with pytest.raises(delivery.DeliveryError, match="snapshot is stale by policy"):
        delivery.stage_publication(publication, _owned_assets())

    degraded_publication, _current, _previous = _publication(
        tmp_path / "degraded",
        current_snapshot_at=stale_snapshot,
        degraded_reason=(
            "Incident OPS-2000-01-02: upstream unavailable; maintainer approved "
            "bounded degraded publication."
        ),
    )
    result = delivery.stage_publication(degraded_publication, _owned_assets())
    assert result.destination == _owned_assets()
    assert delivery.verify_stage(_owned_assets()) == []


def test_stage_rejects_arbitrary_protected_and_nested_destinations(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    protected = tmp_path / "protected-project"
    protected.mkdir()
    sentinel = protected / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    forbidden = [
        protected,
        delivery.DELIVERY_ROOT,
        delivery.DELIVERY_ROOT / "staging",
        delivery.DELIVERY_ROOT / "staging" / "assets" / "nested",
    ]

    for destination in forbidden:
        with pytest.raises(delivery.DeliveryError, match="must be exactly"):
            delivery.stage_publication(publication, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_stage_rejects_symlinked_owned_ancestor(tmp_path: Path) -> None:
    publication, _current, _previous = _publication(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    delivery.DELIVERY_ROOT.mkdir(parents=True)
    (delivery.DELIVERY_ROOT / "staging").symlink_to(external, target_is_directory=True)

    with pytest.raises(delivery.DeliveryError, match="ancestor is a symlink"):
        delivery.stage_publication(publication, _owned_assets())


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is POSIX-only")
def test_stage_verifier_rejects_special_files_without_opening_them(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)
    os.mkfifo(destination / "blocked.fifo")

    errors = delivery.verify_stage(destination)

    assert any(
        "only regular files" in error and "blocked.fifo" in error for error in errors
    )


def test_stage_verifier_enforces_free_plan_budget_with_safety_margin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)
    assert delivery.MAX_WORKER_FILES == 20_000
    assert delivery.MAX_WORKER_FILE_BYTES == 24 * 1024 * 1024

    monkeypatch.setattr(delivery, "MAX_WORKER_FILES", 1)
    monkeypatch.setattr(delivery, "MAX_WORKER_FILE_BYTES", 1)
    errors = delivery.verify_stage(destination)

    assert any("limit is 1" in error for error in errors)
    assert any("must be smaller than 1" in error for error in errors)


def test_remote_verifier_reads_back_every_file_and_checks_missing_path(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)
    seen: list[str] = []

    def fetch(url: str) -> delivery.RemoteResponse:
        path = unquote(urlsplit(url).path).lstrip("/")
        seen.append(path)
        local = destination / path
        if not local.is_file():
            return delivery.RemoteResponse(status=404, body=b"", headers={})
        cache = (
            "public, max-age=31536000, immutable"
            if path.startswith("releases/")
            else "public, max-age=0, must-revalidate"
        )
        return delivery.RemoteResponse(
            status=200,
            body=local.read_bytes(),
            headers={
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
                "X-Robots-Tag": "noindex, nofollow",
                "Cache-Control": cache,
                "ETag": f'"{hashlib.sha256(local.read_bytes()).hexdigest()}"',
            },
        )

    report = delivery.verify_remote(
        destination, "https://openopps-data.example.workers.dev", fetch=fetch
    )

    expected = delivery.served_files(destination)
    assert report.errors == ()
    assert report.checked_files == len(expected)
    assert set(seen[:-1]) == {path.as_posix() for path in expected}
    assert seen[-1].startswith("__openopps_missing__/")


def test_remote_verifier_rejects_wrong_hash_headers_and_missing_behavior(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)

    def broken_fetch(url: str) -> delivery.RemoteResponse:
        path = unquote(urlsplit(url).path).lstrip("/")
        if path.startswith("__openopps_missing__/"):
            return delivery.RemoteResponse(status=200, body=b"surprise", headers={})
        return delivery.RemoteResponse(
            status=200,
            body=b"tampered",
            headers={"Cache-Control": "no-store"},
        )

    report = delivery.verify_remote(
        destination, "https://openopps-data.example.workers.dev", fetch=broken_fetch
    )

    assert any("SHA-256" in error for error in report.errors)
    assert any("CORS" in error for error in report.errors)
    assert any("ETag" in error for error in report.errors)
    assert any("missing-path probe returned 200" in error for error in report.errors)


def test_remote_verifier_rejects_non_workers_dev_origin_without_fetching(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    destination = _owned_assets()
    delivery.stage_publication(publication, destination)

    report = delivery.verify_remote(destination, "https://example.com")

    assert report.checked_files == 0
    assert any("workers.dev" in error for error in report.errors)
    assert (
        delivery.main(["verify-remote", str(destination), "https://example.com"]) == 1
    )


def test_upload_machine_output_is_parsed_into_atomic_minimal_ledger(
    tmp_path: Path,
) -> None:
    publication, current, previous = _publication(tmp_path)
    stage = _owned_assets()
    staged = delivery.stage_publication(publication, stage)
    ledger = tmp_path / "ledger" / "staging.json"
    invocation = delivery.build_upload_invocation(
        config=_ROOT / "deployment" / "openopps-data" / "staging" / "wrangler.jsonc",
        output_file=tmp_path / "wrangler-output.jsonl",
        stage_root=stage,
    )
    output = json.dumps(
        {
            "type": "version-upload",
            "version": 1,
            "worker_name": "openopps-data-staging",
            "worker_tag": "worker-tag",
            "version_id": "095f00a7-23a7-43b7-a227-e4c97cab5f22",
            "preview_url": "https://example.workers.dev",
            "preview_alias_url": None,
            "wrangler_environment": None,
            "worker_name_overridden": False,
            "timestamp": "2026-08-12T15:00:00.000Z",
        }
    )

    entry = delivery.record_upload(
        output,
        ledger,
        environment="staging",
        upload_candidate_root=invocation.upload_candidate_root,
        expected_upload_candidate_digest=invocation.upload_candidate_digest,
        expected_stage_root_digest=staged.root_digest,
        recorded_at="2026-08-12T15:01:00Z",
    )

    persisted = json.loads(ledger.read_text(encoding="utf-8"))
    assert entry["workerVersionId"] == "095f00a7-23a7-43b7-a227-e4c97cab5f22"
    assert entry["currentReleaseId"] == current
    assert entry["previousReleaseId"] == previous
    assert entry["stageRootDigest"] == staged.root_digest
    assert entry["uploadExpectedStageRootDigest"] == staged.root_digest
    assert entry["uploadCandidateDigest"] == invocation.upload_candidate_digest
    assert (
        entry["uploadExpectedCandidateDigest"]
        == invocation.upload_candidate_digest
    )
    assert persisted["entries"] == [entry]
    assert "preview_url" not in json.dumps(persisted)


def test_upload_reads_digest_addressed_candidate_not_mutable_stage(
    tmp_path: Path,
) -> None:
    publication, _current, _previous = _publication(tmp_path / "version-a")
    stage = _owned_assets()
    delivery.stage_publication(publication, stage)
    output_path = tmp_path / "upload.jsonl"
    config = _ROOT / "deployment" / "openopps-data" / "staging" / "wrangler.jsonc"
    invocation = delivery.build_upload_invocation(
        config=config,
        output_file=output_path,
        stage_root=stage,
    )
    candidate_bytes = {
        path.relative_to(invocation.upload_candidate_root): path.read_bytes()
        for path in invocation.upload_candidate_root.rglob("*")
        if path.is_file()
    }
    assert invocation.upload_candidate_root.name == invocation.upload_candidate_digest
    assert invocation.argv[-3:] == [
        "--config",
        str(invocation.upload_candidate_root / "wrangler.jsonc"),
        "--strict",
    ]
    assert all(
        path.stat().st_mode & 0o222 == 0
        for path in [
            invocation.upload_candidate_root,
            *invocation.upload_candidate_root.rglob("*"),
        ]
    )

    headers = stage / "_headers"
    original_headers = headers.read_bytes()
    headers.write_bytes(b"transient source mutation\n")
    headers.write_bytes(original_headers)
    output = json.dumps(
        {
            "type": "version-upload",
            "version": 1,
            "worker_name": "openopps-data-staging",
            "version_id": "095f00a7-23a7-43b7-a227-e4c97cab5f22",
        }
    )
    replacement, _current, _previous = _publication(tmp_path / "version-b")
    delivery.stage_publication(replacement, stage)

    assert candidate_bytes == {
        path.relative_to(invocation.upload_candidate_root): path.read_bytes()
        for path in invocation.upload_candidate_root.rglob("*")
        if path.is_file()
    }
    entry = delivery.record_upload(
        output,
        tmp_path / "ledger.json",
        environment="staging",
        upload_candidate_root=invocation.upload_candidate_root,
        expected_upload_candidate_digest=invocation.upload_candidate_digest,
        expected_stage_root_digest=invocation.stage_root_digest,
        recorded_at="2026-08-12T15:01:00Z",
    )

    assert entry["currentReleaseId"] == invocation.current_release_id
    assert entry["previousReleaseId"] == invocation.previous_release_id
    assert entry["stageRootDigest"] == invocation.stage_root_digest


def test_upload_record_rejects_candidate_tampering(tmp_path: Path) -> None:
    publication, _current, _previous = _publication(tmp_path)
    stage = _owned_assets()
    delivery.stage_publication(publication, stage)
    invocation = delivery.build_upload_invocation(
        config=_ROOT / "deployment" / "openopps-data" / "staging" / "wrangler.jsonc",
        output_file=tmp_path / "upload.jsonl",
        stage_root=stage,
    )
    candidate_headers = invocation.upload_candidate_root / "assets" / "_headers"
    candidate_headers.chmod(0o600)
    candidate_headers.write_bytes(b"candidate mutation\n")
    output = json.dumps(
        {
            "type": "version-upload",
            "version": 1,
            "worker_name": "openopps-data-staging",
            "version_id": "095f00a7-23a7-43b7-a227-e4c97cab5f22",
        }
    )

    with pytest.raises(delivery.DeliveryError, match="upload candidate"):
        delivery.record_upload(
            output,
            tmp_path / "ledger.json",
            environment="staging",
            upload_candidate_root=invocation.upload_candidate_root,
            expected_upload_candidate_digest=invocation.upload_candidate_digest,
            expected_stage_root_digest=invocation.stage_root_digest,
            recorded_at="2026-08-12T15:01:00Z",
        )

    assert not (tmp_path / "ledger.json").exists()


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        json.dumps({"type": "deploy", "version": 1}),
        json.dumps(
            {
                "type": "version-upload",
                "version": 1,
                "worker_name": "openopps-data-staging",
                "version_id": "bad; touch /tmp/pwned",
            }
        ),
    ],
)
def test_upload_machine_output_rejects_malformed_or_untrusted_identity(
    output: str,
) -> None:
    with pytest.raises(delivery.DeliveryError):
        delivery.parse_upload_output(output)


def test_promotion_rollback_repromotion_state_sequence_and_argv_safety(
    tmp_path: Path,
) -> None:
    config = _ROOT / "deployment" / "openopps-data" / "production" / "wrangler.jsonc"
    current = "095f00a7-23a7-43b7-a227-e4c97cab5f22"
    previous = "1a88955c-2fbd-4a72-9d9b-3ba1e59842f2"
    state = delivery.new_rollout_state(current=current, previous=previous)

    promote = delivery.next_rollout_action(state, "promote", config=config)
    rollback = delivery.next_rollout_action(promote.state, "rollback", config=config)
    repromote = delivery.next_rollout_action(
        rollback.state, "re-promote", config=config
    )

    assert promote.argv[-3:] == [f"{current}@100%", "--yes", "--dry-run"]
    assert rollback.argv[-3:] == [f"{previous}@100%", "--yes", "--dry-run"]
    assert repromote.argv[-3:] == [f"{current}@100%", "--yes", "--dry-run"]
    assert repromote.state["phase"] == "repromoted"
    live_plan = delivery.build_rollout_plan(
        current=current, previous=previous, config=config, dry_run=False
    )
    assert [item["action"] for item in live_plan["actions"]] == [
        "promote",
        "rollback",
        "re-promote",
    ]
    assert all("--dry-run" not in item["argv"] for item in live_plan["actions"])
    with pytest.raises(delivery.DeliveryError):
        delivery.new_rollout_state(current="bad; touch /tmp/pwned", previous=previous)
    tampered = dict(promote.state)
    tampered["history"] = [
        {"action": "promote", "workerVersionId": previous, "percentage": 100}
    ]
    with pytest.raises(delivery.DeliveryError, match="history"):
        delivery.next_rollout_action(tampered, "rollback", config=config)


def test_upload_and_deploy_argv_are_exact_and_never_shell_strings(
    tmp_path: Path,
) -> None:
    config = _ROOT / "deployment" / "openopps-data" / "staging" / "wrangler.jsonc"
    output = tmp_path / "wrangler-output.jsonl"
    publication, current, previous = _publication(tmp_path)
    stage = _owned_assets()
    staged = delivery.stage_publication(publication, stage)

    invocation = delivery.build_upload_invocation(
        config=config, output_file=output, stage_root=stage
    )

    assert invocation.argv == [
        "pnpm",
        "--dir",
        str((_ROOT / "web").resolve()),
        "exec",
        "wrangler",
        "versions",
        "upload",
        "--config",
        str(invocation.upload_candidate_root / "wrangler.jsonc"),
        "--strict",
    ]
    assert invocation.env == {"WRANGLER_OUTPUT_FILE_PATH": str(output.resolve())}
    assert invocation.stage_root_digest == staged.root_digest
    assert invocation.upload_candidate_root.name == invocation.upload_candidate_digest
    assert invocation.current_release_id == current
    assert invocation.previous_release_id == previous
    assert "--json" not in invocation.argv
    assert all(isinstance(part, str) for part in invocation.argv)
    output.write_text("stale\n", encoding="utf-8")
    with pytest.raises(delivery.DeliveryError, match="absent"):
        delivery.build_upload_invocation(
            config=config, output_file=output, stage_root=stage
        )

    copied = tmp_path / "unowned-configs"
    _copy_config(config, copied / "staging")
    _copy_config(
        _ROOT / "deployment" / "openopps-data" / "production" / "wrangler.jsonc",
        copied / "production",
    )
    assert delivery.validate_configs(copied) == []
    with pytest.raises(delivery.DeliveryError, match="repository-owned"):
        delivery.build_upload_invocation(
            config=copied / "staging" / "wrangler.jsonc",
            output_file=tmp_path / "other-output.jsonl",
            stage_root=stage,
        )


def test_archive_is_deterministic_and_contains_checksums_sbom_and_provenance(
    tmp_path: Path,
) -> None:
    publication, current, previous = _publication(tmp_path)
    stage = _owned_assets()
    staged = delivery.stage_publication(publication, stage)
    asset_name = f"openopps-data-{staged.root_digest}.tar.gz"
    first = tmp_path / "first" / asset_name
    second = tmp_path / "second" / asset_name

    first_result = delivery.build_recovery_archive(
        stage,
        first,
        created_at="2026-08-12T15:00:00Z",
        source_revision="0123456789abcdef0123456789abcdef01234567",
    )
    second_result = delivery.build_recovery_archive(
        stage,
        second,
        created_at="2026-08-12T15:00:00Z",
        source_revision="0123456789abcdef0123456789abcdef01234567",
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_result.sha256 == second_result.sha256
    assert (
        first_result.asset_name
        == f"openopps-data-{first_result.stage_root_digest}.tar.gz"
    )
    members = delivery.inspect_recovery_archive(first)
    assert "SHA256SUMS" in members
    assert "bundle-manifest.json" in members
    assert "sbom.spdx.json" in members
    assert "provenance.json" in members
    provenance = json.loads(members["provenance.json"])
    assert provenance["currentReleaseId"] == current
    assert provenance["previousReleaseId"] == previous
    assert provenance["wranglerVersion"] == "4.122.0"
    assert set(provenance["materials"]) == {
        "channelPointerSha256",
        "deliveryScriptSha256",
        "headersSha256",
        "productionConfigSha256",
        "stagingConfigSha256",
        "webLockSha256",
        "webPackageSha256",
    }


def test_archive_streams_stage_files_without_whole_file_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, _current, _previous = _publication(
        tmp_path, binary_bytes=2 * 1024 * 1024
    )
    stage = _owned_assets()
    staged = delivery.stage_publication(publication, stage)
    archive = tmp_path / f"openopps-data-{staged.root_digest}.tar.gz"
    original_read_bytes = Path.read_bytes

    def reject_stage_read_bytes(path: Path) -> bytes:
        if path.is_relative_to(stage):
            raise AssertionError(f"whole-file read attempted for {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_stage_read_bytes)

    result = delivery.build_recovery_archive(
        stage,
        archive,
        created_at="2026-08-12T15:00:00Z",
        source_revision="0123456789abcdef0123456789abcdef01234567",
    )

    assert result.bytes > 0


def _publication(
    tmp_path: Path,
    *,
    binary_bytes: int = 0,
    current_snapshot_at: str | None = None,
    degraded_reason: str | None = None,
) -> tuple[Path, str, str]:
    publication = tmp_path / "publication"
    promoted = datetime.now(timezone.utc)
    current_snapshot = (
        datetime.fromisoformat(current_snapshot_at.replace("Z", "+00:00"))
        if current_snapshot_at is not None
        else promoted - timedelta(hours=1)
    )
    previous_snapshot = current_snapshot - timedelta(days=1)
    previous_manifest = _release(
        publication,
        "Previous",
        previous_snapshot.isoformat(),
        binary_bytes=binary_bytes,
    )
    current_manifest = _release(
        publication,
        "Current",
        current_snapshot.isoformat(),
        binary_bytes=binary_bytes,
    )
    release.atomic_write_channel_pointer(
        publication,
        current_manifest,
        channel="production",
        prior_release_id=previous_manifest["releaseId"],
        degraded_reason=degraded_reason,
        promoted_at=promoted.isoformat(),
    )
    return publication, current_manifest["releaseId"], previous_manifest["releaseId"]


def _release(
    publication: Path,
    company: str,
    snapshot_at: str,
    *,
    binary_bytes: int = 0,
) -> dict[str, object]:
    staging = publication.parent / f"staging-{company.casefold()}"
    canonical_snapshot = release.canonical_utc_timestamp(snapshot_at)
    source_key = company.casefold()
    snapshot_counts = {
        "sourceRows": 1,
        "providerRoutes": 1,
        "boards": 1,
        "jobs": 1,
        "openJobs": 1,
    }
    _write_json(
        staging / "search-manifest.json",
        {
            "version": 6,
            "snapshotAt": canonical_snapshot,
            "facets": {"sources": [source_key]},
            "counts": {"snapshot": snapshot_counts},
            "detailShards": {"tierCounts": {"T1": 0, "T2": 1}},
        },
    )
    _write_json(
        staging / "publication-policy.json",
        {
            "schemaVersion": 1,
            "allowedLicenseStatuses": [
                "official_public",
                "oss_attribution_required",
                "public_attribution_required",
            ],
            "attributionRequiredStatuses": [
                "oss_attribution_required",
                "public_attribution_required",
            ],
            "sourceCount": 1,
            "sources": [
                {
                    "key": source_key,
                    "licenseStatus": "official_public",
                    "sourceAttribution": None,
                    "publicationAllowed": True,
                }
            ],
            "quality": {
                "snapshotAt": canonical_snapshot,
                **snapshot_counts,
                "detailTiers": {"T1": 0, "T2": 1},
            },
        },
    )
    _write_json(staging / "providers.json", {"rows": [[company]], "count": 1})
    _write_json(staging / "jobs-details" / "00.json", {"job-1": {"company": company}})
    if binary_bytes:
        (staging / "payload.bin").write_bytes(b"x" * binary_bytes)
    manifest = release.build_release_manifest(
        staging,
        snapshot_at=snapshot_at,
        source=_SOURCE,
        generator=_GENERATOR,
    )
    release.write_release_manifest(staging, manifest)
    destination = publication / "releases" / manifest["releaseId"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(destination)
    return manifest


def _rewrite_current_governance(publication: Path, *, mutation: str) -> None:
    pointer_path = publication / "channels" / "production.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    current = str(pointer["releaseId"])
    current_root = publication / "releases" / current
    old_manifest = json.loads(
        (current_root / "manifest.json").read_text(encoding="utf-8")
    )
    policy_path = current_root / "publication-policy.json"
    if mutation == "missing-search":
        (current_root / "search-manifest.json").unlink()
    elif mutation == "missing-policy":
        policy_path.unlink()
    else:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["sources"][0]["publicationAllowed"] = False
        _write_json(policy_path, policy)
    (current_root / "manifest.json").unlink()
    manifest = release.build_release_manifest(
        current_root,
        snapshot_at=old_manifest["snapshotAt"],
        source=old_manifest["source"],
        generator=old_manifest["generator"],
    )
    release.write_release_manifest(current_root, manifest)
    replacement = publication / "releases" / manifest["releaseId"]
    current_root.rename(replacement)
    release.atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        prior_release_id=pointer["priorReleaseId"],
        degraded_reason=pointer["degradedReason"],
        promoted_at=pointer["promotedAt"],
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")


def _copy_config(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "wrangler.jsonc").write_bytes(source.read_bytes())


def _remove_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    root.rmdir()
