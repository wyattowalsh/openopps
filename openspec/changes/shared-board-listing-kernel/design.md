## Context

`unified-cli-job-pulls` added explicit URL-list hooks without changing `fetch_jobs` (closed T105/G302). Catalog sync still uses a second listing walk: Lever is unpaginated, Teamtailor reads one RSS page, Greenhouse ignores advertised counts, and pull normalizes onto a synthetic `source_key="url-pull"` board whose `key` is the ATS token. `ProviderListResult` requires `job.board_key == board_identity`. `to_job_fetch_result()` does not rebind. Persisting those jobs would mint a second identity namespace and `close_missing` real catalog rows.

This change added no Alembic revision. Live product head after W6.1 is `0006_url_pull_runs` (`uv run alembic heads`); `0005_update_snapshot_ledger` is the landed ledger, not a `.draft`. Do not describe `0004` as the current head. Exclusive lanes still own `cli.py`, `models.py`, `storage.py`, `ingest.py`, `source_policy.py`, and `discovery/**` for later writers.

## Goals / Non-Goals

**Goals:**

- One membership kernel per adopted board provider, with identity bind after evidence is complete.
- Catalog sync inherits truthful pagination and advertised-count fail-closed where the URL-list hook already has that contract.
- Preserve per-provider ingest identity (Teamtailor guid, Ashby listing id, Rippling/Workday empty-detail fallback).
- Keep `check_jobs` cheap. Keep plugins that only implement `fetch_jobs` syncable.
- SSOT the overlay source key and attach overlay/household ATS routes via `detect_url_matches`.

**Non-Goals:**

- `fetch_jobs` calling `pull_list`, or `ingest.py` duck-typing list hooks.
- `url_pull_runs`, default `--save`, Alembic, `cli.py` / `models.py` splits, HTTP binder promotion, `openopps/pull/` nest.
- Unifying `detect_route` with `parse_url_target`, or Greenhouse/Lever/Teamtailor identity decoders with `decode_url_identity_segment`.
- Moving `overlay_targets.py` into `discovery/`.
- Merging `MembershipEvidence` with `PullMembershipEvidence`, discovery HTTP with `openopps.http`, or claiming mocked fixtures prove live ATS availability.

## Decisions

### Kernel then bind, never wrap

`list_public_membership` (adapter-private) returns `BoardListingKernelResult`: native board identity, `ProviderPosting`s normalized onto that native identity, `MembershipEvidence`, and `DetailCoverageEvidence`. `bind_listing_jobs` is the only writer of catalog versus URL-pull `JobRecord.board_key` / `id` / `company`.

- Catalog: `identity_mode="ingest"`, `include_unlisted=False`, `detail_budget=None`, bind onto the ledger `BoardRecord`, return `JobFetchResult`.
- URL-list: `identity_mode="pull"`, bind onto `synthetic_url_pull_board(native_identity)`, return `ProviderListResult`.
- `check_jobs` does not call the kernel.
- Ingest timeout stays `job_route_timeout_seconds` (180). Pull detail budgets and `url_pull` cache identity scope stay pull-only.
- Incomplete/non-terminal membership never sets `authoritative=True`.

A url-pull bind whose `board.key` is not the native identity fails closed. Catalog binds may use a different `board.key` (source-scoped ledger keys).

### Path barriers versus live changes

Do not write:

- `src/openopps/cli.py`, `tests/integration/openopps/test_cli.py`, `tests/unit/openopps/test_cli_helper_contracts.py` — ingest `W-CLI` + unified-cli D712
- `src/openopps/models.py`, `storage.py`, `alembic/**`, `update_snapshot.py` — ingest `W-STORAGE` + unified-cli D704–D711
- `src/openopps/ingest.py` — ingest `W-INGEST`
- `src/openopps/source_policy.py` and `providers/sources/**` except overlay/household/source_scope SSOT
- `src/openopps/discovery/**` — ingest `W-DISCOVERY`
- `pull_service.py` persistence join / `--save` help — unified-cli §7–8 (D712 landed opt-in `--save` on `d464e84`)
- Root `README.md` chrome — `readme-landing-assets`
- Wheel/SBOM recipes — `release-0-1-1-toolchain-artifacts`

May write: `providers/boards/*.py` except frozen `__init__.py` / `tokens.py`, new `url_targets.py` / `listing.py`, overlay/household/source_scope SSOT, `src/openopps/AGENTS.md` module bullets.

### No-schema-write receipt (A005)

This change added no models, tables, or revisions. Historical A005 receipt recorded head `0004` and inactive `0005` `.draft` at authoring time. Current live head is `0006_url_pull_runs` after `414d5828` (0005) and `d8e70fce` (0006).

### Overlay SSOT

`JOB_SEEKER_OVERLAY_SOURCE_KEY` is defined in `overlay.py`. `source_scope.py` imports and re-exports it. Overlay and household attach jobs-capable routes through `ProviderRegistry.detect_url_matches`. Household keeps its ATS host allow/block lists. `overlay_targets.py` stays under `providers/sources/`.

### Parallel task graph

| Lane | Owns | Conflict |
| --- | --- | --- |
| OpenSpec | `openspec/changes/shared-board-listing-kernel/**` | none |
| Helpers | `providers/boards/{listing,url_targets}.py` | serialize before adapter rewrites |
| Group A tests | `test_url_pull_providers_ashby_bamboohr_consider.py` | one writer |
| Group B tests | `test_url_pull_providers_greenhouse_lever_teamtailor.py` | one writer |
| Group C tests | `test_url_pull_providers_rippling_workable_workday_wpjobmanager.py` | one writer |
| Sync tests | `test_providers.py`, `test_listing_bind.py`, plugin ingest-contract tests | one writer for `test_providers.py` |
| Adapters | one `providers/boards/<name>.py` each | frozen hubs |
| Overlay | `overlay.py`, `source_scope.py`, `household_routes.py` | serial on the overlay key move |
| Docs | `src/openopps/AGENTS.md` module list | none vs adapters |

## Risks / Trade-offs

- Lever/Teamtailor catalog sync may walk more pages than today’s single GET and can hit the 180s ingest timeout before the adapter page budget. Accepted: completeness over a silent first page.
- Greenhouse ingest now fail-closes on advertised-count mismatch. Accepted: ingest already maps `ValueError` to validation and does not persist.
- Sharing pull cache `role` keys on ingest would split historical `http_cache` rows. Ingest kernel calls omit URL-pull cache identity.

## Migration Plan

No schema migration. Existing SQLite job rows keep catalog `board_key` values. Operators re-sync boards to pick up paginated Lever/Teamtailor completeness; they do not migrate identities.

## Open Questions

None for this change. Grammar unification, identity-decoder unification, `openopps/pull/` nest, and storage persistence remain deferred.
