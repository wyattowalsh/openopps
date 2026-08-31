## Context

OpenOpps is a CLI-first Python package with a static Fumadocs site. Python plugins load through the `openopps.plugins` entry point group. Quarantined discovery (`openopps discovery scout|verify-scout|preview-promotion` and the `admin sources` aliases) is isolated from `openopps sync`. The portable source-scout skill currently lives at `skills/openopps-source-scout/` and is inert/advisory.

Agent Plugins 1.0.0 is a filesystem package format (`plugin.json`, `skills/`, `mcp.json`, `./bin/mcp`) that clients load from a local path. This change adds two packages in-tree and does not create a marketplace.

## Goals / Non-Goals

**Goals:**

- Ship `openopps` (end users of the installed CLI except quarantined discovery) and `openopps-dev` (checkout contributors: source-scout, discovery CLI, isolation, evals).
- Match Agent Plugins 1.0.0 layout and schemas exactly; omit `extensions`.
- Author skills with skill-creator structure (dispatch table, empty-args, Use when / NOT for). MCP is stdlib stdio `help`+`run`, not skill-creator work.
- Keep source-scout inert; acceptance remains `launch_isolated_scout`.
- Validate in CI through existing Python jobs (`just agent-plugins-check` inside `just ci-python`).

**Non-Goals:**

- Marketplace, npm package, hosted MCP (`sse` / `streamable-http`), or public `openopps mcp` CLI command.
- Client-extension directories or `com.*` folders.
- Harness projection (`.agents/skills`, `.cursor/skills`) or `wagents --apply`.
- Live Cloudflare Workers, Kaggle mutation, Alembic `0005`, source-policy 1780 publication.
- Driving a browser, mutating the Next.js app, or calling `/api/` / live Workers from `openopps-web`.
- Turning `examples/plugins/` into Agent Plugins packages.
- A general contributing, OpenSpec, web, Kaggle, or Workers plugin under `openopps-dev`.

## Decisions

### Two packages, inverse filters

| Plugin `name` | Root | MCP `run` |
| --- | --- | --- |
| `openopps` | `agent-plugins/openopps/` | Deny `discovery *` and `admin sources scout\|verify-scout\|preview-promotion` |
| `openopps-dev` | `agent-plugins/openopps.dev/` | Allow only `discovery scout\|verify-scout\|preview-promotion` (prefer `--json`) |

Contributor hub **skill** directory is kebab-case `openopps-dev` (skill-creator). Plugin **name** is also `openopps-dev`: Agent Plugins 1.0.0 allows a single dot for namespacing, but Grok and Claude plugin validators reject dots. The checkout directory keeps `openopps.dev/` as the path SSOT.

### MCP shape

- One stdio server, `"command": "./bin/mcp"`, `"cwd": "${PLUGIN_ROOT}"`.
- Also ship `.mcp.json` without `$schema` so Grok/Claude plugin MCP discovery finds `./bin/mcp`.
- Do not set `env.PLUGIN_ROOT` or `env.PLUGIN_DATA`.
- Duplicate `./bin/mcp` per package (self-contained). Detect mode from sibling `plugin.json` `name`.
- Tools: `help` and `run` only. No generated per-Typer tools.
- Inner CLI resolution: `OPENOPPS_BIN`, then `openopps` on inherited `PATH`, then `uv run openopps` in the checkout found by walking to `pyproject.toml` whose project name is `openopps`.
- Windows shebang is out of current CI; `./bin/mcp` is executable with `python3` shebang.

### Source-scout move

Copy/move the skill **into** the contributor plugin. Do not symlink out of the plugin root. Resolve repository root by walking to `pyproject.toml`, not `SKILL_ROOT.parents[1]`. Keep `SKILL_ROOT = Path(__file__).resolve().parent.parent`. `resolve_docs_steward.py` still looks for `skills/docs-steward` on the **repository** root.

### Schema vendor

CI never fetches schemas at plugin load. Vendor 1.0.0 copies at `tests/fixtures/agent-plugins/schemas/1.0.0/`. `scripts/verify_agent_plugins.py` validates locally with a Draft 2020-12 subset sufficient for these two schemas (no new `jsonschema` runtime dependency).

### Docs and CI

New MDX page `web/content/docs/agent-plugins.mdx`, `meta.json` entry, and `DOC_ROUTES` in `web/app/sitemap.ts`. Cross-link README, contributing, CLI, operations, nested `AGENTS.md`. No sixth GitHub Actions job.

## Risks / Trade-offs

- Clients inject `PLUGIN_ROOT` / `PLUGIN_DATA`; committed `mcp.json` must not contain machine-local `OPENOPPS_BIN`. Document inherited env.
- A plugin-local `pyproject.toml` would break uv-run walk; the resolver requires the OpenOpps project name.
- skill-creator is operator-local; repo CI asserts structure in `tests/unit/openopps/test_agent_plugins.py`.
- Historical OpenSpec evidence in `bounded-quarantined-source-discovery/tasks.md` still names `skills/openopps-source-scout/`; do not reopen that change.

## Migration Plan

1. Vendor schemas and add red tests.
2. Scaffold both packages and MCP runners.
3. Move source-scout and retarget gates.
4. Author skills.
5. Docs + fold CI recipe.
6. Audit and `just agent-plugins-check`.

Rollback is deleting `agent-plugins/` and restoring `skills/openopps-source-scout/` plus path strings. No live authority or schema migration is involved.
