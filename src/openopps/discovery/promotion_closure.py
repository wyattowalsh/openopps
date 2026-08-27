"""Shared-delivery identity closure for B699 catalog/generated bind."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.inventory import (
    DEFAULT_V7_POLICY_PATHS,
    read_packaged_catalog_bytes,
    read_repository_resources,
)
from openopps.discovery.models import (
    ApplyJournal,
    ApprovedIngestionSelectorEnvelope,
    EvidenceOnlyDecisionReceipt,
    PromotionLedgerEvent,
)
from openopps.discovery.policy import V7PolicyDigestBinding, bind_v7_policy_digests
from openopps.discovery.promotion import (
    PromotionPreview,
    bind_catalog_fingerprints,
    build_approved_envelope,
    build_evidence_receipt,
    compute_promotion_intent_digest,
    preview_promotion,
    validate_promotion_decision,
)
from openopps.discovery.promotion_runtime import (
    CATALOG_RELATIVE_PATH,
    GENERATED_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    READONLY_WHEEL_PATHS,
    SHARED_DELIVERY_OWNED_PATHS,
    SHARED_DELIVERY_WHEEL_MEMBERS,
    PromotionLayout,
    apply_promotion,
    assert_zero_drift,
    encode_promotion_ledger,
    load_promotion_ledger,
    observe_cas_state,
    reserve_promotion,
)


DECISION_ID = "b699-identity-closure-20260822"
CLOSURE_VALIDATED_AT = datetime(2026, 8, 22, 10, 50, tzinfo=UTC)
PROFILE_SCHEMA_RELATIVE_PATH = (
    "src/openopps/discovery/data/trusted-discovery-profile.schema.json"
)
DECISION_SCHEMA_RELATIVE_PATH = (
    "src/openopps/discovery/data/discovery-promotion-policy-decision.schema.json"
)
SCHEMA_MANIFEST_RELATIVE_PATH = "src/openopps/discovery/data/manifest.json"


@dataclass(frozen=True, slots=True)
class SharedDeliveryClosure:
    """Exact after-tree bytes for one catalog-identity shared-delivery apply."""

    preview: PromotionPreview
    decision: Mapping[str, object]
    receipt: EvidenceOnlyDecisionReceipt
    envelope: ApprovedIngestionSelectorEnvelope
    after_bytes: Mapping[str, bytes]
    readonly_wheel_bytes: Mapping[str, bytes]
    catalog_keys: tuple[str, ...]
    v7: V7PolicyDigestBinding
    decision_id: str
    generated_bytes: bytes


def _digest_file(repository_root: Path, relative: str) -> str:
    return sha256((repository_root / relative).read_bytes()).hexdigest()


def bind_repository_v7_policy(repository_root: Path) -> V7PolicyDigestBinding:
    """Hash the frozen v7 policy inputs without importing source_policy."""

    resources = read_repository_resources(repository_root, DEFAULT_V7_POLICY_PATHS)
    return bind_v7_policy_digests(
        policy_code=resources["policy_code"],
        policy_schema=resources["policy_schema"],
        policy_evidence=resources["policy_evidence"],
        policy_corpus=resources["policy_corpus"],
        public_selector=None,
    )


def compute_closure_digests(
    repository_root: Path,
    *,
    catalog: bytes,
    generated: bytes,
    v7: V7PolicyDigestBinding,
) -> tuple[str, str, str, str]:
    """Return manifest, resources, profile, and supplementary policy digests."""

    manifest_digest = _digest_file(repository_root, SCHEMA_MANIFEST_RELATIVE_PATH)
    resources_digest = sha256(
        canonical_json_bytes(
            {
                "catalogSha256": sha256(catalog).hexdigest(),
                "generatedSha256": sha256(generated).hexdigest(),
                "v7PolicyInputs": v7.as_dict(),
            }
        )
    ).hexdigest()
    profile_digest = _digest_file(repository_root, PROFILE_SCHEMA_RELATIVE_PATH)
    supplementary = _digest_file(repository_root, DECISION_SCHEMA_RELATIVE_PATH)
    return manifest_digest, resources_digest, profile_digest, supplementary


def build_shared_delivery_closure(
    repository_root: Path,
    *,
    head_sha: str,
    decision_id: str = DECISION_ID,
    validated_at: datetime = CLOSURE_VALIDATED_AT,
    layout: PromotionLayout = PromotionLayout(),
) -> SharedDeliveryClosure:
    """Bind the current packaged catalog into envelope, receipt, and decision."""

    root = Path(repository_root)
    catalog = (root / CATALOG_RELATIVE_PATH).read_bytes()
    generated = (root / GENERATED_RELATIVE_PATH).read_bytes()
    read_packaged_catalog_bytes(catalog)
    v7 = bind_repository_v7_policy(root)
    manifest_digest, resources_digest, profile_digest, supplementary = (
        compute_closure_digests(
            root, catalog=catalog, generated=generated, v7=v7
        )
    )
    fingerprint, file_digest, keys = bind_catalog_fingerprints(catalog)
    extra_after = {
        layout.generated: generated,
    }
    preview = preview_promotion(
        manifest_digest=manifest_digest,
        candidates=(),
        catalog_before=catalog,
        v7=v7,
        head_sha=head_sha,
        package_owner="openopps.providers.sources",
        existing_identities=(),
        existing_owner_by_key={},
        resources_digest=resources_digest,
        profile_digest=profile_digest,
        extra_after_paths=extra_after,
        extra_before_paths={layout.generated: generated},
    )
    if preview.catalog_after != catalog:
        raise ValueError("identity closure must preserve catalog bytes")
    if preview.catalog_before_digest != preview.catalog_after_digest:
        raise ValueError("identity closure catalog digests must match")
    envelope = build_approved_envelope(
        source_keys=keys,
        packaged_catalog_fingerprint=fingerprint,
        catalog_content_digest=file_digest,
        catalog_tree_digest=file_digest,
        v7=v7,
        supplementary_policy_digest=supplementary,
        promotion_digest=preview.promotion_digest,
    )
    intent_dump = preview.intent.model_dump(mode="json", by_alias=True)
    decision_payload = {
        "schemaVersion": 1,
        "decisionId": decision_id,
        "promotionIntentDigest": compute_promotion_intent_digest(preview.intent),
        **intent_dump,
    }
    decision = validate_promotion_decision(
        decision_payload,
        expected_intent=preview.intent,
        invocation_mode="maintainer",
    )
    receipt = build_evidence_receipt(decision, validated_at=validated_at)
    after_bytes = {
        layout.catalog: catalog,
        layout.decision: canonical_json_bytes(decision),
        layout.envelope: canonical_json_bytes(
            envelope.model_dump(mode="json", by_alias=True)
        ),
        layout.generated: generated,
        layout.receipt: canonical_json_bytes(
            receipt.model_dump(mode="json", by_alias=True)
        ),
    }
    readonly = read_repository_resources(root, READONLY_WHEEL_PATHS)
    readonly_wheel_bytes = {
        READONLY_WHEEL_PATHS[name]: payload for name, payload in readonly.items()
    }
    return SharedDeliveryClosure(
        preview=preview,
        decision=decision,
        receipt=receipt,
        envelope=envelope,
        after_bytes=after_bytes,
        readonly_wheel_bytes=readonly_wheel_bytes,
        catalog_keys=keys,
        v7=v7,
        decision_id=decision_id,
        generated_bytes=generated,
    )


def apply_shared_delivery_closure(
    repository_root: Path,
    *,
    head_sha: str,
    invocation_mode: str,
    lock_nonce: str,
    committed_events: Sequence[PromotionLedgerEvent] | None = None,
    closure: SharedDeliveryClosure | None = None,
    layout: PromotionLayout = PromotionLayout(),
) -> tuple[SharedDeliveryClosure, PromotionLedgerEvent, ApplyJournal]:
    """Reserve, then apply the identity closure under the promotion lock."""

    root = Path(repository_root)
    built = closure or build_shared_delivery_closure(root, head_sha=head_sha)
    catalog_fp = built.preview.catalog_before_digest
    expected = observe_cas_state(
        root,
        head_sha=head_sha,
        catalog_fingerprint=catalog_fp,
        layout=layout,
        owned_paths=SHARED_DELIVERY_OWNED_PATHS,
    )
    reserved = reserve_promotion(
        root,
        decision_id=built.decision_id,
        intent=built.preview.intent,
        invocation_mode=invocation_mode,
        head_sha=head_sha,
        catalog_fingerprint=catalog_fp,
        expected_cas=expected,
        committed_events=() if committed_events is None else committed_events,
        layout=layout,
        owned_paths=SHARED_DELIVERY_OWNED_PATHS,
    )
    generated_bytes = built.generated_bytes

    def generation_runner(_staged: Path) -> Mapping[str, bytes]:
        return {GENERATED_RELATIVE_PATH: generated_bytes}

    journal = apply_promotion(
        root,
        decision_id=built.decision_id,
        intent=built.preview.intent,
        invocation_mode=invocation_mode,
        head_sha=head_sha,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fp,
            layout=layout,
            owned_paths=SHARED_DELIVERY_OWNED_PATHS,
        ),
        after_bytes=built.after_bytes,
        committed_events=(reserved,),
        lock_nonce=lock_nonce,
        allowlist=SHARED_DELIVERY_OWNED_PATHS,
        layout=layout,
        generation_runner=generation_runner,
        wheel_members=SHARED_DELIVERY_WHEEL_MEMBERS,
        readonly_wheel_bytes=built.readonly_wheel_bytes,
    )
    applied_ledger = encode_promotion_ledger(
        load_promotion_ledger(root / layout.ledger, committed_events=(reserved,))
    )
    assert_zero_drift(
        root,
        {
            **built.after_bytes,
            LEDGER_RELATIVE_PATH: applied_ledger,
        },
        generation_runner=generation_runner,
        wheel_members=SHARED_DELIVERY_WHEEL_MEMBERS,
    )
    return built, reserved, journal
