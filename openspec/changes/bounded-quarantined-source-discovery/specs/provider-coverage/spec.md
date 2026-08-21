## MODIFIED Requirements

### Requirement: Coverage audit evaluates high-impact provider candidates

OpenOpps SHALL audit quarantined public source, board, and ATS-provider candidates that may materially improve board or job coverage without bespoke per-company logic.

#### Scenario: Candidate provider is evaluated

- **WHEN** a candidate such as SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, Rippling, WP Job Manager, iCIMS, Jobvite, or JazzHR is evaluated
- **THEN** OpenOpps records whether generic public route discovery and job fetching are viable
- **AND** records a before-and-after coverage delta or do-not-adopt rationale

#### Scenario: Candidate source or board is evaluated

- **WHEN** a verified quarantine bundle contains a candidate source catalog or individual public board
- **THEN** OpenOpps evaluates it against the approved catalog identity identified by the bundle without opening operational SQLite
- **AND** reports unique net-new boards, provider hints, executable routes, and available job-count evidence
- **AND** does not count duplicate or unresolved identities as coverage gain

## ADDED Requirements

### Requirement: Candidate liveness and support use objective evidence

OpenOpps SHALL classify candidate liveness and support from dated, reproducible, provider-aware evidence rather than editorial importance, domain inference, or an HTTP success code alone.

#### Scenario: A source candidate is live

- **WHEN** a bounded public no-auth request returns the expected source-specific payload or page structure
- **THEN** the evidence records the canonical route, observation time, response classification, content hash, and validated structural markers
- **AND** a generic error page, challenge page, redirect loop, or unrelated HTTP 200 is not live evidence

#### Scenario: A board candidate is live and supported

- **WHEN** a public board route responds with provider-specific executable metadata and an adopted job provider can validate that route
- **THEN** the candidate may satisfy live and supported evidence
- **AND** the evaluation records the provider, route identity, support level, and bounded observation
- **AND** no bespoke per-company fetch logic is introduced

#### Scenario: A candidate requires unsupported access

- **WHEN** evaluation requires authentication, browser automation, anti-bot bypass, brittle scraping, or a provider without generic public fetching
- **THEN** the candidate remains rejected or unsupported
- **AND** the audit records the exact reason

### Requirement: Coverage deltas bind to an approved catalog baseline

OpenOpps SHALL calculate scout-time candidate coverage deltas against one identified approved catalog. Persisted-yield analysis is outside this change and SHALL NOT give the scout database access.

#### Scenario: Candidate coverage is reported

- **WHEN** an evaluation reports projected coverage gain
- **THEN** it includes the quarantine bundle digest, approved catalog fingerprint, observation time, denominator, numerator, and deduplicated net-new counts
- **AND** it distinguishes observed job-count hints from jobs proven fetchable by an adopted provider

### Requirement: Candidate decisions remain auditable

OpenOpps SHALL retain evidence-backed rejection, supersession, and do-not-adopt rationale in quarantine output without adding tombstones to the active packaged catalog.

#### Scenario: A candidate is rejected or superseded

- **WHEN** liveness, support, policy, identity, duplication, or expected yield prevents promotion
- **THEN** the manifest records the terminal candidate state and structured rationale
- **AND** the candidate does not appear as a disabled or fallback packaged source
