## ADDED Requirements

### Requirement: Provider surplus fields are promoted without public raw payload exposure

OpenOpps SHALL promote high-value provider list and detail fields into normalized job fields or bounded version metadata while preserving full raw provider evidence in local SQLite and Kaggle export surfaces.

#### Scenario: Greenhouse surplus fields are normalized

- **WHEN** Greenhouse listings include metadata, requisition identifiers, language, department hierarchy, office hierarchy, or prospect-posting indicators
- **THEN** OpenOpps preserves those values in normalized job fields or `version.extra_payload`
- **AND** docs search artifacts do not need to expose raw application payloads to provide those facets.

#### Scenario: Workable listing and detail payloads are distinct

- **WHEN** Workable jobs are fetched from listing and detail endpoints
- **THEN** OpenOpps keeps listing and detail raw payload evidence distinct
- **AND** normalized job output uses the shared Job contract.

### Requirement: Derived job facets are generated from normalized fields

OpenOpps SHALL derive public docs job facets from normalized fields and bounded metadata rather than from committed raw provider payload snapshots.

#### Scenario: Seniority is derived for docs search

- **WHEN** a job lacks an explicit provider seniority value
- **THEN** OpenOpps derives seniority from title and experience fields
- **AND** the generated docs search manifest can expose a seniority facet without constructing invalid job records.

#### Scenario: Days-open values are generated for job rows

- **WHEN** the docs search index is generated from a SQLite snapshot
- **THEN** each eligible job row includes a days-open value based on current job status and persisted observation timestamps
- **AND** historical non-current versions do not override the current-version freshness timestamp.
