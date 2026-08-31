---
name: openopps-operations
description: >-
  Run cache inspection, plugins list, and examples seed. Use when asking about HTTP cache or example datasets. NOT for admin cache purge, discovery, or Next.js edits.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps operations

Cache status, Python plugin inspection, and deterministic example seed.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | Summarize cache / plugins list / examples seed. |
| `cache` | `openopps cache status --json`. |
| `plugins` | `openopps plugins list --json` (Python entry points, not Agent Plugins). |
| `seed` / `examples` | `openopps examples seed --json`. |
| `purge` | Hand off to `openopps-admin` (destructive). |
| `discovery` | Refuse. |

## Permission posture

Cache status and plugins list are reads. `examples seed` writes the selected DB. Purge is admin-only.

## Critical Rules

1. Always treat `plugins list` as Python `openopps.plugins`, not this Agent Plugin.
2. Never treat `examples seed` as production coverage.
3. Do not run `admin cache purge` unless the user clearly asked to delete cache.
4. Must keep HTTP cache inspect read-only by default.
5. Never run discovery from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `cache` | HTTP JSON cache inspect/stats. |
| `plugins list` | Python openopps.plugins inventory. |
| `examples seed` | Deterministic local example dataset. |

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
| `references/recipes.md` | Operations command strings | After dispatch |
