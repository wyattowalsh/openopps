## Why

Favorite agents cannot drive OpenOpps through a spec-shaped package. The public CLI, the quarantined discovery surface, and the inert source-scout skill are documented for humans, but they are not packaged as [Agent Plugins 1.0.0](https://agent-plugins.org/specification) roots that a client can load from the checkout. Mixing those audiences would either expose `discovery` / `admin sources scout` to end users or bury contributor isolation inside a general CLI plugin.

Python `openopps.plugins` entry points remain a different system. Without an explicit Agent Plugins contract, clients would invent MCP tool sprawl, hosted URLs, or harness projections that this repository forbids.

## What Changes

- Add two codebase-associated Agent Plugins 1.0.0 packages: `agent-plugins/openopps/` for installed-CLI users and `agent-plugins/openopps.dev/` for checkout contributors.
- Shape each package as `plugin.json`, `skills/<dir>/SKILL.md`, `mcp.json`, plugin-bundled `./bin/mcp`, and `LICENSE`. Omit `extensions` and client-extension directories.
- Expose stdio MCP tools `help` and `run` only. User `run` refuses quarantined discovery. Dev `run` allows only `openopps discovery scout|verify-scout|preview-promotion` (JSON).
- Resolve the inner CLI as `OPENOPPS_BIN`, then `openopps` on `PATH`, then `uv run openopps` after walking to repository `pyproject.toml`. Do not add a public `openopps mcp` Typer command or hosted MCP.
- Move source-scout SSOT to `agent-plugins/openopps.dev/skills/openopps-source-scout/`, retarget evals/gates/docs, keep `.agents/` and `.cursor/` projections absent, and never run `wagents --apply`.
- Document local client paths on README, contributing, CLI, operations, nested `AGENTS.md`, and `/docs/agent-plugins`. Fold `just agent-plugins-check` into `just ci-python`.
- Vendor Agent Plugins 1.0.0 schemas under `tests/fixtures/agent-plugins/schemas/1.0.0/` and validate locally.

## Capabilities

### New Capabilities

- `agent-plugins`: Two Agent Plugins 1.0.0 packages, stdio MCP filters, source-scout SSOT location, local distribution, and CI schema gates.

### Modified Capabilities

- `cli-domain`: No public `openopps mcp` command; user agents drive the existing CLI except quarantined discovery; contributor agents drive discovery through the dev plugin only.
- `plugins`: Distinguish Python `openopps.plugins` entry points (`examples/plugins/`) from Agent Plugins packages (`agent-plugins/`).
- `docs-product-boundary`: Add `/docs/agent-plugins` and keep the public site a read-only companion for the user plugin.
- `release-workflows`: Vendor schemas, `scripts/verify_agent_plugins.py`, `just agent-plugins-check` inside `just ci-python`, no extra GitHub Actions job.

## Impact

- New tree `agent-plugins/openopps/` and `agent-plugins/openopps.dev/` plus vendored schemas, verifier, and unit tests.
- Move `skills/openopps-source-scout/` into the contributor plugin; rewrite repo-root resolution to walk to `pyproject.toml`.
- Docs, Justfile, nested `AGENTS.md`, and sitemap updates. No marketplace, npm package, hosted MCP, live Workers/Kaggle, Alembic `0005`, or source-policy 1780 publication.
- Discovery remains not same-run with `openopps sync`.

## Acceptance summary

1. Both packages validate against vendored Agent Plugins 1.0.0 `plugin.schema.json` and `mcp.schema.json`.
2. User MCP deny-list and dev MCP allow-list unit tests pass; `./bin/mcp` resolution order holds; no public `openopps mcp` command.
3. Source-scout lives only at `agent-plugins/openopps.dev/skills/openopps-source-scout/` with retargeted evals/gates and absent harness projections.
4. Docs cover install/usage including `/docs/agent-plugins`; `just agent-plugins-check` is part of `just ci-python`; discovery network stays disabled in discovery gates.
5. `examples/plugins/` remains the Python plugin template. No marketplace, hosted MCP, client-extension dirs, or live publication.
