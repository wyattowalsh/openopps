from __future__ import annotations

import csv
import json
from functools import lru_cache
from importlib import resources
from io import StringIO
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_text_request
from openopps.models import BoardRecord, JsonDict, SourceRecord, canonical_json_hash
from openopps.models import normalize_public_website_url, validate_public_https_url
from openopps.settings import OpenOppsSettings
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
    "inclusionReason",
)

PACKAGED_PORTFOLIO_CATALOG_FILENAME = "portfolio_source_catalog.json"


def source_record_to_catalog_entry(record: SourceRecord) -> dict[str, Any]:
    return {
        "key": record.key,
        "url": record.url,
        "provider_id": record.provider_id,
        "version": dict(record.version),
        "raw_metadata": dict(record.raw_metadata),
    }


def catalog_entry_to_source_record(entry: Mapping[str, Any]) -> SourceRecord:
    return SourceRecord(
        key=str(entry["key"]),
        url=str(entry["url"]),
        provider_id=str(entry["provider_id"]),
        version=dict(entry.get("version") or {}),
        raw_metadata=dict(entry.get("raw_metadata") or {}),
    )


def portfolio_source_catalog_fingerprint(
    entries: Sequence[Mapping[str, Any]],
) -> str:
    """Stable hash over sorted source keys and canonical URLs."""

    pairs = sorted(
        (str(entry["key"]), str(entry["url"]))
        for entry in entries
        if entry.get("key") and entry.get("url")
    )
    return canonical_json_hash(pairs)


@lru_cache(maxsize=1)
def load_packaged_portfolio_source_records() -> tuple[SourceRecord, ...]:
    """Load portfolio/public-page packaged catalog entries from package data."""

    package = "openopps.providers.sources.data"
    resource = resources.files(package).joinpath(PACKAGED_PORTFOLIO_CATALOG_FILENAME)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(
            f"{PACKAGED_PORTFOLIO_CATALOG_FILENAME} must contain an 'entries' list"
        )
    records = tuple(
        catalog_entry_to_source_record(entry)
        for entry in entries
        if isinstance(entry, dict)
    )
    expected_count = payload.get("count")
    if isinstance(expected_count, int) and expected_count != len(records):
        raise ValueError(
            f"{PACKAGED_PORTFOLIO_CATALOG_FILENAME} count mismatch: "
            f"expected {expected_count}, got {len(records)}"
        )
    fingerprint = payload.get("fingerprint")
    if isinstance(fingerprint, str):
        actual = portfolio_source_catalog_fingerprint(entries)
        if fingerprint != actual:
            raise ValueError(
                f"{PACKAGED_PORTFOLIO_CATALOG_FILENAME} fingerprint mismatch: "
                f"expected {fingerprint}, got {actual}"
            )
    keys = [record.key for record in records]
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise ValueError(
            "Packaged portfolio catalog has duplicate keys: "
            + ", ".join(duplicates)
        )
    return records


def source_taxonomy_metadata(
    *,
    provider_type: str,
    coverage_mode: str,
    access_type: str,
    license_status: str,
    refresh_cadence: str,
    source_category: str,
    source_attribution: str,
    inclusion_reason: str,
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
        "inclusionReason": inclusion_reason,
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
    settings = getattr(client, "_openopps_settings", None)
    if isinstance(settings, OpenOppsSettings):
        return await retrying_text_request(settings)(
            client,
            "GET",
            url,
            headers={"accept": accept},
            follow_redirects=True,
        )
    response = await client.get(url, headers={"accept": accept}, follow_redirects=True)
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
