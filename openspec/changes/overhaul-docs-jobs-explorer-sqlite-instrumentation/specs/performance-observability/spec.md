## ADDED Requirements

### Requirement: Docs telemetry is first-party and free-operable

OpenOpps SHALL instrument the docs app through a first-party telemetry layer that defaults to no-op and can write to a local append-only event lake without paid services.

#### Scenario: Telemetry is not configured

- **WHEN** the docs app runs without telemetry environment configuration
- **THEN** telemetry calls are no-ops and do not block page navigation

#### Scenario: Local event-lake telemetry is enabled

- **WHEN** `OPENOPPS_TELEMETRY_SINK=local-event-lake` and `OPENOPPS_TELEMETRY_DIR` are configured
- **THEN** telemetry events are sanitized and appended as NDJSON under date-partitioned files
- **AND** secret-like values are redacted or dropped before persistence

### Requirement: Interactive docs work remains responsive

OpenOpps SHALL keep large static search-index interactions responsive with bounded fetch concurrency, deferred UI state, and worker-capable filtering where appropriate.

#### Scenario: Full jobs index is loaded

- **WHEN** filters require loading the full static jobs index
- **THEN** chunk fetches remain bounded
- **AND** expensive filtering/sorting does not block input responsiveness on large row sets
