## ADDED Requirements

### Requirement: Python plugins and Agent Plugins are distinct systems

OpenOpps SHALL keep Python `openopps.plugins` entry-point packages separate from Agent Plugins 1.0.0 filesystem packages.

#### Scenario: A contributor starts from the example Python plugin

- **WHEN** a contributor reads `examples/plugins/minimal-openopps-plugin/`
- **THEN** it remains a Python entry-point template for `openopps.plugins`
- **AND** it is not an Agent Plugins package (`plugin.json` / `mcp.json` / `./bin/mcp`)

#### Scenario: An agent loads OpenOpps Agent Plugins

- **WHEN** a client loads `agent-plugins/openopps/` or `agent-plugins/openopps.dev/`
- **THEN** those roots follow the Agent Plugins 1.0.0 layout
- **AND** they do not register through the `openopps.plugins` entry-point group
