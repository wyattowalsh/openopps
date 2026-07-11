## Summary

Surface surplus board-ingestion data through normalization, tiered docs search artifacts, and provider promotion without bloating the committed static index.

## Motivation

Public docs artifacts were lossy by design: full HTML for all open jobs would exceed git push limits, while normalized columns under-promote list-endpoint fields already present in raw payloads. Sync evidence tables exist in SQLite but were omitted from the search manifest.

## Scope

- Promote high-value provider list-endpoint fields into `JobRecord` / `version.extra_payload` (`posting_kind`, `seniority`, `provider_extras`).
- Fix Workable raw payload split (`raw_listing` vs `raw_detail`).
- Tier detail shards: T2 full body for indexable jobs, T1 metadata-only for other open jobs; never commit `payloadSnapshots`.
- Add manifest facets for `seniority` and `daysOpen`; attach sync-run aggregates when `job_sync_runs` exists.
- Document surplus taxonomy S1–S4 in docs MDX.

## Release policy

Index release policy **B (adopted)**: commit refreshed `docs/public/data/openopps-search/` artifacts to git and gate releases with maintainer `just docs-search-index-check` (local `kaggle/openoppsdb.sqlite` required). CI validates committed snapshot schema and tests; it does not regenerate the full index on every run.

## Non-goals

- Application-form PII (Greenhouse `questions`, demographics).
- ML skill extraction or LLM summarization.
- Optional Greenhouse pay-transparency N+1 pilot (deferred unless trivial).

## Success criteria

1. Greenhouse metadata/hierarchy promoted; Workable raw split fixed.
2. Index tiered and git-pushable; no 1.9GB monolith.
3. Indexable jobs retain full description in T2 shards.
4. Manifest includes seniority facet and days-open column.
5. MDX explains surplus taxonomy S1–S4.
