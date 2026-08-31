---
name: openopps-admin
description: >-
  Run advanced OpenOpps admin except scout aliases. Use when needing admin db, cache purge, or route probing. NOT for admin sources scout, verify-scout, preview-promotion, or discovery.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps admin

Advanced maintenance. Discovery aliases on `admin sources` are denied by this plugin's MCP `run` and by this skill.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | List admin groups and the scout deny-list. |
| `db` | `admin db init|status|export|vacuum`. |
| `cache purge` | `admin cache purge` after confirming delete scope. |
| `sources add` / `test` / `yield` | Allowed admin source commands (not scout). |
| `boards` | `admin boards add`, `add-provider`, `enrich`, `detect-provider`. |
| `providers` | `admin providers list|detect|explain|probe-routes|registry`. |
| `scout` / `verify-scout` / `preview-promotion` / `discovery` | Refuse; use `openopps-dev`. |

## Permission posture

These commands can write SQLite or delete cache. Confirm `--apply` and purge scope. Never run scout aliases.

## Critical Rules

1. Always refuse `admin sources scout|verify-scout|preview-promotion`.
2. Never persist probe-routes or health without `--apply`.
3. Do not run Alembic `0005`, Workers, or Kaggle from this skill.
4. Must target `OPENOPPS_DB_URL` for `admin db init`.
5. Never treat cache purge as a default; require an explicit delete request.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `admin db` | Local SQLite maintenance. |
| `admin cache purge` | Explicit delete; confirm namespace. |
| `admin sources scout` | Quarantined; refuse. |

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
| `references/recipes.md` | Admin command strings | After dispatch |
