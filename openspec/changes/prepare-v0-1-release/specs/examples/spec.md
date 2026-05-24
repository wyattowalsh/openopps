## ADDED Requirements

### Requirement: Generated examples are deterministic

OpenOpps SHALL provide deterministic offline-friendly examples or smoke paths that let users see v0.1 behavior without relying on live provider endpoints.

#### Scenario: User seeds examples

- **WHEN** the user runs the approved example seed or smoke command
- **THEN** OpenOpps creates coherent synthetic sources, boards, provider routes, jobs, plugin metadata, cache records, and raw payloads
- **AND** repeated runs with the same seed are reproducible

### Requirement: Example data uses typed factories

Example data SHALL be built from typed dataclasses or equivalent factories and may use deterministic Faker seeds for realistic sample content.

#### Scenario: Test creates sample jobs

- **WHEN** tests or docs need representative records
- **THEN** they use the example factories rather than hand-written inconsistent records

### Requirement: Hypothesis strategies validate example invariants

OpenOpps SHALL use bounded Hypothesis strategies for generated example invariants where property-based tests provide better coverage than examples alone.

#### Scenario: Invariant test generates edge cases

- **WHEN** a Hypothesis-backed test generates example data across a range of deterministic seeds
- **THEN** OpenOpps preserves invariants such as unique board, route, and job identifiers

### Requirement: Docs examples do not drift

README and docs snippets for generated examples SHALL be reproducible from commands or golden outputs.

#### Scenario: Docs show generated output

- **WHEN** generated example output appears in README or docs
- **THEN** the repository contains a command or artifact that can reproduce it deterministically
