# First-time Worker bootstrap

This procedure is the one-time exception required to create the two
assets-only Workers named by this directory. Normal releases use
`wrangler versions upload` followed by an explicit version deployment; they do
not use `wrangler deploy`.

The bootstrap helper never runs `cf` or Wrangler. It validates saved read-only
inventory, freezes the already verified dual-release stage into the same
digest-addressed candidate used by normal delivery, and renders a command. Its
default command contains `--dry-run`. Only `--live-command` removes that flag.

Bootstrap changes live traffic and therefore remains behind the live mutation
approval gate in [README.md](README.md). It is not permission to upload an
invalid, stale, rights-blocked, synthetic, or single-release publication.

## Preconditions

- Work from the intended clean source revision on `main`.
- Complete all publication and stage gates in the delivery runbook first.
- Keep `.tmp/openopps-data-release/` local and untracked.
- Confirm the Cloudflare account and `workers.dev` subdomain out of band.
- Use `cf` 0.6.0 for read-only inventory and the repository-pinned Wrangler
  4.122.0 for the one-time deployment.
- Do not enable R2, routes, domains, bindings, scripts, preview URLs, Logpush,
  tail consumers, or observability.

`npx cf auth login` and Wrangler use separate authentication stores. A valid
`cf` login is sufficient for the inventory commands below, but it does not by
itself prove that Wrangler is authenticated. Supply `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` to the live Wrangler process through the operator
environment only. Never echo them, place them in an output file, add them to a
command trace, or persist them in Git. The helper neither accepts nor records
credential values.

## 1. Capture target absence

Render the pinned read-only inventory command and review its output contract:

```bash
release_evidence="$PWD/.tmp/openopps-data-release"
mkdir -p "$release_evidence"
cloudflare_account_id=<32-character-account-id>

uv run python scripts/docs_search_bootstrap.py inventory-command \
  "$release_evidence/workers-before.json" \
  --account-id "$cloudflare_account_id"
```

Run the returned `argv` with stdout redirected to its `stdoutFile`. Its exact
shape is:

```bash
CLOUDFLARE_ACCOUNT_ID="$cloudflare_account_id" \
  npx --yes cf@0.6.0 workers scripts list \
  > "$release_evidence/workers-before.json"
```

Inspect the JSON. The target must be absent. The helper refuses to render a
bootstrap deployment if `openopps-data-staging` or
`openopps-data-production`, as applicable, already exists. Render the plan
within five minutes: older inventory is rejected, and its exact bytes and file
metadata are bound into the plan and rechecked before recording.

## 2. Render and execute the dry run

The staged assets must already contain exactly current and previous v7 release
trees plus `channels/production.json` and `_headers`.

```bash
source_revision="$(git rev-parse HEAD)"

uv run python scripts/docs_search_bootstrap.py plan \
  deployment/openopps-data/staging/wrangler.jsonc \
  deployment/openopps-data/staging/assets \
  "$release_evidence/workers-before.json" \
  "$release_evidence/staging-bootstrap-dry.jsonl" \
  "$release_evidence/staging-bootstrap-dry-plan.json" \
  --source-revision "$source_revision" \
  --account-id "$cloudflare_account_id"
```

Review the written plan. It binds:

- the source revision and pre-bootstrap inventory digest;
- the inventory capture, plan, and five-minute expiry timestamps;
- the exact Worker name and canonical repository config;
- current and previous release IDs;
- the staged-asset digest;
- the complete read-only config-plus-assets candidate digest; and
- the pinned Wrangler version and machine-output path.

Execute only the plan's `argv`, with its `env`, after confirming it contains
`--dry-run`. It must read the config inside
`upload-candidates/<environment>/<candidate-digest>/`, not the mutable
staging directory. A dry-run plan cannot be recorded as a live bootstrap.

## 3. Render the separately authorized live command

Use new absent output and plan paths. The same saved pre-inventory must still
be current; if target state may have changed, recapture inventory instead.
Never replay a saved live plan. Immediately before every live attempt, capture
a new inventory file and render a new plan with new absent output paths. An
expired plan or a Wrangler output written outside its five-minute absence
window cannot produce a valid ledger.

```bash
uv run python scripts/docs_search_bootstrap.py plan \
  deployment/openopps-data/staging/wrangler.jsonc \
  deployment/openopps-data/staging/assets \
  "$release_evidence/workers-before.json" \
  "$release_evidence/staging-bootstrap-live.jsonl" \
  "$release_evidence/staging-bootstrap-live-plan.json" \
  --source-revision "$source_revision" \
  --account-id "$cloudflare_account_id" \
  --live-command
```

Review the plan again. The command must:

- start with the repository-pinned `pnpm ... wrangler deploy` prefix;
- reference only the read-only digest-addressed candidate config;
- include `--strict`;
- embed the full candidate digest in its version message;
- write Wrangler's JSONL record through `WRANGLER_OUTPUT_FILE_PATH`; and
- omit `--dry-run` only in this explicitly live plan.

Execute that one command only after live authorization. Do not substitute an
unfrozen config, `npx wrangler`, Dashboard deployment, direct API mutation, or
an R2 upload.

## 4. Capture exact first-deployment readback

Render the three pinned read-only commands:

```bash
uv run python scripts/docs_search_bootstrap.py readback-commands \
  staging "$release_evidence" \
  --account-id "$cloudflare_account_id"
```

Run each returned `argv`, redirecting stdout to its `stdoutFile`. Their shapes
are:

```bash
CLOUDFLARE_ACCOUNT_ID="$cloudflare_account_id" \
  npx --yes cf@0.6.0 workers beta workers get openopps-data-staging \
  > "$release_evidence/staging-workers-after.json"

CLOUDFLARE_ACCOUNT_ID="$cloudflare_account_id" \
  npx --yes cf@0.6.0 workers deployments list \
  --worker openopps-data-staging \
  > "$release_evidence/staging-deployments.json"

CLOUDFLARE_ACCOUNT_ID="$cloudflare_account_id" \
  npx --yes cf@0.6.0 workers versions list \
  --worker openopps-data-staging --per-page 100 \
  > "$release_evidence/staging-versions.json"
```

Raw `cf` evidence may contain operator metadata such as an author email. Keep
it local and untracked. The sanitized bootstrap ledger does not retain that
metadata or any credential.

Record only an exact first deployment:

```bash
uv run python scripts/docs_search_bootstrap.py record \
  "$release_evidence/staging-bootstrap-live-plan.json" \
  "$release_evidence/staging-workers-after.json" \
  "$release_evidence/staging-deployments.json" \
  "$release_evidence/staging-versions.json" \
  "$release_evidence/staging-bootstrap-ledger.json" \
  --recorded-at 2026-08-13T00:00:00Z
```

Replace `--recorded-at` with the real canonical UTC evidence time. Recording
requires all of the following:

- the pre-inventory bytes still hash to the plan and still show target absence;
- the plan is unexpired and the Wrangler output file and deploy timestamp fall
  inside its exact absent-inventory window;
- the operator-supplied `recordedAt` follows the Wrangler deploy timestamp;
- exactly one supported Wrangler `deploy` record for the intended Worker;
- exactly one Worker, initial version number 1, and deployment;
- exactly that version serving 100% traffic;
- only the expected `workers.dev` origin, with preview URLs disabled;
- no domains, routes, resource references, tail consumers, Logpush, or
  observability; and
- unchanged candidate, stage, current-release, and previous-release identity.

Cloudflare may report provider-managed log/trace persistence defaults even
when those surfaces are disabled. The evidence gate requires the Worker,
logs, and traces `enabled` states all be false; it does not misstate an inert
provider default as active observability.

The ledger records the initial Worker version as
`rollbackWorkerVersionId`. Preserve it. After the next normal
`versions upload`, it is the required previous-good identity for the
promote/rollback/re-promote sequence. Bootstrap itself cannot demonstrate a
rollback because no earlier Worker version exists.

Repeat the complete process independently for production only after staging
bootstrap, normal staging upload, remote byte readback, and rollback proof all
pass.

## Existing target reconciliation

Never run bootstrap deploy against an existing target. The only accepted
existing state is the exact state already captured by its bootstrap ledger:

```bash
uv run python scripts/docs_search_bootstrap.py reconcile-existing \
  "$release_evidence/staging-bootstrap-ledger.json" \
  "$release_evidence/staging-workers-after.json" \
  "$release_evidence/staging-deployments.json" \
  "$release_evidence/staging-versions.json"
```

Recapture those three read-only files before a real reconciliation. The
command rejects any Worker ID, version, deployment, traffic, origin, config,
candidate, release, or attached-resource drift. If the Worker exists without
an exact bootstrap ledger, stop for manual architecture and recovery review;
do not adopt it by name.

## Stop conditions

Stop without deploying or proceeding to normal uploads when:

- target absence is not freshly proved;
- the plan or Wrangler output path already exists;
- the candidate is writable, symlinked, hard-linked, incomplete, or changed;
- a command does not use the pinned clients and exact candidate;
- credentials, account, subdomain, approval, or rollback owner are ambiguous;
- the initial readback contains more than one version or deployment;
- traffic is not exactly 100% on the recorded initial version; or
- any non-assets-only surface appears.
