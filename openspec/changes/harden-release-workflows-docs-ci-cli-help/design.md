## Overview

This change treats repository workflow surfaces as part of the v0.1 product contract. A contributor should be able to discover work through OpenSpec, run local validation through `just`, see the same checks in GitHub Actions, and find the same commands in README/docs/CLI help without contradictory guidance.

## OpenSpec Workflow

OpenSpec remains `spec-driven`; no local schema fork is needed for this change because the package schema already supports proposal, design, specs, and tasks. The repo config now adds stricter rules for workflow/tooling changes and agent-readable handoffs:

- Use `list --json` and `status --change <id> --json` to discover active state.
- Use `instructions --change <id> <artifact> --json` when handing tasks to agents.
- Use `validate --all --strict` for release-wide checks.
- Add schema validation only if future work introduces a local schema fork.

## Local and CI Parity

The Justfile is the local command index. GitHub Actions should not invent hidden behavior; every required CI lane must have a matching just recipe and each recipe must expose the underlying command directly enough for debugging.

Required lanes:

- Python tests and coverage through `uv`.
- OpenSpec validation for all active changes.
- Docs generated data, type-check, build, and lint through `pnpm`.
- Kaggle metadata generation.
- CLI help smoke check.
- Git diff/whitespace check.

## Documentation Sync

Docs and instructions must update together when public workflow surfaces change:

- `README.md` gives the quick command path.
- `docs/content/docs/*.mdx` gives detailed operational guidance.
- `DESIGN.md` owns visual and content-design constraints for docs UI.
- Root and nested `AGENTS.md` files define agent/contributor guardrails.
- CI and Justfile names should appear consistently in docs.

## CLI Help Quality

CLI help remains Typer/Rich-based and command-behavior-preserving. Improvements should be tested with semantic assertions rather than full terminal snapshots because wrapping and Rich formatting vary by terminal width.

Root help should:

- Present the everyday workflow before operational/admin commands.
- Include a short first-run path with `status`, `sync`, `providers coverage`, and `jobs list`.
- Call out `--json` and `--metrics-json` for automation.
- Keep advanced diagnostics visible but clearly marked.

## Parallel Task Graph

1. Baseline: capture dirty status, OpenSpec list/status JSON, CLI help, and generated artifact state.
2. OpenSpec lane: update config rules and add this hardening change.
3. CI/Just lane: add local recipes and GitHub Actions jobs with matching names.
4. Docs/Instructions lane: sync README, DESIGN, docs, and AGENTS guidance.
5. CLI lane: refine help text and semantic tests.
6. Integration: regenerate docs/Kaggle artifacts as needed.
7. Verification: run just parity commands, OpenSpec validation, tests, docs build, and git diff checks.

Steps 2 through 5 can run in parallel if ownership is respected; steps 6 and 7 are sequential.
