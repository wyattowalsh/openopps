## ADDED Requirements

### Requirement: Two Agent Plugins 1.0.0 packages exist in the repository tree

OpenOpps SHALL ship two Agent Plugins 1.0.0 packages named `openopps` and `openopps-dev` at `agent-plugins/openopps/` and `agent-plugins/openopps.dev/`.

#### Scenario: A client loads the user package

- **WHEN** a client opens `agent-plugins/openopps/plugin.json`
- **THEN** `name` is `openopps`
- **AND** `$schema` is `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`
- **AND** `version`, `description`, `license` (`MIT`), `homepage` (`https://www.openopps.dev/docs/agent-plugins`), and `repository` (`https://github.com/wyattowalsh/openopps`) are present
- **AND** `extensions` is omitted

#### Scenario: A client loads the contributor package

- **WHEN** a client opens `agent-plugins/openopps.dev/plugin.json`
- **THEN** `name` is `openopps-dev`
- **AND** the same schema, version, license, homepage, and repository fields are present
- **AND** `extensions` is omitted

### Requirement: Packages match the Agent Plugins standard layout

Each package SHALL contain `plugin.json` at the plugin root, a `skills/` directory of immediate children with regular-file `SKILL.md`, `mcp.json`, plugin-bundled `./bin/mcp`, and `LICENSE`. Plugin `name` values SHALL be kebab-case (`[a-z0-9]+(-[a-z0-9]+)*`) so Grok and Claude validators accept them. Each package SHALL also ship `.mcp.json` as a Grok/Claude stdio alias of `./bin/mcp` without `$schema`. Packages SHALL NOT contain client-extension directories or `com.*` folders.

#### Scenario: Layout is validated

- **WHEN** `scripts/verify_agent_plugins.py` runs
- **THEN** both roots contain the required files including `.mcp.json`
- **AND** every `skills/<dir>/` name equals that skill's frontmatter `name` in kebab-case
- **AND** plugin.json `name` values are kebab-case (`openopps`, `openopps-dev`)
- **AND** no `../` package paths or escaping symlinks exist
- **AND** `examples/plugins/` is not treated as an Agent Plugin

### Requirement: User plugin covers the public CLI except quarantined discovery

The `openopps` plugin SHALL teach the full public CLI except `openopps discovery *` and `admin sources scout`, `verify-scout`, and `preview-promotion`.

#### Scenario: User skills are present

- **WHEN** the user plugin `skills/` directory is listed
- **THEN** it contains hub `openopps` plus `openopps-url-pull`, `openopps-sync`, `openopps-jobs`, `openopps-boards`, `openopps-sources`, `openopps-providers`, `openopps-status`, `openopps-operations`, `openopps-admin`, and `openopps-web`
- **AND** each skill body includes a dispatch table and an empty-args handler
- **AND** descriptions include Use when triggers and NOT for exclusions

#### Scenario: Read-only public site companion

- **WHEN** an agent follows `openopps-web`
- **THEN** it may fetch public HTTPS pages under `https://www.openopps.dev` including `/`, `/explorer`, `/docs`, `/llms.txt`, `/llms-full.txt`, and `/llms.mdx/docs/...`
- **AND** it does not drive a browser, mutate the Next.js app, or call `/api/` or live Workers/Kaggle APIs

### Requirement: Contributor plugin owns discovery and source-scout SSOT

The `openopps-dev` plugin SHALL cover the source-scout skill, `openopps discovery scout|verify-scout|preview-promotion`, isolation via `launch_isolated_scout`, and contributor eval/frontmatter/projection gates. It SHALL NOT be a general contributing, OpenSpec, web, Kaggle, or Workers plugin.

#### Scenario: Source-scout SSOT location

- **WHEN** a contributor or gate looks up the portable source-scout skill
- **THEN** the SSOT is `agent-plugins/openopps.dev/skills/openopps-source-scout/`
- **AND** `skills/openopps-source-scout/` is absent
- **AND** selected `.agents/skills/openopps-source-scout/` and `.cursor/skills/openopps-source-scout/` remain absent
- **AND** plugin scripts do not run `wagents --apply` or a live harness install

#### Scenario: Contributor hub skill name

- **WHEN** the contributor hub skill is loaded
- **THEN** its directory and frontmatter `name` are `openopps-dev`
- **AND** the plugin manifest `name` is `openopps-dev` (kebab-case; Grok and Claude reject dotted names)

### Requirement: MCP is stdio help and run with inverse filters

Each plugin SHALL start MCP with `./bin/mcp` at `"cwd": "${PLUGIN_ROOT}"`. The server SHALL expose tools `help` and `run` only. Inner CLI resolution SHALL be `OPENOPPS_BIN`, then `openopps` on `PATH`, then `uv run openopps` in a checkout.

#### Scenario: User run deny-list

- **WHEN** user MCP `run` is called with `discovery` or `admin sources scout|verify-scout|preview-promotion`
- **THEN** the tool refuses without invoking those commands

#### Scenario: Contributor run allow-list

- **WHEN** contributor MCP `run` is called
- **THEN** it allows only `openopps discovery scout|verify-scout|preview-promotion`
- **AND** it prefers `--json`
- **AND** it rejects `sync` and every other command

#### Scenario: No hosted MCP and no public Typer MCP command

- **WHEN** `mcp.json` is validated
- **THEN** the server `type` is `stdio` and `command` is `./bin/mcp`
- **AND** `env.PLUGIN_ROOT` and `env.PLUGIN_DATA` are unset
- **AND** `sse` and `streamable-http` are absent
- **AND** the public OpenOpps CLI has no `mcp` command

### Requirement: Distribution is the repo tree plus a documented local path

v1 SHALL NOT add a public marketplace, npm package, or hosted MCP URL. Documentation MAY name local filesystem install commands (`grok plugin install`, Cursor `~/.cursor/plugins/local`, Codex/Claude local catalog add, OpenCode MCP/skills paths).

#### Scenario: A user installs the plugin in a client

- **WHEN** documentation describes installation
- **THEN** it names a local filesystem path under the OpenOpps checkout or documented copy
- **AND** it does not advertise a hosted marketplace identifier or hosted MCP URL

### Requirement: Discovery stays isolated from sync and live publication

Plugin skills SHALL NOT perform live Cloudflare, Kaggle, Alembic `0005`, or source-policy 1780 publication. Discovery SHALL NOT share a run with `openopps sync`.

#### Scenario: A contributor runs discovery through the plugin

- **WHEN** `openopps discovery scout` is invoked via the contributor plugin
- **THEN** the command does not apply, activate, or share a run with `openopps sync`
- **AND** fixture and eval scripts remain documented `uv run python` commands, not MCP tools
