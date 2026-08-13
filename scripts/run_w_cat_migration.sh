#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Tombstone for the completed portfolio-catalog extraction. The former
# mutation pipeline is intentionally unavailable; this exact-fingerprint gate
# is the only supported operation.
exec uv run python scripts/migrate_portfolio_catalog.py --verify-archived "$@"
