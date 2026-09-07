#!/usr/bin/env python3
"""Read current promotion closure from one dependency-free isolated wheel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast


def _load_catalog_smoke() -> ModuleType:
    existing = sys.modules.get("smoke_wheel_catalog")
    if isinstance(existing, ModuleType):
        return existing
    path = Path(__file__).resolve().with_name("smoke_wheel_catalog.py")
    spec = importlib.util.spec_from_file_location("smoke_wheel_catalog", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load trusted wheel-smoke helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_catalog_smoke = _load_catalog_smoke()
SmokeValidationError = _catalog_smoke.SmokeValidationError
WheelArtifact = _catalog_smoke.WheelArtifact
_attest_installed_package = _catalog_smoke._attest_installed_package
_attest_installed_wheel_payload = _catalog_smoke._attest_installed_wheel_payload
_create_uv_venv = _catalog_smoke._create_uv_venv
_decode_record_sha256 = _catalog_smoke._decode_record_sha256
_has_symlink_component = _catalog_smoke._has_symlink_component
_install_local_wheel = _catalog_smoke._install_local_wheel
_preflight_wheel_archive = _catalog_smoke._preflight_wheel_archive
_read_bounded_file = _catalog_smoke._read_bounded_file
_read_recorded_installed_files = _catalog_smoke._read_recorded_installed_files
_read_wheel_files = _catalog_smoke._read_wheel_files
_record_path = _catalog_smoke._record_path
_require_installed_files_match_wheel = (
    _catalog_smoke._require_installed_files_match_wheel
)
_run_isolated_function = _catalog_smoke._run_isolated_function
_sanitized_environment = _catalog_smoke._sanitized_environment
_select_openopps_wheel = _catalog_smoke._select_openopps_wheel
_sha256_file = _catalog_smoke._sha256_file
_validate_direct_url = _catalog_smoke._validate_direct_url
_validate_openopps_wheel_layout = _catalog_smoke._validate_openopps_wheel_layout
_validated_external_record_paths = _catalog_smoke._validated_external_record_paths
_validated_uv_bin = _catalog_smoke._validated_uv_bin
_venv_site_packages = _catalog_smoke._venv_site_packages

_EXPECTED_OPENOPPS_VERSION = "0.1.1"
_EXPECTED_CATALOG_VERSION = 2
_EXPECTED_CATALOG_COUNT = 2239
_EXPECTED_CATALOG_FINGERPRINT = (
    "c30f8600353399f37858f691a7b622e12364c46990c0bd93144a9346ededcb32"
)
_EXPECTED_CATALOG_SHA256 = (
    "22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c"
)
_EXPECTED_DECISION_ID = "b699-identity-closure-20260906"
_EXPECTED_DECISION_DIGEST = (
    "1ca03c15e9a697d8ec6989436ae3ad34b708eb570ee57590b15b0df2aa5eca9c"
)
_EXPECTED_PROMOTION_INTENT_DIGEST = (
    "c2e79944f31cd8dd9ed0ed832ff53b8bb77cdad41ae47332440d60bb2a46b90e"
)
_EXPECTED_PROMOTION_DIGEST = (
    "c1686a912ed52cbbd883f26a567c8b4f144755386bd1d2ccea90fa3efdb1c151"
)
_EXPECTED_SOURCE_KEY_DIGEST = (
    "451eb3dfe7fd565361abc2827c3ac26427b51402a3c5b2afdccc82b076b6cacc"
)
_EXPECTED_ENVELOPE_ID = (
    "4211ebb1d68df8f2ba64f2c8f2bf588d76ae63684c5a6ae57731acf5cde8ca6d"
)
_EXPECTED_MANIFEST_DIGEST = (
    "f0a768106ea1640132b672d9e46e31125a13e8e8756a75e16b2bd5ae7824b064"
)
_EXPECTED_SELECTION_DIGEST = (
    "ff109b738e9200540042c20d2bad6ad5e58bbd45b9e74706d464c9e6569f548e"
)
_EXPECTED_POLICY_INPUTS_DIGEST = (
    "8055b54fe0177d334797509eb643475e971db395c5104214381ac877f405a1d7"
)
_EXPECTED_RESOURCES_DIGEST = (
    "a4376db6dd7e565f82f5893cd41b5295ce55ee15dfc682bc7e6423fa05041897"
)
_EXPECTED_PROFILE_DIGEST = (
    "ba1ff085f41254a893bbe3ff08ec28f68ca89ec97f26c6e18875239b5181ce6d"
)
_EXPECTED_HEAD_SHA = "2afe307cc769b640a981e7497cc2673c073d0903"
_EXPECTED_REQUIRED_OPERATIONS = [
    "access",
    "license",
    "publication",
    "redistribution",
    "sync",
]
_EXPECTED_DECISION_IDS = [
    "b699-identity-closure-20260822",
    "b699-identity-closure-20260822",
    "b699-identity-closure-20260906",
    "b699-identity-closure-20260906",
]
_EXPECTED_EVENT_STATES = ["reserved", "applied", "reserved", "applied"]
_EXPECTED_EVENT_DIGESTS = [
    "07e832b2f60089544b857c64f6f76ac19cb30d476f2d8f3b6c05368cfd6065c5",
    "c9237886243b966e22596c990ec870c3300bdf9d297fc0b1d15d72ae65269937",
    "318871cd1afeae92ba3bf4af6baf0f12fff13d73397a7ea8ec510ab51894eeae",
    "63e0327b1188fcfb9874351c8de4e0bf9cd6181e6a7b6646f1ebc97882c35621",
]
_EXPECTED_EVENT_INTENTS = [
    "5f7ec3904f41fd7c4e050ca3c8aec75aa549328309a78528dd0576322cd0e1af",
    "5f7ec3904f41fd7c4e050ca3c8aec75aa549328309a78528dd0576322cd0e1af",
    _EXPECTED_PROMOTION_INTENT_DIGEST,
    _EXPECTED_PROMOTION_INTENT_DIGEST,
]
_EXPECTED_VALIDATOR_VERSION = "openopps.discovery.promotion/1"
_EXPECTED_VALIDATED_AT = "2026-09-06T00:00:00Z"
_EXPECTED_ENVELOPE_POLICY_DIGESTS = {
    "supplementaryPolicyDigest": (
        "967a3b97e05af37d9ee3b4643fdec312cae2b397380ab9ebbea1f5237f3595b0"
    ),
    "v7PolicyCodeDigest": (
        "6a21c11541353524dd4ce73a63a0f20cdbb11d28d02640cbe94fcdeb8e02347f"
    ),
    "v7PolicyCorpusDigest": (
        "4849378598da20ea7e1dd8ccdcc80b1189b5e6853b7661399d40c65a6fb85a08"
    ),
    "v7PolicyEvidenceDigest": (
        "c75401ab710caee87b55682038bcda0206df270d71e3e26e6d5f5642f734f0ec"
    ),
    "v7PolicySchemaDigest": (
        "14b4c2a6ec4b1ade2d0a5860acd24180f6e23b8ee088bff6eeecf17e5a3a0089"
    ),
}
_REQUIRED_ARTIFACT_PATHS = (
    "openopps/providers/sources/data/portfolio_source_catalog.json",
    "openopps/discovery/data/discovery_promotion_policy_decision.json",
    "openopps/discovery/data/approved_ingestion_selector_envelope.json",
    "openopps/discovery/data/promotion_decision_ledger.jsonl",
    "openopps/discovery/data/evidence_only_decision_receipt.json",
)
_ARTIFACT_KEYS_BY_PATH = {
    _REQUIRED_ARTIFACT_PATHS[0]: "catalog",
    _REQUIRED_ARTIFACT_PATHS[1]: "decision",
    _REQUIRED_ARTIFACT_PATHS[2]: "envelope",
    _REQUIRED_ARTIFACT_PATHS[3]: "ledger",
    _REQUIRED_ARTIFACT_PATHS[4]: "receipt",
}
_DECISION_FIELDS = {
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
_INTENT_FIELDS = (
    "headSha",
    "manifestDigest",
    "selectionDigest",
    "resourcesDigest",
    "profileDigest",
    "policyInputsDigest",
    "catalogBeforeDigest",
    "catalogAfterDigest",
    "promotionDigest",
    "requiredOperations",
)
_LEDGER_FIELDS = _DECISION_FIELDS | {
    "eventDigest",
    "predecessorDigest",
    "sequence",
    "state",
}
_RECEIPT_FIELDS = {
    "decisionDigest",
    "decisionId",
    "grantsAuthority",
    "promotionIntentDigest",
    "schemaVersion",
    "validatedAt",
    "validatorVersion",
}
_ENVELOPE_FIELDS = {
    "catalogContentDigest",
    "catalogTreeDigest",
    "envelopeId",
    "packagedCatalogFingerprint",
    "promotionDigest",
    "schemaVersion",
    "sourceCount",
    "sourceKeyDigest",
    "sourceKeys",
    "supplementaryPolicyDigest",
    "v7PolicyCodeDigest",
    "v7PolicyCorpusDigest",
    "v7PolicyEvidenceDigest",
    "v7PolicySchemaDigest",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_MAX_JSON_DEPTH = 128
_MAX_JSON_NODES = 100_000
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeValidationError(message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--uv-bin", type=Path, required=True)
    return parser.parse_args()


def _reject_json_float(value: str) -> NoReturn:
    raise SmokeValidationError(f"floating-point JSON number is forbidden: {value}")


def _reject_json_constant(value: str) -> NoReturn:
    raise SmokeValidationError(f"non-finite JSON number is forbidden: {value}")


def _parse_json_int(value: str) -> int:
    _require(value != "-0", "negative-zero JSON integer is forbidden")
    return int(value)


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON object key is forbidden: {key!r}")
        result[key] = value
    return result


def _validate_json_limits(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        _require(nodes <= _MAX_JSON_NODES, "JSON node limit exceeded")
        _require(depth <= _MAX_JSON_DEPTH, "JSON nesting depth limit exceeded")
        if isinstance(current, dict):
            _require(
                all(type(key) is str for key in current),
                "JSON object keys must be strings",
            )
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        else:
            _require(
                current is None or type(current) in {bool, int, str},
                f"unsupported JSON value type: {type(current).__name__}",
            )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _decode_json_bytes(
    raw: bytes, *, label: str, require_canonical: bool = False
) -> object:
    _require(type(raw) is bytes, f"{label} input must be bytes")
    _require(len(raw) <= _MAX_ARTIFACT_BYTES, f"{label} exceeds its byte limit")
    _require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} contains a UTF-8 BOM")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except SmokeValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SmokeValidationError(f"{label} is not strict UTF-8 JSON") from exc
    _validate_json_limits(payload)
    if require_canonical:
        _require(
            raw == _canonical_json_bytes(payload),
            f"{label} does not use canonical JSON bytes",
        )
    return payload


def _sha256_canonical(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_object_fields(
    payload: object, expected: set[str], *, label: str
) -> dict[str, Any]:
    _require(type(payload) is dict, f"{label} root must be an object")
    mapping = cast(dict[str, Any], payload)
    _require(set(mapping) == expected, f"{label} fields do not match the contract")
    return mapping


def _require_sha256(value: object, *, label: str) -> str:
    _require(
        type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None,
        f"{label} must be a lowercase SHA-256 digest",
    )
    return cast(str, value)


def _require_git_sha(value: object, *, label: str) -> str:
    _require(
        type(value) is str and _GIT_SHA_PATTERN.fullmatch(value) is not None,
        f"{label} must be a lowercase Git SHA",
    )
    return cast(str, value)


def _validate_catalog(catalog_raw: bytes) -> tuple[dict[str, Any], list[str], str]:
    catalog = _catalog_smoke._validate_catalog_shape(catalog_raw)
    _require(
        catalog["version"] == _EXPECTED_CATALOG_VERSION,
        "catalog version does not match the promotion closure",
    )
    _require(
        catalog["count"] == _EXPECTED_CATALOG_COUNT,
        "catalog count does not match the promotion closure",
    )
    entries = catalog["entries"]
    keys = [entry["key"] for entry in entries]
    fingerprint_payload = json.dumps(
        entries,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    fingerprint = hashlib.sha256(fingerprint_payload).hexdigest()
    _require(
        fingerprint == catalog["fingerprint"] == _EXPECTED_CATALOG_FINGERPRINT,
        "catalog fingerprint does not match entries",
    )
    catalog_digest = hashlib.sha256(catalog_raw).hexdigest()
    _require(
        catalog_digest == _EXPECTED_CATALOG_SHA256,
        "catalog file digest does not match the promotion closure",
    )
    return catalog, keys, catalog_digest


def _validate_decision(decision_raw: bytes) -> dict[str, Any]:
    decision = _require_object_fields(
        _decode_json_bytes(
            decision_raw, label="promotion decision", require_canonical=True
        ),
        _DECISION_FIELDS,
        label="promotion decision",
    )
    _require(
        type(decision["schemaVersion"]) is int, "decision schemaVersion must be int"
    )
    _require(decision["schemaVersion"] == 1, "decision schemaVersion is invalid")
    _require(decision["decisionId"] == _EXPECTED_DECISION_ID, "decision ID is invalid")
    _require_git_sha(decision["headSha"], label="decision headSha")
    for field in (
        "manifestDigest",
        "selectionDigest",
        "resourcesDigest",
        "profileDigest",
        "policyInputsDigest",
        "catalogBeforeDigest",
        "catalogAfterDigest",
        "promotionDigest",
        "promotionIntentDigest",
    ):
        _require_sha256(decision[field], label=f"decision {field}")
    _require(
        decision["requiredOperations"] == _EXPECTED_REQUIRED_OPERATIONS
        and all(type(item) is str for item in decision["requiredOperations"]),
        "decision requiredOperations are invalid",
    )
    expected_fields = {
        "headSha": _EXPECTED_HEAD_SHA,
        "manifestDigest": _EXPECTED_MANIFEST_DIGEST,
        "selectionDigest": _EXPECTED_SELECTION_DIGEST,
        "resourcesDigest": _EXPECTED_RESOURCES_DIGEST,
        "profileDigest": _EXPECTED_PROFILE_DIGEST,
        "policyInputsDigest": _EXPECTED_POLICY_INPUTS_DIGEST,
        "promotionDigest": _EXPECTED_PROMOTION_DIGEST,
        "promotionIntentDigest": _EXPECTED_PROMOTION_INTENT_DIGEST,
    }
    for field, expected in expected_fields.items():
        _require(decision[field] == expected, f"decision {field} is not current")
    intent = {field: decision[field] for field in _INTENT_FIELDS}
    _require(
        _sha256_canonical(intent) == decision["promotionIntentDigest"],
        "decision promotion intent digest does not match reviewed fields",
    )
    return decision


def _parse_ledger(ledger_raw: bytes) -> list[dict[str, Any]]:
    _require(type(ledger_raw) is bytes, "promotion ledger input must be bytes")
    _require(len(ledger_raw) <= _MAX_ARTIFACT_BYTES, "promotion ledger is too large")
    _require(ledger_raw.endswith(b"\n"), "promotion ledger must end with LF")
    lines = ledger_raw.splitlines(keepends=True)
    _require(len(lines) == 4, "promotion ledger must contain exactly four events")
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        _require(
            line.endswith(b"\n") and bool(line.strip()),
            "promotion ledger line is invalid",
        )
        event = _require_object_fields(
            _decode_json_bytes(
                line,
                label=f"promotion ledger event {index}",
                require_canonical=True,
            ),
            _LEDGER_FIELDS,
            label=f"promotion ledger event {index}",
        )
        events.append(event)
    return events


def _validate_ledger(
    ledger_raw: bytes, decision: Mapping[str, Any]
) -> list[dict[str, Any]]:
    events = _parse_ledger(ledger_raw)
    _require(
        [event["sequence"] for event in events] == [1, 2, 3, 4]
        and all(type(event["sequence"]) is int for event in events),
        "promotion ledger sequences are not exact contiguous integers",
    )
    _require(
        [event["decisionId"] for event in events] == _EXPECTED_DECISION_IDS,
        "promotion ledger decision IDs are not the approved pairs",
    )
    _require(
        [event["state"] for event in events] == _EXPECTED_EVENT_STATES,
        "promotion ledger states are not the approved transitions",
    )
    _require(
        [event["eventDigest"] for event in events] == _EXPECTED_EVENT_DIGESTS,
        "promotion ledger event identities are not current",
    )
    _require(
        [event["promotionIntentDigest"] for event in events] == _EXPECTED_EVENT_INTENTS,
        "promotion ledger intent identities are not current",
    )

    previous: str | None = None
    state_by_decision: dict[str, str] = {}
    intent_by_decision: dict[str, str] = {}
    intent_owner: dict[str, str] = {}
    for event in events:
        _require(
            type(event["schemaVersion"]) is int and event["schemaVersion"] == 1,
            "promotion ledger schemaVersion is invalid",
        )
        _require(type(event["decisionId"]) is str, "ledger decisionId must be string")
        _require(type(event["state"]) is str, "ledger state must be string")
        _require_git_sha(event["headSha"], label="ledger headSha")
        for field in (
            "manifestDigest",
            "selectionDigest",
            "resourcesDigest",
            "profileDigest",
            "policyInputsDigest",
            "catalogBeforeDigest",
            "catalogAfterDigest",
            "promotionDigest",
            "promotionIntentDigest",
            "eventDigest",
        ):
            _require_sha256(event[field], label=f"ledger {field}")
        if event["predecessorDigest"] is not None:
            _require_sha256(
                event["predecessorDigest"], label="ledger predecessorDigest"
            )
        _require(
            event["predecessorDigest"] == previous,
            "promotion ledger predecessor chain is open",
        )
        digest_payload = dict(event)
        digest_payload.pop("eventDigest")
        _require(
            _sha256_canonical(digest_payload) == event["eventDigest"],
            "promotion ledger event digest does not match event fields",
        )
        _require(
            event["requiredOperations"] == _EXPECTED_REQUIRED_OPERATIONS
            and all(type(item) is str for item in event["requiredOperations"]),
            "promotion ledger requiredOperations are invalid",
        )
        intent_payload = {field: event[field] for field in _INTENT_FIELDS}
        _require(
            _sha256_canonical(intent_payload) == event["promotionIntentDigest"],
            "promotion ledger intent digest does not match event fields",
        )

        decision_id = event["decisionId"]
        prior_state = state_by_decision.get(decision_id)
        if prior_state is None:
            _require(
                event["state"] == "reserved", "ledger decision must begin reserved"
            )
            owner = intent_owner.get(event["promotionIntentDigest"])
            _require(owner in {None, decision_id}, "promotion ledger replays an intent")
            intent_owner[event["promotionIntentDigest"]] = decision_id
            intent_by_decision[decision_id] = event["promotionIntentDigest"]
        else:
            _require(
                event["promotionIntentDigest"] == intent_by_decision[decision_id],
                "promotion ledger pair changed intent",
            )
            allowed = {
                "reserved": {"applied", "revoked"},
                "applied": {"revoked"},
                "revoked": set(),
            }[prior_state]
            _require(
                event["state"] in allowed, "promotion ledger transition is invalid"
            )
        state_by_decision[decision_id] = event["state"]
        previous = event["eventDigest"]

    for first, second in ((events[0], events[1]), (events[2], events[3])):
        for field in _INTENT_FIELDS:
            _require(
                first[field] == second[field], f"promotion ledger pair changed {field}"
            )
    latest = events[-1]
    _require(latest["decisionId"] == decision["decisionId"], "latest event ID mismatch")
    _require(
        latest["promotionIntentDigest"] == decision["promotionIntentDigest"],
        "latest event intent mismatch",
    )
    for field in _INTENT_FIELDS:
        _require(latest[field] == decision[field], f"latest event {field} mismatch")
    return events


def _validate_receipt(
    receipt_raw: bytes, decision: Mapping[str, Any], decision_raw: bytes
) -> dict[str, Any]:
    receipt = _require_object_fields(
        _decode_json_bytes(
            receipt_raw, label="decision receipt", require_canonical=True
        ),
        _RECEIPT_FIELDS,
        label="decision receipt",
    )
    _require(
        type(receipt["schemaVersion"]) is int and receipt["schemaVersion"] == 1,
        "decision receipt schemaVersion is invalid",
    )
    _require(
        receipt["decisionId"] == decision["decisionId"],
        "decision receipt decision ID does not match",
    )
    _require(
        receipt["promotionIntentDigest"] == decision["promotionIntentDigest"],
        "decision receipt intent does not match",
    )
    _require_sha256(receipt["decisionDigest"], label="receipt decisionDigest")
    _require(
        receipt["decisionDigest"]
        == hashlib.sha256(decision_raw).hexdigest()
        == _EXPECTED_DECISION_DIGEST,
        "decision receipt digest does not match canonical decision bytes",
    )
    _require(
        type(receipt["grantsAuthority"]) is bool
        and receipt["grantsAuthority"] is False,
        "decision receipt must not grant authority",
    )
    _require(
        receipt["validatorVersion"] == _EXPECTED_VALIDATOR_VERSION,
        "decision receipt validator version is invalid",
    )
    _require(
        receipt["validatedAt"] == _EXPECTED_VALIDATED_AT,
        "decision receipt validation time is invalid",
    )
    return receipt


def _validate_envelope(
    envelope_raw: bytes,
    *,
    catalog: Mapping[str, Any],
    catalog_keys: list[str],
    catalog_digest: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = _require_object_fields(
        _decode_json_bytes(
            envelope_raw, label="approved envelope", require_canonical=True
        ),
        _ENVELOPE_FIELDS,
        label="approved envelope",
    )
    _require(
        type(envelope["schemaVersion"]) is int and envelope["schemaVersion"] == 1,
        "approved envelope schemaVersion is invalid",
    )
    _require(type(envelope["sourceCount"]) is int, "envelope sourceCount must be int")
    _require(type(envelope["sourceKeys"]) is list, "envelope sourceKeys must be list")
    _require(
        all(type(key) is str and bool(key) for key in envelope["sourceKeys"]),
        "envelope sourceKeys must be non-empty strings",
    )
    _require(
        envelope["sourceKeys"] == sorted(set(envelope["sourceKeys"])),
        "envelope sourceKeys must be sorted and unique",
    )
    _require(
        envelope["sourceKeys"] == catalog_keys,
        "envelope sourceKeys do not equal catalog keys",
    )
    _require(
        envelope["sourceCount"]
        == len(envelope["sourceKeys"])
        == catalog["count"]
        == _EXPECTED_CATALOG_COUNT,
        "envelope source count does not match catalog",
    )
    source_key_digest = _sha256_canonical(envelope["sourceKeys"])
    _require(
        envelope["sourceKeyDigest"] == source_key_digest == _EXPECTED_SOURCE_KEY_DIGEST,
        "envelope source-key digest does not match source keys",
    )
    _require(
        envelope["packagedCatalogFingerprint"]
        == catalog["fingerprint"]
        == _EXPECTED_CATALOG_FINGERPRINT,
        "envelope catalog fingerprint does not match catalog",
    )
    _require(
        envelope["catalogContentDigest"]
        == envelope["catalogTreeDigest"]
        == catalog_digest
        == _EXPECTED_CATALOG_SHA256,
        "envelope catalog content/tree digest does not match catalog",
    )
    _require(
        envelope["promotionDigest"]
        == decision["promotionDigest"]
        == _EXPECTED_PROMOTION_DIGEST,
        "envelope promotion digest does not match decision",
    )
    for field, expected in _EXPECTED_ENVELOPE_POLICY_DIGESTS.items():
        _require_sha256(envelope[field], label=f"envelope {field}")
        _require(envelope[field] == expected, f"envelope {field} is not current")
    _require_sha256(envelope["envelopeId"], label="envelope envelopeId")
    envelope_body = dict(envelope)
    envelope_body.pop("envelopeId")
    _require(
        _sha256_canonical(envelope_body)
        == envelope["envelopeId"]
        == _EXPECTED_ENVELOPE_ID,
        "envelope ID does not match envelope content",
    )
    return envelope


def _validate_promotion_digest(
    decision: Mapping[str, Any], source_key_digest: str, catalog_digest: str
) -> None:
    selection_digest = _sha256_canonical(
        {"candidateIds": [], "manifestDigest": decision["manifestDigest"]}
    )
    _require(
        selection_digest == decision["selectionDigest"] == _EXPECTED_SELECTION_DIGEST,
        "promotion selection digest does not match the empty selection",
    )
    _require(
        decision["catalogBeforeDigest"]
        == decision["catalogAfterDigest"]
        == catalog_digest,
        "decision before/after catalog digests do not match packaged catalog",
    )
    promotion_digest = _sha256_canonical(
        {
            "catalogAfterDigest": decision["catalogAfterDigest"],
            "catalogBeforeDigest": decision["catalogBeforeDigest"],
            "manifestDigest": decision["manifestDigest"],
            "policyInputsDigest": decision["policyInputsDigest"],
            "selectionDigest": decision["selectionDigest"],
            "sourceKeyDigest": source_key_digest,
        }
    )
    _require(
        promotion_digest == decision["promotionDigest"] == _EXPECTED_PROMOTION_DIGEST,
        "promotion digest does not match catalog and decision inputs",
    )


def _validate_promotion_artifacts(
    artifacts: Mapping[str, bytes],
) -> dict[str, object]:
    _require(
        set(artifacts) == {"catalog", "decision", "envelope", "ledger", "receipt"},
        "installed promotion artifact set is incomplete or ambiguous",
    )
    _require(
        all(type(value) is bytes for value in artifacts.values()),
        "installed promotion artifacts must be bytes",
    )
    catalog, catalog_keys, catalog_digest = _validate_catalog(artifacts["catalog"])
    decision = _validate_decision(artifacts["decision"])
    _validate_promotion_digest(decision, _EXPECTED_SOURCE_KEY_DIGEST, catalog_digest)
    events = _validate_ledger(artifacts["ledger"], decision)
    _validate_receipt(artifacts["receipt"], decision, artifacts["decision"])
    envelope = _validate_envelope(
        artifacts["envelope"],
        catalog=catalog,
        catalog_keys=catalog_keys,
        catalog_digest=catalog_digest,
        decision=decision,
    )
    _validate_promotion_digest(decision, envelope["sourceKeyDigest"], catalog_digest)
    return {
        "catalogCount": catalog["count"],
        "decisionId": decision["decisionId"],
        "eventStates": [event["state"] for event in events],
    }


def _read_required_wheel_artifacts(selected_wheel: Path) -> dict[str, bytes]:
    return _read_wheel_files(
        selected_wheel,
        _REQUIRED_ARTIFACT_PATHS,
        label="artifact",
        max_file_bytes=_MAX_ARTIFACT_BYTES,
        max_total_bytes=_MAX_ARTIFACT_BYTES,
    )


def _require_installed_artifacts_match_wheel(
    selected_wheel: Path, installed: Mapping[str, bytes]
) -> None:
    _require_installed_files_match_wheel(
        selected_wheel,
        installed,
        _REQUIRED_ARTIFACT_PATHS,
        label="artifact",
        max_file_bytes=_MAX_ARTIFACT_BYTES,
        max_total_bytes=_MAX_ARTIFACT_BYTES,
    )


def _read_required_record_artifacts(
    record_raw: bytes,
    distribution_root: Path,
    *,
    allowed_external_paths: frozenset[str] = frozenset(),
) -> dict[str, bytes]:
    return _read_recorded_installed_files(
        record_raw,
        distribution_root,
        _REQUIRED_ARTIFACT_PATHS,
        label="artifact",
        max_file_bytes=_MAX_ARTIFACT_BYTES,
        max_total_bytes=_MAX_ARTIFACT_BYTES,
        allowed_external_paths=allowed_external_paths,
    )


def _single_distribution_file(dist: Any, filename: str) -> Path:
    files = dist.files
    _require(files is not None, "installed distribution file inventory is unavailable")
    matches = [
        entry
        for entry in files
        if entry.name == filename
        and len(entry.parts) == 2
        and entry.parent.name.endswith(".dist-info")
    ]
    _require(
        len(matches) == 1,
        f"installed distribution must contain exactly one .dist-info/{filename}",
    )
    path = Path(dist.locate_file(matches[0]))
    _require(not path.is_symlink(), f"installed {filename} must not be a symlink")
    return path.resolve(strict=True)


def _installed_promotion_verifier(
    site_packages_value: str,
    wheel_value: str,
    selected_version: str,
    selected_sha256: str,
) -> None:
    site_packages = Path(site_packages_value).resolve(strict=True)
    selected_wheel = Path(wheel_value).resolve(strict=True)
    _require(site_packages.is_dir(), "fresh venv site-packages is not a directory")
    _require(
        selected_version == _EXPECTED_OPENOPPS_VERSION,
        "selected wheel version is not the current OpenOpps release",
    )
    _require(
        _sha256_file(selected_wheel) == selected_sha256,
        "selected wheel changed after discovery",
    )
    sys.path.insert(0, str(site_packages))

    from importlib.metadata import distribution

    dist = distribution("openopps")
    names = dist.metadata.get_all("Name", [])
    versions = dist.metadata.get_all("Version", [])
    _require(
        len(names) == 1
        and _catalog_smoke._canonical_project_name(names[0]) == "openopps",
        "installed distribution Name is missing or ambiguous",
    )
    _require(
        len(versions) == 1 and versions[0] == selected_version,
        "installed distribution version does not match selected wheel",
    )
    distribution_root = Path(str(dist.locate_file(""))).resolve(strict=True)
    _require(
        distribution_root == site_packages
        or distribution_root.is_relative_to(site_packages),
        "installed distribution root is outside the fresh venv",
    )
    direct_url_path = _single_distribution_file(dist, "direct_url.json")
    record_path = _single_distribution_file(dist, "RECORD")
    _require(
        direct_url_path.is_relative_to(distribution_root)
        and record_path.is_relative_to(distribution_root),
        "installed distribution metadata resolves outside its root",
    )
    direct_url_raw = _read_bounded_file(
        direct_url_path,
        limit=_catalog_smoke._MAX_DIRECT_URL_BYTES,
        label="installed direct_url.json",
    )
    record_raw = _read_bounded_file(
        record_path,
        limit=_catalog_smoke._MAX_RECORD_BYTES,
        label="installed RECORD",
    )
    _validate_direct_url(direct_url_raw, selected_wheel, selected_sha256)
    allowed_external_paths = _validated_external_record_paths(
        record_raw, distribution_root
    )
    installed = _read_required_record_artifacts(
        record_raw,
        distribution_root,
        allowed_external_paths=allowed_external_paths,
    )
    _require_installed_artifacts_match_wheel(selected_wheel, installed)
    _attest_installed_wheel_payload(
        selected_wheel,
        record_raw,
        distribution_root,
        selected_version,
        allowed_external_paths=allowed_external_paths,
        require_console_script=True,
    )
    _attest_installed_package(
        selected_wheel,
        record_raw,
        distribution_root,
        site_packages,
        allowed_external_paths=allowed_external_paths,
    )
    artifacts = {
        _ARTIFACT_KEYS_BY_PATH[relative]: payload
        for relative, payload in installed.items()
    }
    summary = _validate_promotion_artifacts(artifacts)
    print(summary["catalogCount"], summary["decisionId"], summary["eventStates"])


def _run_installed_promotion_verifier(
    python: Path,
    site_packages: Path,
    selected: Any,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    _run_isolated_function(
        python,
        Path(__file__),
        "_installed_promotion_verifier",
        [
            str(site_packages),
            str(selected.path),
            selected.version,
            selected.sha256,
        ],
        cwd=cwd,
        env=env,
    )


def main() -> int:
    args = _parse_args()
    uv = _validated_uv_bin(args.uv_bin)
    selected = _select_openopps_wheel(args.wheel_dir)
    _require(
        selected.version == _EXPECTED_OPENOPPS_VERSION,
        "selected wheel version is not the current OpenOpps release",
    )
    _preflight_wheel_archive(selected.path, required_paths=_REQUIRED_ARTIFACT_PATHS)
    _validate_openopps_wheel_layout(selected.path, selected.version)
    with tempfile.TemporaryDirectory(prefix="openopps-promotion-wheel-") as tmp:
        work_dir = Path(tmp)
        env = _sanitized_environment()
        python = _create_uv_venv(uv, work_dir / "venv", cwd=work_dir, env=env)
        _install_local_wheel(
            uv,
            python,
            selected.path,
            selected.sha256,
            cwd=work_dir,
            env=env,
            strict=False,
        )
        _run_installed_promotion_verifier(
            python,
            _venv_site_packages(work_dir / "venv"),
            selected,
            cwd=work_dir,
            env=env,
        )
    print("promotion-wheel-readback ok", selected.path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
