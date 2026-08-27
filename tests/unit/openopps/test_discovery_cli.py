"""Semantic help and non-mutating scout/verify/preview CLI coverage (D1001-D1004, I801-I816)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from click import unstyle
from typer.testing import CliRunner

from openopps.cli import app
from openopps.discovery.api import (
    preview_repository_promotion,
    run_offline_quarantine_scout,
    verify_scout_manifest_path,
)
from openopps.models import BoardRecord, SourceRecord
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


runner = CliRunner()
HELP_WIDTH = 120
REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "portfolio_source_catalog.json"
)
ENVELOPE_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "discovery"
    / "data"
    / "approved_ingestion_selector_envelope.json"
)
ENVELOPE = json.loads(ENVELOPE_PATH.read_text(encoding="utf-8"))
DECISION_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "discovery"
    / "data"
    / "discovery_promotion_policy_decision.json"
)
RECEIPT_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "discovery"
    / "data"
    / "evidence_only_decision_receipt.json"
)
LEDGER_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "discovery"
    / "data"
    / "promotion_decision_ledger.jsonl"
)
GENERATED_PATH = REPO_ROOT / "web" / "lib" / "generated" / "openopps-data.json"
LOCK_PATH = REPO_ROOT / "var" / "openopps" / "promotion.lock"
DECISION = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _plain(text: str) -> str:
    return unstyle(text)


def _help(*args: str) -> str:
    result = runner.invoke(app, list(args), terminal_width=HELP_WIDTH)
    assert result.exit_code == 0, result.output
    return _plain(result.output)


def test_root_help_places_discovery_on_the_advanced_panel() -> None:
    output = _help("--help")
    assert "Everyday workflow" in output
    assert "Advanced admin" in output
    assert "Quarantined source discovery" in output
    advanced = output[output.find("Advanced admin") :]
    everyday = output.split("Everyday workflow", 1)[1].split("Advanced admin", 1)[0]
    assert "Quarantined source discovery" in advanced
    assert "Quarantined source discovery" not in everyday
    assert "same-run" not in output.casefold()
    assert "hosted discovery" not in output.casefold()
    assert "browser automation" not in output.casefold()


def test_discovery_group_help_is_read_verify_only() -> None:
    output = _help("discovery", "--help")
    folded = output.casefold()
    assert "scout" in folded
    assert "verify-scout" in folded
    assert "preview-promotion" in folded
    assert "quarantine" in folded
    assert "promote" in folded or "promotion" in folded
    assert "dry-run" in folded or "preview" in folded
    assert "approved-ingestion" in folded or "envelope" in folded
    assert "sourceselector" in folded
    assert "same-run" in folded
    assert "--apply" not in folded
    assert "sync" not in folded or "does not" in folded


def test_admin_sources_help_exposes_open_spec_scout_and_verify() -> None:
    output = _help("admin", "sources", "--help")
    folded = output.casefold()
    assert "scout" in folded
    assert "verify-scout" in folded
    assert "preview-promotion" in folded
    assert "--apply" not in folded


def test_scout_help_requires_output_and_has_no_apply_option() -> None:
    for args in (
        ("discovery", "scout", "--help"),
        ("admin", "sources", "scout", "--help"),
    ):
        output = _help(*args)
        folded = output.casefold()
        assert "--output" in output
        assert "--json" in output
        assert "quarantine" in folded
        assert "envelope" in folded or "approved-ingestion" in folded
        assert "sourceselector" in folded
        assert "same-run" in folded
        assert "--apply" not in output
        assert "sqlite" in folded or "catalog" in folded


def test_verify_scout_help_is_offline_and_read_only() -> None:
    for args in (
        ("discovery", "verify-scout", "--help"),
        ("admin", "sources", "verify-scout", "--help"),
    ):
        output = _help(*args)
        folded = output.casefold()
        assert "manifest" in folded
        assert "--json" in output
        assert "--apply" not in output
        assert "rewrite" in folded or "activating" in folded or "offline" in folded


def test_everyday_sync_help_does_not_advertise_discovery_activation() -> None:
    output = _help("sources", "sync", "--help")
    folded = output.casefold()
    assert "scout" not in folded
    assert "verify-scout" not in folded
    assert "preview-promotion" not in folded
    assert "same-run" not in folded


def test_scout_requires_explicit_output_directory() -> None:
    result = runner.invoke(app, ["discovery", "scout", "--json"])
    assert result.exit_code != 0
    combined = _plain(result.output + result.stderr)
    assert "--output" in combined


def test_offline_scout_then_verify_emits_json_without_mutation(
    tmp_path: Path,
) -> None:
    catalog_before = CATALOG.read_bytes()
    output = tmp_path / "quarantine"
    db_path = tmp_path / "openopps.db"
    env = {"OPENOPPS_DB_URL": f"sqlite:///{db_path}"}

    scout = runner.invoke(
        app,
        ["discovery", "scout", "--output", str(output), "--json"],
        env=env,
    )
    assert scout.exit_code == 0, scout.output
    assert scout.stderr == "" or scout.stderr.strip() == ""
    payload = json.loads(scout.stdout)
    assert payload["command"] == "scout"
    assert payload["status"] == "complete"
    assert payload["promoted"] is False
    assert payload["activated"] is False
    assert payload["eligibleForReview"] == 0
    _assert_selector_bound_observability(payload)
    manifest = Path(payload["manifestPath"])
    assert manifest.is_file()
    assert not db_path.exists()
    assert CATALOG.read_bytes() == catalog_before

    verify = runner.invoke(
        app,
        ["admin", "sources", "verify-scout", str(manifest), "--json"],
        env=env,
    )
    assert verify.exit_code == 0, verify.output
    verified = json.loads(verify.stdout)
    assert verified["command"] == "verify-scout"
    assert verified["status"] == "verified"
    assert verified["promoted"] is False
    assert verified["activated"] is False
    assert verified["manifestId"] == payload["manifestId"]
    _assert_selector_bound_observability(verified)
    assert (
        verified["observability"]["envelopeId"]
        == payload["observability"]["envelopeId"]
    )
    assert not db_path.exists()
    assert CATALOG.read_bytes() == catalog_before
    assert manifest.read_bytes()  # unchanged readable file
    listing_before = sorted(
        path.relative_to(manifest.parent) for path in manifest.parent.rglob("*")
    )
    replay = runner.invoke(
        app,
        ["discovery", "verify-scout", str(manifest.parent), "--json"],
        env=env,
    )
    assert replay.exit_code == 0, replay.output
    listing_after = sorted(
        path.relative_to(manifest.parent) for path in manifest.parent.rglob("*")
    )
    assert listing_after == listing_before
    assert CATALOG.read_bytes() == catalog_before


def test_verify_scout_rejects_invalid_manifest_without_promoting(
    tmp_path: Path,
) -> None:
    catalog_before = CATALOG.read_bytes()
    bogus = tmp_path / "manifest.json"
    bogus.write_text("{not-a-bundle}\n", encoding="utf-8")
    result = runner.invoke(app, ["discovery", "verify-scout", str(bogus), "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["promoted"] is False
    assert payload["activated"] is False
    assert payload["diagnostic"]["reasonCode"]
    assert CATALOG.read_bytes() == catalog_before
    assert bogus.read_text(encoding="utf-8") == "{not-a-bundle}\n"


def test_library_scout_and_verify_round_trip(tmp_path: Path) -> None:
    catalog_before = CATALOG.read_bytes()
    payload = run_offline_quarantine_scout(
        tmp_path / "out",
        repository_root=REPO_ROOT,
        execution_id="cli-test-1",
    )
    assert payload["promoted"] is False
    assert payload["activated"] is False
    verified = verify_scout_manifest_path(Path(str(payload["manifestPath"])))
    assert verified["status"] == "verified"
    assert verified["manifestId"] == payload["manifestId"]
    assert CATALOG.read_bytes() == catalog_before


def _assert_selector_bound_observability(payload: dict[str, object]) -> None:
    observability = payload["observability"]
    assert isinstance(observability, dict)
    assert GIT_SHA_RE.fullmatch(str(payload["checkoutSha"]))
    assert observability["envelopeId"] == ENVELOPE["envelopeId"]
    assert observability["attestation"] == "degraded"
    assert observability["degradedClass"] == "unstarted"
    source = observability["source"]
    assert source["planned"] == ENVELOPE["sourceCount"]
    assert source["unstarted"] == ENVELOPE["sourceCount"]
    assert source["succeeded"] == 0
    assert source["cancelled"] == 0
    assert source["complete"] is False
    route = observability["route"]
    assert route["planned"] == 1
    assert route["succeeded"] == 1
    assert route["duplicateSkipped"] == 0
    assert (
        route["planned"]
        == route["succeeded"]
        + route["failed"]
        + route["timedOut"]
        + route["freshSkipped"]
        + route["deferred"]
        + route["duplicateSkipped"]
        + route["missingMetadata"]
        + route["policyBlocked"]
        + route["rateLimited"]
        + route["cancelled"]
        + route["unstarted"]
    )
    evidence = observability["evidence"]
    for field in (
        "catalogContentDigest",
        "catalogTreeDigest",
        "selectorDigest",
        "policyDigest",
        "promotionDigest",
        "invocationDigest",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", str(evidence[field]))
    rendered = json.dumps(payload, sort_keys=True)
    assert "unaccounted_ids" not in rendered
    assert "unaccountedIds" not in rendered
    assert "https://" not in rendered
    assert "http://" not in rendered
    assert ENVELOPE["sourceKeys"][0] not in rendered
    assert ENVELOPE["sourceKeys"][-1] not in rendered


def test_selector_bound_scout_does_not_mutate_stored_only_or_job_sync_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    custom = SourceRecord(
        key="local-custom-i815",
        url="https://example.test/custom-source",
        provider_id="manual",
    )
    store.upsert_source(custom)
    store.upsert_boards(
        [
            BoardRecord(
                key="custom-board",
                source_key="local-custom-i815",
                remote_id="custom-board",
                name="Custom Board",
                domain="example.test",
            )
        ]
    )
    pending = store.begin_job_sync_run("custom-board", "manual")
    sources_before = [item.model_dump(mode="json") for item in store.list_sources()]
    store.engine.dispose()
    before_bytes = db_path.read_bytes()
    wal = Path(f"{db_path}-wal")
    shm = Path(f"{db_path}-shm")
    wal_before = wal.read_bytes() if wal.exists() else None
    shm_before = shm.read_bytes() if shm.exists() else None

    output = tmp_path / "quarantine"
    env = {"OPENOPPS_DB_URL": f"sqlite:///{db_path}"}
    scout = runner.invoke(
        app,
        ["discovery", "scout", "--output", str(output), "--json"],
        env=env,
    )
    assert scout.exit_code == 0, scout.output
    payload = json.loads(scout.stdout)
    _assert_selector_bound_observability(payload)
    assert payload["promoted"] is False
    assert payload["activated"] is False
    assert "local-custom-i815" not in json.dumps(payload)

    assert db_path.read_bytes() == before_bytes
    if wal_before is None:
        assert not wal.exists() or wal.stat().st_size == 0
    else:
        assert wal.read_bytes() == wal_before
    if shm_before is None:
        assert not shm.exists() or shm.stat().st_size == 0
    else:
        assert shm.read_bytes() == shm_before

    after_store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    sources_after = [
        item.model_dump(mode="json") for item in after_store.list_sources()
    ]
    assert sources_after == sources_before
    restored = after_store.get_source("local-custom-i815")
    assert restored is not None
    assert restored.model_dump(mode="json") == custom.model_dump(mode="json")
    assert restored.provider_id == "manual"
    from sqlmodel import Session, select
    from openopps.models import JobSyncRunRow

    with Session(after_store.engine) as session:
        rows = list(session.exec(select(JobSyncRunRow)).all())
    assert len(rows) == 1
    assert rows[0].id == pending.id
    assert rows[0].board_key == "custom-board"
    assert rows[0].provider_id == "manual"
    assert rows[0].status == "pending"
    after_store.engine.dispose()


def test_explicit_local_custom_workflow_remains_outside_selector_bound_scout(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    env = {"OPENOPPS_DB_URL": f"sqlite:///{db_path}"}
    added = runner.invoke(
        app,
        [
            "admin",
            "sources",
            "add",
            "local-custom-i806",
            "--url",
            "https://example.test/local-custom",
            "--provider",
            "manual",
        ],
        env=env,
    )
    assert added.exit_code == 0, added.output
    scout = runner.invoke(
        app,
        ["discovery", "scout", "--output", str(tmp_path / "quarantine"), "--json"],
        env=env,
    )
    assert scout.exit_code == 0, scout.output
    listed = runner.invoke(app, ["sources", "list", "--json"], env=env)
    assert listed.exit_code == 0, listed.output
    records = json.loads(listed.stdout)
    keys = {item["key"] for item in records}
    assert "local-custom-i806" in keys
    payload = json.loads(scout.stdout)
    assert "local-custom-i806" not in json.dumps(payload)
    _assert_selector_bound_observability(payload)


def _promotion_surface_bytes() -> dict[str, bytes]:
    return {
        "catalog": CATALOG.read_bytes(),
        "decision": DECISION_PATH.read_bytes(),
        "envelope": ENVELOPE_PATH.read_bytes(),
        "generated": GENERATED_PATH.read_bytes(),
        "ledger": LEDGER_PATH.read_bytes(),
        "receipt": RECEIPT_PATH.read_bytes(),
    }


def _lock_snapshot() -> bytes | None:
    return LOCK_PATH.read_bytes() if LOCK_PATH.exists() else None


def _assert_preview_payload(
    payload: dict[str, object], *, identity_closure: bool
) -> None:
    assert payload["command"] == "preview-promotion"
    assert payload["status"] == "preview"
    assert payload["promoted"] is False
    assert payload["activated"] is False
    assert payload["applied"] is False
    assert payload["grantsAuthority"] is False
    assert payload["catalogUnchanged"] is True
    assert payload["proposedRecordCount"] == 0
    assert payload["identityClosure"] is identity_closure
    assert payload["decisionId"] == DECISION["decisionId"]
    assert payload["decisionHeadSha"] == DECISION["headSha"]
    assert GIT_SHA_RE.fullmatch(str(payload["checkoutSha"]))
    assert GIT_SHA_RE.fullmatch(str(payload["decisionHeadSha"]))
    assert SHA256_RE.fullmatch(str(payload["catalogBeforeDigest"]))
    assert SHA256_RE.fullmatch(str(payload["catalogAfterDigest"]))
    assert SHA256_RE.fullmatch(str(payload["promotionDigest"]))
    assert SHA256_RE.fullmatch(str(payload["promotionIntentDigest"]))
    assert payload["catalogBeforeDigest"] == payload["catalogAfterDigest"]
    assert payload["envelopeId"] == ENVELOPE["envelopeId"]
    assert payload["sourceCount"] == ENVELOPE["sourceCount"]
    assert payload["ledgerStates"] == ["reserved", "applied"]
    delta = payload["delta"]
    assert isinstance(delta, dict)
    assert "changes" in delta
    intent = payload["intent"]
    assert isinstance(intent, dict)
    assert intent["headSha"] == DECISION["headSha"]
    rendered = json.dumps(payload, sort_keys=True)
    assert "unaccounted_ids" not in rendered
    assert "unaccountedIds" not in rendered
    assert "https://" not in rendered
    assert "http://" not in rendered
    assert ENVELOPE["sourceKeys"][0] not in rendered
    assert ENVELOPE["sourceKeys"][-1] not in rendered
    assert "--apply" not in rendered


def test_preview_promotion_help_is_dry_run_and_has_no_apply_option() -> None:
    for args in (
        ("discovery", "preview-promotion", "--help"),
        ("admin", "sources", "preview-promotion", "--help"),
    ):
        output = _help(*args)
        folded = output.casefold()
        assert "--json" in output
        assert "dry-run" in folded or "preview" in folded
        assert "identity" in folded or "envelope" in folded or "decision" in folded
        assert "manifest" in folded
        assert "sqlite" in folded or "catalog" in folded
        assert "apply" in folded
        assert "--apply" not in output


def test_scout_and_verify_help_still_have_no_apply_after_preview() -> None:
    for args in (
        ("discovery", "scout", "--help"),
        ("discovery", "verify-scout", "--help"),
        ("admin", "sources", "scout", "--help"),
        ("admin", "sources", "verify-scout", "--help"),
    ):
        output = _help(*args)
        assert "--apply" not in output


def test_identity_preview_emits_json_without_mutation(tmp_path: Path) -> None:
    before = _promotion_surface_bytes()
    lock_before = _lock_snapshot()
    db_path = tmp_path / "openopps.db"
    env = {"OPENOPPS_DB_URL": f"sqlite:///{db_path}"}

    first = runner.invoke(
        app,
        ["discovery", "preview-promotion", "--json"],
        env=env,
    )
    assert first.exit_code == 0, first.output
    assert first.stderr == "" or first.stderr.strip() == ""
    payload = json.loads(first.stdout)
    _assert_preview_payload(payload, identity_closure=True)
    assert payload["onDiskMatch"] is True
    assert payload["promotionDigest"] == ENVELOPE["promotionDigest"]
    assert payload["promotionIntentDigest"] == DECISION["promotionIntentDigest"]
    assert not db_path.exists()
    assert _promotion_surface_bytes() == before
    if lock_before is None:
        assert not LOCK_PATH.exists()
    else:
        assert LOCK_PATH.read_bytes() == lock_before

    second = runner.invoke(
        app,
        ["admin", "sources", "preview-promotion", "--json"],
        env=env,
    )
    assert second.exit_code == 0, second.output
    assert second.stderr == "" or second.stderr.strip() == ""
    assert second.stdout == first.stdout
    assert json.loads(second.stdout) == payload
    assert not db_path.exists()
    assert _promotion_surface_bytes() == before


def test_identity_preview_human_output_separates_from_stderr() -> None:
    before = _promotion_surface_bytes()
    result = runner.invoke(app, ["discovery", "preview-promotion"])
    assert result.exit_code == 0, result.output
    assert result.stderr == "" or result.stderr.strip() == ""
    output = _plain(result.output).casefold()
    assert "preview-promotion" in output
    assert "preview" in output
    assert "identity-closure" in output
    assert "catalog unchanged" in output
    assert "did not apply" in output
    assert "sqlite" in output or "catalog" in output
    assert "--apply" not in result.output
    assert _promotion_surface_bytes() == before


def test_preview_with_quarantine_manifest_verifies_and_does_not_apply(
    tmp_path: Path,
) -> None:
    before = _promotion_surface_bytes()
    lock_before = _lock_snapshot()
    output = tmp_path / "quarantine"
    db_path = tmp_path / "openopps.db"
    env = {"OPENOPPS_DB_URL": f"sqlite:///{db_path}"}
    scout = runner.invoke(
        app,
        ["discovery", "scout", "--output", str(output), "--json"],
        env=env,
    )
    assert scout.exit_code == 0, scout.output
    scout_payload = json.loads(scout.stdout)
    manifest = Path(scout_payload["manifestPath"])

    preview = runner.invoke(
        app,
        ["discovery", "preview-promotion", str(manifest), "--json"],
        env=env,
    )
    assert preview.exit_code == 0, preview.output
    assert preview.stderr == "" or preview.stderr.strip() == ""
    payload = json.loads(preview.stdout)
    _assert_preview_payload(payload, identity_closure=False)
    assert payload["verified"] is True
    assert payload["manifestId"] == scout_payload["manifestId"]
    assert payload["onDiskMatch"] is False
    assert payload["promotionDigest"] != ENVELOPE["promotionDigest"]
    assert not db_path.exists()
    assert _promotion_surface_bytes() == before
    assert manifest.is_file()
    if lock_before is None:
        assert not LOCK_PATH.exists()
    else:
        assert LOCK_PATH.read_bytes() == lock_before


def test_preview_rejects_invalid_manifest_without_mutating(tmp_path: Path) -> None:
    before = _promotion_surface_bytes()
    bogus = tmp_path / "manifest.json"
    bogus.write_text("{not-a-bundle}\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["discovery", "preview-promotion", str(bogus), "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["promoted"] is False
    assert payload["activated"] is False
    assert payload["applied"] is False
    assert payload["mutated"] is False
    assert payload["command"] == "preview-promotion"
    assert payload["diagnostic"]["reasonCode"]
    assert _promotion_surface_bytes() == before
    assert bogus.read_text(encoding="utf-8") == "{not-a-bundle}\n"


def test_preview_promotion_rejects_apply_flag_without_mutation() -> None:
    before = _promotion_surface_bytes()
    result = runner.invoke(app, ["discovery", "preview-promotion", "--apply"])
    assert result.exit_code != 0
    combined = _plain(result.output + result.stderr).casefold()
    assert (
        "no such option" in combined
        or "unexpected" in combined
        or "--apply" in combined
    )
    assert _promotion_surface_bytes() == before


def test_library_identity_preview_is_byte_identical_and_read_only() -> None:
    before = _promotion_surface_bytes()
    first = preview_repository_promotion(REPO_ROOT)
    second = preview_repository_promotion(REPO_ROOT)
    assert first == second
    _assert_preview_payload(first, identity_closure=True)
    assert first["onDiskMatch"] is True
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(
        second, sort_keys=True, default=str
    )
    assert _promotion_surface_bytes() == before
