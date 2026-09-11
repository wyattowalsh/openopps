from __future__ import annotations

import base64
import csv
import hashlib
import io
from pathlib import Path
import stat
import sys
import tarfile
import zipfile

import pytest

import verify_release_artifacts as verifier


VERSION = "0.1.1"


def _metadata(
    version: str = VERSION,
    *,
    name: str = "openopps",
    requires_python: str = ">=3.12",
    requires_dist: tuple[str, ...] = ("click>=8.3",),
) -> bytes:
    headers = (
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"Requires-Python: {requires_python}\n"
    )
    headers += "".join(f"Requires-Dist: {item}\n" for item in requires_dist)
    return f"{headers}\n".encode()


def _pyproject(*, name: str = "openopps", version: str = VERSION) -> bytes:
    return (
        "[project]\n"
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["click>=8.3"]\n'
        "[project.scripts]\n"
        'openopps = "openopps.cli:app"\n'
        "[build-system]\n"
        'requires = ["hatchling==1.32.0"]\n'
        'build-backend = "hatchling.build"\n'
    ).encode()


def _build_wheel(
    dist_dir: Path,
    *,
    package_version: str = VERSION,
    project_metadata: bytes | None = None,
    entry_points: bytes = b"[console_scripts]\nopenopps = openopps.cli:app\n",
    wheel_metadata: bytes = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ),
    record_payload: bytes | None = None,
    omit: set[str] | None = None,
) -> Path:
    omit = omit or set()
    dist_info = f"openopps-{VERSION}.dist-info"
    files = {name: b"{}\n" for name in verifier.REQUIRED_WHEEL_FILES}
    files.update(
        {
            "openopps/__init__.py": (f'__version__ = "{package_version}"\n').encode(),
            "openopps/cli.py": b"def app():\n    return None\n",
            f"{dist_info}/METADATA": (
                project_metadata if project_metadata is not None else _metadata()
            ),
            f"{dist_info}/WHEEL": wheel_metadata,
            f"{dist_info}/entry_points.txt": entry_points,
        }
    )
    files = {name: payload for name, payload in files.items() if name not in omit}
    record_name = f"{dist_info}/RECORD"
    if record_name not in omit:
        if record_payload is None:
            record_payload = _record_for_files(files, record_name)
        files[record_name] = record_payload
    wheel = dist_dir / f"openopps-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(files.items()):
            archive.writestr(name, payload)
    return wheel


def _add_tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    archive.addfile(member, io.BytesIO(payload))


def _build_sdist(
    dist_dir: Path,
    *,
    package_version: str = VERSION,
    omit: set[str] | None = None,
    link_name: str | None = None,
    extra_directory: str | None = None,
    directory_payload: bytes = b"",
    extra_file_name: str | None = None,
    extra_file_payload: bytes = b"payload\n",
    project_metadata: bytes | None = None,
    pyproject: bytes | None = None,
) -> Path:
    omit = omit or set()
    root = f"openopps-{VERSION}"
    relative_files = {name: b"{}\n" for name in verifier.REQUIRED_SDIST_FILES}
    relative_files.update(
        {
            "LICENSE": b"test license\n",
            "PKG-INFO": (
                project_metadata if project_metadata is not None else _metadata()
            ),
            "README.md": b"# OpenOpps\n",
            "examples/examples.py": b"def main():\n    return None\n",
            "pyproject.toml": pyproject if pyproject is not None else _pyproject(),
            "src/openopps/__init__.py": (
                f'__version__ = "{package_version}"\n'
            ).encode(),
            "src/openopps/cli.py": b"def app():\n    return None\n",
        }
    )
    sdist = dist_dir / f"openopps-{VERSION}.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        for relative, payload in sorted(relative_files.items()):
            if relative not in omit:
                _add_tar_bytes(archive, f"{root}/{relative}", payload)
        if link_name is not None:
            member = tarfile.TarInfo(f"{root}/src/openopps/escape")
            member.type = tarfile.SYMTYPE
            member.linkname = link_name
            archive.addfile(member)
        if extra_directory is not None:
            member = tarfile.TarInfo(f"{root}/{extra_directory.rstrip('/')}/")
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            member.size = len(directory_payload)
            archive.addfile(
                member,
                io.BytesIO(directory_payload) if directory_payload else None,
            )
        if extra_file_name is not None:
            _add_tar_bytes(archive, extra_file_name, extra_file_payload)
    return sdist


def _build_pair(dist_dir: Path) -> None:
    _build_wheel(dist_dir)
    _build_sdist(dist_dir)


def _record_for_files(files: dict[str, bytes], record_name: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name, payload in sorted(files.items()):
        if name == record_name:
            continue
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        writer.writerow((name, f"sha256={digest}", str(len(payload))))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def _rewrite_wheel_member(
    wheel: Path,
    name: str,
    payload: bytes,
    *,
    regenerate_record: bool = False,
) -> None:
    with zipfile.ZipFile(wheel, mode="r") as archive:
        files = {member.filename: archive.read(member) for member in archive.infolist()}
    files[name] = payload
    if regenerate_record:
        record_name = f"openopps-{VERSION}.dist-info/RECORD"
        files[record_name] = _record_for_files(files, record_name)
    wheel.unlink()
    with zipfile.ZipFile(wheel, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member_name, member_payload in sorted(files.items()):
            archive.writestr(member_name, member_payload)


def test_required_wheel_files_include_alembic_0005_and_reject_draft_names() -> None:
    alembic_0005 = "openopps/alembic/versions/0005_update_snapshot_ledger.py"
    assert alembic_0005 in verifier.REQUIRED_WHEEL_FILES
    assert f"src/{alembic_0005}" in verifier.REQUIRED_SDIST_FILES
    assert not any(name.endswith(".draft") for name in verifier.REQUIRED_WHEEL_FILES)
    assert not any(
        "0006_" in name for name in verifier.REQUIRED_WHEEL_FILES
    ), "do not require an untracked 0006 revision filename"


def test_release_artifacts_reject_alembic_draft_in_wheel(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr(
            "openopps/alembic/versions/0005_update_snapshot_ledger.py.draft",
            b"draft\n",
        )
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="draft file"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifact_pair_passes_with_uv_control_file(tmp_path: Path) -> None:
    _build_pair(tmp_path)
    (tmp_path / ".gitignore").write_text("*\n", encoding="utf-8")

    verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize(
    ("wheel_omit", "sdist_omit"),
    [
        ({"openopps/cli.py"}, set()),
        ({f"openopps-{VERSION}.dist-info/WHEEL"}, set()),
        ({f"openopps-{VERSION}.dist-info/RECORD"}, set()),
        ({f"openopps-{VERSION}.dist-info/METADATA"}, set()),
        ({f"openopps-{VERSION}.dist-info/entry_points.txt"}, set()),
        (
            {"openopps/discovery/data/approved_ingestion_selector_envelope.json"},
            set(),
        ),
        (
            {"openopps/providers/sources/data/source_policy_evidence.json"},
            set(),
        ),
        (
            {"openopps/alembic/versions/0005_update_snapshot_ledger.py"},
            set(),
        ),
        (set(), {"src/openopps/cli.py"}),
        (
            set(),
            {"src/openopps/discovery/data/approved_ingestion_selector_envelope.json"},
        ),
        (
            set(),
            {"src/openopps/providers/sources/data/source_policy_evidence.json"},
        ),
        (
            set(),
            {"src/openopps/alembic/versions/0005_update_snapshot_ledger.py"},
        ),
    ],
)
def test_release_artifacts_require_runnable_package_files(
    tmp_path: Path, wheel_omit: set[str], sdist_omit: set[str]
) -> None:
    _build_wheel(tmp_path, omit=wheel_omit)
    _build_sdist(tmp_path, omit=sdist_omit)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="missing|must contain"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_package_version_drift(tmp_path: Path) -> None:
    _build_wheel(tmp_path, package_version="0.1.0")
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="wheel package version"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_parse_entry_points_instead_of_matching_comments(
    tmp_path: Path,
) -> None:
    _build_wheel(
        tmp_path,
        entry_points=(
            b"# openopps = openopps.cli:app\n"
            b"[console_scripts]\nwrong = openopps.cli:app\n"
        ),
    )
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="console entry points"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_extra_entry_point_groups(tmp_path: Path) -> None:
    _build_wheel(
        tmp_path,
        entry_points=(
            b"[console_scripts]\nopenopps = openopps.cli:app\n"
            b"[pytest11]\nopenopps_ambient = openopps.cli:app\n"
        ),
    )
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="unexpected entry-point"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_default_only_console_entry_point(
    tmp_path: Path,
) -> None:
    _build_wheel(
        tmp_path,
        entry_points=(b"[DEFAULT]\nopenopps = openopps.cli:app\n[console_scripts]\n"),
    )
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="contain defaults"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_sdist_links(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, link_name="../../../../outside")

    with pytest.raises(verifier.ArtifactVerificationError, match="links or special"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_out_of_scope_directories(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("outside-scope/", b"")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="unexpected members"):
        verifier.verify_release_artifacts(tmp_path, VERSION)

    wheel.unlink()
    _build_wheel(tmp_path)
    (tmp_path / f"openopps-{VERSION}.tar.gz").unlink()
    _build_sdist(tmp_path, extra_directory="outside-scope")

    with pytest.raises(verifier.ArtifactVerificationError, match="non-package release"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_slash_named_wheel_symlink(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    link = zipfile.ZipInfo("openopps/link/")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr(link, b"../../outside")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="link or special"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_nonempty_directory_members(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    directory = zipfile.ZipInfo("openopps/payload-dir/")
    directory.create_system = 3
    directory.external_attr = (stat.S_IFDIR | 0o755) << 16
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr(directory, b"payload")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="non-empty directory"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_nonempty_sdist_directory(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(
        tmp_path,
        extra_directory="src/openopps/payload-dir",
        directory_payload=b"payload",
    )

    with pytest.raises(verifier.ArtifactVerificationError, match="non-empty directory"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_wheel_member_budget_counts_directory_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="r") as archive:
        file_count = sum(not member.is_dir() for member in archive.infolist())
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("openopps/header-only/", b"")
    monkeypatch.setattr(verifier, "MAX_ARCHIVE_FILES", file_count)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="too many archive members"
    ):
        verifier._verify_wheel(wheel, VERSION, expected_project=None)


def test_sdist_member_budget_counts_directory_headers_incrementally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = _build_sdist(tmp_path, extra_directory="src/openopps/header-only")
    with tarfile.open(sdist, mode="r:gz") as archive:
        file_count = sum(member.isfile() for member in archive)
    monkeypatch.setattr(verifier, "MAX_ARCHIVE_FILES", file_count)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="too many archive members"
    ):
        verifier._verify_sdist(
            sdist,
            VERSION,
            expected_pyproject=None,
            expected_project=None,
        )


@pytest.mark.parametrize(
    "member_name",
    [
        "openopps/../openopps/cli.py",
        "openopps\\cli.py",
        "openopps//cli.py",
        "openopps/./cli.py",
    ],
)
def test_release_artifacts_reject_noncanonical_wheel_paths(
    tmp_path: Path, member_name: str
) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr(member_name, b"malicious overwrite\n")
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="unsafe archive member"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_casefold_wheel_collisions(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("OpenOpps/cli.py", b"malicious overwrite\n")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="case-colliding"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_unicode_normalization_collisions() -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="case-colliding"):
        verifier._verify_archive_names(
            [
                ("openopps/café.py", False),
                ("openopps/cafe\N{COMBINING ACUTE ACCENT}.py", False),
            ],
            artifact="test",
        )


@pytest.mark.parametrize(
    "members",
    [
        [("openopps/data", False), ("openopps/data/payload.py", False)],
        [("openopps/data/payload.py", False), ("openopps/data", False)],
    ],
)
def test_release_artifacts_reject_file_directory_prefix_collisions(
    members: list[tuple[str, bool]],
) -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="file/directory"):
        verifier._verify_archive_names(members, artifact="test")


def test_release_artifacts_reject_normalized_directory_prefix_collisions() -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="case-colliding"):
        verifier._verify_archive_names(
            [
                ("openopps/café/first.py", False),
                ("openopps/cafe\N{COMBINING ACUTE ACCENT}/second.py", False),
            ],
            artifact="test",
        )


@pytest.mark.parametrize(
    "member_name",
    [
        "openopps/CON.py",
        "openopps/CON .cfg",
        "openopps/CONOUT$",
        "openopps/aux",
        "openopps/AUX/file.py",
        "openopps/LPT1.json",
        "openopps/COM¹.py",
        "openopps/payload.",
        "openopps/payload ",
        "openopps/payload./file.py",
        "openopps/payload /file.py",
    ],
)
def test_release_artifacts_reject_windows_ambiguous_paths(member_name: str) -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="unsafe"):
        verifier._canonical_archive_name(member_name, is_directory=False)


@pytest.mark.parametrize(
    "member_name",
    [
        "openopps/data.v1/café.py",
        "openopps/conftest.py",
        "openopps/console.py",
        "openopps/auxiliary.py",
        "openopps/com0.py",
        "openopps/com10.py",
        "openopps/lpt10.py",
        "openopps/name.with.dots",
        "openopps/name with spaces.py",
    ],
)
def test_release_artifacts_allow_unambiguous_portable_paths(member_name: str) -> None:
    assert (
        verifier._canonical_archive_name(member_name, is_directory=False) == member_name
    )


def test_release_artifacts_reject_noncanonical_sdist_paths(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(
        tmp_path,
        extra_file_name=f"openopps-{VERSION}/src/openopps/./cli.py",
    )

    with pytest.raises(
        verifier.ArtifactVerificationError, match="unsafe archive member"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize(
    "wheel_metadata",
    [
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\n",
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: py3-none-any\n",
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: cp312-cp312-macosx_11_0_arm64\n",
    ],
)
def test_release_artifacts_validate_wheel_metadata(
    tmp_path: Path, wheel_metadata: bytes
) -> None:
    _build_wheel(tmp_path, wheel_metadata=wheel_metadata)
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="WHEEL metadata"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_empty_record(tmp_path: Path) -> None:
    _build_wheel(tmp_path, record_payload=b"")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="does not cover"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize("field", ["hash", "size"])
def test_release_artifacts_verify_record_hashes_and_sizes(
    tmp_path: Path, field: str
) -> None:
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel, mode="r") as archive:
        files = {member.filename: archive.read(member) for member in archive.infolist()}
    record_name = f"openopps-{VERSION}.dist-info/RECORD"
    rows = list(csv.reader(io.StringIO(files[record_name].decode("utf-8"))))
    for row in rows:
        if row[0] == "openopps/cli.py":
            row[1 if field == "hash" else 2] = "0"
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    _rewrite_wheel_member(wheel, record_name, output.getvalue().encode("utf-8"))
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match=f"RECORD {field} mismatch"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_oversized_compressed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_pair(tmp_path)
    monkeypatch.setattr(verifier, "MAX_ARTIFACT_BYTES", 1)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="release artifacts exceed"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_enforce_expanded_size_and_member_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        verifier.ArtifactVerificationError, match="too many archive members"
    ):
        verifier._verify_archive_budget(
            [(str(index), 0) for index in range(verifier.MAX_ARCHIVE_FILES + 1)],
            artifact="test",
        )

    monkeypatch.setattr(verifier, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(verifier.ArtifactVerificationError, match="expands beyond"):
        verifier._verify_archive_budget([("payload", 2)], artifact="test")


@pytest.mark.parametrize(
    ("extra_file", "match"),
    [
        (f"openopps-{VERSION}/src/openopps/AGENTS.md", "local-only path"),
        (f"openopps-{VERSION}/src/openopps/migration.draft", "draft file"),
        (f"openopps-{VERSION}/src/openopps/tests/leak.py", "local-only path"),
    ],
)
def test_release_artifacts_reject_local_only_sdist_members(
    tmp_path: Path, extra_file: str, match: str
) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, extra_file_name=extra_file)

    with pytest.raises(verifier.ArtifactVerificationError, match=match):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_duplicate_wheel_members(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, mode="a") as archive:
            archive.writestr("openopps/cli.py", b"malicious overwrite\n")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="duplicate"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_duplicate_sdist_members(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(
        tmp_path,
        extra_file_name=f"openopps-{VERSION}/src/openopps/cli.py",
    )

    with pytest.raises(verifier.ArtifactVerificationError, match="duplicate"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_release_artifacts_reject_bad_project_metadata(
    tmp_path: Path, artifact: str
) -> None:
    if artifact == "wheel":
        _build_wheel(tmp_path, project_metadata=_metadata(version="9.9.9"))
        _build_sdist(tmp_path)
    else:
        _build_wheel(tmp_path)
        _build_sdist(tmp_path, project_metadata=_metadata(version="9.9.9"))

    with pytest.raises(verifier.ArtifactVerificationError, match="metadata version"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_release_artifacts_reject_malformed_archives(
    tmp_path: Path, artifact: str
) -> None:
    _build_pair(tmp_path)
    path = (
        tmp_path / f"openopps-{VERSION}-py3-none-any.whl"
        if artifact == "wheel"
        else tmp_path / f"openopps-{VERSION}.tar.gz"
    )
    path.write_bytes(b"not an archive")

    with pytest.raises(verifier.ArtifactVerificationError, match=f"{artifact} archive"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_invalid_record_rows(tmp_path: Path) -> None:
    _build_wheel(tmp_path, record_payload=b"only,two\n")
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="invalid row"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_hashed_record_self_row(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    record_name = f"openopps-{VERSION}.dist-info/RECORD"
    with zipfile.ZipFile(wheel, mode="r") as archive:
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    for row in rows:
        if row[0] == record_name:
            row[1:] = ["sha256=invalid", "1"]
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    _rewrite_wheel_member(wheel, record_name, output.getvalue().encode("utf-8"))
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="self-row"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_casefold_record_collisions(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    record_name = f"openopps-{VERSION}.dist-info/RECORD"
    with zipfile.ZipFile(wheel, mode="r") as archive:
        record = archive.read(record_name)
    record += b"OpenOpps/cli.py,sha256=invalid,1\n"
    _rewrite_wheel_member(wheel, record_name, record)
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="case-colliding"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_encrypted_and_unsupported_zip_members() -> None:
    encrypted = zipfile.ZipInfo("openopps/secret.py")
    encrypted.flag_bits = 0x1
    with pytest.raises(verifier.ArtifactVerificationError, match="encrypted"):
        verifier._verify_zip_members([encrypted])

    compressed = zipfile.ZipInfo("openopps/odd.py")
    compressed.compress_type = zipfile.ZIP_BZIP2
    with pytest.raises(
        verifier.ArtifactVerificationError, match="unsupported compression"
    ):
        verifier._verify_zip_members([compressed])


def test_release_artifacts_reject_missing_dist_directory(tmp_path: Path) -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="does not exist"):
        verifier.verify_release_artifacts(tmp_path / "missing", VERSION)


def test_release_artifacts_reject_sdist_package_version_drift(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, package_version="0.1.0")

    with pytest.raises(
        verifier.ArtifactVerificationError, match="sdist package version"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_invalid_and_untrusted_sdist_pyproject(
    tmp_path: Path,
) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, pyproject=b"not = [valid")
    with pytest.raises(
        verifier.ArtifactVerificationError, match="pyproject is invalid"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)

    (tmp_path / f"openopps-{VERSION}.tar.gz").unlink()
    embedded = _pyproject()
    _build_sdist(tmp_path, pyproject=embedded)
    with pytest.raises(verifier.ArtifactVerificationError, match="trusted source"):
        verifier.verify_release_artifacts(
            tmp_path,
            VERSION,
            expected_pyproject=embedded + b"\n",
        )


def test_release_artifacts_reject_sdist_member_outside_root(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, extra_file_name="outside/payload.py")

    with pytest.raises(verifier.ArtifactVerificationError, match="member is outside"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_canonical_archive_name_allows_only_directory_trailing_slash() -> None:
    assert (
        verifier._canonical_archive_name("openopps/", is_directory=True) == "openopps"
    )
    with pytest.raises(verifier.ArtifactVerificationError, match="unsafe"):
        verifier._canonical_archive_name("openopps/", is_directory=False)


@pytest.mark.parametrize(
    ("record_payload", "match"),
    [
        (b"\xff", "RECORD is unreadable"),
        (b'"unterminated\n', "RECORD is invalid CSV"),
    ],
)
def test_release_artifacts_reject_unparseable_record(
    tmp_path: Path, record_payload: bytes, match: str
) -> None:
    _build_wheel(tmp_path, record_payload=record_payload)
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match=match):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize(
    ("source", "match"),
    [
        (b"this is not Python !", "version source is invalid"),
        (b"__version__ = dynamic()\n", "string literal"),
        (b"__version__ = ''\n", "non-empty string"),
        (b"pass\n", "exactly one"),
        (b"__version__ = 'a'\n__version__: str = 'b'\n", "exactly one"),
    ],
)
def test_declared_package_version_rejects_invalid_declarations(
    source: bytes, match: str
) -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match=match):
        verifier._declared_package_version(source, artifact="test")


def test_declared_package_version_accepts_annotated_assignment() -> None:
    assert (
        verifier._declared_package_version(
            b"__version__: str = '0.1.1'\n", artifact="test"
        )
        == VERSION
    )


def test_release_artifacts_reject_invalid_entry_point_encoding(tmp_path: Path) -> None:
    _build_wheel(tmp_path, entry_points=b"\xff")
    _build_sdist(tmp_path)

    with pytest.raises(
        verifier.ArtifactVerificationError, match="entry points are invalid"
    ):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"version": "9.9.9"}, "version"),
        ({"scripts": {"wrong": "openopps.cli:app"}}, "project scripts"),
        ({"build-system": {"requires": []}}, "build system"),
    ],
)
def test_pyproject_contract_rejects_release_contract_drift(
    mutation: dict, match: str
) -> None:
    payload = {
        "project": {
            "name": "openopps",
            "version": VERSION,
            "scripts": {"openopps": "openopps.cli:app"},
        },
        "build-system": {
            "requires": ["hatchling==1.32.0"],
            "build-backend": "hatchling.build",
        },
    }
    if "build-system" in mutation:
        payload["build-system"] = mutation["build-system"]
    else:
        payload["project"].update(mutation)

    with pytest.raises(verifier.ArtifactVerificationError, match=match):
        verifier._verify_pyproject_contract(payload, VERSION, artifact="test")


def test_release_artifacts_reject_wrong_metadata_name(tmp_path: Path) -> None:
    _build_wheel(tmp_path, project_metadata=_metadata(name="other"))
    _build_sdist(tmp_path)

    with pytest.raises(verifier.ArtifactVerificationError, match="project name"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        (_metadata(requires_python=">=3.13"), "Requires-Python"),
        (_metadata(requires_dist=("untrusted>=1",)), "Requires-Dist"),
    ],
)
def test_release_artifacts_bind_dependency_metadata_to_trusted_pyproject(
    tmp_path: Path, artifact: str, metadata: bytes, match: str
) -> None:
    if artifact == "wheel":
        wheel = _build_wheel(tmp_path)
        _rewrite_wheel_member(
            wheel,
            f"openopps-{VERSION}.dist-info/METADATA",
            metadata,
            regenerate_record=True,
        )
        _build_sdist(tmp_path)
    else:
        _build_wheel(tmp_path)
        _build_sdist(tmp_path, project_metadata=metadata)

    with pytest.raises(verifier.ArtifactVerificationError, match=match):
        verifier.verify_release_artifacts(
            tmp_path,
            VERSION,
            expected_pyproject=_pyproject(),
        )


def test_project_version_reads_valid_source_and_rejects_source_errors(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "openopps"
    package.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_bytes(_pyproject())
    init = package / "__init__.py"
    init.write_text(f'__version__ = "{VERSION}"\n', encoding="utf-8")
    assert verifier.project_version(tmp_path) == VERSION

    init.unlink()
    with pytest.raises(
        verifier.ArtifactVerificationError, match="source package version"
    ):
        verifier.project_version(tmp_path)


def test_project_version_rejects_missing_or_invalid_pyproject(tmp_path: Path) -> None:
    with pytest.raises(verifier.ArtifactVerificationError, match="cannot read"):
        verifier.project_version(tmp_path)

    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    with pytest.raises(verifier.ArtifactVerificationError, match="no project.version"):
        verifier.project_version(tmp_path)


def test_release_artifact_cli_main_reads_back_valid_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    dist = project / "dist"
    (project / "src" / "openopps").mkdir(parents=True)
    dist.mkdir()
    (project / "pyproject.toml").write_bytes(_pyproject())
    (project / "src" / "openopps" / "__init__.py").write_text(
        f'__version__ = "{VERSION}"\n', encoding="utf-8"
    )
    _build_pair(dist)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "--dist-dir",
            str(dist),
            "--project-root",
            str(project),
        ],
    )

    assert verifier.main() == 0
    assert "release-artifact-readback ok version=0.1.1" in capsys.readouterr().out


def test_release_artifacts_reject_embedded_pyproject_drift(tmp_path: Path) -> None:
    _build_wheel(tmp_path)
    _build_sdist(tmp_path, pyproject=_pyproject(name="different", version="9.9.9"))

    with pytest.raises(verifier.ArtifactVerificationError, match="project name"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_unexpected_dist_entries(tmp_path: Path) -> None:
    _build_pair(tmp_path)
    (tmp_path / "stale").mkdir()

    with pytest.raises(verifier.ArtifactVerificationError, match="invalid=.*stale"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_release_artifacts_reject_modified_uv_control_file(tmp_path: Path) -> None:
    _build_pair(tmp_path)
    (tmp_path / ".gitignore").write_text("*.whl\n", encoding="utf-8")

    with pytest.raises(verifier.ArtifactVerificationError, match="unexpected contents"):
        verifier.verify_release_artifacts(tmp_path, VERSION)


def test_project_and_source_versions_must_match(tmp_path: Path) -> None:
    (tmp_path / "src" / "openopps").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        _pyproject().decode("utf-8"), encoding="utf-8"
    )
    (tmp_path / "src" / "openopps" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )

    with pytest.raises(verifier.ArtifactVerificationError, match="does not equal"):
        verifier.project_version(tmp_path)
