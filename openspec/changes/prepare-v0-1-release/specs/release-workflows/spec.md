## ADDED Requirements

### Requirement: OpenOppsDB publishes daily full-snapshot artifacts

OpenOpps SHALL provide a generated Kaggle workflow for `wyattowalsh/openoppsdb` that publishes one daily full snapshot of active public job postings and preserves the prior SQLite ledger between scheduled runs.

#### Scenario: Scheduled manager notebook runs the default full workflow

- **WHEN** the connected `wyattowalsh/openoppsdb-manager` notebook runs on its daily Kaggle schedule
- **THEN** it installs OpenOpps from `git+https://github.com/wyattowalsh/openopps.git@main` unless an explicit controlled-test override is set
- **AND** it copies the newest prior `/kaggle/input/**/openoppsdb.sqlite` file into `/kaggle/working/openoppsdb/openoppsdb.sqlite` before syncing
- **AND** it initializes the database and runs `openopps sync --metrics-json` without source, board, provider, or limit filters
- **AND** it captures `sync_metrics.json`, `status.json`, `coverage.json`, and `snapshot-quality.json`
- **AND** it publishes `openoppsdb.sqlite`, every SQLite table as CSV and Parquet exports, `dataset-metadata.json`, the generated data dictionary exposed as `metadata/datapackage.json`, manager-run evidence files, and the generated manager notebook metadata

#### Scenario: Published metadata describes the full bundle

- **WHEN** the Kaggle bundle is generated
- **THEN** transient HTTP cache tables are excluded from the published SQLite database
- **AND** normalized sources, boards, provider routes, jobs, versions, raw payload snapshots, sync runs, sync observations, `openopps_tables`, and `openopps_columns` remain in the published SQLite database
- **AND** `dataset-metadata.json` describes every published file and includes useful Kaggle resource and column descriptions for CSV and Parquet exports
- **AND** `datapackage.json` includes the richer generated data dictionary for every resource, table, and field, with a byte-identical `metadata/datapackage.json` copy for live Kaggle downloads
- **AND** `openoppsdb.sqlite` includes `openopps_tables` and `openopps_columns` metadata tables matching the generated data dictionary

### Requirement: OpenOppsDB publishing is quality-gated

OpenOpps SHALL block Kaggle dataset publishing when the generated snapshot is structurally unusable or when required generation, validation, upload, or post-upload checks fail.

#### Scenario: Required generation or live publish step fails

- **WHEN** database initialization, default sync, artifact generation, schema validation, required-file validation, dataset create/version, manager notebook push, or post-upload status/version verification fails
- **THEN** the OpenOppsDB workflow blocks publishing and reports the blocker in `snapshot-quality.json` instead of silently publishing a misleading version

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
- **THEN** it applies a hard wall-clock timeout to `openopps sync --metrics-json`
- **AND** it streams command diagnostics to Kaggle logs while preserving JSON stdout for evidence files
- **AND** the documented notebook push recipe applies a Kaggle kernel runtime timeout by default

#### Scenario: Provider failures make the snapshot misleading

- **WHEN** provider or source failures are hidden, unclassified, dominant enough to make the snapshot misleading, or leave the run without enabled source, board, executable route, or current/persisted job evidence
- **THEN** the OpenOppsDB workflow blocks publishing unless a documented first-run or upstream-outage explanation makes the empty evidence defensible

### Requirement: OpenOppsDB deployment remains local and verifiable

OpenOpps SHALL keep live Kaggle deployment credentialed and local/manual while providing deterministic non-live validation and thin documented Kaggle CLI wrappers.

#### Scenario: Contributor validates the bundle without live credentials

- **WHEN** a contributor runs the local Kaggle bundle validation recipe
- **THEN** OpenOpps regenerates deterministic metadata and, when a local SQLite database is supplied, validates the generated SQLite/CSV/Parquet/data-dictionary artifact surface without requiring Kaggle credentials

#### Scenario: Maintainer deploys the live Kaggle dataset

- **WHEN** a maintainer runs the documented live create/version and manager notebook push recipes with Kaggle CLI credentials
- **THEN** the commands use the local `KAGGLE_API_TOKEN="$(kaggle auth print-access-token)"` credential pattern without printing secrets
- **AND** CI does not publish the dataset, push the manager notebook, or require Kaggle secrets

#### Scenario: Maintainer verifies the live Kaggle surfaces

- **WHEN** a maintainer runs live post-deploy verification
- **THEN** the workflow checks dataset status/version, dataset files, downloaded metadata, manager notebook availability, and manager notebook files for `wyattowalsh/openoppsdb` and `wyattowalsh/openoppsdb-manager`
