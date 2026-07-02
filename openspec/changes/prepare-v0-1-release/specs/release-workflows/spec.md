## ADDED Requirements

### Requirement: OpenOppsDB publishes daily full-snapshot artifacts

OpenOpps SHALL provide a generated Kaggle workflow for `wyattowalsh/openoppsdb` that publishes one daily full snapshot of active public job postings and preserves the prior SQLite ledger between scheduled runs.

#### Scenario: Scheduled manager notebook runs the default full workflow

- **WHEN** the connected `wyattowalsh/openoppsdb-manager` notebook runs on its daily Kaggle schedule
- **THEN** it installs OpenOpps from `git+https://github.com/wyattowalsh/openopps.git@main` unless an explicit controlled-test override is set
- **AND** it verifies the `openopps_kaggle` runtime package and `runtime-manifest.json` from the private `wyattowalsh/openoppsdb-manager-runtime` input before running the expensive sync
- **AND** it copies the newest prior `/kaggle/input/**/openoppsdb.sqlite` file into `/kaggle/working/openoppsdb/openoppsdb.sqlite` before syncing
- **AND** it may restore large columns from prior Parquet exports when upgrading legacy thin snapshots and rehydrates the public SQLite snapshot into a fresh operational Alembic schema when needed
- **AND** it initializes the database and runs bounded `openopps jobs sync --metrics-json --freshness-seconds --limit`
- **AND** it captures private `sync_metrics.json`, `status.json`, and `coverage.json` evidence
- **AND** it runs `python -m openopps_kaggle` to backfill derived skill helper tables, create the public bundle, write `snapshot-quality.json`, prune manager-run evidence, and stage a public upload directory
- **AND** it publishes only the staged `openoppsdb.sqlite` plus every SQLite table as CSV and Parquet exports as public dataset data files
- **AND** it runs `python -m openopps_kaggle` to attempt best-effort live Kaggle file metadata repair after publishing the new dataset version
- **AND** browser-authenticated local maintainer repair remains the authoritative path for Kaggle DataBundle checklist and column-description score repair when Kaggle notebook credentials cannot access internal metadata endpoints

#### Scenario: Published metadata describes the full bundle

- **WHEN** the Kaggle bundle is generated
- **THEN** transient HTTP cache tables are excluded from the published SQLite database
- **AND** normalized sources, boards, provider routes, jobs, versions, raw payload snapshots, sync runs, sync observations, `openopps_tables`, and `openopps_columns` remain in the published SQLite database
- **AND** `dataset-metadata.json` describes every published public data file and includes useful Kaggle resource and field descriptions for CSV and Parquet exports
- **AND** each CSV and Parquet resource schema lists all fields in file order with field names, human-readable labels, field descriptions, and supported Kaggle field types
- **AND** `openoppsdb.sqlite` includes `openopps_tables` and `openopps_columns` metadata tables matching the generated field metadata
- **AND** nested SQLite table metadata repair remains best-effort when Kaggle does not expose `sqliteInfo.tables`; CSV/Parquet exports remain the Kaggle-rendered tabular metadata surface

### Requirement: OpenOppsDB publishing is quality-gated

OpenOpps SHALL block Kaggle dataset publishing when the generated snapshot is structurally unusable or when required generation, validation, upload, or post-upload checks fail.

#### Scenario: Required generation or live publish step fails

- **WHEN** database initialization, default sync, artifact generation, schema validation, required-file validation, dataset create/version, manager notebook push, or post-upload status/version verification fails
- **THEN** the OpenOppsDB workflow blocks publishing and reports the blocker in private `snapshot-quality.json` evidence instead of silently publishing a misleading version

#### Scenario: Provider failures are classified but the snapshot remains defensible

- **WHEN** public upstream provider or source failures occur during a completed run
- **THEN** publishing may continue only if the failures are classified in `providerErrors` and `providerErrorDetails`
- **AND** the generated database, status, route, and job evidence remains internally consistent with a full-dataset snapshot

#### Scenario: Slow source adapters cannot block the daily run indefinitely

- **WHEN** one source adapter exceeds the configured source sync wall-clock timeout during the default full workflow
- **THEN** OpenOpps records a classified timeout in sync metrics, skips that source for the current run, and continues syncing the remaining sources

#### Scenario: Slow job provider routes cannot block the daily run indefinitely

- **WHEN** one executable job provider route exceeds the configured job-route wall-clock timeout during the default full workflow
- **THEN** OpenOpps records a classified timeout in sync metrics, skips that route for the current run, and continues syncing the remaining routes

#### Scenario: Manager notebook execution is bounded and observable

- **WHEN** the connected manager notebook runs the default full workflow on Kaggle
- **THEN** it applies a hard wall-clock timeout to bounded `openopps jobs sync --metrics-json --freshness-seconds --limit`
- **AND** it streams command diagnostics to Kaggle logs while preserving JSON stdout for evidence files
- **AND** it calls the generator to remove private evidence files and stage the public upload directory before calling `kaggle datasets version`
- **AND** the documented notebook push recipe applies a Kaggle kernel runtime timeout by default

#### Scenario: Manager notebook fails fast without publish credentials

- **WHEN** the connected manager notebook starts without Kaggle API credentials available through `KAGGLE_API_TOKEN`, `KAGGLE_USERNAME`/`KAGGLE_KEY`, a token path, or a local `kaggle.json`
- **THEN** it fails before installing OpenOpps, copying the prior database, or running the expensive sync
- **AND** it reports that Kaggle API credentials are required to publish `openoppsdb`

#### Scenario: Provider failures make the snapshot misleading

- **WHEN** provider or source failures are hidden, unclassified, dominant enough to make the snapshot misleading, or leave the run without source, board, executable route, or current/persisted job evidence
- **THEN** the OpenOppsDB workflow blocks publishing unless a documented first-run or upstream-outage explanation makes the empty evidence defensible

### Requirement: OpenOppsDB deployment remains local and verifiable

OpenOpps SHALL keep live Kaggle deployment credentialed and local/manual while providing deterministic non-live validation and thin documented Kaggle CLI wrappers.

#### Scenario: Contributor validates the bundle without live credentials

- **WHEN** a contributor runs the local Kaggle bundle validation recipe
- **THEN** OpenOpps regenerates deterministic metadata and, when a local SQLite database is supplied, validates the generated SQLite/CSV/Parquet artifact surface without requiring Kaggle credentials

#### Scenario: Maintainer deploys the live Kaggle dataset

- **WHEN** a maintainer runs the documented live create/version and manager notebook push recipes with Kaggle CLI credentials
- **THEN** the commands use local Kaggle CLI credentials from `kaggle auth login` or an already configured Kaggle API credential environment without printing secrets
- **AND** dataset create/version recipes stage a temporary upload directory that excludes private evidence and manager notebook files before calling the Kaggle dataset write command
- **AND** the manager push is preceded by running the private runtime generator create/version recipe so the notebook source gate downloads the current generator script
- **AND** CI does not publish the dataset, push the manager notebook, or require Kaggle secrets

#### Scenario: Maintainer verifies the live Kaggle surfaces

- **WHEN** a maintainer runs live post-deploy verification
- **THEN** the workflow checks dataset status/version, dataset files, downloaded metadata, manager notebook availability, and manager notebook files for `wyattowalsh/openoppsdb` and `wyattowalsh/openoppsdb-manager`
- **AND** it verifies direct SQLite readback plus CSV/Parquet table metadata instead of treating missing Kaggle `sqliteInfo.tables` as an OpenOpps data-shape failure

### Requirement: Release validation checks dependency and docs workflow hygiene

OpenOpps SHALL keep local contributor validation and GitHub Actions aligned for dependency locks, Python tests, docs type-check/build/unit/browser/accessibility tests, docs lint, OpenSpec validation, generated metadata, CLI smoke checks, and diff formatting.

#### Scenario: Contributor runs the local release validation graph

- **WHEN** a contributor runs `just ci`
- **THEN** OpenOpps checks diff formatting, `uv lock --check`, strict OpenSpec validation, coverage-enforced Python tests, docs type-check/build/unit/browser/accessibility tests, docs lint, Kaggle metadata generation, and CLI help smoke checks
- **AND** the graph does not conditionally skip a missing `rtk lint` executable

#### Scenario: CI validates lock files and docs tests

- **WHEN** GitHub Actions runs for a push, pull request, or manual dispatch
- **THEN** CI checks `uv.lock` with `uv lock --check` before frozen Python installation
- **AND** the docs job installs with the frozen pnpm lockfile and runs docs type-check, build, unit tests, browser e2e tests, mobile accessibility tests, and lint

#### Scenario: Maintainer runs optional docs checklist lint

- **WHEN** a maintainer needs the broader docs checklist lint surface
- **THEN** `just docs-rtk-lint` runs `rtk lint` explicitly
- **AND** default CI and `just ci` do not silently skip that lint when `rtk` is unavailable

### Requirement: Dependency maintenance and local secret hygiene are documented

OpenOpps SHALL keep dependency maintenance reviewable and prevent common local credential files from entering the repository.

#### Scenario: Renovate maintains Python and docs locks

- **WHEN** Renovate runs for the repository
- **THEN** it uses the recommended Renovate baseline with managers scoped to Python `pyproject.toml`/`uv.lock` and docs npm/pnpm dependencies
- **AND** scheduled lock-file maintenance keeps `uv.lock` and `docs/pnpm-lock.yaml` fresh through reviewable dependency pull requests

#### Scenario: Local credential files are generated or downloaded

- **WHEN** a maintainer creates local environment, Kaggle, package-registry, network, key, token, or credential files
- **THEN** the repository ignore rules exclude those files from normal git status
- **AND** `.env.example` remains available as the tracked non-secret configuration template
- **AND** CI, docs, and generated artifacts do not require printing or committing secrets
