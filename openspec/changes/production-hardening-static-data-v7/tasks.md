# production-hardening-static-data-v7 - tasks

Reconciled against the 2026-08-13 working tree. A checked task means its
repository implementation and named local proof are present; it does not claim
an exact-SHA origin run, credentialed publication, live deployment, remote
readback, cutover, or destructive cleanup. Those independent gates remain
unchecked below.

## 0. Contract and red-test barrier

- [x] 0.1 Strictly validate proposal, design, delta specs, and task graph.
- [x] 0.2 Record confirmed-finding-to-evidence ownership and merge barriers.
- [x] 0.3 Add provider truncation/count/loop and partial-yield freshness red tests.
- [x] 0.4 Add cache-secret/cancellation/hash/N+1/DB/export red tests.
- [x] 0.5 Add artifact bit-flip/set/path/symlink/stale/rights/determinism/failure red tests.
- [x] 0.6 Freeze search semantics and a reproducible performance baseline corpus.

## 1. Python ingestion and persistence

- [x] 1.1 Add explicit complete/authoritative provider results and close-missing gate.
- [x] 1.2 Harden Rippling pagination/advertised totals.
- [x] 1.3 Harden Workday offset/total/repetition behavior.
- [x] 1.4 Harden WPJobManager pagination/empty-continuation behavior.
- [x] 1.5 Harden BambooHR completeness behavior.
- [x] 1.6 Advance source freshness only on normal completion.
- [x] 1.7 Route ingest through canonical packaged-over-stored resolution.
- [x] 1.8 Encode provider-aware HTTP outcome disposition.
- [x] 1.9 Create pending runs before fetch and record failures/progress/final state.
- [x] 1.10 Commit job upserts in configured batches and close once after complete fetch.
- [x] 1.11 Migrate sync-run schema with upgrade/downgrade coverage.
- [x] 1.12 Store cache v2 hashed identity without raw body/credential URL.
- [x] 1.13 Invalidate legacy cache rows and move supported query secrets off persisted URLs.
- [x] 1.14 Shield coalesced tasks and test cancellation cleanup.
- [x] 1.15 Hydrate current hashes correctly while preserving immutable version hashes.
- [x] 1.16 Replace N+1 job hydration with bounded queries.
- [x] 1.17 Enforce supported file-backed SQLite URLs.
- [x] 1.18 Atomically replace exports.
- [x] 1.19 Measure list memory/query behavior before public limit changes.

## 2. Artifact v7 and public-data governance

- [x] 2.1 Define canonical JSON, UTC timestamps, safe paths, media types, and root algorithm.
- [x] 2.2 Emit file hashes/sizes/roles/counts and full reproducible provenance.
- [x] 2.3 Generate only in owned sibling candidates and verify exact closure before promotion.
- [x] 2.4 Enforce 18,000-file and sub-24-MiB internal budgets.
- [x] 2.5 Enforce ordinary freshness warn/block and auditable degraded override.
- [x] 2.6 Define source/field rights states and fail-closed public inclusion.
- [x] 2.7 Emit attribution, sanitized provenance, and quality summaries.
- [x] 2.8 Add secret/PII fixtures, retention, correction, and takedown procedure.
- [x] 2.9 Promote atomically, preserve previous, and prove repeated-generation identity.
- [ ] 2.10 Retain v6 dual-read only until two v7 releases and rollback pass.

## 3. Kaggle and operational security

- [x] 3.1 Centralize owned staging and reject symlink/protected/unowned delete targets.
- [x] 3.2 Recompute canonical runtime roots and reject substitution/extra/path attacks.
- [x] 3.3 Replace mutable source/tool installs with immutable lock-controlled inputs.
- [x] 3.4 Replace Just shell interpolation with validated argv/environment transport.
- [x] 3.5 Stage/hash publication before one mutation and record exact readback/rollback ledger.
- [x] 3.6 Archive or fingerprint-gate completed one-shot migrations.

## 4. Release-pinned web product

- [x] 4.1 Add typed v7 schemas and one integrity-checking SnapshotClient.
- [x] 4.2 Route search, detail, metadata, sitemap, and build through the pinned client.
- [x] 4.3 Prove build/routes with the full local production tree absent.
- [x] 4.4 Benchmark Pagefind and compressed bitset workers on frozen semantics.
- [x] 4.5 Record engine ADR from parity, median/p95, heap, transfer, and saved-count evidence.
- [x] 4.6 Remove production server-side full-index construction/scanning.
- [x] 4.7 Make reducers pure and IndexedDB persistence serialized/transactional.
- [x] 4.8 Preserve state on failure; validate imports and retain three backups.
- [x] 4.9 Require complete saved-search baselines for review/reconciliation.
- [x] 4.10 Add opt-in verified bounded offline cache and privacy-bounded telemetry.
- [x] 4.11 Keep JobPosting disabled until normalized readiness passes.
- [x] 4.12 Repair lint, error/loading/empty states, focus/keyboard, accessibility, and three-browser E2E.

## 5. Free delivery and independent archive

- [x] 5.1 Add pinned assets-only staging/production Wrangler configs and config assertions.
- [x] 5.2 Emit immutable/revalidated cache, CORS, `nosniff`, and `noindex` headers.
- [x] 5.3 Stage current+previous releases/channel and preflight counts/sizes/symlinks/headers.
- [ ] 5.4 Upload the actual dual-release corpus to Workers Free staging twice.
- [ ] 5.5 Fetch/hash every file and verify status, CORS, cache, ETag, and missing paths.
- [ ] 5.6 Promote 100%, roll back, verify, and re-promote; never gradual-split.
- [ ] 5.7 Build a content-addressed GitHub Release archive with manifest/SBOM/provenance/attestation.
- [x] 5.8 Stop on undocumented Free limits and report R2 feasibility only.

## 6. Dependencies, CI, docs, and proof

- [x] 6.1 Upgrade secure dependency floors and regenerate locks.
- [x] 6.2 Give Renovate Python/npm and Dependabot actions exclusive ownership.
- [x] 6.3 Configure Ruff/ty, reach zero package diagnostics, and gate them.
- [x] 6.4 Test Python 3.12/3.13/3.14 and lowest direct dependencies.
- [x] 6.5 Pin tools/actions, set timeouts, disable credential persistence, and add dependency review/SBOM/attestations.
- [x] 6.6 Make `just ci` and GitHub Actions execute one canonical gate graph.
- [x] 6.7 Update config, docs, README, and nested AGENTS for `web/`, v7, recipes, environment, and rollback.
- [x] 6.8 Run docs stewardship, determinism, full Python/web/E2E/build/OpenSpec gates, and adversarial proof review.
- [ ] 6.9 Push only with approval; capture exact-SHA CI, both deployments, and production smoke.

## 7. Tree and history cleanup

- [ ] 7.1 Remove the committed production tree ordinarily only after cutover/archive proof.
- [ ] 7.2 Retain schema, tiny deterministic fixture, generator/verifier, and signed release record.
- [ ] 7.3 Prove clean-clone CI/build without the full tree.
- [ ] 7.4 Inventory refs/deployments, freeze writes, and independently verify a mirror bundle.
- [ ] 7.5 Prepare both historical-path filters, SHA mapping, and recovery instructions.
- [ ] 7.6 Execute no rewrite or force-push without separate explicit approval.
- [ ] 7.7 After approval, verify all refs, fresh clone, CI, deployment, production, collaborator recovery, and host-retention follow-up.
