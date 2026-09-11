from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

import release_sbom as sbom


VERSION = "0.1.1"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _bypass_pair_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sbom, "project_version", lambda _root: VERSION)
    monkeypatch.setattr(
        sbom,
        "verify_release_artifacts",
        lambda *_args, **_kwargs: None,
    )


def _add_tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    archive.addfile(member, io.BytesIO(payload))


def _build_minimal_pair(dist_dir: Path) -> tuple[Path, Path]:
    dist_dir.mkdir()
    wheel = dist_dir / f"openopps-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("openopps/__init__.py", f'__version__ = "{VERSION}"\n')
        archive.writestr(
            f"openopps-{VERSION}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: openopps\nVersion: {VERSION}\n\n",
        )
        archive.writestr(f"openopps-{VERSION}.dist-info/RECORD", "")

    sdist = dist_dir / f"openopps-{VERSION}.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(
            archive,
            f"openopps-{VERSION}/PKG-INFO",
            f"Metadata-Version: 2.4\nName: openopps\nVersion: {VERSION}\n\n".encode(),
        )
        _add_tar_bytes(
            archive,
            f"openopps-{VERSION}/src/openopps/__init__.py",
            f'__version__ = "{VERSION}"\n'.encode(),
        )
    return wheel, sdist


def _prepare(tmp_path: Path) -> tuple[Path, Path, dict[str, sbom.ArtifactIdentity]]:
    dist_dir = tmp_path / "dist"
    _build_minimal_pair(dist_dir)
    work_dir = tmp_path / "release-sbom"
    identities = sbom.prepare_release_sbom_inputs(
        dist_dir,
        work_dir,
        REPO_ROOT,
    )
    return dist_dir, work_dir, identities


def _spdx(identity: sbom.ArtifactIdentity) -> dict:
    root_id = f"SPDXRef-Root-{identity.kind}"
    project_id = f"SPDXRef-Package-openopps-{identity.kind}"
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": identity.source_name,
        "creationInfo": {
            "creators": ["Organization: Anchore, Inc", sbom.EXPECTED_SYFT_CREATOR]
        },
        "packages": [
            {
                "name": "openopps",
                "SPDXID": project_id,
                "versionInfo": VERSION,
                "filesAnalyzed": identity.kind == "wheel",
                "sourceInfo": sbom._expected_source_info(identity.kind, VERSION),
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/openopps@{VERSION}",
                    }
                ],
            },
            {
                "name": identity.source_name,
                "SPDXID": root_id,
                "versionInfo": identity.source_version,
                "filesAnalyzed": False,
            },
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": root_id,
                "relationshipType": "DESCRIBES",
            },
            {
                "spdxElementId": root_id,
                "relatedSpdxElement": project_id,
                "relationshipType": "CONTAINS",
            },
        ],
    }


def _write_sboms(
    work_dir: Path,
    identities: dict[str, sbom.ArtifactIdentity],
) -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for kind, identity in identities.items():
        payload = _spdx(identity)
        payloads[kind] = payload
        (work_dir / identity.sbom_file).write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
    return payloads


def test_prepare_extracts_exact_artifacts_and_mirrors_sdist_metadata(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _wheel, sdist = _build_minimal_pair(dist_dir)
    work_dir = tmp_path / "release-sbom"
    github_output = tmp_path / "github-output"

    identities = sbom.prepare_release_sbom_inputs(
        dist_dir,
        work_dir,
        REPO_ROOT,
        github_output=github_output,
    )

    with tarfile.open(sdist, mode="r:gz") as archive:
        source = archive.extractfile(f"openopps-{VERSION}/PKG-INFO")
        assert source is not None
        source_metadata = source.read()
    mirrored = (
        work_dir
        / "sdist/root"
        / sbom.SDIST_METADATA_DIR
        / f"openopps-{VERSION}.dist-info/METADATA"
    )
    assert mirrored.read_bytes() == source_metadata
    assert (work_dir / "wheel/root/openopps/__init__.py").is_file()
    assert set(identities) == {"wheel", "sdist"}
    outputs = github_output.read_text(encoding="utf-8")
    assert f"wheel_scan_root={work_dir.as_posix()}/wheel/root" in outputs
    assert f"sdist_sbom={work_dir.as_posix()}/sdist.spdx.json" in outputs
    assert "wheel_source_version=sha256:" in outputs


def test_prepare_requires_a_fresh_work_directory(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _build_minimal_pair(dist_dir)
    work_dir = tmp_path / "release-sbom"
    work_dir.mkdir()

    with pytest.raises(sbom.ReleaseSbomError, match="must not already exist"):
        sbom.prepare_release_sbom_inputs(dist_dir, work_dir, REPO_ROOT)


def test_prepare_rejects_unsafe_archive_members(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    wheel, _sdist = _build_minimal_pair(dist_dir)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("../outside", "payload")

    with pytest.raises(sbom.ReleaseSbomError, match="unsafe member path"):
        sbom.prepare_release_sbom_inputs(
            dist_dir,
            tmp_path / "release-sbom",
            REPO_ROOT,
        )


def test_prepare_rejects_sdist_links(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _wheel, sdist = _build_minimal_pair(dist_dir)
    sdist.unlink()
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(
            archive,
            f"openopps-{VERSION}/PKG-INFO",
            f"Metadata-Version: 2.4\nName: openopps\nVersion: {VERSION}\n\n".encode(),
        )
        member = tarfile.TarInfo(f"openopps-{VERSION}/src/openopps/escape")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../../../outside"
        archive.addfile(member)

    with pytest.raises(sbom.ReleaseSbomError, match="link or special member"):
        sbom.prepare_release_sbom_inputs(
            dist_dir,
            tmp_path / "release-sbom",
            REPO_ROOT,
        )


def test_verify_accepts_artifact_tied_semantic_spdx(tmp_path: Path) -> None:
    dist_dir, work_dir, identities = _prepare(tmp_path)
    _write_sboms(work_dir, identities)

    sbom.verify_release_sboms(dist_dir, work_dir, REPO_ROOT)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("document-name", "wrong document name"),
        ("generator-version", "not generated by Syft 1.51.1"),
        ("artifact-digest", "wrong artifact digest"),
        ("project-version", "wrong OpenOpps version"),
        ("project-purl", "wrong OpenOpps purl"),
        ("metadata-origin", "expected metadata"),
        ("missing-root-link", "does not contain OpenOpps"),
        ("duplicate-spdxid", "duplicate package SPDXIDs"),
        ("duplicate-project", "exactly one OpenOpps package"),
    ],
)
def test_verify_rejects_semantic_identity_drift(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    dist_dir, work_dir, identities = _prepare(tmp_path)
    payloads = _write_sboms(work_dir, identities)
    payload = copy.deepcopy(payloads["wheel"])
    project = payload["packages"][0]
    root = payload["packages"][1]
    if mutation == "document-name":
        payload["name"] = "other.whl"
    elif mutation == "generator-version":
        payload["creationInfo"]["creators"][-1] = "Tool: syft-1.51.0"
    elif mutation == "artifact-digest":
        root["versionInfo"] = "sha256:" + "0" * 64
    elif mutation == "project-version":
        project["versionInfo"] = "0.1.0"
    elif mutation == "project-purl":
        project["externalRefs"][0]["referenceLocator"] = "pkg:pypi/other@0.1.1"
    elif mutation == "metadata-origin":
        project["sourceInfo"] = "acquired package info from an unrelated manifest"
    elif mutation == "missing-root-link":
        payload["relationships"] = payload["relationships"][:1]
    elif mutation == "duplicate-spdxid":
        root["SPDXID"] = project["SPDXID"]
    elif mutation == "duplicate-project":
        duplicate = copy.deepcopy(project)
        duplicate["SPDXID"] += "-duplicate"
        payload["packages"].append(duplicate)
    (work_dir / identities["wheel"].sbom_file).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(sbom.ReleaseSbomError, match=message):
        sbom.verify_release_sboms(dist_dir, work_dir, REPO_ROOT)


def test_verify_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    dist_dir, work_dir, identities = _prepare(tmp_path)
    payloads = _write_sboms(work_dir, identities)
    wheel_payload = json.dumps(payloads["wheel"])
    (work_dir / identities["wheel"].sbom_file).write_text(
        '{"spdxVersion":"SPDX-2.3",' + wheel_payload[1:],
        encoding="utf-8",
    )

    with pytest.raises(sbom.ReleaseSbomError, match="duplicate key"):
        sbom.verify_release_sboms(dist_dir, work_dir, REPO_ROOT)


def test_verify_rejects_scan_root_tampering(tmp_path: Path) -> None:
    dist_dir, work_dir, identities = _prepare(tmp_path)
    _write_sboms(work_dir, identities)
    (work_dir / "wheel/root/openopps/__init__.py").write_text(
        '__version__ = "tampered"\n',
        encoding="utf-8",
    )

    with pytest.raises(sbom.ReleaseSbomError, match="files do not match"):
        sbom.verify_release_sboms(dist_dir, work_dir, REPO_ROOT)


def test_verify_rejects_swapped_artifact_sboms(tmp_path: Path) -> None:
    dist_dir, work_dir, identities = _prepare(tmp_path)
    payloads = _write_sboms(work_dir, identities)
    (work_dir / identities["wheel"].sbom_file).write_text(
        json.dumps(payloads["sdist"]),
        encoding="utf-8",
    )

    with pytest.raises(sbom.ReleaseSbomError, match="wrong document name"):
        sbom.verify_release_sboms(dist_dir, work_dir, REPO_ROOT)
