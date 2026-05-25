# OpenOpps Module Audit

First-slice audit for the approved v0.1 overhaul plan. The goal is to keep `src/openopps/` modules cohesive while adding migrations, generated docs data, and CI/tooling.

| Module              | Responsibility                                                         | Decision         | Rationale                                                                                                                        |
| ------------------- | ---------------------------------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py`       | Package metadata surface                                               | Keep             | Lightweight package boundary.                                                                                                    |
| `cache.py`          | SQLite-backed HTTP JSON response cache                                 | Keep             | Live source-sync evidence shows strong repeated-run value; keep it optional and separate from Alembic-managed app SQLite.        |
| `cli.py`            | Typer command wiring and output-mode routing                           | Keep             | Correct boundary for command composition; future progress UX belongs here or in explicit progress hooks.                         |
| `coverage.py`       | Offline persisted-data coverage and provider adoption audit            | Keep             | Uses stored SQLite evidence only; should not merge with live health or export serialization.                                     |
| `docs_data.py`      | Deterministic package-derived metadata for the docs site               | Move to script   | Docs-only generated metadata belongs with `scripts/generate_docs_data.py` instead of the installable CLI package.                |
| `enrichment.py`     | Deterministic normalized job enrichment                                | Keep             | Isolated transformation logic.                                                                                                   |
| `examples.py`       | Deterministic demo data                                                | Move to examples | Demo-only synthetic data belongs under `examples/examples.py`; the CLI loads it lazily for `examples seed`.                      |
| `export.py`         | JSONL/CSV/Parquet serialization                                        | Keep             | Serialization boundary; do not absorb coverage analysis.                                                                         |
| `health.py`         | Live source/provider health checks                                     | Keep             | Network side-effect boundary with a different failure domain than coverage.                                                      |
| `http.py`           | Shared HTTPX client and retry/cache request behavior                   | Keep             | Provider adapters depend on this for consistent HTTP behavior, request dedupe, explicit refresh behavior, and cache integration. |
| `ingest.py`         | Source and job sync orchestration                                      | Keep             | Coordinates providers, storage, metrics, and request dedupe.                                                                     |
| `intro.py`          | Optional CLI intro animation                                           | Keep             | Isolated UX concern; must stay off JSON/machine paths.                                                                           |
| `main.py`           | Module execution entry point                                           | Keep             | Thin console entry support.                                                                                                      |
| `metrics.py`        | Sync/runtime metrics structures                                        | Keep             | Cross-command metrics boundary.                                                                                                  |
| `migrations.py`     | Programmatic Alembic migration and stamping helpers                    | Keep             | Durable app SQLite schema migration boundary; does not own optional HTTP cache schema.                                           |
| `models.py`         | Pydantic domain models and normalized validation helpers               | Keep             | Source of truth for records and URL/host validation.                                                                             |
| `plugins.py`        | Entry-point plugin loading and conflict reporting                      | Keep             | Trusted plugin execution boundary.                                                                                               |
| `route_probe.py`    | Live route probing and optional persistence                            | Keep             | Network side-effect layer; pure readiness checks moved out.                                                                      |
| `route_registry.py` | Durable route registry selection from stored records                   | Keep             | Programmatic selection boundary; should depend only on pure route helpers and storage.                                           |
| `route_select.py`   | Pure provider filter, route readiness, request-key, and dedupe helpers | Keep and expand  | Owns side-effect-free route logic used by registry, coverage, health, and probe.                                                 |
| `settings.py`       | `OPENOPPS_` runtime configuration                                      | Keep             | Pydantic Settings boundary.                                                                                                      |
| `storage.py`        | Durable app SQLite persistence                                         | Keep             | Alembic will target this schema, not the optional HTTP cache.                                                                    |
| `url_validation.py` | Re-export shim for model validation helpers                            | Delete           | All validation helpers now live in `models.py`; no compatibility evidence requires the shim.                                     |
| `utils.py`          | Small generic identifiers/string helpers                               | Keep             | Shared pure helpers.                                                                                                             |

## Boundary Decisions

- Keep `coverage.py`, `health.py`, and `export.py` separate: offline analysis, live probing, and serialization have distinct failure modes.
- Keep `route_probe.py` side-effectful and move reusable readiness logic to `route_select.py`.
- Remove `scripts/probe_provider_routes.py`; the CLI command has equivalent options and a richer output-mode surface.

## Cache Decision Gate

Decision: keep the HTTP response cache for v0.1, but keep it separate from durable app SQLite migrations.

Evidence gathered on 2026-05-21 with a temporary SQLite/cache path and `uv run openopps sources sync a16z --no-db --page-size 25 --metrics-json`:

- Fresh run with `--refresh-cache`: 31 pages, 766 boards, 547 provider hints, `elapsedSeconds=21.18601312499959`.
- Immediate cached run without refresh: same 31 pages, 766 boards, 547 provider hints, `elapsedSeconds=0.28579250001348555`.
- Cache status after the run: 31 fresh `http-json` records.
- Validator availability in the sampled cache DB: 31 of 31 records had `ETag`; 0 had `Last-Modified`.
- Existing tests cover deterministic keying, TTL expiry, refresh bypass, conditional `304` reuse, stale-on-error eligibility, in-flight duplicate suppression, namespace purge, JSON cleanliness, and route-probe cache reuse.

The cache should stay enabled by default for v0.1 because it materially reduces repeated upstream traffic while preserving explicit refresh semantics. Keep Alembic focused on durable app SQLite only; the optional HTTP cache remains self-initializing in `cache.py`.
