"""Edge-path coverage for targeted ATS replay without network I/O."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from openopps.discovery.enumerators import (
    CapturedObservation,
    ChannelRunBuilder,
    EnumeratorError,
    digest_input_set,
)
from openopps.discovery.models import BoundedReason, ChannelBudget, ChannelProfile
from openopps.discovery.targeted_ats import (
    TARGETED_ATS_ENUMERATOR_VERSION,
    EmployerTarget,
    _run_target,
    classify_public_route,
    enumerate_targeted_ats_channel,
)


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
GREENHOUSE_PAGE = "https://boards.greenhouse.io/acme"
GREENHOUSE_ORIGIN = "https://boards.greenhouse.io:443"
CAREERS_PAGE = "https://careers.acme.example.test/jobs"
CAREERS_ORIGIN = "https://careers.acme.example.test:443"


def _budget(**updates: int) -> ChannelBudget:
    values = {
        "query_limit": 8,
        "request_limit": 12,
        "origin_limit": 8,
        "redirect_limit": 2,
        "page_limit": 2,
        "response_byte_limit": 8_000,
        "aggregate_byte_limit": 40_000,
        "candidate_limit": 20,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 16,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(updates)
    return ChannelBudget(**values)


def _profile(
    seed_ids: tuple[str, ...],
    origins: tuple[str, ...],
    **budget: int,
) -> ChannelProfile:
    return ChannelProfile(
        channel="targeted_ats",
        budget=_budget(**budget),
        seed_ids=seed_ids,
        allowed_origins=origins,
        allowed_query_keys=("board",),
        parser_ids=("html-links-v1",),
    )


def _target(
    target_id: str,
    locator: str,
    *,
    claimed: str | None = None,
) -> EmployerTarget:
    return EmployerTarget(
        target_id=target_id,
        public_page_locator=locator,
        claimed_provider_hint=claimed,
    )


def _html(*hrefs: str) -> bytes:
    anchors = "".join(f'<a href="{href}">x</a>' for href in hrefs)
    return f"<!doctype html><html><body>{anchors}</body></html>".encode()


def _observation(
    locator: str,
    *,
    status_code: int | None = 200,
    body: bytes | None = None,
    media_type: str | None = "text/html",
    transport_state: str = "response",
) -> CapturedObservation:
    return CapturedObservation(
        locator=locator,
        transport_state=transport_state,  # type: ignore[arg-type]
        status_code=status_code,
        body=body,
        media_type=media_type,
    )


def _enumerate(
    *,
    target_id: str,
    locator: str,
    origins: tuple[str, ...],
    observations: tuple[CapturedObservation, ...] = (),
    claimed: str | None = None,
    **budget: int,
):
    return enumerate_targeted_ats_channel(
        profile=_profile((target_id,), origins, **budget),
        targets=(_target(target_id, locator, claimed=claimed),),
        observations=observations,
        observed_at=OBSERVED_AT,
    )


@pytest.mark.parametrize(
    "locator",
    (
        pytest.param("", id="empty"),
        pytest.param("not-a-url", id="unparseable"),
        pytest.param("http://boards.greenhouse.io/acme", id="http-scheme"),
        pytest.param("https://127.0.0.1/jobs", id="ip-literal"),
        pytest.param("https://localhost/jobs", id="localhost"),
        pytest.param(" ftp://boards.greenhouse.io/acme", id="leading-space"),
    ),
)
def test_classify_public_route_returns_none_for_invalid_locators(locator: str) -> None:
    assert classify_public_route(locator) is None


@pytest.mark.parametrize(
    ("locator", "provider_id", "support", "token"),
    (
        pytest.param(
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
            "greenhouse",
            "jobs",
            "acme",
            id="greenhouse-api",
        ),
        pytest.param(
            "https://jobs.lever.co/acme",
            "lever",
            "jobs",
            "acme",
            id="lever-board",
        ),
        pytest.param(
            "https://api.lever.co/v0/postings/acme",
            "lever",
            "jobs",
            "acme",
            id="lever-api",
        ),
        pytest.param(
            "https://jobs.ashbyhq.com/acme",
            "ashbyhq",
            "jobs",
            "acme",
            id="ashby-board",
        ),
        pytest.param(
            "https://api.ashbyhq.com/posting-api/job-board/acme",
            "ashbyhq",
            "jobs",
            "acme",
            id="ashby-api",
        ),
        pytest.param(
            "https://apply.workable.com/acme",
            "workable",
            "jobs",
            "acme",
            id="workable",
        ),
        pytest.param(
            "https://ats.rippling.com/acme/jobs",
            "rippling",
            "jobs",
            "acme",
            id="rippling",
        ),
        pytest.param(
            "https://acme.teamtailor.com/jobs",
            "teamtailor",
            "jobs",
            "acme",
            id="teamtailor",
        ),
        pytest.param(
            "https://acme.bamboohr.com/careers",
            "bamboohr",
            "jobs",
            "acme",
            id="bamboohr",
        ),
        pytest.param(
            "https://acme.myworkdayjobs.com/External",
            "workday",
            "jobs",
            "acme",
            id="workday",
        ),
        pytest.param(
            "https://jobs.example.test/wp-json/wp/v2/job-listings",
            "wpjobmanager",
            "jobs",
            "https://jobs.example.test:443",
            id="wpjobmanager",
        ),
        pytest.param(
            "https://acme.recruitee.com/o",
            "recruitee",
            "detect",
            "acme",
            id="recruitee",
        ),
        pytest.param(
            "https://jobs.jobvite.com/acme",
            "jobvite",
            "detect",
            "acme",
            id="jobvite-token",
        ),
        pytest.param(
            "https://jobs.jobvite.com/",
            "jobvite",
            "detect",
            "jobs.jobvite.com",
            id="jobvite-host",
        ),
        pytest.param(
            "https://acme.applytojob.com/",
            "jazzhr",
            "detect",
            "acme",
            id="jazzhr",
        ),
    ),
)
def test_classify_public_route_matches_remaining_builtin_hosts(
    locator: str,
    provider_id: str,
    support: str,
    token: str,
) -> None:
    hint = classify_public_route(locator)
    assert hint is not None
    assert hint.provider_id == provider_id
    assert hint.support == support
    assert hint.token == token


@pytest.mark.parametrize(
    "locator",
    (
        pytest.param("https://boards.greenhouse.io/", id="greenhouse-board-no-token"),
        pytest.param(
            "https://boards-api.greenhouse.io/v1/boards/acme",
            id="greenhouse-api-incomplete",
        ),
        pytest.param("https://jobs.lever.co/", id="lever-board-no-token"),
        pytest.param("https://api.lever.co/v0/postings", id="lever-api-incomplete"),
        pytest.param("https://jobs.ashbyhq.com/", id="ashby-board-no-token"),
        pytest.param(
            "https://api.ashbyhq.com/posting-api/job-board",
            id="ashby-api-incomplete",
        ),
        pytest.param("https://ats.rippling.com/acme", id="rippling-without-jobs"),
        pytest.param("https://apply.workable.com/api/v3/accounts/acme", id="workable-api"),
    ),
)
def test_classify_public_route_rejects_incomplete_builtin_tokens(locator: str) -> None:
    assert classify_public_route(locator) is None


@pytest.mark.parametrize(
    ("seed_ids", "targets"),
    (
        pytest.param(("alpha",), (), id="empty-targets"),
        pytest.param(
            ("dup",),
            (
                _target("dup", "https://boards.greenhouse.io/a"),
                _target("dup", "https://boards.greenhouse.io/b"),
            ),
            id="duplicate-ids",
        ),
        pytest.param(
            ("alpha",),
            (_target("beta", GREENHOUSE_PAGE),),
            id="seed-mismatch",
        ),
        pytest.param(
            ("alpha", "beta"),
            (_target("alpha", GREENHOUSE_PAGE),),
            id="missing-seed",
        ),
    ),
)
def test_enumerate_rejects_empty_and_mismatched_employer_targets(
    seed_ids: tuple[str, ...],
    targets: tuple[EmployerTarget, ...],
) -> None:
    with pytest.raises(EnumeratorError, match="employer_targets"):
        enumerate_targeted_ats_channel(
            profile=_profile(seed_ids, (GREENHOUSE_ORIGIN,)),
            targets=targets,
            observations=(),
            observed_at=OBSERVED_AT,
        )


def test_run_target_blocks_when_locator_is_invalid_after_plan() -> None:
    profile = _profile(("blocked-page",), (CAREERS_ORIGIN,))
    builder = ChannelRunBuilder(
        channel="targeted_ats",
        enumerator_version=TARGETED_ATS_ENUMERATOR_VERSION,
        input_set_sha256=digest_input_set({"coverage": "invalid-locator"}),
        budget=profile.budget,
        observed_at=OBSERVED_AT,
    )
    builder.plan("blocked-page:page")
    _run_target(
        builder,
        profile=profile,
        target=_target("blocked-page", "http://careers.acme.example.test/jobs"),
        captured={},
    )
    receipt = builder.close()
    assert receipt.operation_outcomes == ("blocked",)
    assert receipt.request_receipts == ()
    assert receipt.occurrences == ()


def test_disallowed_origin_is_unsafe_without_emitting_a_request() -> None:
    receipt = _enumerate(
        target_id="off-origin",
        locator=CAREERS_PAGE,
        origins=(GREENHOUSE_ORIGIN,),
    )
    assert receipt.operation_outcomes == ("blocked",)
    assert receipt.request_receipts == ()
    assert receipt.occurrences == ()


def test_zero_request_budget_leaves_planned_operation_unstarted() -> None:
    receipt = _enumerate(
        target_id="no-budget",
        locator=GREENHOUSE_PAGE,
        origins=(GREENHOUSE_ORIGIN,),
        observations=(_observation(GREENHOUSE_PAGE, body=_html()),),
        query_limit=1,
        request_limit=0,
        concurrency_limit=0,
        per_origin_concurrency_limit=0,
    )
    assert receipt.operation_outcomes == ("unstarted",)
    assert receipt.accounting.unstarted == 1
    assert receipt.request_receipts == ()
    assert receipt.accounting.channel_state == "partial"


def test_missing_observation_is_inconclusive_failed_replay() -> None:
    receipt = _enumerate(
        target_id="missing-obs",
        locator=GREENHOUSE_PAGE,
        origins=(GREENHOUSE_ORIGIN,),
        observations=(),
    )
    assert receipt.operation_outcomes == ("failed",)
    assert receipt.request_receipts[0].outcome == "failed"
    assert receipt.request_receipts[0].reason_code is BoundedReason.EVIDENCE_INCOMPLETE
    assert receipt.occurrences == ()


def test_html_parser_rejection_fails_the_operation() -> None:
    bloated = b"<!doctype html><html><body>" + b"<p>n</p>" * 32 + b"</body></html>"
    receipt = _enumerate(
        target_id="parser-reject",
        locator=GREENHOUSE_PAGE,
        origins=(GREENHOUSE_ORIGIN,),
        observations=(_observation(GREENHOUSE_PAGE, body=bloated),),
        parser_depth_limit=1,
    )
    assert receipt.operation_outcomes == ("failed",)
    assert receipt.request_receipts[0].reason_code is BoundedReason.PARSER_REJECTED
    assert all(
        not item.occurrence_id.endswith("supported") for item in receipt.occurrences
    )


@pytest.mark.parametrize(
    ("status_code", "transport_state", "request_outcome", "operation_outcome", "reason"),
    (
        pytest.param(
            429,
            "response",
            "rate_limited",
            "rate_limited",
            BoundedReason.RATE_LIMITED,
            id="http-429",
        ),
        pytest.param(
            500,
            "response",
            "failed",
            "failed",
            BoundedReason.ACCESS_BLOCKED,
            id="http-500",
        ),
        pytest.param(
            None,
            "network_unreachable",
            "failed",
            "failed",
            BoundedReason.TRANSPORT_REJECTED,
            id="network-unreachable",
        ),
    ),
)
def test_unsuccessful_observations_finish_failed_or_rate_limited(
    status_code: int | None,
    transport_state: str,
    request_outcome: str,
    operation_outcome: str,
    reason: BoundedReason,
) -> None:
    receipt = _enumerate(
        target_id="unsuccessful",
        locator=GREENHOUSE_PAGE,
        origins=(GREENHOUSE_ORIGIN,),
        observations=(
            _observation(
                GREENHOUSE_PAGE,
                status_code=status_code,
                body=None,
                media_type=None,
                transport_state=transport_state,
            ),
        ),
    )
    assert receipt.operation_outcomes == (operation_outcome,)
    assert receipt.request_receipts[0].outcome == request_outcome
    assert receipt.request_receipts[0].reason_code is reason
    assert receipt.occurrences == ()


def test_select_hint_matches_ats_href_after_skipping_invalid_and_unmatched() -> None:
    body = _html(
        "javascript:alert(1)",
        "http://jobs.lever.co/skip",
        "/relative",
        "https://127.0.0.1/jobs",
        "https://careers.other.example.test/openings",
        "https://jobs.lever.co/acme",
    )
    receipt = _enumerate(
        target_id="href-lever",
        locator=CAREERS_PAGE,
        origins=(CAREERS_ORIGIN,),
        observations=(_observation(CAREERS_PAGE, body=body),),
    )
    assert receipt.operation_outcomes == ("succeeded",)
    assert len(receipt.occurrences) == 1
    occurrence = receipt.occurrences[0]
    assert occurrence.occurrence_id.endswith("supported")
    assert occurrence.identity.provider_id == "lever"
    assert occurrence.identity.provider_token == "acme"
    assert occurrence.identity.canonical_url == "https://jobs.lever.co/acme"
    assert occurrence.identity.canonical_url != CAREERS_PAGE
