## ADDED Requirements

### Requirement: Provider coverage reports board-level non-supported share

OpenOpps SHALL report the measured percentage of persisted boards with any non-supported provider hint using distinct persisted boards in the current report scope as the denominator.

#### Scenario: Coverage report includes non-supported percentage

- **WHEN** the user runs provider coverage reporting
- **THEN** the report includes total boards, boards with non-supported provider hints, and the corresponding percentage

### Requirement: Coverage distinguishes provider support categories

OpenOpps SHALL separately report boards with baseline job-capable providers, adopted v0.1 providers, detect-only providers, unsupported or unknown providers, only non-supported provider hints, and missing executable route metadata.

#### Scenario: Board has both supported and detect-only hints

- **WHEN** a board has a job-capable route and a detect-only route
- **THEN** it counts toward boards with non-supported provider hints
- **AND** it does not count as only non-supported

#### Scenario: Board has only detect-only hints

- **WHEN** a board has provider hints but none are job-capable
- **THEN** it counts toward boards with only non-supported provider hints

### Requirement: Coverage audit evaluates high-impact provider candidates

OpenOpps SHALL audit candidate public ATS providers that may materially improve board coverage without bespoke per-company logic.

#### Scenario: Candidate provider is evaluated

- **WHEN** a candidate such as SmartRecruiters, Workable, Recruitee, Teamtailor, BambooHR, Rippling, WP Job Manager, iCIMS, Jobvite, or JazzHR is evaluated
- **THEN** OpenOpps records whether generic public route discovery and job fetching are viable
- **AND** records a before-and-after coverage delta or do-not-adopt rationale

#### Scenario: Candidate has no-auth public board support

- **WHEN** Workable, Teamtailor, BambooHR, Rippling, or WP Job Manager is promoted to job-fetching support
- **THEN** OpenOpps records that adoption is based on public no-auth board routes
- **AND** does not count authenticated APIs, browser automation, or third-party scraper APIs as v0.1 core support evidence

### Requirement: Candidate providers are adopted only with generic public fetching

OpenOpps SHALL only promote candidate providers to v0.1 job-fetching support when generic route detection and public job fetching are reliable enough for the release.

#### Scenario: Candidate requires brittle scraping

- **WHEN** a candidate provider requires authenticated APIs, browser automation, brittle scraping, or bespoke per-company logic
- **THEN** it remains detect-only or unsupported metadata
- **AND** the provider audit records the reason

#### Scenario: Wellfound source remains anti-bot blocked

- **WHEN** Wellfound/Angel startup discovery is blocked by anti-bot controls and no static no-auth extraction path is proven
- **THEN** OpenOpps reports Wellfound/Angel as unsupported or disabled source metadata
- **AND** does not present it as a failed job-capable provider

### Requirement: Published coverage includes snapshot context

README or docs coverage results SHALL include snapshot date, source set, denominator, numerator, percentage, examples, and candidate provider deltas.

#### Scenario: User reads provider coverage docs

- **WHEN** provider coverage percentages are documented
- **THEN** the user can see what source snapshot produced the measurement and when it was measured
