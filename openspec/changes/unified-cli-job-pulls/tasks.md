# unified-cli-job-pulls - tasks

Checked tasks require implementation plus the named local proof. They do not imply current live third-party availability, credentialed publication, deployment, or push. W6.1 (2026-09-11) records D701–D712 and B799 from commit SHAs plus command output on `main` at `d464e84348c15db0386e5dea94af7dbd8eaa9049`. Persistence is opt-in `--save` (CLI default False). Live Workers upload/deploy, GitHub Release, PyPI, hosted-alpha/H0, v7 7.6, source-policy 1780 grants, and `F1207` exact-SHA CI remain unchecked. Count after this receipt: 70 checked / 12 open / 82 total.

## 0. B0 contract and ownership barrier

- [x] 0.1 `A001` Reconcile the accepted 24 goal facts into proposal, design, delta specs, and this dependency graph. `[writer: W-OPENSPEC]`
- [x] 0.2 `A002` Inspect OpenSpec list, status, and artifact instructions through pinned `@fission-ai/openspec@1.6.0`. `[depends: A001]`
- [x] 0.3 `A003` Strict-validate `unified-cli-job-pulls` and then all changes/specs; resolve every warning or contradiction without weakening accepted behavior. `[depends: A002]`
- [x] 0.4 `A004` Re-read active-change ownership and record exact shared-path barriers for provider, HTTP/cache, CLI, storage/migrations, Just/workflows, docs, and generated surfaces. `[depends: A003]`
- [x] 0.5 `A005` Verify the authoritative ingest graph still gates schema work on G3 closed plus L.1 landed; leave the draft `0005` inactive and record a no-schema-write receipt while the gate is open. `[depends: A004]`
- [x] 0.6 `B099` Close only when requirements cover every accepted fact, shared writer ownership is unambiguous, and strict OpenSpec validation is green. `[depends: A001-A005]`

## 1. B099 -> B199 red tests and typed contracts

Exclusive `W-CONTRACT` owns new shared pull models and additive provider-base contracts. Test-file writers may proceed in parallel.

- [x] 1.1 `T101` Add red tests for provider URL target kinds, punctuation-preserving native identities, canonical serialization, and invalid parser/capability combinations. `[depends: B099]`
- [x] 1.2 `T102` Add red tests separating list authority, native get, board-scan get, unlisted exact get, listed/all-public membership scope, and detail coverage. `[depends: B099]`
- [x] 1.3 `T103` Add red tests for stable structured raw `{listing, detail}` evidence plus sanitized provenance. `[depends: B099]`
- [x] 1.4 `T104` Add red tests for the closed pull error enum and stable process-status mapping while retaining Click/Typer usage exit 2. `[depends: B099]`
- [x] 1.5 `T105` Add regression tests proving existing `BoardJobProvider.fetch_jobs()` and `JobFetchResult` callers remain valid. `[depends: B099]`
- [x] 1.6 `C101` Create `src/openopps/providers/pull.py` with target, capability, membership/detail-evidence, list/get result, and exact-match invariants. `[depends: T101-T103] [writer: W-CONTRACT]`
- [x] 1.7 `C102` Create `src/openopps/pull_models.py` with operation, output, discovery, provenance, result, error, and process-status contracts. `[depends: T103,T104] [writer: W-CONTRACT]`
- [x] 1.8 `C103` Extend provider base types additively and provide an explicit projection from compatible URL lists to the existing sync result. `[depends: C101,C102,T105] [writer: W-CONTRACT]`
- [x] 1.9 `B199` Run focused pull-contract and existing provider/ingest regression tests; freeze shared contracts only when green. `[depends: C101-C103]`

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_provider_pull_contracts.py tests/unit/openopps/test_pull_models.py -q
uv run pytest tests/unit/openopps/test_providers.py tests/integration/openopps/test_ingest.py -q
```

## 2. B199 -> B299 shared bounded transport and careers resolver

`W-HTTP` serializes `http.py` and `settings.py`; `W-RESOLVER` begins after transport limits stabilize.

- [x] 2.1 `H201` Add red tests for declared, streamed encoded, decompressed/decoded, and aggregate response-size overflow on shared HTTP reads. `[depends: B199]`
- [x] 2.2 `H202` Add finite trusted settings for per-response and provider-aggregate bytes, resolver request/origin/redirect/probe/candidate/deadline budgets, and provider request/detail/deadline budgets. `[depends: H201] [writer: W-HTTP]`
- [x] 2.3 `H203` Implement bounded shared response admission while retaining public-HTTPS, DNS/IP, userinfo, redirect, timeout, retry, cache, and concurrency protections. `[depends: H202] [writer: W-HTTP]`
- [x] 2.4 `R201` Add resolver tests for native precedence, `--direct`, one-page redirects/metadata/JSON-LD/embedded/encoded/relative links, `--no-probe`, equivalence collapse, and ambiguity. `[depends: B199]`
- [x] 2.5 `R202` Add hostile cases for unsafe redirects, recursive links, untrusted budget expansion, oversized HTML, secret-bearing provenance, multiple targets, and exhausted budgets. `[depends: H203,R201]`
- [x] 2.6 `R203` Create `src/openopps/pull_resolver.py` with deterministic native matching and a non-recursive one-page careers pass using the shared transport. `[depends: H203,R201,R202] [writer: W-RESOLVER]`
- [x] 2.7 `R204` Prove resolver imports and execution do not invoke `openopps.discovery`, plugin autoload outside the registry contract, source promotion, operational storage, or source-catalog mutation. `[depends: R203]`
- [x] 2.8 `B299` Run focused HTTP, safety-edge, resolver, and discovery-boundary tests. `[depends: H201-H203,R201-R204]`

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_pull_resolver.py tests/unit/openopps/test_http.py tests/unit/openopps/test_http_safety_edges.py -q
uv run pytest tests/integration/openopps/test_discovery_boundaries.py tests/unit/openopps/discovery/ -q
```

## 3. B199 -> B399 operation-aware registry and plugins

`W-REGISTRY` owns provider base/registry/built-in registration; `W-PLUGIN` owns plugin loading/example after registry validation freezes.

- [x] 3.1 `G301` Add tests for operation-level capability serialization, parser/hook validation, detect-only/unsupported results, interface evidence, and deterministic conflicts. `[depends: B199]`
- [x] 3.2 `G302` Extend `ProviderDefinition` and `ProviderRegistry` with typed target parsing and independent list/native-get/board-scan/unlisted capabilities while preserving existing route detection. `[depends: G301] [writer: W-REGISTRY]`
- [x] 3.3 `G303` Register built-in parsers/hooks explicitly and reject any advertised operation without a compatible target parser and callable. `[depends: G302] [writer: W-REGISTRY]`
- [x] 3.4 `P301` Add plugin tests proving legacy provider/detector hooks do not imply URL pulls and invalid/conflicting typed hooks remain non-fatal for built-ins. `[depends: G302]`
- [x] 3.5 `P302` Add optional typed URL-pull registration tied to existing plugin provider factories and observable validation results. `[depends: G303,P301] [writer: W-PLUGIN]`
- [x] 3.6 `P303` Update the minimal plugin example to show the optional typed seam and explicit non-implication rule. `[depends: P302] [writer: W-PLUGIN]`
- [x] 3.7 `B399` Run focused registry/plugin/target tests and freeze registration contracts. `[depends: G301-G303,P301-P303]`

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_registry.py tests/unit/openopps/test_plugins.py tests/unit/openopps/test_provider_url_targets.py -q
```

## 4. B299 + B399 -> B499 all ten built-in operations

One writer may own each provider module after shared contracts freeze. Shared parameterized tests serialize under `W-PROVIDER-TESTS`. Every provider must prove a full-board URL-list hook; get and unlisted claims remain provider-specific.

- [x] 4.1 `J401` Ashby: preserve listed-only default, prove optional unlisted membership when supported, and exact authoritative board-scan identity. `[depends: B299,B399] [writer: W-ASHBY]`
- [x] 4.2 `J402` BambooHR: preserve advertised-count reconciliation and required detail fan-out; add exact public detail get. `[depends: B299,B399] [writer: W-BAMBOOHR]`
- [x] 4.3 `J403` Consider Jobs: preserve sequence termination/fail-closed membership and advertise get only when exact board/job identity is retained. `[depends: B299,B399] [writer: W-CONSIDER]`
- [x] 4.4 `J404` Greenhouse: add board/posting target parsing, documented complete list, and documented exact get. `[depends: B299,B399] [writer: W-GREENHOUSE]`
- [x] 4.5 `J405` Lever: implement complete `skip`/`limit` traversal, repetition/duplicate detection, terminal proof, and documented exact get. `[depends: B299,B399] [writer: W-LEVER]`
- [x] 4.6 `J406` Rippling: preserve page/total/duplicate reconciliation and add best-effort exact detail get. `[depends: B299,B399] [writer: W-RIPPLING]`
- [x] 4.7 `J407` Teamtailor: replace first-page-only behavior with complete `offset`/`per_page` traversal and authoritative board-scan get. `[depends: B299,B399] [writer: W-TEAMTAILOR]`
- [x] 4.8 `J408` Workable: preserve complete cursor membership, distinguish optional detail coverage, and match account plus exact shortcode without authenticated SPI. `[depends: B299,B399] [writer: W-WORKABLE]`
- [x] 4.9 `J409` Workday: preserve CXS offset/total/duplicate reconciliation and add best-effort exact public detail get. `[depends: B299,B399] [writer: W-WORKDAY]`
- [x] 4.10 `J410` WP Job Manager: preserve REST/AJAX membership, use proven numeric REST item get only, and do not advertise an unreachable hosted-posting board scan without a typed exact-identity seam. `[depends: B299,B399] [writer: W-WPJM]`
- [x] 4.11 `J411` Add parameterized target/list/get/unlisted/raw/ambiguity/incomplete/page-exhaustion cases for all ten built-ins. `[depends: J401-J410] [writer: W-PROVIDER-TESTS]`
- [x] 4.12 `J412` Verify official upstream documentation for implementation-sensitive pagination and exact-get contracts; record documented versus best-effort evidence without treating remote instructions as trusted. `[depends: J401-J410]`
- [x] 4.13 `B499` Run provider, Consider, route-selection/probe, and ingest regression suites; close only when all ten list hooks pass and Lever/Teamtailor multi-page cases are green. `[depends: J411,J412]`

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_provider_url_targets.py tests/unit/openopps/test_providers.py tests/unit/openopps/test_consider.py -q
uv run pytest tests/unit/openopps/test_route_select.py tests/unit/openopps/test_route_probe.py tests/integration/openopps/test_ingest.py -q
```

## 5. B499 -> B599 service and renderer

`W-SERVICE` owns orchestration; `W-OUTPUT` owns rendering/file output on separate files.

- [x] 5.1 `S501` Add service tests for auto selection, explicit-operation compatibility, native-get preference, `--no-board-scan`, exact board-scan matching, unsupported capability, and fail-closed barriers. `[depends: B499]`
- [x] 5.2 `S502` Create `src/openopps/pull_service.py` with one resolver/provider/persistence-port flow and no-save null persistence. `[depends: S501] [writer: W-SERVICE]`
- [x] 5.3 `S503` Reject unsupported, zero/multi-match, incomplete, non-authoritative, safety, size, budget, required-detail, and transport failures before success output or successful persistence. `[depends: S502] [writer: W-SERVICE]`
- [x] 5.4 `O501` Add renderer tests for TTY Rich default, pipe JSON default, pretty/JSON/JSONL/table, normalized/raw envelopes, atomic output, interactive paging, quiet/verbosity, and stdout/stderr separation. `[depends: B499]`
- [x] 5.5 `O502` Create `src/openopps/pull_output.py` as the only pull renderer and atomic file writer. `[depends: O501] [writer: W-OUTPUT]`
- [x] 5.6 `B599` Run focused service/output tests and freeze the CLI-facing service contract. `[depends: S501-S503,O501,O502]`

Focused proof:

```bash
uv run pytest tests/unit/openopps/test_pull_service.py tests/unit/openopps/test_pull_output.py -q
```

## 6. B599 -> B699 public CLI and help

One exclusive `W-CLI` writer owns `src/openopps/cli.py` and shared CLI tests.

- [x] 6.1 `L601` Add integration tests for `jobs pull`, public provider detect/inspect/capabilities, every pull control, stable domain exits, and clean machine output. `[depends: B599]`
- [x] 6.2 `L602` Add root-dispatch regression tests for leading HTTPS URLs, root options, help/version/intro, empty invocation, malformed URLs, option values, and ordinary unknown commands. `[depends: B599]`
- [x] 6.3 `L603` Add `jobs pull <URL> --operation auto|list|get` plus direct/probe/scan/unlisted/save/raw/format/output/pager/cache/quiet/verbosity options, delegating to the frozen service and renderer. `[depends: L601] [writer: W-CLI]`
- [x] 6.4 `L604` Add public `providers detect`, `providers inspect`, and `providers capabilities` while preserving existing public and admin commands. `[depends: L601] [writer: W-CLI]`
- [x] 6.5 `L605` Add the narrow `OpenOppsRootGroup` URL rewrite without duplicating option parsing or changing other command meanings. `[depends: L602-L604] [writer: W-CLI]`
- [x] 6.6 `L606` Update semantic Typer help tests and the `cli-help` recipe only if its enumerated public surfaces require it. `[depends: L603-L605] [writer: W-CLI]`
- [x] 6.7 `B699` Run focused URL/provider CLI, helper-contract, existing integration CLI, smoke, and `just cli-help` gates. `[depends: L601-L606]`

Focused proof:

```bash
uv run pytest tests/integration/openopps/test_url_pull_cli.py tests/integration/openopps/test_provider_pull_cli.py -q
uv run pytest tests/integration/openopps/test_cli.py tests/unit/openopps/test_cli_helper_contracts.py tests/smoke/openopps/test_package.py -q
just cli-help
```

Pre-G3 contract-repair receipt (2026-08-31):

- Resolver tests now exercise canonical, alternate/metadata, Open Graph, and
  JSON-LD discovery branches plus static and runtime isolation from discovery
  and catalog mutation.
- Explicit-get board scans fail closed on incomplete, non-authoritative, and
  page-budget results before persistence; stale list-backed evidence cannot
  authorize a result, and stale native detail is inspection-only under
  `--no-save` with an essential stale warning.
- Terminal observability now carries payload-free resolver/provider/cache/
  persistence evidence on success and failure, including duplicate
  `remote_id` accounting and plugin HTTP calls made from a changed task
  context.
- URL-pull HTTP cache identity now separates resolver/provider phase,
  provider, resolved operation, retrieval mechanism, typed native target and
  route, membership scope, and per-request role while retaining shared schema,
  request, pagination, body, header, and credential dimensions.
- A broad pre-G3 URL-pull/CLI/provider/HTTP/plugin regression wave passed 699
  tests. Historical only: W6.1 later closed §7 (`0005`/`0006`, D712 opt-in
  `--save`) without treating this 2026-08-31 wave as that proof.

Optional live-smoke receipt (2026-08-31; non-mutating and not a substitute for
the automated provider matrix):

- The public Ashby sample posting from the accepted ergonomic reference returned
  exactly one normalized job with `provider=ashbyhq`, `operation=get`,
  `persisted=false`, and exit 0 through `jobs pull --no-save`.
- The matching public Ashby board returned 19 normalized jobs with
  `provider=ashbyhq`, `operation=list`, `persisted=false`, and exit 0 through
  `jobs pull --no-save`.
- Both output files passed structural JSON assertions. The isolated temporary
  SQLite database contained exactly `http_cache` and `http_cache_metadata`,
  proving that this smoke wrote no operational ledger tables while still
  exercising the independently governed shared cache.
- This receipt proves current availability only for those two Ashby requests at
  the stated time. It does not prove exhaustive live availability for every
  provider and does not weaken the mocked, fail-closed contract gates.

R1.04 blocked-join receipt (2026-09-01) is **historical**. It described Alembic
head `0004`, `0005` `.draft`, persist-unavailable `--save`, and HEAD `8c6a9b2`.
Those blockers are not current product truth.

W6.1 persist-join receipt (2026-09-11):

- `git rev-parse HEAD` → `d464e84348c15db0386e5dea94af7dbd8eaa9049`
  (`feat(cli): join URL-pull persistence behind opt-in --save`).
- `uv run alembic heads` → `0006_url_pull_runs (head)` only.
- `uv run python -c "import openopps; print(openopps.__version__)"` → `0.1.1`
  (`44a712acb8bbff94709c42fa150e0aeca28ce5ca`).
- `git show HEAD:src/openopps/cli.py` documents ephemeral default
  (`save: ... = False`, `--save/--no-save`, epilog “Pulls stay ephemeral by
  default; pass --save”). `PullProcessStatus.PERSISTENCE_FAILED = 9`.
- `git ls-tree -r --name-only HEAD -- src/openopps/alembic/versions/` includes
  `0005_update_snapshot_ledger.py` and `0006_url_pull_runs.py`; no `*.draft`.
- Package overlay-outcomes CLI and overlay 1813 remain HOLD; do not check them.
- W5.R2 persist-join independent review **PASS**ed on `d464e84` (2026-09-11).
- Docs `W801`/`W802`/`W804`/`W805`/`B899` stay open until the documentation commit.
  `W803` is an explicit Justfile no-change (mixed dirty HOLD unstaged).

## 7. External G3/L.1 -> B799 storage and migration join

Landed on `main`. Live Alembic head is `0006_url_pull_runs`. Persistence join is opt-in `--save` (not persist-by-default). Evidence below uses `git log` SHAs and command output; it does not use `goals/*`.

- [x] 7.1 `D701` Record evidence that G3 is closed, L.1 landed, all prior W-STORAGE writers stopped, and the current linear Alembic head is known. `[external-gate: G3,L.1]` Evidence: `git log -1 --format='%H %s' 2e659c1afead081973da97485021eb67c8a328a3` → `feat(discovery): reserve b699 identity closure 20260906`; `git log -1 --format='%H %s' 748397265f729cc761fc258055f279c3264b4131` → `feat(discovery): apply b699 identity closure 20260906`; `git log -1 --format='%H %s' 414d58281b6ff52c7a5d0cd64cea3fb79b1cfde4` → `feat(storage): activate frozen update-snapshot ledger 0005`; `uv run alembic heads` → `0006_url_pull_runs (head)`.
- [x] 7.2 `D702` Reserve the next linear URL-pull migration and exact path ownership without overlapping L.2 or O.1. `[depends: D701] [writer: W-STORAGE]` Evidence: `git log -1 --format='%H %s' d8e70fce8357a7d5d2fec3a077f9568a2f7e1cd7` → `feat(storage): add url-pull runs and membership-scoped persistence`; `git show HEAD:src/openopps/alembic/versions/0006_url_pull_runs.py` has `revision: str = "0006_url_pull_runs"` and `down_revision: str | None = "0005_update_snapshot_ledger"`.
- [x] 7.3 `D703` Add migration red tests for `url_pull_runs`, membership scopes/defaults, upgrade/downgrade, update-snapshot copies, and managed-table manifests. `[depends: D702]` Evidence: `d8e70fce` added `tests/integration/openopps/test_migrations.py` (+206) and `tests/integration/openopps/test_url_pull_storage.py`; `uv run pytest tests/integration/openopps/test_migrations.py tests/unit/openopps/test_update_snapshot.py tests/integration/openopps/test_url_pull_storage.py tests/integration/openopps/test_storage_export.py -q` → `Pytest: 75 passed`.
- [x] 7.4 `D704` Add `UrlPullRunRow` and bounded sanitized audit fields separate from `job_sync_runs` and O.1 `sync_invocations`. `[depends: D703] [writer: W-STORAGE]` Evidence: `d8e70fce` `src/openopps/models.py` (+159); `git grep -n UrlPullRunRow HEAD -- src/openopps/models.py src/openopps/storage.py`.
- [x] 7.5 `D705` Add deterministic reserved `url-pull` source/board/route identity with equivalent-URL convergence, punctuation distinction, no domain/catalog mutation, selector exclusion, and collision rejection. `[depends: D703] [writer: W-STORAGE]` Evidence: `d8e70fce` `src/openopps/url_pull_identity.py` (`URL_PULL_RESERVED_SOURCE_KEY = "url-pull"`, SHA-256 digest, `url_pull_board_key`); `fb80ec89d83868e7fdc7d81d4254acb777684032` `fix(ingest): exclude url-pull routes from unscoped jobs sync`; `git grep -n url_pull HEAD -- src/openopps/route_registry.py`.
- [x] 7.6 `D706` Add membership scope to jobs and list runs with safe migration defaults and listed/direct-only/all-public reconciliation predicates. `[depends: D703] [writer: W-STORAGE]` Evidence: `d8e70fce` storage/models membership columns and `0006_url_pull_runs` ALTERs; same 75-test command as D703.
- [x] 7.7 `D707` Add explicit begin/fail/complete URL-pull audit APIs and link list to its ordinary job-sync lifecycle or get to its exact job/version. `[depends: D704-D706] [writer: W-STORAGE]` Evidence: `git grep -n 'def begin_url_pull_run\|def fail_url_pull_run\|def apply_url_pull_list\|def apply_url_pull_get' HEAD -- src/openopps/storage.py` on `d8e70fce`.
- [x] 7.8 `D708` Implement complete-before-apply atomic list persistence; inject early/late failures and prove no lifecycle/current-version drift. `[depends: D707] [writer: W-STORAGE]` Evidence: `d8e70fce` `_apply_url_pull_list_atomic`; `test_url_pull_storage.py` in the 75-passed command.
- [x] 7.9 `D709` Implement point-get persistence for exactly one posting with no `job_sync_run`, route reconciliation, generic sync invocation, or unrelated closure. `[depends: D707] [writer: W-STORAGE]` Evidence: `d8e70fce` `apply_url_pull_get` / `_apply_url_pull_get_atomic`; same storage tests.
- [x] 7.10 `D710` Prove `--no-save` leaves all operational tables unchanged while normal cache writes remain independently governed. `[depends: D708,D709]` Evidence: `d464e84348c15db0386e5dea94af7dbd8eaa9049` wires `NullPullPersistence()` when `save` is False; `git show HEAD:src/openopps/pull_service.py` `persist: bool = False`; `test_no_save_port_does_not_call_store_apply` in the 75-passed suite.
- [x] 7.11 `D711` Update snapshot schema revision/copy models/operational and managed table manifests, with a matching URL-pull copy, in the same serialized migration wave. `[depends: D704-D706] [writer: W-STORAGE]` Evidence: `414d5828` activated `0005_update_snapshot_ledger`; `d8e70fce` extended update-snapshot copies; `git log -1 --format='%H %s' 3737df79e41b264f2276022c773ccc71cb29b8c8` → `test(storage): retarget kaggle and wheel gates to alembic 0006`.
- [x] 7.12 `D712` Join the real persistence port to the pull service and CLI only after storage/migration tests pass. `[depends: D708-D711,B699] [writer: W-SERVICE]` Evidence: `d464e84348c15db0386e5dea94af7dbd8eaa9049` `feat(cli): join URL-pull persistence behind opt-in --save`; `PullService.from_settings(..., persist=False)` uses `OpenOppsStorePullPersistence` only when `persist` is true; CLI `--save/--no-save` default False; help does not advertise persist-by-default.
- [x] 7.13 `B799` Run URL-pull storage, migration, update-snapshot, storage/export, ingest, and conservation regression suites. `[depends: D701-D712]` Evidence: `uv run pytest tests/integration/openopps/test_url_pull_storage.py tests/integration/openopps/test_storage_export.py tests/integration/openopps/test_migrations.py tests/unit/openopps/test_update_snapshot.py -q` → `Pytest: 75 passed`; `uv run pytest tests/integration/openopps/test_ingest_sync_conservation.py -q` → `Pytest: 4 passed`. Dirty leftover `tests/integration/openopps/test_cli.py` overlay-outcomes was not used as proof.

Focused proof:

```bash
uv run pytest tests/integration/openopps/test_url_pull_storage.py tests/integration/openopps/test_storage_export.py -q
uv run pytest tests/integration/openopps/test_migrations.py tests/unit/openopps/test_update_snapshot.py -q
uv run pytest tests/integration/openopps/test_ingest.py tests/integration/openopps/test_ingest_sync_conservation.py -q
```

## 8. B699 + B799 -> B899 docs, agent guidance, and workflow parity

Docs-after-join stay open in this OpenSpec commit except the Justfile no-change receipt. `W801`/`W802` land in the separate documentation commit. Overlay-outcomes CLI and overlay 1813 remain HOLD.

- [ ] 8.1 `W801` Update README and CLI/provider/operations/configuration/data-model/contributor docs with commands, support tiers, evidence, persistence/no-save/cache semantics, identity, raw/machine output, and failures. `[depends: B699,B799] [writer: W-DOCS]`
- [ ] 8.2 `W802` Update root, package, and web `AGENTS.md` files where module ownership, public surfaces, migrations, or validation commands changed. `[depends: W801] [writer: W-DOCS]`
- [x] 8.3 `W803` Update the Justfile and matching GitHub Actions job together only if the canonical validation surface changes; otherwise record an explicit no-change parity check. `[depends: B699,B799] [writer: W-DELIVERY]` Evidence: W6.1 does not stage `Justfile`. `git diff -- Justfile` is mixed HOLD (`security-audit-web` and leftover recipe hunks), integrator-queued. Canonical URL-pull validation already lives in committed pytest/OpenSpec; publication workflow landed in `32a26bb3bbd83b420eff61c86690122b6cd56119` (`ci(release): add exact-SHA publication workflow and artifact gates`). No new just recipe is required for D712.
- [ ] 8.4 `W804` Invoke `/docs-steward` after public API/file/schema/agent-guidance edits and record the skill's validation or explicit supported skip result without installing missing tooling. `[depends: W801-W803]`
- [ ] 8.5 `W805` Regenerate only package-derived docs data proven affected; do not regenerate Kaggle or committed search artifacts without a direct generator-contract change. `[depends: W804] [writer: W-GENERATED]`
- [ ] 8.6 `B899` Run docs data generation, type checks, build, tests, strict change validation, and applicable local/CI parity gates. `[depends: W801-W805]`

Docs proof:

```bash
cd web
pnpm data:generate
pnpm types:check
pnpm build
pnpm test
cd ..
rtk npx -y @fission-ai/openspec@1.6.0 validate unified-cli-job-pulls --strict
```

## 9. B899 -> B999 fact closure and full assurance

Full-assurance tasks wait on `B899`. Do not close `V901`-`V906` or `B999` while storage/docs joins are open.

- [ ] 9.1 `V901` Produce a fact-to-test receipt showing all 24 accepted facts have at least one passing automated assertion. `[depends: B899]` `[blocked-join: B899]`
- [ ] 9.2 `V902` Run focused Ruff and `ty` over affected package surfaces. `[depends: V901]`
- [ ] 9.3 `V903` Run the complete Python test suite and coverage separately. `[depends: V901]`
- [ ] 9.4 `V904` Run lock, CLI help, strict all-OpenSpec, and repository aggregate CI gates. `[depends: V902,V903]`
- [ ] 9.5 `V905` Run `git diff --check`, inspect the final worktree, preserve unrelated untracked work, and report source/focused/full/docs/OpenSpec/CI evidence as distinct layers. `[depends: V904]`
- [ ] 9.6 `V906` Obtain independent correctness/security review of resolver safety, provider authority, stdout isolation, persistence atomicity, and migration ownership; reconcile every material finding. `[depends: V905]`
- [ ] 9.7 `B999` Close only when every accepted fact passes, all external joins are complete, no required work remains, and mocked tests are not mislabeled as live upstream proof. `[depends: V901-V906]`

Full proof:

```bash
uv run ruff check src/openopps
uv run ty check
uv run pytest
uv run pytest --cov=openopps --cov-report=term-missing
uv lock --check
just cli-help
rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict
just ci
git diff --check
```

## Notes — joins (W6.1)

| Join | Barrier | Blocks | Status |
| --- | --- | --- | --- |
| Storage gate | G3 reservation `2e659c1` + apply `7483972`; L.1 `414d5828` | `D701` | landed |
| L.1 / URL-pull schema | Live `uv run alembic heads` = `0006_url_pull_runs`; `0005` is the ledger, not `.draft` | `D702`-`D712`, `B799` | landed |
| Unified persistence | D712 `d464e84` opt-in `--save` (default False, exit 9) | docs `W801`+ | landed for storage/CLI; docs still open |
| Justfile | Mixed dirty HOLD (`security-audit-web`) | W6.1 staging | no-change / integrator-queued |
| Live authority | Workers upload/deploy, GitHub Release, PyPI, `github-release`/`pypi` environments, hosted-alpha/H0, v7 7.6, source-policy 1780 grants, exact-SHA CI on a pushed SHA | W11 / `F1207` | **NO-GO** (unchecked) |

Kaggle live dataset identity is v76 (not v33/v34). This receipt does not mutate Kaggle. Overlay 1813 / overlay-outcomes CLI stay HOLD.

## Stop and preservation rules

- Do not flip CLI persistence to persist-by-default. `--save` stays opt-in; `--no-save` is the ephemeral alias; HTTP cache stays independent.
- Stop live Workers upload/deploy, Kaggle mutation, PyPI/GitHub Release publication, hosted-alpha, and v7 7.6 from this change. Source-policy 1780 stays blocked pending written grants.
- Stop successful list persistence on incomplete pages, count mismatch, duplicate/repeated continuation, unsafe redirect, size/budget exhaustion, required-detail failure, or non-authoritative evidence. Never persist partial results as a successful snapshot.
- Stop exact get on lost identity, zero/multiple matches, unsupported native operation with scan disabled, or incomplete/non-authoritative fallback.
- Never use URL pulling to invoke scout acceptance, add/promote/activate a source, mutate packaged/effective catalogs, call authenticated ATS APIs, deploy, publish, or perform Git mutation.
- Serialize shared files and generated surfaces. Do not stage, clean, edit, or remove the pre-existing `.grok/`, `.playwright-mcp/`, or `inspect-shots/` paths.
