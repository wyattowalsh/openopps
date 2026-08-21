## ADDED Requirements

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
