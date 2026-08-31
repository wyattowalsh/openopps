---
name: openopps-status
description: >-
  Check local OpenOpps status and doctor checklists. Use when asking whether the CLI is healthy or what the DB contains. NOT for syncing, probing, or discovery.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps status

`status` and `doctor` read local DB, cache, and plugin load state.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | `openopps status --json`. |
| `doctor` / `setup` | `openopps doctor --json` plus the first-run checklist. |
| `sync` | Hand off to `openopps-sync`. |
| `discovery` | Refuse. |

## Permission posture

Read-only local inspection. Do not init the DB unless the user asked `openopps-admin`.

## Critical Rules

1. Always prefer `--json` for status and doctor.
2. Never treat doctor as a live ATS network probe.
3. Do not crash the CLI when a Python plugin fails; surface it here.
4. Must keep this skill read-only.
5. Never run sync, probe-routes, or discovery from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `status` | Local DB and runtime snapshot. |
| `doctor` | Checklist of next healthy actions. |
| `sync` | Mutation; different skill. |

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
| `references/recipes.md` | Status command strings | After dispatch |
