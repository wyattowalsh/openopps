"""Split Git delivery: reserve and apply cannot run in one process."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json
import shutil

import pytest

from openopps.discovery.promotion import PromotionLedgerError
from openopps.discovery.promotion_closure import (
    DECISION_ID,
    apply_reserved_shared_delivery_closure,
    apply_shared_delivery_closure,
    build_shared_delivery_closure,
    reserve_shared_delivery_closure,
)
from openopps.discovery.promotion_runtime import (
    CATALOG_RELATIVE_PATH,
    DECISION_RELATIVE_PATH,
    ENVELOPE_RELATIVE_PATH,
    GENERATED_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    READONLY_WHEEL_PATHS,
    RECEIPT_RELATIVE_PATH,
    SHARED_DELIVERY_OWNED_PATHS,
    load_promotion_ledger,
)


ROOT = Path(__file__).resolve().parents[4]
HEAD = "fd7bab3b4ddfad59dc4138e05905f891bcb1f44a"
# Distinct HEAD so a new reservation is not an intent replay of 20260822.
NEW_HEAD = "b" * 40
NEW_DECISION_ID = "b699-identity-closure-20260906"
NEW_VALIDATED_AT = datetime(2026, 9, 6, tzinfo=UTC)
CLOSURE_SURFACES = (
    CATALOG_RELATIVE_PATH,
    GENERATED_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    "src/openopps/discovery/data/manifest.json",
    "src/openopps/discovery/data/trusted-discovery-profile.schema.json",
    "src/openopps/discovery/data/discovery-promotion-policy-decision.schema.json",
    *READONLY_WHEEL_PATHS.values(),
)
OWNED_CREATED_ON_APPLY = (
    DECISION_RELATIVE_PATH,
    ENVELOPE_RELATIVE_PATH,
    RECEIPT_RELATIVE_PATH,
)


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in CLOSURE_SURFACES:
        source = ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    # The repository ledger now carries later landed closures (20260906); the
    # Git-delivery fixture is the immutable 20260822 reserved+applied prefix.
    lines = (ROOT / LEDGER_RELATIVE_PATH).read_text(encoding="utf-8").splitlines(
        keepends=True
    )
    historical = [
        line for line in lines if json.loads(line)["decisionId"] == DECISION_ID
    ]
    assert [json.loads(line)["state"] for line in historical] == [
        "reserved",
        "applied",
    ]
    (root / LEDGER_RELATIVE_PATH).write_text("".join(historical), encoding="utf-8")
    return root


def _copied_payloads(root: Path) -> dict[str, bytes]:
    return {relative: (root / relative).read_bytes() for relative in CLOSURE_SURFACES}


def _tree_payloads(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_reserve_writes_only_ledger_and_rejects_replay_of_old_decision(
    tmp_path: Path,
) -> None:
    root = _seed(tmp_path)
    historical = load_promotion_ledger(root / LEDGER_RELATIVE_PATH)
    assert [event.decision_id for event in historical] == [DECISION_ID, DECISION_ID]
    assert [event.state for event in historical] == ["reserved", "applied"]
    before = _copied_payloads(root)

    closure, reserved = reserve_shared_delivery_closure(
        root,
        head_sha=NEW_HEAD,
        decision_id=NEW_DECISION_ID,
        invocation_mode="maintainer",
        committed_events=historical,
        validated_at=NEW_VALIDATED_AT,
    )
    after = _copied_payloads(root)
    changed = {relative for relative in after if after[relative] != before[relative]}
    assert changed == {LEDGER_RELATIVE_PATH}
    assert all(not (root / relative).exists() for relative in OWNED_CREATED_ON_APPLY)
    assert reserved.state == "reserved"
    assert reserved.decision_id == NEW_DECISION_ID
    assert closure.decision_id == NEW_DECISION_ID

    with pytest.raises(
        PromotionLedgerError, match="refusing replay of b699-identity-closure-20260822"
    ):
        reserve_shared_delivery_closure(
            root,
            head_sha=HEAD,
            decision_id=DECISION_ID,
            invocation_mode="maintainer",
            committed_events=(*historical, reserved),
        )


def test_apply_without_committed_reservation_writes_nothing(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    historical = load_promotion_ledger(root / LEDGER_RELATIVE_PATH)
    closure = build_shared_delivery_closure(
        root,
        head_sha=NEW_HEAD,
        decision_id=NEW_DECISION_ID,
        validated_at=NEW_VALIDATED_AT,
    )
    before = _tree_payloads(root)
    with pytest.raises(PromotionLedgerError, match="committed reserved event"):
        apply_reserved_shared_delivery_closure(
            root,
            head_sha=NEW_HEAD,
            decision_id=NEW_DECISION_ID,
            invocation_mode="maintainer",
            lock_nonce="no-reserve",
            committed_events=historical,
            closure=closure,
        )
    assert _tree_payloads(root) == before


def test_apply_after_reservation_closes_owned_paths(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    historical = load_promotion_ledger(root / LEDGER_RELATIVE_PATH)
    closure, reserved = reserve_shared_delivery_closure(
        root,
        head_sha=NEW_HEAD,
        decision_id=NEW_DECISION_ID,
        invocation_mode="maintainer",
        committed_events=historical,
        validated_at=NEW_VALIDATED_AT,
    )
    ledger_after_reserve = (root / LEDGER_RELATIVE_PATH).read_bytes()
    journal = apply_reserved_shared_delivery_closure(
        root,
        head_sha=NEW_HEAD,
        decision_id=NEW_DECISION_ID,
        invocation_mode="maintainer",
        lock_nonce="b699-git-apply",
        committed_events=(*historical, reserved),
        closure=closure,
    )
    events = load_promotion_ledger(
        root / LEDGER_RELATIVE_PATH, committed_events=(*historical, reserved)
    )
    assert events[-1].state == "applied"
    assert events[-1].decision_id == NEW_DECISION_ID
    assert events[-1].predecessor_digest == reserved.event_digest
    assert events[-2].event_digest == reserved.event_digest
    assert (root / LEDGER_RELATIVE_PATH).read_bytes() != ledger_after_reserve
    assert {entry.path for entry in journal.entries} == set(SHARED_DELIVERY_OWNED_PATHS)
    assert (root / CATALOG_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        CATALOG_RELATIVE_PATH
    ]
    assert (root / GENERATED_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        GENERATED_RELATIVE_PATH
    ]


def test_combined_helper_raises_promotion_ledger_error() -> None:
    with pytest.raises(PromotionLedgerError, match="combined reserve\\+apply"):
        apply_shared_delivery_closure()
