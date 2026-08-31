#!/usr/bin/env python3
"""Validate in-tree Agent Plugins 1.0.0 packages against vendored schemas.

Does not fetch schemas at runtime. Does not require skill-creator.
"""

from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "tests" / "fixtures" / "agent-plugins" / "schemas" / "1.0.0"
PLUGIN_SCHEMA_PATH = SCHEMA_ROOT / "plugin.schema.json"
MCP_SCHEMA_PATH = SCHEMA_ROOT / "mcp.schema.json"
PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
HOMEPAGE = "https://www.openopps.dev/docs/agent-plugins"
REPOSITORY = "https://github.com/wyattowalsh/openopps"
USER_ROOT = REPO_ROOT / "agent-plugins" / "openopps"
DEV_ROOT = REPO_ROOT / "agent-plugins" / "openopps.dev"
USER_SKILLS = (
    "openopps",
    "openopps-url-pull",
    "openopps-sync",
    "openopps-jobs",
    "openopps-boards",
    "openopps-sources",
    "openopps-providers",
    "openopps-status",
    "openopps-operations",
    "openopps-admin",
    "openopps-web",
)
DEV_SKILLS = (
    "openopps-dev",
    "openopps-source-scout",
    "openopps-discovery",
    "openopps-isolation",
    "openopps-discovery-evals",
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
PLUGIN_NAME_RE = SKILL_NAME_RE
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*([^\s#]+)\s*$", re.MULTILINE)
LEGACY_SCOUT = REPO_ROOT / "skills" / "openopps-source-scout"
PYTHON_PLUGIN_EXAMPLE = REPO_ROOT / "examples" / "plugins" / "minimal-openopps-plugin"
CLI_PATH = REPO_ROOT / "src" / "openopps" / "cli.py"
PROJECTION_PATHS = (
    REPO_ROOT / ".agents" / "skills" / "openopps-source-scout",
    REPO_ROOT / ".cursor" / "skills" / "openopps-source-scout",
    REPO_ROOT / ".grok" / "skills" / "openopps-source-scout",
)
COM_DIR_RE = re.compile(r"^com\.")
EXTENSION_DIR_NAMES = frozenset(
    {
        "claude-code",
        "codex",
        "cursor",
        "gemini-cli",
        "github-copilot",
        "opencode",
        "windsurf",
    }
)


class PluginVerificationError(RuntimeError):
    """A package failed Agent Plugins 1.0.0 or OpenOpps layout checks."""


def _pointer(path: list[str | int]) -> str:
    if not path:
        return "/"
    parts = [""]
    for item in path:
        parts.append(str(item).replace("~", "~0").replace("/", "~1"))
    return "/".join(parts) or "/"


class SchemaError(PluginVerificationError):
    def __init__(self, message: str, path: list[str | int] | None = None) -> None:
        location = _pointer(path or [])
        super().__init__(f"{location}: {message}")
        self.path = list(path or [])


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaError(f"unsupported $ref {ref!r}")
    current: Any = root
    for part in ref[2:].split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise SchemaError(f"unresolved $ref {ref!r}")
        current = current[token]
    if not isinstance(current, dict):
        raise SchemaError(f"$ref {ref!r} did not resolve to an object")
    return current


def _is_type(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return False


def validate_instance(
    instance: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: list[str | int] | None = None,
) -> None:
    here = list(path or [])
    if "$ref" in schema:
        validate_instance(instance, _resolve_ref(str(schema["$ref"]), root), root, here)
        return
    if "oneOf" in schema:
        matched = 0
        errors: list[str] = []
        for index, option in enumerate(schema["oneOf"]):
            try:
                validate_instance(instance, option, root, here)
            except SchemaError as exc:
                errors.append(f"oneOf[{index}] {exc}")
            else:
                matched += 1
        if matched != 1:
            detail = "; ".join(errors) if matched == 0 else f"{matched} options matched"
            raise SchemaError(f"oneOf failed ({detail})", here)
        return
    if "not" in schema:
        try:
            validate_instance(instance, schema["not"], root, here)
        except SchemaError:
            pass
        else:
            raise SchemaError("matched a forbidden schema", here)
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"expected const {schema['const']!r}", here)
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"expected one of {schema['enum']!r}", here)
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(instance, expected_type):
        raise SchemaError(f"expected type {expected_type}", here)
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            raise SchemaError("shorter than minLength", here)
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            raise SchemaError("longer than maxLength", here)
        if "pattern" in schema and re.search(str(schema["pattern"]), instance) is None:
            raise SchemaError("does not match pattern", here)
    if isinstance(instance, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                raise SchemaError(f"missing required property {key!r}", here)
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            names_schema = schema.get("propertyNames")
            if isinstance(names_schema, dict):
                validate_instance(key, names_schema, root, here + [key])
            if key in properties:
                validate_instance(value, properties[key], root, here + [key])
            elif additional is False:
                raise SchemaError(f"additional property {key!r} is not allowed", here)
            elif isinstance(additional, dict):
                validate_instance(value, additional, root, here + [key])
    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(instance):
            validate_instance(item, item_schema, root, here + [index])


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PluginVerificationError(f"missing {path.relative_to(REPO_ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise PluginVerificationError(f"invalid JSON in {path.relative_to(REPO_ROOT)}: {exc}") from exc


def _require_file(path: Path, *, executable: bool = False) -> None:
    if not path.is_file() or path.is_symlink():
        raise PluginVerificationError(
            f"{path.relative_to(REPO_ROOT)} must be a regular file"
        )
    if executable and not (path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        raise PluginVerificationError(
            f"{path.relative_to(REPO_ROOT)} must be executable"
        )


def _containment(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(resolved_root):
                raise PluginVerificationError(
                    f"symlink {path.relative_to(REPO_ROOT)} escapes the plugin root"
                )


def _parse_skill_frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} is missing YAML frontmatter"
        )
    end = text.find("\n---", 3)
    if end < 0:
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} has unterminated frontmatter"
        )
    block = text[4:end]
    data: dict[str, str] = {}
    pending_key: str | None = None
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending_key, pending
        if pending_key is not None:
            data[pending_key] = " ".join(pending).strip()
            pending_key = None
            pending = []

    for line in block.splitlines():
        if pending_key is not None and (line.startswith("  ") or line.startswith("\t")):
            pending.append(line.strip().lstrip(">").strip())
            continue
        flush()
        if ":" not in line or line[:1] in {" ", "\t"}:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {">", ">-", "|", "|-"}:
            pending_key = key
            pending = []
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        data[key] = value
    flush()
    return data


def _skill_body(skill_file: Path) -> str:
    text = skill_file.read_text(encoding="utf-8")
    end = text.find("\n---", 3)
    return text[end + 4 :] if end >= 0 else text


def _assert_skill(plugin_root: Path, name: str) -> None:
    skill_dir = plugin_root / "skills" / name
    skill_file = skill_dir / "SKILL.md"
    if not skill_dir.is_dir() or skill_dir.is_symlink():
        raise PluginVerificationError(
            f"{skill_dir.relative_to(REPO_ROOT)} must be a directory"
        )
    _require_file(skill_file)
    if not SKILL_NAME_RE.fullmatch(name) or "--" in name or len(name) < 2 or len(name) > 64:
        raise PluginVerificationError(f"invalid skill directory name {name!r}")
    frontmatter = _parse_skill_frontmatter(skill_file)
    if frontmatter.get("name") != name:
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} frontmatter name must equal {name!r}"
        )
    description = frontmatter.get("description", "")
    if "Use when" not in description or "NOT for" not in description:
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} description must include Use when and NOT for"
        )
    body = _skill_body(skill_file)
    body_lines = body.splitlines()
    if len(body_lines) > 500:
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} body exceeds 500 lines"
        )
    lowered = body.lower()
    if "| `$arguments`" not in lowered and "| `$ARGUMENTS`" not in body:
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} must include a dispatch table"
        )
    if not re.search(r"\|\s*`?Empty`?\s*\|", body, re.IGNORECASE):
        raise PluginVerificationError(
            f"{skill_file.relative_to(REPO_ROOT)} must include an empty-args handler"
        )


def _assert_no_extension_dirs(root: Path) -> None:
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if COM_DIR_RE.match(name) or name in EXTENSION_DIR_NAMES:
            raise PluginVerificationError(
                f"{child.relative_to(REPO_ROOT)} is a client-extension directory (omit in v1)"
            )


def _assert_mcp(root: Path, document: dict[str, Any]) -> None:
    servers = document.get("mcpServers")
    if not isinstance(servers, dict) or len(servers) != 1:
        raise PluginVerificationError(
            f"{root.relative_to(REPO_ROOT)}/mcp.json must declare exactly one stdio server"
        )
    server = next(iter(servers.values()))
    if server.get("type") != "stdio":
        raise PluginVerificationError("MCP server type must be stdio")
    if server.get("command") != "./bin/mcp":
        raise PluginVerificationError('MCP command must be "./bin/mcp"')
    if server.get("cwd") != "${PLUGIN_ROOT}":
        raise PluginVerificationError('MCP cwd must be "${PLUGIN_ROOT}"')
    if "env" in server:
        env = server["env"]
        if not isinstance(env, dict):
            raise PluginVerificationError("MCP env must be an object when present")
        for forbidden in ("PLUGIN_ROOT", "PLUGIN_DATA"):
            if forbidden in env:
                raise PluginVerificationError(f"MCP env must not set {forbidden}")
    for key in ("command", "cwd"):
        value = str(server.get(key, ""))
        if ".." in value.split("/"):
            raise PluginVerificationError(f"MCP {key} must not contain .. segments")


def _assert_grok_mcp_alias(root: Path, mcp_document: dict[str, Any]) -> None:
    alias_path = root / ".mcp.json"
    _require_file(alias_path)
    alias = load_json(alias_path)
    if "$schema" in alias:
        raise PluginVerificationError(
            f"{alias_path.relative_to(REPO_ROOT)} must omit $schema (Grok/Claude MCP alias)"
        )
    servers = alias.get("mcpServers")
    canonical = mcp_document.get("mcpServers")
    if not isinstance(servers, dict) or not isinstance(canonical, dict):
        raise PluginVerificationError(".mcp.json must declare mcpServers")
    if set(servers) != set(canonical):
        raise PluginVerificationError(".mcp.json server names must match mcp.json")
    for name, server in servers.items():
        if not isinstance(server, dict):
            raise PluginVerificationError(f".mcp.json server {name!r} must be an object")
        if server.get("type") != "stdio" or server.get("command") != "./bin/mcp":
            raise PluginVerificationError(
                f".mcp.json server {name!r} must be stdio ./bin/mcp"
            )
        if "env" in server:
            env = server["env"]
            if isinstance(env, dict) and (
                "PLUGIN_ROOT" in env or "PLUGIN_DATA" in env
            ):
                raise PluginVerificationError(
                    f".mcp.json server {name!r} must not set PLUGIN_ROOT or PLUGIN_DATA"
                )


def verify_package(
    root: Path,
    *,
    expected_name: str,
    expected_skills: tuple[str, ...],
) -> dict[str, object]:
    plugin_path = root / "plugin.json"
    mcp_path = root / "mcp.json"
    license_path = root / "LICENSE"
    mcp_bin = root / "bin" / "mcp"
    skills_root = root / "skills"
    if not root.is_dir():
        raise PluginVerificationError(f"missing plugin root {root.relative_to(REPO_ROOT)}")
    _require_file(plugin_path)
    _require_file(mcp_path)
    _require_file(license_path)
    _require_file(mcp_bin, executable=True)
    if not skills_root.is_dir():
        raise PluginVerificationError(f"missing {skills_root.relative_to(REPO_ROOT)}")
    _containment(root)
    _assert_no_extension_dirs(root)
    plugin_schema = load_json(PLUGIN_SCHEMA_PATH)
    mcp_schema = load_json(MCP_SCHEMA_PATH)
    plugin_document = load_json(plugin_path)
    mcp_document = load_json(mcp_path)
    validate_instance(plugin_document, plugin_schema, plugin_schema)
    validate_instance(mcp_document, mcp_schema, mcp_schema)
    if plugin_document.get("$schema") != PLUGIN_SCHEMA_ID:
        raise PluginVerificationError("plugin.json $schema mismatch")
    if mcp_document.get("$schema") != MCP_SCHEMA_ID:
        raise PluginVerificationError("mcp.json $schema mismatch")
    if not PLUGIN_NAME_RE.fullmatch(expected_name) or "--" in expected_name:
        raise PluginVerificationError(
            f"plugin name {expected_name!r} must be kebab-case (Grok/Claude reject dots)"
        )
    if plugin_document.get("name") != expected_name:
        raise PluginVerificationError(
            f"{plugin_path.relative_to(REPO_ROOT)} name must be {expected_name!r}"
        )
    if plugin_document.get("license") != "MIT":
        raise PluginVerificationError("plugin license must be MIT")
    if plugin_document.get("homepage") != HOMEPAGE:
        raise PluginVerificationError("plugin homepage mismatch")
    if plugin_document.get("repository") != REPOSITORY:
        raise PluginVerificationError("plugin repository mismatch")
    if "extensions" in plugin_document:
        raise PluginVerificationError("omit plugin.json extensions in v1")
    _assert_mcp(root, mcp_document)
    _assert_grok_mcp_alias(root, mcp_document)
    shebang = mcp_bin.read_bytes().splitlines()[:1]
    if not shebang or shebang[0] != b"#!/usr/bin/env python3":
        raise PluginVerificationError("bin/mcp must use a python3 shebang")
    children = sorted(
        path.name for path in skills_root.iterdir() if not path.name.startswith(".")
    )
    extra = [name for name in children if name not in expected_skills]
    missing = [name for name in expected_skills if name not in children]
    if extra or missing:
        raise PluginVerificationError(
            f"{skills_root.relative_to(REPO_ROOT)} skill set mismatch "
            f"missing={missing} extra={extra}"
        )
    for name in expected_skills:
        _assert_skill(root, name)
    return {
        "name": expected_name,
        "ok": True,
        "root": str(root.relative_to(REPO_ROOT)),
        "skills": list(expected_skills),
    }


def verify_repository_invariants() -> None:
    if LEGACY_SCOUT.exists():
        raise PluginVerificationError(
            "skills/openopps-source-scout/ must be removed after the SSOT move"
        )
    if (PYTHON_PLUGIN_EXAMPLE / "plugin.json").exists():
        raise PluginVerificationError(
            "examples/plugins must remain a Python openopps.plugins template"
        )
    cli_text = CLI_PATH.read_text(encoding="utf-8")
    if re.search(r'@app\.command\(\s*"mcp"', cli_text) or re.search(
        r'add_typer\([^)]*name="mcp"', cli_text
    ):
        raise PluginVerificationError("public CLI must not expose an mcp command")
    for projection in PROJECTION_PATHS:
        if projection.exists():
            raise PluginVerificationError(
                f"harness projection {projection.relative_to(REPO_ROOT)} must stay absent"
            )


def verify() -> dict[str, object]:
    if not PLUGIN_SCHEMA_PATH.is_file() or not MCP_SCHEMA_PATH.is_file():
        raise PluginVerificationError("vendored Agent Plugins 1.0.0 schemas are missing")
    plugin_schema = load_json(PLUGIN_SCHEMA_PATH)
    mcp_schema = load_json(MCP_SCHEMA_PATH)
    if plugin_schema.get("$id") != PLUGIN_SCHEMA_ID:
        raise PluginVerificationError("vendored plugin schema $id mismatch")
    if mcp_schema.get("$id") != MCP_SCHEMA_ID:
        raise PluginVerificationError("vendored mcp schema $id mismatch")
    verify_repository_invariants()
    packages = [
        verify_package(USER_ROOT, expected_name="openopps", expected_skills=USER_SKILLS),
        verify_package(
            DEV_ROOT, expected_name="openopps-dev", expected_skills=DEV_SKILLS
        ),
    ]
    return {"ok": True, "packages": packages}


def main() -> int:
    try:
        payload = verify()
    except PluginVerificationError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        sys.stdout.write("\n")
        return 1
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
