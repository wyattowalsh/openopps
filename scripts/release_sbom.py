#!/usr/bin/env python3
"""Prepare and verify artifact-specific SPDX input for the release workflow."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any
import zipfile

from verify_release_artifacts import (
    ArtifactVerificationError,
    project_version,
    verify_release_artifacts,
)


MANIFEST_SCHEMA_VERSION = 1
EXPECTED_PROJECT_NAME = "openopps"
EXPECTED_SYFT_CREATOR = "Tool: syft-1.51.1"
WORK_DIR_MANIFEST = "manifest.json"
SDIST_METADATA_DIR = ".openopps-sbom"


class ReleaseSbomError(RuntimeError):
    """Raised when semantic SBOM preparation or readback fails closed."""


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_file: str
    artifact_sha256: str
    kind: str
    scan_root: str
    sbom_file: str
    source_name: str
    source_version: str


@dataclass(frozen=True)
class ArchiveTree:
    files: dict[str, bytes]
    directories: frozenset[str]


def prepare_release_sbom_inputs(
    dist_dir: Path,
    work_dir: Path,
    project_root: Path,
    *,
    github_output: Path | None = None,
) -> dict[str, ArtifactIdentity]:
    """Verify the release pair and create fresh, safe Syft scan roots."""
    version = _verify_release_pair(dist_dir, project_root)
    _require_separate_fresh_work_dir(dist_dir, work_dir)
    work_dir.mkdir(mode=0o700)

    identities: dict[str, ArtifactIdentity] = {}
    for kind, artifact in _expected_artifacts(dist_dir, version).items():
        scan_root = work_dir / kind / "root"
        scan_root.mkdir(parents=True)
        tree = _archive_tree(artifact, kind=kind, version=version)
        _write_archive_tree(scan_root, tree)
        identity = _artifact_identity(
            artifact,
            kind=kind,
            work_dir=work_dir,
            scan_root=scan_root,
        )
        identities[kind] = identity

    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "project": EXPECTED_PROJECT_NAME,
        "version": version,
        "artifacts": {kind: asdict(identity) for kind, identity in identities.items()},
    }
    (work_dir / WORK_DIR_MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if github_output is not None:
        _write_github_outputs(github_output, identities, work_dir=work_dir)
    return identities


def verify_release_sboms(
    dist_dir: Path,
    work_dir: Path,
    project_root: Path,
) -> None:
    """Verify scan-root identity and artifact-specific SPDX semantics."""
    version = _verify_release_pair(dist_dir, project_root)
    expected_artifacts = _expected_artifacts(dist_dir, version)
    expected_identities = {
        kind: _artifact_identity(
            artifact,
            kind=kind,
            work_dir=work_dir,
            scan_root=work_dir / kind / "root",
        )
        for kind, artifact in expected_artifacts.items()
    }
    manifest = _load_manifest(work_dir / WORK_DIR_MANIFEST)
    expected_manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "project": EXPECTED_PROJECT_NAME,
        "version": version,
        "artifacts": {
            kind: asdict(identity) for kind, identity in expected_identities.items()
        },
    }
    if manifest != expected_manifest:
        raise ReleaseSbomError("SBOM preparation manifest does not match the release pair")

    for kind, artifact in expected_artifacts.items():
        identity = expected_identities[kind]
        scan_root = work_dir / identity.scan_root
        expected_tree = _archive_tree(artifact, kind=kind, version=version)
        _verify_scan_tree(scan_root, expected_tree)
        _verify_spdx_document(
            work_dir / identity.sbom_file,
            identity=identity,
            version=version,
        )


def _expected_artifacts(dist_dir: Path, version: str) -> dict[str, Path]:
    return {
        "wheel": dist_dir / f"openopps-{version}-py3-none-any.whl",
        "sdist": dist_dir / f"openopps-{version}.tar.gz",
    }


def _verify_release_pair(dist_dir: Path, project_root: Path) -> str:
    try:
        version = project_version(project_root)
        expected_pyproject = (project_root / "pyproject.toml").read_bytes()
        verify_release_artifacts(
            dist_dir,
            version,
            expected_pyproject=expected_pyproject,
        )
    except (ArtifactVerificationError, OSError) as exc:
        raise ReleaseSbomError(f"release artifact verification failed: {exc}") from exc
    return version


def _require_separate_fresh_work_dir(dist_dir: Path, work_dir: Path) -> None:
    if work_dir.exists() or work_dir.is_symlink():
        raise ReleaseSbomError(f"SBOM work directory must not already exist: {work_dir}")
    resolved_dist = dist_dir.resolve()
    resolved_work = work_dir.resolve()
    if resolved_work == resolved_dist:
        raise ReleaseSbomError("SBOM work directory must be separate from dist")
    if resolved_work.is_relative_to(resolved_dist):
        raise ReleaseSbomError("SBOM work directory must not be inside dist")
    if resolved_dist.is_relative_to(resolved_work):
        raise ReleaseSbomError("SBOM work directory must not contain dist")


def _artifact_identity(
    artifact: Path,
    *,
    kind: str,
    work_dir: Path,
    scan_root: Path,
) -> ArtifactIdentity:
    digest = _sha256_file(artifact)
    return ArtifactIdentity(
        artifact_file=artifact.as_posix(),
        artifact_sha256=digest,
        kind=kind,
        scan_root=scan_root.relative_to(work_dir).as_posix(),
        sbom_file=f"{kind}.spdx.json",
        source_name=artifact.name,
        source_version=f"sha256:{digest}",
    )


def _archive_tree(artifact: Path, *, kind: str, version: str) -> ArchiveTree:
    if kind == "wheel":
        return _wheel_tree(artifact)
    if kind == "sdist":
        tree = _sdist_tree(artifact)
        metadata_source = f"openopps-{version}/PKG-INFO"
        try:
            metadata = tree.files[metadata_source]
        except KeyError as exc:
            raise ReleaseSbomError("sdist is missing PKG-INFO for Syft metadata") from exc
        metadata_path = (
            f"{SDIST_METADATA_DIR}/openopps-{version}.dist-info/METADATA"
        )
        files = dict(tree.files)
        files[metadata_path] = metadata
        directories = set(tree.directories)
        _add_parent_directories(PurePosixPath(metadata_path), directories)
        return ArchiveTree(files=files, directories=frozenset(directories))
    raise ReleaseSbomError(f"unsupported release artifact kind: {kind!r}")


def _wheel_tree(artifact: Path) -> ArchiveTree:
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    try:
        with zipfile.ZipFile(artifact) as archive:
            seen: set[str] = set()
            for member in archive.infolist():
                relative = _safe_member_path(member.filename)
                normalized = relative.as_posix()
                if normalized in seen:
                    raise ReleaseSbomError(
                        f"wheel contains duplicate member: {member.filename!r}"
                    )
                seen.add(normalized)
                unix_mode = member.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if member.is_dir():
                    if member.file_size != 0 or file_type not in (0, stat.S_IFDIR):
                        raise ReleaseSbomError(
                            f"wheel contains invalid directory: {member.filename!r}"
                        )
                    directories.add(normalized)
                    _add_parent_directories(relative, directories)
                    continue
                if file_type not in (0, stat.S_IFREG):
                    raise ReleaseSbomError(
                        f"wheel contains a link or special member: {member.filename!r}"
                    )
                files[normalized] = archive.read(member)
                _add_parent_directories(relative, directories)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseSbomError(f"cannot read wheel {artifact}: {exc}") from exc
    return ArchiveTree(files=files, directories=frozenset(directories))


def _sdist_tree(artifact: Path) -> ArchiveTree:
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    try:
        with tarfile.open(artifact, mode="r:gz") as archive:
            seen: set[str] = set()
            for member in archive.getmembers():
                relative = _safe_member_path(member.name)
                normalized = relative.as_posix()
                if normalized in seen:
                    raise ReleaseSbomError(
                        f"sdist contains duplicate member: {member.name!r}"
                    )
                seen.add(normalized)
                if member.isdir():
                    if member.size != 0:
                        raise ReleaseSbomError(
                            f"sdist contains non-empty directory: {member.name!r}"
                        )
                    directories.add(normalized)
                    _add_parent_directories(relative, directories)
                    continue
                if not member.isfile():
                    raise ReleaseSbomError(
                        f"sdist contains a link or special member: {member.name!r}"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ReleaseSbomError(
                        f"cannot read sdist member: {member.name!r}"
                    )
                files[normalized] = extracted.read()
                _add_parent_directories(relative, directories)
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseSbomError(f"cannot read sdist {artifact}: {exc}") from exc
    return ArchiveTree(files=files, directories=frozenset(directories))


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise ReleaseSbomError(f"archive has an unsafe member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseSbomError(f"archive has an unsafe member path: {name!r}")
    return path


def _add_parent_directories(path: PurePosixPath, directories: set[str]) -> None:
    for parent in path.parents:
        if parent == PurePosixPath("."):
            break
        directories.add(parent.as_posix())


def _write_archive_tree(root: Path, tree: ArchiveTree) -> None:
    for relative in sorted(tree.directories, key=lambda value: (value.count("/"), value)):
        (root / relative).mkdir(exist_ok=True)
    for relative, payload in sorted(tree.files.items()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(payload)


def _verify_scan_tree(root: Path, expected: ArchiveTree) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ReleaseSbomError(f"SBOM scan root is missing or unsafe: {root}")
    actual_files: dict[str, bytes] = {}
    actual_directories: set[str] = set()
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            path = current_path / name
            if path.is_symlink() or not stat.S_ISDIR(path.stat(follow_symlinks=False).st_mode):
                raise ReleaseSbomError(f"SBOM scan root contains an unsafe directory: {path}")
            actual_directories.add(path.relative_to(root).as_posix())
        for name in file_names:
            path = current_path / name
            mode = path.stat(follow_symlinks=False).st_mode
            if path.is_symlink() or not stat.S_ISREG(mode):
                raise ReleaseSbomError(f"SBOM scan root contains an unsafe file: {path}")
            actual_files[path.relative_to(root).as_posix()] = path.read_bytes()
    if actual_directories != set(expected.directories):
        raise ReleaseSbomError("SBOM scan-root directory set does not match the artifact")
    if actual_files != expected.files:
        raise ReleaseSbomError("SBOM scan-root files do not match the artifact")


def _verify_spdx_document(
    sbom_path: Path,
    *,
    identity: ArtifactIdentity,
    version: str,
) -> None:
    payload = _load_json_object(sbom_path, label="SPDX SBOM")
    if payload.get("spdxVersion") != "SPDX-2.3":
        raise ReleaseSbomError(f"{identity.kind} SBOM is not SPDX 2.3 JSON")
    if payload.get("dataLicense") != "CC0-1.0":
        raise ReleaseSbomError(f"{identity.kind} SBOM has the wrong data license")
    if payload.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise ReleaseSbomError(f"{identity.kind} SBOM has the wrong document SPDXID")
    if payload.get("name") != identity.source_name:
        raise ReleaseSbomError(f"{identity.kind} SBOM has the wrong document name")
    creation_info = payload.get("creationInfo")
    if not isinstance(creation_info, dict):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid creation info")
    creators = creation_info.get("creators")
    if not isinstance(creators, list) or EXPECTED_SYFT_CREATOR not in creators:
        raise ReleaseSbomError(f"{identity.kind} SBOM was not generated by Syft 1.51.1")

    packages = payload.get("packages")
    relationships = payload.get("relationships")
    if not isinstance(packages, list) or not all(
        isinstance(package, dict) for package in packages
    ):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid packages")
    if not isinstance(relationships, list) or not all(
        isinstance(relationship, dict) for relationship in relationships
    ):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid relationships")
    package_ids = [package.get("SPDXID") for package in packages]
    if not all(isinstance(package_id, str) and package_id for package_id in package_ids):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid package SPDXIDs")
    if len(package_ids) != len(set(package_ids)):
        raise ReleaseSbomError(f"{identity.kind} SBOM has duplicate package SPDXIDs")
    if not all(
        isinstance(relationship.get(field), str) and relationship.get(field)
        for relationship in relationships
        for field in ("spdxElementId", "relatedSpdxElement", "relationshipType")
    ):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid relationship fields")

    describes = [
        relationship
        for relationship in relationships
        if relationship.get("relationshipType") == "DESCRIBES"
    ]
    if len(describes) != 1 or describes[0].get("spdxElementId") != "SPDXRef-DOCUMENT":
        raise ReleaseSbomError(
            f"{identity.kind} SBOM must describe exactly one artifact root"
        )
    root_id = describes[0].get("relatedSpdxElement")
    roots = [package for package in packages if package.get("SPDXID") == root_id]
    if len(roots) != 1:
        raise ReleaseSbomError(f"{identity.kind} SBOM artifact root is missing")
    root = roots[0]
    if root.get("name") != identity.source_name:
        raise ReleaseSbomError(f"{identity.kind} SBOM root has the wrong artifact name")
    if root.get("versionInfo") != identity.source_version:
        raise ReleaseSbomError(f"{identity.kind} SBOM root has the wrong artifact digest")
    if root.get("filesAnalyzed") is not False:
        raise ReleaseSbomError(f"{identity.kind} SBOM root has unexpected file semantics")

    project_packages = [
        package for package in packages if package.get("name") == EXPECTED_PROJECT_NAME
    ]
    if len(project_packages) != 1:
        raise ReleaseSbomError(
            f"{identity.kind} SBOM must contain exactly one OpenOpps package"
        )
    project_package = project_packages[0]
    if project_package.get("versionInfo") != version:
        raise ReleaseSbomError(f"{identity.kind} SBOM has the wrong OpenOpps version")
    project_id = project_package.get("SPDXID")
    contains_project = [
        relationship
        for relationship in relationships
        if relationship.get("spdxElementId") == root_id
        and relationship.get("relationshipType") == "CONTAINS"
        and relationship.get("relatedSpdxElement") == project_id
    ]
    if not isinstance(project_id, str) or len(contains_project) != 1:
        raise ReleaseSbomError(
            f"{identity.kind} SBOM artifact root does not contain OpenOpps"
        )
    external_refs = project_package.get("externalRefs")
    if not isinstance(external_refs, list) or not all(
        isinstance(reference, dict) for reference in external_refs
    ):
        raise ReleaseSbomError(f"{identity.kind} SBOM has invalid OpenOpps references")
    purls = [
        reference.get("referenceLocator")
        for reference in external_refs
        if reference.get("referenceCategory") == "PACKAGE-MANAGER"
        and reference.get("referenceType") == "purl"
    ]
    if purls != [f"pkg:pypi/openopps@{version}"]:
        raise ReleaseSbomError(f"{identity.kind} SBOM has the wrong OpenOpps purl")
    expected_files_analyzed = identity.kind == "wheel"
    if project_package.get("filesAnalyzed") is not expected_files_analyzed:
        raise ReleaseSbomError(
            f"{identity.kind} SBOM has the wrong OpenOpps file-analysis semantics"
        )
    expected_source_info = _expected_source_info(identity.kind, version)
    if project_package.get("sourceInfo") != expected_source_info:
        raise ReleaseSbomError(
            f"{identity.kind} SBOM did not acquire OpenOpps from expected metadata"
        )


def _expected_source_info(kind: str, version: str) -> str:
    if kind == "wheel":
        return (
            "acquired package info from installed python package manifest file: "
            f"/openopps-{version}.dist-info/METADATA, "
            f"/openopps-{version}.dist-info/RECORD"
        )
    return (
        "acquired package info from installed python package manifest file: "
        f"/{SDIST_METADATA_DIR}/openopps-{version}.dist-info/METADATA"
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    return _load_json_object(path, label="SBOM preparation manifest")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseSbomError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseSbomError(f"{label} must be a JSON object")
    return payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ReleaseSbomError(f"JSON object contains duplicate key: {key!r}")
        payload[key] = value
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseSbomError(f"cannot hash artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _write_github_outputs(
    path: Path,
    identities: dict[str, ArtifactIdentity],
    *,
    work_dir: Path,
) -> None:
    lines: list[str] = []
    for kind, identity in identities.items():
        values = {
            "artifact": identity.artifact_file,
            "scan_root": (work_dir / identity.scan_root).as_posix(),
            "sbom": (work_dir / identity.sbom_file).as_posix(),
            "source_name": identity.source_name,
            "source_version": identity.source_version,
        }
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise ReleaseSbomError("GitHub output values must be single-line")
            lines.append(f"{kind}_{name}={value}")
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        raise ReleaseSbomError(f"cannot write GitHub outputs {path}: {exc}") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dist-dir", type=Path, required=True)
        subparser.add_argument("--work-dir", type=Path, required=True)
        subparser.add_argument("--project-root", type=Path, default=Path.cwd())
        if command == "prepare":
            subparser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "prepare":
        identities = prepare_release_sbom_inputs(
            args.dist_dir,
            args.work_dir,
            args.project_root,
            github_output=args.github_output,
        )
        print(
            "release-sbom-input ok "
            + " ".join(
                f"{kind}=sha256:{identity.artifact_sha256}"
                for kind, identity in identities.items()
            )
        )
        return 0
    verify_release_sboms(args.dist_dir, args.work_dir, args.project_root)
    print("release-sbom-readback ok wheel=semantic sdist=semantic")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseSbomError as exc:
        raise SystemExit(f"release-sbom error: {exc}") from exc
