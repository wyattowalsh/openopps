## Overview

OpenOpps v0.1 becomes a polished CLI-only release. The visible product flow is: discover boards, inspect provider readiness, sync jobs, search/list records, export records, and inspect local status. Advanced diagnostics remain available, but they are no longer presented as the primary user journey.

## CLI Design

Stable commands emphasize everyday workflows: source discovery/sync, board list/show/export, job sync/list/show/export, provider coverage/health, cache inspection, plugin inspection, generated examples, and status/doctor. Low-level mutation and maintenance commands move behind `admin`, `debug`, or equivalently explicit advanced surfaces.

JSON mode remains a strict machine-readable channel. Human tables, warnings, cache notices, plugin load notices, and progress output must not contaminate JSON stdout.

## Cache Design

The cache is owned by OpenOpps and stored in SQLite so it is observable and testable. Cache keys are deterministic and include method, normalized URL, namespace, schema version, provider/source/route identity, relevant query/body values, and response-affecting headers. Records preserve response status, selected headers, ETag, Last-Modified, content hash, fetched/expires timestamps, stale-on-error eligibility, duration, and payload.

Explicit refresh bypasses cache reads while still allowing successful fresh responses to update the cache. Stale-on-error only applies to safe read paths and must be visible in metrics/status. Health checks should either bypass cache by default or clearly report cached/stale use.

## Plugin Design

Plugins are discovered through documented Python package entry points. Core OpenOpps owns the public plugin models and hooks. Hooks are versioned and validated so plugins can extend source adapters, job-provider adapters, route detectors, metadata enrichers, cache policy contributors, export contributors, and CLI command contributors without monkey-patching internals.

Plugin failures are non-fatal for built-ins. Status, doctor, and plugin-inspection output report plugin metadata, capabilities, conflicts, disabled/blocked plugins, validation errors, import errors, and warnings.

## Metadata Design

Raw upstream source, board, route, and job payloads remain preserved for auditability. v0.1 promotes useful reusable fields into normalized records only when they improve filtering, display, export, status, or diagnostics. Automatic enrichment uses source payloads, provider route pages, and job payloads; broad bespoke company website scraping remains out of scope.

## Provider Coverage Design

Coverage reports use board-level metrics. The main denominator is distinct persisted boards in the report scope. The primary non-supported numerator is distinct boards with any non-supported provider hint. Reports also distinguish job-capable baseline providers, adopted v0.1 providers, detect-only providers, unsupported or unknown providers, only-non-supported boards, and missing executable route metadata.

Provider adoption decisions require evidence that route discovery and job fetching are generic and public. Rejected candidate providers get recorded do-not-adopt rationale.

## Example Data Design

Generated examples use typed factories or dataclasses plus deterministic Faker seeds. Bounded Hypothesis coverage validates generated example invariants across deterministic seeds. Example outputs used in README/docs should be reproducible from commands or golden outputs.

## Implementation Topology

Implementation should follow the approved build plan in `goals/openopps-v0-1/build-plan.md`: contract freeze, independent build lanes, lead-owned integration, hardening, and release validation.
