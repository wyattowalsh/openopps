set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

openspec := env_var_or_default("OPENOPPS_OPENSPEC", "npx -y @fission-ai/openspec@1.6.0")
kaggle := "uv run --with kaggle kaggle"
kaggle-gen := "PYTHONPATH=scripts uv run python -m openopps_kaggle"

default:
    @just --list

# Install Python dependencies for local development.
setup:
    uv sync
    cd web && pnpm install

# Fast local confidence checks.
quick: cli-help test-cli openspec-list openspec-validate-all

# Full local validation graph matching primary CI lanes.
ci: diff-check lock-check openspec-validate-all test-cov web-check web-build web-test web-e2e web-a11y web-lint kaggle-meta cli-help

# CI plus network-dependent security audits (GHA Security job parity).
ci-full: ci security-audit wheel-catalog-smoke

# Local parity with GHA security job (requires network).
security-audit: security-audit-python security-audit-docs

security-audit-python:
    uv export --frozen --all-extras --dev --no-hashes -o /tmp/requirements-audit.txt
    uvx pip-audit -r /tmp/requirements-audit.txt --progress-spinner off

security-audit-docs:
    cd web && pnpm audit --prod --audit-level high

# Build a wheel and confirm packaged portfolio catalog is importable.
wheel-catalog-smoke:
    uv build --wheel -o /tmp/openopps-wheels
    uv run python scripts/smoke_wheel_catalog.py

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

# --- Web app (Next/Fumadocs; formerly docs/) ---

# Generate package-derived web data.
web-generate:
    cd web && pnpm data:generate

# Generate the static search-index snapshot from the local Kaggle SQLite DB.
# Requires a clean-schema kaggle/openoppsdb.sqlite (not a legacy root openoppsdb.sqlite).
web-search-index:
    @if [ ! -f kaggle/openoppsdb.sqlite ]; then echo "Missing kaggle/openoppsdb.sqlite; download or export a clean public snapshot (no sources.enabled) before regenerating search artifacts. CI does not regenerate from SQLite."; exit 1; fi
    cd web && pnpm data:generate:search

# Verify the committed search-index artifact graph is complete.
web-search-artifacts-check:
    uv run python scripts/verify_docs_search_artifacts.py --root web/public/data/openopps-search --require-git-tracked

# Require the committed search-index snapshot to match a local Kaggle SQLite DB.
web-search-index-check:
    @if [ ! -f kaggle/openoppsdb.sqlite ]; then echo "Missing kaggle/openoppsdb.sqlite; refresh or download a clean public snapshot (no sources.enabled) before running web-search-index-check. CI validates committed artifacts only."; exit 1; fi
    cd web && pnpm data:generate:search
    uv run python scripts/verify_docs_search_artifacts.py --root web/public/data/openopps-search --require-git-tracked
    git diff --exit-code -- web/public/data/openopps-search

# Generate data, MDX output, Next route types, and TypeScript checks.
web-check:
    cd web && pnpm types:check
    uv run pytest tests/unit/openopps/test_docs_search_index.py -k committed

# Build the Fumadocs/Next.js web app.
web-build:
    cd web && NEXT_TELEMETRY_DISABLED=1 CI=true pnpm build
    just web-function-trace-check

# Verify API function traces do not bundle committed search artifacts.
web-function-trace-check:
    uv run python scripts/verify_docs_function_trace.py

# Run web unit tests.
web-test:
    cd web && pnpm test

# Run browser E2E checks for the production-built public surface and jobs board.
web-e2e: web-build
    cd web && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium

# Run focused browser accessibility checks against the production build.
web-a11y: web-build
    cd web && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=mobile-chromium accessibility.spec.ts

# Run focused SEO/static-route browser checks against the production build.
web-seo-check: web-build
    cd web && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium seo-static.spec.ts seo-job-detail.spec.ts routes.spec.ts

# Run web lint surfaces.
web-lint:
    cd web && pnpm lint

# Run optional maintainer web lint that requires rtk locally.
web-rtk-lint:
    cd web && rtk lint

# Transition aliases (docs-* → web-*).
docs-generate: web-generate
docs-search-index: web-search-index
docs-search-artifacts-check: web-search-artifacts-check
docs-search-index-check: web-search-index-check
docs-check: web-check
docs-build: web-build
docs-function-trace-check: web-function-trace-check
docs-test: web-test
docs-e2e: web-e2e
docs-a11y: web-a11y
docs-seo-check: web-seo-check
docs-lint: web-lint
docs-rtk-lint: web-rtk-lint

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

# Non-secret CI/local smoke: init a clean temp DB, generate bundle artifacts, stage public upload.
kaggle-bundle-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    db="$work/openoppsdb.sqlite"
    OPENOPPS_DB_URL="sqlite:///$db" uv run openopps admin db init
    out="$work/kaggle-out"
    mkdir -p "$out"
    # Seed cover image so generate does not require network (repo-root social asset or committed kaggle cover).
    if [[ -f web/public/social/openoppsdb.png ]]; then
      cp web/public/social/openoppsdb.png "$out/dataset-cover-image.png"
    elif [[ -f kaggle/dataset-cover-image.png ]]; then
      cp kaggle/dataset-cover-image.png "$out/dataset-cover-image.png"
    fi
    PYTHONPATH=scripts uv run python -m openopps_kaggle --output-dir "$out" --data-db "$db" --skip-notebooks
    stage="$work/stage"
    mkdir -p "$stage"
    PYTHONPATH=scripts uv run python -m openopps_kaggle --output-dir "$out" --stage-public-upload-dir "$stage" --skip-notebooks
    test -f "$stage/openoppsdb.sqlite"
    test -f "$stage/dataset-metadata.json"
    # Public stage must not include private evidence.
    ! test -f "$stage/sync_metrics.json"
    ! test -f "$stage/snapshot-quality.json"

# Create the private OpenOppsDB manager runtime generator Kaggle dataset.
kaggle-runtime-generator-create:
    @upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-runtime-generator-dir "$upload_dir"; {{ kaggle }} datasets create -p "$upload_dir" -q -t -r zip

# Version the private OpenOppsDB manager runtime generator Kaggle dataset.
kaggle-runtime-generator-version message="OpenOppsDB manager runtime generator":
    @message="{{ message }}"; message="${message#message=}"; upload_dir="$(mktemp -d)"; trap 'rm -rf "$upload_dir"' EXIT; {{ kaggle-gen }} --stage-runtime-generator-dir "$upload_dir"; {{ kaggle }} datasets version -p "$upload_dir" -m "$message" -q -t -r zip

# Create the public OpenOppsDB Kaggle dataset from a rebuild+stage data-only bundle.
# Requires db=<sqlite path> by default. Pass allow_stale=1 only to stage the current
# kaggle/ tree without rebuild (loud warning; not for normal publishes).
kaggle-dataset-create db="" allow_stale="0":
    #!/usr/bin/env bash
    db="{{ db }}"; db="${db#db=}"
    allow_stale="{{ allow_stale }}"; allow_stale="${allow_stale#allow_stale=}"
    if [[ "$allow_stale" == "1" || "$allow_stale" == "true" ]]; then
      echo "WARNING: allow_stale=1 stages current kaggle/ without rebuild-from-db. Prefer db=<clean.sqlite>." >&2
    else
      if [[ -z "$db" ]]; then
        echo "error: kaggle-dataset-create requires db=<path-to-clean-openoppsdb.sqlite> (or allow_stale=1)." >&2
        exit 1
      fi
      if [[ ! -f "$db" ]]; then
        echo "error: SQLite database not found: $db" >&2
        exit 1
      fi
      {{ kaggle-gen }} --data-db "$db"
    fi
    upload_dir="$(mktemp -d)"
    trap 'rm -rf "$upload_dir"' EXIT
    {{ kaggle-gen }} --stage-public-upload-dir "$upload_dir"
    {{ kaggle }} datasets create -p "$upload_dir" --public -q -t -r zip

# Version the public OpenOppsDB Kaggle dataset from a rebuild+stage data-only bundle.
# Requires db=<sqlite path> by default. Pass allow_stale=1 only to stage the current
# kaggle/ tree without rebuild (loud warning; not for normal publishes).
kaggle-dataset-version message="OpenOppsDB snapshot" db="" allow_stale="0":
    #!/usr/bin/env bash
    message="{{ message }}"; message="${message#message=}"
    db="{{ db }}"; db="${db#db=}"
    allow_stale="{{ allow_stale }}"; allow_stale="${allow_stale#allow_stale=}"
    if [[ "$allow_stale" == "1" || "$allow_stale" == "true" ]]; then
      echo "WARNING: allow_stale=1 stages current kaggle/ without rebuild-from-db. Prefer db=<clean.sqlite>." >&2
    else
      if [[ -z "$db" ]]; then
        echo "error: kaggle-dataset-version requires db=<path-to-clean-openoppsdb.sqlite> (or allow_stale=1)." >&2
        exit 1
      fi
      if [[ ! -f "$db" ]]; then
        echo "error: SQLite database not found: $db" >&2
        exit 1
      fi
      {{ kaggle-gen }} --data-db "$db"
    fi
    current_version="$({{ kaggle }} datasets status wyattowalsh/openoppsdb --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["current_version_number"])')"
    next_version="$((current_version + 1))"
    upload_dir="$(mktemp -d)"
    trap 'rm -rf "$upload_dir"' EXIT
    {{ kaggle-gen }} --stage-public-upload-dir "$upload_dir"
    {{ kaggle }} datasets version -p "$upload_dir" -m "$message" -q -t -r zip
    PYTHONPATH=scripts uv run --with kaggle --with browser-cookie3 --with requests python -m openopps_kaggle --wait-live-dataset-ready --wait-live-dataset-min-version "$next_version" --update-live-file-metadata --live-file-metadata-browser-cookies

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
# Pass change=<name> when an active change exists; archived changes are under openspec/changes/archive/.
openspec-status change="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "{{ change }}" ]]; then
      {{ openspec }} list --json
    else
      {{ openspec }} status --change "{{ change }}" --json
    fi

# Show OpenSpec task instructions for one change as agent-readable JSON.
openspec-tasks change="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "{{ change }}" ]]; then
      echo "usage: just openspec-tasks change=<active-change-name>" >&2
      exit 2
    fi
    {{ openspec }} instructions --change "{{ change }}" tasks --json

# Validate one OpenSpec change strictly.
openspec-validate change="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -z "{{ change }}" ]]; then
      {{ openspec }} validate --all --strict
    else
      {{ openspec }} validate "{{ change }}" --strict
    fi

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
