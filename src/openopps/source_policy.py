"""Fail-closed source-policy evidence for public corpus operations.

This module deliberately does not fetch remote policy pages or mutate the packaged
source catalog.  It validates a dated evidence snapshot, expands its selectors only
against a caller-provided corpus, and refuses to render an ingestion selector while
any selected source is ineligible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openopps.models import SourceRecord
from openopps.providers.sources import BOARD_SOURCE_CATALOG


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
DECISION_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
DEFAULT_EVIDENCE_PATH = (
    Path(__file__).parent
    / "providers"
    / "sources"
    / "data"
    / "source_policy_evidence.json"
)
DEFAULT_SCHEMA_PATH = DEFAULT_EVIDENCE_PATH.with_suffix(".schema.json")

LicenseState = Literal[
    "official_public",
    "oss_attribution_required",
    "public_attribution_required",
    "needs_review",
    "permission_required",
    "prohibited",
    "unknown",
]
AccessState = Literal[
    "allowed", "permission_required", "prohibited", "unavailable", "unknown"
]
RedistributionState = Literal[
    "allowed",
    "attribution_required",
    "permission_required",
    "prohibited",
    "unknown",
]
ExecutionState = Literal["allowed", "blocked"]
DecisionType = Literal["platform_terms", "repository_status", "historical_block"]
EvidenceKind = Literal["platform_terms", "repository_catalog", "historical_observation"]
PUBLICATION_ALLOWED_LICENSE_STATES = frozenset(
    {"official_public", "oss_attribution_required", "public_attribution_required"}
)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class SourcePolicyValidationError(ValueError):
    """The policy evidence does not close over the selected source corpus."""


class SourcePolicyBlockedError(SourcePolicyValidationError):
    """The selected corpus is validly described but not eligible for execution."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class PolicyAxes(_StrictModel):
    """Independent policy axes; no single license label grants every operation."""

    license: LicenseState
    access: AccessState
    redistribution: RedistributionState
    sync: ExecutionState
    publication: ExecutionState

    @model_validator(mode="after")
    def validate_allowed_operations(self) -> PolicyAxes:
        if self.sync == "allowed" and self.access != "allowed":
            raise ValueError("sync cannot be allowed unless access is allowed")
        if self.publication == "allowed":
            if self.sync != "allowed":
                raise ValueError("publication cannot be allowed when sync is blocked")
            if self.license not in PUBLICATION_ALLOWED_LICENSE_STATES:
                raise ValueError(
                    "publication cannot be allowed without an allowed license state"
                )
            if self.redistribution in {
                "permission_required",
                "prohibited",
                "unknown",
            }:
                raise ValueError(
                    "publication cannot be allowed when redistribution is unresolved"
                )
        return self


class EvidenceReference(_StrictModel):
    kind: EvidenceKind
    locator: str = Field(min_length=1, max_length=500)
    observed_at: date
    summary: str = Field(min_length=1, max_length=1000)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    last_updated: str | None = Field(default=None, min_length=1, max_length=100)
    sections: tuple[str, ...] = ()

    @field_validator("locator")
    @classmethod
    def validate_locator(cls, value: str, info: Any) -> str:
        if value != value.strip():
            raise ValueError("locator must not have surrounding whitespace")
        kind = info.data.get("kind")
        if kind in {"repository_catalog", "historical_observation"}:
            if value.startswith(("/", "../")) or "\\" in value:
                raise ValueError("repository locator must be a relative POSIX path")
            if kind == "repository_catalog" and not value.startswith(
                "src/openopps/providers/sources/"
            ):
                raise ValueError("repository locator must identify the source catalog")
            if kind == "historical_observation" and value != (
                "web/public/data/openopps-search/manifest.json"
            ):
                raise ValueError(
                    "historical locator must identify the committed v6 manifest"
                )
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("external evidence locator must be a public HTTPS URL")
        return value

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not section.strip() or section != section.strip() for section in value):
            raise ValueError("evidence sections must be non-empty and trimmed")
        if len(set(value)) != len(value):
            raise ValueError("evidence sections must be unique")
        return value


class SourceScope(_StrictModel):
    provider_ids: tuple[str, ...] = ()
    source_keys: tuple[str, ...] = ()
    source_count: int = Field(ge=1)
    source_keys_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_selector(self) -> SourceScope:
        has_providers = bool(self.provider_ids)
        has_keys = bool(self.source_keys)
        if has_providers == has_keys:
            raise ValueError(
                "scope must define exactly one of providerIds or sourceKeys"
            )
        values = self.provider_ids if has_providers else self.source_keys
        if tuple(sorted(values)) != values or len(set(values)) != len(values):
            raise ValueError("scope selector values must be sorted and unique")
        if has_keys:
            if len(self.source_keys) != self.source_count:
                raise ValueError("explicit sourceKeys do not match sourceCount")
            actual = compute_source_keys_sha256(self.source_keys)
            if actual != self.source_keys_sha256:
                raise ValueError("explicit sourceKeys do not match sourceKeysSha256")
        return self


class PolicyDecision(_StrictModel):
    id: str = Field(pattern=DECISION_ID_PATTERN)
    decision_type: DecisionType
    scope: SourceScope
    axes: PolicyAxes
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    catalog_license_status: LicenseState | None = None
    source_attribution: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_decision_type(self) -> PolicyDecision:
        evidence_kinds = {reference.kind for reference in self.evidence}
        if self.decision_type == "repository_status":
            if self.scope.provider_ids or len(self.scope.source_keys) != 1:
                raise ValueError(
                    "repository_status must identify exactly one explicit source"
                )
            if evidence_kinds != {"repository_catalog"}:
                raise ValueError(
                    "repository_status must use repository_catalog evidence"
                )
            if self.catalog_license_status is None:
                raise ValueError("repository_status requires catalogLicenseStatus")
            if self.axes.license != self.catalog_license_status:
                raise ValueError("catalogLicenseStatus must equal the license axis")
            if self.catalog_license_status in PUBLICATION_ALLOWED_LICENSE_STATES:
                if self.axes.publication != "allowed":
                    raise ValueError(
                        "allowed repository_status decisions must allow publication"
                    )
                if self.source_attribution is None:
                    raise ValueError(
                        "allowed repository_status requires sourceAttribution"
                    )
            elif self.axes.sync != "blocked" or self.axes.publication != "blocked":
                raise ValueError(
                    "unresolved repository_status decisions must block operations"
                )
        else:
            if self.catalog_license_status is not None or self.source_attribution:
                raise ValueError(
                    "blocked decisions must not carry catalog grant metadata"
                )
            if self.axes.sync != "blocked" or self.axes.publication != "blocked":
                raise ValueError(
                    "non-repository decisions must block sync and publication"
                )
            expected_kind = (
                "platform_terms"
                if self.decision_type == "platform_terms"
                else "historical_observation"
            )
            if evidence_kinds != {expected_kind}:
                raise ValueError(
                    f"{self.decision_type} must use {expected_kind} evidence"
                )
        return self


class SourcePolicyEvidence(_StrictModel):
    schema_version: Literal[1]
    policy_id: str = Field(pattern=DECISION_ID_PATTERN)
    reviewed_at: date
    corpus_id: str = Field(pattern=DECISION_ID_PATTERN)
    decisions: tuple[PolicyDecision, ...] = Field(min_length=1)

    @field_validator("decisions")
    @classmethod
    def validate_decision_order(
        cls, value: tuple[PolicyDecision, ...]
    ) -> tuple[PolicyDecision, ...]:
        ids = tuple(decision.id for decision in value)
        if tuple(sorted(ids)) != ids or len(set(ids)) != len(ids):
            raise ValueError("decisions must have sorted, unique ids")
        return value


class SourceCorpus(_StrictModel):
    schema_version: Literal[1]
    corpus_id: str = Field(pattern=DECISION_ID_PATTERN)
    artifact_path: Literal["web/public/data/openopps-search/manifest.json"]
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_at: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    source_keys_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_blocked_source_count: int = Field(ge=0)
    expected_blocked_source_keys_sha256: str = Field(pattern=SHA256_PATTERN)
    source_keys: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_keys")
    @classmethod
    def validate_source_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(value)) != value or len(set(value)) != len(value):
            raise ValueError("sourceKeys must be sorted and unique")
        for key in value:
            if not key or key != key.strip():
                raise ValueError("sourceKeys must be non-empty and trimmed")
            if not _matches_source_key(key):
                raise ValueError(f"invalid source key {key!r}")
        return value

    @model_validator(mode="after")
    def validate_counts_and_digest(self) -> SourceCorpus:
        if len(self.source_keys) != self.source_count:
            raise ValueError("sourceKeys do not match sourceCount")
        if compute_source_keys_sha256(self.source_keys) != self.source_keys_sha256:
            raise ValueError("sourceKeys do not match sourceKeysSha256")
        if self.expected_blocked_source_count > self.source_count:
            raise ValueError("expected blocked count exceeds sourceCount")
        if self.artifact_path.startswith(("/", "../")) or "\\" in self.artifact_path:
            raise ValueError("artifactPath must be a repository-relative POSIX path")
        return self


class SourcePolicyAudit(_StrictModel):
    schema_version: Literal[1] = 1
    policy_id: str
    corpus_id: str
    source_count: int
    allowed_count: int
    catalog_declared_allowed_count: int
    independently_verified_allowed_count: Literal[0] = 0
    allowed_evidence_basis: Literal[
        "repository_catalog_declarations_not_independent_legal_review"
    ] = "repository_catalog_declarations_not_independent_legal_review"
    blocked_count: int
    source_keys_sha256: str = Field(pattern=SHA256_PATTERN)
    blocked_source_keys_sha256: str = Field(pattern=SHA256_PATTERN)
    allowed_source_keys: tuple[str, ...]
    blocked_source_keys: tuple[str, ...]


class SourceSelector(_StrictModel):
    schema_version: Literal[1] = 1
    corpus_id: str
    source_count: int
    source_keys_sha256: str = Field(pattern=SHA256_PATTERN)
    source_keys: tuple[str, ...]


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically with a single trailing newline."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def compute_source_keys_sha256(source_keys: Sequence[str]) -> str:
    """Hash a source selector as sorted-contract newline-delimited UTF-8 bytes."""

    return hashlib.sha256(
        "".join(f"{source_key}\n" for source_key in source_keys).encode()
    ).hexdigest()


def load_source_policy_evidence(
    path: Path = DEFAULT_EVIDENCE_PATH,
) -> SourcePolicyEvidence:
    return parse_source_policy_evidence(path.read_bytes(), source=path)


def parse_source_policy_evidence(
    raw: bytes, *, source: Path = DEFAULT_EVIDENCE_PATH
) -> SourcePolicyEvidence:
    """Validate one already-captured canonical evidence byte snapshot."""

    payload = _decode_json_object(raw, source)
    if raw != canonical_json_bytes(payload):
        raise SourcePolicyValidationError(f"{source} must use canonical JSON bytes")
    return SourcePolicyEvidence.model_validate(payload)


def load_source_corpus(path: Path) -> SourceCorpus:
    return parse_source_corpus(path.read_bytes(), source=path)


def parse_source_corpus(raw: bytes, *, source: Path) -> SourceCorpus:
    """Validate one already-captured canonical source-corpus byte snapshot."""

    payload = _decode_json_object(raw, source)
    if raw != canonical_json_bytes(payload):
        raise SourcePolicyValidationError(f"{source} must use canonical JSON bytes")
    return SourceCorpus.model_validate(payload)


def audit_source_policy(
    *,
    corpus: SourceCorpus,
    evidence: SourcePolicyEvidence,
    catalog: Mapping[str, SourceRecord] = BOARD_SOURCE_CATALOG,
) -> SourcePolicyAudit:
    """Validate complete, non-overlapping evidence and return eligibility state."""

    if evidence.corpus_id != corpus.corpus_id:
        raise SourcePolicyValidationError(
            f"evidence corpus {evidence.corpus_id!r} does not match "
            f"{corpus.corpus_id!r}"
        )
    corpus_keys = set(corpus.source_keys)
    decisions_by_key: dict[str, PolicyDecision] = {}
    for decision in evidence.decisions:
        expanded = _expand_scope(decision.scope, corpus=corpus, catalog=catalog)
        if len(expanded) != decision.scope.source_count:
            raise SourcePolicyValidationError(
                f"decision {decision.id!r} expanded to {len(expanded)} sources; "
                f"expected {decision.scope.source_count}"
            )
        digest = compute_source_keys_sha256(expanded)
        if digest != decision.scope.source_keys_sha256:
            raise SourcePolicyValidationError(
                f"decision {decision.id!r} source digest {digest} does not match "
                f"{decision.scope.source_keys_sha256}"
            )
        unexpected = set(expanded) - corpus_keys
        if unexpected:
            raise SourcePolicyValidationError(
                f"decision {decision.id!r} includes keys outside the corpus: "
                + ", ".join(sorted(unexpected))
            )
        for key in expanded:
            if key in decisions_by_key:
                raise SourcePolicyValidationError(
                    f"source {key!r} is covered by multiple decisions"
                )
            decisions_by_key[key] = decision
            if decision.decision_type == "repository_status":
                _validate_repository_status(key, decision, catalog)

    uncovered = corpus_keys - decisions_by_key.keys()
    if uncovered:
        raise SourcePolicyValidationError(
            "uncovered source keys: " + ", ".join(sorted(uncovered))
        )

    allowed = tuple(
        key for key in corpus.source_keys if _is_eligible(decisions_by_key[key].axes)
    )
    allowed_set = set(allowed)
    blocked = tuple(key for key in corpus.source_keys if key not in allowed_set)
    blocked_digest = compute_source_keys_sha256(blocked)
    if len(blocked) != corpus.expected_blocked_source_count:
        raise SourcePolicyValidationError(
            f"blocked source count {len(blocked)} does not match "
            f"{corpus.expected_blocked_source_count}"
        )
    if blocked_digest != corpus.expected_blocked_source_keys_sha256:
        raise SourcePolicyValidationError(
            f"blocked source digest {blocked_digest} does not match "
            f"{corpus.expected_blocked_source_keys_sha256}"
        )
    return SourcePolicyAudit(
        policy_id=evidence.policy_id,
        corpus_id=corpus.corpus_id,
        source_count=len(corpus.source_keys),
        allowed_count=len(allowed),
        catalog_declared_allowed_count=len(allowed),
        blocked_count=len(blocked),
        source_keys_sha256=corpus.source_keys_sha256,
        blocked_source_keys_sha256=blocked_digest,
        allowed_source_keys=allowed,
        blocked_source_keys=blocked,
    )


def match_source_policy_denials(
    *,
    source_keys: Sequence[str],
    evidence: SourcePolicyEvidence,
    catalog: Mapping[str, SourceRecord] = BOARD_SOURCE_CATALOG,
) -> dict[str, tuple[PolicyDecision, ...]]:
    """Return deny-only matches without interpreting absence as permission.

    Provider-scoped decisions apply to any caller key currently owned by that
    provider, independent of the evidence snapshot's recorded count and digest.
    Explicit-key decisions apply only to those exact keys.  Allowed decisions and
    uncovered keys are intentionally omitted; the caller must retain its own
    positive rights gate.
    """

    matches: dict[str, tuple[PolicyDecision, ...]] = {}
    for key in sorted(set(source_keys)):
        record = catalog.get(key)
        matched: list[PolicyDecision] = []
        for decision in evidence.decisions:
            if decision.axes.publication != "blocked":
                continue
            scope = decision.scope
            if key in scope.source_keys or (
                record is not None and record.provider_id in scope.provider_ids
            ):
                matched.append(decision)
        if matched:
            matches[key] = tuple(matched)
    return matches


def render_source_selector(
    *, corpus: SourceCorpus, evidence: SourcePolicyEvidence
) -> bytes:
    """Render exact selector bytes only if every corpus source is eligible."""

    audit = audit_source_policy(corpus=corpus, evidence=evidence)
    return _render_source_selector_from_audit(corpus=corpus, audit=audit)


def _render_source_selector_from_audit(
    *, corpus: SourceCorpus, audit: SourcePolicyAudit
) -> bytes:
    if audit.blocked_count:
        raise SourcePolicyBlockedError(
            f"selector blocked by {audit.blocked_count} ineligible sources "
            f"({audit.blocked_source_keys_sha256})"
        )
    selector = SourceSelector(
        corpus_id=corpus.corpus_id,
        source_count=corpus.source_count,
        source_keys_sha256=corpus.source_keys_sha256,
        source_keys=corpus.source_keys,
    )
    return canonical_json_bytes(selector.model_dump(mode="json", by_alias=True))


def validate_repository_source_policy(
    *,
    corpus_path: Path,
    manifest_path: Path,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> SourcePolicyAudit:
    """Validate canonical evidence plus the exact committed v6 manifest identity."""

    _corpus, _evidence, audit = _load_validated_repository_policy(
        corpus_path=corpus_path,
        evidence_path=evidence_path,
        manifest_path=manifest_path,
        schema_path=schema_path,
    )
    return audit


def render_repository_source_selector(
    *,
    corpus_path: Path,
    manifest_path: Path,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> bytes:
    """Validate one exact repository snapshot and render from those in-memory models."""

    corpus, _evidence, audit = _load_validated_repository_policy(
        corpus_path=corpus_path,
        evidence_path=evidence_path,
        manifest_path=manifest_path,
        schema_path=schema_path,
    )
    return _render_source_selector_from_audit(corpus=corpus, audit=audit)


def _load_validated_repository_policy(
    *, corpus_path: Path, evidence_path: Path, manifest_path: Path, schema_path: Path
) -> tuple[SourceCorpus, SourcePolicyEvidence, SourcePolicyAudit]:
    """Load each input once, bind it to the artifact, and return immutable models."""

    validate_source_policy_schema(schema_path)
    corpus = load_source_corpus(corpus_path)
    evidence = load_source_policy_evidence(evidence_path)
    raw_manifest = manifest_path.read_bytes()
    actual_artifact_digest = hashlib.sha256(raw_manifest).hexdigest()
    if actual_artifact_digest != corpus.artifact_sha256:
        raise SourcePolicyValidationError(
            f"artifact SHA-256 {actual_artifact_digest} does not match "
            f"{corpus.artifact_sha256}"
        )
    manifest = _decode_json_object(raw_manifest, manifest_path)
    facets = manifest.get("facets")
    sources = facets.get("sources") if isinstance(facets, dict) else None
    if sources != list(corpus.source_keys):
        raise SourcePolicyValidationError(
            "artifact source facets do not match the recorded corpus"
        )
    if manifest.get("snapshotAt") != corpus.snapshot_at:
        raise SourcePolicyValidationError(
            "artifact snapshotAt does not match the recorded corpus"
        )
    audit = audit_source_policy(corpus=corpus, evidence=evidence)
    return corpus, evidence, audit


def validate_source_policy_schema(path: Path = DEFAULT_SCHEMA_PATH) -> None:
    """Require the committed JSON Schema to equal the current strict model schema."""

    validate_source_policy_schema_bytes(path.read_bytes(), source=path)


def validate_source_policy_schema_bytes(
    raw: bytes, *, source: Path = DEFAULT_SCHEMA_PATH
) -> None:
    """Validate one already-captured canonical schema byte snapshot."""

    expected = canonical_json_bytes(SourcePolicyEvidence.model_json_schema())
    if raw != expected:
        raise SourcePolicyValidationError(
            f"{source} does not match the canonical SourcePolicyEvidence JSON Schema"
        )


def _expand_scope(
    scope: SourceScope,
    *,
    corpus: SourceCorpus,
    catalog: Mapping[str, SourceRecord],
) -> tuple[str, ...]:
    if scope.source_keys:
        return scope.source_keys
    providers = set(scope.provider_ids)
    return tuple(
        key
        for key in corpus.source_keys
        if key in catalog and catalog[key].provider_id in providers
    )


def _validate_repository_status(
    key: str,
    decision: PolicyDecision,
    catalog: Mapping[str, SourceRecord],
) -> None:
    record = catalog.get(key)
    if record is None:
        raise SourcePolicyValidationError(
            f"repository-status source {key!r} is absent from the packaged catalog"
        )
    status = record.raw_metadata.get("licenseStatus")
    attribution = record.raw_metadata.get("sourceAttribution")
    if status != decision.catalog_license_status:
        raise SourcePolicyValidationError(
            f"repository-status source {key!r} licenseStatus drifted"
        )
    if attribution != decision.source_attribution:
        raise SourcePolicyValidationError(
            f"repository-status source {key!r} sourceAttribution drifted"
        )


def _is_eligible(axes: PolicyAxes) -> bool:
    return (
        axes.license in PUBLICATION_ALLOWED_LICENSE_STATES
        and axes.access == "allowed"
        and axes.redistribution in {"allowed", "attribution_required"}
        and axes.sync == "allowed"
        and axes.publication == "allowed"
    )


def _load_canonical_json_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = _decode_json_object(raw, path)
    if raw != canonical_json_bytes(payload):
        raise SourcePolicyValidationError(f"{path} must use canonical JSON bytes")
    return payload


def _decode_json_object(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourcePolicyValidationError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise SourcePolicyValidationError(f"{path} must contain a JSON object")
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourcePolicyValidationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _matches_source_key(value: str) -> bool:
    import re

    return re.fullmatch(SOURCE_KEY_PATTERN, value) is not None


__all__ = [
    "DEFAULT_EVIDENCE_PATH",
    "DEFAULT_SCHEMA_PATH",
    "EvidenceReference",
    "PolicyAxes",
    "PolicyDecision",
    "SourceCorpus",
    "SourcePolicyAudit",
    "SourcePolicyBlockedError",
    "SourcePolicyEvidence",
    "SourcePolicyValidationError",
    "SourceScope",
    "audit_source_policy",
    "canonical_json_bytes",
    "compute_source_keys_sha256",
    "load_source_corpus",
    "load_source_policy_evidence",
    "parse_source_policy_evidence",
    "match_source_policy_denials",
    "parse_source_corpus",
    "render_repository_source_selector",
    "render_source_selector",
    "validate_source_policy_schema",
    "validate_repository_source_policy",
    "validate_source_policy_schema_bytes",
]
