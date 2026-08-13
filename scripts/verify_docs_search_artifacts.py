"""Validate committed docs search artifacts against their manifest."""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from scripts.docs_search_release import (
        PromotionPolicy,
        RELEASE_SCHEMA_VERSION,
        validate_publication,
        validate_release,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from docs_search_release import (  # type: ignore[no-redef]
        PromotionPolicy,
        RELEASE_SCHEMA_VERSION,
        validate_publication,
        validate_release,
    )

FORBIDDEN_DETAIL_KEYS = frozenset({"payloadSnapshots", "descriptionHtml"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("web/public/data/openopps-search"),
        help="Docs search artifact root.",
    )
    parser.add_argument(
        "--require-git-tracked",
        action="store_true",
        help="Require generated artifact files to be tracked by git.",
    )
    parser.add_argument(
        "--channel",
        help="Treat --root as a v7 publication root and verify this channel.",
    )
    parser.add_argument(
        "--max-snapshot-age-hours",
        type=float,
        help="Reject a v7 release when snapshot age exceeds this promotion limit.",
    )
    args = parser.parse_args(argv)
    if args.max_snapshot_age_hours is not None and args.max_snapshot_age_hours <= 0:
        parser.error("--max-snapshot-age-hours must be greater than zero")
    policy = (
        PromotionPolicy(max_snapshot_age=timedelta(hours=args.max_snapshot_age_hours))
        if args.max_snapshot_age_hours is not None
        else None
    )
    errors = validate_artifacts(
        args.root,
        require_git_tracked=args.require_git_tracked,
        policy=policy,
        channel=args.channel,
    )
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"docs search artifacts ok: {args.root}")
    return 0


def validate_artifacts(
    root: Path,
    *,
    require_git_tracked: bool = False,
    policy: PromotionPolicy | None = None,
    channel: str | None = None,
) -> list[str]:
    if channel is not None:
        production = channel == "production"
        if production:
            maximum_age = timedelta(hours=48)
            requested_age = policy.max_snapshot_age if policy is not None else None
            if requested_age is None or requested_age > maximum_age:
                policy = PromotionPolicy(
                    max_snapshot_age=maximum_age,
                    max_files=(policy or PromotionPolicy()).max_files,
                    max_file_bytes=(policy or PromotionPolicy()).max_file_bytes,
                )
        errors = validate_publication(
            root,
            channel=channel,
            policy=policy,
            require_publication_graph=production,
        )
        if require_git_tracked and not errors:
            root = root.resolve()
            errors.extend(_git_tracking_errors(root, _artifact_files(root)))
        return errors
    root = root.resolve()
    errors: list[str] = []
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return [f"missing manifest: {manifest_path}"]
    manifest = _read_json(manifest_path)
    if manifest.get("schemaVersion") == RELEASE_SCHEMA_VERSION:
        errors = validate_release(root, policy=policy)
        if require_git_tracked and not errors:
            errors.extend(_git_tracking_errors(root, _artifact_files(root)))
        return errors
    detail_shards = manifest.get("detailShards")
    if not isinstance(detail_shards, dict):
        return ["manifest is missing detailShards"]
    buckets = detail_shards.get("buckets")
    if not isinstance(buckets, dict):
        errors.append("manifest detailShards.buckets must be an object")
        buckets = {}
    bucket_count = detail_shards.get("bucketCount")
    if bucket_count != len(buckets):
        errors.append(
            f"detailShards.bucketCount {bucket_count!r} does not match {len(buckets)} buckets"
        )

    manifest_files = _manifest_files(manifest)
    disk_files = _artifact_files(root)
    missing = sorted(manifest_files - disk_files)
    extra = sorted(
        path
        for path in disk_files - manifest_files
        if path.parts[:1] == ("jobs-details",)
    )
    errors.extend(f"manifest path missing on disk: {path.as_posix()}" for path in missing)
    errors.extend(f"detail shard exists but is not in manifest: {path.as_posix()}" for path in extra)

    detail_root = root / "jobs-details"
    disk_bucket_names = {path.stem for path in detail_root.glob("*.json")}
    manifest_bucket_names = set(buckets)
    if disk_bucket_names != manifest_bucket_names:
        errors.append(
            "detail shard bucket names do not match manifest "
            f"(disk={len(disk_bucket_names)}, manifest={len(manifest_bucket_names)})"
        )
    for bucket, details in sorted(buckets.items()):
        if not isinstance(details, dict):
            errors.append(f"detail shard bucket {bucket} metadata must be an object")
            continue
        path = _public_path_to_relative(details.get("path"))
        if path != Path("jobs-details") / f"{bucket}.json":
            errors.append(f"detail shard bucket {bucket} has unexpected path {details.get('path')!r}")
            continue
        file_path = root / path
        if file_path.is_file():
            try:
                payload = _read_json(file_path)
            except json.JSONDecodeError as exc:
                errors.append(f"detail shard {path.as_posix()} is invalid JSON: {exc}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"detail shard {path.as_posix()} must be an object")
                continue
            if len(payload) != details.get("count"):
                errors.append(
                    f"detail shard {path.as_posix()} count {len(payload)} "
                    f"does not match manifest {details.get('count')!r}"
                )
            errors.extend(_forbidden_detail_key_errors(path, payload))

    detail_ids_file = detail_shards.get("idIndexFile")
    if isinstance(detail_ids_file, str):
        _validate_id_index_count(
            root,
            Path(detail_ids_file),
            detail_shards.get("count"),
            "detail id index",
            errors,
        )
    indexable_ids_file = detail_shards.get("indexableIdIndexFile")
    if isinstance(indexable_ids_file, str):
        _validate_id_index_count(
            root,
            Path(indexable_ids_file),
            detail_shards.get("indexableCount"),
            "indexable id index",
            errors,
        )

    if require_git_tracked:
        errors.extend(_git_tracking_errors(root, disk_files))
    return errors


def _manifest_files(manifest: dict[str, Any]) -> set[Path]:
    files: set[Path] = {Path("manifest.json")}
    detail_shards = manifest.get("detailShards")
    if isinstance(detail_shards, dict):
        for key in ("idIndexFile", "indexableIdIndexFile"):
            value = detail_shards.get(key)
            if isinstance(value, str):
                files.add(Path(value))
        buckets = detail_shards.get("buckets")
        if isinstance(buckets, dict):
            for details in buckets.values():
                if isinstance(details, dict):
                    relative_path = _public_path_to_relative(details.get("path"))
                    if relative_path is not None:
                        files.add(relative_path)
    entities = manifest.get("entities")
    if isinstance(entities, dict):
        for details in entities.values():
            if not isinstance(details, dict):
                continue
            file_value = details.get("file")
            if isinstance(file_value, str):
                files.add(Path(file_value))
            chunks = details.get("chunks")
            if isinstance(chunks, list):
                for chunk in chunks:
                    if isinstance(chunk, dict) and isinstance(chunk.get("file"), str):
                        files.add(Path(chunk["file"]))
    lineage = manifest.get("lineageAggregate")
    if isinstance(lineage, dict) and isinstance(lineage.get("file"), str):
        files.add(Path(lineage["file"]))
    return files


def _validate_id_index_count(
    root: Path,
    relative_path: Path,
    expected: object,
    label: str,
    errors: list[str],
) -> None:
    path = root / relative_path
    if not path.is_file():
        errors.append(f"{label} missing: {relative_path.as_posix()}")
        return
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("ids"), list):
        errors.append(f"{label} must contain an ids array: {relative_path.as_posix()}")
        return
    if payload.get("count") != len(payload["ids"]):
        errors.append(f"{label} count does not match ids length: {relative_path.as_posix()}")
    if expected is not None and payload.get("count") != expected:
        errors.append(
            f"{label} count {payload.get('count')!r} does not match manifest {expected!r}"
        )


def _git_tracking_errors(root: Path, disk_files: set[Path]) -> list[str]:
    repo_root = _git_repo_root(root)
    if repo_root is None:
        return [f"{root} is not inside a git worktree"]
    root_relative = root.relative_to(repo_root)
    tracked = {
        Path(path)
        for path in _git_lines(repo_root, ["git", "ls-files", "--", root_relative.as_posix()])
    }
    status_lines = _git_lines(
        repo_root,
        ["git", "status", "--porcelain", "--", root_relative.as_posix()],
    )
    untracked = [
        line[3:]
        for line in status_lines
        if line.startswith("?? ") and line[3:]
    ]
    errors = [
        f"generated artifact is not git-tracked: {path.as_posix()}"
        for path in sorted(disk_files)
        if root_relative / path not in tracked
    ]
    errors.extend(f"generated artifact is untracked: {path}" for path in sorted(untracked))
    return errors


def _git_repo_root(path: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    return Path(completed.stdout.strip()).resolve()


def _git_lines(cwd: Path, command: list[str]) -> list[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _public_path_to_relative(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    prefix = "/data/openopps-search/"
    if value.startswith(prefix):
        return Path(value.removeprefix(prefix))
    return Path(value.lstrip("/"))


def _artifact_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _forbidden_detail_key_errors(
    shard_path: Path, payload: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    for job_id, detail in payload.items():
        if not isinstance(detail, dict):
            continue
        for key in FORBIDDEN_DETAIL_KEYS:
            if key in detail:
                errors.append(
                    f"detail shard {shard_path.as_posix()} job {job_id} "
                    f"must not include {key!r}"
                )
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
