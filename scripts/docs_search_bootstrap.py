"""Fail-closed planning and evidence for first-time public-data Workers.

Normal OpenOpps delivery uses ``wrangler versions upload`` so an upload cannot
change traffic. Cloudflare requires one ordinary deployment to create a Worker,
however. This module constrains that one-time exception to a digest-addressed,
read-only delivery candidate, proves the target name was absent immediately
before the command was rendered, and records the initial deployment as the
previous-good rollback identity for later version-only rollouts.

The module never executes Cloudflare or Wrangler. Live commands are rendered
only with an explicit flag, and credentials are neither accepted nor recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from urllib.parse import urlsplit

import docs_search_delivery as delivery
import docs_search_release as release

BOOTSTRAP_SCHEMA_VERSION = 1
CF_CLI_VERSION = "0.6.0"
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_INVENTORY_AGE_SECONDS = 300
CONFIG_ENVIRONMENTS = ("staging", "production")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_WORKER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPLOY_RECORD_KEYS = {
    "type",
    "version",
    "worker_name",
    "worker_tag",
    "version_id",
    "targets",
    "wrangler_environment",
    "worker_name_overridden",
    "timestamp",
}


class BootstrapError(ValueError):
    """Raised when a bootstrap input or observed remote state is unsafe."""


@dataclass(frozen=True)
class CandidateEvidence:
    """Identity of the frozen input that Wrangler is allowed to consume."""

    root: Path
    candidate_digest: str
    stage_digest: str
    current_release_id: str
    previous_release_id: str


@dataclass(frozen=True)
class RemoteIdentity:
    """Sanitized identity of one exact first deployment."""

    worker_id: str
    version_id: str
    deployment_id: str
    workers_dev_origin: str


def inventory_command(output_file: Path, *, account_id: str) -> dict[str, Any]:
    """Render the pinned, read-only Worker inventory command."""

    output_file = _require_absent_output(output_file, "inventory output")
    account_id = _require_account_id(account_id)
    return {
        "argv": [
            "npx",
            "--yes",
            f"cf@{CF_CLI_VERSION}",
            "workers",
            "scripts",
            "list",
        ],
        "env": {"CLOUDFLARE_ACCOUNT_ID": account_id},
        "stdoutFile": str(output_file),
        "mutation": False,
    }


def remote_readback_commands(
    environment: str, output_root: Path, *, account_id: str
) -> dict[str, Any]:
    """Render pinned read-only commands used after the one-time deployment."""

    environment = _require_environment(environment)
    account_id = _require_account_id(account_id)
    worker = f"openopps-data-{environment}"
    output_root = output_root.absolute()
    if output_root.is_symlink():
        raise BootstrapError("readback output directory must not be a symlink")
    paths = {
        "inventory": output_root / f"{environment}-workers-after.json",
        "deployments": output_root / f"{environment}-deployments.json",
        "versions": output_root / f"{environment}-versions.json",
    }
    for label, path in paths.items():
        _require_absent_output(path, f"{label} output")
    prefix = ["npx", "--yes", f"cf@{CF_CLI_VERSION}", "workers"]
    command_env = {"CLOUDFLARE_ACCOUNT_ID": account_id}
    return {
        "commands": [
            {
                "kind": "inventory",
                "argv": [
                    *prefix,
                    "beta",
                    "workers",
                    "get",
                    worker,
                ],
                "env": command_env,
                "stdoutFile": str(paths["inventory"]),
            },
            {
                "kind": "deployments",
                "argv": [
                    *prefix,
                    "deployments",
                    "list",
                    "--worker",
                    worker,
                ],
                "env": command_env,
                "stdoutFile": str(paths["deployments"]),
            },
            {
                "kind": "versions",
                "argv": [
                    *prefix,
                    "versions",
                    "list",
                    "--worker",
                    worker,
                    "--per-page",
                    "100",
                ],
                "env": command_env,
                "stdoutFile": str(paths["versions"]),
            },
        ],
        "mutation": False,
    }


def build_bootstrap_plan(
    *,
    config: Path,
    stage_root: Path,
    inventory_path: Path,
    deploy_output: Path,
    plan_path: Path,
    source_revision: str,
    account_id: str,
    live_command: bool = False,
) -> dict[str, Any]:
    """Write a candidate-bound bootstrap plan after proving target absence."""

    environment, config = _validate_config(config)
    worker = f"openopps-data-{environment}"
    inventory_bytes, inventory, inventory_mtime_ns = _read_recent_inventory(
        inventory_path
    )
    _require_worker_absent(inventory, worker)
    source_revision = _require_git_revision(source_revision)
    account_id = _require_account_id(account_id)
    deploy_output = _require_absent_output(deploy_output, "Wrangler output")
    plan_path = _require_absent_output(plan_path, "bootstrap plan")
    planned_at = datetime.now(timezone.utc)
    captured_at = _datetime_from_ns(inventory_mtime_ns)
    expires_at = captured_at + timedelta(seconds=MAX_INVENTORY_AGE_SECONDS)

    invocation = delivery.build_upload_invocation(
        config=config,
        output_file=deploy_output,
        stage_root=stage_root,
    )
    candidate = _candidate_evidence(
        invocation.upload_candidate_root,
        environment=environment,
        expected_candidate_digest=invocation.upload_candidate_digest,
        expected_stage_digest=invocation.stage_root_digest,
    )
    argv = [
        *_wrangler_prefix(),
        "deploy",
        "--config",
        str(candidate.root / delivery.CONFIG_FILE),
        "--strict",
        "--message",
        f"OpenOpps bootstrap candidate {candidate.candidate_digest}",
    ]
    if not live_command:
        argv.append("--dry-run")
    plan = {
        "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
        "phase": "bootstrap-planned",
        "liveCommand": live_command,
        "environment": environment,
        "workerName": worker,
        "accountId": account_id,
        "sourceRevision": source_revision,
        "plannedAt": _canonical_datetime(planned_at),
        "inventoryCapturedAt": _canonical_datetime(captured_at),
        "expiresAt": _canonical_datetime(expires_at),
        "inventoryBeforePath": str(inventory_path.absolute()),
        "inventoryBeforeSha256": _sha256(inventory_bytes),
        "inventoryBeforeMtimeNs": inventory_mtime_ns,
        "configPath": str(config),
        "candidateRoot": str(candidate.root),
        "candidateDigest": candidate.candidate_digest,
        "stageRootDigest": candidate.stage_digest,
        "currentReleaseId": candidate.current_release_id,
        "previousReleaseId": candidate.previous_release_id,
        "wranglerVersion": delivery.WRANGLER_VERSION,
        "cfCliVersion": CF_CLI_VERSION,
        "deployOutputPath": str(deploy_output),
        "argv": argv,
        "env": {
            "CLOUDFLARE_ACCOUNT_ID": account_id,
            "WRANGLER_OUTPUT_FILE_PATH": str(deploy_output),
        },
    }
    _validate_plan(plan)
    _atomic_write_json(plan_path, plan)
    return plan


def parse_deploy_output(output: str | bytes, *, expected_worker: str) -> dict[str, Any]:
    """Parse exactly one supported Wrangler ``deploy`` machine record."""

    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BootstrapError("Wrangler machine output is not UTF-8") from exc
    records: list[Any] = []

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise BootstrapError(
                    f"Wrangler machine output contains duplicate key {key!r}"
                )
            value[key] = item
        return value

    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line, object_pairs_hook=pairs_hook))
        except json.JSONDecodeError as exc:
            raise BootstrapError(
                f"Wrangler machine output line {line_number} is invalid JSON"
            ) from exc
    matches = [
        item
        for item in records
        if isinstance(item, dict) and item.get("type") == "deploy"
    ]
    if len(matches) != 1:
        raise BootstrapError(
            "Wrangler machine output must contain exactly one deploy record"
        )
    record = cast(dict[str, Any], matches[0])
    if set(record) != _DEPLOY_RECORD_KEYS:
        raise BootstrapError("Wrangler deploy record schema is invalid")
    if record.get("version") != 1 or record.get("worker_name") != expected_worker:
        raise BootstrapError("Wrangler deploy record identity is invalid")
    _require_uuid(record.get("version_id"), "Wrangler version_id")
    worker_tag = record.get("worker_tag")
    if worker_tag is not None and (
        not isinstance(worker_tag, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", worker_tag)
    ):
        raise BootstrapError("Wrangler deploy record worker_tag is invalid")
    if record.get("wrangler_environment") is not None:
        raise BootstrapError("Wrangler deploy must not select a named environment")
    if record.get("worker_name_overridden") is not False:
        raise BootstrapError("Wrangler must not override the configured Worker name")
    targets = record.get("targets")
    if (
        not isinstance(targets, list)
        or len(targets) != 1
        or not isinstance(targets[0], str)
    ):
        raise BootstrapError("Wrangler deploy must report exactly one target")
    _validate_workers_dev_origin(targets[0], expected_worker)
    timestamp = record.get("timestamp")
    if not isinstance(timestamp, str):
        raise BootstrapError("Wrangler deploy record timestamp is missing")
    record["timestamp"] = _canonical_timestamp(timestamp, "Wrangler timestamp")
    return record


def record_bootstrap(
    *,
    plan_path: Path,
    inventory_after_path: Path,
    deployments_path: Path,
    versions_path: Path,
    ledger_path: Path,
    recorded_at: str,
) -> dict[str, Any]:
    """Record a live bootstrap only after exact first-deployment readback."""

    plan_bytes, plan = _read_json_evidence(plan_path)
    if not isinstance(plan, dict):
        raise BootstrapError("bootstrap plan must be a JSON object")
    plan = cast(dict[str, Any], plan)
    _validate_plan(plan)
    if plan["liveCommand"] is not True or "--dry-run" in plan["argv"]:
        raise BootstrapError("a dry-run bootstrap plan cannot record a live deployment")

    before_bytes, before = _read_json_evidence(Path(plan["inventoryBeforePath"]))
    if _sha256(before_bytes) != plan["inventoryBeforeSha256"]:
        raise BootstrapError("pre-bootstrap Worker inventory changed after planning")
    if (
        Path(plan["inventoryBeforePath"]).stat().st_mtime_ns
        != plan["inventoryBeforeMtimeNs"]
    ):
        raise BootstrapError("pre-bootstrap Worker inventory metadata changed")
    _require_worker_absent(before, plan["workerName"])
    candidate = _candidate_evidence(
        Path(plan["candidateRoot"]),
        environment=plan["environment"],
        expected_candidate_digest=plan["candidateDigest"],
        expected_stage_digest=plan["stageRootDigest"],
    )
    if (
        candidate.current_release_id != plan["currentReleaseId"]
        or candidate.previous_release_id != plan["previousReleaseId"]
    ):
        raise BootstrapError("bootstrap candidate release identity changed")

    deploy_output_path = Path(plan["deployOutputPath"])
    deploy_bytes = _read_regular_bytes(deploy_output_path, "Wrangler output")
    deploy_output_mtime_ns = deploy_output_path.stat(follow_symlinks=False).st_mtime_ns
    inventory_mtime_ns = cast(int, plan["inventoryBeforeMtimeNs"])
    expiry_ns = inventory_mtime_ns + MAX_INVENTORY_AGE_SECONDS * 1_000_000_000
    if not inventory_mtime_ns <= deploy_output_mtime_ns <= expiry_ns:
        raise BootstrapError(
            "Wrangler output must be written within the absent-inventory window"
        )
    deploy_record = parse_deploy_output(
        deploy_bytes, expected_worker=plan["workerName"]
    )
    captured_at = _parse_timestamp(
        plan["inventoryCapturedAt"], "inventory capture timestamp"
    )
    expires_at = _parse_timestamp(plan["expiresAt"], "plan expiry timestamp")
    deploy_timestamp = _parse_timestamp(
        deploy_record["timestamp"], "Wrangler deploy timestamp"
    )
    recorded_timestamp = _parse_timestamp(recorded_at, "recordedAt")
    if not captured_at <= deploy_timestamp <= expires_at:
        raise BootstrapError(
            "Wrangler deploy timestamp is outside the absent-inventory window"
        )
    if not deploy_timestamp < recorded_timestamp <= expires_at:
        raise BootstrapError(
            "recordedAt must follow the deploy timestamp before plan expiry"
        )
    if recorded_timestamp > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise BootstrapError("recordedAt must not be in the future")
    after_bytes, after = _read_json_evidence(inventory_after_path)
    deployments_bytes, deployments = _read_json_evidence(deployments_path)
    versions_bytes, versions = _read_json_evidence(versions_path)
    remote = _exact_remote_identity(
        worker_name=plan["workerName"],
        expected_version_id=deploy_record["version_id"],
        expected_target=deploy_record["targets"][0],
        expected_candidate_digest=plan["candidateDigest"],
        inventory=after,
        deployments=deployments,
        versions=versions,
    )
    ledger_path = _require_absent_output(ledger_path, "bootstrap ledger")
    entry = {
        "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
        "phase": "bootstrapped",
        "recordedAt": _canonical_datetime(recorded_timestamp),
        "wranglerDeployTimestamp": deploy_record["timestamp"],
        "inventoryCapturedAt": plan["inventoryCapturedAt"],
        "planExpiresAt": plan["expiresAt"],
        "environment": plan["environment"],
        "workerName": plan["workerName"],
        "accountId": plan["accountId"],
        "workerId": remote.worker_id,
        "workerVersionId": remote.version_id,
        "workerDeploymentId": remote.deployment_id,
        "rollbackWorkerVersionId": remote.version_id,
        "workersDevOrigin": remote.workers_dev_origin,
        "sourceRevision": plan["sourceRevision"],
        "currentReleaseId": plan["currentReleaseId"],
        "previousReleaseId": plan["previousReleaseId"],
        "stageRootDigest": plan["stageRootDigest"],
        "candidateRoot": plan["candidateRoot"],
        "candidateDigest": plan["candidateDigest"],
        "planSha256": _sha256(plan_bytes),
        "inventoryBeforeSha256": plan["inventoryBeforeSha256"],
        "inventoryAfterSha256": _sha256(after_bytes),
        "deployOutputSha256": _sha256(deploy_bytes),
        "deploymentsOutputSha256": _sha256(deployments_bytes),
        "versionsOutputSha256": _sha256(versions_bytes),
        "wranglerVersion": delivery.WRANGLER_VERSION,
        "cfCliVersion": CF_CLI_VERSION,
    }
    _validate_ledger(entry)
    _atomic_write_json(ledger_path, entry)
    return entry


def reconcile_existing(
    *,
    ledger_path: Path,
    inventory_path: Path,
    deployments_path: Path,
    versions_path: Path,
) -> dict[str, Any]:
    """Accept an existing Worker only when it exactly matches its ledger."""

    _ledger_bytes, ledger = _read_json_evidence(ledger_path)
    if not isinstance(ledger, dict):
        raise BootstrapError("bootstrap ledger must be a JSON object")
    ledger = cast(dict[str, Any], ledger)
    _validate_ledger(ledger)
    candidate = _candidate_evidence(
        Path(ledger["candidateRoot"]),
        environment=ledger["environment"],
        expected_candidate_digest=ledger["candidateDigest"],
        expected_stage_digest=ledger["stageRootDigest"],
    )
    if (
        candidate.current_release_id != ledger["currentReleaseId"]
        or candidate.previous_release_id != ledger["previousReleaseId"]
    ):
        raise BootstrapError("existing Worker ledger release identity changed")
    inventory_bytes, inventory = _read_json_evidence(inventory_path)
    deployments_bytes, deployments = _read_json_evidence(deployments_path)
    versions_bytes, versions = _read_json_evidence(versions_path)
    remote = _exact_remote_identity(
        worker_name=ledger["workerName"],
        expected_version_id=ledger["workerVersionId"],
        expected_target=ledger["workersDevOrigin"],
        expected_candidate_digest=ledger["candidateDigest"],
        inventory=inventory,
        deployments=deployments,
        versions=versions,
    )
    if (
        remote.worker_id != ledger["workerId"]
        or remote.deployment_id != ledger["workerDeploymentId"]
        or remote.version_id != ledger["rollbackWorkerVersionId"]
    ):
        raise BootstrapError("existing Worker does not match bootstrap ledger identity")
    return {
        "ok": True,
        "phase": "bootstrap-reconciled",
        "environment": ledger["environment"],
        "workerName": ledger["workerName"],
        "accountId": ledger["accountId"],
        "workerVersionId": remote.version_id,
        "workerDeploymentId": remote.deployment_id,
        "rollbackWorkerVersionId": remote.version_id,
        "workersDevOrigin": remote.workers_dev_origin,
        "inventorySha256": _sha256(inventory_bytes),
        "deploymentsSha256": _sha256(deployments_bytes),
        "versionsSha256": _sha256(versions_bytes),
        "mutation": False,
    }


def _validate_config(config: Path) -> tuple[str, Path]:
    config = config.resolve()
    root = delivery.CONFIG_ROOT.resolve()
    try:
        relative = config.relative_to(root)
    except ValueError as exc:
        raise BootstrapError("config must be repository-owned") from exc
    if len(relative.parts) != 2 or relative.name != delivery.CONFIG_FILE:
        raise BootstrapError("config must be a staging or production wrangler.jsonc")
    environment = _require_environment(relative.parts[0])
    errors = delivery.validate_configs(root)
    if errors:
        raise BootstrapError("delivery config drift: " + "; ".join(errors))
    return environment, config


def _wrangler_prefix() -> list[str]:
    package = json.loads(
        (delivery.REPOSITORY_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    dependencies = package.get("devDependencies") if isinstance(package, dict) else None
    if (
        not isinstance(dependencies, dict)
        or dependencies.get("wrangler") != delivery.WRANGLER_VERSION
    ):
        raise BootstrapError(
            f"web/package.json must pin wrangler {delivery.WRANGLER_VERSION}"
        )
    return [
        "pnpm",
        "--dir",
        str((delivery.REPOSITORY_ROOT / "web").resolve()),
        "exec",
        "wrangler",
    ]


def _candidate_evidence(
    root: Path,
    *,
    environment: str,
    expected_candidate_digest: object,
    expected_stage_digest: object,
) -> CandidateEvidence:
    expected_candidate = _require_sha256(expected_candidate_digest, "candidate digest")
    expected_stage = _require_sha256(expected_stage_digest, "stage root digest")
    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise BootstrapError("bootstrap candidate must be a regular directory")
    if (
        root.name != expected_candidate
        or root.parent.name != _require_environment(environment)
        or root.parent.parent.name != "upload-candidates"
    ):
        raise BootstrapError("bootstrap candidate path is not digest-addressed")
    if {path.name for path in root.iterdir()} != {delivery.CONFIG_FILE, "assets"}:
        raise BootstrapError(
            "bootstrap candidate must contain exactly config and assets"
        )
    config = root / delivery.CONFIG_FILE
    canonical = delivery.CONFIG_ROOT / environment / delivery.CONFIG_FILE
    if (
        config.is_symlink()
        or not config.is_file()
        or config.read_bytes() != canonical.read_bytes()
    ):
        raise BootstrapError("bootstrap candidate config drifted")
    files, directories = _safe_tree(root)
    for path in [root, *directories, *files]:
        if path.stat(follow_symlinks=False).st_mode & (
            stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        ):
            raise BootstrapError("bootstrap candidate must be read-only")
    actual_candidate = _tree_digest(root)
    if actual_candidate != expected_candidate:
        raise BootstrapError("bootstrap candidate digest changed")
    assets = root / "assets"
    stage_errors = delivery.verify_stage(assets)
    if stage_errors:
        raise BootstrapError("bootstrap stage is invalid: " + "; ".join(stage_errors))
    actual_stage = _tree_digest(assets)
    if actual_stage != expected_stage:
        raise BootstrapError("bootstrap stage root digest changed")
    pointer = _read_json_object(assets / "channels" / "production.json")
    current = _require_sha256(pointer.get("releaseId"), "current release ID")
    previous = _require_sha256(pointer.get("priorReleaseId"), "previous release ID")
    if current == previous:
        raise BootstrapError("current and previous releases must be distinct")
    return CandidateEvidence(root, actual_candidate, actual_stage, current, previous)


def _safe_tree(root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in dirnames:
            path = parent / name
            if path.is_symlink():
                raise BootstrapError("bootstrap candidate must not contain symlinks")
            directories.append(path)
        for name in filenames:
            path = parent / name
            mode = path.stat(follow_symlinks=False).st_mode
            if path.is_symlink() or not stat.S_ISREG(mode):
                raise BootstrapError(
                    "bootstrap candidate must contain only regular files/directories"
                )
            if path.stat(follow_symlinks=False).st_nlink != 1:
                raise BootstrapError("bootstrap candidate must not contain hard links")
            files.append(path)
    return sorted(files), sorted(directories)


def _tree_digest(root: Path) -> str:
    files, _directories = _safe_tree(root)
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(content_digest)
    return digest.hexdigest()


def _require_worker_absent(inventory: object, worker_name: str) -> None:
    workers = _script_inventory(inventory)
    if worker_name in workers:
        raise BootstrapError(
            f"Worker {worker_name!r} already exists; bootstrap deploy is forbidden. "
            "Use reconcile-existing with its exact bootstrap ledger."
        )


def _script_inventory(inventory: object) -> dict[str, dict[str, Any]]:
    if not isinstance(inventory, list):
        raise BootstrapError("Worker inventory must be the cf scripts JSON array")
    result: dict[str, dict[str, Any]] = {}
    for item in inventory:
        if not isinstance(item, dict):
            raise BootstrapError("Worker inventory entries must be objects")
        name = item.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
            raise BootstrapError("Worker inventory contains an invalid name")
        if name in result:
            raise BootstrapError("Worker inventory contains a duplicate name")
        result[name] = cast(dict[str, Any], item)
    return result


def _exact_remote_identity(
    *,
    worker_name: str,
    expected_version_id: object,
    expected_target: object,
    expected_candidate_digest: object,
    inventory: object,
    deployments: object,
    versions: object,
) -> RemoteIdentity:
    expected_version = _require_uuid(expected_version_id, "expected version ID")
    candidate_digest = _require_sha256(
        expected_candidate_digest, "expected candidate digest"
    )
    if not isinstance(expected_target, str):
        raise BootstrapError("expected Worker target must be a string")
    target = _validate_workers_dev_origin(expected_target, worker_name)
    if not isinstance(inventory, dict) or inventory.get("name") != worker_name:
        raise BootstrapError("post-bootstrap Worker detail has the wrong identity")
    worker = cast(dict[str, Any], inventory)
    worker_id = worker.get("id")
    if not isinstance(worker_id, str) or not _WORKER_ID_RE.fullmatch(worker_id):
        raise BootstrapError("post-bootstrap Worker ID is invalid")
    if worker.get("tags") != [] or worker.get("logpush") is not False:
        raise BootstrapError("bootstrap Worker has unexpected tags or Logpush")
    if worker.get("tail_consumers") != []:
        raise BootstrapError("bootstrap Worker has unexpected tail consumers")
    references = worker.get("references")
    if not isinstance(references, dict) or any(
        not isinstance(value, list) or value for value in references.values()
    ):
        raise BootstrapError("bootstrap Worker has unexpected resource references")
    observability = worker.get("observability")
    if not isinstance(observability, dict) or observability.get("enabled") is not False:
        raise BootstrapError("bootstrap Worker observability must be disabled")
    for surface in ("logs", "traces"):
        nested = observability.get(surface)
        if not isinstance(nested, dict) or nested.get("enabled") is not False:
            raise BootstrapError(f"bootstrap Worker {surface} must be disabled")
    subdomain = worker.get("subdomain")
    if (
        not isinstance(subdomain, dict)
        or subdomain.get("enabled") is not True
        or subdomain.get("previews_enabled") is not False
        or subdomain.get("url") != target
    ):
        raise BootstrapError("bootstrap Worker subdomain state is not exact")

    if not isinstance(deployments, dict) or set(deployments) != {"deployments"}:
        raise BootstrapError("deployment readback schema is invalid")
    deployment_items = deployments.get("deployments")
    if not isinstance(deployment_items, list) or len(deployment_items) != 1:
        raise BootstrapError("bootstrap Worker must have exactly one deployment")
    deployment = deployment_items[0]
    if not isinstance(deployment, dict):
        raise BootstrapError("bootstrap deployment must be an object")
    deployment_id = _require_uuid(deployment.get("id"), "deployment ID")
    if (
        deployment.get("source") != "wrangler"
        or deployment.get("strategy") != "percentage"
    ):
        raise BootstrapError("bootstrap deployment source/strategy is invalid")
    traffic = deployment.get("versions")
    if (
        not isinstance(traffic, list)
        or len(traffic) != 1
        or not isinstance(traffic[0], dict)
        or traffic[0].get("version_id") != expected_version
        or traffic[0].get("percentage") != 100
    ):
        raise BootstrapError(
            "bootstrap deployment must serve one expected version at 100%"
        )

    if not isinstance(versions, dict) or set(versions) != {"items"}:
        raise BootstrapError("version readback schema is invalid")
    version_items = versions.get("items")
    if not isinstance(version_items, list) or len(version_items) != 1:
        raise BootstrapError("bootstrap Worker must have exactly one version")
    version = version_items[0]
    if (
        not isinstance(version, dict)
        or version.get("id") != expected_version
        or version.get("number") != 1
    ):
        raise BootstrapError("bootstrap version identity is invalid")
    metadata = version.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("source") != "wrangler":
        raise BootstrapError("bootstrap version source is invalid")
    annotations = version.get("annotations")
    if (
        not isinstance(annotations, dict)
        or annotations.get("workers/message")
        != f"OpenOpps bootstrap candidate {candidate_digest}"
        or annotations.get("workers/triggered_by") != "upload"
    ):
        raise BootstrapError("bootstrap version annotations do not bind the candidate")
    return RemoteIdentity(worker_id, expected_version, deployment_id, target)


def _validate_workers_dev_origin(value: str, worker_name: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise BootstrapError("Worker target is not a valid URL") from exc
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname.startswith(f"{worker_name}.")
        or not hostname.endswith(".workers.dev")
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BootstrapError("Worker target must be the exact workers.dev origin")
    return value.rstrip("/")


_PLAN_KEYS = {
    "schemaVersion",
    "phase",
    "liveCommand",
    "environment",
    "workerName",
    "accountId",
    "sourceRevision",
    "plannedAt",
    "inventoryCapturedAt",
    "expiresAt",
    "inventoryBeforePath",
    "inventoryBeforeSha256",
    "inventoryBeforeMtimeNs",
    "configPath",
    "candidateRoot",
    "candidateDigest",
    "stageRootDigest",
    "currentReleaseId",
    "previousReleaseId",
    "wranglerVersion",
    "cfCliVersion",
    "deployOutputPath",
    "argv",
    "env",
}


def _validate_plan(plan: Mapping[str, Any]) -> None:
    if set(plan) != _PLAN_KEYS or plan.get("schemaVersion") != BOOTSTRAP_SCHEMA_VERSION:
        raise BootstrapError("bootstrap plan schema is invalid")
    environment = _require_environment(plan.get("environment"))
    worker = f"openopps-data-{environment}"
    if plan.get("phase") != "bootstrap-planned" or plan.get("workerName") != worker:
        raise BootstrapError("bootstrap plan phase/Worker is invalid")
    _require_account_id(plan.get("accountId"))
    if not isinstance(plan.get("liveCommand"), bool):
        raise BootstrapError("bootstrap plan liveCommand must be boolean")
    for key in (
        "inventoryBeforePath",
        "configPath",
        "candidateRoot",
        "deployOutputPath",
    ):
        value = plan.get(key)
        if (
            not isinstance(value, str)
            or "\x00" in value
            or not Path(value).is_absolute()
        ):
            raise BootstrapError(f"bootstrap plan {key} must be an absolute path")
    _require_git_revision(plan.get("sourceRevision"))
    for key in (
        "inventoryBeforeSha256",
        "candidateDigest",
        "stageRootDigest",
        "currentReleaseId",
        "previousReleaseId",
    ):
        _require_sha256(plan.get(key), key)
    inventory_mtime_ns = plan.get("inventoryBeforeMtimeNs")
    if not isinstance(inventory_mtime_ns, int) or inventory_mtime_ns <= 0:
        raise BootstrapError("bootstrap plan inventory mtime is invalid")
    planned_at = _parse_timestamp(plan.get("plannedAt"), "plan timestamp")
    captured_at = _parse_timestamp(
        plan.get("inventoryCapturedAt"), "inventory capture timestamp"
    )
    expires_at = _parse_timestamp(plan.get("expiresAt"), "plan expiry timestamp")
    expected_captured_at = _datetime_from_ns(inventory_mtime_ns)
    if captured_at != expected_captured_at:
        raise BootstrapError("bootstrap plan inventory timestamp does not match mtime")
    if expires_at - captured_at != timedelta(seconds=MAX_INVENTORY_AGE_SECONDS):
        raise BootstrapError("bootstrap plan expiry window is invalid")
    if captured_at > planned_at + timedelta(seconds=5) or planned_at > expires_at:
        raise BootstrapError("bootstrap plan timing is invalid")
    if datetime.now(timezone.utc) > expires_at:
        raise BootstrapError("bootstrap plan has expired; recapture inventory")
    if plan["currentReleaseId"] == plan["previousReleaseId"]:
        raise BootstrapError("bootstrap plan releases must be distinct")
    expected_config = (
        delivery.CONFIG_ROOT / environment / delivery.CONFIG_FILE
    ).resolve()
    if Path(cast(str, plan["configPath"])).resolve() != expected_config:
        raise BootstrapError("bootstrap plan config path is not repository-owned")
    if plan.get("wranglerVersion") != delivery.WRANGLER_VERSION:
        raise BootstrapError("bootstrap plan Wrangler version drifted")
    if plan.get("cfCliVersion") != CF_CLI_VERSION:
        raise BootstrapError("bootstrap plan cf version drifted")
    argv = plan.get("argv")
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        raise BootstrapError("bootstrap plan argv is invalid")
    expected_prefix = [*_wrangler_prefix(), "deploy", "--config"]
    if argv[: len(expected_prefix)] != expected_prefix:
        raise BootstrapError("bootstrap plan does not use pinned Wrangler deploy")
    candidate_config = str(
        Path(cast(str, plan["candidateRoot"])) / delivery.CONFIG_FILE
    )
    if argv[len(expected_prefix)] != candidate_config:
        raise BootstrapError("bootstrap plan does not consume the frozen candidate")
    expected_tail = [
        "--strict",
        "--message",
        f"OpenOpps bootstrap candidate {plan['candidateDigest']}",
    ]
    if plan["liveCommand"]:
        if argv[-3:] != expected_tail or "--dry-run" in argv:
            raise BootstrapError("live bootstrap argv is invalid")
    elif argv[-4:] != [*expected_tail, "--dry-run"]:
        raise BootstrapError("dry-run bootstrap argv is invalid")
    expected_env = {
        "CLOUDFLARE_ACCOUNT_ID": plan.get("accountId"),
        "WRANGLER_OUTPUT_FILE_PATH": plan.get("deployOutputPath"),
    }
    if plan.get("env") != expected_env:
        raise BootstrapError("bootstrap plan environment is invalid")


_LEDGER_KEYS = {
    "schemaVersion",
    "phase",
    "recordedAt",
    "wranglerDeployTimestamp",
    "inventoryCapturedAt",
    "planExpiresAt",
    "environment",
    "workerName",
    "accountId",
    "workerId",
    "workerVersionId",
    "workerDeploymentId",
    "rollbackWorkerVersionId",
    "workersDevOrigin",
    "sourceRevision",
    "currentReleaseId",
    "previousReleaseId",
    "stageRootDigest",
    "candidateRoot",
    "candidateDigest",
    "planSha256",
    "inventoryBeforeSha256",
    "inventoryAfterSha256",
    "deployOutputSha256",
    "deploymentsOutputSha256",
    "versionsOutputSha256",
    "wranglerVersion",
    "cfCliVersion",
}


def _validate_ledger(ledger: Mapping[str, Any]) -> None:
    if (
        set(ledger) != _LEDGER_KEYS
        or ledger.get("schemaVersion") != BOOTSTRAP_SCHEMA_VERSION
    ):
        raise BootstrapError("bootstrap ledger schema is invalid")
    environment = _require_environment(ledger.get("environment"))
    worker = f"openopps-data-{environment}"
    if ledger.get("phase") != "bootstrapped" or ledger.get("workerName") != worker:
        raise BootstrapError("bootstrap ledger phase/Worker is invalid")
    _require_account_id(ledger.get("accountId"))
    recorded_at = ledger.get("recordedAt")
    if not isinstance(recorded_at, str):
        raise BootstrapError("bootstrap ledger recordedAt must be a UTC timestamp")
    recorded_timestamp = _parse_timestamp(recorded_at, "recordedAt")
    deploy_timestamp = ledger.get("wranglerDeployTimestamp")
    if not isinstance(deploy_timestamp, str):
        raise BootstrapError("bootstrap ledger Wrangler timestamp is invalid")
    deploy_time = _parse_timestamp(deploy_timestamp, "Wrangler deploy timestamp")
    captured_time = _parse_timestamp(
        ledger.get("inventoryCapturedAt"), "inventory capture timestamp"
    )
    expires_time = _parse_timestamp(
        ledger.get("planExpiresAt"), "plan expiry timestamp"
    )
    if not captured_time <= deploy_time < recorded_timestamp <= expires_time:
        raise BootstrapError("bootstrap ledger timestamp order is invalid")
    candidate_root = ledger.get("candidateRoot")
    if (
        not isinstance(candidate_root, str)
        or "\x00" in candidate_root
        or not Path(candidate_root).is_absolute()
    ):
        raise BootstrapError("bootstrap ledger candidateRoot must be an absolute path")
    worker_id = ledger.get("workerId")
    if not isinstance(worker_id, str) or not _WORKER_ID_RE.fullmatch(worker_id):
        raise BootstrapError("bootstrap ledger Worker ID is invalid")
    version = _require_uuid(ledger.get("workerVersionId"), "Worker version ID")
    _require_uuid(ledger.get("workerDeploymentId"), "Worker deployment ID")
    if ledger.get("rollbackWorkerVersionId") != version:
        raise BootstrapError("bootstrap rollback identity must be the initial version")
    target = ledger.get("workersDevOrigin")
    if not isinstance(target, str):
        raise BootstrapError("bootstrap ledger origin is invalid")
    _validate_workers_dev_origin(target, worker)
    _require_git_revision(ledger.get("sourceRevision"))
    for key in (
        "currentReleaseId",
        "previousReleaseId",
        "stageRootDigest",
        "candidateDigest",
        "planSha256",
        "inventoryBeforeSha256",
        "inventoryAfterSha256",
        "deployOutputSha256",
        "deploymentsOutputSha256",
        "versionsOutputSha256",
    ):
        _require_sha256(ledger.get(key), key)
    if ledger.get("currentReleaseId") == ledger.get("previousReleaseId"):
        raise BootstrapError("bootstrap ledger releases must be distinct")
    if ledger.get("wranglerVersion") != delivery.WRANGLER_VERSION:
        raise BootstrapError("bootstrap ledger Wrangler version drifted")
    if ledger.get("cfCliVersion") != CF_CLI_VERSION:
        raise BootstrapError("bootstrap ledger cf version drifted")


def _require_environment(value: object) -> str:
    if not isinstance(value, str) or value not in CONFIG_ENVIRONMENTS:
        raise BootstrapError(f"environment must be one of {CONFIG_ENVIRONMENTS!r}")
    return value


def _require_uuid(value: object, label: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise BootstrapError(f"{label} must be a lowercase UUID")
    return value


def _require_account_id(value: object) -> str:
    if not isinstance(value, str) or not _ACCOUNT_ID_RE.fullmatch(value):
        raise BootstrapError(
            "Cloudflare account ID must be 32 lowercase hex characters"
        )
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise BootstrapError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_git_revision(value: object) -> str:
    if not isinstance(value, str) or not _GIT_REVISION_RE.fullmatch(value):
        raise BootstrapError("source revision must be a lowercase 40-character Git SHA")
    return value


def _canonical_datetime(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _datetime_from_ns(value: int) -> datetime:
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
        microsecond=nanoseconds // 1_000
    )


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise BootstrapError(f"{label} must be a canonical UTC timestamp")
    try:
        canonical = release.canonical_utc_timestamp(value)
    except ValueError as exc:
        raise BootstrapError(f"{label} must be a canonical UTC timestamp") from exc
    return datetime.fromisoformat(canonical.replace("Z", "+00:00"))


def _canonical_timestamp(value: object, label: str) -> str:
    return _canonical_datetime(_parse_timestamp(value, label))


def _require_absent_output(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink():
        raise BootstrapError(f"{label} must not be a symlink")
    if any(ancestor.is_symlink() for ancestor in path.parents):
        raise BootstrapError(f"{label} ancestor must not be a symlink")
    if path.exists():
        raise BootstrapError(f"{label} must be absent")
    return path


def _read_regular_bytes(path: Path, label: str) -> bytes:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise BootstrapError(f"{label} must be a regular file")
    size = path.stat().st_size
    if size > MAX_EVIDENCE_BYTES:
        raise BootstrapError(f"{label} exceeds the evidence size limit")
    return path.read_bytes()


def _read_json_evidence(path: Path) -> tuple[bytes, Any]:
    content = _read_regular_bytes(path, "JSON evidence")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise BootstrapError(f"JSON evidence contains duplicate key {key!r}")
            value[key] = item
        return value

    try:
        return content, json.loads(content, object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("JSON evidence is invalid") from exc


def _read_recent_inventory(path: Path) -> tuple[bytes, Any, int]:
    content, value = _read_json_evidence(path)
    mtime_ns = path.absolute().stat().st_mtime_ns
    age = datetime.now(timezone.utc).timestamp() - (mtime_ns / 1_000_000_000)
    if age < -5 or age > MAX_INVENTORY_AGE_SECONDS:
        raise BootstrapError(
            "Worker inventory must have been captured in the last 300 seconds"
        )
    return content, value, mtime_ns


def _read_json_object(path: Path) -> dict[str, Any]:
    _content, value = _read_json_evidence(path)
    if not isinstance(value, dict):
        raise BootstrapError(f"JSON evidence must be an object: {path}")
    return cast(dict[str, Any], value)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _atomic_write_json(path: Path, value: object) -> None:
    """Publish one evidence file without replacing a concurrent writer."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise BootstrapError(f"bootstrap output already exists: {path}") from exc
        except OSError as exc:
            raise BootstrapError(
                f"unable to publish bootstrap output without replacement: {path}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory-command")
    inventory.add_argument("output_file", type=Path)
    inventory.add_argument("--account-id", required=True)

    readback = subparsers.add_parser("readback-commands")
    readback.add_argument("environment", choices=CONFIG_ENVIRONMENTS)
    readback.add_argument("output_root", type=Path)
    readback.add_argument("--account-id", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("config", type=Path)
    plan.add_argument("stage_root", type=Path)
    plan.add_argument("inventory", type=Path)
    plan.add_argument("deploy_output", type=Path)
    plan.add_argument("plan_output", type=Path)
    plan.add_argument("--source-revision", required=True)
    plan.add_argument("--account-id", required=True)
    plan.add_argument("--live-command", action="store_true")

    record = subparsers.add_parser("record")
    record.add_argument("plan", type=Path)
    record.add_argument("inventory_after", type=Path)
    record.add_argument("deployments", type=Path)
    record.add_argument("versions", type=Path)
    record.add_argument("ledger", type=Path)
    record.add_argument("--recorded-at", required=True)

    reconcile = subparsers.add_parser("reconcile-existing")
    reconcile.add_argument("ledger", type=Path)
    reconcile.add_argument("inventory", type=Path)
    reconcile.add_argument("deployments", type=Path)
    reconcile.add_argument("versions", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic local planning/evidence operations only."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory-command":
            result = inventory_command(args.output_file, account_id=args.account_id)
        elif args.command == "readback-commands":
            result = remote_readback_commands(
                args.environment, args.output_root, account_id=args.account_id
            )
        elif args.command == "plan":
            result = build_bootstrap_plan(
                config=args.config,
                stage_root=args.stage_root,
                inventory_path=args.inventory,
                deploy_output=args.deploy_output,
                plan_path=args.plan_output,
                source_revision=args.source_revision,
                account_id=args.account_id,
                live_command=args.live_command,
            )
        elif args.command == "record":
            result = record_bootstrap(
                plan_path=args.plan,
                inventory_after_path=args.inventory_after,
                deployments_path=args.deployments,
                versions_path=args.versions,
                ledger_path=args.ledger,
                recorded_at=args.recorded_at,
            )
        else:
            result = reconcile_existing(
                ledger_path=args.ledger,
                inventory_path=args.inventory,
                deployments_path=args.deployments,
                versions_path=args.versions,
            )
    except (BootstrapError, delivery.DeliveryError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
