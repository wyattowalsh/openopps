from __future__ import annotations

import ast
import asyncio
from collections.abc import Mapping
import inspect
import os
from pathlib import Path
import stat
import sys
from typing import Any

import pytest

from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.isolation import (
    ApplicationFilesystem,
    IsolationError,
    ScoutLaunchRequest,
    ScoutProcessLimits,
    launch_isolated_scout,
    run_fresh_scout_process,
)


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _request(
    root: Path,
    *,
    input_bytes: bytes | None = None,
    parent_environment: Mapping[str, str] | None = None,
) -> ScoutLaunchRequest:
    return ScoutLaunchRequest(
        input_bytes=input_bytes or canonical_json_bytes({"suggestions": []}),
        quarantine_root=root,
        parent_environment=parent_environment
        or {
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
    )


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def test_launcher_has_no_injected_process_bypass() -> None:
    parameters = inspect.signature(launch_isolated_scout).parameters

    assert "runner" not in parameters


async def test_launcher_executes_resolved_validated_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    target = _write_executable(tmp_path / "trusted-worker", "exit 0")
    alias = tmp_path / "worker-alias"
    alias.symlink_to(target)
    observed: dict[str, object] = {}

    async def refusing_exec(
        *argv: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> asyncio.subprocess.Process:
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        raise OSError("synthetic refusal")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refusing_exec)

    with pytest.raises(IsolationError) as caught:
        await run_fresh_scout_process(
            executable=os.fspath(alias),
            request=_request(root),
            environment={
                "LANG": "C.UTF-8",
                "NO_PROXY": "*",
                "PYTHONNOUSERSITE": "1",
            },
            limits=ScoutProcessLimits(),
        )

    assert caught.value.reason_code == "isolated_process_start"
    argv = observed["argv"]
    assert isinstance(argv, tuple)
    assert argv[0] == os.fspath(alias)
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["executable"] == os.fspath(target.resolve())


def test_descriptor_relative_filesystem_writes_exact_private_exclusive_tree(
    tmp_path: Path,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    filesystem = ApplicationFilesystem(root=root)

    destination = filesystem.write_new("nested/result.json", b"{}\n")

    assert destination == root / "nested/result.json"
    assert destination.read_bytes() == b"{}\n"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "nested").stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.stat().st_uid == os.getuid()
    assert destination.stat().st_nlink == 1
    with pytest.raises(IsolationError) as caught:
        filesystem.write_new("nested/result.json", b"replacement")
    assert caught.value.reason_code == "filesystem_write"
    assert destination.read_bytes() == b"{}\n"


def test_descriptor_relative_filesystem_creates_only_the_new_private_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "new-quarantine"

    destination = ApplicationFilesystem(root=root).write_new("result", b"{}\n")

    assert destination == root / "result"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "relative",
    [
        "../escape",
        "/absolute",
        "nested/../../escape",
        "nested//result",
        "nested/./result",
        "nested/%2f/result",
        "nested\\result",
    ],
)
def test_descriptor_relative_filesystem_rejects_out_of_root_forms(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _private_directory(tmp_path / "quarantine")

    with pytest.raises(IsolationError) as caught:
        ApplicationFilesystem(root=root).write_new(relative, b"forbidden")

    assert caught.value.reason_code == "filesystem_containment"
    assert tuple(root.iterdir()) == ()


def test_descriptor_relative_filesystem_rejects_root_and_nested_symlinks(
    tmp_path: Path,
) -> None:
    actual_root = _private_directory(tmp_path / "actual")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(actual_root, target_is_directory=True)
    outside = _private_directory(tmp_path / "outside")

    with pytest.raises(IsolationError) as root_error:
        ApplicationFilesystem(root=linked_root).write_new("result", b"forbidden")
    assert root_error.value.reason_code == "filesystem_root_identity"

    nested_link = actual_root / "nested"
    nested_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(IsolationError) as nested_error:
        ApplicationFilesystem(root=actual_root).write_new("nested/result", b"forbidden")
    assert nested_error.value.reason_code == "filesystem_directory_identity"
    assert tuple(outside.iterdir()) == ()


def test_descriptor_relative_filesystem_rejects_symlinked_root_ancestor(
    tmp_path: Path,
) -> None:
    actual_parent = _private_directory(tmp_path / "actual-parent")
    root = _private_directory(actual_parent / "quarantine")
    alias = tmp_path / "alias"
    alias.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(IsolationError) as caught:
        ApplicationFilesystem(root=alias / root.name).write_new("result", b"forbidden")

    assert caught.value.reason_code == "filesystem_root_identity"
    assert tuple(root.iterdir()) == ()


def test_descriptor_relative_filesystem_detects_directory_swap_during_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    nested = _private_directory(root / "nested")
    outside = _private_directory(tmp_path / "outside")
    original_open = os.open
    swapped = False

    def racing_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "result" and dir_fd is not None and not swapped:
            swapped = True
            nested.rename(root / "displaced")
            nested.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    with pytest.raises(IsolationError) as caught:
        ApplicationFilesystem(root=root).write_new("nested/result", b"bounded")

    assert caught.value.reason_code == "filesystem_directory_identity"
    assert tuple(outside.iterdir()) == ()
    assert (root / "displaced/result").read_bytes() == b"bounded"


def test_descriptor_relative_filesystem_rejects_non_private_root(
    tmp_path: Path,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    root.chmod(0o755)

    with pytest.raises(IsolationError) as caught:
        ApplicationFilesystem(root=root).write_new("result", b"forbidden")

    assert caught.value.reason_code == "filesystem_directory_identity"
    assert tuple(root.iterdir()) == ()


async def test_real_worker_validates_canonical_output_before_private_write(
    tmp_path: Path,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    request = _request(root)

    result = await launch_isolated_scout(
        request,
        executable=sys.executable,
        filesystem=ApplicationFilesystem(root=root),
        limits=ScoutProcessLimits(timeout_seconds=10),
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert decode_canonical_json(result.stdout) == {
        "profileId": "offline",
        "result": {"suggestions": []},
        "seed": 17,
    }
    destination = root / "worker/result.json"
    assert destination.read_bytes() == result.stdout
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


async def test_real_process_has_fixed_module_safe_env_and_no_ambient_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    request = _request(root)
    observed: dict[str, object] = {}
    original = asyncio.create_subprocess_exec

    async def recording_exec(
        *argv: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> asyncio.subprocess.Process:
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return await original(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)

    await launch_isolated_scout(
        request,
        executable=sys.executable,
        filesystem=ApplicationFilesystem(root=root),
        limits=ScoutProcessLimits(timeout_seconds=10),
    )

    argv = observed["argv"]
    kwargs = observed["kwargs"]
    assert isinstance(argv, tuple)
    assert argv[1:] == (
        "-I",
        "-B",
        "-m",
        "openopps.discovery.worker",
        "--profile-id",
        "offline",
        "--seed",
        "17",
    )
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == os.path.sep
    assert kwargs["close_fds"] is True
    assert kwargs["start_new_session"] is True
    assert "pass_fds" not in kwargs
    assert kwargs["env"] == {
        "LANG": "C.UTF-8",
        "NO_PROXY": "*",
        "PYTHONNOUSERSITE": "1",
    }
    rendered = repr((argv, kwargs["env"], kwargs["cwd"]))
    for forbidden in (
        "synthetic-secret",
        "synthetic-token",
        "operational.db",
        ".git",
        "proxy.invalid",
        "plugin",
        str(root),
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("body", "reason_code"),
    [
        ("printf '{\"result\":[]}\\n'", "isolated_process_output"),
        ("printf '{ \"result\": [] }\\n'", "isolated_process_output"),
        (
            "printf 'raw-secret-stderr' >&2; exit 17",
            "isolated_process_failed",
        ),
    ],
)
async def test_invalid_or_failed_process_never_writes_or_discloses_stderr(
    tmp_path: Path,
    body: str,
    reason_code: str,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    executable = _write_executable(tmp_path / "synthetic-worker", body)

    with pytest.raises(IsolationError) as caught:
        await launch_isolated_scout(
            _request(root),
            executable=os.fspath(executable),
            filesystem=ApplicationFilesystem(root=root),
            limits=ScoutProcessLimits(timeout_seconds=10),
        )

    assert caught.value.reason_code == reason_code
    assert "raw-secret-stderr" not in str(caught.value)
    assert tuple(root.iterdir()) == ()


async def test_canonical_authority_bearing_suggestion_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    input_bytes = canonical_json_bytes(
        {
            "suggestions": [
                {
                    "candidateLocator": "https://jobs.example.test/",
                    "command": "publish --force",
                    "parserId": "html-links-v1",
                    "providerId": "greenhouse",
                    "provenanceResourceIds": ["sha256:" + "a" * 64],
                }
            ]
        }
    )

    with pytest.raises(IsolationError) as caught:
        await launch_isolated_scout(
            _request(root, input_bytes=input_bytes),
            executable=sys.executable,
            filesystem=ApplicationFilesystem(root=root),
            limits=ScoutProcessLimits(timeout_seconds=10),
        )

    assert caught.value.reason_code == "isolated_process_output"
    assert tuple(root.iterdir()) == ()


@pytest.mark.parametrize(
    ("body", "limits", "reason_code"),
    [
        (
            "while :; do :; done",
            ScoutProcessLimits(timeout_seconds=0.02),
            "isolated_process_timeout",
        ),
        (
            "printf 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'",
            ScoutProcessLimits(timeout_seconds=10, max_stdout_bytes=32),
            "isolated_process_stdout_overflow",
        ),
        (
            "printf 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' >&2",
            ScoutProcessLimits(timeout_seconds=10, max_stderr_bytes=32),
            "isolated_process_stderr_overflow",
        ),
    ],
)
async def test_process_timeout_and_pipe_overflow_are_bounded_and_cleaned_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    limits: ScoutProcessLimits,
    reason_code: str,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    executable = _write_executable(tmp_path / "synthetic-worker", body)
    processes: list[asyncio.subprocess.Process] = []
    original = asyncio.create_subprocess_exec

    async def recording_exec(
        *argv: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> asyncio.subprocess.Process:
        process = await original(*argv, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)

    with pytest.raises(IsolationError) as caught:
        await run_fresh_scout_process(
            executable=os.fspath(executable),
            request=_request(root),
            environment={
                "LANG": "C.UTF-8",
                "NO_PROXY": "*",
                "PYTHONNOUSERSITE": "1",
            },
            limits=limits,
        )

    assert caught.value.reason_code == reason_code
    assert len(processes) == 1
    assert processes[0].returncode is not None


async def test_process_cancellation_reaps_the_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _private_directory(tmp_path / "quarantine")
    executable = _write_executable(tmp_path / "synthetic-worker", "while :; do :; done")
    processes: list[asyncio.subprocess.Process] = []
    original = asyncio.create_subprocess_exec

    async def recording_exec(
        *argv: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> asyncio.subprocess.Process:
        process = await original(*argv, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)
    task = asyncio.create_task(
        run_fresh_scout_process(
            executable=os.fspath(executable),
            request=_request(root),
            environment={
                "LANG": "C.UTF-8",
                "NO_PROXY": "*",
                "PYTHONNOUSERSITE": "1",
            },
            limits=ScoutProcessLimits(timeout_seconds=2),
        )
    )
    while not processes:
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert processes[0].returncode is not None


def test_application_filesystem_production_default_omits_opener(
    tmp_path: Path,
) -> None:
    parameters = inspect.signature(ApplicationFilesystem.__init__).parameters
    assert parameters["opener"].default is None

    root = _private_directory(tmp_path / "quarantine")
    filesystem = ApplicationFilesystem(root=root)
    destination = filesystem.write_new("result.json", b"{}\n")

    assert filesystem._opener is None
    assert destination == root / "result.json"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.stat().st_nlink == 1


def test_discovery_package_does_not_construct_filesystem_with_injected_opener() -> None:
    root = Path(__file__).resolve().parents[4] / "src" / "openopps" / "discovery"
    injected: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            if isinstance(func, ast.Attribute):
                name = func.attr
            if name != "ApplicationFilesystem":
                continue
            if any(keyword.arg == "opener" for keyword in node.keywords):
                injected.append(path.name)
    assert injected == []
