## Context

Catalog ingest already emits `SyncMetrics` on `--metrics-json`. URL pull already emits `PullTerminalObservability` on `--raw` and verbose stderr, writes HTTP cache, and defaults to `_UnavailablePullPersistence`. Overlay JSON is packaged and `lru_cache`d. Quarantined scout writes only an explicit quarantine directory. Docs telemetry is a first-party `/api/telemetry` lake.

Those four surfaces currently share vocabulary (`coverage`, `discovery`, `boards`, `retries`) without shared units. `combine_sync_metrics` adds source-catalog board yield to probe and jobs-stage counters. `status` nextAction on `sources==0` recommends pulling an HTTPS URL as if that populated catalog SQLite. Exhausted pull 429 becomes `PROVIDER_FAILED`. `--save` is advertised while the storage join is closed.

`unified-cli-job-pulls` owns opt-in `--save` after D712 (`d464e84`). Live Alembic head is `0006_url_pull_runs`. This change does not start further schema work and does not flip persist-by-default.

## Goals / Non-Goals

**Goals:**

- Make uncovered-board URL pulls honest and measurable without catalog or overlay mutation.
- Keep four observability stacks isolated while sharing one payload-free `HttpOperationSnapshot`.
- Freeze SyncMetrics v2 `stages` and always-on `schemaVersion`.
- Give pull a `--metrics-file` channel that does not contaminate stdout jobs.
- Classify coverage offline from overlay JSON and optional catalog lookup.
- Record the opt-in `--save` default, `--no-save` alias, persist-failure exit 9, and 429 → `RATE_LIMITED` mapping.
- Correct empty-catalog nextAction and overlay packaged-gain accounting.
- Rename pull stderr `discovery=` to `resolution=`.

**Non-Goals:**

- G3 `D701`–`D712`, overlay JSON writes, scout promotion, `url_pull_runs`, Alembic, or `admin boards add` from pull.
- Inventing a `RunMetrics` envelope, attaching `--metrics-json` to `jobs pull`, or mixing scout metric names into pull.
- OTEL SDK, Prometheus exporters, traces, `http.server.duration` histograms, or hosted-alpha / web event-lake changes.
- Unifying health, coverage, and pull under one `coverage` key.
- Expanding `provider_error_count` past the existing 0/1 latch.
- Operational robots.txt stacks, or treating Workable stale-on-error success as a new robots concern (keep it as `http.cacheStaleFallbackCount`).
- Editing application code, tests, agent-plugins, or `AGENTS.md` in this OpenSpec leaf.

## Decisions

### Four isolated stacks

| Stack | Envelope | Machine channel | Isolation rule |
| --- | --- | --- | --- |
| Catalog ingest | `SyncMetrics` | `--metrics-json` **stdout** | Conservation terminals; nested `http` snapshot |
| URL pull | `PullTerminalObservability` | `--raw` envelope; **`--metrics-file`**; `-v` stderr | No SyncMetrics shape; no scout metric names |
| Discovery | selector-bound JSON + `openopps.discovery.*` | scout `--json` | No operational SQLite; no overlay writes |
| Web | first-party `/api/telemetry` | docs lake | No CLI pull events |

`--metrics-json` remains catalog sync stdout only. Agent recipes that apply it to url-pull are false and are corrected in a later docs/plugin wave.

Ingest may keep using discovery **accounting helpers**. Pull modules SHALL NOT import `openopps.discovery`. Overlay outcomes stay offline classifiers, not scout admission.

### Shared HTTP snapshot, not a shared run envelope

Reuse `HttpOperationSnapshot` on `PullHttpObservability` and `SyncMetrics.http`. One collector: `http_operation_observability`. `record_http_retry` becomes a thin alias that increments the bound collector and does not double-count `SyncMetrics.retries` when the snapshot is the source of truth.

Labels follow OpenTelemetry HTTP attribute *ideas*: low-cardinality method/status **counts**. Metrics, files, and stderr SHALL NOT use `url.full`, raw query, headers, secrets, or page bodies as labels.

### SyncMetrics v2 stages

`schemaVersion` is always present on `--metrics-json` (1 until stages land, 2 when units freeze).

v2 emits `stages.sources`, `stages.boards`, and `stages.jobs`. Each stage's `boards` unit is exact to that stage. `combine_sync_metrics` SHALL NOT add source-catalog board yield to probe or jobs-stage board counters.

v1 top-level `boards` stays sources-sync catalog yield **only** (stop adding probe counts). Adding `stages` is compatible; changing the meaning of `boards` without versioning is a breaking metrics contract. Conservation remains first-wins: planned = sum of mutually exclusive terminals.

Workable listing stale-on-error that turns a 429 into a successful catalog sync stays visible as `http.cacheStaleFallbackCount`, not a new robots stack.

### Pull metrics file and quiet diagnostics

`--metrics-file PATH` is a `jobs pull` option. The writer uses the same atomic replace pattern as `pull_output.py`. The file is one camelCase object with `schemaVersion`. Quiet mode still writes the file. Stdout remains the selected jobs representation.

`--raw` stays snake_case. Do not break existing raw consumers.

Coverage class appears in the pretty TTY panel, `--metrics-file` / `--raw`, and `-v` stderr. An always-on success `coverage=` stderr line is forbidden: agents that ignore stderr must still get the full result. Failures and stale-cache warnings remain essential.

No new loguru on pull success. Operator truth is stderr diagnostics plus the metrics file.

### Coverage class

Closed enum on `PullTerminalObservability`:

| Class | Meaning |
| --- | --- |
| `catalog_route` | URL matches a stored catalog route |
| `overlay_packaged` | URL matches packaged overlay JSON |
| `url_pull_reserved` | Reserved `url-pull` ledger identity after an opt-in `--save` persist |
| `ephemeral_new` | Supported-provider URL not in catalog or overlay; jobs may still return |
| `not_applicable` | Failures |

Success plus ephemeral persistence requires a class in `{catalog_route, overlay_packaged, url_pull_reserved, ephemeral_new}`. Failures use `not_applicable` (or error_code-only if classification is unavailable). Classification is offline: overlay `lru_cache` plus optional SQLite route lookup. No extra HTTP.

A supported-provider URL that is not in packaged coverage does **not** enter `job_seeker_overlay.json` or catalog selectors.

### Opt-in persistence (post-D712)

`unified-cli-job-pulls` persist-by-default is **not** the post-D712 contract. The operational default is ephemeral: successful `jobs pull` writes HTTP cache only unless `--save` is selected.

`--save` persists a complete validated result through `OpenOppsStorePullPersistence`. Persist failure exits 9 (`PERSISTENCE_FAILED`). The hint SHALL NOT say the storage join is not enabled. `--no-save` remains the explicit ephemeral alias.

Default pretty/JSON MUST be able to show `persisted=false`. HTTP cache writes are not proof of operational persistence.

### 429 mapping (single choice)

After shared retries are exhausted, HTTP 429 on a URL pull maps to a new closed `PullErrorCode.RATE_LIMITED`. That code maps to `PullProcessStatus.UPSTREAM_FAILED` (process status family 8).

This is the only 429 mapping. Do not also add `BUDGET_EXCEEDED` with reason `rate_limited`. Do not keep exhausted 429 as `PROVIDER_FAILED`. Counters remain present. Diagnostics do not dump headers.

`_ERROR_PROCESS_STATUSES` remains exhaustive over `PullErrorCode`.

### status nextAction

`openopps status` is a new process. There is no session and no memory of the last pull. When `sources==0`, copy SHALL say the catalog is empty; URL pull does not populate it; use `sources sync` / `examples seed`; `jobs pull` is ephemeral. Never claim a prior pull filled coverage.

Doctor JSON may later add an additive `checklist` or `setup.catalogEmpty` key. Do not fork a second schema in this change.

### Overlay packaged family

Packaged overlay is a coverage family with tiers `core`, `expand`, and `growth`. Offline outcomes per overlay id are `fetchable_packaged`, `no_public_ats`, `duplicate`, and `policy_blocked`. Those four outcomes are conserved per id.

Locators attach jobs-capable routes only through `detect_url_matches`. OpenOpps SHALL NOT invent an ATS token from a company domain. URL pull and scout SHALL NOT count as packaged overlay gain.

### Cache status duration aggregates

`cache status` exposes aggregates of stored `request_duration_ms` (count, present count, optional min/max/sum or equivalent summary). Aggregates SHALL NOT include request URLs, cache keys that embed secrets, query strings, or payloads.

### Rename `discovery=` to `resolution=`

Pull stderr currently prefixes resolver method with `discovery=`, which collides with quarantined scout. The prefix becomes `resolution=` and continues to report `DiscoveryMethod` (native vs careers resolution), not scout.

## Migration and rollback

This OpenSpec leaf is additive documentation. Implementation waves are additive flags, fields, and modules. Rolling back Python later removes `--metrics-file`, coverage class, `RATE_LIMITED`, nested `http`, and `stages` without changing persisted catalog rows. Pre-G3 pulls already do not write operational tables.

v1 SyncMetrics `boards` remains sources-sync catalog yield so existing `--metrics-json` notebooks keep a stable field. v2 readers use `stages`.

## Parallel task graph and ownership

```text
Wave 0 OpenSpec (this leaf)
  |
  +--> Wave 1 parallel red tests (T-COV, T-FILE, T-SAVE, T-429, T-UNITS,
  |         T-STATUS, T-OVERLAY, T-RES, T-PLUGIN, T-HTTP-BIND, T-CACHE-STAT, T-ISO)
  |
  +--> Wave 2 parallel new modules (pull_coverage, pull_metrics, overlay_report)
         |
         +--> Wave 3 pull_models contracts
                |
                +--> Wave 4 serial http.py --> metrics.py --> ingest.py
                |         Wave 5 pull_service + pull_output, then thin cli.py
                +--> Wave 6 coverage notes, overlay-outcomes CLI, cache timings,
                |         status nextAction after CLI wrappers exist
                +--> Wave 7 AGENTS/help, agent-plugins, just/CI, strict OpenSpec, pytest
```

Same-file edits are serialized. `cli.py` is only Wave 5–6 after helpers exist. `http.py` is only `W-HTTP`. `metrics.py` is only `W-METRICS`. `ingest.py` is only `W-INGEST`. `pull_models.py` is only `W-CONTRACT`. This leaf owns `openspec/changes/cli-coverage-growth-observability/**` and MUST NOT touch application code.

## Risks / Trade-offs

- **Opt-in `--save` vs older persist-by-default drafts.** Current product truth after D712 is ephemeral default. Accepted: do not flip CLI to persist-by-default.
- **v1 `boards` notebooks.** Leaving top-level `boards` as catalog yield (not a combined sum) may change current confused combine output. Accepted: `schemaVersion: 2` plus `stages` makes units explicit; v1 field is frozen as catalog yield only.
- **New `RATE_LIMITED` code.** Callers that exhaustively switch on `PullErrorCode` must be updated in Wave 3. Accepted: better than overloading `PROVIDER_FAILED` or adding a second 429 mapping.
- **Quiet success hides coverage class.** Agents that ignore stderr still get jobs JSON; they need `--metrics-file` or `--raw` for class. Accepted: do not break “stderr is context.”
- **`url_pull_reserved` is true only after opt-in `--save` lands a reserved identity.** Default ephemeral pulls stay `ephemeral_new` / catalog / overlay classes.
