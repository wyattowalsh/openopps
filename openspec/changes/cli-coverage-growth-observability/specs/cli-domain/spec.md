# cli-domain Specification

## MODIFIED Requirements

### Requirement: Status or doctor reports next action

OpenOpps SHALL provide a status or doctor path that reports database configuration, record counts, cache status, plugin status, provider/source readiness, coverage gaps, setup issues, and the next recommended action. When the catalog has zero sources, nextAction SHALL say the catalog is empty, that URL pull does not populate it, and that `sources sync` or `examples seed` is the catalog fill path. `jobs pull` SHALL be described as ephemeral by default (opt-in `--save`). Empty catalog SHALL NOT imply that a prior or future URL pull filled coverage. Status is a new process and SHALL NOT remember the last pull.

#### Scenario: User checks an empty database

- **WHEN** the user runs status or doctor on an empty database
- **THEN** OpenOpps reports zero-count state clearly
- **AND** suggests the next command needed to populate or inspect data

#### Scenario: Empty catalog does not treat URL pull as catalog fill

- **WHEN** the user runs `openopps status` or `openopps doctor` with `sources==0`
- **THEN** nextAction states that the catalog is empty
- **AND** it does not claim that `jobs pull` or a root HTTPS URL populated or will populate catalog SQLite
- **AND** it recommends `sources sync` or `examples seed` for catalog fill
- **AND** it may mention `jobs pull` only as an ephemeral jobs fetch

## ADDED Requirements

### Requirement: Catalog metrics JSON is a sync-only stdout channel

OpenOpps SHALL keep `--metrics-json` on catalog sync commands and SHALL NOT expose it as a `jobs pull` or root URL-pull option. Automation help MAY point to `--metrics-json` for sync and to `--metrics-file` or `--raw` for pull.

#### Scenario: User inspects jobs pull help

- **WHEN** the user runs `openopps jobs pull --help`
- **THEN** help documents `--metrics-file` when that option exists
- **AND** it does not advertise `--metrics-json` as a pull metrics channel

#### Scenario: User inspects sync help

- **WHEN** the user runs help for `openopps sync` or another catalog sync command
- **THEN** `--metrics-json` remains the documented catalog metrics stdout channel

### Requirement: URL pull writes observability to --metrics-file

`jobs pull` SHALL accept `--metrics-file PATH` and write `PullTerminalObservability` as one camelCase JSON object with `schemaVersion` using atomic replace. Quiet mode SHALL still write the file. Stdout jobs SHALL remain uncontaminated. Pretty TTY output MAY include `coverage=`, `persisted=`, and `board=`. Coverage class on success SHALL NOT be an essential always-on stderr line. Verbosity `-v` MAY emit a coverage line on stderr. Failures and stale-cache warnings remain essential.

#### Scenario: User requests a pull metrics file

- **WHEN** the user runs `openopps jobs pull <URL> --metrics-file PATH`
- **THEN** stdout is the selected jobs representation
- **AND** PATH receives camelCase observability including coverage class
- **AND** `--quiet` does not skip the file write

#### Scenario: Interactive pretty output shows coverage

- **WHEN** a successful pull renders pretty output on a TTY
- **THEN** the panel includes coverage class and `persisted=false` when persistence did not land
- **AND** agents that read only stdout still receive the full jobs result

### Requirement: URL pulls default to ephemeral persistence with opt-in `--save`

After the `unified-cli-job-pulls` storage join (D712), a successful URL pull SHALL leave operational catalog, overlay JSON, source, board, route, job, lifecycle, and `url_pull_runs` tables unchanged unless the user selects `--save`. The CLI persistence default SHALL be False. `--no-save` is the explicit ephemeral alias. HTTP cache writes remain independently governed. `--save` SHALL persist a complete validated result; persist failure SHALL exit 9 (`PERSISTENCE_FAILED`). The user-facing hint SHALL NOT claim that the storage join is not enabled.

#### Scenario: Default pull stays ephemeral

- **WHEN** `openopps jobs pull <URL>` succeeds without `--save`
- **THEN** stdout still emits jobs
- **AND** operational catalog, overlay JSON, and `url_pull_runs` are unchanged
- **AND** HTTP cache writes may still occur

#### Scenario: Save failure exits 9

- **WHEN** the user supplies `--save` and persistence cannot complete
- **THEN** OpenOpps exits with `PERSISTENCE_FAILED` (process status 9)
- **AND** it does not claim a saved success
- **AND** the hint does not say the storage join is not enabled

### Requirement: Pull stderr reports resolution rather than discovery

URL-pull stderr diagnostics SHALL prefix resolver method as `resolution=` and SHALL NOT use `discovery=` for that field. The value remains the operational `DiscoveryMethod` (native versus careers resolution) and SHALL NOT be presented as quarantined scout.

#### Scenario: Verbose pull reports resolver method

- **WHEN** a URL pull emits verbosity diagnostics that include resolver method
- **THEN** stderr contains `resolution=`
- **AND** it does not contain a `discovery=` prefix for that field
