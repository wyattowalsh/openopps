from __future__ import annotations

import csv
from io import StringIO
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from openopps.models import BoardRecord, JsonDict, SourceRecord
from openopps.models import normalize_public_website_url, validate_public_https_url
from openopps.utils import slugify, source_board_key


SOURCE_TAXONOMY_KEYS = (
    "providerType",
    "coverageMode",
    "accessType",
    "licenseStatus",
    "refreshCadence",
    "sourceYear",
    "sourceCategory",
    "sourceAttribution",
    "defaultEnabledReason",
)


def source_taxonomy_metadata(
    *,
    provider_type: str,
    coverage_mode: str,
    access_type: str,
    license_status: str,
    refresh_cadence: str,
    source_category: str,
    source_attribution: str,
    default_enabled_reason: str,
    source_year: int | None = None,
    **extra: Any,
) -> JsonDict:
    metadata: JsonDict = {
        "providerType": provider_type,
        "coverageMode": coverage_mode,
        "accessType": access_type,
        "licenseStatus": license_status,
        "refreshCadence": refresh_cadence,
        "sourceCategory": source_category,
        "sourceAttribution": source_attribution,
        "defaultEnabledReason": default_enabled_reason,
    }
    if source_year is not None:
        metadata["sourceYear"] = source_year
    for key, value in extra.items():
        if value is not None:
            metadata[key] = value
    return metadata


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str = "text/plain, text/csv, text/html;q=0.8, */*;q=0.5",
    allow_manual: bool = False,
) -> str:
    validate_public_https_url(url, allow_manual=allow_manual)
    if url.lower().startswith("manual://"):
        raise ValueError(f"Manual source {url} must provide embedded rows or CSV text")
    response = await client.get(url, headers={"accept": accept})
    response.raise_for_status()
    return response.text


def csv_records(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    return [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
    ]


def embedded_csv_records(source: SourceRecord) -> list[dict[str, str]] | None:
    rows = source.raw_metadata.get("rows")
    if isinstance(rows, list):
        normalized = []
        for row in rows:
            if isinstance(row, dict):
                normalized.append(
                    {
                        str(key).strip(): str(value or "").strip()
                        for key, value in row.items()
                    }
                )
        return normalized
    csv_text = source.raw_metadata.get("csv")
    if isinstance(csv_text, str) and csv_text.strip():
        return csv_records(csv_text)
    return None


def first_string(row: dict[str, Any], *keys: str) -> str | None:
    lower_map = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            value = lower_map.get(key.lower())
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def domain_from_url(value: object) -> str | None:
    url = normalize_public_website_url(value)
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower().removeprefix("www.") if host else None


def unique_strings(values: Sequence[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


def index_board_record(
    *,
    source: SourceRecord,
    name: str,
    remote_id: str,
    remote_slug: str | None = None,
    website_url: str | None = None,
    description: str | None = None,
    markets: list[str] | None = None,
    locations: list[str] | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> BoardRecord:
    slug = remote_slug or slugify(remote_id or name)
    website = normalize_public_website_url(website_url)
    return BoardRecord(
        key=source_board_key(source.key, slug),
        source_key=source.key,
        remote_id=remote_id,
        remote_slug=slug,
        name=name,
        domain=domain_from_url(website),
        website_url=website,
        description=description,
        markets=unique_strings(markets or []),
        locations=unique_strings(locations or []),
        raw_payload=cast(JsonDict, raw_payload or {}),
    )


def parse_cncf_landscape_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    category: str | None = None
    subcategory: str | None = None
    pending_name_for: str | None = None
    item: dict[str, str] | None = None
    item_indent: int | None = None
    allowed_item_keys = {
        "name",
        "description",
        "homepage_url",
        "repo_url",
        "project",
        "open_source",
        "joined",
    }

    def flush_item() -> None:
        nonlocal item
        if item and item.get("name") and item.get("homepage_url"):
            items.append(item)
        item = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped == "- category:":
            flush_item()
            pending_name_for = "category"
            subcategory = None
            continue
        if stripped == "- subcategory:":
            flush_item()
            pending_name_for = "subcategory"
            continue
        if stripped == "- item:":
            flush_item()
            item_indent = indent
            item = {
                "category": category or "",
                "subcategory": subcategory or "",
            }
            pending_name_for = None
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        scalar = _yaml_scalar(value)
        if pending_name_for == "category" and key == "name":
            category = scalar
            pending_name_for = None
            continue
        if pending_name_for == "subcategory" and key == "name":
            subcategory = scalar
            pending_name_for = None
            continue
        if item is None or item_indent is None:
            continue
        if indent != item_indent + 2 or key not in allowed_item_keys:
            continue
        item[key] = scalar
    flush_item()
    return items


def _yaml_scalar(value: str) -> str:
    stripped = value.strip()
    if stripped in {"|-", "|", ">-", ">"}:
        return ""
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped
