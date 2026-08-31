## ADDED Requirements

### Requirement: Agent Plugins are documented on the public docs site

OpenOpps SHALL publish a dedicated docs page at `/docs/agent-plugins` that describes both Agent Plugins packages, local client paths, MCP `help`/`run` filters, and the distinction from Python `openopps.plugins`.

#### Scenario: A user opens the Agent Plugins docs page

- **WHEN** a user visits `/docs/agent-plugins`
- **THEN** the page names `agent-plugins/openopps/` and `agent-plugins/openopps.dev/`
- **AND** it documents local filesystem install rather than a marketplace
- **AND** it states that user MCP refuses discovery and that contributor MCP allows only the three discovery commands
- **AND** the page is in the docs content graph and sitemap `DOC_ROUTES`

### Requirement: User plugin SHALL teach the public site as read-only

The `openopps` Agent Plugin SHALL include skills that teach https://www.openopps.dev routes and llm-text URLs as a read-only companion.

#### Scenario: An agent follows the web skill

- **WHEN** the agent uses `openopps-web`
- **THEN** it treats `/`, `/explorer`, `/docs`, `/llms.txt`, `/llms-full.txt`, and `/llms.mdx/` as read-only public URLs
- **AND** it does not call `/api/jobs/search` or other `/api/` routes
- **AND** it does not mutate the Next.js app or live Workers/Kaggle
