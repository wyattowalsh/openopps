# ONE-SHOT maintainer script: refuse re-running after portfolio catalog is extracted.
"""Phase C: drop inline portfolio catalog from special.py after JSON is written."""

from __future__ import annotations

from pathlib import Path

SPECIAL = Path(__file__).resolve().parents[1] / "src/openopps/providers/sources/special.py"


def _remove_assign_block(text: str, name: str) -> str:
    start = text.find(f"{name}:")
    if start < 0:
        raise SystemExit(f"missing {name}")
    open_paren = text.find("(", start)
    depth = 0
    end = None
    for index in range(open_paren, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(text) and text[end] in "\r\n":
                    end += 1
                break
    if end is None:
        raise SystemExit(f"unterminated {name}")
    return text[:start] + text[end:]


def main() -> None:
    text = SPECIAL.read_text(encoding="utf-8")
    if "load_packaged_portfolio_source_records" not in text:
        text = text.replace(
            "from openopps.providers.sources.source_utils import source_taxonomy_metadata",
            "from openopps.providers.sources.source_utils import (\n"
            "    load_packaged_portfolio_source_records,\n"
            "    source_taxonomy_metadata,\n)",
        )
    text = text.replace("    *PUBLIC_PAGE_SOURCES,\n", "")
    text = text.replace(
        "    *_PORTFOLIO_INLINE_SOURCE_RECORDS,\n",
        "    *load_packaged_portfolio_source_records(),\n",
    )
    text = _remove_assign_block(text, "PUBLIC_PAGE_SOURCES")
    text = _remove_assign_block(text, "_PORTFOLIO_INLINE_SOURCE_RECORDS")
    SPECIAL.write_text(text, encoding="utf-8")
    print(f"finalized {SPECIAL}")


if __name__ == "__main__":
    main()