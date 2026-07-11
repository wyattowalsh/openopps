# storage-export Specification

## Purpose
Define OpenOpps persistence and export behavior for SQLite-backed records, no-database JSONL mode, analytical export formats, and portable database snapshots.
## Requirements
### Requirement: SQLite storage persists normalized records

OpenOpps SHALL persist sources, boards, board-provider relationships, and jobs in SQLite through SQLModel when DB mode is enabled.

#### Scenario: User initializes the database

- **WHEN** the user runs `openopps admin db init`
- **THEN** the schema exists and SQLite is configured for WAL mode

### Requirement: No-DB mode writes normalized JSONL

OpenOpps SHALL support writing normalized records to JSONL without requiring a database connection.

#### Scenario: User syncs a source without DB

- **WHEN** the user runs a sync command with no-DB output
- **THEN** normalized JSONL records are written using the same Pydantic models as DB mode

### Requirement: Exports support common analytical formats

OpenOpps SHALL export boards and jobs as JSONL, CSV, Parquet, or SQLite.

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

### Requirement: Filtered exports support SQLite

OpenOpps SHALL export filtered board and job records to SQLite files in addition to JSONL, CSV, and Parquet.

#### Scenario: User exports filtered jobs as SQLite

- **WHEN** the user runs `openopps jobs export --format sqlite --output jobs.sqlite`
- **THEN** OpenOpps writes a SQLite database containing a `jobs` table
- **AND** the rows match the same filter semantics as the corresponding jobs list/export operation
- **AND** nested values are encoded as stable JSON strings
- **AND** `_openopps_export_metadata` records entity, row count, filters, generated timestamp, and export format

#### Scenario: User exports filtered boards as SQLite

- **WHEN** the user runs `openopps boards export --format sqlite --output boards.sqlite`
- **THEN** OpenOpps writes a SQLite database containing a `boards` table
- **AND** `_openopps_export_metadata` records the board export metadata

### Requirement: Local database snapshots are exportable

OpenOpps SHALL provide an admin command that exports a portable snapshot of the configured local SQLite database.

#### Scenario: User exports the local database

- **WHEN** the user runs `openopps admin db export --output openoppsdb.sqlite`
- **THEN** OpenOpps uses SQLite backup/checkpoint behavior rather than raw sidecar copying
- **AND** the output passes `PRAGMA integrity_check`
- **AND** non-SQLite configured storage fails with a clear unsupported-backend message

### Requirement: Raw upstream payloads remain preserved

OpenOpps SHALL preserve raw upstream source, board, provider-route, and job payloads when available for auditability and future reprocessing.

#### Scenario: Source emits raw company payload

- **WHEN** source sync stores a board
- **THEN** the raw upstream board payload remains available on the normalized record

### Requirement: Job postings retain stable identity and version history

OpenOpps SHALL model job postings as stable identities with normalized content versions, raw payload snapshots, sync runs, and sync observations.

#### Scenario: User inspects job history

- **WHEN** the user runs `jobs history <job-id> --json`
- **THEN** OpenOpps returns ordered normalized content versions for that stable job identity
- **AND** each version includes its version number, hashes, and first/last seen timestamps