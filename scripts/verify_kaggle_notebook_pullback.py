"""Compatibility wrapper for pulled Kaggle notebook verification."""

from __future__ import annotations

import sys

from openopps_kaggle.verify_notebooks import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
