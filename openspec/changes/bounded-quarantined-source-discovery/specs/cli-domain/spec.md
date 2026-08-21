## ADDED Requirements

### Requirement: Quarantined discovery is an explicit advanced CLI workflow

OpenOpps SHALL expose source and board scouting under the advanced `admin sources` surface without adding discovery controls to the everyday sync path.

#### Scenario: A maintainer runs the scout

- **WHEN** the maintainer runs `openopps admin sources scout --output <directory> --json`
- **THEN** the command requires an explicit quarantine output directory
- **AND** emits clean machine-readable run status
- **AND** performs no SQLite, catalog, generated-data, release, Git, or deployment mutation

#### Scenario: A user inspects default help

- **WHEN** the user runs `openopps --help` or an everyday sync command
- **THEN** the normal source, board, and job workflow remains primary
- **AND** no same-run activation, prompt, TUI, browser automation, or hosted discovery flow is advertised

### Requirement: Quarantine verification is offline and read-only

OpenOpps SHALL provide an offline advanced command for exact quarantine-bundle verification.

#### Scenario: A maintainer verifies a bundle

- **WHEN** the maintainer runs `openopps admin sources verify-scout <manifest> --json`
- **THEN** the command validates canonical bytes, root identity, exact members, paths, hashes, sizes, schema, and run state without network access
- **AND** stdout contains only parseable JSON
- **AND** the command does not rewrite or repair the bundle

#### Scenario: Verification fails

- **WHEN** any manifest or member contract is invalid
- **THEN** the command exits nonzero with bounded structured errors
- **AND** does not partially accept or promote candidates

### Requirement: Scout commands do not promote

OpenOpps SHALL keep repository promotion outside scout and verification command execution.

#### Scenario: A scout finds an eligible candidate

- **WHEN** the scout or verifier reports `eligible_for_review`
- **THEN** no CLI apply option adds the candidate to the catalog
- **AND** help directs maintainers to the separate dry-run-first repository promotion workflow
