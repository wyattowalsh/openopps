# Facts

- The Kaggle dataset id is `wyattowalsh/openoppsdb` and the connected manager notebook id is `wyattowalsh/openoppsdb-manager`.
- The dataset update target is one full daily snapshot of active public job postings across all enabled OpenOpps sources and boards.
- The manager notebook installs OpenOpps with `pip install --upgrade git+https://github.com/wyattowalsh/openopps.git@main` by default, with a documented override only for controlled testing.
- Each manager run copies the newest prior `openoppsdb.sqlite` dataset input into the Kaggle working directory before syncing, so job identities, versions, observations, and lifecycle state accumulate instead of starting over.
- Each manager run initializes the database if needed and then runs the default full CLI workflow `openopps sync --metrics-json` with no source, board, provider, or limit filters.
- The snapshot database excludes transient HTTP cache tables from published artifacts while preserving normalized sources, boards, provider routes, jobs, job versions, raw payload snapshots, sync runs, sync observations, and generated metadata tables.
- Every published SQLite table is exported to both `exports/csv/<table>.csv` and `exports/parquet/<table>.parquet`.
- `dataset-metadata.json` describes every published SQLite, CSV, and Parquet data file and includes concise, useful Kaggle resource and column descriptions for every CSV and Parquet table export.
- Manager-run evidence files such as `sync_metrics.json`, `status.json`, `coverage.json`, `snapshot-quality.json`, `sync_stderr.txt`, and generated datapackage metadata are private quality-gate artifacts and must be pruned before dataset publication.
- The published SQLite database includes `openopps_tables` and `openopps_columns` metadata tables with table and column descriptions that match the generated Kaggle field metadata.
- Publishing blocks when the database initialization, default sync command, artifact generation, schema validation, required-file validation, Kaggle dataset create/version command, manager notebook push, or post-upload status/version check fails.
- Publishing blocks when the resulting snapshot is structurally unusable, including missing enabled source evidence, missing board data, missing executable route evidence, or missing current/persisted job evidence without a documented first-run or upstream-outage explanation.
- Provider or source failures from public upstream systems do not automatically block publishing when the run completes, the dataset is internally consistent, and the failures are classified in `providerErrors` and `providerErrorDetails`.
- Provider or source failures do block publishing when they are hidden, unclassified, dominant enough to make the snapshot misleading, or leave the run without a defensible full-dataset snapshot.
- The deployment flow uses Kaggle CLI credentials to create or version the public dataset and push the connected manager notebook.
- Post-deploy verification confirms the live Kaggle dataset version is complete and current, including `openoppsdb.sqlite`, CSV exports, Parquet exports, generated field-level Kaggle metadata, dataset status/version, and manager notebook availability, while excluding private evidence and datapackage files from the public file list.
- The repo validation path includes generated artifact parity, focused Kaggle metadata/export tests, full `just ci` parity when feasible, live deployment verification, and manual inspection of the final dataset surfaces.
