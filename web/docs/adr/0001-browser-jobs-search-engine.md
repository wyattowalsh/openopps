# ADR 0001: Release-pinned browser jobs search

- Status: accepted
- Date: 2026-08-12
- Updated: 2026-08-31 (published v6 columnar jobs snapshot)
- Scope: OpenSpec `production-hardening-static-data-v7` tasks 0.6 and 4.4-4.6

## Context

The former `/api/jobs/search` implementation materialized every jobs chunk and
scanned the full corpus inside a Next.js request process. The checked-in v6
snapshot contains 88,800 rows in 89 chunks: about 83.8 MB of uncompressed job
JSON. That design duplicated a large cache per server instance, made cold
requests expensive, and was incompatible with a static-assets-first release.

The public jobs contract is broader than keyword search. It includes:

- narrow and `wide` substring query fields;
- fuzzy/subsequence source, provider, location, department, team, workplace,
  employment, and skill filters;
- open-only versus `includeAllIndexed` membership;
- salary interval overlap and inclusive posted-date ranges;
- OpenOpps relevance weighting with latest-observed tie breaking;
- stable clamped pagination; and
- complete saved-search counts using `first-seen-v1` cursors.

These rules are frozen by `jobs-search-engine-core.test.ts`. The existing
`filterAndSortJobs` implementation remains the semantic oracle.

## Options evaluated

### Pagefind 1.5.2 custom records

Pagefind's official Node API can create custom records with content, flat string
metadata, categorical string filters, and flat string sort values. Its browser
API searches lazily and supports those filters and sorts. This is attractive for
keyword bandwidth, but it cannot express OpenOpps' fuzzy/subsequence facet
matching, salary interval overlap, date ranges, narrow/wide field selection,
custom relevance ordering, or saved-count cursor rules. A second pass over all
candidate records would still be required, so Pagefind fails semantic parity and
was not latency-tested as a production candidate. It also emitted 12,045 files
for 12,000 records; a comparable one-fragment-per-job production build would
exceed the release's 18,000-file internal budget well before 88,800 records.

Official references:

- <https://pagefind.app/docs/node-api/>
- <https://pagefind.app/docs/api/>
- <https://pagefind.app/docs/filtering/>

### Dependency-free columnar postings plus bitsets

The selected engine builds integer posting lists for fuzzy facets, intersects
them through transient `Uint32Array` bitsets, then applies the unchanged oracle
predicate and ordering only to candidates. It runs in one dedicated browser Web
Worker per session. The worker resolves the mutable channel once, verifies and
pins its release, verifies every chunk through `OpenOppsSnapshotClient`, and
serves search, summaries, and saved counts. Abort messages are request-scoped.

## Reproducible benchmark

Run from `web/`:

```bash
pagefind_bench_dir="$(mktemp -d)"
npm install --prefix "$pagefind_bench_dir" --no-save pagefind@1.5.2
OPENOPPS_PAGEFIND_MODULE="$pagefind_bench_dir/node_modules/pagefind/lib/index.js" \
  pnpm dlx tsx@4.20.6 scripts/benchmark-jobs-search.ts
```

The deterministic modulo-v1 corpus contains 12,000 rows and five cases covering
open/latest, relevance paging, wide/all-indexed, fuzzy facets, and numeric/date
ranges. The script executes five warmups and 25 timed runs and prints JSON.

Measure end-to-end payload and retained-memory proxies against the committed
production corpus separately:

```bash
pnpm dlx tsx@4.20.6 scripts/measure-jobs-search-production.ts
```

Measured on Apple Silicon with Node 26.5.0 on 2026-08-12:

| Candidate | Semantic parity | Median | p95 | Additional index | Transfer / heap estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing full-scan oracle (five cold cases) | yes | 84.65 ms | 151.51 ms | none | 5,190,084-byte row JSON lower bound |
| Columnar/bitset worker (five cold cases) | yes | 76.97 ms | 84.32 ms | 486,696 bytes | 269,127-byte gzip row estimate + typed index |
| Columnar/bitset worker (five warm cases) | yes | 0.02 ms | 0.03 ms | shared above | shared above |
| Pagefind 1.5.2 | **no** | not applicable | not applicable | 4,125,064 bytes / 12,045 files | would require a full semantic post-pass |

Worker index construction was 38.68 ms for 12,000 rows. Pagefind custom-record
index construction was 1,926.42 ms; query latency was not treated as a viable
production metric after the required semantic-parity gate failed. Measurements are
comparative, not universal service-level guarantees; browser, CPU, corpus, and
cache state vary. The benchmark emits its corpus identity and all raw metrics so
future changes can be compared instead of relying on this snapshot.

The production measurement covers all 88,800 rows and 89 chunks, not just the
synthetic posting index. The current worker input is 83,803,459 raw bytes; a
deterministic gzip-level-9 proxy is 14,163,694 bytes. Its typed posting lists add
3,199,892 bytes. A Node process observed a 41,356,248-byte heap increase while
building that index, but this is explicitly not a browser heap guarantee because
GC timing, string representation, runtime, and concurrent load vary. The
serialized bytes plus typed-index bytes are the deterministic retained-memory
lower-bound proxies; actual browser heap can be materially higher.

The ordered-result cache is dual bounded: at most 48 entries and at most 250,000
retained row references across all entries (about 2,000,000 reference bytes at an
eight-byte proxy, excluding referenced row objects already owned by the worker).
Broad queries are evicted oldest-first to stay within this aggregate cap; a
deterministic test injects a 5,000-reference cap, fills eight broad 1,000-row
results, and proves only the five newest result arrays remain. The same tested
invariant is configured to 250,000 references in production.

## Decision

Use the dependency-free columnar/bitset Web Worker. Keep final predicate and
ordering logic shared with the semantic oracle. Retire the production server
scan: the stale-client route returns `410 browser_worker_required` and never
loads the corpus. No implicit server fallback is allowed.

The worker prefers the published columnar jobs snapshot under
`jobs/columnar/*.json` (search payload version 6, or 8 if a future bump is
required — never 7). Each file stores columns 0–14 and 17–21 as parallel
arrays (`layout: "columnar"`), including `descriptionSnippet` and
`skillTokens`. Closed rows remain so `includeAllIndexed` stays correct. T2
detail bodies are not a substitute for `descriptionSnippet`. The worker still
builds in-memory posting lists and bitsets from those inflated rows;
`jobs-search-engine-core.test.ts` remains the semantic oracle, including page-2.
Row-oriented `jobs/chunks/*.json` stay for T0 `latest.json` and explorer. Ordinary
HTTP content encoding can reduce wire bytes, but that is deployment-dependent;
the 14.16 MB gzip figure above is a local proxy, not a delivery guarantee. Fetch,
parse, filtering, and sort happen off the main thread; the release is pinned and
integrity-checked and the materialized rows are cached for the session.

## Consequences and safeguards

- Search, summaries, and saved counts share one immutable session snapshot.
- The main thread remains responsive during fetch, parse, filtering, and sort.
- One worker holds the row corpus rather than every server instance holding it.
- The route cannot silently regress to a production full scan.
- Cancellation rejects only the caller and sends a scoped cancel request.
- Candidate bitsets are an optimization; exact user-visible semantics remain
  controlled by `jobMatchesFilters` and `filterAndSortJobs`.
