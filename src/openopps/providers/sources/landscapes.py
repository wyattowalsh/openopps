from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from openopps.models import BoardProviderRecord, BoardRecord, SourceRecord
from openopps.providers.sources.source_utils import fetch_text, index_board_record
from openopps.providers.sources.source_utils import parse_cncf_landscape_items
from openopps.providers.sources.source_utils import source_taxonomy_metadata
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify


CNCF_LANDSCAPE_SOURCE = SourceRecord(
    key="cncf-landscape",
    url="https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml",
    provider_id="cncf_landscape",
    raw_metadata=source_taxonomy_metadata(
        provider_type="ecosystem_landscape",
        coverage_mode="projects",
        access_type="public_github_data",
        license_status="oss_attribution_required",
        refresh_cadence="periodic",
        source_category="cloud_native_ecosystem",
        source_attribution="Cloud Native Computing Foundation landscape.yml data; logos and Crunchbase-derived fields are intentionally not ingested.",
        inclusion_reason="Public GitHub landscape data is a high-yield non-VC ecosystem backbone.",
        indexName="CNCF Landscape",
    ),
)


class CncfLandscapeSourceAdapter:
    provider_id = "cncf_landscape"
    provider_label = "CNCF Landscape"
    provider_description = "CNCF landscape source adapter that discovers cloud-native projects and vendors from public GitHub data."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        text = await fetch_text(client, source.url, accept="text/yaml, text/plain")
        items = parse_cncf_landscape_items(text)
        boards = [_board_from_landscape_item(source, item) for item in items]
        yield boards, [], {"total": len(boards), "sourceUrl": source.url}


def _board_from_landscape_item(
    source: SourceRecord, item: dict[str, str]
) -> BoardRecord:
    name = item["name"]
    category = item.get("category") or None
    subcategory = item.get("subcategory") or None
    project = item.get("project") or None
    raw_payload = {
        "sourceReferenceUrl": source.url,
        "sourceProvider": source.provider_id,
        "indexName": source.raw_metadata.get("indexName"),
        "category": category,
        "subcategory": subcategory,
        "project": project,
        "repoUrl": item.get("repo_url") or None,
        "openSource": item.get("open_source") or None,
        "joined": item.get("joined") or None,
    }
    return index_board_record(
        source=source,
        name=name,
        remote_id=item.get("repo_url") or item.get("homepage_url") or name,
        remote_slug=slugify(name),
        website_url=item.get("homepage_url"),
        description=item.get("description") or None,
        markets=[value for value in [category, subcategory, project] if value],
        raw_payload=raw_payload,
    )


SOURCE_RECORDS = (CNCF_LANDSCAPE_SOURCE,)
