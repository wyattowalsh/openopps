# cli-coverage-growth-observability - tasks

Checked tasks require the named local proof. They do not authorize overlay JSON writes, scout promotion, Alembic, OTEL, hosted alerts, live publication, commit, or push. Schema-dependent persistence remains owned by `unified-cli-job-pulls` D701–D712.

Wave 0 is this OpenSpec package. Later waves wait on exclusive writers in the design graph. Do not start two writers on `cli.py`. Do not import `openopps.discovery` from pull modules.

## 0. Wave 0 — OpenSpec contract `[writer: W-OPENSPEC]`

- [x] 0.1 `O001` Add change `cli-coverage-growth-observability` proposal: honesty, four-stack isolation, and non-goals (G3, overlay mutation, OTEL, hosted).
- [x] 0.2 `O002` Design: four stacks, `HttpOperationSnapshot` share, metrics v2 `stages`, `--metrics-file`, coverage class, 429 mapping, `resolution=` rename, pre-G3 ephemeral exception, closed persistence reason.
- [x] 0.3 `O003` Delta `performance-observability`: freeze SyncMetrics keys; `schemaVersion` always; nested `http`; conservation equations; no URLs in labels; `--metrics-json` is catalog sync stdout only.
- [x] 0.4 `O004` Delta `cli-domain`: `--metrics-file`; ephemeral default as explicit exception to persist-by-default; stderr vs pretty vs file; `--metrics-json` is sync-only; `resolution=` rename.
- [x] 0.5 `O005` Delta `provider-coverage`: overlay family + tiers; SHALL NOT count url-pull or scout as packaged gain; status nextAction catalog-empty copy.
- [x] 0.6 `O006` Delta `provider-ingestion`: overlay locators, `detect_url_matches` only, no domain-invented tokens; 429 closed mapping on pull.
- [x] 0.7 `O007` Delta `cache`: `cache status` exposes duration aggregates without leaking URLs.
- [x] 0.8 `O008` Strict-validate this change with pinned `@fission-ai/openspec@1.6.0`. `[depends: O001-O007]`

Proof:

```bash
rtk npx -y @fission-ai/openspec@1.6.0 validate cli-coverage-growth-observability --strict
```

## 1. Wave 1 — red tests (parallel after O002 facts)

- [x] 1.1 `T-COV` Add `tests/unit/openopps/test_pull_coverage.py`: overlay-known greenhouse vs unknown token vs catalog route fixture vs failure `not_applicable`. No HTTP.
- [x] 1.2 `T-FILE` Add `tests/unit/openopps/test_pull_metrics_file.py` plus CLI integration: jobs stdout is the job array; file is camelCase observability plus coverage class; `--quiet` still writes the file; atomic replace.
- [x] 1.3 `T-SAVE` Historical pre-join red test: `--save` hint contained a closed unavailable reason. Post-D712 current contract is opt-in `--save` with persist-failure exit 9; do not treat `persistence_unavailable` / “storage join is not enabled” as current product truth.
- [x] 1.4 `T-429` Exhausted 429 maps to `RATE_LIMITED`; counters remain present; no header dump.
- [x] 1.5 `T-UNITS` `test_metrics.py`: `combine_sync_metrics` does not add source boards to probe boards; v2 `stages` present; `http` nested when collector bound.
- [x] 1.6 `T-STATUS` status JSON/human nextAction when sources=0 does not imply pull filled the catalog.
- [x] 1.7 `T-OVERLAY` overlay outcomes JSON includes growth-tier counts; `policy_blocked` / `duplicate` / `fetchable_packaged` / `no_public_ats` conserved per id.
- [x] 1.8 `T-RES` stderr uses `resolution=` not `discovery=`; help semantic test.
- [x] 1.9 `T-PLUGIN` url-pull recipes do not recommend `--metrics-json` for pull; they mention `--metrics-file` / `--raw`.
- [x] 1.10 `T-HTTP-BIND` ingest with collector bound: retry increments snapshot and does not double-count `retries`.
- [x] 1.11 `T-CACHE-STAT` cache status JSON includes duration summary fields.
- [x] 1.12 `T-ISO` `pull_coverage` / `pull_service` still do not import `openopps.discovery`.

## 2. Wave 2 — new modules (parallel; no existing-file writes)

- [x] 2.1 `N-COV` `[W-CONTRACT]` Create `src/openopps/pull_coverage.py`: classify from overlay `lru_cache` plus optional store route lookup. Pure, payload-free.
- [x] 2.2 `N-FILE` `[W-OUTPUT]` Create `src/openopps/pull_metrics.py`: `write_pull_metrics_file(observability, path)`, camelCase dump, `schemaVersion`, atomic write, 500-char diagnostic bound if errors.
- [x] 2.3 `N-OVL` `[W-OVERLAY-CLI]` Create `src/openopps/overlay_report.py`: `overlay_worklist_outcomes()` JSON with tier histograms. No HTTP.

## 3. Wave 3 — contracts `[W-CONTRACT]` (serial on `pull_models.py`)

- [x] 3.1 `C-ENUM` Coverage class plus persistence reason on `PullTerminalObservability`.
- [x] 3.2 `C-VAL` Validators: success + ephemeral ⇒ class in `{catalog_route, overlay_packaged, url_pull_reserved, ephemeral_new}`; failed ⇒ `not_applicable` or error_code-only.
- [x] 3.3 `C-429` Closed `RATE_LIMITED` mapping to process status family 8. Update `_ERROR_PROCESS_STATUSES` exhaustiveness.
- [x] 3.4 `C-COUNT` Keep `provider_error_count` as a 0/1 latch. Do not expand to unbounded counts.

## 4. Wave 4 — HTTP then metrics then ingest (strict serial)

- [x] 4.1 `H-ALIAS` `[W-HTTP]` Single retry increment path; snapshot is source of truth when collector exists.
- [x] 4.2 `H-STALE` Ingest success with stale fallback remains visible in `http.cacheStaleFallbackCount`.
- [x] 4.3 `M-NEST` `[W-METRICS]` `SyncMetrics.http: HttpOperationSnapshot | None`; `as_dict()` camelCase `http`; always `schemaVersion` (1 until stages land, 2 when units freeze).
- [x] 4.4 `M-STAGE` Stop `combine_sync_metrics` from adding incomparable `boards`. Implement `stages`. Preserve conservation first-wins. v1 `boards` = sources-sync catalog yield only.
- [x] 4.5 `I-WRAP` `[W-INGEST]` `with http_operation_observability()` per sync command (or whole `ingest()`); copy snapshot at finish. Do not wrap discovery scout.
- [x] 4.6 `I-BOARD` Boards stage: optional conservation or explicit `unresolvedProbe` count so attestation cannot hide probe errors.

## 5. Wave 5 — pull service, output, thin CLI

- [x] 5.1 `S-CLASS` `[W-PULL-SVC]` After resolve, attach coverage class (store optional; tests inject). Failures still attach observability.
- [x] 5.2 `S-HINT` Unavailable persist → closed reason + hint.
- [x] 5.3 `S-429` Map httpx 429 after retries to `RATE_LIMITED`.
- [x] 5.4 `P-PRETTY` `[W-OUTPUT]` Pretty panel: `coverage=` `persisted=` `board=`.
- [x] 5.5 `P-STDERR` Rename `discovery=` → `resolution=`; coverage line at verbosity ≥1 (not essential success).
- [x] 5.6 `P-FILE` `--metrics-file` on `jobs_pull` only.
- [x] 5.7 `L-WRAP` `[W-CLI]` Typer options plus call helpers. No business logic left in `jobs_pull` beyond orchestration.

## 6. Wave 6 — operator surfaces

- [x] 6.1 `U-STATUS` `[W-CLI]` after L-WRAP: nextAction copy; doctor JSON may add additive `checklist` or `setup.catalogEmpty`; do not fork a second schema.
- [x] 6.2 `U-COVNOTE` `[W-COVERAGE-UI]` yield/coverage notes: overlay packaged vs url-pull vs pull-ephemeral.
- [x] 6.3 `U-OVLCMD` `[W-OVERLAY-CLI]` `admin sources overlay-outcomes --json` on the Advanced panel.
- [x] 6.4 `U-CACHE` `[W-CACHE]` duration aggregates on `cache status`.

## 7. Wave 7 — docs, plugins, gates

- [x] 7.1 `D-AGENTS` Update root and `src/openopps/AGENTS.md`: pull vs overlay vs coverage; `--metrics-file`; no catalog-from-URL.
- [x] 7.2 `D-HELP` Semantic help tests for `--metrics-file`, ephemeral default, and `--metrics-json` not on pull.
- [x] 7.3 `D-PLUGIN` `[W-PLUGINS]` Fix url-pull recipes; `just agent-plugins-check`.
- [x] 7.4 `D-KAGGLE` If notebooks assume `boards` meaning, update comments only when v2 changes units.
- [x] 7.5 `W-DELIVERY` Update Justfile and matching GitHub Actions together only if the canonical validation surface changes; otherwise record an explicit no-change parity check.
- [x] 7.6 `V-FOCUS` Focused pytest list below.
- [x] 7.7 `V-SPEC` `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict`.
- [x] 7.8 `V-RUFF` ruff + ty on touched gated paths.
- [x] 7.9 `V-ISO` discovery boundary tests still pass.

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_pull_coverage.py tests/unit/openopps/test_pull_metrics_file.py tests/unit/openopps/test_pull_models.py tests/unit/openopps/test_pull_service.py tests/unit/openopps/test_pull_output.py tests/unit/openopps/test_metrics.py tests/unit/openopps/test_http.py tests/integration/openopps/test_url_pull_cli.py tests/integration/openopps/test_cli.py tests/unit/openopps/test_job_seeker_overlay_outcomes.py tests/integration/openopps/test_discovery_boundaries.py -q
just agent-plugins-check
rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict
uv run ruff check --fix src/openopps tests
uv run ty check
```

## Stop rules

- Stop overlay JSON, catalog selector, or scout-promotion writes from URL pull.
- Stop schema work whenever G3 or L.1 is open.
- Stop adding a second 429 mapping after `RATE_LIMITED` is chosen.
- Stop wrapping discovery scout in ingest HTTP observability.
- Preserve unrelated untracked `.grok/`, `.playwright-mcp/`, and `inspect-shots/` paths.
