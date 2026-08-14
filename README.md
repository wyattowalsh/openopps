<p align="center">
  <img src="web/public/brand/openopps-logo.png" alt="OpenOpps logo" width="128" height="128">
</p>

# OpenOpps

OpenOpps is a v0.1 Python CLI for discovering firm hiring boards from aggregate sources, resolving public provider routes, syncing normalized public jobs, and exporting an auditable local opportunity ledger. Public ingestion is CLI-driven; the Fumadocs site under `web/` ships static Jobs (`/`) and Explorer (`/explorer`) workbenches, not a live sync backend. The checked-in version 6 snapshot remains the transition fallback; version 7 adds release-pinned, content-addressed public data without implying that a live cutover has occurred.

The public domain nouns are:

- `sources`: aggregate catalogs such as `a16z`, `accel`, `lsvp`, `sequoia`, `bvp`, `greylock`, `kleinerperkins`, `southparkcommons`, `signalfire`, `yc` (preferred startup-board source), public-company indexes, and ecosystem landscapes. WorkAtAStartup and Wellfound/Angel discovery are out of scope for v0.1.
- `boards`: firm/company hiring boards discovered from sources.
- `jobs`: normalized public postings fetched from boards.
- `providers`: adapters that detect or fetch provider-specific boards, such as Ashby, Greenhouse, Lever, Workday, Workable, Teamtailor, BambooHR, Rippling, and WP Job Manager.
- `cache`, `plugins`, and `examples`: operational surfaces for request cache inspection, Python plugin discovery, and deterministic demo data.

## Install and Run

```bash
uv sync
just --list
uv run openopps admin db init
uv run openopps status
uv run openopps --help
```

Initialize the SQLite schema once per `OPENOPPS_DB_URL` before live syncs. For an isolated database, set `OPENOPPS_DB_URL=sqlite:///./path/to/openopps.sqlite` (or copy `.env.example` to `.env`) before `admin db init`.

`just` is the contributor command index. It mirrors CI while keeping the raw `uv`, `pnpm`, and OpenSpec commands visible in this README and the docs site.

## CLI

```bash
uv run openopps sources list
uv run openopps examples seed --json
uv run openopps status --json
uv run openopps admin sources test a16z
uv run openopps sync a16z --metrics-json --refresh-cache
uv run openopps sources sync a16z --metrics-json --refresh-cache
uv run openopps sources sync yc --metrics-json
uv run openopps sources sync accel --metrics-json
uv run openopps sources sync sequoia --metrics-json
uv run openopps boards list --source a16z --limit 10
uv run openopps boards list --provider ashbyhq --market AI --has-jobs --json
uv run openopps boards sync --source a16z --provider any --limit 25 --metrics-json
uv run openopps admin boards enrich --source a16z --json
uv run openopps providers coverage --source a16z --provider any --json
uv run openopps providers audit --source a16z --json
uv run openopps providers health --source a16z --provider any --limit 25 --json
uv run openopps admin providers probe-routes --source a16z --provider any --limit 25 --json
uv run openopps admin providers registry --source a16z --passed-probe-only --json
uv run openopps jobs sync --provider ashbyhq --metrics-json --refresh-cache
uv run openopps jobs list --remote Full --skill Python --salary-min 150000 --json
uv run openopps jobs export --format parquet --output /tmp/openopps-jobs.parquet
uv run openopps cache status --json
uv run openopps plugins list --json
```

For first-run discovery, start with `uv run openopps --help` and `uv run openopps status`. The root help groups stable workflow commands separately from advanced admin diagnostics, and automation-oriented commands use `--json` or `--metrics-json` for parseable stdout.

Unscoped commands use superset behavior. For example, `jobs sync` targets every known board with a job-capable provider unless narrowed with `--source`, `--board`, or `--provider`. Provider filters accept `any` and `all` as aliases for removing the provider filter, which is useful in scripts that always pass a provider argument.

When multiple sources discover the same company board, OpenOpps keeps the persisted board key visible through `boards list` and dedupes provider requests before syncing jobs or probing routes. Upstream slugs remain available as `remote_slug`. Metrics report `duplicateRoutesSkipped` so overlapping source coverage does not create duplicate Ashby, Greenhouse, Lever, or Workday requests.

The stable `openopps sync` workflow runs source discovery, board enrichment and route probing, then job sync in order. You can still run each stage independently with `sources sync`, `boards sync`, and `jobs sync` when you want to inspect or rerun one layer. Job sync uses the persisted board-route registry as the intermediate layer between board collection and job execution. Raw source syncs can discover provider hints, board sync can upgrade those hints into executable routes, and `jobs sync` only executes routes that have enough provider-specific route metadata to fetch jobs.

Repeated source refreshes preserve existing executable route metadata when an aggregate source repeats only a provider hint. Already-ready routes, duplicate routes, and unresolved hint-only routes are filtered out of sync targets without inflating the warning `skipped` count. When a persisted provider route returns a terminal unavailable status, OpenOpps removes it from future job-sync targets instead of retrying the same broken route every scheduled run.

Synced jobs include deterministic enrichment fields derived from provider payloads only. OpenOpps normalizes company, employment type, plain-text and HTML descriptions, remote level (`Full`, `Hybrid`, or `None` when knowable), compensation and salary range fields, experience, structured responsibilities, qualifications, skills, and a `job_description` object compatible with JSON Resume's Job Description Schema. Raw provider listing and detail payloads remain preserved as `raw_listing` and `raw_detail` for auditability and future reprocessing.

Board lists and exports can be narrowed by source, detected provider route, market, location, domain, job availability, staff-count range, and limit. Job lists and exports share the same filter path and can be narrowed by source, board, provider, normalized location, department, team, workplace type, remote level, employment type, salary range overlap, skill, simple title/company/description query, posted date range, and limit. Job filters use normalized enriched fields rather than provider-specific raw payloads; `--provider any` and `--provider all` remain aliases for no provider filter.

## Provider Coverage

Provider coverage is an offline report over persisted SQLite data. It does not fetch sources, probe routes, or sample live jobs, so percentages must come from representative persisted source snapshots rather than estimates:

```bash
uv run openopps providers coverage
uv run openopps providers coverage --json
uv run openopps providers coverage --source a16z --provider any --json
uv run openopps providers coverage --source a16z --provider greenhouse
uv run openopps providers audit --source a16z --json
```

The JSON output includes filtered source, board, route, and job counts; route counts by provider, support level, and last status; executable and missing route metadata counts from the durable route registry; non-supported provider coverage; detect-only provider examples; boards with job-capable hints but no executable route; boards with executable routes but zero persisted jobs; and job enrichment completeness for posting URLs, apply URLs, locations, departments, descriptions, normalized compensation/salary, remote level, and employment type.

`providers audit` uses the same persisted-board evidence model to report candidate-provider coverage for SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, Rippling, WP Job Manager, iCIMS, Jobvite, and JazzHR, including examples, adopted-route rationales, and do-not-adopt rationales where generic public fetching is not reliable enough for v0.1.

## Cache

OpenOpps stores shared JSON request cache records in the configured SQLite application database. Cache schema version 2 persists a SHA-256 request identity plus a redacted canonical location; it does not persist raw request bodies, URL user information, or credential-bearing query values. Successful responses store payload hashes, an allowlist of response headers, freshness timestamps, ETag/Last-Modified validators, and stale-on-error eligibility. Legacy cache rows are invalidated rather than migrated.

```bash
uv run openopps cache status
uv run openopps admin cache purge --namespace http-json --json
uv run openopps sources sync a16z --refresh-cache --metrics-json
uv run openopps jobs sync --provider any --refresh-cache --metrics-json
```

`--refresh-cache` bypasses cache reads while allowing successful fresh responses to update cache state. Conditional requests reuse stored ETag and Last-Modified values when an expired cached record has validators. Cache status reports total, fresh, expired, and stale-on-error-eligible records so stale behavior remains visible.

## Plugins

OpenOpps discovers Python plugins through the `openopps.plugins` entry point group. Plugins can contribute validated source adapters, job providers, route detectors, metadata enrichers, cache policies, export contributors, and CLI command metadata. Source adapters and job providers are runtime-wired in v0.1; the other contribution types are validated and reported so future releases can wire them without changing the entry-point shape. A job provider implements the public `BoardJobProvider` contract and returns `openopps.providers.JobFetchResult` from `fetch_jobs`. Set `authoritative=True` only after a complete, verified traversal because an authoritative result may close jobs missing from that snapshot; partial and plain-list results fail closed. Load failures are isolated and visible through `plugins list` instead of crashing the CLI.

```bash
uv run openopps plugins list
uv run openopps plugins list --json
```

Installed plugins are discovered but not executed by default. Use `OPENOPPS_PLUGIN_ALLOWED` as a comma-separated entry-point name list to allow trusted plugins, `OPENOPPS_PLUGIN_DISABLED` to skip specific entries, or `OPENOPPS_PLUGIN_AUTOLOAD=true` only in controlled environments where every installed plugin is trusted.

See `examples/plugins/minimal-openopps-plugin/` for a minimal `pyproject.toml` entry-point package and no-op source/provider/route/metadata/cache/CLI contribution template.

Installed Python plugins are not sandboxed. Only install plugins from sources you trust because plugin code runs in the same Python process as OpenOpps.

## Examples

Use deterministic synthetic data for docs, demos, and smoke tests without hitting upstream services:

```bash
uv run openopps examples seed --seed 42 --boards 4 --jobs-per-board 2 --json
uv run openopps status
```

## Provider Support

Provider definitions have a kind and a support level. Board source adapters discover firm/company boards from aggregate catalogs. Board providers detect or fetch jobs from a specific company board route.

| Board source adapter | Support  | Notes                                                  |
| -------------------- | -------- | ------------------------------------------------------ |
| `consider_a16z`      | `detect` | Source adapter for the a16z companies board.           |
| `consider`           | `detect` | Source adapter for Consider-backed investor boards.    |
| `getro`              | `detect` | Source adapter for Getro-backed investor boards.       |
| `southparkcommons`   | `detect` | Source adapter for South Park Commons jobs data.       |
| `ycombinator`        | `detect` | Source adapter for YC companies via its Algolia index. |

| Board provider   | Support  | Notes                                                                            |
| ---------------- | -------- | -------------------------------------------------------------------------------- |
| `greenhouse`     | `jobs`   | Uses the public Greenhouse job board API.                                        |
| `lever`          | `jobs`   | Uses the public Lever postings JSON API.                                         |
| `ashbyhq`        | `jobs`   | Uses the public Ashby job posting API.                                           |
| `workday`        | `jobs`   | Uses public Workday CXS careers-site endpoints.                                  |
| `workable`       | `jobs`   | Uses Workable's public hosted-board account jobs endpoint.                       |
| `teamtailor`     | `jobs`   | Uses Teamtailor's public jobs RSS feed.                                          |
| `bamboohr`       | `jobs`   | Uses BambooHR's public careers board JSON endpoints, not authenticated ATS APIs. |
| `rippling`       | `jobs`   | Uses Rippling's public ATS board JSON endpoints.                                 |
| `wpjobmanager`   | `jobs`   | Uses explicit WP Job Manager REST or AJAX endpoints only.                        |
| `manatal`, `gem` | `detect` | Preserved as board metadata until reliable public fetching is added.             |

Workday support is limited to public postings visible on careers sites. It parses host, tenant, and site from public board URLs, then uses the public CXS listing and detail endpoints with conservative concurrency.

Ashby support is limited to public postings exposed by `https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}`. Job sync accepts route metadata from either `https://jobs.ashbyhq.com/{JOB_BOARD_NAME}` or the posting API URL; route probing tests candidate board tokens and reports matched hosted board URLs. Postings marked `isListed: false` are treated as direct-link-only and excluded from normal sync output.

BambooHR support is limited to no-auth public careers board JSON endpoints such as `https://{tenant}.bamboohr.com/careers/list` and detail URLs under `/careers/{job_id}/detail`. WP Job Manager support requires an explicit `/wp-json/wp/v2/job-listings` or `/jm-ajax/get_listings/` endpoint; OpenOpps does not treat every WordPress site as a job-capable board.

## Provider Health

Provider health samples aggregate source adapters and job-capable board routes, then reports active, empty, error, missing-route, and not-covered status counts:

```bash
uv run openopps providers health --source a16z --provider any --limit 25 --json
```

Health checks are dry runs by default and use lightweight count/sample requests for job routes instead of full job-detail syncs. Add `--apply` to persist source health under `raw_metadata.health` and board-provider route health under `last_status`. The `notCovered` output groups discovered detect-only providers, such as Manatal or Gem, that are preserved as metadata but do not yet have reliable job fetching.

Use `providers coverage` when you want persisted-data coverage and enrichment quality. Use `providers audit` when you want candidate-provider adoption evidence. Use `providers health` when you want live sampled HTTP health.

## Route Probing

Some aggregate sources expose provider hints, such as `greenhouse` plus a count, without the board token or public careers URL needed to fetch jobs. Route probing tries candidate tokens derived from upstream slugs, remote ids, names, domains, and websites, then reports what matched and what is still unknown:

```bash
uv run openopps admin providers probe-routes --source a16z --provider any --limit 25 --json
```

Probing is a dry run by default. Add `--apply` to persist matched route metadata. Unknown rows include the attempted candidates so the missing board token or Workday careers URL can be filled manually with `admin boards add-provider`. Probe summaries include `duplicateRoutesSkipped` when overlapping source boards collapse to one provider request.

## Board Route Registry

`board_providers` is the durable intermediate registry between discovered boards and job execution. Use it to inspect executable routes before running job sync:

```bash
uv run openopps admin providers registry --provider any
uv run openopps admin providers registry --passed-probe-only --json
```

Without `--include-missing`, the registry shows job-capable routes that already have executable provider metadata, such as an Ashby/Greenhouse/Lever token or a complete Workday CXS route. Add `--passed-probe-only` to require `admin providers probe-routes --apply` to have verified and persisted the route with `last_status="route_ready"`. Add `--include-missing` to include raw job-capable hints that still need probe or manual route metadata.

## Database Initialization

OpenOpps uses an Alembic migration chain for the v0.1 durable app SQLite database. `uv run openopps admin db init` creates or upgrades the configured `OPENOPPS_DB_URL` file-backed SQLite database to the current schema head, including durable job-sync run lifecycle fields. HTTP response cache rows live in the same SQLite database and are managed by `cache.py`, not by Alembic. If a pre-release local database has an unsupported or partial schema, OpenOpps fails fast instead of silently repairing it; reset that local SQLite file or point `OPENOPPS_DB_URL` at a new SQLite file.

```bash
OPENOPPS_DB_URL=sqlite:///openoppsdb.sqlite uv run alembic upgrade head
```

## Storage Modes

SQLite is the default DB-backed mode:

```bash
uv run openopps admin db init
uv run openopps admin db status
```

No-DB source sync is available with explicit JSONL output:

```bash
uv run openopps sources sync a16z --no-db --output /tmp/a16z-boards.jsonl
```

Human sync runs show a brief dynamic progress display by default, including per-stage percentages for source, board, and job stages when totals are known. Add `--verbose` to `sync`, `sources sync`, `boards sync`, or `jobs sync` when you need detailed provider warnings on stderr; JSON modes such as `--metrics-json` remain clean for automation. In metrics, `jobSyncAttempts` counts durable route attempts and `jobSyncRuns` counts only authoritative successes, so failures and partial snapshots cannot satisfy release-quality evidence.

List and export filters push scalar source, board, provider, salary, and text filters into SQLite before materializing normalized records. JSONL exports stream records as they are encoded; empty JSONL and CSV exports produce empty files, and empty Parquet exports produce a readable empty Parquet table.

CSV exports neutralize spreadsheet formula-leading strings by prefixing a single quote. JSONL and Parquet exports preserve normalized values as-is for machine processing.

## Configuration

Configuration uses `OPENOPPS_` environment variables:

- `OPENOPPS_DB_URL` defaults to `sqlite:///openoppsdb.sqlite`.
- `OPENOPPS_MAX_CONNECTIONS` bounds HTTP connection pooling.
- `OPENOPPS_SOURCE_CONCURRENCY` bounds source adapter work.
- `OPENOPPS_SOURCE_TIMEOUT_SECONDS` bounds one source adapter run before recording a classified timeout.
- `OPENOPPS_SOURCE_FRESHNESS_SECONDS` skips recently synced sources during unscoped full-sync retries when set above `0`.
- `OPENOPPS_BOARD_CONCURRENCY` bounds concurrent ready board routes and board-scoped job listing/detail work during job sync and related checks.
- `OPENOPPS_JOB_ROUTE_TIMEOUT_SECONDS` bounds how long one provider route may run during job sync before a classified timeout.
- `OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS` skips recently synced routes during job sync when set above `0`.
- `OPENOPPS_JOB_ROUTE_LIMIT` optionally caps how many stale routes one job sync processes; unset means no cap.
- `OPENOPPS_PROVIDER_CONCURRENCY` bounds concurrent provider route probes during detection and probing, not job-fetch parallelism.
- `OPENOPPS_WORKDAY_CONCURRENCY` keeps Workday CXS requests conservative.
- `OPENOPPS_DB_BATCH_SIZE` controls batched SQLite writes.
- `OPENOPPS_HTTP_TIMEOUT` controls HTTP request timeouts.
- `OPENOPPS_RETRY_ATTEMPTS` controls retry attempts for retriable requests.
- `OPENOPPS_USER_AGENT` customizes the HTTP user agent.
- `OPENOPPS_CACHE_ENABLED` enables or disables shared JSON request caching in the configured SQLite database.
- `OPENOPPS_CACHE_TTL_SECONDS` controls default cache freshness.
- `OPENOPPS_CACHE_REFRESH` bypasses cache reads for cacheable request paths.
- `OPENOPPS_CACHE_STALE_ON_ERROR` allows eligible stale cache records on retryable failures.

Values can also be loaded from a local `.env` file. Copy `.env.example` to
`.env` for local overrides; `.env` is ignored so machine-specific settings stay
out of commits.

## Repository Layout

| Path                              | Purpose                                                                    |
| --------------------------------- | -------------------------------------------------------------------------- |
| `src/openopps/`                   | Python package and `openopps` Typer CLI entry point.                       |
| `src/openopps/providers/sources/` | Firm aggregator board source adapters.                                     |
| `src/openopps/providers/boards/`  | Board provider adapters that fetch jobs from discovered board routes.      |
| `src/openopps/cache.py`           | HTTP JSON cache table management.                                          |
| `src/openopps/plugins.py`         | Entry-point plugin contracts, validation, and load isolation.              |
| `examples/examples.py`            | Deterministic synthetic dataset builder for examples and smoke tests.      |
| `src/openopps/route_registry.py`  | Programmatic selector for executable and probe-verified board routes.      |
| `tests/`                          | Pytest suites split by `unit`, `integration`, and `smoke` scopes.          |
| `scripts/`                        | Helper scripts, including deterministic web data, release/delivery, and Kaggle bundle generation. |
| `kaggle/`                         | Generated Kaggle dataset metadata, data dictionary, and snapshot notebook. |
| `web/`                            | Next.js/Fumadocs web app (docs + jobs workbench).                           |
| `deployment/openopps-data/`       | Assets-only staging/production configs and the public-data delivery runbook. |
| `openspec/`                       | OpenSpec specs and change tracking.                                        |

## Docs Site

```bash
cd web
pnpm install
pnpm data:generate
pnpm dev
pnpm types:check
pnpm build
pnpm lint
pnpm test
```

Documentation content lives in `web/content/docs/`; Fumadocs navigation is curated by `web/content/docs/meta.json`.
The docs IA is organized as `/docs`, `/docs/cli`, `/docs/configuration`, `/docs/data-model`, `/docs/providers`, `/docs/operations`, `/docs/public-data-releases`, and `/docs/contributing`; the jobs workbench lives at `/`, and the data dashboard lives at `/explorer`.
LLM-readable exports are served at `/llms.txt` (compact index) and `/llms-full.txt` (full docs text) when the docs app is running or deployed.

## Public Data Releases

The legacy version 6 search tree remains committed at `web/public/data/openopps-search/` during a bounded transition. Version 7 is additive and uses immutable `releases/<sha256>/` trees plus a schema-version-2 `channels/production.json` pointer. One `OpenOppsSnapshotClient` boundary resolves and pins the release used by search, details, metadata, and sitemaps; the browser search engine runs in a dedicated worker, and the stale server search endpoint fails closed instead of scanning the full corpus.

Generate and verify a v7 publication in an external or ignored root:

```bash
uv run python scripts/generate_docs_search_index.py \
  --data-db kaggle/openoppsdb.sqlite \
  --release-root /absolute/path/to/openopps-search-v7 \
  --channel production \
  --max-snapshot-age-hours 48
uv run python scripts/verify_docs_search_artifacts.py \
  --root /absolute/path/to/openopps-search-v7 \
  --channel production \
  --max-snapshot-age-hours 48
```

Publication is fail-closed on source rights and required attribution. `just source-policy-check` validates the canonical evidence, schema, and exact committed-v6 corpus identity; it is a structural CI gate, not permission to publish. `just source-policy-audit` is the release-eligibility gate. The current audit is deliberately red: 7 of 695 sources only mirror repository catalog declarations, 0 are independently verified, and 688 are blocked. Do not render a selector, generate or upload a production corpus, bootstrap a Worker, or publish while that audit exits 2. The generator applies the evidence as a deny-only overlay and hashes its module, evidence, schema, and corpus into the v7 release identity, so catalog or stored metadata cannot override a reviewed denial.

A degraded stale-snapshot reason can bypass only the 48-hour freshness limit; it cannot bypass rights, privacy, secret, integrity, provenance, or platform-budget gates. Static delivery retains exactly current and previous releases and provides local staging, verification, rollout-plan, exact-archive-SHA bundle, and identity-closed safe-restore tooling under `scripts/docs_search_delivery.py` and `deployment/openopps-data/`. If a target Worker is freshly proven absent, [`scripts/docs_search_bootstrap.py`](scripts/docs_search_bootstrap.py) and the [bootstrap runbook](deployment/openopps-data/BOOTSTRAP.md) provide the sole dry-run-first initial-deploy exception; they do not prove a live bootstrap.

The browser includes an explicit, default-off offline-search installer for v7. It quota-checks, downloads, hashes, and pins only the bounded search/metadata projection for one immutable release; unit tests cover opt-out, quota, integrity, rollback, retirement, and ownership boundaries. That local implementation is not deployed-offline evidence. A real-release install, disconnect/readback journey, and the complete Chromium/Firefox/WebKit journey remain release gates.

See [Public Data Releases](https://openopps.dev/docs/public-data-releases) and [`deployment/openopps-data/README.md`](deployment/openopps-data/README.md) for schema, governance, staging, remote verification, rollback, archive, correction/takedown, retention, and v6 exit gates. The manual `public-data-archive.yml` workflow validates an operator-created one-asset draft, attests its embedded SPDX document, publishes it as a non-latest immutable release, and independently downloads, verifies, and restores it. Repository workflow presence is still preparation evidence: no live Workers rollout, immutable GitHub Release, or archive attestation exists until an authorized exact-SHA run succeeds and its identities are recorded.

## Contributor Workflow

Use `just` for local parity with GitHub Actions:

```bash
just quick
just ci
just lock-check
just openspec-validate-all
just docs-check
just docs-test
just cli-help
```

The underlying commands remain direct and scriptable:

```bash
uv run pytest
uv run pytest --cov=openopps --cov-report=term-missing
uv lock --check
rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict
cd web && pnpm types:check
cd web && pnpm build
cd web && pnpm test
cd web && pnpm exec playwright test --project=chromium
cd web && pnpm exec playwright test --project=mobile-chromium accessibility.spec.ts
just web-search-index-check
just --show public-data-archive-bundle
just --show public-data-archive-restore
just kaggle-meta
just kaggle-bundle-check kaggle/openoppsdb.sqlite
```

`just ci` composes `ci-python`, `ci-openspec`, `ci-web`, and `ci-artifacts`. Those lanes cover the Python release gate, strict OpenSpec validation, web type/build/unit/browser/accessibility/lint/search-artifact checks, Kaggle metadata/bundle smoke, and repository drift. Network-dependent Python and web audits are added by `just ci-full`; `just web-rtk-lint` is the explicit optional maintainer lint for `rtk` and is not part of the default CI recipe.
`just web-search-index-check` is the explicit maintainer parity gate for the committed v6 transition snapshot; it requires a local `kaggle/openoppsdb.sqlite`, regenerates `web/public/data/openopps-search/`, and fails on remaining snapshot drift.

GitHub Actions also runs supported Python 3.12/3.13/3.14 and lowest-direct dependency lanes. Its non-pull-request supply-chain job builds and attests the Python wheel SBOM; the uploaded workflow artifact has 30-day retention. Public-data archive publication is intentionally separate and manual, requires immutable releases plus a pre-created exact draft, and uses isolated least-privilege attest, publish, and readback jobs.

Renovate is configured in `renovate.json` for Python `pyproject.toml`/`uv.lock` and web `package.json`/`pnpm-lock.yaml` maintenance. Review dependency PRs with the same `just ci` path used for local release validation.

Public workflow, CLI, docs-generation, CI, or validation behavior changes must update OpenSpec, README/docs, nested `AGENTS.md`, CI, and `Justfile` in the same logical change. Use OpenSpec JSON/status commands for agent-readable state:

```bash
rtk npx -y @fission-ai/openspec@1.6.0 list --json
rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict
```

## Validation

```bash
uv run pytest
uv run pytest --cov=openopps --cov-report=term-missing
uv lock --check
PYTHONPATH=scripts uv run python -m openopps_kaggle
PYTHONPATH=scripts uv run python -m openopps_kaggle --data-db kaggle/openoppsdb.sqlite
cd web && pnpm types:check
cd web && pnpm build
cd web && pnpm lint
cd web && pnpm test
just docs-rtk-lint
rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict
```

## Kaggle Bundle

The generated Kaggle bundle lives in `kaggle/`. It contains dataset metadata (`dataset-metadata.json`, `dataset-cover-image.png`), the connected manager notebook (`kernel-metadata.json`, `openoppsdb-manager.ipynb`), public example notebooks under `kaggle/starter/` and `kaggle/examples/`, and generated SQLite/CSV/Parquet data artifacts when a full snapshot is bundled. `dataset-metadata.json` is the Kaggle UI source of truth for cover image, public file descriptions, and field-level descriptors for every CSV and Parquet export. `openoppsdb.sqlite` remains directly readable and carries `openopps_tables`/`openopps_columns` metadata for SQLite clients; if Kaggle does not expose nested SQLite table previews for a fresh upload, use the mirrored CSV/Parquet exports for Kaggle-rendered table previews and field metadata. The live dataset recipes stage a temporary upload directory containing only Kaggle dataset control files plus `openoppsdb.sqlite`, `exports/csv/*.csv`, and `exports/parquet/*.parquet`; notebooks, manager-run evidence files, and runtime generator files are private or separate Kaggle kernel inputs and are pruned before public dataset publishing.

```bash
# Prefer a clean-schema operational DB (never a legacy root DB with sources.enabled).
OPENOPPS_DB_URL="sqlite:///$PWD/.tmp/openoppsdb-operational.sqlite" uv run openopps admin db init
# Local full workflow for a maintainer ledger; the *manager notebook* uses bounded:
#   openopps jobs sync --metrics-json --freshness-seconds 86400 --limit 120
OPENOPPS_DB_URL="sqlite:///$PWD/.tmp/openoppsdb-operational.sqlite" uv run openopps jobs sync --metrics-json --freshness-seconds 86400 --limit 120
PYTHONPATH=scripts uv run python -m openopps_kaggle --data-db .tmp/openoppsdb-operational.sqlite
just kaggle-bundle-check kaggle/openoppsdb.sqlite
# Dry-run is the default. Replace 42/7 with the exact live versions that would
# become rollback targets; inspect the generated ledgers before any write.
just kaggle-dataset-version message="OpenOppsDB daily snapshot" db=.tmp/openoppsdb-operational.sqlite expected_current_version=42
just kaggle-runtime-generator-version message="OpenOppsDB manager runtime generator" expected_current_version=7
just kaggle-notebook-push
just kaggle-example-notebooks-push
# A reviewed live write is always explicit.
just kaggle-dataset-version message="OpenOppsDB daily snapshot" db=.tmp/openoppsdb-operational.sqlite expected_current_version=42 execute=1
just kaggle-runtime-generator-version message="OpenOppsDB manager runtime generator" expected_current_version=7 execute=1
just kaggle-notebook-push execute=1
just kaggle-example-notebooks-push execute=1
just kaggle-example-notebooks-status
just kaggle-example-notebooks-pull-check
just kaggle-live-verify
```

Public example notebooks are generated from `PYTHONPATH=scripts uv run python -m openopps_kaggle` as repo-owned Kaggle kernel bundles: `wyattowalsh/openoppsdb-starter-notebook`, `wyattowalsh/openoppsdb-advanced-usage`, `wyattowalsh/openoppsdb-hiring-market-map`, and `wyattowalsh/openoppsdb-skills-radar`. They are read-only, internet-disabled, credential-free, and attached only to `wyattowalsh/openoppsdb`. Use `just kaggle-example-notebooks-pull-check` to pull and verify the live source bundles after pushing; `just kaggle-example-notebooks-files page_size=200` lists output files emitted by those notebook runs.

Kaggle notebook schedules are configured in Kaggle after pushing `wyattowalsh/openoppsdb-manager`; use one daily cron cadence such as `0 6 * * *` and keep internet enabled so the notebook can install and run the OpenOpps CLI. The notebook is connected to `wyattowalsh/openoppsdb` for public snapshot input and `wyattowalsh/openoppsdb-manager-runtime` for the private `openopps_kaggle` runtime package, copies the newest `/kaggle/input/**/openoppsdb.sqlite` snapshot into `/kaggle/working/openoppsdb/openoppsdb.sqlite`, restores projected large columns from prior Parquet exports when needed, rehydrates the plain public SQLite snapshot into a fresh operational Alembic schema, and then runs `openopps sync --metrics-json` (packaged catalog sources, boards, and jobs) under a 6000s budget so a full public snapshot can land even when the prior version is the synthetic example seed. It writes private `sync_metrics.json`, `status.json`, and `coverage.json` evidence, then delegates derived-table backfill, metadata generation, public SQLite metadata tables, CSV/Parquet exports, private `snapshot-quality.json`, evidence pruning, exact public staging, version publication, and immutable-version readback to the verified runtime package.

The manager has no mutable package default. Set `OPENOPPS_PACKAGE_SPEC` to `git+https://github.com/wyattowalsh/openopps.git@<exact-40-or-64-character-commit-sha>` as a Kaggle notebook secret or environment variable (or let `just kaggle-notebook-push execute=1` bake the current `HEAD` SHA into a temporary push copy); branches, tags, ranges, and unpinned packages are rejected. The generated notebook also pins the canonical runtime-package digest through `OPENOPPS_RUNTIME_PACKAGE_SHA256` (currently `aa5d65eb4ad54f1b1300678998951d74502101b693fdc2e89ac4b3f5bfb7fa33`), which must match the private manager-runtime dataset's `runtime-manifest.json`. Refresh that dataset and regenerate the manager notebook together whenever the runtime package changes. Scheduled rehydrate accepts a pre-`0004` public `job_sync_runs` table by inserting the lifecycle columns from `synced_at` / `success` / `error`. The snapshot quality gate does not hard-block empty derived skill tables when every `job_versions.skills` value is null or `[]`. The manager seeds bounded Kaggle runtime defaults for source freshness, job-route freshness, route limits, concurrency, connection limits, timeouts, and retries; set the corresponding `OPENOPPS_` variables in the notebook environment to override those defaults.

Live file/column metadata repair is deliberately separate from dataset publication and immutable-version readback. Run `just kaggle-live-file-metadata` only afterward from a browser-authenticated maintainer environment when the Kaggle DataBundle checklist or column-description score needs authoritative repair; record that result independently from the publication ledger.

The manager must have Kaggle API credentials available inside the scheduled Kaggle notebook environment before it starts. Configure `KAGGLE_USERNAME` and `KAGGLE_KEY`, or `KAGGLE_API_TOKEN`, as Kaggle notebook secrets/environment variables; otherwise the manager fails fast before running the expensive sync.

All Kaggle create, version, and kernel-push recipes are dry-run by default. A version write requires both `expected_current_version=<n>` and `execute=1`; the preflight must observe that exact version before upload, and the ledger retains it as the rollback target. For the first public or private runtime upload, prepare with `kaggle-dataset-create` or `kaggle-runtime-generator-create`, then add `execute=1 allow_no_rollback=1` only after confirming that the missing rollback target is intentional:

```bash
just kaggle-dataset-create db=.tmp/openoppsdb-operational.sqlite
just kaggle-dataset-create db=.tmp/openoppsdb-operational.sqlite execute=1 allow_no_rollback=1
just kaggle-runtime-generator-create
just kaggle-runtime-generator-create execute=1 allow_no_rollback=1
```

Create/version recipes rebuild from `db=` before staging so a stale `kaggle/` tree cannot silently ship; `allow_stale=1` remains a loud maintenance override. The live write path requires Kaggle CLI credentials, is intentionally outside CI, and performs exact immutable-version readback after mutation. `just kaggle-bundle-smoke` is the non-secret clean-DB stage smoke used for local/CI confidence.

`just kaggle-notebook-push` defaults to a two-hour Kaggle kernel timeout (sync plus publication readback can exceed one hour) and only renders a plan unless `execute=1` is supplied. `just kaggle-example-notebooks-push` still defaults to one hour. Override `timeout` only for an intentional longer maintenance run.

Docs/web search index regeneration uses `kaggle/openoppsdb.sqlite` as the maintainer input (`just web-search-index` / `just web-search-index-check`). CI validates **committed** search artifacts only (`just web-search-artifacts-check`) and never regenerates from local SQLite. Always feed a clean public snapshot—not a legacy root ledger with `sources.enabled`.

## Secret Hygiene

Keep local credentials out of the repository. `.env`, `.env.*`, `.envrc`, Kaggle `kaggle.json`, local registry credentials such as `.npmrc` and `.pypirc`, `.netrc`, key bundles, and token or credential JSON files are ignored by default. `.env.example` stays tracked as the non-secret template.

Do not print credentials in logs or docs. Live Kaggle publishing remains a maintainer-only local action; CI and Renovate validation paths do not require Kaggle secrets.
