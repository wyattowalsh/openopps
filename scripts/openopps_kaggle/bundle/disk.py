"""Disk headroom helpers for Kaggle notebook exports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

MIN_FREE_BYTES_FOR_EXPORT = 3 * 1024 * 1024 * 1024
MIN_FREE_BYTES_FOR_SQLITE_MUTATION = 2 * 1024 * 1024 * 1024


def emit_disk_usage(label: str, path: Path) -> None:
    usage_path = path if path.exists() else path.parent
    usage = shutil.disk_usage(usage_path)
    print(
        "OpenOpps disk usage:",
        json.dumps(
            {
                "label": label,
                "path": str(usage_path),
                "totalBytes": usage.total,
                "usedBytes": usage.used,
                "freeBytes": usage.free,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def require_disk_headroom(
    label: str,
    *,
    min_free_bytes: int,
    path: Path,
) -> None:
    usage_path = path if path.exists() else path.parent
    usage = shutil.disk_usage(usage_path)
    emit_disk_usage(label, path)
    if usage.free < min_free_bytes:
        raise RuntimeError(
            f"Insufficient disk headroom for {label}: "
            f"free={usage.free} required={min_free_bytes}"
        )
