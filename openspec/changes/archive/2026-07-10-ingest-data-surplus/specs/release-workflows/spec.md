## ADDED Requirements

### Requirement: Docs search index uses tiered committed artifacts

OpenOpps SHALL publish the public jobs and explorer search surface from committed static artifacts generated from the local SQLite snapshot, using tiered detail shards to bound repository size and public payload exposure.

#### Scenario: Maintainer refreshes the committed search index

- **WHEN** a maintainer runs `just docs-search-index-check` with `kaggle/openoppsdb.sqlite` available
- **THEN** the recipe regenerates `docs/public/data/openopps-search/`
- **AND** the recipe fails if regenerated artifacts differ from the committed tree.

#### Scenario: Public detail shards are written

- **WHEN** the docs search index is generated
- **THEN** open jobs receive metadata detail shards
- **AND** indexable jobs may receive bounded plain-text body shards
- **AND** raw payload snapshots are not committed to the public search index.

### Requirement: Docs search generated text is safe for browser indexing

OpenOpps SHALL convert provider description HTML into bounded plain text before publishing committed docs search detail artifacts.

#### Scenario: HTML descriptions are indexed

- **WHEN** provider descriptions contain HTML tags, encoded entities, spreadsheet export markup, or malformed tag fragments
- **THEN** generated docs search snippets and detail body text remove markup debris
- **AND** text-like comparison operators such as `<60` or `>1GB` remain searchable content.

#### Scenario: Search index schema is validated in CI

- **WHEN** GitHub Actions runs the docs validation job
- **THEN** CI validates the committed search index schema without regenerating the local SQLite-backed snapshot
- **AND** maintainer-only regeneration remains covered by the local docs search index check.
