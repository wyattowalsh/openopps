## Why

OpenOpps can ingest thousands of packaged sources and public job-provider routes, but source expansion remains manually assembled and has no canonical intake contract. Running discovery inside the daily snapshot would couple uncertain external search latency, rate limits, false positives, and rights review to deterministic ingestion and publication.

The repository also lacks a digest-addressed candidate/evidence format, objective cross-channel liveness and support criteria, exact approved-catalog binding for scheduled snapshots, and a deterministic promotion preview. Without those boundaries, a newly observed URL could be mistaken for an approved source, absence of a policy denial could be mistaken for permission, or catalog drift could change a scheduled run after it begins.

## What Changes

- Add one portable agent-primary scout skill and deterministic enumerators for official catalogs and documentation, public code and datasets, search APIs, and targeted employer or ATS queries. The skill supplies suggestions; only an isolated credential-free scout/validator process can admit them.
- Give every channel explicit query, request, response-byte, candidate, concurrency, retry, and wall-clock budgets.
- Normalize and deduplicate source and board candidates while retaining every provenance edge and unresolved identity collision.
- Emit canonical, digest-addressed quarantine bundles containing candidate records, bounded evidence, run completeness, failures, and budget accounting.
- Define objective, testable evidence for candidate liveness and support.
- Add read-only advanced CLI commands for scouting and offline bundle verification.
- Add a deterministic, dry-run-first maintainer promotion preview plus a separately invoked, exact-reviewed, owned-path-only local apply operation. Apply never stages, commits, pushes, publishes, or deploys.
- Bind scheduled daily snapshots to one private `ApprovedIngestionSelectorEnvelope` and catalog-content fingerprint captured before network work; this is distinct from the v7 public `SourceSelector`.
- Add fixture replay, adversarial validation, portable-skill evals, Justfile, CI, documentation, and nested-agent instruction coverage.
- Keep unsanitized discovery artifacts in maintainer-controlled private storage and out of public GitHub Actions artifacts; public CI replays only committed sanitized redistribution-safe fixtures. Do not change public v7 release formats or create a same-run activation path.
- Defer route-retirement implementation until permanent-absence and persisted-ownership decisions are resolved.

## Capabilities

### New Capabilities

- `source-discovery`: Independent bounded scouting, portable-skill confinement, hostile-network handling, canonical quarantine bundles, candidate lifecycle, and deterministic reviewed promotion.

### Modified Capabilities

- `provider-coverage`: Evaluate quarantined source, board, and provider candidates with objective liveness/support evidence and baseline-bound coverage deltas.
- `provider-ingestion`: Pin scheduled runs to one private approved-ingestion selector envelope and conserve exact source/route accounting, including cancellation and unstarted work, without changing explicit local-custom behavior or the v7 public selector.
- `cli-domain`: Add advanced read-only scout and offline verifier commands while keeping promotion separate.
- `performance-observability`: Add finite discovery budgets, host-aware transport accounting, low-cardinality metrics, and benchmark-first performance evidence.
- `release-workflows`: Add deterministic local/offline-CI gates, a private scheduler-agnostic live-scout runbook with no activation, dry-run-first promotion and durable replay protection, documentation parity, and layered release assurance.

## Impact

- New isolated discovery models, schemas, transport, channel enumerators, normalizers, quarantine writer/verifier, promotion renderer, and approved-selector logic under `src/openopps/`.
- Advanced Typer commands under `admin sources`, plus semantic CLI tests.
- A portable repository-owned source-scout skill with Codex, Cursor, and Grok Build validation/eval coverage; its output remains untrusted data.
- New sanitized fixtures, benchmark corpus, JSON schemas, Justfile recipes, and least-privilege offline GitHub Actions validation. Live scout bundles remain outside public CI and public artifacts.
- Updates to README, web MDX, configuration references, contributor/operations docs, generated data where promotion is exercised, and nested `AGENTS.md` instructions.
- The archived `source-integrity-production-readiness` change supplies the canonical packaged-catalog and stored-versus-packaged precedence contract.
- The active `production-hardening-static-data-v7` change retains exclusive ownership of ingestion/providers, cache/storage/migrations, public v7 manifests, source-policy evidence/decision formats, the public `SourceSelector`, Kaggle and Cloudflare publication, shared generated data, shared Just/workflow surfaces, archives, and destructive cleanup. This change reads and hashes those resources only until an explicit `XV7` path-level ownership handoff closes.
- Discovery owns a distinctly named supplementary positive-policy decision, append-only promotion-decision ledger, and private `ApprovedIngestionSelectorEnvelope`; none changes or aliases the v7 policy format or public selector.
- No authenticated scraping, browser automation, anti-bot bypass, recursive crawler, dynamic plugin/dependency loading, operational SQLite mutation, Git mutation, publication, deployment, or route retirement is added to scouting.

## Acceptance summary

1. Every discovery channel stops within explicit deterministic budgets and conserves planned work across success, blocked, rate-limited, timed-out, failed, cancelled, and unstarted terminal classes.
2. A completed quarantine bundle has canonical bytes, an exact safe member set, bounded evidence, sanitized provenance, a non-self-referential root digest, and deterministic replay from captured fixtures.
3. Scouting and verification cannot mutate runtime registries, SQLite, tracked catalogs, generated public data, release channels, or deployment state.
4. Candidate liveness and support decisions are reproducible from dated evidence; ambiguous, incomplete, unsupported, or policy-unresolved candidates remain quarantined.
5. Promotion preview accepts one exact bundle digest, produces an idempotent repository diff, reuses existing catalog fingerprint and read-only v7 policy gates, refuses unresolved collisions or eligibility, and cannot substitute candidate/agent/CI state for a separate maintainer-authored review decision and repository review. A durable append-only ledger and reachable-history audit reject replay after rollback.
6. A scheduled daily snapshot records and consumes one private approved source-key envelope and catalog-content fingerprint; newly discovered candidates and mid-run catalog changes cannot affect that run, and checkout revision is recorded separately to avoid a tracked-file self-reference.
7. The portable skill is advisory and the surrounding harness remains outside OpenOpps' enforcement boundary. Only suggestions accepted by the isolated deterministic validator can enter quarantine or promotion, and identical accepted fixtures produce identical artifacts across supported harnesses.
8. Focused unit, integration, CLI, fixture-replay, adversarial, performance, wheel, documentation, strict OpenSpec, and local/CI parity gates pass.
