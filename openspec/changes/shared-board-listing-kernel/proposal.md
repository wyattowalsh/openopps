## Why

Catalog sync (`jobs sync` → `fetch_jobs`) and URL-first pulls (`jobs pull` → `pull_list`) each walk the same public ATS boards, but they duplicate listing HTTP, pagination, and membership checks. A naive `fetch_jobs` wrap of `pull_list` would mint URL-pull `board_key` values into the ledger, change Teamtailor and Ashby `remote_id`s, cap BambooHR ingest behind pull detail budgets, and let plugins without list hooks look like empty authoritative snapshots.

The two pipelines must keep sharing HTTP, cache, settings, and the provider registry — not orchestration. Completeness on sync is a new provider-ingestion contract; it does not extend `unified-cli-job-pulls` sections 7–9 or open schema work.

## What Changes

- Extract a listing kernel that returns native membership evidence with no catalog `board_key` until `bind_listing_jobs`.
- Rebind kernel jobs onto the catalog `BoardRecord` for `fetch_jobs`, and onto the synthetic `source_key="url-pull"` board for `pull_list`.
- Give Lever and Teamtailor catalog sync the same finite pagination as URL-list; keep Teamtailor ingest guid-first and Ashby ingest free of URL-id override.
- Fail Greenhouse catalog sync closed on advertised-count / duplicate-id mismatch. Keep `check_jobs` as a cheap probe. Never call the kernel from health checks.
- Own `JOB_SEEKER_OVERLAY_SOURCE_KEY` in `overlay.py` and attach overlay/household ATS routes through `ProviderRegistry.detect_url_matches`.
- Add `providers/boards/url_targets.py` and `providers/boards/listing.py` only. Do not nest `openopps/pull/`, split `cli.py`/`models.py`, wrap `ingest.py`, move `overlay_targets.py`, or unify `detect_route` with `parse_url_target`.

## Capabilities

### New Capabilities

None. This change extends provider-ingestion listing completeness and identity bind.

### Modified Capabilities

- `provider-ingestion`: Share one membership kernel plus post-evidence identity bind across catalog sync and URL-list for the ten adopted board providers, without changing `JobFetchResult` / `fetch_jobs()` as the sync and legacy-plugin contract.

## Impact

- New helpers under `src/openopps/providers/boards/{listing,url_targets}.py` and in-place `fetch_jobs` / `pull_list` edits in the ten board adapters.
- Overlay/household/source-scope SSOT for the packaged overlay key and jobs-capable URL matches.
- Nested `src/openopps/AGENTS.md` module bullets for `pull_*`, `providers/pull.py`, and the listing kernel.
- No `cli.py`, `ingest.py`, `models.py`, `storage.py`, Alembic, discovery, source-policy, or default `--save` edits.
- Console entry stays `openopps.cli:app`. Mocked fixtures do not prove live ATS availability.

## Acceptance summary

1. `fetch_jobs` and `pull_list` share listing HTTP and membership evidence; `fetch_jobs` does not call `pull_list`, and `ingest.py` does not duck-type list hooks.
2. Catalog jobs bind to the ledger `BoardRecord` (`board_key` / `id` / `company`); URL-list jobs keep `source_key="url-pull"` and `board_key` equal to the native ATS identity.
3. Incomplete or non-terminal listings never yield `authoritative=True`. `check_jobs` stays a cheap probe except where it already full-walks (Consider, Workable listing count).
4. Teamtailor ingest `remote_id` stays guid-first; Ashby ingest does not apply URL-id override; BambooHR sync is not capped by `pull_provider_max_details`.
5. Overlay key SSOT and `detect_url_matches` attach jobs-capable routes; `overlay_targets.py` stays under `providers/sources/`.
6. Alembic head remains `0004`. `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict` passes. This change is not archived here.
