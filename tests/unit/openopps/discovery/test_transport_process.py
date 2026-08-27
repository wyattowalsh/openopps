from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.metadata
import io
import json
import logging
from pathlib import Path

import pytest

import openopps.discovery.isolation as isolation_module
from openopps.discovery.bundle import (
    BUNDLE_SCHEMA_VERSION,
    BundleMemberSemanticContract,
    BundleResource,
    BundleVerificationPolicy,
    compute_manifest_id,
    compute_member_set_sha256,
    verify_bundle,
    write_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.isolation import (
    ApplicationFilesystem,
    IsolationError,
    ProcessResult,
    ScoutLaunchRequest,
    build_builtin_registry,
    build_credential_free_environment,
    launch_isolated_scout,
    validate_data_only_suggestion,
)
from openopps.discovery.models import (
    ChannelBudget,
    ChannelProfile,
    ObservedResource,
    TrustedDiscoveryProfile,
    WholeRunBudget,
)
from openopps.discovery.secrets import (
    SecretDetectedError,
    admit_scanned_content,
)
from openopps.discovery.transport import (
    ByteBudget,
    ContentLimits,
    DiscoveryTransportError,
    OperationLedger,
    RedirectPolicy,
    RequestBudgetLedger,
    ResponseChunk,
    ResponseHead,
    ScoutRequest,
    VerifiedObservation,
    bounded_retry_delay_ms,
    connect_pinned,
    prepare_redirect,
    read_bounded_response,
    resolve_public_addresses,
    safe_transport_diagnostic,
    select_verified_reuse,
    validate_public_locator,
)


PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_SECOND = "142.250.72.14"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _verified_observation(
    tmp_path: Path,
    content: bytes,
    *,
    tag: str,
) -> VerifiedObservation:
    content_sha256 = hashlib.sha256(content).hexdigest()
    profile_id = "transport-test-profile"
    profile_version = "1"
    profile_digest = "d" * 64
    configuration_sha256 = "c" * 64
    locator = validate_public_locator("https://docs.example.test/jobs")
    resource_id = f"resource-{tag}"
    profile = TrustedDiscoveryProfile(
        profile_id=profile_id,
        profile_version=profile_version,
        whole_run_budget=WholeRunBudget(
            request_limit=2,
            aggregate_byte_limit=4_096,
            candidate_limit=2,
            concurrency_limit=1,
            wall_clock_limit_ms=5_000,
        ),
        channels=(
            ChannelProfile(
                channel="official",
                budget=ChannelBudget(
                    query_limit=1,
                    request_limit=2,
                    origin_limit=1,
                    redirect_limit=1,
                    page_limit=1,
                    response_byte_limit=1_024,
                    aggregate_byte_limit=4_096,
                    candidate_limit=2,
                    concurrency_limit=1,
                    per_origin_concurrency_limit=1,
                    retry_limit=1,
                    parser_depth_limit=8,
                    wall_clock_limit_ms=5_000,
                ),
                seed_ids=("seed",),
                allowed_origins=(locator.origin,),
                allowed_query_keys=(),
                parser_ids=("parser-v1",),
            ),
        ),
        profile_digest=profile_digest,
    )
    observed_resource = ObservedResource(
        resource_id=resource_id,
        role="evidence",
        media_type="application/json",
        content_sha256=content_sha256,
        size_bytes=len(content),
        observed_at=NOW,
        final_locator=locator.url,
        validated_address=PUBLIC_V4,
        etag='"fixture-etag"',
    )
    resources = (
        BundleResource(
            data=content,
            media_type="application/json",
            path=f"resources/{tag}.json",
            provenance_id=resource_id,
            role="evidence",
        ),
        BundleResource(
            data=canonical_json_bytes(
                observed_resource.model_dump(
                    mode="json", by_alias=True, round_trip=True
                )
            ),
            media_type="application/json",
            path=f"semantic/{tag}.observed.json",
            provenance_id=resource_id,
            role="observed-resource",
        ),
        BundleResource(
            data=canonical_json_bytes(
                profile.model_dump(mode="json", by_alias=True, round_trip=True)
            ),
            media_type="application/json",
            path=f"semantic/{tag}.profile.json",
            provenance_id=profile_digest,
            role="trusted-profile",
        ),
    )
    members = [
        {
            "mediaType": resource.media_type,
            "path": resource.path,
            "provenanceId": resource.provenance_id,
            "role": resource.role,
            "sha256": hashlib.sha256(resource.data).hexdigest(),
            "sizeBytes": len(resource.data),
        }
        for resource in resources
    ]
    manifest: dict[str, object] = {
        "configurationSha256": configuration_sha256,
        "executionId": f"transport-test-{tag}",
        "manifestId": "",
        "memberCount": len(members),
        "members": members,
        "memberSetSha256": compute_member_set_sha256(members),
        "observedAt": NOW.isoformat().replace("+00:00", "Z"),
        "profileId": profile_id,
        "profileVersion": profile_version,
        "runState": "complete",
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "toolVersion": "0.1.0",
    }
    manifest["manifestId"] = compute_manifest_id(manifest)
    policy = BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=2),
        now=NOW,
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({(profile_id, profile_version)}),
        supported_schema_versions=frozenset({BUNDLE_SCHEMA_VERSION}),
        required_member_roles=frozenset(
            {"evidence", "observed-resource", "trusted-profile"}
        ),
        supported_member_roles=frozenset(
            {"evidence", "observed-resource", "trusted-profile"}
        ),
        canonical_json_roles=frozenset({"observed-resource", "trusted-profile"}),
        semantic_member_contracts={
            "observed-resource": BundleMemberSemanticContract(
                model_name="ObservedResource"
            ),
            "trusted-profile": BundleMemberSemanticContract(
                model_name="TrustedDiscoveryProfile",
                schema_version_field="schemaVersion",
                supported_schema_versions=frozenset({1}),
            ),
        },
    )
    bundle_root = write_bundle(
        tmp_path / f"quarantine-{tag}",
        manifest=manifest,
        resources=resources,
        verification_policy=policy,
    )
    verified_bundle = verify_bundle(bundle_root, policy=policy)
    observation = VerifiedObservation.from_verified_bundle(
        verified_bundle=verified_bundle,
        expected_locator=locator,
        expected_profile_id=profile_id,
        expected_profile_version=profile_version,
        expected_profile_digest=profile_digest,
        expected_configuration_sha256=configuration_sha256,
    )
    assert observation is not None
    return observation


class FakeResolver:
    def __init__(
        self,
        answers: tuple[str, ...] = (PUBLIC_V4,),
        *,
        later_answers: tuple[str, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answers = answers
        self.later_answers = later_answers
        self.error = error
        self.calls: list[str] = []

    async def __call__(self, hostname: str) -> tuple[str, ...]:
        self.calls.append(hostname)
        if self.error is not None:
            raise self.error
        if self.later_answers is not None and len(self.calls) > 1:
            return self.later_answers
        return self.answers


@dataclass
class FakeConnection:
    peer_address: str
    closed: bool = False

    async def aclose(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, *, peer_address: str | None = None) -> None:
        self.peer_address = peer_address
        self.calls: list[dict[str, object]] = []
        self.connections: list[FakeConnection] = []

    async def __call__(
        self,
        *,
        address: str,
        port: int,
        server_hostname: str,
    ) -> FakeConnection:
        self.calls.append(
            {
                "address": address,
                "port": port,
                "server_hostname": server_hostname,
            }
        )
        connection = FakeConnection(self.peer_address or address)
        self.connections.append(connection)
        return connection


async def _chunks(*chunks: ResponseChunk) -> AsyncIterator[ResponseChunk]:
    for chunk in chunks:
        yield chunk


def _head(**headers: str) -> ResponseHead:
    return ResponseHead(status_code=200, headers=headers)


def _limits(**overrides: int) -> ContentLimits:
    values = {
        "max_encoded_bytes": 128,
        "max_decoded_bytes": 128,
        "max_json_depth": 4,
        "max_xml_depth": 4,
        "max_html_nodes": 8,
    }
    values.update(overrides)
    return ContentLimits(**values)


def _assert_safe_error(exc: Exception, *, unsafe: str) -> None:
    rendered = (
        str(exc),
        repr(exc),
        json.dumps(safe_transport_diagnostic(exc), sort_keys=True),
        json.dumps(vars(exc), default=repr, sort_keys=True),
    )
    assert all(unsafe not in value for value in rendered)


# T121: locator policy rejects every credential-bearing or ambiguous form before DNS.
@pytest.mark.parametrize(
    ("locator", "reason_code"),
    [
        pytest.param(
            "https://user:synthetic-pass@docs.example.test/jobs",
            "locator_userinfo",
            id="userinfo",
        ),
        pytest.param(
            "https://docs.example.test/jobs#credential-fragment",
            "locator_fragment",
            id="fragment",
        ),
        pytest.param(
            "http://docs.example.test/jobs",
            "locator_scheme",
            id="cleartext-scheme",
        ),
        pytest.param(
            "file:///etc/passwd",
            "locator_scheme",
            id="local-file-scheme",
        ),
        pytest.param(
            "https://docs.example.test:444/jobs",
            "locator_port",
            id="untrusted-port",
        ),
        pytest.param(
            "https://127.0.0.1/jobs",
            "locator_ip_literal",
            id="ipv4-literal",
        ),
        pytest.param(
            "https://[::1]/jobs",
            "locator_ip_literal",
            id="ipv6-literal",
        ),
        pytest.param(
            "https://localhost/jobs",
            "locator_localhost",
            id="localhost",
        ),
        pytest.param(
            "https://docs.example.test/jobs?access_token=synthetic-token",
            "locator_secret_query",
            id="credential-query",
        ),
        pytest.param(
            "https://docs.example.test/jobs?X-Amz-Signature=synthetic-signature",
            "locator_secret_query",
            id="signed-query",
        ),
    ],
)
def test_locator_policy_rejects_unsafe_inputs_without_resolving(
    locator: str,
    reason_code: str,
) -> None:
    with pytest.raises(DiscoveryTransportError) as caught:
        validate_public_locator(locator)

    assert caught.value.reason_code == reason_code
    _assert_safe_error(caught.value, unsafe=locator)


def test_locator_policy_accepts_only_canonical_https_authority() -> None:
    locator = validate_public_locator("https://BÜCHER.example/jobs?team=platform")

    assert locator.hostname == "xn--bcher-kva.example"
    assert locator.port == 443
    assert locator.origin == "https://xn--bcher-kva.example:443"
    assert locator.url == "https://xn--bcher-kva.example/jobs?team=platform"


# T122: resolver output is fail-closed and must contain only plain global addresses.
@pytest.mark.parametrize(
    ("answers", "reason_code"),
    [
        pytest.param((), "dns_empty", id="empty-answer-set"),
        pytest.param(
            (PUBLIC_V4, "10.0.0.8"),
            "dns_mixed_scope",
            id="mixed-public-private",
        ),
        pytest.param(("10.0.0.8",), "dns_non_global", id="private"),
        pytest.param(
            ("169.254.169.254",),
            "dns_non_global",
            id="metadata-link-local",
        ),
        pytest.param(("127.0.0.1",), "dns_non_global", id="loopback"),
        pytest.param(
            ("::ffff:93.184.216.34",),
            "dns_ipv4_mapped",
            id="ipv4-mapped-ipv6",
        ),
        pytest.param(
            ("fe80::1%en0",),
            "dns_zone_identifier",
            id="ipv6-zone-identifier",
        ),
    ],
)
async def test_dns_answer_sets_fail_closed(
    answers: tuple[str, ...],
    reason_code: str,
) -> None:
    resolver = FakeResolver(answers)

    with pytest.raises(DiscoveryTransportError) as caught:
        await resolve_public_addresses(
            validate_public_locator("https://docs.example.test/jobs"),
            resolver=resolver,
        )

    assert caught.value.reason_code == reason_code
    assert resolver.calls == ["docs.example.test"]


async def test_dns_failure_is_not_treated_as_permission_to_connect() -> None:
    resolver = FakeResolver(error=OSError("synthetic resolver detail"))

    with pytest.raises(DiscoveryTransportError) as caught:
        await resolve_public_addresses(
            validate_public_locator("https://docs.example.test/jobs"),
            resolver=resolver,
        )

    assert caught.value.reason_code == "dns_failure"
    assert "synthetic resolver detail" not in str(caught.value)


@pytest.mark.parametrize(
    "locator",
    [
        pytest.param("https://2130706433/jobs", id="integer-ipv4"),
        pytest.param("https://0177.0.0.1/jobs", id="octal-ipv4"),
        pytest.param("https://0x7f000001/jobs", id="hex-ipv4"),
        pytest.param("https://exa\u200dmple.test/jobs", id="unsafe-idna-joiner"),
        pytest.param("https://example%2etest/jobs", id="encoded-host-separator"),
    ],
)
def test_numeric_ip_and_unsafe_idna_locator_forms_are_rejected(locator: str) -> None:
    with pytest.raises(DiscoveryTransportError):
        validate_public_locator(locator)


async def test_public_dns_answers_are_sorted_and_deduplicated() -> None:
    resolved = await resolve_public_addresses(
        validate_public_locator("https://docs.example.test/jobs"),
        resolver=FakeResolver((PUBLIC_V6, PUBLIC_V4, PUBLIC_V4)),
    )

    assert resolved.hostname == "docs.example.test"
    assert resolved.addresses == (PUBLIC_V4, PUBLIC_V6)


# T123: the connector receives a vetted numeric address and the original TLS name.
async def test_pinned_connect_uses_one_exact_vetted_dns_answer_set() -> None:
    resolver = FakeResolver(
        (PUBLIC_V4,),
        later_answers=("127.0.0.1",),
    )
    connector = FakeConnector()

    connection = await connect_pinned(
        validate_public_locator("https://docs.example.test/jobs"),
        resolver=resolver,
        connector=connector,
    )

    assert connection.peer_address == PUBLIC_V4
    assert resolver.calls == ["docs.example.test"]
    assert connector.calls == [
        {
            "address": PUBLIC_V4,
            "port": 443,
            "server_hostname": "docs.example.test",
        }
    ]


async def test_pinned_connect_rejects_a_peer_outside_the_vetted_set() -> None:
    connector = FakeConnector(peer_address="127.0.0.1")

    with pytest.raises(DiscoveryTransportError) as caught:
        await connect_pinned(
            validate_public_locator("https://docs.example.test/jobs"),
            resolver=FakeResolver((PUBLIC_V4, PUBLIC_V4_SECOND)),
            connector=connector,
        )

    assert caught.value.reason_code == "peer_address_mismatch"
    assert connector.connections[0].closed is True


# T124: every redirect is revalidated, loop-bounded, and data-free.
def _request(locator: str = "https://docs.example.test/start") -> ScoutRequest:
    return ScoutRequest(
        method="POST",
        locator=validate_public_locator(locator),
        headers={
            "authorization": "Bearer synthetic-value",
            "cookie": "session=synthetic-value",
            "x-caller-header": "synthetic-value",
        },
        body=b"synthetic request body",
    )


def _redirect_policy(**overrides: object) -> RedirectPolicy:
    values: dict[str, object] = {
        "max_hops": 2,
        "allowed_cross_origin": frozenset({("docs.example.test", "api.example.test")}),
    }
    values.update(overrides)
    return RedirectPolicy(**values)


@pytest.mark.parametrize(
    ("location", "history", "reason_code"),
    [
        pytest.param(
            "https://127.0.0.1/private",
            ("https://docs.example.test/start",),
            "locator_ip_literal",
            id="private-target",
        ),
        pytest.param(
            "http://docs.example.test/cleartext",
            ("https://docs.example.test/start",),
            "locator_scheme",
            id="downgrade",
        ),
        pytest.param(
            "file:///etc/passwd",
            ("https://docs.example.test/start",),
            "locator_scheme",
            id="file-location",
        ),
        pytest.param(
            "https://untrusted.example.test/path",
            ("https://docs.example.test/start",),
            "redirect_origin",
            id="disallowed-origin",
        ),
        pytest.param(
            "https://user:synthetic@api.example.test/path",
            ("https://docs.example.test/start",),
            "locator_userinfo",
            id="redirect-credentials",
        ),
        pytest.param(
            "https://docs.example.test\\@untrusted.example.test/path",
            ("https://docs.example.test/start",),
            "locator_ambiguous",
            id="ambiguous-authority",
        ),
        pytest.param(
            "/start",
            ("https://docs.example.test/start",),
            "redirect_loop",
            id="loop",
        ),
        pytest.param(
            "/third",
            (
                "https://docs.example.test/start",
                "https://docs.example.test/second",
                "https://docs.example.test/other",
            ),
            "redirect_limit",
            id="excess-hops",
        ),
    ],
)
def test_redirect_attack_matrix_fails_closed(
    location: str,
    history: tuple[str, ...],
    reason_code: str,
) -> None:
    with pytest.raises(DiscoveryTransportError) as caught:
        prepare_redirect(
            _request(),
            location=location,
            history=history,
            policy=_redirect_policy(),
        )

    assert caught.value.reason_code == reason_code


def test_allowed_redirect_strips_headers_and_body_regardless_of_status() -> None:
    redirected = prepare_redirect(
        _request(),
        location="https://api.example.test/jobs",
        history=("https://docs.example.test/start",),
        policy=_redirect_policy(),
    )

    assert redirected.locator.hostname == "api.example.test"
    assert redirected.method == "GET"
    assert redirected.body is None
    assert redirected.headers == {}


# T125: response admission is streaming, exact, structurally bounded, and inert.
async def test_content_length_over_limit_rejects_before_reading_body() -> None:
    reads = 0

    async def body() -> AsyncIterator[ResponseChunk]:
        nonlocal reads
        reads += 1
        yield ResponseChunk(encoded=b"x", decoded=b"x")

    with pytest.raises(DiscoveryTransportError) as caught:
        await read_bounded_response(
            _head(
                **{
                    "content-type": "application/json",
                    "content-length": "129",
                    "content-encoding": "identity",
                }
            ),
            body(),
            limits=_limits(max_encoded_bytes=128),
            aggregate_budget=ByteBudget(limit=1024),
        )

    assert caught.value.reason_code == "response_too_large"
    assert reads == 0


@pytest.mark.parametrize(
    ("head", "chunks", "reason_code"),
    [
        pytest.param(
            _head(
                **{
                    "content-type": "application/json",
                    "content-length": "2",
                    "content-encoding": "identity",
                }
            ),
            (ResponseChunk(encoded=b"{}\n", decoded=b"{}\n"),),
            "content_length_mismatch",
            id="lying-content-length",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "application/json",
                    "transfer-encoding": "chunked",
                    "content-encoding": "identity",
                }
            ),
            (
                ResponseChunk(encoded=b"1234", decoded=b"1234"),
                ResponseChunk(encoded=b"5678", decoded=b"5678"),
            ),
            "response_too_large",
            id="chunked-overflow",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                }
            ),
            (ResponseChunk(encoded=b"gzip", decoded=b"expanded"),),
            "unsupported_content_encoding",
            id="compression",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "application/zip",
                    "content-encoding": "identity",
                }
            ),
            (ResponseChunk(encoded=b"PK", decoded=b"PK"),),
            "unsupported_media_type",
            id="archive",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "multipart/form-data; boundary=x",
                    "content-encoding": "identity",
                }
            ),
            (ResponseChunk(encoded=b"--x", decoded=b"--x"),),
            "unsupported_media_type",
            id="multipart",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "text/plain",
                    "content-disposition": 'attachment; filename="payload.txt"',
                    "content-encoding": "identity",
                }
            ),
            (ResponseChunk(encoded=b"payload", decoded=b"payload"),),
            "server_selected_filename",
            id="server-selected-filename",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "application/json",
                    "content-encoding": "identity",
                }
            ),
            (
                ResponseChunk(
                    encoded=b'{"a":{"b":{"c":{"d":{"e":1}}}}}',
                    decoded=b'{"a":{"b":{"c":{"d":{"e":1}}}}}',
                ),
            ),
            "parser_depth",
            id="json-depth-bomb",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "application/xml",
                    "content-encoding": "identity",
                }
            ),
            (
                ResponseChunk(
                    encoded=b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>',
                    decoded=b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>',
                ),
            ),
            "xml_entity",
            id="xml-entity-bomb",
        ),
        pytest.param(
            _head(
                **{
                    "content-type": "text/html",
                    "content-encoding": "identity",
                }
            ),
            (
                ResponseChunk(
                    encoded=b"<i></i>" * 9,
                    decoded=b"<i></i>" * 9,
                ),
            ),
            "html_node_limit",
            id="html-node-bomb",
        ),
    ],
)
async def test_hostile_response_matrix_is_rejected(
    head: ResponseHead,
    chunks: tuple[ResponseChunk, ...],
    reason_code: str,
) -> None:
    limits = _limits(
        max_encoded_bytes=7 if reason_code == "response_too_large" else 128
    )

    with pytest.raises(DiscoveryTransportError) as caught:
        await read_bounded_response(
            head,
            _chunks(*chunks),
            limits=limits,
            aggregate_budget=ByteBudget(limit=1024),
        )

    assert caught.value.reason_code == reason_code


async def test_decoded_and_aggregate_byte_budgets_are_independent() -> None:
    with pytest.raises(DiscoveryTransportError) as decoded_error:
        await read_bounded_response(
            _head(
                **{
                    "content-type": "text/plain",
                    "content-encoding": "identity",
                }
            ),
            _chunks(ResponseChunk(encoded=b"1234", decoded=b"123456")),
            limits=_limits(max_encoded_bytes=4, max_decoded_bytes=5),
            aggregate_budget=ByteBudget(limit=20),
        )
    assert decoded_error.value.reason_code == "decoded_body_too_large"

    aggregate = ByteBudget(limit=5)
    admitted = await read_bounded_response(
        _head(
            **{
                "content-type": "text/plain",
                "content-length": "4",
                "content-encoding": "identity",
            }
        ),
        _chunks(ResponseChunk(encoded=b"1234", decoded=b"1234")),
        limits=_limits(),
        aggregate_budget=aggregate,
    )
    assert admitted.body == b"1234"
    assert admitted.encoded_bytes == 4
    assert admitted.decoded_bytes == 4
    assert aggregate.consumed == 4
    assert aggregate.remaining == 1

    with pytest.raises(DiscoveryTransportError) as aggregate_error:
        await read_bounded_response(
            _head(
                **{
                    "content-type": "text/plain",
                    "content-length": "2",
                    "content-encoding": "identity",
                }
            ),
            _chunks(ResponseChunk(encoded=b"56", decoded=b"56")),
            limits=_limits(),
            aggregate_budget=aggregate,
        )
    assert aggregate_error.value.reason_code == "aggregate_byte_budget"


# T126: retries, redirects, pages, and cancellations share one attempt ledger.
def _ledger(**overrides: int) -> RequestBudgetLedger:
    values = {
        "request_limit": 5,
        "origin_limit": 1,
        "max_in_flight": 2,
        "per_origin_in_flight_limit": 2,
        "retry_limit": 1,
        "redirect_limit": 1,
        "pagination_limit": 1,
        "deadline_ms": 10_000,
    }
    values.update(overrides)
    return RequestBudgetLedger(**values)


def test_request_ledger_conserves_reserved_consumed_and_remaining() -> None:
    ledger = _ledger(request_limit=4)

    initial = ledger.reserve(
        kind="initial",
        origin="https://docs.example.test:443",
        now_ms=1,
    )
    retry = ledger.reserve(
        kind="retry",
        origin="https://docs.example.test:443",
        now_ms=2,
    )
    snapshot = ledger.snapshot()
    assert snapshot.limit == 4
    assert snapshot.consumed == 0
    assert snapshot.in_flight == 2
    assert snapshot.remaining == 2
    assert snapshot.consumed + snapshot.in_flight + snapshot.remaining == 4

    ledger.finish(initial, outcome="rate_limited", admitted_bytes=0)
    ledger.finish(retry, outcome="cancelled", admitted_bytes=0)
    snapshot = ledger.snapshot()
    assert snapshot.consumed == 2
    assert snapshot.in_flight == 0
    assert snapshot.remaining == 2
    assert snapshot.outcomes == {"cancelled": 1, "rate_limited": 1}
    assert snapshot.attempt_kinds == {"initial": 1, "retry": 1}


def test_operation_ledger_closes_every_planned_denominator_member_once() -> None:
    ledger = OperationLedger(
        planned_operation_ids=("catalog", "retry", "page", "never-launched")
    )

    ledger.start("catalog")
    ledger.finish("catalog", outcome="succeeded")
    ledger.start("retry")
    ledger.finish("retry", outcome="rate_limited")
    ledger.start("page")
    ledger.finish("page", outcome="cancelled")
    ledger.finish("never-launched", outcome="unstarted")
    snapshot = ledger.close(channel_state="partial")

    assert snapshot.planned == 4
    assert snapshot.terminals == {
        "blocked": 0,
        "cancelled": 1,
        "failed": 0,
        "rate_limited": 1,
        "succeeded": 1,
        "timed_out": 0,
        "unstarted": 1,
    }
    assert sum(snapshot.terminals.values()) == snapshot.planned
    assert snapshot.channel_state == "partial"


def test_run_level_aborted_is_not_an_operation_terminal() -> None:
    ledger = OperationLedger(planned_operation_ids=("planned",))

    with pytest.raises(DiscoveryTransportError) as caught:
        ledger.finish("planned", outcome="aborted")

    assert caught.value.reason_code == "operation_outcome"


@pytest.mark.parametrize(
    ("operation", "reason_code"),
    [
        pytest.param("retry", "retry_budget", id="retry"),
        pytest.param("redirect", "redirect_budget", id="redirect"),
        pytest.param("pagination", "pagination_budget", id="pagination"),
    ],
)
def test_attempt_kind_limits_are_finite(
    operation: str,
    reason_code: str,
) -> None:
    ledger = _ledger()
    first = ledger.reserve(
        kind=operation,
        origin="https://docs.example.test:443",
        now_ms=1,
    )
    ledger.finish(first, outcome="failed", admitted_bytes=0)

    with pytest.raises(DiscoveryTransportError) as caught:
        ledger.reserve(
            kind=operation,
            origin="https://docs.example.test:443",
            now_ms=2,
        )

    assert caught.value.reason_code == reason_code


def test_request_ledger_enforces_origin_concurrency_and_deadline_limits() -> None:
    origin_ledger = _ledger(origin_limit=1)
    origin_ledger.reserve(
        kind="initial",
        origin="https://docs.example.test:443",
        now_ms=1,
    )
    with pytest.raises(DiscoveryTransportError) as origin_error:
        origin_ledger.reserve(
            kind="initial",
            origin="https://api.example.test:443",
            now_ms=2,
        )
    assert origin_error.value.reason_code == "origin_budget"

    concurrency_ledger = _ledger(max_in_flight=1)
    concurrency_ledger.reserve(
        kind="initial",
        origin="https://docs.example.test:443",
        now_ms=1,
    )
    with pytest.raises(DiscoveryTransportError) as concurrency_error:
        concurrency_ledger.reserve(
            kind="initial",
            origin="https://docs.example.test:443",
            now_ms=2,
        )
    assert concurrency_error.value.reason_code == "concurrency_budget"

    deadline_ledger = _ledger(deadline_ms=10)
    with pytest.raises(DiscoveryTransportError) as deadline_error:
        deadline_ledger.reserve(
            kind="initial",
            origin="https://docs.example.test:443",
            now_ms=10,
        )
    assert deadline_error.value.reason_code == "deadline_exhausted"
    assert deadline_ledger.snapshot().remaining == deadline_ledger.snapshot().limit


def test_request_ledger_applies_per_origin_limit_below_global_limit() -> None:
    ledger = _ledger(
        origin_limit=2,
        max_in_flight=2,
        per_origin_in_flight_limit=1,
    )
    first = ledger.reserve(
        kind="initial",
        origin="https://docs.example.test:443",
        now_ms=1,
    )

    with pytest.raises(DiscoveryTransportError) as caught:
        ledger.reserve(
            kind="initial",
            origin="https://docs.example.test:443",
            now_ms=2,
        )
    assert caught.value.reason_code == "origin_concurrency_budget"

    second = ledger.reserve(
        kind="initial",
        origin="https://api.example.test:443",
        now_ms=2,
    )
    snapshot = ledger.snapshot()
    assert snapshot.in_flight == 2
    ledger.finish(first, outcome="succeeded", admitted_bytes=0)
    ledger.finish(second, outcome="succeeded", admitted_bytes=0)
    assert ledger.snapshot().in_flight == 0


def test_total_request_budget_cannot_be_amplified_by_attempt_kind() -> None:
    ledger = _ledger(request_limit=2, retry_limit=2, redirect_limit=2)
    for kind in ("initial", "retry"):
        reservation = ledger.reserve(
            kind=kind,
            origin="https://docs.example.test:443",
            now_ms=1,
        )
        ledger.finish(reservation, outcome="failed", admitted_bytes=0)

    with pytest.raises(DiscoveryTransportError) as caught:
        ledger.reserve(
            kind="redirect",
            origin="https://docs.example.test:443",
            now_ms=2,
        )

    assert caught.value.reason_code == "request_budget"
    snapshot = ledger.snapshot()
    assert snapshot.consumed == 2
    assert snapshot.in_flight == 0
    assert snapshot.remaining == 0


def test_retry_after_never_extends_the_deadline_or_trusted_delay_cap() -> None:
    assert (
        bounded_retry_delay_ms(
            "2",
            now_ms=1_000,
            deadline_ms=5_000,
            max_delay_ms=3_000,
        )
        == 2_000
    )

    with pytest.raises(DiscoveryTransportError) as deadline_error:
        bounded_retry_delay_ms(
            "10",
            now_ms=1_000,
            deadline_ms=5_000,
            max_delay_ms=30_000,
        )
    assert deadline_error.value.reason_code == "retry_after_deadline"

    with pytest.raises(DiscoveryTransportError) as cap_error:
        bounded_retry_delay_ms(
            "4",
            now_ms=1_000,
            deadline_ms=10_000,
            max_delay_ms=3_000,
        )
    assert cap_error.value.reason_code == "retry_after_limit"


# T127: durable and emitted diagnostics contain codes, never hostile locators.
def test_transport_errors_are_safe_for_logs_metrics_bundles_and_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unsafe_locator = (
        "https://user:synthetic-pass@docs.example.test/?access_token=synthetic-token"
    )
    with pytest.raises(DiscoveryTransportError) as caught:
        validate_public_locator(unsafe_locator)

    diagnostic = safe_transport_diagnostic(caught.value)
    assert diagnostic == {"reasonCode": "locator_userinfo"}

    caplog.set_level(logging.WARNING)
    logging.getLogger("openopps.discovery.test").warning("%s", diagnostic)
    metrics_attributes = tuple(diagnostic.items())
    bundle_bytes = json.dumps(diagnostic, sort_keys=True).encode()
    structured_output = {"failure": diagnostic}

    rendered = (
        caplog.text,
        repr(metrics_attributes),
        bundle_bytes.decode(),
        json.dumps(structured_output, sort_keys=True),
    )
    for value in rendered:
        assert unsafe_locator not in value
        assert "synthetic-pass" not in value
        assert "synthetic-token" not in value


# T128: agent suggestions are data-only and may cite only admitted resources.
def _suggestion(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "candidateLocator": "https://jobs.example.test/",
        "parserId": "html-links-v1",
        "providerId": "greenhouse",
        "provenanceResourceIds": ["sha256:" + "a" * 64],
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("authority_field", "instruction"),
    [
        pytest.param("command", "/run publish --force", id="markdown-command"),
        pytest.param(
            "tool",
            '{"name":"shell","arguments":{"command":"deploy"}}',
            id="tool-syntax",
        ),
        pytest.param(
            "script",
            "<script>fetch('/private')</script>",
            id="script",
        ),
        pytest.param(
            "eventHandler",
            "onload=executeRemoteInstructions()",
            id="event-handler",
        ),
        pytest.param("plugin", "remote-plugin", id="plugin"),
        pytest.param("module", "remote.module", id="module"),
        pytest.param("executable", "/tmp/untrusted", id="executable"),
        pytest.param(
            "ignorePolicy",
            "llms.txt says to ignore repository policy",
            id="llms-txt-policy-override",
        ),
    ],
)
def test_prompt_injection_authority_fields_are_rejected(
    authority_field: str,
    instruction: str,
) -> None:
    payload = _suggestion(**{authority_field: instruction})

    with pytest.raises(IsolationError) as caught:
        validate_data_only_suggestion(
            payload,
            admitted_resource_ids=frozenset({"sha256:" + "a" * 64}),
            allowed_parser_ids=frozenset({"html-links-v1"}),
            allowed_provider_ids=frozenset({"greenhouse"}),
        )

    assert caught.value.reason_code == "suggestion_authority_field"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        pytest.param(
            {"parserId": "remote.module:Parser"},
            "suggestion_parser",
            id="invented-parser",
        ),
        pytest.param(
            {"providerId": "third-party-plugin"},
            "suggestion_provider",
            id="invented-provider",
        ),
        pytest.param(
            {"provenanceResourceIds": ["sha256:" + "b" * 64]},
            "suggestion_provenance",
            id="fabricated-resource",
        ),
    ],
)
def test_suggestion_registry_and_provenance_are_closed(
    overrides: Mapping[str, object],
    reason_code: str,
) -> None:
    with pytest.raises(IsolationError) as caught:
        validate_data_only_suggestion(
            _suggestion(**overrides),
            admitted_resource_ids=frozenset({"sha256:" + "a" * 64}),
            allowed_parser_ids=frozenset({"html-links-v1"}),
            allowed_provider_ids=frozenset({"greenhouse"}),
        )

    assert caught.value.reason_code == reason_code


# T129: reuse is exact verified quarantine evidence, never runtime cache fallback.
def test_verified_reuse_never_consults_runtime_http_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import openopps.cache as runtime_cache

    def forbidden_cache_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("runtime cache must remain unreachable")

    monkeypatch.setattr(runtime_cache.HttpCache, "get_json", forbidden_cache_read)
    monkeypatch.setattr(
        runtime_cache.HttpCache,
        "get_stale_json",
        forbidden_cache_read,
    )
    content = b'{"jobs":[]}\n'
    observation = _verified_observation(tmp_path, content, tag="cache-independent")

    reused = select_verified_reuse(
        observation,
        now=NOW + timedelta(hours=1),
        max_age=timedelta(hours=2),
    )

    assert reused is observation


def test_stale_or_digest_mismatched_observation_cannot_be_reused(
    tmp_path: Path,
) -> None:
    content = b"captured evidence"
    valid = _verified_observation(tmp_path, content, tag="stale")
    mismatched = _verified_observation(tmp_path, content, tag="digest-mismatch")
    object.__setattr__(mismatched, "content_sha256", "0" * 64)

    assert (
        select_verified_reuse(
            valid,
            now=NOW + timedelta(hours=3),
            max_age=timedelta(hours=2),
        )
        is None
    )
    with pytest.raises(DiscoveryTransportError) as caught:
        select_verified_reuse(
            mismatched,
            now=NOW + timedelta(minutes=1),
            max_age=timedelta(hours=2),
        )
    assert caught.value.reason_code == "verified_evidence_digest"


# T130: the scout registry is explicit and never consults installed entry points.
def test_builtin_registry_ignores_plugin_autoload_and_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_entry_points(*args: object, **kwargs: object) -> object:
        raise AssertionError("entry points must remain unreachable")

    monkeypatch.setattr(importlib.metadata, "entry_points", forbidden_entry_points)
    builtin = object()
    registry = build_builtin_registry(
        builtins={"html-links-v1": builtin},
        selected_ids=("html-links-v1",),
        environment={
            "OPENOPPS_PLUGIN_AUTOLOAD": "true",
            "OPENOPPS_PLUGIN_ALLOWLIST": "malicious-plugin",
        },
    )

    assert dict(registry) == {"html-links-v1": builtin}


def test_builtin_registry_rejects_unknown_identifiers() -> None:
    with pytest.raises(IsolationError) as caught:
        build_builtin_registry(
            builtins={"html-links-v1": object()},
            selected_ids=("installed-plugin",),
            environment={},
        )

    assert caught.value.reason_code == "builtin_registry_identifier"


# T140: bounded raw bytes are fully scanned before any write or persisted digest.
@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param(
            (b"Authorization: Bearer synthetic-long-token-value-123456",),
            id="bearer",
        ),
        pytest.param(
            (b"Cookie: session=synthetic-session-value-123456",),
            id="cookie",
        ),
        pytest.param(
            (b'{"nested":{"authorization":"Bearer synthetic-nested-token-123456"}}',),
            id="nested-json",
        ),
        pytest.param(
            (b'<meta name="api-key" content="synthetic-html-key-123456">',),
            id="html-metadata",
        ),
        pytest.param(
            (
                b"-----BEGIN PRIVATE KEY-----\n",
                b"c3ludGhldGljLWtleS1tYXRlcmlhbA==\n",
                b"-----END PRIVATE KEY-----\n",
            ),
            id="private-key",
        ),
        pytest.param(
            (
                b"https://files.example.test/object?X-Amz-Signature=",
                b"synthetic-signature-value-123456",
            ),
            id="signed-url",
        ),
        pytest.param(
            (b"Authorization: Be", b"arer synthetic-split-token-123456"),
            id="chunk-split",
        ),
    ],
)
def test_secret_detection_precedes_writer_and_digest(
    chunks: tuple[bytes, ...],
) -> None:
    writes: list[bytes] = []
    digests: list[bytes] = []

    def digest(data: bytes) -> str:
        digests.append(data)
        return hashlib.sha256(data).hexdigest()

    with pytest.raises(SecretDetectedError) as caught:
        admit_scanned_content(
            chunks,
            max_bytes=1024,
            write=writes.append,
            digest=digest,
        )

    assert caught.value.reason_code == "secret_detected"
    assert writes == []
    assert digests == []
    assert all(
        part.decode("utf-8", errors="replace") not in str(caught.value)
        for part in chunks
    )


def test_clean_content_is_hashed_and_written_only_after_complete_scan() -> None:
    events: list[tuple[str, bytes]] = []

    def digest(data: bytes) -> str:
        events.append(("digest", data))
        return hashlib.sha256(data).hexdigest()

    def write(data: bytes) -> None:
        events.append(("write", data))

    admitted = admit_scanned_content(
        (b'{"provider":"greenhouse",', b'"board":"example"}\n'),
        max_bytes=128,
        write=write,
        digest=digest,
    )

    expected = b'{"provider":"greenhouse","board":"example"}\n'
    assert events == [("digest", expected), ("write", expected)]
    assert admitted.size_bytes == len(expected)
    assert admitted.content_sha256 == hashlib.sha256(expected).hexdigest()


def test_secret_scan_budget_exhaustion_has_zero_output_side_effects() -> None:
    writes: list[bytes] = []
    digests: list[bytes] = []

    with pytest.raises(SecretDetectedError) as caught:
        admit_scanned_content(
            (b"1234", b"5678"),
            max_bytes=7,
            write=writes.append,
            digest=lambda data: digests.append(data) or "unused",
        )

    assert caught.value.reason_code == "secret_scan_budget"
    assert writes == []
    assert digests == []


# T143: the launcher exposes one application output capability and no ambient handles.
@pytest.mark.parametrize(
    "parent_environment",
    [
        pytest.param(
            {
                "LANG": "en_US.UTF-8",
                "TZ": "UTC",
                "AWS_SECRET_ACCESS_KEY": "synthetic",
                "GH_TOKEN": "synthetic",
                "DATABASE_URL": "sqlite:///private.db",
                "NETRC": "/private/netrc",
                "HTTP_PROXY": "http://proxy.invalid",
                "OPENOPPS_PLUGIN_AUTOLOAD": "true",
            },
            id="common-secret-and-ambient-handles",
        ),
    ],
)
def test_credential_free_environment_is_a_positive_allowlist(
    parent_environment: Mapping[str, str],
) -> None:
    environment = build_credential_free_environment(
        parent_environment,
        allowlist=frozenset({"LANG", "TZ", "GH_TOKEN"}),
    )

    assert environment == {
        "LANG": "en_US.UTF-8",
        "TZ": "UTC",
        "NO_PROXY": "*",
        "PYTHONNOUSERSITE": "1",
    }


@contextmanager
def _memory_file(path: Path, sink: dict[Path, bytes]) -> Iterator[io.BytesIO]:
    buffer = io.BytesIO()
    try:
        yield buffer
        sink[path] = buffer.getvalue()
    finally:
        buffer.close()


class RecordingOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.files: dict[Path, bytes] = {}

    def __call__(
        self,
        path: Path,
        mode: str,
    ) -> AbstractContextManager[io.BytesIO]:
        assert mode == "xb"
        self.paths.append(path)
        return _memory_file(path, self.files)


def test_application_filesystem_rejects_out_of_root_before_open(
    tmp_path: Path,
) -> None:
    root = tmp_path / "new-quarantine"
    opener = RecordingOpener()
    filesystem = ApplicationFilesystem(root=root, opener=opener)

    filesystem.write_new("receipts/result.json", b"{}\n")
    assert opener.paths == [root / "receipts/result.json"]

    for path in (
        "../outside.json",
        "/absolute/outside.json",
        "receipts/../../outside.json",
    ):
        with pytest.raises(IsolationError) as caught:
            filesystem.write_new(path, b"forbidden")
        assert caught.value.reason_code == "filesystem_containment"

    assert opener.paths == [root / "receipts/result.json"]


class FakeProcessRunner:
    def __init__(self, *, returncode: int) -> None:
        self.returncode = returncode
        self.invocations: list[dict[str, object]] = []

    async def __call__(
        self,
        *,
        executable: str,
        request: ScoutLaunchRequest,
        environment: Mapping[str, str],
        limits: object,
    ) -> ProcessResult:
        self.invocations.append(
            {
                "environment": dict(environment),
                "executable": executable,
                "limits": limits,
                "request": request,
            }
        )
        if self.returncode:
            raise IsolationError("isolated_process_failed")
        return ProcessResult(
            returncode=0,
            stdout=(b'{"profileId":"default","result":{"suggestions":[]},"seed":0}\n'),
            stderr=b"",
        )


def _launch_request(root: Path) -> ScoutLaunchRequest:
    return ScoutLaunchRequest(
        input_bytes=b'{"suggestions":[]}\n',
        quarantine_root=root,
        parent_environment={
            "LANG": "en_US.UTF-8",
            "GH_TOKEN": "synthetic",
            "DATABASE_URL": "sqlite:///private.db",
            "OPENOPPS_PLUGIN_AUTOLOAD": "true",
        },
        environment_allowlist=frozenset({"LANG"}),
    )


@pytest.mark.parametrize("returncode", [0, 17], ids=["success", "failure"])
async def test_launcher_is_credential_free_and_root_bounded_on_every_exit(
    tmp_path: Path,
    returncode: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "new-quarantine"
    opener = RecordingOpener()
    filesystem = ApplicationFilesystem(root=root, opener=opener)
    runner = FakeProcessRunner(returncode=returncode)
    monkeypatch.setattr(isolation_module, "run_fresh_scout_process", runner)

    if returncode:
        with pytest.raises(IsolationError) as caught:
            await launch_isolated_scout(
                _launch_request(root),
                executable="/trusted/python",
                filesystem=filesystem,
            )
        assert caught.value.reason_code == "isolated_process_failed"
        assert "synthetic failure detail" not in str(caught.value)
    else:
        result = await launch_isolated_scout(
            _launch_request(root),
            executable="/trusted/python",
            filesystem=filesystem,
        )
        assert result.returncode == 0

    assert len(runner.invocations) == 1
    invocation = runner.invocations[0]
    assert invocation["executable"] == "/trusted/python"
    assert invocation["environment"] == {
        "LANG": "en_US.UTF-8",
        "NO_PROXY": "*",
        "PYTHONNOUSERSITE": "1",
    }
    request = invocation["request"]
    assert isinstance(request, ScoutLaunchRequest)
    assert request.input_bytes == b'{"suggestions":[]}\n'
    assert opener.paths == ([] if returncode else [root / "worker/result.json"])
    assert all(path.is_relative_to(root) for path in opener.paths)
