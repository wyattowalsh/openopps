# storage-export Specification

## ADDED Requirements

### Requirement: Public job JSON identifies profile and schemaVersion

OpenOpps SHALL emit public job JSON objects that identify `profile` and `schemaVersion`. Supported profiles SHALL be `core`, `search`, `full`, and `raw`. Unrestricted model dumps SHALL NOT be the public job export contract. This identification SHALL apply to DB-backed export and no-DB JSONL using the same Pydantic models.

#### Scenario: JSON export identifies the profile envelope

- **WHEN** jobs are exported as JSON or JSONL
- **THEN** each job object includes `profile` and `schemaVersion`
- **AND** `profile` is one of `core`, `search`, `full`, or `raw`

#### Scenario: No-DB JSONL uses the same profile envelope

- **WHEN** jobs are written as no-DB JSONL
- **THEN** each record includes `profile` and `schemaVersion`
- **AND** the field set matches the selected profile rather than an unrestricted dump

### Requirement: Versioned job profiles bound core search full and raw field intent

OpenOpps SHALL bound public job fields by profile. `core` SHALL carry identity, title, company, status, canonical URLs, and dates. `search` SHALL carry governed cross-provider filter and rank fields for web artifacts. `full` SHALL carry the normalized record plus provenance. `raw` SHALL carry listing and detail evidence only where publication is permitted. Default CLI export and pull profile SHALL be `full`. Web search artifacts SHALL use `search`.

#### Scenario: Core profile omits raw payloads

- **WHEN** a user exports jobs with profile `core`
- **THEN** each object includes identity, title, company, status, canonical URLs, and dates
- **AND** it does not include full raw listing/detail payloads

#### Scenario: Search profile matches web artifact intent

- **WHEN** jobs are projected with profile `search`
- **THEN** the fields are the governed filter/rank set consumed by docs search artifacts
- **AND** raw `payloadSnapshots` remain out of the search projection

#### Scenario: Full is the default CLI superset

- **WHEN** a user exports jobs without selecting a profile
- **THEN** OpenOpps uses `full`
- **AND** the object includes normalized fields plus provenance

#### Scenario: Raw includes listing and detail evidence when publication is permitted

- **WHEN** a user exports jobs with profile `raw` and publication of evidence is permitted
- **THEN** listing and detail evidence remain distinct when both exist
- **AND** prohibited publication surfaces do not receive raw payloads

### Requirement: Companion observations compute at projection without a new Alembic revision

OpenOpps SHALL represent rich observation history as companion records computed at projection time. Companion records SHALL include source path, listing versus detail, method or version, conflict state, and evidence linkage. This change SHALL NOT add Alembic revision `0005` or `0006`, SHALL NOT land a new observations table, and SHALL NOT rewrite `storage.py` `_unique_jobs_by_id`. Identity-conflict handling SHALL live in the observations projection until a later storage-owned migration exists.

#### Scenario: Observations are available without a new migration

- **WHEN** jobs are projected to a public profile
- **THEN** companion observations can be computed from existing stored evidence
- **AND** no Alembic `0005` or `0006` revision from this change is required

#### Scenario: Unique-jobs merge remains unchanged

- **WHEN** overlapping jobs share an identity during storage merge
- **THEN** this change does not alter `_unique_jobs_by_id`
- **AND** listing/detail conflicts are recorded on companion observations instead

### Requirement: Observed derived and editorial values remain distinguishable

OpenOpps SHALL distinguish `provider_observed`, `openopps_derived`, and `editorial` origins. Deterministic provider-observed values SHALL NOT require confidence scores. Public projections SHALL carry compact origin tags. Derived skills and seniority SHALL NOT be tagged as provider-observed. Provider-native fields SHALL remain in a namespaced extension until the field-promotion gate passes.

#### Scenario: Origin tags are a closed enum

- **WHEN** a public projection includes origin tags
- **THEN** each tagged value uses `provider_observed`, `openopps_derived`, or `editorial`
- **AND** a provider-observed value has no required confidence score

#### Scenario: Derived enrichment does not look observed

- **WHEN** OpenOpps derives skills or seniority from title or experience
- **THEN** those values are `openopps_derived`
- **AND** they are not presented as `provider_observed`

### Requirement: Field promotion is a distinct gate from ATS family admission

OpenOpps SHALL require a field-promotion gate before a normalized field enters a public `core`, `search`, or `full` projection. That gate SHALL be independent of the ATS family admission gate. Promotion SHALL require documented semantics, distinguishable observed versus inferred origin, identifiable source evidence, a deterministic parser path, explicit listing/detail conflicts, measured quality, Python and TypeScript agreement where both consume the field, tested export/hash/history implications, and demonstrated downstream utility. Search profile fields SHALL NOT grow without that documented gate.

#### Scenario: A namespaced provider field stays unpublished

- **WHEN** a provider returns a native field that has not passed promotion
- **THEN** the field remains in a namespaced extension or raw evidence
- **AND** it does not appear as a governed `search` field

#### Scenario: Search fields need a documented gate

- **WHEN** a contributor proposes adding a field to the `search` profile
- **THEN** promotion tests require the documented rubric
- **AND** T2 indexability vectors are extended only if search fields actually change
