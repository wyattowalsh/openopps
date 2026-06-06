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
    uv run python scripts/generate_kaggle_metadata.py --data-db "{{ db }}"

# Validate generated Kaggle metadata and optional SQLite/CSV/Parquet bundle surfaces locally.
kaggle-bundle-check db="kaggle/openoppsdb.sqlite":
    @if [ -f "{{ db }}" ]; then uv run python scripts/generate_kaggle_metadata.py --data-db "{{ db }}"; else echo "No SQLite DB at {{ db }}; validating metadata-only Kaggle bundle."; uv run python scripts/generate_kaggle_metadata.py; fi
    uv run pytest tests/unit/openopps/test_kaggle_metadata.py -q

# Create the public OpenOppsDB Kaggle dataset from the local kaggle/ bundle.
kaggle-dataset-create:
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle datasets create -p kaggle --public -q -t -r zip

# Version the public OpenOppsDB Kaggle dataset from the local kaggle/ bundle.
kaggle-dataset-version message="OpenOppsDB snapshot":
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle datasets version -p kaggle -m "{{ message }}" -q -t -r zip

# Push the connected OpenOppsDB manager notebook to Kaggle.
kaggle-notebook-push:
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle kernels push -p kaggle

# Show live OpenOppsDB dataset status from Kaggle.
kaggle-live-status:
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle datasets status wyattowalsh/openoppsdb --format json

# List live OpenOppsDB dataset files from Kaggle.
kaggle-live-files page_size="200":
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle datasets files wyattowalsh/openoppsdb --page-size "{{ page_size }}"

# Download live OpenOppsDB dataset metadata from Kaggle.
kaggle-live-metadata output="/tmp/openoppsdb-kaggle-metadata":
    @mkdir -p "{{ output }}"
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle datasets metadata wyattowalsh/openoppsdb -p "{{ output }}"

# Show live OpenOppsDB manager notebook availability from Kaggle.
kaggle-notebook-status:
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; listing="$(KAGGLE_API_TOKEN="$token" kaggle kernels list --mine --page-size 100)"; echo "$listing"; echo "$listing" | awk '$1 == "wyattowalsh/openoppsdb-manager" { found=1 } END { exit !found }'

# List live OpenOppsDB manager notebook files from Kaggle.
kaggle-notebook-files page_size="200":
    @token="${KAGGLE_API_TOKEN:-$(kaggle auth print-access-token 2>/dev/null || true)}"; if [ -z "$token" ]; then echo "Kaggle OAuth credentials missing; run 'kaggle auth login' first or set KAGGLE_API_TOKEN." >&2; exit 1; fi; KAGGLE_API_TOKEN="$token" kaggle kernels files wyattowalsh/openoppsdb-manager --page-size "{{ page_size }}"

# Run the live non-destructive Kaggle status/file verification commands.
kaggle-live-verify: kaggle-live-status kaggle-live-files kaggle-live-metadata kaggle-notebook-status kaggle-notebook-files

# List OpenSpec changes as agent-readable JSON.
openspec-list:
    {{ openspec }} list --json

# Show one OpenSpec change status as agent-readable JSON.
openspec-status change="prepare-v0-1-release":
    {{ openspec }} status --change "{{ change }}" --json

# Show OpenSpec task instructions for one change as agent-readable JSON.
openspec-tasks change="prepare-v0-1-release":
    {{ openspec }} instructions --change "{{ change }}" tasks --json

# Validate one OpenSpec change strictly.
openspec-validate change="prepare-v0-1-release":
    {{ openspec }} validate "{{ change }}" --strict

# Validate all active OpenSpec changes strictly.
openspec-validate-all:
    {{ openspec }} validate --all --strict

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
