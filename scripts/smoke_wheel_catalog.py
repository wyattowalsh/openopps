#!/usr/bin/env python3
"""Install one scoped wheel over locked dependencies and smoke its catalog/CLI."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast
from urllib.parse import unquote, urlsplit


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRUSTED_DEFAULT_INDEX = "https://pypi.org/simple"
_SAFE_ENV_KEYS = frozenset(
    {
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
)
_SAFE_UV_ENV_KEYS = frozenset({"UV_CACHE_DIR", "UV_NO_PROGRESS", "UV_OFFLINE"})
_CANONICAL_OPENOPPS_NAME = "openopps"
_EXPECTED_OPENOPPS_VERSION = "0.1.1"
_EXPECTED_DIST_INFO_ROOT = "openopps-0.1.1.dist-info"
_EXPECTED_ENTRY_POINTS = b"[console_scripts]\nopenopps = openopps.cli:app\n"
_EXPECTED_DIST_INFO_PATHS = frozenset(
    {
        f"{_EXPECTED_DIST_INFO_ROOT}/METADATA",
        f"{_EXPECTED_DIST_INFO_ROOT}/RECORD",
        f"{_EXPECTED_DIST_INFO_ROOT}/WHEEL",
        f"{_EXPECTED_DIST_INFO_ROOT}/entry_points.txt",
        f"{_EXPECTED_DIST_INFO_ROOT}/licenses/LICENSE",
    }
)
_EXPECTED_NON_PACKAGE_PATHS = frozenset({"examples/examples.py"})
_INSTALLER_GENERATED_DIST_INFO_PATHS = frozenset(
    {
        f"{_EXPECTED_DIST_INFO_ROOT}/INSTALLER",
        f"{_EXPECTED_DIST_INFO_ROOT}/REQUESTED",
        f"{_EXPECTED_DIST_INFO_ROOT}/direct_url.json",
        f"{_EXPECTED_DIST_INFO_ROOT}/uv_cache.json",
    }
)
_EXPECTED_CATALOG_VERSION = 2
_EXPECTED_CATALOG_COUNT = 2239
_EXPECTED_CATALOG_FINGERPRINT = (
    "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
)
_EXPECTED_CATALOG_SHA256 = (
    "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
)
_EXPECTED_EVIDENCE_SHA256 = (
    "c75401ab710caee87b55682038bcda0206df270d71e3e26e6d5f5642f734f0ec"
)
_EXPECTED_SCHEMA_SHA256 = (
    "14b4c2a6ec4b1ade2d0a5860acd24180f6e23b8ee088bff6eeecf17e5a3a0089"
)
_EXPECTED_EVIDENCE_DECISIONS = 10
_MAX_JSON_DEPTH = 128
_MAX_JSON_NODES = 100_000
_MAX_RESOURCE_BYTES = 16 * 1024 * 1024
_MAX_DIRECT_URL_BYTES = 64 * 1024
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_MAX_WHEEL_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_WHEEL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_WHEEL_MEMBERS = 10_000
_MAX_COMPRESSION_RATIO = 1_000
_CATALOG_RELATIVE_PATH = Path(
    "openopps/providers/sources/data/portfolio_source_catalog.json"
)
_EVIDENCE_RELATIVE_PATH = Path(
    "openopps/providers/sources/data/source_policy_evidence.json"
)
_SCHEMA_RELATIVE_PATH = Path(
    "openopps/providers/sources/data/source_policy_evidence.schema.json"
)
_REQUIRED_RESOURCE_PATHS = (
    _CATALOG_RELATIVE_PATH.as_posix(),
    _EVIDENCE_RELATIVE_PATH.as_posix(),
    _SCHEMA_RELATIVE_PATH.as_posix(),
)
_ISOLATED_FUNCTION_BOOTSTRAP = (
    "import importlib.util,sys;"
    "path=sys.argv[1];"
    "name='_openopps_wheel_smoke_child';"
    "spec=importlib.util.spec_from_file_location(name,path);"
    "module=importlib.util.module_from_spec(spec);"
    "sys.modules[name]=module;"
    "spec.loader.exec_module(module);"
    "getattr(module,sys.argv[2])(*sys.argv[3:])"
)
_ISOLATED_CLI_BOOTSTRAP = (
    "import runpy,sys;"
    "sys.path.insert(0,sys.argv[1]);"
    "sys.argv=['openopps',*sys.argv[2:]];"
    "runpy.run_module('openopps',run_name='__main__')"
)


class SmokeValidationError(RuntimeError):
    """Release smoke input or installed artifact failed validation."""


@dataclass(frozen=True, slots=True)
class WheelArtifact:
    path: Path
    name: str
    version: str
    sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeValidationError(message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--wheel-dir", type=Path)
    mode.add_argument("--validate-requirements", type=Path)
    parser.add_argument("--uv-bin", type=Path)
    args = parser.parse_args()
    if args.wheel_dir is not None and args.uv_bin is None:
        parser.error("--uv-bin is required with --wheel-dir")
    if args.validate_requirements is not None and args.uv_bin is not None:
        parser.error("--uv-bin is not accepted with --validate-requirements")
    return args


def _sanitized_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Retain only process basics and source-neutral uv controls."""

    current = os.environ if source is None else source
    allowed = _SAFE_ENV_KEYS | _SAFE_UV_ENV_KEYS
    return {
        key: value
        for key, value in current.items()
        if key.upper() in allowed
        and (not key.upper().startswith("UV_") or key.upper() in _SAFE_UV_ENV_KEYS)
    }


def _canonical_project_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _is_openopps_wheel_name(path: Path) -> bool:
    if path.suffix.lower() != ".whl":
        return False
    distribution, separator, _remainder = path.name[:-4].partition("-")
    return bool(separator) and _canonical_project_name(distribution) == (
        _CANONICAL_OPENOPPS_NAME
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bounded_file(path: Path, *, limit: int, label: str) -> bytes:
    _require(limit > 0, f"{label} byte limit must be positive")
    _require(not path.is_symlink(), f"{label} must not be a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
        _require(stat.S_ISREG(mode), f"{label} must be a regular file")
        _require(
            path.stat(follow_symlinks=False).st_size <= limit,
            f"{label} exceeds its byte limit",
        )
        with path.open("rb") as stream:
            payload = stream.read(limit + 1)
    except OSError as exc:
        raise SmokeValidationError(f"cannot read {label}") from exc
    _require(len(payload) <= limit, f"{label} exceeds its byte limit")
    return payload


def _wheel_member_path(value: str, *, is_dir: bool) -> PurePosixPath:
    _require(value != "", "wheel contains an empty member path")
    _require("\\" not in value and "\x00" not in value, "wheel member path is invalid")
    expected = value[:-1] if is_dir and value.endswith("/") else value
    path = PurePosixPath(expected)
    _require(
        not path.is_absolute()
        and expected == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"wheel member path is not normalized: {value}",
    )
    _require(
        value == path.as_posix() + ("/" if is_dir else ""),
        f"wheel member path is not normalized: {value}",
    )
    return path


def _validated_wheel_members(path: Path) -> dict[str, zipfile.ZipInfo]:
    _require(not path.is_symlink(), "selected wheel must not be a symlink")
    try:
        wheel = path.resolve(strict=True)
        mode = wheel.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise SmokeValidationError("selected wheel is unavailable") from exc
    _require(stat.S_ISREG(mode), "selected wheel must be a regular file")

    try:
        with zipfile.ZipFile(wheel, "r") as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SmokeValidationError("selected wheel is not a readable archive") from exc

    _require(
        0 < len(infos) <= _MAX_WHEEL_MEMBERS,
        "selected wheel has an invalid member count",
    )
    members: dict[str, zipfile.ZipInfo] = {}
    normalized_paths: set[PurePosixPath] = set()
    total_size = 0
    for info in infos:
        member_path = _wheel_member_path(info.filename, is_dir=info.is_dir())
        _require(
            member_path not in normalized_paths,
            f"selected wheel contains a duplicate member path: {info.filename}",
        )
        normalized_paths.add(member_path)
        _require(
            info.flag_bits & 0x1 == 0,
            f"selected wheel member must not be encrypted: {info.filename}",
        )
        _require(
            not stat.S_ISLNK(info.external_attr >> 16),
            f"selected wheel member must not be a symlink: {info.filename}",
        )
        if info.is_dir():
            _require(
                info.file_size == 0,
                f"selected wheel directory has content: {info.filename}",
            )
            continue
        _require(
            0 <= info.file_size <= _MAX_WHEEL_MEMBER_BYTES,
            f"selected wheel member exceeds its byte limit: {info.filename}",
        )
        total_size += info.file_size
        _require(
            total_size <= _MAX_WHEEL_UNCOMPRESSED_BYTES,
            "selected wheel exceeds its aggregate uncompressed byte limit",
        )
        if info.file_size > _MAX_METADATA_BYTES:
            _require(
                info.compress_size > 0
                and info.file_size <= info.compress_size * _MAX_COMPRESSION_RATIO,
                f"selected wheel member has an unsafe compression ratio: {info.filename}",
            )
        members[info.filename] = info
    return members


def _read_wheel_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    limit: int,
    label: str,
) -> bytes:
    _require(not member.is_dir(), f"{label} must be a file")
    _require(0 <= member.file_size <= limit, f"{label} exceeds its byte limit")
    try:
        with archive.open(member, "r") as source:
            payload = source.read(limit + 1)
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise SmokeValidationError(f"cannot read {label}") from exc
    _require(len(payload) <= limit, f"{label} exceeds its byte limit")
    _require(len(payload) == member.file_size, f"{label} size is inconsistent")
    return payload


def _preflight_wheel_archive(
    path: Path, *, required_paths: tuple[str, ...] = ()
) -> None:
    members = _validated_wheel_members(path)
    for relative in required_paths:
        member = members.get(relative)
        if member is None:
            raise SmokeValidationError(
                f"selected wheel must contain exactly one required member: {relative}"
            )
        _require(
            0 < member.file_size <= _MAX_RESOURCE_BYTES,
            f"selected wheel required member has an invalid size: {relative}",
        )


def _read_wheel_metadata(path: Path) -> tuple[str, str]:
    members = _validated_wheel_members(path)
    metadata_members = [
        info
        for info in members.values()
        if len(PurePosixPath(info.filename).parts) == 2
        and PurePosixPath(info.filename).name == "METADATA"
        and PurePosixPath(info.filename).parent.name.endswith(".dist-info")
    ]
    _require(
        len(metadata_members) == 1,
        f"wheel must contain exactly one .dist-info/METADATA: {path}",
    )
    try:
        with zipfile.ZipFile(path, "r") as archive:
            metadata_bytes = _read_wheel_member(
                archive,
                metadata_members[0],
                limit=_MAX_METADATA_BYTES,
                label="wheel METADATA",
            )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SmokeValidationError(
            f"cannot read wheel metadata from {path}: {exc}"
        ) from exc

    message = BytesParser(policy=policy.default).parsebytes(metadata_bytes)
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    _require(
        len(names) == 1 and bool(names[0].strip()),
        "wheel METADATA Name is missing or ambiguous",
    )
    _require(
        len(versions) == 1 and bool(versions[0].strip()),
        "wheel METADATA Version is missing or ambiguous",
    )
    return names[0].strip(), versions[0].strip()


def _select_openopps_wheel(wheel_dir: Path) -> WheelArtifact:
    try:
        root = wheel_dir.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            f"wheel directory is unavailable: {wheel_dir}"
        ) from exc
    _require(root.is_dir(), f"wheel directory is not a directory: {wheel_dir}")

    matches: list[WheelArtifact] = []
    for candidate in sorted(root.iterdir()):
        if not _is_openopps_wheel_name(candidate):
            continue
        _require(
            not candidate.is_symlink(),
            f"matching wheel must not be a symlink: {candidate}",
        )
        try:
            mode = candidate.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise SmokeValidationError(
                f"cannot inspect matching wheel: {candidate}"
            ) from exc
        _require(
            stat.S_ISREG(mode),
            f"matching wheel must be a regular file: {candidate}",
        )
        name, version = _read_wheel_metadata(candidate)
        _require(
            _canonical_project_name(name) == _CANONICAL_OPENOPPS_NAME,
            f"matching wheel METADATA Name is not OpenOpps: {name!r}",
        )
        resolved = candidate.resolve(strict=True)
        matches.append(
            WheelArtifact(
                path=resolved,
                name=name,
                version=version,
                sha256=_sha256_file(resolved),
            )
        )

    _require(
        len(matches) == 1,
        f"expected exactly one OpenOpps wheel in {root}, found {len(matches)}",
    )
    return matches[0]


def _logical_requirements(contents: str) -> list[str]:
    logical: list[str] = []
    parts: list[str] = []
    for raw_line in contents.splitlines():
        stripped = raw_line.strip()
        if not stripped or (not parts and stripped.startswith("#")):
            continue
        continued = stripped.endswith("\\")
        if continued:
            stripped = stripped[:-1].rstrip()
        if stripped:
            parts.append(stripped)
        if not continued and parts:
            logical.append(" ".join(parts))
            parts.clear()
    _require(not parts, "exported requirements contain an unterminated continuation")
    return logical


def _validate_exported_requirements(path: Path) -> None:
    try:
        requirements = _logical_requirements(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SmokeValidationError(
            f"cannot read exported requirements: {path}"
        ) from exc
    _require(bool(requirements), "exported requirements are empty")

    hash_pattern = re.compile(r"(?:^|\s)--hash=sha256:([0-9a-fA-F]{64})(?=\s|$)")
    requirement_pattern = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]*"
        r"(?:\[[A-Za-z0-9._,-]+\])?"
        r"==[^\s;=]+(?:\s*;\s*.+)?$"
    )
    for logical in requirements:
        _require(
            not logical.startswith("-"),
            f"exported requirements contain a package-source directive: {logical}",
        )
        requirement = logical.split(" --hash=", maxsplit=1)[0].strip()
        lowered = requirement.lower()
        _require(
            re.search(r"\s*@\s*", requirement) is None
            and "://" not in requirement
            and not lowered.startswith(("file:", "git+", "hg+", "svn+", "bzr+"))
            and not requirement.startswith(("/", "./", "../", "~")),
            f"exported requirements contain a direct reference: {logical}",
        )
        _require(
            requirement_pattern.fullmatch(requirement) is not None,
            f"exported requirement is not exactly pinned: {logical}",
        )
        hashes = hash_pattern.findall(logical)
        _require(
            bool(hashes),
            f"exported requirement is missing a SHA-256 hash: {logical}",
        )
        residual = hash_pattern.sub("", logical)
        _require(
            "--hash=" not in residual,
            f"exported requirement contains an invalid hash: {logical}",
        )
        _require(
            residual.strip() == requirement,
            f"exported requirement contains unexpected post-hash content: {logical}",
        )


def _validated_uv_bin(value: Path) -> str:
    _require(value.is_absolute(), "--uv-bin must be an absolute path")
    try:
        resolved = value.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise SmokeValidationError("--uv-bin must name a regular executable") from exc
    _require(
        stat.S_ISREG(mode) and os.access(resolved, os.X_OK),
        "--uv-bin must name a regular executable",
    )
    return str(resolved)


def _uv_command(uv: str, *args: str) -> list[str]:
    return [uv, "--no-config", "--no-python-downloads", *args]


def _venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _venv_site_packages(env_dir: Path) -> Path:
    if sys.platform == "win32":
        return env_dir / "Lib/site-packages"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return env_dir / "lib" / version / "site-packages"


def _create_uv_venv(
    uv: str, env_dir: Path, *, cwd: Path, env: Mapping[str, str]
) -> Path:
    subprocess.check_call(
        _uv_command(
            uv,
            "venv",
            "--no-project",
            "--python",
            sys.executable,
            str(env_dir),
        ),
        cwd=cwd,
        env=env,
    )
    return _venv_python(env_dir)


def _install_local_wheel(
    uv: str,
    python: Path,
    wheel: Path,
    wheel_sha256: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    strict: bool = True,
) -> None:
    """Install only the supplied wheel, with dependency and build paths disabled."""

    _require(
        re.fullmatch(r"[0-9a-f]{64}", wheel_sha256) is not None,
        "selected wheel digest must be a lowercase SHA-256",
    )
    try:
        wheel_uri = wheel.resolve(strict=True).as_uri()
    except (OSError, ValueError) as exc:
        raise SmokeValidationError("selected wheel is unavailable") from exc
    direct_reference = f"{_CANONICAL_OPENOPPS_NAME} @ {wheel_uri}#sha256={wheel_sha256}"
    command = _uv_command(
        uv,
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
    )
    if strict:
        command.append("--strict")
    command.append(direct_reference)
    subprocess.check_call(command, cwd=cwd, env=env)


def _prepare_locked_runtime(
    uv: str,
    wheel: Path,
    wheel_sha256: str,
    work_dir: Path,
) -> tuple[Path, dict[str, str]]:
    """Sync hash-checked runtime dependencies from uv.lock, then add the wheel."""

    env = _sanitized_environment()
    requirements = work_dir / "runtime-requirements.txt"
    env_dir = work_dir / "venv"

    subprocess.check_call(
        _uv_command(
            uv,
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
            str(requirements),
        ),
        cwd=_REPO_ROOT,
        env=env,
    )
    _validate_exported_requirements(requirements)
    python = _create_uv_venv(uv, env_dir, cwd=work_dir, env=env)
    subprocess.check_call(
        _uv_command(
            uv,
            "pip",
            "sync",
            "--python",
            str(python),
            "--require-hashes",
            "--strict",
            "--no-build",
            "--no-sources",
            "--default-index",
            _TRUSTED_DEFAULT_INDEX,
            "--index-strategy",
            "first-index",
            "--keyring-provider",
            "disabled",
            str(requirements),
        ),
        cwd=work_dir,
        env=env,
    )
    _install_local_wheel(
        uv,
        python,
        wheel,
        wheel_sha256,
        cwd=work_dir,
        env=env,
    )
    subprocess.check_call(
        _uv_command(uv, "pip", "check", "--python", str(python)),
        cwd=work_dir,
        env=env,
    )
    return python, env


def _reject_json_float(value: str) -> NoReturn:
    raise SmokeValidationError(f"floating-point JSON number is forbidden: {value}")


def _reject_json_constant(value: str) -> NoReturn:
    raise SmokeValidationError(f"non-finite JSON number is forbidden: {value}")


def _parse_json_int(value: str) -> int:
    _require(value != "-0", "negative-zero JSON integer is forbidden")
    return int(value)


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON object key is forbidden: {key!r}")
        result[key] = value
    return result


def _validate_json_limits(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        _require(nodes <= _MAX_JSON_NODES, "JSON node limit exceeded")
        _require(depth <= _MAX_JSON_DEPTH, "JSON nesting depth limit exceeded")
        if isinstance(current, dict):
            _require(
                all(type(key) is str for key in current),
                "JSON object keys must be strings",
            )
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        else:
            _require(
                current is None or type(current) in {bool, int, str},
                f"unsupported JSON value type: {type(current).__name__}",
            )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _decode_json_bytes(
    raw: bytes, *, label: str, require_canonical: bool = False
) -> object:
    _require(type(raw) is bytes, f"{label} input must be bytes")
    _require(len(raw) <= _MAX_RESOURCE_BYTES, f"{label} exceeds its byte limit")
    _require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} contains a UTF-8 BOM")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except SmokeValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SmokeValidationError(f"{label} is not strict UTF-8 JSON") from exc
    _validate_json_limits(payload)
    if require_canonical:
        _require(
            raw == _canonical_json_bytes(payload),
            f"{label} does not use canonical JSON bytes",
        )
    return payload


def _validate_catalog_shape(raw: bytes) -> dict[str, Any]:
    payload_value = _decode_json_bytes(raw, label="catalog")
    _require(type(payload_value) is dict, "catalog root must be an object")
    payload = cast(dict[str, Any], payload_value)
    _require(
        set(payload) == {"count", "entries", "fingerprint", "version"},
        "catalog root fields do not match the approved format",
    )
    _require(type(payload["version"]) is int, "catalog version must be an exact int")
    _require(type(payload["count"]) is int, "catalog count must be an exact int")
    _require(type(payload["entries"]) is list, "catalog entries must be a list")
    _require(
        type(payload["fingerprint"]) is str, "catalog fingerprint must be a string"
    )
    _require(
        payload["count"] == len(payload["entries"]),
        "catalog count does not match entries",
    )
    keys: list[str] = []
    for entry in payload["entries"]:
        _require(type(entry) is dict, "catalog entry must be an object")
        _require(
            set(entry) == {"key", "provider_id", "raw_metadata", "url", "version"},
            "catalog entry fields do not match the approved format",
        )
        for field in ("key", "provider_id", "url"):
            _require(
                type(entry[field]) is str and bool(entry[field].strip()),
                f"catalog entry {field} must be a non-empty string",
            )
        _require(
            type(entry["version"]) is dict, "catalog entry version must be an object"
        )
        _require(
            type(entry["raw_metadata"]) is dict,
            "catalog entry raw_metadata must be an object",
        )
        keys.append(entry["key"])
    _require(len(set(keys)) == len(keys), "catalog entry keys must be unique")
    _require(keys == sorted(keys), "catalog entry keys must be sorted")
    return payload


def _catalog_semantic_fingerprint(entries: list[object]) -> str:
    normalized: list[dict[str, object]] = []
    for value in entries:
        _require(type(value) is dict, "catalog entry must be an object")
        entry = cast(dict[str, Any], value)
        key = entry.get("key")
        url = entry.get("url")
        provider_id = entry.get("provider_id")
        if not key or not url or not provider_id:
            continue
        normalized.append(
            {
                "key": str(key),
                "url": str(url),
                "provider_id": str(provider_id),
                "version": dict(entry.get("version") or {}),
                "raw_metadata": dict(entry.get("raw_metadata") or {}),
            }
        )
    normalized.sort(key=lambda entry: cast(str, entry["key"]))
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_catalog_resources(
    catalog_raw: bytes, evidence_raw: bytes, schema_raw: bytes
) -> Any:
    """Attest raw resources before running candidate-package parity checks."""

    _require(
        hashlib.sha256(evidence_raw).hexdigest() == _EXPECTED_EVIDENCE_SHA256,
        "source-policy evidence digest does not match the release identity",
    )
    _require(
        hashlib.sha256(schema_raw).hexdigest() == _EXPECTED_SCHEMA_SHA256,
        "source-policy schema digest does not match the release identity",
    )

    catalog_payload = _validate_catalog_shape(catalog_raw)
    _require(
        hashlib.sha256(catalog_raw).hexdigest() == _EXPECTED_CATALOG_SHA256,
        "catalog file digest does not match the release identity",
    )
    _require(
        catalog_payload["version"] == _EXPECTED_CATALOG_VERSION,
        "catalog version does not match the release identity",
    )
    _require(
        catalog_payload["count"] == _EXPECTED_CATALOG_COUNT,
        "catalog count does not match the release identity",
    )
    _require(
        catalog_payload["fingerprint"] == _EXPECTED_CATALOG_FINGERPRINT,
        "catalog fingerprint does not match the release identity",
    )
    _require(
        _catalog_semantic_fingerprint(catalog_payload["entries"])
        == _EXPECTED_CATALOG_FINGERPRINT,
        "catalog semantic fingerprint does not match the release identity",
    )
    evidence_payload = _decode_json_bytes(
        evidence_raw, label="source-policy evidence", require_canonical=True
    )
    schema_payload = _decode_json_bytes(
        schema_raw, label="source-policy schema", require_canonical=True
    )

    _require(
        type(evidence_payload) is dict, "source-policy evidence root must be an object"
    )
    evidence = cast(dict[str, Any], evidence_payload)
    _require(
        type(evidence.get("schemaVersion")) is int and evidence["schemaVersion"] == 1,
        "source-policy evidence schemaVersion must be exact integer 1",
    )
    _require(
        type(evidence.get("decisions")) is list
        and len(evidence["decisions"]) == _EXPECTED_EVIDENCE_DECISIONS,
        "source-policy evidence decisions do not match the release identity",
    )
    _require(
        type(schema_payload) is dict, "source-policy schema root must be an object"
    )
    schema = cast(dict[str, Any], schema_payload)
    _require(
        schema.get("title") == "SourcePolicyEvidence",
        "source-policy schema title is invalid",
    )
    _require(
        schema.get("type") == "object" and schema.get("additionalProperties") is False,
        "source-policy schema root contract is invalid",
    )
    properties_value = schema.get("properties")
    _require(
        type(properties_value) is dict,
        "source-policy schema properties are invalid",
    )
    properties = cast(dict[str, Any], properties_value)
    schema_version = properties.get("schemaVersion")
    _require(
        type(schema_version) is dict
        and type(schema_version.get("const")) is int
        and schema_version["const"] == 1,
        "source-policy schema schemaVersion constant is invalid",
    )

    from openopps.discovery.inventory import read_packaged_catalog_bytes
    from openopps.source_policy import (
        parse_source_policy_evidence,
        validate_source_policy_schema_bytes,
    )

    readback = read_packaged_catalog_bytes(catalog_raw)
    _require(
        readback.version == catalog_payload["version"],
        "candidate catalog version readback does not match attested bytes",
    )
    _require(
        readback.count == catalog_payload["count"],
        "candidate catalog count readback does not match attested bytes",
    )
    _require(
        readback.fingerprint == catalog_payload["fingerprint"],
        "candidate catalog fingerprint readback does not match attested bytes",
    )
    _require(
        readback.file_sha256 == _EXPECTED_CATALOG_SHA256,
        "candidate catalog digest readback does not match attested bytes",
    )
    parse_source_policy_evidence(evidence_raw)
    validate_source_policy_schema_bytes(schema_raw)
    return readback


def _require_sha256(value: str, *, label: str) -> None:
    _require(
        re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"{label} must be a lowercase SHA-256",
    )


def _validate_direct_url(
    raw: bytes, selected_wheel: Path, selected_sha256: str
) -> None:
    payload = _decode_json_bytes(raw, label="direct_url.json")
    _require(type(payload) is dict, "direct_url.json root must be an object")
    direct_url = cast(dict[str, Any], payload)
    _require(
        set(direct_url) == {"archive_info", "url"},
        "direct_url.json fields are invalid",
    )
    _require(type(direct_url["url"]) is str, "direct_url.json URL must be a string")
    parsed = urlsplit(direct_url["url"])
    _require(
        parsed.scheme == "file"
        and parsed.netloc in {"", "localhost"}
        and not parsed.query,
        "direct_url.json must contain a local file URL",
    )
    observed_sha256: list[str] = []
    if parsed.fragment:
        algorithm, separator, digest = parsed.fragment.partition("=")
        _require(
            separator == "=" and algorithm == "sha256",
            "direct_url URL fragment must be a single SHA-256",
        )
        observed_sha256.append(digest)
    _require("%00" not in parsed.path.lower(), "direct_url.json URL contains NUL")
    try:
        installed_from = Path(unquote(parsed.path)).resolve(strict=True)
        selected = selected_wheel.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError("direct_url.json wheel path is unavailable") from exc
    _require(
        installed_from == selected,
        "direct_url.json does not resolve to the selected wheel",
    )
    _require_sha256(selected_sha256, label="selected wheel digest")

    archive_info = direct_url["archive_info"]
    _require(type(archive_info) is dict, "direct_url archive_info must be an object")
    archive = cast(dict[str, Any], archive_info)
    _require(
        set(archive).issubset({"hash", "hashes"}),
        "direct_url archive_info fields are invalid",
    )
    legacy_hash = archive.get("hash")
    if legacy_hash is not None:
        _require(type(legacy_hash) is str, "direct_url archive hash must be a string")
        algorithm, separator, digest = legacy_hash.partition("=")
        _require(separator == "=", "direct_url archive hash is malformed")
        if algorithm == "sha256":
            observed_sha256.append(digest)
    hashes = archive.get("hashes")
    if hashes is not None:
        _require(type(hashes) is dict, "direct_url archive hashes must be an object")
        _require(
            all(
                type(key) is str and type(value) is str for key, value in hashes.items()
            ),
            "direct_url archive hashes must map strings to strings",
        )
        if "sha256" in hashes:
            observed_sha256.append(hashes["sha256"])
    _require(
        bool(observed_sha256),
        "direct_url provenance must record at least one SHA-256",
    )
    for digest in observed_sha256:
        _require_sha256(digest, label="direct_url archive SHA-256")
        _require(
            digest == selected_sha256,
            "direct_url archive SHA-256 does not match selected wheel",
        )


def _record_path(value: str, *, allow_parent_parts: bool = False) -> PurePosixPath:
    _require(value != "", "RECORD contains an empty path")
    _require("\\" not in value and "\x00" not in value, "RECORD path is invalid")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", "."} for part in path.parts)
        and (allow_parent_parts or ".." not in path.parts),
        "RECORD path must be normalized and distribution-relative",
    )
    return path


def _has_symlink_component(root: Path, relative: PurePosixPath) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _decode_record_sha256(value: str) -> bytes:
    _require(value.startswith("sha256="), "RECORD resource hash must use SHA-256")
    encoded = value.removeprefix("sha256=")
    _require(bool(encoded) and "=" not in encoded, "RECORD SHA-256 is malformed")
    try:
        decoded = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise SmokeValidationError("RECORD SHA-256 is malformed") from exc
    _require(len(decoded) == 32, "RECORD SHA-256 has the wrong length")
    return decoded


def _parse_record(
    record_raw: bytes,
    *,
    allowed_external_paths: frozenset[str] = frozenset(),
) -> dict[str, tuple[str, str]]:
    _require(type(record_raw) is bytes, "RECORD input must be bytes")
    _require(len(record_raw) <= _MAX_RECORD_BYTES, "RECORD exceeds its byte limit")
    _require(not record_raw.startswith(b"\xef\xbb\xbf"), "RECORD contains a BOM")
    try:
        text = record_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SmokeValidationError("RECORD is not UTF-8") from exc
    _require("\x00" not in text, "RECORD contains NUL")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise SmokeValidationError("RECORD is malformed CSV") from exc
    _require(
        0 < len(rows) <= _MAX_WHEEL_MEMBERS,
        "RECORD has an invalid row count",
    )

    records: dict[str, tuple[str, str]] = {}
    for row in rows:
        _require(len(row) == 3, "RECORD rows must contain exactly three fields")
        relative = _record_path(
            row[0], allow_parent_parts=row[0] in allowed_external_paths
        ).as_posix()
        _require(relative not in records, f"RECORD path is duplicated: {relative}")
        records[relative] = (row[1], row[2])
    return records


def _validate_openopps_wheel_layout(
    selected_wheel: Path, expected_version: str
) -> tuple[str, ...]:
    _require(
        expected_version == _EXPECTED_OPENOPPS_VERSION,
        "selected wheel version is not the current OpenOpps release",
    )
    members = _validated_wheel_members(selected_wheel)
    member_paths = frozenset(members)
    dist_info_roots = {
        PurePosixPath(relative).parts[0]
        for relative in member_paths
        if PurePosixPath(relative).parts[0].endswith(".dist-info")
    }
    _require(
        dist_info_roots == {_EXPECTED_DIST_INFO_ROOT},
        "selected wheel .dist-info tree does not match the release identity",
    )
    _require(
        _EXPECTED_DIST_INFO_PATHS <= member_paths,
        "selected wheel is missing required release metadata",
    )
    _require(
        _EXPECTED_NON_PACKAGE_PATHS <= member_paths,
        "selected wheel is missing required non-package payload",
    )

    allowed = {
        relative
        for relative in member_paths
        if relative.startswith(f"{_CANONICAL_OPENOPPS_NAME}/")
        or relative in _EXPECTED_NON_PACKAGE_PATHS
        or relative in _EXPECTED_DIST_INFO_PATHS
    }
    unexpected = sorted(member_paths - allowed)
    _require(
        not unexpected,
        f"selected wheel contains an unexpected payload: {unexpected[0] if unexpected else ''}",
    )

    record_path = f"{_EXPECTED_DIST_INFO_ROOT}/RECORD"
    entry_points_path = f"{_EXPECTED_DIST_INFO_ROOT}/entry_points.txt"
    try:
        with zipfile.ZipFile(selected_wheel, "r") as archive:
            entry_points = _read_wheel_member(
                archive,
                members[entry_points_path],
                limit=_MAX_METADATA_BYTES,
                label="wheel entry_points.txt",
            )
            _require(
                entry_points == _EXPECTED_ENTRY_POINTS,
                "selected wheel console entry point does not match the release contract",
            )
            record_raw = _read_wheel_member(
                archive,
                members[record_path],
                limit=_MAX_RECORD_BYTES,
                label="wheel RECORD",
            )
            records = _parse_record(record_raw)
            _require(
                set(records) == set(member_paths),
                "wheel RECORD inventory does not match the archive",
            )
            _require(
                records[record_path] == ("", ""),
                "wheel RECORD self-entry must not contain a hash or size",
            )
            for relative in sorted(member_paths - {record_path}):
                payload = _read_wheel_member(
                    archive,
                    members[relative],
                    limit=_MAX_WHEEL_MEMBER_BYTES,
                    label=f"wheel payload {relative}",
                )
                hash_value, size_value = records[relative]
                _require(
                    hashlib.sha256(payload).digest()
                    == _decode_record_sha256(hash_value),
                    f"wheel RECORD hash does not match archive member: {relative}",
                )
                _require(
                    size_value.isascii()
                    and size_value.isdecimal()
                    and str(int(size_value)) == size_value,
                    f"wheel RECORD size is invalid: {relative}",
                )
                _require(
                    len(payload) == int(size_value),
                    f"wheel RECORD size does not match archive member: {relative}",
                )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SmokeValidationError("selected wheel is not a readable archive") from exc
    return tuple(sorted(member_paths))


def _expected_console_script_record(
    distribution_root: Path,
) -> tuple[str, Path] | None:
    root = distribution_root.resolve(strict=True)
    if sys.platform == "win32":
        if root.name.lower() != "site-packages" or root.parent.name.lower() != "lib":
            return None
        venv_root = root.parent.parent
        script = venv_root / "Scripts" / "openopps.exe"
    else:
        python_dir = root.parent
        library_dir = python_dir.parent
        if (
            root.name != "site-packages"
            or not python_dir.name.startswith("python")
            or library_dir.name not in {"lib", "lib64"}
        ):
            return None
        venv_root = library_dir.parent
        script = venv_root / "bin" / "openopps"
    relative = os.path.relpath(script, root).replace(os.sep, "/")
    _record_path(relative, allow_parent_parts=True)
    return relative, script


def _validated_external_record_paths(
    record_raw: bytes, distribution_root: Path
) -> frozenset[str]:
    expected = _expected_console_script_record(distribution_root)
    allowed = frozenset() if expected is None else frozenset({expected[0]})
    records = _parse_record(record_raw, allowed_external_paths=allowed)
    if expected is None or expected[0] not in records:
        return frozenset()

    relative, script = expected
    root = distribution_root.resolve(strict=True)
    venv_root = script.parent.parent.resolve(strict=True)
    script_relative = PurePosixPath(script.relative_to(venv_root).as_posix())
    _require(
        not _has_symlink_component(venv_root, script_relative),
        "installed OpenOpps console script contains a symlink",
    )
    try:
        resolved = script.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            "installed OpenOpps console script is unavailable"
        ) from exc
    _require(
        resolved.is_relative_to(venv_root) and root.is_relative_to(venv_root),
        "installed OpenOpps console script is outside the fresh venv",
    )
    payload = _read_bounded_file(
        resolved,
        limit=_MAX_METADATA_BYTES,
        label="installed OpenOpps console script",
    )
    hash_value, size_value = records[relative]
    _require(
        hashlib.sha256(payload).digest() == _decode_record_sha256(hash_value),
        "RECORD hash does not match the OpenOpps console script",
    )
    _require(
        size_value.isascii()
        and size_value.isdecimal()
        and str(int(size_value)) == size_value,
        "RECORD size is invalid for the OpenOpps console script",
    )
    _require(
        len(payload) == int(size_value),
        "RECORD size does not match the OpenOpps console script",
    )
    return allowed


def _read_recorded_installed_files(
    record_raw: bytes,
    distribution_root: Path,
    relative_paths: tuple[str, ...],
    *,
    label: str,
    max_file_bytes: int,
    max_total_bytes: int,
    allowed_external_paths: frozenset[str] = frozenset(),
    require_nonempty: bool = True,
) -> dict[str, bytes]:
    records = _parse_record(record_raw, allowed_external_paths=allowed_external_paths)
    try:
        root = distribution_root.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            "installed distribution root is unavailable"
        ) from exc
    _require(root.is_dir(), "installed distribution root must be a directory")

    result: dict[str, bytes] = {}
    total_size = 0
    for relative_value in relative_paths:
        _require(relative_value in records, f"RECORD is missing {relative_value}")
        relative = _record_path(relative_value)
        _require(
            not _has_symlink_component(root, relative),
            f"RECORD {label} contains a symlink: {relative_value}",
        )
        candidate = root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise SmokeValidationError(
                f"RECORD {label} is unavailable: {relative_value}"
            ) from exc
        _require(
            resolved.is_relative_to(root),
            f"RECORD {label} does not resolve beneath distribution root: {relative_value}",
        )
        payload = _read_bounded_file(
            resolved,
            limit=max_file_bytes,
            label=f"installed {label} {relative_value}",
        )
        if require_nonempty:
            _require(
                bool(payload),
                f"RECORD {label} has an invalid size: {relative_value}",
            )
        total_size += len(payload)
        _require(
            total_size <= max_total_bytes,
            f"installed {label}s exceed the aggregate byte limit",
        )
        hash_value, size_value = records[relative_value]
        expected_digest = _decode_record_sha256(hash_value)
        _require(
            hashlib.sha256(payload).digest() == expected_digest,
            f"RECORD hash does not match {label}: {relative_value}",
        )
        _require(
            size_value.isascii()
            and size_value.isdecimal()
            and str(int(size_value)) == size_value,
            f"RECORD size is invalid for {label}: {relative_value}",
        )
        _require(
            len(payload) == int(size_value),
            f"RECORD size does not match {label}: {relative_value}",
        )
        result[relative_value] = payload
    return result


def _read_wheel_files(
    selected_wheel: Path,
    relative_paths: tuple[str, ...],
    *,
    label: str,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, bytes]:
    members = _validated_wheel_members(selected_wheel)
    result: dict[str, bytes] = {}
    total_size = 0
    try:
        with zipfile.ZipFile(selected_wheel, "r") as archive:
            for relative in relative_paths:
                member = members.get(relative)
                if member is None:
                    raise SmokeValidationError(
                        f"selected wheel must contain exactly one {label}: {relative}"
                    )
                payload = _read_wheel_member(
                    archive,
                    member,
                    limit=max_file_bytes,
                    label=f"selected wheel {label} {relative}",
                )
                _require(
                    bool(payload),
                    f"selected wheel {label} has an invalid size: {relative}",
                )
                total_size += len(payload)
                _require(
                    total_size <= max_total_bytes,
                    f"selected wheel {label}s exceed the aggregate byte limit",
                )
                result[relative] = payload
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SmokeValidationError("selected wheel is not a readable archive") from exc
    return result


def _require_installed_files_match_wheel(
    selected_wheel: Path,
    installed: Mapping[str, bytes],
    relative_paths: tuple[str, ...],
    *,
    label: str,
    max_file_bytes: int,
    max_total_bytes: int,
) -> None:
    _require(
        set(installed) == set(relative_paths),
        f"installed {label} set does not match the release contract",
    )
    archived = _read_wheel_files(
        selected_wheel,
        relative_paths,
        label=label,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    for relative in relative_paths:
        _require(
            installed[relative] == archived[relative],
            f"installed {label} bytes do not match selected wheel: {relative}",
        )


def _attest_installed_wheel_payload(
    selected_wheel: Path,
    record_raw: bytes,
    distribution_root: Path,
    expected_version: str,
    *,
    allowed_external_paths: frozenset[str] = frozenset(),
    require_console_script: bool = False,
) -> None:
    wheel_paths = set(_validate_openopps_wheel_layout(selected_wheel, expected_version))
    record_path = f"{_EXPECTED_DIST_INFO_ROOT}/RECORD"
    direct_url_path = f"{_EXPECTED_DIST_INFO_ROOT}/direct_url.json"
    records = _parse_record(record_raw, allowed_external_paths=allowed_external_paths)
    record_paths = set(records)
    required_paths = wheel_paths | {direct_url_path}
    _require(
        required_paths <= record_paths,
        "installed RECORD is missing release wheel payloads",
    )
    unexpected = sorted(
        record_paths
        - wheel_paths
        - _INSTALLER_GENERATED_DIST_INFO_PATHS
        - allowed_external_paths
    )
    _require(
        not unexpected,
        f"installed RECORD contains an unexpected payload: {unexpected[0] if unexpected else ''}",
    )
    if require_console_script:
        _require(
            bool(allowed_external_paths) and allowed_external_paths <= record_paths,
            "installed RECORD is missing the OpenOpps console script",
        )
    _require(
        records[record_path] == ("", ""),
        "installed RECORD self-entry must not contain a hash or size",
    )

    archived_payload_paths = tuple(sorted(wheel_paths - {record_path}))
    installed = _read_recorded_installed_files(
        record_raw,
        distribution_root,
        archived_payload_paths,
        label="wheel payload",
        max_file_bytes=_MAX_WHEEL_MEMBER_BYTES,
        max_total_bytes=_MAX_WHEEL_UNCOMPRESSED_BYTES,
        allowed_external_paths=allowed_external_paths,
        require_nonempty=False,
    )
    _require_installed_files_match_wheel(
        selected_wheel,
        installed,
        archived_payload_paths,
        label="wheel payload",
        max_file_bytes=_MAX_WHEEL_MEMBER_BYTES,
        max_total_bytes=_MAX_WHEEL_UNCOMPRESSED_BYTES,
    )

    generated_paths = tuple(sorted(record_paths & _INSTALLER_GENERATED_DIST_INFO_PATHS))
    _read_recorded_installed_files(
        record_raw,
        distribution_root,
        generated_paths,
        label="installer metadata",
        max_file_bytes=_MAX_METADATA_BYTES,
        max_total_bytes=_MAX_METADATA_BYTES,
        allowed_external_paths=allowed_external_paths,
        require_nonempty=False,
    )

    try:
        root = distribution_root.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            "installed distribution root is unavailable"
        ) from exc
    dist_info_root = root / _EXPECTED_DIST_INFO_ROOT
    _require(
        not dist_info_root.is_symlink() and dist_info_root.is_dir(),
        "installed .dist-info root must be a regular directory",
    )
    actual_dist_info_paths: set[str] = set()
    for candidate in dist_info_root.rglob("*"):
        relative = candidate.relative_to(root)
        relative_posix = relative.as_posix()
        _require(
            not _has_symlink_component(root, PurePosixPath(relative_posix)),
            f"installed .dist-info contains a symlink: {relative_posix}",
        )
        if candidate.is_dir():
            continue
        try:
            mode = candidate.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise SmokeValidationError(
                f"installed .dist-info file is unavailable: {relative_posix}"
            ) from exc
        _require(
            stat.S_ISREG(mode),
            f"installed .dist-info entry is not a regular file: {relative_posix}",
        )
        actual_dist_info_paths.add(relative_posix)
        _require(
            len(actual_dist_info_paths) <= _MAX_WHEEL_MEMBERS,
            "installed .dist-info has too many files",
        )
    recorded_dist_info_paths = {
        relative
        for relative in record_paths
        if relative.startswith(f"{_EXPECTED_DIST_INFO_ROOT}/")
    }
    _require(
        actual_dist_info_paths == recorded_dist_info_paths,
        "installed .dist-info file set does not match RECORD",
    )


def _read_required_record_resources(
    record_raw: bytes,
    distribution_root: Path,
    *,
    allowed_external_paths: frozenset[str] = frozenset(),
) -> dict[str, bytes]:
    return _read_recorded_installed_files(
        record_raw,
        distribution_root,
        _REQUIRED_RESOURCE_PATHS,
        label="resource",
        max_file_bytes=_MAX_RESOURCE_BYTES,
        max_total_bytes=_MAX_RESOURCE_BYTES,
        allowed_external_paths=allowed_external_paths,
    )


def _read_required_wheel_resources(selected_wheel: Path) -> dict[str, bytes]:
    return _read_wheel_files(
        selected_wheel,
        _REQUIRED_RESOURCE_PATHS,
        label="resource",
        max_file_bytes=_MAX_RESOURCE_BYTES,
        max_total_bytes=_MAX_RESOURCE_BYTES,
    )


def _require_installed_resources_match_wheel(
    selected_wheel: Path, installed: Mapping[str, bytes]
) -> None:
    _require_installed_files_match_wheel(
        selected_wheel,
        installed,
        _REQUIRED_RESOURCE_PATHS,
        label="resource",
        max_file_bytes=_MAX_RESOURCE_BYTES,
        max_total_bytes=_MAX_RESOURCE_BYTES,
    )


def _attest_installed_package(
    selected_wheel: Path,
    record_raw: bytes,
    distribution_root: Path,
    site_packages: Path,
    *,
    allowed_external_paths: frozenset[str] = frozenset(),
) -> None:
    members = _validated_wheel_members(selected_wheel)
    package_paths = tuple(
        sorted(
            relative
            for relative in members
            if PurePosixPath(relative).parts[0] == _CANONICAL_OPENOPPS_NAME
        )
    )
    _require(bool(package_paths), "selected wheel contains no OpenOpps package files")
    _require(
        f"{_CANONICAL_OPENOPPS_NAME}/__init__.py" in package_paths,
        "selected wheel is missing openopps/__init__.py",
    )

    try:
        root = distribution_root.resolve(strict=True)
        site_root = site_packages.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError("installed package root is unavailable") from exc
    package_root = root / _CANONICAL_OPENOPPS_NAME
    _require(
        not package_root.is_symlink() and package_root.is_dir(),
        "installed OpenOpps package root must be a regular directory",
    )
    _require(
        package_root.resolve(strict=True).is_relative_to(site_root),
        "installed OpenOpps package is outside the fresh venv",
    )

    for child in site_root.iterdir():
        if child.name == _CANONICAL_OPENOPPS_NAME:
            _require(
                child.resolve(strict=True) == package_root.resolve(strict=True),
                "installed OpenOpps package root is ambiguous",
            )
        elif child.name.startswith(f"{_CANONICAL_OPENOPPS_NAME}."):
            raise SmokeValidationError(
                f"installed OpenOpps import is shadowed by {child.name}"
            )

    actual_paths: set[str] = set()
    for candidate in package_root.rglob("*"):
        relative = candidate.relative_to(root)
        _require(
            not _has_symlink_component(root, PurePosixPath(relative.as_posix())),
            f"installed package contains a symlink: {relative.as_posix()}",
        )
        if candidate.is_dir():
            continue
        try:
            mode = candidate.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise SmokeValidationError(
                f"installed package file is unavailable: {relative.as_posix()}"
            ) from exc
        _require(
            stat.S_ISREG(mode),
            f"installed package entry is not a regular file: {relative.as_posix()}",
        )
        actual_paths.add(relative.as_posix())
        _require(
            len(actual_paths) <= _MAX_WHEEL_MEMBERS,
            "installed package has too many files",
        )
    _require(
        actual_paths == set(package_paths),
        "installed OpenOpps package file set does not match the selected wheel",
    )

    installed = _read_recorded_installed_files(
        record_raw,
        root,
        package_paths,
        label="package file",
        max_file_bytes=_MAX_WHEEL_MEMBER_BYTES,
        max_total_bytes=_MAX_WHEEL_UNCOMPRESSED_BYTES,
        allowed_external_paths=allowed_external_paths,
    )
    _require_installed_files_match_wheel(
        selected_wheel,
        installed,
        package_paths,
        label="package file",
        max_file_bytes=_MAX_WHEEL_MEMBER_BYTES,
        max_total_bytes=_MAX_WHEEL_UNCOMPRESSED_BYTES,
    )

    _require(
        _CANONICAL_OPENOPPS_NAME not in sys.modules,
        "candidate OpenOpps code was imported before package attestation",
    )
    spec = importlib.util.find_spec(_CANONICAL_OPENOPPS_NAME)
    if spec is None or spec.origin is None:
        raise SmokeValidationError("installed OpenOpps import spec is unavailable")
    try:
        origin = Path(spec.origin).resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            "installed OpenOpps import origin is unavailable"
        ) from exc
    _require(
        origin == (package_root / "__init__.py").resolve(strict=True),
        "installed OpenOpps import origin does not match the attested package",
    )
    locations = spec.submodule_search_locations
    _require(
        locations is not None
        and {Path(value).resolve(strict=True) for value in locations}
        == {package_root.resolve(strict=True)},
        "installed OpenOpps package search path is ambiguous",
    )


def _single_distribution_file(dist: Any, filename: str) -> Path:
    files = dist.files
    _require(files is not None, "installed distribution file inventory is unavailable")
    matches = [
        entry
        for entry in files
        if entry.name == filename
        and len(entry.parts) == 2
        and entry.parent.name.endswith(".dist-info")
    ]
    _require(
        len(matches) == 1,
        f"installed distribution must contain exactly one .dist-info/{filename}",
    )
    path = Path(dist.locate_file(matches[0]))
    _require(not path.is_symlink(), f"installed {filename} must not be a symlink")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(f"installed {filename} is unavailable") from exc


def _installed_catalog_verifier(
    site_packages_value: str,
    wheel_value: str,
    expected_version: str,
    selected_sha256: str,
) -> None:
    try:
        site_packages = Path(site_packages_value).resolve(strict=True)
        selected_wheel = Path(wheel_value).resolve(strict=True)
    except OSError as exc:
        raise SmokeValidationError(
            "installed verifier input path is unavailable"
        ) from exc
    _require(site_packages.is_dir(), "fresh venv site-packages is not a directory")
    _require(selected_wheel.is_file(), "selected wheel must be a regular file")
    _require(
        expected_version == _EXPECTED_OPENOPPS_VERSION,
        "selected wheel version is not the current OpenOpps release",
    )
    _require_sha256(selected_sha256, label="selected wheel digest")
    _require(
        _sha256_file(selected_wheel) == selected_sha256,
        "selected wheel changed after discovery",
    )
    sys.path.insert(0, str(site_packages))

    from importlib.metadata import distribution

    dist = distribution("openopps")
    names = dist.metadata.get_all("Name", [])
    versions = dist.metadata.get_all("Version", [])
    _require(
        len(names) == 1
        and _canonical_project_name(names[0]) == _CANONICAL_OPENOPPS_NAME,
        "installed distribution Name metadata is missing or ambiguous",
    )
    _require(
        len(versions) == 1 and versions[0] == expected_version,
        "installed distribution version does not match wheel metadata",
    )
    dist_root = Path(str(dist.locate_file(""))).resolve(strict=True)
    _require(
        dist_root == site_packages or dist_root.is_relative_to(site_packages),
        "installed distribution root is outside the fresh venv",
    )
    direct_url_path = _single_distribution_file(dist, "direct_url.json")
    record_path = _single_distribution_file(dist, "RECORD")
    _require(
        direct_url_path.is_relative_to(dist_root)
        and record_path.is_relative_to(dist_root),
        "installed distribution metadata resolves outside its root",
    )
    direct_url_raw = _read_bounded_file(
        direct_url_path,
        limit=_MAX_DIRECT_URL_BYTES,
        label="installed direct_url.json",
    )
    record_raw = _read_bounded_file(
        record_path,
        limit=_MAX_RECORD_BYTES,
        label="installed RECORD",
    )
    _validate_direct_url(direct_url_raw, selected_wheel, selected_sha256)
    allowed_external_paths = _validated_external_record_paths(record_raw, dist_root)
    installed = _read_required_record_resources(
        record_raw,
        dist_root,
        allowed_external_paths=allowed_external_paths,
    )
    _require_installed_resources_match_wheel(selected_wheel, installed)
    _attest_installed_wheel_payload(
        selected_wheel,
        record_raw,
        dist_root,
        expected_version,
        allowed_external_paths=allowed_external_paths,
        require_console_script=True,
    )
    _attest_installed_package(
        selected_wheel,
        record_raw,
        dist_root,
        site_packages,
        allowed_external_paths=allowed_external_paths,
    )

    readback = _validate_catalog_resources(
        installed[_CATALOG_RELATIVE_PATH.as_posix()],
        installed[_EVIDENCE_RELATIVE_PATH.as_posix()],
        installed[_SCHEMA_RELATIVE_PATH.as_posix()],
    )

    import openopps

    _require(
        openopps.__version__ == expected_version,
        "installed package version does not match wheel metadata",
    )
    package_path = Path(openopps.__file__).resolve(strict=True)
    _require(
        package_path.is_relative_to(dist_root),
        "imported OpenOpps package is outside its installed distribution",
    )
    print(readback.version, readback.count, readback.fingerprint[:12])


def _run_isolated_function(
    python: Path,
    module_path: Path,
    function_name: str,
    arguments: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    subprocess.check_call(
        [
            str(python),
            "-I",
            "-S",
            "-B",
            "-c",
            _ISOLATED_FUNCTION_BOOTSTRAP,
            str(module_path.resolve(strict=True)),
            function_name,
            *arguments,
        ],
        cwd=cwd,
        env=env,
    )


def _run_installed_catalog_verifier(
    python: Path,
    site_packages: Path,
    selected_wheel: Path,
    expected_version: str,
    selected_sha256: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    _run_isolated_function(
        python,
        Path(__file__),
        "_installed_catalog_verifier",
        [
            str(site_packages),
            str(selected_wheel),
            expected_version,
            selected_sha256,
        ],
        cwd=cwd,
        env=env,
    )


def _run_isolated_openopps(
    python: Path,
    site_packages: Path,
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    capture_output: bool = False,
) -> str | None:
    command = [
        str(python),
        "-I",
        "-S",
        "-B",
        "-c",
        _ISOLATED_CLI_BOOTSTRAP,
        str(site_packages),
        *arguments,
    ]
    if capture_output:
        return subprocess.check_output(command, cwd=cwd, env=env, text=True)
    subprocess.check_call(command, cwd=cwd, env=env)
    return None


def main() -> int:
    args = _parse_args()
    if args.validate_requirements is not None:
        _validate_exported_requirements(args.validate_requirements)
        print("requirements-lock ok", args.validate_requirements)
        return 0

    _require(args.wheel_dir is not None, "--wheel-dir is required")
    _require(args.uv_bin is not None, "--uv-bin is required")
    wheel_dir = cast(Path, args.wheel_dir)
    uv_bin = cast(Path, args.uv_bin)
    uv = _validated_uv_bin(uv_bin)
    selected = _select_openopps_wheel(wheel_dir)
    _require(
        selected.version == _EXPECTED_OPENOPPS_VERSION,
        "selected wheel version is not the current OpenOpps release",
    )
    _preflight_wheel_archive(selected.path, required_paths=_REQUIRED_RESOURCE_PATHS)
    _validate_openopps_wheel_layout(selected.path, selected.version)
    with tempfile.TemporaryDirectory(prefix="openopps-wheel-smoke-") as tmp:
        work_dir = Path(tmp)
        python, env = _prepare_locked_runtime(
            uv,
            selected.path,
            selected.sha256,
            work_dir,
        )
        site_packages = _venv_site_packages(work_dir / "venv")
        _run_installed_catalog_verifier(
            python,
            site_packages,
            selected.path,
            selected.version,
            selected.sha256,
            cwd=work_dir,
            env=env,
        )
        version_output = _run_isolated_openopps(
            python,
            site_packages,
            ("--version",),
            cwd=work_dir,
            env=env,
            capture_output=True,
        )
        _require(
            version_output is not None
            and version_output.strip() == f"openopps {selected.version}",
            f"installed CLI reported unexpected version: {version_output!r}",
        )
        _run_isolated_openopps(
            python,
            site_packages,
            ("jobs", "--help"),
            cwd=work_dir,
            env=env,
        )
        _run_isolated_openopps(
            python,
            site_packages,
            ("providers", "--help"),
            cwd=work_dir,
            env=env,
        )
    print("wheel-catalog-smoke ok", selected.path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
