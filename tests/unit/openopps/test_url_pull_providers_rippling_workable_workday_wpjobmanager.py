from __future__ import annotations

import httpx
import pytest

from openopps.http import HttpResponseData
from openopps.models import WorkdayJobDetail, WorkdayJobPosting
from openopps.providers.boards import rippling as rippling_module
from openopps.providers.boards import workable as workable_module
from openopps.providers.boards import workday as workday_module
from openopps.providers.boards import wpjobmanager as wpjobmanager_module
from openopps.providers.boards.rippling import (
    RipplingListingSnapshot,
    RipplingProvider,
)
from openopps.providers.boards.workable import (
    WorkableListingSnapshot,
    WorkableProvider,
)
from openopps.providers.boards.workday import (
    WorkdayListingSnapshot,
    WorkdayProvider,
    WorkdayRoute,
)
from openopps.providers.boards.wpjobmanager import (
    WPJobManagerListingSnapshot,
    WPJobManagerProvider,
)
from openopps.providers.pull import (
    MembershipScope,
    ProviderGetMethod,
    ProviderTargetKind,
)
from openopps.settings import OpenOppsSettings


@pytest.mark.parametrize(
    ("url", "kind", "board", "posting"),
    [
        (
            "https://ats.rippling.com/acme/jobs",
            ProviderTargetKind.BOARD,
            "acme",
            None,
        ),
        (
            "https://ats.rippling.com/api/v2/board/acme/jobs/job.1",
            ProviderTargetKind.POSTING,
            "acme",
            "job.1",
        ),
    ],
)
def test_rippling_typed_targets(
    url: str,
    kind: ProviderTargetKind,
    board: str,
    posting: str | None,
) -> None:
    target = RipplingProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.board_identity == board
    assert target.posting_identity == posting


@pytest.mark.parametrize(
    "url",
    [
        "https://ats.rippling.com/acme/jobs/job/extra",
        "https://ats.rippling.com/api/v2/board/acme/jobs/job/extra",
        "https://ats.rippling.com/acme%3Fadmin/jobs",
        "https://ats.rippling.com/acme%20jobs/jobs",
        "https://ats.rippling.com/acme%5Cother/jobs",
        "https://ats.rippling.com/acme%/jobs",
        "https://ats.rippling.com/acme/jobs/job%252Fextra",
        "https://example.com/acme/jobs",
    ],
)
def test_rippling_typed_targets_reject_ambiguous_paths(url: str) -> None:
    assert RipplingProvider.parse_url_target(url) is None


@pytest.mark.asyncio
async def test_rippling_pull_list_requires_complete_detail_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RipplingProvider(OpenOppsSettings())
    target = provider.parse_url_target("https://ats.rippling.com/acme/jobs")
    assert target is not None
    listing = {
        "id": "job-1",
        "name": "Engineer",
        "url": "https://ats.rippling.com/acme/jobs/job-1",
    }
    detail = {"id": "job-1", "name": "Engineer", "description": "Build."}

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _slug: str,
    ) -> RipplingListingSnapshot:
        return RipplingListingSnapshot((listing,), 2, 1)

    async def fetch_detail(
        _client: httpx.AsyncClient,
        _slug: str,
        _job_id: str,
    ) -> dict[str, object]:
        return detail

    monkeypatch.setattr(provider, "_fetch_listing_snapshot", fetch_snapshot)
    monkeypatch.setattr(provider, "_fetch_detail", fetch_detail)
    async with httpx.AsyncClient() as client:
        result = await provider.pull_list(client, target, include_unlisted=False)

    assert result.ready_for_apply
    assert result.membership.pages_fetched == 2
    assert result.membership.advertised_count == 1
    assert result.detail_coverage.required
    assert result.detail_coverage.complete
    assert result.postings[0].listing == listing
    assert result.postings[0].detail == detail


@pytest.mark.asyncio
async def test_rippling_rejects_detail_fanout_before_scheduling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RipplingProvider(OpenOppsSettings(pull_provider_max_details=1))
    target = provider.parse_url_target("https://ats.rippling.com/acme/jobs")
    assert target is not None

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _slug: str,
    ) -> RipplingListingSnapshot:
        return RipplingListingSnapshot(
            (
                {"id": "job-1", "name": "One"},
                {"id": "job-2", "name": "Two"},
            ),
            1,
            2,
        )

    async def fetch_detail(*_args: object) -> dict[str, object]:
        raise AssertionError("detail work must not be scheduled")

    monkeypatch.setattr(provider, "_fetch_listing_snapshot", fetch_snapshot)
    monkeypatch.setattr(provider, "_fetch_detail", fetch_detail)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="detail fan-out limit"):
            await provider.pull_list(client, target, include_unlisted=False)


@pytest.mark.asyncio
async def test_rippling_native_get_rejects_mismatched_detail_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RipplingProvider(OpenOppsSettings())
    target = provider.parse_url_target("https://ats.rippling.com/acme/jobs/requested")
    assert target is not None

    async def fetch_detail(
        _client: httpx.AsyncClient,
        _slug: str,
        _job_id: str,
    ) -> dict[str, object]:
        return {"id": "different", "name": "Engineer"}

    monkeypatch.setattr(provider, "_fetch_detail", fetch_detail)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="identity"):
            await provider.pull_get(client, target)


@pytest.mark.asyncio
async def test_rippling_listing_traversal_enforces_page_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RipplingProvider(OpenOppsSettings())

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        *,
        params: dict[str, int],
        cache_identity: dict[str, str],
    ) -> dict[str, object]:
        assert cache_identity == {"role": "membership_page"}
        page = params["page"]
        return {"items": [{"id": f"job-{page}-{index}"} for index in range(100)]}

    monkeypatch.setattr(rippling_module, "_RIPPLING_MAX_PAGES", 1)
    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="page budget"):
            await provider._fetch_listing_snapshot(client, "acme")


@pytest.mark.parametrize(
    "advertised",
    [
        {"totalPages": 2},
        {"totalItems": 1},
    ],
)
@pytest.mark.asyncio
async def test_rippling_rejects_empty_first_page_with_advertised_continuation(
    monkeypatch: pytest.MonkeyPatch,
    advertised: dict[str, int],
) -> None:
    provider = RipplingProvider(OpenOppsSettings())

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        *,
        params: dict[str, int],
        cache_identity: dict[str, str],
    ) -> dict[str, object]:
        assert cache_identity == {"role": "membership_page"}
        assert params["page"] == 0
        return {"items": [], **advertised}

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="incomplete pagination"):
            await provider._fetch_listing_snapshot(client, "acme")


@pytest.mark.asyncio
async def test_rippling_detail_request_sets_detail_cache_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RipplingProvider(OpenOppsSettings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        return {"id": "job-1"}

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        await provider._fetch_detail(client, "acme", "job-1")

    assert roles == [{"role": "detail"}]


@pytest.mark.parametrize(
    ("url", "kind", "board", "posting"),
    [
        (
            "https://apply.workable.com/acme",
            ProviderTargetKind.BOARD,
            "acme",
            None,
        ),
        (
            "https://apply.workable.com/acme/j/ABC.1/apply",
            ProviderTargetKind.POSTING,
            "acme",
            "ABC.1",
        ),
        (
            "https://apply.workable.com/api/v3/accounts/acme/jobs",
            ProviderTargetKind.BOARD,
            "acme",
            None,
        ),
        (
            "https://www.workable.com/api/v2/accounts/acme/jobs/ABC.1",
            ProviderTargetKind.POSTING,
            "acme",
            "ABC.1",
        ),
    ],
)
def test_workable_typed_targets(
    url: str,
    kind: ProviderTargetKind,
    board: str,
    posting: str | None,
) -> None:
    target = WorkableProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.board_identity == board
    assert target.posting_identity == posting


@pytest.mark.parametrize(
    "url",
    [
        "https://apply.workable.com/acme%3Fadmin",
        "https://apply.workable.com/acme%20jobs",
        "https://apply.workable.com/acme/j/ABC%5C1",
        "https://apply.workable.com/acme%",
        "https://apply.workable.com/acme/j/job%253Fadmin",
    ],
)
def test_workable_typed_targets_reject_unsafe_decoded_identities(url: str) -> None:
    assert WorkableProvider.parse_url_target(url) is None


@pytest.mark.asyncio
async def test_workable_pull_list_keeps_membership_authoritative_when_optional_details_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkableProvider(OpenOppsSettings())
    target = provider.parse_url_target("https://apply.workable.com/acme")
    assert target is not None
    listings = (
        {"shortcode": "ONE", "title": "One"},
        {"shortcode": "TWO", "title": "Two"},
    )

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _token: str,
    ) -> WorkableListingSnapshot:
        return WorkableListingSnapshot(listings, total=2, page_count=2)

    async def fetch_details(
        _client: httpx.AsyncClient,
        _token: str,
    ) -> dict[str, dict[str, object]]:
        return {"ONE": {"shortcode": "ONE", "description": "Details"}}

    monkeypatch.setattr(
        provider._public_client, "fetch_listing_snapshot", fetch_snapshot
    )
    monkeypatch.setattr(
        provider._public_client, "fetch_details_by_shortcode", fetch_details
    )
    async with httpx.AsyncClient() as client:
        result = await provider.pull_list(client, target, include_unlisted=False)

    assert result.ready_for_apply
    assert result.membership.scope == MembershipScope.LISTED
    assert result.membership.pages_fetched == 2
    assert result.detail_coverage.required is False
    assert result.detail_coverage.completed_count == 1
    assert result.detail_coverage.failed_count == 1
    assert (
        result.exact_match(
            provider_id="workable",
            board_identity="acme",
            posting_identity="TWO",
        ).job.title
        == "Two"
    )


@pytest.mark.asyncio
async def test_workable_requests_preserve_route_identity_and_add_bounded_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkableProvider(OpenOppsSettings())
    identities: list[object] = []

    async def no_rate_limit_wait() -> None:
        return None

    async def request_json(
        _client: httpx.AsyncClient,
        method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        identities.append(kwargs.get("cache_identity"))
        if method == "GET":
            return {"jobs": []}
        return {"total": 0, "results": []}

    monkeypatch.setattr(
        workable_module, "wait_for_workable_rate_limit", no_rate_limit_wait
    )
    monkeypatch.setattr(provider._public_client, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        await provider._public_client.fetch_listing_snapshot(client, "acme")
        await provider._public_client.fetch_details_by_shortcode(client, "acme")

    assert identities == [
        {
            "provider": "workable",
            "route": "acme",
            "role": "membership_page",
        },
        {"provider": "workable", "route": "acme", "role": "detail"},
    ]


@pytest.mark.parametrize(
    ("url", "kind", "posting"),
    [
        (
            "https://acme.wd1.myworkdayjobs.com/en-US/External",
            ProviderTargetKind.BOARD,
            None,
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/en-US/External/job/NY/Engineer_JR-1",
            ProviderTargetKind.POSTING,
            "NY/Engineer_JR-1",
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/jobs",
            ProviderTargetKind.BOARD,
            None,
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/job/NY/Engineer_JR-1",
            ProviderTargetKind.POSTING,
            "NY/Engineer_JR-1",
        ),
    ],
)
def test_workday_typed_targets(
    url: str,
    kind: ProviderTargetKind,
    posting: str | None,
) -> None:
    target = WorkdayProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.posting_identity == posting
    assert target.board_identity == ("acme.wd1.myworkdayjobs.com:acme:External")


def test_workday_cxs_target_rejects_tenant_host_mismatch() -> None:
    assert (
        WorkdayProvider.parse_url_target(
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/other/External/jobs"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.wd1.myworkdayjobs.com/en-US/External%3Fadmin",
        "https://acme.wd1.myworkdayjobs.com/en-US/External%20Jobs",
        "https://acme.wd1.myworkdayjobs.com/en-US/External/job/NY/Engineer%5CJR-1",
        "https://acme.wd1.myworkdayjobs.com/en-US/External%",
        "https://acme.wd1.myworkdayjobs.com/en-US/External/job/NY%252FEngineer",
    ],
)
def test_workday_typed_targets_reject_unsafe_decoded_identities(url: str) -> None:
    assert WorkdayProvider.parse_url_target(url) is None


@pytest.mark.asyncio
async def test_workday_native_get_preserves_slash_identity_without_listing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkdayProvider(OpenOppsSettings())
    target = provider.parse_url_target(
        "https://acme.wd1.myworkdayjobs.com/en-US/External/job/NY/Engineer_JR-1"
    )
    assert target is not None
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        return {"title": "Engineer", "jobDescription": "<p>Build.</p>"}

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        result = await provider.pull_get(client, target)

    assert result.method == ProviderGetMethod.NATIVE
    assert result.matched_identity == "NY/Engineer_JR-1"
    assert result.posting.job.remote_id == "NY/Engineer_JR-1"
    assert result.posting.listing is None
    assert result.posting.detail == {
        "title": "Engineer",
        "jobDescription": "<p>Build.</p>",
    }
    assert roles == [{"role": "detail"}]


@pytest.mark.asyncio
async def test_workday_pull_list_requires_details_for_every_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkdayProvider(OpenOppsSettings())
    target = provider.parse_url_target(
        "https://acme.wd1.myworkdayjobs.com/en-US/External"
    )
    assert target is not None
    listing = WorkdayJobPosting(
        id="JR-1",
        externalPath="NY/Engineer_JR-1",
        title="Engineer",
    )

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _route: object,
    ) -> WorkdayListingSnapshot:
        return WorkdayListingSnapshot((listing,), 1, 1)

    async def fetch_detail(
        _client: httpx.AsyncClient,
        _route: object,
        _external_path: str,
    ) -> WorkdayJobDetail:
        return WorkdayJobDetail(title="Engineer", jobDescription="Build")

    monkeypatch.setattr(provider, "_fetch_listing_snapshot", fetch_snapshot)
    monkeypatch.setattr(provider, "_fetch_detail", fetch_detail)
    async with httpx.AsyncClient() as client:
        result = await provider.pull_list(client, target, include_unlisted=False)
        posting_target = provider.parse_url_target(
            "https://acme.wd1.myworkdayjobs.com/en-US/External/job/NY/Engineer_JR-1"
        )
        assert posting_target is not None
        get_result = await provider.pull_get(client, posting_target)

    assert result.ready_for_apply
    assert result.detail_coverage.required
    assert result.detail_coverage.completed_count == 1
    assert result.postings[0].job.remote_id == "NY/Engineer_JR-1"
    assert result.postings[0].job.remote_id == get_result.posting.job.remote_id
    assert result.postings[0].job.id == get_result.posting.job.id


@pytest.mark.asyncio
async def test_workday_rejects_detail_fanout_before_scheduling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkdayProvider(OpenOppsSettings(pull_provider_max_details=1))
    target = provider.parse_url_target(
        "https://acme.wd1.myworkdayjobs.com/en-US/External"
    )
    assert target is not None
    listings = tuple(
        WorkdayJobPosting(
            id=f"JR-{index}",
            externalPath=f"NY/Engineer_JR-{index}",
            title="Engineer",
        )
        for index in (1, 2)
    )

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _route: object,
    ) -> WorkdayListingSnapshot:
        return WorkdayListingSnapshot(listings, 1, 2)

    async def fetch_detail(*_args: object) -> WorkdayJobDetail:
        raise AssertionError("detail work must not be scheduled")

    monkeypatch.setattr(provider, "_fetch_listing_snapshot", fetch_snapshot)
    monkeypatch.setattr(provider, "_fetch_detail", fetch_detail)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="detail fan-out limit"):
            await provider.pull_list(client, target, include_unlisted=False)


@pytest.mark.asyncio
async def test_workday_listing_traversal_enforces_page_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WorkdayProvider(OpenOppsSettings())
    route = WorkdayRoute(
        host="acme.wd1.myworkdayjobs.com",
        tenant="acme",
        site="External",
    )

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        assert _kwargs.get("cache_identity") == {"role": "membership_page"}
        return {
            "jobPostings": [
                {
                    "id": f"job-{index}",
                    "externalPath": f"jobs/job-{index}",
                }
                for index in range(20)
            ]
        }

    monkeypatch.setattr(workday_module, "_WORKDAY_MAX_PAGES", 1)
    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="page budget"):
            await provider._fetch_listing_snapshot(client, route)


@pytest.mark.parametrize(
    ("url", "kind", "posting"),
    [
        (
            "https://jobs.example.com/wp-json/wp/v2/job-listings",
            ProviderTargetKind.BOARD,
            None,
        ),
        (
            "https://jobs.example.com/wp-json/wp/v2/job-listings/123",
            ProviderTargetKind.POSTING,
            "123",
        ),
        (
            "https://jobs.example.com/jm-ajax/get_listings",
            ProviderTargetKind.BOARD,
            None,
        ),
    ],
)
def test_wpjobmanager_typed_targets(
    url: str,
    kind: ProviderTargetKind,
    posting: str | None,
) -> None:
    target = WPJobManagerProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.posting_identity == posting


def test_wpjobmanager_rejects_nonnumeric_rest_item_target() -> None:
    assert (
        WPJobManagerProvider.parse_url_target(
            "https://jobs.example.com/wp-json/wp/v2/job-listings/not-numeric"
        )
        is None
    )


def test_wpjobmanager_does_not_advertise_unreachable_board_scan_get() -> None:
    assert not WPJobManagerProvider.pull_capabilities.board_scan_get_supported


@pytest.mark.asyncio
async def test_wpjobmanager_pull_list_exposes_authoritative_scan_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    target = provider.parse_url_target(
        "https://jobs.example.com/wp-json/wp/v2/job-listings"
    )
    assert target is not None
    listing = {
        "id": 7,
        "title": {"rendered": "Engineer"},
        "content": {"rendered": "Build."},
        "link": "https://jobs.example.com/jobs/engineer",
    }

    async def fetch_snapshot(
        _client: httpx.AsyncClient,
        _endpoint: str,
    ) -> WPJobManagerListingSnapshot:
        return WPJobManagerListingSnapshot((listing,), 1, 1, False)

    monkeypatch.setattr(provider, "_fetch_listing_snapshot", fetch_snapshot)
    async with httpx.AsyncClient() as client:
        result = await provider.pull_list(client, target, include_unlisted=False)

    assert result.ready_for_apply
    assert (
        result.exact_match(
            provider_id="wpjobmanager",
            board_identity="https://jobs.example.com/wp-json/wp/v2/job-listings",
            posting_identity="7",
        ).listing
        == listing
    )


@pytest.mark.asyncio
async def test_wpjobmanager_native_get_uses_detail_evidence_and_exact_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    target = provider.parse_url_target(
        "https://jobs.example.com/wp-json/wp/v2/job-listings/7"
    )
    assert target is not None
    detail = {
        "id": 7,
        "title": {"rendered": "Engineer"},
        "content": {"rendered": "Build."},
        "link": "https://jobs.example.com/jobs/engineer",
    }

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        *,
        cache_identity: dict[str, str],
    ) -> dict[str, object]:
        assert cache_identity == {"role": "detail"}
        return detail

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        result = await provider.pull_get(client, target)

    assert result.method == ProviderGetMethod.NATIVE
    assert result.posting.listing is None
    assert result.posting.detail == detail
    assert result.posting.job.remote_id == "7"


@pytest.mark.asyncio
async def test_wpjobmanager_rest_rejects_inconsistent_total_page_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    endpoint = "https://jobs.example.com/wp-json/wp/v2/job-listings"

    async def request_json_response(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **_kwargs: object,
    ) -> HttpResponseData:
        assert _kwargs.get("cache_identity") == {"role": "membership_page"}
        return HttpResponseData(
            body=[{"id": index} for index in range(50)],
            headers={"x-wp-total": "50", "x-wp-totalpages": "2"},
            status_code=200,
        )

    monkeypatch.setattr(provider, "_request_json_response", request_json_response)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="page count"):
            await provider._fetch_listing_snapshot(client, endpoint)


@pytest.mark.asyncio
async def test_wpjobmanager_rest_traversal_enforces_page_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    endpoint = "https://jobs.example.com/wp-json/wp/v2/job-listings"

    async def request_json_response(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **_kwargs: object,
    ) -> HttpResponseData:
        assert _kwargs.get("cache_identity") == {"role": "membership_page"}
        return HttpResponseData(
            body=[{"id": index} for index in range(100)],
            headers={},
            status_code=200,
        )

    monkeypatch.setattr(wpjobmanager_module, "_WPJOBMANAGER_MAX_PAGES", 1)
    monkeypatch.setattr(provider, "_request_json_response", request_json_response)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="page budget"):
            await provider._fetch_listing_snapshot(client, endpoint)


def _wpjobmanager_ajax_html(*, page: int, count: int) -> str:
    listings = "".join(
        (
            '<li class="job_listing">'
            f'<a href="https://jobs.example.com/jobs/{page}-{index}">'
            f"Job {page}-{index}</a></li>"
        )
        for index in range(count)
    )
    return f"<ul>{listings}</ul>"


@pytest.mark.asyncio
async def test_wpjobmanager_ajax_full_page_without_metadata_reaches_terminal_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    endpoint = "https://jobs.example.com/jm-ajax/get_listings"
    requested_pages: list[int] = []
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        *,
        params: dict[str, int],
        cache_identity: dict[str, str],
    ) -> dict[str, object]:
        roles.append(cache_identity)
        page = params["page"]
        requested_pages.append(page)
        return {
            "html": _wpjobmanager_ajax_html(page=page, count=100 if page == 1 else 0)
        }

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        snapshot = await provider._fetch_ajax_listing_snapshot(client, endpoint)

    assert requested_pages == [1, 2]
    assert roles == [{"role": "membership_page"}] * 2
    assert snapshot.pages_fetched == 2
    assert len(snapshot.listings) == 100


@pytest.mark.asyncio
async def test_wpjobmanager_ajax_rejects_page_larger_than_requested_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    endpoint = "https://jobs.example.com/jm-ajax/get_listings"

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        return {"html": _wpjobmanager_ajax_html(page=1, count=101)}

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="per_page"):
            await provider._fetch_ajax_listing_snapshot(client, endpoint)


@pytest.mark.parametrize(
    "metadata",
    [
        {"max_num_pages": "many"},
        {"total": "many"},
    ],
)
@pytest.mark.asyncio
async def test_wpjobmanager_ajax_rejects_present_malformed_pagination_metadata(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, object],
) -> None:
    provider = WPJobManagerProvider(OpenOppsSettings())
    endpoint = "https://jobs.example.com/jm-ajax/get_listings"

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        return {"html": "", **metadata}

    monkeypatch.setattr(provider, "_request_json", request_json)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="must be an integer"):
            await provider._fetch_ajax_listing_snapshot(client, endpoint)


@pytest.mark.parametrize(
    ("provider_cls", "url"),
    [
        (RipplingProvider, "https://ats.rippling.com/acme/jobs"),
        (WorkableProvider, "https://apply.workable.com/acme"),
        (
            WorkdayProvider,
            "https://acme.wd1.myworkdayjobs.com/en-US/External",
        ),
        (
            WPJobManagerProvider,
            "https://jobs.example.com/wp-json/wp/v2/job-listings",
        ),
    ],
)
@pytest.mark.asyncio
async def test_provider_list_hooks_reject_unlisted_enumeration(
    provider_cls: type,
    url: str,
) -> None:
    provider = provider_cls(OpenOppsSettings())
    target = provider.parse_url_target(url)
    assert target is not None

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unlisted"):
            await provider.pull_list(client, target, include_unlisted=True)
