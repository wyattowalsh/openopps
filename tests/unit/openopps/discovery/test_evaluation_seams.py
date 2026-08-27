"""V-lane modules stay replay-first and isolated from operational stores."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DISCOVERY = ROOT / "src" / "openopps" / "discovery"
V_LANE_MODULES = (
    "evaluation.py",
    "identity.py",
    "liveness.py",
    "support.py",
    "policy.py",
)
FORBIDDEN = (
    "openopps.cache",
    "openopps.cli",
    "openopps.http",
    "openopps.ingest",
    "openopps.plugins",
    "openopps.providers",
    "openopps.storage",
    "openopps.source_policy",
    "openopps.discovery.http_client",
    "socket",
    "httpx",
    "httpcore",
)


def test_v_lane_modules_do_not_wire_operational_or_live_http_seams() -> None:
    for name in V_LANE_MODULES:
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
            or any(item.startswith(f"{prefix}.") for prefix in FORBIDDEN)
        }
        assert not forbidden, (name, forbidden)
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "getaddrinfo" not in function_names
