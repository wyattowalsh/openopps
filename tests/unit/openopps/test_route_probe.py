import re
from pathlib import Path

import httpx
import pytest
import respx

from openopps.cache import HttpCache
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.route_registry import BoardRouteRegistry
from openopps.route_probe import probe_routes, token_candidates
from openopps.route_select import route_ready
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def board_record(**updates: object) -> BoardRecord:
    data: dict[str, object] = {
        "key": "acme",
        "source_key": "manual",
        "remote_id": "Acme",
        "remote_slug": "acme",
        "name": "Acme",
        "domain": "acme.com",
        "website_url": "https://acme.com/",
    }
    data.update(updates)
    return BoardRecord.model_validate(data)


def route_record(
    board_key: str = "acme", provider_id: str = "greenhouse"
) -> BoardProviderRecord:
    return BoardProviderRecord(
        id=f"manual:{board_key}:{provider_id}",
        source_key="manual",
        board_key=board_key,
        provider_id=provider_id,
        support_level=ProviderSupport.JOBS,
    )


def source_record(key: str = "manual") -> SourceRecord:
    return SourceRecord(key=key, url=f"{key}://source", provider_id=key)


def store_with_route(
    tmp_path: Path, board: BoardRecord, route: BoardProviderRecord
) -> tuple[OpenOppsSettings, OpenOppsStore]:
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}", provider_concurrency=2
    )
    store = OpenOppsStore(settings)
    store.upsert_source(source_record())
    store.upsert_boards([board])
    store.upsert_board_providers([route])
    return settings, store


def test_token_candidates_use_board_domain_and_suffixes():
    board = board_record(
        key="mercury-banking-for-startups",
        remote_id="Mercury Banking for Startups",
        remote_slug="mercury-banking-for-startups",
        name="Mercury",
        domain="mercury.com",
        website_url="https://mercury.com/",
    )

    candidates = token_candidates(board, max_candidates=20)

    assert "mercury-banking-for-startups" in candidates
    assert "mercury" in candidates


def test_token_candidates_strip_common_provider_noise():
    board = board_record(
        key="11x-ai",
        remote_id="11x.ai",
        remote_slug="11x-ai",
        name="11x.ai",
        domain="11x.ai",
    )

    assert "11x" in token_candidates(board, max_candidates=20)


def test_workday_route_ready_requires_complete_cxs_route():
    partial = route_record(provider_id="workday").model_copy(
        update={"host": "acme.wd1.myworkdayjobs.com"}
    )
    complete = partial.model_copy(update={"tenant": "acme", "site": "External"})

    assert not route_ready(partial)
    assert route_ready(complete)


def test_route_ready_accepts_new_provider_route_shapes():
    assert route_ready(
        route_record(provider_id="workable").model_copy(update={"token": "acme"})
    )
    assert route_ready(
        route_record(provider_id="teamtailor").model_copy(
            update={"host": "acme.teamtailor.com"}
        )
    )
    assert route_ready(
        route_record(provider_id="bamboohr").model_copy(
            update={"host": "acme.bamboohr.com", "tenant": "acme"}
        )
    )
    assert route_ready(
        route_record(provider_id="rippling").model_copy(update={"token": "acme"})
    )
    assert route_ready(
        route_record(provider_id="wpjobmanager").model_copy(
            update={"token": "https://acme.example.com"}
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_matches_greenhouse_and_persists(tmp_path: Path):
    settings, store = store_with_route(tmp_path, board_record(), route_record())
    respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*")
    ).mock(return_value=httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}))

    summary = await probe_routes(
        settings=settings, store=store, provider_id="greenhouse", apply=True
    )

    assert summary.checked == 1
    assert summary.selected_by_provider == {"greenhouse": 1}
    assert summary.matched_by_provider == {"greenhouse": 1}
    assert summary.matched[0].token == "acme"
    assert summary.matched[0].observed_jobs == 2
    persisted = store.list_board_providers(provider_id="greenhouse")[0]
    assert persisted.token == "acme"
    assert persisted.board_url == "https://boards.greenhouse.io/acme"
    assert persisted.last_status == "route_ready"
    registry = BoardRouteRegistry(store).select(
        provider_id="greenhouse", verified_only=True
    )
    assert len(registry.entries) == 1
    assert registry.entries[0].board.key == "acme"
    assert registry.entries[0].verified is True
    assert registry.entries[0].request_key == "greenhouse:token:acme"


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_uses_cached_greenhouse_response(tmp_path: Path):
    settings, store = store_with_route(tmp_path, board_record(), route_record())
    route = respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*")
    ).mock(return_value=httpx.Response(200, json={"jobs": [{"id": 1}]}))

    first = await probe_routes(settings=settings, store=store, provider_id="greenhouse")
    second = await probe_routes(
        settings=settings, store=store, provider_id="greenhouse"
    )

    assert first.matched[0].observed_jobs == 1
    assert second.matched[0].observed_jobs == 1
    assert route.call_count == 1
    assert settings.sqlite_path is not None
    assert HttpCache(settings.sqlite_path).status()["byNamespace"] == {"route_probe": 1}


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_refresh_bypasses_cached_response(tmp_path: Path):
    settings, store = store_with_route(tmp_path, board_record(), route_record())
    route = respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*")
    ).mock(
        side_effect=[
            httpx.Response(200, json={"jobs": [{"id": 1}]}),
            httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}),
        ]
    )

    first = await probe_routes(settings=settings, store=store, provider_id="greenhouse")
    refreshed = await probe_routes(
        settings=settings.model_copy(update={"cache_refresh": True}),
        store=store,
        provider_id="greenhouse",
    )

    assert first.matched[0].observed_jobs == 1
    assert refreshed.matched[0].observed_jobs == 2
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_dedupes_overlapping_source_boards(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}", provider_concurrency=2
    )
    store = OpenOppsStore(settings)
    store.upsert_source(source_record("source-a"))
    store.upsert_source(source_record("source-b"))
    store.upsert_boards(
        [
            board_record(
                key="source-a-acme",
                source_key="source-a",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
            board_record(
                key="source-b-acme",
                source_key="source-b",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            route_record(board_key="source-a-acme").model_copy(
                update={
                    "id": "source-a:source-a-acme:greenhouse",
                    "source_key": "source-a",
                }
            ),
            route_record(board_key="source-b-acme").model_copy(
                update={
                    "id": "source-b:source-b-acme:greenhouse",
                    "source_key": "source-b",
                }
            ),
        ]
    )
    respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/.+/jobs.*")
    ).mock(return_value=httpx.Response(404))

    summary = await probe_routes(
        settings=settings, store=store, provider_id="greenhouse"
    )

    assert summary.discovered == 2
    assert summary.duplicate_routes_skipped == 1
    assert summary.checked == 1


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_lists_unknown_candidates(tmp_path: Path):
    board = board_record(
        key="unknown-labs",
        remote_id="Unknown Labs",
        remote_slug="unknown-labs",
        name="Unknown Labs",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="unknown-labs", provider_id="lever")
    )
    respx.get(re.compile(r"https://api\.lever\.co/v0/postings/.+")).mock(
        return_value=httpx.Response(404)
    )

    summary = await probe_routes(
        settings=settings, store=store, provider_id="lever", max_candidates=4
    )

    assert summary.checked == 1
    assert summary.matched == []
    assert summary.unknown_by_reason == {"no_candidate_token_matched": 1}
    assert summary.unknown[0].reason == "no_candidate_token_matched"
    assert "unknown-labs" in summary.unknown[0].candidates


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_matches_ashby(tmp_path: Path):
    settings, store = store_with_route(
        tmp_path, board_record(), route_record(provider_id="ashbyhq")
    )
    respx.get(
        re.compile(r"https://api\.ashbyhq\.com/posting-api/job-board/acme.*")
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "apiVersion": "1",
                "jobs": [{"title": "Engineer"}, {"title": "Hidden", "isListed": False}],
            },
        )
    )

    summary = await probe_routes(
        settings=settings, store=store, provider_id="ashbyhq", apply=True
    )

    assert summary.checked == 1
    assert summary.matched_by_provider == {"ashbyhq": 1}
    assert summary.matched[0].token == "acme"
    assert summary.matched[0].observed_jobs == 1
    persisted = store.list_board_providers(provider_id="ashbyhq")[0]
    assert persisted.token == "acme"
    assert persisted.board_url == "https://jobs.ashbyhq.com/acme"


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_matches_new_public_board_providers(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        provider_concurrency=3,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(source_record())
    boards = [
        board_record(
            key="workable",
            remote_id="workable",
            remote_slug="workable",
            name="Workable",
            domain="workable.com",
            website_url="https://workable.com/",
        ),
        board_record(
            key="teamtailor",
            remote_id="teamtailor",
            remote_slug="teamtailor",
            name="Teamtailor",
            domain="teamtailor.com",
            website_url="https://teamtailor.com/",
        ),
        board_record(
            key="bamboohr",
            remote_id="bamboohr",
            remote_slug="bamboohr",
            name="BambooHR",
            domain="bamboohr.com",
            website_url="https://bamboohr.com/",
        ),
        board_record(
            key="rippling",
            remote_id="rippling",
            remote_slug="rippling",
            name="Rippling",
            domain="rippling.com",
            website_url="https://rippling.com/",
        ),
        board_record(
            key="wpjobmanager",
            remote_id="wpjobmanager",
            remote_slug="wpjobmanager",
            name="WP Job Manager",
            domain="jobs.example.com",
            website_url="https://jobs.example.com/wp-json/wp/v2/job-listings",
        ),
    ]
    store.upsert_boards(boards)
    store.upsert_board_providers(
        [
            route_record(board_key="workable", provider_id="workable"),
            route_record(board_key="teamtailor", provider_id="teamtailor"),
            route_record(board_key="bamboohr", provider_id="bamboohr"),
            route_record(board_key="rippling", provider_id="rippling"),
            route_record(board_key="wpjobmanager", provider_id="wpjobmanager"),
        ]
    )
    respx.post("https://apply.workable.com/api/v3/accounts/workable/jobs").mock(
        return_value=httpx.Response(
            200, json={"total": 1, "results": [{"shortcode": "eng"}]}
        )
    )
    respx.get("https://teamtailor.teamtailor.com/jobs.rss").mock(
        return_value=httpx.Response(
            200,
            text="<rss><channel><item><title>Engineer</title></item></channel></rss>",
        )
    )
    respx.get("https://bamboohr.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json={"meta": {"totalCount": 2}, "result": []})
    )
    respx.get("https://ats.rippling.com/api/v2/board/rippling/jobs").mock(
        return_value=httpx.Response(200, json={"totalItems": 3, "items": [{}]})
    )
    respx.get("https://jobs.example.com/wp-json/wp/v2/job-listings").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )

    summary = await probe_routes(settings=settings, store=store, apply=True)

    assert summary.checked == 5
    assert summary.matched_by_provider == {
        "bamboohr": 1,
        "rippling": 1,
        "teamtailor": 1,
        "workable": 1,
        "wpjobmanager": 1,
    }
    persisted = {route.provider_id: route for route in store.list_board_providers()}
    assert persisted["workable"].board_url == "https://apply.workable.com/workable"
    assert persisted["teamtailor"].host == "teamtailor.teamtailor.com"
    assert persisted["bamboohr"].tenant == "bamboohr"
    assert persisted["rippling"].host == "ats.rippling.com"
    assert persisted["wpjobmanager"].board_url == (
        "https://jobs.example.com/wp-json/wp/v2/job-listings"
    )
    assert persisted["wpjobmanager"].token == "https://jobs.example.com"


@pytest.mark.asyncio
async def test_wpjobmanager_probe_requires_explicit_rest_endpoint(tmp_path: Path):
    board = board_record(
        key="wordpress",
        remote_slug="wordpress",
        name="WordPress Site",
        website_url="https://jobs.example.com/careers",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="wordpress", provider_id="wpjobmanager")
    )

    summary = await probe_routes(
        settings=settings, store=store, provider_id="wpjobmanager"
    )

    assert summary.checked == 1
    assert summary.matched == []
    assert summary.unknown[0].reason == "needs_explicit_wpjobmanager_endpoint"
    assert summary.unknown[0].candidates == []


@pytest.mark.asyncio
@respx.mock
async def test_wpjobmanager_probe_accepts_explicit_ajax_endpoint(tmp_path: Path):
    board = board_record(
        key="wordpress",
        remote_id="wordpress",
        remote_slug="wordpress",
        name="WordPress Site",
        website_url="https://jobs.example.com/jm-ajax/get_listings/",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="wordpress", provider_id="wpjobmanager")
    )
    respx.get("https://jobs.example.com/jm-ajax/get_listings/").mock(
        return_value=httpx.Response(
            200,
            json={
                "found_jobs": True,
                "html": '<li class="job_listing"><a href="https://jobs.example.com/job/1">Engineer</a></li>',
            },
        )
    )

    summary = await probe_routes(
        settings=settings, store=store, provider_id="wpjobmanager", apply=True
    )

    assert summary.checked == 1
    assert summary.matched_by_provider == {"wpjobmanager": 1}
    assert (
        summary.matched[0].board_url == "https://jobs.example.com/jm-ajax/get_listings/"
    )
    persisted = store.list_board_providers(provider_id="wpjobmanager")[0]
    assert persisted.board_url == "https://jobs.example.com/jm-ajax/get_listings/"
    assert persisted.token == "https://jobs.example.com"


@pytest.mark.asyncio
async def test_workday_probe_reports_incomplete_public_url(tmp_path: Path):
    board = board_record(
        key="acme-workday",
        remote_id="Acme Workday",
        remote_slug="acme-workday",
        name="Acme Workday",
        website_url="https://acme.wd1.myworkdayjobs.com/",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="acme-workday", provider_id="workday")
    )

    summary = await probe_routes(settings=settings, store=store, provider_id="workday")

    assert summary.checked == 1
    assert summary.unknown[0].reason == "needs_public_workday_board_url"
    assert summary.unknown[0].candidates == ["https://acme.wd1.myworkdayjobs.com/"]


@pytest.mark.asyncio
async def test_workday_probe_rejects_deceptive_host(tmp_path: Path):
    board = board_record(
        key="acme-workday",
        remote_id="Acme Workday",
        remote_slug="acme-workday",
        name="Acme Workday",
        website_url="https://myworkdayjobs.com.evil.example/External",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="acme-workday", provider_id="workday")
    )

    summary = await probe_routes(settings=settings, store=store, provider_id="workday")

    assert summary.checked == 1
    assert summary.unknown[0].reason == "needs_public_workday_board_url"
    assert summary.unknown[0].candidates == []


@pytest.mark.asyncio
@respx.mock
async def test_probe_routes_matches_workday_and_persists(tmp_path: Path):
    board = board_record(
        key="acme-workday",
        remote_id="Acme Workday",
        remote_slug="acme-workday",
        name="Acme Workday",
        website_url="https://acme.wd1.myworkdayjobs.com/External",
    )
    settings, store = store_with_route(
        tmp_path, board, route_record(board_key="acme-workday", provider_id="workday")
    )
    respx.post("https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/jobs").mock(
        return_value=httpx.Response(200, json={"total": 2, "jobPostings": [{}]})
    )

    summary = await probe_routes(
        settings=settings, store=store, provider_id="workday", apply=True
    )

    assert summary.matched_by_provider == {"workday": 1}
    assert summary.matched[0].host == "acme.wd1.myworkdayjobs.com"
    assert summary.matched[0].tenant == "acme"
    assert summary.matched[0].site == "External"
    persisted = store.list_board_providers(provider_id="workday")[0]
    assert persisted.host == "acme.wd1.myworkdayjobs.com"
    assert persisted.tenant == "acme"
    assert persisted.site == "External"
