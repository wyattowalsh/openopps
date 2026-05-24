## ADDED Requirements

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

### Requirement: Advanced commands are explicit

Low-level provider diagnostics, route registry inspection, manual source/board creation, manual route attachment, provider detection, database maintenance, cache maintenance, and adapter explainers SHALL be placed behind clearly marked advanced, admin, debug, or private-facing command surfaces.

#### Scenario: User needs maintenance operations

- **WHEN** the user opens advanced/admin/debug help
- **THEN** low-level maintenance and diagnostic commands remain discoverable
- **AND** default user help remains focused on the stable v0.1 flow

### Requirement: Obsolete internal paths do not require aliases

OpenOpps v0.1 SHALL be treated as the first public baseline, so obsolete internal command paths do not require compatibility aliases.

#### Scenario: Internal command moves to admin

- **WHEN** a pre-v0.1 internal command is moved behind an advanced surface
- **THEN** OpenOpps does not need to preserve the old path unless a later approved compatibility requirement says so

### Requirement: JSON output is clean

Machine-readable CLI modes SHALL write parseable JSON to stdout without decorative output, warnings, progress, cache notices, or plugin load notices mixed into the JSON stream.

#### Scenario: User requests JSON output

- **WHEN** the user runs any v0.1 command with JSON output enabled
- **THEN** stdout parses as JSON
- **AND** non-JSON notices are omitted, encoded into structured fields, or written outside the JSON stream

### Requirement: Dry-run and apply semantics are explicit

Diagnostic commands that can mutate persisted state SHALL remain read-only by default and SHALL require an explicit apply-style option for persistence.

#### Scenario: User probes routes

- **WHEN** the user runs provider route probing without an apply option
- **THEN** matched routes are reported without being persisted

#### Scenario: User persists diagnostic health

- **WHEN** the user runs provider health with an apply option
- **THEN** health metadata may be persisted according to the command contract

### Requirement: Status or doctor reports next action

OpenOpps SHALL provide a status or doctor path that reports database configuration, record counts, cache status, plugin status, provider/source readiness, coverage gaps, setup issues, and the next recommended action.

#### Scenario: User checks an empty database

- **WHEN** the user runs status or doctor on an empty database
- **THEN** OpenOpps reports zero-count state clearly
- **AND** suggests the next command needed to populate or inspect data
