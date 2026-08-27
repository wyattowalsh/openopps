from __future__ import annotations

import ast
import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
import hashlib
import inspect
from pathlib import Path
import ssl
from typing import Any, cast

import httpcore
import httpx
import pytest

from openopps.discovery.bundle import (
    BUNDLE_SCHEMA_VERSION,
    BundleResource,
    BundleMemberSemanticContract,
    BundleVerificationPolicy,
    VerifiedBundle,
    compute_manifest_id,
    compute_member_set_sha256,
    verify_bundle,
    write_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.http_client import (
    DiscoveryHttpLimits,
    DiscoveryHttpRuntime,
    DiscoveryHttpRuntimeError,
    HttpTimeouts,
    PinnedAsyncHTTPTransport,
    PinnedAsyncNetworkBackend,
)
from openopps.discovery.models import (
    ChannelBudget,
    ChannelProfile,
    ObservedResource,
    TrustedDiscoveryProfile,
    WholeRunBudget,
)
from openopps.discovery.transport import (
    ContentLimits,
    DiscoveryTransportError,
    RedirectPolicy,
    VerifiedObservation,
    validate_public_locator,
)


PUBLIC_ADDRESS_A = "93.184.216.34"
PUBLIC_ADDRESS_B = "142.250.72.14"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
PROFILE_ID = "bounded-default"
PROFILE_VERSION = "1"
PROFILE_DIGEST = "b" * 64
CONFIGURATION_SHA256 = "c" * 64


def _wire_response(
    status_code: int,
    *,
    headers: Iterable[tuple[str, str]] = (),
    body: bytes = b"",
) -> bytes:
    reasons = {
        200: "OK",
        301: "Moved Permanently",
        302: "Found",
        304: "Not Modified",
        401: "Unauthorized",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }
    lines = [
        f"HTTP/1.1 {status_code} {reasons.get(status_code, 'Status')}".encode(),
        b"Connection: close",
    ]
    lower_names = {name.casefold() for name, _ in headers}
    lines.extend(f"{name}: {value}".encode("ascii") for name, value in headers)
    if "content-length" not in lower_names:
        lines.append(f"Content-Length: {len(body)}".encode())
    return b"\r\n".join((*lines, b"", body))


class _ScriptedStream(httpcore.AsyncNetworkStream):
    def __init__(self, *, address: str, response: bytes) -> None:
        self.address = address
        self.response = response
        self.writes: list[bytes] = []
        self.server_hostnames: list[str | None] = []
        self.closed = False
        self._read = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        del max_bytes, timeout
        if self._read:
            return b""
        self._read = True
        return self.response

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        del timeout
        self.writes.append(buffer)

    async def aclose(self) -> None:
        self.closed = True

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del ssl_context, timeout
        self.server_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str) -> Any:
        if info == "server_addr":
            return (self.address, 443)
        if info == "is_readable":
            return False
        if info == "ssl_object":
            return None
        return None


class _ScriptedBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self, responses: list[bytes], *, peer_override: str | None = None
    ) -> None:
        self.responses = list(responses)
        self.peer_override = peer_override
        self.connect_hosts: list[str] = []
        self.streams: list[_ScriptedStream] = []
        self.sleep_seconds: list[float] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del timeout, local_address, socket_options
        assert port == 443
        self.connect_hosts.append(host)
        stream = _ScriptedStream(
            address=self.peer_override or host,
            response=self.responses.pop(0),
        )
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise AssertionError("Unix sockets must be unreachable")

    async def sleep(self, seconds: float) -> None:
        self.sleep_seconds.append(seconds)


class _FakeClock:
    def __init__(self, now_ms: int = 1_000) -> None:
        self.now_ms = now_ms
        self.sleeps: list[float] = []

    def monotonic_ms(self) -> int:
        return self.now_ms

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_ms += round(seconds * 1_000)


class _SplitByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


async def _resolver(hostname: str) -> tuple[str, ...]:
    if hostname == "other.example":
        return (PUBLIC_ADDRESS_B,)
    return (PUBLIC_ADDRESS_A,)


def _content_limits(*, max_bytes: int = 1_024) -> ContentLimits:
    return ContentLimits(
        max_encoded_bytes=max_bytes,
        max_decoded_bytes=max_bytes,
        max_json_depth=8,
        max_xml_depth=8,
        max_html_nodes=100,
    )


def _verified_bundle(
    tmp_path: Path,
    content: bytes,
    *,
    locator_url: str = "https://example.com/data",
    profile_id: str = PROFILE_ID,
    profile_version: str = PROFILE_VERSION,
    profile_digest: str = PROFILE_DIGEST,
    configuration_sha256: str = CONFIGURATION_SHA256,
    etag: str | None = '"v1"',
    last_modified: str | None = None,
    tag: str = "observation",
) -> VerifiedBundle:
    locator = validate_public_locator(locator_url)
    content_sha256 = hashlib.sha256(content).hexdigest()
    resource_id = f"resource-{tag}"
    profile = TrustedDiscoveryProfile(
        profile_id=profile_id,
        profile_version=profile_version,
        whole_run_budget=WholeRunBudget(
            request_limit=10,
            aggregate_byte_limit=4_096,
            candidate_limit=10,
            concurrency_limit=1,
            wall_clock_limit_ms=5_000,
        ),
        channels=(
            ChannelProfile(
                channel="official",
                budget=ChannelBudget(
                    query_limit=1,
                    request_limit=10,
                    origin_limit=1,
                    redirect_limit=1,
                    page_limit=1,
                    response_byte_limit=1_024,
                    aggregate_byte_limit=4_096,
                    candidate_limit=10,
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
        media_type="text/plain",
        content_sha256=content_sha256,
        size_bytes=len(content),
        observed_at=NOW,
        final_locator=locator.url,
        validated_address=PUBLIC_ADDRESS_A,
        etag=etag,
        last_modified=last_modified,
    )
    profile_bytes = canonical_json_bytes(
        profile.model_dump(mode="json", by_alias=True, round_trip=True)
    )
    observed_resource_bytes = canonical_json_bytes(
        observed_resource.model_dump(mode="json", by_alias=True, round_trip=True)
    )
    resources = (
        BundleResource(
            data=content,
            media_type="text/plain",
            path=f"resources/{tag}.txt",
            provenance_id=resource_id,
            role="evidence",
        ),
        BundleResource(
            data=observed_resource_bytes,
            media_type="application/json",
            path=f"semantic/{tag}.observed.json",
            provenance_id=resource_id,
            role="observed-resource",
        ),
        BundleResource(
            data=profile_bytes,
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
        "executionId": f"http-test-{tag}",
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
        max_evidence_age=timedelta(hours=1),
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
    return verify_bundle(bundle_root, policy=policy)


def _select_observation(
    verified_bundle: VerifiedBundle,
    *,
    locator_url: str = "https://example.com/data",
    profile_id: str = PROFILE_ID,
    profile_version: str = PROFILE_VERSION,
    profile_digest: str = PROFILE_DIGEST,
    configuration_sha256: str = CONFIGURATION_SHA256,
) -> VerifiedObservation | None:
    return VerifiedObservation.from_verified_bundle(
        verified_bundle=verified_bundle,
        expected_locator=validate_public_locator(locator_url),
        expected_profile_id=profile_id,
        expected_profile_version=profile_version,
        expected_profile_digest=profile_digest,
        expected_configuration_sha256=configuration_sha256,
    )


def _verified_observation(
    tmp_path: Path,
    content: bytes,
    *,
    locator_url: str = "https://example.com/data",
    etag: str | None = '"v1"',
    last_modified: str | None = None,
    tag: str = "observation",
) -> VerifiedObservation:
    verified_bundle = _verified_bundle(
        tmp_path,
        content,
        locator_url=locator_url,
        etag=etag,
        last_modified=last_modified,
        tag=tag,
    )
    observation = _select_observation(verified_bundle, locator_url=locator_url)
    assert observation is not None
    return observation


def _runtime(
    responses: list[bytes],
    *,
    clock: _FakeClock | None = None,
    limits: DiscoveryHttpLimits | None = None,
    redirect_policy: RedirectPolicy | None = None,
    peer_override: str | None = None,
) -> tuple[DiscoveryHttpRuntime, _ScriptedBackend, _FakeClock]:
    active_clock = clock or _FakeClock()
    active_limits = limits or DiscoveryHttpLimits(min_origin_interval_ms=0)
    backend = _ScriptedBackend(responses, peer_override=peer_override)
    runtime = DiscoveryHttpRuntime(
        resolver=_resolver,
        content_limits=_content_limits(),
        redirect_policy=redirect_policy
        or RedirectPolicy(
            max_hops=active_limits.redirect_limit,
            allowed_cross_origin=frozenset(),
        ),
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        profile_digest=PROFILE_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        limits=active_limits,
        network_backend=backend,
        monotonic_clock=active_clock.monotonic_ms,
        wall_clock=lambda: NOW,
        sleeper=active_clock.sleep,
        timeouts=HttpTimeouts(),
    )
    return runtime, backend, active_clock


def _request_bytes(stream: _ScriptedStream) -> bytes:
    return b"".join(stream.writes)


@pytest.mark.asyncio
async def test_network_backend_connects_only_to_vetted_ip_and_preserves_sni() -> None:
    delegate = _ScriptedBackend([b""])
    backend = PinnedAsyncNetworkBackend(
        resolver=_resolver,
        delegate=delegate,
    )

    stream = await backend.connect_tcp("example.com", 443)
    await stream.start_tls(ssl.create_default_context(), "example.com")

    assert delegate.connect_hosts == [PUBLIC_ADDRESS_A]
    assert delegate.streams[0].server_hostnames == ["example.com"]


@pytest.mark.asyncio
async def test_network_backend_fails_closed_on_peer_substitution() -> None:
    delegate = _ScriptedBackend([b""], peer_override=PUBLIC_ADDRESS_B)
    backend = PinnedAsyncNetworkBackend(
        resolver=_resolver,
        delegate=delegate,
    )

    with pytest.raises(DiscoveryTransportError, match="peer_address_mismatch"):
        await backend.connect_tcp("example.com", 443)

    assert delegate.streams[0].closed is True


@pytest.mark.asyncio
async def test_pinned_stream_rejects_tls_hostname_substitution() -> None:
    delegate = _ScriptedBackend([b""])
    backend = PinnedAsyncNetworkBackend(
        resolver=_resolver,
        delegate=delegate,
    )
    stream = await backend.connect_tcp("example.com", 443)

    with pytest.raises(DiscoveryTransportError, match="tls_server_hostname"):
        await stream.start_tls(ssl.create_default_context(), "attacker.example")

    assert delegate.streams[0].closed is True


@pytest.mark.asyncio
async def test_network_backend_rejects_unix_and_alternate_connect_configuration() -> (
    None
):
    backend = PinnedAsyncNetworkBackend(
        resolver=_resolver,
        delegate=_ScriptedBackend([b""]),
    )

    with pytest.raises(DiscoveryTransportError, match="unix_socket_forbidden"):
        await backend.connect_unix_socket("/tmp/socket")
    with pytest.raises(DiscoveryTransportError, match="connect_configuration"):
        await backend.connect_tcp("example.com", 8443)
    with pytest.raises(DiscoveryTransportError, match="connect_configuration"):
        await backend.connect_tcp("example.com", 443, local_address="127.0.0.1")


@pytest.mark.asyncio
async def test_transport_emits_exact_credential_free_headers_and_filters_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    backend = _ScriptedBackend(
        [
            _wire_response(
                200,
                headers=(
                    ("Content-Type", "application/json"),
                    ("ETag", '"abc"'),
                    ("Set-Cookie", "session=secret"),
                    ("X-Untrusted", "secret"),
                ),
                body=b"{}",
            )
        ]
    )
    transport = PinnedAsyncHTTPTransport(
        resolver=_resolver,
        network_backend=backend,
    )
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        headers={},
        cookies=None,
        auth=None,
    ) as client:
        response = await client.get(
            "https://example.com/data",
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "X-Caller": "secret",
                "Accept-Encoding": "gzip",
            },
        )

    wire = _request_bytes(backend.streams[0])
    assert backend.connect_hosts == [PUBLIC_ADDRESS_A]
    assert b"Authorization" not in wire
    assert b"Cookie" not in wire
    assert b"X-Caller" not in wire
    assert b"secret" not in wire
    assert wire.count(b"Accept-Encoding: identity") == 1
    assert b"Host: example.com" in wire
    assert response.headers["etag"] == '"abc"'
    assert "set-cookie" not in response.headers
    assert "x-untrusted" not in response.headers


@pytest.mark.asyncio
async def test_transport_rejects_duplicate_allowlisted_response_metadata() -> None:
    backend = _ScriptedBackend(
        [
            _wire_response(
                200,
                headers=(
                    ("Content-Type", "application/json"),
                    ("ETag", '"one"'),
                    ("ETag", '"two"'),
                ),
                body=b"{}",
            )
        ]
    )
    transport = PinnedAsyncHTTPTransport(
        resolver=_resolver,
        network_backend=backend,
    )

    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(
            DiscoveryTransportError,
            match="response_header_duplicate",
        ):
            await client.get("https://example.com/data")


@pytest.mark.asyncio
async def test_runtime_fetches_stream_under_shared_request_and_byte_budgets() -> None:
    runtime, backend, _ = _runtime(
        [
            _wire_response(
                200,
                headers=(("Content-Type", "application/json"),),
                body=b'{"ok":true}',
            )
        ]
    )

    async with runtime:
        result = await runtime.fetch(validate_public_locator("https://example.com/a"))

    assert result.body == b'{"ok":true}'
    assert result.content_sha256 == hashlib.sha256(result.body).hexdigest()
    assert result.secret_detector_version == "openopps.discovery.secrets.v1"
    assert result.evidence_state == "fetched"
    assert result.redirect_history == ("https://example.com/a",)
    assert result.request_budget.consumed == 1
    assert result.request_budget.admitted_bytes == len(result.body)
    assert result.attempts[0].outcome == "succeeded"
    assert backend.streams[0].server_hostnames == ["example.com"]


@pytest.mark.asyncio
async def test_fetch_attempt_kind_is_explicit_and_conserved_in_ledger_and_receipts() -> (
    None
):
    limits = DiscoveryHttpLimits(min_origin_interval_ms=0)
    runtime, _, _ = _runtime(
        [
            _wire_response(
                200,
                headers=(
                    ("Content-Type", "text/plain"),
                    ("X-Attempt-Kind", "pagination"),
                ),
                body=b"initial",
            ),
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"page",
            ),
        ],
        limits=limits,
    )

    async with runtime:
        initial = await runtime.fetch(
            validate_public_locator("https://example.com/initial")
        )
        page = await runtime.fetch(
            validate_public_locator("https://example.com/page"),
            attempt_kind="pagination",
        )

    snapshot = page.request_budget
    assert initial.attempts[0].attempt_kind == "initial"
    assert page.attempts[0].attempt_kind == "pagination"
    assert snapshot.attempt_kinds == {"initial": 1, "pagination": 1}
    assert sum(snapshot.attempt_kinds.values()) == snapshot.consumed
    assert snapshot.consumed + snapshot.in_flight + snapshot.remaining == (
        snapshot.limit
    )


@pytest.mark.asyncio
async def test_fetch_rejects_untrusted_attempt_kind_before_budget_or_network() -> None:
    runtime, backend, _ = _runtime([])

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(
                validate_public_locator("https://example.com/data"),
                attempt_kind=cast(Any, "redirect"),
            )

    snapshot = caught.value.receipt.request_budget
    assert caught.value.reason_code == "attempt_kind"
    assert caught.value.receipt.attempts == ()
    assert snapshot.attempt_kinds == {}
    assert snapshot.consumed == 0
    assert snapshot.in_flight == 0
    assert snapshot.remaining == snapshot.limit
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_runtime_manually_revalidates_redirect_and_strips_conditionals(
    tmp_path: Path,
) -> None:
    observation = _verified_observation(
        tmp_path,
        b"old",
        locator_url="https://example.com/start",
        etag='"old"',
        last_modified=None,
    )
    limits = DiscoveryHttpLimits(min_origin_interval_ms=0)
    policy = RedirectPolicy(
        max_hops=limits.redirect_limit,
        allowed_cross_origin=frozenset({("example.com", "other.example")}),
    )
    runtime, backend, _ = _runtime(
        [
            _wire_response(
                302,
                headers=(("Location", "https://other.example/final"),),
            ),
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"new",
            ),
        ],
        limits=limits,
        redirect_policy=policy,
    )

    async with runtime:
        result = await runtime.fetch(
            validate_public_locator("https://example.com/start"),
            conditional_observation=observation,
        )

    first_wire, second_wire = map(_request_bytes, backend.streams)
    assert b'If-None-Match: "old"' in first_wire
    assert b"If-None-Match" not in second_wire
    assert b"Authorization" not in second_wire
    assert result.redirect_history == (
        "https://example.com/start",
        "https://other.example/final",
    )
    assert result.request_budget.attempt_kinds == {"initial": 1, "redirect": 1}


@pytest.mark.asyncio
async def test_runtime_rejects_unapproved_cross_origin_redirect_before_connect() -> (
    None
):
    runtime, backend, _ = _runtime(
        [
            _wire_response(
                302,
                headers=(("Location", "https://other.example/final"),),
            )
        ]
    )

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(validate_public_locator("https://example.com/start"))

    assert caught.value.reason_code == "redirect_origin"
    assert caught.value.receipt.attempts[0].outcome == "blocked"
    assert backend.connect_hosts == [PUBLIC_ADDRESS_A]


@pytest.mark.asyncio
async def test_runtime_uses_only_verified_evidence_for_conditional_304(
    tmp_path: Path,
) -> None:
    observation = _verified_observation(
        tmp_path,
        b'{"cached":true}',
        etag='W/"v1"',
        last_modified="Thu, 21 Aug 2025 12:00:00 GMT",
    )
    runtime, backend, _ = _runtime([_wire_response(304, headers=(("ETag", 'W/"v1"'),))])

    async with runtime:
        result = await runtime.fetch(
            validate_public_locator("https://example.com/data"),
            conditional_observation=observation,
        )

    wire = _request_bytes(backend.streams[0])
    assert b'If-None-Match: W/"v1"' in wire
    assert b"If-Modified-Since: Thu, 21 Aug 2025 12:00:00 GMT" in wire
    assert result.evidence_state == "not_modified"
    assert result.body == observation.content
    assert result.content_sha256 == observation.content_sha256
    assert result.secret_detector_version == observation.secret_detector_version
    assert result.request_budget.admitted_bytes == 0


@pytest.mark.parametrize(
    ("identity_field", "mismatched_value"),
    [
        pytest.param("locator_url", "https://example.com/different", id="locator"),
        pytest.param("profile_id", "different-profile", id="profile-id"),
        pytest.param("profile_version", "different-version", id="profile-version"),
        pytest.param("profile_digest", "d" * 64, id="profile-digest"),
        pytest.param("configuration_sha256", "e" * 64, id="configuration"),
    ],
)
async def test_conditional_identity_mismatch_emits_no_validator_and_never_reuses_304(
    tmp_path: Path,
    identity_field: str,
    mismatched_value: str,
) -> None:
    overrides = {identity_field: mismatched_value}
    verified = _verified_bundle(
        tmp_path,
        b"old",
        tag=identity_field.replace("_", "-"),
        **overrides,
    )
    observation = _select_observation(verified)
    assert observation is None
    runtime, backend, _ = _runtime([_wire_response(304)])

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(
                validate_public_locator("https://example.com/data"),
                conditional_observation=observation,
            )

    wire = _request_bytes(backend.streams[0])
    assert b"If-None-Match" not in wire
    assert b"If-Modified-Since" not in wire
    assert caught.value.reason_code == "unexpected_not_modified"
    assert caught.value.receipt.request_budget.admitted_bytes == 0


@pytest.mark.asyncio
async def test_verified_a_example_observation_cannot_condition_or_reuse_b_example(
    tmp_path: Path,
) -> None:
    verified = _verified_bundle(
        tmp_path,
        b"a-only",
        locator_url="https://a.example/data",
        tag="a-example",
    )
    observation = _select_observation(
        verified,
        locator_url="https://b.example/data",
    )
    assert observation is None
    runtime, backend, _ = _runtime([_wire_response(304)])

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(
                validate_public_locator("https://b.example/data"),
                conditional_observation=observation,
            )

    wire = _request_bytes(backend.streams[0])
    assert b"If-None-Match" not in wire
    assert b"If-Modified-Since" not in wire
    assert caught.value.reason_code == "unexpected_not_modified"


def test_verified_observation_requires_exact_verified_manifest_member_binding(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        VerifiedObservation()  # type: ignore[call-arg]
    bundle_ctor: Any = VerifiedBundle
    with pytest.raises(TypeError):
        bundle_ctor(
            manifest_id="f" * 64,
            member_paths=("resources/asserted.txt",),
        )

    content = b"exact"
    verified = _verified_bundle(tmp_path, content, tag="exact")
    observation = _select_observation(verified)
    assert observation is not None
    assert observation.content == content
    assert observation.manifest_id == verified.manifest_id
    assert observation.member_path == "resources/exact.txt"
    assert observation.observed_resource_member_path == ("semantic/exact.observed.json")
    assert observation.resource_id == "resource-exact"
    assert observation.member_provenance_id == observation.resource_id
    assert observation.etag == '"v1"'

    generic_resource = BundleResource(
        data=content,
        media_type="text/plain",
        path="resources/generic.txt",
        provenance_id="generic-resource",
        role="evidence",
    )
    generic_member = {
        "mediaType": generic_resource.media_type,
        "path": generic_resource.path,
        "provenanceId": generic_resource.provenance_id,
        "role": generic_resource.role,
        "sha256": hashlib.sha256(generic_resource.data).hexdigest(),
        "sizeBytes": len(generic_resource.data),
    }
    manifest: dict[str, object] = {
        "configurationSha256": CONFIGURATION_SHA256,
        "executionId": "generic",
        "manifestId": "",
        "memberCount": 1,
        "members": [generic_member],
        "memberSetSha256": compute_member_set_sha256([generic_member]),
        "observedAt": NOW.isoformat().replace("+00:00", "Z"),
        "profileId": PROFILE_ID,
        "profileVersion": PROFILE_VERSION,
        "runState": "complete",
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "toolVersion": "0.1.0",
    }
    manifest["manifestId"] = compute_manifest_id(manifest)
    policy = BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=1),
        now=NOW,
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({(PROFILE_ID, PROFILE_VERSION)}),
        supported_schema_versions=frozenset({BUNDLE_SCHEMA_VERSION}),
        required_member_roles=frozenset({"evidence"}),
        supported_member_roles=frozenset({"evidence"}),
        canonical_json_roles=frozenset(),
    )
    bundle_root = write_bundle(
        tmp_path / "quarantine-generic",
        manifest=manifest,
        resources=(generic_resource,),
        verification_policy=policy,
    )
    generic_verified = verify_bundle(bundle_root, policy=policy)
    assert generic_verified.resource_bindings == ()
    assert _select_observation(generic_verified) is None


@pytest.mark.asyncio
async def test_runtime_rejects_tampered_conditional_evidence_without_network(
    tmp_path: Path,
) -> None:
    observation = _verified_observation(tmp_path, b"actual", tag="tampered")
    object.__setattr__(
        observation,
        "content_sha256",
        hashlib.sha256(b"different").hexdigest(),
    )
    runtime, backend, _ = _runtime([])

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(
                validate_public_locator("https://example.com/data"),
                conditional_observation=observation,
            )

    assert caught.value.reason_code == "verified_evidence_digest"
    assert caught.value.receipt.request_budget.consumed == 0
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_runtime_rejects_observation_from_unknown_secret_detector_version(
    tmp_path: Path,
) -> None:
    # A real verifier-derived observation is required before tamper resistance is
    # exercised; no caller-asserted fixture bypasses the bundle graph.
    observation = _verified_observation(tmp_path, b"actual", tag="detector")
    object.__setattr__(observation, "secret_detector_version", "unknown-v0")
    runtime, backend, _ = _runtime([])

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(
                validate_public_locator("https://example.com/data"),
                conditional_observation=observation,
            )

    assert caught.value.reason_code == "verified_secret_detector"
    assert caught.value.receipt.request_budget.consumed == 0
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_http_admission_rejects_chunk_split_secret_with_safe_zero_byte_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, backend, _ = _runtime([])

    async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            stream=_SplitByteStream(
                (b"Authorization: Be", b"arer synthetic-split-token-123456")
            ),
            request=request,
        )

    monkeypatch.setattr(runtime._client, "send", send)
    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(validate_public_locator("https://example.com/data"))

    assert caught.value.reason_code == "secret_detected"
    assert caught.value.receipt.request_budget.admitted_bytes == 0
    assert "synthetic-split-token" not in repr(caught.value.receipt)
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_runtime_honors_bounded_retry_after_and_counts_retry() -> None:
    runtime, backend, clock = _runtime(
        [
            _wire_response(429, headers=(("Retry-After", "2"),)),
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"ok",
            ),
        ]
    )

    async with runtime:
        result = await runtime.fetch(
            validate_public_locator("https://example.com/data")
        )

    assert clock.sleeps == [2.0]
    assert len(backend.streams) == 2
    assert tuple(attempt.attempt_kind for attempt in result.attempts) == (
        "initial",
        "retry",
    )
    assert result.request_budget.outcomes == {"rate_limited": 1, "succeeded": 1}


@pytest.mark.asyncio
async def test_runtime_stops_before_retry_after_exceeds_deadline() -> None:
    limits = DiscoveryHttpLimits(
        wall_clock_limit_ms=1_000,
        max_retry_delay_ms=5_000,
        min_origin_interval_ms=0,
    )
    runtime, backend, clock = _runtime(
        [_wire_response(429, headers=(("Retry-After", "2"),))],
        limits=limits,
    )

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(validate_public_locator("https://example.com/data"))

    assert caught.value.reason_code == "retry_after_deadline"
    assert clock.sleeps == []
    assert len(backend.streams) == 1


@pytest.mark.asyncio
async def test_runtime_applies_per_origin_pacing_across_fetches() -> None:
    limits = DiscoveryHttpLimits(min_origin_interval_ms=250)
    runtime, _, clock = _runtime(
        [
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"one",
            ),
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"two",
            ),
        ],
        limits=limits,
    )

    async with runtime:
        await runtime.fetch(validate_public_locator("https://example.com/one"))
        await runtime.fetch(validate_public_locator("https://example.com/two"))

    assert clock.sleeps == [0.25]


@pytest.mark.asyncio
async def test_runtime_honors_stricter_same_origin_and_global_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = DiscoveryHttpLimits(
        concurrency_limit=2,
        per_origin_concurrency_limit=1,
        min_origin_interval_ms=0,
    )
    policy = RedirectPolicy(
        max_hops=limits.redirect_limit,
        allowed_cross_origin=frozenset(),
    )
    runtime, backend, _ = _runtime([], limits=limits, redirect_policy=policy)
    release = asyncio.Event()
    two_origins_active = asyncio.Event()
    active_by_host: Counter[str] = Counter()
    maximum_by_host: Counter[str] = Counter()
    active_global = 0
    maximum_global = 0

    async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
        nonlocal active_global, maximum_global
        del kwargs
        host = request.url.host
        active_by_host[host] += 1
        active_global += 1
        maximum_by_host[host] = max(maximum_by_host[host], active_by_host[host])
        maximum_global = max(maximum_global, active_global)
        if active_global == 2:
            two_origins_active.set()
        try:
            await release.wait()
        finally:
            active_by_host[host] -= 1
            active_global -= 1
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            stream=_SplitByteStream((b"ok",)),
            request=request,
        )

    monkeypatch.setattr(runtime._client, "send", send)
    async with runtime:
        tasks = (
            asyncio.create_task(
                runtime.fetch(validate_public_locator("https://example.com/one"))
            ),
            asyncio.create_task(
                runtime.fetch(validate_public_locator("https://example.com/two"))
            ),
            asyncio.create_task(
                runtime.fetch(validate_public_locator("https://other.example/three"))
            ),
        )
        await asyncio.wait_for(two_origins_active.wait(), timeout=1)
        assert active_by_host == {"example.com": 1, "other.example": 1}
        release.set()
        await asyncio.gather(*tasks)

    assert maximum_by_host == {"example.com": 1, "other.example": 1}
    assert maximum_global == 2
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_cancelled_fetch_releases_origin_and_global_concurrency_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = DiscoveryHttpLimits(
        concurrency_limit=1,
        per_origin_concurrency_limit=1,
        min_origin_interval_ms=0,
    )
    runtime, backend, _ = _runtime([], limits=limits)
    first_entered = asyncio.Event()
    never_release = asyncio.Event()
    call_count = 0

    async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
        nonlocal call_count
        del kwargs
        call_count += 1
        if call_count == 1:
            first_entered.set()
            await never_release.wait()
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            stream=_SplitByteStream((b"ok",)),
            request=request,
        )

    monkeypatch.setattr(runtime._client, "send", send)
    async with runtime:
        cancelled = asyncio.create_task(
            runtime.fetch(validate_public_locator("https://example.com/one"))
        )
        await asyncio.wait_for(first_entered.wait(), timeout=1)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        result = await asyncio.wait_for(
            runtime.fetch(validate_public_locator("https://example.com/two")),
            timeout=1,
        )

    assert result.body == b"ok"
    assert call_count == 2
    assert runtime.budget_snapshot().in_flight == 0
    assert backend.connect_hosts == []


@pytest.mark.asyncio
async def test_runtime_opens_circuit_and_blocks_next_request() -> None:
    limits = DiscoveryHttpLimits(
        max_attempts_per_resource=1,
        circuit_failure_threshold=1,
        min_origin_interval_ms=0,
    )
    runtime, backend, _ = _runtime(
        [_wire_response(503)],
        limits=limits,
    )

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as first:
            await runtime.fetch(validate_public_locator("https://example.com/one"))
        with pytest.raises(DiscoveryHttpRuntimeError) as second:
            await runtime.fetch(validate_public_locator("https://example.com/two"))

    assert first.value.reason_code == "upstream_failure"
    assert second.value.reason_code == "circuit_open"
    assert len(backend.streams) == 1


@pytest.mark.asyncio
async def test_runtime_failure_receipt_contains_no_remote_header_values() -> None:
    runtime, _, _ = _runtime(
        [
            _wire_response(
                401,
                headers=(
                    ("WWW-Authenticate", 'Bearer secret="do-not-log"'),
                    ("X-Untrusted", "do-not-log"),
                ),
            )
        ]
    )

    async with runtime:
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(validate_public_locator("https://example.com/data"))

    rendered = repr(caught.value.receipt)
    assert caught.value.reason_code == "access_blocked"
    assert "do-not-log" not in rendered
    assert "example.com" not in rendered


@pytest.mark.asyncio
async def test_runtime_enforces_aggregate_bytes_across_requests() -> None:
    limits = DiscoveryHttpLimits(
        aggregate_byte_limit=5,
        min_origin_interval_ms=0,
    )
    runtime, _, _ = _runtime(
        [
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"123",
            ),
            _wire_response(
                200,
                headers=(("Content-Type", "text/plain"),),
                body=b"456",
            ),
        ],
        limits=limits,
    )

    async with runtime:
        await runtime.fetch(validate_public_locator("https://example.com/one"))
        with pytest.raises(DiscoveryHttpRuntimeError) as caught:
            await runtime.fetch(validate_public_locator("https://example.com/two"))

    assert caught.value.reason_code == "aggregate_byte_budget"
    assert caught.value.receipt.request_budget.admitted_bytes == 3


@pytest.mark.parametrize(
    "limits",
    [
        DiscoveryHttpLimits(min_origin_interval_ms=0),
        DiscoveryHttpLimits(min_origin_interval_ms=60_000),
    ],
)
def test_runtime_limits_are_frozen_and_finite(limits: DiscoveryHttpLimits) -> None:
    with pytest.raises((AttributeError, TypeError)):
        setattr(limits, "request_limit", 1)
    with pytest.raises(DiscoveryTransportError):
        DiscoveryHttpLimits(request_limit=0)
    with pytest.raises(DiscoveryTransportError):
        DiscoveryHttpLimits(max_attempts_per_resource=11)
    with pytest.raises(DiscoveryTransportError):
        DiscoveryHttpLimits(
            concurrency_limit=1,
            per_origin_concurrency_limit=2,
        )
    with pytest.raises(DiscoveryTransportError):
        DiscoveryHttpLimits(
            retry_base_delay_ms=2_000,
            max_retry_delay_ms=1_000,
        )


def test_http_client_has_no_runtime_cache_plugin_or_dynamic_import_path() -> None:
    source_path = (
        Path(__file__).parents[4] / "src" / "openopps" / "discovery" / "http_client.py"
    )
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(module)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "openopps.cache" not in imported_names
    assert "openopps.http" not in imported_names
    assert "openopps.plugins" not in imported_names
    assert "importlib" not in imported_names
    assert "importlib.metadata" not in imported_names
    assert called_names.isdisjoint(
        {"open", "__import__", "import_module", "entry_points"}
    )


def _discovery_python_files() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[4] / "src" / "openopps" / "discovery"
    return tuple(sorted(path for path in root.rglob("*.py") if path.name != "*.pyc"))


def _imported_module_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _calls_getaddrinfo(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "getaddrinfo":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "getaddrinfo":
            return True
    return False


def test_scout_http_stack_rejects_weaker_runtime_seams_and_injected_dns() -> None:
    forbidden = (
        "openopps.http",
        "openopps.cache",
        "openopps.plugins",
        "openopps.cli",
        "openopps.ingest",
        "openopps.providers",
        "openopps.storage",
    )
    scout_io = {
        "http_client.py",
        "transport.py",
        "isolation.py",
        "bundle.py",
        "robots.py",
        "worker.py",
    }
    getaddrinfo_files: list[str] = []
    for path in _discovery_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = _imported_module_names(tree)
        assert not {
            name
            for name in imported
            if any(
                name == module or name.startswith(f"{module}.") for module in forbidden
            )
        }, path.name
        if _calls_getaddrinfo(tree):
            getaddrinfo_files.append(path.name)
    assert getaddrinfo_files == []
    assert scout_io <= {path.name for path in _discovery_python_files()}

    for cls in (
        DiscoveryHttpRuntime,
        PinnedAsyncHTTPTransport,
        PinnedAsyncNetworkBackend,
    ):
        resolver = inspect.signature(cls.__init__).parameters["resolver"]
        assert resolver.default is inspect.Parameter.empty
        assert resolver.kind is inspect.Parameter.KEYWORD_ONLY
