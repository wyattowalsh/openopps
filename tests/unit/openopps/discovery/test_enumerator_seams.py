from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DISCOVERY = ROOT / "src" / "openopps" / "discovery"
ENUMERATOR_MODULES = (
    "enumerators.py",
    "official.py",
    "public_code.py",
    "search.py",
    "targeted_ats.py",
    "merge.py",
)
FORBIDDEN = (
    "openopps.cache",
    "openopps.cli",
    "openopps.http",
    "openopps.ingest",
    "openopps.plugins",
    "openopps.providers",
    "openopps.storage",
    "openopps.discovery.http_client",
    "socket",
    "httpx",
    "httpcore",
)


def test_enumerator_modules_stay_replay_only_and_do_not_wire_weaker_seams() -> None:
    for name in ENUMERATOR_MODULES:
        source = (DISCOVERY / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            item
            for item in imported
            if item in FORBIDDEN
            or any(item.startswith(f"{name}.") for name in FORBIDDEN)
        }
        assert not forbidden, (name, forbidden)
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "getaddrinfo" not in function_names
        assert "fetch" not in function_names or name == "enumerators.py"
