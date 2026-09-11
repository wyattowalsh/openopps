## Context

The current CLI is ledger-first: users configure or discover boards, persist provider routes, and then run `jobs sync`. Provider URL detectors return route projections suitable for that workflow, but they do not provide a durable exact-posting target contract. `ProviderRegistry` reports coarse support, `BoardJobProvider.fetch_jobs()` is a board-sync interface, and output/persistence behavior is distributed across the existing commands.

The accepted goal adds an operational URL-first workflow while retaining those contracts. It must distinguish four independent questions: whether a URL can be recognized, whether the provider can list an entire board, whether it can fetch one posting natively, and whether a complete authoritative board can safely support exact-match fallback. Interface stability and unlisted behavior are separate evidence dimensions.

The repository also has an active storage migration program. The authoritative `goals/ingest-pipeline-overhaul/task-graph.yaml` currently records G3 as unmet because the D-B699 Git closeout is pending, L.1 as open, Alembic head `0004`, and `0005_update_snapshot_ledger.py.draft` as inactive. URL-pull schema work must not race or preassign the next revision.

## Goals / Non-Goals

**Goals:**

- Accept supported ATS board, posting, and ordinary careers URLs through one shared service.
- Make provider detection, parsed identities, operation capabilities, completeness, and provenance observable.
- Cover full-board URL pulls for all ten adopted built-in job providers without weakening existing synchronization guarantees.
- Prefer exact native get and use board-scan fallback only when the result is complete, authoritative, and uniquely matched.
- Keep discovery one-page, finite, non-recursive, public-HTTPS-safe, and operationally isolated.
- Provide consistent human and machine output with stable failures and no stdout contamination.
- Persist successful pulls only when the user opts in with `--save` (CLI default False); keep the default and `--no-save` ephemeral for operational state.
- Keep list application atomic and membership-scoped, and make point gets incapable of closing unrelated jobs.
- Preserve provider-native structured listing/detail evidence without promising byte-for-byte HTTP wire replay.

**Non-Goals:**

- Changing the meaning of current sync/list/show/history/export commands.
- Adding a TUI, prompt UI, browser UI, hosted pull service, authenticated ATS integration, browser automation, or recursive crawling.
- Treating operational URL resolution as source scouting, source promotion, or catalog admission.
- Inferring URL-pull support from a detector, legacy plugin, route hint, arbitrary WordPress page, or HTTP success alone.
- Cross-namespace deduplication between operational URL-pull identities and catalog-owned boards.
- Activating the draft Alembic `0005`, taking ownership of L.1/L.2/O.1 tables, or assigning a future revision before the storage handoff.
- Claiming deterministic mocked provider fixtures prove current live third-party availability.

## Decisions

### One service behind two CLI spellings

`openopps <URL>` rewrites only a leading validated HTTPS positional URL into the same Typer callback used by `openopps jobs pull <URL>`. Root options, help, version, empty invocation, malformed inputs, and ordinary unknown commands retain Click/Typer behavior. Pull options are defined once.

`PullOperation` has `auto`, `list`, and `get`. `auto` selects `get` only for a resolved exact-posting target and otherwise selects `list` for a resolved board target. An explicit operation must be compatible with the resolved target and provider capability; the service does not silently reinterpret an incompatible request.

### Typed targets and independent operation capabilities

New additive contracts live in `providers/pull.py` and `pull_models.py`:

- `ProviderUrlTarget` retains provider id, target kind, canonical board identity, optional exact posting identity, safe canonical URL material, and parser evidence.
- Provider capabilities independently declare board list, native exact get, authoritative board-scan get, exact unlisted/direct get, optional full unlisted enumeration, and documented versus best-effort interface stability.
- List results carry normalized jobs, structured listing/detail evidence, membership scope, membership authority, pagination/reconciliation evidence, and detail coverage.
- Get results carry one exact normalized posting, structured listing/detail evidence, and identity-match evidence; they never impersonate a board snapshot.
- Capability registration validates that every advertised operation has a compatible parser and callable hook. Recognition alone never implies execution support.

`BoardJobProvider.fetch_jobs()` and `JobFetchResult` remain available to existing sync and legacy plugin callers. Where semantics align, a new authoritative list hook may project into that contract; URL-specific target, raw evidence, or point-get semantics do not leak into existing callers.

### Deterministic native matching, then one bounded careers page

Resolution proceeds in this order:

1. Parse and validate the requested public HTTPS URL without network access.
2. Run deterministic built-in and validated plugin target parsers. A single executable native match resolves immediately.
3. If `--direct` is present, reject an unmatched or ambiguous native URL without fetching a careers page.
4. Otherwise fetch the requested careers page through the shared safe HTTP client. Validate every redirect and inspect only the final admitted response.
5. Extract bounded canonical/alternate/metadata/JSON-LD links, embedded or encoded ATS URLs, and ordinary page links. Resolve relative links against the admitted page URL.
6. Unless `--no-probe` is present, run only capability-declared slug probes within global and per-provider budgets.
7. Parse all admitted candidates, canonicalize equivalent targets, and require exactly one executable target. Multiple non-equivalent executable targets are ambiguous.

The resolver never follows a discovered page recursively. Remote content cannot add parsers, expand trusted budgets, load plugins, authorize credentials, or select arbitrary code. Provenance records the requested and resolved URLs, method, provider, operation, parsed board/posting identities, validated visited URLs, and bounded probed slugs; it excludes arbitrary headers, page bodies, unsafe query material, and raw exceptions.

### Provider operation matrix

Every built-in below receives an explicit board-target parser and full-board list hook. Capability output reports the exact implemented state rather than treating this table as a blanket guarantee.

| Provider | Full-board contract | Exact-posting contract | Interface evidence |
| --- | --- | --- | --- |
| Ashby | Preserve board response; listed-only default; optional `isListed: false` membership when supported and requested | Exact identity match from authoritative board result | Documented public board surface |
| BambooHR | Reconcile advertised membership and complete required public detail fan-out | Native public detail when exact identifiers are retained | Best-effort public careers surface |
| Consider Jobs | Traverse sequence/page termination and fail closed on incomplete membership | Native only if a supported URL retains board and exact job identity; otherwise truthful board-scan or list-only | Best-effort public board surface |
| Greenhouse | Complete documented board listing | Documented exact job-board endpoint | Documented public API |
| Lever | Traverse `skip`/`limit`, detect duplicates/repeated pages, and prove termination | Documented exact posting endpoint | Documented public postings API |
| Rippling | Preserve page/total/duplicate reconciliation | Existing public detail request when exact identifiers are retained | Best-effort public careers surface |
| Teamtailor | Traverse `offset`/`per_page`, detect duplicates/repeated pages, and prove termination | Exact match from authoritative board result | Best-effort public RSS/careers surface |
| Workable | Preserve cursor traversal; report aggregate detail coverage separately | Account plus exact shortcode/URL board-scan match; no authenticated SPI | Best-effort public careers surface |
| Workday | Preserve CXS offset/total/duplicate reconciliation | Public CXS detail when exact identifiers are retained | Best-effort public CXS surface |
| WP Job Manager | Preserve validated REST/AJAX pagination and membership evidence | Native REST item only for a proven numeric route; non-numeric hosted posting URLs remain unsupported until a typed target can retain exact identity plus board route | Best-effort public plugin surface |

Implementation-sensitive upstream evidence was re-checked on 2026-08-30:

- Ashby's official [Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) documents the single public board response, `includeCompensation`, hosted `jobUrl`, and `isListed: false` direct-link semantics. It does not document a separate exact-get endpoint, so exact Ashby get remains an authoritative board scan.
- Greenhouse's official [Job Board API](https://docs.greenhouse.io/job-board.html) documents unauthenticated list and exact-job GET endpoints, the unique posting `id`, and `content=true` for the complete list payload.
- Lever's official [Postings API](https://github.com/lever/postings-api) documents `skip`/`limit` list traversal and the exact `SITE/POSTING-ID` GET endpoint. OpenOpps additionally requires an observed terminal page and rejects repeated or duplicate evidence before calling a board complete.
- Teamtailor's official [RSS guide](https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide) documents the default 100-job window and `offset`/`per_page` controls. Because it does not specify a native exact-get contract or a separate advertised total, OpenOpps classifies the interface as best-effort and uses a bounded authoritative board scan.
- WP Job Manager's official [REST API note](https://wpjobmanager.com/document/advanced-usage/wp-job-manager-rest-api/) identifies the standard WordPress REST root at `/wp-json/wp/v2/job-listings`. Per-site exposure, AJAX fallbacks, and numeric item availability can vary, so the provider remains best-effort and advertises native get only for a proven numeric REST item route.
- Workable's official [`/jobs/:shortcode`](https://workable.readme.io/reference/jobsshortcode) reference belongs to its authenticated SPI and therefore does not authorize using credentials or claiming the anonymous hosted-careers endpoints as documented. The public collection/detail aggregation remains best-effort and exact get remains a complete board scan.
- The evidence review did not establish official public contracts for the browser-facing BambooHR, Consider Jobs, Rippling, or Workday CXS endpoints used here. Those providers remain explicitly best-effort even when deterministic fixtures prove OpenOpps' local parsing, bounding, and reconciliation behavior.

The user-supplied [`ats-jobs` Gist](https://gist.github.com/wyattowalsh/1415d657dfad77a52319cac904399c4a) is the ergonomic reference for URL-first list/get, bounded careers-page discovery, provider inspection, semantic terminal output, and machine-clean JSON/JSONL/table output. It is not treated as upstream provider authority or copied as a compatibility contract; OpenOpps retains its accepted provider matrix, storage lifecycle, plugins, error model, and existing CLI meanings.

Ordinary list requests use `listed` membership. `include_unlisted` is accepted only when the provider declares exact enumeration support; otherwise the CLI fails with an unsupported-capability error. An exact posting may return a direct/unlisted record only through a declared operation that retains and resolves the exact native posting identity.

### Complete-before-success list and exact get semantics

A list hook buffers or safely stages its bounded result until every required membership page and provider-required detail request has completed and validated. Membership authority and detail coverage are separate fields: optional missing detail can lower coverage without inventing a membership failure, while required detail failure makes the operation fail. Repeated or missing pages, inconsistent advertised totals, duplicate continuation, unsafe redirects, oversized responses, exhausted budgets, schema errors, or transport failures prevent authoritative membership.

Get prefers a declared native public exact operation. Otherwise, unless `--no-board-scan` is set, it runs the provider's full-board list hook and requires complete authoritative membership plus exactly one match under the provider's native identity rules. Zero matches, multiple matches, incomplete/non-authoritative results, or lost posting identity fail nonzero before success output or successful persistence.

### Shared transport, cache, and finite response handling

Resolver, list, and detail requests reuse the existing async HTTPX path, public-HTTPS destination policy, redirect validation, DNS/IP protections, timeouts, bounded concurrency, transient-only retry policy, and cache controls. Pull code does not instantiate a second client/cache stack. Provider execution binds one operation-scoped request and aggregate-decoded-byte budget inherited by bounded child tasks; the outer pull deadline covers resolution and provider validation but exits before any persistence transaction.

Plugin URL-pull hooks receive a least-authority HTTP facade whose supported API is limited to bounded public JSON/text GET and POST operations. Each facade captures and rebinds the exact active provider operation that created it, including across child task contexts, and rejects supported API calls after that operation closes. Plugins are installed, trusted in-process Python extensions rather than sandboxed code: the facade prevents accidental or ordinary API-level budget bypass, but Python reflection or a plugin importing its own networking stack is outside this threat boundary and would require a separate process/IPC isolation design.

The shared response reader adds trusted encoded and decoded byte ceilings. It rejects an oversized declared body before admission and stops streaming when either actual encoded bytes or decompressed/decoded bytes cross the configured ceiling. Careers resolution also has finite request, origin, redirect, page, probe, candidate, and wall-clock budgets; provider pagination/detail fan-out has finite request, aggregate-byte, cardinality, page, concurrency, retry, and deadline limits. Logical provider reads consume request budget before cache lookup, and retries plus redirects consume additional requests. Request, aggregate-byte, and per-response size failures latch their original typed cause for the whole provider operation, cancel admitted sibling reads, and remain terminal even if provider code catches the first exception. Stream admission and final provider validation recheck operation state so detached or cancellation-resistant work cannot produce post-close bytes, cache entries, results, or persistence. Exhaustion produces a bounded domain failure before persistence.

Cache identity includes namespace/schema version, operation, provider/native target, relevant page/cursor/request-body identity, listing-versus-detail role, and membership scope. Cached response validation has a final absolute-deadline barrier, and cache writes or 304 refreshes use an in-transaction deadline guard so a late operation rolls back rather than committing successful cache state. `--refresh-cache` bypasses reads and may write a validated fresh response. `--no-save` does not disable normal cache writes. Eligible stale-on-error use is visible in provenance and cannot confer authoritative membership or lifecycle reconciliation.

### One result contract and one renderer

Normal output serializes the normalized OpenOpps Job contract. Explicit `--raw` serializes a stable envelope containing sanitized pull provenance and per-posting `{listing, detail}` structured provider evidence. It preserves the parsed upstream evidence needed for audit and reprocessing but does not promise original transfer encodings, headers, whitespace, or byte-for-byte wire bodies.

Interactive terminals default to semantic Rich output. Non-interactive stdout defaults to normalized indented JSON. Explicit pretty, JSON, JSONL, and table modes share one renderer; file output uses an owned sibling temporary and atomic replace; paging is allowed only for interactive pretty output. Warnings, progress, cache/plugin notices, retries, verbosity diagnostics, quiet handling, and actionable failure hints use stderr. Machine stdout contains only result bytes.

Domain failures use a closed enum and a documented stable process-status mapping covering unsupported/unrecognized targets, ambiguity, missing exact posting, incomplete/non-authoritative evidence, safety rejection, budget/size exhaustion, transport/provider failures, and persistence failures. Click/Typer usage errors remain exit 2. Error tests freeze the chosen mapping before public CLI wiring.

### Opt-in persistence with an actually ephemeral default

After the storage gate opens, a successful pull persists only when the user selects `--save`. The CLI default remains `--save` False. `--no-save` (and the default) bypasses every operational persistence call and leaves sources, boards, routes, jobs, versions, observations, lifecycle state, `job_sync_runs`, and `url_pull_runs` unchanged. HTTP cache behavior remains independently controlled.

Saved URL-derived work uses one reserved internal `url-pull` source/board/route namespace required by current foreign keys. Identity derives from provider id, punctuation-preserving provider-native board identity, and a digest of canonical discovery material. Equivalent URLs converge; distinct native identities remain distinct. The reserved source has no catalog domain, is excluded from catalog selectors, never reuses or mutates a catalog route, and fails closed on collision with a non-owned row.

`url_pull_runs` is a separate audit domain. It stores bounded status/timestamps/error kind, requested/resolved operation, provider/native identities, sanitized provenance, membership/detail evidence, counts, and links to either a list's ordinary job-sync lifecycle or a get's exact job/version. It never repurposes `job_sync_runs` or planned O.1 `sync_invocations`, and never stores arbitrary headers, query strings, HTML, or raw exception text. A sanitized failed audit may be recorded only when saving is enabled; a failed pull does not synthesize a route solely for the audit and is never marked as a successful snapshot.

An authoritative list validates the entire fetch before entering one atomic lifecycle transaction. Jobs, versions, observations, run completion, and eligible closure commit together; bounded statements or owned staging may be used only when final promotion is atomic. Failure at any early or late batch leaves job lifecycle/current-version state unchanged. A point get upserts and versions exactly one posting, records `operation=get`, creates no `job_sync_run`, and never reconciles a route or closes another job.

Membership scope is persisted. Jobs are `listed` or `direct_only`; list snapshots are `listed` or `all_public`. A listed-only authoritative snapshot reconciles only listed membership. Direct-only jobs remain open, a later listed observation promotes them to listed, and only a provider-supported authoritative `all_public` snapshot may reconcile direct-only membership. Existing retirement timing and provider-terminal rules remain owned by the ingest goal.

### Storage gate and migration ownership

Contract, resolver, registry, provider, output, CLI, and no-save service work may proceed behind a frozen persistence interface. Schema/persistence implementation remains closed until the authoritative ingest task graph records both G3 closed and L.1 landed.

At that barrier the implementer must re-read the actual Alembic head, obtain the W-STORAGE path handoff, and reserve the next linear revision. No task in this change activates `0005_update_snapshot_ledger.py.draft` or assumes the next revision is `0006`. URL-pull model/copy-table edits serialize with L.1/L.2 and O.1. O.1 retains ownership of `sync_invocations`, source/route attempts, `job_sync_runs.invocation_id`, `runId`, and conservation metrics.

### Plugin participation is explicit and isolated

Plugins may optionally register typed target parsers and compatible list/native-get/unlisted operations tied to an existing provider factory. Validation checks parser/hook/capability consistency and deterministic conflicts. A legacy `job_provider` or route detector remains loadable but participates in no URL-pull operation it did not declare. Invalid/conflicting plugin hooks are observable and non-fatal for built-ins. The minimal example documents both the typed extension and the non-implication rule.

## Migration and rollback

The pre-storage portions are additive and can be rolled back by removing URL dispatch, typed registrations, and new modules without changing existing persisted data. Existing sync callers continue to use their current contracts.

After the storage gate, the new linear migration upgrades by adding the separately owned audit and membership-scope surfaces while preserving existing rows with safe defaults. Downgrade removes only URL-pull-owned schema after proving no cross-owned dependency. Update-snapshot copies and managed-table manifests change in the same serialized writer wave. Runtime code must tolerate only the current migrated schema; no speculative legacy dual path is added.

File output uses atomic replacement, and saved list application is transactional. Provider/network failure, process cancellation before commit, or migration failure leaves the previous ledger state valid. No rollback operation deletes catalog boards or routes.

## Parallel task graph and ownership

```text
B0 OpenSpec strict-valid
 |
 +--> B1 red tests + typed contracts
       |
       +--> H transport/limits --> R resolver --------+
       |                                              |
       +--> C registry/plugins --> P1..P10 providers -+--> S service/output --> CLI
       |                                              |                         |
       +----------------------------------------------+                         +--> DOCS
                                                                                      |
external G3 + L.1 + W-STORAGE handoff --> DB migration/storage/atomicity -------------+--> FULL
```

- One writer owns each shared contract group: provider base/registry, HTTP/settings, CLI, storage/models/migrations, OpenSpec, docs, and generated surfaces.
- Provider modules may fan out one writer per module only after typed contracts and registry validation freeze.
- CLI wiring begins only after service and renderer tests pass. Storage-backed CLI success begins only after the external migration join; no-save tests can proceed earlier against a null persistence port.
- Docs and nested-agent changes follow public API/file/schema stabilization. Generated web data changes only when an affected generator proves it necessary.
- Every dispatched lane resolves before its join. Existing untracked `.grok/`, `.playwright-mcp/`, and `inspect-shots/` paths remain untouched.

## Risks / Trade-offs

- Public ATS interfaces drift. Capability output exposes documented versus best-effort evidence, and deterministic fixtures prove OpenOpps behavior without claiming live availability.
- Lever and Teamtailor currently need explicit multi-page hardening before their full-board capability can be truthful.
- A complete board can be large. Atomic application may need owned staging, but visible lifecycle state cannot be partially advanced.
- Reserved operational identities may duplicate catalog-backed real-world boards by design. Cross-namespace merging is deferred because it changes ownership and lifecycle semantics.
- Bare URL rewriting changes root parsing. Regression tests must prove option values and unknown commands cannot be consumed as URLs.
- Stable raw structured evidence increases storage/output size. Provider-native evidence remains bounded and schema-controlled; transport byte budgets apply before parsing.
- The external storage gate may remain open after ephemeral functionality is ready. The CLI must not advertise default saved success until the schema/persistence join is actually complete, and the goal remains incomplete until that join passes.
