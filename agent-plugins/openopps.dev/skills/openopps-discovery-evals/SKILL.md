---
name: openopps-discovery-evals
description: >-
  Run contributor discovery evals with uv run python and just ci-discovery. Use when validating evals, frontmatter, or offline CI. NOT for MCP tools, live network, or publication proof.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps discovery evals

Offline gates. Scripts stay documented `uv run python` commands, not MCP tools.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | List eval scripts and `just ci-discovery`. |
| `skill-eval` / `evals` / `frontmatter` / `projection` / `docs-steward` | Run the matching skill script. |
| `ci` / `just` | `OPENOPPS_DISCOVERY_NETWORK=disabled just ci-discovery`. |
| `mcp` / add as MCP tool | Refuse; keep scripts off MCP. |
| `apply` / live CI network | Refuse. |

## Permission posture

Read-only validators except scout replay writing a temp quarantine dir. Network disabled in these gates.

## Critical Rules

1. Always set `OPENOPPS_DISCOVERY_NETWORK=disabled` for these gates.
2. Never run `wagents --apply`.
3. Do not add fixture scripts as MCP tools.
4. Must not treat a green `just ci-discovery` as live Workers/Kaggle proof.
5. Always keep evals as `uv run python` commands documented in recipes.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `skill-eval` | Evals, frontmatter, projection, docs-steward. |
| `just ci-discovery` | Offline discovery gate graph. |
| `MCP tools` | Do not add eval scripts as MCP tools. |

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
| `references/recipes.md` | Exact eval commands | After dispatch |
