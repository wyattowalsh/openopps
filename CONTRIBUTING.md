# Contributing

OpenOpps contribution workflow, local setup, validation commands, and review expectations live in the web app docs.

- **Docs route:** `/docs/contributing` when running the web app
- **Source:** [`web/content/docs/contributing.mdx`](web/content/docs/contributing.mdx)

From the repository root:

```bash
mise x node@24.20.0 pnpm@11.24.0 -- pnpm --dir web install --frozen-lockfile
mise x node@24.20.0 pnpm@11.24.0 -- pnpm --dir web dev
```

The web toolchain is pinned by `.node-version` and `web/package.json`. An equivalent version manager plus Corepack is fine; use Node 24.20.0 and pnpm 11.24.0 exactly.

Then open `/docs/contributing`. Prefer `just web-*` recipes (for example `just web-check`). For validation before a PR, see that guide and run `just quick` or `just ci` from the repo root.

Alembic `0005_update_snapshot_ledger` and `0006_url_pull_runs` have landed (live head `0006_url_pull_runs`). URL-pull persistence is opt-in `--save` (default False). Live stops stay in force: no Workers upload, no Kaggle mutation, source-policy 1780 blocked, no hosted-alpha, no v7 7.6. Package `release.yml` publishes from an exact SHA and must not create tags.

Two Agent Plugins 1.0.0 packages live at [`agent-plugins/openopps/`](agent-plugins/openopps/) (installed-CLI users) and [`agent-plugins/openopps.dev/`](agent-plugins/openopps.dev/) (checkout contributors, including source-scout SSOT). Point a local agent client at those directories. There is no marketplace, hosted MCP URL, or public `openopps mcp` command. Validate with `just agent-plugins-check`. Details: [`web/content/docs/agent-plugins.mdx`](web/content/docs/agent-plugins.mdx) (`/docs/agent-plugins`).
