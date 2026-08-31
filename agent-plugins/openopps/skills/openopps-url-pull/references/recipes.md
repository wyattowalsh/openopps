# URL pull recipes

```bash
openopps jobs pull https://boards.greenhouse.io/example --json
openopps https://jobs.ashbyhq.com/example --json
openopps jobs pull https://example.invalid/jobs --no-save --json
```

Same workflow for `openopps <url>` and `openopps jobs pull <url>`.
Fail closed on ambiguity. This is operational pull, not quarantined discovery.

## Shared flags

- Prefer `--json` so stdout stays machine-readable.
- `--help` is always safe.
- `--apply` is an explicit persist; dry-run first.
- `--metrics-json` is for sync/status metrics where the CLI supports it.
- Do not mix human diagnostics onto JSON stdout.
- Relative SQLite URLs follow process cwd.
- `OPENOPPS_BIN` overrides PATH when set.
- `OPENOPPS_DB_URL` selects the operational database.
- `OPENOPPS_DISCOVERY_NETWORK=disabled` is required for public CI and skill-eval.
- Do not commit `.env`.

## Refusals

- `openopps discovery scout|verify-scout|preview-promotion` unless this is the contributor discovery skill
- `admin sources scout|verify-scout|preview-promotion`
- `wagents --apply` and live harness install
- live Cloudflare Workers upload
- Kaggle mutation
- Alembic `0005`
- source-policy 1780 publication
- browser automation of the public site
- `/api/` including `/api/jobs/search`
- sharing discovery with `openopps sync` in the same run

## Environment notes

- Clients inject `PLUGIN_ROOT` and `PLUGIN_DATA`; do not put them in committed `mcp.json`.
- Inner CLI resolution is `OPENOPPS_BIN`, then `openopps` on PATH, then `uv run openopps` from a checkout.
- There is no public `openopps mcp` command.
- Python `openopps.plugins` under `examples/plugins/` is a different system.
- Source-scout SSOT is `agent-plugins/openopps.dev/skills/openopps-source-scout/`.
- Selected `.agents/skills/openopps-source-scout/` and `.cursor/skills/openopps-source-scout/` must stay absent.

## Validation

Repo CI does not require skill-creator. When that operator toolkit is present:

```text
uv run python scripts/check.py
uv run python scripts/audit.py skills/openopps-url-pull/
uv run python scripts/package.py skills/openopps-url-pull/ --dry-run
```

Repository smoke:

```bash
just agent-plugins-check
uv run pytest tests/unit/openopps/test_agent_plugins.py tests/unit/openopps/discovery/test_source_scout_skill.py -q
```

Completion criteria: those commands must pass with zero errors before declaring this skill complete. Live Cursor/Codex/Grok loader e2e is out of v1.
