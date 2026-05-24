from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from openopps.models import BoardProviderRecord, BoardRecord, SourceRecord
from openopps.providers.sources.source_utils import csv_records, embedded_csv_records
from openopps.providers.sources.source_utils import (
    fetch_text,
    first_string,
    index_board_record,
)
from openopps.providers.sources.source_utils import (
    optional_int,
    source_taxonomy_metadata,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify


FORTUNE500_SOURCE = SourceRecord(
    key="fortune500",
    url="https://raw.githubusercontent.com/cmusam/fortune500/master/fortune500.csv",
    provider_id="ranking_csv",
    enabled=False,
    raw_metadata=source_taxonomy_metadata(
        provider_type="employer_ranking",
        coverage_mode="ranked_companies",
        access_type="oss_seed",
        license_status="needs_review",
        refresh_cadence="annual",
        source_category="employer_ranking",
        source_attribution="Scrappy community Fortune 500 CSV seed; use a reviewed source URL or embedded user-supplied CSV for refreshes.",
        default_enabled_reason="Disabled by default because Fortune ranking data requires explicit provenance review.",
        indexName="Fortune 500",
    ),
)


class RankingCsvSourceAdapter:
    provider_id = "ranking_csv"
    provider_label = "Ranking CSV"
    provider_description = (
        "Opt-in CSV ranking source adapter for employer and company lists."
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
                client,
                source.url,
                accept="text/csv, text/plain",
                allow_manual=True,
            )
            records = csv_records(text)
        boards = [
            _board_from_ranking_row(source, index, row)
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


def _board_from_ranking_row(
    source: SourceRecord,
    fallback_rank: int,
    row: dict[str, Any],
) -> BoardRecord:
    rank = optional_int(first_string(row, "Rank", "rank", "rank_2024")) or fallback_rank
    name = first_string(row, "Company", "Name", "company", "name", "Title")
    if not name:
        raise ValueError(f"Ranking row has no company name: {row}")
    domain = first_string(row, "Domain", "Website", "URL", "domain", "website")
    industry = first_string(row, "Industry", "Sector", "industry", "sector")
    location = first_string(row, "Location", "Headquarters", "City", "HQ")
    raw_payload = {
        "sourceReferenceUrl": source.url,
        "sourceProvider": source.provider_id,
        "sourceRank": rank,
        "indexName": source.raw_metadata.get("indexName"),
        "industry": industry,
        "location": location,
        "row": row,
    }
    return index_board_record(
        source=source,
        name=name,
        remote_id=str(first_string(row, "ID", "id") or rank or name),
        remote_slug=slugify(f"{rank}-{name}"),
        website_url=domain,
        markets=[industry] if industry else [],
        locations=[location] if location else [],
        raw_payload=raw_payload,
    )


SOURCE_RECORDS = (FORTUNE500_SOURCE,)
