from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.pull import InterfaceStability, MembershipScope
from openopps.settings import OpenOppsSettings

_JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
_BOARD_URL = "https://boards.greenhouse.io/acme"


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(cache_enabled=False, retry_attempts=1)


def _provider() -> GreenhouseProvider:
    return GreenhouseProvider(_settings())


def _board_target():
    target = GreenhouseProvider.parse_url_target(_BOARD_URL)
    assert target is not None
    return target


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
            "id": "manual:acme:greenhouse",
            "source_key": "manual",
            "board_key": "manual:acme",
            "provider_id": "greenhouse",
            "support_level": ProviderSupport.JOBS,
            "token": "acme",
        }
    )


def _job(identity: int | str, *, title: str | None = None) -> dict[str, object]:
    return {
        "id": identity,
        "title": title or f"Job {identity}",
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{identity}",
    }


def _mock_jobs(payload: object) -> None:
    respx.get(_JOBS_URL, params={"content": "true"}).mock(
        return_value=httpx.Response(200, json=payload)
    )


def test_greenhouse_keeps_documented_list_and_native_get() -> None:
    capabilities = GreenhouseProvider.pull_capabilities

    assert capabilities is not None
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is True
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.interface_stability == InterfaceStability.DOCUMENTED
    assert callable(GreenhouseProvider.pull_list)
    assert callable(GreenhouseProvider.pull_get)


@pytest.mark.asyncio
@respx.mock
async def test_listing_completeness_reconciles_advertised_count_on_pull_and_ingest() -> (
    None
):
    payload = {
        "jobs": [_job(101), _job(202)],
        "count": 2,
        "meta": {"total": 2},
    }
    _mock_jobs(payload)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _board_target(), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    assert listed.ready_for_apply is True
    assert listed.membership.scope == MembershipScope.LISTED
    assert listed.membership.authoritative is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.observed_count == 2
    assert listed.membership.advertised_count == 2
    assert [posting.job.remote_id for posting in listed.postings] == ["101", "202"]
    assert {posting.job.board_key for posting in listed.postings} == {"acme"}
    assert listed.postings[0].detail is None
    assert isinstance(ingested, JobFetchResult)
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == ["101", "202"]
    assert {job.board_key for job in ingested} == {"manual:acme"}
    assert {job.company for job in ingested} == {"Acme Corp"}


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"jobs": []},
        {"jobs": [], "meta": {"total": 0}},
        {"jobs": [_job(7)]},
    ],
)
async def test_single_page_listing_is_complete_without_or_with_zero_advertised(
    payload: Mapping[str, object],
) -> None:
    _mock_jobs(payload)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(
            client, _board_target(), include_unlisted=False
        )
        ingested = await provider.fetch_jobs(client, _catalog_board(), _catalog_route())

    jobs = payload["jobs"]
    assert isinstance(jobs, list)
    expected_ids = [str(job["id"]) for job in jobs]
    meta = payload.get("meta")
    advertised = meta.get("total") if isinstance(meta, dict) else None
    assert listed.ready_for_apply is True
    assert listed.membership.complete is True
    assert listed.membership.terminal_page_seen is True
    assert listed.membership.authoritative is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.observed_count == len(expected_ids)
    assert listed.membership.advertised_count == advertised
    assert [posting.job.remote_id for posting in listed.postings] == expected_ids
    assert ingested.authoritative is True
    assert [job.remote_id for job in ingested] == expected_ids


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param(
            {"jobs": [_job(1), _job(1, title="Copy")]},
            "duplicate job ids",
            id="duplicate-ids",
        ),
        pytest.param(
            {"jobs": [_job(1), _job("1", title="String copy")]},
            "duplicate job ids",
            id="duplicate-string-int-ids",
        ),
        pytest.param(
            {"jobs": [_job(1)], "meta": {"total": 2}},
            "advertised count does not match",
            id="meta-total-mismatch",
        ),
        pytest.param(
            {"jobs": [_job(1)], "count": 2},
            "advertised count does not match",
            id="root-count-mismatch",
        ),
        pytest.param(
            {"jobs": [_job(1)], "count": 1, "meta": {"total": 2}},
            "advertised counts are inconsistent",
            id="inconsistent-advertised-counts",
        ),
        pytest.param(
            {"jobs": [_job(1)], "meta": {"total": True}},
            "advertised count is malformed",
            id="boolean-advertised-count",
        ),
        pytest.param(
            {"jobs": [_job(1)], "meta": {"total": -1}},
            "advertised count is malformed",
            id="negative-advertised-count",
        ),
        pytest.param(
            {"jobs": [{"id": True, "title": "Boolean id"}]},
            "malformed public job id",
            id="boolean-job-id",
        ),
    ],
)
async def test_pull_list_and_fetch_jobs_fail_closed_together(
    payload: object,
    message: str,
) -> None:
    _mock_jobs(payload)
    provider = _provider()

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await provider.pull_list(client, _board_target(), include_unlisted=False)
        with pytest.raises(ValueError, match=message):
            await provider.fetch_jobs(client, _catalog_board(), _catalog_route())


@pytest.mark.asyncio
@respx.mock
async def test_pull_list_rejects_unlisted_enumeration_before_fetch() -> None:
    route = respx.get(_JOBS_URL, params={"content": "true"}).mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="unlisted enumeration"):
            await _provider().pull_list(
                client, _board_target(), include_unlisted=True
            )

    assert route.call_count == 0
