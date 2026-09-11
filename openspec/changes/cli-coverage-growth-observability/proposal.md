## Why

Uncovered-board URL pulls already return jobs, but operator surfaces do not tell the truth about coverage. There is no coverage class, `--save` is advertised while persistence is unavailable, exhausted HTTP 429 maps to a generic provider failure, catalog `--metrics-json` can sum incomparable board units, and `status` next-action copy can imply that pulling a URL filled an empty catalog. Overlay growth exists in packaged JSON without a merged coverage family, and pull stderr still says `discovery=` in a product that also has quarantined scout.

Fixing those by mutating `job_seeker_overlay.json`, catalog selectors, or inventing a shared `RunMetrics` envelope would mix conserved catalog denominators with single-URL terminals. The contract must keep four observability stacks isolated, keep stdout jobs uncontaminated, and keep URL-pull persistence opt-in (`--save` default False) rather than persist-by-default.

## What Changes

- Freeze catalog ingest `SyncMetrics` as the `--metrics-json` stdout envelope: always emit `schemaVersion`, add v2 `stages`, nest a payload-free `http` snapshot, and stop summing incomparable board counters.
- Freeze URL-pull `PullTerminalObservability` on `--raw`, `--metrics-file`, pretty coverage lines, and `-v` stderr. Do not attach `--metrics-json` to `jobs pull`.
- Classify each pull with a closed coverage class. URL pull SHALL NOT mutate packaged overlay JSON or catalog selectors.
- Document opt-in `--save` (default ephemeral, `--no-save` alias, persist-failure exit 9). Do not claim persist-by-default or that the storage join is not enabled.
- Map exhausted HTTP 429 on pull to a new closed `RATE_LIMITED` error in the upstream process-status family (8).
- Correct empty-catalog `status`/`doctor` nextAction so URL pull is not described as filling coverage.
- Record the packaged overlay family and tiers. Packaged gain SHALL NOT count url-pull or scout.
- Expose cache `status` duration aggregates without leaking URLs.
- Rename pull stderr `discovery=` to `resolution=`.

## Capabilities

### New Capabilities

None. Coverage-class, metrics-file, overlay-family, and HTTP-snapshot honesty extend existing CLI, coverage, ingestion, cache, and observability capabilities.

### Modified Capabilities

- `performance-observability`: Isolate the four stacks; freeze SyncMetrics keys, `schemaVersion`, v2 `stages`, nested `http`, and conservation; keep pull metrics off the catalog JSON channel.
- `cli-domain`: Add `--metrics-file` for pull; keep `--metrics-json` catalog-sync stdout only; document opt-in `--save`, coverage-class surfaces, and `resolution=` stderr.
- `provider-coverage`: Add the packaged overlay family and tiers; forbid counting url-pull or scout as packaged gain; make empty-catalog nextAction honest.
- `provider-ingestion`: Keep overlay locators URL-match-only with no domain-invented tokens; map exhausted pull 429 to `RATE_LIMITED`.
- `cache`: Report duration aggregates on cache status without URL or secret labels.

## Impact

- OpenSpec-only in this leaf. Later waves own new `pull_coverage.py`, `pull_metrics.py`, and `overlay_report.py`, plus exclusive writers for `pull_models.py`, `http.py`, `metrics.py`, `ingest.py`, `pull_service.py`, `pull_output.py`, thin `cli.py` wrappers, `coverage.py`, `cache.py`, agent-plugin recipes, and AGENTS/help.
- No overlay JSON writes, scout promotion, `url_pull_runs`, Alembic, OTEL SDK, Prometheus, hosted alerts, or `admin boards add` from pull.
- `unified-cli-job-pulls` D712 landed opt-in `--save` (default False). This change records that current contract rather than persist-by-default.
- Console entry stays `openopps.cli:app`. Mocked tests are not live upstream proof.

## Acceptance summary

1. Sync, pull, discovery, and web remain four isolated observability stacks. `--metrics-json` is catalog sync stdout only.
2. `jobs pull --metrics-file` writes camelCase observability with coverage class; stdout jobs stay uncontaminated; `--quiet` still writes the file.
3. Coverage class is a closed enum. URL pull does not mutate catalog or overlay JSON.
4. Default pull is ephemeral. `--save` is opt-in. Persist failure exits 9 (`PERSISTENCE_FAILED`). The hint does not say the storage join is not enabled.
5. Exhausted 429 maps to `RATE_LIMITED` with process status family 8. No second 429 code is added.
6. Sync metrics always include `schemaVersion`. v2 emits `stages`. Combined `boards` is not a sum of incomparable stage units. Nested `http` is payload-free.
7. Empty-catalog nextAction does not imply a URL pull filled coverage. Overlay packaged gain excludes url-pull and scout.
8. Cache status exposes duration aggregates without URLs. Pull stderr uses `resolution=` rather than `discovery=`.
9. `rtk npx -y @fission-ai/openspec@1.6.0 validate cli-coverage-growth-observability --strict` passes. Implementation remains later waves.
