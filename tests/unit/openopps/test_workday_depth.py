from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.workday import WorkdayProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id


_HOST = "acme.wd1.myworkdayjobs.com"
_SITE = "External"
_LIST_URL = f"https://{_HOST}/wday/cxs/acme/{_SITE}/jobs"
_BOARD_URL = f"https://{_HOST}/en-US/{_SITE}"
_CATALOG_BOARD_KEY = "manual:acme"


def _settings(*, pull_provider_max_details: int = 10_000) -> OpenOppsSettings:
    return OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        workday_concurrency=2,
        pull_provider_max_details=pull_provider_max_details,
    )


def _target(url: str) -> ProviderUrlTarget:
    target = WorkdayProvider.parse_url_target(url)
    assert target is not None
    return target


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key=_CATALOG_BOARD_KEY,
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _catalog_route() -> BoardProviderRecord:
    return BoardProviderRecord(
        id="manual:acme:workday",
        source_key="manual",
        board_key=_CATALOG_BOARD_KEY,
        provider_id="workday",
        support_level=ProviderSupport.JOBS,
        host=_HOST,
        tenant="acme",
        site=_SITE,
    )


def _listing(
    index: int,
    *,
    listing_id: str | None = None,
    path: str | None = None,
    title: str | None = None,
) -> dict[str, object]:
    identity = index
    return {
        "id": listing_id if listing_id is not None else f"JR-{identity}",
        "title": title if title is not None else f"Engineer {identity}",
        "externalPath": path if path is not None else f"NY/Engineer_JR-{identity}",
        "locationsText": "New York",
        "jobFamily": "Engineering",
        "postedOn": "Posted Yesterday",
    }


def _cxs_detail(
    path: str,
    title: str,
    *,
    detail_path: str | None = None,
    extra_locations: Sequence[str] = ("Remote",),
) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": title,
            "jobDescription": f"<p>Build {title}.</p>",
            "timeType": "Full time",
            "workerSubType": "Regular",
            "location": "New York, NY",
            "additionalLocations": list(extra_locations),
            "postedOn": "Posted Yesterday",
            "jobFamily": "Engineering",
            "externalPath": detail_path if detail_path is not None else path,
            "jobReqId": path.rsplit("_", 1)[-1],
        },
        "hiringOrganization": {"name": "Acme"},
    }


def _detail_url(path: str) -> str:
    return f"https://{_HOST}/wday/cxs/acme/{_SITE}/job/{path}"


def _posting_url(path: str) -> str:
    return f"{_BOARD_URL}/job/{path}"


def _mock_listed_board(
    listings: Sequence[Mapping[str, object]],
    *,
    advertised_count: int | None = None,
    detail_path_prefix: str | None = None,
) -> None:
    pages: list[dict[str, object]] = []
    remaining = list(listings)
    while remaining or not pages:
        chunk = remaining[:20]
        remaining = remaining[20:]
        payload: dict[str, object] = {"jobPostings": chunk}
        if advertised_count is not None:
            payload["total"] = advertised_count
        pages.append(payload)
        if not remaining:
            break

    def listing_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        assert body.get("limit") == 20
        offset = int(body.get("offset") or 0)
        page_index = offset // 20
        return httpx.Response(200, json=pages[page_index])

    respx.post(_LIST_URL).mock(side_effect=listing_response)
    for listing in listings:
        path = str(listing["externalPath"])
        title = str(listing["title"])
        detail_path = (
            f"{detail_path_prefix}{path}" if detail_path_prefix is not None else path
        )
        respx.get(_detail_url(path)).mock(
            return_value=httpx.Response(
                200,
                json=_cxs_detail(path, title, detail_path=detail_path),
            )
        )


def test_workday_keeps_best_effort_native_get() -> None:
    capabilities = WorkdayProvider.pull_capabilities

    assert capabilities is not None
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.board_scan_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert callable(WorkdayProvider.pull_list)
    assert callable(WorkdayProvider.pull_get)


def test_workday_ingest_does_not_wrap_pull_or_cap_detail_budget() -> None:
    fetch_source = inspect.getsource(WorkdayProvider.fetch_jobs)
    list_source = inspect.getsource(WorkdayProvider.pull_list)

    assert "detail_budget=None" in fetch_source
    assert "self.pull_list(" not in fetch_source
    assert "pull_provider_max_details" in list_source
    assert "detail_budget=None" not in list_source


@pytest.mark.asyncio
async def test_workday_rejects_unlisted_enumeration_without_network() -> None:
    provider = WorkdayProvider(_settings())

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="cannot enumerate unlisted"):
            await provider.pull_list(
                client, _target(_BOARD_URL), include_unlisted=True
            )


@pytest.mark.asyncio
@respx.mock
async def test_workday_cxs_pagination_is_complete_for_pull_and_ingest() -> None:
    listings = [_listing(index) for index in range(1, 22)]
    _mock_listed_board(listings, advertised_count=21)
    provider = WorkdayProvider(_settings())
    expected_paths = [str(item["externalPath"]) for item in listings]

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_BOARD_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(
            client, _catalog_board(), _catalog_route()
        )

    assert listed.ready_for_apply is True
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 2
    assert listed.membership.observed_count == 21
    assert listed.membership.advertised_count == 21
    assert listed.detail_coverage.required is True
    assert listed.detail_coverage.complete is True
    assert [posting.job.remote_id for posting in listed.postings] == expected_paths
    assert {posting.job.board_key for posting in listed.postings} == {
        f"{_HOST.casefold()}:acme:{_SITE}"
    }
    first = listed.postings[0].job
    assert first.title == "Engineer 1"
    assert first.description == "Build Engineer 1."
    assert first.description_html == "<p>Build Engineer 1.</p>"
    assert first.employment_type == "Full time"
    assert first.locations == ["New York", "New York, NY", "Remote"]
    assert first.raw_detail["title"] == "Engineer 1"
    assert first.raw_detail["hiringOrganization"] == {"name": "Acme"}
    assert "jobPostingInfo" not in first.raw_detail
    assert isinstance(ingested, JobFetchResult)
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == [
        str(item["id"]) for item in listings
    ]
    assert {job.board_key for job in ingested} == {_CATALOG_BOARD_KEY}
    assert {job.company for job in ingested} == {"Acme Corp"}
    assert ingested[0].id == stable_id(_CATALOG_BOARD_KEY, "workday", "JR-1")
    assert ingested[0].description == "Build Engineer 1."


@pytest.mark.asyncio
@respx.mock
async def test_workday_empty_board_is_complete_membership() -> None:
    _mock_listed_board((), advertised_count=0)
    provider = WorkdayProvider(_settings())

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_BOARD_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(
            client, _catalog_board(), _catalog_route()
        )

    assert listed.postings == ()
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.advertised_count == 0
    assert listed.ready_for_apply is True
    assert ingested.authoritative is True
    assert list(ingested) == []


@pytest.mark.asyncio
@respx.mock
async def test_workday_short_page_without_advertised_total_is_terminal() -> None:
    listings = [_listing(1), _listing(2)]
    _mock_listed_board(listings)
    provider = WorkdayProvider(_settings())

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_BOARD_URL), include_unlisted=False
        )

    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.advertised_count is None
    assert listed.membership.observed_count == 2
    assert listed.ready_for_apply is True


@pytest.mark.asyncio
@respx.mock
async def test_workday_pull_list_still_fails_closed_at_detail_budget() -> None:
    listings = [_listing(1), _listing(2)]
    _mock_listed_board(listings, advertised_count=2)
    settings = _settings(pull_provider_max_details=1)
    provider = WorkdayProvider(settings)

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="detail fan-out"):
            await provider.pull_list(
                client, _target(_BOARD_URL), include_unlisted=False
            )

    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("pages", "message"),
    [
        pytest.param(
            (
                {
                    "total": 2,
                    "jobPostings": [
                        _listing(1),
                        _listing(1, title="Copy", path="NY/Other_JR-1"),
                    ],
                },
            ),
            "repeated pagination listing",
            id="duplicate-ids",
        ),
        pytest.param(
            (
                {
                    "total": 2,
                    "jobPostings": [
                        _listing(1, listing_id="JR-1", path="NY/Shared"),
                        _listing(2, listing_id="JR-2", path="NY/Shared"),
                    ],
                },
            ),
            "repeated pagination listing",
            id="duplicate-external-paths",
        ),
        pytest.param(
            ({"total": 2, "jobPostings": [_listing(1)]},),
            "advertised total does not match",
            id="advertised-mismatch",
        ),
        pytest.param(
            (
                {
                    "total": 40,
                    "jobPostings": [_listing(index) for index in range(1, 21)],
                },
                {"total": 41, "jobPostings": [_listing(21)]},
            ),
            "advertised total changed",
            id="total-changed",
        ),
        pytest.param(
            (
                {
                    "jobPostings": [_listing(index) for index in range(1, 21)],
                },
                {
                    "jobPostings": [_listing(index) for index in range(1, 21)],
                },
            ),
            "repeated pagination page",
            id="repeated-page",
        ),
        pytest.param(
            ({"total": True, "jobPostings": [_listing(1)]},),
            "advertised total is malformed",
            id="boolean-total",
        ),
        pytest.param(
            ({"total": 1, "jobPostings": [{}]},),
            "omitted a stable identity",
            id="missing-identity",
        ),
        pytest.param(
            (
                {
                    "total": 1,
                    "jobPostings": [
                        {
                            "id": True,
                            "title": "Boolean id",
                            "externalPath": "NY/Boolean",
                        }
                    ],
                },
            ),
            "malformed id",
            id="boolean-id",
        ),
    ],
)
async def test_workday_list_fails_closed_on_incomplete_membership(
    pages: Sequence[Mapping[str, object]],
    message: str,
) -> None:
    remaining = list(pages)

    def listing_response(_request: httpx.Request) -> httpx.Response:
        if not remaining:
            raise AssertionError("Workday listing requested more pages than the fixture")
        return httpx.Response(200, json=remaining.pop(0))

    respx.post(_LIST_URL).mock(side_effect=listing_response)
    provider = WorkdayProvider(_settings())

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await provider.pull_list(
                client, _target(_BOARD_URL), include_unlisted=False
            )
        remaining.extend(pages)
        with pytest.raises(ValueError, match=message):
            await provider.fetch_jobs(client, _catalog_board(), _catalog_route())


@pytest.mark.asyncio
@respx.mock
async def test_workday_native_get_reads_cxs_job_posting_info() -> None:
    path = "NY/Engineer_JR-1"
    respx.get(_detail_url(path)).mock(
        return_value=httpx.Response(
            200,
            json=_cxs_detail(path, "Engineer", detail_path=f"/job/{path}"),
        )
    )
    target = _target(_posting_url(path))
    assert target.target_kind == ProviderTargetKind.POSTING

    async with build_async_client(_settings()) as client:
        result = await WorkdayProvider(_settings()).pull_get(client, target)

    job = result.posting.job
    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.matched_identity == path
    assert job.remote_id == path
    assert job.title == "Engineer"
    assert job.description == "Build Engineer."
    assert job.employment_type == "Full time"
    assert job.workplace_type == "Full time"
    assert job.locations == ["New York, NY", "Remote"]
    assert result.posting.listing is None
    assert job.raw_listing == {}
    assert result.posting.detail == job.raw_detail
    assert job.raw_detail["jobDescription"] == "<p>Build Engineer.</p>"
    assert job.raw_detail["hiringOrganization"] == {"name": "Acme"}
    assert [call.request.url.path for call in respx.calls] == [
        f"/wday/cxs/acme/{_SITE}/job/{path}"
    ]


@pytest.mark.asyncio
@respx.mock
async def test_workday_native_get_keeps_flat_cxs_detail_payloads() -> None:
    path = "NY/Engineer_JR-1"
    payload = {
        "title": "Engineer",
        "timeType": "Full time",
        "workerSubType": "Regular",
        "jobDescription": "<p>Build.</p>",
        "customDetail": {"travel": "low"},
    }
    respx.get(_detail_url(path)).mock(return_value=httpx.Response(200, json=payload))

    async with build_async_client(_settings()) as client:
        result = await WorkdayProvider(_settings()).pull_get(
            client, _target(_posting_url(path))
        )

    assert result.method == ProviderGetMethod.NATIVE
    assert result.posting.job.title == "Engineer"
    assert result.posting.job.description == "Build."
    assert result.posting.detail == payload


@pytest.mark.asyncio
@respx.mock
async def test_workday_native_get_rejects_mismatched_detail_identity() -> None:
    path = "NY/Engineer_JR-1"
    respx.get(_detail_url(path)).mock(
        return_value=httpx.Response(
            200,
            json=_cxs_detail(path, "Other", detail_path="NY/Other_JR-9"),
        )
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match"):
            await WorkdayProvider(_settings()).pull_get(
                client, _target(_posting_url(path))
            )


@pytest.mark.asyncio
@respx.mock
async def test_workday_native_get_rejects_malformed_job_posting_info() -> None:
    path = "NY/Engineer_JR-1"
    respx.get(_detail_url(path)).mock(
        return_value=httpx.Response(200, json={"jobPostingInfo": "nope"})
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="invalid JSON"):
            await WorkdayProvider(_settings()).pull_get(
                client, _target(_posting_url(path))
            )


@pytest.mark.asyncio
@respx.mock
async def test_workday_list_and_native_get_share_slash_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = [_listing(1)]
    _mock_listed_board(
        listings,
        advertised_count=1,
        detail_path_prefix="/job/",
    )
    provider = WorkdayProvider(_settings())
    membership_calls: list[dict[str, object]] = []
    original_membership = provider._list_public_membership

    async def capture_membership(*args: Any, **kwargs: Any) -> Any:
        membership_calls.append(dict(kwargs))
        return await original_membership(*args, **kwargs)

    monkeypatch.setattr(provider, "_list_public_membership", capture_membership)
    path = str(listings[0]["externalPath"])

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_BOARD_URL), include_unlisted=False
        )
        exact = await provider.pull_get(client, _target(_posting_url(path)))
        ingested = await provider.fetch_jobs(
            client, _catalog_board(), _catalog_route()
        )

    assert [call["identity_mode"] for call in membership_calls] == ["pull", "ingest"]
    assert membership_calls[0]["detail_budget"] == 10_000
    assert membership_calls[1]["detail_budget"] is None
    assert listed.postings[0].job.remote_id == path
    assert listed.postings[0].job.remote_id == exact.posting.job.remote_id
    assert listed.postings[0].job.id == exact.posting.job.id
    assert exact.method == ProviderGetMethod.NATIVE
    assert ingested[0].remote_id == "JR-1"
    assert ingested[0].description == "Build Engineer 1."
