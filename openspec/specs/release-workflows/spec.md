# release-workflows Specification

## Purpose
Define the release workflow contract across local Justfile recipes, CI parity, generated public artifacts, documentation, and OpenSpec validation surfaces.
## Requirements
### Requirement: Local validation is discoverable through Justfile

OpenOpps SHALL provide a root Justfile that lists and runs the common contributor validation workflows without hiding the underlying `uv`, `pnpm`, OpenSpec, and docs commands.

#### Scenario: Contributor discovers commands

- **WHEN** a contributor runs `just --list`
- **THEN** the output includes recipes for quick checks, full CI parity, tests, coverage, docs, OpenSpec validation, Kaggle metadata, CLI help, and cleanup inspection

#### Scenario: Contributor runs full local validation

- **WHEN** a contributor runs the full local CI recipe
- **THEN** it runs the same validation families as GitHub Actions
- **AND** failures can be reproduced by running the underlying command shown in the recipe body

### Requirement: CI mirrors local validation

OpenOpps SHALL provide GitHub Actions validation that mirrors local just recipes and uses least-privilege, cache-aware setup.

#### Scenario: Pull request opens

- **WHEN** CI runs for a pull request or push
- **THEN** it validates Python tests, coverage, OpenSpec strict state, docs generated data and type-check/build/lint, Kaggle metadata, CLI help, and repository diff hygiene
- **AND** the workflow uses read-only contents permissions unless a future job explicitly needs more

#### Scenario: New commit supersedes an in-progress run

- **WHEN** a newer commit is pushed to the same branch or pull request
- **THEN** in-progress runs for the same workflow/ref are cancelled

### Requirement: Generated artifact surfaces are explicit

OpenOpps SHALL document and validate generated docs data and Kaggle metadata as tracked public artifact surfaces.

#### Scenario: Exported models change

- **WHEN** package models, provider registry data, docs metadata, or Kaggle-exported schema changes
- **THEN** contributors can run documented just recipes to regenerate and validate derived docs/Kaggle artifacts

### Requirement: Workflow docs stay synchronized

OpenOpps SHALL keep README, docs pages, DESIGN.md, nested AGENTS.md, Justfile recipes, CI jobs, and OpenSpec tasks synchronized for public workflow changes.

#### Scenario: Validation command changes

- **WHEN** a validation command or public workflow changes
- **THEN** the corresponding README/docs, agent instructions, OpenSpec task, CI job, and just recipe are updated in the same logical change
