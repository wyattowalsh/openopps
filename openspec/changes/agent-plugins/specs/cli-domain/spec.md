## ADDED Requirements

### Requirement: Public CLI has no mcp command

OpenOpps SHALL NOT expose a public `openopps mcp` Typer command. Agent Plugins clients SHALL start the bundled `./bin/mcp` from the plugin package.

#### Scenario: User inspects CLI help

- **WHEN** the user runs `openopps --help`
- **THEN** the command list does not include `mcp`
- **AND** quarantined discovery remains on the advanced `discovery` / `admin sources` surface

### Requirement: Agent-driven CLI use respects the same discovery boundary

User-facing Agent Plugin `run` SHALL refuse `discovery` and the `admin sources` scout aliases. Contributor-facing Agent Plugin `run` SHALL allow only the three quarantined discovery commands.

#### Scenario: An agent tries to scout through the user plugin

- **WHEN** user MCP `run` receives `discovery scout` or `admin sources scout`
- **THEN** the runner refuses
- **AND** the public CLI command implementations are unchanged
