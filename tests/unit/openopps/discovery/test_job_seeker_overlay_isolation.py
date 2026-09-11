from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
import stat
import sys

from openopps.discovery import isolation as isolation_module
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.isolation import (
    ApplicationFilesystem,
    ScoutLaunchRequest,
    ScoutProcessLimits,
    launch_isolated_scout,
    validate_data_only_suggestion,
)
from openopps.discovery.models import ChannelBudget, ChannelProfile
from openopps.discovery.targeted_ats import enumerate_targeted_ats_channel
from openopps.discovery.transport import validate_public_locator
from openopps.providers.sources import overlay_targets as overlay_targets_module
from openopps.providers.sources.overlay_targets import load_overlay_targets


ISOLATED_VALIDATOR = "openopps.discovery.isolation.launch_isolated_scout"
OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_TINY_OVERLAY = {
    "version": 1,
    "outcomes": [
        "duplicate",
        "fetchable_packaged",
        "no_public_ats",
        "policy_blocked",
    ],
    "core": [
        {
            "id": "acme",
            "name": "Acme",
            "locator": "https://boards.greenhouse.io/acme",
        }
    ],
    "b_tier": [],
    "growth": [],
}
_PAGE_HTML = b"<!doctype html><html><body><p>Board</p></body></html>"
_DENIED_HOST_LABELS = frozenset(
    {"wellfound", "angel", "angellist", "linkedin", "workatastartup"}
)


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _write_tiny_overlay(root: Path) -> Path:
    path = root / "overlay.json"
    path.write_text(json.dumps(_TINY_OVERLAY), encoding="utf-8")
    return path


def _budget() -> ChannelBudget:
    return ChannelBudget(
        query_limit=8,
        request_limit=12,
        origin_limit=8,
        redirect_limit=2,
        page_limit=2,
        response_byte_limit=8_000,
        aggregate_byte_limit=40_000,
        candidate_limit=20,
        concurrency_limit=2,
        per_origin_concurrency_limit=1,
        retry_limit=2,
        parser_depth_limit=16,
        wall_clock_limit_ms=5_000,
    )


def _module_function_calls(source: str) -> dict[str, frozenset[str]]:
    tree = ast.parse(source)
    found: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        found[node.name] = frozenset(names)
    return found


def _overlay_suggestion(
    *,
    locator: str,
    provider_id: str,
    provenance_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "candidateLocator": locator,
        "parserId": "html-links-v1",
        "providerId": provider_id,
        "provenanceResourceIds": list(provenance_ids),
    }


async def test_overlay_suggestions_are_accepted_only_through_launch_isolated_scout(
    tmp_path: Path,
) -> None:
    isolation_source = Path(isolation_module.__file__).read_text(encoding="utf-8")
    isolation_calls = _module_function_calls(isolation_source)
    validate_callers = {
        name
        for name, names in isolation_calls.items()
        if "validate_data_only_suggestion" in names
    }
    worker_output_callers = {
        name
        for name, names in isolation_calls.items()
        if "_validate_worker_output" in names
    }
    write_callers = {
        name for name, names in isolation_calls.items() if "write_new" in names
    }
    assert validate_callers == {"_validate_worker_output"}
    assert worker_output_callers == {"launch_isolated_scout"}
    assert write_callers == {"launch_isolated_scout"}
    assert "runner" not in inspect.signature(launch_isolated_scout).parameters
    assert (
        f"{isolation_module.__name__}.launch_isolated_scout" == ISOLATED_VALIDATOR
    )

    overlay_source = Path(overlay_targets_module.__file__).read_text(encoding="utf-8")
    overlay_calls = _module_function_calls(overlay_source)
    assert "launch_isolated_scout" not in overlay_source
    assert "validate_data_only_suggestion" not in overlay_source
    for names in overlay_calls.values():
        assert "launch_isolated_scout" not in names
        assert "validate_data_only_suggestion" not in names

    overlay_path = _write_tiny_overlay(tmp_path)
    parsed = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert parsed["version"] == 1
    assert "suggestions" not in parsed
    row = parsed["core"][0]
    assert set(row) == {"id", "name", "locator"}
    assert "candidateLocator" not in row
    assert "outcome" not in row
    host = validate_public_locator(row["locator"]).hostname
    assert not any(label in host for label in _DENIED_HOST_LABELS)

    targets = load_overlay_targets(overlay_path=overlay_path)
    assert tuple(item.target_id for item in targets) == ("acme",)
    target = targets[0]
    origin = validate_public_locator(target.public_page_locator).origin
    receipt = enumerate_targeted_ats_channel(
        profile=ChannelProfile(
            channel="targeted_ats",
            budget=_budget(),
            seed_ids=(target.target_id,),
            allowed_origins=(origin,),
            allowed_query_keys=("board",),
            parser_ids=("html-links-v1",),
        ),
        targets=targets,
        observations=(
            CapturedObservation(
                locator=target.public_page_locator,
                status_code=200,
                body=_PAGE_HTML,
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert receipt.operation_outcomes == ("succeeded",)
    occurrence = next(
        item
        for item in receipt.occurrences
        if item.occurrence_id.endswith(":supported")
    )
    assert occurrence.identity.provider_id == "greenhouse"
    assert occurrence.identity.provider_token == "acme"
    assert occurrence.provenance_ids

    suggestion = _overlay_suggestion(
        locator=occurrence.identity.canonical_url,
        provider_id=occurrence.identity.provider_id,
        provenance_ids=occurrence.provenance_ids,
    )
    admitted = frozenset(occurrence.provenance_ids)
    parsers = frozenset({"html-links-v1"})
    providers = frozenset({occurrence.identity.provider_id})
    quarantine = _private_directory(tmp_path / "quarantine")
    validated = validate_data_only_suggestion(
        suggestion,
        admitted_resource_ids=admitted,
        allowed_parser_ids=parsers,
        allowed_provider_ids=providers,
    )
    assert dict(validated) == suggestion
    assert tuple(quarantine.iterdir()) == ()

    result = await launch_isolated_scout(
        ScoutLaunchRequest(
            input_bytes=canonical_json_bytes({"suggestions": [suggestion]}),
            quarantine_root=quarantine,
            parent_environment={
                "LANG": "C.UTF-8",
                "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                "DATABASE_URL": "sqlite:///operational.db",
                "GH_TOKEN": "synthetic-token",
                "GIT_DIR": "/private/repository/.git",
                "HTTP_PROXY": "http://proxy.invalid",
                "OPENOPPS_PLUGIN_AUTOLOAD": "true",
            },
            environment_allowlist=frozenset({"LANG", "GH_TOKEN"}),
            trusted_profile_id="offline",
            trusted_seed=17,
            admitted_resource_ids=admitted,
            allowed_parser_ids=parsers,
            allowed_provider_ids=providers,
        ),
        executable=sys.executable,
        filesystem=ApplicationFilesystem(root=quarantine),
        limits=ScoutProcessLimits(timeout_seconds=10),
    )

    destination = quarantine / "worker" / "result.json"
    assert result.returncode == 0
    assert result.stderr == b""
    assert destination.read_bytes() == result.stdout
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert decode_canonical_json(result.stdout) == {
        "profileId": "offline",
        "result": {"suggestions": [suggestion]},
        "seed": 17,
    }
    rendered = result.stdout.decode("utf-8")
    for forbidden in (
        "synthetic-secret",
        "synthetic-token",
        "operational.db",
        "openopps sync",
    ):
        assert forbidden not in rendered


def test_discovery_scout_verify_preview_never_import_sync() -> None:
    discovery_root = Path(isolation_module.__file__).resolve().parent
    forbidden_modules = {
        "openopps.ingest",
        "openopps.cli",
        "openopps.storage",
    }
    forbidden_names = {"ingest", "jobs_sync", "sync_jobs"}
    for path in discovery_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert imported.isdisjoint(forbidden_modules), path
        source = path.read_text(encoding="utf-8")
        assert "openopps sync" not in source
        if path.name in {"api.py", "isolation.py", "promotion.py", "worker.py"}:
            for name in forbidden_names:
                assert f"def {name}" not in source
