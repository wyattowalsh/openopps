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
    READONLY_WHEEL_PATHS,
    SHARED_DELIVERY_OWNED_PATHS,
    SHARED_DELIVERY_WHEEL_MEMBERS,
    PromotionLayout,
    PromotionLedgerError,
    apply_promotion,
    observe_cas_state,
    require_maintainer_mutation,
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


def apply_shared_delivery_closure(*args: object, **kwargs: object) -> ApplyJournal:
    raise PromotionLedgerError(
        "refusing combined reserve+apply Git delivery; "
        "use reserve_shared_delivery_closure then "
        "apply_reserved_shared_delivery_closure with the full committed prefix"
    )


def reserve_shared_delivery_closure(
    repository_root: Path,
    *,
    head_sha: str,
    decision_id: str,
    invocation_mode: str,
    committed_events: Sequence[PromotionLedgerEvent],
    validated_at: datetime | None = None,
    layout: PromotionLayout = PromotionLayout(),
) -> tuple[SharedDeliveryClosure, PromotionLedgerEvent]:
    require_maintainer_mutation(invocation_mode)
    if decision_id == DECISION_ID:
        raise PromotionLedgerError("refusing replay of b699-identity-closure-20260822")
    built = build_shared_delivery_closure(
        repository_root,
        head_sha=head_sha,
        decision_id=decision_id,
        validated_at=validated_at or datetime.now(UTC),
    )
    catalog_fp = built.preview.catalog_before_digest
    reserved = reserve_promotion(
        repository_root,
        decision_id=built.decision_id,
        intent=built.preview.intent,
        invocation_mode=invocation_mode,
        head_sha=head_sha,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            repository_root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fp,
            layout=layout,
            owned_paths=SHARED_DELIVERY_OWNED_PATHS,
        ),
        committed_events=committed_events,  # prefix BEFORE this reservation
        layout=layout,
        owned_paths=SHARED_DELIVERY_OWNED_PATHS,
    )
    return built, reserved


def apply_reserved_shared_delivery_closure(
    repository_root: Path,
    *,
    head_sha: str,
    decision_id: str,
    invocation_mode: str,
    lock_nonce: str,
    committed_events: Sequence[PromotionLedgerEvent],
    closure: SharedDeliveryClosure,
    layout: PromotionLayout = PromotionLayout(),
) -> ApplyJournal:
    require_maintainer_mutation(invocation_mode)
    if not committed_events:
        raise PromotionLedgerError("apply requires a committed reserved event")
    latest = committed_events[-1]
    if latest.decision_id != decision_id or latest.state != "reserved":
        raise PromotionLedgerError("apply requires a committed reserved event")
    catalog_fp = closure.preview.catalog_before_digest
    generated_bytes = closure.generated_bytes

    def generation_runner(_staged: Path) -> Mapping[str, bytes]:
        return {GENERATED_RELATIVE_PATH: generated_bytes}

    return apply_promotion(
        repository_root,
        decision_id=decision_id,
        intent=closure.preview.intent,
        invocation_mode=invocation_mode,
        head_sha=head_sha,
        catalog_fingerprint=catalog_fp,
        expected_cas=observe_cas_state(
            repository_root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fp,
            layout=layout,
            owned_paths=SHARED_DELIVERY_OWNED_PATHS,
        ),
        after_bytes=closure.after_bytes,
        committed_events=committed_events,  # FULL prefix including reserved
        lock_nonce=lock_nonce,
        allowlist=SHARED_DELIVERY_OWNED_PATHS,
        layout=layout,
        generation_runner=generation_runner,
        wheel_members=SHARED_DELIVERY_WHEEL_MEMBERS,
        readonly_wheel_bytes=closure.readonly_wheel_bytes,
    )
