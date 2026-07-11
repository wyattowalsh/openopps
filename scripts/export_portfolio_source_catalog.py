"""One-shot exporter: serialize packaged portfolio source records from special.py to JSON.

Run before removing inline catalog literals from special.py:

    uv run python scripts/export_portfolio_source_catalog.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openopps.models import SourceRecord  # noqa: E402
from openopps.providers.sources import special  # noqa: E402
from openopps.providers.sources.source_utils import (  # noqa: E402
    portfolio_source_catalog_fingerprint,
    source_record_to_catalog_entry,
)

OUTPUT = (
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "portfolio_source_catalog.json"
)


def _collect_records() -> list[SourceRecord]:
    inline = getattr(special, "_PORTFOLIO_INLINE_SOURCE_RECORDS", None)
    if inline is None:
        raise SystemExit(
            "special._PORTFOLIO_INLINE_SOURCE_RECORDS is missing; "
            "run this exporter after defining the inline tuple."
        )
    public_page = tuple(getattr(special, "PUBLIC_PAGE_SOURCES", ()))
    combined = [*public_page, *inline]
    keys = [record.key for record in combined]
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise SystemExit(f"duplicate portfolio catalog keys: {', '.join(duplicates)}")
    return combined


def main() -> None:
    records = _collect_records()
    entries = [source_record_to_catalog_entry(record) for record in records]
    entries.sort(key=lambda item: item["key"])
    payload = {
        "version": 1,
        "fingerprint": portfolio_source_catalog_fingerprint(entries),
        "count": len(entries),
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(entries)} entries to {OUTPUT}")
    print(f"fingerprint={payload['fingerprint']}")


if __name__ == "__main__":
    main()