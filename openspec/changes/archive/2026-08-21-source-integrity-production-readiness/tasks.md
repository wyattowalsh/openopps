# source-integrity-production-readiness - tasks

- [x] Add strict Consider route parsing, `consider_jobs`, complete pagination, probing, and closure-safety tests.
- [x] Add complete Workable pagination, shared throttling/client behavior, one-shot enrichment, and failure-safety tests.
- [x] Add effective stored/catalog source resolution across sync, health, probe, and CLI paths.
- [x] Repair packaged Consider metadata, remove terminal dead sources, and recompute catalog fingerprint.
- [x] Replace unbounded saved-search summaries and cache bypass with bounded, abort-safe behavior.
- [x] Make local saved-search writes/imports transactional with upgrade and failure coverage.
- [x] Regenerate package-derived web data and prove deterministic output.
- [x] Run focused Python and web gates, OpenSpec validation, and CLI integration tests.
- [x] Wheel smoke, main CI on origin, both deployments, and production smoke (maintainer/release path).
