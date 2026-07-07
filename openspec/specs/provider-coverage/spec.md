# provider-coverage Specification

## Purpose
Define source-coverage expansion and persisted-data reporting requirements for packaged public company, ranking, ecosystem, and source-yield surfaces.
## Requirements
### Requirement: Source coverage includes non-VC source families

OpenOpps SHALL package source adapters for low-friction public company and ecosystem discovery sources without treating them as job-capable providers.

#### Scenario: Public source family is packaged

- **WHEN** the source catalog is loaded
- **THEN** it includes SEC company tickers, public index CSV, ranking CSV, and CNCF landscape source families
- **AND** those source families preserve their source adapter identity separately from job provider adapters

#### Scenario: Scrappy or license-sensitive source is packaged

- **WHEN** an index or ranking source has unreviewed or community-maintained provenance
- **THEN** OpenOpps excludes it from the packaged source catalog until it has a reviewed public fetch path
- **AND** any packaged access-constrained source records provenance and access constraints without source enablement state

### Requirement: Source metadata records coverage taxonomy

OpenOpps SHALL preserve taxonomy metadata for packaged source records using existing raw metadata fields.

#### Scenario: Source taxonomy is exported

- **WHEN** source metadata is listed, synced, or generated for docs
- **THEN** OpenOpps includes provider type, coverage mode, access type, license status, refresh cadence, source category, source attribution, and access-constraint rationale when known

### Requirement: Source-yield reporting is offline and persisted-data-only

OpenOpps SHALL report source-yield metrics from persisted SQLite records without live source fetches, route probes, or job syncs.

#### Scenario: User requests source yield

- **WHEN** the user runs `openopps admin sources yield --json`
- **THEN** the report includes company candidates, canonical boards, provider hints, job-capable routes, route-ready routes, active job routes, duplicate board rate, unique active boards added, yield score, and taxonomy totals
- **AND** the report includes snapshot scope and a persisted-data-only note

#### Scenario: User requests provider coverage JSON

- **WHEN** the user runs `openopps providers coverage --json`
- **THEN** the source summary includes compact source-yield totals
