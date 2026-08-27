"""CLI-neutral discovery library entry points for skills, commands, and tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeVar
from uuid import uuid4

from openopps.discovery.bundle import (
    MANIFEST_NAME,
    BundleManifestError,
    BundleVerificationError,
    BundleVerificationPolicy,
    VerifiedBundle,
    verify_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.diagnostics import (
    BoundedDiagnostic,
    render_bounded_diagnostic,
)
from openopps.discovery.evaluation import (
    EVALUATION_BUNDLE_PROFILE,
    evaluate_occurrences,
    write_evaluation_bundle,
)
from openopps.discovery.identity import normalize_candidate_identity
from openopps.discovery.inventory import (
    DEFAULT_V7_POLICY_PATHS,
    ApprovedRuntimeCatalogInventory,
    InventoryError,
    PackagedCatalogReadback,
    RepositoryIdentityProjection,
    build_approved_runtime_catalog_inventory,
    project_repository_identities,
    read_repository_resources,
)
from openopps.discovery.models import (
    BoundedReason,
    CandidateIdentity,
    ChannelReplayReceipt,
    StrictDiscoveryModel,
)
from openopps.discovery.policy import bind_v7_policy_digests
from openopps.discovery.schemas import (
    DEFAULT_SCHEMA_ROOT,
    discovery_schema_models,
    render_discovery_schema_files,
    schema_file_name,
    validate_discovery_schema_files,
)
from openopps.discovery.settings import DiscoverySettings


ModelT = TypeVar("ModelT", bound=StrictDiscoveryModel)


def encode_discovery_model(model: StrictDiscoveryModel) -> bytes:
    """Encode a validated strict model using canonical artifact bytes."""

    if not isinstance(model, StrictDiscoveryModel):
        raise TypeError("discovery artifact must be a strict discovery model")
    return canonical_json_bytes(
        model.model_dump(mode="json", by_alias=True, round_trip=True)
    )


def decode_discovery_model(
    model_type: type[ModelT],
    raw: bytes,
) -> ModelT:
    """Require canonical alias-only bytes, then validate one strict model."""

    if model_type not in discovery_schema_models().values():
        raise TypeError("model type is not a registered discovery contract")
    payload = decode_canonical_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("discovery model payload must be a JSON object")
    return model_type.model_validate_json(
        raw,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def encode_channel_replay_receipt(receipt: ChannelReplayReceipt) -> bytes:
    """Encode one validated channel receipt without CLI or runtime imports."""

    if not isinstance(receipt, ChannelReplayReceipt):
        raise TypeError("channel receipt must be a ChannelReplayReceipt")
    return encode_discovery_model(receipt)


def decode_channel_replay_receipt(raw: bytes) -> ChannelReplayReceipt:
    """Decode canonical alias-only bytes for one channel replay receipt."""

    return decode_discovery_model(ChannelReplayReceipt, raw)


def discovery_schema_bytes(model_name: str) -> bytes:
    """Return the canonical generated schema bytes for one registered model."""

    if model_name not in discovery_schema_models():
        raise KeyError("unknown discovery model schema")
    return render_discovery_schema_files()[schema_file_name(model_name)]


def assure_discovery_schemas(
    schema_root: Path = DEFAULT_SCHEMA_ROOT,
) -> None:
    """Read-only assurance that committed schemas equal current model output."""

    validate_discovery_schema_files(schema_root)


def inspect_approved_runtime_catalog(
    *,
    source_records: Iterable[object],
    source_owner_rows: Iterable[Sequence[str]],
    adapter_identity_rows: Iterable[Sequence[str]],
    packaged_catalog: PackagedCatalogReadback,
) -> ApprovedRuntimeCatalogInventory:
    """Return a digest-only approved inventory from explicitly supplied inputs."""

    return build_approved_runtime_catalog_inventory(
        source_records=source_records,
        source_owner_rows=source_owner_rows,
        adapter_identity_rows=adapter_identity_rows,
        packaged_catalog=packaged_catalog,
    )


def project_read_only_identities(
    *,
    v7_policy_inputs: Mapping[str, bytes | None],
    public_selector: bytes | None,
    shared_generated_data: Mapping[str, bytes | None],
    embedded_wheel_resources: Mapping[str, bytes | None],
    discovery_owned: Mapping[str, bytes | None],
) -> RepositoryIdentityProjection:
    """Return digest-only identities for frozen v7 and discovery surfaces."""

    return project_repository_identities(
        v7_policy_inputs=v7_policy_inputs,
        public_selector=public_selector,
        shared_generated_data=shared_generated_data,
        embedded_wheel_resources=embedded_wheel_resources,
        discovery_owned=discovery_owned,
    )


def normalize_discovery_candidate(
    *,
    key: str,
    url: str,
    provider_id: str,
    provider_token: str | None,
    owner: str,
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"] = "source",
    adapter_id: str | None = None,
) -> CandidateIdentity:
    """Normalize one candidate without network, persistence, or plugin access."""

    return normalize_candidate_identity(
        key=key,
        url=url,
        provider_id=provider_id,
        provider_token=provider_token,
        owner=owner,
        candidate_kind=candidate_kind,
        adapter_id=adapter_id,
    )


def verify_quarantine_bundle(
    root: Path,
    *,
    policy: BundleVerificationPolicy,
) -> VerifiedBundle:
    """Run the shared hostile offline verifier without activating candidates."""

    return verify_bundle(root, policy=policy)


def render_discovery_diagnostic(
    reason_code: BoundedReason,
    *,
    detail: str | bytes | None = None,
) -> BoundedDiagnostic:
    """Return the shared bounded diagnostic used by library consumers."""

    return render_bounded_diagnostic(reason_code, detail=detail)


class ScoutCommandError(ValueError):
    """Bounded scout/verify failure that never activates or promotes."""

    def __init__(
        self,
        reason: BoundedReason,
        *,
        command: str,
        detail: str | None = None,
    ) -> None:
        self.reason = reason
        self.command = command
        self.detail = detail
        super().__init__(reason.value)


def evaluation_bundle_verification_policy(
    *,
    now: datetime,
) -> BundleVerificationPolicy:
    """Trusted policy for evaluation quarantine bundles written by scout."""

    clock = now.astimezone(UTC)
    return BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=48),
        now=clock,
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({EVALUATION_BUNDLE_PROFILE}),
        supported_schema_versions=frozenset({"openopps.discovery.bundle.v1"}),
        required_member_roles=frozenset({"evidence"}),
        supported_member_roles=frozenset({"evidence"}),
        canonical_json_roles=frozenset(),
    )


def run_offline_quarantine_scout(
    output_root: Path,
    *,
    repository_root: Path,
    now: datetime | None = None,
    execution_id: str | None = None,
) -> dict[str, object]:
    """Write one evaluation quarantine bundle without activating candidates.

    The scout does not open SQLite, Git, Kaggle, or catalog writers. Channel
    enumeration stays replay-library-only; this entry point evaluates an empty
    occurrence set against read-only v7 policy digests and publishes the
    exact bundle under ``output_root``.
    """

    command = "scout"
    if not isinstance(output_root, Path) or not isinstance(repository_root, Path):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="scout paths must be pathlib.Path values",
        )
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    run_id = execution_id or f"cli-{uuid4().hex}"
    try:
        policy_bytes = read_repository_resources(
            repository_root, DEFAULT_V7_POLICY_PATHS
        )
        v7_binding = bind_v7_policy_digests(
            policy_code=policy_bytes["policy_code"],
            policy_schema=policy_bytes["policy_schema"],
            policy_evidence=policy_bytes["policy_evidence"],
            policy_corpus=policy_bytes["policy_corpus"],
            public_selector=None,
        )
        settings_payload = DiscoverySettings().model_dump(mode="json")
        configuration_sha256 = sha256(
            canonical_json_bytes(
                {
                    "discoverySettings": settings_payload,
                    "v7Policy": v7_binding.as_dict(),
                }
            )
        ).hexdigest()
        result = evaluate_occurrences(
            (),
            approved_catalog=(),
            taxonomies={},
            v7_binding=v7_binding,
            evidence_bytes=policy_bytes["policy_evidence"],
            observed_at=clock,
            source_adapter_ids=(),
        )
        published = write_evaluation_bundle(
            output_root,
            result,
            v7_binding=v7_binding,
            observed_at=clock,
            configuration_sha256=configuration_sha256,
            execution_id=run_id,
            now=clock,
        )
    except ScoutCommandError:
        raise
    except InventoryError as error:
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail=str(error),
        ) from error
    except (OSError, TypeError, ValueError) as error:
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail=str(error),
        ) from error
    accounting = result.accounting.model_dump(
        mode="json", by_alias=True, round_trip=True
    )
    return {
        "accounting": accounting,
        "activated": False,
        "bundleRoot": str(published),
        "command": command,
        "eligibleForReview": result.accounting.promotable,
        "executionId": run_id,
        "manifestId": published.name,
        "manifestPath": str(published / MANIFEST_NAME),
        "outputDirectory": str(output_root),
        "promoted": False,
        "status": "complete",
    }


def verify_scout_manifest_path(
    manifest: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Offline-verify one quarantine bundle. Never rewrite, repair, or activate."""

    command = "verify-scout"
    try:
        root = _bundle_root_from_manifest(manifest, command=command)
        verified = verify_quarantine_bundle(
            root,
            policy=evaluation_bundle_verification_policy(now=now or datetime.now(UTC)),
        )
    except ScoutCommandError:
        raise
    except (BundleManifestError, BundleVerificationError) as error:
        raise ScoutCommandError(
            _verify_reason(error),
            command=command,
            detail=str(error),
        ) from error
    except (OSError, TypeError, ValueError) as error:
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail=str(error),
        ) from error
    return {
        "activated": False,
        "command": command,
        "manifestId": verified.manifest_id,
        "memberPaths": list(verified.member_paths),
        "profileId": verified.profile_id,
        "promoted": False,
        "status": "verified",
    }


def _bundle_root_from_manifest(
    manifest: Path,
    *,
    command: str = "verify-scout",
) -> Path:
    if not isinstance(manifest, Path):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="manifest path must be a pathlib.Path",
        )
    path = manifest.expanduser()
    if path.is_dir():
        return path
    if path.name != MANIFEST_NAME:
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail=f"{command} requires manifest.json or a bundle directory",
        )
    return path.parent


def _verify_reason(error: Exception) -> BoundedReason:
    text = str(error).casefold()
    if "stale" in text or "fresh" in text:
        return BoundedReason.EVIDENCE_STALE
    if "secret" in text:
        return BoundedReason.SECRET_DETECTED
    return BoundedReason.EVIDENCE_INCOMPLETE


def preview_repository_promotion(
    repository_root: Path,
    *,
    manifest: Path | None = None,
) -> dict[str, object]:
    """Render a digest-bound dry-run promotion preview without applying.

    Omitting ``manifest`` previews the on-disk identity-closure envelope,
    decision, receipt, and ledger against the current catalog. Providing a
    quarantine manifest offline-verifies that bundle first, then previews an
    empty candidate selection bound to the verified manifest digest. Neither
    path reserves, applies, acquires the promotion lock, or writes Git,
    SQLite, Kaggle, or catalog bytes.
    """

    command = "preview-promotion"
    if not isinstance(repository_root, Path):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="preview paths must be pathlib.Path values",
        )
    if manifest is not None and not isinstance(manifest, Path):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="preview paths must be pathlib.Path values",
        )
    try:
        return _preview_repository_promotion(
            repository_root,
            manifest=manifest,
            command=command,
        )
    except ScoutCommandError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail=str(error),
        ) from error


def _preview_repository_promotion(
    repository_root: Path,
    *,
    manifest: Path | None,
    command: str,
) -> dict[str, object]:
    from openopps.discovery.diagnostics import read_checkout_sha
    from openopps.discovery.inventory import DEFAULT_DISCOVERY_OWNED_PATHS
    from openopps.discovery.promotion import (
        PromotionPreviewError,
        compute_promotion_intent_digest,
        preview_promotion,
    )
    from openopps.discovery.promotion_closure import (
        bind_repository_v7_policy,
        build_shared_delivery_closure,
        compute_closure_digests,
    )
    from openopps.discovery.promotion_runtime import (
        CATALOG_RELATIVE_PATH,
        GENERATED_RELATIVE_PATH,
        LEDGER_RELATIVE_PATH,
        PromotionLayout,
        load_promotion_ledger,
    )

    root = repository_root.expanduser()
    verified: dict[str, object] | None = None
    if manifest is not None:
        try:
            verified = verify_scout_manifest_path(manifest)
        except ScoutCommandError as error:
            raise ScoutCommandError(
                error.reason,
                command=command,
                detail=error.detail,
            ) from error

    checkout_sha = read_checkout_sha(root)
    layout = PromotionLayout()
    decision_raw = (root / DEFAULT_DISCOVERY_OWNED_PATHS["decision"]).read_bytes()
    decision_payload = decode_canonical_json(decision_raw)
    if not isinstance(decision_payload, dict):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="promotion decision must be a JSON object",
        )
    envelope_bytes = (root / layout.envelope).read_bytes()
    envelope_payload = decode_canonical_json(envelope_bytes)
    if not isinstance(envelope_payload, dict):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="approved-ingestion envelope must be a JSON object",
        )
    receipt_bytes = (root / layout.receipt).read_bytes()
    catalog = (root / CATALOG_RELATIVE_PATH).read_bytes()
    generated = (root / GENERATED_RELATIVE_PATH).read_bytes()
    head_sha = str(decision_payload["headSha"])
    ledger_events = load_promotion_ledger(root / LEDGER_RELATIVE_PATH)

    if verified is None:
        try:
            closure = build_shared_delivery_closure(root, head_sha=head_sha)
        except PromotionPreviewError as error:
            raise ScoutCommandError(
                BoundedReason.EVIDENCE_INCOMPLETE,
                command=command,
                detail=str(error),
            ) from error
        preview = closure.preview
        identity_closure = True
        on_disk_match = (
            closure.after_bytes[layout.catalog] == catalog
            and closure.after_bytes[layout.envelope] == envelope_bytes
            and closure.after_bytes[layout.decision] == decision_raw
            and closure.after_bytes[layout.receipt] == receipt_bytes
            and closure.after_bytes[layout.generated] == generated
        )
        envelope_id = closure.envelope.envelope_id
        decision_id = closure.decision_id
        grants_authority = bool(closure.receipt.grants_authority)
        source_count = int(closure.envelope.source_count)
    else:
        v7 = bind_repository_v7_policy(root)
        _schema_manifest, resources_digest, profile_digest, _supplementary = (
            compute_closure_digests(root, catalog=catalog, generated=generated, v7=v7)
        )
        del _schema_manifest, _supplementary
        try:
            preview = preview_promotion(
                manifest_digest=str(verified["manifestId"]),
                candidates=(),
                catalog_before=catalog,
                v7=v7,
                head_sha=head_sha,
                package_owner="openopps.providers.sources",
                existing_identities=(),
                existing_owner_by_key={},
                resources_digest=resources_digest,
                profile_digest=profile_digest,
                extra_after_paths={layout.generated: generated},
                extra_before_paths={layout.generated: generated},
            )
        except PromotionPreviewError as error:
            raise ScoutCommandError(
                BoundedReason.EVIDENCE_INCOMPLETE,
                command=command,
                detail=str(error),
            ) from error
        identity_closure = False
        on_disk_match = False
        envelope_id = str(envelope_payload["envelopeId"])
        decision_id = str(decision_payload["decisionId"])
        grants_authority = False
        source_count = int(envelope_payload["sourceCount"])

    delta = decode_canonical_json(preview.delta)
    if not isinstance(delta, dict):
        raise ScoutCommandError(
            BoundedReason.EVIDENCE_INCOMPLETE,
            command=command,
            detail="promotion preview delta must be a JSON object",
        )
    payload: dict[str, object] = {
        "activated": False,
        "applied": False,
        "catalogAfterDigest": preview.catalog_after_digest,
        "catalogBeforeDigest": preview.catalog_before_digest,
        "catalogUnchanged": (
            preview.catalog_before_digest == preview.catalog_after_digest
        ),
        "checkoutSha": checkout_sha,
        "command": command,
        "decisionHeadSha": head_sha,
        "decisionId": decision_id,
        "delta": delta,
        "envelopeId": envelope_id,
        "grantsAuthority": grants_authority,
        "identityClosure": identity_closure,
        "intent": preview.intent.model_dump(mode="json", by_alias=True),
        "ledgerStates": [event.state for event in ledger_events],
        "onDiskMatch": on_disk_match,
        "promotionDigest": preview.promotion_digest,
        "promotionIntentDigest": compute_promotion_intent_digest(preview.intent),
        "promoted": False,
        "proposedRecordCount": len(preview.proposed_records),
        "sourceCount": source_count,
        "status": "preview",
    }
    if verified is not None:
        payload["manifestId"] = verified["manifestId"]
        payload["verified"] = True
    return payload
