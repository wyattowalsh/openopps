from __future__ import annotations

import json
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "docs_search_release.py"
)
_SPEC = importlib.util.spec_from_file_location("docs_search_release", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
_VERIFY_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "verify_docs_search_artifacts.py"
)
_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_docs_search_artifacts", _VERIFY_SCRIPT_PATH
)
assert _VERIFY_SPEC and _VERIFY_SPEC.loader
_VERIFY_MODULE = importlib.util.module_from_spec(_VERIFY_SPEC)
sys.modules[_VERIFY_SPEC.name] = _VERIFY_MODULE
_VERIFY_SPEC.loader.exec_module(_VERIFY_MODULE)
MAX_RELEASE_FILE_BYTES = _MODULE.MAX_RELEASE_FILE_BYTES
MAX_RELEASE_FILES = _MODULE.MAX_RELEASE_FILES
PromotionPolicy = _MODULE.PromotionPolicy
atomic_write_channel_pointer = _MODULE.atomic_write_channel_pointer
build_release_manifest = _MODULE.build_release_manifest
validate_publication = _MODULE.validate_publication
validate_release = _MODULE.validate_release
write_release_manifest = _MODULE.write_release_manifest
validate_artifacts = _VERIFY_MODULE.validate_artifacts

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
        {"path": "scripts/generate_docs_search_index.py", "sha256": _DIGEST},
        {"path": "src/openopps/source_policy.py", "sha256": _DIGEST},
        {
            "path": ("src/openopps/providers/sources/data/source_policy_evidence.json"),
            "sha256": _DIGEST,
        },
        {
            "path": (
                "src/openopps/providers/sources/data/source_policy_evidence.schema.json"
            ),
            "sha256": _DIGEST,
        },
        {
            "path": "deployment/openopps-data/source-corpus-v6.json",
            "sha256": _DIGEST,
        },
    ],
}


def test_v7_manifest_closes_over_payload_and_publication_pointer(
    tmp_path: Path,
) -> None:
    staged = _write_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")

    assert manifest["schemaVersion"] == 7
    assert manifest["releaseId"] == manifest["rootDigest"]["value"]
    assert manifest["fileCount"] == len(manifest["files"])
    assert {entry["path"] for entry in manifest["files"]} == {
        "jobs-details/00.json",
        "providers.json",
    }
    assert validate_release(staged) == []
    assert validate_artifacts(staged) == []

    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    atomic_write_channel_pointer(publication, manifest, channel="staging")

    assert (
        validate_publication(
            publication,
            channel="staging",
            policy=PromotionPolicy(max_snapshot_age=None),
            require_publication_graph=False,
        )
        == []
    )


def test_v7_verifier_rejects_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    release = _write_release(tmp_path / "release")
    manifest_path = release / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )

    errors = validate_release(release)

    assert any("manifest must use canonical JSON bytes" in error for error in errors)


def test_v7_publication_rejects_noncanonical_channel_pointer_bytes(
    tmp_path: Path,
) -> None:
    staged = _write_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    pointer_path = atomic_write_channel_pointer(
        publication, manifest, channel="staging"
    )
    pointer = _read_json(pointer_path)
    pointer_path.write_text(
        json.dumps(pointer, separators=(",", ":")), encoding="utf-8"
    )

    errors = validate_publication(
        publication,
        channel="staging",
        policy=PromotionPolicy(max_snapshot_age=None),
        require_publication_graph=False,
    )

    assert any(
        "channel pointer must use canonical JSON bytes" in error for error in errors
    )


def test_v7_verifier_rejects_bit_flip(tmp_path: Path) -> None:
    release = _write_release(tmp_path / "release")
    providers = release / "providers.json"
    providers.write_bytes(providers.read_bytes().replace(b"Acme", b"Bcme"))

    errors = validate_release(release)

    assert any("providers.json SHA-256 does not match" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing", "manifest path missing on disk"),
        ("extra", "unreferenced file exists on disk"),
        ("symlink", "must not contain symlink"),
    ],
)
def test_v7_verifier_rejects_disk_set_violations(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    release = _write_release(tmp_path / "release")
    if mutation == "missing":
        (release / "providers.json").unlink()
    elif mutation == "extra":
        _write_json(release / "extra.json", {})
    else:
        outside = tmp_path / "outside.json"
        _write_json(outside, {})
        (release / "escape.json").symlink_to(outside)

    assert any(expected in error for error in validate_release(release))


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../escape.json",
        "/absolute.json",
        "nested\\windows.json",
        "a/../b.json",
        "https:payload.json",
        "percent%2fescape.json",
        "unicode-☃.json",
        f"{'a' * 1025}.json",
    ],
)
def test_v7_verifier_rejects_unsafe_manifest_paths(
    tmp_path: Path, unsafe_path: str
) -> None:
    release = _write_release(tmp_path / "release")
    manifest = _read_json(release / "manifest.json")
    manifest["files"][0]["path"] = unsafe_path
    _write_json(release / "manifest.json", manifest, pretty=True)

    assert any("files[0].path" in error for error in validate_release(release))


def test_v7_verifier_rejects_duplicate_and_case_colliding_paths(tmp_path: Path) -> None:
    release = _write_release(tmp_path / "release")
    manifest = _read_json(release / "manifest.json")
    manifest["files"].append(dict(manifest["files"][0]))
    case_collision = dict(manifest["files"][0])
    case_collision["path"] = manifest["files"][0]["path"].upper()
    manifest["files"].append(case_collision)
    _write_json(release / "manifest.json", manifest, pretty=True)

    errors = validate_release(release)

    assert any("duplicate manifest path" in error for error in errors)
    assert any("case-colliding manifest paths" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("bytes", 0, "byte size"),
        ("sha256", "0" * 64, "SHA-256"),
        ("mediaType", "text/plain", "media type"),
        ("role", "wrong", "role"),
        ("count", 999, "count"),
    ],
)
def test_v7_verifier_rejects_wrong_file_metadata(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    release = _write_release(tmp_path / "release")
    manifest = _read_json(release / "manifest.json")
    manifest["files"][0][field] = value
    _write_json(release / "manifest.json", manifest, pretty=True)

    assert any(expected in error for error in validate_release(release))


def test_v7_verifier_rejects_wrong_root_digest(tmp_path: Path) -> None:
    release = _write_release(tmp_path / "release")
    manifest = _read_json(release / "manifest.json")
    manifest["releaseId"] = "0" * 64
    manifest["rootDigest"]["value"] = "0" * 64
    _write_json(release / "manifest.json", manifest, pretty=True)

    errors = validate_release(release)

    assert any("releaseId does not match" in error for error in errors)
    assert any("rootDigest does not match" in error for error in errors)


@pytest.mark.parametrize(
    ("container", "field"),
    [("source", "path"), ("generator", "entrypoint")],
)
def test_v7_verifier_rejects_unsafe_provenance_paths(
    tmp_path: Path, container: str, field: str
) -> None:
    release = _write_release(tmp_path / "release")
    manifest = _read_json(release / "manifest.json")
    manifest[container][field] = "/Users/operator/private.sqlite"
    _write_json(release / "manifest.json", manifest, pretty=True)

    errors = validate_release(release)

    assert any(f"{container} provenance is invalid" in error for error in errors)


def test_v7_verifier_rejects_deeply_nested_private_fields(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _write_json(
        release / "jobs-details" / "00.json",
        {"job-1": {"safe": [{"payloadSnapshots": [{"token": "private"}]}]}},
    )
    _write_json(release / "providers.json", {"rows": [], "count": 0})
    _write_manifest(release)

    errors = validate_release(release)

    assert any(
        "forbidden private field 'payloadSnapshots'" in error for error in errors
    )


def test_v7_verifier_rejects_special_files_without_reading_them(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO fixtures require POSIX mkfifo")
    release = _write_release(tmp_path / "release")
    providers = release / "providers.json"
    providers.unlink()
    os.mkfifo(providers)

    errors = validate_release(release)

    assert any("regular files only" in error for error in errors)


@pytest.mark.parametrize(
    "payload",
    [
        {"job-1": {"provider": {"apiKey": "do-not-publish"}}},
        {"job-1": {"url": "https://example.test/apply?access_token=do-not-publish"}},
        {"job-1": {"url": "HTTPS://example.test/apply?x-algolia-api-key=secret"}},
        {"job-1": {"url": "https://user:password@example.test/apply"}},
    ],
)
def test_v7_verifier_rejects_secret_like_fields_and_urls(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    release = tmp_path / "release"
    _write_json(release / "jobs-details" / "00.json", payload)
    _write_json(release / "providers.json", {"rows": [], "count": 0})
    _write_manifest(release)

    errors = validate_release(release)

    assert any(
        "secret-like" in error or "credential-bearing" in error for error in errors
    )


def test_v7_verifier_enforces_explicit_freshness_and_platform_policies(
    tmp_path: Path,
) -> None:
    release = _write_release(tmp_path / "release")
    now = datetime(2026, 2, 5, tzinfo=timezone.utc)
    policy = PromotionPolicy(
        max_snapshot_age=timedelta(hours=24), max_files=1, max_file_bytes=1
    )

    errors = validate_release(release, policy=policy, now=now)

    assert any("snapshot is stale by policy" in error for error in errors)
    assert any(
        "release contains" in error and "limit is 1" in error for error in errors
    )
    assert any("must be smaller than 1" in error for error in errors)
    assert MAX_RELEASE_FILES == 18_000
    assert MAX_RELEASE_FILE_BYTES == 24 * 1024 * 1024


def test_v7_publication_rejects_channel_manifest_mismatch(tmp_path: Path) -> None:
    staged = _write_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    pointer = atomic_write_channel_pointer(publication, manifest, channel="production")
    payload = _read_json(pointer)
    payload["snapshotAt"] = "2026-02-04T00:00:00.000000Z"
    _write_json(pointer, payload, pretty=True)

    assert any(
        "channel pointer snapshotAt does not match" in error
        for error in validate_publication(publication, channel="production")
    )


def test_v7_publication_rejects_incoherent_snapshot_age(tmp_path: Path) -> None:
    staged = _write_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    pointer = atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        promoted_at="2026-02-04T00:00:00Z",
    )
    payload = _read_json(pointer)
    payload["snapshotAgeSeconds"] = 1
    _write_json(pointer, payload, pretty=True)

    assert any(
        "snapshotAgeSeconds does not match" in error
        for error in validate_publication(
            publication,
            channel="production",
            policy=PromotionPolicy(max_snapshot_age=None),
            require_publication_graph=False,
        )
    )


def test_production_publication_requires_complete_governance_graph(
    tmp_path: Path,
) -> None:
    staged = _write_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        promoted_at="2026-02-04T00:00:00Z",
    )

    errors = validate_publication(
        publication,
        channel="production",
        now=datetime(2026, 2, 4, tzinfo=timezone.utc),
    )

    assert any("missing required search-manifest.json" in error for error in errors)
    assert any("missing required publication-policy.json" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("publication-false", "publicationAllowed must be true"),
        ("unapproved-status", "licenseStatus must be an allowed status"),
        ("missing-attribution", "requires non-empty sourceAttribution"),
        ("source-set", "source set does not match search-manifest facets.sources"),
        ("source-count", "sourceCount does not match sources length"),
        ("status-contract", "allowedLicenseStatuses does not match"),
        ("source-policy-digest", "does not match generator component"),
    ],
)
def test_publication_graph_rejects_semantically_tampered_rights_policy(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    governed = _write_governed_release(tmp_path / "governed")
    policy_path = governed / "publication-policy.json"
    policy = _read_json(policy_path)
    sources = policy["sources"]
    assert isinstance(sources, list)
    first = sources[0]
    assert isinstance(first, dict)
    if mutation == "publication-false":
        first["publicationAllowed"] = False
    elif mutation == "unapproved-status":
        first["licenseStatus"] = "needs_review"
    elif mutation == "missing-attribution":
        first["licenseStatus"] = "public_attribution_required"
        first["sourceAttribution"] = None
    elif mutation == "source-set":
        first["key"] = "substituted-source"
    elif mutation == "source-count":
        policy["sourceCount"] = 999
    elif mutation == "status-contract":
        allowed = policy["allowedLicenseStatuses"]
        assert isinstance(allowed, list)
        allowed.append("needs_review")
    else:
        source_policy = policy["sourcePolicy"]
        assert isinstance(source_policy, dict)
        source_policy["evidenceSha256"] = "b" * 64
    _write_json(policy_path, policy, pretty=True)
    _rewrite_manifest(governed)

    errors = validate_release(governed, require_publication_graph=True)

    assert any(expected in error for error in errors)


def test_production_publication_defaults_to_48h_and_requires_auditable_override(
    tmp_path: Path,
) -> None:
    staged = _write_governed_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        promoted_at="2026-02-06T00:00:00Z",
    )
    now = datetime(2026, 2, 6, tzinfo=timezone.utc)

    assert any(
        "snapshot is stale by policy" in error
        for error in validate_publication(publication, channel="production", now=now)
    )

    pointer = atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        degraded_reason=(
            "Provider outage incident OPS-2026-02-06; approved for bounded degraded "
            "publication."
        ),
        promoted_at="2026-02-06T00:00:00Z",
    )
    assert validate_publication(publication, channel="production", now=now) == []

    payload = _read_json(pointer)
    payload["degradedReason"] = "   "
    _write_json(pointer, payload, pretty=True)
    errors = validate_publication(publication, channel="production", now=now)
    assert any("degradedReason is invalid" in error for error in errors)
    assert any("snapshot is stale by policy" in error for error in errors)


def test_production_artifact_verifier_defaults_to_48h_and_honors_degraded_reason(
    tmp_path: Path,
) -> None:
    staged = _write_governed_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    promoted_at = datetime.now(timezone.utc).isoformat()
    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        promoted_at=promoted_at,
    )

    assert any(
        "snapshot is stale by policy" in error
        for error in validate_artifacts(publication, channel="production")
    )
    assert any(
        "snapshot is stale by policy" in error
        for error in validate_artifacts(
            publication,
            channel="production",
            policy=PromotionPolicy(max_snapshot_age=None),
        )
    )
    assert any(
        "snapshot is stale by policy" in error
        for error in validate_artifacts(
            publication,
            channel="production",
            policy=PromotionPolicy(max_snapshot_age=timedelta(days=9_999)),
        )
    )

    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        degraded_reason=(
            "Incident OPS-2026-02-03: upstream recovery remains in progress; "
            "maintainer approved degraded publication."
        ),
        promoted_at=promoted_at,
    )
    assert validate_artifacts(publication, channel="production") == []


@pytest.mark.parametrize("max_snapshot_age", [None, timedelta(days=9_999)])
def test_production_publication_validator_cannot_relax_48h_freshness(
    tmp_path: Path,
    max_snapshot_age: timedelta | None,
) -> None:
    staged = _write_governed_release(tmp_path / "staged")
    manifest = _read_json(staged / "manifest.json")
    publication = tmp_path / "publication"
    release = publication / "releases" / manifest["releaseId"]
    release.parent.mkdir(parents=True)
    staged.rename(release)
    promoted_at = datetime.now(timezone.utc).isoformat()
    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        promoted_at=promoted_at,
    )

    errors = validate_publication(
        publication,
        channel="production",
        policy=PromotionPolicy(max_snapshot_age=max_snapshot_age),
        now=datetime.now(timezone.utc),
    )

    assert any("snapshot is stale by policy" in error for error in errors)

    atomic_write_channel_pointer(
        publication,
        manifest,
        channel="production",
        degraded_reason=(
            "Incident OPS-2026-02-03: upstream recovery remains in progress; "
            "maintainer approved degraded publication."
        ),
        promoted_at=promoted_at,
    )
    assert (
        validate_publication(
            publication,
            channel="production",
            policy=PromotionPolicy(max_snapshot_age=max_snapshot_age),
            now=datetime.now(timezone.utc),
        )
        == []
    )


def _write_release(root: Path) -> Path:
    _write_json(
        root / "jobs-details" / "00.json",
        {"job-1": {"id": "job-1", "company": "Acme"}},
    )
    _write_json(root / "providers.json", {"rows": [["Acme"]], "count": 1})
    _write_manifest(root)
    return root


def _write_governed_release(root: Path) -> Path:
    snapshot_at = "2026-02-03T00:00:00.000000Z"
    snapshot_counts = {
        "sourceRows": 2,
        "providerRoutes": 1,
        "boards": 1,
        "jobs": 1,
        "openJobs": 1,
    }
    _write_json(
        root / "search-manifest.json",
        {
            "version": 6,
            "snapshotAt": snapshot_at,
            "facets": {"sources": ["official", "public-attributed"]},
            "counts": {"snapshot": snapshot_counts},
            "detailShards": {"tierCounts": {"T1": 0, "T2": 1}},
        },
        pretty=True,
    )
    _write_json(
        root / "publication-policy.json",
        {
            "schemaVersion": 1,
            "sourcePolicy": {
                "policyId": "fixture-source-policy",
                "reviewedAt": "2026-02-03",
                "moduleSha256": _DIGEST,
                "evidenceSha256": _DIGEST,
                "schemaSha256": _DIGEST,
                "corpusSha256": _DIGEST,
            },
            "allowedLicenseStatuses": [
                "official_public",
                "oss_attribution_required",
                "public_attribution_required",
            ],
            "attributionRequiredStatuses": [
                "oss_attribution_required",
                "public_attribution_required",
            ],
            "sourceCount": 2,
            "sources": [
                {
                    "key": "official",
                    "licenseStatus": "official_public",
                    "sourceAttribution": None,
                    "publicationAllowed": True,
                },
                {
                    "key": "public-attributed",
                    "licenseStatus": "public_attribution_required",
                    "sourceAttribution": "Public source fixture attribution.",
                    "publicationAllowed": True,
                    "sourceUrl": "https://example.test/public-source",
                },
            ],
            "quality": {
                "snapshotAt": snapshot_at,
                **snapshot_counts,
                "detailTiers": {"T1": 0, "T2": 1},
            },
        },
        pretty=True,
    )
    _write_json(root / "providers.json", {"rows": [["Acme"]], "count": 1})
    _write_manifest(root)
    return root


def _rewrite_manifest(root: Path) -> dict[str, object]:
    old = _read_json(root / "manifest.json")
    (root / "manifest.json").unlink()
    manifest = build_release_manifest(
        root,
        snapshot_at=str(old["snapshotAt"]),
        source=old["source"],
        generator=old["generator"],
    )
    write_release_manifest(root, manifest)
    return manifest


def _write_manifest(root: Path) -> dict[str, object]:
    manifest = build_release_manifest(
        root,
        snapshot_at="2026-02-03T00:00:00Z",
        source=_SOURCE,
        generator=_GENERATOR,
    )
    write_release_manifest(root, manifest)
    return manifest


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    else:
        content = json.dumps(value, separators=(",", ":")) + "\n"
    path.write_text(content, encoding="utf-8")
