"""Adversarial coverage for discovery transport trust boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from openopps.discovery import transport
from openopps.discovery.transport import (
    ByteBudget,
    ContentLimits,
    DiscoveryTransportError,
    ResponseChunk,
    ResponseHead,
    read_bounded_response,
    validate_public_locator,
)


async def _chunks(*values: ResponseChunk) -> AsyncIterator[ResponseChunk]:
    for value in values:
        yield value


def _limits(
    *,
    max_json_depth: int = 16,
    max_xml_depth: int = 16,
) -> ContentLimits:
    return ContentLimits(
        max_encoded_bytes=16_384,
        max_decoded_bytes=16_384,
        max_json_depth=max_json_depth,
        max_xml_depth=max_xml_depth,
        max_html_nodes=128,
    )


async def _read_json(
    body: bytes,
    *,
    max_json_depth: int = 16,
) -> None:
    await read_bounded_response(
        ResponseHead(
            status_code=200,
            headers={
                "content-type": "application/json",
                "content-encoding": "identity",
            },
        ),
        _chunks(ResponseChunk(encoded=body, decoded=body)),
        limits=_limits(max_json_depth=max_json_depth),
        aggregate_budget=ByteBudget(limit=32_768),
    )


async def _read_xml(body: bytes, *, max_xml_depth: int = 16) -> None:
    await read_bounded_response(
        ResponseHead(
            status_code=200,
            headers={
                "content-type": "application/xml",
                "content-encoding": "identity",
            },
        ),
        _chunks(ResponseChunk(encoded=body, decoded=body)),
        limits=_limits(max_xml_depth=max_xml_depth),
        aggregate_budget=ByteBudget(limit=32_768),
    )


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("sig=synthetic", id="azure-sas-signature"),
        pytest.param("X-Goog-Signature=synthetic", id="google-signature"),
        pytest.param("AWSAccessKeyId=synthetic", id="legacy-aws-access-key"),
        pytest.param("%73ig=synthetic", id="encoded-signature-key"),
    ],
)
def test_signed_url_query_keys_are_rejected(query: str) -> None:
    with pytest.raises(DiscoveryTransportError) as caught:
        validate_public_locator(f"https://docs.example.test/jobs?{query}")

    assert caught.value.reason_code == "locator_secret_query"


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("unknown=value", id="unknown-key"),
        pytest.param("utm_source=campaign", id="tracking-key"),
        pytest.param("TEAM=platform", id="noncanonical-case"),
        pytest.param("te%61m=platform", id="encoded-allowlisted-key"),
        pytest.param("team=platform&team=security", id="duplicate-key"),
    ],
)
def test_query_keys_must_be_unique_canonical_and_allowlisted(query: str) -> None:
    with pytest.raises(DiscoveryTransportError) as caught:
        validate_public_locator(f"https://docs.example.test/jobs?{query}")

    assert caught.value.reason_code in {
        "locator_ambiguous",
        "locator_query_key",
    }


def test_safe_allowlisted_query_key_remains_usable() -> None:
    locator = validate_public_locator(
        "https://docs.example.test/jobs?team=platform&page=2"
    )

    assert locator.url == "https://docs.example.test/jobs?team=platform&page=2"


def test_nontransitional_idna_keeps_sharp_s_distinct_from_ascii_ss() -> None:
    sharp_s = validate_public_locator("https://faß.example/jobs")
    ascii_ss = validate_public_locator("https://fass.example/jobs")

    assert sharp_s.hostname == "xn--fa-hia.example"
    assert ascii_ss.hostname == "fass.example"
    assert sharp_s.origin != ascii_ss.origin


@pytest.mark.parametrize(
    ("body", "reason_code"),
    [
        pytest.param(b'{"key": 1, "key": 2}', "json_duplicate_key", id="duplicate"),
        pytest.param(b'{"value": NaN}', "json_nonfinite", id="nan"),
        pytest.param(b'{"value": Infinity}', "json_nonfinite", id="infinity"),
        pytest.param(b'{"value": -Infinity}', "json_nonfinite", id="negative-infinity"),
        pytest.param(b'{"value": 1e9999}', "json_nonfinite", id="float-overflow"),
    ],
)
async def test_hostile_json_ambiguity_is_rejected(
    body: bytes,
    reason_code: str,
) -> None:
    with pytest.raises(DiscoveryTransportError) as caught:
        await _read_json(body)

    assert caught.value.reason_code == reason_code


async def test_json_parser_recursion_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def recurse(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RecursionError("synthetic recursive parser detail")

    monkeypatch.setattr(transport.json, "loads", recurse)

    with pytest.raises(DiscoveryTransportError) as caught:
        await _read_json(b"{}")

    assert caught.value.reason_code == "parser_depth"
    assert "synthetic" not in str(caught.value)


async def test_deep_json_is_rejected_without_leaking_recursion_errors() -> None:
    body = (b"[" * 2_000) + (b"]" * 2_000)

    with pytest.raises(DiscoveryTransportError) as caught:
        await _read_json(body, max_json_depth=8)

    assert caught.value.reason_code == "parser_depth"


async def test_deep_xml_is_rejected_by_iterative_depth_validation() -> None:
    body = (b"<node>" * 1_000) + (b"</node>" * 1_000)

    with pytest.raises(DiscoveryTransportError) as caught:
        await _read_xml(body, max_xml_depth=8)

    assert caught.value.reason_code == "parser_depth"


async def test_xml_parser_recursion_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def recurse(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RecursionError("synthetic recursive XML parser detail")

    monkeypatch.setattr(transport.ElementTree, "fromstring", recurse)

    with pytest.raises(DiscoveryTransportError) as caught:
        await _read_xml(b"<root />")

    assert caught.value.reason_code == "xml_invalid"
    assert "synthetic" not in str(caught.value)


@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param(
            (ResponseChunk(encoded=b"safe", decoded=b"evil"),),
            id="same-size-different-content",
        ),
        pytest.param(
            (
                ResponseChunk(encoded=b"a", decoded=b""),
                ResponseChunk(encoded=b"", decoded=b"a"),
            ),
            id="cross-chunk-reassembly",
        ),
    ],
)
async def test_identity_encoding_requires_exact_chunk_bytes(
    chunks: tuple[ResponseChunk, ...],
) -> None:
    aggregate = ByteBudget(limit=128)

    with pytest.raises(DiscoveryTransportError) as caught:
        await read_bounded_response(
            ResponseHead(
                status_code=200,
                headers={
                    "content-type": "text/plain",
                    "content-encoding": "identity",
                },
            ),
            _chunks(*chunks),
            limits=_limits(),
            aggregate_budget=aggregate,
        )

    assert caught.value.reason_code == "identity_body_mismatch"
    assert aggregate.consumed == 0
