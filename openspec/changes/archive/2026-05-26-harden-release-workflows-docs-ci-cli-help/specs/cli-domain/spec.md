## ADDED Requirements

### Requirement: CLI help is user-friendly and test-covered

OpenOpps SHALL keep root and command-group help focused, workflow-oriented, and covered by semantic tests.

#### Scenario: User opens root help

- **WHEN** the user runs `openopps --help`
- **THEN** help presents the everyday workflow before operational and advanced admin surfaces
- **AND** it includes a concise first-run path through status, sync, provider coverage, and job listing
- **AND** it points automation users to JSON or metrics JSON output

#### Scenario: Help text changes

- **WHEN** CLI help copy, group descriptions, or examples change
- **THEN** tests assert the stable user-facing semantics without relying on full terminal snapshots or exact line wrapping
