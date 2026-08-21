from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import pkgutil
import subprocess
import sys
from types import MappingProxyType
from typing import Any
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from openopps.discovery.api import (
    decode_discovery_model,
    discovery_schema_bytes,
    encode_discovery_model,
    normalize_discovery_candidate,
)
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.diagnostics import (
    MAX_DIAGNOSTIC_INPUT_BYTES,
    MAX_DIAGNOSTIC_SUMMARY_CHARS,
    DiagnosticRenderingError,
    render_bounded_diagnostic,
    render_metric_attributes,
)
from openopps.discovery.inventory import (
    DEFAULT_PACKAGED_CATALOG_PATH,
    DISCOVERY_OWNED_IDENTITY_NAMES,
    V7_POLICY_INPUT_NAMES,
    InventoryError,
    build_approved_runtime_catalog_inventory,
    project_repository_identities,
    read_default_repository_projection,
    read_packaged_catalog_bytes,
    read_wheel_resources,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelBudget,
    ChannelProfile,
    DiscoveryChannel,
    StrictDiscoveryModel,
)
from openopps.discovery.schemas import (
    SCHEMA_MANIFEST_NAME,
    check_discovery_schema_files,
    discovery_schema_models,
    render_discovery_schema_files,
    schema_file_name,
)


ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_DISCOVERY_IMPORTS = (
    "openopps.cache",
    "openopps.cli",
    "openopps.ingest",
    "openopps.plugins",
    "openopps.providers",
    "openopps.storage",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object_schemas(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("type") == "object":
            found.append(value)
        for nested in value.values():
            found.extend(_object_schemas(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_object_schemas(nested))
    return found


def test_generated_schemas_cover_every_strict_model_and_are_byte_current(
    tmp_path: Path,
) -> None:
    model_registry = discovery_schema_models()
    declared = {
        name
        for name, candidate in vars(
            importlib.import_module("openopps.discovery.models")
        ).items()
        if (
            isinstance(candidate, type)
            and candidate is not StrictDiscoveryModel
            and issubclass(candidate, StrictDiscoveryModel)
            and candidate.__module__ == "openopps.discovery.models"
        )
    }
    assert set(model_registry) == declared

    rendered_first = render_discovery_schema_files()
    rendered_second = render_discovery_schema_files()
    assert isinstance(rendered_first, MappingProxyType)
    assert dict(rendered_first) == dict(rendered_second)
    manifest = decode_canonical_json(rendered_first[SCHEMA_MANIFEST_NAME])
    assert manifest["modelCount"] == len(model_registry)
    assert [row["model"] for row in manifest["schemas"]] == sorted(model_registry)
    assert check_discovery_schema_files().ok

    for model_name in model_registry:
        path = schema_file_name(model_name)
        raw = rendered_first[path]
        assert raw == discovery_schema_bytes(model_name)
        schema = decode_canonical_json(raw)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == f"urn:openopps:discovery:schema:{model_name}"
        assert _object_schemas(schema)
        assert all(
            object_schema.get("additionalProperties") is False
            for object_schema in _object_schemas(schema)
        )

    bundle_schema = decode_canonical_json(
        rendered_first["discovery-bundle-manifest.schema.json"]
    )
    assert "schemaVersion" in bundle_schema["properties"]
    assert "schema_version" not in bundle_schema["properties"]
    member_schema = decode_canonical_json(
        rendered_first["bundle-member-manifest.schema.json"]
    )
    assert "mediaType" in member_schema["properties"]
    assert "media_type" not in member_schema["properties"]
    decision_schema = decode_canonical_json(
        rendered_first["discovery-promotion-policy-decision.schema.json"]
    )
    assert set(decision_schema["properties"]) == {
        "catalogAfterDigest",
        "catalogBeforeDigest",
        "decisionId",
        "headSha",
        "manifestDigest",
        "policyInputsDigest",
        "profileDigest",
        "promotionDigest",
        "promotionIntentDigest",
        "requiredOperations",
        "resourcesDigest",
        "schemaVersion",
        "selectionDigest",
    }
    assert set(decision_schema["required"]) == set(decision_schema["properties"])
    assert decision_schema["properties"]["requiredOperations"]["items"]["enum"] == [
        "access",
        "license",
        "publication",
        "redistribution",
        "sync",
    ]

    for name, content in rendered_first.items():
        (tmp_path / name).write_bytes(content)
    drifted = next(name for name in rendered_first if name.endswith(".schema.json"))
    (tmp_path / drifted).write_bytes(rendered_first[drifted] + b" ")
    extra = tmp_path / "obsolete.schema.json"
    extra.write_bytes(b"{}\n")
    result = check_discovery_schema_files(tmp_path)
    assert result.changed == (drifted,)
    assert result.extra == (extra.name,)
    assert result.missing == ()


def test_cli_neutral_model_entry_points_require_canonical_strict_bytes() -> None:
    budget = ChannelBudget(
        query_limit=3,
        request_limit=5,
        origin_limit=2,
        redirect_limit=1,
        page_limit=3,
        response_byte_limit=1_024,
        aggregate_byte_limit=2_048,
        candidate_limit=5,
        concurrency_limit=2,
        per_origin_concurrency_limit=1,
        retry_limit=1,
        parser_depth_limit=8,
        wall_clock_limit_ms=1_000,
    )
    encoded = encode_discovery_model(budget)
    assert decode_discovery_model(ChannelBudget, encoded) == budget
    snake_case = canonical_json_bytes(budget.model_dump(mode="json", by_alias=False))
    with pytest.raises(ValidationError):
        decode_discovery_model(ChannelBudget, snake_case)
    with pytest.raises(ValueError, match="canonical"):
        decode_discovery_model(
            ChannelBudget, encoded.replace(b'"aggregate', b' "aggregate')
        )
    unknown_payload = decode_canonical_json(encoded)
    unknown_payload["extra"] = 1
    unknown = canonical_json_bytes(unknown_payload)
    with pytest.raises(ValidationError):
        decode_discovery_model(ChannelBudget, unknown)

    channel = ChannelProfile(
        channel="official",
        budget=budget,
        seed_ids=(),
        allowed_origins=(),
        allowed_query_keys=(),
        parser_ids=(),
    )
    nested_snake_case = decode_canonical_json(encode_discovery_model(channel))
    nested_snake_case["budget"]["query_limit"] = nested_snake_case["budget"].pop(
        "queryLimit"
    )
    with pytest.raises(ValidationError):
        decode_discovery_model(
            ChannelProfile,
            canonical_json_bytes(nested_snake_case),
        )

    candidate = normalize_discovery_candidate(
        key=" Example ",
        url="https://example.test/jobs",
        provider_id=" Example-Provider ",
        provider_token="CaseSensitiveToken",
        owner=" Example-Owner ",
        candidate_kind="board_route",
        adapter_id=" Example-Adapter ",
    )
    assert candidate.candidate_kind == "board_route"
    assert candidate.adapter_id == "example-adapter"
    assert candidate.provider_token == "CaseSensitiveToken"


def test_diagnostics_never_render_untrusted_detail_and_remain_bounded() -> None:
    secret = (
        "https://private.example.test/path?token=secret "
        "Authorization: Bearer secret Cookie: session=secret "
        + "x"
        * (MAX_DIAGNOSTIC_INPUT_BYTES + 100)
    )
    diagnostic = render_bounded_diagnostic(
        BoundedReason.SECRET_DETECTED,
        detail=secret,
    )
    rendered = json.dumps(diagnostic.as_dict(), sort_keys=True)
    assert "private.example" not in rendered
    assert "Bearer" not in rendered
    assert "session=" not in rendered
    assert diagnostic.admitted_detail_bytes == MAX_DIAGNOSTIC_INPUT_BYTES
    assert diagnostic.detail_truncated is True
    assert diagnostic.detail_prefix_sha256 is not None
    assert len(diagnostic.summary) <= MAX_DIAGNOSTIC_SUMMARY_CHARS
    assert diagnostic == render_bounded_diagnostic(
        BoundedReason.SECRET_DETECTED,
        detail=secret,
    )

    attributes = render_metric_attributes(
        channel=DiscoveryChannel.OFFICIAL,
        terminal_state="failed",
        reason_code=BoundedReason.SECRET_DETECTED,
        complete=False,
        identity_digest="a" * 64,
    )
    assert isinstance(attributes, MappingProxyType)
    assert set(attributes) == {
        "openopps.discovery.channel",
        "openopps.discovery.complete",
        "openopps.discovery.identity.sha256",
        "openopps.discovery.reason",
        "openopps.discovery.scope",
        "openopps.discovery.state",
    }
    assert all("http" not in str(value) for value in attributes.values())
    with pytest.raises(DiagnosticRenderingError):
        render_metric_attributes(
            channel="official",  # type: ignore[arg-type]
            terminal_state="failed",
            reason_code=BoundedReason.SECRET_DETECTED,
            complete=False,
        )
    run_attributes = render_metric_attributes(
        channel=None,
        terminal_state="aborted",
        reason_code=BoundedReason.TIMED_OUT,
        complete=False,
    )
    assert run_attributes["openopps.discovery.scope"] == "run"
    assert "openopps.discovery.channel" not in run_attributes
    with pytest.raises(DiagnosticRenderingError, match="whole-run"):
        render_metric_attributes(
            channel=DiscoveryChannel.SEARCH,
            terminal_state="aborted",
            reason_code=BoundedReason.TIMED_OUT,
            complete=False,
        )


def test_runtime_catalog_readback_matches_the_frozen_approved_inventory() -> None:
    from openopps.models import SourceRecord
    from openopps.providers import sources as source_package
    from openopps.providers.sources import (
        BOARD_SOURCE_ADAPTERS,
        BOARD_SOURCE_RECORDS,
    )

    owner_rows: list[list[str]] = []
    for module_info in pkgutil.iter_modules(
        source_package.__path__, f"{source_package.__name__}."
    ):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        owner_rows.extend(
            [record.key, module.__name__]
            for record in getattr(module, "SOURCE_RECORDS", ())
            if isinstance(record, SourceRecord)
        )
    adapter_rows = [
        [provider_id, adapter.__module__, adapter.__qualname__]
        for provider_id, adapter in BOARD_SOURCE_ADAPTERS.items()
    ]
    packaged = read_packaged_catalog_bytes(
        (ROOT / DEFAULT_PACKAGED_CATALOG_PATH).read_bytes()
    )
    first = build_approved_runtime_catalog_inventory(
        source_records=reversed(BOARD_SOURCE_RECORDS),
        source_owner_rows=reversed(owner_rows),
        adapter_identity_rows=reversed(adapter_rows),
        packaged_catalog=packaged,
    )
    second = build_approved_runtime_catalog_inventory(
        source_records=BOARD_SOURCE_RECORDS,
        source_owner_rows=owner_rows,
        adapter_identity_rows=adapter_rows,
        packaged_catalog=packaged,
    )
    assert first == second
    assert first.source_count == first.unique_source_count == 2_870
    assert first.runtime_semantic_sha256 == (
        "35655ea36568cf0a05ceb51fb7b757126e96d6fc5402b596c140a322baef10e7"
    )
    assert first.owner_map_sha256 == (
        "6121e07d3313b561fcde023ac181e8721c7f31a516d4ded693e634dcbe9384ed"
    )
    assert first.adapter_count == 16
    assert first.adapter_identity_map_sha256 == (
        "3458c6e6fced46c20f55cba5f57c89489c19744dbebd150fa3f3e23ad3380de4"
    )
    assert packaged.fingerprint == (
        "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
    )
    assert packaged.file_sha256 == (
        "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
    )

    with pytest.raises(InventoryError, match="ownership"):
        build_approved_runtime_catalog_inventory(
            source_records=BOARD_SOURCE_RECORDS,
            source_owner_rows=(*owner_rows, owner_rows[0]),
            adapter_identity_rows=adapter_rows,
            packaged_catalog=packaged,
        )


def test_identity_projection_is_digest_only_deterministic_and_non_mutating(
    tmp_path: Path,
) -> None:
    protected_paths = (
        ROOT / "src/openopps/source_policy.py",
        ROOT / "src/openopps/providers/sources/data/source_policy_evidence.json",
        ROOT / "src/openopps/providers/sources/data/source_policy_evidence.schema.json",
        ROOT / "deployment/openopps-data/source-corpus-v6.json",
        ROOT / "web/lib/generated/openopps-data.json",
    )
    before = {
        path: (path.stat().st_mode, path.stat().st_size, _sha256(path))
        for path in protected_paths
    }
    first = read_default_repository_projection(ROOT)
    second = read_default_repository_projection(ROOT)
    after = {
        path: (path.stat().st_mode, path.stat().st_size, _sha256(path))
        for path in protected_paths
    }
    assert first == second
    assert before == after
    assert tuple(item.name for item in first.v7_policy_inputs) == V7_POLICY_INPUT_NAMES
    assert first.public_selector.present is False
    assert all(item.present is False for item in first.discovery_owned)
    assert tuple(item.name for item in first.discovery_owned) == (
        DISCOVERY_OWNED_IDENTITY_NAMES
    )

    wheel = tmp_path / "openopps-test.whl"
    with ZipFile(wheel, mode="w") as archive:
        archive.writestr("openopps/discovery/data/manifest.json", b"schema-manifest")
        archive.writestr("openopps/providers/catalog.json", b"catalog-bytes")
    wheel_before = wheel.read_bytes()
    resources = read_wheel_resources(
        wheel,
        {
            "catalog": "openopps/providers/catalog.json",
            "discovery_schemas": "openopps/discovery/data/manifest.json",
        },
    )
    assert wheel.read_bytes() == wheel_before

    sensitive = b"raw-secret-value-must-not-be-projected"
    projection = project_repository_identities(
        v7_policy_inputs={
            name: f"{name}-bytes".encode() for name in V7_POLICY_INPUT_NAMES
        },
        public_selector=None,
        shared_generated_data={"web_data": sensitive},
        embedded_wheel_resources=resources,
        discovery_owned={name: None for name in DISCOVERY_OWNED_IDENTITY_NAMES},
    )
    serialized = json.dumps(projection.as_dict(), sort_keys=True)
    assert sensitive.decode() not in serialized
    assert projection == project_repository_identities(
        v7_policy_inputs={
            name: f"{name}-bytes".encode() for name in V7_POLICY_INPUT_NAMES
        },
        public_selector=None,
        shared_generated_data={"web_data": sensitive},
        embedded_wheel_resources=dict(reversed(tuple(resources.items()))),
        discovery_owned={
            name: None for name in reversed(DISCOVERY_OWNED_IDENTITY_NAMES)
        },
    )
    with pytest.raises(InventoryError, match="count limit"):
        project_repository_identities(
            v7_policy_inputs={
                name: f"{name}-bytes".encode() for name in V7_POLICY_INPUT_NAMES
            },
            public_selector=None,
            shared_generated_data={f"resource_{index}": b"" for index in range(1_025)},
            embedded_wheel_resources={},
            discovery_owned={name: None for name in DISCOVERY_OWNED_IDENTITY_NAMES},
        )


def test_core_surface_imports_do_not_load_operational_modules() -> None:
    program = (
        "import importlib,json,sys\n"
        "before=set(sys.modules)\n"
        "for name in ("
        "'openopps.discovery.diagnostics',"
        "'openopps.discovery.inventory',"
        "'openopps.discovery.schemas',"
        "'openopps.discovery.api'"
        "): importlib.import_module(name)\n"
        "print(json.dumps(sorted(set(sys.modules)-before)))\n"
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-I", "-c", program],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)
    assert not {
        name
        for name in loaded
        if any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_DISCOVERY_IMPORTS
        )
    }
