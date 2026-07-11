# ingest-data-surplus — tasks

## Completed

- [x] Promote Greenhouse list-endpoint surplus into `JobRecord` / `version.extra_payload` (`posting_kind`, `provider_extras`).
- [x] Split Workable `raw_listing` vs `raw_detail` in provider adapter.
- [x] Tier docs search detail shards: T1 metadata-only, T2 bounded plain-text body (≤4000 chars); omit `payloadSnapshots` from git index.
- [x] Add manifest `seniority` facet and `daysOpen` job column; derive seniority from title/experience when `extra_payload` lacks it.
- [x] Attach sync-run aggregates to manifest `dashboard.sync` when `job_sync_runs` exists.
- [x] Document surplus taxonomy S1–S4 in `docs/content/docs/data-model.mdx`.
- [x] Adopt index release policy B: committed `docs/public/data/openopps-search/` + maintainer `just docs-search-index-check` (not CI regen).
- [x] Update `AGENTS.md` / `docs/AGENTS.md` with tiered-index generator and refresh commands.
