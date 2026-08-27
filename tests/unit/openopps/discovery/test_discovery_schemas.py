"""Unit coverage for generated discovery schema check, validate, and write."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from openopps.discovery.canonical import decode_canonical_json
from openopps.discovery.models import StrictDiscoveryModel
from openopps.discovery.schemas import (
    DEFAULT_SCHEMA_ROOT,
    SCHEMA_MANIFEST_NAME,
    SCHEMA_SET_VERSION,
    DiscoverySchemaError,
    SchemaCheckResult,
    check_discovery_schema_files,
    discovery_schema_models,
    render_discovery_schema_files,
    schema_file_name,
    validate_discovery_schema_files,
    write_discovery_schema_files,
)


def test_schema_check_result_ok_and_as_dict() -> None:
    current = SchemaCheckResult(missing=(), changed=(), extra=())

    assert current.ok
    assert current.as_dict() == {
        "changed": [],
        "extra": [],
        "missing": [],
        "ok": True,
    }

    stale = SchemaCheckResult(
        missing=(SCHEMA_MANIFEST_NAME,),
        changed=("channel-budget.schema.json",),
        extra=("obsolete.schema.json",),
    )

    assert not stale.ok
    assert stale.as_dict() == {
        "changed": ["channel-budget.schema.json"],
        "extra": ["obsolete.schema.json"],
        "missing": [SCHEMA_MANIFEST_NAME],
        "ok": False,
    }


def test_discovery_schema_models_and_schema_file_name() -> None:
    registry = discovery_schema_models()

    assert isinstance(registry, MappingProxyType)
    assert registry
    assert list(registry) == sorted(registry)
    assert all(
        isinstance(model_type, type)
        and model_type is not StrictDiscoveryModel
        and issubclass(model_type, StrictDiscoveryModel)
        for model_type in registry.values()
    )
    assert schema_file_name("ChannelBudget") == "channel-budget.schema.json"
    assert (
        schema_file_name("DiscoveryPromotionPolicyDecision")
        == "discovery-promotion-policy-decision.schema.json"
    )
    paths = [schema_file_name(name) for name in registry]
    assert len(paths) == len(set(paths))
    assert all(path.endswith(".schema.json") for path in paths)


def test_render_discovery_schema_files_includes_manifest() -> None:
    registry = discovery_schema_models()
    rendered = render_discovery_schema_files()

    assert isinstance(rendered, MappingProxyType)
    assert SCHEMA_MANIFEST_NAME in rendered
    assert set(rendered) == {schema_file_name(name) for name in registry} | {
        SCHEMA_MANIFEST_NAME
    }
    assert list(rendered) == sorted(rendered)
    manifest = decode_canonical_json(rendered[SCHEMA_MANIFEST_NAME])
    assert manifest["schemaVersion"] == SCHEMA_SET_VERSION
    assert manifest["modelCount"] == len(registry)
    assert [row["model"] for row in manifest["schemas"]] == list(registry)


def test_check_discovery_schema_files_ok_on_committed_tree() -> None:
    result = check_discovery_schema_files()

    assert result.ok
    assert check_discovery_schema_files(DEFAULT_SCHEMA_ROOT).ok
    assert result.as_dict() == {
        "changed": [],
        "extra": [],
        "missing": [],
        "ok": True,
    }


def test_check_discovery_schema_files_reports_missing_on_empty_directory(
    tmp_path: Path,
) -> None:
    schema_root = tmp_path / "empty"
    schema_root.mkdir()
    expected = set(render_discovery_schema_files())

    result = check_discovery_schema_files(schema_root)

    assert not result.ok
    assert result.missing == tuple(sorted(expected))
    assert SCHEMA_MANIFEST_NAME in result.missing
    assert result.changed == ()
    assert result.extra == ()
    assert result.as_dict()["missing"] == list(result.missing)


def test_check_discovery_schema_files_rejects_symlink_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(DiscoverySchemaError, match="schema root must not be a symlink"):
        check_discovery_schema_files(alias)

    assert tuple(real_root.iterdir()) == ()


def test_validate_discovery_schema_files_ok_on_committed_and_raises_when_not_ok(
    tmp_path: Path,
) -> None:
    validate_discovery_schema_files()
    validate_discovery_schema_files(DEFAULT_SCHEMA_ROOT)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(
        DiscoverySchemaError,
        match="generated discovery schemas differ from model source",
    ):
        validate_discovery_schema_files(empty)


def test_write_discovery_schema_files_ok_and_deletes_extra_schema_json(
    tmp_path: Path,
) -> None:
    schema_root = tmp_path / "schemas"
    schema_root.mkdir()
    extra = schema_root / "obsolete.schema.json"
    extra.write_bytes(b"{}\n")
    leftover = schema_root / "notes.txt"
    leftover.write_text("keep", encoding="utf-8")

    result = write_discovery_schema_files(schema_root)

    assert result.ok
    assert not extra.exists()
    assert leftover.read_text(encoding="utf-8") == "keep"
    expected = render_discovery_schema_files()
    assert {path.name for path in schema_root.iterdir() if path.is_file()} == set(
        expected
    ) | {leftover.name}
    for name, content in expected.items():
        assert (schema_root / name).read_bytes() == content
    assert check_discovery_schema_files(schema_root).ok


def test_write_and_check_reject_symlink_targets(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"sentinel")
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(DiscoverySchemaError, match="schema root must not be a symlink"):
        write_discovery_schema_files(linked_root)
    assert tuple(real_root.iterdir()) == ()

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "trap.schema.json").symlink_to(outside)
    with pytest.raises(
        DiscoverySchemaError, match="schema tree must not contain symlinks"
    ):
        check_discovery_schema_files(tree)

    expected_name = next(iter(render_discovery_schema_files()))
    targets = tmp_path / "targets"
    targets.mkdir()
    (targets / expected_name).symlink_to(outside)
    with pytest.raises(DiscoverySchemaError, match="schema target must not be a symlink"):
        write_discovery_schema_files(targets)
    assert outside.read_bytes() == b"sentinel"
    assert (targets / expected_name).is_symlink()
