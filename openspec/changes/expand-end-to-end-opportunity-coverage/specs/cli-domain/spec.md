# cli-domain Specification

## ADDED Requirements

### Requirement: Jobs export and pull accept a thin profile flag after profile modules exist

After versioned profile modules exist, `jobs export` and `jobs pull` SHALL accept a thin `--profile` option with values `core`, `search`, `full`, and `raw`. The default SHALL be `full`. Omitting `--profile` SHALL keep superset `full` behavior. Selecting `--profile` SHALL narrow the emitted job field set without changing command meanings for `jobs sync`, `jobs list`, `jobs show`, or `jobs history`. Help SHALL be covered by semantic tests rather than full-output snapshots. `--profile` SHALL NOT be added to `cli.py` before the export and pull-output modules emit `profile` and `schemaVersion`.

#### Scenario: Default export uses full

- **WHEN** the user runs `openopps jobs export` after profile modules exist and omits `--profile`
- **THEN** emitted jobs use profile `full`
- **AND** each JSON object identifies `profile` and `schemaVersion`

#### Scenario: User selects search profile

- **WHEN** the user runs `openopps jobs export --profile search`
- **THEN** emitted jobs use profile `search`
- **AND** the field set is the governed search projection rather than `full`

#### Scenario: Jobs pull uses the same profiles

- **WHEN** the user runs `openopps jobs pull <URL> --profile core` after profile modules exist
- **THEN** stdout jobs use profile `core`
- **AND** stdout remains the selected jobs representation without mixing quality-report JSON

#### Scenario: Help documents profile after the flag exists

- **WHEN** the user runs `openopps jobs export --help` or `openopps jobs pull --help` after `--profile` exists
- **THEN** help names `core`, `search`, `full`, and `raw`
- **AND** it states that `full` is the default

### Requirement: Optional coverage-quality diagnostic is not catalog metrics JSON

OpenOpps MAY expose a coverage-quality diagnostic under `admin` or `providers` after quality-reporter and help tests exist. That diagnostic SHALL NOT be `--metrics-json`, SHALL NOT be `--metrics-file`, and SHALL NOT replace catalog `SyncMetrics` or pull `PullTerminalObservability`. `--metrics-json` SHALL remain catalog sync stdout only. `jobs pull` SHALL keep `--metrics-file` as its observability channel.

#### Scenario: Quality diagnostic is a separate command surface

- **WHEN** an optional quality diagnostic is exposed
- **THEN** it lives under `admin` or `providers`
- **AND** it is not a `jobs pull --metrics-json` flag

#### Scenario: Catalog metrics JSON stays SyncMetrics

- **WHEN** the user runs a catalog sync command with `--metrics-json`
- **THEN** stdout is `SyncMetrics`
- **AND** coverage-quality floors are not required keys of that object

### Requirement: Four observability stacks stay isolated from coverage-quality reporting

OpenOpps SHALL keep catalog ingest, URL pull, quarantined discovery, and web telemetry on four isolated envelopes. Coverage-quality reporting SHALL remain a separate reporter and SHALL NOT invent a shared `RunMetrics` envelope. Pull modules SHALL NOT import `openopps.discovery`. Discovery commands SHALL NOT share a run with `openopps sync`.

#### Scenario: Pull help does not advertise metrics-json

- **WHEN** the user runs `openopps jobs pull --help`
- **THEN** help does not advertise `--metrics-json` as a pull metrics channel
- **AND** `--metrics-file` remains the documented pull observability channel when that option exists

#### Scenario: Discovery stays off the sync path

- **WHEN** the user runs `openopps sync` or `openopps discovery scout`
- **THEN** those commands do not share a process or persist overlay/catalog rows from scout into sync
- **AND** discovery remains on the advanced `discovery` / `admin sources` surface without `--apply`

### Requirement: This change does not add hosted publish commands

OpenOpps SHALL remain CLI-first. This change SHALL NOT add hosted publish, Workers upload, Kaggle mutation, TUI, browser, or in-app sync commands. Public CLI help SHALL continue to emphasize local sources, boards, jobs, providers, cache, plugins, and examples.

#### Scenario: Root help stays CLI-first

- **WHEN** the user runs `openopps --help`
- **THEN** help does not advertise hosted publish, Workers upload, or Kaggle mutation
- **AND** it does not advertise TUI, browser UI, or in-browser sync as v0.1 core scope

#### Scenario: No-database export still works

- **WHEN** the user exports jobs without a database after profile modules exist
- **THEN** JSONL still writes the selected profile
- **AND** the command does not require a hosted service
