## Summary

Finish the source-catalog expansion safely by adding complete Consider company-job and Workable ingestion, making packaged catalog configuration authoritative over stale stored configuration, and replacing oversized saved-search fingerprint responses with bounded saved-count requests.

## Motivation

The expanded catalog exposes three release-blocking gaps: Consider company boards are queried as portfolio boards, Workable ingestion returns only the first page while later closing missing jobs, and broad saved-search summaries exceed the production function payload limit. Stored source metadata can also keep corrected packaged routes inert.

## Scope

- Reconcile the consolidated source batch with exact URL and route-token identity.
- Add a distinct `consider_jobs` provider with complete, fail-closed pagination.
- Make Workable listing pagination complete and remove per-job detail fan-out.
- Resolve matching stored sources with packaged configuration precedence while retaining stored runtime metadata.
- Bound saved-search count traffic, preserve shared search-store caching, and make browser persistence transactional.
- Regenerate package-derived web data and validate production deployment.

## Non-goals

- Publishing a Python package or modifying a live production database.
- Browser automation or authenticated scraping.
- Treating partial provider pages as successful snapshots.

## Success criteria

1. Every packaged URL and key is unique and terminal dead sources are excluded.
2. Consider and Workable never close jobs after an incomplete fetch.
3. Packaged source fixes are effective for matching persisted sources.
4. Saved-search request and response bodies remain bounded and persistence failures do not create false UI state.
5. Local gates, built-wheel smoke, exact-SHA CI, both web deployments, and production smoke pass.
