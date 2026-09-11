## Why

OpenOpps can synchronize stored provider routes, but it does not yet offer the direct URL workflow that users expect from a job-board CLI: paste a supported ATS board, exact posting, or ordinary company careers URL and receive a truthful full-board or single-post result. Existing route detectors also project URLs into board-route metadata and may discard exact posting identity, while provider support is reported too coarsely to distinguish list, native get, authoritative board-scan get, and unlisted/direct-link behavior.

Adding URL pulls without an explicit contract would risk overclaiming completeness, confusing operational pulls with source discovery, partially mutating job lifecycle state, or mixing human diagnostics into machine output. The feature therefore needs one capability-aware service shared by both CLI spellings, bounded explainable resolution, operation-specific provider evidence, a safe ephemeral mode, and a separate audited persistence domain.

## What Changes

- Add bare `openopps <URL>` dispatch and `openopps jobs pull <URL> --operation auto|list|get`, backed by the same pull service and renderer without changing existing job command meanings.
- Add public `providers detect`, `providers inspect`, and `providers capabilities` commands with typed target identities, provenance, operation-level capability reporting, and honest unsupported results.
- Resolve native supported ATS URLs deterministically, then optionally inspect exactly one ordinary careers page using bounded redirects, metadata, embedded links, page links, and capability-declared slug probes. Keep this operational path isolated from quarantined discovery and source-catalog mutation.
- Add explicit URL-list hooks for Ashby, BambooHR, Consider Jobs, Greenhouse, Lever, Rippling, Teamtailor, Workable, Workday, and WP Job Manager. Exact gets prefer a declared native public operation and otherwise require an authoritative complete board scan with exactly one match.
- Separate membership authority from detail coverage, make unlisted/direct-link behavior capability-gated, and fail closed on ambiguity, incompleteness, response or page-budget exhaustion, unsafe destinations, and unsupported operations.
- Add semantic Rich output for interactive use; normalized JSON defaults for pipes; explicit pretty, JSON, JSONL, table, raw-envelope, atomic file-output, and interactive pager behavior; and stable stderr/exit semantics.
- Persist successful pulls only with opt-in `--save` (CLI default False). `--no-save` leaves all operational tables unchanged and remains independent from HTTP-cache behavior. Persist failure exits 9. Use deterministic reserved non-catalog identities, a separate `url_pull_runs` audit domain, atomic list application, and point-get non-closure semantics.
- Extend the shared HTTP/cache path with encoded and decoded response-size limits and finite resolver, page, probe, and request budgets rather than creating a second transport stack.
- Extend plugins with optional validated typed URL-target and operation hooks; legacy provider or detector registration alone does not imply URL-pull support.
- Add focused provider, resolver, service, output, storage, migration, CLI, help, plugin, docs, and full-repository assurance.

## Capabilities

### New Capabilities

None. URL pulls extend the existing CLI, provider-ingestion, storage/export, cache, plugin, and observability capabilities.

### Modified Capabilities

- `cli-domain`: Add URL-first pull commands, controls, semantic and machine output, stable failures, and public provider inspection while preserving existing workflow meanings.
- `provider-ingestion`: Add typed URL targets, operation-specific capabilities, bounded careers resolution, complete list/get evidence, all ten built-in list hooks, and explicit unlisted behavior.
- `storage-export`: Add opt-in `--save` (default ephemeral), a separate audit domain, deterministic non-catalog identities, atomic membership-scoped application, point-get non-closure, and stable structured raw evidence.
- `cache`: Reuse the shared cache with pull-specific deterministic identity, refresh behavior, stale visibility, and independence from operational persistence.
- `plugins`: Add explicit validated URL-pull registrations and observable conflicts without inferring support from legacy hooks.
- `performance-observability`: Add bounded shared transport execution, response-size and discovery budgets, and strict stdout/stderr isolation.

## Impact

- New typed contracts and services under `src/openopps/` for pull models, provider URL operations, resolution, orchestration, and output.
- Additive provider registry/plugin metadata plus targeted changes to the ten built-in board-provider modules. Existing `BoardJobProvider.fetch_jobs()` and `JobFetchResult` remain the current synchronization contract.
- Public Typer changes in `src/openopps/cli.py`, semantic help coverage, and a root-group URL dispatch helper. Existing `jobs sync`, `jobs list`, `jobs show`, `jobs history`, and `jobs export` retain their meanings.
- Shared HTTP/settings/cache changes for bounded body handling and pull request identity. No second URL-pull HTTP or cache stack is introduced.
- After the storage join, models, Alembic `0005` then `0006`, atomic storage APIs, update-snapshot copy surfaces, and migration tests. Further revisions are not assigned from this change.
- README, CLI/provider/operations/configuration/data-model/contributor docs, plugin example, and applicable nested `AGENTS.md` updates. Justfile or GitHub Actions changes are made together only if validation surfaces actually change.
- No scouting, source admission, catalog promotion, hosted service, browser/TUI workflow, authenticated ATS API, live publication, deployment, commit, or push is part of this change.

## Acceptance summary

1. Both CLI spellings select the same operation and renderer, existing commands retain their meanings, and machine stdout remains parseable under warnings, quiet, and verbosity settings.
2. Native URLs resolve first; careers resolution is one-page, non-recursive, public-HTTPS-safe, budgeted, explainable, and isolated from source discovery and catalogs.
3. All ten built-ins truthfully declare and pass full-board URL-list contracts. Exact-posting results use a supported native operation or exactly one match from a complete authoritative board result.
4. Membership authority, detail coverage, interface stability, unlisted behavior, cache/stale use, provenance, and failure kind are independently observable; unsupported or incomplete work never looks successful.
5. `--no-save` changes no operational table. Saved list pulls apply atomically and may reconcile only their eligible membership scope; point gets persist one posting and never create or impersonate a route snapshot.
6. Schema-dependent work landed as Alembic `0005_update_snapshot_ledger` then `0006_url_pull_runs`. Live head is `0006_url_pull_runs`. Persistence remains opt-in `--save`.
7. Every accepted goal fact maps to passing automated proof. Focused Python, migration, CLI, provider, storage, docs, strict OpenSpec, and full repository CI evidence is reported by layer; mocked tests are not described as live upstream proof.
