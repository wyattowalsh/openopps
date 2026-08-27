"""B699 shared-delivery identity closure: reserve, apply, wheel readback."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from openopps.discovery.promotion import (
    PromotionDecisionError,
    build_promotion_selection,
)
from openopps.discovery.promotion_closure import (
    CLOSURE_VALIDATED_AT,
    DECISION_ID,
    apply_shared_delivery_closure,
    build_shared_delivery_closure,
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
    PromotionLayout,
    apply_promotion,
    load_promotion_ledger,
    observe_cas_state,
)


ROOT = Path(__file__).resolve().parents[4]
HEAD = "fd7bab3b4ddfad59dc4138e05905f891bcb1f44a"
CLOSURE_SURFACES = (
    CATALOG_RELATIVE_PATH,
    GENERATED_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    "src/openopps/discovery/data/manifest.json",
    "src/openopps/discovery/data/trusted-discovery-profile.schema.json",
    "src/openopps/discovery/data/discovery-promotion-policy-decision.schema.json",
    *READONLY_WHEEL_PATHS.values(),
)


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in CLOSURE_SURFACES:
        source = ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (root / LEDGER_RELATIVE_PATH).write_bytes(b"")
    return root


def test_empty_selection_is_sorted_unique_and_allowed() -> None:
    digest = "a" * 64
    selection = build_promotion_selection(digest, ())
    assert selection.candidate_ids == ()
    assert selection.manifest_digest == digest


def test_identity_preview_preserves_real_catalog_bytes() -> None:
    closure = build_shared_delivery_closure(ROOT, head_sha=HEAD)
    catalog = (ROOT / CATALOG_RELATIVE_PATH).read_bytes()
    generated = (ROOT / GENERATED_RELATIVE_PATH).read_bytes()
    assert closure.preview.catalog_after == catalog
    assert closure.preview.catalog_before_digest == closure.preview.catalog_after_digest
    assert closure.generated_bytes == generated
    assert len(closure.catalog_keys) == 2239
    assert closure.envelope.source_count == 2239
    assert closure.envelope.source_keys == closure.catalog_keys
    assert closure.receipt.grants_authority is False
    assert closure.receipt.validated_at == CLOSURE_VALIDATED_AT
    assert closure.decision["decisionId"] == DECISION_ID
    assert "positive_policy_axes" not in closure.decision


def test_shared_delivery_reserve_apply_wheel_readback_and_stale_retry(
    tmp_path: Path,
) -> None:
    root = _seed(tmp_path)
    layout = PromotionLayout()
    before_catalog = (root / CATALOG_RELATIVE_PATH).read_bytes()
    before_generated = (root / GENERATED_RELATIVE_PATH).read_bytes()
    outsider = root / "README.md"
    outsider.write_text("keep\n", encoding="utf-8")

    closure, reserved, journal = apply_shared_delivery_closure(
        root,
        head_sha=HEAD,
        invocation_mode="maintainer",
        lock_nonce="b699-nonce",
    )
    events = load_promotion_ledger(root / layout.ledger, committed_events=(reserved,))
    assert [event.state for event in events] == ["reserved", "applied"]
    assert events[0].decision_id == DECISION_ID
    assert (root / CATALOG_RELATIVE_PATH).read_bytes() == before_catalog
    assert (root / GENERATED_RELATIVE_PATH).read_bytes() == before_generated
    assert (root / ENVELOPE_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        ENVELOPE_RELATIVE_PATH
    ]
    assert (root / RECEIPT_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        RECEIPT_RELATIVE_PATH
    ]
    assert (root / DECISION_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        DECISION_RELATIVE_PATH
    ]
    changed = {entry.path for entry in journal.entries}
    assert changed == set(SHARED_DELIVERY_OWNED_PATHS)
    assert outsider.read_text(encoding="utf-8") == "keep\n"

    with pytest.raises(Exception, match="reserved|applied|state"):
        apply_promotion(
            root,
            decision_id=DECISION_ID,
            intent=closure.preview.intent,
            invocation_mode="maintainer",
            head_sha=HEAD,
            catalog_fingerprint=closure.preview.catalog_before_digest,
            expected_cas=observe_cas_state(
                root,
                head_sha=HEAD,
                catalog_fingerprint=closure.preview.catalog_before_digest,
                layout=layout,
                owned_paths=SHARED_DELIVERY_OWNED_PATHS,
            ),
            after_bytes=closure.after_bytes,
            committed_events=events,
            lock_nonce="b699-stale",
            allowlist=SHARED_DELIVERY_OWNED_PATHS,
            layout=layout,
        )
    assert (root / CATALOG_RELATIVE_PATH).read_bytes() == before_catalog
    assert (root / GENERATED_RELATIVE_PATH).read_bytes() == before_generated
    assert [event.state for event in load_promotion_ledger(root / layout.ledger)] == [
        "reserved",
        "applied",
    ]


def test_scout_cannot_apply_shared_delivery_closure(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    with pytest.raises(PromotionDecisionError, match="maintainer"):
        apply_shared_delivery_closure(
            root,
            head_sha=HEAD,
            invocation_mode="scout",
            lock_nonce="scout-nonce",
        )


def test_repo_shared_delivery_artifacts_match_identity_closure() -> None:
    closure = build_shared_delivery_closure(ROOT, head_sha=HEAD)
    layout = PromotionLayout()
    assert (ROOT / CATALOG_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        CATALOG_RELATIVE_PATH
    ]
    assert (ROOT / GENERATED_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        GENERATED_RELATIVE_PATH
    ]
    assert (ROOT / ENVELOPE_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        ENVELOPE_RELATIVE_PATH
    ]
    assert (ROOT / RECEIPT_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        RECEIPT_RELATIVE_PATH
    ]
    assert (ROOT / DECISION_RELATIVE_PATH).read_bytes() == closure.after_bytes[
        DECISION_RELATIVE_PATH
    ]
    events = load_promotion_ledger(ROOT / layout.ledger)
    assert [event.state for event in events] == ["reserved", "applied"]
    assert events[0].decision_id == DECISION_ID
    assert events[0].promotion_intent_digest == events[1].promotion_intent_digest
    assert events[0].catalog_before_digest == closure.preview.catalog_before_digest
    assert events[1].catalog_after_digest == closure.preview.catalog_after_digest
