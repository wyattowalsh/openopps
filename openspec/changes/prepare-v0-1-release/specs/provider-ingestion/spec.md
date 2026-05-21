## ADDED Requirements

### Requirement: Baseline job-capable providers remain supported

OpenOpps v0.1 SHALL keep Ashby, Greenhouse, Lever, and public Workday CXS as baseline job-capable providers unless validation proves a provider must be explicitly downgraded.

#### Scenario: Baseline provider route is executable

- **WHEN** a board has a valid baseline provider route
- **THEN** job sync can fetch public postings and normalize them into shared job records

### Requirement: Detect-only providers remain metadata unless proven generic

Teamtailor, Manatal, Gem, and other candidate providers SHALL remain detect-only or unsupported metadata unless the provider coverage audit proves reliable generic public fetching is low risk.

#### Scenario: Detect-only provider is discovered

- **WHEN** a source emits a detect-only provider hint
- **THEN** OpenOpps preserves the hint
- **AND** does not attempt job sync for that provider by default

### Requirement: Provider requests remain bounded and deduped

Source sync, route probing, provider health, metadata enrichment, and job sync SHALL use bounded concurrency and avoid duplicate provider requests where overlapping sources or routes refer to the same upstream provider route.

#### Scenario: Overlapping boards share provider route

- **WHEN** multiple persisted boards resolve to the same provider request key
- **THEN** OpenOpps performs at most one upstream request for that route in the same sync/probe operation
- **AND** reports duplicate skips in metrics where relevant

### Requirement: Provider failures are isolated

Live-network failures SHALL be isolated to the affected source, board, route, provider, cache entry, or plugin-provided adapter and SHALL not crash unrelated work.

#### Scenario: One provider fails

- **WHEN** one provider request fails during a multi-provider sync
- **THEN** OpenOpps summarizes the failure and continues eligible unrelated work when safe
