"""Atomic camelCase metrics-file writer for URL-pull terminal observability."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from openopps.pull_models import PullTerminalObservability
from openopps.pull_output import write_atomic_bytes

PULL_METRICS_SCHEMA_VERSION = 1
_MAX_DIAGNOSTIC_CHARS = 500


def pull_metrics_payload(
    observability: PullTerminalObservability | None,
) -> dict[str, object]:
    """Return one camelCase metrics object with a frozen schemaVersion."""

    payload: dict[str, object] = {"schemaVersion": PULL_METRICS_SCHEMA_VERSION}
    if observability is None:
        return payload
    dumped = observability.model_dump(mode="json")
    camelized = _camelize(dumped)
    if isinstance(camelized, dict):
        payload.update(camelized)
    payload["schemaVersion"] = PULL_METRICS_SCHEMA_VERSION
    return payload


def write_pull_metrics_file(
    observability: PullTerminalObservability | None,
    path: Path,
) -> None:
    """Atomically replace ``path`` with compact camelCase pull observability JSON."""

    payload = pull_metrics_payload(observability)
    encoded = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    write_atomic_bytes(Path(path), encoded.encode("utf-8"))


def _camelize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            _to_camel(str(key)): _camelize(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    if isinstance(value, tuple):
        return [_camelize(item) for item in value]
    if isinstance(value, str):
        return _bound_diagnostic(value)
    return value


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _bound_diagnostic(message: str) -> str:
    if len(message) <= _MAX_DIAGNOSTIC_CHARS:
        return message
    return f"{message[: _MAX_DIAGNOSTIC_CHARS - 3]}..."


__all__ = [
    "PULL_METRICS_SCHEMA_VERSION",
    "pull_metrics_payload",
    "write_pull_metrics_file",
]
