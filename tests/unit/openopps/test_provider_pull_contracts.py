from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from openopps.models import JobRecord, JsonDict, PostingKind
from openopps.providers.base import JobFetchResult
from openopps.providers.pull import (
    DetailCoverageEvidence,
    InterfaceStability,
    MembershipEvidence,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderListResult,
    ProviderPosting,
    ProviderPullCapabilities,
    ProviderPullBudgetError,
    ProviderRouteIdentity,
    ProviderTargetKind,
    ProviderUrlTarget,
    bounded_async_map,
    decode_url_identity_segment,
    ensure_detail_fanout_within_budget,
)


def _job(
    remote_id: str = "123",
    *,
    board_key: str = "acme",
    provider_id: str = "greenhouse",
    listing: JsonDict | None = None,
    detail: JsonDict | None = None,
    posting_kind: PostingKind = "standard",
) -> JobRecord:
    raw_listing = listing if listing is not None else {"id": remote_id}
    raw_detail = detail if detail is not None else {}
    return JobRecord(
        id=f"{board_key}:{provider_id}:{remote_id}",
        board_key=board_key,
        provider_id=provider_id,
        remote_id=remote_id,
        title="Engineer",
        posting_url=f"https://boards.greenhouse.io/acme/jobs/{remote_id}",
        raw_listing=raw_listing,
        raw_detail=raw_detail,
        posting_kind=posting_kind,
    )


def _posting(remote_id: str = "123") -> ProviderPosting:
    job = _job(remote_id, detail={"content": "Build reliable systems."})
    return ProviderPosting(
        job=job,
        listing=job.raw_listing,
        detail=job.raw_detail,
    )


def _posting_without_detail(
    remote_id: str = "123",
    *,
    board_key: str = "acme",
    provider_id: str = "greenhouse",
    posting_kind: PostingKind = "standard",
) -> ProviderPosting:
    job = _job(
        remote_id,
        board_key=board_key,
        provider_id=provider_id,
        detail={},
        posting_kind=posting_kind,
    )
    return ProviderPosting(job=job, listing=job.raw_listing, detail=None)


def _membership(
    observed_count: int,
    *,
    scope: MembershipScope = MembershipScope.LISTED,
    authoritative: bool = True,
) -> MembershipEvidence:
    return MembershipEvidence(
        scope=scope,
        authoritative=authoritative,
        complete=True,
        terminal_page_seen=True,
        pages_fetched=1,
        observed_count=observed_count,
        advertised_count=observed_count if authoritative else None,
    )


@pytest.mark.parametrize(
    "value",
    [
        "bad%",
        "%2F",
        "%3F",
        "%23",
        "%5C",
        "%20",
        "%252F",
        "%253F",
        "%2541",
        "%25ZZ",
        "%25",
        ".",
        "..",
    ],
)
def test_url_identity_decoder_rejects_delimiters_and_malformed_escapes(
    value: str,
) -> None:
    assert decode_url_identity_segment(value) is None


def test_url_identity_decoder_preserves_safe_punctuation_and_utf8() -> None:
    assert decode_url_identity_segment("job.1-_%E2%9C%93") == "job.1-_✓"


def test_posting_target_projects_to_retained_board_route_for_scan() -> None:
    posting = ProviderUrlTarget(
        provider_id="example",
        target_kind=ProviderTargetKind.POSTING,
        url="https://jobs.example.test/acme/jobs/job.1",
        board_identity="acme",
        posting_identity="job.1",
        route=ProviderRouteIdentity(token="acme", host="jobs.example.test"),
    )

    board = posting.for_board_scan()

    assert board.target_kind == ProviderTargetKind.BOARD
    assert board.posting_identity is None
    assert board.board_identity == posting.board_identity
    assert board.route == posting.route
    assert board.url == posting.url


@pytest.mark.asyncio
async def test_bounded_async_map_limits_workers_and_preserves_order() -> None:
    active = 0
    peak = 0

    async def worker(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return value * value

    result = await bounded_async_map(tuple(range(8)), worker, max_concurrency=2)

    assert result == [value * value for value in range(8)]
    assert peak == 2


def test_detail_fanout_budget_fails_before_worker_scheduling() -> None:
    with pytest.raises(ProviderPullBudgetError, match="detail fan-out limit") as exc_info:
        ensure_detail_fanout_within_budget(3, maximum_details=2)

    assert exc_info.value.reason == "detail fan-out"
    assert exc_info.value.limit == 2
    assert exc_info.value.observed == 3


def _source_list(
    *postings: ProviderPosting,
    provider_id: str = "greenhouse",
    board_identity: str = "acme",
    scope: MembershipScope = MembershipScope.LISTED,
    authoritative: bool = True,
) -> ProviderListResult:
    return ProviderListResult(
        provider_id=provider_id,
        board_identity=board_identity,
        postings=postings,
        membership=_membership(
            len(postings), scope=scope, authoritative=authoritative
        ),
    )


def test_provider_url_target_preserves_board_and_posting_identity() -> None:
    target = ProviderUrlTarget(
        provider_id="greenhouse",
        target_kind=ProviderTargetKind.POSTING,
        url="https://boards.greenhouse.io/acme/jobs/123?source=careers",
        board_identity="acme",
        posting_identity="123",
        route=ProviderRouteIdentity(token="acme"),
    )

    assert target.board_identity == "acme"
    assert target.posting_identity == "123"
    assert target.route.token == "acme"
    assert target.url == "https://boards.greenhouse.io/acme/jobs/123"
    assert target.model_dump(mode="json")["target_kind"] == "posting"


def test_provider_url_target_rejects_unbounded_url_material() -> None:
    with pytest.raises(ValidationError, match="at most 2000"):
        ProviderUrlTarget(
            provider_id="greenhouse",
            target_kind=ProviderTargetKind.BOARD,
            url=f"https://boards.greenhouse.io/{'a' * 2_000}",
            board_identity="acme",
        )


@pytest.mark.parametrize(
    ("target_kind", "posting_identity"),
    [
        (ProviderTargetKind.BOARD, "123"),
        (ProviderTargetKind.POSTING, None),
    ],
)
def test_provider_url_target_rejects_incompatible_exact_identity(
    target_kind: ProviderTargetKind,
    posting_identity: str | None,
) -> None:
    with pytest.raises(ValidationError, match="posting identity"):
        ProviderUrlTarget(
            provider_id="greenhouse",
            target_kind=target_kind,
            url="https://boards.greenhouse.io/acme/jobs/123",
            board_identity="acme",
            posting_identity=posting_identity,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"board_scan_get_supported": True},
        {"enumerate_unlisted_supported": True},
        {"exact_unlisted_get_supported": True},
    ],
)
def test_provider_pull_capabilities_reject_impossible_combinations(
    updates: dict[str, bool],
) -> None:
    with pytest.raises(ValidationError):
        ProviderPullCapabilities(
            interface_stability=InterfaceStability.DOCUMENTED,
            **updates,
        )


def test_provider_pull_capabilities_serialize_independent_operations() -> None:
    capabilities = ProviderPullCapabilities(
        list_supported=True,
        native_get_supported=True,
        board_scan_get_supported=True,
        exact_unlisted_get_supported=True,
        enumerate_unlisted_supported=False,
        interface_stability=InterfaceStability.DOCUMENTED,
    )

    assert capabilities.model_dump(mode="json") == {
        "detect_supported": True,
        "list_supported": True,
        "native_get_supported": True,
        "board_scan_get_supported": True,
        "exact_unlisted_get_supported": True,
        "enumerate_unlisted_supported": False,
        "interface_stability": "documented",
    }


def test_authoritative_membership_requires_complete_reconciled_evidence() -> None:
    with pytest.raises(ValidationError, match="authoritative"):
        MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=False,
            terminal_page_seen=False,
            pages_fetched=1,
            observed_count=1,
        )

    with pytest.raises(ValidationError, match="advertised"):
        MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=1,
            advertised_count=2,
        )


def test_list_result_separates_membership_authority_from_detail_coverage() -> None:
    result = ProviderListResult(
        provider_id="greenhouse",
        board_identity="acme",
        postings=(_posting_without_detail(),),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=1,
            advertised_count=1,
        ),
        detail_coverage=DetailCoverageEvidence(
            required=False,
            requested_count=1,
            completed_count=0,
            failed_count=1,
        ),
    )

    assert result.membership.authoritative is True
    assert result.detail_coverage.complete is False
    assert result.ready_for_apply is True
    assert result.to_job_fetch_result() == JobFetchResult(
        jobs=[result.postings[0].job],
        authoritative=True,
    )


def test_required_detail_failure_prevents_list_application() -> None:
    result = ProviderListResult(
        provider_id="greenhouse",
        board_identity="acme",
        postings=(_posting_without_detail(),),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=1,
        ),
        detail_coverage=DetailCoverageEvidence(
            required=True,
            requested_count=1,
            completed_count=0,
            failed_count=1,
        ),
    )

    assert result.ready_for_apply is False


def test_required_detail_coverage_cannot_understate_full_board_membership() -> None:
    postings = (
        _posting("0"),
        *tuple(_posting_without_detail(str(index)) for index in range(1, 100)),
    )

    with pytest.raises(ValidationError, match="every returned posting"):
        ProviderListResult(
            provider_id="greenhouse",
            board_identity="acme",
            postings=postings,
            membership=_membership(100),
            detail_coverage=DetailCoverageEvidence(
                required=True,
                requested_count=1,
                completed_count=1,
            ),
        )


def test_provider_posting_requires_stable_listing_and_detail_roles() -> None:
    job = _job(listing={"id": "123"}, detail={"content": "details"})

    with pytest.raises(ValidationError, match="listing evidence"):
        ProviderPosting(
            job=job,
            listing={"id": "different"},
            detail=job.raw_detail,
        )

    with pytest.raises(ValidationError, match="detail evidence"):
        ProviderPosting(
            job=job,
            listing=job.raw_listing,
            detail={"content": "different"},
        )

    with pytest.raises(ValidationError, match="listing evidence is missing"):
        ProviderPosting(job=job, listing=None, detail=job.raw_detail)

    with pytest.raises(ValidationError, match="detail evidence is missing"):
        ProviderPosting(job=job, listing=job.raw_listing, detail=None)


def test_list_result_rejects_scope_detail_and_board_contradictions() -> None:
    with pytest.raises(ValidationError, match="unlisted"):
        _source_list(_posting_without_detail(posting_kind="unlisted"))

    with pytest.raises(ValidationError, match="posting identities"):
        _source_list(
            _posting_without_detail("123"),
            _posting_without_detail("123"),
        )

    with pytest.raises(ValidationError, match="mix providers"):
        _source_list(
            _posting_without_detail("123", provider_id="greenhouse"),
            _posting_without_detail("456", provider_id="lever"),
        )

    with pytest.raises(ValidationError, match="board identities"):
        _source_list(
            _posting_without_detail("123", board_key="acme"),
            _posting_without_detail("456", board_key="other"),
        )

    with pytest.raises(ValidationError, match="completed detail count"):
        ProviderListResult(
            provider_id="greenhouse",
            board_identity="acme",
            postings=(_posting_without_detail(),),
            membership=_membership(1),
            detail_coverage=DetailCoverageEvidence(
                required=True,
                requested_count=1,
                completed_count=1,
            ),
        )


def test_list_result_rechecks_unchecked_copies_and_nested_raw_mutation() -> None:
    copied = _source_list(_posting_without_detail()).model_copy(
        update={"membership": _membership(0)}
    )

    with pytest.raises(ValueError, match="observed count"):
        _ = copied.ready_for_apply

    result = _source_list(_posting_without_detail())
    result.postings[0].job.raw_listing["id"] = "mutated"

    with pytest.raises(ValueError, match="listing evidence"):
        result.to_job_fetch_result()


def test_native_get_is_never_a_board_membership_snapshot() -> None:
    result = ProviderGetResult(
        posting=_posting(),
        method=ProviderGetMethod.NATIVE,
        matched_identity="123",
    )

    assert result.membership is None

    with pytest.raises(ValidationError, match="native get"):
        ProviderGetResult(
            posting=_posting(),
            method=ProviderGetMethod.NATIVE,
            matched_identity="123",
            source_list=_source_list(_posting_without_detail()),
        )


def test_board_scan_get_requires_authoritative_membership_and_exact_match() -> None:
    source_list = _source_list(_posting_without_detail())
    result = ProviderGetResult.from_board_scan(
        source_list,
        provider_id="greenhouse",
        board_identity="acme",
        posting_identity="123",
    )

    assert result.posting.job.remote_id == result.matched_identity
    assert result.source_list == source_list
    assert result.membership == source_list.membership

    with pytest.raises(ValueError, match="authoritative membership"):
        ProviderGetResult.from_board_scan(
            _source_list(_posting_without_detail(), authoritative=False),
            provider_id="greenhouse",
            board_identity="acme",
            posting_identity="123",
        )

    with pytest.raises(ValueError, match="exactly one posting identity"):
        ProviderGetResult.from_board_scan(
            source_list,
            provider_id="greenhouse",
            board_identity="acme",
            posting_identity="different",
        )


@pytest.mark.parametrize(
    ("provider_id", "board_identity", "error"),
    [
        ("lever", "acme", "provider identity"),
        ("greenhouse", "other", "board identity"),
    ],
)
def test_authoritative_empty_list_retains_and_enforces_target_identity(
    provider_id: str,
    board_identity: str,
    error: str,
) -> None:
    source_list = _source_list(provider_id="greenhouse", board_identity="acme")

    assert source_list.provider_id == "greenhouse"
    assert source_list.board_identity == "acme"
    assert source_list.postings == ()
    assert source_list.ready_for_apply is True

    with pytest.raises(ValueError, match=error):
        source_list.exact_match(
            provider_id=provider_id,
            board_identity=board_identity,
            posting_identity="123",
        )
    with pytest.raises(ValueError, match=error):
        ProviderGetResult.from_board_scan(
            source_list,
            provider_id=provider_id,
            board_identity=board_identity,
            posting_identity="123",
        )


@pytest.mark.parametrize(
    ("source_list", "provider_id", "board_identity", "error"),
    [
        (_source_list(), "greenhouse", "acme", "exactly one posting identity"),
        (
            _source_list(
                _posting_without_detail(provider_id="lever"),
                provider_id="lever",
            ),
            "greenhouse",
            "acme",
            "provider identity",
        ),
        (
            _source_list(
                _posting_without_detail(board_key="other"),
                board_identity="other",
            ),
            "greenhouse",
            "acme",
            "board identity",
        ),
    ],
)
def test_board_scan_get_rejects_unrelated_authoritative_lists(
    source_list: ProviderListResult,
    provider_id: str,
    board_identity: str,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        ProviderGetResult.from_board_scan(
            source_list,
            provider_id=provider_id,
            board_identity=board_identity,
            posting_identity="123",
        )


def test_get_result_rechecks_unchecked_identity_copy() -> None:
    result = ProviderGetResult(
        posting=_posting(),
        method=ProviderGetMethod.NATIVE,
        matched_identity="123",
    ).model_copy(update={"matched_identity": "different"})

    with pytest.raises(ValueError, match="exact posting identity"):
        result.assert_valid()


def test_existing_job_fetch_result_sequence_contract_is_unchanged() -> None:
    job = _job()
    result = JobFetchResult(jobs=[job], authoritative=True)

    assert len(result) == 1
    assert result[0] is job
    assert list(result) == [job]
    assert result.authoritative is True


def test_board_target_for_board_scan_is_identity() -> None:
    target = ProviderUrlTarget(
        provider_id="greenhouse",
        target_kind=ProviderTargetKind.BOARD,
        url="https://boards.greenhouse.io/acme",
        board_identity="acme",
    )

    assert target.for_board_scan() is target


def test_pull_capabilities_require_detection_for_executable_operations() -> None:
    with pytest.raises(ValidationError, match="target detection"):
        ProviderPullCapabilities(
            detect_supported=False,
            list_supported=True,
            interface_stability=InterfaceStability.DOCUMENTED,
        )


def test_detail_coverage_rejects_outcomes_beyond_requested_count() -> None:
    with pytest.raises(ValidationError, match="cannot exceed requested"):
        DetailCoverageEvidence(
            requested_count=1,
            completed_count=1,
            failed_count=1,
        )


def test_list_result_projection_fails_closed_for_unready_or_unlisted() -> None:
    unready = ProviderListResult(
        provider_id="greenhouse",
        board_identity="acme",
        postings=(_posting_without_detail(),),
        membership=_membership(1, authoritative=False),
    )
    with pytest.raises(ValueError, match="authoritative complete result"):
        unready.to_job_fetch_result()
    with pytest.raises(ValueError, match="authoritative membership"):
        unready.exact_match(
            provider_id="greenhouse",
            board_identity="acme",
            posting_identity="123",
        )

    unlisted = ProviderListResult(
        provider_id="greenhouse",
        board_identity="acme",
        postings=(_posting_without_detail(posting_kind="unlisted"),),
        membership=_membership(1, scope=MembershipScope.ALL_PUBLIC),
    )
    with pytest.raises(ValueError, match="listed membership"):
        unlisted.to_job_fetch_result()


def test_board_scan_get_requires_authoritative_source_list() -> None:
    with pytest.raises(ValidationError, match="authoritative source list"):
        ProviderGetResult(
            posting=_posting(),
            method=ProviderGetMethod.BOARD_SCAN,
            matched_identity="123",
        )


def test_detail_fanout_budget_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        ensure_detail_fanout_within_budget(-1, maximum_details=2)
    with pytest.raises(ValueError, match="positive integer"):
        ensure_detail_fanout_within_budget(1, maximum_details=0)
    ensure_detail_fanout_within_budget(2, maximum_details=2)


@pytest.mark.asyncio
async def test_bounded_async_map_empty_and_invalid_concurrency() -> None:
    async def worker(value: int) -> int:
        return value

    assert await bounded_async_map((), worker, max_concurrency=2) == []
    with pytest.raises(ValueError, match="positive integer"):
        await bounded_async_map((1,), worker, max_concurrency=0)


@pytest.mark.asyncio
async def test_bounded_async_map_cancels_siblings_on_worker_failure() -> None:
    started = asyncio.Event()

    async def worker(value: int) -> int:
        if value == 0:
            started.set()
            raise RuntimeError("boom")
        await started.wait()
        await asyncio.sleep(0)
        return value

    with pytest.raises(RuntimeError, match="boom"):
        await bounded_async_map((0, 1), worker, max_concurrency=2)


def test_url_identity_decoder_rejects_control_and_overlong_values() -> None:
    assert decode_url_identity_segment("") is None
    assert decode_url_identity_segment("a" * 501) is None
    assert decode_url_identity_segment("job\x00id") is None
    assert decode_url_identity_segment("job id") is None
    assert decode_url_identity_segment("%C3%28") is None
