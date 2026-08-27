"""Targeted employer/ATS coverage enumerator (E441-E446).

Coverage intake only: locators and captured page evidence may yield provider
hints. A company career-domain never invents an ATS identity by itself.
Built-in route parsing is a frozen host/path table; job sync and plugin
loading are out of scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from openopps.discovery.enumerators import (
    CapturedObservation,
    ChannelRunBuilder,
    EnumeratorError,
    add_local_claim,
    add_remote_claim,
    admit_observation_resource,
    canonical_locator,
    digest_input_set,
    lookup_observation,
    observation_digest,
    observation_map,
    occurrence_from_locator,
    origin_allowed,
    parse_html_locators,
    request_outcome_from_observation,
    require_channel_profile,
    require_observed_at,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelProfile,
    ChannelReplayReceipt,
)
from openopps.discovery.transport import (
    DiscoveryTransportError,
    SafeLocator,
    validate_public_locator,
)


TARGETED_ATS_ENUMERATOR_VERSION = "targeted-ats-fixture-v1"
HintClass = Literal[
    "supported",
    "detect_only",
    "unsupported",
    "unsafe",
    "inconclusive",
]


@dataclass(frozen=True, slots=True)
class EmployerTarget:
    """Maintainer-owned employer or ATS target. No domain-to-ATS invention."""

    target_id: str
    public_page_locator: str
    claimed_provider_hint: str | None = None


@dataclass(frozen=True, slots=True)
class BuiltInRouteHint:
    provider_id: str
    support: Literal["jobs", "detect", "unsupported"]
    token: str | None


def enumerate_targeted_ats_channel(
    *,
    profile: ChannelProfile,
    targets: Sequence[EmployerTarget],
    observations: Sequence[CapturedObservation] | Mapping[str, CapturedObservation],
    observed_at: datetime,
) -> ChannelReplayReceipt:
    """Replay finite public-page/provider-hint coverage intake."""

    profile = require_channel_profile(profile, "targeted_ats")
    observed_at = require_observed_at(observed_at)
    target_values = _validate_targets(profile, targets)
    captured = observation_map(observations)
    input_digest = digest_input_set(
        {
            "enumeratorVersion": TARGETED_ATS_ENUMERATOR_VERSION,
            "observations": [
                observation_digest(captured[key]) for key in sorted(captured)
            ],
            "parserIds": list(profile.parser_ids),
            "seedIds": list(profile.seed_ids),
            "targets": [
                {
                    "claimedProviderHint": target.claimed_provider_hint,
                    "publicPageLocator": target.public_page_locator,
                    "targetId": target.target_id,
                }
                for target in target_values
            ],
        }
    )
    builder = ChannelRunBuilder(
        channel="targeted_ats",
        enumerator_version=TARGETED_ATS_ENUMERATOR_VERSION,
        input_set_sha256=input_digest,
        budget=profile.budget,
        observed_at=observed_at,
    )
    selected = target_values[: profile.budget.query_limit]
    for target in selected:
        builder.plan(f"{target.target_id}:page")
    for target in selected:
        _run_target(builder, profile=profile, target=target, captured=captured)
    return builder.close()


def classify_public_route(locator: str) -> BuiltInRouteHint | None:
    """Parse one public locator with the frozen built-in route table."""

    try:
        safe = validate_public_locator(locator)
    except DiscoveryTransportError:
        return None
    return _match_builtin(safe)


def _validate_targets(
    profile: ChannelProfile,
    targets: Sequence[EmployerTarget],
) -> tuple[EmployerTarget, ...]:
    if not targets:
        raise EnumeratorError("employer_targets")
    ordered = tuple(sorted(targets, key=lambda item: item.target_id))
    identities = tuple(item.target_id for item in ordered)
    if identities != tuple(sorted(set(identities))) or identities != profile.seed_ids:
        raise EnumeratorError("employer_targets")
    for target in ordered:
        canonical_locator(target.public_page_locator)
    return ordered


def _run_target(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    target: EmployerTarget,
    captured: Mapping[str, CapturedObservation],
) -> None:
    operation_id = f"{target.target_id}:page"
    try:
        page = canonical_locator(target.public_page_locator)
    except EnumeratorError:
        builder.finish(operation_id, "blocked")
        return
    if not origin_allowed(profile, page):
        _emit_hint(
            builder,
            target=target,
            locator=page,
            classification="unsafe",
            provider_id="unknown",
            token=None,
            provenance_ids=(),
        )
        builder.finish(operation_id, "blocked")
        return
    if not builder.can_start():
        return
    observation = lookup_observation(captured, page)
    if observation is None:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=page,
            resource_id=None,
            response_status=None,
            admitted_bytes=0,
            elapsed_ms=0,
            reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
        )
        _emit_hint(
            builder,
            target=target,
            locator=page,
            classification="inconclusive",
            provider_id="unknown",
            token=None,
            provenance_ids=(),
        )
        builder.finish(operation_id, "failed")
        return
    outcome, reason = request_outcome_from_observation(observation)
    resource = None
    hrefs: tuple[str, ...] = ()
    if observation.body is not None:
        media = observation.media_type or "text/html"
        resource = admit_observation_resource(
            builder,
            observation,
            page,
            role="ats-page-evidence",
            media_type=media,
        )
        if resource is not None and "html" in media and outcome == "succeeded":
            try:
                hrefs = parse_html_locators(
                    observation.body,
                    node_limit=max(profile.budget.parser_depth_limit, 1) * 16,
                )
            except EnumeratorError:
                outcome = "failed"
                reason = BoundedReason.PARSER_REJECTED
    builder.add_request(
        operation_id,
        attempt_kind="initial",
        outcome=outcome,
        locator=page,
        resource_id=None if resource is None else resource.resource_id,
        response_status=observation.status_code,
        admitted_bytes=0 if resource is None else resource.size_bytes,
        elapsed_ms=observation.elapsed_ms,
        reason_code=reason,
        validated_address=observation.validated_address,
    )
    provenance = () if resource is None else (resource.resource_id,)
    if resource is not None and target.claimed_provider_hint:
        add_remote_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="claimedProviderHint",
            value=target.claimed_provider_hint,
        )
    if outcome == "blocked":
        classification: HintClass = (
            "unsupported" if reason is BoundedReason.AUTH_REQUIRED else "unsafe"
        )
        _emit_hint(
            builder,
            target=target,
            locator=page,
            classification=classification,
            provider_id=target.claimed_provider_hint or "unknown",
            token=None,
            provenance_ids=provenance,
        )
        builder.finish(operation_id, "blocked")
        return
    if outcome != "succeeded":
        _emit_hint(
            builder,
            target=target,
            locator=page,
            classification="inconclusive",
            provider_id="unknown",
            token=None,
            provenance_ids=provenance,
        )
        builder.finish(
            operation_id,
            "rate_limited" if outcome == "rate_limited" else "failed",
        )
        return
    hint = _select_hint(page, hrefs, claimed=target.claimed_provider_hint)
    if resource is not None:
        add_local_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="routeClass",
            value=hint[0],
        )
        if hint[1] is not None:
            add_local_claim(
                builder,
                resource_id=resource.resource_id,
                field_name="builtInProviderId",
                value=hint[1].provider_id,
            )
    classification, matched, matched_locator = hint[0], hint[1], hint[2]
    emit_locator = matched_locator or page
    _emit_hint(
        builder,
        target=target,
        locator=emit_locator,
        classification=classification,
        provider_id=matched.provider_id if matched else "unknown",
        token=matched.token if matched else None,
        provenance_ids=provenance,
        adapter_id=None,
    )
    builder.finish(operation_id, "succeeded")


def _select_hint(
    page: SafeLocator,
    hrefs: Sequence[str],
    *,
    claimed: str | None,
) -> tuple[HintClass, BuiltInRouteHint | None, SafeLocator | None]:
    page_match = _match_builtin(page)
    if page_match is not None:
        return _class_for(page_match), page_match, page
    for raw in hrefs:
        try:
            locator = canonical_locator(raw)
        except EnumeratorError:
            continue
        matched = _match_builtin(locator)
        if matched is None:
            continue
        return _class_for(matched), matched, locator
    if claimed:
        # A claimed hint without matching public route evidence is detect-only
        # coverage intake, never an invented executable ATS from the domain.
        return (
            "detect_only",
            BuiltInRouteHint(
                provider_id=claimed.casefold(), support="detect", token=None
            ),
            page,
        )
    return "inconclusive", None, page


def _class_for(hint: BuiltInRouteHint) -> HintClass:
    if hint.support == "jobs":
        return "supported"
    if hint.support == "unsupported":
        return "unsupported"
    return "detect_only"


def _match_builtin(locator: SafeLocator) -> BuiltInRouteHint | None:
    host = locator.hostname
    parts = [part for part in urlsplit(locator.url).path.split("/") if part]
    if host in {"boards.greenhouse.io", "boards-api.greenhouse.io"}:
        token = _greenhouse_token(host, parts)
        if token:
            return BuiltInRouteHint("greenhouse", "jobs", token)
        return None
    if host in {"jobs.lever.co", "api.lever.co"}:
        token = _lever_token(host, parts)
        if token:
            return BuiltInRouteHint("lever", "jobs", token)
        return None
    if host in {"jobs.ashbyhq.com", "api.ashbyhq.com"}:
        token = _ashby_token(host, parts)
        if token:
            return BuiltInRouteHint("ashbyhq", "jobs", token)
        return None
    if host == "apply.workable.com" and parts and parts[0] != "api":
        return BuiltInRouteHint("workable", "jobs", parts[0])
    if host == "ats.rippling.com":
        if len(parts) >= 2 and parts[1] == "jobs":
            return BuiltInRouteHint("rippling", "jobs", parts[0])
        return None
    if host.endswith(".teamtailor.com"):
        return BuiltInRouteHint(
            "teamtailor",
            "jobs",
            host.removesuffix(".teamtailor.com"),
        )
    if host.endswith(".bamboohr.com"):
        return BuiltInRouteHint("bamboohr", "jobs", host.split(".")[0])
    if host.endswith(".myworkdayjobs.com"):
        return BuiltInRouteHint("workday", "jobs", host.split(".")[0])
    path = urlsplit(locator.url).path.casefold()
    if "/wp-json/" in path and "job" in path:
        return BuiltInRouteHint("wpjobmanager", "jobs", locator.origin)
    if host.endswith(".smartrecruiters.com") or host == "jobs.smartrecruiters.com":
        return BuiltInRouteHint(
            "smartrecruiters", "detect", parts[0] if parts else host
        )
    if host.endswith(".recruitee.com"):
        return BuiltInRouteHint("recruitee", "detect", host.split(".")[0])
    if host.endswith(".icims.com"):
        return BuiltInRouteHint("icims", "unsupported", host.split(".")[0])
    if host.endswith(".jobvite.com"):
        return BuiltInRouteHint("jobvite", "detect", parts[0] if parts else host)
    if host.endswith(".applytojob.com"):
        return BuiltInRouteHint("jazzhr", "detect", host.split(".")[0])
    return None


def _greenhouse_token(host: str, parts: Sequence[str]) -> str | None:
    if host == "boards-api.greenhouse.io":
        if len(parts) == 4 and parts[:2] == ["v1", "boards"] and parts[3] == "jobs":
            return parts[2]
        return None
    return parts[0] if parts else None


def _lever_token(host: str, parts: Sequence[str]) -> str | None:
    if host == "api.lever.co":
        if len(parts) >= 3 and parts[:2] == ["v0", "postings"]:
            return parts[2]
        return None
    return parts[0] if parts else None


def _ashby_token(host: str, parts: Sequence[str]) -> str | None:
    if host == "api.ashbyhq.com":
        if parts[:2] == ["posting-api", "job-board"] and len(parts) > 2:
            return parts[2]
        return None
    return parts[0] if parts else None


def _emit_hint(
    builder: ChannelRunBuilder,
    *,
    target: EmployerTarget,
    locator: SafeLocator,
    classification: HintClass,
    provider_id: str,
    token: str | None,
    provenance_ids: Sequence[str],
    adapter_id: str | None = None,
) -> None:
    if not provenance_ids:
        return
    kind: Literal["source", "board_route"] = (
        "board_route" if classification in {"supported", "detect_only"} else "source"
    )
    builder.add_occurrence(
        occurrence_from_locator(
            occurrence_id=f"targeted-ats:{target.target_id}:{classification}",
            channel="targeted_ats",
            locator=locator,
            provider_id=provider_id or "unknown",
            owner="targeted-ats",
            candidate_kind=kind,
            provenance_ids=tuple(provenance_ids),
            provider_token=token,
            adapter_id=adapter_id,
            key=target.target_id,
        )
    )
