# Private-host source-discovery runbook (unprovisioned)

Scheduler-agnostic template for a maintainer-controlled private host. This
change **does not provision or activate** a live scout schedule, host, secret,
runner, or retention job.

OpenSpec: `bounded-quarantined-source-discovery` **D1016** (template) and
**D1017** (offline fixture tests). **D1018** and **B1099** remain open.

## Scheduler-agnostic template

This runbook is not GitHub-Actions-only and does not contain a cron expression
to enable. It does not select, provision, or activate GitHub Actions, Cloudflare
Cron Triggers, systemd timers, launchd, Kaggle notebooks, Workers, or hosted
runners.

Public/CI-shaped validation stays offline. A later private live scout, if ever
authorized, would still use this same least-privilege shape: explicit
environment allowlist, finite channel and transport budgets, a private output
root, expire/delete retention, and digest-bound readback. That live path is
**unprovisioned / not activated**.

## Environment allowlist

Admit only these classes of environment. Reject credentials, proxy injection,
plugin path mutation, and ambient operational config.

| Class | Keys | Profile |
| --- | --- | --- |
| Network gate | `OPENOPPS_DISCOVERY_NETWORK=disabled` | **Offline** (public/CI-shaped; the only profile this repository exercises) |
| Finite scout limits | existing `OPENOPPS_DISCOVERY_*` settings in `src/openopps/discovery/settings.py` | Both; values stay finite and maintainer-owned. Remote content cannot raise them. |
| Isolated child process | `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ` only, plus forced `NO_PROXY=*` and `PYTHONNOUSERSITE=1` (`openopps.discovery.isolation.build_credential_free_environment`) | Both |
| Forbidden | cloud tokens, Kaggle tokens, GitHub tokens, `HTTP_PROXY` / `HTTPS_PROXY`, database URLs, promotion-lock paths, v7 public `SourceSelector` | Both |

Do not export secrets into the scout process, command traces, Git, or CI logs.

## Offline profile (`OPENOPPS_DISCOVERY_NETWORK=disabled`)

Required for every command this runbook authorizes. Public CI and local
contributor validation use this profile against committed sanitized fixtures
under `tests/fixtures/discovery/`.

Gates refuse any other `OPENOPPS_DISCOVERY_NETWORK` value. Offline scout
enumeration is replay-library-only; the current CLI scout evaluates an empty
occurrence set against read-only v7 policy digests and does not crawl.

## Private live profile (unprovisioned / not activated)

This profile is a template only. It is **unprovisioned / not activated**.

Do not set `OPENOPPS_DISCOVERY_NETWORK` to any value other than `disabled` in
this repository, public CI, Just recipes, or the documented offline commands.

A future maintainer-controlled private host would still be credential-free at
the scout boundary, write only to a private output root outside Git, honor the
same finite channel and transport budgets, expire or delete unsanitized
evidence, and never upload public artifacts. Unavailable access reports a
bounded blocked state. There is no browser automation, scraping bypass, public
artifact upload, or paid-service substitution.

Live scheduler provisioning, credential selection, activation, retention, and
execution are **separate unexercised authority gates**. This document does not
exercise them.

## Finite budgets

Cite existing OpenOpps contracts. Do not invent numeric SLOs. Discovery
benchmark ADR `src/openopps/discovery/data/benchmark-adr.json` remains
`verdict=defer` with `numericRegressionThreshold=null`.

Four finite channel families (skill/OpenSpec finite-channel rule;
`skills/openopps-source-scout/references/context-contract.md`; OpenSpec
`source-discovery` “Discovery channels are finite and explicit”):

| Channel value | Family |
| --- | --- |
| `official` | Official catalogs and documentation |
| `public_code` | Public code and datasets |
| `search` | Search APIs |
| `targeted_ats` | Targeted employer and ATS queries |

Each trusted `ChannelProfile` already supplies finite query, request, origin,
redirect, page, response-byte, aggregate-byte, candidate, concurrency,
per-origin concurrency, retry, parser-depth, and wall-clock limits
(`channel-budget.schema.json`). The whole-run profile separately bounds
requests, aggregate bytes, candidates, concurrency, and wall-clock time
(`whole-run-budget.schema.json`). Exhaustion is incomplete work, not success.

Existing bounded transport (`src/openopps/discovery/transport.py`) enforces
`ByteBudget` and `RequestBudgetLedger` for time-adjacent request accounting,
admitted bytes, origin/concurrency caps, and fail-closed oversized responses.
`DiscoverySettings` exposes the same dimensions as `OPENOPPS_DISCOVERY_*`
(whole-run and channel timeouts, query/request/origin/redirect/concurrency
caps, response and aggregate bytes, candidate caps, retries, pagination,
parser depth, evidence-reuse window). Isolation adds parent-enforced
`ScoutProcessLimits` on stdin/stdout/stderr bytes and wall-clock time.

Do not copy remote quotas into repository SLOs. Do not treat p95 samples as
gates.

## Private output directory

Scout writes only to an explicit quarantine directory (`openopps discovery
scout --output <dir>`). That directory is the private output root.

- Use an absolute path outside the Git worktree.
- Owner-only directory mode (`0o700`) as enforced by
  `openopps.discovery.isolation.ApplicationFilesystem`.
- Never write operational SQLite, the packaged catalog, generated public data,
  release trees, Kaggle, or Cloudflare.
- Never stage, commit, or push quarantine bytes.
- Public CI consumes only committed sanitized redistribution-safe fixtures.

## Retention

Unsanitized or live quarantine evidence stays in maintainer-controlled private
storage.

- Expire or delete the private output root after readback. Do not keep it in
  Git, CI artifacts, or public object storage.
- Never upload public artifacts (no `actions/upload-artifact`, GitHub Release,
  Kaggle dataset, Cloudflare, PyPI, or npm).
- Reuse of exact verified observations is bounded by the existing
  `OPENOPPS_DISCOVERY_EVIDENCE_RETENTION_SECONDS` setting; that window is not a
  publication or SLO grant.
- Retention policy for a live private host is itself a separate unexercised
  authority gate. This runbook does not enable a retention daemon.

## Readback gates

Readback is offline, non-applying, and digest-bound. None of these commands
accept `--apply`.

CLI (optional explicit private output, then delete it). `verify-scout`
accepts the printed `manifestPath` or that bundle directory (the parent of
`manifest.json`):

```bash
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery verify-scout /absolute/private-output/<digest>/manifest.json --json
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery preview-promotion --json
```

`preview-promotion` without a manifest dry-runs the on-disk identity-closure
envelope, decision, receipt, and ledger (`applied=false`,
`grantsAuthority=false`). Passing a quarantine manifest offline-verifies it
first. Neither path reserves, applies, acquires the promotion lock, or mutates
Git remotes, operational SQLite, Kaggle, or Cloudflare.

Equivalent Just wrappers and the canonical script (thin recipes already in the
repository; this runbook does not add any):

```text
just source-discovery-schema-check
just source-discovery-fixtures-check
just source-discovery-manifest-check manifest=<path>
just source-discovery-promotion-preview
just source-discovery-private-envelope-check
just source-discovery-accounting-check
just source-discovery-benchmark-check
just source-discovery-skill-eval-check
just source-discovery-ci
```

```text
OPENOPPS_DISCOVERY_NETWORK=disabled uv run python scripts/source_discovery_gates.py <gate>
```

Gates: `schema`, `fixtures`, `manifest`, `replay-bundle`, `promotion-preview`,
`private-envelope`, `accounting`, `skill-eval`, `benchmark`, `ci`.
`replay-bundle` writes a temporary quarantine, runs the verify-scout library
path, and discards the directory.

## Separate unexercised authority gates

The following remain **separate unexercised authority gates**. This runbook
does not perform them:

1. Live scheduler provisioning
2. Credential selection
3. Activation
4. Retention
5. Execution

Also still separate: Git commit/push, promotion apply, Kaggle mutation,
Cloudflare mutation, Vercel, release publication, source-policy 688 grants,
Alembic 0005 / ingest L.2, and B1099 close.

## Documented offline commands

These are the only commands this runbook authorizes. They require
`OPENOPPS_DISCOVERY_NETWORK=disabled`, use committed sanitized fixtures, and
must not upload or mutate Git.

<!-- d1017-offline-commands -->
```bash
OPENOPPS_DISCOVERY_NETWORK=disabled uv run python scripts/source_discovery_gates.py fixtures
OPENOPPS_DISCOVERY_NETWORK=disabled uv run python scripts/source_discovery_gates.py replay-bundle
OPENOPPS_DISCOVERY_NETWORK=disabled uv run python scripts/source_discovery_gates.py promotion-preview
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery preview-promotion --json
```
<!-- /d1017-offline-commands -->

CLI scout then verify-scout against an explicit private directory, then delete
it. Tests substitute a temporary directory for `$PRIVATE_OUTPUT` and the scout
JSON `manifestPath` for `$SCOUT_MANIFEST`. Never upload that directory.

<!-- d1017-offline-cli-readback -->
```bash
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery scout --output "$PRIVATE_OUTPUT" --json
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery verify-scout "$SCOUT_MANIFEST" --json
OPENOPPS_DISCOVERY_NETWORK=disabled uv run openopps discovery preview-promotion --json
```
<!-- /d1017-offline-cli-readback -->
