# docs-product-boundary Specification

## Purpose
Define the product boundary between the CLI-first OpenOpps core and the static Fumadocs docs workbench used for public job exploration and operational documentation.
## Requirements
### Requirement: OpenOpps core remains CLI-first

OpenOpps SHALL keep the primary product surface as a local-first Typer CLI for source discovery, board and job sync, export, cache, plugins, and maintainer workflows.

#### Scenario: User expects hosted application behavior

- **WHEN** a user reads public product scope documentation
- **THEN** OpenOpps describes CLI commands as the primary power path
- **AND** does not advertise in-browser sync, live database hosting, accounts, or automatic job applications as v0.1 core scope

### Requirement: Docs site is a static data workbench

OpenOpps SHALL publish the Fumadocs site as a read-only static workbench backed by committed generated search artifacts and package-derived docs data rather than a live OpenOpps database on deploy.

#### Scenario: User browses jobs in the docs app

- **WHEN** a user opens the docs app jobs workbench at `/`
- **THEN** job rows and facets load from committed static search artifacts
- **AND** refreshing public data requires maintainer regeneration from local SQLite snapshots, not an in-browser sync command

#### Scenario: User opens the analytics explorer

- **WHEN** a user visits `/explorer`
- **THEN** OpenOpps renders a dashboard-first analytics explorer from the same generated search contracts
- **AND** legacy `/jobs`, `/jobs/[id]`, and `/docs/explorer` routes are not preserved as compatibility routes

### Requirement: Docs exploration does not expand core ingestion scope

Interactive docs features SHALL not require new hosted services, authenticated user flows, or browser-driven provider extraction in the core CLI.

#### Scenario: Maintainer updates public job data

- **WHEN** public search artifacts need to change
- **THEN** maintainers regenerate artifacts through documented CLI and `just` recipes
- **AND** the docs app consumes the regenerated committed files without coupling deploy to a live sync runtime