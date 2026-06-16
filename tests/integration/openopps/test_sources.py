import json

import httpx
import pytest
import respx

from openopps.http import build_async_client
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


def test_source_catalog_includes_requested_portfolio_boards():
    expected = {
        "8vc": ("getro", "https://jobs.8vc.com/companies", "collectionId", "1005"),
        "1011vc": (
            "getro",
            "https://jobs.1011vc.com/companies",
            "collectionId",
            "1488",
        ),
        "5amventures": (
            "consider",
            "https://jobs.5amventures.com/companies",
            "board",
            "5am-ventures",
        ),
        "645ventures": (
            "getro",
            "https://jobs.645ventures.com/companies",
            "collectionId",
            "1621",
        ),
        "airtree": (
            "getro",
            "https://jobs.airtree.vc/companies",
            "collectionId",
            "7418",
        ),
        "aixventures": (
            "consider",
            "https://careers.aixventures.com/companies",
            "board",
            "aix-ventures",
        ),
        "alter": (
            "consider",
            "https://careers.alter.vc/companies",
            "board",
            "alter-global",
        ),
        "alleycorp": (
            "getro",
            "https://jobs.alleycorp.com/companies",
            "collectionId",
            "636",
        ),
        "amplifypartners": (
            "consider",
            "https://talent.amplifypartners.com/companies",
            "board",
            "amplify-partners",
        ),
        "antler": (
            "getro",
            "https://careers.antler.co/companies",
            "collectionId",
            "7715",
        ),
        "anthemis": (
            "consider",
            "https://jobs.anthemis.com/companies",
            "board",
            "anthemis-group",
        ),
        "atomico": (
            "getro",
            "https://careers.atomico.com/companies",
            "collectionId",
            "36986",
        ),
        "baincapitalventures": (
            "consider",
            "https://jobs.baincapitalventures.com/companies",
            "board",
            "bain-ventures",
        ),
        "balderton": (
            "consider",
            "https://careers.balderton.com/companies",
            "board",
            "balderton-capital",
        ),
        "battery": (
            "consider",
            "https://jobs.battery.com/companies",
            "board",
            "battery-ventures",
        ),
        "canaan": (
            "getro",
            "https://careers.canaan.com/companies",
            "collectionId",
            "1419",
        ),
        "climatedraft": (
            "getro",
            "https://jobs.climatedraft.org/companies",
            "collectionId",
            "994",
        ),
        "bcapital": (
            "getro",
            "https://jobs.b.capital/companies",
            "collectionId",
            "515",
        ),
        "blackbird": (
            "getro",
            "https://jobs.blackbird.vc/companies",
            "collectionId",
            "219",
        ),
        "bbgventures": (
            "getro",
            "https://jobs.bbgventures.com/companies",
            "collectionId",
            "766",
        ),
        "blumbergcapital": (
            "getro",
            "https://careers.blumbergcapital.com/companies",
            "collectionId",
            "34577",
        ),
        "blockchaincapital": (
            "getro",
            "https://jobs.blockchaincapital.com/companies",
            "collectionId",
            "815",
        ),
        "bonfirevc": (
            "getro",
            "https://jobs.bonfirevc.com/companies",
            "collectionId",
            "790",
        ),
        "btv": ("getro", "https://jobs.btv.vc/companies", "collectionId", "1637"),
        "costanoavc": (
            "consider",
            "https://jobs.costanoavc.com/companies",
            "board",
            "costanoa-ventures",
        ),
        "contrary": (
            "consider",
            "https://jobs.contrary.com/companies",
            "board",
            "contrary",
        ),
        "conversioncapital": (
            "consider",
            "https://jobs.conversioncapital.com/companies",
            "board",
            "conversion-capital",
        ),
        "crv": ("consider", "https://jobs.crv.com/companies", "board", "crv"),
        "craftventures": (
            "getro",
            "https://jobs.craftventures.com/companies",
            "collectionId",
            "340",
        ),
        "creandum": (
            "consider",
            "https://careers.creandum.com/companies",
            "board",
            "creandum",
        ),
        "dcvc": ("getro", "https://jobs.dcvc.com/companies", "collectionId", "514"),
        "dcg": ("getro", "https://jobs.dcg.co/companies", "collectionId", "116"),
        "designerfund": (
            "getro",
            "https://jobs.designerfund.com/companies",
            "collectionId",
            "11511",
        ),
        "drivecapital": (
            "getro",
            "https://jobs.drivecapital.com/companies",
            "collectionId",
            "158",
        ),
        "eclipse": (
            "getro",
            "https://jobs.eclipse.capital/companies",
            "collectionId",
            "348",
        ),
        "everywhere": (
            "getro",
            "https://jobs.everywhere.vc/companies",
            "collectionId",
            "625",
        ),
        "earlybird": (
            "getro",
            "https://jobs.earlybird.com/companies",
            "collectionId",
            "617",
        ),
        "felicis": (
            "consider",
            "https://jobs.felicis.com/companies",
            "board",
            "felicis",
        ),
        "fincapital": (
            "consider",
            "https://jobs.fin.capital/companies",
            "board",
            "fin-capital",
        ),
        "fiftyyears": (
            "consider",
            "https://jobs.fiftyyears.com/companies",
            "board",
            "fifty-years",
        ),
        "firstmark": (
            "getro",
            "https://jobs.firstmark.com/companies",
            "collectionId",
            "45303",
        ),
        "femalefoundersfund": (
            "getro",
            "https://jobs.femalefoundersfund.com/companies",
            "collectionId",
            "183",
        ),
        "flarecapital": (
            "getro",
            "https://careers.flarecapital.com/companies",
            "collectionId",
            "9366",
        ),
        "foundationcapital": (
            "getro",
            "https://jobs.foundationcapital.com/companies",
            "collectionId",
            "941",
        ),
        "foundry": (
            "getro",
            "https://jobs.foundry.vc/companies",
            "collectionId",
            "25",
        ),
        "freestyle": (
            "getro",
            "https://jobs.freestyle.vc/companies",
            "collectionId",
            "108",
        ),
        "forerunnerventures": (
            "consider",
            "https://jobs.forerunnerventures.com/companies",
            "board",
            "forerunner-ventures",
        ),
        "hardyaka": (
            "consider",
            "https://jobs.hardyaka.com/companies",
            "board",
            "hard-yaka",
        ),
        "fprimecapital": (
            "getro",
            "https://jobs.fprimecapital.com/companies",
            "collectionId",
            "258",
        ),
        "indexventures": (
            "getro",
            "https://indexventures.getro.com/companies",
            "collectionId",
            "1629",
        ),
        "hvcapital": (
            "getro",
            "https://hv.getro.com/companies",
            "collectionId",
            "234",
        ),
        "gv": ("consider", "https://jobs.gv.com/companies", "board", "gv"),
        "goldenventures": (
            "consider",
            "https://jobs.golden.ventures/companies",
            "board",
            "golden-ventures",
        ),
        "greycroft": (
            "getro",
            "https://jobs.greycroft.com/companies",
            "collectionId",
            "616",
        ),
        "insightpartners": (
            "getro",
            "https://jobs.insightpartners.com/companies",
            "collectionId",
            "246",
        ),
        "inovia": (
            "getro",
            "https://careers.inovia.vc/companies",
            "collectionId",
            "1201",
        ),
        "ivp": ("consider", "https://careers.ivp.com/companies", "board", "ivp"),
        "inspiredcapital": (
            "getro",
            "https://jobs.inspiredcapital.com/companies",
            "collectionId",
            "935",
        ),
        "initialized": (
            "consider",
            "https://jobs.initialized.com/companies",
            "board",
            "initialized",
        ),
        "iconventures": (
            "consider",
            "https://jobs.iconventures.com/companies",
            "board",
            "icon-ventures",
        ),
        "illuminatefinancial": (
            "consider",
            "https://jobs.illuminatefinancial.com/companies",
            "board",
            "illuminate-financial",
        ),
        "joinef": (
            "getro",
            "https://portfolio.joinef.com/companies",
            "collectionId",
            "228",
        ),
        "kaporcapital": (
            "getro",
            "https://jobs.kaporcapital.com/companies",
            "collectionId",
            "224",
        ),
        "khoslaventures": (
            "getro",
            "https://jobs.khoslaventures.com/companies",
            "collectionId",
            "257",
        ),
        "kindredcapital": (
            "getro",
            "https://jobs.kindredcapital.vc/companies",
            "collectionId",
            "221",
        ),
        "lererhippeau": (
            "getro",
            "https://jobs.lererhippeau.com/companies",
            "collectionId",
            "120",
        ),
        "linkventures": (
            "consider",
            "https://jobs.linkventures.com/companies",
            "board",
            "link-ventures",
        ),
        "lowercarbon": (
            "getro",
            "https://lowercarbon.getro.com/companies",
            "collectionId",
            "801",
        ),
        "leftlanecap": (
            "getro",
            "https://jobs.leftlanecap.com/companies",
            "collectionId",
            "789",
        ),
        "luxcapital": (
            "getro",
            "https://jobs.luxcapital.com/companies",
            "collectionId",
            "103",
        ),
        "madrona": (
            "getro",
            "https://jobs.madrona.com/companies",
            "collectionId",
            "151",
        ),
        "m13": ("getro", "https://jobs.m13.co/companies", "collectionId", "318"),
        "mayfield": (
            "getro",
            "https://mayfield.getro.com/companies",
            "collectionId",
            "245",
        ),
        "mcj": ("getro", "https://jobs.mcj.vc/companies", "collectionId", "1775"),
        "menlovc": (
            "getro",
            "https://jobs.menlovc.com/companies",
            "collectionId",
            "767",
        ),
        "metaprop": (
            "getro",
            "https://jobs.metaprop.com/companies",
            "collectionId",
            "177",
        ),
        "multicoin": (
            "getro",
            "https://jobs.multicoin.capital/companies",
            "collectionId",
            "390",
        ),
        "nea": ("consider", "https://careers.nea.com/companies", "board", "nea"),
        "nfx": ("getro", "https://jobs.nfx.com/companies", "collectionId", "307"),
        "nextview": (
            "consider",
            "https://jobs.nextview.vc/companies",
            "board",
            "nextview-ventures",
        ),
        "necessary": (
            "consider",
            "https://jobs.necessary.vc/companies",
            "board",
            "necessary-ventures",
        ),
        "nvp": (
            "consider",
            "https://careers.nvp.com/companies",
            "board",
            "norwest-venture-partners",
        ),
        "northzone": (
            "getro",
            "https://portfolio.northzone.com/companies",
            "collectionId",
            "3791",
        ),
        "notablecap": (
            "getro",
            "https://jobs.notablecap.com/companies",
            "collectionId",
            "764",
        ),
        "nyca": ("getro", "https://jobs.nyca.com/companies", "collectionId", "681"),
        "panteracapital": (
            "consider",
            "https://jobs.panteracapital.com/companies",
            "board",
            "pantera-capital",
        ),
        "playground": (
            "consider",
            "https://careers.playground.global/companies",
            "board",
            "playground-global",
        ),
        "oakhcft": (
            "getro",
            "https://jobs.oakhcft.com/companies",
            "collectionId",
            "637",
        ),
        "pointnine": (
            "getro",
            "https://jobs.pointnine.com/companies",
            "collectionId",
            "1680",
        ),
        "primary": (
            "getro",
            "https://jobs.primary.vc/companies",
            "collectionId",
            "1124",
        ),
        "qedinvestors": (
            "consider",
            "https://careers.qedinvestors.com/companies",
            "board",
            "qed-investors",
        ),
        "redpoint": (
            "getro",
            "https://careers.redpoint.com/companies",
            "collectionId",
            "189",
        ),
        "reachcapital": (
            "getro",
            "https://jobs.reachcapital.com/companies",
            "collectionId",
            "685",
        ),
        "rre": ("getro", "https://jobs.rre.com/companies", "collectionId", "114"),
        "pnptc": ("getro", "https://jobs.pnptc.com/companies", "collectionId", "250"),
        "saasventurecapital": (
            "getro",
            "https://careers.saasventurecapital.com/companies",
            "collectionId",
            "929",
        ),
        "sapphireventures": (
            "getro",
            "https://jobs.sapphireventures.com/companies",
            "collectionId",
            "199",
        ),
        "scalevp": (
            "getro",
            "https://jobs.scalevp.com/companies",
            "collectionId",
            "776",
        ),
        "seedcamp": (
            "getro",
            "https://talent.seedcamp.com/companies",
            "collectionId",
            "4186",
        ),
        "signalfire": (
            "getro",
            "https://jobs.signalfire.com/companies",
            "collectionId",
            "135",
        ),
        "speedinvest": (
            "getro",
            "https://careers.speedinvest.com/companies",
            "collectionId",
            "947",
        ),
        "squarepeg": (
            "getro",
            "https://squarepeg.getro.com/companies",
            "collectionId",
            "243",
        ),
        "stage2capital": (
            "getro",
            "https://careers.stage2.capital/companies",
            "collectionId",
            "1112",
        ),
        "summitpartners": (
            "getro",
            "https://jobs.summitpartners.com/companies",
            "collectionId",
            "36623",
        ),
        "teamworthy": (
            "getro",
            "https://teamworthy.getro.com/companies",
            "collectionId",
            "639",
        ),
        "susaventures": (
            "getro",
            "https://jobs.susaventures.com/companies",
            "collectionId",
            "386",
        ),
        "thrivecap": (
            "getro",
            "https://jobs.thrivecap.com/companies",
            "collectionId",
            "2105",
        ),
        "technyc": (
            "getro",
            "https://jobs.technyc.org/companies",
            "collectionId",
            "1543",
        ),
        "techstars": (
            "getro",
            "https://jobs.techstars.com/companies",
            "collectionId",
            "89",
        ),
        "trueventures": (
            "getro",
            "https://jobs.trueventures.com/companies",
            "collectionId",
            "646",
        ),
        "uncorkcapital": (
            "getro",
            "https://jobs.uncorkcapital.com/companies",
            "collectionId",
            "247",
        ),
        "venrock": (
            "getro",
            "https://jobs.venrock.com/companies",
            "collectionId",
            "319",
        ),
        "variant": (
            "getro",
            "https://jobs.variant.fund/companies",
            "collectionId",
            "1508",
        ),
        "25madison": (
            "getro",
            "https://jobs.25madison.com/companies",
            "collectionId",
            "1171",
        ),
        "archetype": (
            "getro",
            "https://jobs.archetype.fund/companies",
            "collectionId",
            "2765",
        ),
        "backed": (
            "getro",
            "https://talent.backed.vc/companies",
            "collectionId",
            "4350",
        ),
        "breakout": (
            "getro",
            "https://jobs.breakout.vc/companies",
            "collectionId",
            "1516",
        ),
        "capitalfactory": (
            "getro",
            "https://jobs.capitalfactory.com/companies",
            "collectionId",
            "719",
        ),
        "correlationvc": (
            "getro",
            "https://jobs.correlationvc.com/companies",
            "collectionId",
            "107",
        ),
        "detroitvc": (
            "getro",
            "https://jobs.detroit.vc/companies",
            "collectionId",
            "308",
        ),
        "g2vp": ("getro", "https://jobs.g2vp.com/companies", "collectionId", "787"),
        "humbaventures": (
            "getro",
            "https://jobs.humbaventures.com/companies",
            "collectionId",
            "11642",
        ),
        "macventurecapital": (
            "getro",
            "https://jobs.macventurecapital.com/companies",
            "collectionId",
            "1449",
        ),
        "marvinvc": (
            "getro",
            "https://jobs.marvinvc.com/companies",
            "collectionId",
            "10950",
        ),
        "moxxie": (
            "getro",
            "https://careers.moxxie.vc/companies",
            "collectionId",
            "1168",
        ),
        "originventures": (
            "getro",
            "https://jobs.originventures.com/companies",
            "collectionId",
            "13589",
        ),
        "powerhouseventures": (
            "getro",
            "https://careers.powerhouse-ventures.co/companies",
            "collectionId",
            "952",
        ),
        "radical": (
            "getro",
            "https://radical.getro.com/companies",
            "collectionId",
            "816",
        ),
        "rallyventures": (
            "getro",
            "https://jobs.rallyventures.com/companies",
            "collectionId",
            "1613",
        ),
        "squadra": (
            "getro",
            "https://talent.squadra.vc/companies",
            "collectionId",
            "4778",
        ),
        "theoryvc": (
            "getro",
            "https://jobs.theoryvc.com/companies",
            "collectionId",
            "29066",
        ),
        "tribecavp": (
            "getro",
            "https://jobs.tribecavp.com/companies",
            "collectionId",
            "101",
        ),
        "trinityventures": (
            "getro",
            "https://jobs.trinityventures.com/companies",
            "collectionId",
            "393",
        ),
        "tusk": ("getro", "https://jobs.tusk.vc/companies", "collectionId", "261"),
        "underscore": (
            "getro",
            "https://jobs.underscore.vc/companies",
            "collectionId",
            "864",
        ),
        "upwest": (
            "getro",
            "https://jobs.upwest.vc/companies",
            "collectionId",
            "298",
        ),
        "volitioncapital": (
            "getro",
            "https://jobs.volitioncapital.com/companies",
            "collectionId",
            "786",
        ),
        "vuventurepartners": (
            "consider",
            "https://jobs.vuventurepartners.com/companies",
            "board",
            "vu-venture-partners",
        ),
        "wing": (
            "getro",
            "https://careers.wing.vc/companies",
            "collectionId",
            "43520",
        ),
        "woven": (
            "consider",
            "https://portfoliojobs.woven.vc/companies",
            "board",
            "woven-capital",
        ),
        "sosv": (
            "consider",
            "https://techjobs.sosv.com/companies",
            "board",
            "sosv",
        ),
        "hoxtonventures": (
            "consider",
            "https://jobs.hoxtonventures.com/companies",
            "board",
            "hoxton-ventures",
        ),
        "acme": ("getro", "https://jobs.acme.vc/companies", "collectionId", "477"),
        "age1": ("consider", "https://careers.age1.com/companies", "board", "age1"),
        "atlasventure": (
            "consider",
            "https://careers.atlasventure.com/companies",
            "board",
            "atlas-venture",
        ),
        "bakarlabs": (
            "consider",
            "https://jobs.bakarlabs.org/companies",
            "board",
            "bakar-bio-labs",
        ),
        "breakthroughenergy": (
            "getro",
            "https://bevjobs.breakthroughenergy.org/companies",
            "collectionId",
            "1533",
        ),
        "cervinventures": (
            "getro",
            "https://jobs.cervinventures.com/companies",
            "collectionId",
            "7385",
        ),
        "definevc": (
            "getro",
            "https://careers.definevc.com/companies",
            "collectionId",
            "1019",
        ),
        "fintech": (
            "getro",
            "https://jobs.fintech.io/companies",
            "collectionId",
            "1590",
        ),
        "firstminute": (
            "getro",
            "https://jobs.firstminute.capital/companies",
            "collectionId",
            "178",
        ),
        "frameworkventures": (
            "getro",
            "https://jobs.framework.ventures/companies",
            "collectionId",
            "1127",
        ),
        "gaingels": (
            "consider",
            "https://jobs.gaingels.com/companies",
            "board",
            "gaingels",
        ),
        "georgian": (
            "getro",
            "https://careers.georgian.io/companies",
            "collectionId",
            "14282",
        ),
        "hitachiventures": (
            "consider",
            "https://jobs.hitachi-ventures.com/companies",
            "board",
            "hitachi-ventures",
        ),
        "jumpcap": (
            "getro",
            "https://jobs.jumpcap.com/companies",
            "collectionId",
            "951",
        ),
        "mavenventures": (
            "getro",
            "https://careers.mavenventures.com/companies",
            "collectionId",
            "1678",
        ),
        "mvp": (
            "consider",
            "https://talent.mvp-vc.com/companies",
            "board",
            "mvp-ventures",
        ),
        "nexusvp": (
            "consider",
            "https://jobs.nexusvp.com/companies",
            "board",
            "nexus-venture-partners",
        ),
        "offline": (
            "consider",
            "https://jobs.offline.vc/companies",
            "board",
            "offline-ventures",
        ),
        "omegavp": (
            "getro",
            "https://jobs.omegavp.com/companies",
            "collectionId",
            "1343",
        ),
        "ret": ("getro", "https://jobs.ret.vc/companies", "collectionId", "216"),
        "rho": ("getro", "https://jobs.rho.com/companies", "collectionId", "1033"),
        "somacap": (
            "getro",
            "https://jobs.somacap.com/companies",
            "collectionId",
            "3194",
        ),
        "tcv": (
            "getro",
            "https://portfoliojobs.tcv.com/companies",
            "collectionId",
            "6428",
        ),
        "thirdpointventures": (
            "getro",
            "https://jobs.thirdpointventures.com/companies",
            "collectionId",
            "1592",
        ),
        "transition": (
            "consider",
            "https://jobs.transition.vc/companies",
            "board",
            "transition-ventures",
        ),
        "vestigoventures": (
            "getro",
            "https://jobs.vestigoventures.com/companies",
            "collectionId",
            "953",
        ),
        "acurio": (
            "getro",
            "https://acurio.getro.com/companies",
            "collectionId",
            "1169",
        ),
        "angelesinvestors": (
            "getro",
            "https://careers.angelesinvestors.com/companies",
            "collectionId",
            "7748",
        ),
        "banktechventures": (
            "getro",
            "https://careers.banktechventures.com/companies",
            "collectionId",
            "11477",
        ),
        "canapi": (
            "getro",
            "https://careers.canapi.com/companies",
            "collectionId",
            "1000",
        ),
        "collidecap": (
            "getro",
            "https://jobs.collidecap.com/companies",
            "collectionId",
            "2766",
        ),
        "cornerstonevc": (
            "getro",
            "https://careers.cornerstonevc.co/companies",
            "collectionId",
            "1737",
        ),
        "elevateventures": (
            "getro",
            "https://jobs.elevateventures.com/companies",
            "collectionId",
            "11444",
        ),
        "energizecap": (
            "getro",
            "https://jobs.energizecap.com/companies",
            "collectionId",
            "1212",
        ),
        "flourishventures": (
            "getro",
            "https://jobs.flourishventures.com/companies",
            "collectionId",
            "249",
        ),
        "globalvc": (
            "getro",
            "https://jobs.global.vc/companies",
            "collectionId",
            "12434",
        ),
        "gsv": ("getro", "https://gsv.getro.com/companies", "collectionId", "777"),
        "hgventures": (
            "getro",
            "https://portcojobs.hgventures.com/companies",
            "collectionId",
            "1500",
        ),
        "hyperplane": (
            "getro",
            "https://careers.hyperplane.vc/companies",
            "collectionId",
            "35402",
        ),
        "imaginary": (
            "getro",
            "https://imaginary.getro.com/companies",
            "collectionId",
            "923",
        ),
        "kingriver": (
            "getro",
            "https://jobs.kingriver.co/companies",
            "collectionId",
            "3558",
        ),
        "lightbank": (
            "getro",
            "https://jobs.lightbank.com/companies",
            "collectionId",
            "10322",
        ),
        "motion": (
            "getro",
            "https://jobs.motion.vc/companies",
            "collectionId",
            "11807",
        ),
        "polychain": (
            "getro",
            "https://jobs.polychain.capital/companies",
            "collectionId",
            "203",
        ),
        "racap": (
            "getro",
            "https://open-positions.racap.com/companies",
            "collectionId",
            "45599",
        ),
        "realventures": (
            "getro",
            "https://jobs.realventures.com/companies",
            "collectionId",
            "166",
        ),
        "sarahsmith": (
            "getro",
            "https://jobs.sarahsmith.fund/companies",
            "collectionId",
            "10817",
        ),
        "seventures": (
            "getro",
            "https://seventures.getro.com/companies",
            "collectionId",
            "7583",
        ),
        "springtimeventures": (
            "getro",
            "https://careers.springtimeventures.com/companies",
            "collectionId",
            "1437",
        ),
        "uluventures": (
            "getro",
            "https://jobs.uluventures.com/companies",
            "collectionId",
            "11411",
        ),
        "venturestudios": (
            "getro",
            "https://jobsatventurestudios.com/discover/companies",
            "collectionId",
            "13820",
        ),
        "2150": ("getro", "https://jobs.2150.vc/companies", "collectionId", "1287"),
        "abstractvc": (
            "consider",
            "https://jobs.abstractvc.com/companies",
            "board",
            "abstract-ventures",
        ),
        "adverb": (
            "consider",
            "https://jobs.adverb.vc/companies",
            "board",
            "adverb-ventures",
        ),
        "atoneventures": (
            "consider",
            "https://jobs.atoneventures.com/companies",
            "board",
            "at-one-ventures",
        ),
        "avp": ("getro", "https://jobs.avp.vc/companies", "collectionId", "1673"),
        "base10": (
            "getro",
            "https://careers.base10.vc/companies",
            "collectionId",
            "1207",
        ),
        "buildingventures": (
            "getro",
            "https://jobs.buildingventures.com/companies",
            "collectionId",
            "1420",
        ),
        "cherry": (
            "getro",
            "https://talent.cherry.vc/companies",
            "collectionId",
            "44081",
        ),
        "citylight": (
            "getro",
            "https://jobs.citylight.vc/companies",
            "collectionId",
            "9796",
        ),
        "convectivecapital": (
            "getro",
            "https://jobs.convectivecapital.com/companies",
            "collectionId",
            "1732",
        ),
        "cventures": (
            "getro",
            "https://jobs.cventures.vc/companies",
            "collectionId",
            "9365",
        ),
        "digitalfuelcapital": (
            "getro",
            "https://careers.digitalfuelcapital.com/companies",
            "collectionId",
            "6758",
        ),
        "e14": ("consider", "https://jobs.e14.vc/companies", "board", "e14-fund"),
        "edisonpartners": (
            "getro",
            "https://jobs.edisonpartners.com/companies",
            "collectionId",
            "148",
        ),
        "expa": ("consider", "https://jobs.expa.com/companies", "board", "expa"),
        "extantia": (
            "consider",
            "https://careers.extantia.com/companies",
            "board",
            "extantia",
        ),
        "f2vc": (
            "consider",
            "https://jobs.f2vc.com/companies",
            "board",
            "f2-venture-capital",
        ),
        "fenbushicapital": (
            "consider",
            "https://careers.fenbushicapital.vc/companies",
            "board",
            "fenbushi-capital",
        ),
        "fyrfly": (
            "getro",
            "https://careers.fyrfly.vc/companies",
            "collectionId",
            "6461",
        ),
        "galaxy": (
            "getro",
            "https://venturecareers.galaxy.com/companies",
            "collectionId",
            "9134",
        ),
        "garuda": (
            "getro",
            "https://jobs.garuda.vc/companies",
            "collectionId",
            "3590",
        ),
        "headline": (
            "getro",
            "https://talent.headline.com/companies",
            "collectionId",
            "3293",
        ),
        "hellokoru": (
            "getro",
            "https://careers.hellokoru.com/companies",
            "collectionId",
            "11675",
        ),
        "hivemind": (
            "getro",
            "https://jobs.hivemind.capital/companies",
            "collectionId",
            "1298",
        ),
        "loeb": ("getro", "https://jobs.loeb.nyc/companies", "collectionId", "1427"),
        "longjourney": (
            "getro",
            "https://jobs.longjourney.vc/companies",
            "collectionId",
            "8279",
        ),
        "lool": (
            "getro",
            "https://opportunities.lool.vc/companies",
            "collectionId",
            "309",
        ),
        "mannatreepartners": (
            "getro",
            "https://careers.mannatreepartners.com/companies",
            "collectionId",
            "1444",
        ),
        "mantisvc": (
            "consider",
            "https://careers.mantisvc.com/companies",
            "board",
            "mantis",
        ),
        "meridianstreetcapital": (
            "getro",
            "https://careers.meridianstreetcapital.com/companies",
            "collectionId",
            "1501",
        ),
        "moderneventures": (
            "getro",
            "https://portfoliocareers.moderneventures.com/companies",
            "collectionId",
            "13293",
        ),
        "munichreventures": (
            "getro",
            "https://portfoliojobs.munichreventures.com/companies",
            "collectionId",
            "1182",
        ),
        "newmarketsvp": (
            "getro",
            "https://jobs.newmarketsvp.com/companies",
            "collectionId",
            "3260",
        ),
        "norrsken": (
            "getro",
            "https://jobs.norrsken.org/companies",
            "collectionId",
            "4217",
        ),
        "notation": (
            "consider",
            "https://consider.com/boards/vc/notation-capital/companies",
            "board",
            "notation-capital",
        ),
        "notion": (
            "consider",
            "https://jobs.notion.vc/companies",
            "board",
            "notion-capital",
        ),
        "octopusventures": (
            "getro",
            "https://talent.octopusventures.com/companies",
            "collectionId",
            "4580",
        ),
        "oneragtime": (
            "consider",
            "https://careers.oneragtime.com/companies",
            "board",
            "oneragtime",
        ),
        "openocean": (
            "getro",
            "https://jobs.openocean.vc/companies",
            "collectionId",
            "13919",
        ),
        "partechpartners": (
            "getro",
            "https://portfoliojobs.partechpartners.com/companies",
            "collectionId",
            "10421",
        ),
        "pelionvp": (
            "getro",
            "https://jobs.pelionvp.com/companies",
            "collectionId",
            "1631",
        ),
        "playvc": (
            "getro",
            "https://careers.play.vc/companies",
            "collectionId",
            "1624",
        ),
        "preludeventures": (
            "getro",
            "https://jobs.preludeventures.com/companies",
            "collectionId",
            "638",
        ),
        "rev1ventures": (
            "getro",
            "https://jobs.rev1ventures.com/companies",
            "collectionId",
            "405",
        ),
        "startx": ("consider", "https://jobs.startx.com/companies", "board", "startx"),
        "threshold": (
            "consider",
            "https://jobs.threshold.vc/companies",
            "board",
            "threshold-ventures",
        ),
        "toyotaventures": (
            "getro",
            "https://jobs.toyota.ventures/companies",
            "collectionId",
            "205",
        ),
        "urbaninnovationfund": (
            "consider",
            "https://jobs.urbaninnovationfund.com/companies",
            "board",
            "urban-innovation-fund",
        ),
        "xange": ("consider", "https://jobs.xange.vc/companies", "board", "xange"),
        "zettavp": (
            "consider",
            "https://careers.zettavp.com/companies",
            "board",
            "zetta-venture-partners",
        ),
        "xyz": ("getro", "https://jobs.xyz.vc/companies", "collectionId", "13359"),
        "01a": (
            "consider",
            "https://jobs.01a.com/companies",
            "board",
            "01-advisors",
        ),
        "360cap": (
            "consider",
            "https://jobs.360cap.vc/companies",
            "board",
            "360-capital",
        ),
        "53stations": (
            "getro",
            "https://jobs.53stations.com/companies",
            "collectionId",
            "45269",
        ),
        "acp": ("getro", "https://jobs.acp.vc/companies", "collectionId", "1339"),
        "activate": (
            "getro",
            "https://jobs.activate.org/companies",
            "collectionId",
            "937",
        ),
        "adara": (
            "consider",
            "https://talent.adara.vc/companies",
            "board",
            "adara-ventures",
        ),
        "aifund": (
            "consider",
            "https://careers.aifund.ai/companies",
            "board",
            "ai-fund",
        ),
        "alven": ("consider", "https://jobs.alven.co/companies", "board", "alven"),
        "amplifyla": (
            "consider",
            "https://jobs.amplify.la/companies",
            "board",
            "amplify-la",
        ),
        "b2venture": (
            "getro",
            "https://jobs.b2venture.vc/companies",
            "collectionId",
            "4283",
        ),
        "becocapital": (
            "getro",
            "https://careers.becocapital.com/companies",
            "collectionId",
            "10883",
        ),
        "benchstrengthvc": (
            "getro",
            "https://jobs.benchstrengthvc.com/companies",
            "collectionId",
            "12600",
        ),
        "brightspark": (
            "getro",
            "https://careers.brightspark.com/",
            "collectionId",
            "1436",
        ),
        "cmont": (
            "getro",
            "https://careers.cmont.com/companies",
            "collectionId",
            "12698",
        ),
        "communitech": (
            "getro",
            "https://www1.communitech.ca/companies",
            "collectionId",
            "628",
        ),
        "comcastventures": (
            "getro",
            "https://portfoliojobs.comcastventures.com/companies",
            "collectionId",
            "256",
        ),
        "congruentvc": (
            "consider",
            "https://jobs.congruentvc.com/companies",
            "board",
            "congruent-ventures",
        ),
        "dawncapital": (
            "getro",
            "https://jobs.dawncapital.com/companies",
            "collectionId",
            "3063",
        ),
        "deepscienceventures": (
            "getro",
            "https://jobs.deepscienceventures.com/companies",
            "collectionId",
            "1630",
        ),
        "diagram": (
            "getro",
            "https://careers.diagram.ca/companies",
            "collectionId",
            "1084",
        ),
        "eniac": ("getro", "https://jobs.eniac.vc/companies", "collectionId", "117"),
        "etherealventures": (
            "consider",
            "https://consider.com/boards/vc/ethereal-ventures/companies",
            "board",
            "ethereal-ventures",
        ),
        "foothillventures": (
            "consider",
            "https://jobs.foothill.ventures/companies",
            "board",
            "foothill-ventures",
        ),
        "founderful": (
            "consider",
            "https://jobs.founderful.com/companies",
            "board",
            "wingman",
        ),
        "galvanizeclimate": (
            "consider",
            "https://consider.com/boards/vc/galvanize-climate-solutions/companies",
            "board",
            "galvanize-climate-solutions",
        ),
        "gradient": (
            "consider",
            "https://careers.gradient.com/companies",
            "board",
            "gradient-ventures",
        ),
        "gtmfund": (
            "consider",
            "https://jobs.gtmfund.com/companies",
            "board",
            "gtmfund",
        ),
        "istariglobal": (
            "consider",
            "https://careers.istari-global.com/companies",
            "board",
            "istari",
        ),
        "israelvcforum": (
            "getro",
            "https://israelvcforum.getro.com/companies",
            "collectionId",
            "10949",
        ),
        "investottawa": (
            "getro",
            "https://techjobfinder.investottawa.ca/companies",
            "collectionId",
            "1546",
        ),
        "jamjarinvestments": (
            "getro",
            "https://jobs.jamjarinvestments.com/companies",
            "collectionId",
            "12863",
        ),
        "lemniscap": (
            "consider",
            "https://careers.lemniscap.com/companies",
            "board",
            "lemniscap",
        ),
        "ngpcap": (
            "getro",
            "https://jobs.ngpcap.com/companies",
            "collectionId",
            "3426",
        ),
        "oregonventurefund": (
            "consider",
            "https://jobs.oregonventurefund.com/companies",
            "board",
            "oregon-venture-fund",
        ),
        "peakxv": (
            "consider",
            "https://careers.peakxv.com/companies",
            "board",
            "sequoia-capital-india",
        ),
        "planeta": (
            "getro",
            "https://jobs.planet-a.com/companies",
            "collectionId",
            "1426",
        ),
        "queertech": (
            "getro",
            "https://queertech.getro.com/companies",
            "collectionId",
            "883",
        ),
        "qumracapital": (
            "getro",
            "https://jobs.qumracapital.com/companies",
            "collectionId",
            "474",
        ),
        "radiancapital": (
            "consider",
            "https://careers.radiancapital.com/companies",
            "board",
            "radian-capital",
        ),
        "redseaventures": (
            "getro",
            "https://jobs.redseaventures.com/companies",
            "collectionId",
            "78",
        ),
        "serena": (
            "consider",
            "https://careers.serena.vc/companies",
            "board",
            "serena",
        ),
        "setventures": (
            "consider",
            "https://careers.setventures.com/companies",
            "board",
            "set-ventures",
        ),
        "skyvc": (
            "consider",
            "https://careers.sky-vc.com/companies",
            "board",
            "jetblue-ventures",
        ),
        "sterlingpartners": (
            "consider",
            "https://consider.com/boards/vc/sterling-partners/companies",
            "board",
            "sterling-partners",
        ),
        "stripes": (
            "getro",
            "https://jobs.stripes.co/companies",
            "collectionId",
            "167",
        ),
        "thomvest": (
            "consider",
            "https://jobs.thomvest.com/companies",
            "board",
            "thomvest",
        ),
        "tidemarkcap": (
            "consider",
            "https://careers.tidemarkcap.com/companies",
            "board",
            "tidemark-capital",
        ),
        "verdane": (
            "consider",
            "https://consider.com/boards/vc/verdane/companies",
            "board",
            "verdane",
        ),
        "ffwd": (
            "getro",
            "https://jobs.ffwd.org/companies",
            "collectionId",
            "997",
        ),
        "leadershipforeducationalequity": (
            "consider",
            "https://consider.com/boards/vc/leadership-for-educational-equity/companies",
            "board",
            "leadership-for-educational-equity",
        ),
        "annarborusa": (
            "getro",
            "https://jobs.annarborusa.org/companies",
            "collectionId",
            "29331",
        ),
        "greentownlabs": (
            "consider",
            "https://jobs.greentownlabs.com/companies",
            "board",
            "greentown-labs",
        ),
        "thisiscny": (
            "getro",
            "https://careers.thisiscny.com/companies",
            "collectionId",
            "392",
        ),
        "investedinthemission": (
            "getro",
            "https://careers.investedinthemission.org/companies",
            "collectionId",
            "8540",
        ),
        "revolution": (
            "getro",
            "https://jobs.revolution.com/companies",
            "collectionId",
            "143",
        ),
        "protocolai": (
            "getro",
            "https://jobs.protocol.ai/companies",
            "collectionId",
            "1336",
        ),
        "climatejobs": (
            "getro",
            "https://climatejobs.shortlist.net/companies",
            "collectionId",
            "6857",
        ),
        "elementalimpact": (
            "getro",
            "https://jobs.elementalimpact.com/companies",
            "collectionId",
            "624",
        ),
        "baincapital": (
            "consider",
            "https://consider.com/boards/vc/bain-capital/companies",
            "board",
            "bain-capital",
        ),
        "ta": (
            "getro",
            "https://careers.ta.com/companies",
            "collectionId",
            "4415",
        ),
        "sggc": (
            "consider",
            "https://careers.sggc.sg/companies",
            "board",
            "edbi",
        ),
        "surgeahead": (
            "consider",
            "https://jobs.surgeahead.com/companies",
            "board",
            "surge-ahead",
        ),
        "launchtn": (
            "getro",
            "https://jobs.launchtn.org/companies",
            "collectionId",
            "260",
        ),
        "emcap": (
            "getro",
            "https://talent.emcap.com/companies",
            "collectionId",
            "164",
        ),
        "energyimpactpartners": (
            "getro",
            "https://jobs.energyimpactpartners.com/companies",
            "collectionId",
            "253",
        ),
        "astanor": (
            "getro",
            "https://jobs.astanor.com/companies",
            "collectionId",
            "8243",
        ),
        "anitab": (
            "getro",
            "https://jobs.anitab.org/companies",
            "collectionId",
            "10323",
        ),
        "motivatevc": (
            "getro",
            "https://jobs.motivate.vc/companies",
            "collectionId",
            "1021",
        ),
        "collaborativefund": (
            "getro",
            "https://collaborative-fund.getro.com/companies",
            "collectionId",
            "97",
        ),
        "sorensoncap": (
            "consider",
            "https://careers.sorensoncap.com/companies",
            "board",
            "sorenson-capital",
        ),
        "cyberfund": (
            "getro",
            "https://talent.cyber.fund/companies",
            "collectionId",
            "9035",
        ),
        "crosscutvc": (
            "getro",
            "https://careers.crosscut.vc/companies",
            "collectionId",
            "948",
        ),
        "humanvc": (
            "getro",
            "https://jobs.human.vc/companies",
            "collectionId",
            "769",
        ),
        "1517fund": (
            "consider",
            "https://consider.com/boards/vc/1517-fund/companies",
            "board",
            "1517-fund",
        ),
        "dynamovc": (
            "consider",
            "https://careers.dynamo.vc/companies",
            "board",
            "dynamo",
        ),
        "bettervc": (
            "getro",
            "https://jobs.better.vc/companies",
            "collectionId",
            "1370",
        ),
        "blackjaysvc": (
            "getro",
            "https://jobs.blackjays.vc/companies",
            "collectionId",
            "1164",
        ),
        "chapterone": (
            "consider",
            "https://consider.com/boards/vc/chapter-one/companies",
            "board",
            "chapter-one",
        ),
        "thewia": (
            "getro",
            "https://jobs.thewia.org/companies",
            "collectionId",
            "106",
        ),
        "stanfordclimateventures": (
            "getro",
            "https://jobs.stanfordclimateventures.org/companies",
            "collectionId",
            "9729",
        ),
        "fusevc": (
            "getro",
            "https://careers.fuse.vc/companies",
            "collectionId",
            "1337",
        ),
        "neworleansbio": (
            "consider",
            "https://careers.neworleansbio.com/companies",
            "board",
            "nobic",
        ),
        "emergecapital": (
            "getro",
            "https://careers.emergecapital.vc/companies",
            "collectionId",
            "4514",
        ),
        "climateinvestment": (
            "getro",
            "https://jobs.climateinvestment.com/companies",
            "collectionId",
            "8639",
        ),
        "fil": (
            "getro",
            "https://careers.fil.org/companies",
            "collectionId",
            "1486",
        ),
        "tacostars": (
            "getro",
            "https://talent.tacostars.org/companies",
            "collectionId",
            "1597",
        ),
        "femtechinsider": (
            "getro",
            "https://jobs.femtechinsider.com/companies",
            "collectionId",
            "14612",
        ),
        "adventinternational": (
            "consider",
            "https://consider.com/boards/vc/advent-international/companies",
            "board",
            "advent-international",
        ),
        "protagonist": (
            "consider",
            "https://jobs.protagonist.co/companies",
            "board",
            "protagonist",
        ),
        "courtsidevc": (
            "consider",
            "https://jobs.courtsidevc.com/companies",
            "board",
            "courtside",
        ),
        "freigeist": (
            "consider",
            "https://consider.com/boards/vc/freigeist/companies",
            "board",
            "freigeist",
        ),
        "gd1": (
            "getro",
            "https://careers.gd1.vc/companies",
            "collectionId",
            "1676",
        ),
        "1835i": (
            "consider",
            "https://consider.com/boards/vc/1835i/companies",
            "board",
            "1835i",
        ),
        "greenfieldgrowth": (
            "getro",
            "https://careers.greenfield-growth.com/companies",
            "collectionId",
            "1534",
        ),
        "rubio": (
            "getro",
            "https://rubio.getro.com/companies",
            "collectionId",
            "1354",
        ),
        "cleanenergyventures": (
            "getro",
            "https://jobs.cleanenergyventures.com/companies",
            "collectionId",
            "1198",
        ),
        "circadianvc": (
            "getro",
            "https://jobs.circadian.vc/companies",
            "collectionId",
            "1181",
        ),
        "yc": (
            "ycombinator",
            "https://www.ycombinator.com/companies",
            "indexName",
            "YCCompany_By_Launch_Date_production",
        ),
        "biocom": (
            "consider",
            "https://consider.com/boards/vc/biocom/companies",
            "board",
            "biocom",
        ),
        "unreasonablegroup": (
            "getro",
            "https://jobs.unreasonablegroup.com/companies",
            "collectionId",
            "1254",
        ),
        "medtechinnovator": (
            "getro",
            "https://jobs.medtechinnovator.org/companies",
            "collectionId",
            "12236",
        ),
        "newyorkbio": (
            "consider",
            "https://consider.com/boards/vc/newyorkbio/companies",
            "board",
            "newyorkbio",
        ),
        "leadedge": (
            "getro",
            "https://jobs.leadedge.com/companies",
            "collectionId",
            "1076",
        ),
        "franciscopartners": (
            "getro",
            "https://careers.franciscopartners.com/companies",
            "collectionId",
            "1442",
        ),
        "breakthroughenergyfellows": (
            "getro",
            "https://befjobs.breakthroughenergy.org/companies",
            "collectionId",
            "2567",
        ),
        "lakestar": (
            "consider",
            "https://consider.com/boards/vc/lakestar/companies",
            "board",
            "lakestar",
        ),
        "riverparkvc": (
            "getro",
            "https://jobs.riverparkvc.com/companies",
            "collectionId",
            "1429",
        ),
        "thirdsphere": (
            "getro",
            "https://jobs.thirdsphere.com/companies",
            "collectionId",
            "862",
        ),
        "massmutualventures": (
            "getro",
            "https://jobs.massmutualventures.com/companies",
            "collectionId",
            "813",
        ),
        "amadeus": (
            "consider",
            "https://consider.com/boards/vc/amadeus/companies",
            "board",
            "amadeus",
        ),
        "pilabs": (
            "getro",
            "https://jobs.pilabs.vc/companies",
            "collectionId",
            "2666",
        ),
        "s3vc": ("getro", "https://jobs.s3vc.com/companies", "collectionId", "684"),
        "mevp": ("getro", "https://jobs.mevp.com/companies", "collectionId", "1034"),
        "westboundequity": (
            "getro",
            "https://jobs.westboundequity.com/companies",
            "collectionId",
            "1007",
        ),
        "canvasvc": (
            "getro",
            "https://jobs.canvas.vc/companies",
            "collectionId",
            "34379",
        ),
        "industriousvc": (
            "getro",
            "https://jobs.industrious.vc/companies",
            "collectionId",
            "33917",
        ),
        "bluebearcap": (
            "getro",
            "https://jobs.bluebearcap.com/companies",
            "collectionId",
            "645",
        ),
        "shieldcap": (
            "getro",
            "https://portfoliocareers.shieldcap.com/companies",
            "collectionId",
            "7517",
        ),
        "purdueinnovates": (
            "getro",
            "https://purdueinnovates.getro.com/companies",
            "collectionId",
            "8045",
        ),
        "claltech": (
            "getro",
            "https://careers.claltech.com/companies",
            "collectionId",
            "1128",
        ),
        "homeworldbio": (
            "consider",
            "https://jobs.homeworld.bio/companies",
            "board",
            "homeworld-collective",
        ),
        "type1ventures": (
            "getro",
            "https://jobs.type1ventures.com/companies",
            "collectionId",
            "3393",
        ),
        "xista": (
            "getro",
            "https://careers.xista.vc/companies",
            "collectionId",
            "1353",
        ),
        "tenexcm": (
            "getro",
            "https://tenexcm.getro.com/companies",
            "collectionId",
            "8805",
        ),
        "ascendvc": (
            "getro",
            "https://jobs.ascend.vc/companies",
            "collectionId",
            "14876",
        ),
        "43north": (
            "consider",
            "https://jobs.43north.org/companies",
            "board",
            "forge-buffalo",
        ),
        "vertexventureshc": (
            "getro",
            "https://jobs.vertexventureshc.com/companies",
            "collectionId",
            "9563",
        ),
        "foresitelabs": (
            "consider",
            "https://careers.foresitelabs.com/companies",
            "board",
            "foresite-labs",
        ),
        "thecolumngroup": (
            "consider",
            "https://jobs.thecolumngroup.com/companies",
            "board",
            "the-column-group",
        ),
        "perotjain": (
            "getro",
            "https://jobs.perotjain.com/companies",
            "collectionId",
            "6626",
        ),
        "gcvc": (
            "getro",
            "https://jobs.gc-vc.com/companies",
            "collectionId",
            "4019",
        ),
        "elsewherepartners": (
            "getro",
            "https://jobs.elsewhere.partners/companies",
            "collectionId",
            "1020",
        ),
        "maineventurefund": (
            "consider",
            "https://careers.maineventurefund.com/companies",
            "board",
            "maine-venture-fund",
        ),
        "muditaventurepartners": (
            "consider",
            "https://consider.com/boards/vc/mudita-venture-partners/companies",
            "board",
            "mudita-venture-partners",
        ),
        "pangacapital": (
            "getro",
            "https://careers.pangacapital.com/companies",
            "collectionId",
            "10388",
        ),
        "lrnewenergy": (
            "getro",
            "https://jobs.lrnewenergy.com/companies",
            "collectionId",
            "4349",
        ),
        "sovereignscapital": (
            "getro",
            "https://portcojobs.sovereignscapital.com/companies",
            "collectionId",
            "1281",
        ),
        "allegiscyber": (
            "getro",
            "https://careers.allegiscyber.com/companies",
            "collectionId",
            "2369",
        ),
        "leadoutcapital": (
            "getro",
            "https://jobs.leadoutcapital.com/companies",
            "collectionId",
            "5174",
        ),
        "overturevc": (
            "getro",
            "https://jobs.overture.vc/companies",
            "collectionId",
            "1876",
        ),
        "sjfventures": (
            "getro",
            "https://jobs.sjfventures.com/companies",
            "collectionId",
            "721",
        ),
        "penderventures": (
            "getro",
            "https://careers.penderventures.com/companies",
            "collectionId",
            "3854",
        ),
        "arenaco": (
            "getro",
            "https://jobs.arenaco.com/companies",
            "collectionId",
            "1113",
        ),
        "hydeparkvp": (
            "getro",
            "https://jobs.hydeparkvp.com/companies",
            "collectionId",
            "112",
        ),
        "mxv": (
            "getro",
            "https://careers.mxv.vc/companies",
            "collectionId",
            "1528",
        ),
        "maveron": (
            "getro",
            "https://jobs.maveron.com/companies",
            "collectionId",
            "810",
        ),
        "scribblevc": (
            "consider",
            "https://jobs.scribble.vc/companies",
            "board",
            "scribble",
        ),
        "getrocommunity": (
            "getro",
            "https://community.getro.com/companies",
            "collectionId",
            "8870",
        ),
        "phoenixcourt": (
            "consider",
            "https://jobs.phoenixcourt.vc/companies",
            "board",
            "localglobe-all",
        ),
        "ventureloop": (
            "ventureloop",
            "https://www.ventureloop.com/",
            "sourceCategory",
            "startup_ecosystem",
        ),
        "techaviv": (
            "consider",
            "https://jobs.techaviv.com/companies",
            "board",
            "techaviv",
        ),
        "ctinnovations": (
            "consider",
            "https://careers.ctinnovations.com/companies",
            "board",
            "connecticut-innovations",
        ),
        "innovationendeavors": (
            "getro",
            "https://jobs.innovationendeavors.com/companies",
            "collectionId",
            "156",
        ),
        "goodwatercap": (
            "consider",
            "https://portfoliojobs.goodwatercap.com/companies",
            "board",
            "goodwater-capital",
        ),
        "shima": (
            "consider",
            "https://jobs.shima.capital/companies",
            "board",
            "shima-capital",
        ),
        "fabricvc": (
            "consider",
            "https://careers.fabric.vc/companies",
            "board",
            "fabric-ventures",
        ),
        "venturesplatform": (
            "getro",
            "https://jobs.venturesplatform.com/companies",
            "collectionId",
            "10784",
        ),
        "deepworkcapital": (
            "getro",
            "https://careers.deepworkcapital.com/companies",
            "collectionId",
            "9497",
        ),
        "makersfund": (
            "consider",
            "https://jobs.makersfund.com/companies",
            "board",
            "makers-fund",
        ),
        "uppartners": (
            "consider",
            "https://careers.up.partners/companies",
            "board",
            "up-partners",
        ),
        "blueyard": (
            "getro",
            "https://jobs.blueyard.com/companies",
            "collectionId",
            "796",
        ),
        "abven": (
            "getro",
            "https://jobs.abven.com/companies",
            "collectionId",
            "400",
        ),
        "differentialvc": (
            "getro",
            "https://jobs.differential.vc/companies",
            "collectionId",
            "765",
        ),
        "arcternventures": (
            "getro",
            "https://careers.arcternventures.com/companies",
            "collectionId",
            "1087",
        ),
        "fiveelms": (
            "getro",
            "https://careers.fiveelms.com/companies",
            "collectionId",
            "10586",
        ),
        "greathillpartners": (
            "consider",
            "https://jobs.greathillpartners.com/companies",
            "board",
            "great-hill-partners",
        ),
        "thirdrockventures": (
            "consider",
            "https://jobs.thirdrockventures.com/companies",
            "board",
            "third-rock-ventures",
        ),
        "genoavc": (
            "consider",
            "https://careers.genoavc.com/companies",
            "board",
            "genoa",
        ),
        "echelon": (
            "getro",
            "https://careers.echelon.xyz/companies",
            "collectionId",
            "12203",
        ),
        "gridironcapital": (
            "consider",
            "https://jobs.gridironcapital.com/companies",
            "board",
            "gridiron-capital",
        ),
        "k1": (
            "consider",
            "https://portfoliocareers.k1.com/companies",
            "board",
            "k1",
        ),
        "cerberus": (
            "getro",
            "https://portfoliojobs.cerberus.com/companies",
            "collectionId",
            "12962",
        ),
        "pumagrowthpartners": (
            "consider",
            "https://jobs.pumagrowthpartners.co.uk/companies",
            "board",
            "puma-pe",
        ),
        "arsenalgrowth": (
            "consider",
            "https://jobs.arsenalgrowth.com/companies",
            "board",
            "arsenal-growth",
        ),
        "meron": (
            "getro",
            "https://careers.meron.co/companies",
            "collectionId",
            "1257",
        ),
        "relevanceventures": (
            "getro",
            "https://careers.relevanceventures.com/companies",
            "collectionId",
            "6065",
        ),
        "elabvc": (
            "getro",
            "https://jobs.elabvc.com/companies",
            "collectionId",
            "1089",
        ),
        "nightdragon": (
            "getro",
            "https://careers.nightdragon.com/companies",
            "collectionId",
            "1105",
        ),
        "greymattercapital": (
            "getro",
            "https://careers.greymattercapital.com/companies",
            "collectionId",
            "4910",
        ),
        "amplitudevc": (
            "getro",
            "https://careers.amplitudevc.com/companies",
            "collectionId",
            "1271",
        ),
        "aldrichcap": (
            "getro",
            "https://careers.aldrichcap.com/companies",
            "collectionId",
            "6659",
        ),
        "valoventures": (
            "getro",
            "https://valoventures.getro.com/companies",
            "collectionId",
            "1540",
        ),
        "kcrise": (
            "getro",
            "https://kcrise.getro.com/companies",
            "collectionId",
            "1503",
        ),
        "skyviewventures": (
            "getro",
            "https://jobs.skyviewventures.com/companies",
            "collectionId",
            "5339",
        ),
        "pulsefund": (
            "getro",
            "https://careers.pulsefund.com/companies",
            "collectionId",
            "13985",
        ),
        "superorganism": (
            "getro",
            "https://jobs.superorganism.com/companies",
            "collectionId",
            "10058",
        ),
        "azollaventures": (
            "consider",
            "https://jobs.azollaventures.com/companies",
            "board",
            "azolla-ventures",
        ),
        "byldvc": (
            "consider",
            "https://careers.byld.vc/companies",
            "board",
            "byld-ventures",
        ),
        "m1c": (
            "consider",
            "https://careers.m1c.vc/companies",
            "board",
            "mission-one",
        ),
        "revent": (
            "consider",
            "https://careers.revent.vc/companies",
            "board",
            "revent",
        ),
        "zeldavc": (
            "consider",
            "https://jobs.zelda.vc/companies",
            "board",
            "zelda-ventures",
        ),
        "i2iventures": (
            "getro",
            "https://i2iventures.getro.com/companies",
            "collectionId",
            "1485",
        ),
        "parameter": (
            "consider",
            "https://jobs.parameter.vc/companies",
            "board",
            "parameter-ventures",
        ),
        "westlygroup": (
            "getro",
            "https://jobs.westlygroup.com/companies",
            "collectionId",
            "10685",
        ),
        "jobsinvc": (
            "getro",
            "https://jobsinvc.getro.com/companies",
            "collectionId",
            "15272",
        ),
        "venturecapitalcareers": (
            "venturecapitalcareers",
            "https://venturecapitalcareers.com/companies",
            "sourceCategory",
            "startup_ecosystem",
        ),
        "innovationbay": (
            "getro",
            "https://jobs.innovationbay.com/companies",
            "collectionId",
            "1014",
        ),
        "capitalg": (
            "consider",
            "https://careers.capitalg.com/companies",
            "board",
            "capitalg",
        ),
        "integritypowersearch": (
            "consider",
            "https://consider.com/boards/vc/integrity-power-search/companies",
            "board",
            "integrity-power-search",
        ),
        "praxis": (
            "getro",
            "https://jobs.praxis.co/companies",
            "collectionId",
            "130",
        ),
        "cultivationcapital": (
            "consider",
            "https://portfoliojobs.cultivationcapital.com/companies",
            "board",
            "cultivation-capital",
        ),
        "cardinalrefer": (
            "consider",
            "https://consider.com/boards/vc/cardinal-refer/companies",
            "board",
            "cardinal-refer",
        ),
        "kaszek": (
            "consider",
            "https://jobs.kaszek.com/companies",
            "board",
            "kaszek",
        ),
        "cranevc": (
            "getro",
            "https://careers.crane.vc/companies",
            "collectionId",
            "1940",
        ),
        "upfront": (
            "getro",
            "https://jobs.upfront.com/companies",
            "collectionId",
            "184",
        ),
        "rethinkcapital": (
            "consider",
            "https://rethink-education-portfolio-jobs.rethink-capital.com/companies",
            "board",
            "rethink-capital",
        ),
        "kickstart": (
            "getro",
            "https://jobs.kickstart.com/companies",
            "collectionId",
            "131",
        ),
        "learncapital": (
            "getro",
            "https://learncapital.getro.com/companies",
            "collectionId",
            "396",
        ),
        "imagineh2o": (
            "getro",
            "https://watertechjobs.imagineh2o.org/companies",
            "collectionId",
            "2336",
        ),
        "engine": (
            "getro",
            "https://jobs.engine.xyz/companies",
            "collectionId",
            "223",
        ),
        "orbitmit": (
            "getro",
            "https://jobs.orbit.mit.edu/companies",
            "collectionId",
            "186",
        ),
        "waed": (
            "consider",
            "https://portfoliojobs.waed.com/companies",
            "board",
            "waed",
        ),
        "brv": (
            "getro",
            "https://jobs.brv.com/companies",
            "collectionId",
            "168",
        ),
        "startupcincy": (
            "getro",
            "https://jobs.startupcincy.com/companies",
            "collectionId",
            "14810",
        ),
        "amplifylaunchpad": (
            "getro",
            "https://amplifylaunchpad.getro.com/companies",
            "collectionId",
            "925",
        ),
        "wassonenterprise": (
            "getro",
            "https://careers.wassonenterprise.com/companies",
            "collectionId",
            "873",
        ),
        "onewayvc": (
            "getro",
            "https://careers.onewayvc.com/companies",
            "collectionId",
            "942",
        ),
        "luminarventures": (
            "getro",
            "https://careers.luminarventures.com/companies",
            "collectionId",
            "10487",
        ),
        "clearventures": (
            "getro",
            "https://jobs.clear.ventures/companies",
            "collectionId",
            "36293",
        ),
        "javelinvp": (
            "getro",
            "https://careers.javelinvp.com/companies",
            "collectionId",
            "324",
        ),
        "grovevc": (
            "getro",
            "https://careers.grovevc.com/companies",
            "collectionId",
            "9398",
        ),
        "forgepointcap": (
            "getro",
            "https://jobs.forgepointcap.com/companies",
            "collectionId",
            "1369",
        ),
        "blackwoodvc": (
            "getro",
            "https://careers.blackwood.vc/companies",
            "collectionId",
            "11543",
        ),
        "westcap": (
            "consider",
            "https://consider.com/boards/vc/westcap/companies",
            "board",
            "westcap",
        ),
        "albumvc": (
            "getro",
            "https://jobs.album.vc/companies",
            "collectionId",
            "134",
        ),
        "americanunderground": (
            "getro",
            "https://jobs.americanunderground.com/companies",
            "collectionId",
            "1117",
        ),
        "deciens": (
            "getro",
            "https://careers.deciens.com/companies",
            "collectionId",
            "5240",
        ),
        "georgiafintechacademy": (
            "getro",
            "https://jobs.georgiafintechacademy.org/companies",
            "collectionId",
            "1357",
        ),
        "ideavillage": (
            "getro",
            "https://jobs.ideavillage.org/companies",
            "collectionId",
            "1183",
        ),
        "4pt0": (
            "getro",
            "https://jobs.4pt0.org/companies",
            "collectionId",
            "13523",
        ),
        "supermooncapital": (
            "getro",
            "https://jobs.supermooncapital.com/companies",
            "collectionId",
            "1208",
        ),
        "dfdf": (
            "consider",
            "https://consider.com/boards/vc/dfdf/companies",
            "board",
            "dfdf",
        ),
        "symboliccapital": (
            "consider",
            "https://consider.com/boards/vc/symbolic-capital/companies",
            "board",
            "symbolic-capital",
        ),
        "greaterwashingtonpartnership": (
            "consider",
            "https://consider.com/boards/vc/greater-washington-partnership/companies",
            "board",
            "greater-washington-partnership",
        ),
        "trilogyequity": (
            "consider",
            "https://trilogy-equity.board.staging.consider.com/companies",
            "board",
            "trilogy-equity",
        ),
        "leoportfolio": (
            "consider",
            "https://consider.com/boards/vc/leo-portfolio/companies",
            "board",
            "leo-portfolio",
        ),
        "nightlabs": (
            "consider",
            "https://consider.com/boards/vc/night-labs/companies",
            "board",
            "night-labs",
        ),
        "bluehaveninitiative": (
            "getro",
            "https://jobs.bluehaveninitiative.com/companies",
            "collectionId",
            "329",
        ),
        "firstraysvc": (
            "getro",
            "https://jobs.firstraysvc.com/companies",
            "collectionId",
            "1194",
        ),
        "bekventures": (
            "consider",
            "https://jobs.bekventures.com/companies",
            "board",
            "digital-east",
        ),
        "pearvc": (
            "ashby",
            "https://jobs.ashbyhq.com/Pear-VC",
            "token",
            "Pear-VC",
        ),
        "forumventures": (
            "ashby",
            "https://jobs.ashbyhq.com/forum-ventures",
            "token",
            "forum-ventures",
        ),
        "nextfrontiercapital": (
            "getro",
            "https://jobs.nextfrontiercapital.com/companies",
            "collectionId",
            "583",
        ),
        "marble": (
            "getro",
            "https://careers.marble.studio/companies",
            "collectionId",
            "7946",
        ),
        "techtitans": (
            "getro",
            "https://careers.techtitans.org/companies",
            "collectionId",
            "1186",
        ),
        "thegarage": (
            "getro",
            "https://jobs.thegarage.northwestern.edu/companies",
            "collectionId",
            "5801",
        ),
        "usv": (
            "consider",
            "https://jobs.usv.com/companies",
            "board",
            "union-square-ventures",
        ),
        "marsdd": (
            "getro",
            "https://techjobs.marsdd.com/companies",
            "collectionId",
            "383",
        ),
        "jumpstartinc": (
            "getro",
            "https://talent.jumpstartinc.org/companies",
            "collectionId",
            "1012",
        ),
        "massdigitalhealth": (
            "getro",
            "https://jobs.massdigitalhealth.org/companies",
            "collectionId",
            "218",
        ),
        "ohiox": ("getro", "https://jobs.ohiox.org/companies", "collectionId", "785"),
        "xrcventures": (
            "getro",
            "https://careers.xrcventures.com/companies",
            "collectionId",
            "1211",
        ),
        "mmc": ("getro", "https://jobs.mmc.vc/companies", "collectionId", "2303"),
        "theventurecity": (
            "getro",
            "https://careers.theventure.city/companies",
            "collectionId",
            "4646",
        ),
        "tandeminvest": (
            "getro",
            "https://jobs.tandeminvest.com/companies",
            "collectionId",
            "13193",
        ),
        "decisivepoint": (
            "getro",
            "https://jobs.decisivepoint.com/companies",
            "collectionId",
            "1074",
        ),
        "aqpsearch": (
            "getro",
            "https://jobs.aqpsearch.com/companies",
            "collectionId",
            "761",
        ),
        "midweststartups": (
            "getro",
            "https://jobs.midweststartups.com/companies",
            "collectionId",
            "768",
        ),
        "techchange": (
            "consider",
            "https://consider.com/boards/vc/techchange/companies",
            "board",
            "techchange",
        ),
        "orbitstartups": (
            "consider",
            "https://consider.com/boards/vc/orbit-startups/companies",
            "board",
            "orbit-startups",
        ),
        "monkshillventures": (
            "consider",
            "https://consider.com/boards/vc/monks-hill-ventures/companies",
            "board",
            "monks-hill-ventures",
        ),
        "skydeck": (
            "consider",
            "https://jobs.skydeck.berkeley.edu/companies",
            "board",
            "berkeley-skydeck",
        ),
        "highalpha": (
            "consider",
            "https://consider.com/boards/vc/high-alpha/companies",
            "board",
            "high-alpha",
        ),
        "gigascale": (
            "consider",
            "https://consider.com/boards/vc/gigascale/companies",
            "board",
            "gigascale",
        ),
        "hunterpointcapital": (
            "consider",
            "https://consider.com/boards/vc/hunter-point-capital/companies",
            "board",
            "hunter-point-capital",
        ),
        "mbaexchange": (
            "consider",
            "https://consider.com/boards/vc/mba-exchange/companies",
            "board",
            "mba-exchange",
        ),
        "1871": (
            "workable_source",
            "https://apply.workable.com/1871/",
            "token",
            "1871",
        ),
        "aihubmasstech": (
            "getro",
            "https://jobs.aihub.masstech.org/companies",
            "collectionId",
            "39725",
        ),
        "icehouseventures": (
            "getro",
            "https://jobs.icehouseventures.co.nz/companies",
            "collectionId",
            "943",
        ),
        "hub71": ("getro", "https://jobs.hub71.com/companies", "collectionId", "9266"),
        "safary": (
            "getro",
            "https://jobs.safary.club/companies",
            "collectionId",
            "36128",
        ),
        "lhh": ("getro", "https://jobs.lhh.co.il/companies", "collectionId", "1200"),
        "coinbase": (
            "getro",
            "https://coinbase.getro.com/companies",
            "collectionId",
            "1625",
        ),
        "theblockchainassociation": (
            "getro",
            "https://jobs.theblockchainassociation.org/companies",
            "collectionId",
            "869",
        ),
        "valorcapitalgroup": (
            "getro",
            "https://jobs.valorcapitalgroup.com/companies",
            "collectionId",
            "299",
        ),
        "allhands": (
            "getro",
            "https://jobs.all-hands.us/companies",
            "collectionId",
            "634",
        ),
        "thepeoplepeoplegroup": (
            "getro",
            "https://jobs.thepeoplepeoplegroup.com/companies",
            "collectionId",
            "42266",
        ),
        "sandscapitalventures": (
            "getro",
            "https://jobs.sandscapitalventures.com/companies",
            "collectionId",
            "1638",
        ),
        "vcet": ("getro", "https://jobs.vcet.co/companies", "collectionId", "15470"),
        "nzero": ("getro", "https://nzero.getro.com/companies", "collectionId", "4218"),
        "quona": ("getro", "https://jobs.quona.com/companies", "collectionId", "313"),
        "obvious": (
            "getro",
            "https://jobs.obvious.com/companies",
            "collectionId",
            "69",
        ),
        "4dxventures": (
            "getro",
            "https://careers.4dxventures.com/companies",
            "collectionId",
            "11906",
        ),
        "outlierventures": (
            "getro",
            "https://jobs.outlierventures.io/companies",
            "collectionId",
            "1524",
        ),
        "morpheus": (
            "getro",
            "https://jobs.morpheus.com/companies",
            "collectionId",
            "10916",
        ),
        "byfounders": (
            "getro",
            "https://jobs.byfounders.vc/companies",
            "collectionId",
            "248",
        ),
        "ibexinvestors": (
            "getro",
            "https://jobs.ibexinvestors.com/companies",
            "collectionId",
            "1081",
        ),
        "outsidersfund": (
            "getro",
            "https://jobs.outsidersfund.com/companies",
            "collectionId",
            "6956",
        ),
        "sogalventures": (
            "getro",
            "https://jobs.sogalventures.com/companies",
            "collectionId",
            "136",
        ),
        "fabervc": (
            "getro",
            "https://talent.faber.vc/companies",
            "collectionId",
            "2601",
        ),
        "jumpcrypto": (
            "getro",
            "https://jobs.jumpcrypto.com/companies",
            "collectionId",
            "20916",
        ),
        "superseed": (
            "getro",
            "https://careers.superseed.com/companies",
            "collectionId",
            "7088",
        ),
        "socialleverage": (
            "getro",
            "https://jobs.socialleverage.com/companies",
            "collectionId",
            "1371",
        ),
        "intudovc": (
            "getro",
            "https://careers.intudovc.com/companies",
            "collectionId",
            "1177",
        ),
        "polkadot": (
            "getro",
            "https://jobs.polkadot.com/companies",
            "collectionId",
            "11180",
        ),
        "traveltechessentialist": (
            "getro",
            "https://jobs.traveltechessentialist.com/companies",
            "collectionId",
            "7682",
        ),
        "folklorevc": (
            "getro",
            "https://roles.folklore.vc/companies",
            "collectionId",
            "1730",
        ),
        "alphapartners": (
            "getro",
            "https://jobs.alphapartners.com/companies",
            "collectionId",
            "1541",
        ),
        "emeraldmanagers": (
            "getro",
            "https://careers.emeraldmanagers.com/companies",
            "collectionId",
            "1448",
        ),
        "syndicateone": (
            "getro",
            "https://syndicate-one.getro.com/companies",
            "collectionId",
            "15503",
        ),
        "dukecapitalpartners": (
            "getro",
            "https://jobs.dukecapitalpartners.duke.edu/companies",
            "collectionId",
            "2734",
        ),
        "inuplands": (
            "getro",
            "https://jobs.inuplands.org/companies",
            "collectionId",
            "8606",
        ),
        "bnbchain": (
            "getro",
            "https://jobs.bnbchain.org/companies",
            "collectionId",
            "3788",
        ),
        "endicottgp": (
            "getro",
            "https://jobs.endicottgp.com/companies",
            "collectionId",
            "7352",
        ),
        "arborview": (
            "getro",
            "https://arborview.getro.com/companies",
            "collectionId",
            "1492",
        ),
        "hashed": (
            "consider",
            "https://consider.com/boards/vc/hashed/companies",
            "board",
            "hashed",
        ),
        "hummingbirdventures": (
            "consider",
            "https://consider.com/boards/vc/hummingbird-ventures/companies",
            "board",
            "hummingbird-ventures",
        ),
        "remotely": (
            "consider",
            "https://consider.com/boards/vc/remotely/companies",
            "board",
            "remotely",
        ),
        "datapowerventures": (
            "consider",
            "https://consider.com/boards/vc/datapower-ventures/companies",
            "board",
            "datapower-ventures",
        ),
        "lightrock": (
            "consider",
            "https://consider.com/boards/vc/lightrock/companies",
            "board",
            "lightrock",
        ),
        "foxmontcapital": (
            "consider",
            "https://consider.com/boards/vc/foxmont-capital/companies",
            "board",
            "foxmont-capital",
        ),
        "adgm": (
            "consider",
            "https://consider.com/boards/vc/adgm/companies",
            "board",
            "adgm",
        ),
        "hcvc": ("consider", "https://jobs.hcvc.co/companies", "board", "hcvc"),
        "onepeak": (
            "consider",
            "https://jobs.onepeak.tech/companies",
            "board",
            "one-peak",
        ),
        "sprints": (
            "consider",
            "https://jobs.sprints.com/companies",
            "board",
            "sprints",
        ),
        "bfnjobs": (
            "public_page",
            "https://bfn-jobs.entrepreneurs.utoronto.ca/companies",
            "observedStatus",
            "not_found",
        ),
        "closedlooppartners": (
            "public_page",
            "https://jobs.closedlooppartners.com/companies",
            "observedStatus",
            "not_found",
        ),
        "terae": ("getro", "https://terae.getro.com/companies", "collectionId", "871"),
        "schmidtmarine": (
            "getro",
            "https://jobs.schmidtmarine.org/companies",
            "collectionId",
            "110",
        ),
        "concorde": (
            "getro",
            "https://talent.concorde.network/companies",
            "collectionId",
            "9695",
        ),
        "fireup": (
            "getro",
            "https://jobs.fire-up.net/companies",
            "collectionId",
            "9893",
        ),
        "dragonfly": (
            "getro",
            "https://jobs.dragonfly.xyz/companies",
            "collectionId",
            "1118",
        ),
        "delphiventures": (
            "getro",
            "https://jobs.delphiventures.io/companies",
            "collectionId",
            "1440",
        ),
        "levelequity": (
            "getro",
            "https://portfoliocareers.levelequity.com/companies",
            "collectionId",
            "1729",
        ),
        "floridafunders": (
            "getro",
            "https://jobs.floridafunders.com/companies",
            "collectionId",
            "781",
        ),
        "electriccapital": (
            "getro",
            "https://jobs.electriccapital.com/companies",
            "collectionId",
            "1640",
        ),
        "launchcapital": (
            "getro",
            "https://jobs.launchcapital.com/companies",
            "collectionId",
            "109",
        ),
        "flashpointvc": (
            "getro",
            "https://jobs.flashpointvc.com/companies",
            "collectionId",
            "11513",
        ),
        "suffolktech": (
            "getro",
            "https://careers.suffolktech.com/companies",
            "collectionId",
            "9596",
        ),
        "blackhornvc": (
            "getro",
            "https://careers.blackhornvc.com/companies",
            "collectionId",
            "2733",
        ),
        "nascent": (
            "getro",
            "https://jobs.nascent.xyz/companies",
            "collectionId",
            "5372",
        ),
        "uvcpartners": (
            "getro",
            "https://talent.uvcpartners.com/companies",
            "collectionId",
            "3062",
        ),
        "blueventurefund": (
            "getro",
            "https://jobs.blueventurefund.com/companies",
            "collectionId",
            "145",
        ),
        "liveoakvp": (
            "getro",
            "https://jobs.liveoakvp.com/companies",
            "collectionId",
            "946",
        ),
        "tlvpartners": (
            "getro",
            "https://jobs.tlv.partners/companies",
            "collectionId",
            "190",
        ),
        "atxventurepartners": (
            "getro",
            "https://jobs.atxventurepartners.com/companies",
            "collectionId",
            "325",
        ),
        "moneta": ("getro", "https://jobs.moneta.vc/companies", "collectionId", "1015"),
        "cedarparktexasedc": (
            "getro",
            "https://jobs.cedarparktexasedc.com/companies",
            "collectionId",
            "803",
        ),
        "petersonventures": (
            "getro",
            "https://jobs.petersonventures.com/companies",
            "collectionId",
            "395",
        ),
        "beliade": (
            "getro",
            "https://jobs.beliade.co/companies",
            "collectionId",
            "191",
        ),
        "oifvc": ("getro", "https://oifvc.getro.com/companies", "collectionId", "1265"),
        "updata": (
            "getro",
            "https://jobs.updata.com/companies",
            "collectionId",
            "3128",
        ),
        "uphonestcapital": (
            "getro",
            "https://uphonestcapital.getro.com/companies",
            "collectionId",
            "1733",
        ),
        "nebraskaangels": (
            "getro",
            "https://careers.nebraskaangels.org/companies",
            "collectionId",
            "7286",
        ),
        "trailheadcap": (
            "getro",
            "https://trailheadcap.getro.com/companies",
            "collectionId",
            "1493",
        ),
        "ballisticventures": (
            "getro",
            "https://careers.ballisticventures.com/companies",
            "collectionId",
            "8441",
        ),
        "thehelm": (
            "getro",
            "https://jobs.thehelm.co/companies",
            "collectionId",
            "1519",
        ),
        "supercellinvestments": (
            "getro",
            "https://supercellinvestments.getro.com/companies",
            "collectionId",
            "12500",
        ),
        "revelpartners": (
            "getro",
            "https://jobs.revelpartners.com/companies",
            "collectionId",
            "683",
        ),
        "sandboxindustries": (
            "getro",
            "https://jobs.sandboxindustries.com/companies",
            "collectionId",
            "877",
        ),
        "eoventures": (
            "getro",
            "https://jobs.eoventures.com/companies",
            "collectionId",
            "14018",
        ),
        "blindspot": (
            "getro",
            "https://blindspot.getro.com/companies",
            "collectionId",
            "1497",
        ),
        "placeholder": (
            "getro",
            "https://jobs.placeholder.vc/companies",
            "collectionId",
            "922",
        ),
        "blacktalentdatabase": (
            "getro",
            "https://jobs.blacktalentdatabase.com/companies",
            "collectionId",
            "10982",
        ),
        "foresitecapital": (
            "consider",
            "https://consider.com/boards/vc/foresite-capital/companies",
            "board",
            "foresite-capital",
        ),
        "paradigmxyz": (
            "consider",
            "https://consider.com/boards/vc/paradigm-xyz/companies",
            "board",
            "paradigm-xyz",
        ),
        "griffingp": (
            "consider",
            "https://careers.griffingp.com/companies",
            "board",
            "griffin-gaming",
        ),
        "allinmilwaukee": (
            "consider",
            "https://consider.com/boards/vc/all-in-milwaukee/companies",
            "board",
            "all-in-milwaukee",
        ),
        "struckcapital": (
            "consider",
            "https://consider.com/boards/vc/struck-capital/companies",
            "board",
            "struck-capital",
        ),
        "seventyseven": (
            "consider",
            "https://consider.com/boards/vc/seventy-seven/companies",
            "board",
            "seventy-seven",
        ),
        "nv": (
            "consider",
            "https://consider.com/boards/vc/nv/companies",
            "board",
            "nv",
        ),
        "tcgcrypto": (
            "consider",
            "https://consider.com/boards/vc/tcg-crypto/companies",
            "board",
            "tcg-crypto",
        ),
        "longgame": (
            "consider",
            "https://consider.com/boards/vc/longgame/companies",
            "board",
            "longgame",
        ),
        "baincrypto": (
            "consider",
            "https://consider.com/boards/vc/bain-crypto/companies",
            "board",
            "bain-crypto",
        ),
        "2048vc": (
            "public_page",
            "https://www.2048.vc/companies",
            "observedStatus",
            "verified_public_page",
        ),
        "defy": (
            "public_page",
            "https://defy.vc/companies/",
            "observedStatus",
            "verified_public_page",
        ),
        "unshackledvc": (
            "public_page",
            "https://www.unshackledvc.com/portfolio",
            "observedStatus",
            "verified_public_page",
        ),
        "clevelandtalent": (
            "getro",
            "https://jobs.clevelandtalent.org/companies",
            "collectionId",
            "clevelandtalent",
        ),
        "highfivepartners": (
            "getro",
            "https://jobs.highfivepartners.com/companies",
            "collectionId",
            "highfivepartners",
        ),
        "indiebio": (
            "consider",
            "https://indiebio.board.staging.consider.com/companies",
            "board",
            "indiebio",
        ),
        "entrepreneurs": (
            "getro",
            "https://jobs.entrepreneurs.utoronto.ca/companies",
            "collectionId",
            "entrepreneurs",
        ),
        "morestartshere": (
            "getro",
            "https://careers.morestartshere.com/companies",
            "collectionId",
            "morestartshere",
        ),
        "makeitcu": (
            "getro",
            "https://jobs.makeitcu.com/companies",
            "collectionId",
            "makeitcu",
        ),
        "innovationworks": (
            "getro",
            "https://jobs.innovationworks.org/companies",
            "collectionId",
            "innovationworks",
        ),
        "charlestonorg": (
            "getro",
            "https://jobs.charlestoncareers.org/companies",
            "collectionId",
            "charlestonorg",
        ),
        "greatersatx": (
            "getro",
            "https://careers.greatersatx.com/companies",
            "collectionId",
            "greatersatx",
        ),
        "inwomenshealth": (
            "getro",
            "https://jobs.inwomenshealth.com/companies",
            "collectionId",
            "inwomenshealth",
        ),
        "skagit": (
            "getro",
            "https://jobs.skagit.org/companies",
            "collectionId",
            "skagit",
        ),
        "workforceinnovationcenter": (
            "getro",
            "https://careers.workforceinnovationcenter.com/companies",
            "collectionId",
            "workforceinnovationcenter",
        ),
        "jobswithnoboss": (
            "getro",
            "https://jobs.jobswithnoboss.com/companies",
            "collectionId",
            "jobswithnoboss",
        ),
        "grandforksiscooler": (
            "getro",
            "https://jobs.grandforksiscooler.com/companies",
            "collectionId",
            "grandforksiscooler",
        ),
        "spirittechcollective": (
            "getro",
            "https://jobs.spirit-tech-collective.com/companies",
            "collectionId",
            "spirittechcollective",
        ),
        "imecistart": (
            "getro",
            "https://jobs.imecistart.com/companies",
            "collectionId",
            "imecistart",
        ),
        "abundancenetwork": (
            "getro",
            "https://jobs.abundancenetwork.com/companies",
            "collectionId",
            "abundancenetwork",
        ),
        "ablepartners": (
            "getro",
            "https://careers.ablepartners.nyc/companies",
            "collectionId",
            "ablepartners",
        ),
        "sierraventures": (
            "getro",
            "https://careers.sierraventures.com/companies",
            "collectionId",
            "sierraventures",
        ),
        "alkeon": (
            "getro",
            "https://jobs.alkeon.com/companies",
            "collectionId",
            "alkeon",
        ),
        "vertexventures": (
            "getro",
            "https://jobs.vertexventures.co.il/companies",
            "collectionId",
            "vertexventures",
        ),
        "kdtvc": ("getro", "https://jobs.kdtvc.com/companies", "collectionId", "kdtvc"),
        "boxgroup": (
            "public_page",
            "https://www.boxgroup.com/portfolio",
            "label",
            "BoxGroup",
        ),
        "flybridge": (
            "public_page",
            "https://www.flybridge.com/portfolio",
            "label",
            "Flybridge",
        ),
        "s2ginvestments": (
            "public_page",
            "https://www.s2ginvestments.com/team/careers/open-positions",
            "label",
            "S2G Investments",
        ),
        "moberlyedc": (
            "getro",
            "https://jobs.moberly-edc.com/companies",
            "collectionId",
            "moberlyedc",
        ),
        "weareadamarie": (
            "getro",
            "https://jobs.weareadamarie.com/companies",
            "collectionId",
            "weareadamarie",
        ),
        "arbitrum": (
            "getro",
            "https://jobs.arbitrum.io/companies",
            "collectionId",
            "arbitrum",
        ),
        "oneventures": (
            "getro",
            "https://jobs.one-ventures.com.au/companies",
            "collectionId",
            "oneventures",
        ),
        "choosemketech": (
            "getro",
            "https://jobs.choosemketech.org/companies",
            "collectionId",
            "choosemketech",
        ),
        "vistria": (
            "consider",
            "https://consider.com/boards/vc/vistria/companies",
            "board",
            "vistria",
        ),
        "healthxventures": (
            "getro",
            "https://jobs.healthxventures.com/companies",
            "collectionId",
            "healthxventures",
        ),
        "watershed": (
            "getro",
            "https://portfolio.watershed.vc/companies",
            "collectionId",
            "watershed",
        ),
        "13bookscapital": (
            "getro",
            "https://careers.13bookscapital.com/companies",
            "collectionId",
            "13bookscapital",
        ),
        "future": (
            "getro",
            "https://jobs.future.ventures/companies",
            "collectionId",
            "future",
        ),
        "vamosventures": (
            "getro",
            "https://jobs.vamosventures.com/companies",
            "collectionId",
            "vamosventures",
        ),
        "peoplefunction": (
            "getro",
            "https://jobs.peoplefunction.com/companies",
            "collectionId",
            "peoplefunction",
        ),
        "ironspring": (
            "getro",
            "https://jobs.ironspring.com/companies",
            "collectionId",
            "ironspring",
        ),
        "forward": (
            "getro",
            "https://careers.forward.one/companies",
            "collectionId",
            "forward",
        ),
        "noromoseley": (
            "getro",
            "https://careers.noromoseley.com/companies",
            "collectionId",
            "noromoseley",
        ),
        "hopelab": (
            "getro",
            "https://hopelab.getro.com/companies",
            "collectionId",
            "hopelab",
        ),
        "seaeventures": (
            "getro",
            "https://careers.seaeventures.com/companies",
            "collectionId",
            "seaeventures",
        ),
        "stventureslab": (
            "getro",
            "https://careers.stventureslab.com/companies",
            "collectionId",
            "stventureslab",
        ),
        "buoyant": (
            "getro",
            "https://careers.buoyant.vc/companies",
            "collectionId",
            "buoyant",
        ),
        "sixty8": (
            "getro",
            "https://jobs.sixty8.capital/companies",
            "collectionId",
            "sixty8",
        ),
        "valtruis": (
            "consider",
            "https://careers.valtruis.com/companies",
            "board",
            "valtruis",
        ),
        "dcedc": (
            "getro",
            "https://careers.dcedc.org/companies",
            "collectionId",
            "dcedc",
        ),
        "workinseguin": (
            "getro",
            "https://www.workinseguin.com/companies",
            "collectionId",
            "workinseguin",
        ),
        "whatsupstateny": (
            "getro",
            "https://jobs.whatsupstateny.com/companies",
            "collectionId",
            "whatsupstateny",
        ),
        "myjonesborocom": (
            "getro",
            "https://jobs.myjonesborojobs.com/companies",
            "collectionId",
            "myjonesborocom",
        ),
        "uprotterdam": (
            "getro",
            "https://jobs.uprotterdam.com/companies",
            "collectionId",
            "uprotterdam",
        ),
        "masscybercenter": (
            "getro",
            "https://jobs.masscybercenter.org/companies",
            "collectionId",
            "masscybercenter",
        ),
        "toledoregion": (
            "getro",
            "https://jobs.toledoregion.com/companies",
            "collectionId",
            "toledoregion",
        ),
        "workinba": (
            "getro",
            "https://careers.workinba.com/companies",
            "collectionId",
            "workinba",
        ),
        "onewagonercounty": (
            "getro",
            "https://jobs.onewagonercounty.com/companies",
            "collectionId",
            "onewagonercounty",
        ),
        "rockfordchamber": (
            "getro",
            "https://jobs.rockfordchamber.com/companies",
            "collectionId",
            "rockfordchamber",
        ),
        "placetobelnk": (
            "getro",
            "https://jobs.placetobelnk.com/companies",
            "collectionId",
            "placetobelnk",
        ),
        "maip": (
            "getro",
            "https://jobs.maip.com/companies",
            "collectionId",
            "maip",
        ),
        "inovait": (
            "getro",
            "https://jobs.inovait.ca/companies",
            "collectionId",
            "inovait",
        ),
        "mehi": (
            "getro",
            "https://jobs.mehi.masstech.org/companies",
            "collectionId",
            "mehi",
        ),
        "peak": (
            "getro",
            "https://jobs.peak.capital/companies",
            "collectionId",
            "peak",
        ),
        "vmgpartners": (
            "getro",
            "https://jobs.vmgpartners.com/companies",
            "collectionId",
            "vmgpartners",
        ),
        "nucleuscapital": (
            "getro",
            "https://careers.nucleus-capital.com/companies",
            "collectionId",
            "nucleuscapital",
        ),
        "swayvc": (
            "getro",
            "https://talent.swayvc.com/companies",
            "collectionId",
            "swayvc",
        ),
        "fayettechamber": (
            "getro",
            "https://careers.fayettechamber.org/companies",
            "collectionId",
            "fayettechamber",
        ),
        "smartfinvc": (
            "getro",
            "https://jobs.smartfinvc.com/companies",
            "collectionId",
            "smartfinvc",
        ),
        "saintjoseph": (
            "getro",
            "https://jobs.saintjoseph.com/companies",
            "collectionId",
            "saintjoseph",
        ),
        "nbchamber": (
            "getro",
            "https://jobs.nbchamber.com/companies",
            "collectionId",
            "nbchamber",
        ),
        "ssedc": (
            "getro",
            "https://jobs.ss-edc.com/companies",
            "collectionId",
            "ssedc",
        ),
        "innovate": (
            "getro",
            "https://jobs.innovate.ms/companies",
            "collectionId",
            "innovate",
        ),
        "kayyakventures": (
            "getro",
            "https://jobs.kayyakventures.com/companies",
            "collectionId",
            "kayyakventures",
        ),
        "hetz": (
            "getro",
            "https://careers.hetz.vc/companies",
            "collectionId",
            "hetz",
        ),
        "connexacapital": (
            "getro",
            "https://careers.connexacapital.com/companies",
            "collectionId",
            "connexacapital",
        ),
        "skale": (
            "getro",
            "https://jobs.skale.space/companies",
            "collectionId",
            "skale",
        ),
        "georgetown": (
            "getro",
            "https://georgetown.getro.com/companies",
            "collectionId",
            "georgetown",
        ),
        "alpinesg": (
            "getro",
            "https://jobs.alpinesg.com/companies",
            "collectionId",
            "alpinesg",
        ),
        "lumoscapitalgroup": (
            "getro",
            "https://lumoscapitalgroup.getro.com/companies",
            "collectionId",
            "lumoscapitalgroup",
        ),
        "southparkcommonsvc": (
            "consider",
            "https://consider.com/boards/vc/south-park-commons/companies",
            "board",
            "southparkcommonsvc",
        ),
        "lcattertonvc": (
            "consider",
            "https://consider.com/boards/vc/l-catterton/companies",
            "board",
            "lcattertonvc",
        ),
        "evpvc": (
            "consider",
            "https://consider.com/boards/vc/evp/companies",
            "board",
            "evpvc",
        ),
        "firstround": (
            "public_page",
            "https://www.firstround.com/companies",
            "label",
            "First Round",
        ),
        "foundersfund": (
            "public_page",
            "https://foundersfund.com/portfolio/",
            "label",
            "Founders Fund",
        ),
        "slow": (
            "public_page",
            "https://slow.co/portfolio/",
            "label",
            "Slow Ventures",
        ),
        "gpv": (
            "public_page",
            "https://www.gpv.com/companies",
            "label",
            "GPV",
        ),
        "villageglobal": (
            "public_page",
            "https://www.villageglobal.com/portfolio",
            "label",
            "Village Global",
        ),
        "foundercollective": (
            "public_page",
            "https://foundercollective.com/portfolio/",
            "label",
            "Founder Collective",
        ),
        "bowerycap": (
            "public_page",
            "https://bowerycap.com/portfolio",
            "label",
            "Bowery Capital",
        ),
        "pillar": (
            "public_page",
            "https://www.pillar.vc/companies/",
            "label",
            "Pillar",
        ),
        "spero": (
            "public_page",
            "https://spero.vc/portfolio/",
            "label",
            "Spero Ventures",
        ),
        "felixcap": (
            "public_page",
            "https://www.felixcap.com/portfolio",
            "label",
            "Felix Capital",
        ),
        "blume": (
            "public_page",
            "https://blume.vc/startups",
            "label",
            "Blume Ventures",
        ),
        "elevationcapital": (
            "public_page",
            "https://www.elevationcapital.com/portfolio",
            "label",
            "Elevation Capital",
        ),
        "chiratae": (
            "public_page",
            "https://www.chiratae.com/companies/",
            "label",
            "Chiratae Ventures",
        ),
        "endiya": (
            "public_page",
            "https://www.endiya.com/portfolio",
            "label",
            "Endiya Partners",
        ),
        "eqtgroup": (
            "public_page",
            "https://eqtgroup.com/about/current-portfolio",
            "label",
            "EQT",
        ),
        "heartcore": (
            "public_page",
            "https://www.heartcore.com/companies",
            "label",
            "Heartcore",
        ),
        "hofcapital": (
            "public_page",
            "https://hofcapital.com/portfolio/",
            "label",
            "Hof Capital",
        ),
        "plus": (
            "public_page",
            "https://plus.vc/investments-portfolio",
            "label",
            "Plus VC",
        ),
        "venturesouq": (
            "public_page",
            "https://www.venturesouq.com/portfolio",
            "label",
            "Venturesouq",
        ),
        "saviu": (
            "public_page",
            "https://www.saviu.vc/portfolio",
            "label",
            "Saviu Ventures",
        ),
        "phxfwd": (
            "getro",
            "https://jobs.phxfwd.org/companies",
            "collectionId",
            "phxfwd",
        ),
        "foodtechscout": (
            "getro",
            "https://jobs.foodtechscout.com/companies",
            "collectionId",
            "foodtechscout",
        ),
        "i2bf": ("getro", "https://talent.i2bf.com/companies", "collectionId", "i2bf"),
        "narreach": (
            "getro",
            "https://careers.narreach.com/companies",
            "collectionId",
            "narreach",
        ),
        "coinfund": (
            "getro",
            "https://jobs.coinfund.io/companies",
            "collectionId",
            "coinfund",
        ),
        "matchstickventures": (
            "getro",
            "https://jobs.matchstickventures.com/companies",
            "collectionId",
            "matchstickventures",
        ),
        "plugandplayfoundation": (
            "getro",
            "https://accessopportunities.plugandplayfoundation.org/companies",
            "collectionId",
            "plugandplayfoundation",
        ),
        "castleisland": (
            "getro",
            "https://jobs.castleisland.vc/companies",
            "collectionId",
            "castleisland",
        ),
        "togethxr": (
            "getro",
            "https://jobs.togethxr.com/companies",
            "collectionId",
            "togethxr",
        ),
        "edomarketplace": (
            "getro",
            "https://edomarketplace.getro.com/companies",
            "collectionId",
            "edomarketplace",
        ),
        "cantos": (
            "getro",
            "https://jobs.cantos.vc/companies",
            "collectionId",
            "cantos",
        ),
        "silvertonpartners": (
            "getro",
            "https://jobs.silvertonpartners.com/companies",
            "collectionId",
            "silvertonpartners",
        ),
        "gfrfund": (
            "getro",
            "https://jobs.gfrfund.com/companies",
            "collectionId",
            "gfrfund",
        ),
        "fortinocapital": (
            "getro",
            "https://talent.fortinocapital.com/companies",
            "collectionId",
            "fortinocapital",
        ),
        "ziggtalent": (
            "getro",
            "https://jobs.ziggtalent.com/companies",
            "collectionId",
            "ziggtalent",
        ),
        "drivetlv": (
            "getro",
            "https://jobs.drivetlv.com/companies",
            "collectionId",
            "drivetlv",
        ),
        "startmunich": (
            "getro",
            "https://jobs.startmunich.de/companies",
            "collectionId",
            "startmunich",
        ),
        "definitioncap": (
            "getro",
            "https://jobs.definitioncap.com/companies",
            "collectionId",
            "definitioncap",
        ),
        "almazcapital": (
            "getro",
            "https://jobs.almazcapital.com/companies",
            "collectionId",
            "almazcapital",
        ),
        "spartangroup": (
            "getro",
            "https://jobs.spartangroup.io/companies",
            "collectionId",
            "spartangroup",
        ),
        "jdssports": (
            "getro",
            "https://jobs.jdssports.co/companies",
            "collectionId",
            "jdssports",
        ),
        "lyragrowth": (
            "getro",
            "https://jobs.lyragrowth.com/companies",
            "collectionId",
            "lyragrowth",
        ),
        "theadclub": (
            "getro",
            "https://careers.theadclub.org/companies",
            "collectionId",
            "theadclub",
        ),
        "tnentertainment": (
            "getro",
            "https://jobs.tnentertainment.com/companies",
            "collectionId",
            "tnentertainment",
        ),
        "rowanedc": (
            "getro",
            "https://jobs.rowanedc.com/companies",
            "collectionId",
            "rowanedc",
        ),
        "clarksvilleishiring": (
            "getro",
            "https://jobs.clarksvilleishiring.com/companies",
            "collectionId",
            "clarksvilleishiring",
        ),
        "flintandgenesee": (
            "getro",
            "https://jobs.flintandgenesee.org/companies",
            "collectionId",
            "flintandgenesee",
        ),
        "growingreenvillenc": (
            "getro",
            "https://jobs.growingreenvillenc.com/companies",
            "collectionId",
            "growingreenvillenc",
        ),
        "selectpriorinvestments": (
            "consider",
            "https://consider.com/boards/vc/select-prior-investments/companies",
            "board",
            "selectpriorinvestments",
        ),
        "fjlabs": ("public_page", "https://fjlabs.com/portfolio", "label", "FJ Labs"),
        "climatecapital": (
            "public_page",
            "https://www.climatecapital.co/portfolio",
            "label",
            "Climate Capital",
        ),
        "shorooq": (
            "public_page",
            "https://www.shorooq.com/portfolio",
            "label",
            "Shorooq",
        ),
        "picuscap": (
            "public_page",
            "https://www.picuscap.com/portfolio/",
            "label",
            "Picus Capital",
        ),
        "portageinvest": (
            "public_page",
            "https://portageinvest.com/portfolio/",
            "label",
            "Portage",
        ),
        "canary": (
            "public_page",
            "https://www.canary.com.br/portfolio/",
            "label",
            "Canary",
        ),
        "raed": ("public_page", "https://raed.vc/portfolio/", "label", "Raed"),
        "tlcomcapital": (
            "public_page",
            "https://tlcomcapital.com/portfolio",
            "label",
            "TLcom Capital",
        ),
        "omnivore": (
            "public_page",
            "https://omnivore.vc/portfolio",
            "label",
            "Omnivore",
        ),
        "3one4capital": (
            "public_page",
            "https://www.3one4capital.com/portfolio",
            "label",
            "3one4 Capital",
        ),
        "jungle": (
            "public_page",
            "https://www.jungle.vc/portfolio",
            "label",
            "Jungle Ventures",
        ),
        "qualgro": (
            "public_page",
            "https://qualgro.com/portfolio/",
            "label",
            "Qualgro",
        ),
        "earthshot": (
            "public_page",
            "https://www.earthshot.vc/companies",
            "label",
            "Earthshot",
        ),
        "daphni": (
            "public_page",
            "https://www.daphni.com/portfolio",
            "label",
            "Daphni",
        ),
        "elaia": ("public_page", "https://www.elaia.com/companies/", "label", "Elaia"),
        "carbonthirteen": (
            "public_page",
            "https://carbonthirteen.com/our-portfolio/",
            "label",
            "Carbon Thirteen",
        ),
        "regeneration": (
            "public_page",
            "https://regeneration.vc/portfolio",
            "label",
            "Regeneration",
        ),
        "boldstart": (
            "public_page",
            "https://boldstart.vc/companies/",
            "label",
            "Boldstart",
        ),
        "bedrockcap": (
            "public_page",
            "https://bedrockcap.com/investments",
            "label",
            "Bedrock Capital",
        ),
        "passioncapital": (
            "public_page",
            "https://passioncapital.com/fund-portfolio/",
            "label",
            "Passion Capital",
        ),
        "alignedclimatecapital": (
            "public_page",
            "https://alignedclimatecapital.com/portfolio/",
            "label",
            "Aligned Climate Capital",
        ),
        "economicdevelopmentjobs": (
            "getro",
            "https://economicdevelopmentjobs.getro.com/companies",
            "collectionId",
            "economicdevelopmentjobs",
        ),
        "get2knownoke": (
            "consider",
            "https://jobs.get2knownoke.com/companies",
            "board",
            "get2knownoke",
        ),
        "whiteboardadvisors": (
            "consider",
            "https://jobs.whiteboardadvisors.com/companies",
            "board",
            "whiteboardadvisors",
        ),
        "firstroundcapital": (
            "consider",
            "https://consider.com/boards/vc/first-round-capital/companies",
            "board",
            "firstroundcapital",
        ),
        "impactsource": (
            "consider",
            "https://www.impactsource.ai/jobs",
            "board",
            "impactsource",
        ),
        "growenid": (
            "getro",
            "https://jobs.growenid.com/companies",
            "collectionId",
            "growenid",
        ),
        "techsquareventures": (
            "getro",
            "https://jobs.techsquareventures.com/companies",
            "collectionId",
            "techsquareventures",
        ),
        "s32": (
            "getro",
            "https://s32.getro.com/companies",
            "collectionId",
            "s32",
        ),
        "peoria": (
            "getro",
            "https://jobs.peoria.org/companies",
            "collectionId",
            "peoria",
        ),
        "amazingcolumbusga": (
            "getro",
            "https://work.amazingcolumbusga.com/companies",
            "collectionId",
            "amazingcolumbusga",
        ),
        "portmuskogee": (
            "getro",
            "https://jobs.portmuskogee.com/companies",
            "collectionId",
            "portmuskogee",
        ),
        "ton": (
            "getro",
            "https://jobs.ton.org/companies",
            "collectionId",
            "ton",
        ),
        "prospect": (
            "consider",
            "https://consider.com/boards/vc/prospect/companies",
            "board",
            "prospect",
        ),
        "riverside": (
            "consider",
            "https://consider.com/boards/vc/riverside/companies",
            "board",
            "riverside",
        ),
        "owlvc": (
            "consider",
            "https://careers.owlvc.com/companies",
            "board",
            "owlvc",
        ),
        "joplincc": (
            "getro",
            "https://jobs.joplincc.com/companies",
            "collectionId",
            "joplincc",
        ),
        "powerlines": (
            "getro",
            "https://careers.powerlines.org/companies",
            "collectionId",
            "powerlines",
        ),
        "thecentermemphis": (
            "getro",
            "https://jobs.thecentermemphis.org/companies",
            "collectionId",
            "thecentermemphis",
        ),
        "silversmith": (
            "getro",
            "https://careers.silversmith.com/companies",
            "collectionId",
            "silversmith",
        ),
        "limitlessdecatur": (
            "getro",
            "https://jobs.limitlessdecatur.com/companies",
            "collectionId",
            "limitlessdecatur",
        ),
        "workupcoweta": (
            "getro",
            "https://careers.workupcoweta.com/companies",
            "collectionId",
            "workupcoweta",
        ),
        "hellowestmichigan": (
            "getro",
            "https://jobs.hellowestmichigan.com/companies",
            "collectionId",
            "hellowestmichigan",
        ),
        "portageinvestvc": (
            "getro",
            "https://careers.portageinvest.com/companies",
            "collectionId",
            "portageinvestvc",
        ),
        "edbi": (
            "consider",
            "https://consider.com/boards/vc/edbi/companies",
            "board",
            "edbi",
        ),
        "firstmomentum": (
            "getro",
            "https://jobs.firstmomentum.vc/companies",
            "collectionId",
            "firstmomentum",
        ),
        "muus": (
            "consider",
            "https://consider.com/boards/vc/muus/companies",
            "board",
            "muus",
        ),
        "anthoscapital": (
            "consider",
            "https://consider.com/boards/vc/anthos-capital/companies",
            "board",
            "anthoscapital",
        ),
        "merantixaicampus": (
            "getro",
            "https://careers.merantix-aicampus.com/companies",
            "collectionId",
            "merantixaicampus",
        ),
        "proptech1": (
            "consider",
            "https://consider.com/boards/vc/proptech1/companies",
            "board",
            "proptech1",
        ),
        "motherventures": (
            "getro",
            "https://jobs.mother-ventures.com/companies",
            "collectionId",
            "motherventures",
        ),
        "spectrumequity": (
            "getro",
            "https://careers.spectrumequity.com/companies",
            "collectionId",
            "spectrumequity",
        ),
        "ridgeline": (
            "getro",
            "https://jobs.ridgeline.vc/companies",
            "collectionId",
            "ridgeline",
        ),
        "avax": (
            "getro",
            "https://jobs.avax.network/companies",
            "collectionId",
            "avax",
        ),
        "omnivorevc": (
            "getro",
            "https://jobs.omnivore.vc/companies",
            "collectionId",
            "omnivorevc",
        ),
        "investnebraska": (
            "getro",
            "https://jobs.investnebraska.com/companies",
            "collectionId",
            "investnebraska",
        ),
        "firstmilevc": (
            "getro",
            "https://jobs.firstmilevc.com/companies",
            "collectionId",
            "firstmilevc",
        ),
        "dlcda": (
            "getro",
            "https://careers.dlcda.com/companies",
            "collectionId",
            "dlcda",
        ),
        "leadershiptriangle": (
            "getro",
            "https://jobs.leadershiptriangle.com/companies",
            "collectionId",
            "leadershiptriangle",
        ),
        "glasswing": (
            "getro",
            "https://jobs.glasswing.vc/companies",
            "collectionId",
            "glasswing",
        ),
        "fulcrumep": (
            "getro",
            "https://jobs.fulcrumep.com/companies",
            "collectionId",
            "fulcrumep",
        ),
        "prudence": (
            "getro",
            "https://jobs.prudence.vc/companies",
            "collectionId",
            "prudence",
        ),
        "fannindevelopment": (
            "getro",
            "https://jobs.fannindevelopment.com/companies",
            "collectionId",
            "fannindevelopment",
        ),
        "developmilledgeville": (
            "getro",
            "https://careers.developmilledgeville.com/companies",
            "collectionId",
            "developmilledgeville",
        ),
        "swanandlegend": (
            "getro",
            "https://jobs.swanandlegend.com/companies",
            "collectionId",
            "swanandlegend",
        ),
        "blackwellnow": (
            "getro",
            "https://jobs.blackwellnow.org/companies",
            "collectionId",
            "blackwellnow",
        ),
        "emanuelchamber": (
            "getro",
            "https://careers.emanuelchamber.org/companies",
            "collectionId",
            "emanuelchamber",
        ),
        "jvpvc": (
            "consider",
            "https://jobs.jvpvc.com/companies",
            "board",
            "jvpvc",
        ),
        "psl": (
            "consider",
            "https://jobs.psl.com/companies",
            "board",
            "psl",
        ),
        "story": (
            "getro",
            "https://careers.story.foundation/companies",
            "collectionId",
            "story",
        ),
        "hannahgrey": (
            "getro",
            "https://hannahgrey.getro.com/companies",
            "collectionId",
            "hannahgrey",
        ),
        "hax": (
            "consider",
            "https://jobs.hax.co/companies",
            "board",
            "hax",
        ),
        "compa": (
            "getro",
            "https://communityjobs.compa.ai/companies",
            "collectionId",
            "compa",
        ),
        "localglobeall": (
            "consider",
            "https://consider.com/boards/vc/localglobe-all/companies",
            "board",
            "localglobeall",
        ),
        "soarky": (
            "getro",
            "https://jobs.soar-ky.org/companies",
            "collectionId",
            "soarky",
        ),
        "fintechaustralia": (
            "getro",
            "https://jobs.fintechaustralia.org.au/companies",
            "collectionId",
            "fintechaustralia",
        ),
        "johotalent": (
            "getro",
            "https://jobs.johotalent.com/companies",
            "collectionId",
            "johotalent",
        ),
        "bitkraft": (
            "getro",
            "https://careers.bitkraft.vc/companies",
            "collectionId",
            "bitkraft",
        ),
        "chirataevc": (
            "consider",
            "https://careers.chiratae.com/companies",
            "board",
            "chirataevc",
        ),
        "lifemultiplied": (
            "getro",
            "https://jobs.lifemultiplied.org/companies",
            "collectionId",
            "lifemultiplied",
        ),
        "dutchtech": (
            "consider",
            "https://consider.com/boards/vc/dutchtech/companies",
            "board",
            "dutchtech",
        ),
        "mitalumnistartups": (
            "consider",
            "https://consider.com/boards/vc/mit-alumni-startups/companies",
            "board",
            "mitalumnistartups",
        ),
        "blumevc": (
            "getro",
            "https://jobs.blume.vc/companies",
            "collectionId",
            "blumevc",
        ),
        "springtide": (
            "getro",
            "https://jobs.springtide.com/companies",
            "collectionId",
            "springtide",
        ),
        "collab": (
            "getro",
            "https://jobs.collab.capital/companies",
            "collectionId",
            "collab",
        ),
        "inflection": (
            "getro",
            "https://jobs.inflection.fund/companies",
            "collectionId",
            "inflection",
        ),
        "terratalent": (
            "getro",
            "https://terratalent.getro.com/companies",
            "collectionId",
            "terratalent",
        ),
        "samaipata": (
            "getro",
            "https://samaipata.getro.com/companies",
            "collectionId",
            "samaipata",
        ),
        "xrpl": (
            "getro",
            "https://jobs.xrpl.org/companies",
            "collectionId",
            "xrpl",
        ),
        "movementlabs": (
            "getro",
            "https://ecosystem.movementlabs.xyz/companies",
            "collectionId",
            "movementlabs",
        ),
        "sui": (
            "getro",
            "https://jobs.sui.io/companies",
            "collectionId",
            "sui",
        ),
        "cobalt": (
            "getro",
            "https://jobs.cobalt.la/companies",
            "collectionId",
            "cobalt",
        ),
        "vimian": (
            "getro",
            "https://careers.vimian.com/companies",
            "collectionId",
            "vimian",
        ),
        "wallstreetfriends": (
            "getro",
            "https://jobs.wallstreetfriends.org/companies",
            "collectionId",
            "wallstreetfriends",
        ),
        "leedsilluminate": (
            "getro",
            "https://jobs.leedsilluminate.com/companies",
            "collectionId",
            "leedsilluminate",
        ),
        "z2sixtyventures": (
            "getro",
            "https://jobs.z2sixtyventures.com/companies",
            "collectionId",
            "z2sixtyventures",
        ),
        "animocabrands": (
            "getro",
            "https://careers.animocabrands.com/companies",
            "collectionId",
            "animocabrands",
        ),
        "bluewing": (
            "getro",
            "https://careers.bluewing.vc/companies",
            "collectionId",
            "bluewing",
        ),
        "joulevc": (
            "getro",
            "https://jobs.joulevc.com/companies",
            "collectionId",
            "joulevc",
        ),
        "tpycapital": (
            "getro",
            "https://jobs.tpycapital.com/companies",
            "collectionId",
            "tpycapital",
        ),
        "reddot": (
            "getro",
            "https://careers.red-dot.capital/companies",
            "collectionId",
            "reddot",
        ),
        "arca": (
            "getro",
            "https://careers.ar.ca/companies",
            "collectionId",
            "arca",
        ),
        "sharpalphaadvisors": (
            "getro",
            "https://jobs.sharpalphaadvisors.com/companies",
            "collectionId",
            "sharpalphaadvisors",
        ),
        "msivfund": (
            "getro",
            "https://jobs.msivfund.com/companies",
            "collectionId",
            "msivfund",
        ),
        "coefficientcap": (
            "getro",
            "https://jobs.coefficientcap.com/companies",
            "collectionId",
            "coefficientcap",
        ),
        "superset": (
            "getro",
            "https://careers.superset.com/companies",
            "collectionId",
            "superset",
        ),
        "dyrdekmachine": (
            "getro",
            "https://careers.dyrdekmachine.com/companies",
            "collectionId",
            "dyrdekmachine",
        ),
        "wyvcjobs": (
            "getro",
            "https://wyvc-jobs.wyomingbusiness.org/companies",
            "collectionId",
            "wyvcjobs",
        ),
        "octopusenergygeneration": (
            "getro",
            "https://portfoliojobs.octopusenergygeneration.com/companies",
            "collectionId",
            "octopusenergygeneration",
        ),
        "colorintech": (
            "getro",
            "https://jobs.colorintech.org/companies",
            "collectionId",
            "colorintech",
        ),
        "bwam": (
            "getro",
            "https://jobs.bwam.network/companies",
            "collectionId",
            "bwam",
        ),
        "boomtownaccelerators": (
            "getro",
            "https://jobs.boomtownaccelerators.com/companies",
            "collectionId",
            "boomtownaccelerators",
        ),
        "rallydaypartners": (
            "getro",
            "https://jobs.rallydaypartners.com/companies",
            "collectionId",
            "rallydaypartners",
        ),
        "communitiesinschools": (
            "getro",
            "https://networkjobs.communitiesinschools.org/companies",
            "collectionId",
            "communitiesinschools",
        ),
        "acgpartners": (
            "getro",
            "https://jobs.acgpartners.com/companies",
            "collectionId",
            "acgpartners",
        ),
        "rubiconfounders": (
            "getro",
            "https://careers.rubiconfounders.com/companies",
            "collectionId",
            "rubiconfounders",
        ),
        "ovalpark": (
            "getro",
            "https://careers.ovalpark.com/companies",
            "collectionId",
            "ovalpark",
        ),
        "varsity": (
            "getro",
            "https://jobs.varsity.vc/companies",
            "collectionId",
            "varsity",
        ),
        "preludegrowth": (
            "getro",
            "https://talent.preludegrowth.com/companies",
            "collectionId",
            "preludegrowth",
        ),
        "reddogcap": (
            "getro",
            "https://jobs.reddogcap.com/companies",
            "collectionId",
            "reddogcap",
        ),
        "tezos": (
            "getro",
            "https://careers.tezos.com/companies",
            "collectionId",
            "tezos",
        ),
        "ocaventures": (
            "getro",
            "https://careers.ocaventures.com/companies",
            "collectionId",
            "ocaventures",
        ),
        "senovo": (
            "getro",
            "https://jobs.senovo.vc/companies",
            "collectionId",
            "senovo",
        ),
        "edencp": (
            "getro",
            "https://careers.edencp.com/companies",
            "collectionId",
            "edencp",
        ),
        "bainpe": (
            "consider",
            "https://consider.com/boards/vc/bain-pe/companies",
            "board",
            "bainpe",
        ),
        "collercapital": (
            "consider",
            "https://consider.com/boards/vc/coller-capital/companies",
            "board",
            "collercapital",
        ),
        "generalcatalyst": (
            "public_page",
            "https://www.generalcatalyst.com/portfolio",
            "label",
            "General Catalyst",
        ),
        "coatue": (
            "public_page",
            "https://www.coatue.com/privates-portfolio",
            "label",
            "Coatue",
        ),
        "visionfund": (
            "public_page",
            "https://visionfund.com/portfolio",
            "label",
            "Vision Fund",
        ),
        "iconiqgrowth": (
            "public_page",
            "https://www.iconiq.com/growth/companies",
            "label",
            "ICONIQ Growth",
        ),
        "wellingtonprivateinvesting": (
            "public_page",
            "https://www.wellington.com/en-us/institutional/capabilities/private-investing/our-investments",
            "label",
            "Wellington Private Investing",
        ),
        "workinbiotech": (
            "public_page",
            "https://workinbiotech.com/",
            "label",
            "Work in Biotech",
        ),
        "flagshippioneering": (
            "public_page",
            "https://www.flagshippioneering.com/companies",
            "label",
            "Flagship Pioneering",
        ),
        "archventure": (
            "public_page",
            "https://www.archventure.com/portfolio/",
            "label",
            "ARCH Venture Partners",
        ),
        "tpb": (
            "public_page",
            "https://www.tpb.co/businesses",
            "label",
            "The Production Board",
        ),
        "airstreet": (
            "public_page",
            "https://www.airstreet.com/portfolio",
            "label",
            "Air Street Capital",
        ),
        "boozallenventures": (
            "public_page",
            "https://www.boozallen.com/expertise/tech-ecosystem/ventures.html",
            "label",
            "Booz Allen Ventures",
        ),
        "starburstaero": (
            "public_page",
            "https://starburst.aero/portfolio/",
            "label",
            "Starburst Aerospace",
        ),
        "1011vcportfolio": (
            "public_page",
            "https://www.1011vc.com/portfolio",
            "label",
            "10-11 Ventures",
        ),
        "japanenergyfundventures": (
            "public_page",
            "https://www.japanenergyfund-ventures.com/",
            "label",
            "Japan Energy Fund Ventures",
        ),
        "conviction": (
            "public_page",
            "https://www.conviction.com/",
            "label",
            "Conviction",
        ),
        "stationf": (
            "public_page",
            "https://stationf.co/startups",
            "label",
            "Station F",
        ),
        "plugandplaytechcenter": (
            "public_page",
            "https://www.plugandplaytechcenter.com/startups",
            "label",
            "Plug and Play Tech Center",
        ),
        "angelpad": (
            "public_page",
            "https://www.angelpad.com/companies",
            "label",
            "AngelPad",
        ),
        "iterative": (
            "public_page",
            "https://www.iterative.vc/companies",
            "label",
            "Iterative",
        ),
        "tribecapital": (
            "public_page",
            "https://www.tribe.capital/portfolio",
            "label",
            "Tribe Capital",
        ),
        "blingcapital": (
            "public_page",
            "https://www.blingcapital.com/portfolio",
            "label",
            "Bling Capital",
        ),
        "hackvc": (
            "public_page",
            "https://hack.vc/portfolio",
            "label",
            "Hack VC",
        ),
        "1kx": (
            "public_page",
            "https://1kx.network/portfolio",
            "label",
            "1kx",
        ),
        "borderless": (
            "public_page",
            "https://borderless.xyz/portfolio",
            "label",
            "Borderless Capital",
        ),
        "worldfund": (
            "public_page",
            "https://www.worldfund.vc/portfolio",
            "label",
            "World Fund",
        ),
        "paleblue": (
            "public_page",
            "https://www.pale.blue/portfolio",
            "label",
            "Pale Blue Dot",
        ),
        "planetary": (
            "public_page",
            "https://www.planetary.vc/portfolio",
            "label",
            "Planetary",
        ),
        "kikocapital": (
            "public_page",
            "https://www.kikocapital.com/portfolio",
            "label",
            "Kiko Capital",
        ),
        "civilizationventures": (
            "public_page",
            "https://www.civilizationventures.com/portfolio",
            "label",
            "Civilization Ventures",
        ),
        "sante": (
            "public_page",
            "https://www.sante.com/portfolio",
            "label",
            "Sante Ventures",
        ),
        "venbio": (
            "public_page",
            "https://www.venbio.com/portfolio",
            "label",
            "VenBio",
        ),
        "lifeforcecapital": (
            "public_page",
            "https://www.lifeforcecapital.com/portfolio",
            "label",
            "LifeForce Capital",
        ),
        "2amvc": (
            "public_page",
            "https://www.2am.vc/portfolio",
            "label",
            "2am VC",
        ),
        "indiaquotient": (
            "public_page",
            "https://www.indiaquotient.in/portfolio",
            "label",
            "India Quotient",
        ),
        "waterbridge": (
            "public_page",
            "https://www.waterbridge.vc/portfolio",
            "label",
            "WaterBridge Ventures",
        ),
        "btvvc": (
            "public_page",
            "https://www.btv.vc/portfolio",
            "label",
            "Bullpen Capital",
        ),
        "rebelfund": (
            "public_page",
            "https://www.rebel-fund.com/portfolio",
            "label",
            "Rebel Fund",
        ),
        "shrug": (
            "public_page",
            "https://www.shrug.vc/portfolio",
            "label",
            "Shrug Capital",
        ),
        "elefund": (
            "public_page",
            "https://www.elefund.com/portfolio",
            "label",
            "Elefund",
        ),
        "k9ventures": (
            "public_page",
            "https://www.k9ventures.com/portfolio",
            "label",
            "K9 Ventures",
        ),
        "mach37": (
            "public_page",
            "https://www.mach37.com/portfolio",
            "label",
            "Mach37",
        ),
        "operatorcollective": (
            "public_page",
            "https://www.operatorcollective.com/portfolio",
            "label",
            "Operator Collective",
        ),
        "moxxievc": (
            "public_page",
            "https://www.moxxie.vc/portfolio",
            "label",
            "Moxxie Ventures",
        ),
        "tuskvc": (
            "public_page",
            "https://tusk.vc/portfolio",
            "label",
            "Tusk Venture Partners",
        ),
        "industrialinnovationfund": (
            "getro",
            "https://jobs.industrialinnovationfund.amazon/companies",
            "collectionId",
            "industrialinnovationfund",
        ),
        "theproductionboard": (
            "getro",
            "https://jobs.theproductionboard.com/companies",
            "collectionId",
            "theproductionboard",
        ),
        "joinwoven": (
            "getro",
            "https://careers.joinwoven.com/companies",
            "collectionId",
            "joinwoven",
        ),
        "bpc": (
            "getro",
            "https://jobs.bpc.com/companies",
            "collectionId",
            "bpc",
        ),
        "wesleyclover": (
            "getro",
            "https://careers.wesleyclover.com/companies",
            "collectionId",
            "wesleyclover",
        ),
        "voltaventures": (
            "getro",
            "https://jobs.voltaventures.eu/companies",
            "collectionId",
            "voltaventures",
        ),
        "kompas": (
            "getro",
            "https://careers.kompas.vc/companies",
            "collectionId",
            "kompas",
        ),
        "endeit": (
            "getro",
            "https://careers.endeit.com/companies",
            "collectionId",
            "endeit",
        ),
        "fov": (
            "getro",
            "https://jobs.fov.ventures/companies",
            "collectionId",
            "fov",
        ),
        "entradaventures": (
            "getro",
            "https://careers.entradaventures.com/companies",
            "collectionId",
            "entradaventures",
        ),
        "jibevc": (
            "getro",
            "https://jobs.jibevc.com/companies",
            "collectionId",
            "jibevc",
        ),
        "prelude": (
            "getro",
            "https://talent.prelude.xyz/companies",
            "collectionId",
            "prelude",
        ),
        "apeiron": (
            "getro",
            "https://jobs.apeiron.vc/companies",
            "collectionId",
            "apeiron",
        ),
        "haass": (
            "getro",
            "https://jobs.haass.network/companies",
            "collectionId",
            "haass",
        ),
        "karmijnkapitaal": (
            "getro",
            "https://jobs.karmijnkapitaal.nl/companies",
            "collectionId",
            "karmijnkapitaal",
        ),
        "logoslabs": (
            "getro",
            "https://jobs.logoslabs.com/companies",
            "collectionId",
            "logoslabs",
        ),
        "akmazocapital": (
            "getro",
            "https://careers.akmazocapital.com/companies",
            "collectionId",
            "akmazocapital",
        ),
        "merylbreidbart": (
            "getro",
            "https://network.merylbreidbart.com/companies",
            "collectionId",
            "merylbreidbart",
        ),
        "thecenterbham": (
            "getro",
            "https://jobs.thecenterbham.org/companies",
            "collectionId",
            "thecenterbham",
        ),
        "boydinnovationcenter": (
            "getro",
            "https://talent.boydinnovationcenter.org/companies",
            "collectionId",
            "boydinnovationcenter",
        ),
        "transtech": (
            "getro",
            "https://jobs.trans-tech.net/companies",
            "collectionId",
            "transtech",
        ),
        "sofindev": (
            "getro",
            "https://sofindev.getro.com/companies",
            "collectionId",
            "sofindev",
        ),
        "jlive": (
            "getro",
            "https://jobs.jlive.app/companies",
            "collectionId",
            "jlive",
        ),
        "wctfct": (
            "getro",
            "https://careers.wct-fct.com/companies",
            "collectionId",
            "wctfct",
        ),
        "democracyfund": (
            "getro",
            "https://network-jobs.democracyfund.org/companies",
            "collectionId",
            "democracyfund",
        ),
        "arena": (
            "getro",
            "https://careers.arena.run/companies",
            "collectionId",
            "arena",
        ),
        "evanwalden": (
            "getro",
            "https://evanwalden.com/companies",
            "collectionId",
            "evanwalden",
        ),
        "westportyouthcommission": (
            "getro",
            "https://jobbank.westportyouthcommission.org/companies",
            "collectionId",
            "westportyouthcommission",
        ),
        "highlandeurope": (
            "consider",
            "https://careers.highlandeurope.com/companies",
            "board",
            "highlandeurope",
        ),
        "moc": (
            "consider",
            "https://jobs.moc.vc/companies",
            "board",
            "moc",
        ),
        "airbusventures": (
            "consider",
            "https://consider.com/boards/vc/airbus-ventures/companies",
            "board",
            "airbusventures",
        ),
        "nightcreator": (
            "consider",
            "https://consider.com/boards/vc/night-creator/companies",
            "board",
            "nightcreator",
        ),
        "voyagervc": (
            "consider",
            "https://careers.voyagervc.com/companies",
            "board",
            "voyagervc",
        ),
        "climactic": (
            "consider",
            "https://jobs.climactic.vc/companies",
            "board",
            "climactic",
        ),
        "m12": (
            "public_page",
            "https://m12.vc/portfolio/",
            "label",
            "M12",
        ),
        "amdventures": (
            "public_page",
            "https://www.amd.com/en/ventures/portfolio.html",
            "label",
            "AMD Ventures",
        ),
        "delltechnologiescapital": (
            "public_page",
            "https://www.delltechnologiescapital.com/companies",
            "label",
            "Dell Technologies Capital",
        ),
        "ciscoinvestments": (
            "public_page",
            "https://www.ciscoinvestments.com/portfolio",
            "label",
            "Cisco Investments",
        ),
        "workdayventures": (
            "public_page",
            "https://ventures.workday.com/en-us/partner-companies.html",
            "label",
            "Workday Ventures",
        ),
        "servicenowventures": (
            "public_page",
            "https://www.servicenow.com/company/ventures.html",
            "label",
            "ServiceNow Ventures",
        ),
        "snowflakeventures": (
            "public_page",
            "https://www.snowflake.com/en/why-snowflake/startup-program/snowflake-ventures/",
            "label",
            "Snowflake Ventures",
        ),
        "databricksventures": (
            "public_page",
            "https://www.databricks.com/databricks-ventures",
            "label",
            "Databricks Ventures",
        ),
        "ibmventures": (
            "public_page",
            "https://www.ibm.com/ventures",
            "label",
            "IBM Ventures",
        ),
        "capitaloneventures": (
            "public_page",
            "https://capitaloneventures.com/portfolio",
            "label",
            "Capital One Ventures",
        ),
        "nvidiastartups": (
            "public_page",
            "https://www.nvidia.com/en-us/startups/showcase/",
            "label",
            "NVIDIA Inception",
        ),
    }

    for key, (provider_id, url, metadata_key, metadata_value) in expected.items():
        source = BOARD_SOURCE_CATALOG[key]
        assert source.provider_id == provider_id
        assert source.url == url
        assert source.raw_metadata[metadata_key] == metadata_value

    southparkcommons = BOARD_SOURCE_CATALOG["southparkcommons"]
    assert southparkcommons.provider_id == "southparkcommons"
    assert southparkcommons.url == "https://www.southparkcommons.com/jobs"

    assert "1871" in BOARD_SOURCE_CATALOG
    workable1871 = BOARD_SOURCE_CATALOG["1871"]
    assert workable1871.provider_id == "workable_source"
    assert workable1871.raw_metadata.get("token") == "1871"

    twobear = BOARD_SOURCE_CATALOG["twobearcapital"]
    assert twobear.provider_id == "public_page"
    assert twobear.enabled is False
    assert twobear.raw_metadata.get("label") == "Two Bear Capital"

    bioct = BOARD_SOURCE_CATALOG["bioct"]
    assert bioct.provider_id == "public_page"
    assert bioct.raw_metadata.get("observedStatus") == "cloudflare_challenge"


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
async def test_public_page_source_adapter_yields_empty_with_note():
    settings = OpenOppsSettings(cache_enabled=False)
    # use a representative from catalog (twobearcapital is public_page, disabled)
    src = BOARD_SOURCE_CATALOG["twobearcapital"]

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in PublicPageSourceAdapter(settings).iter_boards(
                client, src, page_size=50
            )
        ]

    boards, providers, meta = pages[0]
    assert boards == []
    assert providers == []
    assert "Metadata-only public page" in meta["note"]
    assert meta["sourceUrl"].endswith("twobearcapital.com/companies")
