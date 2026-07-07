## ADDED Requirements

### Requirement: Baseline job-capable providers remain supported

OpenOpps v0.1 SHALL keep Ashby, Greenhouse, Lever, and public Workday CXS as baseline job-capable providers unless validation proves a provider must be explicitly downgraded.

#### Scenario: Baseline provider route is executable

- **WHEN** a board has a valid baseline provider route
- **THEN** job sync can fetch public postings and normalize them into shared job records

### Requirement: Detect-only providers remain metadata unless proven generic

Manatal, Gem, Wellfound/Angel, Editorial, and other candidate providers SHALL remain detect-only or unsupported metadata unless the provider coverage audit proves reliable generic public fetching is low risk.

#### Scenario: Detect-only provider is discovered

- **WHEN** a source emits a detect-only provider hint
- **THEN** OpenOpps preserves the hint
- **AND** does not attempt job sync for that provider by default

### Requirement: Adopted public board providers use no-auth routes

OpenOpps v0.1 SHALL support Workable, Teamtailor, BambooHR, Rippling, and WP Job Manager only through public, unauthenticated board routes.

#### Scenario: Public BambooHR board route is executable

- **WHEN** a board has a BambooHR tenant route such as `https://{tenant}.bamboohr.com/careers`
- **THEN** OpenOpps fetches public board JSON from `/careers/company-info`, `/careers/list`, and `/careers/{job_id}/detail` as needed
- **AND** OpenOpps does not require, configure, document, or call the authenticated BambooHR ATS API for v0.1 public sync

#### Scenario: Public Rippling board route is executable

- **WHEN** a board has a Rippling route such as `https://ats.rippling.com/{board_slug}/jobs`
- **THEN** OpenOpps fetches paginated public board JSON from `/api/v2/board/{board_slug}/jobs`
- **AND** may fetch `/api/v2/board/{board_slug}/jobs/{job_id}` for richer job details using bounded concurrency

#### Scenario: Public WP Job Manager route is executable

- **WHEN** a board has an explicit or probed WP Job Manager origin
- **THEN** OpenOpps fetches public listings from `/wp-json/wp/v2/job-listings`
- **AND** OpenOpps does not classify arbitrary WordPress sites as WP Job Manager boards without endpoint evidence

#### Scenario: Public hosted-board route is executable

- **WHEN** a board has a Workable or Teamtailor route
- **THEN** OpenOpps fetches jobs from the public Workable hosted-board Markdown/JSON surface or Teamtailor RSS surface
- **AND** preserves raw upstream payloads for auditability

### Requirement: Anti-bot source surfaces stay out of core job sync

OpenOpps SHALL NOT add browser-driven, authenticated, or anti-bot-bypass source extraction to the v0.1 core CLI.

#### Scenario: Wellfound startup discovery is blocked

- **WHEN** Wellfound/Angel startup discovery cannot be fetched through static no-auth assets or public search-index endpoints
- **THEN** OpenOpps excludes it from the packaged source catalog and records the unsupported outcome in release rationale
- **AND** points future authorized data flows toward plugins or explicit user-provided imports rather than browser/session scraping

#### Scenario: Fair-access source rejects generic scheduled syncs

- **WHEN** an official detect-only source requires caller-specific fair-access headers or network posture beyond the generic scheduled CLI environment
- **THEN** OpenOpps excludes that source from unscoped scheduled sync unless it has an explicitly invoked access-constrained path
- **AND** documents how to run the explicit path when the caller can satisfy the upstream access policy

### Requirement: Provider requests remain bounded and deduped

Source sync, route probing, provider health, metadata enrichment, and job sync SHALL use bounded concurrency and avoid duplicate provider requests where overlapping sources or routes refer to the same upstream provider route.

#### Scenario: Overlapping boards share provider route

- **WHEN** multiple persisted boards resolve to the same provider request key
- **THEN** OpenOpps performs at most one upstream request for that route in the same sync/probe operation
- **AND** reports duplicate skips in metrics where relevant

#### Scenario: Source refresh repeats provider hints

- **WHEN** a later source sync reports the same provider hint without executable route metadata
- **THEN** OpenOpps preserves any previously probed token, hosted board URL, Workday CXS fields, and route status
- **AND** does not turn expected ready-route, duplicate-route, or missing-metadata filtering into warning-worthy skipped work

#### Scenario: Persisted route becomes unavailable

- **WHEN** a provider route returns a terminal unavailable status during job sync
- **THEN** OpenOpps removes that route from future job-sync targets and continues unrelated routes
- **AND** terminal not-found style responses close missing jobs for that route as a successful empty observation

#### Scenario: Provider publishes rate-limit headers

- **WHEN** a provider responds with a retry-after or rate-limit reset header
- **THEN** OpenOpps waits for that provider-directed delay before retrying the JSON request
- **AND** classifies repeated 429 failures as rate-limited diagnostics instead of generic provider errors

#### Scenario: Workable routes are probed or synced

- **WHEN** OpenOpps makes public Workable route-probe, listing, or detail requests
- **THEN** requests are throttled to the documented public ceiling of 10 requests per 10 seconds
- **AND** unrelated providers continue using the general bounded concurrency settings

### Requirement: Sync metrics distinguish fetched and persisted jobs

OpenOpps SHALL keep the existing `jobs` metric as the fetched job count while adding persisted-job accounting for route-level SQLite writes.

#### Scenario: Jobs sync writes metrics JSON

- **WHEN** a jobs sync or combined sync emits `--metrics-json`
- **THEN** the payload includes `jobsPersisted`, `jobSyncRuns`, and `jobsDeduped`
- **AND** existing consumers that read `jobs`, `providerErrors`, `skipped`, or `duplicateRoutesSkipped` continue to receive those fields

#### Scenario: Provider failures are summarized

- **WHEN** provider work fails during source sync, route probing, or job sync
- **THEN** OpenOpps reports the existing provider error counts
- **AND** additive diagnostics classify source fetch, job fetch, validation, unavailable, and rate-limited failures where the failure type is known

### Requirement: Broken packaged sources are removed instead of tombstoned

Packaged source catalog entries SHALL only include currently runnable public sources or sources with explicit opt-in access constraints.

#### Scenario: A packaged source no longer exposes a runnable public endpoint

- **WHEN** live evidence shows a source returns no boards because its public page or API is forbidden, timed out, or unavailable and no replacement endpoint is proven
- **THEN** OpenOpps removes that source from the active packaged catalog
- **AND** does not add disabled tombstones, aliases, fallback legacy entries, or SQLite migrations for pre-release local rows

### Requirement: Provider failures are isolated

Live-network failures SHALL be isolated to the affected source, board, route, provider, cache entry, or plugin-provided adapter and SHALL not crash unrelated work.

#### Scenario: One provider fails

- **WHEN** one provider request fails during a multi-provider sync
- **THEN** OpenOpps summarizes the failure and continues eligible unrelated work when safe
