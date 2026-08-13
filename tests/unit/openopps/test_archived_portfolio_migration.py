from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import runpy

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "migrate_portfolio_catalog.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("archived_catalog_migration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archived_migration_verifies_exact_completed_target() -> None:
    module = _load_module()

    result = module.verify_archived_migration()

    assert result == {
        "archived": True,
        "catalogPath": (
            "src/openopps/providers/sources/data/portfolio_source_catalog.json"
        ),
        "version": 2,
        "count": 2239,
        "fingerprint": (
            "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
        ),
        "fileSha256": (
            "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
        ),
        "completedProgramSha256": {
            "scripts/migrate_portfolio_catalog.py": (
                "342ddfaeececa033d3a46f7c70758d8262af3fa2c542b4f35773a9c41ce43ee7"
            ),
            "scripts/run_w_cat_migration.sh": (
                "afea111567f7eb7c8aabafc71f44fdec3cfb0dbb38a209c9dc598733a48400c3"
            ),
        },
    }


def test_archived_migration_rejects_missing_target(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.ArchivedMigrationError, match="missing"):
        module.verify_archived_migration(tmp_path / "missing.json")


def test_archived_migration_rejects_symlink_target(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "catalog.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "catalog-link.json"
    link.symlink_to(target)

    with pytest.raises(module.ArchivedMigrationError, match="must not be a symlink"):
        module.verify_archived_migration(link)


def test_archived_migration_rejects_semantic_tamper(tmp_path: Path) -> None:
    module = _load_module()
    source = json.loads(module.CATALOG_PATH.read_text(encoding="utf-8"))
    source["entries"][0]["url"] = "https://tampered.example/"
    target = tmp_path / "catalog.json"
    target.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(module.ArchivedMigrationError, match="file digest"):
        module.verify_archived_migration(target)


def test_archived_migration_rejects_byte_tamper_with_same_json(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "catalog.json"
    target.write_bytes(module.CATALOG_PATH.read_bytes() + b"\n")

    with pytest.raises(module.ArchivedMigrationError, match="file digest"):
        module.verify_archived_migration(target)


def test_archived_migration_script_contains_no_former_writes() -> None:
    namespace = runpy.run_path(str(SCRIPT), run_name="archived_catalog_migration")
    source = SCRIPT.read_text(encoding="utf-8")

    assert "source_record_to_catalog_entry" not in source
    assert "OUTPUT.write_text" not in source
    assert "special._PORTFOLIO_INLINE_SOURCE_RECORDS" not in source
    assert "verify_archived_migration" in namespace


def test_legacy_shell_entrypoint_is_a_verifier_tombstone() -> None:
    source = (REPO_ROOT / "scripts" / "run_w_cat_migration.sh").read_text(
        encoding="utf-8"
    )

    assert "--verify-archived" in source
    assert "finalize_portfolio_catalog.py" not in source
    assert "migrate_portfolio_catalog.py --verify-archived" in source
