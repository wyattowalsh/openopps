"""CLI-neutral discovery library entry points for skills, commands, and tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, TypeVar

from openopps.discovery.bundle import (
    BundleVerificationPolicy,
    VerifiedBundle,
    verify_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.diagnostics import (
    BoundedDiagnostic,
    render_bounded_diagnostic,
)
from openopps.discovery.identity import normalize_candidate_identity
from openopps.discovery.inventory import (
    ApprovedRuntimeCatalogInventory,
    PackagedCatalogReadback,
    RepositoryIdentityProjection,
    build_approved_runtime_catalog_inventory,
    project_repository_identities,
)
from openopps.discovery.models import (
    BoundedReason,
    CandidateIdentity,
    ChannelReplayReceipt,
    StrictDiscoveryModel,
)
from openopps.discovery.schemas import (
    DEFAULT_SCHEMA_ROOT,
    discovery_schema_models,
    render_discovery_schema_files,
    schema_file_name,
    validate_discovery_schema_files,
)


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
