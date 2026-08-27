"""P-lane promotion preview, durable ledger, lock, apply, and recovery."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from openopps.discovery.identity import candidate_identity_id, normalize_candidate_identity
from openopps.discovery.models import (
    BoundedReason,
    EvaluationAxes,
    TerminalEvaluation,
)
from openopps.discovery.policy import bind_v7_policy_digests
from openopps.discovery.promotion import (
    EnvelopeValidationError,
    PromotionCandidate,
    PromotionDecisionError,
    PromotionLedgerError,
    PromotionPreviewError,
    bind_catalog_fingerprints,
    bind_policy_input_digests,
    build_approved_envelope,
    build_evidence_receipt,
    build_promotion_selection,
    compute_promotion_intent_digest,
    preview_promotion,
    render_preview_delta,
    revalidate_selected_candidates,
    reverify_promotion_bundle,
    validate_promotion_decision,
)
from openopps.discovery.promotion_runtime import (
    DEFAULT_OWNED_PATHS,
    ApplyInterrupt,
    HistoryAvailabilityError,
    PromotionApplyError,
    PromotionLayout,
    PromotionLockError,
    RecoveryAction,
    acquire_promotion_lock,
    apply_promotion,
    assert_zero_drift,
    compare_cas,
    load_promotion_ledger,
    observe_cas_state,
    recover_promotion,
    reject_ledger_deletion,
    require_maintainer_mutation,
    reserve_promotion,
    revoke_promotion,
    run_generation_closure,
    stage_after_tree,
)


HEAD = "a" * 40
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
DISCOVERY = Path(__file__).resolve().parents[4] / "src" / "openopps" / "discovery"
LEDGER_PATH = (
    DISCOVERY / "data" / "promotion_decision_ledger.jsonl"
)


def _sha(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return sha256(payload).hexdigest()


def _v7():
    return bind_v7_policy_digests(
        policy_code=b"policy-code\n",
        policy_schema=b"{}\n",
        policy_evidence=b'{"decisions":[]}\n',
        policy_corpus=b'{"sourceKeys":[]}\n',
        public_selector=b"selector-bytes\n",
    )


def _fingerprint(entries: list[dict[str, object]]) -> str:
    payload = json.dumps(
        entries,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _catalog(entries: list[dict[str, object]]) -> bytes:
    ordered = sorted(entries, key=lambda item: str(item["key"]))
    rendered = {
        "count": len(ordered),
        "entries": ordered,
        "fingerprint": _fingerprint(ordered),
        "version": 2,
    }
    return json.dumps(
        rendered, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _entry(key: str, url: str, provider: str = "greenhouse") -> dict[str, object]:
    return {
        "key": key,
        "provider_id": provider,
        "raw_metadata": {"label": key},
        "url": url,
        "version": {"schema": "v1"},
    }


def _identity(**updates: object):
    values = {
        "key": "acme",
        "url": "https://jobs.example.test/acme",
        "provider_id": "greenhouse",
        "provider_token": "acme",
        "owner": "official",
    }
    values.update(updates)
    return normalize_candidate_identity(**values)


def _evaluation(identity, **axis_updates: object) -> TerminalEvaluation:
    axes_values = {
        "liveness": "live",
        "support": "supported",
        "policy": "allowed",
        "taxonomy": "complete",
        "already_approved": False,
    }
    axes_values.update(axis_updates)
    axes = EvaluationAxes(**axes_values)
    disposition = "promotable"
    if axes.policy == "blocked":
        disposition = "blocked"
    elif (
        axes.liveness == "inconclusive"
        or axes.support == "inconclusive"
        or axes.policy == "unresolved"
        or axes.taxonomy == "incomplete"
    ):
        disposition = "inconclusive"
    elif axes.support == "unsupported":
        disposition = "unsupported"
    elif axes.already_approved:
        disposition = "already_approved"
    return TerminalEvaluation(
        candidate_id=candidate_identity_id(identity),
        axes=axes,
        disposition=disposition,
        eligible_for_review=disposition == "promotable",
        reason_codes=() if disposition == "promotable" else (BoundedReason.EVIDENCE_INCOMPLETE,),
    )


def _candidate(**updates: object) -> PromotionCandidate:
    identity = _identity(**updates)
    return PromotionCandidate(identity=identity, evaluation=_evaluation(identity))


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src/openopps/discovery/data").mkdir(parents=True)
    (root / "var/openopps").mkdir(parents=True)
    (root / "src/openopps/discovery/data/promotion_decision_ledger.jsonl").write_bytes(
        b""
    )
    return root


def test_committed_ledger_is_reserved_then_applied() -> None:
    assert LEDGER_PATH.is_file()
    events = load_promotion_ledger(LEDGER_PATH)
    assert [event.state for event in events] == ["reserved", "applied"]
    assert events[0].decision_id == "b699-identity-closure-20260822"
    assert events[0].event_digest == events[1].predecessor_digest


def test_selection_requires_sorted_unique_candidate_ids() -> None:
    digest = _sha("manifest")
    selection = build_promotion_selection(digest, ("aaa", "bbb"))
    assert selection.manifest_digest == digest
    assert selection.candidate_ids == ("aaa", "bbb")
    with pytest.raises(PromotionPreviewError, match="sorted"):
        build_promotion_selection(digest, ("bbb", "aaa"))
    with pytest.raises(PromotionPreviewError, match="unique|sorted"):
        build_promotion_selection(digest, ("aaa", "aaa"))
    empty = build_promotion_selection(digest, ())
    assert empty.candidate_ids == ()



def test_reverify_requires_exact_manifest_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Verified:
        manifest_id = "0" * 64

    monkeypatch.setattr(
        "openopps.discovery.promotion.verify_bundle",
        lambda root, policy: _Verified(),
    )
    from datetime import timedelta
    from openopps.discovery.bundle import BundleVerificationPolicy

    policy = BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=48),
        now=NOW,
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({("quarantine-evaluation", "v1")}),
        supported_schema_versions=frozenset({"openopps.discovery.bundle.v1"}),
        required_member_roles=frozenset({"evidence"}),
        supported_member_roles=frozenset({"evidence"}),
        canonical_json_roles=frozenset(),
    )
    verified = reverify_promotion_bundle(
        Path("unused"),
        policy=policy,
        expected_manifest_digest="0" * 64,
    )
    assert verified.manifest_id == "0" * 64
    with pytest.raises(PromotionPreviewError, match="manifest"):
        reverify_promotion_bundle(
            Path("unused"),
            policy=policy,
            expected_manifest_digest="1" * 64,
        )


def test_revalidate_rejects_blocked_incomplete_and_colliding_candidates() -> None:
    good = _candidate()
    revalidate_selected_candidates((good,), selected_ids=(good.candidate_id,))
    blocked = PromotionCandidate(
        identity=good.identity,
        evaluation=_evaluation(good.identity, policy="blocked"),
    )
    with pytest.raises(PromotionPreviewError, match="blocked|eligible"):
        revalidate_selected_candidates(
            (blocked,), selected_ids=(blocked.candidate_id,)
        )
    incomplete = PromotionCandidate(
        identity=good.identity,
        evaluation=_evaluation(good.identity, taxonomy="incomplete"),
    )
    with pytest.raises(PromotionPreviewError, match="taxonomy|eligible"):
        revalidate_selected_candidates(
            (incomplete,), selected_ids=(incomplete.candidate_id,)
        )


def test_preview_is_byte_identical_and_does_not_write(
    tmp_path: Path,
) -> None:
    catalog = _catalog(
        [_entry("existing", "https://jobs.example.test/existing")]
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    kwargs = dict(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=catalog,
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(_identity(key="existing", url="https://jobs.example.test/existing", provider_token="existing"),),
        existing_owner_by_key={"existing": "openopps.providers.sources"},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    first = preview_promotion(**kwargs)
    second = preview_promotion(**kwargs)
    assert first.delta == second.delta
    assert first.catalog_after == second.catalog_after
    assert first.intent == second.intent
    assert first.proposed_records[0].package_owner == "openopps.providers.sources"
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after


def test_preview_rejects_key_and_module_owner_collisions() -> None:
    catalog = _catalog([_entry("acme", "https://jobs.example.test/acme")])
    with pytest.raises(PromotionPreviewError, match="collision"):
        preview_promotion(
            manifest_digest=_sha("manifest"),
            candidates=(_candidate(),),
            catalog_before=catalog,
            v7=_v7(),
            head_sha=HEAD,
            package_owner="openopps.providers.sources",
            existing_identities=(_identity(),),
            existing_owner_by_key={"acme": "other.module"},
            resources_digest=_sha("resources"),
            profile_digest=_sha("profile"),
        )


def test_policy_input_digest_binds_v7_and_separate_decision() -> None:
    v7 = _v7()
    without_decision = bind_policy_input_digests(v7)
    with_decision = bind_policy_input_digests(
        v7, positive_decision_digest=_sha("decision")
    )
    assert without_decision != with_decision
    fingerprint, file_digest, keys = bind_catalog_fingerprints(
        _catalog([_entry("existing", "https://jobs.example.test/existing")])
    )
    assert fingerprint
    assert file_digest == _sha(
        _catalog([_entry("existing", "https://jobs.example.test/existing")])
    )
    assert keys == ("existing",)


def test_preview_delta_is_canonical_and_order_independent() -> None:
    first = render_preview_delta(
        {"b": b"1", "a": b"0"},
        {"a": b"2", "b": b"1"},
    )
    second = render_preview_delta(
        {"a": b"0", "b": b"1"},
        {"b": b"1", "a": b"2"},
    )
    assert first == second
    assert first.endswith(b"\n")


def test_receipt_is_evidence_only() -> None:
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    payload = preview.intent.model_dump(mode="json", by_alias=True)
    payload.update(
        {
            "schemaVersion": 1,
            "decisionId": "maintainer-1",
            "promotionIntentDigest": compute_promotion_intent_digest(preview.intent),
        }
    )
    decision = validate_promotion_decision(
        payload, expected_intent=preview.intent, invocation_mode="maintainer"
    )
    receipt = build_evidence_receipt(decision, validated_at=NOW)
    assert receipt.grants_authority is False
    with pytest.raises(PromotionDecisionError, match="maintainer"):
        validate_promotion_decision(
            payload, expected_intent=preview.intent, invocation_mode="scout"
        )


def test_envelope_rejects_forbidden_key_classes() -> None:
    v7 = _v7()
    envelope = build_approved_envelope(
        source_keys=("acme", "existing"),
        packaged_catalog_fingerprint=_sha("fp"),
        catalog_content_digest=_sha("content"),
        catalog_tree_digest=_sha("tree"),
        v7=v7,
        supplementary_policy_digest=_sha("decision"),
        promotion_digest=_sha("promotion"),
        key_classes={"acme": "owned", "existing": "owned"},
    )
    assert envelope.source_count == 2
    assert "sourceSelector" not in envelope.model_dump(by_alias=True)
    with pytest.raises(EnvelopeValidationError, match="forbidden"):
        build_approved_envelope(
            source_keys=("acme",),
            packaged_catalog_fingerprint=_sha("fp"),
            catalog_content_digest=_sha("content"),
            catalog_tree_digest=_sha("tree"),
            v7=v7,
            supplementary_policy_digest=_sha("decision"),
            promotion_digest=_sha("promotion"),
            key_classes={"acme": "quarantined"},
        )
    with pytest.raises(EnvelopeValidationError, match="selector"):
        build_approved_envelope(
            source_keys=("acme",),
            packaged_catalog_fingerprint=_sha("fp"),
            catalog_content_digest=_sha("content"),
            catalog_tree_digest=_sha("tree"),
            v7=v7,
            supplementary_policy_digest=_sha("decision"),
            promotion_digest=v7.public_selector_sha256 or _sha("x"),
            key_classes={"acme": "owned"},
        )


def test_ledger_load_fails_closed_on_incomplete_and_shallow_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "promotion_decision_ledger.jsonl"
    path.write_bytes(b'{"sequence":1}\npartial')
    with pytest.raises(PromotionLedgerError, match="incomplete"):
        load_promotion_ledger(path)
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    with pytest.raises(HistoryAvailabilityError, match="unavailable"):
        load_promotion_ledger(empty, history_status="shallow")
    with pytest.raises(HistoryAvailabilityError, match="unavailable"):
        load_promotion_ledger(empty, history_status="rewritten")


def test_scout_cannot_reserve_apply_recover_or_revoke() -> None:
    with pytest.raises(PromotionDecisionError, match="maintainer"):
        require_maintainer_mutation("scout")
    with pytest.raises(PromotionDecisionError, match="maintainer"):
        require_maintainer_mutation("verify")
    with pytest.raises(PromotionDecisionError, match="maintainer"):
        require_maintainer_mutation("ci")


def test_lock_contention_and_killed_holder_recovery(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with acquire_promotion_lock(root, operation="reserve", nonce="one"):
        with pytest.raises(PromotionLockError, match="held"):
            with acquire_promotion_lock(root, operation="reserve", nonce="two"):
                raise AssertionError("lock was stolen")
    stale = root / "var/openopps/promotion.lock"
    stale.write_bytes(b'{"startNs":1,"nonce":"old"}\n')
    with acquire_promotion_lock(root, operation="reserve", nonce="fresh"):
        pass


def test_reserve_apply_and_stale_second_apply(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    catalog_fp = preview.catalog_before_digest
    expected = observe_cas_state(
        root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
    )
    reserved = reserve_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=catalog_fp,
        expected_cas=expected,
        committed_events=(),
        layout=layout,
    )
    assert reserved.state == "reserved"
    working = load_promotion_ledger(root / layout.ledger)
    assert len(working) == 1
    with pytest.raises(PromotionLedgerError, match="committed"):
        apply_promotion(
            root,
            decision_id="decision-1",
            intent=preview.intent,
            invocation_mode="maintainer",
            head_sha=HEAD,
            catalog_fingerprint=catalog_fp,
            expected_cas=observe_cas_state(
                root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
            ),
            after_bytes={},
            committed_events=(),
            lock_nonce="nonce-apply",
            layout=layout,
        )
    expected_apply = observe_cas_state(
        root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
    )
    envelope = build_approved_envelope(
        source_keys=("acme", "existing"),
        packaged_catalog_fingerprint=_sha("fp"),
        catalog_content_digest=preview.catalog_after_digest,
        catalog_tree_digest=preview.catalog_after_digest,
        v7=_v7(),
        supplementary_policy_digest=_sha("decision"),
        promotion_digest=preview.promotion_digest,
        key_classes={"acme": "owned", "existing": "owned"},
    )
    receipt = build_evidence_receipt(
        {
            **preview.intent.model_dump(mode="json", by_alias=True),
            "schemaVersion": 1,
            "decisionId": "decision-1",
            "promotionIntentDigest": compute_promotion_intent_digest(preview.intent),
        },
        validated_at=NOW,
    )
    after_bytes = {
        layout.envelope: envelope.model_dump_json(by_alias=True).encode() + b"\n",
        layout.receipt: receipt.model_dump_json(by_alias=True).encode() + b"\n",
    }
    # model_dump_json may not be canonical; use preview helpers' canonical encoder via dump
    from openopps.discovery.canonical import canonical_json_bytes

    after_bytes = {
        layout.envelope: canonical_json_bytes(
            envelope.model_dump(mode="json", by_alias=True)
        ),
        layout.receipt: canonical_json_bytes(
            receipt.model_dump(mode="json", by_alias=True)
        ),
    }
    journal = apply_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=catalog_fp,
        expected_cas=expected_apply,
        after_bytes=after_bytes,
        committed_events=working,
        lock_nonce="nonce-apply",
        layout=layout,
    )
    assert journal.phase == "finalizing"
    applied = load_promotion_ledger(
        root / layout.ledger, committed_events=working
    )
    assert [event.state for event in applied] == ["reserved", "applied"]
    assert (root / layout.envelope).is_file()
    assert (root / layout.receipt).is_file()
    snapshots = {
        path: (root / path).read_bytes()
        for path in (*DEFAULT_OWNED_PATHS,)
        if (root / path).exists()
    }
    with pytest.raises(PromotionLedgerError):
        apply_promotion(
            root,
            decision_id="decision-1",
            intent=preview.intent,
            invocation_mode="maintainer",
            head_sha=HEAD,
            catalog_fingerprint=catalog_fp,
            expected_cas=observe_cas_state(
                root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
            ),
            after_bytes=after_bytes,
            committed_events=applied,
            lock_nonce="nonce-stale",
            layout=layout,
        )
    for path, payload in snapshots.items():
        assert (root / path).read_bytes() == payload


def test_generation_closure_and_crash_restore(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    catalog_fp = preview.catalog_before_digest
    reserved = reserve_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
        ),
        committed_events=(),
        layout=layout,
    )
    from openopps.discovery.canonical import canonical_json_bytes

    after_bytes = {
        layout.envelope: canonical_json_bytes({"k": 1}),
        layout.receipt: canonical_json_bytes({"k": 2}),
    }
    with pytest.raises(ApplyInterrupt):
        apply_promotion(
            root,
            decision_id="decision-1",
            intent=preview.intent,
            invocation_mode="maintainer",
            head_sha=HEAD,
            catalog_fingerprint=catalog_fp,
            expected_cas=observe_cas_state(
                root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
            ),
            after_bytes=after_bytes,
            committed_events=(reserved,),
            lock_nonce="nonce-crash",
            layout=layout,
            crash_at="journal_applying",
        )
    action = recover_promotion(
        root,
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
        ),
        committed_events=(reserved,),
        decision_id="decision-1",
        layout=layout,
    )
    assert action is RecoveryAction.RESTORE_AND_REVOKE
    events = load_promotion_ledger(root / layout.ledger)
    assert events[-1].state == "revoked"
    assert not (root / layout.envelope).exists()
    runs = {"count": 0}

    def runner(_staged: Path) -> dict[str, bytes]:
        runs["count"] += 1
        return {layout.receipt: canonical_json_bytes({"k": 2})}

    assert run_generation_closure(runner, root)[layout.receipt]
    assert runs["count"] == 2
    with pytest.raises(PromotionApplyError, match="byte-identical"):
        run_generation_closure(
            lambda staged: {layout.receipt: os.urandom(4)},
            root,
        )


def test_competing_reservation_same_head_catalog(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    first = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    catalog_fp = first.catalog_before_digest
    reserve_promotion(
        root,
        decision_id="decision-1",
        intent=first.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
        ),
        committed_events=(),
        layout=layout,
    )
    second = preview_promotion(
        manifest_digest=_sha("manifest-2"),
        candidates=(_candidate(key="other", url="https://jobs.example.test/other", provider_token="other"),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources-2"),
        profile_digest=_sha("profile-2"),
    )
    with pytest.raises(PromotionLedgerError, match="HEAD|catalog|reservation"):
        reserve_promotion(
            root,
            decision_id="decision-2",
            intent=second.intent,
            invocation_mode="maintainer",
            head_sha=HEAD,
            catalog_fingerprint=catalog_fp,
            expected_cas=observe_cas_state(
                root, head_sha=HEAD, catalog_fingerprint=catalog_fp, layout=layout
            ),
            committed_events=(),
            layout=layout,
        )


def test_inconsistent_history_and_ledger_deletion_fail_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    reserved = reserve_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=preview.catalog_before_digest,
        expected_cas=observe_cas_state(
            root,
            head_sha=HEAD,
            catalog_fingerprint=preview.catalog_before_digest,
            layout=layout,
        ),
        committed_events=(),
        layout=layout,
    )
    current = load_promotion_ledger(root / layout.ledger, committed_events=())
    assert current == (reserved,)
    forged = reserved.model_copy(update={"decision_id": "forged"})
    with pytest.raises(HistoryAvailabilityError, match="inconsistent"):
        load_promotion_ledger(root / layout.ledger, committed_events=(forged,))
    with pytest.raises(PromotionLedgerError, match="deletion"):
        reject_ledger_deletion()


def test_cas_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    observed = observe_cas_state(
        root, head_sha=HEAD, catalog_fingerprint=_sha("catalog")
    )
    expected = observed.model_copy(update={"head_sha": "b" * 40})
    with pytest.raises(PromotionLockError, match="compare-and-swap"):
        compare_cas(observed, expected)


def test_apply_changes_only_owned_paths(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    outsider = root / "README.md"
    outsider.write_text("keep\n", encoding="utf-8")
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    reserved = reserve_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=preview.catalog_before_digest,
        expected_cas=observe_cas_state(
            root,
            head_sha=HEAD,
            catalog_fingerprint=preview.catalog_before_digest,
            layout=layout,
        ),
        committed_events=(),
        layout=layout,
    )
    from openopps.discovery.canonical import canonical_json_bytes

    after_bytes = {
        layout.envelope: canonical_json_bytes({"envelope": True}),
        layout.receipt: canonical_json_bytes({"receipt": True}),
    }
    apply_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=preview.catalog_before_digest,
        expected_cas=observe_cas_state(
            root,
            head_sha=HEAD,
            catalog_fingerprint=preview.catalog_before_digest,
            layout=layout,
        ),
        after_bytes=after_bytes,
        committed_events=(reserved,),
        lock_nonce="nonce-owned",
        layout=layout,
    )
    assert outsider.read_text(encoding="utf-8") == "keep\n"
    applied_ledger = (root / layout.ledger).read_bytes()
    assert_zero_drift(
        root,
        {
            **after_bytes,
            layout.ledger: applied_ledger,
        },
    )


def test_revoke_appends_without_git_and_retains_history(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    layout = PromotionLayout()
    preview = preview_promotion(
        manifest_digest=_sha("manifest"),
        candidates=(_candidate(),),
        catalog_before=_catalog(
            [_entry("existing", "https://jobs.example.test/existing")]
        ),
        v7=_v7(),
        head_sha=HEAD,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=_sha("resources"),
        profile_digest=_sha("profile"),
    )
    reserved = reserve_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=preview.catalog_before_digest,
        expected_cas=observe_cas_state(
            root,
            head_sha=HEAD,
            catalog_fingerprint=preview.catalog_before_digest,
            layout=layout,
        ),
        committed_events=(),
        layout=layout,
    )
    revoked = revoke_promotion(
        root,
        decision_id="decision-1",
        intent=preview.intent,
        invocation_mode="maintainer",
        head_sha=HEAD,
        catalog_fingerprint=preview.catalog_before_digest,
        expected_cas=observe_cas_state(
            root,
            head_sha=HEAD,
            catalog_fingerprint=preview.catalog_before_digest,
            layout=layout,
        ),
        committed_events=(reserved,),
        layout=layout,
    )
    events = load_promotion_ledger(
        root / layout.ledger, committed_events=(reserved,)
    )
    assert [event.state for event in events] == ["reserved", "revoked"]
    assert events[0].event_digest == reserved.event_digest
    assert revoked.state == "revoked"


def test_promotion_modules_stay_isolated_from_ops_and_positive_policy_axes() -> None:
    forbidden = {
        "openopps.cache",
        "openopps.cli",
        "openopps.http",
        "openopps.ingest",
        "openopps.plugins",
        "openopps.providers",
        "openopps.storage",
        "sqlite3",
        "subprocess",
    }
    for name in ("promotion.py", "promotion_runtime.py", "promotion_closure.py"):
        source = (DISCOVERY / name).read_text(encoding="utf-8")
        assert "positive_policy_axes" not in source or "never accepts" in source
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert imported.isdisjoint(forbidden)
        assert "git" not in imported


def test_stage_rejects_paths_outside_allowlist(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(PromotionApplyError, match="allowlist"):
        stage_after_tree(
            root,
            {"src/openopps/providers/sources/data/portfolio_source_catalog.json": b"{}\n"},
            allowlist=DEFAULT_OWNED_PATHS,
        )
