# provider-ingestion Specification

## Purpose
Define how OpenOpps discovers board sources, preserves provider hints, probes executable public routes, and fetches normalized job records from job-capable providers.
## Requirements
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

OpenOpps SHALL provide packaged source definitions for Lightspeed, Sequoia, Bessemer, Greylock, Kleiner Perkins, and SignalFire.

#### Scenario: User syncs a Getro-backed investor source

- **WHEN** the user runs `openopps sources sync signalfire`
- **THEN** boards from that Getro-backed source are normalized with raw payloads and active job count hints

#### Scenario: User syncs a Consider-backed investor source

- **WHEN** the user runs `openopps sources sync sequoia`
- **THEN** boards from that Consider-backed source are normalized with raw payloads and board-provider hints

### Requirement: Job-capable providers fetch jobs

OpenOpps v0.1 SHALL treat Ashby, Greenhouse, Lever, public Workday CXS, Workable, Teamtailor, BambooHR, Rippling, and WP Job Manager as adopted job-capable providers when executable public routes are present, and SHALL fetch public job postings into the shared Job contract.

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

#### Scenario: Adopted no-auth board provider syncs jobs

- **WHEN** a board has a public Workable, Teamtailor, BambooHR, Rippling, or WP Job Manager route
- **THEN** OpenOpps fetches jobs from the documented public no-auth board surface for that provider
- **AND** preserves raw upstream payloads for auditability

### Requirement: Adopted public board providers use no-auth routes

OpenOpps v0.1 SHALL support Workable, Teamtailor, BambooHR, Rippling, and WP Job Manager only through public, unauthenticated board routes.

#### Scenario: Public BambooHR board route is executable

- **WHEN** a board has a BambooHR tenant route such as `https://{tenant}.bamboohr.com/careers`
- **THEN** OpenOpps fetches public board JSON from the documented careers endpoints as needed
- **AND** OpenOpps does not require, configure, document, or call the authenticated BambooHR ATS API for v0.1 public sync

### Requirement: Provider surplus fields are promoted without public raw payload exposure

OpenOpps SHALL promote high-value provider list and detail fields into normalized job fields or bounded version metadata while preserving full raw provider evidence in local SQLite and Kaggle export surfaces.

#### Scenario: Workable listing and detail payloads are distinct

- **WHEN** Workable jobs are fetched from listing and detail endpoints
- **THEN** OpenOpps keeps listing and detail raw payload evidence distinct
- **AND** normalized job output uses the shared Job contract

### Requirement: Derived job facets are generated from normalized fields

OpenOpps SHALL derive public docs job facets from normalized fields and bounded metadata rather than from committed raw provider payload snapshots.

#### Scenario: Seniority is derived for docs search

- **WHEN** a job lacks an explicit provider seniority value
- **THEN** OpenOpps derives seniority from title and experience fields
- **AND** the generated docs search manifest can expose a seniority facet without constructing invalid job records

### Requirement: Provider route probing reports missing route metadata

OpenOpps SHALL provide a best-effort route probe for job-capable provider hints that lack the token, URL, host, tenant, or site needed for job fetching.

#### Scenario: Probe finds a candidate token

- **WHEN** the user runs `openopps admin providers probe-routes --provider greenhouse`
- **THEN** OpenOpps tries bounded candidate tokens derived from stored board metadata
- **AND** reports matched routes without persisting them unless `--apply` is passed

#### Scenario: Probe finds an Ashby job board name

- **WHEN** the user runs `openopps admin providers probe-routes --provider ashbyhq`
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

### Requirement: WorkAtAStartup remains out of scope for v0.1

OpenOpps SHALL NOT package WorkAtAStartup as a core source adapter while the YC source provider covers startup-board discovery for v0.1.

#### Scenario: Packaged source catalog is loaded

- **WHEN** OpenOpps loads the packaged public source catalog
- **THEN** WorkAtAStartup is excluded
- **AND** YC remains the documented preferred startup-board source for that discovery surface

### Requirement: Wellfound and Angel outcomes are explicit

OpenOpps SHALL document whether Wellfound/Angel startup discovery is supported through static no-auth assets or explicitly unsupported with release rationale.

#### Scenario: Wellfound cannot be fetched without session or browser automation

- **WHEN** Wellfound/Angel discovery cannot be served from static no-auth assets or approved public search-index endpoints
- **THEN** OpenOpps excludes it from the packaged source catalog
- **AND** records the unsupported outcome in release rationale and provider coverage reporting

### Requirement: Editorial source labels are audited before provider identity

OpenOpps SHALL audit `Editorial` and `Editiorial` source labels before registering a dedicated provider adapter identity.

#### Scenario: Editorial label appears without a proven public route

- **WHEN** source data reports Editorial or Editiorial as a provider hint without executable public route metadata
- **THEN** OpenOpps preserves the hint as detect-only metadata
- **AND** does not add a job-capable provider identity until route probe evidence proves a generic public fetch path

### Requirement: Job providers reconcile only complete route snapshots

OpenOpps SHALL close missing jobs only after a provider has fetched and validated a complete route snapshot.

#### Scenario: A later provider page fails

- **WHEN** a later Consider or Workable page is malformed, repeated, unsafe, or unsuccessful
- **THEN** the provider raises without returning a partial list
- **AND** existing jobs remain open with current versions unchanged

### Requirement: Consider company boards use exact job routes

OpenOpps SHALL route `/boards/co/<token>` through `consider_jobs` while preserving valid punctuation.

#### Scenario: A token contains punctuation

- **WHEN** a valid route contains dots, underscores, hyphens, a trailing dot, or a leading digit
- **THEN** selection, probing, and fetching use the same decoded token
- **AND** stale metadata cannot replace the URL-derived token

### Requirement: Workable traverses every listing page

OpenOpps SHALL follow every Workable continuation token and use the complete v3 listing set as authoritative.

#### Scenario: A board has multiple pages

- **WHEN** a response includes `nextPage`
- **THEN** OpenOpps requests the next page with `{"token": nextPage}`
- **AND** performs at most one account-level details request for optional enrichment

