"""Read-only v7 policy binding and discovery-owned promotion requirements."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Literal
import json

from openopps.discovery.canonical import CanonicalJSONError, canonical_json_bytes
from openopps.discovery.models import PolicyAxisSet


PolicyState = Literal["allowed", "blocked", "unresolved"]
REQUIRED_OPERATIONS: tuple[str, ...] = (
    "access",
    "license",
    "publication",
    "redistribution",
    "sync",
)
_BLOCKED_AXIS_VALUES = frozenset(
    {"blocked", "permission_required", "unavailable", "denied"}
)
_ALLOWED_AXIS_VALUES = frozenset({"allowed", "public", "granted"})


class PolicyDisposition(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class V7PolicyDigestBinding:
    policy_code_sha256: str
    policy_schema_sha256: str
    policy_evidence_sha256: str
    policy_corpus_sha256: str
    public_selector_sha256: str | None
    policy_code_size_bytes: int
    policy_schema_size_bytes: int
    policy_evidence_size_bytes: int
    policy_corpus_size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "policyCodeSha256": self.policy_code_sha256,
            "policyCodeSizeBytes": self.policy_code_size_bytes,
            "policyCorpusSha256": self.policy_corpus_sha256,
            "policyCorpusSizeBytes": self.policy_corpus_size_bytes,
            "policyEvidenceSha256": self.policy_evidence_sha256,
            "policyEvidenceSizeBytes": self.policy_evidence_size_bytes,
            "policySchemaSha256": self.policy_schema_sha256,
            "policySchemaSizeBytes": self.policy_schema_size_bytes,
            "publicSelectorSha256": self.public_selector_sha256,
        }


@dataclass(frozen=True, slots=True)
class DenyOverlayMatch:
    decision_id: str
    provider_ids: tuple[str, ...]
    source_keys: tuple[str, ...]
    axes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PromotionPolicyRequirement:
    required_operations: tuple[str, ...]
    decision_present: bool
    serializes_as_v7_policy_evidence: Literal[False] = False
    grants_authority: Literal[False] = False

    def as_dict(self) -> dict[str, object]:
        return {
            "decisionPresent": self.decision_present,
            "grantsAuthority": False,
            "requiredOperations": list(self.required_operations),
            "serializesAsV7PolicyEvidence": False,
        }


@dataclass(frozen=True, slots=True)
class DiscoveryPolicyBinding:
    v7: V7PolicyDigestBinding
    deny_matches: tuple[str, ...]
    axes: PolicyAxisSet
    attribution_requirements: tuple[str, ...]
    promotion_requirement: PromotionPolicyRequirement
    untrusted_observations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "attributionRequirements": list(self.attribution_requirements),
            "axes": self.axes.model_dump(mode="json", by_alias=True, round_trip=True),
            "denyMatches": list(self.deny_matches),
            "promotionRequirement": self.promotion_requirement.as_dict(),
            "untrustedObservations": list(self.untrusted_observations),
            "v7": self.v7.as_dict(),
        }


def bind_v7_policy_digests(
    *,
    policy_code: bytes,
    policy_schema: bytes,
    policy_evidence: bytes,
    policy_corpus: bytes,
    public_selector: bytes | None,
) -> V7PolicyDigestBinding:
    """Hash supplied v7 surfaces without writing or importing them."""

    payloads = (policy_code, policy_schema, policy_evidence, policy_corpus)
    if any(not isinstance(item, (bytes, bytearray)) for item in payloads):
        raise ValueError("v7 policy inputs must be exact bytes")
    selector_digest = (
        None if public_selector is None else sha256(public_selector).hexdigest()
    )
    return V7PolicyDigestBinding(
        policy_code_sha256=sha256(policy_code).hexdigest(),
        policy_schema_sha256=sha256(policy_schema).hexdigest(),
        policy_evidence_sha256=sha256(policy_evidence).hexdigest(),
        policy_corpus_sha256=sha256(policy_corpus).hexdigest(),
        public_selector_sha256=selector_digest,
        policy_code_size_bytes=len(policy_code),
        policy_schema_size_bytes=len(policy_schema),
        policy_evidence_size_bytes=len(policy_evidence),
        policy_corpus_size_bytes=len(policy_corpus),
    )


def match_deny_overlay(
    *,
    provider_id: str,
    source_key: str,
    evidence_bytes: bytes,
) -> tuple[DenyOverlayMatch, ...]:
    """Apply exact provider and source-key denials without catalog expansion."""

    try:
        payload = json.loads(evidence_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("v7 policy evidence is not exact JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("v7 policy evidence must be an object")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return ()
    provider = provider_id.casefold()
    key = source_key.casefold()
    matches: list[DenyOverlayMatch] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        axes = decision.get("axes")
        scope = decision.get("scope")
        if not isinstance(axes, dict) or not isinstance(scope, dict):
            continue
        if str(axes.get("publication", "")).casefold() != "blocked":
            continue
        provider_ids = _string_tuple(scope.get("providerIds"))
        source_keys = _string_tuple(scope.get("sourceKeys"))
        provider_hit = provider in {item.casefold() for item in provider_ids}
        key_hit = key in {item.casefold() for item in source_keys}
        if not provider_hit and not key_hit:
            continue
        decision_id = str(decision.get("id") or "")
        if not decision_id:
            continue
        matches.append(
            DenyOverlayMatch(
                decision_id=decision_id,
                provider_ids=provider_ids,
                source_keys=source_keys,
                axes={str(name): str(value) for name, value in sorted(axes.items())},
            )
        )
    return tuple(matches)


def evaluate_policy(
    axes: PolicyAxisSet,
    *,
    deny_overlay_matches: Iterable[str] = (),
    untrusted_observations: Iterable[str] = (),
) -> PolicyDisposition:
    """Require all five positive axes; observations never grant permission."""

    del untrusted_observations
    if tuple(deny_overlay_matches):
        return PolicyDisposition.BLOCKED
    states = (
        axes.access,
        axes.license,
        axes.redistribution,
        axes.sync,
        axes.publication,
    )
    if "blocked" in states:
        return PolicyDisposition.BLOCKED
    if "unresolved" in states:
        return PolicyDisposition.UNRESOLVED
    return PolicyDisposition.ALLOWED


def axes_from_deny_matches(matches: Iterable[DenyOverlayMatch]) -> PolicyAxisSet:
    """Map matched denial axes without converting unknown values into allow."""

    values: dict[str, PolicyState] = {
        name: "unresolved" for name in REQUIRED_OPERATIONS
    }
    for match in matches:
        for name in REQUIRED_OPERATIONS:
            mapped = _map_axis(match.axes.get(name, "unknown"))
            current = values[name]
            values[name] = _dominate(current, mapped)
    return PolicyAxisSet(**values)


def bind_candidate_policy(
    *,
    provider_id: str,
    source_key: str,
    taxonomy: Mapping[str, object],
    v7: V7PolicyDigestBinding,
    evidence_bytes: bytes,
    untrusted_observations: Iterable[str] = (),
    extra_provider_ids: Iterable[str] = (),
) -> DiscoveryPolicyBinding:
    observations = tuple(untrusted_observations)
    providers: list[str] = []
    seen_providers: set[str] = set()
    for item in (provider_id, *extra_provider_ids):
        folded = item.casefold()
        if folded and folded not in seen_providers:
            seen_providers.add(folded)
            providers.append(item)
    matches: list[DenyOverlayMatch] = []
    seen_decisions: set[str] = set()
    for item in providers:
        for match in match_deny_overlay(
            provider_id=item,
            source_key=source_key,
            evidence_bytes=evidence_bytes,
        ):
            if match.decision_id in seen_decisions:
                continue
            seen_decisions.add(match.decision_id)
            matches.append(match)
    if matches:
        axes = axes_from_deny_matches(matches)
    else:
        axes = PolicyAxisSet(
            access="unresolved",
            license="unresolved",
            redistribution="unresolved",
            sync="unresolved",
            publication="unresolved",
        )
    return DiscoveryPolicyBinding(
        v7=v7,
        deny_matches=tuple(item.decision_id for item in matches),
        axes=axes,
        attribution_requirements=attribution_requirements(taxonomy),
        promotion_requirement=PromotionPolicyRequirement(
            required_operations=REQUIRED_OPERATIONS,
            decision_present=False,
        ),
        untrusted_observations=observations,
    )


def attribution_requirements(taxonomy: Mapping[str, object]) -> tuple[str, ...]:
    """Emit attribution metadata as a requirement, never as permission."""

    value = taxonomy.get("sourceAttribution")
    if not isinstance(value, str) or not value.strip():
        return ()
    return (value.strip(),)


def encode_discovery_policy_binding(binding: DiscoveryPolicyBinding) -> bytes:
    try:
        return canonical_json_bytes(binding.as_dict())
    except CanonicalJSONError as error:
        raise ValueError("discovery policy binding is not canonical") from error


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = tuple(str(item) for item in value if isinstance(item, str) and item.strip())
    return items


def _map_axis(value: str) -> PolicyState:
    folded = value.casefold()
    if folded in _BLOCKED_AXIS_VALUES:
        return "blocked"
    if folded in _ALLOWED_AXIS_VALUES:
        return "unresolved"
    return "unresolved"


def _dominate(current: PolicyState, incoming: PolicyState) -> PolicyState:
    if current == "blocked" or incoming == "blocked":
        return "blocked"
    if current == "unresolved" or incoming == "unresolved":
        return "unresolved"
    return "allowed"
