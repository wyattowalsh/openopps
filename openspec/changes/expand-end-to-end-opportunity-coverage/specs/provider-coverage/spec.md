# provider-coverage Specification

## ADDED Requirements

### Requirement: Successor overlay conserves one outcome per employer

OpenOpps SHALL keep packaged job-seeker overlay as a coverage family with tiers `core`, `expand`, and `growth` (the successor overlay core/B-tier names). Offline overlay outcomes SHALL be exactly one of `fetchable_packaged`, `no_public_ats`, `duplicate`, or `policy_blocked` per overlay id, and those four outcomes SHALL be conserved per id. Overlay classification SHALL remain offline and SHALL NOT fetch locators. Indeed and Glassdoor hosts SHALL be eligible for `policy_blocked` like LinkedIn and Wellfound.

#### Scenario: Overlay outcomes remain conserved per id

- **WHEN** overlay worklist outcomes are computed for core, expand, and growth
- **THEN** every overlay id has exactly one closed outcome
- **AND** the counts of `fetchable_packaged`, `no_public_ats`, `duplicate`, and `policy_blocked` sum to the number of overlay ids
- **AND** growth-tier counts remain present alongside core and expand

#### Scenario: Overlay reporting stays offline

- **WHEN** a user or admin requests overlay outcomes JSON
- **THEN** OpenOpps classifies from packaged JSON or the documented worklist
- **AND** it performs no HTTP

### Requirement: Successor packaged overlay gain excludes url-pull and scout

OpenOpps SHALL NOT count a URL pull, ephemeral jobs result, or quarantined scout candidate as packaged overlay coverage gain. Packaged gain SHALL require a maintainer-owned overlay JSON locator that is already in the packaged family. Packaged overlay totals SHALL NOT increase because a supported URL returned jobs outside the overlay JSON.

#### Scenario: An ephemeral URL pull succeeds

- **WHEN** `jobs pull` returns jobs for a supported URL that is not in packaged overlay JSON
- **THEN** packaged overlay totals do not increase
- **AND** `job_seeker_overlay.json` is not mutated

#### Scenario: A scout candidate is quarantined

- **WHEN** discovery scout records a candidate board or source
- **THEN** packaged overlay and catalog coverage reports do not treat that candidate as packaged gain
- **AND** quarantine remains isolated from operational SQLite

### Requirement: Overlay and household acquisition follow global knowledge-work order

OpenOpps SHALL order overlay and household-index acquisition by globally sought-after knowledge-work employers and boards (AI, software, data, product, security, finance, biotech, and other professional roles). Demand SHALL be work-order only: not an inclusion filter, not US-HQ-only, and not a Jobs/Explorer ranking view. Posting volume MAY be a tie-breaker. OpenOpps SHALL NOT use US-weighted sequencing in overlay work-order copy or helpers. Household seeds SHALL remain `fortune500`, `sp500`, `nasdaq100`, `sec-company-tickers`, and `yc`. Catalog-row counts SHALL NOT be a success metric.

#### Scenario: Overlay work-order copy drops US-weighted sequencing

- **WHEN** overlay work-order copy or helpers describe acquisition order
- **THEN** they describe global knowledge-work demand
- **AND** they do not rank US-HQ employers above otherwise equivalent global employers

#### Scenario: Household indexes do not invent ATS tokens

- **WHEN** household index route gaps are closed
- **THEN** OpenOpps attaches jobs-capable routes only from matched public ATS URLs
- **AND** it does not invent tokens from ticker or company domain

#### Scenario: Coverage success is not padded source counts

- **WHEN** provider coverage or overlay reports summarize this campaign
- **THEN** they do not treat additional packaged source rows alone as the stop line
- **AND** verified postings and quality floors remain the primary coverage story

### Requirement: Isolated coverage-quality floors are executable

OpenOpps SHALL provide an isolated coverage-quality reporter that measures T2 search indexability, listing/detail conflict rate, null and parse success, and provider/field capability gaps. The reporter SHALL reuse the existing T2 indexability predicate rather than inventing a separate indexability envelope. The campaign SHALL expose a diminishing-yield stop: expansion ends when those floors and prioritized demand tiers are met and another research wave yields too few qualified additions. Catalog-row counts SHALL NOT satisfy the stop.

#### Scenario: Quality floors include T2 indexability

- **WHEN** coverage quality is computed for jobs that feed docs search
- **THEN** the report includes a T2 indexability rate
- **AND** that rate uses the same indexability predicate as docs search generation

#### Scenario: Conflict null and parse are reported per provider and field

- **WHEN** coverage quality is computed
- **THEN** the report includes listing/detail conflict, null, and parse outcomes per provider and field
- **AND** capability gaps are listed for advertised versus implemented list and get hooks

#### Scenario: Diminishing yield ends expansion

- **WHEN** quality floors and prioritized demand tiers are met and a further research wave yields too few qualified additions
- **THEN** the stop rule reports that expansion should end
- **AND** adding more unproven source rows does not reset the stop

### Requirement: Coverage quality reporting stays outside SyncMetrics and PullTerminalObservability

OpenOpps SHALL keep coverage-quality output on its own reporter and SHALL NOT emit it as catalog `SyncMetrics`, SHALL NOT write it as pull `PullTerminalObservability`, and SHALL NOT invent a shared `RunMetrics` envelope. Catalog ingest SHALL keep `--metrics-json` as the `SyncMetrics` stdout channel. URL pull SHALL keep `--metrics-file` / `--raw` / `-v` as the pull observability channel. Discovery JSON and web telemetry SHALL remain separate. Pull modules SHALL NOT import `openopps.discovery`.

#### Scenario: Quality report is not catalog metrics JSON

- **WHEN** a user requests catalog `--metrics-json`
- **THEN** stdout is `SyncMetrics`
- **AND** it does not embed coverage-quality floors as SyncMetrics keys

#### Scenario: Quality report is not pull terminal observability

- **WHEN** a user runs `jobs pull --metrics-file PATH`
- **THEN** the file is `PullTerminalObservability`
- **AND** it does not use the coverage-quality schema as its envelope

#### Scenario: Four observability stacks stay isolated

- **WHEN** catalog sync, URL pull, discovery, and web telemetry run
- **THEN** each keeps its existing envelope
- **AND** coverage quality is a separate reporter rather than a fifth mixed stack
