from __future__ import annotations

import json
from typing import cast

import httpx
import pytest
import respx

import openopps.providers.boards.consider as consider_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.boards.ashby import AshbyProvider
from openopps.providers.boards.bamboohr import BambooHRProvider
from openopps.providers.boards.consider import ConsiderJobsProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings


def _target(value: ProviderUrlTarget | None) -> ProviderUrlTarget:
    assert value is not None
    return value


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        board_concurrency=2,
    )


def _ashby_payload() -> dict[str, object]:
    return {
        "apiVersion": "1",
        "jobs": [
            {
                "id": "listed",
                "title": "Listed Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/listed",
                "isListed": True,
                "extra": {"source": "listing"},
            },
            {
                "title": "Direct-link Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/hidden",
                "isListed": False,
                "extra": {"source": "unlisted"},
            },
            {
                "id": "unspecified",
                "title": "Unspecified Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/unspecified",
            },
        ],
    }


def _bamboo_listing(job_id: int, title: str) -> dict[str, object]:
    return {
        "id": job_id,
        "jobOpeningName": title,
        "departmentLabel": "Engineering",
        "listingExtra": {"id": job_id},
    }


def _bamboo_detail(job_id: int, title: str) -> dict[str, object]:
    return {
        "result": {
            "jobOpening": {
                "id": job_id,
                "jobOpeningName": title,
                "description": f"<p>Build system {job_id}.</p>",
                "jobOpeningShareUrl": (f"https://acme.bamboohr.com/careers/{job_id}"),
                "detailExtra": {"id": job_id},
            }
        }
    }


def _consider_job(job_id: str) -> dict[str, object]:
    return {
        "jobId": job_id,
        "title": f"Engineer {job_id}",
        "companyName": "Acme",
        "companySlug": "acme",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/{job_id}",
        "applyUrl": f"https://apply.example.com/{job_id}",
        "timeStamp": "2026-08-30T00:00:00Z",
        "extra": {"id": job_id},
    }


def _consider_response(
    jobs: list[dict[str, object]],
    *,
    sequence: str | None = None,
    total: int = 999,
) -> dict[str, object]:
    meta: dict[str, object] = {"size": 100}
    if sequence is not None:
        meta["sequence"] = sequence
    return {
        "jobs": jobs,
        "total": total,
        "meta": meta,
        "errors": [],
    }


def test_ashby_parses_strict_board_api_posting_and_application_targets() -> None:
    board = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/Pear-VC/"))
    embed = _target(
        AshbyProvider.parse_url_target(
            "https://jobs.ashbyhq.com/Pear-VC/embed?version=2"
        )
    )
    api = _target(
        AshbyProvider.parse_url_target(
            "https://api.ashbyhq.com/posting-api/job-board/Pear-VC"
            "?includeCompensation=true"
        )
    )
    posting = _target(
        AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/Pear-VC/job.123")
    )
    application = _target(
        AshbyProvider.parse_url_target(
            "https://jobs.ashbyhq.com/Pear-VC/job.123/application"
        )
    )

    assert board.target_kind == ProviderTargetKind.BOARD
    assert board.board_identity == "Pear-VC"
    assert board.route.token == "Pear-VC"
    assert embed.target_kind == ProviderTargetKind.BOARD
    assert embed.board_identity == "Pear-VC"
    assert embed.url == "https://jobs.ashbyhq.com/Pear-VC"
    assert api.target_kind == ProviderTargetKind.BOARD
    assert api.url == "https://api.ashbyhq.com/posting-api/job-board/Pear-VC"
    assert posting.target_kind == ProviderTargetKind.POSTING
    assert posting.posting_identity == "job.123"
    assert application.posting_identity == "job.123"
    assert AshbyProvider.build_probe_urls("Pear-VC") == (
        "https://jobs.ashbyhq.com/Pear-VC",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.ashbyhq.com/acme",
        "https://jobs.ashbyhq.com/",
        "https://jobs.ashbyhq.com/acme/job/extra",
        "https://jobs.ashbyhq.com/acme/job?source=test",
        "https://jobs.ashbyhq.com/acme/embed?version=3",
        "https://jobs.ashbyhq.com/acme/embed?version=2&source=test",
        "https://jobs.ashbyhq.com/acme/bad%2Fidentity",
        "https://jobs.ashbyhq.com/acme/bad%ZZidentity",
        "https://api.ashbyhq.com/posting-api/job-board/acme/jobs/1",
        "https://api.ashbyhq.com/posting-api/job-board/acme?other=true",
    ],
)
def test_ashby_rejects_ambiguous_or_unsupported_url_shapes(url: str) -> None:
    assert AshbyProvider.parse_url_target(url) is None


def test_ashby_capabilities_are_operation_specific() -> None:
    capabilities = AshbyProvider.pull_capabilities

    assert capabilities.interface_stability == InterfaceStability.DOCUMENTED
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is True
    assert capabilities.exact_unlisted_get_supported is True


@pytest.mark.asyncio
@respx.mock
async def test_ashby_pull_list_separates_listed_and_all_public_membership() -> None:
    endpoint = respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/acme",
        params={"includeCompensation": "true"},
    ).mock(
        side_effect=[
            httpx.Response(200, json=_ashby_payload()),
            httpx.Response(200, json=_ashby_payload()),
        ]
    )
    target = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/acme"))

    async with build_async_client(_settings()) as client:
        provider = AshbyProvider(_settings())
        listed = await provider.pull_list(client, target, include_unlisted=False)
        all_public = await provider.pull_list(client, target, include_unlisted=True)

    assert endpoint.call_count == 2
    assert listed.provider_id == "ashbyhq"
    assert listed.board_identity == "acme"
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert [posting.job.remote_id for posting in listed.postings] == [
        "listed",
        "unspecified",
    ]
    assert all_public.membership.scope == MembershipScope.ALL_PUBLIC
    assert [posting.job.remote_id for posting in all_public.postings] == [
        "listed",
        "hidden",
        "unspecified",
    ]
    hidden = all_public.exact_match(
        provider_id="ashbyhq",
        board_identity="acme",
        posting_identity="hidden",
    )
    assert hidden.job.posting_kind == "unlisted"
    assert hidden.job.remote_id == "hidden"
    assert hidden.listing == hidden.job.raw_listing
    assert hidden.listing == cast(list[dict[str, object]], _ashby_payload()["jobs"])[1]
    assert hidden.detail is None
    exact = ProviderGetResult.from_board_scan(
        all_public,
        provider_id="ashbyhq",
        board_identity="acme",
        posting_identity="hidden",
    )
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.membership == all_public.membership


@pytest.mark.asyncio
@respx.mock
async def test_ashby_pull_list_rejects_duplicate_native_identities() -> None:
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {"id": "same", "title": "One"},
                    {"id": "same", "title": "Two"},
                ]
            },
        )
    )
    target = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/acme"))

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="identities must be unique"):
            await AshbyProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_ashby_empty_list_is_authoritative_terminal_evidence() -> None:
    respx.get("https://api.ashbyhq.com/posting-api/job-board/empty").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    target = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/empty"))

    async with build_async_client(_settings()) as client:
        result = await AshbyProvider(_settings()).pull_list(
            client, target, include_unlisted=False
        )

    assert result.postings == ()
    assert result.membership.observed_count == 0
    assert result.ready_for_apply is True


@pytest.mark.asyncio
async def test_ashby_pull_list_sets_membership_cache_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AshbyProvider(_settings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        return {"jobs": []}

    monkeypatch.setattr(provider, "_request_json", request_json)
    target = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/acme"))
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, target, include_unlisted=False)

    assert roles == [{"role": "membership"}]


def test_bamboohr_parses_strict_board_posting_and_detail_targets() -> None:
    board = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/")
    )
    posting = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42")
    )
    detail = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42/detail")
    )
    list_endpoint = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/list")
    )

    assert board.target_kind == ProviderTargetKind.BOARD
    assert board.board_identity == "acme"
    assert board.route.host == "acme.bamboohr.com"
    assert board.route.tenant == "acme"
    assert list_endpoint.target_kind == ProviderTargetKind.BOARD
    assert posting.target_kind == ProviderTargetKind.POSTING
    assert posting.posting_identity == "42"
    assert detail.posting_identity == "42"
    assert BambooHRProvider.build_probe_urls("Acme") == (
        "https://acme.bamboohr.com/careers",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://bamboohr.com/careers",
        "https://acme.bamboohr.com/jobs",
        "https://acme.bamboohr.com/careers/42/other",
        "https://acme.bamboohr.com/careers/42?source=test",
        "https://acme.bamboohr.com/careers/bad%2Fidentity",
        "https://acme.bamboohr.com/careers/bad%ZZidentity",
        "https://acme.bamboohr.com/careers/42/detail/extra",
        "https://acme.bamboohr.com.evil.example/careers",
    ],
)
def test_bamboohr_rejects_ambiguous_or_unsupported_url_shapes(url: str) -> None:
    assert BambooHRProvider.parse_url_target(url) is None


def test_bamboohr_capabilities_are_native_get_and_best_effort() -> None:
    capabilities = BambooHRProvider.pull_capabilities

    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.board_scan_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_pull_list_reconciles_count_and_required_details() -> None:
    listings = [_bamboo_listing(41, "Analyst"), _bamboo_listing(42, "Engineer")]
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(
            200,
            json={"meta": {"totalCount": 2}, "result": listings},
        )
    )
    respx.get("https://acme.bamboohr.com/careers/41/detail").mock(
        return_value=httpx.Response(200, json=_bamboo_detail(41, "Analyst"))
    )
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=_bamboo_detail(42, "Engineer"))
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(_settings()) as client:
        result = await BambooHRProvider(_settings()).pull_list(
            client, target, include_unlisted=False
        )

    assert result.provider_id == "bamboohr"
    assert result.board_identity == "acme"
    assert result.membership.scope == MembershipScope.LISTED
    assert result.membership.advertised_count == 2
    assert result.membership.observed_count == 2
    assert result.membership.authoritative is True
    assert result.detail_coverage.required is True
    assert result.detail_coverage.requested_count == 2
    assert result.detail_coverage.completed_count == 2
    assert result.detail_coverage.complete is True
    assert result.ready_for_apply is True
    first = result.postings[0]
    assert first.listing == listings[0]
    assert first.listing == first.job.raw_listing
    assert first.detail == _bamboo_detail(41, "Analyst")["result"]["jobOpening"]
    assert first.detail == first.job.raw_detail


@pytest.mark.asyncio
async def test_bamboohr_pull_list_sets_membership_and_detail_cache_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = BambooHRProvider(_settings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        if url.endswith("/detail"):
            return _bamboo_detail(42, "Engineer")
        return {
            "meta": {"totalCount": 1},
            "result": [_bamboo_listing(42, "Engineer")],
        }

    monkeypatch.setattr(provider, "_request_json", request_json)
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, target, include_unlisted=False)

    assert roles == [{"role": "membership"}, {"role": "detail"}]


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_rejects_detail_fanout_over_trusted_limit() -> None:
    listings = [_bamboo_listing(41, "Analyst"), _bamboo_listing(42, "Engineer")]
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(
            200,
            json={"meta": {"totalCount": 2}, "result": listings},
        )
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        board_concurrency=2,
        pull_provider_max_details=1,
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="detail fan-out limit"):
            await BambooHRProvider(settings).pull_list(
                client, target, include_unlisted=False
            )

    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_legacy_sync_is_not_capped_by_url_pull_detail_limit() -> None:
    listings = [_bamboo_listing(41, "Analyst"), _bamboo_listing(42, "Engineer")]
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json={"result": listings})
    )
    for job_id, title in ((41, "Analyst"), (42, "Engineer")):
        respx.get(f"https://acme.bamboohr.com/careers/{job_id}/detail").mock(
            return_value=httpx.Response(200, json=_bamboo_detail(job_id, title))
        )
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_max_details=1,
    )
    board = BoardRecord(
        key="acme",
        source_key="manual",
        remote_id="acme",
        name="Acme",
    )
    route = BoardProviderRecord(
        id="manual:acme:bamboohr",
        source_key="manual",
        board_key="acme",
        provider_id="bamboohr",
        support_level=ProviderSupport.JOBS,
        tenant="acme",
    )

    async with build_async_client(settings) as client:
        result = await BambooHRProvider(settings).fetch_jobs(client, board, route)

    assert [job.remote_id for job in result] == ["41", "42"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"meta": {"totalCount": 1}, "result": [{"jobOpeningName": "No id"}]},
            "missing an id",
        ),
        (
            {
                "meta": {"totalCount": 2},
                "result": [_bamboo_listing(1, "One"), _bamboo_listing(1, "Two")],
            },
            "duplicate jobs",
        ),
        (
            {"meta": {"totalCount": 2}, "result": [_bamboo_listing(1, "One")]},
            "advertised total",
        ),
    ],
)
async def test_bamboohr_pull_list_rejects_incomplete_membership(
    payload: dict[str, object], message: str
) -> None:
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json=payload)
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await BambooHRProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_pull_list_fails_when_required_detail_is_missing() -> None:
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"totalCount": 1},
                "result": [_bamboo_listing(42, "Engineer")],
            },
        )
    )
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json={"result": {}})
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="detail endpoint returned invalid"):
            await BambooHRProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_pull_list_rejects_mismatched_detail_identity() -> None:
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"totalCount": 1},
                "result": [_bamboo_listing(42, "Engineer")],
            },
        )
    )
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=_bamboo_detail(99, "Other"))
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match its listing"):
            await BambooHRProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_native_get_preserves_detail_without_board_authority() -> None:
    detail_payload = _bamboo_detail(42, "Engineer")
    job_opening = cast(
        dict[str, object],
        cast(dict[str, object], detail_payload["result"])["jobOpening"],
    )
    job_opening.pop("id")
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=detail_payload)
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42")
    )

    async with build_async_client(_settings()) as client:
        result = await BambooHRProvider(_settings()).pull_get(client, target)

    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.matched_identity == "42"
    assert result.posting.job.remote_id == "42"
    assert result.posting.listing is None
    assert result.posting.job.raw_listing == {}
    assert result.posting.detail == result.posting.job.raw_detail


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_native_get_rejects_mismatched_detail_identity() -> None:
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=_bamboo_detail(43, "Other"))
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match"):
            await BambooHRProvider(_settings()).pull_get(client, target)


@pytest.mark.asyncio
async def test_bamboohr_rejects_unlisted_enumeration_without_fetching() -> None:
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="does not support unlisted"):
            await BambooHRProvider(_settings()).pull_list(
                client, target, include_unlisted=True
            )


def test_consider_parses_strict_company_board_and_posting_targets() -> None:
    board = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/q.ai/")
    )
    posting = _target(
        ConsiderJobsProvider.parse_url_target(
            "https://consider.com/boards/co/q.ai/job-1"
        )
    )
    trailing_posting = _target(
        ConsiderJobsProvider.parse_url_target(
            "https://consider.com/boards/co/q.ai/job-1/"
        )
    )

    assert board.target_kind == ProviderTargetKind.BOARD
    assert board.board_identity == "q.ai"
    assert board.posting_identity is None
    assert board.route.token == "q.ai"
    assert posting.target_kind == ProviderTargetKind.POSTING
    assert posting.board_identity == "q.ai"
    assert posting.posting_identity == "job-1"
    assert posting.route.token == "q.ai"
    assert posting.route.host == "consider.com"
    assert trailing_posting.target_kind == ProviderTargetKind.POSTING
    assert trailing_posting.posting_identity == "job-1"
    assert ConsiderJobsProvider.build_probe_urls("q.ai") == (
        "https://consider.com/boards/co/q.ai",
    )
    for url in (
        "https://consider.com/boards/co/q.ai?preview=true",
        "https://consider.com/boards/co/q.ai/job-1?preview=true",
        "https://consider.com/boards/co/q.ai/job-1#section",
        "https://consider.com/boards/co/q.ai/job-1/extra",
        "https://consider.com/boards/vc/q.ai/companies",
        "https://jobs.example.com/boards/co/q.ai",
        "https://jobs.example.com/boards/co/q.ai/job-1",
    ):
        assert ConsiderJobsProvider.parse_url_target(url) is None


def test_consider_capabilities_advertise_board_scan_get_without_native_get() -> None:
    capabilities = ConsiderJobsProvider.pull_capabilities

    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.exact_unlisted_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False


def test_provider_target_parsers_fail_closed_on_oversized_urls() -> None:
    oversized = f"https://jobs.example.com/{'a' * 2_000}"

    assert AshbyProvider.parse_url_target(oversized) is None
    assert BambooHRProvider.parse_url_target(oversized) is None
    assert ConsiderJobsProvider.parse_url_target(oversized) is None


@pytest.mark.asyncio
@respx.mock
async def test_consider_pull_list_uses_sequence_terminal_not_advisory_total() -> None:
    endpoint = respx.post("https://consider.com/api-boards/search-jobs").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_consider_response(
                    [_consider_job("one")], sequence="next", total=500
                ),
            ),
            httpx.Response(
                200,
                json=_consider_response([_consider_job("two")], total=1),
            ),
        ]
    )
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )

    async with build_async_client(_settings()) as client:
        result = await ConsiderJobsProvider(_settings()).pull_list(
            client, target, include_unlisted=False
        )

    assert endpoint.call_count == 2
    assert result.provider_id == "consider_jobs"
    assert result.board_identity == "acme"
    assert result.membership.scope == MembershipScope.LISTED
    assert result.membership.authoritative is True
    assert result.membership.complete is True
    assert result.membership.terminal_page_seen is True
    assert result.membership.pages_fetched == 2
    assert result.membership.observed_count == 2
    assert result.membership.advertised_count is None
    assert result.detail_coverage.requested_count == 0
    assert [posting.job.remote_id for posting in result.postings] == ["one", "two"]
    assert result.postings[0].listing == _consider_job("one")
    assert result.postings[0].listing == result.postings[0].job.raw_listing
    assert result.postings[0].detail is None
    second_request = json.loads(endpoint.calls[1].request.content)
    assert second_request["meta"]["sequence"] == "next"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("responses", "message"),
    [
        (
            [
                _consider_response([_consider_job("one")], sequence="same"),
                _consider_response([_consider_job("two")], sequence="same"),
            ],
            "repeated a sequence",
        ),
        (
            [
                _consider_response([_consider_job("one")], sequence="next"),
                _consider_response([_consider_job("one")]),
            ],
            "repeated a job",
        ),
        ([_consider_response([], sequence="next")], "empty page with continuation"),
    ],
)
async def test_consider_pull_list_rejects_incomplete_sequence_evidence(
    responses: list[dict[str, object]], message: str
) -> None:
    respx.post("https://consider.com/api-boards/search-jobs").mock(
        side_effect=[httpx.Response(200, json=response) for response in responses]
    )
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await ConsiderJobsProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_consider_pull_list_enforces_bounded_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consider_module, "CONSIDER_JOBS_MAX_PAGES", 1)
    endpoint = respx.post("https://consider.com/api-boards/search-jobs").mock(
        return_value=httpx.Response(
            200,
            json=_consider_response([_consider_job("one")], sequence="next"),
        )
    )
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="exceeded the page limit"):
            await ConsiderJobsProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )

    assert endpoint.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_consider_empty_pull_requires_and_records_specific_board() -> None:
    respx.post("https://consider.com/api-boards/search-jobs").mock(
        return_value=httpx.Response(200, json=_consider_response([], total=0))
    )
    respx.get("https://consider.com/boards/co/acme").mock(
        return_value=httpx.Response(
            200,
            text='<meta property="og:title" content="Jobs at Acme | Consider">',
        )
    )
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )

    async with build_async_client(_settings()) as client:
        result = await ConsiderJobsProvider(_settings()).pull_list(
            client, target, include_unlisted=False
        )

    assert result.postings == ()
    assert result.membership.observed_count == 0
    assert result.membership.pages_fetched == 1
    assert result.membership.advertised_count is None
    assert result.ready_for_apply is True


@pytest.mark.asyncio
async def test_consider_pull_sets_page_and_terminal_cache_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ConsiderJobsProvider(_settings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        return _consider_response([], total=0)

    async def request_text(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> str:
        roles.append(kwargs.get("cache_identity"))
        return '<meta property="og:title" content="Jobs at Acme | Consider">'

    monkeypatch.setattr(provider, "_request_json", request_json)
    monkeypatch.setattr(provider, "_request_text", request_text)
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, target, include_unlisted=False)

    assert roles == [
        {"role": "membership_page"},
        {"role": "membership_terminal"},
    ]


@pytest.mark.asyncio
async def test_consider_rejects_unlisted_enumeration_without_fetching() -> None:
    target = _target(
        ConsiderJobsProvider.parse_url_target("https://consider.com/boards/co/acme")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="does not support unlisted"):
            await ConsiderJobsProvider(_settings()).pull_list(
                client, target, include_unlisted=True
            )


@pytest.mark.asyncio
@respx.mock
async def test_consider_board_scan_get_matches_exact_listed_posting() -> None:
    endpoint = respx.post("https://consider.com/api-boards/search-jobs").mock(
        return_value=httpx.Response(
            200,
            json=_consider_response(
                [_consider_job("job-1"), _consider_job("job-2")],
                total=2,
            ),
        )
    )
    posting_target = _target(
        ConsiderJobsProvider.parse_url_target(
            "https://consider.com/boards/co/acme/job-1"
        )
    )
    board_target = posting_target.for_board_scan()
    capabilities = ConsiderJobsProvider.pull_capabilities

    async with build_async_client(_settings()) as client:
        listed = await ConsiderJobsProvider(_settings()).pull_list(
            client, board_target, include_unlisted=False
        )
        with pytest.raises(ValueError, match="does not support unlisted"):
            await ConsiderJobsProvider(_settings()).pull_list(
                client, board_target, include_unlisted=True
            )

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="consider_jobs",
        board_identity="acme",
        posting_identity="job-1",
    )
    assert endpoint.call_count == 1
    assert posting_target.target_kind == ProviderTargetKind.POSTING
    assert posting_target.posting_identity == "job-1"
    assert board_target.target_kind == ProviderTargetKind.BOARD
    assert [posting.job.remote_id for posting in listed.postings] == [
        "job-1",
        "job-2",
    ]
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.job.remote_id == "job-1"
    assert exact.posting.job.board_key == "acme"
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is False


@pytest.mark.asyncio
@respx.mock
async def test_ashby_ingest_keeps_listing_id_when_job_url_tail_differs() -> None:
    payload = {
        "apiVersion": "1",
        "jobs": [
            {
                "id": "ashby-guid-1",
                "title": "Listed Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/url-tail-not-guid",
                "isListed": True,
            },
            {
                "title": "Hidden Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/hidden",
                "isListed": False,
            },
        ],
    }
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/acme",
        params={"includeCompensation": "true"},
    ).mock(return_value=httpx.Response(200, json=payload))
    catalog = BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )
    route = BoardProviderRecord(
        id="manual:acme:ashbyhq",
        source_key="manual",
        board_key="manual:acme",
        provider_id="ashbyhq",
        support_level=ProviderSupport.JOBS,
        token="acme",
    )
    target = _target(AshbyProvider.parse_url_target("https://jobs.ashbyhq.com/acme"))

    async with build_async_client(_settings()) as client:
        provider = AshbyProvider(_settings())
        synced = await provider.fetch_jobs(client, catalog, route)
        listed = await provider.pull_list(client, target, include_unlisted=False)

    assert [job.remote_id for job in synced] == ["ashby-guid-1"]
    assert synced[0].board_key == "manual:acme"
    assert synced[0].company == "Acme Corp"
    assert [posting.job.remote_id for posting in listed.postings] == ["url-tail-not-guid"]
    assert listed.postings[0].job.board_key == "acme"
