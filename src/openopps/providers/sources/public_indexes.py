from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from openopps.models import BoardProviderRecord, BoardRecord, SourceRecord
from openopps.providers.sources.source_utils import (
    csv_records,
    embedded_csv_records,
    fetch_text,
    first_string,
)
from openopps.providers.sources.source_utils import index_board_record
from openopps.providers.sources.source_utils import (
    optional_int,
    source_taxonomy_metadata,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify


SP500_SOURCE = SourceRecord(
    key="sp500",
    url="https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    provider_id="public_index_csv",
    raw_metadata=source_taxonomy_metadata(
        provider_type="public_company_index",
        coverage_mode="listed_companies",
        access_type="oss_seed",
        license_status="public_attribution_required",
        refresh_cadence="periodic",
        source_category="public_company_index",
        source_attribution="Community-maintained S&P 500 constituents CSV derived from public index tables.",
        inclusion_reason="Included as a community-maintained public-company index seed; treat membership provenance as advisory.",
        indexName="S&P 500",
    ),
)

NASDAQ100_SOURCE = SourceRecord(
    key="nasdaq100",
    url="manual://nasdaq100",
    provider_id="public_index_csv",
    raw_metadata=source_taxonomy_metadata(
        provider_type="public_company_index",
        coverage_mode="listed_companies",
        access_type="oss_seed",
        license_status="needs_review",
        refresh_cadence="periodic",
        source_category="public_company_index",
        source_attribution="Community-maintained Nasdaq-100 constituents seed; replace with a reviewed source URL before production refreshes.",
        inclusion_reason="Included as an embedded public-company index seed; treat membership provenance as advisory.",
        indexName="Nasdaq-100",
    ),
)


class PublicIndexCsvSourceAdapter:
    provider_id = "public_index_csv"
    provider_label = "Public Index CSV"
    provider_description = (
        "CSV source adapter for public-company index membership seeds."
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        records = embedded_csv_records(source)
        if records is None:
            text = await fetch_text(
                client, source.url, accept="text/csv, text/plain", allow_manual=True
            )
            records = csv_records(text)
        boards = [
            _board_from_index_row(source, index, row)
            for index, row in enumerate(records, start=1)
        ]
        yield (
            boards,
            [],
            {
                "total": len(boards),
                "sourceUrl": source.url,
                "indexName": source.raw_metadata.get("indexName"),
            },
        )


def _board_from_index_row(
    source: SourceRecord,
    rank: int,
    row: dict[str, Any],
) -> BoardRecord:
    symbol = first_string(row, "Symbol", "Ticker", "Ticker Symbol", "symbol", "ticker")
    name = first_string(row, "Security", "Company", "Name", "company", "name") or symbol
    if not name:
        raise ValueError(f"Index row has no company name: {row}")
    sector = first_string(row, "GICS Sector", "Sector", "sector")
    industry = first_string(row, "GICS Sub-Industry", "Industry", "industry")
    location = first_string(row, "Headquarters Location", "Headquarters", "Location")
    cik = optional_int(first_string(row, "CIK", "cik"))
    remote_slug = slugify(symbol or name)
    raw_payload = {
        "sourceReferenceUrl": source.url,
        "sourceProvider": source.provider_id,
        "sourceRank": rank,
        "indexName": source.raw_metadata.get("indexName"),
        "symbol": symbol,
        "cik": cik,
        "sector": sector,
        "industry": industry,
        "headquarters": location,
        "row": row,
    }
    return index_board_record(
        source=source,
        name=name,
        remote_id=str(symbol or cik or name),
        remote_slug=remote_slug,
        markets=[value for value in [sector, industry] if value],
        locations=[location] if location else [],
        raw_payload=raw_payload,
    )


SOURCE_RECORDS = (SP500_SOURCE, NASDAQ100_SOURCE)
