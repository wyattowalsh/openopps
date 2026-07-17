# Contributing

OpenOpps contribution workflow, local setup, validation commands, and review expectations live in the web app docs.

- **Docs route:** `/docs/contributing` when running the web app
- **Source:** [`web/content/docs/contributing.mdx`](web/content/docs/contributing.mdx)

From the repository root:

```bash
cd web && pnpm install && pnpm dev
```

Then open `/docs/contributing`. Prefer `just web-*` recipes (for example `just web-check`); `just docs-*` remains as transitional aliases. For validation before a PR, see that guide and run `just quick` or `just ci` from the repo root.
