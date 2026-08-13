from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.providers.boards import build_job_provider
from openopps.providers.boards.consider import ConsiderJobsProvider
from openopps.providers.base import JobFetchResult
from openopps.providers.consider import (
    ConsiderRouteMode,
    consider_search_payload,
    parse_consider_route,
    validate_consider_empty_board_html,
)
from openopps.providers.registry import provider_registry
from openopps.providers.sources.consider import ConsiderSourceAdapter
from openopps.route_probe import probe_routes
from openopps.route_select import route_request_key
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def board_record(**updates: object) -> BoardRecord:
    data: dict[str, object] = {
        "key": "manual:hugging-face",
        "source_key": "manual",
        "remote_id": "hugging-face",
        "remote_slug": "hugging-face",
        "name": "Hugging Face",
    }
    data.update(updates)
    return BoardRecord.model_validate(data)


def route_record(**updates: object) -> BoardProviderRecord:
    data: dict[str, object] = {
        "id": "manual:hugging-face:consider_jobs",
        "source_key": "manual",
        "board_key": "manual:hugging-face",
        "provider_id": "consider_jobs",
        "support_level": ProviderSupport.JOBS,
        "board_url": "https://consider.com/boards/co/hugging-face",
        "token": "hugging-face",
    }
    data.update(updates)
    return BoardProviderRecord.model_validate(data)


def job_payload(job_id: str = "job-1", **updates: object) -> dict[str, object]:
    data: dict[str, object] = {
        "jobId": job_id,
        "title": f"Engineer {job_id}",
        "companyName": "Hugging Face",
        "companySlug": "hugging-face",
        "locations": ["Remote"],
        "url": f"https://jobs.example.com/{job_id}",
        "applyUrl": f"https://apply.example.com/{job_id}",
        "timeStamp": "2026-07-17T00:00:00Z",
    }
    data.update(updates)
    return data


def jobs_response(
    jobs: list[dict[str, object]],
    *,
    sequence: object | None = None,
    total: int = 1,
    errors: list[object] | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {"size": 100}
    if sequence is not None:
        meta["sequence"] = sequence
    return {
        "jobs": jobs,
        "total": total,
        "meta": meta,
        "version": {"server": {"git": "abc"}},
        "errors": errors or [],
    }


def test_parse_consider_route_preserves_exact_tokens_and_modes():
    company = parse_consider_route("https://consider.com/boards/co/tem.")
    vc = parse_consider_route(
        "https://consider.com/boards/vc/market-one-capital/companies"
    )
    staging = parse_consider_route(
        "https://360-capital.board.staging.consider.com/companies"
    )
    custom = parse_consider_route(
        "https://jobs.example.com/companies", portfolio_board="q.ai"
    )

    assert (company.mode, company.token, company.endpoint) == (
        ConsiderRouteMode.COMPANY_JOBS,
        "tem.",
        "https://consider.com/api-boards/search-jobs",
    )
    assert (vc.mode, vc.token) == (
        ConsiderRouteMode.PORTFOLIO,
        "market-one-capital",
    )
    assert staging.token == "360-capital"
    assert custom.token == "q.ai"
    assert consider_search_payload(company, page_size=25) == {
        "query": {"parent": "tem."},
        "meta": {"size": 25},
        "board": {"id": "tem.", "isParent": False},
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://consider.com/boards/co/bad%",
        "https://consider.com/boards/co/bad%2Fslug",
        "https://consider.com/boards/co/bad%20slug",
        "https://consider.com/boards/co/acme/extra",
        "https://consider.com/boards/co/acme?preview=true",
        "https://consider.com/boards/vc/acme",
        "https://nested.slug.board.staging.consider.com/companies",
    ],
)
def test_parse_consider_route_rejects_ambiguous_or_unsafe_shapes(url: str):
    with pytest.raises(ValueError):
        parse_consider_route(url)


def test_registry_indexes_consider_jobs_separately_from_consider_source():
    registry = provider_registry()

    source = registry.get("consider")
    jobs = registry.get("consider_jobs")
    detected = registry.detect_url("https://consider.com/boards/co/q.ai")
    assert source is not None and source.kind == "board_source"
    assert jobs is not None and jobs.kind == "board_provider"
    assert build_job_provider("consider_jobs", OpenOppsSettings()) is not None
    assert detected is not None
    assert detected.provider_id == "consider_jobs"
    assert detected.token == "q.ai"


@pytest.mark.asyncio
async def test_company_source_emits_one_exact_consider_jobs_route_without_fetching():
    settings = OpenOppsSettings(cache_enabled=False)
    source = SourceRecord(
        key="tem",
        url="https://consider.com/boards/co/tem.",
        provider_id="consider",
        raw_metadata={"board": "incorrect-normalized-token"},
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in ConsiderSourceAdapter(settings).iter_boards(
                client, source, page_size=25
            )
        ]

    boards, routes, meta = pages[0]
    assert len(pages) == 1
    assert boards[0].remote_slug == "tem."
    assert routes[0].provider_id == "consider_jobs"
    assert routes[0].token == "tem."
    assert routes[0].board_url == source.url
    assert meta == {"mode": "company_jobs", "total": 1}


@pytest.mark.asyncio
@respx.mock
async def test_portfolio_source_buffers_pages_before_yielding_on_cursor_failure():
    settings = OpenOppsSettings(cache_enabled=False)
    source = SourceRecord(
        key="examplevc",
        url="https://consider.com/boards/vc/example.vc/companies",
        provider_id="consider",
    )
    endpoint = respx.post("https://consider.com/api-boards/search-companies").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "companies": [{"id": "one", "name": "One"}],
                    "total": 99,
                    "meta": {"size": 1, "sequence": "same"},
                },
            ),
            httpx.Response(
                200,
                json={
                    "companies": [{"id": "two", "name": "Two"}],
                    "total": 1,
                    "meta": {"size": 1, "sequence": "same"},
                },
            ),
        ]
    )

    async with build_async_client(settings) as client:
        iterator = ConsiderSourceAdapter(settings).iter_boards(
            client, source, page_size=1
        )
        with pytest.raises(ValueError, match="repeated a sequence"):
            await anext(iterator)

    assert endpoint.call_count == 2
    first_payload = json.loads(endpoint.calls[0].request.content)
    assert first_payload["board"] == {"id": "example.vc", "isParent": True}


@pytest.mark.asyncio
@respx.mock
async def test_consider_jobs_fetches_complete_advisory_total_and_normalizes():
    settings = OpenOppsSettings(cache_enabled=False)
    endpoint = respx.post("https://consider.com/api-boards/search-jobs").mock(
        side_effect=[
            httpx.Response(
                200,
                json=jobs_response(
                    [
                        job_payload(
                            hybrid=True,
                            remote=True,
                            departments=[{"label": "Platform"}],
                            salary={
                                "minValue": 100000,
                                "maxValue": 150000,
                                "currency": {"label": "USD", "value": "USD"},
                            },
                            url="http://unsafe.example.com/job-1",
                        )
                    ],
                    sequence="next",
                    total=200,
                ),
            ),
            httpx.Response(200, json=jobs_response([job_payload("job-2")], total=1)),
        ]
    )

    async with build_async_client(settings) as client:
        jobs = await ConsiderJobsProvider(settings).fetch_jobs(
            client, board_record(), route_record()
        )

    assert isinstance(jobs, JobFetchResult)
    assert endpoint.call_count == 2
    assert [job.remote_id for job in jobs] == ["job-1", "job-2"]
    assert jobs[0].remote == "Hybrid"
    assert jobs[0].workplace_type == "Hybrid"
    assert jobs[0].department == "Platform"
    assert jobs[0].salary == "USD 100000 - 150000"
    assert jobs[0].posting_url is None
    assert jobs[0].apply_url == "https://apply.example.com/job-1"
    assert jobs[0].employment_type is None
    second_payload = json.loads(endpoint.calls[1].request.content)
    assert second_payload["meta"]["sequence"] == "next"
    assert second_payload["board"]["isParent"] is False


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("responses", "error"),
    [
        ([jobs_response([], errors=[{"message": "bad"}])], "returned errors"),
        (
            [
                jobs_response([job_payload()], sequence="loop"),
                jobs_response([job_payload("job-2")], sequence="loop"),
            ],
            "repeated a sequence",
        ),
        ([jobs_response([], sequence="next")], "empty page with continuation"),
        (
            [jobs_response([{"title": "Missing id"}])],
            "validation error",
        ),
        (
            [
                jobs_response([job_payload()], sequence="next"),
                jobs_response([job_payload()]),
            ],
            "repeated a job",
        ),
    ],
)
async def test_consider_jobs_fails_whole_fetch_on_invalid_pagination(
    responses: list[dict[str, object]], error: str
):
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://consider.com/api-boards/search-jobs").mock(
        side_effect=[httpx.Response(200, json=response) for response in responses]
    )

    async with build_async_client(settings) as client:
        with pytest.raises((ValueError, Exception), match=error):
            await ConsiderJobsProvider(settings).fetch_jobs(
                client, board_record(), route_record()
            )


@pytest.mark.asyncio
@respx.mock
async def test_empty_consider_jobs_requires_specific_company_page():
    settings = OpenOppsSettings(cache_enabled=False)
    endpoint = respx.post("https://consider.com/api-boards/search-jobs")
    page = respx.get("https://consider.com/boards/co/hugging-face")
    endpoint.mock(return_value=httpx.Response(200, json=jobs_response([], total=0)))
    page.mock(return_value=httpx.Response(200, text="<title>Job Boards</title>"))

    async with build_async_client(settings) as client:
        with pytest.raises(ValueError, match="generic page"):
            await ConsiderJobsProvider(settings).fetch_jobs(
                client, board_record(), route_record()
            )

    page.mock(
        return_value=httpx.Response(
            200,
            text='<meta content="Jobs at Hugging Face | Consider" property="og:title">',
        )
    )
    async with build_async_client(settings) as client:
        result = await ConsiderJobsProvider(settings).fetch_jobs(
            client, board_record(), route_record()
        )
        assert isinstance(result, JobFetchResult)
        assert list(result) == []


def test_empty_consider_page_parser_uses_structured_titles():
    validate_consider_empty_board_html(
        "<html><head><title>Jobs at Acme | Consider</title></head></html>"
    )
    with pytest.raises(ValueError):
        validate_consider_empty_board_html("<title>Job Boards</title>")


def test_consider_route_request_key_preserves_punctuation():
    board = board_record(remote_id="q.ai", remote_slug="q.ai")
    by_url = route_record(
        board_key=board.key,
        board_url="https://consider.com/boards/co/q.ai",
        token=None,
    )
    by_token = route_record(board_key=board.key, board_url=None, token="q.ai")

    assert route_request_key(board, by_url) == "consider_jobs:token:q.ai"
    assert route_request_key(board, by_token) == "consider_jobs:token:q.ai"


@pytest.mark.asyncio
@respx.mock
async def test_route_probe_matches_exact_consider_jobs_token(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    source = SourceRecord(key="manual", url="manual://source", provider_id="manual")
    board = board_record(remote_id="q.ai", remote_slug="q.ai")
    route = route_record(
        board_key=board.key,
        board_url=None,
        token=None,
    )
    store.upsert_source(source)
    store.upsert_boards([board])
    store.upsert_board_providers([route])
    respx.post("https://consider.com/api-boards/search-jobs").mock(
        return_value=httpx.Response(200, json=jobs_response([job_payload()], total=7))
    )

    summary = await probe_routes(
        settings=settings,
        store=store,
        provider_id="consider_jobs",
        apply=True,
    )

    assert summary.checked == 1
    assert summary.matched[0].token == "q.ai"
    assert summary.matched[0].observed_jobs == 7
    persisted = store.list_board_providers(provider_id="consider_jobs")[0]
    assert persisted.token == "q.ai"
    assert persisted.board_url == "https://consider.com/boards/co/q.ai"
