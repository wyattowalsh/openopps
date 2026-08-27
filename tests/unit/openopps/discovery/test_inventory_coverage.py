"""Fail-closed coverage for approved inventory and identity projection."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import stat
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

import openopps.discovery.inventory as inventory
from openopps.discovery.inventory import (
    DEFAULT_DISCOVERY_OWNED_PATHS,
    DEFAULT_SHARED_GENERATED_PATHS,
    DEFAULT_V7_POLICY_PATHS,
    DISCOVERY_OWNED_IDENTITY_NAMES,
    InventoryError,
    V7_POLICY_INPUT_NAMES,
    _read_stable_file,
    build_approved_runtime_catalog_inventory,
    project_repository_identities,
    read_default_repository_projection,
    read_packaged_catalog_bytes,
    read_repository_resources,
    read_wheel_resources,
)


def _semantic_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _entry(
    key: str,
    *,
    provider_id: str = "board_example",
    url: str = "https://example.test/jobs",
    version: object | None = None,
    raw_metadata: object | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "provider_id": provider_id,
        "raw_metadata": {"name": key} if raw_metadata is None else raw_metadata,
        "url": url,
        "version": {"id": "1"} if version is None else version,
    }


def _catalog_bytes(
    entries: list[object],
    *,
    version: object = 2,
    count: object | None = None,
    fingerprint: object | None = None,
    extra: dict[str, object] | None = None,
    omit: frozenset[str] | None = None,
) -> bytes:
    normalized: list[dict[str, object]] = []
    try:
        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError
            normalized.append(
                {
                    "key": entry["key"],
                    "provider_id": entry["provider_id"],
                    "raw_metadata": dict(entry["raw_metadata"]),
                    "url": entry["url"],
                    "version": dict(entry["version"]),
                }
            )
        computed: object = _semantic_hash(normalized)
    except (AttributeError, KeyError, TypeError, ValueError):
        computed = "0" * 64
    payload: dict[str, object] = {
        "count": len(entries) if count is None else count,
        "entries": entries,
        "fingerprint": computed if fingerprint is None else fingerprint,
        "version": version,
    }
    if extra:
        payload.update(extra)
    if omit:
        for field in omit:
            payload.pop(field, None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _source_record(key: str) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        url="https://example.test/jobs",
        provider_id="board_example",
        version={"id": "1"},
        raw_metadata={"name": key},
    )


def _packaged(*keys: str) -> inventory.PackagedCatalogReadback:
    return read_packaged_catalog_bytes(_catalog_bytes([_entry(key) for key in keys]))


def _policy_bytes() -> dict[str, bytes]:
    return {name: f"{name}-bytes".encode() for name in V7_POLICY_INPUT_NAMES}


def _owned_absent() -> dict[str, None]:
    return {name: None for name in DISCOVERY_OWNED_IDENTITY_NAMES}


def _write_relative(root: Path, relative: str, content: bytes) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _seed_identity_repo(root: Path) -> Path:
    for relative in (
        *DEFAULT_V7_POLICY_PATHS.values(),
        *DEFAULT_SHARED_GENERATED_PATHS.values(),
        *DEFAULT_DISCOVERY_OWNED_PATHS.values(),
    ):
        _write_relative(root, relative, f"{relative}-bytes".encode())
    return root


def _make_wheel(
    path: Path,
    members: dict[str, bytes],
    *,
    modes: dict[str, int] | None = None,
) -> Path:
    with ZipFile(path, mode="w") as archive:
        for name, content in members.items():
            info = ZipInfo(name)
            mode = stat.S_IFREG | 0o644
            if modes is not None and name in modes:
                mode = modes[name]
            info.external_attr = mode << 16
            archive.writestr(info, content)
    return path


def test_read_packaged_catalog_bytes_returns_digest_only_readback() -> None:
    entries = [_entry("alpha"), _entry("beta")]
    raw = _catalog_bytes(entries)

    readback = read_packaged_catalog_bytes(raw)

    assert readback.as_dict() == {
        "count": 2,
        "fileSha256": sha256(raw).hexdigest(),
        "fingerprint": _semantic_hash(
            [
                {
                    "key": "alpha",
                    "provider_id": "board_example",
                    "raw_metadata": {"name": "alpha"},
                    "url": "https://example.test/jobs",
                    "version": {"id": "1"},
                },
                {
                    "key": "beta",
                    "provider_id": "board_example",
                    "raw_metadata": {"name": "beta"},
                    "url": "https://example.test/jobs",
                    "version": {"id": "1"},
                },
            ]
        ),
        "sizeBytes": len(raw),
        "version": 2,
    }


def test_read_packaged_catalog_bytes_accepts_empty_key_sorted_catalog() -> None:
    raw = _catalog_bytes([])

    readback = read_packaged_catalog_bytes(raw)

    assert readback.count == 0
    assert readback.fingerprint == _semantic_hash([])


@pytest.mark.parametrize(
    ("raw", "match"),
    (
        pytest.param("{}", "must be bytes", id="not-bytes"),
        pytest.param(b"\xef\xbb\xbf{}", "UTF-8 BOM", id="bom"),
        pytest.param(b"\xff", "strict UTF-8 JSON", id="not-utf8"),
        pytest.param(b"not-json", "strict UTF-8 JSON", id="not-json"),
        pytest.param(b"NaN", "non-finite", id="nan-constant"),
        pytest.param(b"1.5", "floating-point", id="float"),
        pytest.param(
            b'{"count":0,"count":1,"entries":[],"fingerprint":"x","version":2}',
            "duplicate catalog object keys",
            id="duplicate-object-keys",
        ),
        pytest.param(b"[]", "fields do not match", id="list-payload"),
        pytest.param(b"null", "fields do not match", id="null-payload"),
        pytest.param(
            _catalog_bytes([], omit=frozenset({"fingerprint"})),
            "fields do not match",
            id="missing-field",
        ),
        pytest.param(
            _catalog_bytes([], extra={"extra": 1}),
            "fields do not match",
            id="extra-field",
        ),
        pytest.param(_catalog_bytes([], version=1), "version is unsupported", id="old-version"),
        pytest.param(
            _catalog_bytes([], version=True),
            "version is unsupported",
            id="bool-version",
        ),
        pytest.param(_catalog_bytes([], count=-1), "count is invalid", id="negative-count"),
        pytest.param(_catalog_bytes([], count=True), "count is invalid", id="bool-count"),
        pytest.param(
            _catalog_bytes([_entry("alpha")], count=2),
            "close over entries",
            id="count-mismatch",
        ),
        pytest.param(
            _catalog_bytes([], extra={"entries": {"key": "alpha"}}),
            "close over entries",
            id="entries-not-list",
        ),
        pytest.param(
            _catalog_bytes(["alpha"], count=1, fingerprint="x"),
            "entries do not match",
            id="entry-not-object",
        ),
        pytest.param(
            _catalog_bytes([{"key": "alpha"}], count=1, fingerprint="x"),
            "entries do not match",
            id="entry-wrong-fields",
        ),
        pytest.param(
            _catalog_bytes([_entry("")]),
            "non-empty strings",
            id="empty-identity-field",
        ),
        pytest.param(
            _catalog_bytes([_entry("   ")]),
            "non-empty strings",
            id="blank-identity-field",
        ),
        pytest.param(
            _catalog_bytes([_entry("alpha", version="1")]),
            "must be mappings",
            id="version-not-mapping",
        ),
        pytest.param(
            _catalog_bytes([_entry("alpha", raw_metadata=["x"])]),
            "must be mappings",
            id="metadata-not-mapping",
        ),
        pytest.param(
            _catalog_bytes([_entry("alpha"), _entry("alpha")]),
            "not unique",
            id="duplicate-keys",
        ),
        pytest.param(
            _catalog_bytes([_entry("beta"), _entry("alpha")]),
            "key-sorted",
            id="unsorted-keys",
        ),
        pytest.param(
            _catalog_bytes([_entry("alpha")], fingerprint="deadbeef"),
            "fingerprint does not match",
            id="digest-mismatch",
        ),
    ),
)
def test_read_packaged_catalog_bytes_rejects_invalid_payloads(
    raw: object,
    match: str,
) -> None:
    with pytest.raises(InventoryError, match=match):
        read_packaged_catalog_bytes(raw)  # type: ignore[arg-type]


def test_read_packaged_catalog_bytes_rejects_oversized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inventory, "MAX_PACKAGED_CATALOG_BYTES", 4)

    with pytest.raises(InventoryError, match="readback byte limit"):
        read_packaged_catalog_bytes(b"12345")


def test_read_packaged_catalog_bytes_rejects_source_count_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inventory, "MAX_RUNTIME_SOURCE_COUNT", 0)

    with pytest.raises(InventoryError, match="source count limit"):
        read_packaged_catalog_bytes(_catalog_bytes([_entry("alpha")]))


def test_build_approved_runtime_catalog_inventory_is_digest_only() -> None:
    packaged = _packaged("alpha", "beta")
    inventory_readback = build_approved_runtime_catalog_inventory(
        source_records=(_source_record("beta"), _entry("alpha")),
        source_owner_rows=(("beta", "mod.b"), ("alpha", "mod.a")),
        adapter_identity_rows=(
            ("prov_b", "mod.b", "AdapterB"),
            ("prov_a", "mod.a", "AdapterA"),
        ),
        packaged_catalog=packaged,
    )

    payload = inventory_readback.as_dict()
    assert payload["schemaVersion"] == "openopps.discovery.runtime-inventory.v1"
    assert payload["sourceCount"] == payload["uniqueSourceCount"] == 2
    assert payload["adapterCount"] == 2
    assert payload["adapterProviderIds"] == ["prov_a", "prov_b"]
    assert payload["sourceKeysSha256"] == _semantic_hash(["alpha", "beta"])
    assert payload["packagedCatalog"] == packaged.as_dict()


def test_build_approved_runtime_catalog_inventory_rejects_wrong_readback_type() -> None:
    with pytest.raises(InventoryError, match="readback is required"):
        build_approved_runtime_catalog_inventory(
            source_records=(_entry("alpha"),),
            source_owner_rows=(("alpha", "mod.a"),),
            adapter_identity_rows=(("prov", "mod", "Q"),),
            packaged_catalog=_packaged("alpha").as_dict(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("records", "owners", "adapters", "match"),
    (
        pytest.param(
            (),
            (("alpha", "mod.a"),),
            (("prov", "mod", "Q"),),
            "non-empty and unique",
            id="empty-sources",
        ),
        pytest.param(
            (_entry("alpha"), _entry("alpha")),
            (("alpha", "mod.a"),),
            (("prov", "mod", "Q"),),
            "non-empty and unique",
            id="duplicate-sources",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha",),),
            (("prov", "mod", "Q"),),
            "key and module",
            id="owner-wrong-width",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", ""),),
            (("prov", "mod", "Q"),),
            "key and module",
            id="owner-empty-field",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("beta", "mod.a"),),
            (("prov", "mod", "Q"),),
            "incomplete or ambiguous",
            id="owner-key-mismatch",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", "mod.a"), ("alpha", "mod.b")),
            (("prov", "mod", "Q"),),
            "incomplete or ambiguous",
            id="duplicate-owners",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", "mod.a"),),
            (("prov", "mod"),),
            "provider, module, and qualname",
            id="adapter-wrong-width",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", "mod.a"),),
            (("prov", "mod", ""),),
            "provider, module, and qualname",
            id="adapter-empty-field",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", "mod.a"),),
            (),
            "adapter provider IDs must be non-empty and unique",
            id="empty-adapters",
        ),
        pytest.param(
            (_entry("alpha"),),
            (("alpha", "mod.a"),),
            (("prov", "mod.a", "A"), ("prov", "mod.b", "B")),
            "adapter provider IDs must be non-empty and unique",
            id="duplicate-adapters",
        ),
        pytest.param(
            (_entry(""),),
            (("alpha", "mod.a"),),
            (("prov", "mod", "Q"),),
            "non-empty strings",
            id="blank-source-key",
        ),
    ),
)
def test_build_approved_runtime_catalog_inventory_rejects_invalid_rows(
    records: tuple[object, ...],
    owners: tuple[tuple[str, ...], ...],
    adapters: tuple[tuple[str, ...], ...],
    match: str,
) -> None:
    with pytest.raises(InventoryError, match=match):
        build_approved_runtime_catalog_inventory(
            source_records=records,
            source_owner_rows=owners,
            adapter_identity_rows=adapters,
            packaged_catalog=_packaged("alpha"),
        )


def test_build_approved_runtime_catalog_inventory_rejects_count_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packaged = _packaged("alpha")
    monkeypatch.setattr(inventory, "MAX_RUNTIME_SOURCE_COUNT", 0)
    with pytest.raises(InventoryError, match="source inventory exceeds"):
        build_approved_runtime_catalog_inventory(
            source_records=(_entry("alpha"),),
            source_owner_rows=(("alpha", "mod.a"),),
            adapter_identity_rows=(("prov", "mod", "Q"),),
            packaged_catalog=packaged,
        )

    monkeypatch.setattr(inventory, "MAX_RUNTIME_SOURCE_COUNT", 1)
    with pytest.raises(InventoryError, match="ownership exceeds"):
        build_approved_runtime_catalog_inventory(
            source_records=(_entry("alpha"),),
            source_owner_rows=(("alpha", "mod.a"), ("beta", "mod.b")),
            adapter_identity_rows=(("prov", "mod", "Q"),),
            packaged_catalog=packaged,
        )

    monkeypatch.setattr(inventory, "MAX_RUNTIME_ADAPTER_COUNT", 0)
    with pytest.raises(InventoryError, match="adapter inventory exceeds"):
        build_approved_runtime_catalog_inventory(
            source_records=(_entry("alpha"),),
            source_owner_rows=(("alpha", "mod.a"),),
            adapter_identity_rows=(("prov", "mod", "Q"),),
            packaged_catalog=packaged,
        )


def test_project_repository_identities_is_digest_only_and_omits_absent_bytes() -> None:
    projection = project_repository_identities(
        v7_policy_inputs=_policy_bytes(),
        public_selector=None,
        shared_generated_data={"web_openopps_data": b"generated"},
        embedded_wheel_resources={"catalog": b"wheel"},
        discovery_owned=_owned_absent(),
    )
    payload = projection.as_dict()

    assert payload["schemaVersion"] == "openopps.discovery.identity-projection.v1"
    assert payload["publicSelector"] == {
        "name": "public_selector",
        "present": False,
        "sha256": None,
        "sizeBytes": 0,
    }
    assert payload["embeddedWheelResources"][0]["present"] is True
    assert "generated" not in json.dumps(payload)
    assert payload["projectionSha256"] == projection.projection_sha256


def test_project_repository_identities_rejects_missing_v7_policy() -> None:
    present = _policy_bytes()
    present["policy_code"] = None  # type: ignore[assignment]
    with pytest.raises(InventoryError, match="v7 policy input must be present"):
        project_repository_identities(
            v7_policy_inputs=present,
            public_selector=b"selector",
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )


def test_project_repository_identities_rejects_role_and_type_errors() -> None:
    extra_policy = _policy_bytes()
    extra_policy["extra"] = b"x"
    with pytest.raises(InventoryError, match="exact roles"):
        project_repository_identities(
            v7_policy_inputs=extra_policy,
            public_selector=None,
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    owned = _owned_absent()
    owned.pop("ledger")
    with pytest.raises(InventoryError, match="exact roles"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=None,
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=owned,
        )

    with pytest.raises(InventoryError, match="immutable bytes"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector="not-bytes",  # type: ignore[arg-type]
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    with pytest.raises(InventoryError, match="logical identifier"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=None,
            shared_generated_data={"Web-Data": b"x"},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )


def test_project_repository_identities_rejects_count_and_byte_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 0)
    with pytest.raises(InventoryError, match="group exceeds its count limit"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=None,
            shared_generated_data={"web_openopps_data": b"x"},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 6)
    with pytest.raises(InventoryError, match="projection exceeds its resource count"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=None,
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 1_024)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 2)
    with pytest.raises(InventoryError, match="exceeds its byte limit"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=b"abcd",
            shared_generated_data={},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_TOTAL_BYTES", 3)
    with pytest.raises(InventoryError, match="group exceeds its aggregate"):
        project_repository_identities(
            v7_policy_inputs=_policy_bytes(),
            public_selector=None,
            shared_generated_data={"one": b"aa", "two": b"bb"},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )

    tiny_policy = {name: b"xx" for name in V7_POLICY_INPUT_NAMES}
    monkeypatch.setattr(inventory, "MAX_IDENTITY_TOTAL_BYTES", 10)
    with pytest.raises(InventoryError, match="projection exceeds its aggregate"):
        project_repository_identities(
            v7_policy_inputs=tiny_policy,
            public_selector=b"sel",
            shared_generated_data={"web_openopps_data": b"z"},
            embedded_wheel_resources={},
            discovery_owned=_owned_absent(),
        )


def test_read_repository_resources_returns_stable_regular_files(tmp_path: Path) -> None:
    _write_relative(tmp_path, "a/one.txt", b"one")
    _write_relative(tmp_path, "b/two.txt", b"two")

    resources = read_repository_resources(
        tmp_path,
        {"two": "b/two.txt", "one": "a/one.txt"},
    )

    assert resources == {"one": b"one", "two": b"two"}


def test_read_repository_resources_rejects_non_directory_root(tmp_path: Path) -> None:
    root = tmp_path / "file-root"
    root.write_bytes(b"x")

    with pytest.raises(InventoryError, match="must be a directory"):
        read_repository_resources(root, {"item": "file-root"})


@pytest.mark.parametrize(
    ("name", "relative", "match"),
    (
        pytest.param("BadName", "file.txt", "logical identifier", id="invalid-name"),
        pytest.param("1abc", "file.txt", "logical identifier", id="name-starts-digit"),
        pytest.param("a" + "b" * 64, "file.txt", "logical identifier", id="name-too-long"),
        pytest.param("item", "", "relative POSIX path", id="empty-path"),
        pytest.param("item", "/abs.txt", "relative POSIX path", id="absolute-path"),
        pytest.param("item", "dir/", "relative POSIX path", id="trailing-slash"),
        pytest.param("item", "a\\b.txt", "relative POSIX path", id="backslash"),
        pytest.param("item", "a%2fb.txt", "relative POSIX path", id="percent"),
        pytest.param("item", "a//b.txt", "relative POSIX path", id="empty-part"),
        pytest.param("item", "a/./b.txt", "relative POSIX path", id="dot-part"),
        pytest.param("item", "a/../b.txt", "relative POSIX path", id="dotdot-part"),
        pytest.param("item", ".", "relative POSIX path", id="dot"),
        pytest.param("item", "..", "relative POSIX path", id="dotdot"),
    ),
)
def test_read_repository_resources_rejects_invalid_names_and_paths(
    tmp_path: Path,
    name: str,
    relative: str,
    match: str,
) -> None:
    with pytest.raises(InventoryError, match=match):
        read_repository_resources(tmp_path, {name: relative})


def test_read_repository_resources_rejects_non_string_relative_path(tmp_path: Path) -> None:
    with pytest.raises(InventoryError, match="relative POSIX path"):
        read_repository_resources(tmp_path, {"item": 1})  # type: ignore[dict-item]


def test_read_repository_resources_rejects_absolute_pure_posix_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AbsolutePath(PurePosixPath):
        def is_absolute(self) -> bool:
            return True

    monkeypatch.setattr(inventory, "PurePosixPath", AbsolutePath)
    with pytest.raises(InventoryError, match="repository-relative"):
        read_repository_resources(tmp_path, {"item": "file.txt"})


def test_read_repository_resources_rejects_symlink_and_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / "real.txt"
    inside.write_bytes(b"inside")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    (repo / "inner-link.txt").symlink_to(inside)
    (repo / "escape.txt").symlink_to(outside)
    nested = repo / "nested"
    nested.mkdir()
    (nested / "alias").symlink_to(inside, target_is_directory=False)

    with pytest.raises(InventoryError, match="escapes the repository root"):
        read_repository_resources(repo, {"item": "escape.txt"})
    with pytest.raises(InventoryError, match="contains a symlink"):
        read_repository_resources(repo, {"item": "inner-link.txt"})
    with pytest.raises(InventoryError, match="contains a symlink"):
        read_repository_resources(repo, {"item": "nested/alias"})


def test_read_repository_resources_rejects_directory_member(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()

    with pytest.raises(InventoryError, match="must be a regular file"):
        read_repository_resources(tmp_path, {"item": "subdir"})


def test_read_repository_resources_rejects_count_and_byte_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_relative(tmp_path, "a.txt", b"aa")
    _write_relative(tmp_path, "b.txt", b"bb")
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 0)
    with pytest.raises(InventoryError, match="count limit"):
        read_repository_resources(tmp_path, {"item": "a.txt"})

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 1_024)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 1)
    with pytest.raises(InventoryError, match="byte limit"):
        read_repository_resources(tmp_path, {"item": "a.txt"})

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_TOTAL_BYTES", 3)
    with pytest.raises(InventoryError, match="aggregate limit"):
        read_repository_resources(tmp_path, {"one": "a.txt", "two": "b.txt"})


def test_read_stable_file_rejects_symlink_and_missing_paths(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_bytes(b"hello")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    with pytest.raises(InventoryError, match="must not be a symlink"):
        _read_stable_file(link, max_bytes=64)
    with pytest.raises(InventoryError, match="cannot be opened safely"):
        _read_stable_file(tmp_path / "missing.txt", max_bytes=64)


def test_read_stable_file_rejects_growth_and_mutation_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "stable.txt"
    path.write_bytes(b"hello")
    real_fstat = inventory.os.fstat

    def undersized_fstat(descriptor: int) -> SimpleNamespace:
        st = real_fstat(descriptor)
        return SimpleNamespace(
            st_mode=st.st_mode,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            st_size=1,
            st_mtime_ns=st.st_mtime_ns,
            st_ctime_ns=st.st_ctime_ns,
        )

    monkeypatch.setattr(inventory.os, "fstat", undersized_fstat)
    with pytest.raises(InventoryError, match="byte limit"):
        _read_stable_file(path, max_bytes=3)

    def mutating_fstat(descriptor: int) -> SimpleNamespace:
        st = real_fstat(descriptor)
        mutating_fstat.calls += 1
        size = st.st_size if mutating_fstat.calls == 1 else st.st_size + 1
        return SimpleNamespace(
            st_mode=st.st_mode,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            st_size=size,
            st_mtime_ns=st.st_mtime_ns,
            st_ctime_ns=st.st_ctime_ns,
        )

    mutating_fstat.calls = 0
    monkeypatch.setattr(inventory.os, "fstat", mutating_fstat)
    with pytest.raises(InventoryError, match="changed during readback"):
        _read_stable_file(path, max_bytes=64)


def test_read_stable_file_reads_without_nofollow_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "plain.txt"
    path.write_bytes(b"plain")
    monkeypatch.delattr(inventory.os, "O_NOFOLLOW", raising=False)

    assert _read_stable_file(path, max_bytes=64) == b"plain"


def test_read_wheel_resources_returns_requested_members(tmp_path: Path) -> None:
    wheel = _make_wheel(
        tmp_path / "ok.whl",
        {
            "openopps/catalog.json": b"catalog",
            "openopps/discovery/data/manifest.json": b"manifest",
        },
    )

    resources = read_wheel_resources(
        wheel,
        {
            "manifest": "openopps/discovery/data/manifest.json",
            "catalog": "openopps/catalog.json",
        },
    )

    assert resources == {"catalog": b"catalog", "manifest": b"manifest"}


def test_read_wheel_resources_rejects_symlink_missing_and_corrupt(tmp_path: Path) -> None:
    missing = tmp_path / "missing.whl"
    corrupt = tmp_path / "corrupt.whl"
    corrupt.write_bytes(b"not-a-zip")
    real = _make_wheel(tmp_path / "real.whl", {"openopps/catalog.json": b"x"})
    link = tmp_path / "link.whl"
    link.symlink_to(real)

    with pytest.raises(InventoryError, match="must not be a symlink"):
        read_wheel_resources(link, {"catalog": "openopps/catalog.json"})
    with pytest.raises(InventoryError, match="cannot be opened safely"):
        read_wheel_resources(missing, {"catalog": "openopps/catalog.json"})
    with pytest.raises(InventoryError, match="cannot be read safely"):
        read_wheel_resources(corrupt, {"catalog": "openopps/catalog.json"})


def test_read_wheel_resources_rejects_member_inventory_errors(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path / "members.whl", {"openopps/catalog.json": b"x"})
    with pytest.raises(InventoryError, match="required wheel resource is absent"):
        read_wheel_resources(wheel, {"catalog": "openopps/missing.json"})

    link_wheel = _make_wheel(
        tmp_path / "link-member.whl",
        {"openopps/catalog.json": b"x"},
        modes={"openopps/catalog.json": stat.S_IFLNK | 0o777},
    )
    with pytest.raises(InventoryError, match="must be a regular file"):
        read_wheel_resources(link_wheel, {"catalog": "openopps/catalog.json"})

    with pytest.raises(InventoryError, match="logical identifier"):
        read_wheel_resources(wheel, {"Catalog": "openopps/catalog.json"})
    with pytest.raises(InventoryError, match="relative POSIX path"):
        read_wheel_resources(wheel, {"catalog": "../catalog.json"})


def test_read_wheel_resources_rejects_duplicate_and_count_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicates = tmp_path / "dup.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(duplicates, mode="w") as archive:
            archive.writestr("openopps/catalog.json", b"one")
            archive.writestr("openopps/catalog.json", b"two")
    with pytest.raises(InventoryError, match="duplicate member names"):
        read_wheel_resources(duplicates, {"catalog": "openopps/catalog.json"})

    wheel = _make_wheel(
        tmp_path / "limits.whl",
        {"openopps/a.json": b"aa", "openopps/b.json": b"bb"},
    )
    monkeypatch.setattr(inventory, "MAX_WHEEL_MEMBER_COUNT", 0)
    with pytest.raises(InventoryError, match="member inventory exceeds"):
        read_wheel_resources(wheel, {"one": "openopps/a.json"})

    monkeypatch.setattr(inventory, "MAX_WHEEL_MEMBER_COUNT", 10_000)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 0)
    with pytest.raises(InventoryError, match="requested wheel resource set"):
        read_wheel_resources(wheel, {"one": "openopps/a.json"})

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_COUNT", 1_024)
    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 1)
    with pytest.raises(InventoryError, match="wheel resource exceeds its byte limit"):
        read_wheel_resources(wheel, {"one": "openopps/a.json"})

    monkeypatch.setattr(inventory, "MAX_IDENTITY_RESOURCE_BYTES", 64 * 1024 * 1024)
    bulky = _make_wheel(tmp_path / "bulky.whl", {"openopps/a.json": b"x" * 4_096})
    monkeypatch.setattr(inventory, "MAX_IDENTITY_TOTAL_BYTES", bulky.stat().st_size)
    with pytest.raises(InventoryError, match="aggregate byte limit"):
        read_wheel_resources(
            bulky,
            {"one": "openopps/a.json", "two": "openopps/a.json"},
        )


def test_read_wheel_resources_rejects_size_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _make_wheel(tmp_path / "mismatch.whl", {"openopps/catalog.json": b"abcd"})

    class FakeInfo:
        filename = "openopps/catalog.json"
        file_size = 4
        external_attr = 0

        def is_dir(self) -> bool:
            return False

    class FakeZip:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def __enter__(self) -> FakeZip:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def infolist(self) -> list[FakeInfo]:
            return [FakeInfo()]

        def read(self, info: object) -> bytes:
            del info
            return b"mismatch"

    monkeypatch.setattr(inventory, "ZipFile", FakeZip)
    with pytest.raises(InventoryError, match="size does not match metadata"):
        read_wheel_resources(wheel, {"catalog": "openopps/catalog.json"})


def test_read_wheel_resources_rejects_post_read_aggregate_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _make_wheel(tmp_path / "post.whl", {"openopps/catalog.json": b"x"})

    class FakeInfo:
        filename = "openopps/catalog.json"
        file_size = 1
        external_attr = 0

        def is_dir(self) -> bool:
            return False

    class FakeZip:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def __enter__(self) -> FakeZip:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def infolist(self) -> list[FakeInfo]:
            return [FakeInfo()]

        def read(self, info: object) -> bytes:
            del info
            monkeypatch.setattr(inventory, "MAX_IDENTITY_TOTAL_BYTES", 0)
            return b"x"

    monkeypatch.setattr(inventory, "ZipFile", FakeZip)
    with pytest.raises(InventoryError, match="aggregate byte limit"):
        read_wheel_resources(wheel, {"catalog": "openopps/catalog.json"})


def test_read_default_repository_projection_projects_seeded_surfaces(
    tmp_path: Path,
) -> None:
    root = _seed_identity_repo(tmp_path / "repo")
    _write_relative(root, "public/selector.json", b"selector")

    projection = read_default_repository_projection(
        root,
        public_selector_path="public/selector.json",
        embedded_wheel_resources={"catalog": b"wheel"},
        discovery_owned_paths={name: None for name in DISCOVERY_OWNED_IDENTITY_NAMES},
    )

    assert projection.public_selector.present is True
    assert projection.public_selector.size_bytes == len(b"selector")
    assert all(item.present is False for item in projection.discovery_owned)
    assert tuple(item.name for item in projection.v7_policy_inputs) == V7_POLICY_INPUT_NAMES


def test_read_default_repository_projection_reads_default_owned_paths(
    tmp_path: Path,
) -> None:
    root = _seed_identity_repo(tmp_path / "repo")

    projection = read_default_repository_projection(root)

    assert projection.public_selector.present is False
    assert all(item.present is True for item in projection.discovery_owned)
    assert tuple(item.name for item in projection.discovery_owned) == (
        DISCOVERY_OWNED_IDENTITY_NAMES
    )


def test_read_default_repository_projection_rejects_incomplete_owned_roles(
    tmp_path: Path,
) -> None:
    root = _seed_identity_repo(tmp_path / "repo")

    with pytest.raises(InventoryError, match="path roles are incomplete"):
        read_default_repository_projection(
            root,
            discovery_owned_paths={"decision": None, "envelope": None},
        )
