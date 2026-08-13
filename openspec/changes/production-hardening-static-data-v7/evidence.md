# Production-hardening evidence ledger

This ledger is the accounting source for the implementation swarm. A finding is closed only when its implementation task and named proof both pass. `repo-verified` means the repository implementation and named local proof are present. `proof-open` means implementation exists but a required checkout or release condition is still unproven. `live-gated` means repository preparation can finish, but the result requires credentials, external mutation, push authority, or destructive approval. No repository-only state implies a live publication or production-readiness claim.

| Finding | Priority | Owner surface | Remediation tasks | Required proof | Reconciled state (2026-08-13) |
| --- | --- | --- | --- | --- | --- |
| Truncated Rippling, Workday, WPJobManager, or Bamboo snapshots can close unseen jobs | P1 | ingestion | 0.3, 1.1-1.5 | adversarial pagination tests; existing rows remain open | repo-verified |
| Yield-then-raise source sync advances freshness and suppresses retry | P1 | ingestion | 0.3, 1.6 | two-run partial-generator integration test | repo-verified |
| Ingest duplicates inverse stored/catalog precedence | P1 | ingestion | 1.7 | config-drift integration test using canonical resolver | repo-verified |
| Access/schema HTTP failures declassify routes and may close jobs | P1 | ingestion | 1.8 | 400/401/403/429 disposition matrix | repo-verified |
| Failed job fetches are absent from run history and writes ignore batch contract | P2 | persistence | 1.9-1.11 | pre-network failure ledger and multi-batch tests | repo-verified |
| Cache persists raw bodies and query credentials | P1 | cache/http | 0.4, 1.12-1.13 | supported credential-flow SQLite content scan | repo-verified |
| Cancelling one waiter cancels shared coalesced HTTP work | P2 | cache/http | 1.14 | two-waiter cancellation race test | repo-verified |
| Raw-only drift hydrates a stale version payload hash | P2 | storage | 1.15 | raw A-to-B current/version hash test | repo-verified |
| `list_jobs` performs N+1 hydration | P2 | storage | 1.16, 1.19 | constant-bounded SELECT count at multiple N | repo-verified |
| Database URL validation overclaims support and memory SQLite fails | P2 | settings/storage | 1.17 | accepted/rejected URL matrix and initialization tests | repo-verified |
| Export replacement is non-atomic | P2 | export | 1.18 | injected writer failure preserves prior target | repo-verified |
| Artifact generation deletes and rewrites the live tree in place | P1 | artifacts | 0.5, 2.3, 2.9 | injected failure preserves prior release | repo-verified |
| Artifact manifest lacks exact hashes, provenance, root, promotion, and rollback | P1 | artifacts | 2.1-2.3, 2.7, 2.9 | bit-flip/exact-set/determinism suite | repo-verified |
| Public snapshot is stale without an enforced freshness SLO | P1 | artifacts | 2.5 | warn/block/override tests and visible degraded metadata | repo-verified gate; canonical release freshness open |
| Catalog rights/attribution states do not gate public publication | P1 | governance | 2.6-2.8 | full-catalog dry-run report; fail-closed fixtures | repo-verified gate; canonical release blocked (688/695 sources) |
| Runtime staging permits arbitrary recursive deletion | P1 | Kaggle | 3.1 | adversarial path/symlink/ownership tests | repo-verified |
| Runtime package manifest authenticates itself | P1 | Kaggle | 3.2 | whole-manifest substitution and exact-set tests | repo-verified |
| Scheduled Kaggle runtime installs mutable source and tooling | P1 | Kaggle | 3.3 | immutable source/wheel/lock provenance test | repo-verified |
| Credentialed Just recipes interpolate shell source | P1 | operations | 3.4 | metacharacter argv dry-run tests | repo-verified |
| Kaggle publication lacks transactional promotion/readback/rollback ledger | P1 | Kaggle/operations | 3.5 | dry-run state-machine tests; live exact-version evidence | repo-verified locally/live-gated |
| One-shot migration programs remain broadly executable | P3 | operations | 3.6 | exact-fingerprint rejection tests | repo-verified |
| Search, details, metadata, sitemap, and builds use inconsistent origins | P1 | web data | 4.1-4.3 | no-local-production-tree build and route suite | repo-verified |
| Production search constructs/scans the full index server-side | P1 | web search | 0.6, 4.4-4.6 | frozen semantic corpus and reproducible resource benchmark | repo-verified |
| Local state performs persistence inside React updates and can erase on import failure | P1 | web local | 4.7-4.8 | reducer-purity, quota, abort, malformed replace tests | repo-verified |
| Partial saved-search membership can become an incorrect review baseline | P2 | web local | 4.9 | partial-page/release-change reconciliation tests | repo-verified |
| Offline readiness and telemetry exceed privacy/resource boundaries | P2 | web product | 4.10 | quota/integrity/privacy schema tests | repo-verified locally; disconnected production journey open |
| Structured JobPosting can publish invalid data | P2 | SEO | 4.11 | disabled-by-default and normalized-readiness tests | repo-verified |
| Web lint, error states, accessibility, and browser coverage are incomplete | P2 | web quality | 4.12 | zero lint errors; Chromium/Firefox/WebKit journeys | repo-verified |
| Static delivery has no proven full-corpus free deployment or rollback | P1 | release | 5.1-5.8 | actual Workers Free upload/hash/promote/rollback/re-promote evidence | repo-verified local tooling/live-gated |
| Next/web and Python dependencies include known advisories | P1 | dependencies | 6.1 | current production dependency audits | repo-verified |
| Dependabot and Renovate overlap on web npm | P2 | automation | 6.2 | ownership config assertion | repo-verified |
| `ty` is red and not a canonical gate | P2 | typing | 6.3 | zero scoped diagnostics; local/CI gate | repo-verified |
| Supported Python and lowest-dependency contracts are untested | P2 | CI | 6.4 | 3.12/3.13/3.14 and lowest-direct lanes | repo-verified; exact-SHA origin CI verified at `7f772ac` |
| CI tools/timeouts/credential persistence and local parity are incomplete | P2 | CI | 6.5-6.6 | workflow policy tests and one command graph | repo-verified graph |
| Docs/config retain pre-`web/`, manifest-v4, and environment-key drift | P2 | docs | 6.7 | link/recipe/env/schema assertions and docs build | repo-verified |
| Production readiness lacks exact-SHA origin/deployment smoke | P1 | release | 6.8-6.9 | local gates plus exact-SHA CI and both deployments | web release verified at `7f772ac`; Workers/v7 release live-gated |
| Generated production data bloats Git and history | P1 | cleanup | 7.1-7.7 | external recovery, ordinary removal, clean clone; separately approved rewrite | untouched/live-gated |

## Reconciliation evidence (2026-08-13)

Repository proof run against this working tree:

- `uv run pytest -q tests/integration/openopps/test_ingest.py tests/integration/openopps/test_storage_export.py tests/unit/openopps/test_providers.py tests/unit/openopps/test_http.py tests/unit/openopps/test_cache.py tests/unit/openopps/test_settings.py` — 245 passed.
- `uv run pytest -q tests/unit/openopps/test_docs_search_release.py tests/unit/openopps/test_docs_search_delivery.py tests/unit/openopps/test_docs_search_index.py tests/unit/openopps/kaggle/test_publication.py tests/unit/openopps/kaggle/test_runtime_manifest.py tests/unit/openopps/test_ci_governance.py tests/integration/openopps/test_migrations.py -k 'not generated_search_index_artifact_matches_local_db_when_available'` — 188 passed, 1 deliberately deselected local-v6 parity probe.
- `uv run pytest --cov=openopps --cov-report=term-missing -k 'not generated_search_index_artifact_matches_local_db_when_available'` — 841 passed, 1 deliberately deselected local-v6 parity probe, and 91.82% total coverage against the unchanged 90% gate.
- `PYTEST_ADDOPTS="-k 'not generated_search_index_artifact_matches_local_db_when_available'" just test-lowest-direct` — 841 passed and 1 deliberately deselected under the independently resolved lowest-direct environment, including Typer 0.16.0 and Click 8.3.0.
- `cd web && pnpm test` — 47 files and 295 tests passed. `pnpm types:check`, `pnpm lint`, and `NEXT_TELEMETRY_DISABLED=1 pnpm build` also passed; the current request-rendered metadata-route build generated 32/32 static pages. `just web-function-trace-check` reported 106 traced files, 1,788,499 bytes, and zero forbidden or missing paths. The focused offline-runtime lifecycle suite passed 3/3, and the prior full production Playwright run passed 45/45 journeys across Chromium, Firefox, and WebKit.
- Two independent isolated checkouts excluded `web/public/data/openopps-search/` before build, generated a rights-approved v7 fixture through the production generator, and embedded the HTTPS v7 origin in both server and browser build configuration. Both production builds passed 32/32 routes. The first proof verified the legacy manifest returned 404, v7 channel/detail/root sitemap/robots/job-sitemap routes succeeded, malformed and empty sitemap pages returned 404, and one cold `/jobs/sitemap/0.xml` request read the mutable channel exactly once. Chromium, Firefox, WebKit, and mobile Chromium then passed 4/4 v7 detail/sitemap/browser-worker journeys with immutable release reads, no legacy reads, and no `/api/jobs/search` requests; the independent reproduction also passed 4/4 in 36.9 seconds.
- `rtk npx -y @fission-ai/openspec@1.6.0 validate production-hardening-static-data-v7 --strict` and `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict` — the change was valid and all 12 OpenSpec items passed.
- Approved push SHA `7f772ac54424968bc91857f8ae7de7509ba31321` completed GitHub Actions `CI` run `31678891703` with every push-required job green, including the wheel SBOM/attestation; PR-only dependency review was correctly skipped. GitHub production deployments `5883998037` and `5884019875` correspond to Vercel deployments `dpl_3s5t3RSKU55MQ2ja6w36ydsbBqQf` and `dpl_AdiJrvEwu2msPU3Td5kzweBfyefR` at that exact SHA. The stable aliases `https://www.openopps.dev` and `https://openopps-hla2.vercel.app` resolved to those deployments and passed GET smoke for home, Explorer, docs, public-data release docs, LLM text, robots, root and job sitemaps, committed v6 manifest, job detail, canonical redirects, and the fail-closed `/api/jobs/search` boundary.
- A read-only policy report using the committed search-manifest source facets and current local SQLite metadata found 695 included source keys: 7 publication-allowed and 688 blocked for missing rights state. The committed manifest reports `snapshotAt` `2026-07-02T08:33:21.099662Z`. This proves the gates fail closed; it does not approve the full catalog or establish freshness for a final publication.

Known open proof and authority boundaries:

- The ignored local SQLite snapshot is deliberately not treated as canonical release input and is not in parity with the committed v6 artifacts; its exact parity probe remains open while the clean-checkout CI form skips that unavailable maintainer-only input. The 553-MiB committed v6 production tree has not been removed, but isolated production build, server-route, and four-browser proofs now pass with that tree physically absent.
- Local delivery tooling can verify/stage a dual-release graph and construct a deterministic recovery archive, but no actual full-corpus Workers Free upload, remote readback, atomic promote/rollback/re-promote, GitHub Release publication, or public-data attestation has occurred.
- Exact-SHA GitHub CI, both Vercel production deployments, and public-route smoke are recorded above for `7f772ac54424968bc91857f8ae7de7509ba31321`; this does not prove the separate Workers Free v7 upload/readback/cutover, GitHub Release archive, or public-data attestation gates. No ordinary v6-tree deletion, mirror bundle, ref inventory, history rewrite, or force-push was attempted.

## One-writer and barrier map

| Barrier | Single-writer surfaces | Opens when |
| --- | --- | --- |
| B0 contract | this OpenSpec change | strict validation and ledger review pass |
| B1 Python integration | `ingest.py`; cache/http/storage; migrations | all focused Python lanes pass and shared APIs reconcile |
| B2 artifact contract | generator, verifier, v7 schema | v7 fixtures and destructive-failure tests pass |
| B3 web data | shared snapshot/search types and client | B2 schema freezes |
| B4 operations | Kaggle `_core.py`, runtime manifest, Justfile, workflows | B1/B2 public contracts freeze |
| B5 generated data | candidate/release output directories | exactly one generator owns the tree; no concurrent writer |
| B6 release | staging/prod upload, channel mutation, archive | all local gates pass and exact live authority is present |
| B7 cleanup | ordinary removal then optional history rewrite | B6 restore/rollback passes; history rewrite has separate approval |

## Swarm accounting and recovery

- Register each lane before dispatch and mark it in progress only after its owner confirms scope.
- Reconcile all results before opening the next barrier: verified success, explicit read-only duplicate skip, or recovered failure with a replacement owner.
- Resume a cleanly recoverable lane once; reassign after a second failure; stop for user authority on live, destructive, credentialed, or scope-expanding blockers.
- Integrators inspect the combined diff and rerun focused tests; implementers cannot self-certify a cross-surface barrier.
