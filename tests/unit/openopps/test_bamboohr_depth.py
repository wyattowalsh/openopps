from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest
import respx

import openopps.providers.boards.bamboohr as bamboohr_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.bamboohr import BambooHRProvider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipScope,
    ProviderGetMethod,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id


def _settings(*, pull_provider_max_details: int = 10_000) -> OpenOppsSettings:
    return OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        board_concurrency=2,
        pull_provider_max_details=pull_provider_max_details,
    )


def _target(value: ProviderUrlTarget | None) -> ProviderUrlTarget:
    assert value is not None
    return value


def _listing(job_id: int, title: str) -> dict[str, object]:
    return {
        "id": job_id,
        "jobOpeningName": title,
        "departmentLabel": "Engineering",
        "listingExtra": {"id": job_id},
    }


def _detail(job_id: int, title: str) -> dict[str, object]:
    return {
        "result": {
            "jobOpening": {
                "id": job_id,
                "jobOpeningName": title,
                "description": f"<p>Build system {job_id}.</p>",
                "jobOpeningShareUrl": f"https://acme.bamboohr.com/careers/{job_id}",
                "detailExtra": {"id": job_id},
            }
        }
    }


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _route() -> BoardProviderRecord:
    return BoardProviderRecord(
        id="manual:acme:bamboohr",
        source_key="manual",
        board_key="manual:acme",
        provider_id="bamboohr",
        support_level=ProviderSupport.JOBS,
        tenant="acme",
    )


def _mock_listed_board(
    listings: list[dict[str, object]],
    *,
    advertised_count: int | None = None,
) -> None:
    payload: dict[str, object] = {"result": listings}
    if advertised_count is not None:
        payload["meta"] = {"totalCount": advertised_count}
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json=payload)
    )
    for listing in listings:
        job_id = listing["id"]
        title = str(listing["jobOpeningName"])
        respx.get(f"https://acme.bamboohr.com/careers/{job_id}/detail").mock(
            return_value=httpx.Response(200, json=_detail(int(str(job_id)), title))
        )


def test_bamboohr_native_get_stays_true() -> None:
    capabilities = BambooHRProvider.pull_capabilities

    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.board_scan_get_supported is False
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT
    assert callable(BambooHRProvider.pull_get)
    assert callable(BambooHRProvider.pull_list)


def test_bamboohr_ingest_does_not_pass_pull_detail_budget() -> None:
    fetch_source = inspect.getsource(BambooHRProvider.fetch_jobs)
    list_source = inspect.getsource(BambooHRProvider.pull_list)

    assert "detail_budget=None" in fetch_source
    assert "self.pull_list(" not in fetch_source
    assert "pull_provider_max_details" in list_source
    assert "detail_budget=None" not in list_source


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_ingest_fetches_every_listed_detail_beyond_pull_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = [_listing(41, "Analyst"), _listing(42, "Engineer")]
    _mock_listed_board(listings, advertised_count=2)
    settings = _settings(pull_provider_max_details=1)
    provider = BambooHRProvider(settings)
    membership_kwargs: dict[str, object] = {}
    original_membership = provider._list_public_membership

    async def capture_membership(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        membership_kwargs.update(kwargs)
        return await original_membership(*args, **kwargs)

    def forbid_pull_budget(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ingest must not apply pull detail budgets")

    monkeypatch.setattr(provider, "_list_public_membership", capture_membership)
    monkeypatch.setattr(
        bamboohr_module, "ensure_detail_fanout_within_budget", forbid_pull_budget
    )

    async with build_async_client(settings) as client:
        result = await provider.fetch_jobs(client, _catalog_board(), _route())

    assert isinstance(result, JobFetchResult)
    assert result.authoritative is True
    assert [job.remote_id for job in result] == ["41", "42"]
    assert membership_kwargs["detail_budget"] is None
    assert membership_kwargs["identity_mode"] == "ingest"
    assert membership_kwargs["include_unlisted"] is False
    first, second = result.jobs
    assert first.board_key == "manual:acme"
    assert first.company == "Acme Corp"
    assert first.id == stable_id("manual:acme", "bamboohr", "41")
    assert first.raw_listing == listings[0]
    assert first.raw_detail == _detail(41, "Analyst")["result"]["jobOpening"]
    assert second.raw_detail == _detail(42, "Engineer")["result"]["jobOpening"]
    assert respx.calls.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_pull_list_still_fails_closed_at_detail_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = [_listing(41, "Analyst"), _listing(42, "Engineer")]
    _mock_listed_board(listings, advertised_count=2)
    settings = _settings(pull_provider_max_details=1)
    provider = BambooHRProvider(settings)
    membership_kwargs: dict[str, object] = {}
    original_membership = provider._list_public_membership

    async def capture_membership(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        membership_kwargs.update(kwargs)
        return await original_membership(*args, **kwargs)

    monkeypatch.setattr(provider, "_list_public_membership", capture_membership)
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers")
    )

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="detail fan-out"):
            await provider.pull_list(client, target, include_unlisted=False)

    assert membership_kwargs["detail_budget"] == 1
    assert membership_kwargs["identity_mode"] == "pull"
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_list_reports_complete_single_page_membership() -> None:
    listings = [_listing(41, "Analyst"), _listing(42, "Engineer")]
    _mock_listed_board(listings, advertised_count=2)
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
    assert result.membership.authoritative is True
    assert result.membership.complete is True
    assert result.membership.terminal_page_seen is True
    assert result.membership.pages_fetched == 1
    assert result.membership.observed_count == 2
    assert result.membership.advertised_count == 2
    assert result.detail_coverage.required is True
    assert result.detail_coverage.complete is True
    assert result.ready_for_apply is True
    assert [posting.job.remote_id for posting in result.postings] == ["41", "42"]
    assert result.postings[0].job.board_key == "acme"


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
                "result": [_listing(1, "One"), _listing(1, "Two")],
            },
            "duplicate jobs",
        ),
        (
            {"meta": {"totalCount": 2}, "result": [_listing(1, "One")]},
            "advertised total",
        ),
    ],
)
async def test_bamboohr_list_fails_closed_on_incomplete_membership(
    payload: dict[str, object], message: str
) -> None:
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await BambooHRProvider(_settings()).fetch_jobs(
                client, _catalog_board(), _route()
            )
        with pytest.raises(ValueError, match=message):
            await BambooHRProvider(_settings()).pull_list(
                client,
                _target(
                    BambooHRProvider.parse_url_target(
                        "https://acme.bamboohr.com/careers"
                    )
                ),
                include_unlisted=False,
            )


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_native_get_uses_public_detail_without_listing() -> None:
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=_detail(42, "Engineer"))
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42")
    )
    assert target.target_kind == ProviderTargetKind.POSTING

    async with build_async_client(_settings()) as client:
        result = await BambooHRProvider(_settings()).pull_get(client, target)

    assert result.method == ProviderGetMethod.NATIVE
    assert result.membership is None
    assert result.matched_identity == "42"
    assert result.posting.job.remote_id == "42"
    assert result.posting.listing is None
    assert result.posting.job.raw_listing == {}
    assert result.posting.detail == _detail(42, "Engineer")["result"]["jobOpening"]
    assert [call.request.url.path for call in respx.calls] == ["/careers/42/detail"]


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_native_get_rejects_mismatched_detail_identity() -> None:
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(200, json=_detail(43, "Other"))
    )
    target = _target(
        BambooHRProvider.parse_url_target("https://acme.bamboohr.com/careers/42")
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="did not match"):
            await BambooHRProvider(_settings()).pull_get(client, target)
