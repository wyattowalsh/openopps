from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from openopps.http import retrying_json_request
from openopps.models import BoardProviderRecord, BoardRecord, SourceRecord
from openopps.providers.sources.source_utils import index_board_record
from openopps.providers.sources.source_utils import (
    optional_int,
    source_taxonomy_metadata,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify


SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

SEC_COMPANY_TICKERS_SOURCE = SourceRecord(
    key="sec-company-tickers",
    url=SEC_COMPANY_TICKERS_URL,
    provider_id="sec_company_tickers",
    enabled=False,
    raw_metadata=source_taxonomy_metadata(
        provider_type="public_company_index",
        coverage_mode="listed_companies",
        access_type="official_file",
        license_status="official_public",
        refresh_cadence="periodic",
        source_category="public_companies",
        source_attribution="U.S. Securities and Exchange Commission company tickers file",
        default_enabled_reason=(
            "Opt-in because SEC fair-access controls can reject generic scheduled "
            "sync environments; run manually when the caller has a compliant "
            "declared User-Agent and network path."
        ),
    ),
)


class SecCompanyTickersSourceAdapter:
    provider_id = "sec_company_tickers"
    provider_label = "SEC Company Tickers"
    provider_description = "Official SEC public-company ticker source that discovers listed companies as detect-only boards."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        payload = await self._request_json(
            client,
            "GET",
            source.url,
            cache_namespace="source:sec-company-tickers",
        )
        rows = _sec_rows(payload)
        boards = [_board_from_sec_row(source, row) for row in rows]
        yield boards, [], {"total": len(boards), "sourceUrl": source.url}


def _sec_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        fields = [str(field) for field in payload.get("fields", [])]
        return [
            dict(zip(fields, row)) for row in payload["data"] if isinstance(row, list)
        ]
    if isinstance(payload, dict):
        return [item for item in payload.values() if isinstance(item, dict)]
    return [item for item in payload if isinstance(item, dict)]


def _board_from_sec_row(source: SourceRecord, row: dict[str, Any]) -> BoardRecord:
    cik = optional_int(row.get("cik") or row.get("cik_str") or row.get("CIK"))
    ticker = str(row.get("ticker") or row.get("Ticker") or "").strip().upper()
    name = str(
        row.get("name") or row.get("title") or row.get("Company Name") or ticker
    ).strip()
    exchange = str(row.get("exchange") or row.get("Exchange") or "").strip() or None
    remote_id = f"{cik}:{ticker}" if cik and ticker else str(ticker or cik or name)
    remote_slug = slugify(ticker or name)
    raw_payload = {
        "cik": cik,
        "ticker": ticker or None,
        "exchange": exchange,
        "name": name,
        "sourceReferenceUrl": source.url,
        "sourceProvider": source.provider_id,
    }
    return index_board_record(
        source=source,
        name=name,
        remote_id=remote_id,
        remote_slug=remote_slug,
        markets=[exchange] if exchange else [],
        raw_payload=raw_payload,
    )


SOURCE_RECORDS = (SEC_COMPANY_TICKERS_SOURCE,)
