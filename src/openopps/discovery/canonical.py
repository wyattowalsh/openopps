"""Canonical JSON encoding for discovery artifacts.

Discovery artifacts intentionally use a smaller numeric domain than ordinary
JSON: booleans and integers are supported, while every floating-point lexical
form is rejected.  This keeps digest identities independent of runtime float
rendering and prevents numeric coercion at trust boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any, NoReturn


MAX_CANONICAL_JSON_DEPTH = 128
MAX_CANONICAL_JSON_NODES = 100_000


class CanonicalJSONError(ValueError):
    """Raised when a value or byte sequence is not canonical discovery JSON."""


def _reject_constant(value: str) -> NoReturn:
    del value
    raise CanonicalJSONError("non-finite JSON numbers are forbidden")


def _reject_float(value: str) -> NoReturn:
    del value
    raise CanonicalJSONError("floating-point JSON numbers are forbidden")


def _parse_int(value: str) -> int:
    if value == "-0":
        raise CanonicalJSONError("negative zero is forbidden")
    return int(value)


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError("duplicate object keys are forbidden")
        result[key] = value
    return result


def _validate_value(value: Any) -> None:
    """Validate iteratively so hostile nesting and cycles fail with bounded work."""

    pending: list[tuple[Any, int]] = [(value, 0)]
    observed_nodes = 0
    while pending:
        item, depth = pending.pop()
        observed_nodes += 1
        if observed_nodes > MAX_CANONICAL_JSON_NODES:
            raise CanonicalJSONError("canonical JSON exceeds its node limit")
        if depth > MAX_CANONICAL_JSON_DEPTH:
            raise CanonicalJSONError("canonical JSON exceeds its nesting limit")
        if item is None or isinstance(item, (bool, str, int)):
            continue
        if isinstance(item, float):
            raise CanonicalJSONError("floating-point values are forbidden")
        if isinstance(item, Mapping):
            if len(item) > MAX_CANONICAL_JSON_NODES - observed_nodes - len(pending):
                raise CanonicalJSONError("canonical JSON exceeds its node limit")
            children: list[tuple[Any, int]] = []
            for key, child in item.items():
                if not isinstance(key, str):
                    raise CanonicalJSONError(
                        "canonical JSON object keys must be strings"
                    )
                children.append((child, depth + 1))
            pending.extend(reversed(children))
            continue
        if isinstance(item, Sequence) and not isinstance(
            item, (bytes, bytearray, memoryview)
        ):
            if len(item) > MAX_CANONICAL_JSON_NODES - observed_nodes - len(pending):
                raise CanonicalJSONError("canonical JSON exceeds its node limit")
            pending.extend((child, depth + 1) for child in reversed(item))
            continue
        raise CanonicalJSONError("unsupported canonical JSON value")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode one value as sorted, compact UTF-8 JSON plus exactly one LF."""

    try:
        _validate_value(value)
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"{encoded}\n".encode("utf-8")
    except CanonicalJSONError:
        raise
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as error:
        raise CanonicalJSONError("value cannot be encoded as canonical JSON") from error


def decode_canonical_json(raw: bytes) -> Any:
    """Decode canonical discovery JSON and reject alternate wire spellings."""

    if not isinstance(raw, bytes):
        raise CanonicalJSONError("canonical JSON input must be bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CanonicalJSONError("UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CanonicalJSONError("canonical JSON must be valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
            parse_int=_parse_int,
        )
    except CanonicalJSONError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
        raise CanonicalJSONError("invalid canonical JSON") from error
    try:
        canonical = canonical_json_bytes(value)
    except RecursionError as error:  # Defensive guard around interpreter internals.
        raise CanonicalJSONError("canonical JSON exceeds its nesting limit") from error
    if canonical != raw:
        raise CanonicalJSONError("JSON bytes do not use the canonical encoding")
    return value
