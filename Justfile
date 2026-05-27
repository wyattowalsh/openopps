set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

openspec := env_var_or_default("OPENOPPS_OPENSPEC", "npx -y @fission-ai/openspec@latest")

default:
    @just --list

# Install Python dependencies for local development.
setup:
    uv sync
    cd docs && pnpm install

# Fast local confidence checks.
quick: cli-help test-cli openspec-status

# Full local validation graph matching CI lanes.
ci: diff-check openspec-validate-all test-cov docs-check docs-build docs-lint kaggle-meta cli-help

# Run the full pytest suite.
test:
    uv run pytest

# Run coverage-enforced pytest.
test-cov:
    uv run pytest --cov=openopps --cov-report=term-missing

# Run focused CLI integration tests.
test-cli:
    uv run pytest tests/integration/openopps/test_cli.py -q

# Generate package-derived docs data.
docs-generate:
    cd docs && pnpm data:generate

# Generate docs data, MDX output, Next route types, and TypeScript checks.
docs-check:
    cd docs && pnpm types:check

# Build the Fumadocs/Next.js docs site.
docs-build:
    @if [ "$(uname -s)" = "Darwin" ]; then zsh -lc 'cd docs && pnpm build'; else cd docs && pnpm build; fi

# Run docs lint surfaces.
docs-lint:
    cd docs && pnpm lint
    @if command -v rtk >/dev/null 2>&1; then cd docs && rtk lint; else echo "rtk not found; skipped docs rtk lint"; fi

# Generate deterministic Kaggle metadata without bundling local data files.
kaggle-meta:
    uv run python scripts/generate_kaggle_metadata.py

# Generate Kaggle metadata and table exports from an existing SQLite DB.
kaggle-bundle db="kaggle/openoppsdb.sqlite":
    uv run python scripts/generate_kaggle_metadata.py --data-db "{{db}}"

# List OpenSpec changes as agent-readable JSON.
openspec-list:
    {{openspec}} list --json

# Show one OpenSpec change status as agent-readable JSON.
openspec-status change="prepare-v0-1-release":
    {{openspec}} status --change "{{change}}" --json

# Show OpenSpec task instructions for one change as agent-readable JSON.
openspec-tasks change="prepare-v0-1-release":
    {{openspec}} instructions --change "{{change}}" tasks --json

# Validate one OpenSpec change strictly.
openspec-validate change="prepare-v0-1-release":
    {{openspec}} validate "{{change}}" --strict

# Validate all active OpenSpec changes strictly.
openspec-validate-all:
    {{openspec}} validate --all --strict

# Smoke root and key command help.
cli-help:
    uv run openopps --no-intro --help > /tmp/openopps-root-help.txt
    uv run openopps sync --help > /tmp/openopps-sync-help.txt
    uv run openopps providers --help > /tmp/openopps-providers-help.txt
    uv run openopps admin providers probe-routes --help > /tmp/openopps-probe-routes-help.txt

# Check whitespace and patch formatting in the current diff.
diff-check:
    git diff --check

# Dry-run ignored/local artifact cleanup candidates.
clean-ignored-dry-run:
    git clean -ndX
