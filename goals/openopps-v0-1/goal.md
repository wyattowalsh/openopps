# OpenOpps v0.1 Goal

Make OpenOpps v0.1 the first public ground-truth release of a polished local-first CLI for discovering, inspecting, syncing, filtering, and exporting public startup hiring data.

Use the approved goal package files as the source of truth:

- `goals/openopps-v0-1/facts.md`
- `goals/openopps-v0-1/plan.md`

Core constraints:

- Keep v0.1 CLI-only; do not add TUI, Textual, interactive prompt flows, browser UI, or web UI behavior.
- Redesign the public CLI around the everyday user journey and move internal maintenance operations behind advanced/admin/debug surfaces.
- Add robust SQLite-backed caching, richer metadata capture, measured provider coverage reporting, deterministic examples, and a researched plugin architecture.
- Optimize implementation for parallel subagent waves only after OpenSpec and shared model/interface contracts are frozen.
- Treat v0.1 as the first public baseline, so obsolete internal command paths do not need compatibility aliases.

Done means the documented quickstart works from a fresh clone and validates discovery, route readiness, job sync, caching, plugin inspection, generated examples, filtering, export, failure interpretation, provider coverage reporting, tests, OpenSpec validation, docs build, and JSON parseability.
