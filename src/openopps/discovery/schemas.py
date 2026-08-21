"""Canonical generated JSON Schemas for strict discovery models."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Final, Mapping

import pydantic

from openopps.discovery import models
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.models import StrictDiscoveryModel


SCHEMA_SET_VERSION: Final = "openopps.discovery.schemas.v1"
SCHEMA_MANIFEST_NAME: Final = "manifest.json"
DEFAULT_SCHEMA_ROOT: Final = Path(__file__).with_name("data")


class DiscoverySchemaError(ValueError):
    """Raised when generated discovery schemas are missing or stale."""


@dataclass(frozen=True, slots=True)
class SchemaCheckResult:
    """Exact comparison between source-derived and committed schema bytes."""

    missing: tuple[str, ...]
    changed: tuple[str, ...]
    extra: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.changed or self.extra)

    def as_dict(self) -> dict[str, object]:
        return {
            "changed": list(self.changed),
            "extra": list(self.extra),
            "missing": list(self.missing),
            "ok": self.ok,
        }


def discovery_schema_models() -> Mapping[str, type[StrictDiscoveryModel]]:
    """Return every concrete strict model declared in the discovery model module."""

    discovered: dict[str, type[StrictDiscoveryModel]] = {}
    for name, candidate in vars(models).items():
        if (
            isinstance(candidate, type)
            and candidate is not StrictDiscoveryModel
            and issubclass(candidate, StrictDiscoveryModel)
            and candidate.__module__ == models.__name__
        ):
            discovered[name] = candidate
    if not discovered:
        raise DiscoverySchemaError("no strict discovery models were found")
    return MappingProxyType(dict(sorted(discovered.items())))


def schema_file_name(model_name: str) -> str:
    """Convert one model class name to a stable lower-kebab schema filename."""

    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", model_name)
    kebab = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", first).lower()
    if re.fullmatch(r"[a-z][a-z0-9-]*", kebab) is None:
        raise DiscoverySchemaError("model name cannot form a safe schema path")
    return f"{kebab}.schema.json"


def _render_model_schema(
    model_name: str, model_type: type[StrictDiscoveryModel]
) -> bytes:
    schema = model_type.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    schema["$id"] = f"urn:openopps:discovery:schema:{model_name}"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return canonical_json_bytes(schema)


def render_discovery_schema_files() -> Mapping[str, bytes]:
    """Render the complete deterministic schema tree directly from model source."""

    rendered: dict[str, bytes] = {}
    manifest_rows: list[dict[str, object]] = []
    for model_name, model_type in discovery_schema_models().items():
        path = schema_file_name(model_name)
        if path in rendered:
            raise DiscoverySchemaError("model names collide on one schema path")
        content = _render_model_schema(model_name, model_type)
        rendered[path] = content
        manifest_rows.append(
            {
                "model": model_name,
                "path": path,
                "sha256": sha256(content).hexdigest(),
                "sizeBytes": len(content),
            }
        )
    manifest = {
        "generator": {
            "modelModule": "openopps.discovery.models",
            "pydanticVersion": pydantic.__version__,
        },
        "modelCount": len(manifest_rows),
        "schemaSetSha256": sha256(canonical_json_bytes(manifest_rows)).hexdigest(),
        "schemaVersion": SCHEMA_SET_VERSION,
        "schemas": manifest_rows,
    }
    rendered[SCHEMA_MANIFEST_NAME] = canonical_json_bytes(manifest)
    return MappingProxyType(dict(sorted(rendered.items())))


def check_discovery_schema_files(
    schema_root: Path = DEFAULT_SCHEMA_ROOT,
) -> SchemaCheckResult:
    """Compare committed files byte-for-byte with current source-derived schemas."""

    expected = render_discovery_schema_files()
    if schema_root.is_symlink():
        raise DiscoverySchemaError("schema root must not be a symlink")
    if schema_root.is_dir() and any(
        path.is_symlink() for path in schema_root.iterdir()
    ):
        raise DiscoverySchemaError("schema tree must not contain symlinks")
    actual_names = (
        {
            path.name
            for path in schema_root.iterdir()
            if path.is_file()
            and (
                path.name == SCHEMA_MANIFEST_NAME or path.name.endswith(".schema.json")
            )
        }
        if schema_root.is_dir()
        else set()
    )
    expected_names = set(expected)
    missing = tuple(sorted(expected_names - actual_names))
    extra = tuple(sorted(actual_names - expected_names))
    changed = tuple(
        name
        for name in sorted(expected_names & actual_names)
        if schema_root.joinpath(name).read_bytes() != expected[name]
    )
    return SchemaCheckResult(missing=missing, changed=changed, extra=extra)


def validate_discovery_schema_files(
    schema_root: Path = DEFAULT_SCHEMA_ROOT,
) -> None:
    """Fail when committed schemas differ by even one byte from model output."""

    result = check_discovery_schema_files(schema_root)
    if not result.ok:
        raise DiscoverySchemaError(
            "generated discovery schemas differ from model source: "
            f"missing={list(result.missing)!r}, "
            f"changed={list(result.changed)!r}, extra={list(result.extra)!r}"
        )


def _write_atomic(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_discovery_schema_files(
    schema_root: Path = DEFAULT_SCHEMA_ROOT,
) -> SchemaCheckResult:
    """Write the exact generated schema set; intended for the repository script."""

    expected = render_discovery_schema_files()
    if schema_root.is_symlink():
        raise DiscoverySchemaError("schema root must not be a symlink")
    schema_root.mkdir(parents=True, exist_ok=True)
    for name, content in expected.items():
        if schema_root.joinpath(name).is_symlink():
            raise DiscoverySchemaError("schema target must not be a symlink")
        _write_atomic(schema_root / name, content)
    for path in schema_root.iterdir():
        if (
            path.is_file()
            and (
                path.name == SCHEMA_MANIFEST_NAME or path.name.endswith(".schema.json")
            )
            and path.name not in expected
        ):
            path.unlink()
    directory_descriptor = os.open(schema_root, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return check_discovery_schema_files(schema_root)
