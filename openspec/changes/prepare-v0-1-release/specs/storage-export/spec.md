## ADDED Requirements

### Requirement: Raw upstream payloads remain preserved

OpenOpps SHALL preserve raw upstream source, board, provider-route, and job payloads when available for auditability and future reprocessing.

#### Scenario: Source emits raw company payload

- **WHEN** source sync stores a board
- **THEN** the raw upstream board payload remains available on the normalized record

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

### Requirement: Persisted schema changes are managed deliberately

OpenOpps SHALL add compatibility or migration handling only when persisted schema expectations would break known local users or a prior public release.

#### Scenario: v0.1 adds new persisted fields

- **WHEN** the field is new before the first public baseline
- **THEN** OpenOpps may use a clean current-state schema without compatibility aliases for obsolete internal paths
