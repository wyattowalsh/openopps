## ADDED Requirements

### Requirement: Scout execution has explicit finite budgets

OpenOpps SHALL expose bounded discovery configuration for whole-run duration, channel queries and requests, origins, redirect depth, per-host concurrency, response bytes, candidate counts, retries, parser depth, and evidence retention.

#### Scenario: A maintainer configures discovery limits

- **WHEN** supported `OPENOPPS_DISCOVERY_*` settings are supplied
- **THEN** the scout validates positive finite values before network work
- **AND** no channel can exceed the stricter of its channel, host, or whole-run limits
- **AND** remote input cannot raise a trusted limit

#### Scenario: A response exceeds its byte budget

- **WHEN** response headers or streamed bytes exceed the configured limit
- **THEN** OpenOpps stops reading that response
- **AND** records a bounded oversized-response failure without retaining the body

### Requirement: Scout requests are host-aware and retry-bounded

OpenOpps SHALL use bounded asynchronous I/O, provider-aware request identity, conditional fetching where supported, connect-time public-destination enforcement, and finite retries for transient failures.

#### Scenario: An upstream returns rate-limit guidance

- **WHEN** an upstream responds with `429`, `Retry-After`, or a documented reset time
- **THEN** the scout respects the bounded upstream delay
- **AND** records rate-limited time and retry counts
- **AND** stops rather than sleeping beyond the remaining channel or run deadline

#### Scenario: Cached evidence remains fresh enough to reuse

- **WHEN** a prior verified quarantine observation has a valid ETag, Last-Modified value, or configured freshness window
- **THEN** the scout may issue a conditional request or reuse the exact verified bounded observation
- **AND** metrics distinguish fetched, not-modified, and reused evidence
- **AND** the runtime HTTP cache and stale-on-error behavior remain unavailable to the scout

### Requirement: Scout metrics expose completeness and resource use

OpenOpps SHALL emit machine-readable metrics for each channel and the whole run.

#### Scenario: A channel closes its operation ledger

- **WHEN** a channel succeeds, partially completes, is cancelled, or aborts at run level
- **THEN** planned operations equal succeeded plus blocked plus rate-limited plus timed-out plus failed plus cancelled plus unstarted operations
- **AND** started interrupted operations are cancelled while planned operations never launched because of cancellation, fail-fast, deadline, or budget are unstarted
- **AND** retries, redirects, and pagination consume the same immutable request ledger and admitted bytes conserve per-resource and aggregate budgets
- **AND** exactly one terminal channel state is recorded, while `aborted` remains a run-level state and does not replace operation terminals

#### Scenario: A scout reaches a terminal state

- **WHEN** discovery succeeds, partially completes, or fails
- **THEN** metrics include planned and completed queries, requests, bytes, candidates before and after deduplication, collisions, retries, rate limits, policy blocks, errors, elapsed time, and terminal state
- **AND** channel completeness and whole-run completeness are separate fields
- **AND** labels use bounded reason codes and digest identities rather than raw URLs, queries, secrets, or arbitrary upstream strings

#### Scenario: One channel fails while others complete

- **WHEN** an isolated channel reaches a terminal failure
- **THEN** bounded unrelated channels may finish
- **AND** the overall result is explicitly partial
- **AND** no metric or candidate state represents the run as exhaustive

### Requirement: Performance thresholds follow reproducible evidence

OpenOpps SHALL establish discovery performance evidence on a deterministic corpus before adopting numeric regression thresholds.

#### Scenario: The initial benchmark is recorded

- **WHEN** maintainers benchmark normalization, validation, deduplication, collision audit, policy evaluation, and promotion rendering
- **THEN** the corpus spans the frozen runtime source catalog and all built-in adapter identities
- **AND** results record fixture and toolchain digests, environment metadata, median, p95, peak memory, artifact bytes, request counts, and relevant statement counts
- **AND** the initial measurements are evidence rather than an unreviewed CI SLO

#### Scenario: A numeric CI gate is proposed

- **WHEN** repeated controlled measurements establish representative variance and headroom
- **THEN** an ADR documents the methodology and selected threshold before the gate becomes normative
- **AND** otherwise CI enforces structural boundedness and determinism only
