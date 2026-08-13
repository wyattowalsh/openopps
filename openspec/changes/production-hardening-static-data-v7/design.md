## Decisions

### Authoritative ingestion

Provider fetches return a typed result containing jobs, completeness, authority, observed/advertised counts, and continuation evidence. Adapters buffer and validate the entire route. Only complete authoritative results may close jobs. Source freshness advances only after normal iterator exhaustion. Authentication, access, schema, and rate-limit failures are not route absence.

### Durable persistence and private caching

Create a pending sync run before network access, commit `db_batch_size` progress, and finish every run as succeeded or failed. Current-row hashes describe current raw state; version hashes remain immutable. File-backed SQLite is the supported contract, and exports promote sibling temporary files atomically. Cache v2 stores redacted/canonical location plus a hash of request identity, never raw bodies, secrets, or credential-bearing query strings; legacy rows are invalidated. Shared work is shielded from waiter cancellation.

### Immutable artifact v7

Generate only in an owned sibling candidate directory. Immutable assets live under `/releases/<root-digest>/`; `/channels/production.json` names current and previous releases. A canonical manifest enumerates each safe path, byte length, media type, SHA-256, role, semantic count, source/input/generator/lock provenance, schema, and snapshot time. The release ID hashes canonical manifest content without a self-referential root. Source policy has separate structural and eligibility gates: canonical evidence/schema/corpus closure may validate while blocked sources keep the eligibility audit red. The deny-only policy module, evidence, schema, and reference corpus are hashed into generator provenance and cross-checked against `publication-policy.json`; catalog metadata cannot override a reviewed provider or source denial. Promotion requires exact-set, rights, freshness, and platform-budget verification.

### Release-pinned web product

One `SnapshotClient` resolves and validates the channel once per request/session and serves search, details, metadata, sitemaps, and build checks from one release. Search is browser/Web-Worker-first: select Pagefind custom records only if a frozen-corpus benchmark meets semantic parity and recorded budgets; otherwise select a compressed columnar/bitset worker by ADR. The server cannot fall back to a full production scan. Reducers remain pure; IndexedDB writes serialize outside state updates; imports validate and back up state. Offline is opt-in, verified, quota-preflighted, and bounded. Telemetry excludes raw queries and arbitrary intake origins.

### Free serving, governance, and supply chain

Use separate assets-only staging/production Workers on the Free plan, initially via `workers.dev`: no script, bindings, `run_worker_first`, or Workers Cache. A serving version contains current and previous releases, promotes 100% atomically, and applies immutable/revalidated cache policy, CORS, `nosniff`, and `noindex`. Ordinary upload requires an existing Worker. A first bootstrap is a separate, dry-run-first exception: bind one frozen candidate to fresh absent-target account/name evidence, use the pinned Wrangler deploy, require exactly one version/deployment in readback, and record that initial version as `rollbackWorkerVersionId` before ordinary uploads. GitHub Releases holds one exact-archive-SHA-addressed asset with manifest, SBOM, provenance, and attestation; its tag separately addresses the stage-root digest. Archive restore requires external archive/stage/source/current/prior identities, a 4-GiB expanded-byte ceiling, bounded no-follow streaming extraction, semantic manifest/provenance/SPDX closure, stage verification, and OS-native exclusive naming of an absent destination. Archive publication is manual and draft-first: an immutable-release setting and exact one-asset draft precede isolated attest, publish, and fresh read-only verification jobs. Public sources are fail-closed on rights state, required attribution is emitted, and Kaggle installs immutable source/tool inputs and verifies a recomputed canonical package root.

## Compatibility and ownership

- v6 stays readable only through a bounded dual-read cutover; only v7 may be newly promoted.
- Cache v1 is invalidated, not migrated. SQLite migrations preserve existing rows. Browser storage upgrades in place and retains three pre-import backups.
- `jobs list` remains behavior-compatible until query/memory measurements justify a separate public deprecation.
- One owner each controls ingestion/providers, cache/storage/migrations, artifact schema/generator/verifier, Kaggle runtime, shared web data types, and Just/workflows. Generated-tree writers and live release mutations are serialized.
- The four-slot runtime executes rolling root-plus-three tranches. Every dispatch resolves as verified success, explicit read-only skip, or recovered failure before its barrier opens.

## Stop and rollback rules

- Stop reconciliation on incomplete pagination, count mismatch, loops, access/schema failure, or ambiguous empty results.
- Stop release on non-determinism, digest/set/path/symlink, rights/privacy/freshness, provenance, or budget failure.
- Stop Free hosting on actual full-corpus rejection; report R2 feasibility without activating it.
- Stop cutover if web consumers mix releases or require the committed full tree.
- Stop live publication without exact target, credentials, previous-good version, and rollback proof. For an absent Worker, stop unless the one-time bootstrap records its initial version/deployment as the rollback identity.
- Stop archive publication unless immutable releases are enabled, the exact `main` SHA owns a non-latest one-asset draft, and independent download, GitHub/SPDX attestation verification, and safe dual-release restore all pass.
- Stop ordinary tree removal until serving and archive recovery pass; stop history rewriting until backup, ref inventory, SHA mapping, freeze, and separate force-push approval exist.
