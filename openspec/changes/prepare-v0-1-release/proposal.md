## Summary

Prepare OpenOpps v0.1 as the first public ground-truth release of the local-first CLI. This change freezes the contract for the redesigned command surface, SQLite-backed caching, richer metadata capture, plugin extension seams, generated examples, provider coverage measurement, documentation, and release validation.

## Motivation

OpenOpps currently exposes many internal maintenance and diagnostic commands as first-class public CLI paths. The v0.1 release should feel like a coherent product: discover boards, inspect route readiness, sync jobs, filter/list data, export data, and understand local status. The release also needs stronger primitives for repeated network work, community extension, synthetic examples, and measured provider coverage gaps.

## Scope

- Redesign the public CLI around stable everyday workflows and move low-level commands behind advanced/admin/debug surfaces.
- Add observable SQLite-backed caching for source pages, route probes, provider job requests, and metadata enrichment.
- Preserve raw upstream payloads and promote useful source, board, route, and job metadata into normalized fields.
- Add a documented plugin architecture based on Python package entry points and validated OpenOpps-owned hooks/contracts.
- Add deterministic generated examples for docs, smoke tests, and invariant tests.
- Add board-level provider coverage metrics, including the measured percentage of boards with non-supported provider hints.
- Update README, docs, package instructions, and release validation artifacts to match v0.1.

## Non-Goals

- Do not add TUI, Textual, Rich prompt flows, browser UI, or web UI behavior.
- Do not add compatibility aliases for obsolete internal command paths unless a later approved release-compatibility requirement introduces them.
- Do not add hosted service behavior, authenticated scraping, browser automation, email alerts, user accounts, automated applications, or broad v1.0 stability guarantees.
- Do not claim plugin sandboxing; plugins execute normal installed Python code.

## Parallelization Strategy

The OpenSpec contract is the sequential freeze point. After validation, implementation should proceed through independent lanes for CLI, cache, plugins, provider coverage, metadata enrichment, generated examples, docs, and verification, with a single lead-owned integration pass for shared files.
