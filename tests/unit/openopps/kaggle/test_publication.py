from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from openopps_kaggle import publication
from openopps_kaggle.constants import (
    DATASET_ID,
    RUNTIME_GENERATOR_DATASET_ID,
)
from openopps_kaggle.runtime_manifest import stage_runtime_package


@pytest.fixture(autouse=True)
def _pinned_kaggle_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep publication unit tests independent of optional local CLI installs."""

    monkeypatch.setattr(
        publication,
        "version",
        lambda package: publication.KAGGLE_CLI_VERSION
        if package == "kaggle"
        else pytest.fail(f"unexpected distribution lookup: {package}"),
    )


def _runtime_stage(tmp_path: Path) -> Path:
    stage = tmp_path / "runtime-stage"
    stage_runtime_package(stage)
    return stage


def _plan(
    tmp_path: Path,
    stage: Path,
    *,
    execute: bool = False,
    message: str = "release; $(touch /tmp/must-not-run) ' quoted",
) -> dict[str, object]:
    return publication.prepare_publication(
        stage,
        tmp_path / "ledger.json",
        kind="runtime",
        action="version",
        message=message,
        expected_current_version=7,
        recorded_at="2026-08-12T12:34:56-04:00",
        execute=execute,
        environ={
            "PATH": os.environ["PATH"],
            "KAGGLE_API_TOKEN": "test-only-token",
            "UNRELATED_SECRET": "must-not-pass",
        },
    )


def test_stage_verification_returns_exact_content_identity(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)

    identity = publication.verify_publication_stage(stage, kind="runtime")

    assert identity["fileCount"] == len(identity["files"])
    assert identity["totalBytes"] == sum(item["bytes"] for item in identity["files"])
    assert len(identity["sha256"]) == 64


@pytest.mark.parametrize("attack", ["bitflip", "extra", "missing", "symlink", "fifo"])
def test_stage_verification_rejects_adversarial_tree(
    tmp_path: Path, attack: str
) -> None:
    stage = _runtime_stage(tmp_path)
    target = stage / "openopps_kaggle" / "cli.py"
    if attack == "bitflip":
        target.write_bytes(target.read_bytes() + b"\n# changed\n")
    elif attack == "extra":
        (stage / "extra.txt").write_text("extra\n", encoding="utf-8")
    elif attack == "missing":
        target.unlink()
    elif attack == "symlink":
        (stage / "openopps_kaggle" / "link.py").symlink_to(target)
    else:
        os.mkfifo(stage / "openopps_kaggle" / "pipe")

    with pytest.raises(publication.PublicationError):
        publication.verify_publication_stage(stage, kind="runtime")


def test_dry_run_is_default_and_metacharacters_remain_one_argv_element(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _runtime_stage(tmp_path)
    monkeypatch.setattr(
        publication,
        "_run_kaggle",
        lambda *args, **kwargs: pytest.fail("dry run must not invoke Kaggle"),
    )

    result = _plan(tmp_path, stage)
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))

    assert result["dryRun"] is True
    assert result["phase"] == "staged"
    assert result["datasetId"] == RUNTIME_GENERATOR_DATASET_ID
    mutation = result["commands"]["mutationArgv"]
    assert mutation == [
        "kaggle",
        "datasets",
        "version",
        "--path",
        "{STAGE_DIR}",
        "--message",
        "{MESSAGE}",
        "--quiet",
        "--keep-tabular",
        "--dir-mode",
        "zip",
    ]
    assert (
        ledger["entries"][0]["messageSha256"]
        == hashlib.sha256(b"release; $(touch /tmp/must-not-run) ' quoted").hexdigest()
    )
    assert "release;" not in json.dumps(ledger)
    assert ledger["entries"][0]["commands"]["rollback"] == {
        "targetVersion": 7,
        "downloadArgv": [
            "kaggle",
            "datasets",
            "download",
            f"{RUNTIME_GENERATOR_DATASET_ID}/versions/7",
            "--path",
            "{ROLLBACK_STAGE_DIR}",
            "--unzip",
            "--force",
            "--quiet",
        ],
        "publishArgv": [
            "kaggle",
            "datasets",
            "version",
            "--path",
            "{ROLLBACK_STAGE_DIR}",
            "--message",
            "Rollback to immutable Kaggle version 7",
            "--quiet",
            "--keep-tabular",
            "--dir-mode",
            "zip",
        ],
    }


def test_kaggle_cli_version_check_rejects_missing_or_mismatched_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(publication, "version", lambda _package: "2.2.3")
    with pytest.raises(publication.PublicationError, match="must be exactly 2.2.4"):
        publication.require_kaggle_cli_version()

    def missing(_package: str) -> str:
        raise publication.PackageNotFoundError("kaggle")

    monkeypatch.setattr(publication, "version", missing)
    with pytest.raises(publication.PublicationError, match="not installed"):
        publication.require_kaggle_cli_version()


def test_live_version_requires_exact_prior_version_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _runtime_stage(tmp_path)
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        seen.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"status":"active","current_version_number":8}',
            stderr="",
        )

    monkeypatch.setattr(publication, "_run_kaggle", fake_run)

    with pytest.raises(publication.PublicationError, match="preflight.*mismatch"):
        _plan(tmp_path, stage, execute=True)

    assert seen == [
        [
            "datasets",
            "status",
            RUNTIME_GENERATOR_DATASET_ID,
            "--format",
            "json",
        ]
    ]
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["entries"][0]["phase"] == "preflight-failed"
    assert ledger["entries"][0]["error"] == {"type": "PublicationError"}


def test_live_publication_uses_immutable_candidate_when_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _runtime_stage(tmp_path)
    stage_identity = publication.verify_publication_stage(stage, kind="runtime")
    seen: list[list[str]] = []
    mutation_stage: Path | None = None

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        seen.append(argv)
        if argv[:2] == ["datasets", "status"]:
            (stage / "unexpected-after-verification.txt").write_text(
                "changed\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"status":"active","current_version_number":7}',
                stderr="",
            )
        assert argv[:2] == ["datasets", "version"]
        nonlocal mutation_stage
        mutation_stage = Path(argv[argv.index("--path") + 1])
        assert mutation_stage != stage.resolve()
        assert not (mutation_stage / "unexpected-after-verification.txt").exists()
        assert (
            publication.verify_publication_stage(mutation_stage, kind="runtime")
            == stage_identity
        )
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr="failed")

    monkeypatch.setattr(publication, "_run_kaggle", fake_run)

    with pytest.raises(publication.PublicationError, match="exit code 9"):
        _plan(tmp_path, stage, execute=True)

    assert [argv[:2] for argv in seen] == [
        ["datasets", "status"],
        ["datasets", "version"],
    ]
    assert mutation_stage is not None
    assert not mutation_stage.exists()


def test_successful_live_state_machine_mutates_once_then_records_exact_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _runtime_stage(tmp_path)
    stage_identity = publication.verify_publication_stage(stage, kind="runtime")
    seen: list[list[str]] = []
    statuses = iter((7, 8))
    mutation_stage: Path | None = None

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        seen.append(argv)
        if argv[:2] == ["datasets", "status"]:
            current = next(statuses)
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"status": "active", "current_version_number": current}
                ),
                stderr="",
            )
        assert argv[:2] == ["datasets", "version"]
        nonlocal mutation_stage
        mutation_stage = Path(argv[argv.index("--path") + 1])
        assert mutation_stage != stage.resolve()
        assert (
            publication.verify_publication_stage(mutation_stage, kind="runtime")
            == stage_identity
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def fake_readback(expected_stage: Path, **kwargs: object) -> dict[str, object]:
        assert mutation_stage is not None
        assert expected_stage.resolve() == mutation_stage.resolve()
        assert kwargs["version_number"] == 8
        return stage_identity

    monkeypatch.setattr(publication, "_run_kaggle", fake_run)
    monkeypatch.setattr(publication, "verify_remote_readback", fake_readback)

    result = _plan(tmp_path, stage, execute=True)

    mutation_calls = [argv for argv in seen if argv[:2] == ["datasets", "version"]]
    assert len(mutation_calls) == 1
    assert mutation_calls[0][:4] == [
        "datasets",
        "version",
        "--path",
        str(mutation_stage),
    ]
    assert mutation_calls[0][4:] == [
        "--message",
        "release; $(touch /tmp/must-not-run) ' quoted",
        "--quiet",
        "--keep-tabular",
        "--dir-mode",
        "zip",
    ]
    assert mutation_stage is not None
    assert not mutation_stage.exists()
    assert result["phase"] == "readback-verified"
    assert result["readback"] == {
        "version": 8,
        "bundleSha256": stage_identity["sha256"],
        "fileCount": stage_identity["fileCount"],
        "totalBytes": stage_identity["totalBytes"],
        "verifiedAt": result["readback"]["verifiedAt"],
    }
    ledger_raw = (tmp_path / "ledger.json").read_text(encoding="utf-8")
    assert "must-not-run" not in ledger_raw
    persisted = json.loads(ledger_raw)["entries"][0]
    assert persisted["phase"] == "readback-verified"
    assert persisted["commands"]["rollback"]["targetVersion"] == 7


def test_live_create_requires_explicit_no_rollback_acceptance(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)

    with pytest.raises(publication.PublicationError, match="no prior rollback target"):
        publication.prepare_publication(
            stage,
            tmp_path / "ledger.json",
            kind="runtime",
            action="create",
            message="initial release",
            expected_current_version=None,
            recorded_at="2026-08-12T16:00:00Z",
            execute=True,
            environ={"PATH": os.environ["PATH"]},
        )


def test_runtime_create_stays_private_while_public_create_is_explicitly_public() -> (
    None
):
    runtime_commands = publication._publication_commands(
        kind="runtime",
        action="create",
        dataset_id=RUNTIME_GENERATOR_DATASET_ID,
        expected_current_version=None,
        published_version=1,
    )
    public_commands = publication._publication_commands(
        kind="public",
        action="create",
        dataset_id=DATASET_ID,
        expected_current_version=None,
        published_version=1,
    )

    assert "--public" not in runtime_commands["mutationArgv"]
    assert "--public" in public_commands["mutationArgv"]
    assert runtime_commands["rollback"] is None
    assert public_commands["rollback"] is None


def test_ledger_rejects_symlink_and_tampered_schema(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)
    target = tmp_path / "target.json"
    target.write_text("sentinel\n", encoding="utf-8")
    ledger = tmp_path / "ledger.json"
    ledger.symlink_to(target)

    with pytest.raises(publication.PublicationError, match="must not be a symlink"):
        publication.prepare_publication(
            stage,
            ledger,
            kind="runtime",
            action="version",
            message="safe",
            expected_current_version=1,
            recorded_at="2026-08-12T16:00:00Z",
        )

    assert target.read_text(encoding="utf-8") == "sentinel\n"
    ledger.unlink()
    ledger.write_text('{"schemaVersion":1,"entries":[],"secret":"x"}\n')
    with pytest.raises(publication.PublicationError, match="schema is invalid"):
        publication.prepare_publication(
            stage,
            ledger,
            kind="runtime",
            action="version",
            message="safe",
            expected_current_version=1,
            recorded_at="2026-08-12T16:00:00Z",
        )


def test_ledger_rejects_tampered_digest_and_command_graph(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)
    ledger = tmp_path / "ledger.json"
    _plan(tmp_path, stage)
    original = json.loads(ledger.read_text(encoding="utf-8"))

    tampered_digest = json.loads(json.dumps(original))
    tampered_digest["entries"][0]["expectedFiles"][0]["sha256"] = "0" * 64
    ledger.write_text(json.dumps(tampered_digest), encoding="utf-8")
    with pytest.raises(publication.PublicationError, match="bundle digest"):
        _plan(tmp_path, stage)

    tampered_command = json.loads(json.dumps(original))
    tampered_command["entries"][0]["commands"]["mutationArgv"] = "shell string"
    ledger.write_text(json.dumps(tampered_command), encoding="utf-8")
    with pytest.raises(publication.PublicationError, match="commands are inconsistent"):
        _plan(tmp_path, stage)


def test_ledger_rejects_symlinked_parent(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    link_dir = tmp_path / "linked"
    link_dir.symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(
        publication.PublicationError, match="parent must not be a symlink"
    ):
        publication.prepare_publication(
            stage,
            link_dir / "ledger.json",
            kind="runtime",
            action="version",
            message="safe",
            expected_current_version=1,
            recorded_at="2026-08-12T16:00:00Z",
        )

    assert not (target_dir / "ledger.json").exists()


def test_kaggle_subprocess_environment_is_allowlisted() -> None:
    env = publication.kaggle_subprocess_environment(
        {
            "PATH": "/usr/bin",
            "KAGGLE_USERNAME": "user",
            "KAGGLE_KEY": "secret",
            "OPENOPPS_DB_URL": "must-not-pass",
            "UNRELATED_SECRET": "must-not-pass",
        }
    )

    assert env == {
        "KAGGLE_KEY": "secret",
        "KAGGLE_USERNAME": "user",
        "PATH": "/usr/bin",
    }


def test_kaggle_runner_uses_current_python_module_and_never_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_subprocess_run(argv: list[str], **kwargs: object):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(publication.subprocess, "run", fake_subprocess_run)
    dangerous_message = "snapshot; $(touch /tmp/no) ' quoted"

    publication._run_kaggle(
        ["datasets", "version", "--message", dangerous_message],
        env={"PATH": "/usr/bin"},
        timeout_seconds=30,
    )

    assert captured["argv"] == [
        publication.sys.executable,
        "-m",
        "kaggle",
        "datasets",
        "version",
        "--message",
        dangerous_message,
    ]
    assert captured["shell"] is False
    assert captured["env"] == {"PATH": "/usr/bin"}


def test_live_execution_fails_before_command_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _runtime_stage(tmp_path)
    monkeypatch.setattr(
        publication,
        "_run_kaggle",
        lambda *args, **kwargs: pytest.fail("no command may run without credentials"),
    )

    with pytest.raises(publication.PublicationError, match="credentials are required"):
        publication.prepare_publication(
            stage,
            tmp_path / "ledger.json",
            kind="runtime",
            action="version",
            message="safe",
            expected_current_version=1,
            recorded_at="2026-08-12T16:00:00Z",
            execute=True,
            environ={"PATH": os.environ["PATH"]},
        )


def test_file_listing_rejects_unsafe_duplicate_or_partial_shapes() -> None:
    with pytest.raises(publication.PublicationError, match="unsafe"):
        publication._parse_file_listing('[{"name":"../secret","size":1}]')
    with pytest.raises(publication.PublicationError, match="repeats"):
        publication._parse_file_listing('[{"name":"a","size":1},{"name":"a","size":1}]')
    with pytest.raises(publication.PublicationError, match="invalid shape"):
        publication._parse_file_listing('[{"name":"a","size":1,"digest":"x"}]')


def test_kernel_push_dry_run_uses_allowlisted_argv_and_rejects_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(publication, "require_kaggle_cli_version", lambda: "2.2.4")
    result = publication.run_kernel_push(
        "examples", timeout_seconds=3600, execute=False
    )

    assert result["dryRun"] is True
    assert len(result["commands"]) == 4
    assert all(
        command[:3] == ["kaggle", "kernels", "push"] for command in result["commands"]
    )
    with pytest.raises(publication.PublicationError, match="unsupported"):
        publication.run_kernel_push(
            "examples; touch /tmp/no", timeout_seconds=3600, execute=False
        )


def test_public_plan_targets_public_dataset(tmp_path: Path) -> None:
    stage = _runtime_stage(tmp_path)
    with pytest.raises(publication.PublicationError, match="file set mismatch"):
        publication.prepare_publication(
            stage,
            tmp_path / "ledger.json",
            kind="public",
            action="version",
            message="snapshot",
            expected_current_version=4,
            recorded_at="2026-08-12T16:00:00Z",
        )
    assert DATASET_ID != RUNTIME_GENERATOR_DATASET_ID
