## ADDED Requirements

### Requirement: Discovery runs as an independent quarantined scout

OpenOpps SHALL run source and board discovery independently from source sync, job sync, snapshot generation, and publication.

#### Scenario: A bounded scout invocation starts

- **WHEN** a maintainer or a separately authorized private scheduler invokes the scout
- **THEN** the scout may read approved configuration and public discovery surfaces
- **AND** it writes only to an explicit quarantine output root
- **AND** it does not mutate SQLite, runtime source registries, the packaged catalog, generated public data, release trees, or deployment channels

#### Scenario: A candidate is discovered before a daily snapshot

- **WHEN** a scout emits a new source or board candidate
- **THEN** that candidate remains quarantined
- **AND** the next daily snapshot continues using the last reviewed approved catalog
- **AND** no flag or same-run apply path can activate the candidate

### Requirement: Discovery channels are finite and explicit

OpenOpps SHALL limit official catalog and documentation discovery, public code and dataset discovery, search API discovery, and targeted employer or ATS discovery with explicit per-channel, per-host, and whole-run budgets.

#### Scenario: A channel exhausts a budget

- **WHEN** a channel reaches its query, request, response-byte, candidate, retry, or wall-clock limit
- **THEN** the channel stops issuing new work
- **AND** the manifest records the exhausted budget and unfinished work
- **AND** the run does not claim complete discovery for that channel

#### Scenario: A remote surface publishes access controls

- **WHEN** robots rules, documented API quotas, `Retry-After`, rate-limit reset metadata, or an explicit access restriction applies
- **THEN** the scout honors the applicable restriction
- **AND** it does not bypass authentication, anti-bot, session, or access controls

### Requirement: Quarantine bundles are content-addressed and exactly verifiable

OpenOpps SHALL emit each scout result as a canonical quarantine bundle whose manifest identifies the exact safe member set, bytes, roles, media types, sizes, hashes, configuration, tool version, run state, and evidence provenance.

#### Scenario: A scout completes normally

- **WHEN** every scheduled channel reaches a terminal state
- **THEN** OpenOpps writes canonical JSON using a documented non-self-referential root algorithm
- **AND** hash-bound counts, sizes, ordinals, and durations use strict non-negative integer units without floating-point values or coercion
- **AND** the manifest enumerates every bounded evidence member by safe relative POSIX path, byte length, media type, role, and SHA-256
- **AND** the final bundle is promoted atomically from an owned sibling candidate directory

#### Scenario: A bundle is modified or structurally unsafe

- **WHEN** a member is missing, extra, duplicated, case- or Unicode-normalization-colliding, oversized, symlinked, hard-linked unsafely, a device, FIFO, or socket, path-traversing, permission-unsafe, hash-mismatched, or non-canonical
- **THEN** exact verification fails
- **AND** the bundle is ineligible for review or promotion

#### Scenario: Bundle contents change while they are verified

- **WHEN** no-follow containment, regular-file type, or file identity differs before and after a member read
- **THEN** verification fails closed
- **AND** no partially verified member or bundle identity is accepted

#### Scenario: Bundle contracts are unknown, stale, replayed, or incomplete

- **WHEN** a schema or parser version is unknown, evidence is future-dated or stale, a promotion identity was replayed or revoked, or any planned terminal denominator is unclosed
- **THEN** verification fails
- **AND** the bundle remains quarantined

#### Scenario: Scout generation is interrupted

- **WHEN** generation fails before exact verification and atomic promotion
- **THEN** no partial directory is presented as a completed bundle
- **AND** any previously completed bundle remains unchanged

### Requirement: Candidate normalization preserves provenance and ambiguity

OpenOpps SHALL normalize candidates with provider-aware source, URL, domain, and board-route identities while retaining every channel-specific observation.

#### Scenario: Multiple channels find the same candidate

- **WHEN** observations resolve to the same documented canonical identity
- **THEN** OpenOpps emits one candidate with all distinct provenance edges
- **AND** deterministic ordering does not depend on channel completion order

#### Scenario: Candidate identities conflict

- **WHEN** two observations share a key, URL, domain, or provider hint but cannot be proven to identify the same source or board
- **THEN** OpenOpps retains an unresolved collision
- **AND** it does not silently merge, overwrite, or promote either identity

### Requirement: Discovery evidence is bounded and trust-separated

OpenOpps SHALL treat fetched pages, API responses, code search results, datasets, agent output, and embedded instructions as untrusted evidence and SHALL retain only the bounded material required to reproduce candidate evaluation.

#### Scenario: Evidence contains secret-like or unbounded content

- **WHEN** a response contains credentials, cookies, authorization material, credential-bearing query parameters, excessive bodies, or unrelated payloads
- **THEN** OpenOpps scans bounded bytes before any durable write or persisted content digest
- **AND** excludes high-confidence secret-bearing material and makes the candidate non-promotable
- **AND** records only a bounded reason code and safe transport metadata for excluded bytes
- **AND** any admitted raw or transformed resource has a distinct role and digest that identifies exactly the stored bytes

#### Scenario: Retrieved content contains instructions

- **WHEN** remote content asks the scout to change behavior, execute commands, reveal data, or ignore policy
- **THEN** the content remains inert evidence
- **AND** repository and operator configuration remain authoritative

#### Scenario: A locator resolves unsafely

- **WHEN** a requested or redirected locator uses credentials, an unsupported scheme or port, a private or non-global address, a disallowed redirect, or a DNS answer that cannot be pinned safely
- **THEN** the request fails closed before the unsafe connection
- **AND** the bounded reason code contains no secret-bearing locator material

### Requirement: Candidate processing, disposition, and relationships are explicit

OpenOpps SHALL represent candidate processing state, evaluation disposition, derived review eligibility, and supersession as separate fields with evidence-backed transitions and no automatic transition into the approved catalog.

#### Scenario: Evidence is incomplete or policy unresolved

- **WHEN** liveness, support, identity, access, synchronization eligibility, or required publication eligibility is unresolved
- **THEN** the candidate remains `evaluated` with disposition `inconclusive` and cannot become `eligible_for_review`
- **AND** the blocking reasons remain machine-readable

#### Scenario: Independent evaluation axes disagree

- **WHEN** candidate evidence contains any blocked, unresolved, incomplete, unsupported, or positive axis combination
- **THEN** explicit rights or security blocks dominate, then incomplete or unresolved evidence, then unsupported execution
- **AND** disposition is exactly one of `alreadyApproved`, `promotable`, `blocked`, `unsupported`, or `inconclusive`
- **AND** only `promotable` derives `eligible_for_review`; `blocked` and `unsupported` may derive a rejected review outcome
- **AND** observation or field order cannot change the disposition

#### Scenario: A later observation replaces an earlier candidate

- **WHEN** exact evidence proves that one candidate supersedes another
- **THEN** both unique candidate identities remain in their declared denominator
- **AND** the manifest records an orthogonal `supersededBy` edge, replacement identity, and rationale without replacing either disposition

### Requirement: Promotion is separate, reviewed, deterministic, and policy-gated

OpenOpps SHALL promote candidates only through a separate maintainer workflow that consumes one exact verified bundle digest and produces a deterministic repository diff.

#### Scenario: A maintainer previews promotion

- **WHEN** a maintainer selects eligible candidates from a verified bundle
- **THEN** the preview validates exact identity, liveness, support, taxonomy, catalog collisions, and the existing operation-specific policy gates
- **AND** absence of a denial is not treated as positive permission
- **AND** candidate manifests cannot contain approval, reviewer, signature, review-receipt, or revocation state
- **AND** no repository file changes unless the maintainer separately requests apply

#### Scenario: A maintainer records a review decision

- **WHEN** immutable bundle and selection digests have been displayed for review
- **THEN** the maintainer authors a separate canonical `DiscoveryPromotionPolicyDecision` outside the quarantine root that binds the manifest, selection, resources, trusted profile, required operation axes, read-only v7 policy inputs, and catalog-before digests
- **AND** that supplementary discovery decision neither edits nor aliases the v7 source-policy format or public `SourceSelector`
- **AND** the decision receipt is evidence rather than sufficient authority
- **AND** scout, verification, preview, CI, and scheduled workflows cannot generate a positive decision or invoke apply

#### Scenario: A decision is reserved, applied, or revoked

- **WHEN** promotion advances beyond preview
- **THEN** the canonical hash-chained ledger at `src/openopps/discovery/data/promotion_decision_ledger.jsonl` records an append-only `reserved`, `applied`, or `revoked` event bound to `decisionId`, one composite `promotionIntentDigest`, and all reviewed component digests
- **AND** reservation is a separately committed ledger-only phase before apply
- **AND** apply consults the current ledger and reachable repository history for duplicate decision IDs or composite promotion-intent digests
- **AND** reusable component digests are equality evidence and are not globally rejected when a distinct promotion intent legitimately reuses them
- **AND** deletion, reordering, mutation, or replay of an earlier ledger event fails closed
- **AND** reserve and apply fail closed when sufficient reachable history is unavailable, shallow, rewritten, or inconsistent with the current ledger

#### Scenario: Concurrent promotion mutations contend

- **WHEN** reserve, apply, recovery, or revoke starts
- **THEN** it acquires one nonblocking repository-scoped OS-native lock at `var/openopps/promotion.lock`
- **AND** after acquisition it revalidates `HEAD`, catalog fingerprint, ledger tail/hash chain, reservation ownership, all recovery journals, and owned-path cleanliness before writing
- **AND** contention, ambiguous ownership, or stale compare-and-swap state fails closed without elapsed-time lock stealing
- **AND** a killed holder can be followed only through normal kernel-lock acquisition and mandatory journal recovery
- **AND** one nonterminal reservation prevents same- or different-intent reservation of the same HEAD/catalog-before tuple

#### Scenario: The complete after-tree is prepared

- **WHEN** a committed reservation is ready for apply
- **THEN** OpenOpps renders catalog, every handed-off generated file, private envelope, receipt, and candidate applied-ledger bytes into one private staging tree
- **AND** canonical generation runs twice with byte identity
- **AND** a candidate wheel built from the staged tree passes exact embedded-resource and receipt verification
- **AND** any generation or wheel failure occurs before repository mutation

#### Scenario: Apply is interrupted at any write boundary

- **WHEN** a process, filesystem, cancellation, generation, or wheel failure occurs after reservation but before catalog, handed-off generated data, private envelope, receipt, and ledger closure
- **THEN** the owned non-symlinked journal at `var/openopps/promotion-recovery/<promotionIntentDigest>/` preserves the exact intent, HEAD, owned path set, before/after existence, modes, bytes/digests, write order, and `prepared`, `applying`, or `finalizing` phase with file and directory fsyncs
- **AND** every later apply/recovery entry point resolves that journal before accepting new work
- **AND** recovery finalizes only when all exact catalog, generated, envelope, receipt, and ledger after bytes are installed; otherwise it restores all exact preimages and revokes the consumed decision
- **AND** recovery is restartable at every generation, wheel, file, directory, rename, ledger, finalization, and lock-holder-death cut point
- **AND** catalog, every handed-off generated file, envelope, receipt, and the terminal ledger event must close in one reviewed repository commit after the earlier reservation commit
- **AND** recovery racing a new apply produces one lock winner and one clean refusal without a ledger fork or mixed tree

#### Scenario: Promotion applies successfully

- **WHEN** explicit apply is requested after review and every gate passes
- **THEN** the resulting tracked catalog, handed-off generated surfaces, private envelope, receipt, and applied ledger event match the preverified complete staged after-tree
- **AND** a repeated preview from the same bundle and selection produces no additional drift
- **AND** publication and deployment remain separate workflows

#### Scenario: An applied promotion is rolled back

- **WHEN** maintainers restore the prior catalog and generated bytes
- **THEN** rollback uses a forward compensating commit that retains prior ledger events and appends `revoked`
- **AND** restoring the earlier catalog bytes cannot make the original decision reusable
- **AND** a second apply of the stale decision fails without writing even when `catalogBefore` bytes match again

### Requirement: Portable scout guidance cannot bypass deterministic authority

OpenOpps SHALL provide one portable agent-primary source-scout skill whose outputs are advisory candidate suggestions accepted only through the same deterministic schemas and isolated validators used by non-agent enumerators. OpenOpps SHALL NOT claim that skill prose confines unrelated tools already authorized in the surrounding harness.

#### Scenario: A supported harness runs the scout skill

- **WHEN** Codex, Cursor, or Grok Build uses the portable scout skill
- **THEN** the skill receives versioned schemas, finite channel budgets, read-only provider and policy inventories, prior-attempt context, and deterministic validation commands
- **AND** every suggested candidate cites a captured bounded provenance receipt
- **AND** the supported handoff passes suggestions into a credential-free subprocess with no database, plugin, Git, deployment, or production mutation handle
- **AND** OpenOpps' filesystem adapter accepts only one explicit new quarantine root and attempts no out-of-root open, without claiming OS-wide account confinement

#### Scenario: Agent output requests authority or violates a contract

- **WHEN** agent output requests mutation, fabricates evidence, exceeds a budget, contains instructions from retrieved content, or fails schema validation
- **THEN** deterministic code rejects or quarantines that output
- **AND** no harness action outside the isolated process can cause OpenOpps to accept or activate the output without the same validator, review, ledger, and repository gates

#### Scenario: Equivalent captured inputs are replayed across harnesses

- **WHEN** supported harnesses emit schema-valid suggestions from the same captured fixtures
- **THEN** the shared validator produces the same canonical candidate identities and dispositions
- **AND** harness-specific prose or completion order does not affect semantic artifact bytes
