## Context and frozen baseline

OpenOpps currently discovers and executes packaged `SourceRecord` instances directly. It has no separate candidate, evidence, quarantine, or promotion contract. Unscoped source resolution also appends persisted sources absent from the packaged catalog, so repository removal alone does not constrain a production run to the current approved catalog.

Barrier B000 freezes the pre-change state at commit `8e3c797b975a1f79844c1906e96c0993d88ab1f1`:

| Surface | Frozen value |
| --- | --- |
| Runtime source records | 2,870 |
| Runtime unique source keys | 2,870 |
| Runtime ownership collisions | 0 |
| Runtime source adapters | 16 |
| Runtime semantic fingerprint | `35655ea36568cf0a05ceb51fb7b757126e96d6fc5402b596c140a322baef10e7` |
| Packaged portfolio records | 2,239 |
| Packaged catalog version | 2 |
| Packaged catalog fingerprint | `c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32` |
| Packaged catalog file | SHA-256 `22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c`, 883,259 bytes |
| Source owner map | SHA-256 `6121e07d3313b561fcde023ac181e8721c7f31a516d4ded693e634dcbe9384ed` over 2,870 sorted canonical `[key,module]` rows plus LF |
| Adapter identity map | SHA-256 `3458c6e6fced46c20f55cba5f57c89489c19744dbebd150fa3f3e23ad3380de4` over 16 sorted canonical `[providerId,module,qualname]` rows plus LF |
| Complete required taxonomy | 895 |
| No standard taxonomy fields | 1,975 |
| Generated web source records | 2,870, exact runtime-key parity |
| Generated web data file | SHA-256 `0dd26acd756d5fc1c65a6654ee2a03d2c9e7264156e7aec3cc146c36187c68e7`, 827,494 bytes |
| Source-policy reference corpus | 695 |
| Independently verified policy-allowed sources | 0 |
| Catalog-declared allowed sources | 7 |
| Policy-blocked sources | 688 |
| Source-policy module | SHA-256 `6a21c11541353524dd4ce73a63a0f20cdbb11d28d02640cbe94fcdeb8e02347f` |
| Source-policy evidence | SHA-256 `0ec5b9ad2897f3a00dbaa07c1c132941d97d169e41668f786c8f58bf11840b22` |
| Source-policy schema | SHA-256 `14b4c2a6ec4b1ade2d0a5860acd24180f6e23b8ee088bff6eeecf17e5a3a0089` |
| Source-policy corpus | SHA-256 `f087deb3bb4644e74cd1786f9309464ceeb3eea8527b25c549d49ad3299a9f6a` |
| Source-policy blocked set | SHA-256 `c10d1ae394bf8d905b6e59c310007ece0048e324e834455824a99335cd3ef014` |

The eight required taxonomy fields are `providerType`, `coverageMode`, `accessType`, `licenseStatus`, `refreshCadence`, `sourceCategory`, `sourceAttribution`, and `inclusionReason`. `sourceYear` remains optional.

At the frozen baseline, 895 records have exactly 8/8 required taxonomy values, 1,975 have 0/8, no record is partially populated, and `sourceYear` is present on zero records.

The 16 frozen adapter IDs are `ashby`, `cncf_landscape`, `consider`, `consider_a16z`, `getro`, `greenhouse_source`, `lever_source`, `public_index_csv`, `public_page`, `ranking_csv`, `sec_company_tickers`, `southparkcommons`, `venturecapitalcareers`, `ventureloop`, `workable_source`, and `ycombinator`. The wheel baseline contains exactly the forced resources `examples/examples.py`, `openopps/providers/sources/data/portfolio_source_catalog.json`, `openopps/providers/sources/data/source_policy_evidence.json`, and `openopps/providers/sources/data/source_policy_evidence.schema.json`; the example resource SHA-256 is `1a649cbedda47d5ef3c8e4c3325bc1e7f6ac89e587031c89ad10d1d3281a4326`.

Frozen source modules contribute: `special` 2,246 records/9 adapters; `getro` 435/1; `consider` 184/2; `public_indexes` 2/1; `landscapes` 1/1; `rankings` 1/1; `sec` 1/1; and `source_utils` 0/0. Whole-wheel bytes are not a stable baseline because ordinary build timestamps may vary; exact embedded resource hashes are the package gate.

The focused before-state command was `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/unit/openopps/test_portfolio_source_catalog.py tests/unit/openopps/test_source_registry.py tests/unit/openopps/test_source_resolution.py tests/unit/openopps/test_source_scope.py tests/unit/openopps/test_source_policy.py tests/unit/openopps/test_settings.py tests/unit/openopps/test_coverage.py tests/unit/openopps/test_route_select.py tests/unit/openopps/test_metrics.py tests/unit/openopps/test_docs_data.py`, with 75 passing tests. This is a frozen regression receipt, not proof for the proposed behavior.

The selected execution defaults relevant to this change are source concurrency 4, source timeout 900 seconds, board/job-route concurrency 16, job-route timeout 180 seconds, provider-probe concurrency 12, Workday concurrency 2, DB batch size 500, HTTP timeout 30 seconds, HTTP maximum connections 40, three retry attempts, and a 3,600-second HTTP JSON cache TTL. Cache stale-on-error and plugin autoload both default to false. Source and job-route freshness skips default to disabled, and the job-route limit defaults to unlimited.

These values are before-state evidence, not permanent hard-coded product counts. Promotion is expected to change counts and fingerprints. Future gates recompute parity and retain the frozen values only as migration and regression evidence. The ignored local `kaggle/openoppsdb.sqlite` is a synthetic example seed and is not production coverage or performance evidence.

## Goals / Non-Goals

**Goals:**

- Discover net-new public source catalogs and supported boards through four finite channels.
- Keep discovery physically, temporally, and authoritatively separate from daily ingestion.
- Preserve bounded canonical evidence and every provenance edge without treating retrieved claims as facts or permission.
- Make normalization, deduplication, liveness, support, policy, promotion, selectors, and accounting deterministic and testable.
- Give supported agent harnesses rich context while keeping their suggestions behind the same isolated strict validator as deterministic enumerators; harness-wide permissions remain outside OpenOpps' enforcement boundary.
- Require reviewed repository promotion before any candidate becomes executable, then admit it only to a later pinned daily run.
- Establish reproducible performance evidence before setting numeric SLOs.
- Preserve local-custom behavior and historical records while deferring retirement until its remaining policy decisions are resolved.

**Non-Goals:**

- An unbounded crawler, broad web index, authenticated scraper, browser automation, anti-bot bypass, or bespoke per-company ATS integration.
- Same-run activation, agent self-approval, rights inference, automatic catalog mutation, or direct production persistence.
- Dynamic plugin loading, dependency installation, remote code execution, or model-selected requests/parsers.
- Public v7, Kaggle, Cloudflare, Vercel, release-archive, or destructive-cleanup changes.
- Permanent-absence or route-retirement implementation before its blocked decisions are resolved.
- A compatibility reader or migration path for candidate artifacts that have never been persisted or published.

## Decisions

### Separate quarantined scout

Discovery runs as a bounded invocation separate from daily ingestion and is designed for a future maintainer-controlled private schedule. This change neither provisions nor activates that schedule. The scout emits canonical candidate and evidence manifests into an explicit private quarantine output and has no write path to operational `sources`, `boards`, `board_providers`, `jobs`, sync-run tables, runtime caches, packaged catalogs, generated data, or public release trees.

A daily snapshot pins the last reviewed catalog and selector identities before network access. Files created by a concurrent scout are neither read nor eligible for that invocation. There is no same-run activation flag.

### Agent-primary coordination with deterministic enforcement

One portable `openopps-source-scout` skill coordinates open-ended discovery across Codex, Cursor, and Grok Build. It receives finite channel profiles, versioned schemas, bounded read-only inventories, prior-attempt summaries, and validation commands. Its output is untrusted candidate suggestion data.

Deterministic OpenOpps code exclusively owns acceptance into quarantine, promotion, and runtime state:

- schema validation and canonicalization;
- URL, source, board-route, and provider identity normalization;
- catalog collision detection and candidate deduplication;
- liveness and provider-support verification;
- operation-specific source-policy evaluation;
- promotion-bundle rendering and exact-selector generation;
- persistence boundaries and exact accounting;
- generated docs, wheel-resource, and repository parity.

Harness instructions improve discovery quality but are advisory, not a confinement or security boundary. A surrounding Codex, Cursor, or Grok session may have independently authorized tools outside OpenOpps' control. The supported workflow passes suggestion data only into a fresh credential-free scout/validator subprocess with no database, runtime cache, plugin registry, or Git/deployment handle. Its application filesystem adapter accepts only the explicit new quarantine root; this is not an OS-wide writable-path guarantee. Agent output cannot make OpenOpps select arbitrary parser code, approve rights, write operational state, or promote a candidate.

### Four bounded discovery channels

The scout coordinates four independent channel families:

1. official catalogs and documentation;
2. public code and datasets;
3. search APIs;
4. targeted employer and ATS queries.

Each channel declares finite query, request, origin, redirect, page, response-byte, candidate, concurrency, retry, parser-depth, and wall-clock budgets. Every retry, redirect, pagination request, and admitted byte consumes the same immutable run budget. Budget exhaustion is a normal terminal result with exact accounting, not an implicit partial success.

Default values are selected from official upstream limits, captured fixtures, and benchmark evidence. Remote input cannot raise a trusted limit. The initial implementation must establish conservative finite defaults before enabling live scouting; no universal latency or throughput SLO is invented in this contract.

### Six explicit trust zones

1. **Maintainer-owned code and configuration.** Versioned profiles, schemas, parser identifiers, origin/query rules, budgets, and rights-policy rules become trusted only through ordinary repository review.
2. **Quarantined scout process.** A fresh credential-free process receives no database, runtime cache, plugin registry, mutation command, or production object. OpenOpps exposes only one application-owned quarantine output capability and its supported code performs no out-of-root opens. This is tested through an instrumented filesystem adapter, not asserted as an OS-account confinement guarantee.
3. **Untrusted network.** Seeds, DNS, redirects, headers, bodies, HTML, JSON, XML, sitemaps, `robots.txt`, `llms.txt`, rate-limit metadata, and errors remain hostile observations.
4. **Optional isolated model extraction.** If later enabled, the extraction subprocess receives only bounded provenance-tagged content and exposes no tools, network, ambient filesystem, credentials, or runtime objects. A normal parent harness is outside this confinement claim; its only supported handoff is strict suggestion data that can nominate facts tied to admitted resource identifiers.
5. **Quarantine artifact.** A bundle is evidence, never configuration, until strict offline verification succeeds. Runtime registries and selectors never read quarantine directories.
6. **Review and promotion.** A later process consumes one immutable bundle digest, validates it, and renders a proposed repository delta. Only a reviewed repository commit can activate configuration for a later run.

Crossing a boundary never upgrades the trust level of the data. HTTP success, robots allowance, an “official” label, upstream license text, catalog metadata, or model confidence cannot establish access, synchronization, redistribution, or publication permission.

### Dedicated connect-time-safe transport

The scout does not reuse the generic runtime HTTP client unchanged. The existing runtime client documents that its pre-connect DNS check is not DNS-rebinding-proof and may continue after resolution failure; those semantics are insufficient for broad discovery.

The dedicated transport:

- permits only trusted-profile HTTPS destinations and validated ports;
- rejects userinfo, fragments, IP literals, localhost names, non-global addresses, mixed public/private DNS answers, DNS failure, unsafe IDNA, IPv6 zone identifiers, and alternate numeric IP encodings;
- connects to an address from the exact validated answer set while preserving the original hostname for TLS SNI and certificate verification;
- revalidates every redirect, caps redirect depth, denies downgrade, and denies cross-origin redirects unless trusted versioned code permits the exact transition;
- uses `trust_env=False`, an empty cookie jar, no `.netrc`, proxies, authentication, client certificates, or caller-supplied arbitrary headers;
- never forwards auth, cookies, caller headers, or request bodies across redirects;
- streams responses under encoded, decoded, per-resource, aggregate, node-count, nesting, and wall-clock limits;
- initially requests identity encoding and rejects unsupported content encodings, archive media types, multipart content, and server-selected filenames;
- records only allowlisted response metadata and sanitized bounded diagnostics.

Implementation uses a public `httpx.AsyncBaseTransport` that owns a public `httpcore.AsyncConnectionPool` configured with a custom `httpcore.AsyncNetworkBackend`. The backend connects the delegate stream to an address from the validated set; HTTPCore retains the original host for HTTP authority, TLS SNI, and certificate verification. The implementation does not mutate HTTPX's private `_pool` attribute or depend on undocumented redirect behavior.

Authenticated APIs are out of scope for the initial scout. If later required, they need a separate OpenSpec design and must not weaken redirect, credential, provenance, or rights isolation.

### Closed parser and provider registry

Scout and promotion processes use a built-in-only registry from the pinned application lock. They do not invoke installed `openopps.plugins` entry points, even when plugin autoload environment settings are present.

A profile selects only trusted enum identifiers. A manifest cannot name a module, class, callable, package, plugin, entry point, executable, URL-loaded parser, template, notebook, or post-processing command. No JavaScript, WASM, browser automation, shell command, or remote code executes.

### Canonical identities and artifacts

Operational execution identity and semantic artifact identity remain distinct:

- `executionId` identifies one operational execution and may be nondeterministic;
- `manifestId` is the SHA-256 of canonical semantic manifest content, excluding the self-referential digest and nondeterministic execution metadata.

Candidate, evidence, selector, promotion, and accounting artifacts reuse the repository's canonical UTF-8 JSON conventions: sorted keys and semantic arrays, duplicate-key rejection, finite numbers, strict schema versions, no BOM, exactly one trailing newline, and recomputed SHA-256 identities. Identical captured inputs reproduce byte-identical semantic artifacts regardless of channel completion order or harness prose.

Hash-bound schemas avoid floating-point ambiguity: counts, sizes, retries, ordinals, elapsed durations, and deadlines use non-negative integers with explicit units such as bytes or milliseconds; wall-clock instants use normalized UTC strings. Negative zero, fractional numeric spellings, NaN, infinity, and numeric coercion are rejected before canonicalization.

Candidate identity includes a normalized public locator, candidate kind, proposed provider or source-adapter identity, and any provider-specific stable token needed for disambiguation. Unresolved normalization or ownership collisions are retained and block promotion; first-wins and last-wins behavior are forbidden.

### Candidate and evidence model

Each candidate carries slots for:

- schema and enumerator versions;
- channel, canonical locator, kind, proposed key, provider, and adapter;
- all eight required taxonomy fields plus per-field evidence and status; values may remain null while quarantined, but promotion requires eight accepted values;
- every provenance resource and locally computed content hash;
- captured observation time, request classification, safe redirect chain, final locator, media type, byte length, and validated connection address;
- robots, Sitemap, ETag, Last-Modified, and rate-limit observations where applicable;
- request, byte, retry, redirect, and budget counters;
- independent liveness, support, taxonomy, and policy axes;
- duplicate and collision evidence;
- prior-attempt and health references;
- terminal quarantine state and bounded reason code.

Locally observed provenance and remotely asserted claims are separate fields. Remote provider names, ownership claims, timestamps, digests, and license statements cannot overwrite local observations or grant rights.

The verification axes are independent:

- liveness: `live`, `inconclusive`, or a future qualifying-absence state;
- support: `supported`, `unsupported`, or `inconclusive`;
- policy: `allowed`, `blocked`, or `unresolved`;
- taxonomy: `complete` or `incomplete`.

Promotion eligibility requires `live + supported + allowed + complete`, exact identity, no unresolved collision, current evidence, and a separately reviewed positive operation-specific policy decision. Inconclusive candidates stay quarantined.

Terminal disposition is monotonic and independent of input order:

1. Any explicit rights denial, permission requirement, credential violation, transport-security violation, or other security failure yields `blocked`.
2. Otherwise, any missing, stale, incomplete, ambiguous, conflicting, or policy-unresolved required evidence yields `inconclusive`.
3. Otherwise, positively rights-closed complete evidence without a supported built-in execution route yields `unsupported`.
4. Only the all-positive combination yields `promotable`.

No evaluator may use first-match, last-match, majority, model confidence, or optimistic defaults. The complete axis cross-product and permutation order are fixture-tested.

### Atomic exact-set quarantine bundles

Bundle construction occurs beneath an owned sibling candidate directory. Resource names are locally selected digest identities; server-controlled filenames are ignored. Resources are written before the canonical manifest, and completion is exposed only after exact offline verification and atomic directory promotion.

The verifier rejects missing or extra files, duplicate or case-fold/Unicode-normalization-colliding paths, absolute paths, traversal, encoded separators, backslashes, symlinks, hard links that violate immutability, devices, sockets, FIFOs, file-identity swaps, unsafe permissions, size mismatches, digest mismatches, noncanonical bytes, unknown schema/parser versions, future-dated evidence, stale evidence, replayed promotion digests, and incomplete terminal accounting. It opens regular files without following symlinks, validates containment, and verifies file identity before and after reading.

Interrupted generation never overwrites an existing completed bundle or exposes a partial bundle as valid. The initial format does not extract archives.

Profiles default to structured field extraction rather than raw-body retention. When a profile requires exact raw evidence, the full bounded response is accumulated only in volatile memory and scanned with a versioned high-confidence credential detector before any durable write or digest enters output. A credential match excludes the bytes, makes the candidate non-promotable, and persists only a bounded reason code plus safe transport metadata. No raw-content digest is persisted for excluded secret-bearing material. For admitted content, `contentSha256` always identifies the exact stored bytes; transformed excerpts use a separate role and digest and never masquerade as byte-for-byte raw provenance. Detection spans streamed chunk boundaries.

### Cache and evidence reuse

The initial scout is isolated from the runtime `HttpCache` and stale-on-error path. An attacker-controlled or stale runtime cache therefore cannot become candidate evidence.

Conditional requests may reuse only a previously exact-verified bounded quarantine resource whose provenance remains within the trusted freshness window. Each reused or not-modified result retains its prior content identity plus the new observation receipt. Promotion rehashes local bytes and does not refetch or substitute live content.

### Deterministic promotion and private approved-ingestion envelope

A promotion bundle contains:

- quarantine manifest digest;
- exact selected-candidate set and digest;
- expected catalog-before fingerprint;
- proposed catalog-after fingerprint and source ownership;
- a discovery-owned supplementary positive-policy decision digest plus read-only v7 policy code/schema/evidence/corpus digests;
- generated docs-data digest;
- expected wheel-resource identities;
- validation receipt plus the digest of a separate maintainer-authored review decision and any later revocation state.

Candidate manifests and scout output schemas forbid `approved`, reviewer, signature, review-receipt, and revocation fields. After the immutable bundle and selection digests are displayed, a maintainer authors a separate canonical `DiscoveryPromotionPolicyDecision` outside the quarantine root. That decision binds the manifest, selected candidates, resources, trusted profile, required operation axes, read-only v7 policy inputs, and catalog-before digests. It supplements but never edits, aliases, or weakens the v7 source-policy format. The promotion tool validates the decision but cannot create a positive decision in scout, verify, preview, CI, or scheduled modes.

The repository review and eventual commit are the activation trust root; a syntactically valid decision or generated receipt is evidence, not sufficient authority. Explicit maintainer invocation is still required for apply, and apply does not claim cryptographic reviewer identity. Copied, candidate-supplied, automatically generated, mismatched, replayed, or revoked decisions fail closed.

Durable replay and revocation state lives at `src/openopps/discovery/data/promotion_decision_ledger.jsonl`. It is canonical hash-chained JSON Lines under `W-DISCOVERY-POLICY`; every event binds its predecessor, decision ID, one composite `promotionIntentDigest`, manifest, selection, policy-input, catalog-before, catalog-after, and promotion digests. Only `decisionId` and `promotionIntentDigest` are global replay keys. Constituent manifest, catalog, policy, resource, and selection digests are equality-bound evidence that may legitimately recur in a different composite intent; they are never globally blacklisted on their own. The only ledger states are `reserved`, `applied`, and `revoked`; transitions are append-only and order-validated. If sufficient reachable repository history is unavailable, shallow, rewritten, or inconsistent with the ledger, reserve/apply fail closed.

All reserve, apply, recovery, and revoke mutations acquire one repository-scoped, nonblocking OS-native exclusive lock at `var/openopps/promotion.lock`. The opened lock path is containment-, symlink-, and inode-validated. Kernel lock ownership is authoritative; owner PID/start/nonce/operation/intent metadata is diagnostic and never permits elapsed-time lock stealing. Contention or ambiguous ownership fails closed. A killed holder releases the kernel lock; the next holder must acquire it normally, validate or replace stale metadata, and resolve any journal before new work. After every acquisition, the process re-reads and compare-and-swaps the current `HEAD`, catalog fingerprint, ledger tail/hash chain, active reservation, complete recovery-journal set, and owned-path cleanliness. A nonterminal reservation locks its exact HEAD/catalog-before tuple against both same- and different-intent reservations until applied or revoked.

Promotion performs three separately reviewable phases:

1. `preview` is non-mutating; two previews over identical inputs must be byte-identical.
2. Explicit `reserve`, under the repository lock and fresh compare-and-swap, appends only a `reserved` event. The maintainer reviews and commits that ledger-only change before apply. A reserved decision is ineligible if current or reachable repository history already records the same `decisionId` or `promotionIntentDigest` as applied or revoked, or another nonterminal reservation owns the same HEAD/catalog-before tuple.
3. Before terminal apply, the tool renders the complete proposed repository after-tree into a private staging tree: catalog, every handed-off generated file, private envelope, receipt, and candidate `applied` ledger bytes. It runs the canonical generator twice against that staged tree and requires byte identity, then builds a candidate wheel from the staged tree and verifies every embedded resource and receipt identity. Generator or wheel failure occurs before repository mutation. Explicit `apply` then acquires the repository lock, revalidates the committed reservation, staged-input digests, HEAD/catalog/ledger compare-and-swap, complete private-envelope contract, history, journal set, and clean owned paths. It writes and fsyncs `var/openopps/promotion-recovery/<promotionIntentDigest>/`, containing the lock nonce, intent/reservation/HEAD identities, complete owned path set including handed-off generated bytes, exact before/after existence, modes, bytes and digests, write order, and `prepared` phase. The recovery root and every component must be owned, non-symlinked, and containment-validated. Apply advances the journal to `applying`, atomically replaces each owned file, verifies catalog/generated/envelope/receipt/ledger closure, fsyncs the final state, marks `finalizing`, and only then removes the journal. A second stale apply fails without writing.

Every mutating promotion entry point holds the repository lock and resolves the complete journal set before accepting new work. Deterministic recovery finishes only an all-after-bytes application with exact catalog/generated/envelope/receipt/ledger closure; otherwise it restores every exact preimage, appends `revoked`, and verifies restored closure. Recovery is restartable at every staged generation, wheel, file, directory, rename, ledger, and lock-holder-death cut point and never silently retries the promotion. Recovery racing a new apply yields one lock winner and one clean refusal. The applied catalog, all handed-off generated bytes, envelope, receipt, and `applied` ledger event must enter repository history in one reviewed commit; governance validation rejects split or partial application commits. The earlier reservation remains its own commit; the candidate wheel is pre-apply validation evidence, not a tracked mutation.

Rollback is a forward compensating commit: it restores catalog/generated bytes, retains all prior ledger events, and appends `revoked`. A whole-commit revert that removes ledger history fails governance validation. Apply and validation inspect both the current ledger and reachable Git history, so restoring prior catalog bytes cannot make an old decision reusable. History rewrite is outside this workflow and cannot be used as rollback.

Promotion fails if the current catalog fingerprint differs from `catalogBefore`, any evidence is stale or replayed, a collision or taxonomy deficit remains, policy is not positively closed for required operations, generation drifts, or wheel resources disagree. Preview is the default and writes no repository files. Explicit apply remains a separate maintainer action and does not stage, commit, push, publish, deploy, sync, probe, or mutate SQLite.

Production ingestion consumes a private `ApprovedIngestionSelectorEnvelope` bound to the catalog content/tree digest, runtime catalog fingerprint, sorted source-key digest, read-only v7 policy-input digests, supplementary discovery-policy digest, and promotion digest. It is not the v7 public `SourceSelector` and cannot be substituted for one. The eventual checkout commit SHA is recorded separately in the post-checkout invocation attestation, avoiding a tracked selector that self-references its containing commit. This preserves ordinary explicitly selected local-custom behavior while excluding persisted-only and quarantined rows from scheduled runs without deleting or reclassifying them.

A candidate becomes daily-eligible only after its reviewed repository change and selector update are committed. A scout output directory is never an ingestion input.

### Exact accounting contracts

Every count is over a declared exact-set identity, and every term is mutually exclusive.

Per-channel operation accounting:

```text
plannedOperations
  = succeeded
  + blocked
  + rateLimited
  + timedOut
  + failed
  + cancelled
  + unstarted
```

`cancelled` means work that started but was interrupted. `unstarted` means planned work never launched because of cancellation, fail-fast policy, deadline, or budget exhaustion. `aborted` is a run-level state only and never replaces a source, route, candidate, or operation terminal class.

Each channel also conserves one immutable resource ledger: reserved/in-flight plus consumed plus remaining request units equals the configured request budget; every response, transport failure, timeout, cancellation, retry, redirect, and pagination hop maps to one attempt outcome; admitted bytes plus remaining byte capacity equals the applicable per-resource and aggregate limits. A terminal channel has exactly one channel state and enumerates unfinished work explicitly. Hard process death leaves the run nonterminal until recovery materializes cancelled and unstarted denominator members; it cannot emit a terminal completeness attestation early.

Scout accounting:

```text
observedCandidateOccurrences
  = invalidOccurrences + normalizedOccurrences

normalizedOccurrences
  = duplicateOccurrences + uniqueCandidates

uniqueCandidates
  = alreadyApproved + quarantinedCandidates

quarantinedCandidates
  = promotable + blocked + unsupported + inconclusive
```

Daily source accounting:

```text
plannedSources
  = succeeded
  + failed
  + timedOut
  + freshSkipped
  + policyBlocked
  + rateLimited
  + cancelled
  + unstarted
```

A complete source attestation requires `failed = timedOut = policyBlocked = rateLimited = cancelled = unstarted = 0`. Fresh skips are valid only when their evidence is bound to the pinned catalog and invocation freshness policy.

Daily route accounting, over the pre-dedup exact set of observed job-capable route entries:

```text
plannedRoutes
  = succeeded
  + failed
  + timedOut
  + freshSkipped
  + deferred
  + duplicateSkipped
  + missingMetadata
  + policyBlocked
  + rateLimited
  + cancelled
  + unstarted
```

A complete route attestation requires `failed = timedOut = deferred = missingMetadata = policyBlocked = rateLimited = cancelled = unstarted = 0` and `authoritativeSucceeded = succeeded`. Rate-limit exhaustion is `rateLimited`, not generic success or freshness skip. A degraded snapshot uses a separate typed policy decision and is never labeled complete.

Every `duplicateSkipped` route names exactly one canonical representative. That representative is either authoritative `succeeded` or an authoritative `freshSkipped` whose evidence binds the pinned envelope, catalog, invocation freshness policy, and representative identity. No duplicate group may contain only skipped members. Complete route evidence additionally requires `authoritativeFreshSkipped = freshSkipped`.

Candidate processing state and evaluation disposition are separate. Processing is `discovered` before evaluation and `evaluated` afterward. Evaluation disposition is exactly `already_approved`, `promotable`, `blocked`, `unsupported`, or `inconclusive`; `eligible_for_review` is derived if and only if disposition is `promotable`, while `rejected` is a review outcome for `blocked` or `unsupported`. Supersession is an orthogonal `supersededBy` evidence edge and never removes either unique identity from its declared denominator.

## Architecture

```text
Approved catalog + policy/profile digests
                 │
                 ▼
      portable agent scout skill
                 │ suggestions only
       ┌─────────┼──────────┬───────────┐
       ▼         ▼          ▼           ▼
   official   code/data   search API   employer/ATS
       └───────── bounded receipts ─────┘
                 │
                 ▼
       deterministic normalize/dedupe
                 │
                 ▼
     exact content-addressed quarantine
                 │
       ┌─────────┼──────────┐
       ▼         ▼          ▼
   liveness   support     policy/taxonomy
       └─────────┼──────────┘
                 ▼
       deterministic promotion preview
                 │ reviewed later commit
                 ▼
 approved catalog + generated data + selector
                 │ next process/run only
                 ▼
    sources → routes → authoritative jobs
```

## Performance evidence contract

The first benchmark wave creates a deterministic corpus derived from the frozen 2,870-source catalog and all 16 adapter identities. It measures normalization and schema-validation time, deduplication, catalog-collision audit, policy evaluation, promotion rendering, peak resident memory, candidate and receipt bytes, relevant SQLite statement count, median, and p95 across repeated controlled runs. Evidence records toolchain, platform, CPU, and fixture digests.

The initial result is evidence, not an SLO. A later ADR may adopt thresholds only after documenting representativeness, variance, headroom, and CI stability. Until then, CI enforces finite configuration, deterministic bytes, exact accounting, and no unbounded code path.

## Standards and current-practice alignment

- The scout implements the [Robots Exclusion Protocol in RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) and the [Sitemaps protocol](https://www.sitemaps.org/protocol.html) as bounded access observations. Robots network/`5xx` unreachability means complete disallow; successful rules are cached for at most 24 hours; the parser accepts at least the RFC's 500-KiB minimum within the stricter whole-run budget. A security-rejected cross-origin robots redirect also fails closed rather than weakening the destination policy. Sitemap files and indexes remain far below the protocol's 50,000-entry/50-MB maxima under trusted local budgets. Neither protocol grants legal or publication rights.
- ETag, Last-Modified, conditional requests, and bounded `Retry-After` handling follow [RFC 9110 HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html).
- Redirect denial/revalidation, trusted-origin allowlisting, all-address DNS checks, and DNS-pinning defenses follow the [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html). OpenOpps adds connect-time address pinning because a preflight DNS check alone leaves a time-of-check/time-of-use gap.
- The transport design uses the documented [HTTPX custom transport API](https://www.python-httpx.org/advanced/transports/) and [HTTPCore custom network backend API](https://www.encode.io/httpcore/network-backends/). `trust_env=False` follows [HTTPX environment configuration guidance](https://www.python-httpx.org/environment_variables/) to prevent ambient proxy and certificate-path inheritance.
- Untrusted models use Pydantic's current [strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) plus `extra="forbid"` from [ConfigDict](https://docs.pydantic.dev/latest/api/config/), with committed generated JSON Schemas and byte-equality checks.
- [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785.html) is an interoperability reference, not a claimed wire contract. Existing OpenOpps artifacts deliberately use repository-defined canonical JSON with a trailing newline and Python-compatible number/string serialization. Discovery reuses that contract rather than silently introducing a second canonicalizer; any future JCS migration requires a versioned format and ADR.
- Metrics follow the current [OpenTelemetry semantic-convention discipline](https://opentelemetry.io/docs/specs/semconv/how-to-write-conventions/) by preferring established namespaces and bounded low-cardinality attributes.
- Public offline CI follows GitHub's [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use): explicit read-only token permissions, immutable action pins, no persisted checkout credentials, finite timeouts, no live scout network access, and only committed sanitized redistribution-safe fixtures. Unsanitized bundles are never GitHub Actions artifacts.

## Failure and rollback rules

- A transport-policy, credential, containment, canonicalization, digest, parser-safety, plugin, instruction-boundary, or rights violation aborts the channel or promotion and emits no promotable output.
- A required resource failure, timeout, unsafe redirect, unsupported representation, parse ambiguity, or exhausted budget makes the candidate incomplete. Remote input cannot downgrade a required resource to optional.
- DNS failure is a security failure, never permission to connect.
- No stale cache, prior bundle, partial manifest, inferred default, or model confidence substitutes for missing evidence.
- Identity collisions and conflicting canonicalization fail closed; no first-wins or last-wins resolution exists.
- Scout failure leaves runtime SQLite, runtime cache, catalogs, policy evidence, generated artifacts, and plugin state unchanged outside the explicit new quarantine candidate directory.
- Promotion failure before reservation writes no repository delta or review receipt. After a committed reservation, failure consumes that decision and requires a fresh decision rather than deleting ledger history.
- Promotion never activates the current process. Before merge, rollback discards only uncommitted catalog proposal bytes while preserving any committed reservation. After merge, rollback is a forward compensating commit followed by deterministic regeneration and validation; it retains `reserved` and `applied` ledger events and appends `revoked`.
- Reverted promotion digests remain revoked and require a fresh bundle and review before reconsideration.
- Candidate, route, board, and approved-catalog history is not destructively deleted by rollback.

## Compatibility

- `BOARD_SOURCE_CATALOG` and the packaged portfolio catalog remain the approved source SSOT.
- Existing explicit local-custom source behavior remains available outside selector-bound scheduled execution.
- Candidate artifacts are additive and need no legacy reader or migration path.
- Existing v7 source-policy code, schema, evidence, corpus, and public `SourceSelector` are read/hash-only and remain fail-closed; this change does not reinterpret catalog declarations as independent permission.
- `DiscoveryPromotionPolicyDecision`, the promotion ledger, and `ApprovedIngestionSelectorEnvelope` are discovery-owned private contracts and must not be imported as v7 public release selectors or policy records.
- Public v7 artifact and deployment formats remain owned by `production-hardening-static-data-v7` and are not changed here.
- Retirement storage changes wait for the unresolved absence and ownership decision.

## Evidence layers

Completion claims identify the strongest layer actually proven:

1. **Contract:** OpenSpec and schema validation.
2. **Source:** models, canonicalization, enumerators, validators, and static inspection.
3. **Focused tests:** unit, property, adversarial, integration, and replay fixtures.
4. **Generated repository:** deterministic second generation and exact diff.
5. **Build/package:** web build where affected, wheel contents, and installed-wheel smoke.
6. **Clean checkout/CI:** pinned toolchain and exact-SHA remote gates.
7. **Captured live scout:** bounded read-only external discovery with artifact readback.
8. **Daily runtime:** exact selector, conserved accounting, and durable authoritative runs.
9. **Publication:** separately authorized Kaggle, Cloudflare, release, or deployment mutation with exact readback.

Dispatch or worker completion proves none of the downstream layers.

## Exclusive writers and merge barriers

| Lock | Exclusive paths or responsibility |
| --- | --- |
| `W-OS` | `openspec/changes/bounded-quarantined-source-discovery/**` |
| `W-T-CANON` | canonical artifact red/green test files |
| `W-T-EVAL` | identity, policy, lifecycle, promotion, and accounting test files |
| `W-T-NET` | transport and process-isolation test files |
| `W-CONTRACT` | discovery models, schemas, canonical encoding, shared identity rules |
| `W-HTTP` | dedicated scout transport and request-policy primitives |
| `W-CHANNEL-OFFICIAL` | official catalog/document enumerator modules and tests |
| `W-CHANNEL-CODE` | public code/dataset enumerator modules and tests |
| `W-CHANNEL-SEARCH` | search enumerator modules and tests |
| `W-CHANNEL-ATS` | employer/ATS enumerator modules and tests |
| `W-NORMALIZE` | candidate normalization, deduplication, collision, and taxonomy modules |
| `W-LIVENESS` | candidate liveness modules and fixtures |
| `W-SUPPORT` | provider/source support-classification modules and fixtures |
| `W-EVALUATION-JOIN` | final disposition, accounting closure, manifest join, and reconciliation |
| `W-DB` | `models.py`, `storage.py`, migrations, operational accounting |
| `W-CLI` | CLI command tree and semantic help |
| `W-CATALOG` | packaged sources, ownership, promotion renderer |
| `W-DISCOVERY-POLICY` | supplementary discovery policy decisions and `src/openopps/discovery/data/promotion_decision_ledger.jsonl` only |
| `W-FIXTURE` | sanitized discovery/adversarial fixtures and benchmark corpus |
| `W-BUNDLE` | quarantine bundle reader/writer implementation |
| `W-SETTINGS` | discovery-only Pydantic settings and environment parsing |
| `W-DOCS-GENERATED` | discovery-owned docs/schema projections only after `XV7` handoff for any shared generated path |
| `W-PACKAGE` | private temporary candidate-wheel build and embedded-resource verification |
| `W-SKILL` | portable source-scout skill, projections, and evals |
| `W-OBS` | discovery metrics, benchmark harness, and ADR |
| `W-SHARED-DELIVERY` | `Justfile`, public workflows, and shared generated data only after `XV7` handoff |
| `W-XV7-GOVERNANCE` | exact cross-change handoff record and digest evidence in the two OpenSpec change roots |
| `W-DOCS` | README, web MDX, and nested `AGENTS.md` files |
| `W-GIT` | index, commits, pushes, and remote verification |

Same-lock tasks run sequentially. Independent channel, fixture, verifier, and review files run in parallel. With four available slots, orchestration uses rolling root-plus-three tranches and closes every dispatch before opening the dependent barrier.

The active `production-hardening-static-data-v7` owner retains ingestion/providers, cache/storage/migrations, source-policy module/schema/evidence, public `SourceSelector`, Kaggle/notebook, shared generated data, `Justfile`, and public workflow writes. `XV7` closes only after that change archives or explicitly records a path-level handoff. Before `XV7`, this change may only read and hash those surfaces; it never writes ingestion, provider, cache, storage, migration, Kaggle, or v7 policy/public-selector files.

## Alternatives considered

- **Inline discovery during the daily snapshot:** rejected because uncertain search latency, quotas, false positives, and rights review would change a run after its denominator was chosen.
- **Pure agent discovery and promotion:** rejected because model behavior cannot enforce schemas, rights, identity, budgets, filesystem safety, or activation boundaries.
- **Only deterministic enumerators:** rejected because official catalogs, repositories, datasets, and employer/provider surfaces are heterogeneous and benefit from bounded agent-assisted exploration.
- **Reuse the generic runtime HTTP client:** rejected because it may instantiate the runtime SQLite cache, permit stale-on-error behavior, load ambient configuration, and does not pin DNS validation to the actual connection.
- **Reuse public v7 release manifests for quarantine:** rejected because candidate evidence is private, short-lived, incomplete, and not a publication artifact; v7 ownership remains separate.
- **Auto-open a pull request or auto-apply eligible candidates:** rejected because positive rights review, catalog ownership, and exact human selection are independent authority gates.
- **Adopt RFC 8785 silently:** rejected because current OpenOpps artifacts already have a versioned canonical JSON convention with different newline and serialization semantics.
- **Delete stored-only rows to enforce the selector:** rejected because those rows may be explicit local custom sources and the ownership distinction is not yet evidenced.

## Risks / Trade-offs

- **Custom transport code can drift from HTTPX/HTTPCore releases.** → Use only documented public transport/backend interfaces, pin through `uv.lock`, add contract tests for both success and hostile paths, and re-audit on dependency upgrades.
- **Broad public discovery increases SSRF and parser attack surface.** → Use a separate credential-free process, connect-time address pinning, closed profiles/parsers, strict streaming budgets, captured hostile fixtures, and no operational objects.
- **Bounded evidence may omit useful context.** → Preserve exact admitted bytes for profile-approved resource roles, store hashes and structured provenance for all observations, mark oversize/unsupported responses incomplete, and never claim exhaustive discovery.
- **Private evidence retention can still carry sensitive or copyrighted material.** → Reject credential-like content, store only profile-permitted bounded resources, keep artifacts private with reviewed retention, and make publication a separate positive-rights decision.
- **Local review files cannot prove a human identity cryptographically.** → Forbid review state in quarantine, require a separate maintainer-authored digest-bound decision and explicit apply invocation, treat the receipt as evidence rather than authority, and make repository review/commit the activation trust root.
- **Fail-closed policy currently leaves no independently verified allowed source.** → Treat this as an expected promotion blocker, not a reason to weaken policy; scouting and offline evaluation remain useful while rights review proceeds separately.
- **A large hyperfine graph can create coordination overhead.** → Use writer locks, dependency barriers, rolling root-plus-three tranches, deterministic fixtures, and explicit dispatch accounting.
- **Exact selectors create a second identity surface.** → Derive selectors from the approved catalog and policy in one deterministic path, bind every digest, and reject drift before network work.
- **Cross-harness agent suggestions may vary.** → Hash semantic input fixtures, require strict provenance-bound output, normalize through one library, and compare canonical accepted results rather than prose.
- **Initial benchmark measurements may be noisy.** → Record environment and fixture digests, repeat runs, publish variance, and defer numeric gates until an ADR establishes stability.

## Migration Plan

1. Land the archived prerequisite and this validated OpenSpec contract without changing runtime behavior.
2. Add strict models, schemas, canonicalization, hostile fixtures, and the dedicated transport behind library-only entry points.
3. Add deterministic channel replay, normalization, evaluation, and exact quarantine verification; prove zero runtime writes.
4. Add offline advanced scout/verifier commands and the portable skill, still with no promotion apply or schedule activation.
5. Add dry-run promotion, discovery-owned positive policy closure, durable decision-ledger replay protection, and the private approved-ingestion selector. Any shared generated-data or delivery write waits at `XV7`.
6. Add selector-bound scheduled ingestion as an explicit advanced path while preserving ordinary local-custom behavior.
7. Add metrics, benchmark evidence, docs, nested instructions, Justfile, and offline CI gates.
8. Commit and push atomically, then prove exact-SHA CI and read-only deployment smoke.
9. Keep public CI offline. A later separately authorized maintainer-controlled private scheduler may run the live scout under finite reviewed profiles and private artifact readback; this change supplies only a scheduler-agnostic runbook/template and does not provision or activate it. Kaggle, Cloudflare, publication, and retirement remain separate future gates.

Rollback is additive: before merge, discard uncommitted catalog proposal bytes but preserve any committed reservation. After merge, create a forward compensating commit that regenerates and restores the previous envelope/catalog bytes, retains `reserved` and `applied` ledger events, and appends `revoked`. A whole-promotion revert that deletes ledger events fails validation. No rollback rewrites history or mutates operational data.

## Open Questions

- Which conservative numeric defaults should each trusted channel profile use? Resolve from official service limits, captured fixtures, and benchmark evidence in `H301`; remote content never sets them.
- Which repository-owned portable skill SSOT and generated harness projections match the maintainer's existing agent-stack conventions? Resolve read-only in `S701` before adding files or running sync previews.
- Which public no-auth search APIs remain viable under documented terms and quotas? Unsupported or credentialed channels report `blocked`; there is no fallback scraper.
- Which candidates can receive independently reviewed positive access/license/redistribution/sync/publication decisions? Until evidence exists, their policy axis stays `unresolved` or `blocked`.
- What qualifying absence signals, minimum horizon, and persisted package-owned/local-custom ownership evidence permit route retirement? This requires a future `route-first-reversible-retirement` OpenSpec change and has no task or implementation branch here.
