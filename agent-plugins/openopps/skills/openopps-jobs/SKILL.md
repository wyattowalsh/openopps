---
name: openopps-jobs
description: >-
  Check stored OpenOpps jobs: list, show, history, and export. Use when the user wants local ledger job records. NOT for jobs pull, jobs sync, or discovery.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps jobs

Read and export normalized jobs already in local SQLite.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | `openopps jobs list` with optional filters and `--json`. |
| `show <id>` | `openopps jobs show`. |
| `history <id>` | `openopps jobs history`. |
| `export` | `openopps jobs export` to JSONL, CSV, or Parquet. |
| `pull` / URL | Hand off to `openopps-url-pull`. |
| `sync` | Hand off to `openopps-sync`. |
| `discovery` | Refuse. |

## Permission posture

List/show/history are reads. Export writes files the user names. Do not sync or pull unless handed off.

## Critical Rules

1. Always prefer `--json` for list filters.
2. Never fetch live ATS data via `jobs list/show/history/export`.
3. Do not call web `/api/jobs/search`.
4. Must hand off URL ingest to `openopps-url-pull`.
5. Never run discovery from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `jobs list` | Read stored job rows from local SQLite. |
| `jobs export` | Write named JSONL, CSV, or Parquet. |
| `jobs pull` | Live URL ingest; not this skill. |

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
| `references/recipes.md` | Jobs command strings | After dispatch |
