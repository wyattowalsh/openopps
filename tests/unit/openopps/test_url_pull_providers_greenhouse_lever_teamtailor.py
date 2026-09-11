from __future__ import annotations

from collections.abc import Callable
import xml.etree.ElementTree as ET

import httpx
import pytest
import respx

import openopps.providers.boards.lever as lever_module
import openopps.providers.boards.teamtailor as teamtailor_module
from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.boards.teamtailor import TeamtailorProvider
from openopps.providers.pull import (
    InterfaceStability,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderTargetKind,
)
from openopps.settings import OpenOppsSettings


def _settings() -> OpenOppsSettings:
    return OpenOppsSettings(cache_enabled=False, retry_attempts=1)


def _target(parser: Callable[[str], object], url: str):
    target = parser(url)
    assert target is not None
    return target


def _lever_job(identity: str) -> dict[str, object]:
    return {
        "id": identity,
        "text": f"Job {identity}",
        "hostedUrl": f"https://jobs.lever.co/acme/{identity}",
        "applyUrl": f"https://jobs.lever.co/acme/{identity}/apply",
        "categories": {"location": "Remote"},
        "description": f"<p>Build {identity}.</p>",
    }


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


@pytest.mark.parametrize(
    ("url", "kind", "board_identity", "posting_identity"),
    [
        (
            "https://boards.greenhouse.io/Acme%26Co",
            ProviderTargetKind.BOARD,
            "Acme&Co",
            None,
        ),
        (
            "https://job-boards.greenhouse.io/acme/jobs/123?gh_src=abc",
            ProviderTargetKind.POSTING,
            "acme",
            "123",
        ),
        (
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123?content=true",
            ProviderTargetKind.POSTING,
            "acme",
            "123",
        ),
    ],
)
def test_greenhouse_strict_target_parsing(
    url: str,
    kind: ProviderTargetKind,
    board_identity: str,
    posting_identity: str | None,
) -> None:
    target = GreenhouseProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.board_identity == board_identity
    assert target.posting_identity == posting_identity
    assert "?" not in target.url


@pytest.mark.parametrize(
    "url",
    [
        "https://greenhouse.io/acme",
        "https://support.greenhouse.io/acme",
        "https://boards.greenhouse.io/acme/jobs",
        "https://boards.greenhouse.io/acme/jobs/123/extra",
        "https://boards-api.greenhouse.io/v2/boards/acme/jobs",
        "https://boards.greenhouse.io:8443/acme",
        "https://boards.greenhouse.io/acme%2Fother",
        "https://boards.greenhouse.io/acme//jobs/123",
        "https://boards.greenhouse.io/%20acme",
    ],
)
def test_greenhouse_rejects_non_native_shapes(url: str) -> None:
    assert GreenhouseProvider.parse_url_target(url) is None


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_list_and_exact_get_preserve_distinct_raw_evidence() -> None:
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "true"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                        "content": "<p>List body</p>",
                        "listingOnly": True,
                    }
                ],
                "meta": {"total": 1},
            },
        )
    )
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123",
        params={"content": "true"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 123,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "content": "<p>Detail body</p>",
                "detailOnly": True,
            },
        )
    )
    provider = GreenhouseProvider(_settings())
    board_target = _target(
        GreenhouseProvider.parse_url_target,
        "https://job-boards.greenhouse.io/acme",
    )
    posting_target = _target(
        GreenhouseProvider.parse_url_target,
        "https://boards.greenhouse.io/acme/jobs/123",
    )

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(client, board_target, include_unlisted=False)
        exact = await provider.pull_get(client, posting_target)

    assert listed.ready_for_apply is True
    assert listed.membership.pages_fetched == 1
    assert listed.membership.advertised_count == 1
    assert listed.postings[0].listing == listed.postings[0].job.raw_listing
    assert listed.postings[0].listing["listingOnly"] is True
    assert listed.postings[0].detail is None
    assert exact.method == ProviderGetMethod.NATIVE
    assert exact.membership is None
    assert exact.posting.listing is None
    assert exact.posting.detail == exact.posting.job.raw_detail
    assert exact.posting.detail["detailOnly"] is True


@pytest.mark.asyncio
async def test_greenhouse_pull_sets_membership_and_detail_cache_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GreenhouseProvider(_settings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        roles.append(kwargs.get("cache_identity"))
        if url.endswith("/123"):
            return {
                "id": 123,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            }
        return {"jobs": []}

    monkeypatch.setattr(provider, "_request_json", request_json)
    board_target = _target(
        provider.parse_url_target,
        "https://boards.greenhouse.io/acme",
    )
    posting_target = _target(
        provider.parse_url_target,
        "https://boards.greenhouse.io/acme/jobs/123",
    )
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, board_target, include_unlisted=False)
        await provider.pull_get(client, posting_target)

    assert roles == [{"role": "membership"}, {"role": "detail"}]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"jobs": [{"id": 1}, {"id": 1}]},
            "duplicate job ids",
        ),
        (
            {"jobs": [{"id": 1}], "meta": {"total": 2}},
            "advertised count",
        ),
        (
            {"jobs": [{"title": "No public id"}]},
            "missing a public job id",
        ),
        (
            {"jobs": "not-a-list"},
            "invalid JSON",
        ),
    ],
)
async def test_greenhouse_list_fails_closed_on_invalid_membership(
    payload: object,
    message: str,
) -> None:
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "true"},
    ).mock(return_value=httpx.Response(200, json=payload))
    target = _target(
        GreenhouseProvider.parse_url_target,
        "https://boards.greenhouse.io/acme",
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await GreenhouseProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_exact_get_requires_response_identity_equality() -> None:
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123",
        params={"content": "true"},
    ).mock(return_value=httpx.Response(200, json={"id": 456}))
    target = _target(
        GreenhouseProvider.parse_url_target,
        "https://boards.greenhouse.io/acme/jobs/123",
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="different job id"):
            await GreenhouseProvider(_settings()).pull_get(client, target)


@pytest.mark.parametrize(
    ("url", "kind", "posting_identity"),
    [
        ("https://jobs.lever.co/Acme%26Co", ProviderTargetKind.BOARD, None),
        (
            "https://api.lever.co/v0/postings/acme?mode=json",
            ProviderTargetKind.BOARD,
            None,
        ),
        (
            "https://jobs.lever.co/acme/post-1",
            ProviderTargetKind.POSTING,
            "post-1",
        ),
        (
            "https://jobs.lever.co/acme/post-1/apply?lever-source=site",
            ProviderTargetKind.POSTING,
            "post-1",
        ),
        (
            "https://api.lever.co/v0/postings/acme/post-1?mode=json",
            ProviderTargetKind.POSTING,
            "post-1",
        ),
    ],
)
def test_lever_strict_target_parsing(
    url: str,
    kind: ProviderTargetKind,
    posting_identity: str | None,
) -> None:
    target = LeverProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.posting_identity == posting_identity
    assert "?" not in target.url


@pytest.mark.parametrize(
    "url",
    [
        "https://lever.co/acme",
        "https://jobs.lever.co/acme/post-1/not-apply",
        "https://jobs.lever.co/acme/post-1/apply/extra",
        "https://api.lever.co/v1/postings/acme",
        "https://api.lever.co/v0/postings",
        "https://jobs.lever.co:8443/acme",
        "https://jobs.lever.co/acme%2Fother",
        "https://jobs.lever.co/acme//post-1",
        "https://jobs.lever.co/%20acme",
    ],
)
def test_lever_rejects_non_native_shapes(url: str) -> None:
    assert LeverProvider.parse_url_target(url) is None


@pytest.mark.asyncio
@respx.mock
async def test_lever_traverses_exact_full_pages_until_empty_and_gets_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    list_url = "https://api.lever.co/v0/postings/acme"
    respx.get(
        list_url,
        params={"mode": "json", "skip": 0, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("a"), _lever_job("b")]))
    respx.get(
        list_url,
        params={"mode": "json", "skip": 2, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("c"), _lever_job("d")]))
    terminal = respx.get(
        list_url,
        params={"mode": "json", "skip": 4, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=[]))
    respx.get(
        "https://api.lever.co/v0/postings/acme/c",
        params={"mode": "json"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={**_lever_job("c"), "description": "<p>Exact detail</p>"},
        )
    )
    provider = LeverProvider(_settings())
    board_target = _target(LeverProvider.parse_url_target, "https://jobs.lever.co/acme")
    posting_target = _target(
        LeverProvider.parse_url_target, "https://jobs.lever.co/acme/c/apply"
    )

    async with build_async_client(_settings()) as client:
        listed = await provider.pull_list(client, board_target, include_unlisted=False)
        exact = await provider.pull_get(client, posting_target)

    assert [posting.job.remote_id for posting in listed.postings] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert listed.membership.pages_fetched == 3
    assert terminal.call_count == 1
    assert listed.postings[0].listing["id"] == "a"
    assert listed.postings[0].detail is None
    assert exact.method == ProviderGetMethod.NATIVE
    assert exact.posting.listing is None
    assert exact.posting.detail["description"] == "<p>Exact detail</p>"


@pytest.mark.asyncio
async def test_lever_pull_sets_page_and_detail_cache_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LeverProvider(_settings())
    roles: list[object] = []

    async def request_json(
        _client: httpx.AsyncClient,
        _method: str,
        url: str,
        **kwargs: object,
    ) -> object:
        roles.append(kwargs.get("cache_identity"))
        return _lever_job("job-1") if url.endswith("/job-1") else []

    monkeypatch.setattr(provider, "_request_json", request_json)
    board_target = _target(
        provider.parse_url_target,
        "https://jobs.lever.co/acme",
    )
    posting_target = _target(
        provider.parse_url_target,
        "https://jobs.lever.co/acme/job-1",
    )
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, board_target, include_unlisted=False)
        await provider.pull_get(client, posting_target)

    assert roles == [{"role": "membership_page"}, {"role": "detail"}]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("failure", ["duplicate", "repeat", "malformed"])
async def test_lever_fails_closed_on_duplicate_repeat_or_malformed_pages(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    url = "https://api.lever.co/v0/postings/acme"
    first_page = [_lever_job("a"), _lever_job("b")]
    if failure == "duplicate":
        second_page: object = [_lever_job("b")]
        message = "duplicate posting ids"
    elif failure == "repeat":
        second_page = first_page
        message = "repeated postings page"
    else:
        second_page = {"data": []}
        message = "invalid JSON"
    respx.get(
        url,
        params={"mode": "json", "skip": 0, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=first_page))
    respx.get(
        url,
        params={"mode": "json", "skip": 2, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=second_page))
    target = _target(LeverProvider.parse_url_target, "https://jobs.lever.co/acme")

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await LeverProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_lever_page_cap_fails_before_an_unbounded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 1)
    monkeypatch.setattr(lever_module, "_LEVER_MAX_PAGES", 2)
    url = "https://api.lever.co/v0/postings/acme"
    first = respx.get(
        url,
        params={"mode": "json", "skip": 0, "limit": 1},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("a")]))
    second = respx.get(
        url,
        params={"mode": "json", "skip": 1, "limit": 1},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("b")]))
    target = _target(LeverProvider.parse_url_target, "https://jobs.lever.co/acme")

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="finite page budget"):
            await LeverProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )

    assert first.call_count == 1
    assert second.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_lever_exact_get_requires_response_identity_equality() -> None:
    respx.get(
        "https://api.lever.co/v0/postings/acme/a",
        params={"mode": "json"},
    ).mock(return_value=httpx.Response(200, json=_lever_job("different")))
    target = _target(LeverProvider.parse_url_target, "https://jobs.lever.co/acme/a")

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="different posting id"):
            await LeverProvider(_settings()).pull_get(client, target)


@pytest.mark.parametrize(
    ("url", "kind", "posting_identity"),
    [
        ("https://acme.teamtailor.com/", ProviderTargetKind.BOARD, None),
        ("https://acme.teamtailor.com/jobs", ProviderTargetKind.BOARD, None),
        ("https://acme.teamtailor.com/jobs.rss", ProviderTargetKind.BOARD, None),
        (
            "https://acme.teamtailor.com/jobs/123-senior-engineer?source=site",
            ProviderTargetKind.POSTING,
            "123-senior-engineer",
        ),
    ],
)
def test_teamtailor_strict_target_parsing(
    url: str,
    kind: ProviderTargetKind,
    posting_identity: str | None,
) -> None:
    target = TeamtailorProvider.parse_url_target(url)

    assert target is not None
    assert target.target_kind == kind
    assert target.board_identity == "acme"
    assert target.posting_identity == posting_identity
    assert target.route.host == "acme.teamtailor.com"


@pytest.mark.parametrize(
    "url",
    [
        "https://teamtailor.com/jobs",
        "https://teamtailor.com.evil.example/jobs",
        "https://acme.teamtailor.com/careers",
        "https://acme.teamtailor.com/jobs/123/apply",
        "https://acme.teamtailor.com:8443/jobs",
        "https://acme.teamtailor.com/jobs/acme%2Fother",
        "https://acme.teamtailor.com/jobs//123",
        "https://acme.teamtailor.com/jobs/%20posting",
    ],
)
def test_teamtailor_rejects_non_native_shapes(url: str) -> None:
    assert TeamtailorProvider.parse_url_target(url) is None


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_traverses_pages_and_board_scan_matches_url_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 2)
    url = "https://acme.teamtailor.com/jobs.rss"
    respx.get(url, params={"offset": 0, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(
                ("101-engineer", "guid-not-the-url-tail-101", "First"),
                ("102-designer", "guid-not-the-url-tail-102", "Second"),
            ),
        )
    )
    respx.get(url, params={"offset": 2, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("103-writer", "guid-not-the-url-tail-103", "Third")),
        )
    )
    provider = TeamtailorProvider(_settings())
    board_target = _target(
        TeamtailorProvider.parse_url_target,
        "https://acme.teamtailor.com/jobs",
    )

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
    assert listed.membership.pages_fetched == 2
    assert listed.postings[0].listing["guid"] == "guid-not-the-url-tail-101"
    assert exact.method == ProviderGetMethod.BOARD_SCAN
    assert exact.posting.job.remote_id == "102-designer"
    assert TeamtailorProvider.pull_capabilities.native_get_supported is False
    assert TeamtailorProvider.pull_capabilities.interface_stability == (
        InterfaceStability.BEST_EFFORT
    )

    legacy_item = ET.fromstring(
        _rss(("101-engineer", "guid-not-the-url-tail-101", "First"))
    ).find("channel/item")
    assert legacy_item is not None
    legacy = provider._normalize(
        BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme"),
        legacy_item,
    )
    assert legacy.remote_id == "guid-not-the-url-tail-101"


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_pull_list_accepts_exact_target_board_scan_projection() -> (
    None
):
    url = "https://acme.teamtailor.com/jobs.rss"
    respx.get(url, params={"offset": 0, "per_page": 100}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("101", "guid-101", "Engineer")),
        )
    )
    provider = TeamtailorProvider(_settings())
    posting_target = _target(
        provider.parse_url_target,
        "https://acme.teamtailor.com/jobs/101",
    )

    async with build_async_client(_settings()) as client:
        result = await provider.pull_list(
            client,
            posting_target.for_board_scan(),
            include_unlisted=False,
        )

    assert (
        result.exact_match(
            provider_id="teamtailor",
            board_identity="acme",
            posting_identity="101",
        ).job.title
        == "Job 101"
    )


@pytest.mark.asyncio
async def test_teamtailor_pull_list_sets_membership_page_cache_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = TeamtailorProvider(_settings())
    roles: list[object] = []

    async def request_text(
        _client: httpx.AsyncClient,
        _method: str,
        _url: str,
        **kwargs: object,
    ) -> str:
        roles.append(kwargs.get("cache_identity"))
        return _rss()

    monkeypatch.setattr(provider, "_request_text", request_text)
    target = _target(
        provider.parse_url_target,
        "https://acme.teamtailor.com/jobs",
    )
    async with httpx.AsyncClient() as client:
        await provider.pull_list(client, target, include_unlisted=False)

    assert roles == [{"role": "membership_page"}]


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_exact_full_page_requires_empty_terminal_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 1)
    url = "https://acme.teamtailor.com/jobs.rss"
    respx.get(url, params={"offset": 0, "per_page": 1}).mock(
        return_value=httpx.Response(200, text=_rss(("101", "guid-101", "First")))
    )
    terminal = respx.get(url, params={"offset": 1, "per_page": 1}).mock(
        return_value=httpx.Response(200, text=_rss())
    )
    target = _target(
        TeamtailorProvider.parse_url_target, "https://acme.teamtailor.com/jobs"
    )

    async with build_async_client(_settings()) as client:
        listed = await TeamtailorProvider(_settings()).pull_list(
            client, target, include_unlisted=False
        )

    assert listed.membership.pages_fetched == 2
    assert terminal.call_count == 1


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("failure", ["duplicate", "repeat", "malformed"])
async def test_teamtailor_fails_closed_on_duplicate_repeat_or_malformed_pages(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 2)
    url = "https://acme.teamtailor.com/jobs.rss"
    first_page = _rss(
        ("101", "guid-101", "First"),
        ("102", "guid-102", "Second"),
    )
    if failure == "duplicate":
        second_page = _rss(("103", "guid-102", "Duplicate GUID"))
        message = "duplicate posting GUIDs"
    elif failure == "repeat":
        second_page = first_page
        message = "repeated RSS page"
    else:
        second_page = "<rss><not-channel /></rss>"
        message = "missing a channel"
    respx.get(url, params={"offset": 0, "per_page": 2}).mock(
        return_value=httpx.Response(200, text=first_page)
    )
    respx.get(url, params={"offset": 2, "per_page": 2}).mock(
        return_value=httpx.Response(200, text=second_page)
    )
    target = _target(
        TeamtailorProvider.parse_url_target, "https://acme.teamtailor.com/jobs"
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match=message):
            await TeamtailorProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_page_cap_fails_before_an_unbounded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 1)
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_MAX_PAGES", 2)
    url = "https://acme.teamtailor.com/jobs.rss"
    first = respx.get(url, params={"offset": 0, "per_page": 1}).mock(
        return_value=httpx.Response(200, text=_rss(("101", "guid-101", "First")))
    )
    second = respx.get(url, params={"offset": 1, "per_page": 1}).mock(
        return_value=httpx.Response(200, text=_rss(("102", "guid-102", "Second")))
    )
    target = _target(
        TeamtailorProvider.parse_url_target, "https://acme.teamtailor.com/jobs"
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="finite page budget"):
            await TeamtailorProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )

    assert first.call_count == 1
    assert second.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_rejects_title_only_membership_identity() -> None:
    respx.get(
        "https://acme.teamtailor.com/jobs.rss",
        params={"offset": 0, "per_page": 100},
    ).mock(
        return_value=httpx.Response(
            200,
            text="<rss><channel><item><title>Only a title</title></item></channel></rss>",
        )
    )
    target = _target(
        TeamtailorProvider.parse_url_target, "https://acme.teamtailor.com/jobs"
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="stable provider identity"):
            await TeamtailorProvider(_settings()).pull_list(
                client, target, include_unlisted=False
            )


def _catalog_board() -> BoardRecord:
    return BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )


def _catalog_route(provider_id: str, **updates: object) -> BoardProviderRecord:
    payload: dict[str, object] = {
        "id": f"manual:acme:{provider_id}",
        "source_key": "manual",
        "board_key": "manual:acme",
        "provider_id": provider_id,
        "support_level": ProviderSupport.JOBS,
        "token": "acme",
    }
    payload.update(updates)
    return BoardProviderRecord.model_validate(payload)


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_fetch_jobs_fails_closed_on_advertised_count() -> None:
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "true"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"jobs": [{"id": 1, "title": "Engineer"}], "meta": {"total": 2}},
        )
    )

    async with build_async_client(_settings()) as client:
        with pytest.raises(ValueError, match="advertised count"):
            await GreenhouseProvider(_settings()).fetch_jobs(
                client,
                _catalog_board(),
                _catalog_route("greenhouse"),
            )


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_fetch_jobs_rebinds_catalog_identity() -> None:
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "true"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                    }
                ]
            },
        )
    )

    async with build_async_client(_settings()) as client:
        result = await GreenhouseProvider(_settings()).fetch_jobs(
            client,
            _catalog_board(),
            _catalog_route("greenhouse"),
        )
        listed = await GreenhouseProvider(_settings()).pull_list(
            client,
            _target(GreenhouseProvider.parse_url_target, "https://boards.greenhouse.io/acme"),
            include_unlisted=False,
        )

    assert isinstance(result, JobFetchResult)
    assert result.authoritative is True
    assert result.jobs[0].board_key == "manual:acme"
    assert result.jobs[0].company == "Acme Corp"
    assert listed.postings[0].job.board_key == "acme"


@pytest.mark.asyncio
@respx.mock
async def test_lever_fetch_jobs_paginates_and_rebinds_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lever_module, "_LEVER_PAGE_SIZE", 2)
    list_url = "https://api.lever.co/v0/postings/acme"
    respx.get(
        list_url,
        params={"mode": "json", "skip": 0, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("a"), _lever_job("b")]))
    respx.get(
        list_url,
        params={"mode": "json", "skip": 2, "limit": 2},
    ).mock(return_value=httpx.Response(200, json=[_lever_job("c")]))

    async with build_async_client(_settings()) as client:
        result = await LeverProvider(_settings()).fetch_jobs(
            client,
            _catalog_board(),
            _catalog_route("lever"),
        )

    assert [job.remote_id for job in result] == ["a", "b", "c"]
    assert result.authoritative is True
    assert {job.board_key for job in result} == {"manual:acme"}
    assert {job.company for job in result} == {"Acme Corp"}


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_fetch_jobs_paginates_guid_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(teamtailor_module, "_TEAMTAILOR_PAGE_SIZE", 2)
    url = "https://acme.teamtailor.com/jobs.rss"
    respx.get(url, params={"offset": 0, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(
                ("101-engineer", "guid-not-the-url-tail-101", "First"),
                ("102-designer", "guid-not-the-url-tail-102", "Second"),
            ),
        )
    )
    respx.get(url, params={"offset": 2, "per_page": 2}).mock(
        return_value=httpx.Response(
            200,
            text=_rss(("103-writer", "guid-not-the-url-tail-103", "Third")),
        )
    )
    provider = TeamtailorProvider(_settings())
    board_target = _target(
        TeamtailorProvider.parse_url_target,
        "https://acme.teamtailor.com/jobs",
    )

    async with build_async_client(_settings()) as client:
        result = await provider.fetch_jobs(
            client,
            _catalog_board(),
            _catalog_route("teamtailor", host="acme.teamtailor.com", token="acme"),
        )
        listed = await provider.pull_list(client, board_target, include_unlisted=False)

    assert [job.remote_id for job in result] == [
        "guid-not-the-url-tail-101",
        "guid-not-the-url-tail-102",
        "guid-not-the-url-tail-103",
    ]
    assert result.authoritative is True
    assert {job.board_key for job in result} == {"manual:acme"}
    assert [posting.job.remote_id for posting in listed.postings] == [
        "101-engineer",
        "102-designer",
        "103-writer",
    ]
    assert listed.postings[0].job.board_key == "acme"
