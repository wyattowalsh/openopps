---
name: openopps-sync
description: >-
  Run staged OpenOpps source, board, and job sync. Use when the user asks to sync catalogs or run openopps sync. NOT for URL pulls, job listing, or discovery.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps sync

Everyday ingest: sources → boards → jobs. Top-level `openopps sync` runs that order.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | Run `openopps sync` (optional source key). |
| `sources` | `openopps sources sync [source]`. |
| `boards` | `openopps boards sync`. |
| `jobs` | `openopps jobs sync`. |
| Filters (`--source`, `--board`, `--provider`) | Pass the same flags the CLI documents. |
| `pull` / URL | Hand off to `openopps-url-pull`. |
| `discovery` / `scout` | Refuse. Discovery is not same-run with sync. |

## Permission posture

May shell sync commands that write local SQLite. Confirm `OPENOPPS_DB_URL` first. Do not run discovery in the same run.

## Critical Rules

1. Always keep discovery out of the same run as `openopps sync`.
2. Never treat `--provider any` or `--provider all` as a named provider.
3. Do not apply quarantined scout output here.
4. Must prefer `--json` / `--metrics-json` for automation.
5. Never run `openopps discovery *` from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `openopps sync` | Staged source, board, and job sync. |
| `metrics-json` | Machine-readable sync metrics on stdout. |
| `discovery` | Quarantined scout family; never same-run. |

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
| `references/recipes.md` | Sync command strings | After dispatch |
