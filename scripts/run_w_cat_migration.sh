#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
LOC_BEFORE="$(wc -l < src/openopps/providers/sources/special.py | tr -d ' ')"
uv run python scripts/migrate_portfolio_catalog.py
uv run python scripts/finalize_portfolio_catalog.py
LOC_AFTER="$(wc -l < src/openopps/providers/sources/special.py | tr -d ' ')"
echo "special.py LOC before=${LOC_BEFORE} after=${LOC_AFTER}"
uv run pytest tests/unit/openopps/test_source_registry.py tests/unit/openopps/test_source_scope.py tests/integration/openopps/test_sources.py tests/unit/openopps/test_portfolio_source_catalog.py -q