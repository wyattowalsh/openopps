## ADDED Requirements

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
