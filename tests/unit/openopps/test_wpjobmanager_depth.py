from __future__ import annotations

import inspect

import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.wpjobmanager import WPJobManagerProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderTargetKind,
)
from openopps.settings import OpenOppsSettings

_REST_URL = "https://jobs.example.com/wp-json/wp/v2/job-listings"
_AJAX_URL = "https://jobs.example.com/jm-ajax/get_listings"


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(cache_enabled=False, retry_attempts=1)


def _provider() -> WPJobManagerProvider:
    return WPJobManagerProvider(_settings())


def _target(url: str):
    target = WPJobManagerProvider.parse_url_target(url)
    assert target is not None
    return target


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _catalog_route(*, board_url: str = _REST_URL) -> BoardProviderRecord:
    return BoardProviderRecord.model_validate(
        {
            "id": "manual:acme:wpjobmanager",
            "source_key": "manual",
            "board_key": "manual:acme",
            "provider_id": "wpjobmanager",
            "support_level": ProviderSupport.JOBS,
            "board_url": board_url,
        }
    )


def _rest_job(identity: int | str, *, title: str | None = None) -> dict[str, object]:
    return {
        "id": identity,
        "title": {"rendered": title or f"Job {identity}"},
        "content": {"rendered": f"<p>Build {identity}.</p>"},
        "link": f"https://jobs.example.com/jobs/{identity}",
        "meta": {"_company_name": "Acme Labs"},
    }


def _rest_headers(total: int, pages: int = 1) -> dict[str, str]:
    return {"x-wp-total": str(total), "x-wp-totalpages": str(pages)}


def _mock_rest_page(
    page: int,
    jobs: list[dict[str, object]],
    *,
    total: int,
    pages: int = 1,
) -> None:
    respx.get(_REST_URL, params={"per_page": 100, "page": page}).mock(
        return_value=httpx.Response(
            200,
            json=jobs,
            headers=_rest_headers(total, pages),
        )
    )


def _ajax_html(*jobs: tuple[str, str]) -> str:
    listings = "".join(
        (f'<li class="job_listing"><a href="{link}"><h3>{title}</h3></a></li>')
        for link, title in jobs
    )
    return f"<ul class='job_listings'>{listings}</ul>"


def test_wpjobmanager_native_get_stays_true() -> None:
    capabilities = WPJobManagerProvider.pull_capabilities

    assert capabilities is not None
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.board_scan_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.exact_unlisted_get_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert callable(WPJobManagerProvider.pull_list)
    assert callable(WPJobManagerProvider.pull_get)


def test_wpjobmanager_fetch_jobs_does_not_wrap_pull_list() -> None:
    source = inspect.getsource(WPJobManagerProvider.fetch_jobs)

    assert "self.pull_list(" not in source
    assert "_list_public_membership" in source


def test_wpjobmanager_ajax_urls_are_list_only() -> None:
    target = _target(_AJAX_URL)

    assert target.target_kind == ProviderTargetKind.BOARD
    assert target.posting_identity is None
    assert WPJobManagerProvider.parse_url_target(f"{_AJAX_URL}/7") is None


@pytest.mark.asyncio
@respx.mock
async def test_rest_listing_completeness_reconciles_pull_and_ingest() -> None:
    jobs = [_rest_job(7), _rest_job(8)]
    _mock_rest_page(1, jobs, total=2)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_REST_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert listed.ready_for_apply is True
    assert listed.provider_id == "wpjobmanager"
    assert listed.board_identity == _REST_URL
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.observed_count == 2
    assert listed.membership.advertised_count == 2
    assert listed.detail_coverage.required is False
    assert [posting.job.remote_id for posting in listed.postings] == ["7", "8"]
    assert {posting.job.board_key for posting in listed.postings} == {_REST_URL}
    assert listed.postings[0].listing == jobs[0]
    assert listed.postings[0].detail is None
    assert listed.postings[0].job.raw_listing == jobs[0]
    assert listed.postings[0].job.raw_detail == {}
    assert isinstance(ingested, JobFetchResult)
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == ["7", "8"]
    assert {job.board_key for job in ingested} == {"manual:acme"}
    assert {job.company for job in ingested} == {"Acme Labs"}


@pytest.mark.asyncio
@respx.mock
async def test_rest_pagination_records_terminal_page_on_pull_and_ingest() -> None:
    page_one = [_rest_job(index) for index in range(1, 101)]
    page_two = [_rest_job(101)]
    _mock_rest_page(1, page_one, total=101, pages=2)
    _mock_rest_page(2, page_two, total=101, pages=2)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_REST_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert listed.membership.pages_fetched == 2
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.advertised_count == 101
    assert listed.membership.observed_count == 101
    assert listed.ready_for_apply is True
    assert listed.postings[-1].job.remote_id == "101"
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested][-1] == "101"
    assert len(ingested.jobs) == 101


@pytest.mark.asyncio
@respx.mock
async def test_rest_empty_board_is_complete_membership() -> None:
    _mock_rest_page(1, [], total=0, pages=0)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_REST_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert listed.postings == ()
    assert listed.membership.pages_fetched == 1
    assert listed.membership.advertised_count == 0
    assert listed.membership.observed_count == 0
    assert listed.membership.terminal_page_seen is True
    assert listed.ready_for_apply is True
    assert ingested.authoritative is True
    assert list(ingested) == []


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("body", "headers", "message"),
    [
        pytest.param(
            [_rest_job(1), _rest_job(1, title="Copy")],
            _rest_headers(2),
            "repeated pagination listing",
            id="duplicate-ids",
        ),
        pytest.param(
            [_rest_job(1), _rest_job("1", title="String copy")],
            _rest_headers(2),
            "repeated pagination listing",
            id="duplicate-string-int-ids",
        ),
        pytest.param(
            [_rest_job(1)],
            _rest_headers(2),
            "advertised total",
            id="advertised-total-mismatch",
        ),
        pytest.param(
            [_rest_job(index) for index in range(50)],
            _rest_headers(50, pages=2),
            "page count",
            id="advertised-page-count-mismatch",
        ),
        pytest.param(
            [_rest_job(1)],
            {"x-wp-total": "many", "x-wp-totalpages": "1"},
            "must be an integer",
            id="malformed-total-header",
        ),
        pytest.param(
            [{"title": {"rendered": "No id"}}],
            _rest_headers(1),
            "missing a public job id",
            id="missing-id",
        ),
        pytest.param(
            [{"id": True, "title": {"rendered": "Boolean"}}],
            _rest_headers(1),
            "malformed public job id",
            id="boolean-id",
        ),
        pytest.param(
            {"not": "a list"},
            {},
            "invalid JSON",
            id="non-list-body",
        ),
    ],
)
async def test_rest_pull_list_and_fetch_jobs_fail_closed_together(
    body: object,
    headers: dict[str, str],
    message: str,
) -> None:
    respx.get(_REST_URL, params={"per_page": 100, "page": 1}).mock(
        return_value=httpx.Response(200, json=body, headers=headers)
    )
    provider = _provider()

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await provider.pull_list(client, _target(_REST_URL), include_unlisted=False)
        with pytest.raises(ValueError, match=message):
            await provider.fetch_jobs(client, _catalog_board(), _catalog_route())


@pytest.mark.asyncio
@respx.mock
async def test_native_get_uses_detail_without_listing_or_membership() -> None:
    detail = _rest_job(7, title="Engineer")
    respx.get(f"{_REST_URL}/7").mock(return_value=httpx.Response(200, json=detail))
    target = _target(f"{_REST_URL}/7")
    assert target.target_kind == ProviderTargetKind.POSTING

    async with build_async_client(_settings()) as client:
        result = await _provider().pull_get(client, target)

    assert WPJobManagerProvider.pull_capabilities.native_get_supported is True
    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.source_list is None
    assert result.matched_identity == "7"
    assert result.posting.job.remote_id == "7"
    assert result.posting.listing is None
    assert result.posting.job.raw_listing == {}
    assert result.posting.detail == detail
    assert result.posting.job.raw_detail == detail
    assert result.posting.job.title == "Engineer"
    assert [call.request.url.path for call in respx.calls] == [
        "/wp-json/wp/v2/job-listings/7"
    ]


@pytest.mark.asyncio
@respx.mock
async def test_native_get_rejects_mismatched_detail_identity() -> None:
    respx.get(f"{_REST_URL}/7").mock(
        return_value=httpx.Response(200, json=_rest_job(8, title="Other"))
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match"):
            await _provider().pull_get(client, _target(f"{_REST_URL}/7"))


@pytest.mark.asyncio
@respx.mock
async def test_native_get_rejects_boolean_detail_id() -> None:
    respx.get(f"{_REST_URL}/7").mock(
        return_value=httpx.Response(
            200, json={"id": True, "title": {"rendered": "Nope"}}
        )
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match"):
            await _provider().pull_get(client, _target(f"{_REST_URL}/7"))


@pytest.mark.asyncio
@respx.mock
async def test_ajax_listing_completeness_on_pull_and_ingest() -> None:
    first = ("https://jobs.example.com/jobs/one", "One")
    second = ("https://jobs.example.com/jobs/two", "Two")
    respx.get(_AJAX_URL, params={"page": 1, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            json={
                "found_jobs": True,
                "max_num_pages": 2,
                "found": 2,
                "html": _ajax_html(first),
            },
        )
    )
    respx.get(_AJAX_URL, params={"page": 2, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            json={
                "found_jobs": True,
                "max_num_pages": 2,
                "found": 2,
                "html": _ajax_html(second),
            },
        )
    )
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _target(_AJAX_URL), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(
            client, _catalog_board(), _catalog_route(board_url=_AJAX_URL)
        )

    assert listed.ready_for_apply is True
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.pages_fetched == 2
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.advertised_count == 2
    assert listed.membership.observed_count == 2
    assert listed.detail_coverage.required is False
    assert [posting.job.remote_id for posting in listed.postings] == [
        first[0],
        second[0],
    ]
    assert listed.postings[0].detail is None
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == [first[0], second[0]]
    assert WPJobManagerProvider.pull_capabilities.native_get_supported is True


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param(
            {
                "html": _ajax_html(
                    ("https://jobs.example.com/jobs/one", "One"),
                    ("https://jobs.example.com/jobs/one", "Copy"),
                ),
                "max_num_pages": 1,
                "found": 2,
            },
            "repeated AJAX pagination listing",
            id="duplicate-links",
        ),
        pytest.param(
            {
                "html": _ajax_html(("https://jobs.example.com/jobs/one", "One")),
                "max_num_pages": 1,
                "found": 2,
            },
            "advertised total",
            id="advertised-total-mismatch",
        ),
        pytest.param(
            {"html": "", "max_num_pages": "many"},
            "must be an integer",
            id="malformed-page-count",
        ),
    ],
)
async def test_ajax_pull_list_and_fetch_jobs_fail_closed_together(
    payload: dict[str, object], message: str
) -> None:
    respx.get(_AJAX_URL, params={"page": 1, "per_page": 100}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    provider = _provider()

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await provider.pull_list(client, _target(_AJAX_URL), include_unlisted=False)
        with pytest.raises(ValueError, match=message):
            await provider.fetch_jobs(
                client,
                _catalog_board(),
                _catalog_route(board_url=_AJAX_URL),
            )


@pytest.mark.asyncio
@respx.mock
async def test_pull_list_rejects_unlisted_enumeration_before_fetch() -> None:
    route = respx.get(_REST_URL, params={"per_page": 100, "page": 1}).mock(
        return_value=httpx.Response(200, json=[], headers=_rest_headers(0, pages=0))
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="unlisted"):
            await _provider().pull_list(
                client, _target(_REST_URL), include_unlisted=True
            )

    assert route.call_count == 0
