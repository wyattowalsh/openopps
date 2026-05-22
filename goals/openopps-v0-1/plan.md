## Solution Approach

Make OpenOpps v0.1 the first public ground-truth release of a polished local-first CLI: keep the proven source, provider, storage, export, and sync internals, redesign the visible command surface around the everyday user journey, add a robust caching layer, add richer source and board metadata, build a researched plugin system as a core extension architecture, and move low-level maintenance operations behind clearly marked advanced/admin/debug command surfaces. Do not include a TUI in v0.1. Optimize implementation for massively parallel subagent waves after the OpenSpec and shared model/interface contracts are frozen, with CLI, cache, plugins, examples, provider audit, docs, and validation progressing independently where file ownership allows.

## Research-Informed Choices

- Use Python package entry points for plugin discovery because `importlib.metadata.entry_points()` is the standard-library path for discovering installed distribution-provided entry points.
- Use Pluggy-style hookspec and hookimpl concepts, either by depending on `pluggy` or by implementing a very small equivalent, because validated hook signatures create clearer extension seams than arbitrary imports or monkey-patching.
- Prefer OpenOpps-owned dataclasses, protocols, Pydantic models, and registries around plugins so the package controls adapter contracts, error handling, caching boundaries, conflict reporting, and status output.
- Use a SQLite-backed cache owned by OpenOpps instead of opaque HTTP client magic so cached source pages, provider requests, route probes, metadata enrichment, freshness, invalidation, and diagnostics are visible and testable.
- Use Faker for realistic deterministic sample records and Hypothesis strategies for edge cases and invariants because examples should be coherent enough for demos while tests should probe malformed, partial, and high-volume data.
- Treat provider coverage percentages as persisted-data release artifacts, not estimates. Deterministic v0.1 validation uses seeded persisted data; representative live snapshot percentages are a post-v0.1 follow-up before publishing real-world percentages.

## Parallel Execution Map

- Wave 0 contract freeze: one lead owns OpenSpec, shared model/interface decisions, command names, cache key semantics, plugin hook names, coverage metric definitions, and example-data boundaries before implementation subagents start.
- Wave 1 independent builds: split subagent teams by file ownership into CLI regrouping, cache layer, plugin manager, generated examples, provider coverage audit, metadata enrichment, README outline, and docs outline.
- Wave 2 integration: merge through stable contracts into status/doctor, metrics, JSON cleanliness, storage/export parity, cache/plugin diagnostics, and provider coverage reporting.
- Wave 3 hardening: parallel test teams cover CLI/help, cache behavior, plugin behavior, provider/source regressions, examples/Hypothesis invariants, docs build, and fresh-clone smoke checks.
- Wave 4 release verification: one lead reconciles artifacts, docs, OpenSpec tasks, validation logs, deterministic provider coverage evidence, and release-readiness language.
- Parallel safety rule: subagents should not edit the same module concurrently; shared files such as `src/openopps/cli.py`, `src/openopps/models.py`, `src/openopps/storage.py`, README, and docs navigation need a lead-owned integration pass.
- Merge contract: every subagent returns changed files, tests run, uncovered risks, JSON-output implications, docs implications, and any OpenSpec task status changes before handoff.

## Useful Or Necessary v0.1 Features

- Cleaner CLI contract: necessary because this is the first public release and should define the intended product surface rather than preserve current internal command exposure.
- Intelligent cache: necessary because source sync, route probing, job fetching, and metadata enrichment can duplicate upstream traffic; caching should reduce latency and load while preserving explicit refresh semantics.
- Richer metadata: necessary because OpenOpps already preserves raw payloads; v0.1 should promote the useful parts into normalized fields for filtering, status, exports, and troubleshooting.
- Robust plugin system: necessary because provider/source coverage is the core product constraint; community developers need documented extension seams for adapters and diagnostics without editing the core package.
- Provider coverage audit: necessary because Ashby, Greenhouse, Lever, and Workday are strong baseline providers, but generic public ATS support for providers like SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, iCIMS, Jobvite, or JazzHR could materially improve startup-board coverage if implemented without bespoke per-company logic.
- Local `status` or `doctor` command: necessary because OpenOpps depends on local SQLite state, cache state, plugins, source/provider readiness, and live public endpoints.
- Offline-friendly examples: useful because live source/provider endpoints can be flaky; deterministic generated examples let users verify behavior and let tests assert invariants without network dependency.
- Next-step guidance for empty or partial results: necessary because empty board lists, missing route metadata, detect-only providers, stale cache, and no jobs can all be valid states.
- Consistent export recipes: useful because the strongest v0.1 value is analysis-ready data; users should quickly reach JSONL for audit, CSV for spreadsheets, and Parquet for analytics.

## Ordered Steps

1. Define the v0.1 CLI, cache, metadata, plugin, provider-coverage, and example-data contract in OpenSpec before changing code.
   - Touches: `openspec/changes/<new-v0-1-release-change>/proposal.md`, `openspec/changes/<new-v0-1-release-change>/design.md`, `openspec/changes/<new-v0-1-release-change>/tasks.md`, `openspec/changes/<new-v0-1-release-change>/specs/cli-domain/spec.md`, `openspec/changes/<new-v0-1-release-change>/specs/storage-export/spec.md`, and likely new specs for plugins and caching.
   - Include requirements for the stable user-facing journey, advanced command placement, JSON cleanliness, dry-run/apply semantics, cache freshness/invalidation, metadata promotion, plugin discovery/hooks/conflicts/failure isolation, provider coverage percentage definitions, generated examples, status/doctor output, and docs alignment.
   - Define the provider coverage denominator as distinct persisted boards in the report scope, and define primary numerator as distinct boards with any non-supported provider hint.
   - Verification: prefer the repo-local OpenSpec workflow such as `uv run wagents openspec ... --format json` when available, then run strict validation for the new change.

2. Update repo-local instructions to match the new ground-truth v0.1 contract.
   - Touches: `src/openopps/AGENTS.md` and possibly root `AGENTS.md` if validation commands or release expectations change.
   - Replace the current hard rule that all public nouns are `sources`, `boards`, `jobs`, `providers`, and `db` with a v0.1 rule that distinguishes stable user-facing commands from advanced/admin/debug commands.
   - State that v0.1 is the first public baseline, so obsolete internal command paths do not require compatibility aliases.
   - Verification: inspect `src/openopps/AGENTS.md` and confirm it no longer conflicts with the approved OpenSpec change.

3. Audit the current CLI commands and classify each command as stable user-facing or advanced.
   - Touches: `src/openopps/cli.py` and `tests/integration/openopps/test_cli.py` during implementation.
   - Stable user-facing commands should cover source discovery, board listing/inspection/export, route readiness/coverage/health, job sync/list/show/export, plugins inspection, cache inspection, and local status.
   - Advanced commands should include manual source creation, source adapter sampling, manual board creation, manual provider-route attachment, one-off provider detection, adapter explanation, route registry inspection, route probing internals, board refresh, cache maintenance, and database maintenance.
   - Verification: add or update CLI help tests that assert stable help emphasizes the everyday journey and advanced help contains the low-level operations.

4. Redesign the Typer command structure with the smallest safe code change.
   - Touches: `src/openopps/cli.py`.
   - Keep existing implementation functions where possible, but reattach commands to the new stable or advanced Typer groups instead of rewriting business logic.
   - Candidate stable surface: `sources list`, `sources sync`, `boards list`, `boards show`, `boards export`, `jobs sync`, `jobs list`, `jobs show`, `jobs export`, `providers coverage`, `providers health`, `plugins list`, `cache status`, `status` or `doctor`.
   - Candidate advanced surface: `admin sources add`, `admin sources test`, `admin boards add`, `admin boards add-provider`, `admin boards detect-provider`, `admin boards refresh`, `admin providers list`, `admin providers detect`, `admin providers explain`, `admin providers probe-routes`, `admin providers registry`, `admin cache purge`, `admin cache refresh`, `admin db init`, `admin db status`, and `admin db vacuum`.
   - Do not keep old low-level command aliases for v0.1 unless a later approved release-compatibility requirement introduces them.
   - Verification: run targeted help and command tests with `uv run pytest tests/integration/openopps/test_cli.py -q`.

5. Design and implement the robust v0.1 plugin architecture.
   - Touches: `pyproject.toml`, a likely new `src/openopps/plugins.py` or `src/openopps/plugins/` package, `src/openopps/providers/`, `src/openopps/cli.py`, tests, README, and docs.
   - Use a documented entry point group such as `openopps.plugins` for discovery, reading distribution name/version through `importlib.metadata` where available.
   - Define OpenOpps-owned plugin models such as `PluginMetadata`, `PluginCapability`, `PluginLoadResult`, `PluginConflict`, and `PluginContext`.
   - Define validated hooks or protocols for source adapter registration, job-provider adapter registration, route detector registration, metadata enricher registration, cache policy registration, export contributor registration, and CLI command registration.
   - Version hookspecs explicitly so future releases can introduce new hooks without silently changing v0.1 hook behavior.
   - Define hook ordering, first-result versus multi-result behavior, capability namespace rules, plugin CLI command namespace policy, and conflict resolution before writing plugin examples.
   - Prefer a Pluggy-backed manager if it materially simplifies hookspec validation, hook ordering, tracing, and entry-point loading; otherwise implement the minimal manager directly on top of `importlib.metadata.entry_points()` and explicit protocol validation.
   - Keep plugins inside OpenOpps boundaries: plugins receive settings, HTTP/cache helpers, model constructors, and registries, not arbitrary storage internals or global mutable state.
   - Load plugins non-fatally and record every load error, validation error, conflict, blocked plugin, duplicate capability, and registration warning for `status`/`doctor` and `plugins list`.
   - Support deterministic disabling or allow-listing of plugins through config or environment so users can isolate failures.
   - Document that Python plugins execute normal installed Python code and are not sandboxed by OpenOpps.
   - Include a packaged example plugin or template with a minimal `pyproject.toml` entry point and at least one source/provider-style hook.
   - Verification: add tests for entry-point discovery, metadata extraction, hook/protocol validation, successful adapter registration, route detector registration, metadata enricher registration, cache policy registration, CLI command registration, plugin disabling, duplicate capability conflicts, import-time failure isolation, and JSON-safe plugin status output.

6. Add an intelligent SQLite-backed cache layer that stays simple and observable.
   - Touches: likely new `src/openopps/cache.py`, `src/openopps/storage.py`, `src/openopps/http.py`, `src/openopps/ingest.py`, `src/openopps/route_probe.py`, `src/openopps/health.py`, provider adapters, CLI tests, and storage tests.
   - Create cache records with deterministic keys derived from method, normalized URL, provider/source/route identity, relevant query/body parameters, schema version, and cache namespace.
   - Store status code, selected headers, ETag, Last-Modified, content hash, fetched timestamp, expires timestamp, stale-on-error flag, request duration, and payload bytes or JSON in SQLite.
   - Define the cache schema migration path, canonical key algorithm, namespace isolation guarantees, transaction/locking behavior for concurrent syncs, payload size limits, and eviction or purge policy before wiring providers through the cache.
   - Support conditional requests with `If-None-Match` and `If-Modified-Since` when upstream metadata exists.
   - Support explicit `--refresh` or equivalent bypass semantics so user-initiated refreshes are never hidden by cache hits.
   - Support stale-on-error for safe read paths so transient upstream failures can return known data with clear stale warnings when configured.
   - Dedupe in-flight duplicate provider requests during one sync run before consulting or writing persistent cache.
   - Keep cache policy small: default TTLs by namespace, plugin-contributed overrides through validated cache policy hooks, cache size/status inspection, `cache status`, `cache inspect`, explicit purge controls, and explicit refresh controls.
   - Verification: add tests for deterministic keying, TTL expiry, explicit refresh bypass, conditional request headers, 304 reuse, stale-on-error warnings, namespace isolation, duplicate in-flight suppression, JSON output silence, and cache metrics.

7. Expand source, board, route, and job metadata capture without turning v0.1 into a scraping project.
   - Touches: `src/openopps/models.py`, `src/openopps/providers/sources/`, `src/openopps/providers/boards/`, `src/openopps/storage.py`, `src/openopps/export.py`, `src/openopps/cli.py`, and tests.
   - Preserve full upstream source metadata in `SourceRecord.raw_metadata`, full company or board payloads in `BoardRecord.raw_payload`, full provider-route payloads in `BoardProviderRecord.raw_payload`, and full job payloads in `JobRecord.raw_payload` where available.
   - Promote high-value cross-source fields into normalized models when available: source collection IDs, page totals, sync cursors, source health, board website, domain, description, markets, locations, staff count, job count hints, funding or cohort tags, provider labels, route job counts, route URLs, route tokens, route status, job compensation, departments, teams, employment type, remote level, and posting timestamps.
   - Add an automatic enrichment path that updates existing boards from source payloads, provider route pages, and job sync payloads, while avoiding broad bespoke company website scraping for v0.1.
   - Ensure `boards show`, `boards list`, exports, `status`/`doctor`, and cache/plugin diagnostics expose useful normalized metadata without requiring raw JSON inspection.
   - Verification: add tests that seed partial board metadata, run a sync or enrichment path, assert normalized fields are promoted, assert raw payloads remain intact, and assert list/export filters continue to match storage semantics.

8. Run a provider coverage gap audit and only add extra job-fetching providers if they are high-coverage and generic.
   - Touches: `src/openopps/providers/boards/`, `src/openopps/route_probe.py`, `src/openopps/route_registry.py`, `src/openopps/providers/registry.py`, provider tests, README, and docs if new providers are adopted.
   - Treat Ashby, Greenhouse, Lever, and Workday as the baseline v0.1 job-capable providers.
   - Audit candidate public ATS providers that may significantly improve route coverage without bespoke per-company adapters: SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, iCIMS, Jobvite, and JazzHR.
   - Compute board-level percentages from persisted source snapshots: total boards, boards with provider hints, boards with baseline job-capable providers, boards with adopted v0.1 providers, boards with any non-supported provider hints, boards with only non-supported provider hints, boards with detect-only providers, boards with unsupported or unknown providers, and boards missing executable route metadata.
   - Add coverage report fields such as `boards.withNonSupportedProviderHints`, `boards.withOnlyNonSupportedProviderHints`, `boards.nonSupportedProviderCoverage.percentage`, `routes.nonSupportedTotal`, and `routes.nonSupportedByProvider`.
   - Publish deterministic persisted-data source set, denominator, numerator, percentage, examples, and candidate-provider evidence in README/docs. Publish representative live snapshot dates and real-world percentages only after a post-v0.1 live-source snapshot exists.
   - Promote a candidate to v0.1 job-fetching support only when a generic route detector and public job-fetch implementation can be derived from hosted-board URLs, public JSON endpoints, or stable embedded payloads.
   - Keep candidates as detect-only metadata when fetching would require authenticated APIs, brittle browser scraping, custom per-company rules, or unclear public endpoint stability.
   - Record do-not-adopt rationale for every rejected candidate so future provider work starts from evidence instead of rediscovery.
   - Verification: add a route-fixture audit summary, provider unit tests for every adopted provider, route-probe tests for detection and dry-run/apply behavior, and coverage reporting that distinguishes baseline, adopted, detect-only, unsupported/unknown, missing-route, and only-non-supported boards.

9. Add the v0.1 status/doctor path.
   - Touches: `src/openopps/cli.py`, `src/openopps/storage.py`, `src/openopps/coverage.py`, the plugin manager, the cache layer, and possibly a new `src/openopps/doctor.py`.
   - Report database URL/path, source count, board count, board-provider route count, job count, cache status, cache freshness, plugin count, plugin failures, executable route count, missing route metadata count, detect-only provider count, and suggested next action.
   - Support JSON output for automation and human output for quick diagnosis.
   - Verification: add tests for empty DB status, seeded DB status, cache status, plugin status, and JSON parseability.

10. Add generated examples and deterministic smoke paths.

- Touches: likely new `src/openopps/examples.py` or `src/openopps/fixtures.py`, `tests/fixtures/`, CLI commands, docs, and storage helpers.
- Define typed example dataclasses or factories for sources, boards, provider routes, jobs, plugin metadata, cache records, and raw upstream payloads.
- Choose explicit user-facing commands such as `examples seed`, `examples reset`, and `examples export`, or document a smaller command shape if implementation finds a better CLI fit.
- Use Faker with deterministic seeds to generate realistic demo content for docs and CLI smoke paths.
- Use Hypothesis strategies to generate edge cases for storage upserts, filter parity, export shape, cache keying, plugin conflict handling, and provider payload preservation.
- Generate docs snippets or golden outputs from the example path so README/docs examples do not drift from executable behavior.
- Keep generated demo data obviously synthetic and separate from real synced records unless the user explicitly imports it.
- Verification: add tests that seed a temporary SQLite database with generated examples, list/filter/export jobs deterministically, and run Hypothesis-backed invariants with bounded examples suitable for CI.

11. Preserve JSON cleanliness and dry-run/apply safety while moving commands and adding plugins/cache.

- Touches: `src/openopps/cli.py`, `src/openopps/route_probe.py`, `src/openopps/health.py`, plugin loader, cache layer, and existing tests as needed.
- Ensure intro animation and human tables never pollute JSON output.
- Ensure provider route probing and provider health remain read-only unless an explicit apply-style option is passed.
- Ensure plugin registration, cache warnings, and stale-on-error messages cannot pollute JSON output with import-time logging or decorative terminal output.
- Verification: keep or add tests for `--json` parseability, `--no-intro`, `probe-routes` default dry-run behavior, `health` default dry-run behavior, plugin loader silence in JSON mode, and cache warning structure in JSON mode.

12. Tighten user-facing errors, next-step guidance, and metrics where current command behavior leaks internals.

- Touches: `src/openopps/cli.py`, `src/openopps/ingest.py`, `src/openopps/metrics.py`, `src/openopps/route_probe.py`, `src/openopps/health.py`, cache layer, and plugin manager as needed.
- Convert uncaught implementation exceptions for common user mistakes into actionable Typer errors.
- Add next-step messages for empty databases, empty filters, missing route metadata, detect-only provider hints, unsupported providers, stale cache, plugin failures, and live-network failures.
- Keep metrics fields for elapsed time, boards, jobs, pages, skipped items, duplicate route skips, cache hits, cache misses, stale cache uses, plugin loads, plugin failures, and provider/source error counts.
- Verification: add focused tests for unknown source, unknown board, unsupported provider, missing route metadata, stale cache warning, plugin load failure, and empty database cases.

13. Verify storage, filters, exports, cache, plugins, and normalized data remain stable after CLI reshaping.

- Touches: `src/openopps/storage.py`, `src/openopps/export.py`, `src/openopps/models.py`, cache/plugin modules, and tests only if CLI changes expose gaps.
- Keep list/export filter parity for boards and jobs.
- Keep raw provider payload preservation and normalized enrichment fields in exports.
- Keep plugin-provided adapters and built-in adapters flowing through the same storage/export boundaries.
- Verification: `uv run pytest tests/integration/openopps/test_storage_export.py tests/unit/openopps/test_job_enrichment.py tests/integration/openopps/test_cli.py -q` plus cache/plugin/example tests.

14. Run provider/source regression coverage before docs are finalized.

- Touches: provider code only if tests reveal regressions: `src/openopps/providers/sources/`, `src/openopps/providers/boards/`, `src/openopps/providers/registry.py`, `src/openopps/route_select.py`, and `src/openopps/route_registry.py`.
- Confirm Ashby, Greenhouse, Lever, and Workday remain the baseline v0.1 job-capable providers.
- Confirm any added provider from the coverage audit has generic public fetching and meaningful coverage impact.
- Confirm Teamtailor, Manatal, Gem, and other candidates remain detect-only metadata unless reliable public fetching has already landed or the audit justifies adoption.
- Verification: `uv run pytest tests/unit/openopps/test_providers.py tests/integration/openopps/test_sources.py tests/unit/openopps/test_workday.py tests/unit/openopps/test_route_probe.py tests/unit/openopps/test_registry.py tests/unit/openopps/test_health.py tests/unit/openopps/test_coverage.py -q` plus adopted provider tests.

15. Write a release acceptance matrix before final docs polish.

- Touches: `README.md`, docs, OpenSpec tasks, or a release note/checklist file if the repo has one.
  - Cover CLI command surface, cache behavior, plugin behavior, generated examples, deterministic provider coverage evidence, storage/export parity, JSON output, docs, fresh-clone quickstart, full tests, OpenSpec validation, and release smoke commands.
- Verification: every acceptance row has an owner, command or evidence artifact, and pass/fail result before the goal is marked complete.

16. Rewrite the README around the v0.1 happy path.

- Touches: `README.md`.
- Lead with the value proposition, install, one clean quickstart, stable command surface, status/doctor path, cache behavior, generated examples, plugin extension story, metadata model, provider support matrix, deterministic provider audit results, storage/export explanation, troubleshooting, and validation commands.
- Move advanced command examples out of the primary path and label them as advanced/admin/debug.
- Verification: manually run every README quickstart command that is deterministic locally; for live network examples, run a small representative sample or mark them as live-network examples.

17. Update the Fumadocs docs site to match README and the redesigned CLI.

- Touches: `docs/content/docs/index.mdx`, `docs/content/docs/cli-reference.mdx`, `docs/content/docs/providers.mdx`, `docs/content/docs/operations.mdx`, `docs/content/docs/configuration.mdx`, likely cache, metadata/data-model, plugin-development, generated examples, provider coverage audit, troubleshooting/doctor pages, and `docs/content/docs/meta.json` if navigation changes.
- Fix existing release-language drift such as docs that say `V1` when the target is v0.1.
- Keep docs examples runnable from the repository root unless they explicitly start with `cd docs`.
- Verification: from `docs/`, run `pnpm types:check` and `pnpm build`.

18. Run full release validation and smoke checks.

- Touches: no files unless validation reveals failures.
- Run `uv run pytest`.
- Run representative CLI smoke checks against a temporary SQLite database, including help output, status/doctor, plugin list/loader inspection, cache status, generated example seeding, source list, board metadata display, board list on an empty DB, job list on an empty DB, JSON output parsing, and at least one small live source/provider sample if network access is acceptable.
- Verification: record the exact commands and outcomes in the implementation summary or release notes.

19. Finalize v0.1 release readiness language.

- Touches: `pyproject.toml`, README, docs, and release notes only if wording or version metadata is inconsistent.
- Keep `version = "0.1.0"` unless the implementation discovers a concrete need to change it.
- Treat v0.1 as the first public baseline for CLI behavior, cache semantics, documented plugin hooks, persisted local data behavior, and export formats.
- Verification: inspect `pyproject.toml`, README, docs, and release notes for consistent `v0.1` language.

## Risks And Open Questions

- TUI is explicitly out of scope for v0.1; do not add Textual, Rich prompt flows, or TUI docs as part of this goal.
- Because v0.1 is the first public ground-truth release, moving current commands is acceptable; use git, PyPI releases, GitHub releases, and release notes to manage future changes instead of compatibility aliases.
- Plugin APIs can become a central product surface immediately; design them carefully with documented hooks, typed contexts, validation, failure isolation, and thorough tests rather than labeling them as throwaway experimental internals.
- Plugin entry points execute arbitrary installed Python code; load plugins non-fatally, surface failures clearly, support deterministic disabling, avoid giving plugins unrestricted access to storage internals, and do not imply sandboxing in docs.
- Cache correctness is subtle; keep the design simple, make keys deterministic, make freshness observable, preserve explicit refresh semantics, and test stale/error behavior carefully.
- Cache schema or invalidation bugs can silently skew user analysis; require namespace isolation tests, explicit refresh behavior, and visible cache freshness in status/doctor output.
- More metadata can increase schema churn; prefer existing raw metadata/payload preservation plus small normalized fields that clearly improve filtering, display, export, or diagnostics.
- Automatic metadata enrichment can become bespoke scraping; limit v0.1 enrichment to source payloads, provider route pages, and job payloads with generic extraction paths.
- Adding too many providers can dilute reliability; adopt only high-coverage providers with generic public routes and keep the rest detect-only with clear coverage reporting.
- Real-world provider coverage percentages can become stale; publish snapshot date, source set, denominator, and numerator with any post-v0.1 live result.
- Massive parallel implementation can create interface drift; freeze OpenSpec, model contracts, command names, hook specs, and cache key semantics before parallel subagent waves edit code.
- Generated example data must be realistic enough to teach the product but obviously synthetic enough that users do not confuse it with real synced opportunities.
- Live source/provider checks may be flaky because upstream public endpoints can change or rate-limit; keep tests deterministic and reserve live checks for smoke validation.
- Docs must avoid promising v1.0 stability while still giving users confidence that v0.1 CLI, cache, plugin, storage, and export behavior are the intended first public baseline.
