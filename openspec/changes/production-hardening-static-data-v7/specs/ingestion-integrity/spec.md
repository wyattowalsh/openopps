## ADDED Requirements

### Requirement: Reconciliation requires a complete authoritative snapshot

OpenOpps SHALL close missing jobs only after a validated complete authoritative route snapshot.

#### Scenario: Pagination is truncated or inconsistent

- **WHEN** continuation repeats, a later page fails, an advertised total is not observed, or an empty page still advertises continuation
- **THEN** the run fails as non-authoritative
- **AND** no unseen job is closed

### Requirement: Freshness represents normal completion

OpenOpps SHALL advance source freshness only after the source iterator completes normally.

#### Scenario: Source yields then raises

- **WHEN** a source yields one or more pages and then fails
- **THEN** prior freshness remains authoritative
- **AND** the next eligible sync retries it

### Requirement: Every sync attempt is inspectable

OpenOpps SHALL create a pending run before network access and finish every attempt as succeeded or failed with bounded error and committed-batch metadata.

#### Scenario: Fetch fails before the first job

- **WHEN** provider access or schema validation fails
- **THEN** a failed run is queryable
- **AND** job and closure state remain unchanged

### Requirement: Route absence is distinct from request failure

OpenOpps SHALL NOT declassify job support solely from authentication, authorization, schema, throttling, or unclassified bad-request responses.

#### Scenario: A route returns 400, 401, 403, or 429

- **WHEN** no provider-specific terminal-absence evidence exists
- **THEN** the result is non-authoritative failure
- **AND** existing jobs remain open
