## ADDED Requirements

### Requirement: Saved-search counts remain bounded

The web jobs board SHALL refresh saved-search counts without transferring the complete result membership or fingerprint set.

#### Scenario: A search matches the full dataset

- **WHEN** the saved search is refreshed
- **THEN** request and response stay within explicit API budgets
- **AND** refresh work is batched, deduplicated, and abortable

### Requirement: Saved-search persistence is transactional

The web jobs board SHALL update visible saved-search state only after its IndexedDB transaction succeeds.

#### Scenario: Storage aborts or exceeds quota

- **WHEN** a saved-search mutation fails
- **THEN** prior persisted and visible state remains authoritative
- **AND** the failure is handled without an unhandled rejection or partial replace import
