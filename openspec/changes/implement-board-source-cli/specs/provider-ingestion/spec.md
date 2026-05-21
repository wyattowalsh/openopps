## ADDED Requirements

### Requirement: Provider registry reports support levels

OpenOpps SHALL classify providers with support levels `detect`, `jobs`, or `unsupported`.

#### Scenario: User lists providers

- **WHEN** the user runs `openopps providers list`
- **THEN** each provider row includes its provider id and support level

### Requirement: a16z source sync discovers boards

The a16z source adapter SHALL fetch boards from the Consider-backed public companies endpoint and preserve source metadata and provider hints.

#### Scenario: User syncs a16z source

- **WHEN** the user runs `openopps sources sync a16z`
- **THEN** boards from the a16z source are normalized with raw payloads and board-provider hints
- **AND** generated board keys are source-scoped so overlapping source records do not overwrite each other

### Requirement: Accel source sync discovers boards

The Accel source adapter SHALL fetch boards from the Getro-backed public companies endpoint and preserve source metadata.

#### Scenario: User syncs Accel source

- **WHEN** the user runs `openopps sources sync accel`
- **THEN** boards from the Accel source are normalized with raw payloads and active job count hints

### Requirement: Additional investor source sync discovers boards

OpenOpps SHALL provide default source definitions for General Catalyst, Lightspeed, Sequoia, Bessemer, Greylock, and Kleiner Perkins.

#### Scenario: User syncs a Getro-backed investor source

- **WHEN** the user runs `openopps sources sync generalcatalyst`
- **THEN** boards from that Getro-backed source are normalized with raw payloads and active job count hints

#### Scenario: User syncs a Consider-backed investor source

- **WHEN** the user runs `openopps sources sync sequoia`
- **THEN** boards from that Consider-backed source are normalized with raw payloads and board-provider hints

### Requirement: Job-capable providers fetch jobs

Ashby, Greenhouse, Lever, and public Workday CXS providers SHALL fetch public job postings and normalize them into the shared Job contract.

#### Scenario: Ashby board syncs jobs

- **WHEN** a board has an Ashby provider route
- **THEN** OpenOpps fetches jobs from the public Ashby job posting API
- **AND** excludes postings marked `isListed: false` from normal job sync output

#### Scenario: Greenhouse board syncs jobs

- **WHEN** a board has a Greenhouse provider route
- **THEN** OpenOpps fetches jobs from the public Greenhouse board API

#### Scenario: Lever board syncs jobs

- **WHEN** a board has a Lever provider route
- **THEN** OpenOpps fetches jobs from the public Lever postings JSON API

#### Scenario: Workday board syncs jobs

- **WHEN** a board has a Workday CXS provider route with host tenant and site
- **THEN** OpenOpps paginates public listings and fetches details for listings with `externalPath`

### Requirement: Provider route probing reports missing route metadata

OpenOpps SHALL provide a best-effort route probe for job-capable provider hints that lack the token, URL, host, tenant, or site needed for job fetching.

#### Scenario: Probe finds a candidate token

- **WHEN** the user runs `openopps providers probe-routes --provider greenhouse`
- **THEN** OpenOpps tries bounded candidate tokens derived from stored board metadata
- **AND** reports matched routes without persisting them unless `--apply` is passed

#### Scenario: Probe finds an Ashby job board name

- **WHEN** the user runs `openopps providers probe-routes --provider ashbyhq`
- **THEN** OpenOpps tests candidate board names against the public Ashby posting API
- **AND** reports the matched Ashby hosted board URL

#### Scenario: Probe cannot resolve a route

- **WHEN** candidate tokens or Workday URL hints do not resolve
- **THEN** OpenOpps lists the board as unknown with the candidates or URL hints that were tried

#### Scenario: Probe reports diagnostics

- **WHEN** route probing completes
- **THEN** the JSON summary includes selected-by-provider, matched-by-provider, unresolved-reason, and error counts

### Requirement: Provider health reports working and uncovered providers

OpenOpps SHALL provide a provider health command that samples board-discovery source adapters and job-capable board routes, while reporting discovered providers that are not yet covered by job fetching.

#### Scenario: User checks provider health

- **WHEN** the user runs `openopps providers health --json`
- **THEN** OpenOpps reports source status counts, board-route status counts, duplicate route skips, and grouped not-covered providers
- **AND** health checks do not persist status metadata unless `--apply` is passed
- **AND** job-route health checks use lightweight count or sample requests rather than full job-detail syncs

#### Scenario: Health status is persisted

- **WHEN** the user runs `openopps providers health --apply`
- **THEN** source health is stored under source raw metadata
- **AND** board-provider route health is stored on `last_status`

### Requirement: Provider requests are deduped across overlapping sources

OpenOpps SHALL preserve overlapping source board records while avoiding duplicate external provider requests for the same board route.

#### Scenario: Overlapping sources have the same provider token

- **WHEN** two source boards point to the same job-capable provider route
- **THEN** OpenOpps requests that provider route once during job sync
- **AND** reports the duplicate route skip in metrics

#### Scenario: Overlapping sources share an upstream board slug

- **WHEN** two source adapters emit the same upstream board slug for different source keys
- **THEN** OpenOpps stores them under separate source-scoped board keys
- **AND** preserves each source's board-provider routes and job attribution separately

#### Scenario: Overlapping sources have the same board identity before route probing

- **WHEN** two source boards lack route metadata but share the same provider and canonical board domain
- **THEN** OpenOpps probes that board/provider combination once
- **AND** reports the duplicate route skip in the probe summary

### Requirement: Detect-only providers are preserved

Providers without reliable V1 job fetching SHALL remain detectable metadata and SHALL NOT be reported as job-capable.

#### Scenario: Board has a detect-only provider hint

- **WHEN** source data reports a detect-only provider
- **THEN** OpenOpps preserves the hint without attempting a job sync for that provider by default
