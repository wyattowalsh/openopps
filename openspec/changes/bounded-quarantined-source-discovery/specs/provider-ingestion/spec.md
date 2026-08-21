## ADDED Requirements

### Requirement: Scheduled snapshots consume an exact private approved-ingestion selector envelope

OpenOpps SHALL bind each scheduled daily snapshot to one validated private `ApprovedIngestionSelectorEnvelope` and packaged-catalog fingerprint before source or provider network work begins. The envelope SHALL remain distinct from, and SHALL NOT modify or replace, the v7 public `SourceSelector`.

#### Scenario: A daily snapshot starts

- **WHEN** the scheduled snapshot workflow begins
- **THEN** it validates and records the sorted source keys, source count, source-key digest, packaged-catalog fingerprint, catalog content/tree digest, read-only v7 policy code/schema/evidence/corpus digests, supplementary discovery-policy digest, promotion digest, and envelope identity
- **AND** every source-sync stage uses that pinned in-memory selection
- **AND** planned source and route denominators remain available for completeness reporting
- **AND** the checkout commit SHA is recorded separately in the invocation attestation rather than embedded self-referentially in tracked envelope bytes

#### Scenario: The approved catalog changes during a run

- **WHEN** tracked catalog bytes or an external quarantine bundle change after selection
- **THEN** the active run continues only with its already validated pinned selector
- **AND** records the original selector and catalog fingerprint
- **AND** the change is eligible only for a later run after normal review

#### Scenario: Selector identity does not match the catalog

- **WHEN** source keys, count, source-key digest, catalog fingerprint, catalog content/tree digest, any policy-input digest, supplementary policy digest, or promotion digest does not match
- **THEN** the scheduled run fails before network access
- **AND** it does not publish a snapshot under the mismatched identity

### Requirement: Quarantined candidates cannot enter ingestion

OpenOpps SHALL NOT treat a discovery manifest, evidence member, candidate record, or promotion preview as a runtime source registry or executable provider route.

#### Scenario: A candidate bundle is present beside a daily run

- **WHEN** a verified or unverified quarantine bundle exists locally
- **THEN** unscoped source sync, route probing, job sync, and snapshot generation ignore it
- **AND** only the pinned private approved-ingestion envelope determines scheduled source eligibility

#### Scenario: A caller attempts same-run activation

- **WHEN** a caller supplies a newly emitted candidate or manifest to a scheduled snapshot invocation
- **THEN** OpenOpps rejects the attempt
- **AND** no candidate source, board, route, or job observation is persisted

### Requirement: Scheduled selection does not erase explicit local custom behavior

OpenOpps SHALL keep ordinary explicitly scoped local custom-source workflows separate from the approved scheduled-snapshot selector.

#### Scenario: A user invokes an explicit local custom source

- **WHEN** a user has registered a custom source through the existing advanced local workflow and selects it explicitly
- **THEN** the local workflow may resolve that source according to the existing custom-source contract
- **AND** the custom source does not enter the scheduled snapshot unless separately reviewed into its private approved-ingestion envelope

#### Scenario: Stored source ownership is ambiguous

- **WHEN** a stored-only source might be either retired package state or an explicit local custom source
- **THEN** this change does not delete, migrate, or silently reclassify it
- **AND** retirement remains blocked pending evidence-backed ownership resolution

### Requirement: Scheduled ingestion conserves exact terminal accounting

OpenOpps SHALL account for every pinned source and every pre-dedup observed job-capable route in exactly one mutually exclusive terminal class.

#### Scenario: A source-sync run reaches a terminal state

- **WHEN** the pinned source set completes, partially completes, or fails
- **THEN** planned sources equal succeeded plus failed plus timed out plus freshness-skipped plus policy-blocked plus rate-limited plus cancelled plus unstarted sources
- **AND** started interrupted work is `cancelled`, planned work never launched because of cancellation, fail-fast, deadline, or budget is `unstarted`, and `aborted` remains run-level only
- **AND** a complete attestation has no failure, timeout, policy-blocked, rate-limited, cancelled, or unstarted source

#### Scenario: A route-sync run reaches a terminal state

- **WHEN** the pre-dedup planned route set completes, partially completes, or fails
- **THEN** planned routes equal succeeded plus failed plus timed out plus freshness-skipped plus deferred plus duplicate-skipped plus missing-metadata plus policy-blocked plus rate-limited plus cancelled plus unstarted routes
- **AND** each duplicate-skipped route names exactly one canonical representative that is an authoritative success or authoritative freshness skip
- **AND** no duplicate group contains only skipped entries, and freshness evidence binds the pinned envelope, catalog, invocation policy, and representative identity
- **AND** a complete attestation has no failed, timed-out, deferred, missing-metadata, policy-blocked, rate-limited, cancelled, unstarted, or non-authoritative success or freshness skip
