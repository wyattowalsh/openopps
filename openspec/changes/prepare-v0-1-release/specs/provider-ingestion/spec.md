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
- **THEN** OpenOpps records the source as disabled or unsupported metadata
- **AND** points future authorized data flows toward plugins or explicit user-provided imports rather than browser/session scraping

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
