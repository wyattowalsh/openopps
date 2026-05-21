<p align="center">
  <img src="docs/public/brand/openopps-logo.png" alt="OpenOpps logo" width="128" height="128">
</p>

# OpenOpps

OpenOpps is a CLI-only v0.1 for discovering firm hiring boards from aggregate sources, resolving public provider routes, syncing normalized public jobs, and exporting an auditable local opportunity ledger.

The public domain nouns are:

- `sources`: aggregate catalogs such as `a16z`, `accel`, `generalcatalyst`, `lsvp`, `sequoia`, `bvp`, `greylock`, `kleinerperkins`, and `yc`.
- `boards`: firm/company hiring boards discovered from sources.
- `jobs`: normalized public postings fetched from boards.
- `providers`: adapters that detect or fetch provider-specific boards, such as Ashby, Greenhouse, Lever, and Workday.
- `cache`, `plugins`, and `examples`: operational surfaces for request cache inspection, Python plugin discovery, and deterministic demo data.

## Install and Run

```bash
uv sync
uv run openopps status
uv run openopps --help
```

## CLI

```bash
uv run openopps sources list
uv run openopps examples seed --json
uv run openopps status --json
uv run openopps admin sources test a16z
uv run openopps sources sync a16z --metrics-json --refresh-cache
uv run openopps sources sync yc --metrics-json
uv run openopps sources sync accel --metrics-json
uv run openopps sources sync sequoia --metrics-json
uv run openopps boards list --source a16z --limit 10
uv run openopps boards list --provider ashbyhq --market AI --has-jobs --json
uv run openopps boards enrich --source a16z --json
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

Commands default to superset behavior. For example, `jobs sync` targets every known board with a job-capable provider unless narrowed with `--source`, `--board`, or `--provider`. Provider filters accept `any` and `all` as aliases for the full supported provider set.

When multiple sources discover the same company board, OpenOpps keeps separate source-scoped board records and dedupes provider requests before syncing jobs or probing routes. Generated source board keys are durable source-scoped identifiers such as `a16z:acme`; upstream slugs remain available as `remote_slug`. Metrics report `duplicateRoutesSkipped` so overlapping source coverage does not create duplicate Ashby, Greenhouse, Lever, or Workday requests.

Job sync uses the persisted board-route registry as the intermediate layer between board collection and job execution. Raw source syncs can discover provider hints, route probing can upgrade those hints into executable routes, and `jobs sync` only executes routes that have enough provider-specific route metadata to fetch jobs.

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

`providers audit` uses the same persisted-board evidence model to report candidate-provider coverage for SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, iCIMS, Jobvite, and JazzHR, including examples and do-not-adopt rationales where generic public fetching is not reliable enough for v0.1.

## Cache

OpenOpps uses a SQLite-backed request cache for shared JSON request paths used by source adapters and job providers. The cache key includes method, normalized URL/query, selected request headers, JSON body, namespace, and optional provider identity. Successful responses store payload hashes, selected response headers, freshness timestamps, ETag/Last-Modified validators, and stale-on-error eligibility.

```bash
uv run openopps cache status
uv run openopps admin cache purge --namespace http-json --json
uv run openopps sources sync a16z --refresh-cache --metrics-json
uv run openopps jobs sync --provider any --refresh-cache --metrics-json
```

`--refresh-cache` bypasses cache reads while allowing successful fresh responses to update cache state. Conditional requests reuse stored ETag and Last-Modified values when an expired cached record has validators.

## Plugins

OpenOpps discovers Python plugins through the `openopps.plugins` entry point group. Plugins can contribute source adapters, job providers, route detectors, metadata enrichers, cache policies, export contributors, and CLI commands. Load failures are isolated and visible through `plugins list` instead of crashing the CLI.

```bash
uv run openopps plugins list
uv run openopps plugins list --json
```

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
| `ycombinator`        | `detect` | Source adapter for YC companies via its Algolia index. |

| Board provider                 | Support  | Notes                                                                |
| ------------------------------ | -------- | -------------------------------------------------------------------- |
| `greenhouse`                   | `jobs`   | Uses the public Greenhouse job board API.                            |
| `lever`                        | `jobs`   | Uses the public Lever postings JSON API.                             |
| `ashbyhq`                      | `jobs`   | Uses the public Ashby job posting API.                               |
| `workday`                      | `jobs`   | Uses public Workday CXS careers-site endpoints.                      |
| `teamtailor`, `manatal`, `gem` | `detect` | Preserved as board metadata until reliable public fetching is added. |

Workday support is limited to public postings visible on careers sites. It parses host, tenant, and site from public board URLs, then uses the public CXS listing and detail endpoints with conservative concurrency.

Ashby support is limited to public postings exposed by `https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}`. Job sync accepts route metadata from either `https://jobs.ashbyhq.com/{JOB_BOARD_NAME}` or the posting API URL; route probing tests candidate board tokens and reports matched hosted board URLs. Postings marked `isListed: false` are treated as direct-link-only and excluded from normal sync output.

## Provider Health

Provider health samples aggregate source adapters and job-capable board routes, then reports active, empty, error, missing-route, and not-covered status counts:

```bash
uv run openopps providers health --source a16z --provider any --limit 25 --json
```

Health checks are dry runs by default and use lightweight count/sample requests for job routes instead of full job-detail syncs. Add `--apply` to persist source health under `raw_metadata.health` and board-provider route health under `last_status`. The `notCovered` output groups discovered detect-only providers, such as Teamtailor or Gem, that are preserved as metadata but do not yet have reliable job fetching.

Use `providers coverage` when you want persisted-data coverage and enrichment quality. Use `providers audit` when you want candidate-provider adoption evidence. Use `providers health` when you want live sampled HTTP health.

## Route Probing

Some aggregate sources expose provider hints, such as `greenhouse` plus a count, without the board token or public careers URL needed to fetch jobs. Route probing tries candidate tokens derived from upstream slugs, remote ids, names, domains, and websites, then reports what matched and what is still unknown:

```bash
uv run openopps admin providers probe-routes --source a16z --provider any --limit 25 --json
uv run python scripts/probe_provider_routes.py --source a16z --provider all --limit 25
```

Probing is a dry run by default. Add `--apply` to persist matched route metadata. Unknown rows include the attempted candidates so the missing board token or Workday careers URL can be filled manually with `admin boards add-provider`. Probe summaries include `duplicateRoutesSkipped` when overlapping source boards collapse to one provider request.

## Board Route Registry

`board_providers` is the durable intermediate registry between discovered boards and job execution. Use it to inspect executable routes before running job sync:

```bash
uv run openopps admin providers registry --provider any
uv run openopps admin providers registry --passed-probe-only --json
```

By default, the registry shows job-capable routes that already have executable provider metadata, such as an Ashby/Greenhouse/Lever token or a complete Workday CXS route. Add `--passed-probe-only` to require `admin providers probe-routes --apply` to have verified and persisted the route with `last_status="route_ready"`. Add `--include-missing` to include raw job-capable hints that still need probe or manual route metadata.

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

List and export filters push scalar source, board, provider, salary, and text filters into SQLite before materializing normalized records. JSONL exports stream records as they are encoded; empty JSONL and CSV exports produce empty files, and empty Parquet exports produce a readable empty Parquet table.

CSV exports neutralize spreadsheet formula-leading strings by prefixing a single quote. JSONL and Parquet exports preserve normalized values as-is for machine processing.

## Configuration

Configuration uses `OPENOPPS_` environment variables:

- `OPENOPPS_DB_URL` defaults to `sqlite:///openopps.db`.
- `OPENOPPS_MAX_CONNECTIONS` bounds HTTP connection pooling.
- `OPENOPPS_SOURCE_CONCURRENCY` bounds source adapter work.
- `OPENOPPS_BOARD_CONCURRENCY` bounds board-level processing.
- `OPENOPPS_PROVIDER_CONCURRENCY` bounds provider job fetching.
- `OPENOPPS_WORKDAY_CONCURRENCY` keeps Workday CXS requests conservative.
- `OPENOPPS_JOB_SYNC_SOURCES` optionally narrows unscoped `jobs sync` to a comma-separated source list; empty means all sources.
- `OPENOPPS_DB_BATCH_SIZE` controls batched SQLite writes.
- `OPENOPPS_HTTP_TIMEOUT` controls HTTP request timeouts.
- `OPENOPPS_RETRY_ATTEMPTS` controls retry attempts for retriable requests.
- `OPENOPPS_USER_AGENT` customizes the HTTP user agent.
- `OPENOPPS_CACHE_ENABLED` enables or disables shared JSON request caching.
- `OPENOPPS_CACHE_TTL_SECONDS` controls default cache freshness.
- `OPENOPPS_CACHE_REFRESH` bypasses cache reads for cacheable request paths.
- `OPENOPPS_CACHE_STALE_ON_ERROR` allows eligible stale cache records on retryable failures.

Values can also be loaded from a local `.env` file.

## Repository Layout

| Path                              | Purpose                                                                  |
| --------------------------------- | ------------------------------------------------------------------------ |
| `src/openopps/`                   | Python package and `openopps` Typer CLI entry point.                     |
| `src/openopps/providers/sources/` | Firm aggregator board source adapters.                                   |
| `src/openopps/providers/boards/`  | Board provider adapters that fetch jobs from discovered board routes.    |
| `src/openopps/cache.py`           | SQLite-backed HTTP JSON cache.                                           |
| `src/openopps/plugins.py`         | Entry-point plugin contracts, validation, and load isolation.            |
| `src/openopps/examples.py`        | Deterministic synthetic dataset builder for examples and smoke tests.    |
| `src/openopps/route_registry.py`  | Programmatic selector for executable and probe-verified board routes.    |
| `tests/`                          | Pytest coverage for CLI, providers, storage, exports, and sync behavior. |
| `scripts/`                        | Helper scripts, including provider route probing.                        |
| `docs/`                           | Next.js/Fumadocs developer docs site.                                    |
| `openspec/`                       | OpenSpec specs and change tracking.                                      |

## Docs Site

```bash
cd docs
pnpm install
pnpm dev
pnpm types:check
pnpm build
pnpm lint
```

Documentation content lives in `docs/content/docs/`; Fumadocs navigation is curated by `docs/content/docs/meta.json`.

## Validation

```bash
uv run pytest
cd docs && pnpm types:check
cd docs && pnpm build
rtk npx -y @fission-ai/openspec@latest validate "prepare-v0-1-release" --strict
```
