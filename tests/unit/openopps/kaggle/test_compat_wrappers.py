from __future__ import annotations

import runpy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_legacy_generate_kaggle_metadata_wrapper_delegates_to_package() -> None:
    namespace = runpy.run_path(str(REPO_ROOT / "scripts" / "generate_kaggle_metadata.py"))

    assert namespace["main"].__module__ == "openopps_kaggle.cli"


def test_legacy_notebook_pullback_wrapper_delegates_to_package() -> None:
    namespace = runpy.run_path(
        str(REPO_ROOT / "scripts" / "verify_kaggle_notebook_pullback.py")
    )

    assert namespace["main"].__module__ == "openopps_kaggle.verify_notebooks"


def test_legacy_kagglehub_readback_wrapper_delegates_to_package() -> None:
    namespace = runpy.run_path(str(REPO_ROOT / "scripts" / "verify_kagglehub_readback.py"))

    assert namespace["main"].__module__ == "openopps_kaggle.verify_readback"
