# OpenOppsDB Kaggle Evidence

Last updated: 2026-06-06

## Current Status

The OpenOppsDB Kaggle dataset is live at `wyattowalsh/openoppsdb` version 14 and
now matches the corrected public file-surface contract. The public file list is
limited to `openoppsdb.sqlite`, `exports/csv/*.csv`, and
`exports/parquet/*.parquet`. Private manager evidence and datapackage files are
not present in the live v14 file list.

The connected manager notebook `wyattowalsh/openoppsdb-manager` was pushed as
Kaggle kernel version 4. Its latest run still fails fast because the Kaggle
notebook environment does not expose publish credentials.

## Repository Evidence

- Branch/worktree at implementation time: `main`.
- Implementation commit: `26f09f970b4f8089fab522e9842ab4346e2622ab`
  (`fix: narrow openoppsdb kaggle surface`).
- GitHub CI for that commit:
  - run `27071844368`
  - status `completed`
  - conclusion `success`
  - URL: `https://github.com/wyattowalsh/openopps/actions/runs/27071844368`
- Local validation passed:
  - `uv run pytest tests/unit/openopps/test_kaggle_metadata.py -q`
    (`21 passed`)
  - `just kaggle-bundle-check kaggle/openoppsdb.sqlite` (`21 passed`)
  - `rtk npx -y @fission-ai/openspec@latest validate "prepare-v0-1-release" --strict`
  - `just docs-build`
  - `just ci` (`328 passed`, coverage `90.45%`, docs typecheck/build/lint
    passed)
- Local generated `kaggle/` tree contains only Kaggle control files,
  manager notebook files, `openoppsdb.sqlite`, 14 CSV exports, and 14 Parquet
  exports. Staged live dataset uploads contain only Kaggle dataset control files
  plus the SQLite/CSV/Parquet data files.

## Live Dataset Evidence

- `just kaggle-live-status` reports:
  - `status`: `ready`
  - `current_version_number`: `14`
- `just kaggle-live-files 200` reports exactly `29` public files:
  - `openoppsdb.sqlite`
  - 14 CSV exports under `exports/csv/`
  - 14 Parquet exports under `exports/parquet/`
- The live v14 file list does not contain:
  - `coverage.json`
  - `status.json`
  - `sync_metrics.json`
  - `snapshot-quality.json`
  - `sync_stderr.txt`
  - `datapackage.json`
  - `metadata/datapackage.json`
- Live creation timestamps for v14 files are around
  `2026-06-06 19:39:26` through `2026-06-06 19:40:01` UTC.
- `kaggle datasets metadata wyattowalsh/openoppsdb` returns the v14 dataset
  `info` block with the corrected description and expected update frequency,
  but Kaggle's metadata download endpoint strips the uploaded `resources`
  schema array.

## Field Metadata Evidence

- The generated and uploaded `dataset-metadata.json` declares `29` resources:
  `openoppsdb.sqlite`, every CSV export, and every Parquet export.
- Every CSV and Parquet resource schema includes field names, titles,
  descriptions, and Kaggle-supported field types.
- Sample generated field metadata for `exports/csv/jobs.csv` field
  `board_key`:
  - `title`: `Board Key`
  - `description`: `Board key this job belongs to.`
  - `type`: `id`
- Focused tests enforce that CSV/Parquet field titles are human-readable labels,
  not duplicated descriptions, and that private evidence/datapackage resources
  are absent from Kaggle dataset metadata.

## Downloaded Artifact Evidence

Representative live v14 files were downloaded from Kaggle and inspected locally:

- `exports/csv/openopps_tables.csv`
- `exports/parquet/openopps_tables.parquet`

The downloaded CSV and Parquet files are readable and match:

- rows: `14`
- columns: `table_name`, `table_title`, `table_description`, `csv_path`,
  `parquet_path`

## Browser Evidence

- Chrome DevTools MCP opened `https://www.kaggle.com/datasets/wyattowalsh/openoppsdb`
  successfully and captured accessibility snapshots plus network requests.
- The public Kaggle page and a fresh isolated cache-busting Chrome context still
  showed stale v13 content immediately after v14 became ready: old description,
  `34 files`, and private evidence files in Data Explorer.
- The CLI/API status and file endpoints consistently report v14 ready with the
  corrected 29-file surface, so the browser discrepancy is treated as Kaggle
  public page cache lag, not as the live dataset API state.
- Chrome DevTools also opened the private manager notebook URL, but the browser
  context is unauthenticated and Kaggle displays `We can't find that page.`

## Manager Notebook Evidence

- Kaggle manager id: `wyattowalsh/openoppsdb-manager`.
- Pushed manager notebook: Kaggle kernel version `4`.
- Authenticated kernel list reports:
  - ref: `wyattowalsh/openoppsdb-manager`
  - title: `openoppsdb manager`
  - lastRunTime: `2026-06-06 19:43:27.227000`
- Direct `kaggle kernels status wyattowalsh/openoppsdb-manager` currently
  returns Kaggle `500 Server Error`; authenticated kernel list and logs are the
  usable status surfaces.
- Latest manager log shows the expected fail-fast blocker at about `10.588s`:
  - fails in cell 1 at `require_kaggle_credentials()`
  - occurs before `install_openopps()`, `copy_latest_input_db()`, or sync
  - error message: `Kaggle API credentials are required to publish openoppsdb.
    Configure KAGGLE_USERNAME/KAGGLE_KEY or KAGGLE_API_TOKEN as Kaggle notebook
    secrets before running the manager.`

## Remaining Blocker

Kaggle-side notebook publish credentials must be configured for
`wyattowalsh/openoppsdb-manager`. The Kaggle CLI 2.1.2 surface available here
supports kernel push/list/status/log/output operations, but it does not expose a
kernel secret or notebook environment-variable setter.

Required external action:

- Configure `KAGGLE_API_TOKEN` or `KAGGLE_USERNAME`/`KAGGLE_KEY` as Kaggle
  notebook secrets/environment variables for `wyattowalsh/openoppsdb-manager`.
- Rerun the manager notebook.
- Verify that the manager completes the full sync, quality gate, prune step, and
  dataset publish path and creates a new live dataset version greater than `14`.
