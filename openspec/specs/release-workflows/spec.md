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

### Requirement: Docs search index uses tiered committed artifacts

OpenOpps SHALL publish the public jobs and explorer search surface from committed static artifacts generated from the local SQLite snapshot, using tiered detail shards to bound repository size and public payload exposure.

#### Scenario: Maintainer refreshes the committed search index

- **WHEN** a maintainer runs `just web-search-index-check` with `kaggle/openoppsdb.sqlite` available
- **THEN** the recipe regenerates `web/public/data/openopps-search/`
- **AND** the recipe fails if regenerated artifacts differ from the committed tree

#### Scenario: Public detail shards are written

- **WHEN** the docs search index is generated
- **THEN** open jobs receive metadata-only T1 detail shards
- **AND** indexable jobs may receive bounded plain-text T2 body shards
- **AND** raw payload snapshots are not committed to the public search index

### Requirement: Docs search generated text is safe for browser indexing

OpenOpps SHALL convert provider description HTML into bounded plain text before publishing committed docs search detail artifacts.

#### Scenario: Search index schema is validated in CI

- **WHEN** GitHub Actions runs the docs validation job
- **THEN** CI validates the committed search index schema without regenerating the local SQLite-backed snapshot
- **AND** maintainer-only regeneration remains covered by the local docs search index check

### Requirement: Docs search artifacts expose generated data contracts

OpenOpps SHALL generate docs search artifacts with explicit schema versioning, count provenance, facets, suggestions, dashboard aggregates, and job detail shards.

#### Scenario: Search manifest is generated

- **WHEN** `scripts/generate_docs_search_index.py` builds the docs search index from a SQLite snapshot
- **THEN** the manifest version field identifies the runtime schema consumed by the docs app
- **AND** package-catalog counts are distinguishable from SQLite snapshot counts
- **AND** generated facets and suggestions include sources, providers, locations, departments, teams, companies, skills, workplace types, employment types, statuses, and salary currencies
- **AND** dashboard aggregates are generated before browser runtime

### Requirement: Docs routes are hard-moved

OpenOpps SHALL make the jobs workbench and analytics explorer top-level docs-app routes.

#### Scenario: User opens the docs app root

- **WHEN** a user visits `/`
- **THEN** the jobs workbench is the primary screen

#### Scenario: User opens the analytics explorer

- **WHEN** a user visits `/explorer`
- **THEN** OpenOpps renders a dashboard-first analytics explorer
- **AND** `/jobs`, `/jobs/[id]`, and `/docs/explorer` are not preserved as compatibility routes

### Requirement: Docs IA remains synchronized

OpenOpps SHALL keep docs navigation, README references, LLM routes, generated data, and validation commands aligned with public route and export changes.

#### Scenario: Public routes or export formats change

- **WHEN** OpenOpps changes a public docs route, export format, generated docs data field, or validation command
- **THEN** the docs content graph, README guidance, LLM-readable routes, and local validation commands are updated in the same change

### Requirement: OpenOppsDB deployment remains local and verifiable

OpenOpps SHALL keep live Kaggle deployment credentialed and local/manual while providing deterministic non-live validation and thin documented Kaggle CLI wrappers.

#### Scenario: Contributor validates the bundle without live credentials

- **WHEN** a contributor runs the local Kaggle bundle validation recipe
- **THEN** OpenOpps regenerates deterministic metadata and, when a local SQLite database is supplied, validates the generated SQLite/CSV/Parquet artifact surface without requiring Kaggle credentials

#### Scenario: Maintainer deploys the live Kaggle dataset

- **WHEN** a maintainer runs the documented live create/version and manager notebook push recipes with Kaggle CLI credentials
- **THEN** the commands use local Kaggle CLI credentials from `kaggle auth login` or an already configured Kaggle API credential environment without printing secrets
- **AND** dataset create/version recipes stage a temporary upload directory that excludes private evidence and manager notebook files before calling the Kaggle dataset write command
- **AND** the manager push is preceded by running the private runtime generator create/version recipe so the notebook source gate downloads the current generator script
- **AND** CI does not publish the dataset, push the manager notebook, or require Kaggle secrets

#### Scenario: Maintainer verifies the live Kaggle surfaces

- **WHEN** a maintainer runs live post-deploy verification
- **THEN** the workflow checks dataset status/version, dataset files, downloaded metadata, manager notebook availability, and manager notebook files for `wyattowalsh/openoppsdb` and `wyattowalsh/openoppsdb-manager`
- **AND** it verifies direct SQLite readback plus CSV/Parquet table metadata instead of treating missing Kaggle `sqliteInfo.tables` as an OpenOpps data-shape failure
