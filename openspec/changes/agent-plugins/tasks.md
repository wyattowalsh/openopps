# agent-plugins - tasks

Execution follows `goals/agent-plugins/task-graph.yaml`. Exclusive lanes never overlap writers.

## G0 — Contract freeze

- [x] T001 OpenSpec change `openspec/changes/agent-plugins/` (proposal, design, tasks, spec deltas)
- [x] T002 Vendor `plugin.schema.json` and `mcp.schema.json` 1.0.0; add `scripts/verify_agent_plugins.py`
- [x] T003 Red tests `tests/unit/openopps/test_agent_plugins.py` for layout, names, filters, no extension dirs

## G1 — Packages + MCP runners

- [x] T010 Scaffold `agent-plugins/openopps/` (`plugin.json`, `mcp.json`, `LICENSE`, `./bin/mcp` user deny-list)
- [x] T011 Scaffold `agent-plugins/openopps.dev/` (`plugin.json`, `mcp.json`, `LICENSE`, `./bin/mcp` discovery allow-list)
- [x] T012 Green schema + filter unit tests for both runners
- [x] T013 `verify_agent_plugins.py` passes on both roots once skills land (G3)

## G2 — Source-scout SSOT move

- [x] T020 Move `skills/openopps-source-scout/` into the contributor plugin; walk to `pyproject.toml`
- [x] T021 Retarget `scripts/source_discovery_gates.py` and `tests/unit/openopps/discovery/test_source_scout_skill.py`; projections stay absent
- [x] T022 skill-creator Develop (existing) on moved source-scout; keep inert; fix S718/parents docs

## G3 — Skills

User plugin:

- [x] T030 `openopps` hub
- [x] T031 `openopps-url-pull`
- [x] T032 `openopps-sync`
- [x] T033 `openopps-jobs`
- [x] T034 `openopps-boards`
- [x] T035 `openopps-sources`
- [x] T036 `openopps-providers`
- [x] T037 `openopps-status`
- [x] T038 `openopps-operations`
- [x] T039 `openopps-admin`
- [x] T040 `openopps-web`

Contributor plugin:

- [x] T041 `openopps-dev` hub
- [x] T042 `openopps-discovery`
- [x] T043 `openopps-isolation`
- [x] T044 `openopps-discovery-evals`

## G4 — Docs + CI

- [x] T050 `agent-plugins.mdx` + `meta.json` + sitemap + README + AGENTS + contributing/cli/operations
- [x] T051 `just agent-plugins-check` folded into `just ci-python`; governance tests
- [x] T052 Skill presence, descriptions, dispatch/empty-args, web URL, deny/allow string tests

## G5 — Audit join

- [x] T060 skill-creator Audit each new skill; Security Audit source-scout + isolation (operator-local)
- [x] T061 `just agent-plugins-check` and `just ci-discovery`
- [x] T062 OpenSpec `--strict`; docs-steward skip via moved `resolve_docs_steward.py`
