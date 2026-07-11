# plugins Specification

## Purpose
Define plugin discovery, validated hooks, failure isolation, and observable capability reporting for OpenOpps extensions.
## Requirements
### Requirement: Plugins are discovered through entry points

OpenOpps SHALL discover installed plugins through documented Python package entry points.

#### Scenario: Plugin distribution is installed

- **WHEN** an installed distribution exposes the approved OpenOpps entry-point group
- **THEN** OpenOpps can discover the plugin metadata and contribution object

### Requirement: Plugin failures are non-fatal for built-ins

Plugin import failures, validation errors, duplicate capabilities, blocked plugins, and registration warnings SHALL not prevent built-in OpenOpps functionality from running.

#### Scenario: Plugin import raises

- **WHEN** a plugin raises during import or registration
- **THEN** OpenOpps reports the plugin load failure through plugin inspection, status, or doctor output
- **AND** packaged source and provider adapters remain available

### Requirement: Plugin capabilities and conflicts are observable

OpenOpps SHALL report plugin names, versions, capabilities, conflicts, disabled state, allow-list state, load failures, and warnings through plugin-inspection output and status or doctor output.

#### Scenario: Two plugins claim same capability

- **WHEN** two plugin contributions conflict under the approved capability namespace rules
- **THEN** OpenOpps resolves or blocks the conflict deterministically
- **AND** reports the conflict in structured output

### Requirement: Example plugin demonstrates extension seams

OpenOpps SHALL include a small plugin template or example plugin showing the approved entry-point metadata and at least one source/provider-style contribution.

#### Scenario: Contributor starts from the example

- **WHEN** a contributor reads the example plugin
- **THEN** it shows the minimal package metadata and contribution function needed to integrate with OpenOpps