# Contributing

OpenOpps contribution workflow, local setup, validation commands, and review expectations live in the web app docs.

- **Docs route:** `/docs/contributing` when running the web app
- **Source:** [`web/content/docs/contributing.mdx`](web/content/docs/contributing.mdx)

From the repository root:

```bash
cd web && pnpm install && pnpm dev
```

Then open `/docs/contributing`. Prefer `just web-*` recipes (for example `just web-check`); `just docs-*` remains as transitional aliases. For validation before a PR, see that guide and run `just quick` or `just ci` from the repo root.

Two Agent Plugins 1.0.0 packages live at [`agent-plugins/openopps/`](agent-plugins/openopps/) (installed-CLI users) and [`agent-plugins/openopps.dev/`](agent-plugins/openopps.dev/) (checkout contributors, including source-scout SSOT). Point a local agent client at those directories. There is no hosted marketplace, hosted MCP URL, or public `openopps mcp` command. Validate with `just agent-plugins-check`. Details: [`web/content/docs/agent-plugins.mdx`](web/content/docs/agent-plugins.mdx) (`/docs/agent-plugins`).
