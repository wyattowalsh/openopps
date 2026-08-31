## ADDED Requirements

### Requirement: Agent Plugins packages are schema-validated in the Python CI lane

OpenOpps SHALL vendor Agent Plugins 1.0.0 `plugin.schema.json` and `mcp.schema.json` under `tests/fixtures/agent-plugins/schemas/1.0.0/` and validate both package manifests locally. `just agent-plugins-check` SHALL run as part of `just ci-python` rather than as a new GitHub Actions job.

#### Scenario: Contributor runs the Python release gate

- **WHEN** a contributor runs `just ci-python`
- **THEN** `just agent-plugins-check` runs
- **AND** it invokes `uv run python scripts/verify_agent_plugins.py` and the Agent Plugins unit tests
- **AND** GitHub Actions still has the existing job set without a dedicated agent-plugins job

#### Scenario: Discovery skill evals after the SSOT move

- **WHEN** `just ci-discovery` or `source_discovery_gates.py skill-eval` runs
- **THEN** eval, frontmatter, dry-run projection, and docs-steward scripts target `agent-plugins/openopps.dev/skills/openopps-source-scout/`
- **AND** `OPENOPPS_DISCOVERY_NETWORK` remains `disabled`
- **AND** live Cursor/Codex/Grok loader e2e is not required
