## ADDED Requirements

### Requirement: WorkAtAStartup remains out of scope for v0.1

OpenOpps SHALL NOT package WorkAtAStartup as a core source adapter while the YC source provider covers startup-board discovery for v0.1.

#### Scenario: Packaged source catalog is loaded

- **WHEN** OpenOpps loads the packaged public source catalog
- **THEN** WorkAtAStartup is excluded
- **AND** YC remains the documented preferred startup-board source for that discovery surface

### Requirement: Wellfound and Angel outcomes are explicit

OpenOpps SHALL document whether Wellfound/Angel startup discovery is supported through static no-auth assets or explicitly unsupported with release rationale.

#### Scenario: Wellfound cannot be fetched without session or browser automation

- **WHEN** Wellfound/Angel discovery cannot be served from static no-auth assets or approved public search-index endpoints
- **THEN** OpenOpps excludes it from the packaged source catalog
- **AND** records the unsupported outcome in release rationale and provider coverage reporting

### Requirement: Editorial source labels are audited before provider identity

OpenOpps SHALL audit `Editorial` and `Editiorial` source labels before registering a dedicated provider adapter identity.

#### Scenario: Editorial label appears without a proven public route

- **WHEN** source data reports Editorial or Editiorial as a provider hint without executable public route metadata
- **THEN** OpenOpps preserves the hint as detect-only metadata
- **AND** does not add a job-capable provider identity until route probe evidence proves a generic public fetch path