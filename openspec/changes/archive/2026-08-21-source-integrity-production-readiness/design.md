## Decisions

### Provider separation

`consider` remains a portfolio source adapter. Company board URLs use `consider_jobs`; a provider-neutral parser determines URL mode and exact token identity.

### Complete snapshots

Consider and Workable buffer a route and either return all validated jobs or raise. Later-page failures, cursor loops, malformed payloads, and unsafe URLs are incomplete snapshots and cannot trigger `close_missing=True`. Workable v3 listings are authoritative; one aggregate details response is optional enrichment.

### Stored source precedence

When stored and packaged records share key, URL, and provider, metadata is `stored | packaged`. Unknown stored runtime keys survive, but packaged configuration wins and a changed effective configuration clears freshness. A different stored URL or provider remains a local override.

### Saved-search production bounds

The web API does not transfer full result membership. Count requests are batched and capped, shared search-store builds are not owned by a caller abort signal, and browser state changes only after IndexedDB transaction completion. Legacy saved records remain readable but require explicit review when their baseline cannot be represented safely.

### Release

Changes land as atomic commits on `main`. Because feature-branch CI is not automatic and this checkout is already on `main`, local full gates precede the push; the resulting main CI and both Vercel deployments are monitored for the exact SHA. Rollback uses ordinary revert commits.

## Failure rules

- An inconclusive zero-result Consider page is unhealthy, not authoritative empty data.
- Any affected persisted rows requiring destructive migration stop release for explicit approval.
- Generated data is accepted only when a second generation produces no drift.
