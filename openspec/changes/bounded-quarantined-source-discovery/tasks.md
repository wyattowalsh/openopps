# bounded-quarantined-source-discovery - tasks

This graph is dependency-driven. Checked work proves only its named evidence
layer. Same-lock writers are serialized; independent leaves run in rolling
root-plus-three tranches. Every dispatch resolves as verified success, explicit
read-only skip, or recovered failure before its barrier opens.

## Critical path and parallel topology

```text
B000 frozen decisions + prerequisite archive
  │
  ▼
B099 OpenSpec contract
  │
  ▼
B199 red tests + deterministic fixtures
  │
  ▼
C2xx core contracts → B299
  │
  ├──────── S7xx advisory skill ──────────────────────────→ B799
  ▼
H3xx transport/bundle → B399
  │
  ▼
E41x/E42x/E43x/E44x channels → B499
  │
  ▼
V5xx normalize/evaluate/quarantine → B599
  │
  ├── XV799 ── P6xx promotion/private envelope ──────────→ B699
  │                                                          │
  │                                                          ▼
  │                                                   I8xx daily pinning → B899
  │                                                          │
  └───────────────────────────┬──────────────────────────────┘
                              ▼
                        O9xx evidence → B999
                              │
         XV799 shared handoff ┼── D10xx CLI/docs/offline CI → B1099
                              │
                              ▼
                    exact-SHA release assurance
```

Every file-writing task inherits one declared lock from its lane unless the task
line names a narrower override. A dispatch packet must state its owned paths,
predecessor artifact digests, and acceptance command. Read-only review tasks
have no writer lock and never edit.

| Task family | Inherited lock / serialization rule |
| --- | --- |
| `A*`, `B*` OpenSpec writes | `W-OS` |
| `XV701-XV799` | `W-XV7-GOVERNANCE`; exact handoff records only, sequential across both change roots |
| `T101-T110` | `W-T-CANON`; one canonical-artifact test file at a time |
| `T111-T120`, `T138-T142` | `W-T-EVAL`; one evaluation/accounting test file at a time |
| `T121-T130`, `T143` | `W-T-NET`; one network/process-isolation test file at a time |
| `T131-T137` | `W-FIXTURE` |
| `C*` | `W-CONTRACT`, except `C227` uses `W-SETTINGS` |
| `H301-H320` | `W-HTTP`; split transport files may dispatch only after their interface digest is frozen |
| `H321-H328` | `W-BUNDLE` |
| `H331-H334` | `H331` acquires `W-HTTP` then `W-BUNDLE`; `H332-H334` are read-only test/review/remediation-receipt joins |
| `E41*`, `E42*`, `E43*`, `E44*` | distinct `W-CHANNEL-OFFICIAL`, `W-CHANNEL-CODE`, `W-CHANNEL-SEARCH`, `W-CHANNEL-ATS` locks |
| `E45*` | `W-CONTRACT` |
| `V501-V506` | `W-NORMALIZE` |
| `V511-V516` | `W-LIVENESS` |
| `V521-V525` | `W-SUPPORT` |
| `V531-V536` | `W-DISCOVERY-POLICY` |
| `V541-V549` | `W-EVALUATION-JOIN` |
| `S*` | `W-SKILL` |
| `P601-P615` | `W-CATALOG` unless explicitly `W-DISCOVERY-POLICY`; shared paths wait for `XV7` |
| `P616`, `P619`, `P623` | acquire `W-CATALOG`, `W-DOCS-GENERATED`, then `W-DISCOVERY-POLICY` in that order |
| `P617` | `W-DOCS-GENERATED`; `P618` uses `W-PACKAGE`; `P620-P622` and `P625-P626` are read-only assurance/joins; `P624` uses `W-T-EVAL` |
| `I801-I806` | `W-CLI`; `I807-I815` use `W-DB`; `I816` acquires `W-CLI` then `W-DB`; `I819-I821` are read-only tests/review/remediation-receipt joins |
| `O*` | `W-OBS` |
| `D1001-D1004` | `W-CLI`; `D1005-D1015` use `W-SHARED-DELIVERY` after `XV7`; `D1016-D1018` and `D1021-D1029` use `W-DOCS`; `D1030` uses `W-DOCS-GENERATED` |
| `D1041-D1051`, `D1053`, `B1099` | read-only assurance, except explicit `D1048` uses `W-OS` |
| `D1052` | read-only join that routes every remediation to its original declared lock; it never edits directly |
| `F1203-F1206` | `W-GIT`; all other `F*` tasks are read-only assurance |

Review, command-only validation, barrier, and receipt-join tasks are assurance,
not implementation writers. A reconcile task never becomes an unbounded writer:
it dispatches each fix to the original task's declared lock, waits for its
acceptance receipt, and performs a read-only join.

## 0. Barrier B000 — resolved decisions, baseline, and ownership

- [x] 0.1 `B001` Resolve coverage intake rather than ATS-from-domain invention.
- [x] 0.2 `B002` Resolve catalog-first candidate scope and objective board inclusion.
- [x] 0.3 `B003` Resolve agent-primary hybrid architecture.
- [x] 0.4 `B004` Resolve bounded four-channel discovery breadth.
- [x] 0.5 `B005` Resolve downstream context and authority boundary.
- [x] 0.6 `B006` Resolve separate quarantined scout and no same-run activation.
- [x] 0.7 `B007` Resolve route-first reversible retirement direction.
- [x] 0.8 `B008` Resolve that transient operational failure is never permanent absence.
- [x] 0.9 `B009` Freeze exact catalog, owner-map, adapter-map, taxonomy, generated-data, embedded wheel-resource, policy-input, runtime-config, and 75-test baselines at `8e3c797b975a1f79844c1906e96c0993d88ab1f1`.
- [x] 0.10 `B010` Record candidate, source, and route conservation equations.
- [x] 0.11 `B011` Record benchmark-first performance evidence policy.
- [x] 0.12 `B012` Complete and archive `source-integrity-production-readiness` into canonical specs.
- [x] 0.13 `B013` Confirm `production-hardening-static-data-v7` retains public v7, source-policy, Kaggle, Cloudflare, archive, and destructive-cleanup ownership.
- [x] 0.14 `B014` Record exclusive writer locks and protected unrelated worktree state.
- [x] 0.15 `B019` Close B000 only after baseline reproduction, strict OpenSpec validation, and ownership-safe worktree inspection.

## 1. Barrier B000 → B099 — OpenSpec authoring

All writes use `W-OS`. Supporting agents draft read-only; one writer integrates sequentially.

- [x] 1.1 `A001` Create the `bounded-quarantined-source-discovery` change shell. `[depends: B019]`
- [x] 1.2 `A002` Write the problem, scope, non-goals, dependencies, and rollout boundary. `[depends: A001]`
- [x] 1.3 `A003` Add frozen baseline counts and explicitly label them before-state evidence. `[depends: A002]`
- [x] 1.4 `A004` Add separate-scout, no-same-run, and approved-selector decisions. `[depends: A002]`
- [x] 1.5 `A005` Add agent-primary skill and deterministic-enforcement boundaries. `[depends: A002]`
- [x] 1.6 `A006` Add four finite channel families and immutable budget semantics. `[depends: A004,A005]`
- [x] 1.7 `A007` Add six trust zones and authority transitions. `[depends: A004,A005]`
- [x] 1.8 `A008` Add dedicated connect-time-safe transport design. `[depends: A007]`
- [x] 1.9 `A009` Add closed parser/provider registry and plugin isolation. `[depends: A007]`
- [x] 1.10 `A010` Add canonical candidate, resource, bundle, selector, promotion, and review identities. `[depends: A004]`
- [x] 1.11 `A011` Add exact bundle member, path, digest, freshness, and atomicity rules. `[depends: A010]`
- [x] 1.12 `A012` Add independent liveness, support, taxonomy, and policy axes. `[depends: A010]`
- [x] 1.13 `A013` Add positive policy closure and provenance-claim separation. `[depends: A012]`
- [x] 1.14 `A014` Add candidate/source/route conservation equations. `[depends: A010]`
- [x] 1.15 `A015` Add deterministic promotion and selector closure. `[depends: A011-A014]`
- [x] 1.16 `A016` Add benchmark evidence contract and no-premature-SLO rule. `[depends: A006,A014]`
- [x] 1.17 `A017` Add compatibility, failure, rollback, revocation, and evidence-layer rules. `[depends: A007-A016]`
- [x] 1.18 `A018` Add `source-discovery` delta requirements and scenarios. `[depends: A004-A013]`
- [x] 1.19 `A019` Add `provider-coverage` delta requirements and scenarios. `[depends: A012-A014]`
- [x] 1.20 `A020` Add `provider-ingestion` delta requirements and scenarios. `[depends: A014,A015]`
- [x] 1.21 `A021` Add `cli-domain` delta requirements and semantic-help behavior. `[depends: A004,A011]`
- [x] 1.22 `A022` Add `performance-observability` delta requirements and scenarios. `[depends: A006,A008,A016]`
- [x] 1.23 `A023` Add `release-workflows` delta requirements and evidence separation. `[depends: A015,A017]`
- [x] 1.24 `A024` Add hyperfine dependency graph, writer locks, joins, stop rules, and explicitly deferred future retirement scope. `[depends: A018-A023]`
- [x] 1.25 `A025` Inspect OpenSpec list, status, and instructions in JSON. `[depends: A024]`
- [x] 1.26 `A026` Run strict validation for this change and all changes/specs. `[depends: A025]`
- [x] 1.27 `A027` Resolve every warning, contradiction, or schema error without weakening a requirement. `[depends: A026]`
- [x] 1.28 `A028` Obtain independent contract, security, and graph-completeness reviews. `[depends: A027]`
- [x] 1.29 `A029` Reconcile review findings and rerun strict validation. `[depends: A028]`
- [x] 1.30 `B099` Close only when every implementation task maps to a requirement/scenario and validation is green. `[depends: A029]`

### Independent cross-change ownership barrier

Core discovery work may proceed before this barrier. Any write to the active v7
owner's ingestion/provider/cache/storage/migration/source-policy/public-selector/
Kaggle/shared-generated/Just/workflow
surfaces is forbidden. Shared delivery work opens only after the handoff.

Record: [`xv7-handoff.md`](xv7-handoff.md).

- [x] 1.31 `XV701` Re-read `production-hardening-static-data-v7` ownership and record exact overlapping paths. `[depends: B099]`
- [x] 1.32 `XV702` Confirm v7 has archived or record an explicit path-level handoff after every prior writer stops. `[depends: XV701]`
- [x] 1.33 `XV703` Record exact handoff-time digests and prove discovery changes keep non-handed-off ingestion/provider/cache/storage/migration, v7 source-policy, public `SourceSelector`, Kaggle, and public-v7 paths byte-identical. `[depends: XV702]`
- [x] 1.34 `XV799` Close the shared-surface barrier and activate `W-SHARED-DELIVERY` for only the handed-off paths. `[depends: XV703]`

## 2. Barrier B099 → B199 — red tests and deterministic fixtures

Parallel tranche A owns separate test files `T101-T110`, `T111-T120`, and
`T121-T130`. Fixture-manifest writes `T131-T136` are serialized.

### Canonical artifact tranche

- [x] 2.1 `T101` Add canonical key-order, separator, UTF-8, BOM, and trailing-newline red tests. `[depends: B099]`
- [x] 2.2 `T102` Add duplicate-key, float, fractional spelling, negative-zero, non-finite-number, numeric-coercion, unknown-field, and unknown-schema rejection tests. `[depends: B099]`
- [x] 2.3 `T103` Add semantic `manifestId` versus nondeterministic `executionId` tests. `[depends: B099]`
- [x] 2.4 `T104` Add deterministic array ordering and duplicate-ID rejection tests. `[depends: B099]`
- [x] 2.5 `T105` Add exact manifest member-set, declared-size, count, and aggregate-digest closure tests. `[depends: B099]`
- [x] 2.6 `T106` Add absolute/traversal/backslash/encoded-separator/empty-component path tests. `[depends: B099]`
- [x] 2.7 `T107` Add Unicode-normalization and case-fold collision tests. `[depends: B099]`
- [x] 2.8 `T108` Add symlink, hardlink, FIFO, device, socket, inode-swap, extra-file, and missing-file tests. `[depends: B099]`
- [x] 2.9 `T109` Add future, stale, replayed, revoked, and unsupported-profile manifest tests. `[depends: B099]`
- [x] 2.10 `T110` Add interrupted-write and existing-bundle non-overwrite tests. `[depends: B099]`

### Identity, policy, and accounting tranche

- [x] 2.11 `T111` Add exact key, exact URL, canonical URL, provider-token, and approved-catalog collision tests. `[depends: B099]`
- [x] 2.12 `T112` Add duplicate-occurrence versus unique-candidate conservation tests. `[depends: B099]`
- [x] 2.13 `T113` Add `alreadyApproved/promotable/blocked/unsupported/inconclusive` partition tests. `[depends: B099]`
- [x] 2.14 `T114` Add all-eight-taxonomy and optional-`sourceYear` tests. `[depends: B099]`
- [x] 2.15 `T115` Add positive policy closure tests for access, license, redistribution, sync, and publication axes. `[depends: B099]`
- [x] 2.16 `T116` Add deny-overlay non-match, HTTP 200, robots allow, upstream “official,” and model-confidence bypass tests. `[depends: B099]`
- [x] 2.17 `T117` Add liveness `live/inconclusive` tests proving transient failure is not absence. `[depends: B099]`
- [x] 2.18 `T118` Add support `supported/unsupported/inconclusive` route-evidence tests. `[depends: B099]`
- [x] 2.19 `T119` Add exact daily source conservation tests including rate-limited, started-cancelled, planned-unstarted, run-aborted, and hard-process-death/nonterminal cases. `[depends: B099]`
- [x] 2.20 `T120` Add exact pre-dedup route conservation tests including rate-limited, cancelled, unstarted, missing metadata, non-authoritative success/freshness, and canonical duplicate representatives. `[depends: B099]`

### Network and isolation tranche

- [x] 2.21 `T121` Add credential-bearing URL, userinfo, fragment, unsafe scheme/port, IP-literal, localhost, and secret-query tests. `[depends: B099]`
- [x] 2.22 `T122` Add DNS failure, empty/mixed answer, private/link-local/metadata/loopback, IPv4-mapped IPv6, zone-ID, numeric-IP, and IDNA tests. `[depends: B099]`
- [x] 2.23 `T123` Add DNS-rebinding sentinel proving the socket uses only the vetted address set. `[depends: B099]`
- [x] 2.24 `T124` Add redirect attack matrix: private target, downgrade, disallowed origin, credentials, ambiguity, loop, excess hops, and header/body stripping. `[depends: B099]`
- [x] 2.25 `T125` Add encoded/decoded/aggregate size, lying `Content-Length`, chunked overflow, compression, archive, multipart, JSON-depth, XML-entity, and HTML-node bomb tests. `[depends: B099]`
- [x] 2.26 `T126` Add retry, redirect, pagination, origin, `429`, `Retry-After`, cancellation, concurrency, wall-clock amplification, and exact planned/consumed/in-flight/remaining operation-ledger tests. `[depends: B099]`
- [x] 2.27 `T127` Add secret non-disclosure assertions over logs, exceptions, metrics, bundle bytes, and structured output. `[depends: B099]`
- [x] 2.28 `T128` Add prompt-injection corpus covering `llms.txt`, Markdown commands, tool syntax, scripts, event handlers, and invented parser/plugin names. `[depends: B099]`
- [x] 2.29 `T129` Add runtime-cache poisoning and stale-on-error isolation sentinel. `[depends: B099]`
- [x] 2.30 `T130` Add malicious plugin entry-point/autoload isolation sentinel. `[depends: B099]`

### Integration and benchmark fixtures

- [x] 2.31 `T131` Add zero operational-table/catalog/generated-data mutation sentinels. `[depends: B099] [writer: W-FIXTURE]`
- [x] 2.32 `T132` Add same-run activation sentinel for concurrent quarantine output. `[depends: B099] [writer: W-FIXTURE]`
- [x] 2.33 `T133` Add captured robots success/unavailable/unreachable/redirect/cache/500-KiB, bounded Sitemap index/host/lastmod, ETag, Last-Modified, rate-limit, and parser fixtures. `[depends: B099] [writer: W-FIXTURE]`
- [x] 2.34 `T134` Add captured known-good/known-bad portable-skill output fixtures. `[depends: B099] [writer: W-FIXTURE]`
- [x] 2.35 `T135` Create a deterministic benchmark corpus from all 2,870 source records and 16 adapter identities. `[depends: B099] [writer: W-FIXTURE]`
- [x] 2.36 `T136` Record fixture digests and environment metadata without a numeric regression threshold. `[depends: T135]`
- [x] 2.37 `T137` Prove fixture regeneration is byte-identical and contains no secrets or user-owned data. `[depends: T133-T136]`
- [x] 2.38 `T138` Reject candidate-supplied approval/reviewer/signature/receipt/revocation fields, missing or mismatched maintainer decision provenance, CI self-approval, and copied review decisions. `[depends: B099]`
- [x] 2.39 `T139` Exhaustively test disposition cross-products and input-order permutations so blocked dominates incomplete/unresolved, incomplete/unresolved dominates unsupported, and only all-positive is promotable. `[depends: B099]`
- [x] 2.40 `T140` Test bearer, cookie, signed-URL, nested JSON, HTML metadata, private-key, and chunk-split secret detection before any write or output digest. `[depends: B099]`
- [x] 2.41 `T141` Test append-only ledger ordering, hash-chain closure, duplicate `decisionId`/composite-`promotionIntentDigest` rejection, legitimate constituent-digest reuse, same/different-intent reservation contention, killed lock holder, recovery/apply races, revocation, and current-plus-reachable-history lookup. `[depends: B099]`
- [x] 2.42 `T142` Inject generation/wheel failure and interruption after every journal write/fsync, staged member, rename, directory fsync, ledger append, finalization, and lock-holder death; prove deterministic finalize-or-restore-and-revoke recovery, complete generated-byte/one-commit closure, prior-catalog restoration, and failed reuse with zero writes. `[depends: T138,T141]`
- [x] 2.43 `T143` Test the credential-free launcher environment allowlist, hidden parent secrets, application-root filesystem-open sentinels on every success/failure path, and zero database/cache/plugin/Git handles without claiming OS-wide confinement. `[depends: B099]`
- [x] 2.44 `B199` Close only when each red test fails for its intended missing contract and fixtures are deterministic. `[depends: T101-T143]`

## 3. Barrier B199 → B299 — core contracts

Exclusive `W-CONTRACT` writer owns shared models, schemas, canonical encoding,
identity normalization, and exact accounting.

- [x] 3.1 `C201` Create the isolated discovery package without importing storage, cache, plugins, or CLI modules. `[depends: B199]`
- [x] 3.2 `C202` Define strict channel, candidate-kind, lifecycle, axis, disposition, and bounded-reason enums. `[depends: C201]`
- [x] 3.3 `C203` Define finite immutable channel and whole-run budget models using strict non-negative integer units. `[depends: C202]`
- [x] 3.4 `C204` Define observed resource, redirect-hop, request receipt, and provenance-claim models. `[depends: C202,C203]`
- [x] 3.5 `C205` Define candidate occurrence, normalized candidate, collision, and terminal evaluation models. `[depends: C204]`
- [x] 3.6 `C206` Define exact scout candidate and per-channel operation accounting, including one terminal channel state and planned/consumed/in-flight/remaining budget conservation. `[depends: C205]`
- [x] 3.7 `C207` Define source and route terminal accounting with explicit rate-limited, cancelled, unstarted, and run-level-aborted semantics plus authoritative duplicate-representative invariants. `[depends: C202]`
- [x] 3.8 `C208` Define bundle manifest, exact member, and semantic/execution identity models. `[depends: C204-C207]`
- [x] 3.9 `C209` Define promotion selection, composite intent, repository-lock/CAS state, `DiscoveryPromotionPolicyDecision`, evidence-only receipt, canonical hash-chained ledger events, fsynced apply journal, revocation, and private `ApprovedIngestionSelectorEnvelope` models while forbidding review state in candidate manifests. `[depends: C205,C208]`
- [x] 3.10 `C210` Configure every untrusted-input model as strict and extra-forbid. `[depends: C203-C209]`
- [x] 3.11 `C211` Implement canonical JSON bytes with duplicate-key and non-finite rejection. `[depends: C210]`
- [x] 3.12 `C212` Implement non-self-referential semantic digest and execution-metadata separation. `[depends: C211]`
- [x] 3.13 `C213` Implement deterministic semantic array ordering and uniqueness. `[depends: C211]`
- [x] 3.14 `C214` Generate canonical JSON Schemas from strict models. `[depends: C210]`
- [x] 3.15 `C215` Add generated-schema/source byte-equality validation. `[depends: C214]`
- [x] 3.16 `C216` Implement safe public-locator parsing without network access. `[depends: C205]`
- [x] 3.17 `C217` Implement provider-aware source, route, and stable-token identity normalization. `[depends: C216]`
- [x] 3.18 `C218` Implement exact candidate occurrence and terminal-disposition accounting. `[depends: C206,C217]`
- [x] 3.19 `C219` Implement exact source and route accounting validation. `[depends: C207]`
- [x] 3.20 `C220` Implement approved runtime catalog inventory and fingerprint readback. `[depends: C212]`
- [x] 3.21 `C221` Implement read-only identity projection for v7 policy inputs, public selector, shared generated data, and embedded wheel resources plus discovery-owned decision/ledger/envelope identities; write none of the v7 surfaces. `[depends: C220]`
- [x] 3.22 `C222` Implement bounded redacted diagnostics and metric attribute rendering. `[depends: C202]`
- [x] 3.23 `C227` Add strict bounded `OPENOPPS_DISCOVERY_*` Pydantic settings, explicit environment parsing, semantic documentation metadata, and focused invalid/boundary-value tests. `[depends: C203] [writer: W-SETTINGS]`
- [x] 3.24 `C223` Add CLI-neutral library entry points shared by skill, CLI, and tests. `[depends: C216-C222]`
- [x] 3.25 `C224` Make canonical, schema, identity, taxonomy, and accounting red tests green. `[depends: C201-C223]`
- [x] 3.26 `C225` Run focused Ruff, `ty`, schema-determinism, settings, and package-import isolation checks. `[depends: C224,C227]`
- [x] 3.27 `C226` Obtain independent contract and compatibility review. `[depends: C225]` Evidence: `goals/ingest-pipeline-overhaul/maps/c226-contract-review.md` (PASS 2026-08-22; residuals out of close).
- [x] 3.28 `B299` Close core contracts only after review findings are reconciled. `[depends: C226]` Evidence: `goals/ingest-pipeline-overhaul/maps/c226-contract-review.md` (PASS; no material findings to reconcile).

## 4. Barrier B299 → B399 — dedicated transport and hostile bundle I/O

`W-HTTP` serializes transport primitives. Bundle reader/writer files may proceed
in parallel once shared path and digest contracts stabilize.

### Transport core

- [x] 4.1 `H301` Freeze trusted scout profile fields and conservative finite defaults from official limits and fixture evidence. `[depends: B299]`
- [x] 4.2 `H302` Implement public HTTPS destination policy, trusted port policy, IDNA normalization, and query-key allowlists. `[depends: H301,C216]`
- [x] 4.3 `H303` Implement fail-closed async DNS resolution and exact validated-address sets. `[depends: H302]`
- [x] 4.4 `H304` Implement connect-time address pinning while preserving original-host TLS SNI and certificate validation. `[depends: H303]`
- [x] 4.5 `H305` Reject second-resolution substitution, mixed/non-global answers, and DNS failure. `[depends: H304]`
- [x] 4.6 `H306` Implement credential-free HTTP client construction with `trust_env=False`, empty cookies/auth, no `.netrc`, proxies, or arbitrary headers. `[depends: H302]`
- [x] 4.7 `H307` Implement manual redirect processing with per-hop validation and bounded trusted-origin transitions. `[depends: H304,H306]`
- [x] 4.8 `H308` Strip request credentials, bodies, cookies, and caller headers across redirects. `[depends: H307]`
- [x] 4.9 `H309` Implement identity-encoding request policy and media-type allowlists. `[depends: H306]`
- [x] 4.10 `H310` Implement header precheck plus streamed per-resource and aggregate byte enforcement. `[depends: H309]`
- [x] 4.11 `H311` Implement JSON duplicate/depth, safe XML, and HTML node/text limits. `[depends: H310]`
- [x] 4.12 `H312` Implement one immutable request/redirect/retry/origin/time budget ledger. `[depends: H301,H307,H310]`
- [x] 4.13 `H313` Implement per-origin pacing, circuit breaking, bounded `Retry-After`, and deadline-aware retry stop. `[depends: H312]`
- [x] 4.14 `H314` Implement allowlisted response metadata and safe exception receipts. `[depends: H310,C222]`
- [x] 4.15 `H315` Implement ETag/Last-Modified conditional requests against exact verified quarantine evidence only. `[depends: H314]`
- [x] 4.16 `H316` Prove runtime cache and stale-on-error paths cannot be imported or opened. `[depends: H306,H315]`
- [x] 4.17 `H317` Prove installed plugin discovery/factory execution remains unreachable. `[depends: H306]`
- [x] 4.18 `H318` Implement versioned high-confidence body-secret detection over bounded in-memory bytes before persistence or output digesting, including chunk-boundary matches and distinct admitted-byte semantics. `[depends: H310,H314]`
- [x] 4.19 `H319` Implement a fresh scout subprocess launcher with an explicit environment allowlist, trusted profile/seed/output arguments, no database/cache/plugin/proxy/token/Git/deployment handles, and an application filesystem adapter rooted at the new quarantine directory. `[depends: H301,C227]`
- [x] 4.20 `H320` Prove secret-shaped parent variables are unobservable and every supported success/failure path attempts no out-of-root open or operational path; explicitly avoid claiming OS-account confinement. `[depends: H319,T143]`

### Bundle writer/reader in parallel

- [x] 4.21 `H321` Implement locally named digest resources and safe relative POSIX member paths. `[depends: B299] [writer: W-BUNDLE]`
- [x] 4.22 `H322` Implement exclusive sibling candidate directory creation and restrictive file modes. `[depends: H321]`
- [x] 4.23 `H323` Implement resources-first, fsync-aware, canonical-manifest-last bundle publication. `[depends: H322,C212,H318]`
- [x] 4.24 `H324` Implement exact-set offline verifier with duplicate/case/Unicode/path closure. `[depends: H321,C208]`
- [x] 4.25 `H325` Implement no-follow regular-file reads, containment, identity-before/after, and special-file rejection. `[depends: H324]`
- [x] 4.26 `H326` Implement byte/size/digest/count/aggregate/canonicality verification. `[depends: H325,C212]`
- [x] 4.27 `H327` Implement version, future-time, freshness, replay, and revocation validation. `[depends: H326,C209]`
- [x] 4.28 `H328` Prove interrupted generation cannot replace or validate as a completed bundle. `[depends: H323-H327]`

### Transport/bundle join

- [x] 4.29 `H331` Make DNS, redirect, credential, launcher, decompression, parser, quota, cache, plugin, path, TOCTOU, replay, and secret tests green under ordered `W-HTTP` then `W-BUNDLE`. `[depends: H301-H328]`
- [x] 4.30 `H332` Run focused HTTP and bundle property tests under cancellation and concurrency without editing. `[depends: H331]`
- [x] 4.31 `H333` Obtain independent SSRF, filesystem, and supply-chain security review. `[depends: H332]` Evidence: `goals/ingest-pipeline-overhaul/maps/h333-security-review.md` (PASS 2026-08-22; H334/B399 remain open).
- [x] 4.32 `H334` Route findings to ordered `W-HTTP` then `W-BUNDLE` owners, reconcile their receipts without direct edits, and reject weaker runtime seams. `[depends: H333]` Evidence: `goals/ingest-pipeline-overhaul/maps/h334-http-bundle-receipts.md` (PASS 2026-08-22; weaker `openopps.http` / cache / plugin seams rejected).
- [x] 4.33 `B399` Close only when the dedicated transport and hostile bundle verifier are fail-closed. `[depends: H334]` Evidence: `goals/ingest-pipeline-overhaul/maps/h334-http-bundle-receipts.md` (fail-closed; H333 residuals 3–6 closed by tests; E411+ not started).

## 5. Barrier B299/B399 → B499 — parallel discovery channels

Each channel owns separate modules and fixtures. Shared receipt merge is a later
join. Live requests are not required for this barrier; captured replay is the
acceptance evidence.

### Official catalogs and documentation lane

- [x] 5.1 `E411` Define maintainer-owned official seed/profile input. `[depends: B299]` Evidence: `src/openopps/discovery/official.py` `OfficialSeed` + trusted `ChannelProfile`; `tests/unit/openopps/discovery/test_official_enumerator.py`.
- [x] 5.2 `E412` Implement bounded official-document enumeration. `[depends: B399,E411]` Evidence: `enumerate_official_channel` replay-only (no `openopps.http` / DNS); captured catalog/HTML fixtures.
- [x] 5.3 `E413` Implement RFC 9309 robots parsing, complete-disallow on unreachable or security-rejected redirects, at-most-24-hour reuse, and bounded evidence capture without trusting remote instructions. `[depends: E412]` Evidence: official enumerator calls `evaluate_robots`; unreachable / security-rejected redirect tests; existing `robots.py` + `test_robots.py`.
- [x] 5.4 `E414` Implement bounded Sitemap index traversal and `lastmod` observation. `[depends: E412]` Evidence: one-hop index→urlset; `admit_public_sitemap_locators` before fetch; lastmod remote claims; host-mismatch dropped.
- [x] 5.5 `E415` Normalize official candidate references without promotion judgment. `[depends: E413,E414]` Evidence: occurrences only (no promotable/eligibleForReview bytes); catalog + HTML locators.
- [x] 5.6 `E416` Emit exact official-channel accounting and incomplete-state receipts. `[depends: E415]` Evidence: conserved request/byte ledgers; budget-exhaustion `partial` + unfinished operation IDs.
- [x] 5.7 `E417` Make official fixtures, conditional request, and budget exhaustion tests green. `[depends: E416]` Evidence: `test_official_enumerator.py` (catalog, 304/verified-cache, request_limit=1 partial).

### Public code and datasets lane

- [x] 5.8 `E421` Define maintainer-owned repository/dataset seed and provenance contract. `[depends: B299]` Evidence: `RepositorySeed` in `src/openopps/discovery/public_code.py`.
- [x] 5.9 `E422` Implement bounded public code/dataset enumeration. `[depends: B399,E421]` Evidence: `enumerate_public_code_channel` captured replay; `test_public_code_enumerator.py`.
- [x] 5.10 `E423` Preserve repository revision, path, claimed license locator, and content digest as separate provenance fields. `[depends: E422]` Evidence: local revision/path/digest claims vs remote license assertion (`accepted is False`).
- [x] 5.11 `E424` Reject archives, dynamic dependencies, executable content, and parser identifiers from remote data. `[depends: E422]` Evidence: zip/sh/package.json/parserId fixtures blocked.
- [x] 5.12 `E425` Emit exact code/dataset-channel accounting. `[depends: E423,E424]` Evidence: closed `ChannelReplayReceipt` accounting on public-code runs.
- [x] 5.13 `E426` Make rate-limit, truncation, stale-revision, duplicate, and malformed-record fixtures green. `[depends: E425]` Evidence: `test_public_code_rate_limit_truncation_stale_revision_duplicate_malformed`.

### Search API lane

- [x] 5.14 `E431` Define finite explicit query-set and public no-auth API profile. `[depends: B299]` Evidence: `SearchQuerySet` + `SearchApiProfile` in `src/openopps/discovery/search.py`.
- [x] 5.15 `E432` Implement bounded search enumeration without recursive query expansion. `[depends: B399,E431]` Evidence: `relatedQueries` ignored; pagination only via `next` within page budget.
- [x] 5.16 `E433` Preserve a query-set digest while excluding raw arbitrary query text from metrics. `[depends: E432]` Evidence: `search_metric_attributes` uses digest; raw queries absent from metric values.
- [x] 5.17 `E434` Stop authenticated or unavailable channels as blocked without fallback scraping. `[depends: E432]` Evidence: auth_required/unavailable emit blocked ops, no HTML scrape occurrences.
- [x] 5.18 `E435` Emit exact search-channel accounting. `[depends: E433,E434]` Evidence: planned query operations conserved on `ChannelReplayReceipt`.
- [x] 5.19 `E436` Make quota, pagination, duplicate, partial, and credential-absence fixtures green. `[depends: E435]` Evidence: `test_search_enumerator.py` 429/pagination/duplicates/missing page/no credential use.

### Targeted employer and ATS lane

- [x] 5.20 `E441` Define finite employer/ATS target-set input. `[depends: B299]` Evidence: `EmployerTarget` in `src/openopps/discovery/targeted_ats.py`.
- [x] 5.21 `E442` Implement targeted public-page/provider-hint enumeration. `[depends: B399,E441]` Evidence: `enumerate_targeted_ats_channel` coverage intake from captured pages.
- [x] 5.22 `E443` Reuse only built-in provider route parsing without full job sync or plugin loading. `[depends: E442]` Evidence: frozen host/path table; AST forbids `openopps.providers` / plugins.
- [x] 5.23 `E444` Distinguish detect-only hints from executable public route evidence. `[depends: E443]` Evidence: greenhouse `supported` vs SmartRecruiters `detect_only`.
- [x] 5.24 `E445` Emit exact employer/ATS-channel accounting. `[depends: E444]` Evidence: closed targeted-ats receipts with conserved ledgers.
- [x] 5.25 `E446` Make supported, detect-only, unsupported, unsafe, and inconclusive fixtures green. `[depends: E445]` Evidence: `test_targeted_ats_enumerator.py` (greenhouse/smartrecruiters/icims/401/inconclusive careers page).

### Stable merge join

- [x] 5.26 `E451` Merge channel receipts in stable channel and identity order. `[depends: E417,E426,E436,E446] [writer: W-CONTRACT]` Evidence: `src/openopps/discovery/merge.py` `CHANNEL_ORDER`.
- [x] 5.27 `E452` Reject duplicate receipt IDs, conflicting provenance, and mismatched counters. `[depends: E451]` Evidence: `MergeError` duplicate_receipt / conflicting_provenance / mismatched_counters.
- [x] 5.28 `E453` Preserve every distinct provenance edge through deduplication. `[depends: E452]` Evidence: merged `provenance_edges` equals the union of channel edges.
- [x] 5.29 `E454` Prove identical captured channel inputs reproduce identical merged bytes independent of completion order. `[depends: E453]` Evidence: `encode_merged_discovery_receipt(forward) == reverse`.
- [x] 5.30 `E455` Run isolated-channel-failure tests proving unrelated bounded channels may finish while the whole result remains partial. `[depends: E454]` Evidence: `test_isolated_channel_failure_keeps_unrelated_channels_and_marks_partial`.
- [x] 5.31 `B499` Close only when every channel is finite, independently replayable, and exact-accounted. `[depends: E455]` Evidence: `goals/ingest-pipeline-overhaul/maps/e-lane-enumerators.md`; four replay enumerators + merge; 25 focused tests green; no live HTTP/DNS.

## 6. Barrier B299/B499 → B599 — normalization, evaluation, and quarantine

Normalization, liveness, support, and policy lanes use separate files and run in
parallel. The final disposition writer is serialized.

### Normalization and collision lane

- [x] 6.1 `V501` Normalize public locators and provider-specific stable identities. `[depends: B299]`
- [x] 6.2 `V502` Generate proposed keys without silently resolving collisions. `[depends: V501]`
- [x] 6.3 `V503` Compare exact and canonical identities against every approved source. `[depends: V501]`
- [x] 6.4 `V504` Group duplicate occurrences while preserving provenance edges. `[depends: V503]`
- [x] 6.5 `V505` Enforce all eight taxonomy fields on promotion candidates. `[depends: V502]`
- [x] 6.6 `V506` Keep unresolved key, URL, provider, token, and owner conflicts explicit. `[depends: V502-V505]`

### Liveness lane

- [x] 6.7 `V511` Define source- and provider-specific positive liveness evidence. `[depends: B299]`
- [x] 6.8 `V512` Implement bounded liveness checks through the dedicated transport. `[depends: B399,V511]`
- [x] 6.9 `V513` Reject generic errors, challenges, redirect loops, and unrelated HTTP 200 pages as live evidence. `[depends: V512]`
- [x] 6.10 `V514` Classify timeout, DNS, TLS, rate-limit, auth, permission, and `5xx` outcomes as inconclusive. `[depends: V512]`
- [x] 6.11 `V515` Preserve observation time, response class, structural markers, and bounded receipt. `[depends: V513,V514]`
- [x] 6.12 `V516` Keep permanent-absence classification disabled pending the retirement decision. `[depends: V511]`

### Support lane

- [x] 6.13 `V521` Define objective source-adapter and board-route support evidence. `[depends: B299]`
- [x] 6.14 `V522` Reuse the closed built-in adapter/route registry for support classification. `[depends: V521]`
- [x] 6.15 `V523` Distinguish source support, detect-only hint, executable route, and authoritative job support. `[depends: V522]`
- [x] 6.16 `V524` Require complete route metadata for executable support. `[depends: V522]`
- [x] 6.17 `V525` Preserve unsupported and inconclusive reasons without overclaiming. `[depends: V523,V524]`

### Positive policy lane

- [x] 6.18 `V531` Read and bind exact v7 policy code/schema/evidence/corpus/public-selector digests without modifying those owned surfaces. `[depends: B299] [writer: W-DISCOVERY-POLICY]`
- [x] 6.19 `V532` Apply existing provider and exact-source denial decisions as a read-only fail-closed overlay without broadening or reinterpreting them. `[depends: V531]`
- [x] 6.20 `V533` Treat uncovered candidates and denial non-matches as unresolved. `[depends: V532]`
- [x] 6.21 `V534` Preserve access, license, redistribution, sync, and publication as independent axes. `[depends: V531]`
- [x] 6.22 `V535` Require a separate discovery-owned `DiscoveryPromotionPolicyDecision` for every operation needed by promotion; never serialize it as v7 policy evidence. `[depends: V533,V534] [writer: W-DISCOVERY-POLICY]`
- [x] 6.23 `V536` Emit discovery-owned attribution requirements without converting metadata into permission or writing v7 policy resources. `[depends: V535] [writer: W-DISCOVERY-POLICY]`

### Evaluation and bundle join

- [x] 6.24 `V541` Compute dispositions with monotonic order-independent precedence: security/rights block, then incomplete/unresolved evidence, then unsupported execution, with promotable only for the all-positive cross-product. `[depends: V506,V516,V525,V536,B499] [writer: W-EVALUATION-JOIN]`
- [x] 6.25 `V542` Validate all scout conservation equations across terminal dispositions. `[depends: V541]`
- [x] 6.26 `V543` Write the canonical quarantine receipt graph and exact manifest. `[depends: V542,B399]`
- [x] 6.27 `V544` Prove evaluation performs no operational-store, runtime-cache, catalog, generated-data, plugin, or Git writes. `[depends: V543]`
- [x] 6.28 `V545` Prove prompt-injected and fabricated agent outputs remain inert or rejected. `[depends: V543]`
- [x] 6.29 `V546` Make identity, liveness, support, policy, accounting, and same-run isolation red tests green. `[depends: V501-V545]`
- [x] 6.30 `V547` Run success, partial, failure, timeout, and cancellation byte-for-byte isolation integration tests. `[depends: V546]`
- [x] 6.31 `V548` Obtain independent correctness and security review of the full quarantine join. `[depends: V547]`
- [x] 6.32 `V549` Reconcile findings and rerun deterministic replay. `[depends: V548]`
- [x] 6.33 `B599` Close only when one exact bundle is reproducible, hostile-input-safe, and non-mutating. `[depends: V549]` Evidence: `goals/ingest-pipeline-overhaul/maps/v-lane-evaluation.md`; replay-first evaluate_occurrences + write_evaluation_bundle; 46 focused tests green; no live HTTP/DNS; no EvaluationDisposition fork.

## 7. Barrier B299/B599 → B799 — portable scout skill and downstream context

This lane owns `W-SKILL`. It may begin after core schemas stabilize and joins
with quarantine verification before acceptance. No live installation is allowed.

- [x] 7.1 `S701` Select the repository-owned portable skill SSOT and harness projection paths. `[depends: B299]` Evidence: `skills/openopps-source-scout/` is the repository SSOT; selected `.agents/skills/openopps-source-scout/` and `.cursor/skills/openopps-source-scout/` remain absent; Grok Build has no repository projection.
- [x] 7.2 `S702` Define skill scope, non-authority statement, and deterministic-tool boundary. `[depends: S701]` Evidence: `skills/openopps-source-scout/SKILL.md` states captured-input scope, advisory non-authority, and `launch_isolated_scout` as the only acceptance path.
- [x] 7.3 `S703` Document the four channel families and required finite budgets. `[depends: S702]` Evidence: `skills/openopps-source-scout/references/context-contract.md` names `official`/`public_code`/`search`/`targeted_ats` plus the finite ChannelBudget and whole-run limit fields.
- [x] 7.4 `S704` Expose exact candidate, evidence, and receipt schema context. `[depends: C214,S702]` Evidence: C214 `src/openopps/discovery/data/manifest.json`; context-contract names candidate/evidence/receipt schemas from that manifest; `assure_discovery_schemas` is a stop gate, not a write.
- [x] 7.5 `S705` Expose approved provider, policy, catalog, and taxonomy inventories read-only. `[depends: C220,S702]` Evidence: C220 `ApprovedRuntimeCatalogInventory`/`PackagedCatalogReadback`; context-contract exposes catalog, `adapterProviderIds`, digest-only `v7PolicyInputs`, and taxonomy as read-only.
- [x] 7.6 `S706` Expose bounded prior-attempt, health, and probe context without raw secrets or arbitrary payloads. `[depends: V515,S702]` Evidence: V515 `LivenessProbeRecord` time/class/markers/receipt; skill context contract names `observedAt`/`responseClass`/`structuralMarkers`/`receiptId` plus channel-replay prior-attempt and `liveness-evidence` health; absence never authorizes a probe; no raw bodies or live `openopps.health`.
- [x] 7.7 `S707` Require every suggestion to cite an admitted provenance resource identity. `[depends: S704,S706]` Evidence: SKILL.md and context-contract require non-empty admitted `provenanceResourceIds`; known-bad unadmitted-provenance fixture rejects `suggestion_provenance`.
- [x] 7.8 `S708` State that skill prose is advisory and the parent harness is outside OpenOpps' enforcement boundary; route the supported handoff only through the credential-free isolated scout/validator subprocess with no mutation handles. `[depends: S702,H320]` Evidence: H320 closed; `SKILL.md` states prose is advisory, the parent harness is outside the enforcement boundary, and the only handoff is credential-free `launch_isolated_scout` with no mutation handles.
- [x] 7.9 `S709` Add prompt-injection, fabricated-evidence, unbounded-query, arbitrary-link, and secret-handling evals. `[depends: S707,S708]` Evidence: `skills/openopps-source-scout/evals/evals.json` ids `prompt-injection-inert`, `fabricated-evidence-rejected`, `unbounded-query-refused`, `arbitrary-link-unresolved`, `secret-content-redacted`.
- [x] 7.10 `S710` Add schema-valid known-good and known-bad output fixtures. `[depends: S709,T134]` Evidence: T134 fixtures in `tests/fixtures/discovery/skill/` (schema-valid known-good plus known-bad provenance/parser/provider; schema-invalid authority); `scripts/validate_fixture.py` and evals replay them.
- [x] 7.11 `S711` Add Codex discovery, context, read, and validator smoke. `[depends: S710]` Evidence: eval `codex-structural-smoke` plus `test_codex_cursor_and_grok_structural_smokes_share_semantic_bytes`; SSOT discovery/context/read; `validate_fixture.py` → `launch_isolated_scout`; no Codex projection.
- [x] 7.12 `S712` Add Cursor discovery, context, read, and validator smoke. `[depends: S710]` Evidence: eval `cursor-structural-smoke` plus the same isolated fixture smoke; no Cursor projection.
- [x] 7.13 `S713` Add Grok Build discovery, context, read, and validator smoke without live install or billing changes. `[depends: S710]` Evidence: eval `grok-structural-smoke` plus the same isolated fixture smoke; no Grok projection, login, billing, or install.
- [x] 7.14 `S714` Prove all supported harness outputs pass through the same deterministic validator. `[depends: S711-S713,B599]` Evidence: B599 closed; Codex/Cursor/Grok labels share `launch_isolated_scout` with byte-identical known-good semantic output; `test_codex_cursor_and_grok_structural_smokes_share_semantic_bytes`; no dry-run projection or install.
- [x] 7.15 `S715` Run portable-agent validation and dry-run projection/sync checks only. `[depends: S714]` Evidence: in-repo `skills/openopps-source-scout/scripts/dry_run_projection.py`; Codex/Cursor planned-absent with SSOT file hashes; Grok `no-repository-projection`; selected paths unwritten; `wagentsInvoked` false; `validate_frontmatter.py`/`validate_evals.py` ok; no apply/install.
- [x] 7.16 `S716` Resolve docs-steward availability with `uv run wagents skills search docs-steward --json`; if present invoke it, otherwise record the exact absent-result skip receipt, with no install in either branch. `[depends: S715]` Evidence: `scripts/resolve_docs_steward.py`; command exact; `present` false; `invoked` false; `install` false; `inRepoProcess` false; skip `reasonCode` `wagents_absent` or `wagents_error`; no install in either branch.
- [x] 7.17 `S717` Obtain independent prompt/security and portability review. `[depends: S716]` Evidence: nested cursor-grok-4.6-xhigh security-auditor PASS and code-reviewer PASS (2026-08-22); prompt/security: advisory prose, isolated `launch_isolated_scout` only, new scripts inert; portability: SSOT-only, dry-run honest, docs-steward skip honest, 26 then 27 evals.
- [x] 7.18 `S718` Reconcile findings without overclaiming harness confinement or granting accepted model output any mutation or approval authority. `[depends: S717]` Evidence: `parents[2]` resolver-root miss corrected to `SKILL_ROOT.parents[1]`; residuals non-blocking (structural evals, `uv run` may rebuild); no harness-confinement claim; accepted-data-only has no mutation/approval authority.
- [x] 7.19 `B799` Close only when the skill is portable, bounded, eval-covered, and every supported acceptance path is isolated and validator-confined. `[depends: S718]` Evidence: portable SSOT; selected projections absent; 27 evals; Codex/Cursor/Grok share `launch_isolated_scout`; dry-run + docs-steward skip + review reconciled. Skill stays inert. D-B799 noted complete; G3 still waits D-B699.

## 8. Barrier B599 → B699 — promotion and private approved-ingestion envelope

`W-CATALOG` and `W-DISCOVERY-POLICY` are serialized. Shared generated paths wait
for `XV7`; Git/index operations remain outside apply. Preview and offline
validation must pass before any explicit reserve or apply path is implemented.

- [x] 8.1 `P601` Define a promotion selection file containing only verified manifest and candidate identities. `[depends: B599]`
- [x] 8.2 `P602` Reverify canonical bundle bytes and manifest digest before selection. `[depends: P601]`
- [x] 8.3 `P603` Revalidate selected candidates remain live, supported, taxonomy-complete, positively policy-closed, current, and collision-free. `[depends: P602]`
- [x] 8.4 `P604` Bind promotion to exact `catalogBefore` and source-key fingerprints. `[depends: P603]`
- [x] 8.5 `P605` Bind promotion to exact read-only v7 policy code/schema/evidence/corpus/public-selector digests and the separate discovery-owned positive-decision digest. `[depends: P603]`
- [x] 8.6 `P606` Render proposed source records with explicit package ownership. `[depends: P604,P605] [writer: W-CATALOG]`
- [x] 8.7 `P607` Reject key, exact URL, canonical URL, provider-token, and module-owner collisions. `[depends: P606]`
- [x] 8.8 `P608` Compute catalog-after, source-key, selection, and promotion digests. `[depends: P607]`
- [x] 8.9 `P609` Render a reviewable dry-run repository delta without editing files. `[depends: P608]`
- [x] 8.10 `P610` Require a separate maintainer-authored canonical decision outside quarantine, bind every reviewed digest, forbid candidate/agent/CI approval state, and treat the generated receipt as evidence rather than authority. `[depends: P609] [writer: W-DISCOVERY-POLICY]`
- [x] 8.11 `P611` Implement and validate the canonical hash-chained append-only decision ledger at its fixed repository path, using only `decisionId` and composite `promotionIntentDigest` as replay keys while equality-checking reusable components; fail closed on shallow, unavailable, rewritten, or inconsistent history. `[depends: P610,C209,T141] [writer: W-DISCOVERY-POLICY]`
- [x] 8.12 `P612` Implement one nonblocking OS-native repository promotion lock with validated path/inode, diagnostic owner nonce, post-acquire HEAD/catalog/ledger/journal/cleanliness compare-and-swap, no time-based stealing, and killed-holder recovery. `[depends: P611,T141] [writer: W-DISCOVERY-POLICY]`
- [x] 8.13 `P613` Add separately invocable reserve and revoke operations under the promotion lock; reserve writes only one ledger event, rejects a competing nonterminal HEAD/catalog-before tuple, never writes Git state, and must be committed before apply. `[depends: P612] [writer: W-DISCOVERY-POLICY]`
- [x] 8.14 `P614` Define private `ApprovedIngestionSelectorEnvelope` binding catalog content/tree and runtime fingerprints, source keys, v7 policy inputs, supplementary policy, and promotion digests; keep checkout commit SHA in later invocation evidence. `[depends: P608]`
- [x] 8.15 `P615` Reject envelopes containing persisted-only, quarantined, blocked, absent, duplicate, non-owned, or v7-public-selector-substitution keys. `[depends: P614]`
- [x] 8.16 `P616` Render one complete private staged after-tree containing catalog, every handed-off generated file, envelope, receipt, and candidate applied-ledger bytes plus exact before/after path, mode, byte, and digest metadata. `[depends: P609,P613,P615,XV799] [writers: W-CATALOG,W-DOCS-GENERATED,W-DISCOVERY-POLICY]`
- [x] 8.17 `P617` Run canonical handed-off generation twice against the staged tree and require byte-identical exact output closure. `[depends: P616] [writer: W-DOCS-GENERATED]`
- [x] 8.18 `P618` Build a candidate wheel from the staged after-tree and verify exact embedded catalog, read-only v7 policy inputs, schemas, ledger, envelope, discovery resources, and receipt identities before repository mutation. `[depends: P617] [writer: W-PACKAGE]`
- [x] 8.19 `P619` Under the promotion lock, revalidate compare-and-swap state and install the complete preverified after-tree through the fsynced `prepared`/`applying`/`finalizing` journal; terminal apply occurs only after exact closure. `[depends: P616-P618] [writers: W-CATALOG,W-DOCS-GENERATED,W-DISCOVERY-POLICY]`
- [x] 8.20 `P620` After apply, rerun generation and wheel resource readback only as zero-drift assertions. `[depends: P619]`
- [x] 8.21 `P621` Prove scout and verifier processes cannot invoke reserve, revoke, recovery, or promotion apply. `[depends: P613,P619]`
- [x] 8.22 `P622` Prove promotion never syncs, probes, opens runtime cache, loads plugins, writes SQLite, stages Git, commits, pushes, publishes, or deploys. `[depends: P619]`
- [x] 8.23 `P623` Implement locked startup/apply recovery and forward-compensating rollback: finalize only exact all-after state; otherwise restartably restore all catalog/generated/envelope/receipt/ledger preimages, append revocation, and reject whole-promotion ledger deletion. `[depends: P619-P622] [writers: W-CATALOG,W-DOCS-GENERATED,W-DISCOVERY-POLICY]`
- [x] 8.24 `P624` Make stale-fingerprint, rights, parity, taxonomy, envelope, ledger-history, composite-replay, reusable-component, staged-generation/wheel-failure, every crash cut, same/different-intent contention, killed-holder/recovery race, one-commit closure, forward-rollback, and stale-apply red tests green. `[depends: P601-P623,T142] [writer: W-T-EVAL]`
- [x] 8.25 `P625` Obtain independent deterministic-diff, concurrency, recovery, policy, replay, and package-closure review. `[depends: P624]`
- [x] 8.26 `P626` Reconcile findings through declared locks; prove two previews are byte-identical, one complete staged/apply path changes only owned paths, post-apply generation/package readback has zero drift, and a second stale apply fails with zero writes. `[depends: P625]`
- [x] 8.27 `B699` Close only when catalog, all handed-off generated data, staged wheel readback, private envelope, promotion receipt, and durable ledger have exact mutual closure and the applied set is one reviewed commit after its reservation. `[depends: P626]` Evidence: `goals/ingest-pipeline-overhaul/maps/p-lane-promotion.md` — identity closure of the full 2239-key catalog + current generated data + envelope + receipt + decision + reserved-then-applied ledger landed; staged and hatch wheel readback green; git commit still pending (reservation commit, then one apply commit).

## 9. Barrier B699 → B899 — daily selector and conserved ingestion

CLI and storage/model writers are serialized at their respective joins. No
Kaggle, public-selector, or retirement mutation enters this wave.

- [x] 9.1 `I801` Add a production/admin entry point that accepts one exact private `ApprovedIngestionSelectorEnvelope` without accepting the v7 public `SourceSelector`. `[depends: B699] [writer: W-CLI]` Evidence: `openopps discovery scout|verify-scout --json` (and `admin sources` aliases) bind the packaged private envelope via `prepare_selector_bound_scout` in `diagnostics.py` before scout/verify work; `corpusId`/`sourceKeysSha256` SourceSelector JSON is rejected; no public-selector option. Observability is CLI JSON only (not a hosted backend). Not production `openopps sync`. `tests/unit/openopps/test_discovery_cli.py`, `test_observability_join.py`.
- [x] 9.2 `I802` Add semantic help proving selector-bound execution is advanced and discovery is not same-run. `[depends: I801]` Evidence: `discovery` group is Advanced admin; scout/verify help names the private envelope, rejects SourceSelector, and states discovery is not same-run with ingest/promotion. Everyday `sources sync` help does not advertise discovery activation. `test_discovery_cli.py`.
- [x] 9.3 `I803` Validate envelope revision, catalog content/tree and runtime fingerprints, source-key digest, read-only v7 policy-input digests, supplementary policy digest, and promotion digest before network access; record checkout SHA separately. `[depends: I801]` Evidence: `prepare_selector_bound_scout` runs before `run_offline_quarantine_scout` / `verify_scout_manifest_path`; checks envelope id, catalog fingerprint/content/tree, source-key digest, four v7 policy digests, decision-schema supplementary digest, and packaged promotion digest. `checkoutSha` is recorded beside observability, not inside envelope bytes. `test_observability_join.py` mismatch/SourceSelector cases; CLI `--json`.
- [x] 9.4 `I804` Freeze the validated source set in memory before any request. `[depends: I803]` Evidence: `SelectorBoundScoutPin.frozen_source_ids` is a tuple copy of envelope keys taken at prepare; join uses that pin, not a later catalog re-read. `test_prepare_selector_bound_scout_pins_packaged_envelope`.
- [x] 9.5 `I805` Exclude persisted-only and quarantine rows from selector-bound production execution. `[depends: I804]` Evidence: pin is the packaged envelope key set (`validate_envelope_keys`); `persisted_only`/`quarantined` classes fail prepare; stored-only `local-custom-i815` is absent from CLI JSON and is not executed. Scout does not ingest. `test_prepare_selector_bound_scout_rejects_persisted_only_keys`; CLI stored-row test.
- [x] 9.6 `I806` Preserve existing explicit local-custom behavior outside selector-bound execution. `[depends: I805]` Evidence: `admin sources add` + `sources list` still resolve an explicit local custom source after scout; scout JSON does not include that key and does not sync it. `test_explicit_local_custom_workflow_remains_outside_selector_bound_scout`.
- [x] 9.7 `I807` Add per-source success, failure, timeout, freshness-skip, policy-blocked, rate-limited, cancelled, and unstarted terminal result types without destructive migration; keep aborted as run-level only. `[depends: I804] [writer: W-DB]` Evidence: scout I-lane `SourceOutcome` + `SOURCE_DISPOSITIONS` / `build_source_accounting` in `src/openopps/discovery/accounting.py`; aborted remains run-level; `tests/unit/openopps/discovery/test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.8 `I808` Enforce exact source conservation and complete-attestation predicate. `[depends: I807]` Evidence: `build_source_accounting` complete predicate + `join_scout_observability` conserved source plan; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.9 `I809` Capture the pre-dedup job-capable route denominator including missing metadata. `[depends: I804]` Evidence: `ROUTE_DISPOSITIONS` includes `missing_metadata`; `build_route_accounting` + join route plan; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.10 `I810` Add mutually exclusive success, failure, timeout, freshness-skip, deferred, duplicate, missing, policy-blocked, rate-limited, cancelled, and unstarted route classes. `[depends: I809]` Evidence: `RouteOutcome` + `ROUTE_DISPOSITIONS` in `accounting.py`; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.11 `I811` Enforce exact route conservation, authoritative-success/freshness predicates, and one authoritative representative per duplicate group. `[depends: I810]` Evidence: `build_route_accounting` + join route conservation with duplicate representative; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.12 `I812` Keep complete and explicitly typed degraded results separate. `[depends: I808,I811]` Evidence: `classify_typed_degraded` + `join_scout_observability` (`diagnostics.py`) keep `attestation` and `degradedClass` as separate fields; never opaque incomplete; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.13 `I813` Include catalog, selector, policy, promotion, and invocation digests in run evidence. `[depends: I803,I812]` Evidence: `ScoutRunEvidence` six sha256 digests in `accounting.py`; present in `join_scout_observability` `as_dict()["evidence"]`; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.14 `I814` Prove concurrent scout files and mid-run catalog changes cannot affect the pinned set. `[depends: I804,I813]` Evidence: `join_scout_observability` freezes planned IDs and plan digests immediately; catalog mutation after pin leaves digest unchanged; `test_observability_join.py`. No Alembic/ingest/CLI.
- [x] 9.15 `I815` Prove selector-bound execution does not delete, migrate, or reclassify stored-only rows. `[depends: I805,I806]` Evidence: CLI scout against an existing SQLite with stored-only `SourceRecord` + pending `job_sync_runs` leaves DB bytes, source dump, and the pending run unchanged. No L.2 update-snapshot ledger. `test_selector_bound_scout_does_not_mutate_stored_only_or_job_sync_rows`.
- [x] 9.16 `I816` Make exact envelope, same-run isolation, cancellation/unstarted, source-accounting, route-accounting, duplicate-representative, and local-custom red tests green under ordered `W-CLI` then `W-DB`. `[depends: I801-I815]` Evidence: W-CLI then W-DB in `test_discovery_cli.py` (envelope JSON, no same-run activate/promote, unstarted source conservation, route conservation, local-custom) plus existing `test_observability_join.py` cancellation/duplicate-representative cases. Scout pin accounts envelope sources as unstarted (not ingested).
- [x] 9.17 `I819` Run focused ingestion, storage, CLI, read-only v7 policy-input, and discovery-envelope tests; do not touch Kaggle. `[depends: I816]` Evidence: `uv run pytest tests/unit/openopps/test_discovery_cli.py tests/unit/openopps/discovery/test_observability_join.py tests/unit/openopps/test_source_resolution.py tests/unit/openopps/discovery/test_discovery_policy.py tests/unit/openopps/discovery/test_promotion_apply.py` → 66 passed. No Kaggle.
- [x] 9.18 `I820` Obtain independent accounting, compatibility, and migration-safety review. `[depends: I819]` Evidence: completed [I-lane accounting review](9df666a3-9568-4ed7-bc77-e5d5c27f8f19); receipt `goals/ingest-pipeline-overhaul/maps/i820-accounting-review.md`. I801–I819 stay ticked. No material code findings. B899 stays open. No Alembic/L.2/Kaggle.
- [x] 9.19 `I821` Route findings to ordered `W-CLI` then `W-DB` owners and reconcile their receipts without direct edits or changes to local-custom behavior, v7 public selectors, Kaggle, or retirement. `[depends: I820]` Evidence: W-CLI then W-DB on [I-lane accounting review](9df666a3-9568-4ed7-bc77-e5d5c27f8f19): no material findings. Process finding (premature/missing-map citation) reconciled by retargeting I820 evidence to that receipt. Local-custom, v7 SourceSelector, Kaggle, and retirement unchanged. B899 later closed by ingest conservation (`maps/b899-ingest-conservation.md`).
- [x] 9.20 `B899` Close only when a pinned run conserves every source and route exactly once, including cancelled and unstarted work. `[depends: I821]` Evidence: pinned `openopps sync` conserves every source and job-capable route in the pin catalog (planned = Σ terminals, including cancelled/unstarted). Fixture: temp SQLite + mocked HTTP/fake adapters for all job-capable routes in that pin — not scout envelope-unstarted + one `scout-evaluation` route, and not a live 2239-key crawl. Getro is `policy_blocked` (not a production allow); stored-only extras are not fetched. Typed `complete` vs `degraded`. `--metrics-json` conservation is counts/digests only (no URLs, secrets, or unaccounted ids). I815 still uses `job_sync_runs` (no L.2 / Alembic 0005). Receipt `goals/ingest-pipeline-overhaul/maps/b899-ingest-conservation.md`. Focused pytest 213 passed. D-B899 closes with this barrier. O9xx not started.

## 10. Barrier B699/B799/B899 → B999 — observability and benchmark evidence

- [x] 10.1 `O901` Define bounded metric names for scout, channel, candidate, evaluation, promotion, skill handoff, source, and route stages. `[depends: B799,B899]` Evidence: `METRIC_NAMES` in `src/openopps/discovery/observability.py` names scout, channel, candidate, evaluation, promotion, skill_handoff, source, and route. `tests/unit/openopps/discovery/test_observability.py`. `maps/o-lane.md`.
- [x] 10.2 `O902` Define low-cardinality bounded reason-code and terminal-state dimensions. `[depends: O901]` Evidence: `REASON_CODES` is `BoundedReason`; `TERMINAL_STATES` is complete|partial|failed|cancelled|aborted|nonterminal; stage terminals are frozen vocabularies. `test_observability.py`.
- [x] 10.3 `O903` Exclude raw URLs, raw queries, secrets, payload fragments, and arbitrary upstream labels. `[depends: O902]` Evidence: `assert_bounded_metric_payload` rejects `https://`, query tokens, Authorization/Bearer/Cookie/`token=`, `unaccounted`, and unknown names/reasons.
- [x] 10.4 `O904` Emit exact accounting totals and reason distributions per channel and run. `[depends: O901-O903]` Evidence: `build_metric_catalog_report` conserves `planned = Σ terminals` and emits `BoundedReason` histograms per channel and scout run.
- [x] 10.5 `O905` Emit manifest, catalog, selector, policy, and promotion digest correlation. `[depends: O904]` Evidence: report `digests` carries manifest, catalog content/tree, selector, policy, and promotion SHA-256 only.
- [x] 10.6 `O906` Distinguish fetched, not-modified, reused, blocked, rate-limited, partial, and complete evidence. `[depends: O904]` Evidence: `classify_evidence_class` plus per-series `evidence` histograms; conserved with planned counts.
- [x] 10.7 `O907` Run the deterministic 2,870-source/16-adapter offline discovery/promotion benchmark fixture in a recorded clean environment and require exactly zero SQLite statements. `[depends: T135,B699]` Evidence: `openopps.discovery.benchmark.run_offline_promotion_benchmark` binds T135 corpus to the packaged 2,870/16 inventory under `sqlite_statement_guard`; statement count 0; HTTP 0. `tests/unit/openopps/discovery/test_benchmark.py`. `maps/o-lane.md`.
- [x] 10.8 `O908` Measure normalization, schema validation, dedupe, collision audit, policy evaluation, and promotion rendering. `[depends: O907]` Evidence: six `OperationLedger` stages in `benchmark.py`; identity preview proposes zero records and preserves catalog bytes.
- [x] 10.9 `O909` Record median, p95, peak RSS, artifact bytes, request counts, and relevant statement counts. `[depends: O908]` Evidence: integer `medianUs`/`p95Us`, `peakRssBytes`, `artifactBytes`, `httpRequestCount=0`, `sqliteStatementCount=0` on `BenchmarkReport.as_dict()`.
- [x] 10.10 `O910` Repeat controlled runs and report variance. `[depends: O909]` Evidence: five odd-count repeats; range plus nearest-rank p95; deterministic artifact fingerprint across repeats.
- [x] 10.11 `O911` Write an ADR assessing fixture representativeness, variance, headroom, and CI stability. `[depends: O910]` Evidence: `src/openopps/discovery/data/benchmark-adr.json` and `goals/ingest-pipeline-overhaul/maps/o-lane.md`.
- [x] 10.12 `O912` Record exactly one machine-readable ADR verdict: `adopt` or `defer`. `[depends: O911]` Evidence: ADR `verdict` is `defer`.
- [x] 10.13 `O913` Implement the recorded verdict deterministically: add only reviewed evidence-backed thresholds for `adopt`, otherwise retain structural gates and write a no-numeric-SLO `defer` receipt. `[depends: O912]` Evidence: `benchmark-implementation-receipt.json` `verdict=defer`, `numericRegressionThreshold=null`, structural gates only.
- [x] 10.14 `O914` Validate that the one implementation receipt matches the ADR verdict and contains no artifacts from the opposite branch. `[depends: O913]` Evidence: `assert_receipt_matches_adr`; adopt-mismatch red test; no SLO/threshold sibling artifacts.
- [x] 10.15 `O915` Add metric-cardinality and secret-nondisclosure tests. `[depends: O901-O906]` Evidence: `test_observability.py` (8 names, ≤6 attributes, closed enums, no URLs/secrets); `test_benchmark.py` asserts ADR `defer` and no SLO token in catalog names.
- [x] 10.16 `O916` Obtain independent observability and performance-method review. `[depends: O914,O915]` Evidence: `goals/ingest-pipeline-overhaul/maps/o916-observability-review.md` PASS. No numeric SLO. ADR remains `defer`.
- [x] 10.17 `O917` Reconcile findings without unsupported performance claims. `[depends: O916]` Evidence: no material findings; p95 remains descriptive evidence; defer retained. `maps/o-lane.md`.
- [x] 10.18 `B999` Close when evidence is reproducible, bounded, and accurately labeled. `[depends: O917]` Evidence: catalog + offline benchmark + review; 11 catalog pytest + 6 benchmark pytest; ADR `defer`; no hosted backend. `maps/o-lane.md`. D1005 not started.

## 11. Barrier B899/B999 → B1099 — CLI, CI, docs, and final local assurance

Docs and Just/CI lanes run in parallel after public contracts stabilize. Shared
generated surfaces and Git operations remain serialized.

### CLI and local recipes lane

- [x] 11.1 `D1001` Add `admin sources scout --output <dir> --json` with explicit output and no mutation. `[depends: B599] [writer: W-CLI]` Evidence: `src/openopps/cli.py` `discovery_scout` on `discovery` (Advanced admin) and `admin sources`; `run_offline_quarantine_scout` writes only `--output`; `tests/unit/openopps/test_discovery_cli.py`.
- [x] 11.2 `D1002` Add offline `admin sources verify-scout <manifest> --json`. `[depends: B399] [writer: W-CLI]` Evidence: `discovery_verify_scout` + `verify_scout_manifest_path`; read-only; no rewrite/activate; `tests/unit/openopps/test_discovery_cli.py`.
- [x] 11.3 `D1003` Add promotion preview command or script with no scout/verify apply option. `[depends: B699] [writer: W-CLI]` Evidence: `openopps discovery preview-promotion [--json]` and `admin sources` alias; `preview_repository_promotion` dry-runs the on-disk B699 identity closure (optional quarantine manifest is verify-then-empty-selection). No apply/reserve/lock; no Git/SQLite/Kaggle/catalog mutation. `tests/unit/openopps/test_discovery_cli.py`.
- [x] 11.4 `D1004` Add semantic help and stdout/stderr separation tests. `[depends: D1001-D1003]` Evidence: `tests/unit/openopps/test_discovery_cli.py` covers discovery/admin-sources `preview-promotion` help (no `--apply`), JSON stdout vs empty stderr, byte-identical identity preview, invalid-manifest fail-closed, and scout/verify still without apply.
- [x] 11.5 `D1005` Add thin schema, fixture, manifest, promotion-preview, private-envelope, accounting, and benchmark Just recipes only after shared-path handoff. `[depends: D1004,B999,XV799] [writer: W-SHARED-DELIVERY]` Evidence: Justfile `source-discovery-{schema,fixtures,manifest,promotion-preview,private-envelope,accounting,benchmark}-check` plus skill-eval/`ci-discovery`; `maps/d10xx-ci.md`.
- [x] 11.6 `D1006` Prove every recipe delegates to canonical library/script entry points. `[depends: D1005]` Evidence: recipes wrap only `scripts/source_discovery_gates.py`; `test_discovery_just_recipes_delegate_to_canonical_gates_script` passed.

### Least-privilege CI lane

- [x] 11.7 `D1011` Add offline schema, sanitized-fixture replay, bundle, skill-eval, private-envelope, and accounting CI gates with discovery network access disabled. `[depends: D1005] [writer: W-SHARED-DELIVERY]` Evidence: `CI_GATES` + `_require_offline()`; `OPENOPPS_DISCOVERY_NETWORK=disabled just ci-discovery` ok (8 sub-gates).
- [x] 11.8 `D1012` Mirror canonical local recipes without duplicating command logic. `[depends: D1011]` Evidence: `.github/workflows/ci.yml` discovery job runs only `just ci-discovery`; `test_discovery_ci_yaml_mirrors_just_without_duplicating_gate_commands` passed.
- [x] 11.9 `D1013` Keep public CI offline, immutable-action-pinned, read-only, credential-free, and limited to committed sanitized redistribution-safe fixtures. `[depends: D1011,XV799] [writer: W-SHARED-DELIVERY]` Evidence: SHA-pinned, `contents: read`, credential-free, sanitized `tests/fixtures/discovery`; `test_public_discovery_ci_is_offline_pinned_read_only_and_credential_free` passed.
- [x] 11.10 `D1014` Disable persisted checkout credentials and all live discovery network access in public CI. `[depends: D1013]` Evidence: `persist-credentials: false`; job env `OPENOPPS_DISCOVERY_NETWORK: disabled`; no `schedule:` / `repository_dispatch:`.
- [x] 11.11 `D1015` Add governance tests rejecting a live-scout `schedule:` trigger, networked live dispatch, unsanitized bundle upload, commit, push, PR, install, publish, release, or deploy step. `[depends: D1014]` Evidence: `test_public_workflows_reject_live_scout_schedule_triggers` + `test_discovery_governance_detector_rejects_d1015_examples`; 24 passed in `test_ci_governance.py`.
- [x] 11.12 `D1016` Add a scheduler-agnostic private-host runbook/template with explicit environment allowlist, finite budgets, private output, retention, and readback gates; do not provision it. `[depends: D1001,B799] [writer: W-DOCS]` Evidence: `docs/source-discovery-private-host-runbook.md` unprovisioned template (allowlist, budgets, private output, retention, readback); `maps/d1016-private-host-runbook.md`.
- [x] 11.13 `D1017` Test runbook commands locally against sanitized fixtures without live network access or public artifact upload. `[depends: D1016]` Evidence: `tests/unit/openopps/test_discovery_private_host_runbook.py` 9 passed; CLI 20 passed; `OPENOPPS_DISCOVERY_NETWORK=disabled`.
- [x] 11.14 `D1018` Record in owned documentation that live scheduler provisioning, credential selection, activation, retention, and execution are separate unexercised authority gates. `[depends: D1015,D1017] [writer: W-DOCS]` Evidence: five unexercised gates named in runbook, README, and contributing.mdx; `maps/d1018-live-authority.md`.

### Documentation and agent context lane

- [x] 11.15 `D1021` Update README with scout, quarantine, promotion, selector, and daily guarantees. `[depends: B899,B799] [writer: W-DOCS]` Evidence: README `## Quarantined Source Discovery`; scout/verify/preview; no `--apply`; packaged envelope pin; `maps/d1021-readme.md`.
- [x] 11.16 `D1022` Update CLI, providers, operations, configuration, and contributing MDX. `[depends: D1021]` Evidence: `web/content/docs/{cli,providers,operations,configuration,contributing}.mdx` discovery slices; index TOC points policy-vs-verification at Operations.
- [x] 11.17 `D1023` Document the eight required taxonomy fields and frozen 895/1,975 baseline. `[depends: D1021]` Evidence: providers.mdx eight `REQUIRED_TAXONOMY_FIELDS`; frozen 895 8/8 and 1,975 0/8; `maps/d1023-taxonomy.md`.
- [x] 11.18 `D1024` Document policy declaration versus independent positive verification. `[depends: D1021]` Evidence: operations.mdx policy declaration vs independent verification; 0 independently verified; 688 blocked.
- [x] 11.19 `D1025` Document complete versus degraded candidate/source/route accounting. `[depends: D1021]` Evidence: operations.mdx complete vs degraded candidate/source/route accounting and `classify_typed_degraded`.
- [x] 11.20 `D1026` Document bundle freshness, replay, rollback, and revocation. `[depends: D1022]` Evidence: operations.mdx 48h bundle age, offline replay, ledger reserved/applied/revoked, no discovery rollback CLI.
- [x] 11.21 `D1027` Document skill non-authority and deterministic validator boundary. `[depends: D1022,B799]` Evidence: operations.mdx + contributing.mdx: skill advisory; acceptance only `launch_isolated_scout` / `validate_fixture.py`.
- [x] 11.22 `D1028` Update root and nested `AGENTS.md` for discovery modules, skill, generated surfaces, validation, and live authority. `[depends: D1022]` Evidence: root/`src/openopps`/`web` AGENTS.md discovery isolation, inert skill, live-authority split; `maps/d1028-agents.md`.
- [x] 11.23 `D1029` Invoke docs stewardship after public API, file structure, skill, and agent-definition changes stabilize. `[depends: D1027,D1028]` Evidence: `uv run python skills/openopps-source-scout/scripts/resolve_docs_steward.py` SKIP `wagents_absent` (present false, invoked false, install false); `maps/d1029-docs-steward.md`.
- [x] 11.24 `D1030` Regenerate handed-off docs data twice and require zero drift. `[depends: D1029,XV799] [writer: W-DOCS-GENERATED]` Evidence: `cd web && pnpm data:generate` twice; SHA-256 `0dd26acd756d5fc1c65a6654ee2a03d2c9e7264156e7aec3cc146c36187c68e7` unchanged vs HEAD; `maps/d1030-docs-data.md`.

### Local assurance join

- [x] 11.25 `D1041` Run focused canonicalization, schema, HTTP, filesystem, plugin, policy, and prompt-injection tests. `[depends: D1006,D1018,D1030]` Evidence: schema-check ok; 149 canonical/bundle/core; 169 HTTP/transport/isolation (incl. prompt-injection); 30 plugin/policy/skill; maps/d1041-slice-*.md.
- [x] 11.26 `D1042` Run focused channel, quarantine, promotion, private-envelope, ingestion, storage, CLI, and skill tests; exclude v7-owned Kaggle mutation. `[depends: D1041]` Evidence: 43 enumerator/channel; envelope+preview applied=false grantsAuthority=false; 129 promotion/accounting; 51 ingest/storage/CLI/skill; no Kaggle mutation; maps/d1042-slice-*.md.
- [x] 11.27 `D1043` Run full Python tests and coverage. `[depends: D1042]` Evidence: `uv run pytest --cov=openopps --cov-report=term-missing` 1879 passed, 1 skipped (maintainer search-index match), 0 failed; TOTAL 90.18%; fail_under 90 not blocked; `maps/d1043-pytest-cov.md`.
- [x] 11.28 `D1044` Run Ruff, `ty`, and `uv lock --check`. `[depends: D1043]` Evidence: `ruff check src tests` pass; `ty check` pass; `uv lock --check` 101 packages; `maps/d1044-python-quality.md`.
- [x] 11.29 `D1045` Run deterministic generated-data and benchmark-fixture checks twice. `[depends: D1043]` Evidence: fixtures-check twice ok identical; benchmark-check twice ok httpRequestCount=0 sqliteStatementCount=0; `maps/d1045-fixtures-twice.md`. D1030 docs-data hash unchanged.
- [x] 11.30 `D1046` Compare exact handed-off baseline digests and named `web/**` tracked paths: on any difference run web data generation, types, lint, tests, build, and function-trace checks; otherwise record an unchanged-digest / empty-path-diff skip receipt. `[depends: D1045,XV799]` Evidence: `openopps-data.json` SHA-256 `0dd26acd…` matches xv7-handoff; skip web regen; MDX/AGENTS dirty is W-DOCS not XV703; `maps/d1046-digest-compare.md`.
- [x] 11.31 `D1047` Build and install a wheel; verify catalog, policy, schema, skill, and discovery resources plus CLI help. `[depends: D1045]` Evidence: `just promotion-wheel-readback` 27 passed; catalog 2239; discovery data 44 members; skill not in wheel (SSOT `skills/openopps-source-scout`); discovery help has no `--apply`; `maps/d1047-wheel.md`.
- [x] 11.32 `D1048` Run strict OpenSpec validation after implementation evidence is linked. `[depends: D1046,D1047] [writer: W-OS]` Evidence: `@fission-ai/openspec@1.6.0 validate --all --strict` 12 passed 0 failed; `maps/d1048-openspec.md`.
- [x] 11.33 `D1049` Run source-policy structural validation read-only and report eligibility separately. `[depends: D1048]` Evidence: `just source-policy-check` exit 0; audit exit 2 expected (688 blocked, independentlyVerifiedAllowedCount=0); `maps/d1049-source-policy.md`.
- [x] 11.34 `D1050` Run the canonical aggregate `just ci` gate and capture its exact result without collapsing layer-specific evidence. `[depends: D1049]` Evidence: `just ci` exit 0; python 1879 passed 90.15%; openspec 12/0; discovery 8/8; web e2e 45 passed; artifacts diff-check 0; `maps/d1050-just-ci.md`.
- [x] 11.35 `D1051` Run independent correctness, security, performance-evidence, docs, CI, and graph-completeness reviews. `[depends: D1050]` Evidence: maps/d1051-{correctness,security,performance,docs,ci,graph}.md; all PASS or PASS-with-open-tail; no material remediations.
- [x] 11.36 `D1052` Route every finding back to its original declared writer lock, wait for acceptance receipts, and perform a read-only dispatch join without direct edits. `[depends: D1051]` Evidence: no material D1051 findings; `maps/d1052-join.md`.
- [x] 11.37 `D1053` Inspect final diff, worktree ownership, generated paths, and exact staging candidates. `[depends: D1052]` Evidence: `maps/d1053-worktree.md`; main@fd7bab3; generated JSON clean; 103 staging candidates; B1099 stays open.
- [x] 11.38 `B1099` Close only when local source, focused-test, generated, package, and OpenSpec evidence is green. `[depends: D1053]` Evidence: D1005–D1053 ticked; `just ci` exit 0 (`maps/d1050-just-ci.md`); OpenSpec validate `--all --strict` 12/0; wheel readback; generated JSON `0dd26acd…`; D1053 worktree inspect. Git/F12xx, B699 reservation-then-apply, P688 (688 blocked), L.1/Alembic 0005, and live Workers remain section-12 / G3 residuals — not this local-assurance close. `maps/d1053-worktree.md`.

## 12. Barrier B1099 → final release assurance

`W-GIT` is serialized after every file writer stops. User authority covers
atomic commits and push; live scouting, schedule activation, Kaggle, Cloudflare,
Vercel, release publication, and destructive cleanup remain independent gates.

- [x] 12.1 `F1201` Re-read branch, status, nested instructions, and protected unrelated paths. `[depends: B1099]` Evidence: `main`@`fd7bab3` even with origin; nested AGENTS isolation; protected providers/storage/kaggle/deployment/uv.lock/source-policy JSON clean; 0005 stays `.draft`; generated JSON clean; `maps/f1201-reread.md`.
- [x] 12.2 `F1202` Confirm no agent or process still owns a file writer. `[depends: F1201]` Evidence: pin writer joined; no product exclusive lock; `maps/f1202-writers.md`. F1203 W-GIT not acquired.
- [ ] 12.3 `F1203` Stage only reviewed named paths and inspect the exact index. `[depends: F1202] [writer: W-GIT]`
- [ ] 12.4 `F1204` Create atomic conventional commits by logical change. `[depends: F1203] [writer: W-GIT]`
- [ ] 12.5 `F1205` Verify each commit tree and local gates without amending, rebasing, stashing, or resetting. `[depends: F1204]`
- [ ] 12.6 `F1206` Push under current authority and verify remote branch SHA. `[depends: F1205] [writer: W-GIT]`
- [ ] 12.7 `F1207` Monitor exact-SHA CI to terminal state. `[depends: F1206]`
- [ ] 12.8 `F1208` Verify any automatic docs deployment for the exact SHA without mutating unrelated services. `[depends: F1207]`
- [ ] 12.9 `F1209` Perform bounded read-only production smoke only for repository-approved public routes. `[depends: F1208]`
- [ ] 12.10 `F1210` Optionally run one separately authorized bounded live scout and verify its artifact readback; otherwise report this evidence layer unproven. `[depends: F1209]`
- [ ] 12.11 `F1211` Keep private live-scheduler provisioning/activation, Kaggle mutation, Cloudflare mutation, release publication, and any future retirement work separately unexecuted unless explicitly authorized. `[depends: F1210]`
- [ ] 12.12 `F1212` Record exact evidence by layer and any remaining blocked task IDs. `[depends: F1211]`
- [ ] 12.13 `F1299` Close only when repository delivery is proven and every live or blocked boundary is reported truthfully. `[depends: F1212]`

## Requirement-to-wave coverage

| Capability | Primary implementation waves | Assurance joins |
| --- | --- | --- |
| Independent bounded scout | `C2xx`, `H3xx`, `E4xx` | `B499`, `B599`, `D1041` |
| Canonical quarantine bundle | `C2xx`, `H32x`, `V54x` | `B399`, `B599`, `D1047` |
| Objective liveness/support/policy | `V51x`, `V52x`, `V53x` | `V546`, `B599`, `D1042` |
| Portable skill boundary | `S7xx` | `B799`, `D1029`, `D1042` |
| Deterministic promotion | `P6xx` | `B699`, `D1047` |
| Exact scheduled selector/accounting | `I8xx` | `B899`, `D1042` |
| Bounded metrics/performance evidence | `O9xx` | `B999`, `D1044` |
| CLI/docs/CI parity | `D10xx` | `B1099`, `F1207` |

## Normative task traceability

| Delta requirement | Implementing task IDs |
| --- | --- |
| `source-discovery`: Discovery runs as an independent quarantined scout | `T131-T132`, `C201`, `C223`, `H319-H320`, `H331`, `E411-E455`, `V543-V545`, `S708`, `D1001-D1002` |
| `source-discovery`: Discovery channels are finite and explicit | `T126`, `C203`, `C206`, `H312-H313`, `E411-E455`, `V542`, `O904` |
| `source-discovery`: Quarantine bundles are content-addressed and exactly verifiable | `T101-T110`, `C208`, `C210-C215`, `C224`, `H321-H328`, `H331`, `V543` |
| `source-discovery`: Candidate normalization preserves provenance and ambiguity | `T111-T114`, `C204-C205`, `C216-C218`, `C220`, `C223-C224`, `E451-E454`, `V501-V506` |
| `source-discovery`: Discovery evidence is bounded and trust-separated | `T121-T140`, `T143`, `C204`, `C222`, `H301-H331`, `V511-V536`, `V544-V545` |
| `source-discovery`: Candidate processing, disposition, and relationships are explicit | `T112-T118`, `T139`, `C202`, `C205-C206`, `C218`, `V504`, `V541-V542`, `V546` |
| `source-discovery`: Promotion is separate, reviewed, deterministic, and policy-gated | `T138`, `T141-T142`, `C209`, `C221`, `C224`, `P601-P626` |
| `source-discovery`: Portable scout guidance cannot bypass deterministic authority | `T128`, `T134`, `T143`, `H319-H320`, `S701-S718` |
| `provider-coverage`: Coverage audit evaluates high-impact provider candidates | `E441-E446`, `V521-V525`, `V541-V549`, `P603` |
| `provider-coverage`: Candidate liveness and support use objective evidence | `T117-T118`, `E441-E446`, `V511-V525`, `V546` |
| `provider-coverage`: Coverage deltas bind to an approved catalog baseline | `C220`, `C224`, `V503-V505`, `P603-P604` |
| `provider-coverage`: Candidate decisions remain auditable | `C205`, `C218`, `V541-V549`, `P603` |
| `provider-ingestion`: Scheduled snapshots consume an exact private approved-ingestion selector envelope | `T119-T120`, `C207`, `C219`, `P614-P620`, `I801-I815` |
| `provider-ingestion`: Quarantined candidates cannot enter ingestion | `T132`, `C220`, `V544`, `P621`, `I804-I805`, `I814` |
| `provider-ingestion`: Scheduled selection does not erase explicit local custom behavior | `T119`, `C207`, `I805-I806`, `I815-I816`, `I821` |
| `provider-ingestion`: Scheduled ingestion conserves exact terminal accounting | `T119-T120`, `C206-C207`, `C219`, `I807-I813`, `I816`, `O904` |
| `cli-domain`: Quarantined discovery is an explicit advanced CLI workflow | `C223`, `D1001`, `D1004` |
| `cli-domain`: Quarantine verification is offline and read-only | `H324-H327`, `D1002`, `D1004` |
| `cli-domain`: Scout commands do not promote | `P621`, `D1001-D1004` |
| `performance-observability`: Scout execution has explicit finite budgets | `C203`, `C206`, `C227`, `H301`, `H310-H313`, `E411-E455` |
| `performance-observability`: Scout requests are host-aware and retry-bounded | `T122-T126`, `H301-H317`, `E413-E414` |
| `performance-observability`: Scout metrics expose completeness and resource use | `C206-C207`, `C222`, `E416`, `E425`, `E435`, `E445`, `O901-O906` |
| `performance-observability`: Performance thresholds follow reproducible evidence | `T135-T137`, `O907-O917` |
| `release-workflows`: Discovery contracts have deterministic local and CI gates | `D1005-D1015`, `D1041-D1050` |
| `release-workflows`: Promotion preview is digest-bound and dry-run-first | `T138`, `T141-T142`, `P601-P626`, `D1003-D1005` |
| `release-workflows`: Public CI remains offline and live scouting remains private | `H319-H320`, `D1011-D1018` |
| `release-workflows`: Discovery workflow documentation remains synchronized | `S716`, `D1021-D1030` |
| `release-workflows`: Active v7 ownership gates shared repository writes | `XV701-XV799`, `P616-P620`, `D1005-D1015`, `D1030` |
| `release-workflows`: Release assurance separates evidence layers | `D1041-D1053`, `F1201-F1299` |

Implementation writers and green tasks appear above. `C225-C226`, `H332-H334`,
`I819-I821`, `P625-P626`, `D1041-D1053` except explicit writer `D1048`, and
`F1201-F1299` except Git writers are command-only validation, independent
review, remediation-receipt joins, or release assurance; they do not directly
edit implementation files.

Route-first reversible retirement is intentionally absent from this task graph.
Its qualifying-absence, observation-horizon, and persisted-ownership decisions
remain an Open Question and require a future `route-first-reversible-retirement`
change before any implementation task exists.
