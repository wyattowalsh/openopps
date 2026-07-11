# examples Specification

## Purpose
Define deterministic generated example data and bounded property tests that demonstrate v0.1 CLI behavior without live provider dependencies.
## Requirements
### Requirement: Generated examples are deterministic

OpenOpps SHALL provide deterministic offline-friendly examples or smoke paths that let users see v0.1 behavior without relying on live provider endpoints.

#### Scenario: User seeds examples

- **WHEN** the user runs the approved example seed or smoke command
- **THEN** OpenOpps creates coherent synthetic sources, boards, provider routes, jobs, plugin metadata, cache records, and raw payloads
- **AND** repeated runs with the same seed are reproducible

### Requirement: Hypothesis strategies validate example invariants

OpenOpps SHALL use bounded Hypothesis strategies for generated example invariants where property-based tests provide better coverage than examples alone.

#### Scenario: Invariant test generates edge cases

- **WHEN** a Hypothesis-backed test generates example data across a range of deterministic seeds
- **THEN** OpenOpps preserves invariants such as unique board, route, and job identifiers