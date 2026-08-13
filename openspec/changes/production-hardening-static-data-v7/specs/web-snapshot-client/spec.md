## ADDED Requirements

### Requirement: Every public-data consumer pins one release

The web app SHALL use one validated release ID for search, details, metadata, sitemaps, build checks, and request/session caches.

#### Scenario: The channel changes during use

- **WHEN** later asset requests execute
- **THEN** they continue using the pinned immutable release
- **AND** mixed-release content is rejected

### Requirement: Search is bounded without full server scans

The web app SHALL use a browser worker engine selected by a reproducible semantic and performance benchmark.

#### Scenario: The preferred engine fails its benchmark

- **WHEN** semantic parity or recorded budgets fail
- **THEN** the ADR-selected fallback is used
- **AND** the server does not scan the full corpus

### Requirement: Local state is transactional and recoverable

The web app SHALL commit IndexedDB changes before visible state advances and preserve recoverable backups before replacement imports.

#### Scenario: Persistence, quota, or import validation fails

- **WHEN** a mutation cannot commit
- **THEN** prior persisted and visible state remains authoritative
- **AND** the user receives an actionable handled error

### Requirement: Offline and telemetry are privacy bounded

Offline cache SHALL be opt-in, release-pinned, integrity-checked, quota-preflighted, and bounded; telemetry SHALL exclude raw queries and arbitrary origins.

#### Scenario: Storage or integrity preflight fails

- **WHEN** twice the estimated bytes are unavailable or verification fails
- **THEN** unrelated data is not evicted
- **AND** offline readiness is not claimed
