from __future__ import annotations

from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types

import pytest

from verify_agent_plugins import (
    DEV_ROOT,
    DEV_SKILLS,
    MCP_SCHEMA_ID,
    PLUGIN_SCHEMA_ID,
    USER_ROOT,
    USER_SKILLS,
    SchemaError,
    load_json,
    validate_instance,
    verify,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_PATH = REPO_ROOT / "src" / "openopps" / "cli.py"
EXAMPLE_PLUGIN = REPO_ROOT / "examples" / "plugins" / "minimal-openopps-plugin"


def _load_mcp(root: Path, module_name: str) -> types.ModuleType:
    path = root / "bin" / "mcp"
    loader = SourceFileLoader(module_name, str(path))
    module = types.ModuleType(module_name)
    loader.exec_module(module)
    return module


def test_vendored_schemas_match_published_ids() -> None:
    plugin_schema = load_json(
        REPO_ROOT / "tests/fixtures/agent-plugins/schemas/1.0.0/plugin.schema.json"
    )
    mcp_schema = load_json(
        REPO_ROOT / "tests/fixtures/agent-plugins/schemas/1.0.0/mcp.schema.json"
    )
    assert plugin_schema["$id"] == PLUGIN_SCHEMA_ID
    assert mcp_schema["$id"] == MCP_SCHEMA_ID
    assert plugin_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert mcp_schema["additionalProperties"] is False
    assert "PLUGIN_ROOT" in json.dumps(mcp_schema)


def test_schema_validator_rejects_unknown_plugin_fields_and_reserved_env() -> None:
    plugin_schema = load_json(
        REPO_ROOT / "tests/fixtures/agent-plugins/schemas/1.0.0/plugin.schema.json"
    )
    mcp_schema = load_json(
        REPO_ROOT / "tests/fixtures/agent-plugins/schemas/1.0.0/mcp.schema.json"
    )
    with pytest.raises(SchemaError):
        validate_instance(
            {"$schema": PLUGIN_SCHEMA_ID, "name": "openopps", "extra": True},
            plugin_schema,
            plugin_schema,
        )
    with pytest.raises(SchemaError):
        validate_instance(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "openopps": {
                        "type": "stdio",
                        "command": "./bin/mcp",
                        "env": {"PLUGIN_ROOT": "/tmp"},
                    }
                },
            },
            mcp_schema,
            mcp_schema,
        )


def test_packages_are_schema_valid_without_extension_dirs() -> None:
    payload = verify()
    assert payload["ok"] is True
    names = {row["name"] for row in payload["packages"]}
    assert names == {"openopps", "openopps-dev"}
    for root in (USER_ROOT, DEV_ROOT):
        plugin = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        mcp = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
        assert "extensions" not in plugin
        assert plugin["$schema"] == PLUGIN_SCHEMA_ID
        assert plugin["license"] == "MIT"
        assert plugin["homepage"] == "https://www.openopps.dev/docs/agent-plugins"
        assert plugin["repository"] == "https://github.com/wyattowalsh/openopps"
        assert "." not in plugin["name"]
        grok_mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        assert "$schema" not in grok_mcp
        assert grok_mcp["mcpServers"].keys() == mcp["mcpServers"].keys()
        server = next(iter(mcp["mcpServers"].values()))
        assert server["type"] == "stdio"
        assert server["command"] == "./bin/mcp"
        assert server["cwd"] == "${PLUGIN_ROOT}"
        assert "env" not in server
        assert server.get("type") not in {"sse", "streamable-http"}
        children = {path.name for path in root.iterdir() if path.is_dir()}
        assert not any(name.startswith("com.") for name in children)
        for forbidden in (
            "claude-code",
            "codex",
            "cursor",
            "gemini-cli",
            "github-copilot",
            "opencode",
            "windsurf",
        ):
            assert forbidden not in children
        mcp_bin = root / "bin" / "mcp"
        assert mcp_bin.is_file() and not mcp_bin.is_symlink()
        assert mcp_bin.stat().st_mode & stat.S_IXUSR
        assert mcp_bin.read_bytes().startswith(b"#!/usr/bin/env python3")


def test_examples_plugins_remain_python_entry_points() -> None:
    assert EXAMPLE_PLUGIN.is_dir()
    assert not (EXAMPLE_PLUGIN / "plugin.json").exists()
    assert not (EXAMPLE_PLUGIN / "mcp.json").exists()
    pyproject = (EXAMPLE_PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    assert "openopps.plugins" in pyproject


def test_public_cli_has_no_mcp_command() -> None:
    text = CLI_PATH.read_text(encoding="utf-8")
    assert '@app.command(\n    "mcp"' not in text
    assert '@app.command("mcp"' not in text
    assert 'name="mcp"' not in text
    result = subprocess.run(
        [sys.executable, "-c", "from openopps.cli import app; print([cmd.name for cmd in app.registered_commands] + [group.name for group in app.registered_groups])"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    names = result.stdout.strip().strip("[]")
    assert "mcp" not in {item.strip(" '\"") for item in names.split(",")}


def test_user_run_denies_discovery_and_admin_scout_aliases() -> None:
    mcp = _load_mcp(USER_ROOT, "openopps_user_mcp")
    assert mcp.load_plugin_name(USER_ROOT) == "openopps"
    denied = [
        ["discovery"],
        ["discovery", "scout"],
        ["discovery", "verify-scout", "--json"],
        ["discovery", "preview-promotion"],
        ["admin", "sources", "scout"],
        ["admin", "sources", "verify-scout"],
        ["admin", "sources", "preview-promotion", "--json"],
        ["openopps", "discovery", "scout"],
    ]
    for argv in denied:
        message = mcp.user_run_refusal(argv)
        assert message is not None, argv
        assert "quarantined" in message
    for argv in (
        ["status", "--json"],
        ["jobs", "list"],
        ["sync"],
        ["jobs", "pull", "https://boards.greenhouse.io/example"],
        ["admin", "db", "status"],
        ["admin", "sources", "list"],
        ["admin", "cache", "purge"],
    ):
        assert mcp.user_run_refusal(argv) is None, argv


def test_dev_run_allows_only_discovery_json_commands() -> None:
    mcp = _load_mcp(DEV_ROOT, "openopps_dev_mcp")
    assert mcp.load_plugin_name(DEV_ROOT) == "openopps-dev"
    for argv in (
        ["discovery", "scout", "--output", "/tmp/q"],
        ["discovery", "verify-scout", "manifest.json"],
        ["openopps", "discovery", "preview-promotion"],
        ["--verbose", "discovery", "scout"],
    ):
        assert mcp.dev_run_refusal(argv) is None, argv
        preferred = mcp.prefer_json_argv(argv)
        assert "--json" in preferred
    for argv in (
        ["sync"],
        ["jobs", "list"],
        ["status"],
        ["admin", "sources", "scout"],
        ["discovery"],
        ["discovery", "apply"],
        [],
    ):
        message = mcp.dev_run_refusal(argv)
        assert message is not None, argv
        assert "allows only" in message


def test_mcp_exposes_only_help_and_run_tools() -> None:
    user = _load_mcp(USER_ROOT, "openopps_user_mcp_tools")
    dev = _load_mcp(DEV_ROOT, "openopps_dev_mcp_tools")
    user_tools = {tool["name"]: tool for tool in user.tools_list("openopps")}
    dev_tools = {tool["name"]: tool for tool in dev.tools_list("openopps-dev")}
    assert set(user_tools) == {"help", "run"}
    assert set(dev_tools) == {"help", "run"}
    assert "discovery" not in user_tools["run"]["description"].lower() or "refuses discovery" in user_tools["run"]["description"].lower()
    assert "Refuses discovery" in user_tools["run"]["description"]
    assert "discovery scout|verify-scout|preview-promotion" in dev_tools["run"]["description"]
    refused = user.handle_run("openopps", {"argv": ["discovery", "scout"]}, USER_ROOT)
    assert refused["isError"] is True
    allowed_denied = dev.handle_run(
        "openopps-dev", {"argv": ["sync"]}, DEV_ROOT
    )
    assert allowed_denied["isError"] is True


def test_mcp_resolution_prefers_openopps_bin_then_filters_before_spawn(
    tmp_path: Path,
) -> None:
    user = _load_mcp(USER_ROOT, "openopps_user_mcp_bin")
    stub = tmp_path / "openopps-stub"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env_bin = os.environ.get("OPENOPPS_BIN")
    path_override = os.environ.get("PATH")
    os.environ["OPENOPPS_BIN"] = str(stub)
    try:
        command, cwd = user.resolve_openopps(USER_ROOT)
        assert command == [str(stub)]
        assert cwd is None
        refused = user.handle_run(
            "openopps", {"argv": ["discovery", "scout"]}, USER_ROOT
        )
        assert refused["isError"] is True
        assert "quarantined" in refused["content"][0]["text"]
        result = user.handle_run(
            "openopps", {"argv": ["status", "--json"]}, USER_ROOT
        )
        assert result["isError"] is False
        assert "status" in result["content"][0]["text"]
        assert "--json" in result["content"][0]["text"]
    finally:
        if env_bin is None:
            os.environ.pop("OPENOPPS_BIN", None)
        else:
            os.environ["OPENOPPS_BIN"] = env_bin
        if path_override is not None:
            os.environ["PATH"] = path_override


def test_user_skills_have_distinct_triggers_and_dispatch() -> None:
    descriptions: list[str] = []
    for name in USER_SKILLS:
        skill_file = USER_ROOT / "skills" / name / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert f"name: {name}" in text.split("---", 2)[1]
        body = text.split("---", 2)[2]
        assert "| `$ARGUMENTS`" in body or "| `$ARGUMENTS`" in text
        assert "Empty" in body
        frontmatter = text.split("---", 2)[1]
        assert "Use when" in frontmatter
        assert "NOT for" in frontmatter
        descriptions.append(frontmatter)
        assert len(body.splitlines()) <= 500
    assert len(set(descriptions)) == len(descriptions)
    hub = (USER_ROOT / "skills" / "openopps" / "SKILL.md").read_text(encoding="utf-8")
    assert "OPENOPPS_" in hub
    assert "discovery" in hub.lower()
    assert "openopps.plugins" in hub
    assert "/llms.txt" in hub
    web = (USER_ROOT / "skills" / "openopps-web" / "SKILL.md").read_text(encoding="utf-8")
    for url in (
        "https://www.openopps.dev",
        "/explorer",
        "/docs",
        "/llms.txt",
        "/llms-full.txt",
        "/llms.mdx/",
    ):
        assert url in web
    assert "/api/" in web
    assert "NOT" in web.split("---", 2)[1]
    assert "browser" in web.lower()
    admin = (USER_ROOT / "skills" / "openopps-admin" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "scout" in admin.lower()
    assert "preview-promotion" in admin


def test_dev_skills_stay_on_discovery_isolation_and_evals() -> None:
    hub = (DEV_ROOT / "skills" / "openopps-dev" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: openopps-dev" in hub
    assert "sync" in hub.lower()
    assert "launch_isolated_scout" in hub
    discovery = (DEV_ROOT / "skills" / "openopps-discovery" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "verify-scout" in discovery
    assert "preview-promotion" in discovery
    isolation = (DEV_ROOT / "skills" / "openopps-isolation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "launch_isolated_scout" in isolation
    evals = (DEV_ROOT / "skills" / "openopps-discovery-evals" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "uv run python" in evals
    assert "MCP" in evals or "mcp" in evals
    scout = (
        DEV_ROOT / "skills" / "openopps-source-scout" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "agent-plugins/openopps.dev/skills/openopps-source-scout/" in scout
    assert not (REPO_ROOT / "skills" / "openopps-source-scout").exists()
    for projection in (
        REPO_ROOT / ".agents" / "skills" / "openopps-source-scout",
        REPO_ROOT / ".cursor" / "skills" / "openopps-source-scout",
        REPO_ROOT / ".grok" / "skills" / "openopps-source-scout",
    ):
        assert not projection.exists()
