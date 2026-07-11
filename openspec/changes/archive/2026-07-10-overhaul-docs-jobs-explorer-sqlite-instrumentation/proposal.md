## Summary

Overhaul OpenOpps exports, docs search artifacts, jobs/explorer routes, and telemetry instrumentation so the docs site becomes a compact data workbench backed by generated SQLite snapshot metadata.

## Motivation

The current docs site exposes jobs, explorer, and count surfaces through partially overlapping generated assets and prose. SQLite is already central to OpenOppsDB but is not available as a first-class CLI export format. The docs app also lacks first-party telemetry despite being the primary interactive surface for public job exploration.

## Scope

- Add SQLite as a filtered export format and add a full local SQLite snapshot export command.
- Extend the generated docs search index to manifest v4 with count provenance, facets, suggestions, dashboard aggregates, and richer job detail shards.
- Move the jobs workbench to `/`, move the analytics explorer to `/explorer`, and remove stale `/jobs` and `/docs/explorer` routes.
- Restructure docs around start, CLI, configuration, data model, providers, operations, and contributing pages.
- Add first-party telemetry with a no-op default and local event-lake sink for zero-cost operation.

## Non-Goals

- Do not add accounts, hosted application flows, prompt flows, TUI flows, or automatic job applications.
- Do not require a paid analytics vendor.
- Do not add compatibility redirects for the hard route move.
- Do not parallelize SQLite writes into a single database.

## Parallelization Strategy

Freeze OpenSpec and generated data contracts first. Then split implementation across non-overlapping lanes for Python export/CLI, search-index generation, TypeScript search contracts, jobs UI, explorer dashboard, docs IA, design tokens, telemetry, and validation. Keep shared generated artifacts and package lock updates serialized.
