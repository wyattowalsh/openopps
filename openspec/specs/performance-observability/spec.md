# performance-observability Specification

## Purpose
Define bounded sync execution, retry behavior, operator-visible metrics, and storage-read efficiency requirements for the local-first OpenOpps CLI.
## Requirements
### Requirement: Sync uses bounded streaming pipelines

Source and job sync operations SHALL use bounded async I/O, streaming validation, and batched persistence instead of unbounded fan-out or all-record memory accumulation.

#### Scenario: User syncs all jobs

- **WHEN** `openopps jobs sync` runs across many boards
- **THEN** provider fetches are bounded by configured concurrency and storage backpressure

### Requirement: Sync emits metrics

Sync operations SHALL optionally emit machine-readable metrics containing counts, timing, retry, provider error, and throughput data.

#### Scenario: User requests metrics JSON

- **WHEN** a sync command is run with `--metrics-json`
- **THEN** the command outputs valid JSON metrics for the completed run

### Requirement: Configuration exposes performance knobs

OpenOpps SHALL expose settings for HTTP limits, source concurrency, board concurrency, provider concurrency, Workday concurrency, database batch size, timeouts, and retry attempts.

#### Scenario: User configures provider concurrency

- **WHEN** `OPENOPPS_PROVIDER_CONCURRENCY` is set
- **THEN** job sync uses that value as its provider fan-out limit

### Requirement: HTTP retries include transient provider responses

OpenOpps SHALL retry configured JSON requests for transport failures and selected transient HTTP status responses.

#### Scenario: Provider returns a transient status

- **WHEN** a provider returns `429`, `500`, `502`, `503`, or `504` before a successful JSON response
- **THEN** OpenOpps retries up to the configured retry attempts
- **AND** non-transient `4xx` responses fail without retry

### Requirement: Storage reads avoid unnecessary materialization

OpenOpps SHALL push scalar list/export filters and safe limits into SQLite before converting rows into normalized records.

#### Scenario: User lists filtered jobs with a limit

- **WHEN** the requested job filters are SQL-pushable and a limit is supplied
- **THEN** SQLite applies the filters and limit before OpenOpps materializes normalized job records
- **AND** filters that depend on JSON/list fields or date-prefix parsing may still run after SQL narrowing to preserve behavior

### Requirement: Docs telemetry is first-party and free-operable

OpenOpps SHALL instrument the docs app through a first-party telemetry layer that defaults to no-op and can write to a local append-only event lake without paid services.

#### Scenario: Telemetry is not configured

- **WHEN** the docs app runs without telemetry environment configuration
- **THEN** telemetry calls are no-ops and do not block page navigation

### Requirement: Interactive docs work remains responsive

OpenOpps SHALL keep large static search-index interactions responsive with bounded fetch concurrency, deferred UI state, and worker-capable filtering where appropriate.

#### Scenario: Full jobs index is loaded

- **WHEN** filters require loading the full static jobs index
- **THEN** chunk fetches remain bounded
- **AND** expensive filtering/sorting does not block input responsiveness on large row sets
