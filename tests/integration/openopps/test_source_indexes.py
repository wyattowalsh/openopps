import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.providers.sources.landscapes import (
    CNCF_LANDSCAPE_SOURCE,
    CncfLandscapeSourceAdapter,
)
from openopps.providers.sources.public_indexes import (
    NASDAQ100_SOURCE,
    SP500_SOURCE,
    PublicIndexCsvSourceAdapter,
)
from openopps.providers.sources.rankings import (
    FORTUNE500_SOURCE,
    RankingCsvSourceAdapter,
)
from openopps.providers.sources.sec import (
    SEC_COMPANY_TICKERS_SOURCE,
    SEC_COMPANY_TICKERS_URL,
    SecCompanyTickersSourceAdapter,
)
from openopps.settings import OpenOppsSettings


@pytest.mark.asyncio
@respx.mock
async def test_sec_company_tickers_normalizes_listed_company_boards():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(SEC_COMPANY_TICKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
            },
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in SecCompanyTickersSourceAdapter(settings).iter_boards(
                client, SEC_COMPANY_TICKERS_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert providers == []
    assert meta["total"] == 1
    assert boards[0].key == "sec-company-tickers:aapl"
    assert boards[0].name == "Apple Inc."
    assert boards[0].remote_id == "320193"
    assert boards[0].markets == ["Nasdaq"]
    assert boards[0].raw_payload["sourceProvider"] == "sec_company_tickers"


@pytest.mark.asyncio
@respx.mock
async def test_public_index_csv_normalizes_remote_csv_rows():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(SP500_SOURCE.url).mock(
        return_value=httpx.Response(
            200,
            text=(
                "Symbol,Security,GICS Sector,GICS Sub-Industry,Headquarters Location,CIK\n"
                "AAPL,Apple Inc.,Information Technology,Technology Hardware,Cupertino CA,320193\n"
            ),
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in PublicIndexCsvSourceAdapter(settings).iter_boards(
                client, SP500_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert providers == []
    assert meta["indexName"] == "S&P 500"
    assert boards[0].key == "sp500:aapl"
    assert boards[0].remote_id == "320193"
    assert boards[0].markets == ["Information Technology", "Technology Hardware"]
    assert boards[0].locations == ["Cupertino CA"]


@pytest.mark.asyncio
async def test_public_index_csv_supports_manual_embedded_rows():
    settings = OpenOppsSettings(cache_enabled=False)
    source = NASDAQ100_SOURCE.model_copy(
        update={
            "raw_metadata": {
                **NASDAQ100_SOURCE.raw_metadata,
                "rows": [
                    {
                        "Symbol": "MSFT",
                        "Security": "Microsoft Corporation",
                        "Sector": "Information Technology",
                    }
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
    assert providers == []
    assert meta["indexName"] == "Nasdaq-100"
    assert boards[0].key == "nasdaq100:msft"
    assert boards[0].name == "Microsoft Corporation"
    assert boards[0].markets == ["Information Technology"]


@pytest.mark.asyncio
async def test_ranking_csv_supports_manual_embedded_rows():
    settings = OpenOppsSettings(cache_enabled=False)
    source = FORTUNE500_SOURCE.model_copy(
        update={
            "url": "manual://fortune500",
            "raw_metadata": {
                **FORTUNE500_SOURCE.raw_metadata,
                "rows": [
                    {
                        "Rank": "1",
                        "Company": "Acme Retail",
                        "Website": "acme.example",
                        "Industry": "Retail",
                        "Location": "Austin TX",
                    }
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

    boards, providers, meta = pages[0]
    assert providers == []
    assert meta["indexName"] == "Fortune 500"
    assert boards[0].key == "fortune500:1-acme-retail"
    assert boards[0].website_url == "https://acme.example"
    assert boards[0].markets == ["Retail"]


@pytest.mark.asyncio
@respx.mock
async def test_cncf_landscape_normalizes_allowed_landscape_fields_only():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(CNCF_LANDSCAPE_SOURCE.url).mock(
        return_value=httpx.Response(
            200,
            text="""
- category:
  name: Runtime
  subcategories:
    - subcategory:
      name: Container Runtime
      items:
        - item:
          name: Acme Runtime
          homepage_url: https://acme.example
          description: Fast runtime.
          repo_url: https://github.com/acme/runtime
          open_source: true
          crunchbase: https://www.crunchbase.com/organization/acme
""".strip(),
        )
    )

    async with build_async_client(settings) as client:
        pages = [
            page
            async for page in CncfLandscapeSourceAdapter(settings).iter_boards(
                client, CNCF_LANDSCAPE_SOURCE, page_size=100
            )
        ]

    boards, providers, meta = pages[0]
    assert providers == []
    assert meta["total"] == 1
    assert boards[0].key == "cncf-landscape:acme-runtime"
    assert boards[0].website_url == "https://acme.example"
    assert boards[0].markets == ["Runtime", "Container Runtime"]
    assert "crunchbase" not in boards[0].raw_payload
