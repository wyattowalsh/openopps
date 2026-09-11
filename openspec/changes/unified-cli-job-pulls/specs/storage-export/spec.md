## ADDED Requirements

### Requirement: Successful URL pulls persist only with opt-in `--save`

OpenOpps SHALL persist the normalized result and dedicated audit state for a successful URL pull to the configured local ledger only when the user explicitly selects `--save`. The persistence default SHALL be off (`--save` False). `--no-save` remains an explicit ephemeral alias for that default.

#### Scenario: A successful board pull uses the default ephemeral behavior

- **WHEN** a URL pull completes an authoritative full-board list operation without `--save`
- **THEN** OpenOpps does not persist operational board, route, jobs, versions, observations, lifecycle result, raw evidence, or URL-pull audit state
- **AND** it still reports the pull result

#### Scenario: A successful posting pull uses the default ephemeral behavior

- **WHEN** a URL pull completes an exact single-post get operation without `--save`
- **THEN** OpenOpps does not persist that posting's normalized identity, version, observation, raw evidence, or URL-pull audit state
- **AND** it does not require the posting to belong to a packaged source-catalog board

#### Scenario: An explicit `--save` pull persists the result

- **WHEN** a URL pull completes an authoritative list or exact get with `--save`
- **THEN** OpenOpps persists the normalized result and dedicated URL-pull audit state to the configured local ledger
- **AND** it reports the persistence outcome with the pull result

#### Scenario: Save without a writable ledger fails closed

- **WHEN** a URL pull runs with `--save` without a writable local ledger
- **THEN** the invocation fails with an actionable persistence error rather than claiming a saved success
- **AND** a default invocation without `--save` remains ephemeral and does not require a writable ledger

### Requirement: No-save leaves operational state unchanged

OpenOpps SHALL make `--no-save` an operational-persistence boundary for URL pulls without implicitly changing HTTP-cache policy.

#### Scenario: A no-save pull succeeds

- **WHEN** a URL pull completes with `--no-save`
- **THEN** operational source, board, route, job, version, observation, lifecycle, job-sync-run, and URL-pull-run records remain unchanged
- **AND** the normalized or raw result is still emitted according to the selected output contract
- **AND** HTTP-cache reads and writes remain governed independently by cache controls

### Requirement: URL pulls use a dedicated audit domain

OpenOpps SHALL record saved URL-pull attempts in a dedicated `url_pull_runs` operational audit domain that remains distinct from `job_sync_runs` and generic sync-invocation accounting.

#### Scenario: A saved pull attempt starts

- **WHEN** a URL pull enters the saved execution path
- **THEN** OpenOpps creates a pending URL-pull audit with requested and resolved operation, bounded timestamps and status, provider and parsed identities, sanitized discovery provenance, and membership and detail evidence fields
- **AND** it does not store arbitrary request headers, query strings, HTML, or raw exception text in that audit

#### Scenario: An authoritative board pull completes

- **WHEN** a saved list operation has fetched and validated its complete authoritative provider result
- **THEN** its URL-pull audit completes with bounded counts and authority evidence
- **AND** it may link to the job-sync lifecycle created by the atomic list application

#### Scenario: An exact posting pull completes

- **WHEN** a saved get operation persists one exact posting
- **THEN** its URL-pull audit records `operation=get` and may link to the exact job and version
- **AND** OpenOpps does not create a `job_sync_run` or generic sync invocation for that point retrieval

#### Scenario: A pull fails before successful application

- **WHEN** a saved pull is ambiguous, unsupported, incomplete, non-authoritative, or otherwise fails
- **THEN** OpenOpps may retain a sanitized terminal failure in `url_pull_runs`
- **AND** it does not persist partial results as a successful snapshot or create a synthetic board route solely for the failed attempt

### Requirement: Saved URL pulls use a deterministic non-catalog namespace

OpenOpps SHALL resolve saved URL-derived boards and routes only inside one reserved operational `url-pull` namespace, using provider-native board identity plus a collision-resistant digest rather than pasted posting URLs or lossy slug normalization alone.

#### Scenario: Equivalent URLs identify the same operational board

- **WHEN** canonical variants of a board or posting URL resolve to the same provider-native board identity
- **THEN** repeated saved pulls converge on the same reserved source, board, and route identity
- **AND** the reserved operational source remains excluded from packaged and effective source catalogs and source selectors
- **AND** its public domain field remains unset

#### Scenario: Distinct native identities normalize similarly

- **WHEN** punctuation-distinct or otherwise similar provider-native board identifiers would collide under lossy slug normalization
- **THEN** their reserved operational identities remain distinct

#### Scenario: The reserved namespace is occupied by an unowned row

- **WHEN** URL-pull persistence finds an existing source, board, or route key in the reserved namespace that is not owned by the URL-pull subsystem
- **THEN** persistence fails closed with a collision error
- **AND** no catalog, domain, job, or lifecycle state is mutated

### Requirement: List and get persistence have distinct lifecycle authority

OpenOpps SHALL apply full-board list results and exact single-post get results through separate lifecycle semantics.

#### Scenario: An authoritative list is saved

- **WHEN** every required membership page and provider-required detail request has completed and the result passes authority validation
- **THEN** OpenOpps applies the list as a route snapshot and may close missing jobs only under the existing lifecycle rules for that exact membership scope
- **AND** the job-sync lifecycle is created and linked only after complete-fetch validation succeeds

#### Scenario: An exact get is saved

- **WHEN** a native get or authoritative board-scan fallback identifies exactly one posting
- **THEN** OpenOpps upserts and versions only that posting
- **AND** it never performs route reconciliation, closes an unrelated job, or represents the get as an authoritative route snapshot

#### Scenario: A result lacks lifecycle authority

- **WHEN** a list or board-scan result is incomplete, ambiguous, non-authoritative, or exhausts a required budget
- **THEN** OpenOpps does not apply job lifecycle changes
- **AND** it does not label partial persisted data as a successful snapshot

### Requirement: Membership scopes govern reconciliation

OpenOpps SHALL persist posting membership as `listed` or `direct_only` and authoritative list-run scope as `listed` or `all_public`, and SHALL use those scopes when reconciling jobs.

#### Scenario: A direct-link-only posting is saved

- **WHEN** an exact get retrieves a public posting that is absent from ordinary listed board membership
- **THEN** OpenOpps stores the posting with `direct_only` membership
- **AND** a later listed-only snapshot cannot close that posting

#### Scenario: A direct-link posting later becomes listed

- **WHEN** an authoritative listed board snapshot observes a previously direct-only posting
- **THEN** OpenOpps promotes the posting's membership to `listed`

#### Scenario: An all-public snapshot is reconciled

- **WHEN** a provider supports the explicit unlisted opt-in and a complete authoritative list operation includes it
- **THEN** OpenOpps records `all_public` as the list-run membership scope
- **AND** only that scope may reconcile both listed and direct-only membership

### Requirement: URL-pull lifecycle application is atomic

OpenOpps SHALL fetch and validate the complete provider result before applying URL-pull lifecycle state, and SHALL commit normalized jobs, versions, observations, membership transitions, and permitted closure as one atomic application.

#### Scenario: Persistence fails during list application

- **WHEN** any early or late batch, constraint, or commit step fails while applying a validated board result
- **THEN** all job open, closed, current-version, observation, and membership state remains as it was before application
- **AND** no successful job-sync snapshot is committed
- **AND** a separately retained sanitized URL-pull failure audit does not imply lifecycle success

#### Scenario: A board exceeds an in-memory application bound

- **WHEN** a validated board result requires staged persistence to remain bounded
- **THEN** OpenOpps stages rows only in owned operational storage
- **AND** promotes or reconciles those rows in one transaction
- **AND** an interrupted or failed promotion leaves prior lifecycle state authoritative

### Requirement: Saved pulls preserve normalized and structured raw evidence

OpenOpps SHALL preserve normalized job records together with the provider-native structured `listing` and `detail` evidence captured for each posting, when those payloads are available, plus sanitized pull provenance sufficient for audit and reprocessing.

#### Scenario: Listing and detail payloads are both available

- **WHEN** a saved provider operation returns listing metadata and a separate detail payload for a posting
- **THEN** OpenOpps preserves the two structured payload roles without flattening one into the other
- **AND** relates the evidence to the persisted job identity and version

#### Scenario: A provider returns only one payload role

- **WHEN** a provider contract returns only listing or only detail evidence
- **THEN** OpenOpps preserves the available structured payload and identifies its role
- **AND** does not invent the missing role or claim full wire-level losslessness

### Requirement: Portable snapshots preserve URL-pull audit history

OpenOpps SHALL include the dedicated URL-pull audit domain in supported operational database copy and snapshot paths without merging it into job-sync or generic sync-invocation tables.

#### Scenario: A local operational snapshot is created

- **WHEN** OpenOpps copies the managed operational ledger into a supported update snapshot or portable SQLite snapshot
- **THEN** `url_pull_runs` records are copied with deterministic schema handling and valid references
- **AND** the source ledger and copied URL-pull audit history remain unchanged
