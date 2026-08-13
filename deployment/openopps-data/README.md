# OpenOpps public-data delivery

This directory contains two independently named Cloudflare Workers Static Assets configurations:

- `staging/wrangler.jsonc` for `openopps-data-staging`
- `production/wrangler.jsonc` for `openopps-data-production`

Both configs are assets-only, use their sibling `assets/` directory, expose `workers.dev`, disable preview URLs and metrics, and intentionally define no Worker script, binding, or `run_worker_first` path. The generated `assets/` trees and local release evidence are ignored by Git.

The commands in this runbook have different authority classes. Generation, local verification, command rendering, and archive construction are local. `wrangler versions upload`, `wrangler versions deploy`, remote publication, GitHub Release upload, Worker-version deletion, and Git history changes mutate external state and require an explicitly authorized maintainer session.

Nothing in this directory proves that a live staging or production rollout occurred.

## Prerequisites

- Run from the repository root on the intended source revision.
- Install locked Python and web dependencies.
- Use the pinned Wrangler version from `web/package.json`; the delivery validator currently requires `4.122.0` exactly.
- Start from a clean public `kaggle/openoppsdb.sqlite` snapshot containing no private payload surfaces.
- Require both structural source-policy validation and a green release-eligibility audit for the exact included corpus. Repository catalog declarations are not independent permission evidence.
- Know the exact Cloudflare account, staging/production Worker names, staging/production `workers.dev` origins, current previous-good Worker version IDs, and rollback owner.
- Preserve the previous-good staged tree or verified recovery archive so rollback readback can be compared to the correct bytes.

For non-interactive Wrangler authentication, keep `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the operator environment only. Use a narrowly scoped token. Do not place credential values in this README, `.env.example`, Git, generated JSON, screenshots, issue comments, or shell tracing. An interactive local operator may use `wrangler login` instead.

## 1. Record inputs and run canonical gates

```bash
git status --short --branch
git rev-parse HEAD
uv lock --check
cd web && pnpm install --frozen-lockfile
cd ..
just ci
just security-audit
just source-policy-check
just source-policy-audit
```

`just ci` is the canonical local graph for Python, OpenSpec, web, browser, and generated-artifact gates. `source-policy-check` is intentionally structural: it validates canonical bytes, schema, evidence, and the exact v6 corpus identity. `source-policy-audit` is the release-eligibility gate and must exit zero before generation or upload. The current committed-v6 audit is release-ineligible: 7 of 695 sources mirror repository catalog declarations, 0 are independently verified, and 688 are blocked, so the audit exits 2 and no selector may be rendered. `just security-audit` is network-dependent. None of these commands deploys the public-data Worker.

Keep the exact source SHA and command outputs with the release evidence. Local success is not origin-CI success; require the GitHub Actions run for the same SHA before production promotion.

## 2. Generate and verify publication v7

Choose an external or ignored publication root. Do not point `--release-root` at the legacy v6 tree.

```bash
publication_root=/absolute/path/to/openopps-search-v7

uv run python scripts/generate_docs_search_index.py \
  --data-db kaggle/openoppsdb.sqlite \
  --release-root "$publication_root" \
  --channel production \
  --max-snapshot-age-hours 48

uv run python scripts/verify_docs_search_artifacts.py \
  --root "$publication_root" \
  --channel production \
  --max-snapshot-age-hours 48
```

The default and documented release threshold is 48 hours. If incident policy explicitly authorizes an older snapshot, rerun generation with a specific `--allow-stale-reason`. That reason and the snapshot age are public. The override does not bypass rights, attribution, privacy, secret, integrity, provenance, or platform-budget checks.

Delivery requires `channels/production.json` to name two distinct valid releases. The first v7 publication can have `priorReleaseId: null`; obtain and verify a genuinely distinct successor before proceeding. Never fabricate a second ID or edit a release directory.

Before staging, inspect these generated files:

- `channels/production.json`
- `releases/<releaseId>/manifest.json`
- `releases/<releaseId>/publication-policy.json`
- `releases/<releaseId>/search-manifest.json`

Stop on any missing/`needs_review` source rights state, missing required attribution, stale snapshot without approved degraded evidence, or verifier error.

The generated `publication-policy.json` separates license, access, redistribution, synchronization, and publication decisions. Its `sourcePolicy` identity and SHA-256 values must match the policy module, evidence, schema, and exact reference corpus listed in the release manifest's generator components. The reviewed policy is a deny-only overlay: a provider-scoped or exact-source denial overrides catalog or persisted metadata, while absence from the overlay never grants publication rights.

## 3. Validate configs and stage exact dual-release trees

```bash
uv run python scripts/docs_search_delivery.py \
  validate-config deployment/openopps-data

uv run python scripts/docs_search_delivery.py \
  stage "$publication_root" deployment/openopps-data/staging/assets

uv run python scripts/docs_search_delivery.py \
  verify-stage deployment/openopps-data/staging/assets
```

`stage` accepts only the two repository-owned destinations `deployment/openopps-data/staging/assets` and `deployment/openopps-data/production/assets`. It builds a sibling candidate, verifies it, and atomically replaces the destination. The staged tree contains exactly:

```text
_headers
channels/production.json
releases/<current-release-id>/...
releases/<previous-release-id>/...
```

The stage validator enforces the dual-release exact set, release hashes, channel coherence, safe regular files/directories, case-collision checks, cache/security headers, a 20,000-file budget, and a strict-less-than-24-MiB per-file budget.

Stage production independently only after staging proof is complete:

```bash
uv run python scripts/docs_search_delivery.py \
  stage "$publication_root" deployment/openopps-data/production/assets

uv run python scripts/docs_search_delivery.py \
  verify-stage deployment/openopps-data/production/assets
```

## 4. Render and review the upload invocation

The helper returns JSON and never executes Wrangler:

```bash
mkdir -p .tmp/openopps-data-release

uv run python scripts/docs_search_delivery.py upload-command \
  deployment/openopps-data/staging/wrangler.jsonc \
  .tmp/openopps-data-release/staging-upload.jsonl \
  --stage-root deployment/openopps-data/staging/assets
```

Review the returned `argv`, `env`, `upload_candidate_root`, `upload_candidate_digest`, `stage_root_digest`, `current_release_id`, and `previous_release_id`. The helper copies the validated config and asset tree into `.tmp/openopps-data-release/upload-candidates/<environment>/<candidate-digest>/`, verifies the complete config-plus-assets digest, and removes every write bit before rendering Wrangler. Wrangler therefore reads the frozen digest-addressed candidate, not the mutable staging tree. Preserve the candidate and both returned digests through the recording step. The supported machine interface is `WRANGLER_OUTPUT_FILE_PATH`; Wrangler `versions upload --json` is not used. The output path must not already exist, which prevents stale upload records from being reused.

With separate live authorization, the rendered staging invocation has this shape:

```bash
WRANGLER_OUTPUT_FILE_PATH="$PWD/.tmp/openopps-data-release/staging-upload.jsonl" \
  pnpm --dir "$PWD/web" exec wrangler versions upload \
  --config "$PWD/.tmp/openopps-data-release/upload-candidates/staging/<candidate-digest>/wrangler.jsonc" \
  --strict
```

Do not copy this command into an unauthorized session. If the expected Worker does not already exist or account/Free-plan identity is ambiguous, stop and follow the separately gated [first-Worker bootstrap runbook](BOOTSTRAP.md); do not substitute an ad hoc `wrangler deploy`. The bootstrap helper is the one-time, dry-run-first exception: it binds a frozen candidate to a freshly proven absent target and records the single initial version/deployment as the rollback identity before ordinary version uploads begin.

After an authorized upload, strictly parse and append its sanitized identity to a local ledger:

```bash
uv run python scripts/docs_search_delivery.py record-upload \
  .tmp/openopps-data-release/staging-upload.jsonl \
  .tmp/openopps-data-release/upload-ledger.json \
  staging \
  .tmp/openopps-data-release/upload-candidates/staging/<candidate-digest> \
  --expected-upload-candidate-digest <upload-candidate-digest-from-command> \
  --expected-stage-root-digest <stage-root-digest-from-command> \
  --recorded-at 2026-08-12T00:00:00.000000Z
```

Use the real canonical UTC upload time. Recording re-verifies the read-only candidate path, exact candidate digest, exact staged-asset digest, config bytes, and release graph. Mutable staging changes—including a transient change restored before recording—cannot affect the bytes Wrangler reads because the rendered command does not reference that tree. The record includes Worker name/version, current and previous release IDs, expected and actual candidate/staged-tree digests, Wrangler version, and phase. It contains no credentials. Repeat the same render/upload/record sequence with the production config only after the staging sequence passes.

## 5. Promote, verify, roll back, and re-promote

The rollout helper validates UUID-shaped Worker version IDs and renders the complete single-version, 100%-traffic sequence. Its default output contains `--dry-run`:

```bash
uv run python scripts/docs_search_delivery.py rollout-plan \
  deployment/openopps-data/staging/wrangler.jsonc \
  <new-worker-version-id> \
  <previous-good-worker-version-id>
```

After review and separate live approval, add `--live-command` to render commands without `--dry-run`. The helper still does not execute them:

```bash
uv run python scripts/docs_search_delivery.py rollout-plan \
  deployment/openopps-data/staging/wrangler.jsonc \
  <new-worker-version-id> \
  <previous-good-worker-version-id> \
  --live-command
```

Do not execute the three commands as an unobserved batch. Use these barriers:

1. Execute only the rendered **promote** command (`new@100%`).
2. Verify the new staging origin against the new staged tree.
3. Exercise Jobs, Explorer, details, metadata, sitemap, and search smoke paths with the v6 tree unavailable.
4. Execute only the rendered **rollback** command (`previous@100%`).
5. Verify the staging origin against the retained previous-good stage or restored archive, not against the new tree.
6. Execute only the rendered **re-promote** command (`new@100%`).
7. Re-run exact remote verification and critical web smoke paths against the new stage.

Exact remote readback is:

```bash
uv run python scripts/docs_search_delivery.py verify-remote \
  deployment/openopps-data/staging/assets \
  https://openopps-data-staging.<account-subdomain>.workers.dev
```

The origin must be a port-free HTTPS `workers.dev` origin with no credentials, path, query, or fragment. Verification fetches every served asset without redirects and requires exact bytes/SHA-256, CORS `*`, `nosniff`, `noindex`, the expected immutable/revalidating cache policy, a non-empty ETag, and a deterministic missing-path 404.

Repeat the gated sequence for production only after staging proof, exact-SHA CI, the previous-good production version, and rollback ownership are recorded. Record Cloudflare version/deployment IDs and remote-verifier output. A rendered plan, upload record, or successful staging rollout is not proof of production rollout.

## 6. Build and verify the recovery archive

The `stage` command prints `root_digest`; retain it as the stage identity used by the release tag. The archive filename is addressed separately by the exact archive SHA-256:

```bash
source_revision=<40-character-lowercase-git-sha>
archive_directory="$PWD/.tmp/openopps-data-release"

just public-data-archive-bundle \
  stage=deployment/openopps-data/production/assets \
  output_directory="$archive_directory" \
  created_at=2026-08-12T00:00:00.000000Z \
  source_revision="$source_revision"
```

The command prints `path`, `asset_name`, `sha256`, and `stage_root_digest`. Its output filename is `openopps-data-<archive-sha256>.tar.gz`: the asset name addresses the exact archive bytes, while the later release tag addresses the stage tree. The bundle streams the dual-release tree and includes `SHA256SUMS`, `bundle-manifest.json`, `sbom.spdx.json`, and `provenance.json`. It refuses to replace an existing archive at the same content address. Record the printed identities outside the archive, then restore-test every identity from the release ledger into a new directory:

```bash
stage_digest=<64-character-stage-root-digest>
archive_sha256=<64-character-archive-sha256>
archive_path="$archive_directory/openopps-data-$archive_sha256.tar.gz"
current_release_id=<64-character-current-release-id>
previous_release_id=<64-character-previous-release-id>
restore_parent="$(mktemp -d)"

just public-data-archive-restore \
  archive="$archive_path" \
  destination="$restore_parent/assets" \
  archive_sha256="$archive_sha256" \
  stage_root_digest="$stage_digest" \
  source_revision="$source_revision" \
  current_release_id="$current_release_id" \
  previous_release_id="$previous_release_id"
```

`restore` requires a regular archive, an absent destination under a non-shared parent, and all five external identities. It verifies the raw archive SHA-256, SHA-addressed filename, member path/type/order/count/size bounds, a 4-GiB expanded-byte ceiling, checksum closure, duplicate-free JSON, bundle/provenance/SPDX semantics, current and prior release trees, and the final stage-root digest. Files stream through no-follow, exclusive creates into a private sibling candidate; an OS-native exclusive rename (`RENAME_NOREPLACE`/`RENAME_EXCL`) names the verified candidate only after `verify-stage` passes. It fails closed on unsupported filesystems/platforms and never overwrites a concurrently created destination. Do not use `tar -x` or extract an unverified archive over a working directory or publication root.

## 7. GitHub archive and attestation gate

The manual `.github/workflows/public-data-archive.yml` workflow is the reviewed archive publication path. It cannot create a draft or upload an asset. Before dispatch, a maintainer must separately enable GitHub immutable releases, build and restore-test the archive, verify that `source_revision` is the current `main` SHA, and create one non-latest draft whose only asset is the exact archive:

```bash
release_tag="openopps-data-v7-$stage_digest"
gh release create "$release_tag" "$archive_path" \
  --draft \
  --latest=false \
  --target "$source_revision" \
  --title "$release_tag" \
  --notes "OpenOpps v7 public-data recovery archive."

gh workflow run public-data-archive.yml \
  --ref main \
  -f release_tag="$release_tag" \
  -f archive_sha256="$archive_sha256" \
  -f stage_root_digest="$stage_digest" \
  -f source_revision="$source_revision" \
  -f current_release_id="$current_release_id" \
  -f previous_release_id="$previous_release_id"
```

The workflow rejects any non-`main` dispatch, source SHA mismatch, disabled immutable-release setting, non-draft/already-immutable/prerelease record, wrong tag namespace, extra asset, filename/digest/identity drift, or source SHA not on `main`. If the release tag already exists, it must peel—whether lightweight or annotated—to that exact source commit. Its first read-only job freshly downloads and restores the draft, then adds only `id-token: write` and `attestations: write` for the pinned `actions/attest` step; registry push and storage records remain explicitly disabled. A separate `contents: write` job rechecks the immutable-release setting, tag target, archive, and attestation before publishing with `latest=false`, then requires the record to report immutable immediately. A fresh `contents: read` job independently peels the final tag, requires exactly one asset, runs `gh release verify`, `gh release verify-asset`, workflow/source-bound SPDX v2.3 attestation verification, and restores again. Because GitHub release immutability and automatic release attestations can become visible asynchronously, that final job retries the immutable flag and release/asset verification at 10-second intervals for no more than 120 seconds per gate, then fails exactly.

The ordinary CI supply-chain job still covers the Python wheel separately. Repository workflow presence, local archive success, or draft creation alone does not satisfy task 5.7. Record the successful archive workflow run, immutable release URL/tag, archive digest, attestation verification, and restore output for the exact promoted SHA before calling the independent archive gate complete. Do not dispatch until immutable releases and the exact draft are intentionally prepared; this repository change does not enable the setting or create a release.

## 8. v6 retirement and history boundary

Keep `web/public/data/openopps-search/` and the v6 reader until all generation, rights, Free-plan full-corpus upload, remote readback, v6-absent web, production promote/rollback/re-promote, exact-SHA CI, archive attestation, independent download, and restore gates pass.

After those gates, removing the v6 tree is an ordinary reviewed commit. It does not authorize rewriting Git history.

History rewriting requires a different proposal and explicit approval covering protected backups, every ref, old-to-new SHA mapping, collaborator freeze, branch protection/release coordination, fresh-clone validation, recovery instructions, and the exact force-push targets. Without that approval, do not run `git filter-repo`, delete refs, or force-push.

## Stop conditions

Stop the rollout and preserve or restore the previous-good version when any of these occurs:

- channel/release identity, exact-set, digest, path, rights, privacy, freshness, provenance, or platform-budget validation fails;
- the full corpus is rejected by the actual Free-plan target;
- Wrangler output lacks exactly one valid `version-upload` record for the intended Worker;
- remote bytes, headers, ETag, redirect, or 404 behavior differ;
- server and browser consumers resolve different releases;
- v6-absent build, route, or browser checks fail;
- previous-good stage/archive or rollback version identity is missing;
- exact-SHA origin CI or independent archive recovery evidence is absent; or
- external target, credentials, approval, or rollback ownership is ambiguous.

Do not silently activate a paid or different hosting service when the Free-plan gate fails. Record the exact error and return to architecture review.
