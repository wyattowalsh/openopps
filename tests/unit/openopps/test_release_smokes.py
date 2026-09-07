"""Fail-closed contracts for isolated installed-wheel smoke scripts."""

from __future__ import annotations

import argparse
import base64
import builtins
import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import smoke_promotion_wheel as promotion_smoke
import smoke_wheel_catalog as catalog_smoke
import pytest


def test_promotion_smoke_reuses_catalog_trust_boundary_helpers() -> None:
    assert promotion_smoke._validate_direct_url is catalog_smoke._validate_direct_url
    assert promotion_smoke._record_path is catalog_smoke._record_path
    assert (
        promotion_smoke._read_recorded_installed_files
        is catalog_smoke._read_recorded_installed_files
    )
    assert promotion_smoke._read_bounded_file is catalog_smoke._read_bounded_file
    assert (
        promotion_smoke._preflight_wheel_archive
        is catalog_smoke._preflight_wheel_archive
    )
    assert (
        promotion_smoke._attest_installed_package
        is catalog_smoke._attest_installed_package
    )
    assert (
        promotion_smoke._attest_installed_wheel_payload
        is catalog_smoke._attest_installed_wheel_payload
    )
    assert (
        promotion_smoke._validate_openopps_wheel_layout
        is catalog_smoke._validate_openopps_wheel_layout
    )


def test_sanitized_environment_is_an_exact_narrow_allowlist() -> None:
    sanitized = catalog_smoke._sanitized_environment(
        {
            "HOME": "/safe-home",
            "LANG": "en_US.UTF-8",
            "PATH": "/safe-bin",
            "TMPDIR": "/safe-tmp",
            "PIP_CONFIG_FILE": "/tmp/attacker-pip.conf",
            "pip_extra_index_url": "https://attacker.invalid/simple",
            "PIP_INDEX_URL": "https://attacker.invalid/simple",
            "PIP_NO_INDEX": "1",
            "PYTHONHOME": "/tmp/python-home",
            "PYTHONOPTIMIZE": "2",
            "pythonpath": "/tmp/source-shadow",
            "VIRTUAL_ENV": "/tmp/ambient-venv",
            "HTTP_PROXY": "http://attacker.invalid:8080",
            "https_proxy": "http://attacker.invalid:8080",
            "ALL_PROXY": "socks5://attacker.invalid:1080",
            "NO_PROXY": "pypi.org",
            "SSL_CERT_FILE": "/tmp/attacker-ca.pem",
            "ssl_cert_dir": "/tmp/attacker-certs",
            "REQUESTS_CA_BUNDLE": "/tmp/attacker-ca.pem",
            "CURL_CA_BUNDLE": "/tmp/attacker-ca.pem",
            "NODE_EXTRA_CA_CERTS": "/tmp/attacker-ca.pem",
            "UV_CACHE_DIR": "/tmp/safe-cache",
            "UV_CONFIG_FILE": "/tmp/attacker-uv.toml",
            "UV_DEFAULT_INDEX": "https://attacker.invalid/simple",
            "UV_INDEX": "private=https://attacker.invalid/simple",
            "UV_NATIVE_TLS": "1",
            "UV_NO_PROGRESS": "1",
            "UV_OFFLINE": "1",
            "UV_SYSTEM_CERTS": "1",
            "OPENOPPS_TOKEN": "secret",
        }
    )

    assert sanitized == {
        "HOME": "/safe-home",
        "LANG": "en_US.UTF-8",
        "PATH": "/safe-bin",
        "TMPDIR": "/safe-tmp",
        "UV_CACHE_DIR": "/tmp/safe-cache",
        "UV_NO_PROGRESS": "1",
        "UV_OFFLINE": "1",
    }


def _write_wheel(
    path: Path,
    *,
    name: str = "OpenOpps",
    version: str = "0.1.1",
    metadata_members: int = 1,
    include_name: bool = True,
    include_version: bool = True,
) -> None:
    headers = ["Metadata-Version: 2.4"]
    if include_name:
        headers.append(f"Name: {name}")
    if include_version:
        headers.append(f"Version: {version}")
    metadata = ("\n".join(headers) + "\n").encode()
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(metadata_members):
            suffix = "" if index == 0 else f"-{index}"
            archive.writestr(f"openopps-{version}{suffix}.dist-info/METADATA", metadata)


def _write_release_wheel(
    path: Path,
    *,
    extra_members: dict[str, bytes] | None = None,
    entry_points: bytes = catalog_smoke._EXPECTED_ENTRY_POINTS,
    record_mutation: str | None = None,
) -> None:
    version = "0.1.1"
    dist_info = f"openopps-{version}.dist-info"
    metadata = (f"Metadata-Version: 2.4\nName: OpenOpps\nVersion: {version}\n").encode()
    members = {
        "openopps/__init__.py": b'__version__ = "0.1.1"\n',
        "examples/examples.py": b"# packaged example\n",
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        f"{dist_info}/entry_points.txt": entry_points,
        f"{dist_info}/licenses/LICENSE": b"test license\n",
    }
    if extra_members is not None:
        members.update(extra_members)
    record_path = f"{dist_info}/RECORD"
    record_rows = {
        relative: _record_row(relative, payload)
        for relative, payload in members.items()
    }
    self_row = f"{record_path},,\n"
    target = "openopps/__init__.py"
    if record_mutation == "missing_member":
        del record_rows[target]
    elif record_mutation == "extra_member":
        record_rows["ghost.py"] = _record_row("ghost.py", b"ghost\n")
    elif record_mutation == "wrong_digest":
        size = len(members[target])
        record_rows[target] = f"{target},sha256={'A' * 43},{size}\n"
    elif record_mutation == "wrong_size":
        row_prefix = record_rows[target].rsplit(",", maxsplit=1)[0]
        record_rows[target] = f"{row_prefix},{len(members[target]) + 1}\n"
    elif record_mutation == "noncanonical_size":
        row_prefix = record_rows[target].rsplit(",", maxsplit=1)[0]
        record_rows[target] = f"{row_prefix},0{len(members[target])}\n"
    elif record_mutation == "hashed_self":
        self_row = f"{record_path},sha256={'A' * 43},1\n"
    elif record_mutation is not None:
        raise ValueError(f"unknown RECORD mutation: {record_mutation}")
    record = ("".join(record_rows.values()) + self_row).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for relative, payload in members.items():
            archive.writestr(relative, payload)
        archive.writestr(record_path, record)


def _mark_first_wheel_member_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = payload.find(signature)
        if position < 0:
            raise RuntimeError(f"wheel header is missing: {signature!r}")
        start = position + flag_offset
        flags = int.from_bytes(payload[start : start + 2], "little") | 0x1
        payload[start : start + 2] = flags.to_bytes(2, "little")
    path.write_bytes(payload)


def test_select_openopps_wheel_accepts_build_and_platform_tags(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-2-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(wheel)

    selected = catalog_smoke._select_openopps_wheel(tmp_path)

    assert selected.path == wheel.resolve()
    assert selected.name == "OpenOpps"
    assert selected.version == "0.1.1"
    assert selected.sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_select_openopps_wheel_allows_unrelated_wheel(tmp_path: Path) -> None:
    unrelated = tmp_path / "other_project-9.0-py3-none-any.whl"
    _write_wheel(unrelated, name="other-project", version="9.0")
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel(wheel)

    selected = catalog_smoke._select_openopps_wheel(tmp_path)

    assert selected.path == wheel.resolve()


def test_select_openopps_wheel_rejects_zero_matches(tmp_path: Path) -> None:
    _write_wheel(
        tmp_path / "other_project-9.0-py3-none-any.whl",
        name="other-project",
        version="9.0",
    )

    with pytest.raises(RuntimeError, match="exactly one OpenOpps wheel"):
        catalog_smoke._select_openopps_wheel(tmp_path)


def test_select_openopps_wheel_rejects_multiple_matches(tmp_path: Path) -> None:
    for build in ("1", "2"):
        _write_wheel(tmp_path / f"openopps-0.1.1-{build}-py3-none-any.whl")

    with pytest.raises(RuntimeError, match="exactly one OpenOpps wheel"):
        catalog_smoke._select_openopps_wheel(tmp_path)


def test_select_openopps_wheel_rejects_matching_directory(tmp_path: Path) -> None:
    (tmp_path / "openopps-0.1.1-py3-none-any.whl").mkdir()

    with pytest.raises(RuntimeError, match="regular file"):
        catalog_smoke._select_openopps_wheel(tmp_path)


def test_select_openopps_wheel_rejects_escaping_symlink(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    outside = tmp_path / "outside-openopps.whl"
    _write_wheel(outside)
    (wheel_dir / "openopps-0.1.1-py3-none-any.whl").symlink_to(outside)

    with pytest.raises(RuntimeError, match="symlink"):
        catalog_smoke._select_openopps_wheel(wheel_dir)


@pytest.mark.parametrize(
    ("metadata_members", "include_name", "include_version", "message"),
    [
        (0, True, True, "invalid member count"),
        (2, True, True, "METADATA"),
        (1, False, True, "Name"),
        (1, True, False, "Version"),
    ],
)
def test_select_openopps_wheel_rejects_missing_or_ambiguous_metadata(
    tmp_path: Path,
    metadata_members: int,
    include_name: bool,
    include_version: bool,
    message: str,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel(
        wheel,
        metadata_members=metadata_members,
        include_name=include_name,
        include_version=include_version,
    )

    with pytest.raises(RuntimeError, match=message):
        catalog_smoke._select_openopps_wheel(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unsafe", "not normalized"),
        ("duplicate", "duplicate member path"),
        ("encrypted", "must not be encrypted"),
        ("symlink", "must not be a symlink"),
    ],
)
def test_archive_preflight_rejects_unsafe_member_metadata(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel(wheel)
    if mutation == "unsafe":
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("../escape.py", b"escape")
    elif mutation == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("openopps-0.1.1.dist-info/METADATA", b"duplicate")
    elif mutation == "encrypted":
        _mark_first_wheel_member_encrypted(wheel)
    else:
        link = zipfile.ZipInfo("openopps/link.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(link, b"../../outside")

    with pytest.raises(RuntimeError, match=message):
        catalog_smoke._preflight_wheel_archive(wheel)


def test_archive_preflight_enforces_member_count_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("one", b"1")
        archive.writestr("two", b"2")
        archive.writestr("three", b"3")
    monkeypatch.setattr(catalog_smoke, "_MAX_WHEEL_MEMBERS", 2)

    with pytest.raises(RuntimeError, match="member count"):
        catalog_smoke._preflight_wheel_archive(wheel)


def test_archive_preflight_enforces_per_member_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("oversized", b"12345")
    monkeypatch.setattr(catalog_smoke, "_MAX_WHEEL_MEMBER_BYTES", 4)

    with pytest.raises(RuntimeError, match="member exceeds its byte limit"):
        catalog_smoke._preflight_wheel_archive(wheel)


def test_archive_preflight_enforces_aggregate_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("one", b"1234")
        archive.writestr("two", b"5678")
    monkeypatch.setattr(catalog_smoke, "_MAX_WHEEL_UNCOMPRESSED_BYTES", 7)

    with pytest.raises(RuntimeError, match="aggregate uncompressed"):
        catalog_smoke._preflight_wheel_archive(wheel)


def test_archive_preflight_rejects_unsafe_compression_ratio_for_required_member(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    required = "openopps/resource.json"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(required, b"0" * 4_096)
    monkeypatch.setattr(catalog_smoke, "_MAX_METADATA_BYTES", 1)
    monkeypatch.setattr(catalog_smoke, "_MAX_COMPRESSION_RATIO", 2)

    with pytest.raises(RuntimeError, match="unsafe compression ratio"):
        catalog_smoke._preflight_wheel_archive(wheel, required_paths=(required,))


def test_release_wheel_layout_accepts_only_expected_payloads(tmp_path: Path) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_release_wheel(wheel)

    paths = catalog_smoke._validate_openopps_wheel_layout(wheel, "0.1.1")

    assert "openopps/__init__.py" in paths
    assert "examples/examples.py" in paths
    assert f"{catalog_smoke._EXPECTED_DIST_INFO_ROOT}/RECORD" in paths


@pytest.mark.parametrize(
    ("record_mutation", "message"),
    [
        ("missing_member", "inventory does not match"),
        ("extra_member", "inventory does not match"),
        ("wrong_digest", "hash does not match archive member"),
        ("wrong_size", "size does not match archive member"),
        ("noncanonical_size", "size is invalid"),
        ("hashed_self", "self-entry must not contain a hash or size"),
    ],
)
def test_release_wheel_layout_rejects_invalid_archive_record(
    tmp_path: Path,
    record_mutation: str,
    message: str,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_release_wheel(wheel, record_mutation=record_mutation)

    with pytest.raises(RuntimeError, match=message):
        catalog_smoke._validate_openopps_wheel_layout(wheel, "0.1.1")


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("startup_hook.pth", "unexpected payload"),
        ("sitecustomize.py", "unexpected payload"),
        ("sqlmodel/__init__.py", "unexpected payload"),
        ("openopps-0.1.1.data/scripts/python", "unexpected payload"),
        ("shadow-1.0.dist-info/METADATA", "dist-info tree"),
    ],
)
def test_release_wheel_layout_rejects_unscoped_payloads(
    tmp_path: Path,
    relative: str,
    message: str,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_release_wheel(wheel, extra_members={relative: b"malicious\n"})

    with pytest.raises(RuntimeError, match=message):
        catalog_smoke._validate_openopps_wheel_layout(wheel, "0.1.1")


def test_release_wheel_layout_rejects_unexpected_console_scripts(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_release_wheel(
        wheel,
        entry_points=(
            b"[console_scripts]\n"
            b"openopps = openopps.cli:app\n"
            b"python = openopps.cli:app\n"
        ),
    )

    with pytest.raises(RuntimeError, match="console entry point"):
        catalog_smoke._validate_openopps_wheel_layout(wheel, "0.1.1")


def test_release_wheel_layout_is_checked_before_runtime_creation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_release_wheel(
        wheel,
        extra_members={
            **{
                relative: b"resource"
                for relative in catalog_smoke._REQUIRED_RESOURCE_PATHS
            },
            "startup_hook.pth": b"import payload\n",
        },
    )
    runtime_calls: list[object] = []
    monkeypatch.setattr(
        catalog_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(catalog_smoke, "_validated_uv_bin", lambda _path: "/tool/uv")
    monkeypatch.setattr(
        catalog_smoke,
        "_prepare_locked_runtime",
        lambda *args, **kwargs: runtime_calls.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="unexpected payload"):
        catalog_smoke.main()

    assert runtime_calls == []


def test_archive_preflight_happens_before_runtime_creation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel(wheel)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("../escape.py", b"escape")
    runtime_calls: list[object] = []
    monkeypatch.setattr(
        catalog_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(catalog_smoke, "_validated_uv_bin", lambda _path: "/tool/uv")
    monkeypatch.setattr(
        catalog_smoke,
        "_prepare_locked_runtime",
        lambda *args, **kwargs: runtime_calls.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="not normalized"):
        catalog_smoke.main()

    assert runtime_calls == []


def test_exported_requirements_accept_only_hashed_locked_requirements(
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "example==1.2.3 ; python_version >= '3.12' \\\n"
        f"    --hash=sha256:{'a' * 64} \\\n"
        f"    --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )

    catalog_smoke._validate_exported_requirements(requirements)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (
            "--extra-index-url https://attacker.invalid/simple\n"
            f"example==1.2.3 --hash=sha256:{'a' * 64}\n",
            "directive",
        ),
        (
            f"example @ https://attacker.invalid/example.whl --hash=sha256:{'a' * 64}\n",
            "direct reference",
        ),
        ("example==1.2.3\n", "hash"),
        (f"example>=1 --hash=sha256:{'a' * 64}\n", "exactly pinned"),
        (
            f"example==1.2.3 --hash=sha256:{'a' * 64} "
            "--trusted-host attacker.invalid\n",
            "post-hash",
        ),
    ],
)
def test_exported_requirements_reject_source_and_integrity_escapes(
    tmp_path: Path, contents: str, message: str
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        catalog_smoke._validate_exported_requirements(requirements)


@pytest.mark.parametrize(
    "label",
    ["installed direct_url.json", "installed RECORD"],
)
def test_metadata_reads_are_bounded_without_path_read_bytes(
    monkeypatch,
    tmp_path: Path,
    label: str,
) -> None:
    path = tmp_path / "metadata"
    path.write_bytes(b"12345")

    def reject_unbounded_read(_path: Path) -> bytes:
        raise AssertionError("Path.read_bytes must not be used for installed metadata")

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)

    with pytest.raises(RuntimeError, match="exceeds its byte limit"):
        catalog_smoke._read_bounded_file(path, limit=4, label=label)


@pytest.mark.parametrize("label", ["resource", "artifact", "package file"])
def test_installed_payload_reads_are_bounded_without_path_read_bytes(
    monkeypatch,
    tmp_path: Path,
    label: str,
) -> None:
    relative = "openopps/payload.bin"
    payload = b"12345"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    record = _record_row(relative, payload).encode()

    def reject_unbounded_read(_path: Path) -> bytes:
        raise AssertionError("Path.read_bytes must not be used for installed payloads")

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)

    with pytest.raises(RuntimeError, match="exceeds its byte limit"):
        catalog_smoke._read_recorded_installed_files(
            record,
            tmp_path,
            (relative,),
            label=label,
            max_file_bytes=4,
            max_total_bytes=4,
        )


def test_explicit_uv_bin_must_be_absolute_regular_and_executable(
    tmp_path: Path,
) -> None:
    relative = Path("uv")
    with pytest.raises(RuntimeError, match="absolute"):
        catalog_smoke._validated_uv_bin(relative)

    missing = tmp_path / "missing-uv"
    with pytest.raises(RuntimeError, match="regular executable"):
        catalog_smoke._validated_uv_bin(missing)

    directory = tmp_path / "uv-directory"
    directory.mkdir()
    with pytest.raises(RuntimeError, match="regular executable"):
        catalog_smoke._validated_uv_bin(directory)

    executable = tmp_path / "uv"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    assert catalog_smoke._validated_uv_bin(executable) == str(executable.resolve())


def test_parse_args_requires_explicit_uv_bin(monkeypatch, tmp_path: Path) -> None:
    uv = tmp_path / "uv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_wheel_catalog.py",
            "--wheel-dir",
            str(tmp_path),
            "--uv-bin",
            str(uv),
        ],
    )

    args = catalog_smoke._parse_args()

    assert args.wheel_dir == tmp_path
    assert args.validate_requirements is None
    assert args.uv_bin == uv


def test_requirements_validation_mode_is_standalone(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        f"example==1.2.3 --hash=sha256:{'a' * 64}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_wheel_catalog.py",
            "--validate-requirements",
            str(requirements),
        ],
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_validated_uv_bin",
        lambda _path: (_ for _ in ()).throw(AssertionError("uv path was reached")),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_select_openopps_wheel",
        lambda _path: (_ for _ in ()).throw(AssertionError("wheel path was reached")),
    )

    assert catalog_smoke.main() == 0
    assert capsys.readouterr().out == f"requirements-lock ok {requirements}\n"


def test_requirements_validation_mode_rejects_invalid_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_wheel_catalog.py",
            "--validate-requirements",
            str(requirements),
        ],
    )

    with pytest.raises(RuntimeError, match="hash"):
        catalog_smoke.main()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--validate-requirements", "requirements.txt", "--uv-bin", "/tool/uv"],
        [
            "--validate-requirements",
            "requirements.txt",
            "--wheel-dir",
            "dist",
            "--uv-bin",
            "/tool/uv",
        ],
    ],
)
def test_requirements_validation_mode_rejects_ambiguous_arguments(
    monkeypatch,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["smoke_wheel_catalog.py", *arguments])

    with pytest.raises(SystemExit, match="2"):
        catalog_smoke._parse_args()


def test_locked_runtime_uses_hash_sync_then_dependency_free_wheel_install(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.touch()
    sanitized = {"PATH": "/safe-bin", "UV_CACHE_DIR": "/tmp/safe-cache"}
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    monkeypatch.setattr(catalog_smoke, "_sanitized_environment", lambda: sanitized)

    def capture_call(command, *, cwd, env):
        calls.append((list(command), Path(cwd), dict(env)))
        if "export" in command:
            (tmp_path / "runtime-requirements.txt").write_text(
                f"example==1.2.3 --hash=sha256:{'a' * 64}\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(subprocess, "check_call", capture_call)

    wheel_sha256 = "b" * 64
    python, returned_env = catalog_smoke._prepare_locked_runtime(
        "/tool/uv", wheel, wheel_sha256, tmp_path
    )

    assert python == catalog_smoke._venv_python(tmp_path / "venv")
    assert returned_env == sanitized
    assert len(calls) == 5

    common = ["/tool/uv", "--no-config", "--no-python-downloads"]
    export, create_venv, sync, install, check = calls
    assert export == (
        common
        + [
            "--quiet",
            "export",
            "--locked",
            "--no-sources",
            "--format",
            "requirements.txt",
            "--no-dev",
            "--no-emit-project",
            "--no-emit-local",
            "--no-emit-index-url",
            "--output-file",
            str(tmp_path / "runtime-requirements.txt"),
        ],
        catalog_smoke._REPO_ROOT,
        sanitized,
    )
    assert create_venv == (
        common
        + [
            "venv",
            "--no-project",
            "--python",
            catalog_smoke.sys.executable,
            str(tmp_path / "venv"),
        ],
        tmp_path,
        sanitized,
    )
    assert sync == (
        common
        + [
            "pip",
            "sync",
            "--python",
            str(python),
            "--require-hashes",
            "--strict",
            "--no-build",
            "--no-sources",
            "--default-index",
            "https://pypi.org/simple",
            "--index-strategy",
            "first-index",
            "--keyring-provider",
            "disabled",
            str(tmp_path / "runtime-requirements.txt"),
        ],
        tmp_path,
        sanitized,
    )
    assert install == (
        common
        + [
            "pip",
            "install",
            "--python",
            str(python),
            "--offline",
            "--no-deps",
            "--no-build",
            "--no-index",
            "--no-sources",
            "--keyring-provider",
            "disabled",
            "--strict",
            (f"openopps @ {wheel.resolve().as_uri()}#sha256={wheel_sha256}"),
        ],
        tmp_path,
        sanitized,
    )
    assert check == (
        common + ["pip", "check", "--python", str(python)],
        tmp_path,
        sanitized,
    )


def test_dependency_free_local_install_command_is_exact(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.touch()
    wheel_sha256 = "a" * 64
    python = tmp_path / "venv" / "bin" / "python"
    env = {"PATH": "/safe-bin"}
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def capture_call(command, *, cwd, env):
        calls.append((list(command), Path(cwd), dict(env)))

    monkeypatch.setattr(subprocess, "check_call", capture_call)

    catalog_smoke._install_local_wheel(
        "/tool/uv",
        python,
        wheel,
        wheel_sha256,
        cwd=tmp_path,
        env=env,
        strict=False,
    )

    assert calls == [
        (
            [
                "/tool/uv",
                "--no-config",
                "--no-python-downloads",
                "pip",
                "install",
                "--python",
                str(python),
                "--offline",
                "--no-deps",
                "--no-build",
                "--no-index",
                "--no-sources",
                "--keyring-provider",
                "disabled",
                (f"openopps @ {wheel.resolve().as_uri()}#sha256={wheel_sha256}"),
            ],
            tmp_path,
            env,
        )
    ]


def test_promotion_smoke_installs_only_the_selected_wheel(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel_artifacts(
        wheel,
        {
            relative: relative.encode()
            for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS
        },
    )
    sanitized = {"PATH": "/safe-bin"}
    installs: list[tuple[str, Path, Path, str, Path, dict[str, str], bool]] = []
    verifier_calls: list[
        tuple[Path, Path, catalog_smoke.WheelArtifact, Path, dict[str, str]]
    ] = []

    monkeypatch.setattr(
        promotion_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(promotion_smoke, "_sanitized_environment", lambda: sanitized)
    monkeypatch.setattr(
        promotion_smoke,
        "_validated_uv_bin",
        lambda uv_bin: str(uv_bin),
    )

    def create_venv(uv, env_dir, *, cwd, env):
        assert uv == "/tool/uv"
        assert env == sanitized
        assert Path(cwd) == env_dir.parent
        return catalog_smoke._venv_python(env_dir)

    def install_wheel(
        uv,
        python,
        selected_wheel,
        selected_sha256,
        *,
        cwd,
        env,
        strict,
    ):
        installs.append(
            (
                uv,
                python,
                selected_wheel,
                selected_sha256,
                Path(cwd),
                dict(env),
                strict,
            )
        )

    def run_verifier(python, site_packages, selected, *, cwd, env):
        verifier_calls.append((python, site_packages, selected, Path(cwd), dict(env)))

    monkeypatch.setattr(promotion_smoke, "_create_uv_venv", create_venv)
    monkeypatch.setattr(promotion_smoke, "_install_local_wheel", install_wheel)
    monkeypatch.setattr(
        promotion_smoke, "_run_installed_promotion_verifier", run_verifier
    )

    assert promotion_smoke.main() == 0
    assert len(installs) == 1
    (
        uv,
        python,
        selected_wheel,
        selected_sha256,
        work_dir,
        install_env,
        strict,
    ) = installs[0]
    selected = catalog_smoke._select_openopps_wheel(tmp_path)
    assert uv == "/tool/uv"
    assert python == catalog_smoke._venv_python(work_dir / "venv")
    assert selected_wheel == selected.path
    assert selected_sha256 == selected.sha256
    assert install_env == sanitized
    assert strict is False
    assert verifier_calls == [
        (
            python,
            catalog_smoke._venv_site_packages(work_dir / "venv"),
            selected,
            work_dir,
            sanitized,
        )
    ]


_SOURCE_CATALOG_ROOT = catalog_smoke._REPO_ROOT / "src/openopps/providers/sources/data"
_SOURCE_PROMOTION_ROOT = catalog_smoke._REPO_ROOT / "src/openopps/discovery/data"


def _catalog_resource_bytes() -> tuple[bytes, bytes, bytes]:
    return (
        (_SOURCE_CATALOG_ROOT / "portfolio_source_catalog.json").read_bytes(),
        (_SOURCE_CATALOG_ROOT / "source_policy_evidence.json").read_bytes(),
        (_SOURCE_CATALOG_ROOT / "source_policy_evidence.schema.json").read_bytes(),
    )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _mutated_catalog_resources(resource: str) -> tuple[bytes, bytes, bytes]:
    catalog_raw, evidence_raw, schema_raw = _catalog_resource_bytes()
    if resource == "catalog":
        payload = json.loads(catalog_raw)
        payload["entries"][0]["url"] = "https://attacker.invalid/shape-preserving"
        catalog_raw = json.dumps(payload, indent=2).encode() + b"\n"
    elif resource == "evidence":
        payload = json.loads(evidence_raw)
        payload["reviewedAt"] = "2026-08-14"
        evidence_raw = _canonical_bytes(payload)
    elif resource == "schema":
        payload = json.loads(schema_raw)
        payload["$defs"]["PolicyAxes"]["description"] += " Tampered."
        schema_raw = _canonical_bytes(payload)
    else:  # pragma: no cover - test helper misuse
        raise ValueError(f"unknown resource: {resource}")
    return catalog_raw, evidence_raw, schema_raw


def _record_row(relative: str, payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return f"{relative},sha256={digest.decode()},{len(payload)}\n"


def _write_installed_catalog_fixture(
    tmp_path: Path,
    *,
    catalog_raw: bytes,
    evidence_raw: bytes,
    schema_raw: bytes,
    extra_package_members: dict[str, bytes] | None = None,
) -> tuple[Path, Path, str, Path]:
    version = "0.1.1"
    if sys.platform == "win32":
        site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    else:
        site_packages = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    dist_info = f"openopps-{version}.dist-info"
    marker = tmp_path / "candidate-imported"
    init_payload = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('candidate package imported')\n"
    ).encode()
    metadata = (f"Metadata-Version: 2.4\nName: OpenOpps\nVersion: {version}\n").encode()
    wheel_metadata = (
        "Wheel-Version: 1.0\n"
        "Generator: release-smoke-test\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode()
    package_members = {"openopps/__init__.py": init_payload}
    if extra_package_members is not None:
        package_members.update(extra_package_members)
    wheel_members = {
        **package_members,
        str(catalog_smoke._CATALOG_RELATIVE_PATH): catalog_raw,
        str(catalog_smoke._EVIDENCE_RELATIVE_PATH): evidence_raw,
        str(catalog_smoke._SCHEMA_RELATIVE_PATH): schema_raw,
        "examples/examples.py": b"# packaged example\n",
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
        f"{dist_info}/entry_points.txt": catalog_smoke._EXPECTED_ENTRY_POINTS,
        f"{dist_info}/licenses/LICENSE": b"test license\n",
    }
    wheel_record_path = f"{dist_info}/RECORD"
    wheel_record = (
        "".join(
            _record_row(relative, payload)
            for relative, payload in wheel_members.items()
        )
        + f"{wheel_record_path},,\n"
    )
    wheel = tmp_path / f"openopps-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for relative, payload in wheel_members.items():
            archive.writestr(relative, payload)
        archive.writestr(wheel_record_path, wheel_record.encode())
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()

    direct_url = _canonical_bytes(
        {
            "archive_info": {
                "hash": f"sha256={wheel_sha256}",
                "hashes": {"sha256": wheel_sha256},
            },
            "url": wheel.resolve().as_uri(),
        }
    )
    installed_members = {
        **wheel_members,
        f"{dist_info}/direct_url.json": direct_url,
    }
    expected_console = catalog_smoke._expected_console_script_record(site_packages)
    assert expected_console is not None
    console_relative, console_path = expected_console
    console_payload = b'#!/bin/sh\nexec python -m openopps "$@"\n'
    installed_record = (
        "".join(
            _record_row(relative, payload)
            for relative, payload in installed_members.items()
        )
        + _record_row(console_relative, console_payload)
        + f"{wheel_record_path},,\n"
    )
    installed_members[wheel_record_path] = installed_record.encode()
    for relative, payload in installed_members.items():
        target = site_packages / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    console_path.parent.mkdir(parents=True, exist_ok=True)
    console_path.write_bytes(console_payload)
    return site_packages, wheel, wheel_sha256, marker


def _run_package_attestation_process(
    site_packages: Path,
    wheel: Path,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    record = site_packages / "openopps-0.1.1.dist-info/RECORD"
    code = (
        "import importlib.util,pathlib,sys;"
        "spec=importlib.util.spec_from_file_location('catalog_under_test',sys.argv[1]);"
        "module=importlib.util.module_from_spec(spec);"
        "sys.modules[spec.name]=module;"
        "spec.loader.exec_module(module);"
        "site=pathlib.Path(sys.argv[2]).resolve(strict=True);"
        "sys.path.insert(0,str(site));"
        "record=pathlib.Path(sys.argv[4]).read_bytes();"
        "allowed=module._validated_external_record_paths(record,site);"
        "module._attest_installed_package("
        "pathlib.Path(sys.argv[3]),record,site,site,allowed_external_paths=allowed)"
    )
    return subprocess.run(
        [
            sys.executable,
            "-O",
            "-I",
            "-S",
            "-B",
            "-c",
            code,
            str(Path(catalog_smoke.__file__).resolve()),
            str(site_packages),
            str(wheel),
            str(record),
        ],
        cwd=cwd,
        env={},
        check=False,
        capture_output=True,
        text=True,
    )


def _run_catalog_verifier_process(
    site_packages: Path,
    wheel: Path,
    wheel_sha256: str,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-O",
            "-I",
            "-S",
            "-B",
            "-c",
            catalog_smoke._ISOLATED_FUNCTION_BOOTSTRAP,
            str(Path(catalog_smoke.__file__).resolve()),
            "_installed_catalog_verifier",
            str(site_packages),
            str(wheel),
            "0.1.1",
            wheel_sha256,
        ],
        cwd=cwd,
        env={},
        check=False,
        capture_output=True,
        text=True,
    )


def test_full_installed_package_attestation_accepts_exact_wheel_bytes(
    tmp_path: Path,
) -> None:
    site_packages, wheel, _wheel_sha256, marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=_catalog_resource_bytes()[0],
        evidence_raw=_catalog_resource_bytes()[1],
        schema_raw=_catalog_resource_bytes()[2],
    )

    completed = _run_package_attestation_process(
        site_packages,
        wheel,
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert not marker.exists(), "package attestation executed candidate __init__.py"


@pytest.mark.parametrize(
    ("relative", "mutation", "message"),
    [
        ("openopps/__init__.py", "modified", "hash does not match wheel payload"),
        ("openopps/__init__.py", "symlink", "contains a symlink"),
        (
            "openopps/discovery/inventory.py",
            "modified",
            "hash does not match wheel payload",
        ),
        ("openopps/discovery/inventory.py", "symlink", "contains a symlink"),
    ],
)
def test_installed_package_mutation_is_rejected_before_candidate_execution(
    tmp_path: Path,
    relative: str,
    mutation: str,
    message: str,
) -> None:
    inventory_marker = tmp_path / "inventory-imported"
    inventory_payload = (
        "from pathlib import Path\n"
        f"Path({str(inventory_marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('candidate inventory imported')\n"
    ).encode()
    site_packages, wheel, wheel_sha256, init_marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=_catalog_resource_bytes()[0],
        evidence_raw=_catalog_resource_bytes()[1],
        schema_raw=_catalog_resource_bytes()[2],
        extra_package_members={
            "openopps/discovery/__init__.py": b"# package\n",
            "openopps/discovery/inventory.py": inventory_payload,
        },
    )
    target = site_packages / relative
    if mutation == "modified":
        target.write_bytes(b"tampered")
    else:
        outside = tmp_path / f"outside-{target.name}"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)

    completed = _run_catalog_verifier_process(
        site_packages,
        wheel,
        wheel_sha256,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not init_marker.exists(), (
        "candidate __init__.py ran before package attestation"
    )
    assert not inventory_marker.exists(), (
        "candidate inventory ran before package attestation"
    )


def test_top_level_openopps_shadow_is_rejected_before_candidate_execution(
    tmp_path: Path,
) -> None:
    site_packages, wheel, wheel_sha256, init_marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=_catalog_resource_bytes()[0],
        evidence_raw=_catalog_resource_bytes()[1],
        schema_raw=_catalog_resource_bytes()[2],
    )
    shadow_marker = tmp_path / "shadow-imported"
    (site_packages / "openopps.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(shadow_marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )

    completed = _run_catalog_verifier_process(
        site_packages,
        wheel,
        wheel_sha256,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert "import is shadowed by openopps.py" in completed.stderr
    assert not init_marker.exists(), "candidate __init__.py ran before shadow rejection"
    assert not shadow_marker.exists(), "shadow module ran before shadow rejection"


def test_unexpected_installed_record_payload_is_rejected_before_candidate_execution(
    tmp_path: Path,
) -> None:
    site_packages, wheel, wheel_sha256, init_marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=_catalog_resource_bytes()[0],
        evidence_raw=_catalog_resource_bytes()[1],
        schema_raw=_catalog_resource_bytes()[2],
    )
    payload = b"import attacker_payload\n"
    unexpected = site_packages / "startup_hook.pth"
    unexpected.write_bytes(payload)
    record = site_packages / "openopps-0.1.1.dist-info/RECORD"
    record.write_bytes(
        record.read_bytes() + _record_row("startup_hook.pth", payload).encode()
    )

    completed = _run_catalog_verifier_process(
        site_packages,
        wheel,
        wheel_sha256,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert "installed RECORD contains an unexpected payload" in completed.stderr
    assert not init_marker.exists(), (
        "candidate code ran before RECORD inventory rejection"
    )


def test_unrecorded_installed_metadata_is_rejected_before_candidate_execution(
    tmp_path: Path,
) -> None:
    site_packages, wheel, wheel_sha256, init_marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=_catalog_resource_bytes()[0],
        evidence_raw=_catalog_resource_bytes()[1],
        schema_raw=_catalog_resource_bytes()[2],
    )
    rogue = site_packages / "openopps-0.1.1.dist-info/rogue.txt"
    rogue.write_text("rogue\n", encoding="utf-8")

    completed = _run_catalog_verifier_process(
        site_packages,
        wheel,
        wheel_sha256,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert "installed .dist-info file set does not match RECORD" in completed.stderr
    assert not init_marker.exists(), "candidate code ran before metadata-tree rejection"


def test_catalog_resource_verifier_accepts_current_release_identity() -> None:
    readback = catalog_smoke._validate_catalog_resources(*_catalog_resource_bytes())

    assert readback.version == 2
    assert readback.count == 2239
    assert (
        readback.fingerprint
        == "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
    )
    assert (
        readback.file_sha256
        == "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
    )


def test_catalog_raw_digest_is_attested_before_candidate_import(
    monkeypatch,
) -> None:
    catalog_raw, evidence_raw, schema_raw = _catalog_resource_bytes()
    altered_raw = catalog_raw + b" "
    real_import = builtins.__import__

    def reject_candidate_import(name, *args, **kwargs):
        if name.startswith("openopps"):
            raise AssertionError("candidate-wheel code was imported")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_candidate_import)

    with pytest.raises(RuntimeError, match="catalog file digest"):
        catalog_smoke._validate_catalog_resources(
            altered_raw,
            evidence_raw,
            schema_raw,
        )


def test_catalog_semantic_fingerprint_is_independent_of_forged_readback(
    monkeypatch,
) -> None:
    catalog_raw, evidence_raw, schema_raw = _catalog_resource_bytes()
    payload = json.loads(catalog_raw)
    payload["entries"][0]["url"] = "https://attacker.invalid/forged"
    altered_raw = json.dumps(payload, indent=2).encode() + b"\n"
    altered_digest = hashlib.sha256(altered_raw).hexdigest()

    from openopps.discovery import inventory

    forged = SimpleNamespace(
        version=catalog_smoke._EXPECTED_CATALOG_VERSION,
        count=catalog_smoke._EXPECTED_CATALOG_COUNT,
        fingerprint=catalog_smoke._EXPECTED_CATALOG_FINGERPRINT,
        file_sha256=altered_digest,
    )
    monkeypatch.setattr(
        inventory,
        "read_packaged_catalog_bytes",
        lambda raw: forged,
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_EXPECTED_CATALOG_SHA256",
        altered_digest,
    )

    with pytest.raises(RuntimeError, match="fingerprint"):
        catalog_smoke._validate_catalog_resources(
            altered_raw,
            evidence_raw,
            schema_raw,
        )


@pytest.mark.parametrize("resource", ["catalog", "evidence", "schema"])
def test_catalog_resource_verifier_rejects_bad_installed_data(
    resource: str,
) -> None:
    catalog_raw, evidence_raw, schema_raw = _catalog_resource_bytes()
    if resource == "catalog":
        payload = json.loads(catalog_raw)
        payload["count"] = True
        catalog_raw = json.dumps(payload).encode()
    elif resource == "evidence":
        payload = json.loads(evidence_raw)
        payload["schemaVersion"] = True
        evidence_raw = _canonical_bytes(payload)
    else:
        payload = json.loads(schema_raw)
        payload["title"] = "WrongSourcePolicyEvidence"
        schema_raw = _canonical_bytes(payload)

    with pytest.raises((RuntimeError, ValueError)):
        catalog_smoke._validate_catalog_resources(catalog_raw, evidence_raw, schema_raw)


def test_catalog_resource_verifier_rejects_duplicate_catalog_keys() -> None:
    _catalog_raw, evidence_raw, schema_raw = _catalog_resource_bytes()
    duplicate = b'{"count":0,"count":0,"entries":[],"fingerprint":"","version":2}'

    with pytest.raises((RuntimeError, ValueError), match="duplicate"):
        catalog_smoke._validate_catalog_resources(duplicate, evidence_raw, schema_raw)


@pytest.mark.parametrize("resource", ["catalog", "evidence", "schema"])
def test_catalog_resource_verifier_rejects_shape_preserving_mutation(
    resource: str,
) -> None:
    with pytest.raises(RuntimeError, match=resource):
        catalog_smoke._validate_catalog_resources(*_mutated_catalog_resources(resource))


def test_catalog_semantic_fingerprint_matches_production_implementation() -> None:
    from openopps.providers.sources.source_utils import (
        portfolio_source_catalog_fingerprint,
    )

    payload = json.loads(_catalog_resource_bytes()[0])
    entries = payload["entries"]

    smoke_fingerprint = catalog_smoke._catalog_semantic_fingerprint(entries)
    production_fingerprint = portfolio_source_catalog_fingerprint(entries)

    assert smoke_fingerprint == production_fingerprint == payload["fingerprint"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", "changed-key"),
        ("url", "https://example.invalid/changed"),
        ("provider_id", "changed-provider"),
        ("version", {"revision": "changed"}),
        ("raw_metadata", {"changed": True}),
    ],
)
def test_catalog_semantic_fingerprint_field_differentials_match_production(
    field: str,
    value: object,
) -> None:
    from openopps.providers.sources.source_utils import (
        portfolio_source_catalog_fingerprint,
    )

    payload = json.loads(_catalog_resource_bytes()[0])
    entries = json.loads(json.dumps(payload["entries"][:2]))
    baseline = catalog_smoke._catalog_semantic_fingerprint(entries)
    entries[0][field] = value

    smoke_fingerprint = catalog_smoke._catalog_semantic_fingerprint(entries)
    production_fingerprint = portfolio_source_catalog_fingerprint(entries)

    assert smoke_fingerprint == production_fingerprint
    assert smoke_fingerprint != baseline


@pytest.mark.parametrize("resource", ["catalog", "evidence", "schema"])
def test_real_installed_verifier_attests_resources_before_candidate_import(
    resource: str,
    tmp_path: Path,
) -> None:
    catalog_raw, evidence_raw, schema_raw = _mutated_catalog_resources(resource)
    site_packages, wheel, wheel_sha256, marker = _write_installed_catalog_fixture(
        tmp_path,
        catalog_raw=catalog_raw,
        evidence_raw=evidence_raw,
        schema_raw=schema_raw,
    )

    with pytest.raises(subprocess.CalledProcessError):
        catalog_smoke._run_installed_catalog_verifier(
            Path(sys.executable),
            site_packages,
            wheel,
            "0.1.1",
            wheel_sha256,
            cwd=tmp_path,
            env={},
        )

    assert not marker.exists(), "candidate __init__.py ran before raw attestation"


def test_installed_catalog_verifier_runner_binds_selected_wheel_and_digest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Path, str, list[str], Path, dict[str, str]]] = []

    def capture(
        python: Path,
        module_path: Path,
        function_name: str,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        calls.append(
            (
                python,
                module_path,
                function_name,
                arguments,
                cwd,
                env,
            )
        )

    monkeypatch.setattr(catalog_smoke, "_run_isolated_function", capture)
    python = Path("/venv/bin/python")
    site_packages = Path("/venv/lib/python3.12/site-packages")
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.touch()
    digest = "a" * 64
    env = {"PATH": "/safe-bin"}

    catalog_smoke._run_installed_catalog_verifier(
        python,
        site_packages,
        wheel,
        "0.1.1",
        digest,
        cwd=tmp_path,
        env=env,
    )

    assert calls == [
        (
            python,
            Path(catalog_smoke.__file__),
            "_installed_catalog_verifier",
            [str(site_packages), str(wheel), "0.1.1", digest],
            tmp_path,
            env,
        )
    ]


def test_catalog_main_uses_wheel_metadata_and_exact_cli_groups(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-2-py3-none-manylinux_2_28_x86_64.whl"
    _write_wheel_artifacts(
        wheel,
        {relative: b"resource" for relative in catalog_smoke._REQUIRED_RESOURCE_PATHS},
    )
    env = {"PATH": "/safe-bin"}
    verifier_calls: list[tuple[Path, Path, Path, str, str, Path, dict[str, str]]] = []
    cli_calls: list[tuple[Path, Path, tuple[str, ...], Path, dict[str, str], bool]] = []

    monkeypatch.setattr(
        catalog_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_validated_uv_bin",
        lambda uv_bin: str(uv_bin),
    )

    def prepare(
        uv: str,
        selected_wheel: Path,
        selected_sha256: str,
        work_dir: Path,
    ):
        assert uv == "/tool/uv"
        assert selected_wheel == wheel.resolve()
        assert selected_sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()
        return catalog_smoke._venv_python(work_dir / "venv"), env

    def run_verifier(
        python,
        site_packages,
        selected_wheel,
        expected_version,
        selected_sha256,
        *,
        cwd,
        env,
    ):
        verifier_calls.append(
            (
                python,
                site_packages,
                selected_wheel,
                expected_version,
                selected_sha256,
                Path(cwd),
                dict(env),
            )
        )

    def run_cli(python, site_packages, arguments, *, cwd, env, capture_output=False):
        cli_calls.append(
            (
                python,
                site_packages,
                tuple(arguments),
                Path(cwd),
                dict(env),
                capture_output,
            )
        )
        return "openopps 0.1.1\n" if capture_output else None

    monkeypatch.setattr(catalog_smoke, "_prepare_locked_runtime", prepare)
    monkeypatch.setattr(catalog_smoke, "_run_installed_catalog_verifier", run_verifier)
    monkeypatch.setattr(catalog_smoke, "_run_isolated_openopps", run_cli)

    assert catalog_smoke.main() == 0
    (
        verifier_python,
        site_packages,
        selected_wheel,
        version,
        selected_sha256,
        work_dir,
        verifier_env,
    ) = verifier_calls[0]
    assert selected_wheel == wheel.resolve()
    assert version == "0.1.1"
    assert selected_sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert site_packages == catalog_smoke._venv_site_packages(work_dir / "venv")
    assert verifier_env == env
    assert cli_calls == [
        (
            verifier_python,
            site_packages,
            ("--version",),
            work_dir,
            env,
            True,
        ),
        (
            verifier_python,
            site_packages,
            ("jobs", "--help"),
            work_dir,
            env,
            False,
        ),
        (
            verifier_python,
            site_packages,
            ("providers", "--help"),
            work_dir,
            env,
            False,
        ),
    ]


def test_catalog_main_fails_for_wrong_installed_version(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel_artifacts(
        wheel,
        {relative: b"resource" for relative in catalog_smoke._REQUIRED_RESOURCE_PATHS},
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_validated_uv_bin",
        lambda uv_bin: str(uv_bin),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_prepare_locked_runtime",
        lambda uv, selected, selected_sha256, work: (
            catalog_smoke._venv_python(work / "venv"),
            {"PATH": "/safe-bin"},
        ),
    )

    def reject_version(*args, **kwargs):
        raise RuntimeError("installed distribution version does not match wheel")

    monkeypatch.setattr(
        catalog_smoke, "_run_installed_catalog_verifier", reject_version
    )

    with pytest.raises(RuntimeError, match="version"):
        catalog_smoke.main()


def test_catalog_main_fails_when_a_command_group_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    _write_wheel_artifacts(
        wheel,
        {relative: b"resource" for relative in catalog_smoke._REQUIRED_RESOURCE_PATHS},
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_parse_args",
        lambda: argparse.Namespace(
            wheel_dir=tmp_path,
            validate_requirements=None,
            uv_bin=Path("/tool/uv"),
        ),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_validated_uv_bin",
        lambda uv_bin: str(uv_bin),
    )
    monkeypatch.setattr(
        catalog_smoke,
        "_prepare_locked_runtime",
        lambda uv, selected, selected_sha256, work: (
            catalog_smoke._venv_python(work / "venv"),
            {"PATH": "/safe-bin"},
        ),
    )
    monkeypatch.setattr(
        catalog_smoke, "_run_installed_catalog_verifier", lambda *a, **k: None
    )

    def missing_group(
        python, site_packages, arguments, *, cwd, env, capture_output=False
    ):
        if tuple(arguments) == ("providers", "--help"):
            raise subprocess.CalledProcessError(2, list(arguments))
        return "openopps 0.1.1\n" if capture_output else None

    monkeypatch.setattr(catalog_smoke, "_run_isolated_openopps", missing_group)

    with pytest.raises(subprocess.CalledProcessError):
        catalog_smoke.main()


def test_installed_verifier_child_is_isolated(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def capture(command, *, cwd, env):
        calls.append((list(command), Path(cwd), dict(env)))

    monkeypatch.setattr(catalog_smoke.subprocess, "check_call", capture)
    catalog_smoke._run_isolated_function(
        Path("/venv/bin/python"),
        catalog_smoke.Path(catalog_smoke.__file__).resolve(),
        "_validate_catalog_shape",
        ["argument"],
        cwd=tmp_path,
        env={"PATH": "/safe-bin"},
    )

    command, cwd, env = calls[0]
    assert command[:5] == ["/venv/bin/python", "-I", "-S", "-B", "-c"]
    assert command[-3:] == [
        str(catalog_smoke.Path(catalog_smoke.__file__).resolve()),
        "_validate_catalog_shape",
        "argument",
    ]
    assert cwd == tmp_path
    assert env == {"PATH": "/safe-bin"}
    assert "assert " not in command[5]


def test_optimized_interpreter_still_rejects_invalid_catalog_data() -> None:
    script = catalog_smoke.Path(catalog_smoke.__file__).resolve()
    invalid = b'{"count":0,"entries":[],"fingerprint":"","version":true}'
    code = (
        "import importlib.util,sys;"
        "spec=importlib.util.spec_from_file_location('catalog_under_test',sys.argv[1]);"
        "module=importlib.util.module_from_spec(spec);"
        "sys.modules[spec.name]=module;"
        "spec.loader.exec_module(module);"
        "module._validate_catalog_shape(bytes.fromhex(sys.argv[2]))"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-O",
            "-I",
            "-S",
            "-B",
            "-c",
            code,
            str(script),
            invalid.hex(),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "version" in completed.stderr


def test_optimized_interpreter_still_enforces_full_resource_attestation(
    tmp_path: Path,
) -> None:
    script = catalog_smoke.Path(catalog_smoke.__file__).resolve()
    resources = _mutated_catalog_resources("evidence")
    paths: list[Path] = []
    for index, payload in enumerate(resources):
        path = tmp_path / f"resource-{index}.json"
        path.write_bytes(payload)
        paths.append(path)
    code = (
        "import importlib.util,pathlib,sys;"
        "spec=importlib.util.spec_from_file_location('catalog_under_test',sys.argv[1]);"
        "module=importlib.util.module_from_spec(spec);"
        "sys.modules[spec.name]=module;"
        "spec.loader.exec_module(module);"
        "raw=[pathlib.Path(value).read_bytes() for value in sys.argv[2:]];"
        "module._validate_catalog_resources(*raw)"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-O",
            "-I",
            "-S",
            "-B",
            "-c",
            code,
            str(script),
            *(str(path) for path in paths),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "source-policy evidence digest" in completed.stderr


def _promotion_artifact_bytes() -> dict[str, bytes]:
    return {
        "catalog": (
            _SOURCE_CATALOG_ROOT / "portfolio_source_catalog.json"
        ).read_bytes(),
        "decision": (
            _SOURCE_PROMOTION_ROOT / "discovery_promotion_policy_decision.json"
        ).read_bytes(),
        "envelope": (
            _SOURCE_PROMOTION_ROOT / "approved_ingestion_selector_envelope.json"
        ).read_bytes(),
        "ledger": (
            _SOURCE_PROMOTION_ROOT / "promotion_decision_ledger.jsonl"
        ).read_bytes(),
        "receipt": (
            _SOURCE_PROMOTION_ROOT / "evidence_only_decision_receipt.json"
        ).read_bytes(),
    }


def test_promotion_artifact_verifier_accepts_exact_four_event_closure() -> None:
    summary = promotion_smoke._validate_promotion_artifacts(_promotion_artifact_bytes())

    assert summary == {
        "catalogCount": 2239,
        "decisionId": "b699-identity-closure-20260906",
        "eventStates": ["reserved", "applied", "reserved", "applied"],
    }


def _mutate_promotion_artifacts(case: str) -> dict[str, bytes]:
    artifacts = _promotion_artifact_bytes()
    if case.startswith("ledger_"):
        events = [json.loads(line) for line in artifacts["ledger"].splitlines()]
        if case == "ledger_predecessor":
            events[3]["predecessorDigest"] = "0" * 64
        elif case == "ledger_event_digest":
            events[2]["eventDigest"] = "0" * 64
        else:
            events[3]["promotionIntentDigest"] = "0" * 64
        artifacts["ledger"] = b"".join(_canonical_bytes(event) for event in events)
        return artifacts

    artifact, field = {
        "receipt": ("receipt", "decisionDigest"),
        "decision": ("decision", "promotionDigest"),
        "envelope": ("envelope", "envelopeId"),
        "catalog": ("catalog", "count"),
    }[case]
    payload = json.loads(artifacts[artifact])
    payload[field] = 2238 if case == "catalog" else "0" * 64
    artifacts[artifact] = (
        json.dumps(payload, indent=2).encode() + b"\n"
        if case == "catalog"
        else _canonical_bytes(payload)
    )
    return artifacts


@pytest.mark.parametrize(
    "case",
    [
        "ledger_predecessor",
        "ledger_event_digest",
        "ledger_intent",
        "receipt",
        "decision",
        "envelope",
        "catalog",
    ],
)
def test_promotion_artifact_verifier_rejects_mutated_bindings(case: str) -> None:
    with pytest.raises(RuntimeError):
        promotion_smoke._validate_promotion_artifacts(_mutate_promotion_artifacts(case))


@pytest.mark.parametrize("mutation", ["path", "hash"])
def test_direct_url_must_bind_to_selected_wheel(tmp_path: Path, mutation: str) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    target = wheel
    archive_digest = digest
    if mutation == "path":
        target = tmp_path / "other.whl"
        target.write_bytes(b"other")
    else:
        archive_digest = "0" * 64
    payload = {
        "archive_info": {
            "hash": f"sha256={archive_digest}",
            "hashes": {"sha256": archive_digest},
        },
        "url": target.resolve().as_uri(),
    }

    if mutation in {"path", "hash"}:
        with pytest.raises(RuntimeError):
            promotion_smoke._validate_direct_url(
                _canonical_bytes(payload), wheel.resolve(), digest
            )


def test_direct_url_accepts_selected_wheel_and_matching_archive_hash(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    payload = {
        "archive_info": {
            "hash": f"sha256={digest}",
            "hashes": {"sha256": digest},
        },
        "url": wheel.resolve().as_uri(),
    }

    promotion_smoke._validate_direct_url(
        _canonical_bytes(payload), wheel.resolve(), digest
    )


def test_direct_url_accepts_matching_pep508_fragment_sha256(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    payload = {
        "archive_info": {},
        "url": f"{wheel.resolve().as_uri()}#sha256={digest}",
    }

    promotion_smoke._validate_direct_url(
        _canonical_bytes(payload),
        wheel.resolve(),
        digest,
    )


@pytest.mark.parametrize(
    "archive_info",
    [
        None,
        {},
        {
            "hash": "sha512=abc",
            "hashes": {"sha512": "abc"},
        },
    ],
    ids=["missing", "empty", "non-sha-only"],
)
def test_direct_url_requires_at_least_one_sha256_representation(
    tmp_path: Path,
    archive_info: dict[str, object] | None,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    payload: dict[str, object] = {"url": wheel.resolve().as_uri()}
    if archive_info is not None:
        payload["archive_info"] = archive_info

    with pytest.raises(RuntimeError):
        promotion_smoke._validate_direct_url(
            _canonical_bytes(payload),
            wheel.resolve(),
            digest,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("conflicting_hashes", "does not match selected wheel"),
        ("conflicting_fragment", "does not match selected wheel"),
        ("malformed_archive_info", "archive_info must be an object"),
        ("malformed_legacy_hash", "archive hash is malformed"),
        ("malformed_hashes", "archive hashes must be an object"),
        ("extra_archive_field", "archive_info fields are invalid"),
        ("non_local_url", "local file URL"),
        ("url_query", "local file URL"),
    ],
)
def test_direct_url_rejects_ambiguous_or_untrusted_provenance(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    payload: dict[str, object] = {
        "archive_info": {
            "hash": f"sha256={digest}",
            "hashes": {"sha256": digest},
        },
        "url": wheel.resolve().as_uri(),
    }
    if case == "conflicting_hashes":
        payload["archive_info"] = {
            "hash": f"sha256={digest}",
            "hashes": {"sha256": "0" * 64},
        }
    elif case == "conflicting_fragment":
        payload["url"] = f"{wheel.resolve().as_uri()}#sha256={'0' * 64}"
    elif case == "malformed_archive_info":
        payload["archive_info"] = []
    elif case == "malformed_legacy_hash":
        payload["archive_info"] = {"hash": f"sha256:{digest}"}
    elif case == "malformed_hashes":
        payload["archive_info"] = {"hashes": [digest]}
    elif case == "extra_archive_field":
        payload["archive_info"] = {
            "hashes": {"sha256": digest},
            "signature": "attacker-controlled",
        }
    elif case == "non_local_url":
        payload["url"] = "https://attacker.invalid/openopps.whl"
    else:
        payload["url"] = f"{wheel.resolve().as_uri()}?source=attacker"

    with pytest.raises(RuntimeError, match=message):
        promotion_smoke._validate_direct_url(
            _canonical_bytes(payload),
            wheel.resolve(),
            digest,
        )


def _record_bytes(root: Path) -> bytes:
    rows: list[str] = []
    for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = relative.encode()
        path.write_bytes(payload)
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        rows.append(f"{relative},sha256={digest.decode()},{len(payload)}\n")
    return "".join(rows).encode()


def test_record_requires_all_artifacts_and_validates_hashes(
    tmp_path: Path,
) -> None:
    record = _record_bytes(tmp_path)

    artifacts = promotion_smoke._read_required_record_artifacts(record, tmp_path)

    assert set(artifacts) == set(promotion_smoke._REQUIRED_ARTIFACT_PATHS)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("wrong_digest", "hash does not match"),
        ("wrong_size", "size does not match"),
        ("duplicate", "duplicated"),
        ("malformed_csv", "malformed CSV"),
        ("bom", "BOM"),
        ("nul", "NUL"),
    ],
)
def test_record_rejects_malformed_or_mismatched_required_entries(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    record = _record_bytes(tmp_path)
    target = promotion_smoke._REQUIRED_ARTIFACT_PATHS[0]
    target_line = next(
        line
        for line in record.splitlines(keepends=True)
        if line.startswith(target.encode() + b",")
    )
    if case == "wrong_digest":
        fields = target_line.decode().rstrip("\n").split(",")
        fields[1] = f"sha256={'A' * 43}"
        record = record.replace(target_line, (",".join(fields) + "\n").encode())
    elif case == "wrong_size":
        fields = target_line.decode().rstrip("\n").split(",")
        fields[2] = str(int(fields[2]) + 1)
        record = record.replace(target_line, (",".join(fields) + "\n").encode())
    elif case == "duplicate":
        record += target_line
    elif case == "malformed_csv":
        record = b'"unterminated,' + record
    elif case == "bom":
        record = b"\xef\xbb\xbf" + record
    else:
        record = record.replace(target.encode(), target.encode() + b"\x00", 1)

    with pytest.raises(RuntimeError, match=message):
        promotion_smoke._read_required_record_artifacts(record, tmp_path)


@pytest.mark.parametrize(
    "value",
    [
        "/absolute/artifact.json",
        "openopps/../artifact.json",
        "openopps/./artifact.json",
        "openopps//artifact.json",
        "openopps\\artifact.json",
        "openopps/artifact.json\x00",
    ],
)
def test_record_path_rejects_unsafe_or_non_normalized_values(value: str) -> None:
    with pytest.raises(RuntimeError, match="RECORD path"):
        promotion_smoke._record_path(value)


def _write_wheel_artifacts(wheel: Path, artifacts: dict[str, bytes]) -> None:
    _write_release_wheel(wheel, extra_members=artifacts)


def test_required_wheel_artifacts_are_read_exactly(tmp_path: Path) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    expected = {
        relative: f"wheel:{relative}".encode()
        for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS
    }
    _write_wheel_artifacts(wheel, expected)

    archived = promotion_smoke._read_required_wheel_artifacts(wheel)

    assert archived == expected
    promotion_smoke._require_installed_artifacts_match_wheel(wheel, expected)


def test_installed_artifact_bytes_must_match_selected_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    archived = {
        relative: f"wheel:{relative}".encode()
        for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS
    }
    _write_wheel_artifacts(wheel, archived)
    installed = dict(archived)
    installed[promotion_smoke._REQUIRED_ARTIFACT_PATHS[0]] = b"tampered"

    with pytest.raises(RuntimeError, match="selected wheel"):
        promotion_smoke._require_installed_artifacts_match_wheel(wheel, installed)


def test_installed_artifact_set_rejects_extra_member(tmp_path: Path) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    installed = {
        relative: f"wheel:{relative}".encode()
        for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS
    }
    _write_wheel_artifacts(wheel, installed)
    installed["openopps/discovery/data/unexpected.json"] = b"unexpected"

    with pytest.raises(RuntimeError, match="artifact set"):
        promotion_smoke._require_installed_artifacts_match_wheel(wheel, installed)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "exactly one"),
        ("duplicate", "duplicate member path"),
        ("symlink", "symlink"),
    ],
)
def test_required_wheel_artifacts_reject_unsafe_archive_members(
    tmp_path: Path, mutation: str, message: str
) -> None:
    wheel = tmp_path / "openopps-0.1.1-py3-none-any.whl"
    artifacts = {
        relative: relative.encode()
        for relative in promotion_smoke._REQUIRED_ARTIFACT_PATHS
    }
    target = promotion_smoke._REQUIRED_ARTIFACT_PATHS[0]
    if mutation in {"missing", "symlink"}:
        artifacts.pop(target)
    _write_wheel_artifacts(wheel, artifacts)
    if mutation == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr(target, b"duplicate")
    elif mutation == "symlink":
        link = zipfile.ZipInfo(target)
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(link, b"../../outside")

    with pytest.raises(RuntimeError, match=message):
        promotion_smoke._read_required_wheel_artifacts(wheel)


def test_record_parser_requires_an_explicit_console_script_allowlist() -> None:
    console_relative = "../../../bin/openopps"
    record = _record_row(console_relative, b"script").encode()

    with pytest.raises(RuntimeError, match="RECORD path"):
        catalog_smoke._parse_record(record)

    parsed = catalog_smoke._parse_record(
        record,
        allowed_external_paths=frozenset({console_relative}),
    )

    assert parsed == {
        console_relative: (
            _record_row(console_relative, b"script").split(",", maxsplit=2)[1],
            "6",
        )
    }


@pytest.mark.parametrize(
    "relative",
    [
        "../../../bin/not-openopps",
        "../../../outside/openopps",
        "../../../../bin/openopps",
    ],
)
def test_record_parser_rejects_other_external_paths(relative: str) -> None:
    console_relative = "../../../bin/openopps"
    record = _record_row(relative, b"script").encode()

    with pytest.raises(RuntimeError, match="RECORD path"):
        catalog_smoke._parse_record(
            record,
            allowed_external_paths=frozenset({console_relative}),
        )


def test_record_rejects_missing_or_escaping_required_artifact(
    tmp_path: Path,
) -> None:
    record = _record_bytes(tmp_path)
    missing = promotion_smoke._REQUIRED_ARTIFACT_PATHS[-1]
    without_last = b"".join(
        line
        for line in record.splitlines(keepends=True)
        if not line.startswith(missing.encode() + b",")
    )
    with pytest.raises(RuntimeError, match="RECORD"):
        promotion_smoke._read_required_record_artifacts(without_last, tmp_path)

    outside = tmp_path.parent / "outside-artifact.json"
    outside.write_bytes(b"outside")
    victim = tmp_path / promotion_smoke._REQUIRED_ARTIFACT_PATHS[0]
    victim.unlink()
    victim.symlink_to(outside)
    with pytest.raises(RuntimeError, match="beneath|symlink"):
        promotion_smoke._read_required_record_artifacts(record, tmp_path)


def _just_output(*args: str) -> str:
    return subprocess.check_output(
        [
            "just",
            "--justfile",
            str(catalog_smoke._REPO_ROOT / "Justfile"),
            "--working-directory",
            str(catalog_smoke._REPO_ROOT),
            "--color",
            "never",
            *args,
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )


@pytest.mark.parametrize(
    ("recipe", "driver_names"),
    [
        ("wheel-catalog-smoke", ["smoke_wheel_catalog.py"]),
        (
            "promotion-wheel-readback",
            ["smoke_wheel_catalog.py", "smoke_promotion_wheel.py"],
        ),
    ],
)
def test_just_smoke_launchers_are_scoped_and_environment_isolated(
    recipe: str, driver_names: list[str]
) -> None:
    shown = _just_output("--show", recipe)
    lines = [line.strip() for line in shown.splitlines() if line.strip()]

    assert f"{recipe}: lock-check" in lines
    assert sum("mktemp -d" in line for line in lines) == 1
    work_index = next(index for index, line in enumerate(lines) if "mktemp -d" in line)
    assert lines[work_index + 1] == "trap 'rm -rf -- \"$work\"' EXIT"
    assert "/usr/bin/env -i" in shown
    assert "UV_NATIVE_TLS" not in shown
    assert "UV_SYSTEM_CERTS" not in shown
    assert "PIP_" not in shown
    assert "PYTHONPATH" not in shown
    assert "_PROXY" not in shown.upper()
    assert "CERT" not in shown.upper()

    python_find = (
        'python_bin="$("${clean_env[@]}" "$uv_bin" --no-config '
        '--no-python-downloads python find 3.12 --system)"'
    )
    assert python_find in lines
    assert '[[ "$python_bin" == /* && -f "$python_bin" && -x "$python_bin" ]]' in shown
    assert 'python_version="$("${clean_env[@]}" "$python_bin" -I -S -B -c ' in shown
    assert '[[ "$python_version" == "3.12" ]]' in shown

    for driver_name in driver_names:
        expected = (
            f'"${{clean_env[@]}}" "$python_bin" -I -S -B '
            f'scripts/{driver_name} --wheel-dir "$artifact_dir" '
            '--uv-bin "$uv_bin"'
        )
        assert expected in lines
        matching_lines = [
            line
            for line in lines
            if f"scripts/{driver_name}" in line and "--wheel-dir" in line
        ]
        assert matching_lines == [expected]


@pytest.mark.parametrize(
    ("recipe", "lock_name", "consumer_fragment"),
    [
        (
            "wheel-catalog-smoke",
            "build_constraints",
            '--build-constraints "$build_constraints"',
        ),
        (
            "promotion-wheel-readback",
            "test_requirements",
            '--requirements "$test_requirements"',
        ),
        (
            "promotion-wheel-readback",
            "build_constraints",
            '--build-constraints "$build_constraints"',
        ),
    ],
)
def test_just_validates_each_export_before_its_first_consumer(
    recipe: str,
    lock_name: str,
    consumer_fragment: str,
) -> None:
    lines = [
        line.strip()
        for line in _just_output("--show", recipe).splitlines()
        if line.strip()
    ]
    export_fragment = f'--output-file "${lock_name}"'
    validation = (
        '"${clean_env[@]}" "$python_bin" -I -S -B '
        "scripts/smoke_wheel_catalog.py --validate-requirements "
        f'"${lock_name}"'
    )
    export_indexes = [
        index for index, line in enumerate(lines) if export_fragment in line
    ]
    validation_indexes = [
        index for index, line in enumerate(lines) if line == validation
    ]
    consumer_indexes = [
        index for index, line in enumerate(lines) if consumer_fragment in line
    ]

    assert len(export_indexes) == 1
    assert len(validation_indexes) == 1
    assert len(consumer_indexes) == 1
    assert export_indexes[0] < validation_indexes[0] < consumer_indexes[0]


def test_just_smoke_dry_run_expands_lock_check_before_recipe() -> None:
    for recipe in ("wheel-catalog-smoke", "promotion-wheel-readback"):
        dry_run = _just_output("--dry-run", recipe)
        assert dry_run.index("uv lock --check") < dry_run.index("mktemp -d")
