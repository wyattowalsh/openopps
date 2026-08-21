## ADDED Requirements

### Requirement: Packaged configuration repairs matching stored sources

OpenOpps SHALL apply current packaged configuration to a stored source with the same key, URL, and provider without discarding unknown stored runtime metadata.

#### Scenario: Packaged route metadata changes

- **WHEN** stored identity matches but configuration metadata is stale
- **THEN** packaged metadata wins in sync, health, probe, and CLI views
- **AND** freshness is cleared so the corrected route is evaluated

### Requirement: Source catalogs remain exactly accountable

OpenOpps SHALL enforce unique exact URLs and keys and exclude sources with repeated terminal evidence.

#### Scenario: Catalog generation completes

- **WHEN** the packaged catalog is loaded or built into a wheel
- **THEN** count, fingerprint, runtime catalog, generated web data, and wheel resources agree
