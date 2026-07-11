## ADDED Requirements

### Requirement: Raw upstream payloads remain preserved

OpenOpps SHALL preserve raw upstream source, board, provider-route, and job payloads when available for auditability and future reprocessing.

#### Scenario: Source emits raw company payload

- **WHEN** source sync stores a board
- **THEN** the raw upstream board payload remains available on the normalized record

#### Scenario: Job payload changes without normalized content changes

- **WHEN** a successful provider-route job sync observes a raw listing or detail payload with a new canonical payload hash
- **THEN** OpenOpps stores the distinct raw payload snapshot
- **AND** does not create a new normalized job version unless the normalized content hash also changes

### Requirement: Metadata promotion is normalized and useful

OpenOpps SHALL promote reusable metadata into normalized fields when the metadata improves filtering, display, export, status, or diagnostics.

#### Scenario: Board metadata is available

- **WHEN** source, route, or job payloads include board website, domain, description, markets, locations, staff count, job count hints, funding or cohort tags, provider label, route count, route status, or timestamps
- **THEN** OpenOpps promotes supported fields into normalized records where defined
- **AND** preserves raw payloads alongside promoted fields

### Requirement: Exports include enriched normalized fields

OpenOpps SHALL include normalized enriched fields in board and job exports where available while preserving filter parity with list commands.

#### Scenario: User exports filtered jobs

- **WHEN** the user exports jobs with filters
- **THEN** the exported set matches the corresponding list command semantics
- **AND** includes enriched normalized fields such as company, title, locations, departments, workplace type, employment type, remote level, compensation, salary range, skills, and description where available

#### Scenario: User exports jobs without an explicit lifecycle filter

- **WHEN** the user lists or exports jobs without `--status`
- **THEN** OpenOpps returns current active jobs only
- **AND** the user can pass `--status closed` or `--status all` to include closed postings intentionally

### Requirement: Job postings retain stable identity and version history

OpenOpps SHALL model job postings as stable identities with normalized content versions, raw payload snapshots, sync runs, and sync observations.

#### Scenario: Job content changes during a successful route sync

- **WHEN** a successful provider-route sync observes a known job with a new normalized content hash
- **THEN** OpenOpps creates a new `job_versions` row before updating the stable job's current version pointer
- **AND** records a `changed` sync observation linked to the sync run, job, version, content hash, and payload hash

#### Scenario: Job content is unchanged during a successful route sync

- **WHEN** a successful provider-route sync observes a known open job with the same normalized content hash
- **THEN** OpenOpps updates the stable job and current version `last_seen_at` timestamps
- **AND** does not create a duplicate `job_versions` row for the same job/content hash

#### Scenario: Job disappears from a successful provider response

- **WHEN** a successful provider-route sync completes and an open job for that board/provider route was not observed
- **THEN** OpenOpps marks that stable job `closed`
- **AND** records a `closed` sync observation
- **AND** provider errors, skipped routes, missing metadata, or missing adapters do not close jobs

#### Scenario: User inspects job history

- **WHEN** the user runs `jobs history <job-id> --json`
- **THEN** OpenOpps returns ordered normalized content versions for that stable job identity
- **AND** each version includes its version number, hashes, and first/last seen timestamps

### Requirement: Board records expose source overlap

OpenOpps SHALL merge board records that share the same normalized company domain while exposing the complete set of source keys and emitted source-board keys represented by the canonical board.

#### Scenario: Company appears in multiple sources

- **WHEN** two incoming board records share the same normalized company domain
- **THEN** OpenOpps persists one canonical board record for that domain
- **AND** the record includes sorted `source_keys` and `source_board_keys` entries for the merged sources

### Requirement: Persisted schema changes are managed deliberately

OpenOpps SHALL treat the v0.1 schema as the first ground-truth local storage contract and avoid compatibility handling for pre-release local schema shapes.

#### Scenario: v0.1 adds new persisted fields

- **WHEN** the field is new before the first public baseline
- **THEN** OpenOpps may use a clean current-state schema without compatibility aliases for obsolete internal paths
