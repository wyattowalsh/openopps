"""Bounded official catalog and documentation enumerator (E411-E417)."""

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
    parse_bounded_json,
    parse_bounded_xml,
    parse_html_locators,
    request_outcome_from_observation,
    require_channel_profile,
    require_observed_at,
    sitemap_entries,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelProfile,
    ChannelReplayReceipt,
)
from openopps.discovery.robots import (
    RobotsTransportState,
    admit_public_sitemap_locators,
    evaluate_robots,
)
from openopps.discovery.transport import SafeLocator


OFFICIAL_ENUMERATOR_VERSION = "official-fixture-v1"
DEFAULT_PRODUCT_TOKEN = "OpenOppsBot"
_ROBOTS_STATES: Mapping[str, RobotsTransportState] = {
    "response": "response",
    "network_unreachable": "network_unreachable",
    "security_rejected_redirect": "security_rejected_redirect",
    "verified_cache": "verified_cache",
}


@dataclass(frozen=True, slots=True)
class OfficialSeed:
    """Maintainer-owned official catalog or documentation seed."""

    seed_id: str
    document_locator: str
    parser_id: str
    robots_locator: str | None = None
    sitemap_locator: str | None = None


def enumerate_official_channel(
    *,
    profile: ChannelProfile,
    seeds: Sequence[OfficialSeed],
    observations: Sequence[CapturedObservation] | Mapping[str, CapturedObservation],
    observed_at: datetime,
    product_token: str = DEFAULT_PRODUCT_TOKEN,
) -> ChannelReplayReceipt:
    """Replay finite official-document discovery without live network access."""

    profile = require_channel_profile(profile, "official")
    observed_at = require_observed_at(observed_at)
    seed_values = _validate_seeds(profile, seeds)
    captured = observation_map(observations)
    input_digest = digest_input_set(
        {
            "allowedOrigins": list(profile.allowed_origins),
            "enumeratorVersion": OFFICIAL_ENUMERATOR_VERSION,
            "observations": [
                observation_digest(captured[key]) for key in sorted(captured)
            ],
            "parserIds": list(profile.parser_ids),
            "productToken": product_token,
            "seedIds": list(profile.seed_ids),
            "seeds": [
                {
                    "documentLocator": seed.document_locator,
                    "parserId": seed.parser_id,
                    "robotsLocator": seed.robots_locator,
                    "seedId": seed.seed_id,
                    "sitemapLocator": seed.sitemap_locator,
                }
                for seed in seed_values
            ],
        }
    )
    builder = ChannelRunBuilder(
        channel="official",
        enumerator_version=OFFICIAL_ENUMERATOR_VERSION,
        input_set_sha256=input_digest,
        budget=profile.budget,
        observed_at=observed_at,
    )
    selected = seed_values[: profile.budget.query_limit]
    for seed in selected:
        builder.plan(f"{seed.seed_id}:robots")
        if seed.sitemap_locator is not None:
            builder.plan(f"{seed.seed_id}:sitemap")
        builder.plan(f"{seed.seed_id}:document")
    for seed in selected:
        _run_seed(
            builder,
            profile=profile,
            seed=seed,
            captured=captured,
            product_token=product_token,
        )
    return builder.close()


def _validate_seeds(
    profile: ChannelProfile,
    seeds: Sequence[OfficialSeed],
) -> tuple[OfficialSeed, ...]:
    if not seeds:
        raise EnumeratorError("official_seeds")
    ordered = tuple(sorted(seeds, key=lambda seed: seed.seed_id))
    identities = tuple(seed.seed_id for seed in ordered)
    if identities != tuple(sorted(set(identities))):
        raise EnumeratorError("official_seeds")
    if identities != profile.seed_ids:
        raise EnumeratorError("official_seeds")
    for seed in ordered:
        if seed.parser_id not in profile.parser_ids:
            raise EnumeratorError("official_parser")
        canonical_locator(seed.document_locator)
        if seed.robots_locator is not None:
            canonical_locator(seed.robots_locator)
        if seed.sitemap_locator is not None:
            canonical_locator(seed.sitemap_locator)
    return ordered


def _run_seed(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: OfficialSeed,
    captured: Mapping[str, CapturedObservation],
    product_token: str,
) -> None:
    document = canonical_locator(seed.document_locator)
    robots_locator = canonical_locator(
        seed.robots_locator or f"https://{document.hostname}/robots.txt"
    )
    origin_blocked, admitted_sitemaps = _run_robots(
        builder,
        profile=profile,
        seed=seed,
        robots_locator=robots_locator,
        document=document,
        captured=captured,
        product_token=product_token,
    )
    sitemap_id = f"{seed.seed_id}:sitemap"
    if admitted_sitemaps and sitemap_id not in builder.planned_ids:
        builder.plan(sitemap_id)
    _run_sitemap(
        builder,
        profile=profile,
        seed=seed,
        document=document,
        captured=captured,
        origin_blocked=origin_blocked,
        admitted_sitemaps=admitted_sitemaps,
    )
    _run_document(
        builder,
        profile=profile,
        seed=seed,
        document=document,
        captured=captured,
        origin_blocked=origin_blocked,
    )


def _run_robots(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: OfficialSeed,
    robots_locator: SafeLocator,
    document: SafeLocator,
    captured: Mapping[str, CapturedObservation],
    product_token: str,
) -> tuple[bool, tuple[SafeLocator, ...]]:
    operation_id = f"{seed.seed_id}:robots"
    if not origin_allowed(profile, robots_locator):
        builder.finish(operation_id, "blocked")
        return True, ()
    if not builder.can_start():
        return True, ()
    observation = lookup_observation(captured, robots_locator)
    if observation is None:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=robots_locator,
            resource_id=None,
            response_status=None,
            admitted_bytes=0,
            elapsed_ms=0,
            reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
        )
        builder.finish(operation_id, "failed")
        return True, ()
    outcome, reason = request_outcome_from_observation(observation)
    transport_state = _ROBOTS_STATES.get(observation.transport_state)
    if transport_state is None:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome=outcome,
            locator=robots_locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=reason,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "failed")
        return True, ()
    decision = evaluate_robots(
        transport_state=transport_state,
        status_code=observation.status_code,
        body=observation.body,
        product_token=product_token,
        request_target=document.url,
        cached_age_seconds=observation.cached_age_seconds,
    )
    resource = None
    if observation.body is not None and decision.policy is not None:
        resource = admit_observation_resource(
            builder,
            observation,
            robots_locator,
            role="robots-evidence",
            media_type=observation.media_type or "text/plain",
        )
    request_outcome: Literal[
        "succeeded", "blocked", "rate_limited", "timed_out", "failed", "cancelled"
    ]
    request_reason: BoundedReason
    if decision.access == "allowed":
        request_outcome = "succeeded"
        request_reason = BoundedReason.NONE
        operation_outcome: Literal[
            "succeeded", "blocked", "rate_limited", "timed_out", "failed"
        ] = "succeeded"
        origin_blocked = False
    else:
        request_outcome = "blocked"
        request_reason = decision.reason_code
        operation_outcome = "blocked"
        origin_blocked = True
    builder.add_request(
        operation_id,
        attempt_kind="initial",
        outcome=request_outcome,
        locator=robots_locator,
        resource_id=None if resource is None else resource.resource_id,
        response_status=observation.status_code,
        admitted_bytes=0 if resource is None else resource.size_bytes,
        elapsed_ms=observation.elapsed_ms,
        reason_code=request_reason,
        validated_address=observation.validated_address,
    )
    if resource is not None:
        add_local_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="robotsAccess",
            value=decision.access,
        )
        add_local_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="robotsReused",
            value="true" if decision.reused else "false",
        )
        raw_sitemaps = decision.policy.sitemap_locators if decision.policy else ()
        add_remote_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="robotsSitemapObservations",
            value=",".join(raw_sitemaps) if raw_sitemaps else None,
        )
    builder.finish(operation_id, operation_outcome)
    if decision.policy is None:
        return origin_blocked, ()
    admitted = admit_public_sitemap_locators(decision.policy.sitemap_locators)
    same_origin = tuple(
        locator
        for locator in admitted
        if locator.hostname == document.hostname and origin_allowed(profile, locator)
    )
    return origin_blocked, same_origin


def _run_sitemap(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: OfficialSeed,
    document: SafeLocator,
    captured: Mapping[str, CapturedObservation],
    origin_blocked: bool,
    admitted_sitemaps: Sequence[SafeLocator],
) -> None:
    operation_id = f"{seed.seed_id}:sitemap"
    if operation_id not in builder.planned_ids:
        return
    if origin_blocked:
        builder.finish(operation_id, "blocked")
        return
    targets: list[SafeLocator] = []
    seen: set[str] = set()
    if seed.sitemap_locator is not None:
        seed_sitemap = canonical_locator(seed.sitemap_locator)
        if seed_sitemap.hostname == document.hostname and origin_allowed(
            profile, seed_sitemap
        ):
            targets.append(seed_sitemap)
            seen.add(seed_sitemap.url)
    for locator in admitted_sitemaps:
        if locator.url not in seen:
            targets.append(locator)
            seen.add(locator.url)
    if not targets:
        builder.finish(operation_id, "blocked")
        return
    if not builder.can_start():
        return
    pages = 0
    pending: list[tuple[SafeLocator, bool]] = [(target, False) for target in targets]
    saw_success = False
    saw_block = False
    saw_failure = False
    saw_rate_limit = False
    attempt: Literal["initial", "pagination"] = "initial"
    while pending and pages < profile.budget.page_limit:
        if not builder.can_start():
            break
        locator, nested = pending.pop(0)
        pages += 1
        observation = lookup_observation(captured, locator)
        if observation is None:
            builder.add_request(
                operation_id,
                attempt_kind=attempt,
                outcome="failed",
                locator=locator,
                resource_id=None,
                response_status=None,
                admitted_bytes=0,
                elapsed_ms=0,
                reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
            )
            saw_failure = True
            attempt = "pagination"
            continue
        outcome, reason = request_outcome_from_observation(observation)
        resource = None
        kind = None
        entries: tuple[tuple[str, str | None], ...] = ()
        if outcome == "succeeded" and observation.body is not None:
            try:
                root = parse_bounded_xml(
                    observation.body,
                    depth_limit=profile.budget.parser_depth_limit,
                )
                kind, entries = sitemap_entries(root)
                resource = admit_observation_resource(
                    builder,
                    observation,
                    locator,
                    role="sitemap-evidence",
                    media_type=observation.media_type or "application/xml",
                )
            except EnumeratorError:
                outcome = "failed"
                reason = BoundedReason.PARSER_REJECTED
        builder.add_request(
            operation_id,
            attempt_kind=attempt,
            outcome=outcome,
            locator=locator,
            resource_id=None if resource is None else resource.resource_id,
            response_status=observation.status_code,
            admitted_bytes=0 if resource is None else resource.size_bytes,
            elapsed_ms=observation.elapsed_ms,
            reason_code=reason,
            validated_address=observation.validated_address,
        )
        attempt = "pagination"
        if outcome == "rate_limited":
            saw_rate_limit = True
            continue
        if outcome == "blocked":
            saw_block = True
            continue
        if outcome != "succeeded" or resource is None:
            saw_failure = True
            continue
        saw_success = True
        _record_sitemap_entries(
            builder,
            profile=profile,
            seed=seed,
            document=document,
            resource_id=resource.resource_id,
            kind=kind or "urlset",
            entries=entries,
            nested=nested,
            pending=pending,
        )
    if saw_rate_limit and not saw_success:
        builder.finish(operation_id, "rate_limited")
    elif saw_block and not saw_success:
        builder.finish(operation_id, "blocked")
    elif saw_failure and not saw_success:
        builder.finish(operation_id, "failed")
    else:
        builder.finish(operation_id, "succeeded")


def _record_sitemap_entries(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: OfficialSeed,
    document: SafeLocator,
    resource_id: str,
    kind: str,
    entries: Sequence[tuple[str, str | None]],
    nested: bool,
    pending: list[tuple[SafeLocator, bool]],
) -> None:
    lastmod_by_url: dict[str, str | None] = {}
    raw_locators: list[str] = []
    for raw_locator, lastmod in entries:
        raw_locators.append(raw_locator)
        try:
            lastmod_by_url[canonical_locator(raw_locator).url] = lastmod
        except EnumeratorError:
            continue
    admitted = admit_public_sitemap_locators(raw_locators)
    for ordinal, locator in enumerate(admitted):
        if locator.hostname != document.hostname:
            continue
        if not origin_allowed(profile, locator):
            continue
        lastmod = lastmod_by_url.get(locator.url)
        if lastmod:
            add_remote_claim(
                builder,
                resource_id=resource_id,
                field_name=f"lastmod:{ordinal}",
                value=lastmod,
            )
        if kind == "sitemapindex" and not nested:
            pending.append((locator, True))
            continue
        if kind == "urlset":
            _emit_official_occurrence(
                builder,
                seed=seed,
                locator=locator,
                candidate_kind="source",
                provenance_ids=(resource_id,),
                suffix=f"sitemap-{ordinal:04d}",
            )


def _run_document(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: OfficialSeed,
    document: SafeLocator,
    captured: Mapping[str, CapturedObservation],
    origin_blocked: bool,
) -> None:
    operation_id = f"{seed.seed_id}:document"
    if origin_blocked or not origin_allowed(profile, document):
        builder.finish(operation_id, "blocked")
        return
    if not builder.can_start():
        return
    pages = 0
    pending: list[SafeLocator] = [document]
    attempt: Literal["initial", "pagination"] = "initial"
    saw_success = False
    saw_failure = False
    saw_block = False
    saw_rate_limit = False
    while pending and pages < profile.budget.page_limit:
        if not builder.can_start():
            break
        locator = pending.pop(0)
        pages += 1
        observation = lookup_observation(captured, locator)
        if observation is None:
            builder.add_request(
                operation_id,
                attempt_kind=attempt,
                outcome="failed",
                locator=locator,
                resource_id=None,
                response_status=None,
                admitted_bytes=0,
                elapsed_ms=0,
                reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
            )
            saw_failure = True
            attempt = "pagination"
            continue
        outcome, reason = request_outcome_from_observation(observation)
        resource = None
        extracted: tuple[str, ...] = ()
        next_locator = None
        if outcome == "succeeded" and observation.body is not None:
            try:
                extracted, next_locator = _parse_official_document(
                    observation.body,
                    parser_id=seed.parser_id,
                    depth_limit=profile.budget.parser_depth_limit,
                )
                media = observation.media_type or _media_for_parser(seed.parser_id)
                resource = admit_observation_resource(
                    builder,
                    observation,
                    locator,
                    role="parser-evidence",
                    media_type=media,
                )
            except EnumeratorError:
                outcome = "failed"
                reason = BoundedReason.PARSER_REJECTED
        if observation.status_code == 304 or observation.transport_state in {
            "not_modified",
            "verified_cache",
        }:
            outcome = "succeeded"
            reason = BoundedReason.NONE
        builder.add_request(
            operation_id,
            attempt_kind=attempt,
            outcome=outcome,
            locator=locator,
            resource_id=None if resource is None else resource.resource_id,
            response_status=observation.status_code,
            admitted_bytes=0 if resource is None else resource.size_bytes,
            elapsed_ms=observation.elapsed_ms,
            reason_code=reason,
            validated_address=observation.validated_address,
        )
        attempt = "pagination"
        if outcome == "rate_limited":
            saw_rate_limit = True
            continue
        if outcome == "blocked":
            saw_block = True
            continue
        if outcome != "succeeded":
            saw_failure = True
            continue
        saw_success = True
        if resource is None:
            continue
        add_local_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="parserId",
            value=seed.parser_id,
        )
        _emit_official_occurrence(
            builder,
            seed=seed,
            locator=locator,
            candidate_kind="catalog",
            provenance_ids=(resource.resource_id,),
            suffix="document",
            key=seed.seed_id,
        )
        for ordinal, raw in enumerate(extracted):
            try:
                candidate = canonical_locator(raw)
            except EnumeratorError:
                continue
            if not origin_allowed(profile, candidate) and (
                candidate.hostname != document.hostname
            ):
                continue
            _emit_official_occurrence(
                builder,
                seed=seed,
                locator=candidate,
                candidate_kind="source",
                provenance_ids=(resource.resource_id,),
                suffix=f"item-{ordinal:04d}",
            )
        if next_locator is not None:
            try:
                nxt = canonical_locator(next_locator)
            except EnumeratorError:
                nxt = None
            if nxt is not None and origin_allowed(profile, nxt):
                pending.append(nxt)
    if saw_rate_limit and not saw_success:
        builder.finish(operation_id, "rate_limited")
    elif saw_block and not saw_success:
        builder.finish(operation_id, "blocked")
    elif saw_failure and not saw_success:
        builder.finish(operation_id, "failed")
    else:
        builder.finish(operation_id, "succeeded")


def _parse_official_document(
    body: bytes,
    *,
    parser_id: str,
    depth_limit: int,
) -> tuple[tuple[str, ...], str | None]:
    if parser_id == "official-json-v1":
        value = parse_bounded_json(body, depth_limit=depth_limit)
        if not isinstance(value, dict):
            raise EnumeratorError("parser_rejected")
        locators: list[str] = []
        items = value.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key in ("jobs", "url", "locator"):
                    candidate = item.get(key)
                    if isinstance(candidate, str) and candidate:
                        locators.append(candidate)
                        break
        nxt = value.get("next")
        next_locator = nxt if isinstance(nxt, str) and nxt else None
        return tuple(locators), next_locator
    if parser_id == "html-links-v1":
        return parse_html_locators(body, node_limit=max(depth_limit, 1) * 16), None
    raise EnumeratorError("official_parser")


def _media_for_parser(parser_id: str) -> str:
    if parser_id == "html-links-v1":
        return "text/html"
    return "application/json"


def _emit_official_occurrence(
    builder: ChannelRunBuilder,
    *,
    seed: OfficialSeed,
    locator: SafeLocator,
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"],
    provenance_ids: Sequence[str],
    suffix: str,
    key: str | None = None,
) -> None:
    parsed = urlsplit(locator.url)
    occurrence_id = f"official:{seed.seed_id}:{suffix}"
    builder.add_occurrence(
        occurrence_from_locator(
            occurrence_id=occurrence_id,
            channel="official",
            locator=locator,
            provider_id="official",
            owner="official",
            candidate_kind=candidate_kind,
            provenance_ids=provenance_ids,
            key=key or f"{parsed.hostname}-{suffix}",
        )
    )
