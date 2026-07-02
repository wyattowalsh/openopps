## ADDED Requirements

### Requirement: Docs search artifacts expose generated data contracts

OpenOpps SHALL generate docs search artifacts with explicit schema versioning, count provenance, facets, suggestions, dashboard aggregates, and job detail shards.

#### Scenario: Search manifest is generated

- **WHEN** `scripts/generate_docs_search_index.py` builds the docs search index from a SQLite snapshot
- **THEN** the manifest version identifies the runtime schema
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
