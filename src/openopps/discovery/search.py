"""Bounded public no-auth search enumerator (E431-E436)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from openopps.discovery.diagnostics import render_metric_attributes
from openopps.discovery.enumerators import (
    CapturedObservation,
    ChannelRunBuilder,
    EnumeratorError,
    add_local_claim,
    admit_observation_resource,
    canonical_locator,
    digest_input_set,
    lookup_observation,
    observation_digest,
    observation_map,
    occurrence_from_locator,
    origin_allowed,
    parse_bounded_json,
    request_outcome_from_observation,
    require_channel_profile,
    require_observed_at,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelProfile,
    ChannelReplayReceipt,
    DiscoveryChannel,
)
from openopps.discovery.transport import SafeLocator


SEARCH_ENUMERATOR_VERSION = "search-fixture-v1"


@dataclass(frozen=True, slots=True)
class SearchQuerySet:
    """Finite explicit maintainer-owned search queries."""

    queries: tuple[str, ...]

    @property
    def digest(self) -> str:
        return digest_input_set(list(self.queries))


@dataclass(frozen=True, slots=True)
class SearchApiProfile:
    """Public no-auth search API profile. Authenticated APIs stay blocked."""

    profile_id: str
    locator: str
    available: bool = True
    auth_required: bool = False
    pagination_key: str = "next"


def enumerate_search_channel(
    *,
    profile: ChannelProfile,
    query_set: SearchQuerySet,
    api: SearchApiProfile,
    observations: Sequence[CapturedObservation] | Mapping[str, CapturedObservation],
    observed_at: datetime,
) -> ChannelReplayReceipt:
    """Replay finite search discovery without recursive query expansion."""

    profile = require_channel_profile(profile, "search")
    observed_at = require_observed_at(observed_at)
    queries = _validate_query_set(profile, query_set)
    api_locator = canonical_locator(api.locator)
    if not origin_allowed(profile, api_locator):
        raise EnumeratorError("search_origin")
    captured = observation_map(observations)
    query_digest = query_set.digest
    input_digest = digest_input_set(
        {
            "api": {
                "authRequired": api.auth_required,
                "available": api.available,
                "locator": api_locator.url,
                "paginationKey": api.pagination_key,
                "profileId": api.profile_id,
            },
            "enumeratorVersion": SEARCH_ENUMERATOR_VERSION,
            "observations": [
                observation_digest(captured[key]) for key in sorted(captured)
            ],
            "querySetSha256": query_digest,
            "seedIds": list(profile.seed_ids),
        }
    )
    builder = ChannelRunBuilder(
        channel="search",
        enumerator_version=SEARCH_ENUMERATOR_VERSION,
        input_set_sha256=input_digest,
        budget=profile.budget,
        observed_at=observed_at,
    )
    selected = queries[: profile.budget.query_limit]
    for index, _query in enumerate(selected):
        builder.plan(f"query-{index:04d}")
    if api.auth_required or not api.available:
        for index, _query in enumerate(selected):
            builder.finish(f"query-{index:04d}", "blocked")
        return builder.close()
    seen_locators: set[str] = set()
    for index, _query in enumerate(selected):
        _run_query(
            builder,
            profile=profile,
            api=api,
            api_locator=api_locator,
            query_index=index,
            query_digest=query_digest,
            captured=captured,
            seen_locators=seen_locators,
        )
    return builder.close()


def search_metric_attributes(
    receipt: ChannelReplayReceipt,
    *,
    query_set: SearchQuerySet,
) -> Mapping[str, bool | str]:
    """Channel metrics identify the query-set digest, never raw query text."""

    return render_metric_attributes(
        channel=DiscoveryChannel.SEARCH,
        terminal_state=receipt.accounting.channel_state,
        reason_code=(
            BoundedReason.NONE
            if receipt.accounting.channel_state == "complete"
            else BoundedReason.BUDGET_EXHAUSTED
            if receipt.accounting.unfinished_operation_ids
            else BoundedReason.EVIDENCE_INCOMPLETE
        ),
        complete=receipt.accounting.channel_state == "complete",
        identity_digest=query_set.digest,
    )


def _validate_query_set(
    profile: ChannelProfile,
    query_set: SearchQuerySet,
) -> tuple[str, ...]:
    queries = query_set.queries
    if (
        not queries
        or any(not item or not isinstance(item, str) for item in queries)
        or queries != tuple(sorted(set(queries)))
        or len(queries) > profile.budget.query_limit
    ):
        raise EnumeratorError("search_query_set")
    expected_ids = tuple(f"query-{index:04d}" for index in range(len(queries)))
    if profile.seed_ids != expected_ids:
        raise EnumeratorError("search_query_set")
    return queries


def _run_query(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    api: SearchApiProfile,
    api_locator: SafeLocator,
    query_index: int,
    query_digest: str,
    captured: Mapping[str, CapturedObservation],
    seen_locators: set[str],
) -> None:
    operation_id = f"query-{query_index:04d}"
    locator = api_locator
    if not builder.can_start():
        return
    pages = 0
    pending: list[SafeLocator] = [locator]
    attempt: str = "initial"
    saw_success = False
    saw_failure = False
    saw_block = False
    saw_rate_limit = False
    while pending and pages < profile.budget.page_limit:
        if not builder.can_start():
            break
        current = pending.pop(0)
        if not isinstance(current, SafeLocator):
            current = canonical_locator(current)
        pages += 1
        observation = lookup_observation(captured, current)
        if observation is None:
            builder.add_request(
                operation_id,
                attempt_kind=attempt,  # type: ignore[arg-type]
                outcome="failed",
                locator=current,
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
        results: tuple[str, ...] = ()
        next_locator = None
        if outcome == "succeeded" and observation.body is not None:
            try:
                results, next_locator = _parse_search_page(
                    observation.body,
                    pagination_key=api.pagination_key,
                    depth_limit=profile.budget.parser_depth_limit,
                )
                resource = admit_observation_resource(
                    builder,
                    observation,
                    current,
                    role="search-evidence",
                    media_type=observation.media_type or "application/json",
                )
            except EnumeratorError:
                outcome = "failed"
                reason = BoundedReason.PARSER_REJECTED
        builder.add_request(
            operation_id,
            attempt_kind=attempt,  # type: ignore[arg-type]
            outcome=outcome,
            locator=current,
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
        add_local_claim(
            builder,
            resource_id=resource.resource_id,
            field_name="querySetSha256",
            value=query_digest,
        )
        for ordinal, raw in enumerate(results):
            try:
                candidate = canonical_locator(raw)
            except EnumeratorError:
                continue
            duplicate = candidate.url in seen_locators
            seen_locators.add(candidate.url)
            suffix = f"{operation_id}:p{pages:02d}:{ordinal:04d}"
            if duplicate:
                suffix = f"{suffix}:duplicate"
            builder.add_occurrence(
                occurrence_from_locator(
                    occurrence_id=f"search:{suffix}",
                    channel="search",
                    locator=candidate,
                    provider_id="search",
                    owner="search",
                    candidate_kind="source",
                    provenance_ids=(resource.resource_id,),
                )
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


def _parse_search_page(
    body: bytes,
    *,
    pagination_key: str,
    depth_limit: int,
) -> tuple[tuple[str, ...], str | None]:
    value = parse_bounded_json(body, depth_limit=depth_limit)
    if not isinstance(value, dict):
        raise EnumeratorError("parser_rejected")
    locators: list[str] = []
    results = value.get("results")
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            for key in ("url", "locator", "html_url"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate:
                    locators.append(candidate)
                    break
    nxt = value.get(pagination_key)
    next_locator = nxt if isinstance(nxt, str) and nxt else None
    return tuple(locators), next_locator
