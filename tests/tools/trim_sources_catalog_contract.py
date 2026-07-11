"""One-shot maintainer helper: remove inlined catalog contract from integration tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tests/integration/openopps/test_sources.py"

START = "###CATALOG_CHUNK###"
END = "###CATALOG_END###"


def main() -> None:
    text = TARGET.read_text()
    if START not in text:
        print("no catalog chunk marker; nothing to trim")
        return
    start_idx = text.index(START)
    end_idx = text.index(END)
    trimmed = text[:start_idx] + text[end_idx + len(END) :].lstrip("\n")
    TARGET.write_text(trimmed)
    print(f"trimmed {TARGET} ({len(text)} -> {len(trimmed)} bytes)")


if __name__ == "__main__":
    main()