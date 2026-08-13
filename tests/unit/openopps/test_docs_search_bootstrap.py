from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
bootstrap = _load_script("docs_search_bootstrap", "docs_search_bootstrap.py")

_VERSION = "095f00a7-23a7-43b7-a227-e4c97cab5f22"
_DEPLOYMENT = "1a88955c-2fbd-4a72-9d9b-3ba1e59842f2"
_SOURCE_REVISION = "0123456789abcdef0123456789abcdef01234567"
_WORKER_ID = "a" * 32
_ACCOUNT_ID = "c" * 32
_DIGEST = "b" * 64
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
            "path": "src/openopps/providers/sources/data/source_policy_evidence.json",
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


@pytest.fixture(autouse=True)
def _isolate_delivery_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delivery, "DELIVERY_ROOT", tmp_path / "owned-delivery")


def test_read_only_inventory_commands_are_pinned_and_never_execute(
    tmp_path: Path,
) -> None:
    inventory = bootstrap.inventory_command(
        tmp_path / "before.json", account_id=_ACCOUNT_ID
    )
    readback = bootstrap.remote_readback_commands(
        "staging", tmp_path / "after", account_id=_ACCOUNT_ID
    )

    assert inventory["argv"][:3] == ["npx", "--yes", "cf@0.6.0"]
    assert inventory["argv"][-3:] == ["workers", "scripts", "list"]
    assert inventory["env"] == {"CLOUDFLARE_ACCOUNT_ID": _ACCOUNT_ID}
    assert inventory["mutation"] is False
    assert [item["kind"] for item in readback["commands"]] == [
        "inventory",
        "deployments",
        "versions",
    ]
    assert all(
        item["argv"][:3] == ["npx", "--yes", "cf@0.6.0"]
        for item in readback["commands"]
    )
    assert all(
        item["env"] == {"CLOUDFLARE_ACCOUNT_ID": _ACCOUNT_ID}
        for item in readback["commands"]
    )
    assert readback["mutation"] is False
    (tmp_path / "before.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(bootstrap.BootstrapError, match="absent"):
        bootstrap.inventory_command(tmp_path / "before.json", account_id=_ACCOUNT_ID)


def test_plan_is_candidate_bound_and_dry_run_by_default(tmp_path: Path) -> None:
    plan, stage = _plan(tmp_path, live=False)
    candidate = Path(plan["candidateRoot"])

    assert plan["liveCommand"] is False
    assert plan["argv"][-1] == "--dry-run"
    assert plan["argv"][:5] == [
        "pnpm",
        "--dir",
        str((_ROOT / "web").resolve()),
        "exec",
        "wrangler",
    ]
    assert plan["argv"][5:8] == [
        "deploy",
        "--config",
        str(candidate / "wrangler.jsonc"),
    ]
    assert plan["stageRootDigest"] == delivery._tree_digest(stage)
    assert candidate.name == plan["candidateDigest"]
    assert all(
        path.stat().st_mode & 0o222 == 0 for path in [candidate, *candidate.rglob("*")]
    )
    assert not Path(plan["deployOutputPath"]).exists()


def test_live_plan_requires_explicit_flag_and_embeds_full_candidate_digest(
    tmp_path: Path,
) -> None:
    plan, _stage = _plan(tmp_path, live=True)

    assert plan["liveCommand"] is True
    assert "--dry-run" not in plan["argv"]
    assert plan["argv"][-2:] == [
        "--message",
        f"OpenOpps bootstrap candidate {plan['candidateDigest']}",
    ]
    assert plan["env"] == {
        "CLOUDFLARE_ACCOUNT_ID": _ACCOUNT_ID,
        "WRANGLER_OUTPUT_FILE_PATH": plan["deployOutputPath"],
    }


def test_plan_refuses_an_existing_target_and_renders_nothing(tmp_path: Path) -> None:
    publication, _current, _previous = _publication(tmp_path)
    stage = delivery.DELIVERY_ROOT / "staging" / "assets"
    delivery.stage_publication(publication, stage)
    inventory = tmp_path / "workers.json"
    _write_json(inventory, [{"id": "openopps-data-staging"}])

    with pytest.raises(bootstrap.BootstrapError, match="already exists"):
        bootstrap.build_bootstrap_plan(
            config=_config(),
            stage_root=stage,
            inventory_path=inventory,
            deploy_output=tmp_path / "deploy.jsonl",
            plan_path=tmp_path / "plan.json",
            source_revision=_SOURCE_REVISION,
            account_id=_ACCOUNT_ID,
        )

    assert not (tmp_path / "plan.json").exists()
    assert not (tmp_path / "deploy.jsonl").exists()
    assert not (tmp_path / "upload-candidates").exists()


def test_plan_never_replaces_a_concurrently_created_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, _current, _previous = _publication(tmp_path)
    stage = delivery.DELIVERY_ROOT / "staging" / "assets"
    delivery.stage_publication(publication, stage)
    inventory = tmp_path / "workers.json"
    _write_json(inventory, [])
    plan_path = tmp_path / "plan.json"
    original_link = bootstrap.os.link

    def race_link(source: Path, destination: Path, **kwargs: object) -> None:
        plan_path.write_text('{"owner":"concurrent"}\n', encoding="utf-8")
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(bootstrap.os, "link", race_link)

    with pytest.raises(bootstrap.BootstrapError, match="already exists"):
        bootstrap.build_bootstrap_plan(
            config=_config(),
            stage_root=stage,
            inventory_path=inventory,
            deploy_output=tmp_path / "deploy.jsonl",
            plan_path=plan_path,
            source_revision=_SOURCE_REVISION,
            account_id=_ACCOUNT_ID,
        )

    assert plan_path.read_text(encoding="utf-8") == '{"owner":"concurrent"}\n'


def test_plan_refuses_stale_absence_inventory(tmp_path: Path) -> None:
    publication, _current, _previous = _publication(tmp_path)
    stage = delivery.DELIVERY_ROOT / "staging" / "assets"
    delivery.stage_publication(publication, stage)
    inventory = tmp_path / "workers.json"
    inventory.write_text("[]\n", encoding="utf-8")
    old = datetime.now(timezone.utc).timestamp() - 301
    os.utime(inventory, (old, old))

    with pytest.raises(bootstrap.BootstrapError, match="last 300 seconds"):
        bootstrap.build_bootstrap_plan(
            config=_config(),
            stage_root=stage,
            inventory_path=inventory,
            deploy_output=tmp_path / "deploy.jsonl",
            plan_path=tmp_path / "plan.json",
            source_revision=_SOURCE_REVISION,
            account_id=_ACCOUNT_ID,
        )

    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        '{"type":"deploy","type":"deploy"}',
        json.dumps({"type": "version-upload", "version": 1}),
        json.dumps(
            {
                "type": "deploy",
                "version": 1,
                "worker_name": "openopps-data-production",
                "version_id": _VERSION,
                "targets": ["https://openopps-data-production.example.workers.dev"],
            }
        ),
        json.dumps(
            {
                "type": "deploy",
                "version": 1,
                "worker_name": "openopps-data-staging",
                "version_id": "bad; touch /tmp/pwned",
                "targets": ["https://openopps-data-staging.example.workers.dev"],
            }
        ),
        json.dumps(
            {
                "type": "deploy",
                "version": 1,
                "worker_name": "openopps-data-staging",
                "version_id": _VERSION,
                "targets": ["https://attacker.example"],
            }
        ),
    ],
)
def test_deploy_output_parser_is_strict(output: str) -> None:
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.parse_deploy_output(output, expected_worker="openopps-data-staging")


def test_deploy_output_parser_matches_exact_wrangler_4_122_jsonl_schema(
    tmp_path: Path,
) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    record = _deploy_record(plan)

    parsed = bootstrap.parse_deploy_output(
        json.dumps(record), expected_worker="openopps-data-staging"
    )

    assert set(parsed) == {
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
    assert parsed["version_id"] == _VERSION
    assert parsed["timestamp"] == plan["plannedAt"]
    with pytest.raises(bootstrap.BootstrapError, match="schema"):
        bootstrap.parse_deploy_output(
            json.dumps({**record, "unexpected": True}),
            expected_worker="openopps-data-staging",
        )


def test_record_captures_exact_initial_deployment_as_rollback_identity(
    tmp_path: Path,
) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    evidence = _remote_evidence(tmp_path)
    _write_deploy_output(plan)

    entry = bootstrap.record_bootstrap(
        plan_path=tmp_path / "plan.json",
        inventory_after_path=evidence["inventory"],
        deployments_path=evidence["deployments"],
        versions_path=evidence["versions"],
        ledger_path=tmp_path / "bootstrap-ledger.json",
        recorded_at=_recorded_at(plan),
    )

    persisted = json.loads(
        (tmp_path / "bootstrap-ledger.json").read_text(encoding="utf-8")
    )
    assert entry == persisted
    assert entry["workerVersionId"] == _VERSION
    assert entry["rollbackWorkerVersionId"] == _VERSION
    assert entry["workerDeploymentId"] == _DEPLOYMENT
    assert entry["workerId"] == _WORKER_ID
    assert entry["accountId"] == _ACCOUNT_ID
    assert entry["candidateDigest"] == plan["candidateDigest"]
    assert entry["stageRootDigest"] == plan["stageRootDigest"]
    assert "author_email" not in json.dumps(entry)


def test_record_never_replaces_a_concurrently_created_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    evidence = _remote_evidence(tmp_path)
    _write_deploy_output(plan)
    ledger = tmp_path / "bootstrap-ledger.json"
    original_link = bootstrap.os.link

    def race_link(source: Path, destination: Path, **kwargs: object) -> None:
        ledger.write_text('{"owner":"concurrent"}\n', encoding="utf-8")
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(bootstrap.os, "link", race_link)

    with pytest.raises(bootstrap.BootstrapError, match="already exists"):
        bootstrap.record_bootstrap(
            plan_path=tmp_path / "plan.json",
            inventory_after_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
            ledger_path=ledger,
            recorded_at=_recorded_at(plan),
        )

    assert ledger.read_text(encoding="utf-8") == '{"owner":"concurrent"}\n'


@pytest.mark.parametrize(
    "mutation", ["extra-version", "route", "preview", "wrong-target", "message"]
)
def test_record_rejects_non_exact_remote_state(tmp_path: Path, mutation: str) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    _write_deploy_output(plan)
    evidence = _remote_evidence(tmp_path)
    if mutation == "extra-version":
        value = json.loads(evidence["versions"].read_text(encoding="utf-8"))
        value["items"].append({**value["items"][0], "id": "2" * 36})
        _write_json(evidence["versions"], value)
    elif mutation == "route":
        value = json.loads(evidence["inventory"].read_text(encoding="utf-8"))
        value["references"]["domains"].append("unexpected.example")
        _write_json(evidence["inventory"], value)
    elif mutation == "preview":
        value = json.loads(evidence["inventory"].read_text(encoding="utf-8"))
        value["subdomain"]["previews_enabled"] = True
        _write_json(evidence["inventory"], value)
    elif mutation == "wrong-target":
        value = json.loads(evidence["inventory"].read_text(encoding="utf-8"))
        value["subdomain"]["url"] = "https://openopps-data-staging.other.workers.dev"
        _write_json(evidence["inventory"], value)
    else:
        value = json.loads(evidence["versions"].read_text(encoding="utf-8"))
        value["items"][0]["annotations"]["workers/message"] = "wrong candidate"
        _write_json(evidence["versions"], value)

    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.record_bootstrap(
            plan_path=tmp_path / "plan.json",
            inventory_after_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
            ledger_path=tmp_path / "bootstrap-ledger.json",
            recorded_at=_recorded_at(plan),
        )

    assert not (tmp_path / "bootstrap-ledger.json").exists()


def test_expired_plan_and_late_deploy_output_cannot_be_replayed(tmp_path: Path) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    expired = dict(plan)
    captured = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)
    expired["inventoryBeforeMtimeNs"] = int(captured.timestamp() * 1_000_000_000)
    expired["inventoryCapturedAt"] = captured.isoformat().replace("+00:00", "Z")
    expired["plannedAt"] = (
        (captured + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    expired["expiresAt"] = (
        (captured + timedelta(seconds=bootstrap.MAX_INVENTORY_AGE_SECONDS))
        .isoformat()
        .replace("+00:00", "Z")
    )
    with pytest.raises(bootstrap.BootstrapError, match="expired"):
        bootstrap._validate_plan(expired)

    _write_deploy_output(plan)
    output = Path(str(plan["deployOutputPath"]))
    expiry_ns = int(plan["inventoryBeforeMtimeNs"]) + (
        bootstrap.MAX_INVENTORY_AGE_SECONDS * 1_000_000_000
    )
    os.utime(output, ns=(expiry_ns + 1, expiry_ns + 1))
    evidence = _remote_evidence(tmp_path)
    with pytest.raises(bootstrap.BootstrapError, match="absent-inventory window"):
        bootstrap.record_bootstrap(
            plan_path=tmp_path / "plan.json",
            inventory_after_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
            ledger_path=tmp_path / "ledger.json",
            recorded_at=_recorded_at(plan),
        )


def test_recorded_at_must_follow_deploy_timestamp(tmp_path: Path) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    _write_deploy_output(plan)
    evidence = _remote_evidence(tmp_path)

    with pytest.raises(bootstrap.BootstrapError, match="must follow"):
        bootstrap.record_bootstrap(
            plan_path=tmp_path / "plan.json",
            inventory_after_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
            ledger_path=tmp_path / "ledger.json",
            recorded_at=str(plan["plannedAt"]),
        )


def test_existing_worker_is_accepted_only_by_exact_ledger_reconciliation(
    tmp_path: Path,
) -> None:
    plan, _stage = _plan(tmp_path, live=True)
    _write_deploy_output(plan)
    evidence = _remote_evidence(tmp_path)
    ledger = tmp_path / "bootstrap-ledger.json"
    bootstrap.record_bootstrap(
        plan_path=tmp_path / "plan.json",
        inventory_after_path=evidence["inventory"],
        deployments_path=evidence["deployments"],
        versions_path=evidence["versions"],
        ledger_path=ledger,
        recorded_at=_recorded_at(plan),
    )

    result = bootstrap.reconcile_existing(
        ledger_path=ledger,
        inventory_path=evidence["inventory"],
        deployments_path=evidence["deployments"],
        versions_path=evidence["versions"],
    )

    assert result["ok"] is True
    assert result["mutation"] is False
    assert result["rollbackWorkerVersionId"] == _VERSION
    value = json.loads(evidence["deployments"].read_text(encoding="utf-8"))
    value["deployments"][0]["versions"][0]["percentage"] = 99
    _write_json(evidence["deployments"], value)
    with pytest.raises(bootstrap.BootstrapError, match="100%"):
        bootstrap.reconcile_existing(
            ledger_path=ledger,
            inventory_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
        )


def test_record_rejects_dry_run_plan_and_changed_pre_inventory(tmp_path: Path) -> None:
    plan, _stage = _plan(tmp_path, live=False)
    evidence = _remote_evidence(tmp_path)
    _write_deploy_output(plan)
    with pytest.raises(bootstrap.BootstrapError, match="dry-run"):
        bootstrap.record_bootstrap(
            plan_path=tmp_path / "plan.json",
            inventory_after_path=evidence["inventory"],
            deployments_path=evidence["deployments"],
            versions_path=evidence["versions"],
            ledger_path=tmp_path / "ledger.json",
            recorded_at=_recorded_at(plan),
        )

    second = tmp_path / "second"
    second.mkdir()
    live_plan, _stage = _plan(second, live=True)
    _write_deploy_output(live_plan)
    Path(live_plan["inventoryBeforePath"]).write_text("[ ]\n", encoding="utf-8")
    second_evidence = _remote_evidence(second)
    with pytest.raises(bootstrap.BootstrapError, match="changed"):
        bootstrap.record_bootstrap(
            plan_path=second / "plan.json",
            inventory_after_path=second_evidence["inventory"],
            deployments_path=second_evidence["deployments"],
            versions_path=second_evidence["versions"],
            ledger_path=second / "ledger.json",
            recorded_at=_recorded_at(live_plan),
        )


def _plan(tmp_path: Path, *, live: bool) -> tuple[dict[str, object], Path]:
    publication, _current, _previous = _publication(tmp_path)
    stage = delivery.DELIVERY_ROOT / "staging" / "assets"
    delivery.stage_publication(publication, stage)
    inventory = tmp_path / "workers-before.json"
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text("[]\n", encoding="utf-8")
    plan = bootstrap.build_bootstrap_plan(
        config=_config(),
        stage_root=stage,
        inventory_path=inventory,
        deploy_output=tmp_path / "deploy.jsonl",
        plan_path=tmp_path / "plan.json",
        source_revision=_SOURCE_REVISION,
        account_id=_ACCOUNT_ID,
        live_command=live,
    )
    return plan, stage


def _config() -> Path:
    return _ROOT / "deployment" / "openopps-data" / "staging" / "wrangler.jsonc"


def _origin() -> str:
    return "https://openopps-data-staging.example.workers.dev"


def _worker() -> dict[str, object]:
    return {
        "id": _WORKER_ID,
        "name": "openopps-data-staging",
        "tags": [],
        "observability": {
            "enabled": False,
            "logs": {"enabled": False},
            "traces": {"enabled": False},
        },
        "logpush": False,
        "references": {
            "workers": [],
            "domains": [],
            "dispatch_namespace_outbounds": [],
            "durable_objects": [],
            "queues": [],
        },
        "subdomain": {
            "enabled": True,
            "previews_enabled": False,
            "url": _origin(),
        },
        "tail_consumers": [],
    }


def _deploy_record(plan: dict[str, object]) -> dict[str, object]:
    return {
        "type": "deploy",
        "version": 1,
        "worker_name": "openopps-data-staging",
        "worker_tag": "worker-tag",
        "version_id": _VERSION,
        "targets": [_origin()],
        "wrangler_environment": None,
        "worker_name_overridden": False,
        "timestamp": plan["plannedAt"],
    }


def _write_deploy_output(plan: dict[str, object]) -> None:
    Path(str(plan["deployOutputPath"])).write_text(
        json.dumps(_deploy_record(plan)) + "\n", encoding="utf-8"
    )


def _recorded_at(plan: dict[str, object]) -> str:
    planned = datetime.fromisoformat(str(plan["plannedAt"]).replace("Z", "+00:00"))
    return (
        (planned + timedelta(microseconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _remote_evidence(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "inventory": tmp_path / "workers-after.json",
        "deployments": tmp_path / "deployments.json",
        "versions": tmp_path / "versions.json",
    }
    _write_json(paths["inventory"], _worker())
    _write_json(
        paths["deployments"],
        {
            "deployments": [
                {
                    "id": _DEPLOYMENT,
                    "source": "wrangler",
                    "strategy": "percentage",
                    "author_email": "not-persisted@example.test",
                    "versions": [{"version_id": _VERSION, "percentage": 100}],
                }
            ]
        },
    )
    _write_json(
        paths["versions"],
        {
            "items": [
                {
                    "id": _VERSION,
                    "number": 1,
                    "metadata": {
                        "source": "wrangler",
                        "author_email": "not-persisted@example.test",
                    },
                    "annotations": {
                        "workers/message": (
                            "OpenOpps bootstrap candidate "
                            + str(
                                json.loads(
                                    (tmp_path / "plan.json").read_text(encoding="utf-8")
                                )["candidateDigest"]
                            )
                        ),
                        "workers/triggered_by": "upload",
                    },
                }
            ]
        },
    )
    return paths


def _publication(tmp_path: Path) -> tuple[Path, str, str]:
    publication = tmp_path / "publication"
    promoted = datetime.now(timezone.utc)
    current_snapshot = promoted - timedelta(hours=1)
    previous = _release(publication, "Previous", current_snapshot - timedelta(days=1))
    current = _release(publication, "Current", current_snapshot)
    release.atomic_write_channel_pointer(
        publication,
        current,
        channel="production",
        prior_release_id=previous["releaseId"],
        promoted_at=promoted.isoformat(),
    )
    return publication, current["releaseId"], previous["releaseId"]


def _release(
    publication: Path, company: str, snapshot_at: datetime
) -> dict[str, object]:
    staging = publication.parent / f"staging-{company.casefold()}"
    canonical_snapshot = release.canonical_utc_timestamp(snapshot_at.isoformat())
    source_key = company.casefold()
    counts = {
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
            "counts": {"snapshot": counts},
            "detailShards": {"tierCounts": {"T1": 0, "T2": 1}},
        },
    )
    _write_json(
        staging / "publication-policy.json",
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
                **counts,
                "detailTiers": {"T1": 0, "T2": 1},
            },
        },
    )
    _write_json(staging / "providers.json", {"rows": [[company]], "count": 1})
    _write_json(staging / "jobs-details" / "00.json", {"job-1": {"company": company}})
    manifest = release.build_release_manifest(
        staging,
        snapshot_at=snapshot_at.isoformat(),
        source=_SOURCE,
        generator=_GENERATOR,
    )
    release.write_release_manifest(staging, manifest)
    destination = publication / "releases" / manifest["releaseId"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(destination)
    return manifest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
