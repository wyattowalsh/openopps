"""Parse the D1016 private-host runbook and execute documented D1017 offline commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK_PATH = REPO_ROOT / "docs" / "source-discovery-private-host-runbook.md"
GATES_SCRIPT = REPO_ROOT / "scripts" / "source_discovery_gates.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "discovery"
CATALOG = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "portfolio_source_catalog.json"
)
ENVELOPE = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "discovery"
    / "data"
    / "approved_ingestion_selector_envelope.json"
)

REQUIRED_HEADINGS = (
    "Scheduler-agnostic template",
    "Environment allowlist",
    "Offline profile (`OPENOPPS_DISCOVERY_NETWORK=disabled`)",
    "Private live profile (unprovisioned / not activated)",
    "Finite budgets",
    "Private output directory",
    "Retention",
    "Readback gates",
    "Separate unexercised authority gates",
    "Documented offline commands",
)
CHANNEL_FAMILIES = ("official", "public_code", "search", "targeted_ats")
AUTHORITY_GATES = (
    "live scheduler provisioning",
    "credential selection",
    "activation",
    "retention",
    "execution",
)
UPLOAD_FORBIDDEN = re.compile(
    r"(?:"
    r"actions/upload-artifact|upload-artifact|"
    r"gh\s+release|twine\s+upload|npm\s+publish|"
    r"wrangler\s+(?:deploy|versions\s+upload|publish)|"
    r"kaggle\s+(?:datasets\s+)?(?:create|version|push)|"
    r"git\s+commit|git\s+push|--apply\b"
    r")",
    re.IGNORECASE,
)
NETWORK_ASSIGNMENT = re.compile(r"OPENOPPS_DISCOVERY_NETWORK=([A-Za-z0-9_-]+)")
HEADING = re.compile(r"^#{1,3}\s+(.*\S)\s*$", re.MULTILINE)
FENCE = re.compile(
    r"<!-- (?P<name>d1017-offline(?:-commands|-cli-readback)) -->"
    r"\s*```(?:bash|sh)?\n(?P<body>.*?)\n```\s*"
    r"<!-- /(?P=name) -->",
    re.DOTALL,
)
ENV_PREFIX = "OPENOPPS_DISCOVERY_NETWORK=disabled "


def _runbook() -> str:
    assert RUNBOOK_PATH.is_file(), f"missing runbook: {RUNBOOK_PATH}"
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _headings(text: str) -> tuple[str, ...]:
    return tuple(HEADING.findall(text))


def _fenced_commands(text: str, marker: str) -> tuple[str, ...]:
    blocks = {match.group("name"): match.group("body") for match in FENCE.finditer(text)}
    assert marker in blocks, f"missing {marker} fence in {RUNBOOK_PATH}"
    commands: list[str] = []
    for line in blocks[marker].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        commands.append(stripped)
    assert commands, f"{marker} fence listed no commands"
    return tuple(commands)


def _git_porcelain() -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _openopps_cmd() -> list[str]:
    candidate = Path(sys.executable).parent / "openopps"
    if candidate.is_file():
        return [str(candidate)]
    return [sys.executable, str(REPO_ROOT / "src" / "openopps" / "main.py")]


def _argv(
    command: str,
    *,
    private_output: Path | None = None,
    scout_manifest: Path | None = None,
) -> list[str]:
    body = command.strip()
    if body.startswith(ENV_PREFIX):
        body = body[len(ENV_PREFIX) :]
    if private_output is not None:
        body = body.replace("$PRIVATE_OUTPUT", str(private_output))
    if scout_manifest is not None:
        body = body.replace("$SCOUT_MANIFEST", str(scout_manifest))
    parts = shlex.split(body)
    if parts[:3] == ["uv", "run", "python"]:
        script = Path(parts[3])
        assert not script.is_absolute()
        return [sys.executable, str(REPO_ROOT / script), *parts[4:]]
    if parts[:3] == ["uv", "run", "openopps"]:
        return [*_openopps_cmd(), *parts[3:]]
    raise AssertionError(f"unsupported documented command: {command}")


def _offline_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OPENOPPS_DISCOVERY_NETWORK"] = "disabled"
    return env


def _run_documented(
    command: str,
    *,
    private_output: Path | None = None,
    scout_manifest: Path | None = None,
) -> dict[str, object]:
    assert command.startswith(ENV_PREFIX), command
    assert UPLOAD_FORBIDDEN.search(command) is None, command
    completed = subprocess.run(
        _argv(command, private_output=private_output, scout_manifest=scout_manifest),
        cwd=REPO_ROOT,
        env=_offline_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert UPLOAD_FORBIDDEN.search(combined) is None, combined
    assert completed.returncode == 0, combined
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict), payload
    return payload


def test_runbook_declares_required_sections() -> None:
    text = _runbook()
    headings = _headings(text)
    for heading in REQUIRED_HEADINGS:
        assert heading in headings, heading
    assert FIXTURE_ROOT.is_dir()
    assert (FIXTURE_ROOT / "manifest.json").is_file()


def test_runbook_is_scheduler_agnostic_and_unprovisioned() -> None:
    text = _runbook()
    folded = text.casefold()
    assert "scheduler-agnostic" in folded
    assert "not github-actions-only" in folded
    assert "does not contain a cron expression" in folded
    assert "**unprovisioned / not activated**" in text
    assert "do not provision" in folded or "does not provision" in folded
    assert re.search(r"^schedule\s*:", text, re.MULTILINE) is None
    assert "cron:" not in folded
    for assignment in NETWORK_ASSIGNMENT.findall(text):
        assert assignment == "disabled", assignment


def test_runbook_documents_offline_allowlist_finite_budgets_and_transport() -> None:
    text = _runbook()
    assert "`OPENOPPS_DISCOVERY_NETWORK=disabled`" in text
    assert "OPENOPPS_DISCOVERY_*" in text
    assert "LANG" in text and "LC_ALL" in text and "TZ" in text
    assert "build_credential_free_environment" in text
    for channel in CHANNEL_FAMILIES:
        assert f"`{channel}`" in text
    assert "ByteBudget" in text
    assert "RequestBudgetLedger" in text
    assert "src/openopps/discovery/transport.py" in text
    assert "context-contract.md" in text
    assert "verdict=defer" in text
    assert "numericRegressionThreshold=null" in text
    assert "slo" in text.casefold()
    assert "do not invent numeric slos" in text.casefold()


def test_runbook_documents_private_output_retention_and_readback() -> None:
    text = _runbook()
    folded = text.casefold()
    assert "private output" in folded
    assert "outside the git worktree" in folded
    assert "expire or delete" in folded
    assert "never upload public artifacts" in folded
    assert "openopps discovery verify-scout" in folded
    assert "openopps discovery preview-promotion" in folded
    assert "just source-discovery-" in folded
    assert "scripts/source_discovery_gates.py" in text
    assert "--apply" in text
    assert "replay-bundle" in text


def test_runbook_states_separate_unexercised_authority_gates() -> None:
    text = _runbook()
    folded = text.casefold()
    assert "separate unexercised authority gates" in folded
    for gate in AUTHORITY_GATES:
        assert gate in folded, gate
    assert "d1018" in folded
    assert "b1099" in folded
    assert "remain open" in folded


def test_documented_offline_commands_run_without_network_git_mutation_or_upload() -> None:
    text = _runbook()
    commands = _fenced_commands(text, "d1017-offline-commands")
    assert any(command.endswith(" fixtures") for command in commands)
    assert any("replay-bundle" in command for command in commands)
    assert any("promotion-preview" in command for command in commands)
    assert any("discovery preview-promotion --json" in command for command in commands)
    porcelain_before = _git_porcelain()
    catalog_before = CATALOG.read_bytes()
    envelope_before = ENVELOPE.read_bytes()

    payloads: list[dict[str, object]] = []
    for command in commands:
        payloads.append(_run_documented(command))

    assert payloads[0].get("ok") is True
    assert payloads[0].get("gate") == "fixtures"
    assert payloads[0].get("network") == "disabled"
    assert payloads[1].get("ok") is True
    assert payloads[1].get("gate") == "replay-bundle"
    assert payloads[1].get("activated") is False
    assert payloads[1].get("promoted") is False
    assert payloads[2].get("ok") is True
    assert payloads[2].get("gate") == "promotion-preview"
    assert payloads[2].get("applied") is False
    assert payloads[2].get("grantsAuthority") is False
    assert payloads[3].get("command") == "preview-promotion"
    assert payloads[3].get("applied") is False
    assert payloads[3].get("grantsAuthority") is False

    assert _git_porcelain() == porcelain_before
    assert CATALOG.read_bytes() == catalog_before
    assert ENVELOPE.read_bytes() == envelope_before


def test_offline_cli_scout_verify_and_preview_then_delete_private_output(
    tmp_path: Path,
) -> None:
    text = _runbook()
    commands = _fenced_commands(text, "d1017-offline-cli-readback")
    assert len(commands) == 3
    assert "discovery scout --output" in commands[0]
    assert "discovery verify-scout" in commands[1]
    assert "$SCOUT_MANIFEST" in commands[1]
    assert "discovery preview-promotion --json" in commands[2]
    private_output = (tmp_path / "quarantine").resolve()
    porcelain_before = _git_porcelain()
    catalog_before = CATALOG.read_bytes()

    scout = _run_documented(commands[0], private_output=private_output)
    assert scout["command"] == "scout"
    assert scout["promoted"] is False
    assert scout["activated"] is False
    manifest = Path(str(scout["manifestPath"]))
    assert manifest.is_file()
    assert manifest.resolve().is_relative_to(private_output)

    verify = _run_documented(
        commands[1],
        private_output=private_output,
        scout_manifest=manifest,
    )
    assert verify["command"] == "verify-scout"
    assert verify["status"] == "verified"
    assert verify["promoted"] is False
    assert verify["activated"] is False

    preview = _run_documented(commands[2], private_output=private_output)
    assert preview["command"] == "preview-promotion"
    assert preview["applied"] is False
    assert preview["grantsAuthority"] is False

    for path in sorted(private_output.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    if private_output.exists():
        private_output.rmdir()
    assert not private_output.exists()
    assert _git_porcelain() == porcelain_before
    assert CATALOG.read_bytes() == catalog_before


def test_offline_gates_refuse_non_disabled_network() -> None:
    completed = subprocess.run(
        [sys.executable, str(GATES_SCRIPT), "fixtures"],
        cwd=REPO_ROOT,
        env={**os.environ, "OPENOPPS_DISCOVERY_NETWORK": "private-live"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "OPENOPPS_DISCOVERY_NETWORK=disabled" in combined
    assert UPLOAD_FORBIDDEN.search(combined) is None


def test_runbook_does_not_document_live_execution() -> None:
    text = _runbook()
    live = text.split("## Private live profile (unprovisioned / not activated)", 1)[1]
    live = live.split("## Finite budgets", 1)[0]
    assert "```bash" not in live
    assert "--apply" not in live
    assert UPLOAD_FORBIDDEN.search(live) is None
