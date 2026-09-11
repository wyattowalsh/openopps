## ADDED Requirements

### Requirement: Catalog sync and URL-list share a membership kernel with post-evidence identity bind

OpenOpps SHALL fetch public board membership through one per-provider listing kernel used by both catalog `fetch_jobs` and URL-list `pull_list`. The kernel SHALL NOT assign a catalog `JobRecord.board_key` until `bind_listing_jobs`. Catalog sync SHALL bind onto the ledger `BoardRecord`. URL-list SHALL bind onto a synthetic board whose `source_key` is `url-pull` and whose `key` equals the provider-native board identity. `fetch_jobs` SHALL NOT call `pull_list`. Ingest SHALL continue to invoke `fetch_jobs` and SHALL NOT duck-type URL-list hooks. Incomplete or non-terminal membership SHALL NOT yield `authoritative=True`. Point-get, `--raw`, unlisted enumeration, and `source_key="url-pull"` SHALL NOT leak onto ingest. `check_jobs` SHALL remain a cheap probe except where it already full-walks a listing count. Console entry SHALL remain `openopps.cli:app`.

#### Scenario: Lever catalog sync needs more than one listing page

- **WHEN** a Lever board requires multiple `skip` and `limit` requests during catalog sync
- **THEN** OpenOpps traverses the pages through a proven terminal page before returning `JobFetchResult`
- **AND** the returned jobs use the catalog board key rather than the URL-pull identity
- **AND** `check_jobs` remains a single unpaginated count request
- **AND** an incomplete walk never reports `authoritative=True`

#### Scenario: Teamtailor catalog sync paginates without changing stored identity

- **WHEN** a Teamtailor board RSS feed spans multiple pages during catalog sync
- **THEN** OpenOpps traverses those pages through a proven terminal page
- **AND** ingest `remote_id` remains guid-first when a guid is present
- **AND** URL-list continues to prefer link identity from the posting URL tail

#### Scenario: Greenhouse advertised count does not match returned jobs

- **WHEN** Greenhouse catalog sync receives an advertised count that does not equal the returned job count
- **THEN** `fetch_jobs` fails closed with a validation error
- **AND** `check_jobs` still uses the lightweight `content=false` probe rather than the listing kernel

#### Scenario: Catalog bind and URL-pull bind stay distinct

- **WHEN** the listing kernel returns a complete listed membership
- **THEN** catalog `fetch_jobs` jobs have the ledger board key, stable id, and catalog company name
- **AND** URL-list jobs keep `board_key` equal to the native ATS identity
- **AND** binding a URL-pull identity onto a synthetic board whose key is not that native identity fails closed

#### Scenario: Ashby ingest keeps listing identity

- **WHEN** Ashby catalog sync fetches listed postings whose job URL tail differs from the listing id
- **THEN** ingest `remote_id` stays the listing id
- **AND** URL-list may still override from the hosted job URL
- **AND** catalog sync never enumerates unlisted postings

#### Scenario: BambooHR catalog sync is not capped by the URL-pull detail budget

- **WHEN** BambooHR catalog sync fetches more postings than `pull_provider_max_details`
- **THEN** ingest still fetches every listed detail
- **AND** URL-list continues to fail closed at that detail budget

#### Scenario: A plugin implements fetch_jobs without pull_list

- **WHEN** ingest synchronizes a job provider that returns `JobFetchResult` from `fetch_jobs` and does not register a URL-list hook
- **THEN** OpenOpps uses that `fetch_jobs` result
- **AND** it does not infer an authoritative empty URL-list snapshot

#### Scenario: Overlay and household attach jobs-capable ATS routes

- **WHEN** a packaged overlay or household locator is a public ATS URL
- **THEN** OpenOpps attaches a route only when `detect_url_matches` returns a jobs-capable provider
- **AND** the packaged overlay source key has one owner in the overlay adapter module
- **AND** `overlay_targets.py` remains an operational loader under `providers/sources/`
- **AND** `detect_route` and `parse_url_target` remain independent projections
