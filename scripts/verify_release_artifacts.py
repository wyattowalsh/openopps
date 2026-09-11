#!/usr/bin/env python3
"""Fail closed on stale, oversized, or mis-scoped OpenOpps release artifacts."""

from __future__ import annotations

import argparse
import ast
import base64
from configparser import ConfigParser, Error as ConfigParserError
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tomllib
import unicodedata
import zipfile


MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
UV_DIST_CONTROL_FILE = ".gitignore"
UV_DIST_CONTROL_CONTENTS = {b"*", b"*\n"}
EXPECTED_PROJECT_NAME = "openopps"
EXPECTED_PROJECT_SCRIPTS = {"openopps": "openopps.cli:app"}
EXPECTED_BUILD_SYSTEM = {
    "requires": ["hatchling==1.32.0"],
    "build-backend": "hatchling.build",
}
FORBIDDEN_PARTS = {
    ".grok",
    ".playwright-mcp",
    "AGENTS.md",
    "goals",
    "inspect-shots",
    "tests",
    "web",
}
REQUIRED_WHEEL_FILES = {
    "examples/examples.py",
    "openopps/__init__.py",
    "openopps/cli.py",
    "openopps/discovery/data/approved_ingestion_selector_envelope.json",
    "openopps/discovery/data/discovery_promotion_policy_decision.json",
    "openopps/discovery/data/evidence_only_decision_receipt.json",
    "openopps/discovery/data/promotion_decision_ledger.jsonl",
    "openopps/providers/sources/data/portfolio_source_catalog.json",
    "openopps/providers/sources/data/source_policy_evidence.json",
    "openopps/providers/sources/data/source_policy_evidence.schema.json",
    "openopps/alembic/versions/0005_update_snapshot_ledger.py",
}
REQUIRED_SDIST_FILES = {
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "pyproject.toml",
} | {
    f"src/{name}" if name.startswith("openopps/") else name
    for name in REQUIRED_WHEEL_FILES
}
ALLOWED_SDIST_ROOT_FILES = {
    ".gitignore",
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "pyproject.toml",
}
WINDOWS_DEVICE_NAMES = {
    "aux",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
} | {
    f"{prefix}{suffix}"
    for prefix in ("com", "lpt")
    for suffix in (*map(str, range(1, 10)), "¹", "²", "³")
}


class ArtifactVerificationError(RuntimeError):
    """Raised when built artifacts do not match the release package contract."""


class _CaseSensitiveConfigParser(ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def project_version(project_root: Path) -> str:
    pyproject_path = project_root / "pyproject.toml"
    try:
        pyproject_source = pyproject_path.read_bytes()
        payload = tomllib.loads(pyproject_source.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ArtifactVerificationError(f"cannot read source pyproject: {exc}") from exc
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ArtifactVerificationError("pyproject.toml has no project.version")
    _verify_pyproject_contract(payload, version, artifact="source pyproject")
    init_path = project_root / "src" / "openopps" / "__init__.py"
    try:
        source_version = _declared_package_version(
            init_path.read_bytes(), artifact="source package"
        )
    except OSError as exc:
        raise ArtifactVerificationError(
            f"cannot read source package version: {exc}"
        ) from exc
    if source_version != version:
        raise ArtifactVerificationError(
            f"source package version {source_version!r} does not equal {version!r}"
        )
    return version


def verify_release_artifacts(
    dist_dir: Path,
    expected_version: str,
    *,
    expected_pyproject: bytes | None = None,
) -> None:
    if not dist_dir.is_dir():
        raise ArtifactVerificationError(
            f"artifact directory does not exist: {dist_dir}"
        )

    entries = sorted(dist_dir.iterdir())
    expected_names = {
        f"openopps-{expected_version}-py3-none-any.whl",
        f"openopps-{expected_version}.tar.gz",
    }
    actual_names = {path.name for path in entries if path.name != UV_DIST_CONTROL_FILE}
    invalid_entries = [
        path.name
        for path in entries
        if path.is_symlink()
        or not path.is_file()
        or path.name not in expected_names | {UV_DIST_CONTROL_FILE}
    ]
    if actual_names != expected_names or invalid_entries:
        raise ArtifactVerificationError(
            "artifact directory must contain exactly the expected wheel and sdist "
            "plus an optional uv control file; "
            f"expected={sorted(expected_names)!r} actual={sorted(actual_names)!r} "
            f"invalid={sorted(invalid_entries)!r}"
        )
    control_path = dist_dir / UV_DIST_CONTROL_FILE
    if (
        control_path.exists()
        and control_path.read_bytes() not in UV_DIST_CONTROL_CONTENTS
    ):
        raise ArtifactVerificationError("uv dist .gitignore has unexpected contents")

    artifacts = [dist_dir / name for name in sorted(expected_names)]
    oversized = [
        path.name for path in artifacts if path.stat().st_size > MAX_ARTIFACT_BYTES
    ]
    if oversized:
        raise ArtifactVerificationError(
            f"release artifacts exceed {MAX_ARTIFACT_BYTES} bytes: {oversized!r}"
        )

    expected_project = (
        _trusted_project_metadata(expected_pyproject, expected_version)
        if expected_pyproject is not None
        else None
    )

    try:
        _verify_wheel(
            dist_dir / f"openopps-{expected_version}-py3-none-any.whl",
            expected_version,
            expected_project=expected_project,
        )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArtifactVerificationError(f"wheel archive is unreadable: {exc}") from exc
    try:
        _verify_sdist(
            dist_dir / f"openopps-{expected_version}.tar.gz",
            expected_version,
            expected_pyproject=expected_pyproject,
            expected_project=expected_project,
        )
    except (OSError, tarfile.TarError) as exc:
        raise ArtifactVerificationError(f"sdist archive is unreadable: {exc}") from exc


def _verify_wheel(
    wheel_path: Path,
    expected_version: str,
    *,
    expected_project: dict | None,
) -> None:
    with zipfile.ZipFile(wheel_path) as archive:
        members = archive.infolist()
        _verify_archive_budget(
            [(member.filename, member.file_size) for member in members],
            artifact="wheel",
        )
        _verify_archive_names(
            [(member.filename, member.is_dir()) for member in members],
            artifact="wheel",
        )
        _verify_zip_members(members)
        dist_info_root = f"openopps-{expected_version}.dist-info"
        unexpected_members = sorted(
            member.filename
            for member in members
            if not _wheel_member_is_allowed(member.filename, dist_info_root)
        )
        if unexpected_members:
            raise ArtifactVerificationError(
                f"wheel contains unexpected members: {unexpected_members!r}"
            )
        file_members = [member for member in members if not member.is_dir()]
        names = {member.filename for member in file_members}
        missing = sorted(REQUIRED_WHEEL_FILES - names)
        if missing:
            raise ArtifactVerificationError(
                f"wheel is missing required files: {missing!r}"
            )
        metadata_names = sorted(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            raise ArtifactVerificationError(
                f"wheel must contain one METADATA file, found {metadata_names!r}"
            )
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_names[0])
        )
        _verify_metadata(
            metadata,
            expected_version,
            artifact="wheel",
            expected_project=expected_project,
        )

        package_version = _declared_package_version(
            archive.read("openopps/__init__.py"), artifact="wheel package"
        )
        if package_version != expected_version:
            raise ArtifactVerificationError(
                f"wheel package version {package_version!r} "
                f"does not equal {expected_version!r}"
            )

        entry_points = f"openopps-{expected_version}.dist-info/entry_points.txt"
        if entry_points not in names:
            raise ArtifactVerificationError(
                "wheel is missing console entry-point metadata"
            )
        _verify_entry_points(archive.read(entry_points))

        required_dist_info = {
            f"openopps-{expected_version}.dist-info/RECORD",
            f"openopps-{expected_version}.dist-info/WHEEL",
        }
        missing_dist_info = sorted(required_dist_info - names)
        if missing_dist_info:
            raise ArtifactVerificationError(
                f"wheel is missing required dist-info files: {missing_dist_info!r}"
            )
        wheel_metadata_name = f"openopps-{expected_version}.dist-info/WHEEL"
        record_name = f"openopps-{expected_version}.dist-info/RECORD"
        _verify_wheel_metadata(archive.read(wheel_metadata_name))
        _verify_wheel_record(
            archive,
            file_members=file_members,
            record_name=record_name,
        )


def _verify_sdist(
    sdist_path: Path,
    expected_version: str,
    *,
    expected_pyproject: bytes | None,
    expected_project: dict | None,
) -> None:
    expected_root = f"openopps-{expected_version}"
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        members = _read_bounded_tar_members(archive)
        member_names = [member.name for member in members]
        _verify_archive_names(
            [(member.name, member.isdir()) for member in members],
            artifact="sdist",
        )
        _verify_sdist_member_scope(member_names, expected_root)
        invalid_types = [
            member.name
            for member in members
            if not member.isdir() and not member.isfile()
        ]
        if invalid_types:
            raise ArtifactVerificationError(
                f"sdist contains links or special members: {invalid_types!r}"
            )
        nonempty_directories = [
            member.name for member in members if member.isdir() and member.size != 0
        ]
        if nonempty_directories:
            raise ArtifactVerificationError(
                f"sdist contains non-empty directory members: {nonempty_directories!r}"
            )
        file_members = [member for member in members if member.isfile()]
        names = {member.name for member in file_members}

        relative_names: set[str] = set()
        for name in names:
            path = PurePosixPath(name)
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            relative_names.add(relative)

        missing = sorted(REQUIRED_SDIST_FILES - relative_names)
        if missing:
            raise ArtifactVerificationError(
                f"sdist is missing required files: {missing!r}"
            )

        metadata_name = f"{expected_root}/PKG-INFO"
        metadata_member = archive.getmember(metadata_name)
        metadata_file = archive.extractfile(metadata_member)
        if metadata_file is None:
            raise ArtifactVerificationError("sdist PKG-INFO is unreadable")
        metadata = BytesParser(policy=policy.default).parsebytes(metadata_file.read())
        _verify_metadata(
            metadata,
            expected_version,
            artifact="sdist",
            expected_project=expected_project,
        )

        init_name = f"{expected_root}/src/openopps/__init__.py"
        init_member = archive.extractfile(archive.getmember(init_name))
        if init_member is None:
            raise ArtifactVerificationError("sdist package version file is unreadable")
        package_version = _declared_package_version(
            init_member.read(), artifact="sdist package"
        )
        if package_version != expected_version:
            raise ArtifactVerificationError(
                f"sdist package version {package_version!r} "
                f"does not equal {expected_version!r}"
            )

        pyproject_name = f"{expected_root}/pyproject.toml"
        pyproject_member = archive.extractfile(archive.getmember(pyproject_name))
        if pyproject_member is None:
            raise ArtifactVerificationError("sdist pyproject.toml is unreadable")
        embedded_pyproject = pyproject_member.read()
        try:
            embedded_payload = tomllib.loads(embedded_pyproject.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ArtifactVerificationError(
                f"sdist pyproject is invalid: {exc}"
            ) from exc
        _verify_pyproject_contract(
            embedded_payload, expected_version, artifact="sdist pyproject"
        )
        if expected_pyproject is not None and embedded_pyproject != expected_pyproject:
            raise ArtifactVerificationError(
                "sdist pyproject.toml bytes do not equal the trusted source"
            )


def _verify_archive_names(members: list[tuple[str, bool]], *, artifact: str) -> None:
    seen_members: dict[str, str] = {}
    directories: dict[str, str] = {}
    files: dict[str, str] = {}
    for name, is_directory in members:
        canonical = _canonical_archive_name(name, is_directory=is_directory)
        prefixes = _archive_path_prefixes(canonical)
        collision_key = prefixes[-1][1]
        previous = seen_members.get(collision_key)
        if previous is not None:
            raise _archive_path_collision_error(
                artifact, previous, name, kind="duplicate or normalization/case"
            )

        for prefix, prefix_key in prefixes[:-1]:
            previous_file = files.get(prefix_key)
            if previous_file is not None:
                raise _archive_path_collision_error(
                    artifact, previous_file, name, kind="file/directory"
                )
            previous_directory = directories.get(prefix_key)
            if previous_directory is not None and previous_directory != prefix:
                raise _archive_path_collision_error(
                    artifact,
                    previous_directory,
                    name,
                    kind="normalization/case",
                )
            directories.setdefault(prefix_key, prefix)

        if is_directory:
            previous_directory = directories.get(collision_key)
            if previous_directory is not None and previous_directory != canonical:
                raise _archive_path_collision_error(
                    artifact,
                    previous_directory,
                    name,
                    kind="normalization/case",
                )
            directories.setdefault(collision_key, canonical)
        else:
            previous_directory = directories.get(collision_key)
            if previous_directory is not None:
                raise _archive_path_collision_error(
                    artifact, previous_directory, name, kind="file/directory"
                )
            files[collision_key] = canonical

        seen_members[collision_key] = name
        path = PurePosixPath(canonical)
        if canonical.endswith(".draft"):
            raise ArtifactVerificationError(
                f"draft file leaked into artifact: {name!r}"
            )
        forbidden = FORBIDDEN_PARTS.intersection(path.parts)
        if forbidden:
            raise ArtifactVerificationError(
                f"local-only path leaked into artifact: {name!r} ({sorted(forbidden)!r})"
            )


def _canonical_archive_name(name: str, *, is_directory: bool) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
    if name.endswith("/"):
        if not is_directory or name.endswith("//"):
            raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
        canonical = name[:-1]
    else:
        canonical = name
    parts = canonical.split("/")
    if not canonical or any(part in {"", ".", ".."} for part in parts):
        raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
    if any(part.endswith((" ", ".")) for part in parts):
        raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
    if any(_is_windows_device_name(part) for part in parts):
        raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
    path = PurePosixPath(canonical)
    if path.is_absolute() or path.as_posix() != canonical:
        raise ArtifactVerificationError(f"unsafe archive member path: {name!r}")
    return canonical


def _archive_collision_key(canonical: str) -> str:
    normalized = unicodedata.normalize("NFC", canonical)
    return unicodedata.normalize("NFC", normalized.casefold())


def _archive_path_prefixes(canonical: str) -> list[tuple[str, str]]:
    parts = canonical.split("/")
    return [
        (prefix, _archive_collision_key(prefix))
        for index in range(1, len(parts) + 1)
        if (prefix := "/".join(parts[:index]))
    ]


def _archive_path_collision_error(
    artifact: str,
    first: str,
    second: str,
    *,
    kind: str,
) -> ArtifactVerificationError:
    return ArtifactVerificationError(
        f"{artifact} contains {kind}-colliding member paths: {first!r}, {second!r}"
    )


def _is_windows_device_name(part: str) -> bool:
    normalized = unicodedata.normalize("NFC", part)
    stem = normalized.partition(".")[0].rstrip(" ").casefold()
    return stem in WINDOWS_DEVICE_NAMES


def _verify_zip_members(members: list[zipfile.ZipInfo]) -> None:
    for member in members:
        if member.flag_bits & 0x1:
            raise ArtifactVerificationError(
                f"wheel contains an encrypted member: {member.filename!r}"
            )
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ArtifactVerificationError(
                f"wheel contains an unsupported compression method: {member.filename!r}"
            )
        unix_mode = member.external_attr >> 16
        member_type = stat.S_IFMT(unix_mode)
        expected_type = stat.S_IFDIR if member.is_dir() else stat.S_IFREG
        if member_type not in {0, expected_type}:
            raise ArtifactVerificationError(
                f"wheel contains a link or special member: {member.filename!r}"
            )
        if member.is_dir() and member.file_size != 0:
            raise ArtifactVerificationError(
                f"wheel contains a non-empty directory member: {member.filename!r}"
            )


def _verify_wheel_metadata(payload: bytes) -> None:
    metadata = BytesParser(policy=policy.default).parsebytes(payload)
    expected = {
        "Wheel-Version": "1.0",
        "Root-Is-Purelib": "true",
        "Tag": "py3-none-any",
    }
    for key, expected_value in expected.items():
        values = metadata.get_all(key, [])
        if values != [expected_value]:
            raise ArtifactVerificationError(
                f"wheel WHEEL metadata has invalid {key}: {values!r}"
            )


def _verify_wheel_record(
    archive: zipfile.ZipFile,
    *,
    file_members: list[zipfile.ZipInfo],
    record_name: str,
) -> None:
    try:
        record_payload = archive.read(record_name).decode("utf-8")
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ArtifactVerificationError(f"wheel RECORD is unreadable: {exc}") from exc
    try:
        rows = list(csv.reader(io.StringIO(record_payload, newline=""), strict=True))
    except csv.Error as exc:
        raise ArtifactVerificationError(f"wheel RECORD is invalid CSV: {exc}") from exc

    records: dict[str, tuple[str, str]] = {}
    seen_casefold: dict[str, str] = {}
    for row in rows:
        if len(row) != 3:
            raise ArtifactVerificationError(f"wheel RECORD has an invalid row: {row!r}")
        name, digest, size = row
        canonical = _canonical_archive_name(name, is_directory=False)
        collision_key = _archive_collision_key(canonical)
        if canonical in records or collision_key in seen_casefold:
            raise ArtifactVerificationError(
                "wheel RECORD contains duplicate or normalization/case-colliding "
                f"paths: {name!r}"
            )
        records[canonical] = (digest, size)
        seen_casefold[collision_key] = canonical

    member_names = {member.filename for member in file_members}
    if set(records) != member_names:
        missing = sorted(member_names - set(records))
        unexpected = sorted(set(records) - member_names)
        raise ArtifactVerificationError(
            f"wheel RECORD does not cover every file: missing={missing!r} "
            f"unexpected={unexpected!r}"
        )

    for member in file_members:
        digest, size = records[member.filename]
        if member.filename == record_name:
            if digest or size:
                raise ArtifactVerificationError(
                    "wheel RECORD self-row must have empty hash and size"
                )
            continue
        try:
            payload = archive.read(member)
        except (RuntimeError, zipfile.BadZipFile) as exc:
            raise ArtifactVerificationError(
                f"wheel member is unreadable: {member.filename!r}: {exc}"
            ) from exc
        expected_digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        if digest != f"sha256={expected_digest}":
            raise ArtifactVerificationError(
                f"wheel RECORD hash mismatch for {member.filename!r}"
            )
        if size != str(len(payload)):
            raise ArtifactVerificationError(
                f"wheel RECORD size mismatch for {member.filename!r}"
            )


def _wheel_member_is_allowed(name: str, dist_info_root: str) -> bool:
    normalized = name.rstrip("/")
    return (
        normalized == "examples"
        or normalized == "examples/examples.py"
        or normalized == "openopps"
        or normalized.startswith("openopps/")
        or normalized == dist_info_root
        or normalized.startswith(f"{dist_info_root}/")
    )


def _verify_sdist_member_scope(names: list[str], expected_root: str) -> None:
    for name in names:
        path = PurePosixPath(name.rstrip("/"))
        if not path.parts or path.parts[0] != expected_root:
            raise ArtifactVerificationError(
                f"sdist member is outside {expected_root!r}: {name!r}"
            )
        relative = PurePosixPath(*path.parts[1:]).as_posix()
        if relative in {".", "examples", "src", "src/openopps"}:
            continue
        if relative in ALLOWED_SDIST_ROOT_FILES or relative == "examples/examples.py":
            continue
        if relative.startswith("src/openopps/"):
            continue
        raise ArtifactVerificationError(
            f"sdist contains a non-package release member: {relative!r}"
        )


def _verify_archive_budget(members: list[tuple[str, int]], *, artifact: str) -> None:
    _verify_member_count(len(members), artifact=artifact)
    _verify_uncompressed_size(
        sum(size for _, size in members),
        artifact=artifact,
    )


def _read_bounded_tar_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    total_size = 0
    for member in archive:
        members.append(member)
        _verify_member_count(len(members), artifact="sdist")
        total_size += member.size
        _verify_uncompressed_size(total_size, artifact="sdist")
    return members


def _verify_member_count(member_count: int, *, artifact: str) -> None:
    if member_count > MAX_ARCHIVE_FILES:
        raise ArtifactVerificationError(
            f"{artifact} contains too many archive members: "
            f"{member_count} > {MAX_ARCHIVE_FILES}"
        )


def _verify_uncompressed_size(total_size: int, *, artifact: str) -> None:
    if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise ArtifactVerificationError(
            f"{artifact} expands beyond {MAX_ARCHIVE_UNCOMPRESSED_BYTES} bytes"
        )


def _declared_package_version(source: bytes, *, artifact: str) -> str:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ArtifactVerificationError(
            f"{artifact} version source is invalid: {exc}"
        ) from exc
    versions: list[str] = []
    for node in tree.body:
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__version__"
        ):
            value = node.value
        if value is not None:
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, TypeError) as exc:
                raise ArtifactVerificationError(
                    f"{artifact} __version__ must be a string literal"
                ) from exc
            if not isinstance(parsed, str) or not parsed:
                raise ArtifactVerificationError(
                    f"{artifact} __version__ must be a non-empty string"
                )
            versions.append(parsed)
    if len(versions) != 1:
        raise ArtifactVerificationError(
            f"{artifact} must declare exactly one __version__, found {versions!r}"
        )
    return versions[0]


def _verify_entry_points(payload: bytes) -> None:
    parser = _CaseSensitiveConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(payload.decode("utf-8"))
    except (ConfigParserError, UnicodeDecodeError) as exc:
        raise ArtifactVerificationError(
            f"wheel entry points are invalid: {exc}"
        ) from exc
    if parser.defaults():
        raise ArtifactVerificationError(
            f"wheel entry points contain defaults: {parser.defaults()!r}"
        )
    if parser.sections() != ["console_scripts"]:
        raise ArtifactVerificationError(
            f"wheel has unexpected entry-point groups: {parser.sections()!r}"
        )
    console_scripts = (
        dict(parser.items("console_scripts", raw=True))
        if parser.has_section("console_scripts")
        else {}
    )
    if console_scripts != {"openopps": "openopps.cli:app"}:
        raise ArtifactVerificationError(
            f"wheel has the wrong console entry points: {console_scripts!r}"
        )


def _verify_pyproject_contract(
    payload: dict, expected_version: str, *, artifact: str
) -> None:
    project = payload.get("project")
    build_system = payload.get("build-system")
    if not isinstance(project, dict) or project.get("name") != EXPECTED_PROJECT_NAME:
        raise ArtifactVerificationError(f"{artifact} has the wrong project name")
    if project.get("version") != expected_version:
        raise ArtifactVerificationError(
            f"{artifact} version {project.get('version')!r} "
            f"does not equal {expected_version!r}"
        )
    if project.get("scripts") != EXPECTED_PROJECT_SCRIPTS:
        raise ArtifactVerificationError(f"{artifact} has the wrong project scripts")
    if build_system != EXPECTED_BUILD_SYSTEM:
        raise ArtifactVerificationError(f"{artifact} has the wrong build system")


def _trusted_project_metadata(payload: bytes, expected_version: str) -> dict:
    try:
        pyproject = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ArtifactVerificationError(f"trusted pyproject is invalid: {exc}") from exc
    _verify_pyproject_contract(
        pyproject, expected_version, artifact="trusted pyproject"
    )
    project = pyproject["project"]
    requires_python = project.get("requires-python")
    dependencies = project.get("dependencies")
    if not isinstance(requires_python, str) or not requires_python:
        raise ArtifactVerificationError("trusted pyproject has invalid requires-python")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) and item for item in dependencies
    ):
        raise ArtifactVerificationError("trusted pyproject has invalid dependencies")
    if len(dependencies) != len(set(dependencies)):
        raise ArtifactVerificationError("trusted pyproject has duplicate dependencies")
    return project


def _verify_metadata(
    metadata,
    expected_version: str,
    *,
    artifact: str,
    expected_project: dict | None,
) -> None:
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    if names != ["openopps"]:
        raise ArtifactVerificationError(
            f"{artifact} metadata has the wrong project name"
        )
    if versions != [expected_version]:
        raise ArtifactVerificationError(
            f"{artifact} metadata version {versions!r} "
            f"does not equal {expected_version!r}"
        )
    if expected_project is None:
        return
    requires_python = metadata.get_all("Requires-Python", [])
    expected_requires_python = [expected_project["requires-python"]]
    if requires_python != expected_requires_python:
        raise ArtifactVerificationError(
            f"{artifact} metadata Requires-Python {requires_python!r} "
            f"does not equal trusted source {expected_requires_python!r}"
        )
    requires_dist = metadata.get_all("Requires-Dist", [])
    expected_requires_dist = expected_project["dependencies"]
    if sorted(requires_dist) != sorted(expected_requires_dist):
        raise ArtifactVerificationError(
            f"{artifact} metadata Requires-Dist does not equal trusted source: "
            f"actual={sorted(requires_dist)!r} "
            f"expected={sorted(expected_requires_dist)!r}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    expected_version = project_version(args.project_root)
    expected_pyproject = (args.project_root / "pyproject.toml").read_bytes()
    verify_release_artifacts(
        args.dist_dir,
        expected_version,
        expected_pyproject=expected_pyproject,
    )
    print(
        f"release-artifact-readback ok version={expected_version} dir={args.dist_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
