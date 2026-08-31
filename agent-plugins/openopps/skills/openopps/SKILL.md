---
name: openopps
description: >-
  Configure installed-CLI OpenOpps routing, JSON, and safety classes. Use when choosing a public command group. NOT for discovery, source-scout, or Next.js edits.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps hub

Drive the public OpenOpps CLI for an installed user. Prefer `openopps` on PATH or `OPENOPPS_BIN`. In a checkout, `uv run openopps` is fine. MCP `run` from this package refuses `discovery` and `admin sources scout|verify-scout|preview-promotion`.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| `install` / `path` / `setup` | Show install and CLI resolution (`OPENOPPS_BIN`, PATH, `uv run`). |
| `json` / `metrics` | Prefer `--json` / `--metrics-json`; keep stdout parseable. |
| `safety` / `apply` / `purge` | Classify `--apply` and `admin cache purge` as explicit write/delete. |
| `config` / `env` / `db` | Map `OPENOPPS_*` and `OPENOPPS_DB_URL` (relative SQLite follows cwd). |
| `plugins` / `naming` | Distinguish Python `openopps.plugins` from this Agent Plugin. |
| `docs` / `llms` | Point at https://www.openopps.dev/docs and `/llms.txt`. |
| A URL | Hand off to `openopps-url-pull`. |
| `sync` | Hand off to `openopps-sync`. |
| `jobs` / `boards` / `sources` / `providers` / `status` / `cache` / `admin` / `web` | Hand off to the matching skill. |
| `discovery` / `scout` / `source-scout` | Refuse; use the `openopps-dev` plugin in a checkout. |
| Empty | Summarize public groups, JSON defaults, safety classes, and the discovery deny-list. |

## Permission posture

May shell `openopps` and MCP `help`/`run` for public commands. Do not call discovery, live Workers, Kaggle, or Alembic `0005`. Do not commit `.env`.

## Critical Rules

1. Never run `openopps discovery *` or `admin sources scout|verify-scout|preview-promotion` from this plugin.
2. Never share discovery with `openopps sync` in the same run.
3. Python `openopps.plugins` (`examples/plugins/`) is a different system from Agent Plugins.
4. Prefer `--json` for automation. Do not mix human diagnostics onto machine stdout.
5. Treat `--apply` and `admin cache purge` as explicit mutation; confirm scope first.
6. `OPENOPPS_DB_URL` defaults to `sqlite:///openoppsdb.sqlite` relative to process cwd.
7. Point humans at https://www.openopps.dev/docs/agent-plugins and `/llms.txt`.
8. There is no public `openopps mcp` command; clients start `./bin/mcp`.

## Safety classes

| Class | Examples | Rule |
| --- | --- | --- |
| Read | `status`, `doctor`, `* list`, `* show`, `providers coverage` | Safe default. |
| Write local | `sync`, `examples seed`, `admin db init` | Needs a chosen `OPENOPPS_DB_URL`. |
| Persist diagnostics | `providers health --apply`, `admin providers probe-routes --apply` | Dry-run first. |
| Delete | `admin cache purge` | Namespace-scope when possible. |
| Quarantined | `discovery *` | Denied here. |

## Docs

- Site: https://www.openopps.dev/docs
- Agent Plugins: https://www.openopps.dev/docs/agent-plugins
- LLM index: https://www.openopps.dev/llms.txt


## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `OPENOPPS_BIN` | Preferred explicit path to the openopps executable. |
| `openopps.plugins` | Python entry-point plugins; not this Agent Plugin. |
| `quarantined discovery` | scout, verify-scout, and preview-promotion; denied here. |

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
| `references/recipes.md` | Install, JSON, config, and hand-off commands | After dispatch |
