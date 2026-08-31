---
name: openopps-discovery
description: >-
  Run quarantined OpenOpps discovery CLI commands. Use when the user wants scout, verify-scout, or preview-promotion JSON. NOT for sync, admin mutation, or treating prose as acceptance.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps discovery CLI

Three commands. No `--apply`. Not same-run with sync.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | Restate scout / verify-scout / preview-promotion and JSON. |
| `scout` | `openopps discovery scout --output <dir> --json` (explicit quarantine dir). |
| `verify-scout` | `openopps discovery verify-scout <manifest> --json` (offline, no rewrite). |
| `preview-promotion` | `openopps discovery preview-promotion [manifest] --json` (dry-run). |
| `sync` / `--apply` | Refuse. |
| `isolate` | Hand off to `openopps-isolation`. |
| `skill` | Hand off to `openopps-source-scout`. |

## Permission posture

Scout writes only the given quarantine directory. Verify and preview are read-only. Keep `OPENOPPS_DISCOVERY_NETWORK=disabled` unless the user explicitly runs a live scout outside CI.

## Critical Rules

1. Always prefer `--json` (MCP `run` injects it).
2. Never pass `--apply` on these commands.
3. Do not open operational SQLite, catalogs, Git, Kaggle, or Cloudflare.
4. Must keep MCP `run` on `discovery scout|verify-scout|preview-promotion` only.
5. Never share a run with `openopps sync`.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `discovery scout` | Write a quarantine directory; JSON. |
| `verify-scout` | Offline verify of a scout manifest. |
| `preview-promotion` | Dry-run promotion preview; no apply. |

## Loading

Read reference files as indicated by the dispatch table. Do not load all at once.

### Progressive disclosure

Frontmatter for discovery. Load recipes on demand after dispatch. Do not load all at once.

### Classification logic

1. Always follow the dispatch table before shelling a command.
2. Never expand scope into denied command families.
3. Require explicit user intent for write or delete classes.

## Reference File Index

| File | Content | Read when |
| --- | --- | --- |
| `references/recipes.md` | Discovery CLI strings | After dispatch |
