"""Household index boards attach packaged ATS routes by clear name match only."""

from __future__ import annotations

import httpx

from openopps.http import build_async_client
from openopps.models import BoardRecord, ProviderSupport, SourceRecord
from openopps.providers.boards import BOARD_JOB_PROVIDERS
from openopps.providers.sources import BOARD_SOURCE_ADAPTERS, BOARD_SOURCE_CATALOG
from openopps.providers.sources import household_routes as household_routes_module
from openopps.providers.sources.household_routes import household_index_provider_records
from openopps.providers.sources.public_indexes import (
    NASDAQ100_SOURCE,
    PublicIndexCsvSourceAdapter,
)
from openopps.providers.sources.rankings import (
    FORTUNE500_SOURCE,
    RankingCsvSourceAdapter,
)
from openopps.providers.sources.source_utils import load_packaged_portfolio_source_records
from openopps.settings import OpenOppsSettings


def _catalog_record(key: str) -> SourceRecord:
    for record in load_packaged_portfolio_source_records():
        if record.key == key:
            return record
    raise AssertionError(f"missing packaged catalog key {key}")


def _providers_for_board(
    providers: list,
    board_key: str,
) -> list:
    return [route for route in providers if route.board_key == board_key]


def test_household_routes_module_is_not_a_catalog_source() -> None:
    assert not hasattr(household_routes_module, "SOURCE_RECORDS")
    assert "household_routes" not in BOARD_SOURCE_CATALOG
    assert "household_routes" not in BOARD_SOURCE_ADAPTERS


def test_matched_household_name_gets_jobs_capable_packaged_route() -> None:
    catalog = _catalog_record("gendigital")
    source = SourceRecord(
        key="nasdaq100",
        url="manual://nasdaq100",
        provider_id="public_index_csv",
    )
    matched = BoardRecord(
        key="nasdaq100:gen",
        source_key="nasdaq100",
        remote_id="GEN",
        name="Gen Digital Inc.",
        domain="apple.com",
        website_url="https://www.apple.com",
    )
    unmatched = BoardRecord(
        key="nasdaq100:acme",
        source_key="nasdaq100",
        remote_id="AAPL",
        name="Acme Retail",
        domain="apple.com",
        website_url="https://job-boards.greenhouse.io/10pearls",
    )

    providers = household_index_provider_records(source, [matched, unmatched])

    routes = _providers_for_board(providers, matched.key)
    assert len(routes) == 1
    route = routes[0]
    assert route.source_key == source.key
    assert route.board_key == matched.key
    assert route.support_level == ProviderSupport.JOBS
    assert route.provider_id in BOARD_JOB_PROVIDERS
    assert route.board_url == catalog.url
    assert route.token == "gen-digital"
    assert route.token != matched.remote_id
    assert _providers_for_board(providers, unmatched.key) == []


def test_overlay_ats_locator_attaches_unique_household_name() -> None:
    source = SourceRecord(
        key="sp500",
        url="manual://sp500",
        provider_id="public_index_csv",
    )
    matched = BoardRecord(
        key="sp500:anthropic",
        source_key="sp500",
        remote_id="ANTH",
        name="Anthropic",
        domain="anthropic.com",
        website_url="https://www.anthropic.com",
    )
    unmatched = BoardRecord(
        key="sp500:acme",
        source_key="sp500",
        remote_id="ACME",
        name="Acme Retail",
        website_url="https://job-boards.greenhouse.io/10pearls",
    )

    providers = household_index_provider_records(source, [matched, unmatched])

    routes = _providers_for_board(providers, matched.key)
    assert len(routes) == 1
    route = routes[0]
    assert route.source_key == source.key
    assert route.board_key == matched.key
    assert route.provider_id == "greenhouse"
    assert route.support_level == ProviderSupport.JOBS
    assert route.board_url == "https://job-boards.greenhouse.io/anthropic"
    assert route.token == "anthropic"
    assert route.token != matched.remote_id
    assert _providers_for_board(providers, unmatched.key) == []


def test_trailing_corporate_descriptors_attach_unique_overlay_ats() -> None:
    source = SourceRecord(
        key="sp500",
        url="manual://sp500",
        provider_id="public_index_csv",
    )
    palantir = BoardRecord(
        key="sp500:pltr",
        source_key="sp500",
        remote_id="PLTR",
        name="Palantir Technologies Inc.",
    )
    micron = BoardRecord(
        key="sp500:mu",
        source_key="sp500",
        remote_id="MU",
        name="Micron Technology, Inc.",
    )
    coinbase = BoardRecord(
        key="sp500:coin",
        source_key="sp500",
        remote_id="COIN",
        name="Coinbase Global, Inc.",
    )
    samsung = BoardRecord(
        key="sp500:smsn",
        source_key="sp500",
        remote_id="SMSN",
        name="Samsung Electronics",
    )
    ge_health = BoardRecord(
        key="sp500:gehc",
        source_key="sp500",
        remote_id="GEHC",
        name="GE HealthCare Technologies Inc.",
    )
    unmatched = BoardRecord(
        key="sp500:acme",
        source_key="sp500",
        remote_id="ACME",
        name="Acme Retail",
    )

    providers = household_index_provider_records(
        source,
        [palantir, micron, coinbase, samsung, ge_health, unmatched],
    )

    palantir_routes = _providers_for_board(providers, palantir.key)
    assert len(palantir_routes) == 1
    assert palantir_routes[0].provider_id == "lever"
    assert palantir_routes[0].board_url == "https://jobs.lever.co/palantir"
    assert palantir_routes[0].token != palantir.remote_id

    micron_routes = _providers_for_board(providers, micron.key)
    assert len(micron_routes) == 1
    assert micron_routes[0].provider_id == "workday"
    assert micron_routes[0].board_url == (
        "https://micron.wd1.myworkdayjobs.com/external"
    )

    coinbase_routes = _providers_for_board(providers, coinbase.key)
    assert len(coinbase_routes) == 1
    assert coinbase_routes[0].provider_id == "greenhouse"
    assert coinbase_routes[0].board_url == (
        "https://job-boards.greenhouse.io/coinbase"
    )

    samsung_routes = _providers_for_board(providers, samsung.key)
    assert len(samsung_routes) == 1
    assert samsung_routes[0].board_url == (
        "https://sec.wd3.myworkdayjobs.com/samsung_jobs"
    )

    ge_routes = _providers_for_board(providers, ge_health.key)
    assert len(ge_routes) == 1
    assert ge_routes[0].board_url == (
        "https://gehc.wd5.myworkdayjobs.com/GEHC_ExternalSite"
    )
    assert "GE_ExternalSite" not in (ge_routes[0].board_url or "")
    assert _providers_for_board(providers, unmatched.key) == []


def test_ambiguous_overlay_employer_name_does_not_attach() -> None:
    source = SourceRecord(
        key="fortune500",
        url="manual://fortune500",
        provider_id="ranking_csv",
    )
    boards = [
        BoardRecord(
            key="fortune500:chevron",
            source_key="fortune500",
            remote_id="CVX",
            name="Chevron Corporation",
        )
    ]

    providers = household_index_provider_records(source, boards)

    assert providers == []


def test_unmatched_and_lookalike_names_stay_empty() -> None:
    source = SourceRecord(
        key="sp500",
        url="manual://sp500",
        provider_id="public_index_csv",
    )
    boards = [
        BoardRecord(
            key="sp500:aapl",
            source_key="sp500",
            remote_id="AAPL",
            name="Apple Inc.",
            domain="apple.com",
            website_url="https://www.apple.com",
        ),
        BoardRecord(
            key="sp500:msft",
            source_key="sp500",
            remote_id="MSFT",
            name="Microsoft Corporation",
        ),
    ]

    providers = household_index_provider_records(source, boards)

    assert providers == []


async def test_nasdaq100_embedded_seed_attaches_packaged_lever_route() -> None:
    catalog = _catalog_record("matchgroup")
    settings = OpenOppsSettings(cache_enabled=False)
    source = NASDAQ100_SOURCE.model_copy(
        update={
            "raw_metadata": {
                **NASDAQ100_SOURCE.raw_metadata,
                "rows": [
                    {
                        "Symbol": "MTCH",
                        "Security": "Match Group, Inc.",
                        "Sector": "Communication Services",
                    },
                    {
                        "Symbol": "AAPL",
                        "Security": "Acme Retail",
                        "Sector": "Retail",
                    },
                ],
            }
        }
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in PublicIndexCsvSourceAdapter(settings).iter_boards(
                client, source, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert meta["indexName"] == "Nasdaq-100"
    matched = next(board for board in boards if board.name == "Match Group, Inc.")
    unmatched = next(board for board in boards if board.name == "Acme Retail")
    routes = _providers_for_board(providers, matched.key)
    assert len(routes) == 1
    route = routes[0]
    assert route.provider_id == "lever"
    assert route.support_level == ProviderSupport.JOBS
    assert route.board_url == catalog.url
    assert route.token == "matchgroup"
    assert route.token != matched.remote_id
    assert _providers_for_board(providers, unmatched.key) == []


async def test_fortune500_embedded_seed_attaches_packaged_ashby_route() -> None:
    catalog = _catalog_record("gendigital")
    settings = OpenOppsSettings(cache_enabled=False)
    source = FORTUNE500_SOURCE.model_copy(
        update={
            "url": "manual://fortune500",
            "raw_metadata": {
                **FORTUNE500_SOURCE.raw_metadata,
                "rows": [
                    {
                        "Rank": "1",
                        "Company": "Gen Digital Inc.",
                        "Website": "apple.com",
                        "Industry": "Software",
                    },
                    {
                        "Rank": "2",
                        "Company": "Acme Retail",
                        "Website": "https://job-boards.greenhouse.io/10pearls",
                        "Industry": "Retail",
                    },
                ],
            },
        }
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in RankingCsvSourceAdapter(settings).iter_boards(
                client, source, page_size=100
            )
        ]

    boards, providers, _meta = pages[0]
    matched = next(board for board in boards if board.name == "Gen Digital Inc.")
    unmatched = next(board for board in boards if board.name == "Acme Retail")
    routes = _providers_for_board(providers, matched.key)
    assert len(routes) == 1
    route = routes[0]
    assert route.provider_id == "ashbyhq"
    assert route.support_level == ProviderSupport.JOBS
    assert route.board_url == catalog.url
    assert route.token == "gen-digital"
    assert _providers_for_board(providers, unmatched.key) == []


async def test_household_index_routes_do_not_use_network() -> None:
    settings = OpenOppsSettings(cache_enabled=False)
    source = NASDAQ100_SOURCE.model_copy(
        update={
            "raw_metadata": {
                **NASDAQ100_SOURCE.raw_metadata,
                "rows": [
                    {"Symbol": "MTCH", "Security": "Match Group, Inc."},
                    {"Symbol": "ACME", "Security": "Acme Retail"},
                ],
            }
        }
    )

    def _forbid_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network request: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_forbid_network)
    ) as client:
        pages = [
            page
            async for page in PublicIndexCsvSourceAdapter(settings).iter_boards(
                client, source, page_size=100
            )
        ]

    _boards, providers, _meta = pages[0]
    assert any(route.provider_id == "lever" for route in providers)
    assert any(route.token == "matchgroup" for route in providers)


def test_ticker_and_denied_hosts_do_not_invent_ats_tokens() -> None:
    source = SourceRecord(
        key="sec-company-tickers",
        url="manual://sec-company-tickers",
        provider_id="public_index_csv",
    )
    boards = [
        BoardRecord(
            key="sec-company-tickers:aapl",
            source_key="sec-company-tickers",
            remote_id="AAPL",
            name="Apple Inc.",
            domain="apple.com",
            website_url="https://www.apple.com",
        ),
        BoardRecord(
            key="sec-company-tickers:denied",
            source_key="sec-company-tickers",
            remote_id="INDEED",
            name="Indeed",
            domain="indeed.com",
            website_url="https://www.indeed.com/jobs",
        ),
        BoardRecord(
            key="sec-company-tickers:glass",
            source_key="sec-company-tickers",
            remote_id="GLASS",
            name="Glassdoor",
            domain="glassdoor.com",
            website_url="https://www.glassdoor.com/Job/index.htm",
        ),
    ]

    providers = household_index_provider_records(source, boards)

    assert providers == []
