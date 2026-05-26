# storage-export Specification

## Purpose
Define OpenOpps persistence and export behavior for SQLite-backed records, no-database JSONL mode, and analytical export formats.
## Requirements
### Requirement: SQLite storage persists normalized records

OpenOpps SHALL persist sources, boards, board-provider relationships, and jobs in SQLite through SQLModel when DB mode is enabled.

#### Scenario: User initializes the database

- **WHEN** the user runs `openopps db init`
- **THEN** the schema exists and SQLite is configured for WAL mode

### Requirement: No-DB mode writes normalized JSONL

OpenOpps SHALL support writing normalized records to JSONL without requiring a database connection.

#### Scenario: User syncs a source without DB

- **WHEN** the user runs a sync command with no-DB output
- **THEN** normalized JSONL records are written using the same Pydantic models as DB mode

### Requirement: Exports support common analytical formats

OpenOpps SHALL export boards and jobs as JSONL, CSV, or Parquet.

#### Scenario: User exports jobs as parquet

- **WHEN** the user runs `openopps jobs export --format parquet`
- **THEN** a Parquet file containing normalized jobs is written

#### Scenario: User exports jobs as CSV

- **WHEN** provider-controlled string fields begin with spreadsheet formula prefixes
- **THEN** CSV output neutralizes those cells
- **AND** JSONL and Parquet preserve normalized values without CSV-specific escaping

#### Scenario: User exports records as JSONL

- **WHEN** records are exported as JSONL
- **THEN** records are written incrementally as line-delimited JSON

#### Scenario: User exports no matching records

- **WHEN** an export filter matches no records
- **THEN** JSONL and CSV exports are deterministic empty files
- **AND** Parquet exports are deterministic readable empty Parquet tables
