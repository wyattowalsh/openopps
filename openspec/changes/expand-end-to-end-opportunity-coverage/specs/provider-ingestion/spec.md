# provider-ingestion Specification

## ADDED Requirements

### Requirement: Ten built-in ATS families publish honest capability manifests

OpenOpps SHALL publish capability manifests for exactly these ten built-in jobs-capable provider ids: `greenhouse`, `lever`, `ashbyhq`, `workable`, `workday`, `rippling`, `teamtailor`, `bamboohr`, `consider_jobs`, and `wpjobmanager`. Each manifest SHALL match implemented list and exact-get hooks and SHALL state whether the public interface is documented or best-effort. A list hook SHALL succeed only after complete public membership, pagination or terminal-page evidence, and fail-closed handling of duplicate identities or advertised-count mismatch where the provider documents those contracts. Exact-get SHALL mean a declared native public detail hook, or an authoritative complete board-scan with exactly one exact-identity match. OpenOpps SHALL NOT advertise a native get that is not implemented. Support levels SHALL remain `detect`, `jobs`, or `unsupported`.

#### Scenario: Capability reporting lists the ten built-ins without overclaiming get

- **WHEN** OpenOpps reports provider capabilities for built-in ATS families
- **THEN** each of the ten ids is present with a jobs-capable list declaration backed by an executable hook
- **AND** `greenhouse` and `lever` report documented list plus native get
- **AND** `workday`, `rippling`, `bamboohr`, and `wpjobmanager` report best-effort list plus native get
- **AND** `ashbyhq` reports documented list, no native get, board-scan get, and gated unlisted enumerate
- **AND** `workable` and `teamtailor` report best-effort list, no native get, and board-scan get
- **AND** `consider_jobs` reports best-effort list with no native get and no board-scan get until exact-get proof

#### Scenario: Ashby Workable and Teamtailor remain board-scan get only

- **WHEN** a caller requests exact-get for an `ashbyhq`, `workable`, or `teamtailor` posting target
- **THEN** OpenOpps uses a declared authoritative board-scan get when that capability is advertised
- **AND** the manifest does not claim a native public detail hook
- **AND** success requires a complete board result and exactly one exact-identity match

#### Scenario: Consider has no get until exact-get evidence lands

- **WHEN** capability manifests are evaluated before Consider exact-get proof
- **THEN** `consider_jobs` reports no native get and no board-scan get
- **AND** OpenOpps does not advertise a successful exact posting retrieval for Consider

#### Scenario: Consider exact-get is advertised only after proof

- **WHEN** G2 evidence proves a stable public posting URL or an authoritative complete board-scan get for Consider
- **THEN** `consider_jobs` may advertise exact-get matching that proven hook
- **AND** a native get is advertised only when that public posting URL is stable
- **AND** otherwise exact-get is an authoritative board-scan with exactly one match

#### Scenario: Greenhouse listing fail-closed evidence

- **WHEN** a Greenhouse board documents an advertised job count or yields duplicate posting ids
- **THEN** listing completeness fixtures fail closed rather than returning a partial successful membership
- **AND** the capability manifest still reports documented list plus native get

### Requirement: Indeed and Glassdoor stay unsupported like LinkedIn and Wellfound

OpenOpps SHALL treat Indeed and Glassdoor as unsupported providers and hosts, in the same class as LinkedIn and Wellfound. OpenOpps SHALL NOT register `indeed.com` or `glassdoor.com` as jobs-capable providers, SHALL NOT package them as core source adapters, and SHALL NOT attempt unauthenticated job fetching from those hosts. Wellfound, AngelList, WorkAtAStartup, and LinkedIn SHALL remain out of scope. OpenOpps SHALL NOT add a CB-unicorn rank feed.

#### Scenario: Indeed is unsupported like LinkedIn

- **WHEN** a user lists providers or evaluates a URL on `indeed.com`
- **THEN** OpenOpps reports Indeed as unsupported
- **AND** it does not fetch jobs from Indeed
- **AND** the outcome matches the LinkedIn and Wellfound unsupported class

#### Scenario: Glassdoor is unsupported like Wellfound

- **WHEN** a user lists providers or evaluates a URL on `glassdoor.com`
- **THEN** OpenOpps reports Glassdoor as unsupported
- **AND** it does not fetch jobs from Glassdoor
- **AND** overlay outcomes may classify those hosts as `policy_blocked`

### Requirement: Successor overlay locators remain URL-match only

Packaged overlay and household locators SHALL attach a jobs-capable provider route only when URL matching classifies the locator as jobs-capable. OpenOpps SHALL NOT invent an ATS token from a company domain, overlay name, ticker, or careers host guess. Overlay JSON remains maintainer-owned packaged data. A URL pull SHALL NOT create, promote, or rewrite overlay locators or catalog selectors. Household index seeds SHALL remain `fortune500`, `sp500`, `nasdaq100`, `sec-company-tickers`, and `yc`.

#### Scenario: A packaged overlay locator is a public ATS URL

- **WHEN** overlay JSON contains a public ATS URL that URL matching classifies as jobs-capable
- **THEN** OpenOpps may attach that provider route on overlay source sync
- **AND** it does not derive a different token from the company domain

#### Scenario: A household index row has only a company domain

- **WHEN** a household index seed has a company domain or ticker without a matched ATS URL
- **THEN** OpenOpps does not invent an ATS token
- **AND** the row may remain a board without a jobs-capable provider

#### Scenario: URL pull does not mutate overlay or catalog

- **WHEN** the user runs `openopps jobs pull <URL>` for a supported provider
- **THEN** packaged overlay JSON is unchanged
- **AND** catalog source and board selectors are unchanged

### Requirement: New public ATS families admit only behind a demand-and-proof gate

OpenOpps SHALL add a new jobs-capable ATS family only when all of the following hold: the family is public and unauthenticated; it unlocks materially sought-after knowledge-work employers that the ten built-ins and overlay/index cannot already cover; it proves board listing plus exact-posting retrieval; it ships a capability manifest and deterministic fixtures; and provider-native fields remain in a namespaced extension until the separate field-promotion gate passes. Login-walled, anti-bot, and one-off HTML career pages SHALL be recorded as `no_public_ats` and SHALL NOT receive generic scrapers. An employer-specific adapter SHALL require independent signals for demand, inventory, geographic or role breadth, no reusable platform path, tests, provenance, and a named maintenance owner. SmartRecruiters, Recruitee, iCIMS, Jobvite, and JazzHR SHALL remain candidates until this gate fires.

#### Scenario: A candidate family lacks exact-get proof

- **WHEN** a candidate ATS can list some postings but cannot prove exact-get
- **THEN** OpenOpps does not register it as a jobs-capable provider
- **AND** the evaluation records a do-not-adopt rationale

#### Scenario: One-off HTML does not register a provider

- **WHEN** a sought-after employer has only a one-off HTML career page
- **THEN** OpenOpps does not add a generic scraper or jobs provider id
- **AND** the overlay or index outcome is `no_public_ats` rather than a new family

#### Scenario: An admitted family keeps native fields namespaced

- **WHEN** a new family passes admission and ships fixtures
- **THEN** OpenOpps registers a jobs-capable provider with an honest capability manifest
- **AND** provider-native fields stay in a namespaced extension until the field-promotion gate passes

### Requirement: Quarantined discovery never shares a run with catalog sync

OpenOpps SHALL keep scout, verify-scout, `launch_isolated_scout`, and preview-promotion on a quarantined path that never shares a run with `openopps sync`. Those commands SHALL NOT take `--apply`, SHALL NOT mutate operational SQLite, Git, Kaggle, or Cloudflare, and SHALL NOT populate catalog selectors or packaged overlay JSON. Untrusted scout output SHALL be accepted only through `launch_isolated_scout`. Pull modules SHALL NOT import `openopps.discovery`.

#### Scenario: Scout does not run inside sync

- **WHEN** a user runs `openopps sync`
- **THEN** OpenOpps does not invoke scout, verify-scout, or preview-promotion
- **AND** catalog ingest does not read untrusted scout output as a source registry

#### Scenario: Discovery commands stay isolated

- **WHEN** a user runs `openopps discovery scout`, `verify-scout`, or `preview-promotion`
- **THEN** those commands do not call `openopps sync`
- **AND** they do not persist operational catalog, overlay, or URL-pull ledger rows
- **AND** they expose no `--apply` option

### Requirement: Shared listing kernel remains optional after a proven shared gap

OpenOpps MAY share listing evidence helpers across catalog `fetch_jobs` and URL-list `pull_list` only after a proven shared gap. Per-family adapters SHALL remain honest without wrapping ingest in `pull_list` or wrapping `fetch_jobs` in the kernel. Teamtailor guid-first ingest SHALL NOT be replaced by a kernel wrap of `fetch_jobs`.

#### Scenario: Adapters deepen without a kernel rewrite

- **WHEN** a built-in ATS family closes listing or exact-get honesty
- **THEN** that adapter may land without editing `listing.py`
- **AND** catalog fetch and URL-list still MUST NOT wrap each other

#### Scenario: Kernel is touched only after a shared evidence gap

- **WHEN** G2 writers prove a shared listing-evidence gap across families
- **THEN** a later exclusive kernel writer MAY adjust `listing.py`
- **AND** the change still MUST NOT wrap ingest in `pull_list`
