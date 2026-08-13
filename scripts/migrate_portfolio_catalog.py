"""Archived portfolio-catalog migration gate.

The source extraction was a one-shot migration and completed with packaged
catalog version 2.  This tombstone is deliberately read-only: it verifies the
exact completed result and refuses every attempt to run the former mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openopps.providers.sources.source_utils import (  # noqa: E402
    portfolio_source_catalog_fingerprint,
)

CATALOG_PATH = (
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "portfolio_source_catalog.json"
)
EXPECTED_VERSION = 2
EXPECTED_COUNT = 2239
EXPECTED_FINGERPRINT = "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
EXPECTED_FILE_SHA256 = "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
COMPLETED_PROGRAM_SHA256 = {
    "scripts/migrate_portfolio_catalog.py": (
        "342ddfaeececa033d3a46f7c70758d8262af3fa2c542b4f35773a9c41ce43ee7"
    ),
    "scripts/run_w_cat_migration.sh": (
        "afea111567f7eb7c8aabafc71f44fdec3cfb0dbb38a209c9dc598733a48400c3"
    ),
}


class ArchivedMigrationError(RuntimeError):
    """Raised when the immutable completed migration result has drifted."""


def verify_archived_migration(catalog_path: Path = CATALOG_PATH) -> dict[str, object]:
    """Verify exact catalog bytes and semantic fingerprint without writing."""

    raw_path = catalog_path.expanduser()
    if raw_path.is_symlink():
        raise ArchivedMigrationError("archived catalog target must not be a symlink")
    path = raw_path.resolve()
    if not path.is_file():
        raise ArchivedMigrationError(f"archived catalog target is missing: {path}")
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if file_sha256 != EXPECTED_FILE_SHA256:
        raise ArchivedMigrationError(
            "archived catalog file digest mismatch: "
            f"expected={EXPECTED_FILE_SHA256} actual={file_sha256}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchivedMigrationError("archived catalog is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ArchivedMigrationError("archived catalog must be a JSON object")
    if payload.get("version") != EXPECTED_VERSION:
        raise ArchivedMigrationError("archived catalog version fingerprint changed")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ArchivedMigrationError("archived catalog entries must be an array")
    if payload.get("count") != EXPECTED_COUNT or len(entries) != EXPECTED_COUNT:
        raise ArchivedMigrationError("archived catalog count fingerprint changed")
    fingerprint = portfolio_source_catalog_fingerprint(entries)
    if payload.get("fingerprint") != fingerprint:
        raise ArchivedMigrationError("archived catalog self-fingerprint is invalid")
    if fingerprint != EXPECTED_FINGERPRINT:
        raise ArchivedMigrationError(
            "archived catalog semantic fingerprint mismatch: "
            f"expected={EXPECTED_FINGERPRINT} actual={fingerprint}"
        )
    return {
        "archived": True,
        "catalogPath": path.relative_to(ROOT).as_posix()
        if path.is_relative_to(ROOT)
        else str(path),
        "version": EXPECTED_VERSION,
        "count": EXPECTED_COUNT,
        "fingerprint": fingerprint,
        "fileSha256": file_sha256,
        "completedProgramSha256": COMPLETED_PROGRAM_SHA256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-archived",
        action="store_true",
        help="verify the immutable completed migration result",
    )
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)
    if not args.verify_archived:
        parser.error(
            "portfolio catalog migration is archived; only --verify-archived is allowed"
        )
    try:
        result = verify_archived_migration(args.catalog)
    except ArchivedMigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
