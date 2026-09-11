from __future__ import annotations

import inspect
from collections.abc import Callable

import httpx
import pytest
import respx

import openopps.providers.boards.teamtailor as teamtailor_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.teamtailor import TeamtailorProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id

_RSS_URL = "https://acme.teamtailor.com/jobs.rss"
_BOARD_URL = "https://acme.teamtailor.com/jobs"


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(cache_enabled=False, retry_attempts=1)


def _target(parser: Callable[[str], object], url: str):
    target = parser(url)
    assert target is not None
    return target


def _rss(*items: tuple[str, str, str]) -> str:
    rendered = "".join(
        (
            "<item>"
            f"<title>Job {tail}</title>"
            f"<link>https://acme.teamtailor.com/jobs/{tail}</link>"
            f"<guid>{guid}</guid>"
            f"<description><![CDATA[<p>{description}</p>]]></description>"
            "</item>"
        )
        for tail, guid, description in items
    )
    return f"<rss><channel>{rendered}</channel></rss>"


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _catalog_route(**updates: object) -> BoardProviderRecord:
    payload: dict[str, object] = {
        "id": "manual:acme:teamtailor",
        "source_key": "manual",
        "board_key": "manual:acme",
        "provider_id": "teamtailor",
        "support_level": ProviderSupport.JOBS,
        "token": "acme",
        "host": "acme.teamtailor.com",
    }
    payload.update(updates)
    return BoardProviderRecord.model_validate(payload)


def test_teamtailor_does_not_advertise_native_get() -> None:
    capabilities = TeamtailorProvider.pull_capabilities

    assert capabilities is not None
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.exact_unlisted_get_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert callable(getattr(TeamtailorProvider, "pull_get", None)) is False
    assert callable(getattr(TeamtailorProvider, "pull_list", None)) is True


def test_teamtailor_listing_kernel_does_not_wrap_fetch_jobs() -> None:
    fetch_source = inspect.getsource(TeamtailorProvider.fetch_jobs)
    list_source = inspect.getsource(TeamtailorProvider.pull_list)
    kernel_source = inspect.getsource(TeamtailorProvider._list_public_membership)
    check_source = inspect.getsource(TeamtailorProvider.check_jobs)

    assert "self.pull_list(" not in fetch_source
    assert "await self.pull_list" not in fetch_source
    assert "to_provider_list_result" not in fetch_source
    assert "_list_public_membership" in fetch_source
    assert "to_job_fetch_result" in fetch_source
    assert "_list_public_membership" in list_source
    assert "self.fetch_jobs(" not in kernel_source
    assert "await self.fetch_jobs" not in kernel_source
    assert "self.pull_list(" not in kernel_source
    assert "_list_public_membership" not in check_source
    assert "self.pull_list(" not in check_source
    assert "self.fetch_jobs(" not in check_source


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_fetch_jobs_keeps_guid_first_ingest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 2)
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(
                ("101-engineer", "guid-not-the-url-tail-101", "First"),
                ("102-designer", "guid-not-the-url-tail-102", "Second"),
            ),
        )
    )
    respx.get(_RSS_URL, params={"offset": 2, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("103-writer", "guid-not-the-url-tail-103", "Third")),
        )
    )
    provider = TeamtailorProvider(_settings())
    board = _catalog_board()

    async with build_async_client(_settings()) as client:
        result = await provider.fetch_jobs(client, board, _catalog_route())

    assert isinstance(result, JobFetchResult)
    assert result.authoritative is True
    assert [job.remote_id for job in result] == [
        "guid-not-the-url-tail-101",
        "guid-not-the-url-tail-102",
        "guid-not-the-url-tail-103",
    ]
    assert {job.board_key for job in result} == {"manual:acme"}
    assert {job.company for job in result} == {"Acme Corp"}
    assert result[0].id == stable_id(
        "manual:acme", "teamtailor", "guid-not-the-url-tail-101"
    )
    assert result[0].raw_listing["guid"] == "guid-not-the-url-tail-101"
    assert result[0].posting_url == "https://acme.teamtailor.com/jobs/101-engineer"


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_pull_list_prefers_link_identity_for_board_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 2)
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(
                ("101-engineer", "guid-not-the-url-tail-101", "First"),
                ("102-designer", "guid-not-the-url-tail-102", "Second"),
            ),
        )
    )
    respx.get(_RSS_URL, params={"offset": 2, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("103-writer", "guid-not-the-url-tail-103", "Third")),
        )
    )
    provider = TeamtailorProvider(_settings())
    board_target = _target(provider.parse_url_target, _BOARD_URL)

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(client, board_target, include_unlisted=False)

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="teamtailor",
        board_identity="acme",
        posting_identity="102-designer",
    )

    assert [posting.job.remote_id for posting in listed.postings] == [
        "101-engineer",
        "102-designer",
        "103-writer",
    ]
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 2
    assert listed.membership.observed_count == 3
    assert listed.postings[0].job.board_key == "acme"
    assert listed.postings[0].listing["guid"] == "guid-not-the-url-tail-101"
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.job.remote_id == "102-designer"
    assert exact.matched_identity == "102-designer"
    assert exact.membership == listed.membership
    with pytest.raises(ValueError, match="exactly one posting identity"):
        ProviderGetResult.from_board_scan(
            listed,
            provider_id="teamtailor",
            board_identity="acme",
            posting_identity="guid-not-the-url-tail-102",
        )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_board_scan_get_requires_complete_exact_match() -> None:
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("101-engineer", "guid-101", "Engineer")),
        )
    )
    provider = TeamtailorProvider(_settings())
    posting_target = _target(
        provider.parse_url_target,
        "https://acme.teamtailor.com/jobs/101-engineer",
    )

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            posting_target.for_board_scan(),
            include_unlisted=False,
        )
        with pytest.raises(ValueError, match="board target"):
            await provider.pull_list(client, posting_target, include_unlisted=False)

    exact = ProviderGetResult.from_board_scan(
        listed,
        provider_id="teamtailor",
        board_identity="acme",
        posting_identity="101-engineer",
    )
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.job.title == "Job 101-engineer"
    with pytest.raises(ValueError, match="exactly one posting identity"):
        ProviderGetResult.from_board_scan(
            listed,
            provider_id="teamtailor",
            board_identity="acme",
            posting_identity="missing-posting",
        )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_fetch_jobs_does_not_call_pull_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("101-engineer", "guid-101", "First")),
        )
    )
    provider = TeamtailorProvider(_settings())

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fetch_jobs must not wrap pull_list")

    monkeypatch.setattr(provider, "pull_list", forbidden)

    async with build_async_client(_settings()) as client:
        result = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert [job.remote_id for job in result] == ["guid-101"]
    assert result.authoritative is True


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_pull_list_does_not_wrap_fetch_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("101-engineer", "guid-101", "First")),
        )
    )
    provider = TeamtailorProvider(_settings())

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("listing kernel must not wrap fetch_jobs")

    monkeypatch.setattr(provider, "fetch_jobs", forbidden)

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client,
            _target(provider.parse_url_target, _BOARD_URL),
            include_unlisted=False,
        )

    assert [posting.job.remote_id for posting in listed.postings] == ["101-engineer"]
    assert listed.membership.authoritative is True


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_ingest_fails_closed_on_duplicate_guids() -> None:
    respx.get(_RSS_URL, params={"offset": 0, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(
                ("101-engineer", "shared-guid", "First"),
                ("102-designer", "shared-guid", "Second"),
            ),
        )
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="duplicate posting"):
            await TeamtailorProvider(_settings()).fetch_jobs(
                client, _catalog_board(), _catalog_route()
            )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_rejects_unlisted_enumeration() -> None:
    provider = TeamtailorProvider(_settings())
    target = _target(provider.parse_url_target, _BOARD_URL)

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="unlisted enumeration"):
            await provider.pull_list(client, target, include_unlisted=True)


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_check_jobs_stays_a_cheap_probe() -> None:
    rss = respx.get(_RSS_URL).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("101-engineer", "guid-101", "First")),
        )
    )

    async with build_async_client(_settings()) as client:
        count = await TeamtailorProvider(_settings()).check_jobs(
            client, _catalog_board(), _catalog_route()
        )

    assert count == 1
    assert rss.call_count == 1
    assert rss.calls[0].request.url.params.get("offset") is None
    assert rss.calls[0].request.url.params.get("per_page") is None
