## Summary

Harden OpenOpps ingestion, persistence, public-data publication, and the read-only Jobs/Explorer so incomplete upstream snapshots cannot close jobs, cached requests cannot persist credentials, generated releases are reproducible and independently verifiable, and the production snapshot can move out of Git onto an atomic, rollback-tested, completely-free static-asset path.

## Motivation

The current implementation can mark partial source syncs fresh, reconcile incomplete provider pages as authoritative, persist query credentials and raw request bodies, expose stale payload hashes, perform N+1 job hydration, and publish generated data without content digests or atomic promotion. The web app has mixed local/remote data access, security advisories, full-index server construction, and local-state failure modes. Publication also uses mutable runtime inputs, unsafe shell interpolation, and incomplete rights/freshness gates. The committed snapshot is 41 days old and occupies 577,248,789 bytes across 1,120 files.

## Scope

- Make provider and source reconciliation explicitly complete, authoritative, and failure-ledgered.
- Minimize cached request material, fix shared-request cancellation, and bound SQLite hydration/export behavior.
- Add content-addressed v7 artifacts with provenance, exact verification, atomic staging, freshness/rights gates, and rollback records.
- Route all web data consumers through one release-pinned client and eliminate production server-wide index scans.
- Harden browser persistence, import/reconciliation, offline behavior, telemetry, accessibility, and browser evidence.
- Harden Kaggle staging/runtime integrity, public-data governance, CI parity, dependencies, typing, SBOMs, and attestations.
- Prove an assets-only Cloudflare Workers Static Assets Free deployment with atomic promotion and rollback, plus an independent archive.
- Remove production data from ordinary Git only after cutover; prepare but do not execute the separately approved history rewrite.

## Non-goals

- Hosted ingestion, accounts, write APIs, a TUI, or a non-CLI Python product surface.
- Silently switching to a metered host if Free-plan proof fails.
- Enabling structured `JobPosting` before normalized required fields validate.
- Pushing, publishing, production mutation, history rewriting, or force-pushing without the required separate authority.

## Success criteria

1. Incomplete upstream responses never advance freshness or close jobs; every attempt has a terminal ledger state.
2. Cache rows contain no raw request bodies or credential-bearing URLs; shared cancellation, current hashes, query counts, and exports are correct.
3. A v7 release verifies exact closure, paths, canonical bytes, digests, provenance, rights, freshness, and platform budgets and is reproducible.
4. Web build/routes/E2E pass with the full local production tree absent and every consumer pinned to one release.
5. The actual full corpus uploads to Workers Free staging, verifies, atomically promotes, rolls back, and re-promotes without Worker execution or paid service.
6. Dependency, type, lint, test, build, OpenSpec, artifact, and supply-chain gates are green through canonical `just` recipes.
7. Exact release evidence plus an independent archive restores current and previous data.
8. Ordinary data-tree removal follows cutover; history rewriting remains a separately approved destructive wave.
