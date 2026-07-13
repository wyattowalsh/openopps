# ONE-SHOT maintainer script: refuse re-running after portfolio catalog is extracted.
"""Export packaged portfolio catalog JSON from special.py (phases A–B)."""

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


def main() -> None:
    public_page = tuple(getattr(special, "PUBLIC_PAGE_SOURCES", ()))
    inline = tuple(getattr(special, "_PORTFOLIO_INLINE_SOURCE_RECORDS", ()))
    if not inline:
        raise SystemExit("special._PORTFOLIO_INLINE_SOURCE_RECORDS is empty or missing")
    records: list[SourceRecord] = [*public_page, *inline]
    keys = [record.key for record in records]
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise SystemExit(f"duplicate portfolio catalog keys: {', '.join(duplicates)}")
    entries = [source_record_to_catalog_entry(record) for record in records]
    entries.sort(key=lambda item: item["key"])
    fingerprint = portfolio_source_catalog_fingerprint(entries)
    payload = {
        "version": 1,
        "fingerprint": fingerprint,
        "count": len(entries),
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} entries to {OUTPUT}")
    print(f"fingerprint={fingerprint}")


if __name__ == "__main__":
    main()