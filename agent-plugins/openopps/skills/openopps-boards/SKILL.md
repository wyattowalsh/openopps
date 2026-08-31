---
name: openopps-boards
description: >-
  Check local OpenOpps boards: list, show, sync, and export. Use when the user asks about company boards or routes. NOT for job listing, URL pulls, or source-scout.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps boards

Durable firm/company hiring boards discovered from sources.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | `openopps boards list` with source/provider/company filters. |
| `show <key>` | `openopps boards show`. |
| `sync` | `openopps boards sync` (hand off filters; still boards-scoped). |
| `export` | `openopps boards export`. |
| `jobs` | Hand off to `openopps-jobs`. |
| `discovery` | Refuse. |

## Permission posture

List/show/export are local. Sync writes boards/routes. Do not `--apply` admin detect unless the user asked for `openopps-admin`.

## Critical Rules

1. Always prefer `--json` for board list/show/export.
2. Never treat public `boards` as `admin boards add`.
3. Do not fetch live ATS postings from this skill.
4. Must keep board keys as `source:slug`; `remote_slug` is upstream only.
5. Never run discovery or URL pull from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `boards list` | Read stored board rows. |
| `boards sync` | Refresh boards from configured sources. |
| `jobs list` | Job ledger; different skill. |

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
| `references/recipes.md` | Boards command strings | After dispatch |
