# shared-board-listing-kernel - tasks

Checked tasks require named local proof. They do not authorize archive, tag, publication, Workers upload, Kaggle mutation, production bootstrap, commit, or push.

## 1. Contract

- [x] 1.1 Record listing-kernel, catalog-rebind, identity-mode, check_jobs, overlay SSOT, and path-barrier requirements in proposal, design, and the `provider-ingestion` delta. Include accepted facts A001 and no-schema-write receipt A005 (Alembic head `0004`, draft `0005` untouched, G3 open).
- [x] 1.2 Inspect active changes with pinned `@fission-ai/openspec@1.6.0` (`list --json`, `status --json`, `instructions --json`) and strict-validate this change, then `--all --strict`. Do not archive this change.

## 2. Helpers

- [x] 2.1 Add `src/openopps/providers/boards/url_targets.py` with `strict_decoded_path_parts` byte-identical to Rippling/Workable/Workday `_strict_path_parts`, plus `synthetic_url_pull_board`. Import `decode_url_identity_segment` from `providers.pull`. Do not merge Greenhouse/Lever/Teamtailor/Ashby/BambooHR identity decoders.
- [x] 2.2 Add `src/openopps/providers/boards/listing.py` with `BoardListingKernelResult` and `bind_listing_jobs`. Catalog binds rewrite `board_key` / `id` / `company`; URL-pull binds require `board.key == native_board_identity` and `source_key="url-pull"`.
- [x] 2.3 Point Rippling, Workable, and Workday path parsing at `strict_decoded_path_parts`.

## 3. Board listing kernels

- [x] 3.1 Ashby: listed-only ingest; no URL-id override on ingest; pull may still override; `check_jobs` stays cheap.
- [x] 3.2 BambooHR: missing-route `authoritative=False`; `detail_budget=None` on ingest; pull keeps `pull_provider_max_details`; uncapped-sync test stays green.
- [x] 3.3 Consider: shared listing evidence; bind catalog versus `_pull_board`; `check_jobs` may keep today’s full listing walk.
- [x] 3.4 Greenhouse: shared membership GET; ingest inherits advertised-count / duplicate-id fail-closed; `check_jobs` stays `content=false`.
- [x] 3.5 Lever: ingest uses paginated `skip`/`limit`; `check_jobs` stays unpaginated; do not apply `url_pull` cache scope.
- [x] 3.6 Rippling: pull stays strict; ingest keeps listing-id fallback / empty-detail authoritative snapshots.
- [x] 3.7 Teamtailor: ingest paginates with `prefer_link_identity=False`; pull keeps `True`.
- [x] 3.8 Workable: shared public client; catalog rebind only; `check_jobs` may keep listing-count walk.
- [x] 3.9 Workday: pull stays strict; ingest keeps `remote_id` and empty-detail fallback.
- [x] 3.10 WP Job Manager: catalog rebind; missing-endpoint `authoritative=False`.
- [x] 3.11 Parameterized proof: kernel listed+complete ⇒ `fetch_jobs` jobs use catalog `board_key`; `pull_list` jobs use url-pull `board_key`. `fetch_jobs` never calls `pull_list`. `ingest.py` still calls `fetch_jobs` only.

## 4. Overlay SSOT

- [x] 4.1 `JOB_SEEKER_OVERLAY_SOURCE_KEY` owned by `overlay.py`; `source_scope.py` imports it. Do not move `overlay_targets.py`.
- [x] 4.2 Overlay and household attach jobs-capable routes through `detect_url_matches`. Household keeps host allow/block lists. Do not unify `detect_route` versus `parse_url_target`.

## 5. Assurance

- [x] 5.1 Update `src/openopps/AGENTS.md` to name `pull_*`, `providers/pull.py`, and the listing kernel. Do not rewrite URL-pull user docs.
- [x] 5.2 `uv run ruff check` and `uv run ty check` on touched package surfaces.
- [x] 5.3 Focused pytest for URL-pull groups, `test_providers.py`, listing bind, overlay/household/source-scope, plugin ingest contract, pull-resolver isolation, and discovery boundaries.
- [x] 5.4 Re-run `rtk npx -y @fission-ai/openspec@1.6.0 validate shared-board-listing-kernel --strict` and `validate --all --strict`. Leave this change unarchived.
