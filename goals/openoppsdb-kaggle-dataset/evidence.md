# OpenOppsDB Kaggle Evidence

Last updated: 2026-06-06

## Current Status

The OpenOppsDB Kaggle dataset is live and verified at `wyattowalsh/openoppsdb`
version 13, but the full daily scheduled publisher is not complete yet. The
connected manager notebook is deployed and scheduled, but its latest Kaggle run
fails fast because the Kaggle notebook environment does not yet expose publish
credentials.

## Repository Evidence

- Branch/worktree: `main`, clean against `origin/main`.
- Latest implementation commit: `9b353b557df9f6db0905f8644672b6dccbeee644`.
- Latest GitHub CI: run `27068360705`, status `completed`, conclusion `success`.
- The credential hardening commit makes the manager fail before installing
  OpenOpps, copying the prior database, or running sync when Kaggle credentials
  are absent.

## Live Dataset Evidence

- `just kaggle-live-status` reports:
  - `status`: `ready`
  - `current_version_number`: `13`
- `just kaggle-live-verify` passes against `wyattowalsh/openoppsdb`.
- Version 13 includes the expected public artifact surface:
  - `openoppsdb.sqlite` (`4047974400` bytes)
  - `metadata/datapackage.json`
  - `snapshot-quality.json`
  - `status.json`
  - `coverage.json`
  - `sync_metrics.json`
  - full CSV exports under `exports/csv/`
  - full Parquet exports under `exports/parquet/`
- Browser/Chrome DevTools inspection of the public dataset page verified:
  - page title `openoppsdb`
  - expected update frequency `Daily`
  - visible evidence files in the Data Explorer
  - visible dataset size `7.13 GB`
  - dataset description documenting the daily manager flow

## Downloaded Artifact Evidence

Representative live files were downloaded from Kaggle and inspected locally:

- `snapshot-quality.json`
  - `status`: `pass`
  - `hardBlockers`: `[]`
  - warnings: `classified_provider_errors_present`,
    `status_issue:missing_route_metadata`, `status_issue:detect_only_routes`,
    `status_issue:only_non_supported_provider_hints`
- quality counts:
  - `sources`: `502`
  - `boards`: `25411`
  - `persistedJobs`: `64513`
  - `currentJobs`: `64487`
  - `jobSyncRuns`: `2719`
  - `providerErrorCount`: `493`
- `sync_metrics.json` excerpt:
  - `jobs`: `62223`
  - `boards`: `27163`
  - `skipped`: `450`
  - `jobsPersisted`: `61770`
  - `jobsDeduped`: `453`
- `metadata/datapackage.json` contains `33` resources and includes the sampled
  required resources.
- `exports/csv/openopps_tables.csv` and
  `exports/parquet/openopps_tables.parquet` are readable and match:
  - `14` rows
  - columns: `table_name`, `table_title`, `table_description`, `csv_path`,
    `parquet_path`

## Manager Notebook Evidence

- Kaggle manager id: `wyattowalsh/openoppsdb-manager`.
- Pulled Kaggle metadata reports:
  - `id_no`: `121909491`
  - `kernel_type`: `notebook`
  - `is_private`: `true`
  - `enable_internet`: `true`
  - `keywords`: `["scheduled"]`
  - `dataset_sources`: `["wyattowalsh/openoppsdb"]`
- `just kaggle-live-verify` sees the manager in the authenticated notebook list
  with `lastRunTime` `2026-06-06 16:58:52.160000`.
- The latest downloaded manager log shows the expected fail-fast blocker at
  about `10.139s`:
  - fails in cell 1 at `require_kaggle_credentials()`
  - occurs before `install_openopps()`, `copy_latest_input_db()`, or sync
  - error message: `Kaggle API credentials are required to publish openoppsdb.
    Configure KAGGLE_USERNAME/KAGGLE_KEY or KAGGLE_API_TOKEN as Kaggle notebook
    secrets before running the manager.`

## Remaining Blocker

Kaggle-side notebook publish credentials must be configured for
`wyattowalsh/openoppsdb-manager`. The Kaggle CLI 2.1.2 surface available here
supports kernel push/list/status/log/output operations, but it does not expose a
kernel secret or notebook environment-variable setter. The private manager page
is also not accessible from the current unauthenticated Chrome DevTools browser
context.

Required external action:

- Configure `KAGGLE_API_TOKEN` or `KAGGLE_USERNAME`/`KAGGLE_KEY` as Kaggle
  notebook secrets/environment variables for `wyattowalsh/openoppsdb-manager`.
- Rerun the manager notebook.
- Verify that the manager completes the full sync, quality gate, and dataset
  publish path and creates a new live dataset version greater than `13`.
