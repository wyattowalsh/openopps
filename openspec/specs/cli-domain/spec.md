# cli-domain Specification

## Purpose
Define the stable OpenOpps CLI domain, including workflow-oriented command grouping, scriptable output contracts, and filtering behavior for sources, boards, jobs, providers, cache, plugins, examples, and admin maintenance operations.
## Requirements
### Requirement: CLI help is user-friendly and test-covered

OpenOpps SHALL keep root and command-group help focused, workflow-oriented, and covered by semantic tests.

#### Scenario: User opens root help

- **WHEN** the user runs `openopps --help`
- **THEN** help presents the everyday workflow before operational and advanced admin surfaces
- **AND** it includes a concise first-run path through status, sync, provider coverage, and job listing
- **AND** it points automation users to JSON or metrics JSON output

#### Scenario: Help text changes

- **WHEN** CLI help copy, group descriptions, or examples change
- **THEN** tests assert the stable user-facing semantics without relying on full terminal snapshots or exact line wrapping

### Requirement: CLI exposes stable v0.1 workflow groups

OpenOpps SHALL expose Typer command groups for the everyday v0.1 workflow: top-level `sources`, `boards`, `jobs`, `providers`, `cache`, `plugins`, and `examples`, plus `status` or `doctor` and stable `sync` orchestration.

#### Scenario: User inspects CLI help

- **WHEN** the user runs `openopps --help`
- **THEN** the command list emphasizes `sources`, `boards`, `jobs`, `providers`, `cache`, `plugins`, and `examples`
- **AND** low-level database maintenance, route probing, and provider diagnostics are grouped under `admin` rather than advertised as top-level `db` or `providers probe-routes` commands

### Requirement: Advanced commands are explicit

Low-level provider diagnostics, route registry inspection, manual source/board creation, manual route attachment, provider detection, database maintenance, cache maintenance, and adapter explainers SHALL be placed behind clearly marked `admin`, `debug`, or private-facing command surfaces.

#### Scenario: User needs maintenance operations

- **WHEN** the user opens `openopps admin --help`
- **THEN** maintenance commands such as `admin db init`, `admin providers probe-routes`, and `admin sources yield` remain discoverable
- **AND** default user help remains focused on the stable v0.1 flow

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

#### Scenario: User selects any provider for route probing

- **WHEN** the user runs `openopps admin providers probe-routes --provider any`
- **THEN** every stored job-capable provider route is eligible for probing

#### Scenario: User selects all providers

- **WHEN** the user runs `openopps jobs sync --provider all`
- **THEN** the provider filter behaves the same as omitting `--provider`

### Requirement: CLI exposes stable v0.1 workflow surface

OpenOpps SHALL expose stable v0.1 commands for full sync orchestration, source discovery, board inspection/export, route readiness, job sync/list/show/export, plugin inspection, cache inspection, generated examples, and local status or doctor output.

#### Scenario: User inspects default help

- **WHEN** the user runs `openopps --help`
- **THEN** the help emphasizes the everyday workflow rather than every low-level maintenance command
- **AND** it does not advertise TUI, Textual, prompt UI, browser UI, or web UI behavior

#### Scenario: User follows stable workflow

- **WHEN** the user uses stable v0.1 commands
- **THEN** the available path supports running the full sync workflow, discovering boards, checking route readiness, syncing jobs, filtering/listing data, exporting data, and checking local status

#### Scenario: User runs the full sync workflow

- **WHEN** the user runs `openopps sync` with optional source, board, or provider filters
- **THEN** OpenOpps runs source discovery, board route resolution, and job sync in order
- **AND** machine-readable metrics remain parseable when JSON metrics are requested

### Requirement: JSON output is clean

Machine-readable CLI modes SHALL write parseable JSON to stdout without decorative output, warnings, progress, cache notices, or plugin load notices mixed into the JSON stream.

#### Scenario: User requests JSON output

- **WHEN** the user runs any v0.1 command with JSON output enabled
- **THEN** stdout parses as JSON
- **AND** non-JSON notices are omitted, encoded into structured fields, or written outside the JSON stream

### Requirement: Dry-run and apply semantics are explicit

Diagnostic commands that can mutate persisted state SHALL remain read-only by default and SHALL require an explicit apply-style option for persistence.

#### Scenario: User probes routes

- **WHEN** the user runs `openopps admin providers probe-routes` without an apply option
- **THEN** matched routes are reported without being persisted

#### Scenario: User persists diagnostic health

- **WHEN** the user runs `openopps providers health` with an apply option
- **THEN** health metadata may be persisted according to the command contract

### Requirement: Status or doctor reports next action

OpenOpps SHALL provide a status or doctor path that reports database configuration, record counts, cache status, plugin status, provider/source readiness, coverage gaps, setup issues, and the next recommended action.

#### Scenario: User checks an empty database

- **WHEN** the user runs status or doctor on an empty database
- **THEN** OpenOpps reports zero-count state clearly
- **AND** suggests the next command needed to populate or inspect data

### Requirement: CLI help describes SQLite export support

OpenOpps SHALL describe SQLite alongside JSONL, CSV, and Parquet in public export command help.

#### Scenario: User reads export help

- **WHEN** the user runs help for `boards export` or `jobs export`
- **THEN** SQLite is listed as a supported export format
- **AND** the command remains filter-compatible with existing list/export behavior