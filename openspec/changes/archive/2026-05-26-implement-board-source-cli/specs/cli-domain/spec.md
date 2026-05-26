## ADDED Requirements

### Requirement: CLI exposes sources boards jobs providers and db
OpenOpps SHALL expose Typer command groups named `sources`, `boards`, `jobs`, `providers`, and `db`.

#### Scenario: User inspects CLI help
- **WHEN** the user runs `openopps --help`
- **THEN** the command list includes `sources`, `boards`, `jobs`, `providers`, and `db`

### Requirement: Commands default to superset scope
List, export, and sync commands SHALL operate over every applicable configured record when no source, board, or provider filter is provided.

#### Scenario: User lists boards without filters
- **WHEN** the user runs `openopps boards list`
- **THEN** boards from all sources are eligible for output

#### Scenario: User syncs jobs without filters
- **WHEN** the user runs `openopps jobs sync`
- **THEN** every board with a job-capable provider is eligible for synchronization

### Requirement: Commands support narrowing filters
CLI commands SHALL accept filters that narrow source, board, provider, and output behavior without changing the normalized record contract.

#### Scenario: User narrows boards by source
- **WHEN** the user runs `openopps boards list --source a16z`
- **THEN** only boards discovered from the `a16z` source are returned

#### Scenario: User narrows jobs by board
- **WHEN** the user runs `openopps jobs list --board fivetran`
- **THEN** only jobs attached to that board are returned

#### Scenario: User selects any provider
- **WHEN** the user runs `openopps providers probe-routes --provider any`
- **THEN** every stored job-capable provider route is eligible for probing

#### Scenario: User selects all providers
- **WHEN** the user runs `openopps jobs sync --provider all`
- **THEN** the provider filter behaves the same as omitting `--provider`
