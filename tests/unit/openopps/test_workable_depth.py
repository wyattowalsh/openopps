from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

import httpx
import pytest
import respx

import openopps.providers.boards.workable as workable_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.workable import (
    WorkablePublicClient,
    WorkableSnapshotError,
    WorkableProvider,
)
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
)
from openopps.settings import OpenOppsSettings


_LISTING_URL = "https://apply.workable.com/api/v3/accounts/acme/jobs"
_DETAILS_URL = "https://www.workable.com/api/accounts/acme?details=true"


def _settings(**updates: object) -> OpenOppsSettings:
    payload: dict[str, object] = {
        "cache_enabled": False,
        "retry_attempts": 1,
        "cache_refresh": True,
    }
    payload.update(updates)
    return OpenOppsSettings.model_validate(payload)


def _target(url: str):
    target = WorkableProvider.parse_url_target(url)
    assert target is not None
    return target


def _listing(
    *jobs: tuple[str, str], total: int, next_page: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "total": total,
        "results": [
            {"shortcode": shortcode, "title": title} for shortcode, title in jobs
        ],
    }
    if next_page is not None:
        payload["nextPage"] = next_page
    return payload


def _details(*jobs: tuple[str, str]) -> dict[str, object]:
    return {
        "jobs": [
            {"shortcode": shortcode, "description": f"<p>{title}</p>"}
            for shortcode, title in jobs
        ]
    }


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme",
    )


def _catalog_route() -> BoardProviderRecord:
    return BoardProviderRecord.model_validate(
        {
            "id": "manual:acme:workable",
            "source_key": "manual",
            "board_key": "manual:acme",
            "provider_id": "workable",
            "support_level": ProviderSupport.JOBS,
            "token": "acme",
        }
    )


def test_workable_does_not_fake_native_get() -> None:
    capabilities = WorkableProvider.pull_capabilities

    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert callable(getattr(WorkableProvider, "pull_get", None)) is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.exact_unlisted_get_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT


@pytest.mark.asyncio
async def test_workable_rejects_unlisted_enumeration_without_network() -> None:
    provider = WorkableProvider(_settings())
    target = _target("https://apply.workable.com/acme")

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="unlisted"):
            await provider.pull_list(client, target, include_unlisted=True)


@pytest.mark.asyncio
@respx.mock
async def test_workable_cursor_pagination_records_terminal_evidence_and_board_scan_get() -> (
    None
):
    listing_bodies: list[object] = []

    def listing_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        listing_bodies.append(body)
        token = body.get("token")
        if token is None:
            return httpx.Response(
                200,
                json=_listing(
                    ("ONE", "First"), ("TWO", "Second"), total=3, next_page="cursor-2"
                ),
            )
        if token == "cursor-2":
            return httpx.Response(
                200,
                json=_listing(("THREE", "Third"), total=3),
            )
        raise AssertionError(f"unexpected Workable cursor {token!r}")

    listing = respx.post(_LISTING_URL).mock(side_effect=listing_response)
    respx.get(_DETAILS_URL).mock(
        return_value=httpx.Response(
            200,
            json=_details(("ONE", "First"), ("TWO", "Second"), ("THREE", "Third")),
        )
    )
    provider = WorkableProvider(_settings())
    posting_target = _target("https://apply.workable.com/acme/j/TWO")

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            posting_target.for_board_scan(),
            include_unlisted=False,
        )

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="workable",
        board_identity="acme",
        posting_identity="TWO",
    )

    assert listing.call_count == 2
    assert listing_bodies == [{}, {"token": "cursor-2"}]
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 2
    assert listed.membership.observed_count == 3
    assert listed.membership.advertised_count == 3
    assert listed.ready_for_apply is True
    assert [posting.job.remote_id for posting in listed.postings] == [
        "ONE",
        "TWO",
        "THREE",
    ]
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.matched_identity == "TWO"
    assert exact.posting.job.title == "Second"
    assert exact.membership == listed.membership
    assert WorkableProvider.pull_capabilities.native_get_supported is False


@pytest.mark.asyncio
@respx.mock
async def test_workable_board_scan_get_does_not_call_authenticated_shortcode_spi() -> (
    None
):
    respx.post(_LISTING_URL).mock(
        return_value=httpx.Response(
            200,
            json=_listing(("ABC.1", "Engineer"), total=1),
        )
    )
    respx.get(_DETAILS_URL).mock(
        return_value=httpx.Response(200, json=_details(("ABC.1", "Engineer")))
    )
    provider = WorkableProvider(_settings())
    posting_target = _target("https://www.workable.com/api/v2/accounts/acme/jobs/ABC.1")

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            posting_target.for_board_scan(),
            include_unlisted=False,
        )

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="workable",
        board_identity="acme",
        posting_identity="ABC.1",
    )
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.job.remote_id == "ABC.1"
    with pytest.raises(ValueError, match="exactly one posting identity"):
        listed.exact_match(
            provider_id="workable",
            board_identity="acme",
            posting_identity="missing",
        )


@pytest.mark.asyncio
@respx.mock
async def test_workable_empty_board_is_terminal_membership() -> None:
    listing = respx.post(_LISTING_URL).mock(
        return_value=httpx.Response(200, json=_listing(total=0))
    )
    respx.get(_DETAILS_URL).mock(return_value=httpx.Response(200, json={"jobs": []}))
    provider = WorkableProvider(_settings())

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            _target("https://apply.workable.com/acme"),
            include_unlisted=False,
        )

    assert listing.call_count == 1
    assert listed.postings == ()
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.advertised_count == 0
    assert listed.membership.observed_count == 0
    assert listed.ready_for_apply is True


@pytest.mark.asyncio
@respx.mock
async def test_workable_optional_details_failure_is_not_native_get() -> None:
    respx.post(_LISTING_URL).mock(
        return_value=httpx.Response(
            200,
            json=_listing(("ONE", "First"), ("TWO", "Second"), total=2),
        )
    )
    respx.get(_DETAILS_URL).mock(
        return_value=httpx.Response(500, json={"error": "nope"})
    )
    provider = WorkableProvider(_settings())

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            _target("https://apply.workable.com/acme"),
            include_unlisted=False,
        )

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="workable",
        board_identity="acme",
        posting_identity="TWO",
    )
    assert listed.membership.authoritative is True
    assert listed.membership.terminal_page_seen is True
    assert listed.detail_coverage.required is False
    assert listed.detail_coverage.completed_count == 0
    assert listed.detail_coverage.failed_count == 2
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.detail is None
    assert callable(getattr(provider, "pull_get", None)) is False


@pytest.mark.asyncio
@respx.mock
async def test_workable_fetch_jobs_is_authoritative_only_after_terminal_page() -> None:
    def listing_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        if body.get("token") is None:
            return httpx.Response(
                200,
                json=_listing(("ONE", "First"), total=2, next_page="cursor-2"),
            )
        return httpx.Response(200, json=_listing(("TWO", "Second"), total=2))

    respx.post(_LISTING_URL).mock(side_effect=listing_response)
    respx.get(_DETAILS_URL).mock(
        return_value=httpx.Response(
            200, json=_details(("ONE", "First"), ("TWO", "Second"))
        )
    )

    async with build_async_client(_settings()) as client:
        jobs = await WorkableProvider(_settings()).fetch_jobs(
            client,
            _catalog_board(),
            _catalog_route(),
        )

    assert isinstance(jobs, JobFetchResult)
    assert jobs.authoritative is True
    assert [job.remote_id for job in jobs] == ["ONE", "TWO"]


@pytest.mark.asyncio
async def test_workable_listing_requires_terminal_cursor_and_reconciled_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = await _fetch_snapshot(
        monkeypatch,
        (
            _listing(
                ("ONE", "First"), ("TWO", "Second"), total=3, next_page="cursor-2"
            ),
            _listing(("THREE", "Third"), total=3),
        ),
    )

    assert snapshot.total == 3
    assert snapshot.page_count == 2
    assert [cast(str, item["shortcode"]) for item in snapshot.listings] == [
        "ONE",
        "TWO",
        "THREE",
    ]


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        pytest.param(
            (
                _listing(
                    ("ONE", "First"), ("TWO", "Second"), total=2, next_page="cursor-2"
                ),
                _listing(("TWO", "Duplicate"), total=2),
            ),
            "duplicate job",
            id="duplicate-shortcode",
        ),
        pytest.param(
            (
                _listing(("ONE", "First"), total=2, next_page="cursor-2"),
                _listing(("TWO", "Second"), total=3),
            ),
            "total changed",
            id="total-changed",
        ),
        pytest.param(
            (_listing(("ONE", "First"), ("TWO", "Second"), total=3),),
            "ended before the advertised total",
            id="premature-terminal",
        ),
        pytest.param(
            (_listing(("ONE", "First"), ("TWO", "Second"), total=1),),
            "exceeded the advertised total",
            id="exceeded-total",
        ),
        pytest.param(
            (
                _listing(("ONE", "First"), total=3, next_page="cursor-2"),
                {"total": 3, "results": [], "nextPage": "cursor-3"},
            ),
            "empty continuation page",
            id="empty-continuation",
        ),
        pytest.param(
            (
                _listing(
                    ("ONE", "First"), ("TWO", "Second"), total=4, next_page="same"
                ),
                _listing(("THREE", "Third"), total=4, next_page="same"),
            ),
            "repeated a continuation token",
            id="repeated-cursor",
        ),
        pytest.param(
            (
                {
                    "total": 1,
                    "results": [{"shortcode": "ONE", "title": "First"}],
                    "nextPage": "",
                },
            ),
            "invalid continuation token",
            id="empty-cursor",
        ),
        pytest.param(
            (
                {
                    "total": 1,
                    "results": [{"shortcode": "ONE", "title": "First"}],
                    "nextPage": "  tok  ",
                },
            ),
            "invalid continuation token",
            id="padded-cursor",
        ),
        pytest.param(
            (
                {
                    "total": 1,
                    "results": [{"shortcode": "ONE", "title": "First"}],
                    "nextPage": 2,
                },
            ),
            "invalid continuation token",
            id="nonstring-cursor",
        ),
        pytest.param(
            ([{"shortcode": "ONE"}],),
            "invalid JSON",
            id="non-object-page",
        ),
        pytest.param(
            ({"total": True, "results": []},),
            "invalid JSON",
            id="boolean-total",
        ),
        pytest.param(
            ({"total": 1, "results": [{}]},),
            "omitted a job shortcode",
            id="missing-shortcode",
        ),
        pytest.param(
            ({"total": 2, "results": [], "nextPage": "cursor-2"},),
            "incomplete empty page",
            id="empty-first-page",
        ),
    ],
)
@pytest.mark.asyncio
async def test_workable_listing_fails_closed_without_terminal_success(
    monkeypatch: pytest.MonkeyPatch,
    pages: Sequence[object],
    message: str,
) -> None:
    with pytest.raises(WorkableSnapshotError, match=message):
        await _fetch_snapshot(monkeypatch, pages)


@pytest.mark.asyncio
async def test_workable_page_budget_fails_closed_before_unbounded_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        requested.append(kwargs.get("json"))
        return _listing(("ONE", "First"), total=4, next_page="cursor-2")

    monkeypatch.setattr(workable_module, "wait_for_workable_rate_limit", _no_rate_limit)
    public = WorkablePublicClient(request_json, max_pages=1, refresh=True)
    async with httpx.AsyncClient() as client:
        with pytest.raises(WorkableSnapshotError, match="page budget"):
            await public.fetch_listing_snapshot(client, "acme")

    assert requested == [{}]


@pytest.mark.asyncio
async def test_workable_page_cap_stops_after_inconsistent_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        token = cast(Mapping[str, object], kwargs.get("json") or {}).get("token")
        requested.append(token)
        if token is None:
            return _listing(
                ("ONE", "First"), ("TWO", "Second"), total=3, next_page="c2"
            )
        if token == "c2":
            return _listing(("THREE", "Third"), total=3, next_page="c3")
        raise AssertionError("Workable page cap must not fetch a third request")

    monkeypatch.setattr(workable_module, "wait_for_workable_rate_limit", _no_rate_limit)
    public = WorkablePublicClient(request_json, max_pages=2, refresh=True)
    async with httpx.AsyncClient() as client:
        with pytest.raises(WorkableSnapshotError, match="exceeded 2 pages"):
            await public.fetch_listing_snapshot(client, "acme")

    assert requested == [None, "c2"]


@pytest.mark.asyncio
async def test_workable_http_error_after_first_page_is_not_a_complete_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        token = cast(Mapping[str, object], kwargs.get("json") or {}).get("token")
        if token is None:
            return _listing(("ONE", "First"), total=2, next_page="cursor-2")
        request = httpx.Request("POST", _LISTING_URL)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(workable_module, "wait_for_workable_rate_limit", _no_rate_limit)
    public = WorkablePublicClient(request_json, max_pages=8, refresh=True)
    async with httpx.AsyncClient() as client:
        with pytest.raises(WorkableSnapshotError, match="failed after the first page"):
            await public.fetch_listing_snapshot(client, "acme")


async def _no_rate_limit() -> None:
    return None


async def _fetch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    pages: Sequence[object],
    *,
    max_pages: int = 8,
) -> Any:
    remaining = list(pages)

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> object:
        if not remaining:
            raise AssertionError(
                "Workable listing requested more pages than the fixture"
            )
        return remaining.pop(0)

    monkeypatch.setattr(workable_module, "wait_for_workable_rate_limit", _no_rate_limit)
    public = WorkablePublicClient(request_json, max_pages=max_pages, refresh=True)
    async with httpx.AsyncClient() as client:
        return await public.fetch_listing_snapshot(client, "acme")
