#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json

from openopps.route_probe import probe_routes
from openopps.route_select import normalize_provider_filter
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe missing provider route tokens for known OpenOpps boards.")
    parser.add_argument("--source")
    parser.add_argument("--board")
    parser.add_argument("--provider", choices=["any", "all", "ashbyhq", "greenhouse", "lever", "workday"])
    parser.add_argument("--apply", action="store_true", help="Persist matched routes to the configured DB.")
    parser.add_argument("--include-existing", action="store_true", help="Probe routes even if they already have route metadata.")
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    settings = OpenOppsSettings()
    summary = asyncio.run(
        probe_routes(
            settings=settings,
            store=OpenOppsStore(settings),
            source_key=args.source,
            board_key=args.board,
            provider_id=normalize_provider_filter(args.provider),
            only_missing=not args.include_existing,
            apply=args.apply,
            max_candidates=args.max_candidates,
            limit=args.limit,
        )
    )
    print(json.dumps(summary.as_dict(), default=str, indent=2))


if __name__ == "__main__":
    main()
