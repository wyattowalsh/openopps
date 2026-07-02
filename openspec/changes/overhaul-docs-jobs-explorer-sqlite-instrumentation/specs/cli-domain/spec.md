## ADDED Requirements

### Requirement: CLI help describes SQLite export support

OpenOpps SHALL describe SQLite alongside JSONL, CSV, and Parquet in public export command help.

#### Scenario: User reads export help

- **WHEN** the user runs help for `boards export` or `jobs export`
- **THEN** SQLite is listed as a supported export format
- **AND** the command remains filter-compatible with existing list/export behavior
