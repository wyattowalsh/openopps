from __future__ import annotations

import json
import importlib.util
import subprocess
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "verify_docs_search_artifacts.py"
_SPEC = importlib.util.spec_from_file_location("verify_docs_search_artifacts", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate_artifacts = _MODULE.validate_artifacts


def test_verifier_accepts_complete_manifest_and_detail_shards(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)

    assert validate_artifacts(root) == []


def test_verifier_rejects_missing_manifest_detail_shard(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)
    (root / "jobs-details" / "01.json").unlink()

    errors = validate_artifacts(root)

    assert any("manifest path missing on disk: jobs-details/01.json" in error for error in errors)
    assert any("detail shard bucket names do not match manifest" in error for error in errors)


def test_verifier_rejects_extra_detail_shard(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)
    write_json(root / "jobs-details" / "02.json", {})

    errors = validate_artifacts(root)

    assert any("detail shard exists but is not in manifest: jobs-details/02.json" in error for error in errors)


def test_verifier_rejects_forbidden_detail_keys(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)
    shard_path = root / "jobs-details" / "00.json"
    payload = json.loads(shard_path.read_text(encoding="utf-8"))
    payload["job-a"]["descriptionHtml"] = "<p>secret</p>"
    write_json(shard_path, payload)

    errors = validate_artifacts(root)

    assert any(
        "must not include 'descriptionHtml'" in error and "job-a" in error
        for error in errors
    )


def test_verifier_rejects_payload_snapshots_in_detail_shards(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)
    shard_path = root / "jobs-details" / "01.json"
    payload = json.loads(shard_path.read_text(encoding="utf-8"))
    payload["job-b"]["payloadSnapshots"] = [{"kind": "listing"}]
    write_json(shard_path, payload)

    errors = validate_artifacts(root)

    assert any(
        "must not include 'payloadSnapshots'" in error and "job-b" in error
        for error in errors
    )


def test_verifier_rejects_bucket_count_mismatch(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["detailShards"]["bucketCount"] = 3
    write_json(manifest_path, manifest)

    errors = validate_artifacts(root)

    assert any("detailShards.bucketCount 3 does not match 2 buckets" in error for error in errors)


def test_verifier_rejects_untracked_generated_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    root = write_artifacts(repo)
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "add", "web/public/data/openopps-search/manifest.json"], cwd=repo, check=True)

    errors = validate_artifacts(root, require_git_tracked=True)

    assert any("generated artifact is not git-tracked" in error for error in errors)
    assert any("generated artifact is untracked" in error for error in errors)


def write_artifacts(base: Path) -> Path:
    root = base / "web" / "public" / "data" / "openopps-search"
    write_json(
        root / "manifest.json",
        {
            "version": 6,
            "detailShards": {
                "root": "/data/openopps-search/jobs-details",
                "format": "bucket-map",
                "bucketCount": 2,
                "count": 2,
                "idIndexFile": "jobs-detail-ids.json",
                "indexableIdIndexFile": "jobs-indexable-ids.json",
                "indexableCount": 1,
                "buckets": {
                    "00": {"path": "/data/openopps-search/jobs-details/00.json", "count": 1},
                    "01": {"path": "/data/openopps-search/jobs-details/01.json", "count": 1},
                },
            },
            "entities": {
                "jobs": {
                    "file": "jobs/latest.json",
                    "columns": [],
                    "count": 0,
                    "chunks": [
                        {"index": 0, "file": "jobs/chunks/0000.json", "path": "/data/openopps-search/jobs/chunks/0000.json", "count": 0}
                    ],
                },
                "boards": {"file": "boards.json", "columns": [], "count": 0},
                "providers": {"file": "providers.json", "columns": [], "count": 0},
            },
            "lineageAggregate": {"file": "lineage-aggregate.json"},
        },
    )
    write_json(root / "jobs-details" / "00.json", {"job-a": {"id": "job-a"}})
    write_json(root / "jobs-details" / "01.json", {"job-b": {"id": "job-b"}})
    write_json(root / "jobs-detail-ids.json", {"count": 2, "ids": ["job-a", "job-b"]})
    write_json(root / "jobs-indexable-ids.json", {"count": 1, "ids": ["job-a"]})
    write_json(root / "jobs" / "latest.json", {})
    write_json(root / "jobs" / "chunks" / "0000.json", {})
    write_json(root / "boards.json", {})
    write_json(root / "providers.json", {})
    write_json(root / "lineage-aggregate.json", {})
    return root


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
