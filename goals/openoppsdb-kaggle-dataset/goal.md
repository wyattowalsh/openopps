# OpenOppsDB Kaggle Dataset

Build, deploy, and verify the Kaggle dataset `wyattowalsh/openoppsdb` as a daily full-snapshot pipeline for active public OpenOpps job postings. The pipeline should install OpenOpps from `wyattowalsh/openopps`, run the default full CLI sync, preserve the existing SQLite ledger, validate snapshot quality, export SQLite/CSV/Parquet artifacts, publish through the Kaggle CLI, and verify the live dataset and manager notebook.

Use `facts.md` as the shared understanding of required outcomes and `plan.md` as the execution plan.

Done means the accepted facts are implemented and verified: local generated artifacts and tests pass, the quality gate blocks broken or misleading snapshots while preserving classified provider-error evidence, the live Kaggle dataset and manager notebook are deployed, Browser tools verify the Kaggle schedule/status surfaces, downloaded live artifacts pass SQLite/CSV/Parquet/metadata inspection, the cleaned work is committed, and the final evidence is recorded.
