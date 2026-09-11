# expand-end-to-end-opportunity-coverage - tasks

Checked tasks require the named local proof. They do not authorize overlay JSON writes from URL pull, scout `--apply`, Alembic `0005` or `0006`, a shared `RunMetrics` envelope, Workers upload, Kaggle mutation, source-policy 1780 grants, hosted publish, commit, or push. Persistence/`url_pull_runs` remain owned by `unified-cli-job-pulls`. Four-stack metrics honesty remains owned by `cli-coverage-growth-observability`. Listing identity bind remains owned by `shared-board-listing-kernel`. v7 publication remains owned by `production-hardening-static-data-v7`.

G0 OpenSpec (T001–T004) is this package on `[writer: W-OS]`. Later gates wait on exclusive writers in `goals/expand-end-to-end-opportunity-coverage/task-graph.yaml`. Do not start two writers on `cli.py`. Do not import `openopps.discovery` from pull modules. G6 skip is first-class success. Tracked OpenSpec ticks after T004 require repository tests or commits — never ignored `goals/*` files.

## 0. G0 — OpenSpec contract `[writer: W-OS]`

- [x] T001 Proposal: successor coverage, five slices, no live publish, no shared RunMetrics.
- [x] T002 Design: versioned profiles, companion observations, admission vs field-promotion, exclusive lanes, G6 skip, mermaid/task graph. `[depends: T001]`
- [x] T003 Spec deltas for `provider-ingestion`, `provider-coverage`, `storage-export`, `cli-domain`, and `docs-product-boundary`. `[depends: T002]`
- [x] T004 `tasks.md` plus strict validate `expand-end-to-end-opportunity-coverage`. `[depends: T003]`

Proof:

```bash
rtk npx -y @fission-ai/openspec@1.6.0 validate expand-end-to-end-opportunity-coverage --strict
```

## 1. G0 — parallel red tests (implementation lanes; not this leaf)

- [x] T005 Red test: `indeed.com` and `glassdoor.com` are unsupported like LinkedIn/Wellfound. `[writer: W-POLICY]`
- [x] T006 Red test: literal ten ATS ids; capabilities match list/get hooks; Consider G0 had no get (G2 T038 now advertises honest board-scan get). `[writer: W-CAP]`
- [x] T007 Red test: JSON objects identify `profile`+`schemaVersion`; `core`/`search`/`full`/`raw` field sets. `[writer: W-PROFILES]`
- [x] T008 Red test: origin `provider_observed`\|`openopps_derived`\|`editorial`; no confidence required for observed. `[writer: W-OBS]`
- [x] T009 Red test: quality report schema; not `SyncMetrics`; not `PullTerminalObservability`. `[writer: W-QUALITY]`
- [x] T010 Red test: packaged overlay gain excludes url-pull and scout. `[writer: W-REPORT]`

## 2. G1 — deny-list and capability manifests

- [x] T020 Add Indeed/Glassdoor deny rationales in `source_scope.py`. `[writer: W-POLICY]` `[depends: T005]`
- [x] T021 Treat indeed/glassdoor hosts as `policy_blocked` in overlay outcomes. `[writer: W-OUTCOMES]` `[depends: T005]`
- [x] T022 Green capability manifest tests against current ten adapters; do not fake native get. `[writer: W-CAP]` `[depends: T006]`

Proof:

```bash
uv run pytest tests/unit/openopps/test_source_scope.py tests/unit/openopps/test_job_seeker_overlay_outcomes.py tests/unit/openopps/test_provider_capability_manifests.py -q --basetemp /private/tmp/openopps-e2e-g1
```

## 3. G2 — ten ATS deepen (Consider exact-get required)

- [x] T030 Greenhouse: listing completeness + advertised-count/duplicate-id fail-closed fixtures. `[writer: W-ATS-GH]` `[depends: T022]`
- [x] T031 Lever: finite pagination + native get fixtures. `[writer: W-ATS-LEVER]` `[depends: T022]`
- [x] T032 Ashby: honest board-scan get; no ingest URL-id override; unlisted enumerate gated. `[writer: W-ATS-ASHBY]` `[depends: T022]`
- [x] T033 Workable: board-scan get honesty + terminal evidence. `[writer: W-ATS-WORKABLE]` `[depends: T022]`
- [x] T034 Workday CXS list/get completeness; keep best-effort stability. `[writer: W-ATS-WORKDAY]` `[depends: T022]`
- [x] T035 Rippling list/native get fixtures; no unrelated EOF drive-by unless still broken. `[writer: W-ATS-RIPPLING]` `[depends: T022]`
- [x] T036 Teamtailor guid-first ingest + board-scan get; no kernel wrap of `fetch_jobs`. `[writer: W-ATS-TT]` `[depends: T022]`
- [x] T037 BambooHR list/native get; do not cap ingest behind pull detail budgets. `[writer: W-ATS-BAMBOO]` `[depends: T022]`
- [x] T038 Consider exact-get: native if stable public posting URL else authoritative board-scan. `[writer: W-ATS-CONSIDER]` `[depends: T022]`
- [x] T039 WP Job Manager list/native get fixtures. `[writer: W-ATS-WPJM]` `[depends: T022]`
- [x] T040 Optional `listing.py` kernel fix only if G2 writers prove a shared evidence gap. `[writer: W-KERNEL]` `[depends: T030, T031, T032, T033, T034, T035, T036, T037, T038, T039]` **Skipped:** no shared listing-kernel gap proven; `listing.py` untouched.

Proof:

```bash
uv run pytest tests/unit/openopps/test_greenhouse_depth.py tests/unit/openopps/test_lever_depth.py tests/unit/openopps/test_workable_depth.py tests/unit/openopps/test_workday_depth.py tests/unit/openopps/test_teamtailor_depth.py tests/unit/openopps/test_bamboohr_depth.py tests/unit/openopps/test_wpjobmanager_depth.py tests/unit/openopps/test_url_pull_providers_ashby_bamboohr_consider.py tests/unit/openopps/test_url_pull_providers_rippling_workable_workday_wpjobmanager.py tests/unit/openopps/test_url_pull_providers_greenhouse_lever_teamtailor.py tests/unit/openopps/test_provider_capability_manifests.py tests/unit/openopps/test_registry.py -q --basetemp /private/tmp/openopps-e2e-g2
```

## 4. G3 — overlay and household indexes, global demand order

- [x] T050 Drop US-weighted sequencing from overlay work-order copy; keep URL-match locators. `[writer: W-OVERLAY]` `[depends: T021]`
- [x] T051 Household index route gaps; never invent ATS tokens from ticker/domain. `[writer: W-INDEX]` `[depends: T021]`
- [x] T052 Per-employer outcome conservation still holds on core/expand/growth. `[writer: W-OVERLAY]` `[depends: T050]`
- [x] T053 Green packaged-gain exclusion; overlay family/tier histograms. `[writer: W-REPORT]` `[depends: T010, T050]`
- [x] T054 Isolation tests: scout/verify/preview never import or call sync. `[writer: W-DISCOVERY]` `[depends: T050]`

## 5. G4 — profiles and companion observations (parallel with G2; disjoint files)

- [x] T060 Implement `job_profiles.py` `core`/`search`/`full`/`raw`; default CLI `full`, web `search`. `[writer: W-PROFILES]` `[depends: T007]`
- [x] T061 Wire `export_records` through profiles; JSON/JSONL emit `profile`+`schemaVersion`. `[writer: W-EXPORT]` `[depends: T060]`
- [x] T062 Pull JSON envelope uses the same profiles; stdout jobs uncontaminated. `[writer: W-PULL-OUT]` `[depends: T060]`
- [x] T063 Thin `--profile` on `jobs export` / `jobs pull`; semantic help tests. `[writer: W-CLI]` `[depends: T061, T062]`
- [x] T064 `observations.py` companion records; compute-at-projection; no Alembic. `[writer: W-OBS]` `[depends: T008]`
- [x] T065 Compact origin tags on projections; derived != observed. `[writer: W-PROFILES]` `[depends: T060, T064]`
- [x] T066 Stop `_populate_enriched_fields` from looking provider-observed; do not edit `storage.py`. `[writer: W-OBS]` `[depends: T064]`
- [x] T067 Field-promotion rubric tests; search fields need documented gate. `[writer: W-PROFILES]` `[depends: T065]`
- [x] T068 If search profile fields change, extend T2 vectors; else skip. `[writer: W-SEARCH]` `[depends: T067]` **Skipped:** `SEARCH_PROFILE_FIELDS` stay snake_case `JobRecord` names; T2 camelCase vectors unchanged.
- [x] T069 Keep `jobs-static-data.ts` `isIndexableJobDetail` in lockstep if T068 fires. `[writer: W-WEB-TS]` `[depends: T068]` **Skipped:** T068 did not fire.

Proof:

```bash
uv run --frozen ruff check --select E9,F63,F7,F82 src/openopps/job_profiles.py src/openopps/observations.py src/openopps/export.py
uv run --frozen ty check
```

## 6. G5 — isolated quality floors and stop rule

- [x] T070 `coverage_quality.py`: null/parse/conflict/T2/capability; diminishing-yield stop. `[writer: W-QUALITY]` `[depends: T009, T022, T060]`
- [x] T071 Optional admin/providers quality diagnostic; not `--metrics-json`. `[writer: W-CLI]` `[depends: T063, T070]` **Skipped:** OpenSpec MAY; quality stays in `coverage_quality.py`, not a CLI metrics channel.
- [x] T072 Stop-rule unit: too few qualified additions ends expansion. `[writer: W-QUALITY]` `[depends: T070]`
- [x] T073 Nested AGENTS + docs only if public CLI/help changed. `[writer: W-DOCS]` `[depends: T063, T071]`

## 7. G6 — demand-gated new family or explicit skip

- [x] T080 Evidence memo: which candidate ATS unlocks overlay/index employers. `[writer: W-GOAL]` `[depends: T038, T052]` (gitignored `goals/.../g6-candidate-ats.md`; tracked proof is T082)
- [x] T081 Implement at most families that pass admission; else no-op. `[writer: W-REG]` `[depends: T080]` **No-op:** no candidate passed admission; registry unchanged by this goal.
- [x] T082 Skip test: one-off HTML / denied hosts do not register a jobs provider. `[writer: W-CAP]` `[depends: T080]`

G6 skip (T082 without a new family) is first-class success. SmartRecruiters, Recruitee, iCIMS, Jobvite, and JazzHR stay candidates until admission fires.

## 8. G7 — live-proof runbook and goal package

- [x] T090 Gitignored live-proof runbook: read-only pull, no save, no apply, no wrangler. `[writer: W-GOAL]` `[depends: T070, T082]`
- [x] T091 Grep workflows: no live ATS job added. `[writer: W-GOAL]` `[depends: T090]`
- [x] T092 Tick OpenSpec only with tracked test/commit proof. `[writer: W-OS]` `[depends: T004, T022, T061, T070]`
- [x] T093 Write `goal.md` with facts, plan, DAG, done condition. `[writer: W-GOAL]` `[depends: T090]`

## 9. Docs, nested AGENTS, local/CI parity

- [x] D-AGENTS Nested `src/openopps/AGENTS.md` and root `AGENTS.md` only if public CLI/help actually changed (`T073`). `[writer: W-DOCS]`
- [x] D-HELP Semantic help tests for `--profile` and quality diagnostic not `--metrics-json` (`T063`, `T071`). `[writer: W-CLI]`
- [x] D-DOCS Public docs name CLI-first coverage, profile defaults (`full` CLI, `search` web), and no live Workers/Kaggle. `[writer: W-DOCS]`
- [x] W-DELIVERY Update Justfile and matching GitHub Actions together only if the canonical validation surface changes; otherwise record an explicit no-change parity check.
- [x] V-SPEC `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict` after later deltas land.
- [x] V-ISO Discovery boundary tests still pass; `pull_coverage.py` / `pull_service.py` still do not import `openopps.discovery`.

Focused proof after implementation waves:

```bash
uv lock --check
rtk npx -y @fission-ai/openspec@1.6.0 validate expand-end-to-end-opportunity-coverage --strict
uv run pytest tests/unit/openopps/test_source_scope.py \
  tests/unit/openopps/test_job_seeker_overlay.py \
  tests/unit/openopps/test_job_seeker_overlay_outcomes.py \
  tests/unit/openopps/test_job_seeker_overlay_growth.py \
  tests/unit/openopps/test_registry.py \
  tests/unit/openopps/discovery/test_job_seeker_overlay_isolation.py \
  -q --basetemp /private/tmp/openopps-e2e-gate
```

Add new test modules from the DAG as they land. Do not run live ATS, Wrangler, Kaggle, or Alembic upgrade in this change.

## Stop rules

- Stop overlay JSON, catalog selector, or scout-promotion writes from URL pull.
- Stop Alembic `0005`/`0006` and `storage.py` `_unique_jobs_by_id` rewrites.
- Stop inventing a shared `RunMetrics` envelope or attaching `--metrics-json` to `jobs pull`.
- Stop faking native get for Ashby, Workable, or Teamtailor. Consider exact-get is G2 evidence, not a G0 claim.
- Stop US-weighted overlay sequencing. Stop treating catalog-row counts as the stop line.
- Stop registering a new ATS family from one-off HTML or denied hosts; G6 skip is success.
- Preserve unrelated dirty worktree files. Do not commit or push unless asked.
