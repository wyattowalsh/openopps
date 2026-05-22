from __future__ import annotations

import json
from pathlib import Path

from openopps.docs_data import build_docs_data


def main() -> None:
    output_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "lib"
        / "generated"
        / "openopps-data.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_docs_data(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
