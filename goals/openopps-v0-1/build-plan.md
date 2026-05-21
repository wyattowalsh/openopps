# OpenOpps v0.1 Subagent-Optimized Build Plan

## Purpose

Execute `goals/openopps-v0-1/goal.md` with maximum safe parallelism while preserving the approved constraints in `facts.md` and `plan.md`.

The build target is a polished CLI-only v0.1 release. Do not add TUI, Textual, interactive prompt flows, browser UI, or web UI behavior.

## Operating Model

Use a lead-plus-subagents workflow.

- The lead owns sequencing, conflict control, OpenSpec integration, shared interface decisions, final merges, and final validation.
- Subagents own independent file lanes and return patches, findings, validation output, and risks.
- No implementation subagent starts until the OpenSpec contract freezes command names, cache semantics, plugin hooks, provider coverage metrics, metadata fields, example-data contracts, and status/doctor output.
- No two subagents edit the same source file in the same wave.
- Shared files are integrated by the lead or a single assigned integration subagent.
- Do not create branches, worktrees, or commits unless the user explicitly approves that workflow.
- If a team/worktree workflow is explicitly approved later, use Pattern E: one lead, domain teammates, and nested read-only or test subagents inside each domain.

## Source Of Truth

- Goal: `goals/openopps-v0-1/goal.md`
- Approved facts: `goals/openopps-v0-1/facts.md`
- Approved plan: `goals/openopps-v0-1/plan.md`
- Current package instructions: `AGENTS.md`, `src/openopps/AGENTS.md`, `docs/AGENTS.md`
- Validation commands: `uv run pytest`, `cd docs && pnpm types:check`, `cd docs && pnpm build`

## Critical Constraints

- v0.1 is the first public ground-truth release; obsolete internal command paths do not need compatibility aliases.
- CLI behavior, persisted local data behavior, documented plugin hooks, plugin metadata contracts, cache semantics, and export formats are the supported v0.1 surface.
- Cache correctness must be observable and must not hide explicit refreshes.
- Plugin entry points execute normal installed Python code; docs must not imply sandboxing.
- Provider coverage percentages must be measured from representative persisted source snapshots, not estimated.
- Tests must stay deterministic; reserve live provider checks for explicit smoke validation.
- JSON output must remain parseable and free of decorative output.

## Phase 0: Contract Freeze

This phase is mostly sequential because it defines the interfaces all later subagents depend on.

### Wave 0A: Parallel Read-Only Contract Inputs

Dispatch these read-only subagents in one wave.

| Subagent              | Scope                                                                               | Output                                                                        |
| --------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| CLI contract scout    | `src/openopps/cli.py`, `tests/test_cli.py`, README CLI examples                     | Stable/admin command map, mutation safety notes, JSON risk list               |
| Cache contract scout  | `src/openopps/http.py`, `storage.py`, `ingest.py`, `route_probe.py`, `health.py`    | Cache key fields, cache table shape, refresh/stale policy, integration seams  |
| Plugin contract scout | `providers/`, `route_select.py`, `route_registry.py`, `models.py`, `pyproject.toml` | Hook list, entry-point group, conflict rules, plugin context boundary         |
| Provider audit scout  | `coverage.py`, `health.py`, provider registry, tests                                | Board-level coverage denominator/numerators and candidate audit method        |
| Examples scout        | current fixtures/tests/docs                                                         | Example dataclasses, Faker/Hypothesis strategy boundaries, golden output plan |
| Docs/spec scout       | `openspec/`, `docs/`, `README.md`                                                   | v0.1 language drift, docs page map, OpenSpec spec split                       |

Accounting gate: all six subagents must return before the lead writes OpenSpec.

### Wave 0B: OpenSpec Authoring

Single owner writes the new v0.1 OpenSpec change.

Files owned:

- `openspec/changes/<v0-1-release>/proposal.md`
- `openspec/changes/<v0-1-release>/design.md`
- `openspec/changes/<v0-1-release>/tasks.md`
- `openspec/changes/<v0-1-release>/specs/cli-domain/spec.md`
- `openspec/changes/<v0-1-release>/specs/storage-export/spec.md`
- `openspec/changes/<v0-1-release>/specs/cache/spec.md`
- `openspec/changes/<v0-1-release>/specs/plugins/spec.md`
- `openspec/changes/<v0-1-release>/specs/provider-coverage/spec.md`
- `openspec/changes/<v0-1-release>/specs/examples/spec.md`

Contract decisions to freeze:

- Stable CLI surface and admin/debug surface.
- Status versus doctor command naming.
- Cache key algorithm, table fields, TTL defaults, refresh bypass, stale-on-error behavior, cache inspection commands.
- Plugin entry-point group, hook names, hook ordering, hook versioning, plugin metadata fields, conflict policy, disable/allow-list behavior.
- Provider coverage denominator and numerators.
- Metadata promotion fields and raw payload preservation boundaries.
- Example command names and generated fixture boundaries.
- JSON output guarantees and dry-run/apply guarantees.

Gate commands:

- `uv run wagents openspec ... --format json` if repo-local workflow is available.
- Strict OpenSpec validation for the new change.

Do not start implementation until this gate passes.

## Phase 1: Independent Build Lanes

After OpenSpec approval, dispatch implementation subagents by non-overlapping ownership. Each lane writes tests with its code and reports exact validation commands.

### Lane A: CLI Surface

Primary files:

- `src/openopps/cli.py`
- `tests/test_cli.py`
- `src/openopps/AGENTS.md`

Responsibilities:

- Regroup stable commands around everyday workflow.
- Move low-level operations behind admin/debug surfaces.
- Add `status` or `doctor` command shell if contract requires it.
- Wire `plugins list`, `cache status`, and example commands only after those modules expose stable interfaces.
- Preserve JSON cleanliness and dry-run/apply semantics.
- Remove or demote old public exposure without compatibility aliases.

Avoid editing:

- `storage.py`, `models.py`, `providers/**`, `route_probe.py`, `health.py`, `coverage.py`, docs pages.

Validation:

- `uv run pytest tests/test_cli.py`
- JSON parse smoke checks for all new `--json` outputs.

### Lane B: Cache Core

Primary files:

- `src/openopps/cache.py`
- `src/openopps/http.py`
- `tests/test_http.py`
- cache-focused tests under `tests/` as needed

Responsibilities:

- Implement deterministic cache keys from method, normalized URL, query/body, namespace, schema version, provider/source/route identity, and response-affecting headers.
- Store status code, selected headers, ETag, Last-Modified, content hash, fetched timestamp, expiry, stale-on-error eligibility, request duration, and payload.
- Add TTL expiry, explicit refresh bypass, conditional request reuse, stale-on-error, namespace isolation, and metrics.
- Avoid holding SQLite write locks during network awaits.
- Keep cache output silent unless the caller asks for diagnostics.

Avoid editing:

- `cli.py` except through a lead-owned integration pass.
- `providers/**` except after cache wrapper contract is stable.

Validation:

- `uv run pytest tests/test_http.py`
- Targeted cache tests for TTL, refresh, conditional requests, 304 reuse, stale-on-error, namespace isolation, duplicate suppression, and JSON silence.

### Lane C: Plugin Core

Primary files:

- `src/openopps/plugins.py` or `src/openopps/plugins/`
- `tests/test_plugins.py`
- plugin-related pyproject metadata only if contract requires a dependency or entry-point example

Responsibilities:

- Discover plugins through a documented entry-point group.
- Define `PluginMetadata`, `PluginCapability`, `PluginLoadResult`, `PluginConflict`, `PluginContext`, hookspec version, and hook validation.
- Support source adapters, job-provider adapters, route detectors, metadata enrichers, cache policy contributors, export contributors, and CLI command contributors through documented seams.
- Record import failures, validation errors, duplicate capability conflicts, disabled plugins, and warnings without breaking built-ins.
- Support deterministic disabling or allow-listing.
- Document that plugins are not sandboxed.

Avoid editing:

- Provider static registries until the integration wave.
- `cli.py` until `plugins list` integration.

Validation:

- `uv run pytest tests/test_plugins.py`
- Tests monkeypatch entry points; do not depend on installed local packages.

### Lane D: Provider Registry And Coverage Audit

Primary files:

- `src/openopps/coverage.py`
- `src/openopps/providers/registry.py`
- `src/openopps/providers/boards/**` only for adopted generic providers
- `tests/test_coverage.py`
- provider-specific tests for any adopted provider

Responsibilities:

- Add board-level non-supported provider metrics.
- Define denominator as distinct persisted boards in report scope.
- Define primary numerator as distinct boards with any non-supported provider hint.
- Add secondary metrics for only-non-supported boards, detect-only boards, unsupported/unknown boards, missing executable route metadata, and non-supported routes by provider.
- Audit SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, iCIMS, Jobvite, and JazzHR.
- Adopt a candidate only if generic public route discovery and job fetching are reliable.
- Record do-not-adopt rationale for rejected candidates.

Avoid editing:

- `cli.py` except after coverage report fields are stable.
- README/docs until measured results exist.

Validation:

- `uv run pytest tests/test_coverage.py`
- `uv run pytest tests/test_providers.py tests/test_route_probe.py tests/test_registry.py tests/test_health.py`

### Lane E: Metadata Enrichment

Primary files:

- `src/openopps/models.py`
- `src/openopps/storage.py`
- `src/openopps/export.py`
- source/provider adapters only where metadata is promoted
- metadata-focused tests

Responsibilities:

- Preserve source, board, route, and job raw payloads.
- Promote useful source, board, route, and job metadata into normalized fields.
- Add automatic enrichment from source payloads, provider route pages, and job sync payloads.
- Avoid bespoke company website scraping.
- Preserve list/export filter parity.

Avoid editing:

- `cli.py` display changes until model/storage fields are stable.
- cache/plugin internals.

Validation:

- `uv run pytest tests/test_storage_export.py tests/test_job_enrichment.py`
- Additional tests for partial metadata enrichment and raw payload preservation.

### Lane F: Generated Examples

Primary files:

- `src/openopps/examples.py` or `src/openopps/fixtures.py`
- `tests/test_examples.py`
- `tests/fixtures/` if needed

Responsibilities:

- Add typed dataclasses or factories for sources, boards, routes, jobs, plugin metadata, cache records, and raw upstream payloads.
- Use deterministic Faker seeds for realistic sample data.
- Use bounded Hypothesis strategies for storage, filters, exports, cache keys, plugin conflicts, and payload preservation.
- Add user-facing example commands such as `examples seed`, `examples reset`, and `examples export` if approved by OpenSpec.
- Generate reproducible golden output snippets for README/docs.

Avoid editing:

- `cli.py` until example APIs are stable.
- docs until golden output is generated.

Validation:

- `uv run pytest tests/test_examples.py`
- Bounded Hypothesis runs suitable for CI.

### Lane G: Docs Outline And Drift Cleanup

Primary files after contracts freeze:

- `README.md`
- `docs/content/docs/index.mdx`
- `docs/content/docs/cli-reference.mdx`
- `docs/content/docs/providers.mdx`
- `docs/content/docs/operations.mdx`
- `docs/content/docs/configuration.mdx`
- new docs pages for cache, plugins, generated examples, provider coverage audit, metadata/data model, troubleshooting/doctor
- `docs/content/docs/meta.json` only by the docs navigation owner

Responsibilities:

- Replace v1 language with v0.1 language.
- Rewrite docs around the happy path.
- Keep advanced/admin/debug commands documented but not primary.
- Add cache behavior, plugin development, example data, provider coverage audit, metadata model, storage/export, and troubleshooting docs.
- Publish measured provider coverage percentages with snapshot date, source set, denominator, numerator, examples, and candidate deltas.

Avoid editing:

- Code files.
- `meta.json` unless assigned as docs navigation owner.

Validation:

- `cd docs && pnpm types:check`
- `cd docs && pnpm build`

## Phase 2: Integration Wave

Use one lead-owned integration wave after Phase 1 lanes complete.

Integration tasks:

- Wire cache policy through source sync, job sync, route probing, and health according to OpenSpec.
- Wire plugin manager into built-in provider/source registries without breaking current built-ins.
- Wire plugin and cache diagnostics into `status` or `doctor`.
- Wire coverage metrics into CLI output and docs artifacts.
- Wire generated examples into CLI and docs snippets.
- Update README and docs with actual command names and measured coverage results.
- Reconcile `src/openopps/AGENTS.md` with the final command surface.

Shared files that require single-owner integration:

- `src/openopps/cli.py`
- `src/openopps/models.py`
- `src/openopps/storage.py`
- `src/openopps/providers/registry.py`
- `src/openopps/providers/sources/__init__.py`
- `src/openopps/providers/boards/__init__.py`
- `src/openopps/route_probe.py`
- `src/openopps/route_select.py`
- `README.md`
- `docs/content/docs/meta.json`
- OpenSpec `tasks.md`

Integration gate:

- `uv run pytest tests/test_cli.py tests/test_http.py tests/test_plugins.py tests/test_coverage.py tests/test_examples.py`
- JSON parse smoke checks for status, plugins, cache, coverage, boards, jobs, and examples.

## Phase 3: Hardening And Review

Dispatch independent verification subagents after the integration gate.

| Subagent                      | Scope                                                                   | Commands                                |
| ----------------------------- | ----------------------------------------------------------------------- | --------------------------------------- |
| CLI verifier                  | stable/admin help, dry-run/apply, JSON outputs                          | `uv run pytest tests/test_cli.py`       |
| Cache verifier                | keying, TTL, refresh, stale-on-error, concurrency risk                  | cache tests and targeted smoke commands |
| Plugin verifier               | entry-point monkeypatching, conflicts, disabling, failure isolation     | `uv run pytest tests/test_plugins.py`   |
| Provider verifier             | baseline providers, adopted candidates, route probing, health           | provider/route/health tests             |
| Storage/export verifier       | filter parity, raw payload preservation, metadata fields                | storage/export/job enrichment tests     |
| Examples verifier             | deterministic seeds, Hypothesis bounds, golden output drift             | examples tests                          |
| Docs verifier                 | README commands, docs typecheck/build, v0.1 language                    | docs validation commands                |
| Security/reliability reviewer | plugin non-sandboxing docs, cache stale risks, network failure handling | review report only                      |

Accounting gate: all verifier findings must be resolved, accepted as residual risk, or explicitly deferred before release validation.

## Phase 4: Release Validation

Run this as a single lead-owned release gate.

Required commands:

- `uv sync`
- `uv run pytest`
- strict OpenSpec validation for the v0.1 change
- `cd docs && pnpm types:check`
- `cd docs && pnpm build`

Required smoke checks:

- Fresh database status or doctor.
- Generated example seed/list/export path.
- Source discovery path against at least one representative source or deterministic fixture.
- Route readiness or coverage report.
- Job sync path for at least one supported provider or deterministic fixture.
- Cache status and explicit refresh behavior.
- Plugin list and plugin failure-isolation output.
- JSON parse checks for all machine-readable outputs.
- Provider coverage report with measured non-supported provider board percentages.

Required artifacts:

- Acceptance matrix with pass/fail status.
- Provider coverage snapshot with date, source set, denominator, numerator, percentages, examples, candidate deltas, and rejection rationales.
- Release summary with validation commands and outcomes.
- Docs pages and README matching the final command surface.

## Acceptance Matrix Template

| Area              | Acceptance Criterion                                                   | Owner Lane      | Evidence                     | Validation                            | Status      |
| ----------------- | ---------------------------------------------------------------------- | --------------- | ---------------------------- | ------------------------------------- | ----------- |
| OpenSpec          | v0.1 CLI/cache/plugin/provider/examples contracts are strict-validated | Contract        | OpenSpec change              | strict validation                     | Not started |
| CLI               | Stable commands cover happy path and internals are admin/debug         | CLI             | help tests and CLI reference | `uv run pytest tests/test_cli.py`     | Not started |
| JSON              | Machine-readable outputs parse cleanly                                 | CLI/integration | JSON smoke logs              | targeted parse checks                 | Not started |
| Cache             | TTL, refresh, stale-on-error, namespace isolation, metrics pass        | Cache           | cache tests                  | `uv run pytest tests/test_http.py`    | Not started |
| Plugins           | Discovery, validation, conflicts, disabling, failure isolation pass    | Plugin          | plugin tests/docs            | `uv run pytest tests/test_plugins.py` | Not started |
| Provider coverage | Non-supported provider board percentages are measured and published    | Provider audit  | coverage snapshot            | coverage tests and report             | Not started |
| Metadata          | Raw payloads preserved and normalized fields promoted                  | Metadata        | storage/export tests         | storage/export tests                  | Not started |
| Examples          | Deterministic examples seed, list, export, and docs snippets reproduce | Examples        | examples tests/golden output | examples tests                        | Not started |
| Docs              | README/docs match v0.1 surface and build                               | Docs            | docs pages                   | docs typecheck/build                  | Not started |
| Release           | Fresh clone quickstart works end-to-end                                | Lead            | release smoke log            | full validation                       | Not started |

## Subagent Prompt Template

Use this template for implementation lanes after the contract freeze:

```text
You are implementing Lane <name> for OpenOpps v0.1 in /Users/ww/dev/projects/openopps.

Source of truth:
- goals/openopps-v0-1/goal.md
- goals/openopps-v0-1/facts.md
- goals/openopps-v0-1/plan.md
- goals/openopps-v0-1/build-plan.md
- approved OpenSpec change: <path>

Hard constraints:
- CLI-only. Do not add TUI, Textual, prompt UI, browser UI, or web UI.
- Do not preserve obsolete internal command paths unless OpenSpec says so.
- Keep JSON outputs parseable and free of decorative output.
- Do not edit files outside your ownership lane without asking the lead.
- Add focused tests with every behavioral change.

Owned files:
- <list>

Avoid files:
- <list>

Acceptance criteria:
- <list>

Verification commands:
- <list>

Return:
- changed files
- tests run and outcomes
- unresolved risks
- JSON/docs/OpenSpec implications
- suggested follow-up integration work
```

## Recovery Rules

- If a subagent fails to return, re-spawn only that lane with the same ownership boundary.
- If two lanes need the same file, stop parallel work on that file and assign it to the integration lead.
- If OpenSpec contract ambiguity appears during implementation, stop the affected lane and update the contract before continuing.
- If cache or plugin behavior threatens JSON cleanliness, prioritize JSON tests before feature completion.
- If provider audit cannot produce a measured percentage because snapshots are unavailable, block provider-coverage docs until a representative persisted snapshot is generated.

## Recommended First Build Dispatch

After approving this build plan, start with Phase 0 Wave 0A read-only scouts, then write and validate the OpenSpec contract. Do not dispatch implementation subagents until the contract freeze gate passes.
