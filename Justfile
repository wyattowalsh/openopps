set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set positional-arguments

openspec := "npx -y @fission-ai/openspec@1.6.0"
kaggle := "uv run --frozen --group ops kaggle"
kaggle-gen := "PYTHONPATH=scripts uv run python -m openopps_kaggle"
kaggle-ops-gen := "PYTHONPATH=scripts uv run --frozen --group ops python -m openopps_kaggle"

default:
    @just --list

# Install Python dependencies for local development.
setup:
    uv sync
    cd web && pnpm install

# Fast local confidence checks.
quick: python-quality cli-help test-cli openspec-list openspec-validate-all

# Canonical local validation graph. GitHub Actions invokes the same lane recipes.
ci: ci-python ci-openspec ci-web ci-artifacts

# Python 3.12 release gate.
ci-python: lock-check python-quality test-cov cli-help wheel-catalog-smoke

# Compatibility gate used by the Python 3.13/3.14 CI matrix lanes.
ci-python-compat: lock-check test

# OpenSpec contract gate.
ci-openspec: openspec-list openspec-validate-all

# Web product gate.
ci-web: web-check web-build web-test web-e2e web-a11y web-lint web-search-artifacts-check

# Generated-artifact and repository-diff gate.
ci-artifacts: kaggle-generated-diff-check kaggle-bundle-smoke diff-check

# CI plus network-dependent security audits (GHA Security job parity).
ci-full: ci security-audit test-lowest-direct

# Local parity with GHA security job (requires network).
security-audit: security-audit-python security-audit-docs

security-audit-python:
    #!/usr/bin/env bash
    set -euo pipefail
    audit_requirements="$(mktemp)"
    trap 'rm -f "$audit_requirements"' EXIT
    uv export --quiet --frozen --all-extras --all-groups --no-hashes --output-file "$audit_requirements"
    uv run --frozen pip-audit --requirement "$audit_requirements" --progress-spinner off

security-audit-docs:
    cd web && pnpm audit --audit-level high

# Build the release wheel into the conventional artifact directory.
build-wheel:
    uv build --wheel --out-dir dist

# Build a wheel and confirm packaged portfolio catalog is importable.
wheel-catalog-smoke:
    uv build --wheel --out-dir /tmp/openopps-wheels
    uv run python scripts/smoke_wheel_catalog.py

# Check that uv.lock is current for pyproject.toml.
lock-check:
    uv lock --check

# Lint the supported Python package surface.
ruff-check:
    uv run --frozen ruff check src/openopps

# Type-check the supported Python package surface.
ty-check:
    uv run --frozen ty check

# Static Python quality gate.
python-quality: ruff-check ty-check

# Run the full pytest suite.
test:
    uv run pytest

# Run coverage-enforced pytest.
test-cov:
    uv run pytest --cov=openopps --cov-report=term-missing

# Exercise the suite with the lowest direct versions without rewriting uv.lock.
test-lowest-direct:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="$PWD"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    cp pyproject.toml README.md "$work/"
    cp -R src "$work/src"
    mkdir -p "$work/examples"
    cp examples/examples.py "$work/examples/"
    (
      cd "$work"
      UV_FROZEN=0 uv lock --python 3.12 --resolution lowest-direct
      UV_FROZEN=1 uv sync --python 3.12 --all-extras --all-groups
    )
    PYTHONPATH="$repo/src:$repo/scripts${PYTHONPATH:+:$PYTHONPATH}" "$work/.venv/bin/python" -m pytest "$repo/tests"

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
    cd web && OPENOPPS_E2E_WEB_SERVER_COMMAND="pnpm exec next start -p 3211" pnpm exec playwright test --project=chromium --project=firefox --project=webkit

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

# Generate first, then fail on any byte drift in committed Kaggle artifacts.
kaggle-generated-diff-check: kaggle-meta
    git diff --exit-code -- kaggle
    @untracked="$(git ls-files --others --exclude-standard -- kaggle)"; test -z "$untracked" || { echo "Untracked generated Kaggle artifacts:" >&2; printf '%s\n' "$untracked" >&2; exit 1; }

# Generate Kaggle metadata and table exports from an existing SQLite DB.
kaggle-bundle db="kaggle/openoppsdb.sqlite":
    @db="$1"; {{ kaggle-gen }} --data-db "${db#db=}"

# Validate generated Kaggle metadata and optional SQLite/CSV/Parquet bundle surfaces locally.
kaggle-bundle-check db="kaggle/openoppsdb.sqlite":
    @db="$1"; db="${db#db=}"; if [ -f "$db" ]; then {{ kaggle-gen }} --data-db "$db"; else echo "No SQLite DB at $db; validating metadata-only Kaggle bundle."; {{ kaggle-gen }}; fi
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

# Prepare the first private runtime dataset publication. Dry-run is the default;
# live create additionally requires execute=1 allow_no_rollback=1.
kaggle-runtime-generator-create message="OpenOppsDB manager runtime generator" execute="0" allow_no_rollback="0" ledger="var/kaggle-runtime-publication-ledger.json":
    #!/usr/bin/env bash
    set -euo pipefail
    message="$1"; message="${message#message=}"
    execute="$2"; execute="${execute#execute=}"
    allow_no_rollback="$3"; allow_no_rollback="${allow_no_rollback#allow_no_rollback=}"
    ledger="$4"; ledger="${ledger#ledger=}"
    args=(publication publish --kind runtime --action create --message "$message" --ledger "$ledger")
    case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac
    case "$allow_no_rollback" in 1|true) args+=(--allow-no-rollback) ;; 0|false) ;; *) echo "allow_no_rollback must be 0/1/false/true" >&2; exit 2 ;; esac
    {{ kaggle-ops-gen }} "${args[@]}"

# Prepare a versioned private runtime publication with an exact prior rollback target.
# Supply expected_current_version=<n>; add execute=1 only after reviewing the dry-run ledger.
kaggle-runtime-generator-version message="OpenOppsDB manager runtime generator" expected_current_version="" execute="0" ledger="var/kaggle-runtime-publication-ledger.json":
    #!/usr/bin/env bash
    set -euo pipefail
    message="$1"; message="${message#message=}"
    expected_current_version="$2"; expected_current_version="${expected_current_version#expected_current_version=}"
    execute="$3"; execute="${execute#execute=}"
    ledger="$4"; ledger="${ledger#ledger=}"
    args=(publication publish --kind runtime --action version --message "$message" --expected-current-version "$expected_current_version" --ledger "$ledger")
    case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac
    {{ kaggle-ops-gen }} "${args[@]}"

# Prepare the first public OpenOppsDB publication from a clean SQLite database.
# Dry-run is the default. allow_stale=1 is a loud maintenance-only override;
# live create additionally requires execute=1 allow_no_rollback=1.
kaggle-dataset-create db="" allow_stale="0" message="OpenOppsDB initial snapshot" execute="0" allow_no_rollback="0" ledger="var/kaggle-publication-ledger.json":
    #!/usr/bin/env bash
    set -euo pipefail
    db="$1"; db="${db#db=}"
    allow_stale="$2"; allow_stale="${allow_stale#allow_stale=}"
    message="$3"; message="${message#message=}"
    execute="$4"; execute="${execute#execute=}"
    allow_no_rollback="$5"; allow_no_rollback="${allow_no_rollback#allow_no_rollback=}"
    ledger="$6"; ledger="${ledger#ledger=}"
    args=(publication publish --kind public --action create --message "$message" --ledger "$ledger")
    if [[ -n "$db" ]]; then args+=(--data-db "$db"); fi
    case "$allow_stale" in 1|true) args+=(--allow-stale) ;; 0|false) ;; *) echo "allow_stale must be 0/1/false/true" >&2; exit 2 ;; esac
    case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac
    case "$allow_no_rollback" in 1|true) args+=(--allow-no-rollback) ;; 0|false) ;; *) echo "allow_no_rollback must be 0/1/false/true" >&2; exit 2 ;; esac
    {{ kaggle-ops-gen }} "${args[@]}"

# Prepare a public OpenOppsDB version with exact stage hashes and rollback/readback argv.
# Supply expected_current_version=<n>; add execute=1 only after reviewing the dry-run ledger.
kaggle-dataset-version message="OpenOppsDB snapshot" db="" allow_stale="0" expected_current_version="" execute="0" ledger="var/kaggle-publication-ledger.json":
    #!/usr/bin/env bash
    set -euo pipefail
    message="$1"; message="${message#message=}"
    db="$2"; db="${db#db=}"
    allow_stale="$3"; allow_stale="${allow_stale#allow_stale=}"
    expected_current_version="$4"; expected_current_version="${expected_current_version#expected_current_version=}"
    execute="$5"; execute="${execute#execute=}"
    ledger="$6"; ledger="${ledger#ledger=}"
    args=(publication publish --kind public --action version --message "$message" --expected-current-version "$expected_current_version" --ledger "$ledger")
    if [[ -n "$db" ]]; then args+=(--data-db "$db"); fi
    case "$allow_stale" in 1|true) args+=(--allow-stale) ;; 0|false) ;; *) echo "allow_stale must be 0/1/false/true" >&2; exit 2 ;; esac
    case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac
    {{ kaggle-ops-gen }} "${args[@]}"

# Update live OpenOppsDB file descriptions and column metadata on Kaggle.
kaggle-live-file-metadata:
    {{ kaggle-ops-gen }} --update-live-file-metadata --live-file-metadata-browser-cookies

# Prepare or execute the connected manager notebook push through validated argv.
kaggle-notebook-push timeout="3600" execute="0":
    @timeout="$1"; timeout="${timeout#timeout=}"; execute="$2"; execute="${execute#execute=}"; args=(publication kernel-push --bundle manager --timeout-seconds "$timeout"); case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac; {{ kaggle-ops-gen }} "${args[@]}"

# Prepare or execute the public starter notebook push through validated argv.
kaggle-starter-notebook-push timeout="3600" execute="0":
    @timeout="$1"; timeout="${timeout#timeout=}"; execute="$2"; execute="${execute#execute=}"; args=(publication kernel-push --bundle starter --timeout-seconds "$timeout"); case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac; {{ kaggle-ops-gen }} "${args[@]}"

# Prepare or execute all public example notebook pushes through validated argv.
kaggle-example-notebooks-push timeout="3600" execute="0":
    @timeout="$1"; timeout="${timeout#timeout=}"; execute="$2"; execute="${execute#execute=}"; args=(publication kernel-push --bundle examples --timeout-seconds "$timeout"); case "$execute" in 1|true) args+=(--execute) ;; 0|false) ;; *) echo "execute must be 0/1/false/true" >&2; exit 2 ;; esac; {{ kaggle-ops-gen }} "${args[@]}"

# Show live OpenOppsDB dataset status from Kaggle.
kaggle-live-status:
    {{ kaggle }} datasets status wyattowalsh/openoppsdb --format json

# List live OpenOppsDB dataset files from Kaggle.
kaggle-live-files page_size="200":
    @page_size="$1"; {{ kaggle }} datasets files wyattowalsh/openoppsdb --page-size "${page_size#page_size=}"

# Verify live OpenOppsDB readback through KaggleHub adapters.
kagglehub-live-readback dataset="wyattowalsh/openoppsdb" version="":
    #!/usr/bin/env bash
    set -euo pipefail
    dataset="$1"
    version="$2"
    if [[ "$dataset" == dataset=* ]]; then dataset="${dataset#dataset=}"; fi
    if [[ "$dataset" == version=* ]]; then version="${dataset#version=}"; dataset="wyattowalsh/openoppsdb"; fi
    if [[ "$version" == version=* ]]; then version="${version#version=}"; fi
    args=(verify-readback --dataset "$dataset")
    if [[ -n "$version" ]]; then args+=(--version "$version"); fi
    {{ kaggle-ops-gen }} "${args[@]}"

# Download live OpenOppsDB dataset metadata from Kaggle.
kaggle-live-metadata output="/tmp/openoppsdb-kaggle-metadata":
    @output="$1"; output="${output#output=}"; mkdir -p "$output"; {{ kaggle }} datasets metadata wyattowalsh/openoppsdb -p "$output"

# Show live OpenOppsDB manager notebook availability from Kaggle.
kaggle-notebook-status:
    @status="$({{ kaggle }} kernels status wyattowalsh/openoppsdb-manager)"; echo "$status"; echo "$status" | grep -q 'KernelWorkerStatus.COMPLETE'

# List live OpenOppsDB manager notebook files from Kaggle.
kaggle-notebook-files page_size="200":
    @page_size="$1"; {{ kaggle }} kernels files wyattowalsh/openoppsdb-manager --page-size "${page_size#page_size=}"

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
    @page_size="$1"; page_size="${page_size#page_size=}"; for kernel in wyattowalsh/openoppsdb-starter-notebook wyattowalsh/openoppsdb-advanced-usage wyattowalsh/openoppsdb-hiring-market-map wyattowalsh/openoppsdb-skills-radar; do echo "== $kernel =="; {{ kaggle }} kernels files "$kernel" --page-size "$page_size"; done

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
    change="$1"; change="${change#change=}"
    if [[ -z "$change" ]]; then
      {{ openspec }} list --json
    else
      {{ openspec }} status --change "$change" --json
    fi

# Show OpenSpec task instructions for one change as agent-readable JSON.
openspec-tasks change="":
    #!/usr/bin/env bash
    set -euo pipefail
    change="$1"; change="${change#change=}"
    if [[ -z "$change" ]]; then
      echo "usage: just openspec-tasks change=<active-change-name>" >&2
      exit 2
    fi
    {{ openspec }} instructions --change "$change" tasks --json

# Validate one OpenSpec change strictly.
openspec-validate change="":
    #!/usr/bin/env bash
    set -euo pipefail
    change="$1"; change="${change#change=}"
    if [[ -z "$change" ]]; then
      {{ openspec }} validate --all --strict
    else
      {{ openspec }} validate "$change" --strict
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
