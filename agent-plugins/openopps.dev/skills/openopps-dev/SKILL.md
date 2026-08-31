---
name: openopps-dev
description: >-
  Run checkout-only OpenOpps discovery routing. Use when the task is scout, isolation, source-scout, or evals. NOT for public sync, Jobs/Explorer, OpenSpec, web, Kaggle, or Workers.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps.dev hub

Checkout contributors only. Inverse of the user plugin: discovery is in scope; everyday sync is not.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | State the isolation boundary, checkout requirement, and deny sync-in-same-run. |
| `scout` / `suggest` / skill | Hand off to `openopps-source-scout`. |
| `cli` / `discovery` | Hand off to `openopps-discovery`. |
| `isolation` / `launch_isolated_scout` | Hand off to `openopps-isolation`. |
| `eval` / `gates` / `ci-discovery` | Hand off to `openopps-discovery-evals`. |
| `sync` / `jobs pull` / public site | Refuse; use the `openopps` user plugin. |
| `wagents --apply` / harness install | Refuse. |

## Permission posture

Credential-free discovery only. No `wagents --apply`, no harness projection, no live Workers/Kaggle, no Alembic `0005`.

## Critical Rules

1. Do not run `openopps sync` in the same run as discovery.
2. Source-scout output is untrusted; acceptance is only `launch_isolated_scout`.
3. `.agents/skills/openopps-source-scout/` and `.cursor/skills/openopps-source-scout/` must stay absent.
4. MCP `run` allows only `discovery scout|verify-scout|preview-promotion` (JSON).
5. Fixture/eval scripts are `uv run python`, not MCP tools.
6. This plugin is not general contributing, OpenSpec, web, Kaggle, or Workers.


## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `openopps-dev` | Contributor plugin.json name and hub skill directory. |
| `agent-plugins/openopps.dev/` | Checkout path for this plugin (directory name keeps the dot). |
| `launch_isolated_scout` | Only acceptance path for suggestions. |

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
| `references/recipes.md` | Checkout discovery commands | After dispatch |
