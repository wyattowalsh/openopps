from __future__ import annotations

import inspect
from collections.abc import Callable

import httpx
import pytest
import respx

import openopps.providers.boards.lever as lever_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderTargetKind,
)
from openopps.settings import OpenOppsSettings

_LIST_URL = "https://api.lever.co/v0/postings/acme"
_BOARD_URL = "https://jobs.lever.co/acme"


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(cache_enabled=False, retry_attempts=1)


def _provider() -> LeverProvider:
    return LeverProvider(_settings())


def _target(parser: Callable[[str], object], url: str):
    target = parser(url)
    assert target is not None
    return target


def _board_target():
    return _target(LeverProvider.parse_url_target, _BOARD_URL)


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _catalog_route() -> BoardProviderRecord:
    return BoardProviderRecord.model_validate(
        {
            "id": "manual:acme:lever",
            "source_key": "manual",
            "board_key": "manual:acme",
            "provider_id": "lever",
            "support_level": ProviderSupport.JOBS,
            "token": "acme",
        }
    )


def _lever_job(identity: str, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": identity,
        "text": f"Job {identity}",
        "hostedUrl": f"https://jobs.lever.co/acme/{identity}",
        "applyUrl": f"https://jobs.lever.co/acme/{identity}/apply",
        "categories": {"location": "Remote"},
        "description": f"<p>Build {identity}.</p>",
    }
    payload.update(updates)
    return payload


def _mock_page(skip: int, jobs: object, *, limit: int) -> respx.Route:
    return respx.get(
        _LIST_URL,
        params={"mode": "json", "skip": skip, "limit": limit},
    ).mock(return_value=httpx.Response(200, json=jobs))


def test_lever_keeps_documented_list_and_native_get() -> None:
    capabilities = LeverProvider.pull_capabilities

    assert capabilities is not None
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.board_scan_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.exact_unlisted_get_supported is False
    assert capabilities.interface_stability == InterfaceStability.DOCUMENTED
    assert callable(LeverProvider.pull_list)
    assert callable(LeverProvider.pull_get)


def test_lever_listing_kernel_does_not_wrap_fetch_or_pull() -> None:
    fetch_source = inspect.getsource(LeverProvider.fetch_jobs)
    list_source = inspect.getsource(LeverProvider.pull_list)
    get_source = inspect.getsource(LeverProvider.pull_get)
    kernel_source = inspect.getsource(LeverProvider._list_public_membership)
    check_source = inspect.getsource(LeverProvider.check_jobs)

    assert "self.pull_list(" not in fetch_source
    assert "to_provider_list_result" not in fetch_source
    assert "_list_public_membership" in fetch_source
    assert "to_job_fetch_result" in fetch_source
    assert "_list_public_membership" in list_source
    assert "self.fetch_jobs(" not in kernel_source
    assert "self.pull_list(" not in kernel_source
    assert "_list_public_membership" not in check_source
    assert "skip" not in check_source
    assert "limit" not in check_source
    assert "_list_public_membership" not in get_source
    assert "from_board_scan" not in get_source
    assert "ProviderGetMethod.NATIVE" in get_source


@pytest.mark.asyncio
@respx.mock
async def test_lever_empty_listing_is_complete_terminal_on_pull_and_ingest() -> None:
    page = _mock_page(0, [], limit=100)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _board_target(), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert page.call_count == 2
    assert listed.postings == ()
    assert listed.ready_for_apply is True
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.observed_count == 0
    assert listed.membership.advertised_count is None
    assert listed.detail_coverage.required is False
    assert isinstance(ingested, JobFetchResult)
    assert ingested.authoritative is True
    assert list(ingested) == []


@pytest.mark.asyncio
@respx.mock
async def test_lever_short_last_page_is_terminal_without_empty_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    first = _mock_page(0, [_lever_job("a"), _lever_job("b")], limit=2)
    last = _mock_page(2, [_lever_job("c")], limit=2)
    extra = _mock_page(3, [_lever_job("should-not-fetch")], limit=2)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _board_target(), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert first.call_count == 2
    assert last.call_count == 2
    assert extra.call_count == 0
    assert [posting.job.remote_id for posting in listed.postings] == ["a", "b", "c"]
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.complete is True
    assert listed.membership.authoritative is True
    assert listed.membership.pages_fetched == 2
    assert listed.membership.observed_count == 3
    assert listed.ready_for_apply is True
    assert listed.postings[0].detail is None
    assert listed.postings[0].listing == listed.postings[0].job.raw_listing
    assert {posting.job.board_key for posting in listed.postings} == {"acme"}
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == ["a", "b", "c"]
    assert {job.board_key for job in ingested} == {"manual:acme"}
    assert {job.company for job in ingested} == {"Acme Corp"}


@pytest.mark.asyncio
@respx.mock
async def test_lever_full_pages_require_empty_terminal_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    first = _mock_page(0, [_lever_job("a"), _lever_job("b")], limit=2)
    second = _mock_page(2, [_lever_job("c"), _lever_job("d")], limit=2)
    terminal = _mock_page(4, [], limit=2)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _board_target(), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert first.call_count == 2
    assert second.call_count == 2
    assert terminal.call_count == 2
    assert [posting.job.remote_id for posting in listed.postings] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.complete is True
    assert listed.membership.authoritative is True
    assert listed.membership.pages_fetched == 3
    assert listed.membership.observed_count == 4
    assert listed.ready_for_apply is True
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == ["a", "b", "c", "d"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param(
            [_lever_job("a"), _lever_job("b"), _lever_job("c")],
            "more jobs than the requested page size",
            id="oversized-page",
        ),
        pytest.param(
            [{"text": "No public id"}],
            "missing a posting id",
            id="missing-posting-id",
        ),
        pytest.param(
            [_lever_job("a"), _lever_job("a", text="Copy")],
            "duplicate posting ids",
            id="intra-page-duplicate",
        ),
    ],
)
async def test_lever_invalid_pages_fail_closed_on_pull_and_ingest(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    message: str,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    _mock_page(0, payload, limit=2)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await provider.pull_list(client, _board_target(), include_unlisted=False)
        with pytest.raises(ValueError, match=message):
            await provider.fetch_jobs(client, _catalog_board(), _catalog_route())


@pytest.mark.asyncio
@respx.mock
async def test_lever_page_budget_fails_closed_on_pull_and_ingest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 1)
    monkeypatch.setattr(lever_module, "_LEVER_MAX_PAGES", 2)
    first = _mock_page(0, [_lever_job("a")], limit=1)
    second = _mock_page(1, [_lever_job("b")], limit=1)
    extra = _mock_page(2, [_lever_job("c")], limit=1)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="finite page budget"):
            await provider.pull_list(client, _board_target(), include_unlisted=False)
        with pytest.raises(ValueError, match="finite page budget"):
            await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert first.call_count == 2
    assert second.call_count == 2
    assert extra.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_lever_rejects_unlisted_enumeration_before_fetch() -> None:
    route = _mock_page(0, [_lever_job("a")], limit=100)

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="unlisted enumeration"):
            await _provider().pull_list(
                client, _board_target(), include_unlisted=True
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.lever.co/acme/post-1",
        "https://jobs.lever.co/acme/post-1/apply",
        "https://api.lever.co/v0/postings/acme/post-1?mode=json",
    ],
)
async def test_lever_native_get_uses_public_posting_endpoint_without_listing(
    url: str,
) -> None:
    listing = _mock_page(0, [_lever_job("post-1")], limit=100)
    detail = respx.get(
        "https://api.lever.co/v0/postings/acme/post-1",
        params={"mode": "json"},
    ).mock(
        return_value=httpx.Response(
            200,
            json=_lever_job("post-1", description="<p>Exact detail</p>"),
        )
    )
    target = _target(LeverProvider.parse_url_target, url)
    assert target.target_kind == ProviderTargetKind.POSTING

    async with build_async_client(_settings()) as client:
        result = await _provider().pull_get(client, target)

    assert listing.call_count == 0
    assert detail.call_count == 1
    assert detail.calls[0].request.url.params.get("skip") is None
    assert detail.calls[0].request.url.params.get("limit") is None
    assert [call.request.url.path for call in respx.calls] == [
        "/v0/postings/acme/post-1"
    ]
    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.matched_identity == "post-1"
    assert result.posting.job.remote_id == "post-1"
    assert result.posting.listing is None
    assert result.posting.job.raw_listing == {}
    assert result.posting.detail == result.posting.job.raw_detail
    assert result.posting.detail["description"] == "<p>Exact detail</p>"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param([_lever_job("post-1")], "invalid JSON", id="listing-array"),
        pytest.param({"text": "Engineer"}, "missing a posting id", id="missing-id"),
        pytest.param(
            _lever_job("other"),
            "different posting id",
            id="mismatched-id",
        ),
    ],
)
async def test_lever_native_get_rejects_non_exact_detail_payloads(
    payload: object,
    message: str,
) -> None:
    respx.get(
        "https://api.lever.co/v0/postings/acme/post-1",
        params={"mode": "json"},
    ).mock(return_value=httpx.Response(200, json=payload))
    target = _target(
        LeverProvider.parse_url_target, "https://jobs.lever.co/acme/post-1"
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await _provider().pull_get(client, target)


@pytest.mark.asyncio
@respx.mock
async def test_lever_native_get_rejects_board_target() -> None:
    listing = _mock_page(0, [_lever_job("post-1")], limit=100)

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="posting target"):
            await _provider().pull_get(client, _board_target())

    assert listing.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_lever_fetch_jobs_does_not_call_pull_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_page(0, [_lever_job("a")], limit=100)
    provider = _provider()

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fetch_jobs must not wrap pull_list")

    monkeypatch.setattr(provider, "pull_list", forbidden)

    async with build_async_client(_settings()) as client:
        result = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert [job.remote_id for job in result] == ["a"]
    assert result.authoritative is True


@pytest.mark.asyncio
@respx.mock
async def test_lever_pull_get_does_not_scan_the_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(
        "https://api.lever.co/v0/postings/acme/post-1",
        params={"mode": "json"},
    ).mock(return_value=httpx.Response(200, json=_lever_job("post-1")))
    provider = _provider()

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("native get must not scan board membership")

    monkeypatch.setattr(provider, "pull_list", forbidden)
    monkeypatch.setattr(provider, "_list_public_membership", forbidden)
    target = _target(
        provider.parse_url_target, "https://jobs.lever.co/acme/post-1"
    )

    async with build_async_client(_settings()) as client:
        result = await provider.pull_get(client, target)

    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.matched_identity == "post-1"
