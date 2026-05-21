## ADDED Requirements

### Requirement: SQLite cache stores observable HTTP results

OpenOpps SHALL provide a SQLite-backed cache for source pages, route probes, provider job requests, and metadata enrichment where caching improves speed or reduces duplicate upstream traffic.

#### Scenario: Response is cached

- **WHEN** a cacheable request succeeds
- **THEN** OpenOpps stores a deterministic cache record with request identity, response status, selected headers, payload, content hash, timestamps, expiration policy, and stale-on-error eligibility

### Requirement: Cache keys are deterministic and isolated

Cache keys SHALL include enough request identity to avoid mixing source, provider, route, query, pagination, body, namespace, and schema-version results.

#### Scenario: Similar requests differ by provider route

- **WHEN** two requests share a URL but differ by provider/source/route identity or relevant request parameters
- **THEN** their cache keys are distinct

### Requirement: Explicit refresh bypasses cache reads

OpenOpps SHALL provide explicit refresh semantics that bypass cache reads while allowing successful fresh responses to update cache state.

#### Scenario: User requests refresh

- **WHEN** a user passes the approved refresh option for a cacheable operation
- **THEN** OpenOpps performs a fresh upstream request instead of returning a cache hit

### Requirement: Conditional requests reuse upstream validators

OpenOpps SHALL use ETag and Last-Modified metadata for conditional requests when upstream responses provide those validators and the request path enables conditional cache validation.

#### Scenario: Upstream returns not modified

- **WHEN** a conditional request receives a not-modified response
- **THEN** OpenOpps reuses the cached payload and updates observable freshness metadata

### Requirement: Stale-on-error is explicit and visible

OpenOpps SHALL only use stale cached data on configured safe read paths and SHALL expose stale use through metrics, status, doctor, or structured output.

#### Scenario: Upstream transiently fails

- **WHEN** stale-on-error is enabled and a retryable upstream failure occurs
- **THEN** OpenOpps may return eligible stale data
- **AND** reports that stale data was used

### Requirement: Cache inspection and invalidation are available

OpenOpps SHALL expose cache status and cache inspection or purge controls through stable or advanced CLI surfaces.

#### Scenario: User inspects cache

- **WHEN** the user runs cache status or status/doctor
- **THEN** OpenOpps reports cache size, freshness, hit/miss/stale metrics where available, and invalidation guidance
