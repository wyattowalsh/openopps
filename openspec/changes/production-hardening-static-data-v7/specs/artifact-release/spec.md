## ADDED Requirements

### Requirement: Public releases are content-addressed and exactly verifiable

OpenOpps SHALL publish a canonical v7 manifest whose root identifies the exact safe file set, bytes, types, roles/counts, provenance, and snapshot time.

#### Scenario: Any byte or graph edge changes

- **WHEN** a file is modified, missing, duplicate, case-colliding, extra, symlinked, or unsafe
- **THEN** exact verification fails before promotion

### Requirement: Generation and promotion are atomic

OpenOpps SHALL generate in an owned sibling candidate, validate it completely, and atomically promote only an accepted target or channel.

#### Scenario: Generation fails mid-write

- **WHEN** generation is interrupted
- **THEN** the prior promoted release remains byte-identical and usable
- **AND** no channel resolves the partial candidate

### Requirement: Publication is freshness and rights gated

OpenOpps SHALL reject ordinary promotion for an over-age snapshot or any included source without an allowed rights state.

#### Scenario: Degraded freshness is explicitly authorized

- **WHEN** an auditable degraded override is supplied
- **THEN** the reason and age are public
- **AND** rights, privacy, secret, and integrity gates remain non-bypassable

### Requirement: Current and previous releases are independently recoverable

OpenOpps SHALL retain exact current and previous bytes in the serving version and an independent content-addressed archive.

#### Scenario: Production rolls back

- **WHEN** the previous release is restored
- **THEN** channel, manifest, every asset, and web critical path verify against that root
