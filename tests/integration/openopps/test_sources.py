import json

import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import SourceRecord
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.providers.sources.consider import (
    A16Z_SOURCE,
    CONSIDER_SOURCE_CATALOG,
    ConsiderA16zSourceAdapter,
)
from openopps.providers.sources.getro import GETRO_SOURCE_CATALOG, GetroSourceAdapter
from openopps.providers.sources.special import (
    PEAR_VC_SOURCE,
    SOUTHPARKCOMMONS_SOURCE,
    VENTURE_CAPITAL_CAREERS_SOURCE,
    VENTURE_LOOP_SOURCE,
    WORKABLE_1871_SOURCE,
    YCOMBINATOR_SOURCE,
    AshbySourceAdapter,
    PublicPageSourceAdapter,
    SouthParkCommonsSourceAdapter,
    VentureCapitalCareersSourceAdapter,
    VentureLoopSourceAdapter,
    WorkableSourceAdapter,
    YCombinatorSourceAdapter,
)
from openopps.settings import OpenOppsSettings


@pytest.mark.asyncio
@respx.mock
async def test_consider_a16z_normalizes_boards_and_provider_hints():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://jobs.a16z.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "Fivetran",
                        "slug": "fivetran",
                        "name": "Fivetran",
                        "domain": "fivetran.com",
                        "numJobs": 131,
                        "jobSources": [
                            {"id": "greenhouse", "label": "Greenhouse", "count": 131}
                        ],
                        "website": {"url": "http://fivetran.com/"},
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
                "version": {"server": {"git": "abc"}},
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in ConsiderA16zSourceAdapter(settings).iter_boards(
                client, A16Z_SOURCE, page_size=1
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "a16z:fivetran"
    assert boards[0].website_url == "https://fivetran.com/"
    assert boards[0].num_jobs_hint == 131
    assert providers[0].provider_id == "greenhouse"
    assert providers[0].support_level == "jobs"
    assert meta["version"]["server"]["git"] == "abc"


@pytest.mark.asyncio
@respx.mock
async def test_consider_source_preserves_unknown_provider_hints_as_detect_only():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://jobs.a16z.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "Acme",
                        "slug": "acme",
                        "name": "Acme",
                        "numJobs": 3,
                        "jobSources": [
                            {
                                "id": "smartrecruiters",
                                "label": "SmartRecruiters",
                                "count": 3,
                            }
                        ],
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in ConsiderA16zSourceAdapter(settings).iter_boards(
                client, A16Z_SOURCE, page_size=1
            )
        ]

    _boards, providers, _meta = pages[0]
    assert providers[0].provider_id == "smartrecruiters"
    assert providers[0].support_level == "detect"


@pytest.mark.asyncio
@respx.mock
async def test_getro_normalizes_company_boards():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://api.getro.com/api/v2/collections/8672/search/companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "count": 2,
                    "companies": [
                        {
                            "id": 202755,
                            "slug": "100ms-2",
                            "name": "100ms",
                            "domain": "100ms.live",
                            "activeJobsCount": 10,
                            "headCount": 2,
                            "locations": [
                                "San Francisco, CA, USA",
                                "Bengaluru, Karnataka, India",
                            ],
                            "visibleIndustryTags": ["Software"],
                            "description": "Live video infrastructure.",
                        },
                        {
                            "id": 202756,
                            "slug": "media-co",
                            "name": "Media Co",
                            "domain": '[\n\t"Entertainment",\n\t"Broadcast Media"\n]',
                            "activeJobsCount": 2,
                            "visibleIndustryTags": [
                                "Entertainment",
                                "Broadcast Media",
                            ],
                        },
                    ],
                }
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in GetroSourceAdapter(settings).iter_boards(
                client, GETRO_SOURCE_CATALOG["accel"], page_size=12
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "accel:100ms-2"
    assert boards[0].name == "100ms"
    assert boards[0].domain == "100ms.live"
    assert boards[0].website_url == "https://100ms.live"
    assert boards[0].num_jobs_hint == 10
    assert boards[0].markets == ["Software"]
    assert boards[1].key == "accel:media-co"
    assert boards[1].domain is None
    assert boards[1].website_url is None
    assert boards[1].markets == ["Entertainment", "Broadcast Media"]
    assert providers == []
    assert meta["total"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_getro_falls_back_to_embedded_initial_state():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://api.getro.com/api/v2/collections/8672/search/companies").mock(
        return_value=httpx.Response(403, json={"errors": [{"title": "blocked"}]})
    )
    respx.get("https://jobs.accel.com/companies").mock(
        return_value=httpx.Response(
            200,
            text=(
                '<script id="__NEXT_DATA__" type="application/json">'
                '{"props":{"pageProps":{"initialState":{"companies":{"total":581,"found":['
                '{"id":202755,"slug":"100ms-2","name":"100ms","domain":"100ms.live","activeJobsCount":10}'
                "]}}}}}</script>"
            ),
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in GetroSourceAdapter(settings).iter_boards(
                client, GETRO_SOURCE_CATALOG["accel"], page_size=12
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "accel:100ms-2"
    assert providers == []
    assert meta["total"] == 581
    assert meta["partial"] is True


@pytest.mark.asyncio
@respx.mock
async def test_getro_follows_redirects_when_discovering_collection_id():
    settings = OpenOppsSettings(cache_enabled=False)
    source = GETRO_SOURCE_CATALOG["accel"].model_copy(
        update={"url": "https://jobs.example.com/", "raw_metadata": {}}
    )
    respx.get("https://jobs.example.com/").mock(
        return_value=httpx.Response(
            302, headers={"location": "https://jobs.example.com/companies"}
        )
    )
    respx.get("https://jobs.example.com/companies").mock(
        return_value=httpx.Response(200, text='{"id":"8672","label":"Companies"}')
    )
    respx.post("https://api.getro.com/api/v2/collections/8672/search/companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "count": 1,
                    "companies": [
                        {
                            "id": 202755,
                            "slug": "100ms-2",
                            "name": "100ms",
                            "domain": "100ms.live",
                            "activeJobsCount": 10,
                        }
                    ],
                }
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in GetroSourceAdapter(settings).iter_boards(
                client, source, page_size=12
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "accel:100ms-2"
    assert providers == []
    assert meta["collectionId"] == "8672"


@pytest.mark.asyncio
@respx.mock
async def test_getro_rediscover_collection_id_when_metadata_is_not_digits():
    settings = OpenOppsSettings(cache_enabled=False)
    source = GETRO_SOURCE_CATALOG["accel"].model_copy(
        update={"raw_metadata": {"collectionId": "accel"}}
    )
    landing = respx.get("https://jobs.accel.com/companies").mock(
        return_value=httpx.Response(200, text='{"id":"8672","label":"Companies"}')
    )
    respx.post("https://api.getro.com/api/v2/collections/8672/search/companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "count": 1,
                    "companies": [
                        {
                            "id": 202755,
                            "slug": "100ms-2",
                            "name": "100ms",
                            "domain": "100ms.live",
                            "activeJobsCount": 10,
                        }
                    ],
                }
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in GetroSourceAdapter(settings).iter_boards(
                client, source, page_size=12
            )
        ]

    boards, providers, meta = pages[0]
    assert landing.call_count == 1
    assert boards[0].key == "accel:100ms-2"
    assert providers == []
    assert meta["collectionId"] == "8672"


@pytest.mark.asyncio
@respx.mock
async def test_consider_generic_source_uses_source_host_and_board_id():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://jobs.lsvp.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "Anduril Industries",
                        "slug": "anduril-industries",
                        "name": "Anduril Industries",
                        "domain": "anduril.com",
                        "numJobs": 10,
                        "jobSources": [
                            {"id": "ashbyhq", "label": "Ashby", "count": 10}
                        ],
                        "website": {"url": ""},
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in ConsiderA16zSourceAdapter(settings).iter_boards(
                client, CONSIDER_SOURCE_CATALOG["lsvp"], page_size=1
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "lsvp:anduril-industries"
    assert boards[0].website_url is None
    assert providers[0].provider_id == "ashbyhq"
    assert providers[0].support_level == "jobs"
    assert meta["total"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_ycombinator_fetches_algolia_batches():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://www.ycombinator.com/companies").mock(
        return_value=httpx.Response(
            200,
            text='window.AlgoliaOpts = {"app":"45BWZJ1SGC","key":"search-key"}',
        )
    )
    respx.post("https://45bwzj1sgc-dsn.algolia.net/1/indexes/*/queries").mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [{"hits": [], "facets": {"batch": {"S24": 2}}}]}
            ),
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "hits": [
                                {
                                    "id": 1,
                                    "name": "Acme AI",
                                    "slug": "acme-ai",
                                    "website": "https://acme.example",
                                    "one_liner": "AI for testing.",
                                    "team_size": 12,
                                    "batch": "S24",
                                    "industries": ["B2B", "Artificial Intelligence"],
                                    "all_locations": "San Francisco; Remote",
                                },
                                {
                                    "id": 2,
                                    "name": "Blank Fields AI",
                                    "slug": "blank-fields-ai",
                                    "website": "",
                                    "one_liner": "Has sparse YC data.",
                                    "team_size": 3,
                                    "batch": "S24",
                                    "industries": ["B2B"],
                                    "all_locations": "",
                                    "regions": ["Remote"],
                                },
                            ]
                        }
                    ]
                },
            ),
        ]
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in YCombinatorSourceAdapter(settings).iter_boards(
                client, YCOMBINATOR_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "yc:acme-ai"
    assert boards[0].domain == "acme.example"
    assert boards[0].markets == ["B2B", "Artificial Intelligence"]
    assert boards[0].locations == ["San Francisco", "Remote"]
    assert boards[0].staff_count == 12
    assert boards[1].website_url is None
    assert boards[1].locations == ["Remote"]
    assert providers == []
    assert meta["batch"] == "S24"


@pytest.mark.asyncio
@respx.mock
async def test_southparkcommons_normalizes_embedded_jobs_data():
    settings = OpenOppsSettings(cache_enabled=False)
    jobs = [
        {
            "id": "acme.com|https://job-boards.greenhouse.io/acme/jobs/1",
            "companyDomain": "acme.com",
            "companyName": "Acme",
            "companySlug": "acme",
            "companyBio": "Builds test tools.",
            "title": "Engineer",
            "url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "locations": ["Remote"],
            "industry": "B2B",
        },
        {
            "id": "acme.com|https://jobs.lever.co/acme/2",
            "companyDomain": "acme.com",
            "companyName": "Acme",
            "companySlug": "acme",
            "title": "Designer",
            "url": "https://jobs.lever.co/acme/2",
            "locations": ["New York"],
            "industry": "B2B",
        },
        {
            "id": "beta.com|https://jobs.ashbyhq.com/beta/3",
            "companyDomain": "beta.com",
            "companyName": "Beta",
            "companySlug": "beta",
            "title": "PM",
            "url": "https://jobs.ashbyhq.com/beta/3",
            "locations": ["San Francisco"],
            "industry": "Consumer",
        },
    ]
    respx.get("https://www.southparkcommons.com/jobs").mock(
        return_value=httpx.Response(
            200,
            text=(
                '<script type="application/json" id="jobs-data">'
                f"{json.dumps(jobs)}"
                "</script>"
            ),
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in SouthParkCommonsSourceAdapter(settings).iter_boards(
                client, SOUTHPARKCOMMONS_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert [board.key for board in boards] == [
        "southparkcommons:acme",
        "southparkcommons:beta",
    ]
    assert boards[0].num_jobs_hint == 2
    assert boards[0].locations == ["Remote", "New York"]
    provider_map = {
        (provider.board_key, provider.provider_id): provider for provider in providers
    }
    assert provider_map[("southparkcommons:acme", "greenhouse")].token == "acme"
    assert provider_map[("southparkcommons:acme", "greenhouse")].count_hint == 1
    assert provider_map[("southparkcommons:acme", "greenhouse")].board_url == (
        "https://boards.greenhouse.io/acme"
    )
    assert provider_map[("southparkcommons:acme", "lever")].token == "acme"
    assert provider_map[("southparkcommons:beta", "ashbyhq")].token == "beta"
    assert meta == {"jobs": 3, "total": 2}


@pytest.mark.asyncio
@respx.mock
async def test_ashby_source_emits_board_and_provider_route():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/Pear-VC?includeCompensation=false"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "apiVersion": "1",
                "jobs": [
                    {
                        "id": "job-1",
                        "title": "Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/Pear-VC/job-1",
                        "isListed": True,
                    },
                    {
                        "id": "job-2",
                        "title": "Hidden Role",
                        "jobUrl": "https://jobs.ashbyhq.com/Pear-VC/job-2",
                        "isListed": False,
                    },
                ],
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in AshbySourceAdapter(settings).iter_boards(
                client, PEAR_VC_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "pearvc:pear-vc"
    assert boards[0].name == "Pear VC"
    assert boards[0].num_jobs_hint == 1
    assert boards[0].raw_payload["token"] == "Pear-VC"
    assert providers[0].provider_id == "ashbyhq"
    assert providers[0].support_level == "jobs"
    assert providers[0].count_hint == 1
    assert providers[0].board_url == "https://jobs.ashbyhq.com/Pear-VC"
    assert providers[0].token == "Pear-VC"
    assert meta == {"apiVersion": "1", "token": "Pear-VC", "total": 1}


@pytest.mark.asyncio
@respx.mock
async def test_venturecapitalcareers_normalizes_company_cards():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://venturecapitalcareers.com/companies").mock(
        return_value=httpx.Response(
            200,
            text=(
                '<div><div class="inline-flex">80 jobs</div></div>'
                '<a href="/companies/cvx-ventures">'
                '<h3 class="font-heading">CVX Ventures</h3></a>'
                '<p data-slot="text">We invest in venture and growth opportunities.</p>'
                '<div><div class="inline-flex">13 jobs</div></div>'
                '<a href="/companies/iconiq-growth">'
                '<h3 class="font-heading">ICONIQ Capital</h3></a>'
                '<p data-slot="text">A global investment firm.</p>'
            ),
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in VentureCapitalCareersSourceAdapter(settings).iter_boards(
                client, VENTURE_CAPITAL_CAREERS_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert [board.key for board in boards] == [
        "venturecapitalcareers:cvx-ventures",
        "venturecapitalcareers:iconiq-growth",
    ]
    assert boards[0].name == "CVX Ventures"
    assert boards[0].description == "We invest in venture and growth opportunities."
    assert boards[0].num_jobs_hint == 80
    assert boards[0].raw_payload["profileUrl"] == (
        "https://venturecapitalcareers.com/companies/cvx-ventures"
    )
    assert providers == []
    assert meta["pageSize"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_ventureloop_source_preserves_landing_page_without_scraping_search():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://www.ventureloop.com/").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://www.ventureloop.com/ventureloop/home.php"},
        )
    )
    landing = respx.get("https://www.ventureloop.com/ventureloop/home.php").mock(
        return_value=httpx.Response(200, text="<title>VentureLoop</title>")
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in VentureLoopSourceAdapter(settings).iter_boards(
                client, VENTURE_LOOP_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert boards == []
    assert providers == []
    assert landing.call_count == 1
    assert meta["sourceUrl"].endswith("/ventureloop/home.php")
    assert meta["total"] == 0
    assert "does not expose company records" in meta["note"]


@pytest.mark.asyncio
@respx.mock
async def test_workable_source_adapter_normalizes_board():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://apply.workable.com/api/v3/accounts/1871/jobs").mock(
        return_value=httpx.Response(200, json={"results": [], "total": 0})
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in WorkableSourceAdapter(settings).iter_boards(
                client, WORKABLE_1871_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert len(boards) == 1
    assert boards[0].name == "1871"
    assert boards[0].num_jobs_hint == 0
    assert providers[0].provider_id == "workable"
    assert meta["total"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_workable_source_adapter_extracts_token_from_api_url():
    settings = OpenOppsSettings(cache_enabled=False)
    source = SourceRecord(
        key="workable-api",
        url="https://apply.workable.com/api/v3/accounts/acme/jobs",
        provider_id="workable_source",
    )
    respx.post("https://apply.workable.com/api/v3/accounts/acme/jobs").mock(
        return_value=httpx.Response(200, json={"results": [], "total": 0})
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in WorkableSourceAdapter(settings).iter_boards(
                client, source, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].remote_id == "acme"
    assert providers[0].token == "acme"
    assert meta["token"] == "acme"


@pytest.mark.asyncio
@respx.mock
async def test_public_page_source_adapter_extracts_links_and_provider_routes():
    settings = OpenOppsSettings(cache_enabled=False)
    src = BOARD_SOURCE_CATALOG["twobearcapital"]
    respx.get("https://jobs.twobearcapital.com/companies").mock(
        return_value=httpx.Response(
            200,
            text="""
            <html><body>
              <a href="https://acme.example">Acme Robotics</a>
              <a href="https://jobs.lever.co/exampleco">View jobs</a>
              <a href="https://linkedin.com/company/acme">LinkedIn</a>
            </body></html>
            """,
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in PublicPageSourceAdapter(settings).iter_boards(
                client, src, page_size=50
            )
        ]

    boards, providers, meta = pages[0]
    assert {board.name for board in boards} == {"Acme Robotics", "Exampleco"}
    assert providers[0].provider_id == "lever"
    assert providers[0].support_level == "jobs"
    assert "Best-effort public page extraction" in meta["note"]
    assert meta["sourceUrl"].endswith("twobearcapital.com/companies")
