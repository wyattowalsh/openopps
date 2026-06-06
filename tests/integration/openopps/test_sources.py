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
    AshbySourceAdapter,
    PEAR_VC_SOURCE,
    SOUTHPARKCOMMONS_SOURCE,
    SouthParkCommonsSourceAdapter,
    VENTURE_CAPITAL_CAREERS_SOURCE,
    VENTURE_LOOP_SOURCE,
    VentureCapitalCareersSourceAdapter,
    VentureLoopSourceAdapter,
    YCOMBINATOR_SOURCE,
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
                    "count": 1,
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
                client, GETRO_SOURCE_CATALOG["accel"], page_size=12
            )
        ]

    boards, providers, meta = pages[0]
    assert boards[0].key == "accel:100ms-2"
    assert boards[0].name == "100ms"
    assert boards[0].num_jobs_hint == 10
    assert boards[0].markets == ["Software"]
    assert providers == []
    assert meta["total"] == 1


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
    }

    for key, (provider_id, url, metadata_key, metadata_value) in expected.items():
        source = BOARD_SOURCE_CATALOG[key]
        assert source.provider_id == provider_id
        assert source.url == url
        assert source.raw_metadata[metadata_key] == metadata_value

    southparkcommons = BOARD_SOURCE_CATALOG["southparkcommons"]
    assert southparkcommons.provider_id == "southparkcommons"
    assert southparkcommons.url == "https://www.southparkcommons.com/jobs"
