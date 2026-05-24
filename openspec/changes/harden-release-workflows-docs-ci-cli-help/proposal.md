## Summary

Harden OpenOpps v0.1 release workflows by making OpenSpec, documentation, agent instructions, CI/CD, the contributor Justfile, and CLI help operate as one synchronized public workflow surface.

## Motivation

OpenOpps now has a broad CLI, generated docs data, generated Kaggle metadata, plugin seams, provider-route diagnostics, and multiple active OpenSpec changes. Contributors and agents need a single reliable path for discovering tasks, validating changes, and reproducing CI locally. The current repo has strong individual commands, but the connections between OpenSpec state, docs, just recipes, GitHub Actions, and CLI help are not yet explicit enough.

## Scope

- Extend OpenSpec rules for workflow/tooling changes, agent-readable status, and parallel task dispatch.
- Add release-hardening requirements for local/CI parity, generated artifacts, docs/instructions synchronization, and CLI help quality.
- Add or update GitHub Actions to mirror local validation with least-privilege permissions and cache-aware setup.
- Add a root Justfile as the human-friendly command index for tests, docs, OpenSpec, Kaggle metadata, CLI help checks, and CI parity.
- Tighten README, DESIGN.md, docs, and nested AGENTS.md so supporting files describe the same workflow.
- Keep OpenOpps CLI-only; this change does not add a hosted service, browser UI, TUI, prompts, background scheduler, or credentialed integrations.

## Non-Goals

- Do not change provider ingestion semantics, route dedupe, storage schema, plugin contracts, or export wire formats.
- Do not introduce compatibility aliases for pre-v0.1 commands.
- Do not make CI publish releases, upload Kaggle bundles, deploy docs, or use secrets.
- Do not replace Fumadocs, Tailwind, shadcn/ui, uv, pnpm, Typer, or OpenSpec.

## Parallelization Strategy

Implementation is intentionally split into independent lanes:

- OpenSpec lane: config rules and this change directory.
- CI/Just lane: `.github/**` and `Justfile`.
- Docs/Instructions lane: README, DESIGN, docs MDX, and nested AGENTS files.
- CLI Help lane: Typer help text and semantic help tests.
- Integration lane: generated artifacts and full validation after all lanes land.
