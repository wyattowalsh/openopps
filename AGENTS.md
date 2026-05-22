OpenOpps is a Python 3.12+ CLI-only v0.1 project managed with `uv` and `pyproject.toml`.

- `./src/openopps/` is the Python package and `openopps = "openopps.cli:app"` console entry point.
- `./tests/` mirrors package behavior by execution scope: `tests/unit/openopps/` for isolated module tests, `tests/integration/openopps/` for local storage/CLI/mocked HTTP seams, `tests/smoke/openopps/` for fast critical wiring checks, and `tests/e2e/` reserved for real-boundary journeys.
- `./scripts/` contains helper scripts such as docs metadata generation.
- `./examples/plugins/minimal-openopps-plugin/` is the minimal entry-point plugin template for the `openopps.plugins` group.
- `./docs/` is the Fumadocs/Next.js docs framework; use pnpm from that directory. Its content graph lives in `docs/content/docs/meta.json`, MDX pages live in `docs/content/docs/`, package-derived docs data is generated into `docs/lib/generated/openopps-data.json`, and LLM-readable routes are exposed by `docs/app/llms.txt/`, `docs/app/llms-full.txt/`, and `docs/app/llms.mdx/` route handlers.
- `./openspec/` contains OpenSpec specs and change tracking, including `prepare-v0-1-release`.
- `./DESIGN.md` is the project design system. Read it before changing visual UI, docs theme, typography, colors, spacing, or component styling.
- Runtime configuration uses `OPENOPPS_` environment variables via Pydantic Settings. Local `.env` files may be used but must not be printed or committed.
- Keep OpenOpps CLI-first. Do not add prompt, TUI, browser, web app, or hosted-service flows unless the user explicitly changes product scope.

Useful validation commands:

```bash
uv run pytest
uv run pytest --cov=openopps --cov-report=term-missing
cd docs && pnpm data:generate
cd docs && pnpm types:check
cd docs && pnpm build
cd docs && rtk lint
rtk npx -y @fission-ai/openspec@latest validate "prepare-v0-1-release" --strict
```

Update nested `AGENTS.md` files when package responsibilities, docs framework wiring, validation commands, or repo-local workflows change.
