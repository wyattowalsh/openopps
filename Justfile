set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

openspec := env_var_or_default("OPENOPPS_OPENSPEC", "npx -y @fission-ai/openspec@latest")
kaggle := "uv run --with kaggle kaggle"
kaggle-gen := "PYTHONPATH=scripts uv run python -m openopps_kaggle"

default:
    @just --list

# Install Python dependencies for local development.
setup:
    uv sync
    cd docs && pnpm install

# Fast local confidence checks.
quick: cli-help test-cli openspec-status

# Full local validation graph matching CI lanes.
ci: diff-check lock-check openspec-validate-all test-cov docs-check docs-build docs-test docs-e2e docs-lint kaggle-meta cli-help

# Check that uv.lock is current for pyproject.toml.
lock-check:
    uv lock --check

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

# Generate the static docs search-index snapshot from the local Kaggle SQLite DB.
docs-search-index:
    cd docs && pnpm data:generate:search

# Require the committed docs search-index snapshot to match a local Kaggle SQLite DB.
docs-search-index-check:
    @if [ ! -f kaggle/openoppsdb.sqlite ]; then echo "Missing kaggle/openoppsdb.sqlite; refresh or download the local snapshot before running docs-search-index-check."; exit 1; fi
    cd docs && pnpm data:generate:search
    git diff --exit-code -- docs/public/data/openopps-search

# Generate docs data, MDX output, Next route types, and TypeScript checks.
docs-check:
    cd docs && pnpm types:check

# Build the Fumadocs/Next.js docs site.
docs-build:
    cd docs && NEXT_TELEMETRY_DISABLED=1 CI=true pnpm build

# Run docs unit tests.
docs-test:
    cd docs && pnpm test

# Run browser E2E checks for the production-built public docs and jobs board surface.
docs-e2e: docs-build
    cd docs && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium

# Run focused browser accessibility checks against the production build.
docs-a11y: docs-build
    cd docs && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium accessibility.spec.ts

# Run focused SEO/static-route browser checks against the production build.
docs-seo-check: docs-build
    cd docs && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium seo-static.spec.ts seo-job-detail.spec.ts routes.spec.ts

# Run docs lint surfaces.
docs-lint:
    cd docs && pnpm lint

# Run optional maintainer docs lint that requires rtk locally.
docs-rtk-lint:
    cd docs && rtk lint

# Generate deterministic Kaggle metadata without bundling local data files.
kaggle-meta:
    {{ kaggle-gen }}

# Generate Kaggle metadata and table exports from an existing SQLite DB.
kaggle-bundle db="kaggle/openoppsdb.sqlite":
    @db="{{ db }}"; {{ kaggle-gen }} --data-db "${db#db=}"

# Validate generated Kaggle metadata and optional SQLite/CSV/Parquet bundle surfaces locally.
kaggle-bundle-check db="kaggle/openoppsdb.sqlite":
    @db="{{ db }}"; db="${db#db=}"; if [ -f "$db" ]; then {{ kaggle-gen }} --data-db "$db"; else echo "No SQLite DB at $db; validating metadata-only Kaggle bundle."; {{ kaggle-gen }}; fi
    uv run pytest tests/unit/openopps/kaggle/ -q

# Create the private OpenOppsDB manager runtime generator Kaggle dataset.
kaggle-runtime-generator-create:
    @upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-runtime-generator-dir "$upload_dir"; {{ kaggle }} datasets create -p "$upload_dir" -q -t -r zip

# Version the private OpenOppsDB manager runtime generator Kaggle dataset.
kaggle-runtime-generator-version message="OpenOppsDB manager runtime generator":
    @message="{{ message }}"; message="${message#message=}"; upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-runtime-generator-dir "$upload_dir"; {{ kaggle }} datasets version -p "$upload_dir" -m "$message" -q -t -r zip

# Create the public OpenOppsDB Kaggle dataset from a staged data-only bundle.
kaggle-dataset-create:
    @upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-public-upload-dir "$upload_dir"; {{ kaggle }} datasets create -p "$upload_dir" --public -q -t -r zip

# Version the public OpenOppsDB Kaggle dataset from a staged data-only bundle.
kaggle-dataset-version message="OpenOppsDB snapshot":
    @message="{{ message }}"; message="${message#message=}"; current_version="$({{ kaggle }} datasets status wyattowalsh/openoppsdb --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["current_version_number"])')"; next_version="$((current_version + 1))"; upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-public-upload-dir "$upload_dir"; {{ kaggle }} datasets version -p "$upload_dir" -m "$message" -q -t -r zip; PYTHONPATH=scripts uv run --with kaggle --with browser-cookie3 --with requests python -m openopps_kaggle --wait-live-dataset-ready --wait-live-dataset-min-version "$next_version" --update-live-file-metadata --live-file-metadata-browser-cookies

# Update live OpenOppsDB file descriptions and column metadata on Kaggle.
kaggle-live-file-metadata:
    PYTHONPATH=scripts uv run --with kaggle --with browser-cookie3 --with requests python -m openopps_kaggle --update-live-file-metadata --live-file-metadata-browser-cookies

# Push the connected OpenOppsDB manager notebook to Kaggle.
kaggle-notebook-push timeout="3600":
    @timeout="{{ timeout }}"; {{ kaggle }} kernels push -p kaggle --timeout "${timeout#timeout=}"

# Push the public OpenOppsDB starter notebook to Kaggle.
kaggle-starter-notebook-push timeout="3600":
    @timeout="{{ timeout }}"; {{ kaggle }} kernels push -p kaggle/starter --timeout "${timeout#timeout=}"

# Push all public OpenOppsDB example notebooks to Kaggle.
kaggle-example-notebooks-push timeout="3600":
    @timeout="{{ timeout }}"; timeout="${timeout#timeout=}"; for dir in kaggle/starter kaggle/examples/advanced-usage kaggle/examples/hiring-market-map kaggle/examples/skills-radar; do {{ kaggle }} kernels push -p "$dir" --timeout "$timeout"; done

# Show live OpenOppsDB dataset status from Kaggle.
kaggle-live-status:
    {{ kaggle }} datasets status wyattowalsh/openoppsdb --format json

# List live OpenOppsDB dataset files from Kaggle.
kaggle-live-files page_size="200":
    @page_size="{{ page_size }}"; {{ kaggle }} datasets files wyattowalsh/openoppsdb --page-size "${page_size#page_size=}"

# Verify live OpenOppsDB readback through KaggleHub adapters.
kagglehub-live-readback dataset="wyattowalsh/openoppsdb" version="":
    @dataset="{{ dataset }}"; version="{{ version }}"; if [[ "$dataset" == dataset=* ]]; then dataset="${dataset#dataset=}"; fi; if [[ "$dataset" == version=* ]]; then version="${dataset#version=}"; dataset="wyattowalsh/openoppsdb"; fi; if [[ "$version" == version=* ]]; then version="${version#version=}"; fi; version_arg=""; if [ -n "$version" ]; then version_arg="--version $version"; fi; PYTHONPATH=scripts uv run --with 'kagglehub[polars-datasets]' python -m openopps_kaggle verify-readback --dataset "$dataset" $version_arg

# Download live OpenOppsDB dataset metadata from Kaggle.
kaggle-live-metadata output="/tmp/openoppsdb-kaggle-metadata":
    @output="{{ output }}"; output="${output#output=}"; mkdir -p "$output"; {{ kaggle }} datasets metadata wyattowalsh/openoppsdb -p "$output"

# Show live OpenOppsDB manager notebook availability from Kaggle.
kaggle-notebook-status:
    @status="$({{ kaggle }} kernels status wyattowalsh/openoppsdb-manager)"; echo "$status"; echo "$status" | grep -q 'KernelWorkerStatus.COMPLETE'

# List live OpenOppsDB manager notebook files from Kaggle.
kaggle-notebook-files page_size="200":
    @page_size="{{ page_size }}"; {{ kaggle }} kernels files wyattowalsh/openoppsdb-manager --page-size "${page_size#page_size=}"

# Show live OpenOppsDB starter notebook status from Kaggle.
kaggle-starter-notebook-status:
    @status="$({{ kaggle }} kernels status wyattowalsh/openoppsdb-starter-notebook)"; echo "$status"; echo "$status" | grep -q 'KernelWorkerStatus.COMPLETE'

# Show live OpenOppsDB public example notebook statuses from Kaggle.
kaggle-example-notebooks-status:
    @for kernel in wyattowalsh/openoppsdb-starter-notebook wyattowalsh/openoppsdb-advanced-usage wyattowalsh/openoppsdb-hiring-market-map wyattowalsh/openoppsdb-skills-radar; do status="$({{ kaggle }} kernels status "$kernel")"; echo "$status"; echo "$status" | grep -q 'KernelWorkerStatus.COMPLETE'; done

# Pull and verify live OpenOppsDB public example notebook source bundles from Kaggle.
kaggle-example-notebooks-pull-check:
    @tmp_dir="$(mktemp -d)"; trap 'rm -rf "$tmp_dir"' EXIT; for kernel in wyattowalsh/openoppsdb-starter-notebook wyattowalsh/openoppsdb-advanced-usage wyattowalsh/openoppsdb-hiring-market-map wyattowalsh/openoppsdb-skills-radar; do slug="${kernel#*/}"; mkdir -p "$tmp_dir/$slug"; {{ kaggle }} kernels pull "$kernel" -p "$tmp_dir/$slug" -m >/dev/null; done; PYTHONPATH=scripts uv run python -m openopps_kaggle verify-notebooks "$tmp_dir"

# List output files emitted by live OpenOppsDB public example notebook runs.
kaggle-example-notebooks-files page_size="200":
    @page_size="{{ page_size }}"; page_size="${page_size#page_size=}"; for kernel in wyattowalsh/openoppsdb-starter-notebook wyattowalsh/openoppsdb-advanced-usage wyattowalsh/openoppsdb-hiring-market-map wyattowalsh/openoppsdb-skills-radar; do echo "== $kernel =="; {{ kaggle }} kernels files "$kernel" --page-size "$page_size"; done

# Run the live non-destructive Kaggle status/file verification commands.
kaggle-live-verify: kaggle-live-status kaggle-live-files kagglehub-live-readback kaggle-live-metadata kaggle-notebook-status kaggle-notebook-files kaggle-starter-notebook-status kaggle-example-notebooks-status kaggle-example-notebooks-pull-check

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
