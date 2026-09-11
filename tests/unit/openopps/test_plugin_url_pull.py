from __future__ import annotations

import asyncio
from contextvars import Context
from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest

from openopps.http import (
    HttpOperationClosedError,
    HttpRequestLimitError,
    HttpResponseLimitError,
    http_cache_identity_scope,
    http_operation_budget,
    http_operation_observability,
)
from openopps.models import JobRecord, JsonDict, PostingKind
from openopps.plugins import (
    ENTRY_POINT_GROUP,
    PluginCapability,
    PluginContribution,
    PluginContext,
    PluginMetadata,
    PluginRegistry,
    PluginUrlPullBindingError,
    PluginUrlPullRegistration,
    bind_plugin_url_pull_provider,
    load_plugins,
)
from openopps.providers.boards import build_job_provider, build_url_pull_provider
from openopps.providers.pull import (
    InterfaceStability,
    MembershipEvidence,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderListResult,
    ProviderPosting,
    ProviderPullCapabilities,
    ProviderPullHttpClient,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.providers.registry import provider_registry
from openopps.settings import OpenOppsSettings


@dataclass(frozen=True)
class FakeDistribution:
    name: str | None = "openopps-example"
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class FakeEntryPoint:
    name: str
    factory: Any
    dist: FakeDistribution | None = None
    group: str = ENTRY_POINT_GROUP

    def load(self):
        return self.factory


def _job(
    remote_id: str = "123",
    *,
    board_key: str = "acme",
    provider_id: str = "pullable",
    listing: JsonDict | None = None,
    detail: JsonDict | None = None,
    posting_kind: PostingKind = "standard",
) -> JobRecord:
    raw_listing = listing if listing is not None else {"id": remote_id}
    raw_detail = detail if detail is not None else {}
    return JobRecord(
        id=f"{board_key}:{provider_id}:{remote_id}",
        board_key=board_key,
        provider_id=provider_id,
        remote_id=remote_id,
        title="Engineer",
        posting_url=f"https://boards.greenhouse.io/{board_key}/jobs/{remote_id}",
        raw_listing=raw_listing,
        raw_detail=raw_detail,
        posting_kind=posting_kind,
    )


async def _contract_list_hook(
    client: ProviderPullHttpClient,
    target: ProviderUrlTarget,
    *,
    include_unlisted: bool,
) -> ProviderListResult:
    del client, target, include_unlisted
    raise AssertionError("contract test does not execute the provider")


async def _contract_native_get_hook(
    client: ProviderPullHttpClient,
    target: ProviderUrlTarget,
) -> ProviderGetResult:
    del client, target
    raise AssertionError("contract test does not execute the provider")


def _empty_plugin_list_result(target: ProviderUrlTarget) -> ProviderListResult:
    return ProviderListResult(
        provider_id=target.provider_id,
        board_identity=target.board_identity,
        postings=(),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=0,
        ),
    )


def _parse(provider_id: str):
    def parse(url: str) -> ProviderUrlTarget:
        return ProviderUrlTarget(
            provider_id=provider_id,
            target_kind=ProviderTargetKind.BOARD,
            url=url,
            board_identity="acme",
        )

    return parse


def _list_capabilities() -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        list_supported=True,
        interface_stability=InterfaceStability.DOCUMENTED,
    )


def _native_capabilities() -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        native_get_supported=True,
        interface_stability=InterfaceStability.DOCUMENTED,
    )


def test_load_plugins_accepts_explicit_typed_url_pull_registration() -> None:
    class PullProvider:
        async def pull_list(
            self, *_args: object, **_kwargs: object
        ) -> ProviderListResult:
            raise AssertionError("contract test does not execute the provider")

    capabilities = _list_capabilities()
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "pullable",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="pullable", version="1.0.0"),
                    job_providers={"pullable": lambda _settings: PullProvider()},
                    url_pull_providers={
                        "pullable": PluginUrlPullRegistration(
                            target_parser=_parse("pullable"),
                            capabilities=capabilities,
                            list_hook_factory=lambda provider: provider.pull_list,
                        )
                    },
                ),
            )
        ],
        allowed={"pullable"},
    )

    assert registry.as_dict()["urlPullProviders"] == [
        {
            "plugin": "pullable",
            "providerId": "pullable",
            "capabilities": capabilities.model_dump(mode="json"),
            "hasListHook": True,
            "hasNativeGetHook": False,
            "hasProbeBuilder": False,
            "status": "active",
            "resolution": "active_plugin",
            "blockedBy": [],
        }
    ]
    assert sorted(registry.capabilities()) == [
        "job_provider:pullable",
        "url_pull_provider:pullable",
    ]
    assert registry.url_pull_registration("pullable") is not None
    assert registry.resolve_url_pulls(
        builtin_provider_ids=registry.url_pull_resolution_builtin_ids or (),
        settings=registry.url_pull_resolution_settings,
    ) is registry


def test_load_plugins_rejects_url_pull_registration_without_provider_factory() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    url_pull_providers={
                        "orphan": PluginUrlPullRegistration(
                            target_parser=_parse("orphan"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
            )
        ],
        allowed={"invalid"},
    )

    assert registry.as_dict()["failed"] == 1
    assert "matching job provider factory" in (
        registry.as_dict()["plugins"][0]["error"] or ""
    )


def test_load_plugins_rejects_capability_hook_mismatch_nonfatally() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    job_providers={"invalid": lambda _settings: object()},
                    url_pull_providers={
                        "invalid": PluginUrlPullRegistration(
                            target_parser=_parse("invalid"),
                            capabilities=_list_capabilities(),
                        )
                    },
                ),
            )
        ],
        allowed={"invalid"},
    )

    assert registry.as_dict()["loaded"] == 0
    assert registry.as_dict()["failed"] == 1
    assert "list capability requires a list hook factory" in (
        registry.as_dict()["plugins"][0]["error"] or ""
    )


@pytest.mark.parametrize(
    ("capabilities", "hooks", "message"),
    [
        (
            ProviderPullCapabilities(interface_stability=InterfaceStability.DOCUMENTED),
            {"list_hook_factory": lambda _provider: _contract_list_hook},
            "list hook factory requires list capability",
        ),
        (
            ProviderPullCapabilities(interface_stability=InterfaceStability.DOCUMENTED),
            {"native_get_hook_factory": lambda _provider: _contract_native_get_hook},
            "native-get hook factory requires native-get capability",
        ),
        (
            ProviderPullCapabilities(
                native_get_supported=True,
                interface_stability=InterfaceStability.DOCUMENTED,
            ),
            {},
            "native-get capability requires a native-get hook factory",
        ),
        (
            ProviderPullCapabilities(
                detect_supported=False,
                interface_stability=InterfaceStability.BEST_EFFORT,
            ),
            {},
            "must declare target detection",
        ),
    ],
)
def test_url_pull_registration_validation_fails_closed(
    capabilities: ProviderPullCapabilities,
    hooks: dict[str, Any],
    message: str,
) -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    job_providers={"invalid": lambda _settings: object()},
                    url_pull_providers={
                        "invalid": PluginUrlPullRegistration(
                            target_parser=_parse("invalid"),
                            capabilities=capabilities,
                            **hooks,
                        )
                    },
                ),
            )
        ],
        allowed={"invalid"},
    )

    assert registry.as_dict()["failed"] == 1
    assert message in (registry.as_dict()["plugins"][0]["error"] or "")


def test_url_pull_capability_requires_typed_registration() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    capabilities=(PluginCapability("url_pull_provider", "missing"),),
                    job_providers={"invalid": lambda _settings: object()},
                ),
            )
        ],
        allowed={"invalid"},
    )

    assert registry.as_dict()["failed"] == 1
    assert "typed registration" in (registry.as_dict()["plugins"][0]["error"] or "")


def test_url_pull_rejects_non_registration_mapping_values() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    job_providers={"invalid": lambda _settings: object()},
                    url_pull_providers={"invalid": cast(Any, object())},
                ),
            )
        ],
        allowed={"invalid"},
    )

    assert registry.as_dict()["failed"] == 1
    assert "PluginUrlPullRegistration" in (
        registry.as_dict()["plugins"][0]["error"] or ""
    )


def test_url_pull_rejects_non_callable_parser_and_probe_builder() -> None:
    parser_registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "parser",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    job_providers={"invalid": lambda _settings: object()},
                    url_pull_providers={
                        "invalid": PluginUrlPullRegistration(
                            target_parser=cast(Any, "not-callable"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
            )
        ],
        allowed={"parser"},
    )
    probe_registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "probe",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid", version="1.0.0"),
                    job_providers={"invalid": lambda _settings: object()},
                    url_pull_providers={
                        "invalid": PluginUrlPullRegistration(
                            target_parser=_parse("invalid"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                            probe_url_builder=cast(Any, "not-callable"),
                        )
                    },
                ),
            )
        ],
        allowed={"probe"},
    )

    assert "target_parser must be callable" in (
        parser_registry.as_dict()["plugins"][0]["error"] or ""
    )
    assert "probe_url_builder must be callable" in (
        probe_registry.as_dict()["plugins"][0]["error"] or ""
    )


def test_load_plugins_reports_url_pull_registration_conflicts() -> None:
    capabilities = ProviderPullCapabilities(
        interface_stability=InterfaceStability.DOCUMENTED,
    )

    def contribution(name: str) -> PluginContribution:
        return PluginContribution(
            metadata=PluginMetadata(name=name, version="1.0.0"),
            job_providers={"same": lambda _settings: object()},
            url_pull_providers={
                "same": PluginUrlPullRegistration(
                    target_parser=_parse("same"),
                    capabilities=capabilities,
                )
            },
        )

    entry_points = {
        "one": FakeEntryPoint("one", lambda _context: contribution("one")),
        "two": FakeEntryPoint("two", lambda _context: contribution("two")),
    }

    def load(order: tuple[str, ...]) -> PluginRegistry:
        return load_plugins(
            entry_points=[entry_points[name] for name in order],
            allowed={"one", "two"},
            builtin_provider_ids=(),
        )

    registry = load(("one", "two"))
    reversed_registry = load(("two", "one"))

    assert [conflict.as_dict() for conflict in registry.conflicts] == [
        {
            "capability": "job_provider:same",
            "existingPlugin": "one",
            "plugin": "two",
        },
        {
            "capability": "url_pull_provider:same",
            "existingPlugin": "one",
            "plugin": "two",
        },
    ]
    assert registry.load_results[1].warnings == (
        "conflict:job_provider:same",
        "conflict:url_pull_provider:same",
        "url_pull_blocked:same:ambiguous_plugin_ownership",
    )
    assert [item["status"] for item in registry.as_dict()["urlPullProviders"]] == [
        "blocked",
        "blocked",
    ]
    assert registry.url_pull_registration("same") is None
    assert reversed_registry.conflicts == registry.conflicts
    assert reversed_registry.as_dict()["urlPullProviders"] == (
        registry.as_dict()["urlPullProviders"]
    )


def test_builtin_provider_id_blocks_plugin_url_pull_deterministically() -> None:
    plugin_registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "greenhouse-shadow",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(
                        name="greenhouse-shadow",
                        version="1.0.0",
                    ),
                    job_providers={"greenhouse": lambda _settings: object()},
                    url_pull_providers={
                        "greenhouse": PluginUrlPullRegistration(
                            target_parser=_parse("greenhouse"),
                            capabilities=ProviderPullCapabilities(
                                interface_stability=InterfaceStability.DOCUMENTED,
                            ),
                        )
                    },
                ),
            )
        ],
        allowed={"greenhouse-shadow"},
    )

    state = plugin_registry.as_dict()["urlPullProviders"][0]
    assert state["status"] == "blocked"
    assert state["resolution"] == "built_in_precedence"
    assert state["blockedBy"] == ["builtin:greenhouse"]
    assert plugin_registry.url_pull_registration("greenhouse") is None
    assert plugin_registry.capabilities("url_pull_provider") == {}

    built = build_job_provider(
        "greenhouse",
        OpenOppsSettings(),
        plugin_registry=plugin_registry,
    )
    assert built is not None
    assert built.provider_id == "greenhouse"


def test_plugin_hook_factories_are_validated_against_actual_provider() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid-hooks",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="invalid-hooks", version="1.0.0"),
                    job_providers={
                        "number_hook": lambda _settings: object(),
                        "missing_hook": lambda _settings: object(),
                    },
                    url_pull_providers={
                        "number_hook": PluginUrlPullRegistration(
                            target_parser=_parse("number_hook"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: 42,
                        ),
                        "missing_hook": PluginUrlPullRegistration(
                            target_parser=_parse("missing_hook"),
                            capabilities=_native_capabilities(),
                            native_get_hook_factory=lambda provider: provider.pull_get,
                        ),
                    },
                ),
            )
        ],
        allowed={"invalid-hooks"},
        builtin_provider_ids=(),
    )

    data = registry.as_dict()
    assert data["loaded"] == 1
    assert [
        (item["providerId"], item["status"], item["resolution"])
        for item in data["urlPullProviders"]
    ] == [
        ("missing_hook", "blocked", "invalid_native_get_hook"),
        ("number_hook", "blocked", "invalid_list_hook"),
    ]
    assert registry.capabilities("url_pull_provider") == {}
    assert (
        build_url_pull_provider(
            "number_hook",
            OpenOppsSettings(),
            plugin_registry=registry,
        )
        is None
    )
    assert provider_registry(plugin_registry=registry).get("greenhouse") is not None


def test_invalid_duplicate_does_not_block_the_only_valid_url_pull_owner() -> None:
    capabilities = _list_capabilities()

    def contribution(name: str, *, valid: bool) -> PluginContribution:
        return PluginContribution(
            metadata=PluginMetadata(name=name, version="1.0.0"),
            job_providers={"shared": lambda _settings: object()},
            url_pull_providers={
                "shared": PluginUrlPullRegistration(
                    target_parser=_parse("shared"),
                    capabilities=capabilities,
                    list_hook_factory=cast(
                        Any,
                        (lambda _provider: _contract_list_hook)
                        if valid
                        else (lambda _provider: 42),
                    ),
                )
            },
        )

    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "invalid-owner",
                lambda _context: contribution("invalid-owner", valid=False),
            ),
            FakeEntryPoint(
                "valid-owner",
                lambda _context: contribution("valid-owner", valid=True),
            ),
        ],
        allowed={"invalid-owner", "valid-owner"},
        builtin_provider_ids=(),
    )

    assert [
        (state["plugin"], state["status"], state["resolution"])
        for state in registry.as_dict()["urlPullProviders"]
    ] == [
        ("invalid-owner", "blocked", "invalid_list_hook"),
        ("valid-owner", "active", "active_plugin"),
    ]
    assert registry.url_pull_registration("shared") is not None
    assert provider_registry(plugin_registry=registry).pull_capabilities("shared") == (
        capabilities
    )


def test_built_plugin_provider_uses_only_explicit_bound_hooks() -> None:
    class ProviderWithLegacyMethod:
        marker = "forwarded"

        async def pull_list(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("legacy provider method must not be inferred")

    capabilities = _list_capabilities()
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "bound",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="bound", version="1.0.0"),
                    job_providers={
                        "bound": lambda _settings: ProviderWithLegacyMethod()
                    },
                    url_pull_providers={
                        "bound": PluginUrlPullRegistration(
                            target_parser=_parse("bound"),
                            capabilities=capabilities,
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
            )
        ],
        allowed={"bound"},
        builtin_provider_ids=(),
    )

    bound = build_url_pull_provider(
        "bound",
        OpenOppsSettings(),
        plugin_registry=registry,
    )

    assert bound is not None
    assert bound.pull_capabilities == capabilities
    assert bound.pull_list is not _contract_list_hook
    assert callable(bound.pull_list)
    assert bound.marker == "forwarded"
    assert not hasattr(bound, "pull_get")


@pytest.mark.asyncio
async def test_plugin_pull_hook_receives_only_bounded_http_and_request_budget() -> None:
    requests: list[httpx.Request] = []
    received_http: list[ProviderPullHttpClient] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def pull_list(
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        assert include_unlisted is False
        received_http.append(client)
        for raw_surface in (
            "client",
            "get",
            "request",
            "send",
            "auth",
            "cookies",
            "headers",
            "_ProviderPullHttpClient__client",
        ):
            assert not hasattr(client, raw_surface)
        assert await client.get_json(
            "https://plugin.example/first",
            role="listing",
            params={"page": 1},
        ) == {"ok": True}
        await client.get_json("https://plugin.example/second", role="detail")
        return _empty_plugin_list_result(target)

    settings = OpenOppsSettings(cache_enabled=False, retry_attempts=1)
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "bounded-http",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="bounded-http", version="1.0.0"),
                    job_providers={"bounded_http": lambda _settings: object()},
                    url_pull_providers={
                        "bounded_http": PluginUrlPullRegistration(
                            target_parser=_parse("bounded_http"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: pull_list,
                        )
                    },
                ),
            )
        ],
        allowed={"bounded-http"},
        builtin_provider_ids=(),
        context=PluginContext(settings=settings),
    )
    bound = build_url_pull_provider(
        "bounded_http",
        settings,
        plugin_registry=registry,
    )
    target = ProviderUrlTarget(
        provider_id="bounded_http",
        target_kind=ProviderTargetKind.BOARD,
        url="https://plugin.example/acme",
        board_identity="acme",
    )

    assert bound is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with http_operation_observability():
            with http_operation_budget(
                maximum_requests=1,
                maximum_response_bytes=100,
            ):
                with pytest.raises(HttpRequestLimitError):
                    await bound.pull_list(client, target, include_unlisted=False)

    assert len(received_http) == 1
    assert len(requests) == 1
    assert requests[0].url.path == "/first"


@pytest.mark.asyncio
async def test_plugin_native_get_hook_uses_bounded_post_surfaces() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(".txt"):
            return httpx.Response(200, text="ok", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def pull_get(
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        assert await client.post_json(
            "https://plugin.example/post.json",
            role="detail",
            json_body={"id": target.posting_identity},
        ) == {"ok": True}
        assert (
            await client.post_text(
                "https://plugin.example/post.txt",
                role="detail",
                json_body={"id": target.posting_identity},
            )
            == "ok"
        )
        job = _job(provider_id=target.provider_id, remote_id="101")
        return ProviderGetResult(
            posting=ProviderPosting(
                job=job,
                listing=job.raw_listing,
                detail=job.raw_detail,
            ),
            method=ProviderGetMethod.NATIVE,
            matched_identity="101",
        )

    settings = OpenOppsSettings(cache_enabled=False, retry_attempts=1)
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "native-http",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="native-http", version="1.0.0"),
                    job_providers={"native_http": lambda _settings: object()},
                    url_pull_providers={
                        "native_http": PluginUrlPullRegistration(
                            target_parser=lambda url: ProviderUrlTarget(
                                provider_id="native_http",
                                target_kind=ProviderTargetKind.POSTING,
                                url=url,
                                board_identity="acme",
                                posting_identity="101",
                            ),
                            capabilities=_native_capabilities(),
                            native_get_hook_factory=lambda _provider: pull_get,
                        )
                    },
                ),
            )
        ],
        allowed={"native-http"},
        builtin_provider_ids=(),
        context=PluginContext(settings=settings),
    )
    bound = build_url_pull_provider(
        "native_http",
        settings,
        plugin_registry=registry,
    )
    target = ProviderUrlTarget(
        provider_id="native_http",
        target_kind=ProviderTargetKind.POSTING,
        url="https://plugin.example/acme/jobs/101",
        board_identity="acme",
        posting_identity="101",
    )

    assert bound is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with http_operation_observability():
            with http_operation_budget(
                maximum_requests=2,
                maximum_response_bytes=100,
            ):
                result = await bound.pull_get(client, target)

    assert result.matched_identity == "101"
    assert [request.url.path for request in requests] == ["/post.json", "/post.txt"]


@pytest.mark.asyncio
async def test_plugin_pull_http_enforces_shared_aggregate_response_budget() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=request.url.path.strip("/"), request=request)

    async def pull_list(
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        assert include_unlisted is False
        assert await client.get_text("https://plugin.example/abc", role="listing") == (
            "abc"
        )
        await client.get_text("https://plugin.example/def", role="detail")
        return _empty_plugin_list_result(target)

    settings = OpenOppsSettings(cache_enabled=False, retry_attempts=1)
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "aggregate-http",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="aggregate-http", version="1.0.0"),
                    job_providers={"aggregate_http": lambda _settings: object()},
                    url_pull_providers={
                        "aggregate_http": PluginUrlPullRegistration(
                            target_parser=_parse("aggregate_http"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: pull_list,
                        )
                    },
                ),
            )
        ],
        allowed={"aggregate-http"},
        builtin_provider_ids=(),
        context=PluginContext(settings=settings),
    )
    bound = build_url_pull_provider(
        "aggregate_http",
        settings,
        plugin_registry=registry,
    )
    target = ProviderUrlTarget(
        provider_id="aggregate_http",
        target_kind=ProviderTargetKind.BOARD,
        url="https://plugin.example/acme",
        board_identity="acme",
    )

    assert bound is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with http_operation_observability():
            with http_operation_budget(
                maximum_requests=2,
                maximum_response_bytes=5,
            ):
                with pytest.raises(HttpResponseLimitError) as exc_info:
                    await bound.pull_list(client, target, include_unlisted=False)

    assert exc_info.value.reason == "aggregate"
    assert [request.url.path for request in requests] == ["/abc", "/def"]


@pytest.mark.asyncio
async def test_plugin_http_client_rejects_invalid_construction_and_redirects() -> (
    None
):
    settings = OpenOppsSettings(cache_enabled=False, retry_attempts=1)
    async with httpx.AsyncClient() as client:
        with pytest.raises(TypeError, match="httpx.AsyncClient"):
            ProviderPullHttpClient(cast(Any, object()), settings, provider_id="x")
        with pytest.raises(TypeError, match="OpenOppsSettings"):
            ProviderPullHttpClient(client, cast(Any, object()), provider_id="x")
        with pytest.raises(ValueError, match="provider_id"):
            ProviderPullHttpClient(client, settings, provider_id=" ")
        with http_operation_observability():
            with http_operation_budget(
                maximum_requests=1,
                maximum_response_bytes=100,
            ):
                http = ProviderPullHttpClient(client, settings, provider_id="example")
                with pytest.raises(ValueError, match="max_redirects"):
                    await http.get_json(
                        "https://plugin.example/x",
                        role="listing",
                        max_redirects=6,
                    )
                with pytest.raises(TypeError, match="max_redirects"):
                    await http.get_text(
                        "https://plugin.example/x",
                        role="listing",
                        max_redirects=cast(Any, True),
                    )


@pytest.mark.asyncio
async def test_retained_plugin_http_facade_cannot_escape_its_operation_scope() -> None:
    retained: list[ProviderPullHttpClient] = []
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="unexpected", request=request)

    async def pull_list(
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        retained.append(client)
        return _empty_plugin_list_result(target)

    settings = OpenOppsSettings(cache_enabled=False, retry_attempts=1)
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "retained-http",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="retained-http", version="1.0.0"),
                    job_providers={"retained_http": lambda _settings: object()},
                    url_pull_providers={
                        "retained_http": PluginUrlPullRegistration(
                            target_parser=_parse("retained_http"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: pull_list,
                        )
                    },
                ),
            )
        ],
        allowed={"retained-http"},
        builtin_provider_ids=(),
        context=PluginContext(settings=settings),
    )
    bound = build_url_pull_provider(
        "retained_http",
        settings,
        plugin_registry=registry,
    )
    target = ProviderUrlTarget(
        provider_id="retained_http",
        target_kind=ProviderTargetKind.BOARD,
        url="https://plugin.example/acme",
        board_identity="acme",
    )

    assert bound is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with http_operation_observability():
            with http_operation_budget(
                maximum_requests=1,
                maximum_response_bytes=10,
            ) as budget:
                await bound.pull_list(client, target, include_unlisted=False)

        assert retained
        with pytest.raises(HttpOperationClosedError):
            await retained[0].get_text(
                "https://plugin.example/escaped",
                role="listing",
            )

    assert budget.closed
    assert requests == []


@pytest.mark.asyncio
async def test_plugin_http_rebinds_cache_scope_across_detached_tasks(
    tmp_path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=f"response-{len(requests)}",
            request=request,
        )

    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'plugin-http-context.db'}",
        retry_attempts=1,
    )
    url = "https://plugin.example/context"
    cache_scope = {"board_identity": "acme", "target_kind": "board"}

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with http_operation_observability() as first_counters:
            with http_cache_identity_scope(cache_scope):
                with http_operation_budget(
                    maximum_requests=1,
                    maximum_response_bytes=100,
                ) as first_budget:
                    first_http = ProviderPullHttpClient(
                        client,
                        settings,
                        provider_id="context_http",
                    )
                    first_body = await asyncio.create_task(
                        first_http.get_text(url, role="listing"),
                        context=Context(),
                    )
            first_snapshot = first_counters.snapshot()

        with http_operation_observability() as second_counters:
            with http_cache_identity_scope(cache_scope):
                with http_operation_budget(
                    maximum_requests=1,
                    maximum_response_bytes=100,
                ) as second_budget:
                    second_http = ProviderPullHttpClient(
                        client,
                        settings,
                        provider_id="context_http",
                    )
                    second_body = await second_http.get_text(url, role="listing")
            second_snapshot = second_counters.snapshot()

    assert first_body == second_body == "response-1"
    assert len(requests) == 1
    assert first_budget.requests_used == 1
    assert first_snapshot.cache_miss_count == 1
    assert second_budget.requests_used == 1
    assert second_snapshot.cache_hit_count == 1


def test_build_reuses_the_exact_binding_reported_by_inspection() -> None:
    settings = OpenOppsSettings()
    created_providers: list[object] = []

    def provider_factory(_settings: OpenOppsSettings) -> object:
        provider = object()
        created_providers.append(provider)
        return provider

    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "stable-binding",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="stable-binding", version="1.0.0"),
                    job_providers={"stable_binding": provider_factory},
                    url_pull_providers={
                        "stable_binding": PluginUrlPullRegistration(
                            target_parser=_parse("stable_binding"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
            )
        ],
        allowed={"stable-binding"},
        context=PluginContext(settings=settings),
    )
    state = registry.active_url_pull_state("stable_binding")
    built = build_url_pull_provider(
        "stable_binding",
        settings,
        plugin_registry=registry,
    )

    assert state is not None
    assert built is state.bound_provider
    assert len(created_providers) == 1


def test_manual_registry_cannot_bypass_hook_capability_validation() -> None:
    registry = PluginRegistry(
        contributions=(
            PluginContribution(
                metadata=PluginMetadata(name="manual", version="1.0.0"),
                job_providers={"manual": lambda _settings: object()},
                url_pull_providers={
                    "manual": PluginUrlPullRegistration(
                        target_parser=_parse("manual"),
                        capabilities=_list_capabilities(),
                    )
                },
            ),
        ),
        load_results=(),
        conflicts=(),
    ).resolve_url_pulls(builtin_provider_ids=())

    state = registry.as_dict()["urlPullProviders"][0]
    assert state["status"] == "blocked"
    assert state["resolution"] == "invalid_registration"
    assert registry.url_pull_registration("manual") is None


def test_legacy_pull_named_method_does_not_imply_url_pull_registration() -> None:
    class LegacyProvider:
        async def pull_list(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("legacy method must remain outside URL pulls")

    registry = PluginRegistry(
        contributions=(
            PluginContribution(
                metadata=PluginMetadata(name="legacy", version="1.0.0"),
                job_providers={"legacy": lambda _settings: LegacyProvider()},
            ),
        ),
        load_results=(),
        conflicts=(),
    )

    assert (
        build_url_pull_provider(
            "legacy",
            OpenOppsSettings(),
            plugin_registry=registry,
        )
        is None
    )


def test_bind_plugin_url_pull_provider_quarantines_factory_and_settings_failures() -> (
    None
):
    registration = PluginUrlPullRegistration(
        target_parser=_parse("broken"),
        capabilities=_list_capabilities(),
        list_hook_factory=lambda _provider: _contract_list_hook,
    )

    with pytest.raises(PluginUrlPullBindingError) as factory_error:
        bind_plugin_url_pull_provider(
            "broken",
            registration,
            lambda _settings: (_ for _ in ()).throw(RuntimeError("boom")),
            OpenOppsSettings(),
        )
    with pytest.raises(PluginUrlPullBindingError) as none_error:
        bind_plugin_url_pull_provider(
            "broken",
            registration,
            lambda _settings: None,
            OpenOppsSettings(),
        )
    with pytest.raises(PluginUrlPullBindingError) as settings_error:
        bind_plugin_url_pull_provider(
            "broken",
            registration,
            lambda _settings: object(),
            object(),
        )
    with pytest.raises(PluginUrlPullBindingError) as hook_error:
        bind_plugin_url_pull_provider(
            "broken",
            PluginUrlPullRegistration(
                target_parser=_parse("broken"),
                capabilities=_list_capabilities(),
                list_hook_factory=lambda _provider: (_ for _ in ()).throw(
                    RuntimeError("hook")
                ),
            ),
            lambda _settings: object(),
            OpenOppsSettings(),
        )

    assert factory_error.value.code == "provider_factory_failed"
    assert none_error.value.code == "provider_factory_returned_none"
    assert settings_error.value.code == "invalid_settings"
    assert hook_error.value.code == "invalid_list_hook"


def test_bind_captures_stdout_and_stderr_as_inspection_warnings() -> None:
    def factory(_settings: OpenOppsSettings) -> object:
        print("stdout noise")
        print("stderr noise", file=__import__("sys").stderr)
        return object()

    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "noisy",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="noisy", version="1.0.0"),
                    job_providers={"noisy": factory},
                    url_pull_providers={
                        "noisy": PluginUrlPullRegistration(
                            target_parser=_parse("noisy"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
            )
        ],
        allowed={"noisy"},
        builtin_provider_ids=(),
    )

    state = registry.as_dict()["urlPullProviders"][0]
    assert state["status"] == "active"
    assert state["warnings"] == ["captured_stdout", "captured_stderr"]


def test_entry_point_package_falls_back_to_distribution_metadata() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "meta",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="meta", version="1.0.0"),
                    job_providers={"meta": lambda _settings: object()},
                    url_pull_providers={
                        "meta": PluginUrlPullRegistration(
                            target_parser=_parse("meta"),
                            capabilities=_list_capabilities(),
                            list_hook_factory=lambda _provider: _contract_list_hook,
                        )
                    },
                ),
                dist=FakeDistribution(name=None, metadata={"Name": "from-meta"}),
            )
        ],
        allowed={"meta"},
        builtin_provider_ids=(),
    )

    assert registry.as_dict()["plugins"][0]["metadata"]["package"] == "from-meta"
    assert registry.active_url_pull_state("meta") is not None


@pytest.mark.parametrize(
    ("contribution", "message"),
    [
        (
            PluginContribution(metadata=PluginMetadata(name="", version="1.0.0")),
            "plugin metadata name is required",
        ),
        (
            PluginContribution(metadata=PluginMetadata(name="invalid", version="")),
            "plugin metadata version is required",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(
                    name="invalid",
                    version="1.0.0",
                    api_version="9.9",
                )
            ),
            "unsupported plugin api version",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                capabilities=(PluginCapability("job_provider", ""),),
            ),
            "plugin capability name is required",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                capabilities=(
                    PluginCapability("job_provider", "same"),
                    PluginCapability("job_provider", "same"),
                ),
            ),
            "duplicate plugin capability",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers={"": lambda _settings: object()},
            ),
            "contains an empty name",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers={"invalid": cast(Any, "not-callable")},
            ),
            "must be callable",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers={"invalid": lambda _settings: object()},
                url_pull_providers={
                    "invalid": PluginUrlPullRegistration(
                        target_parser=_parse("invalid"),
                        capabilities=cast(Any, object()),
                        list_hook_factory=lambda _provider: _contract_list_hook,
                    )
                },
            ),
            "must be ProviderPullCapabilities",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers={"invalid": lambda _settings: object()},
                url_pull_providers={
                    "invalid": PluginUrlPullRegistration(
                        target_parser=_parse("invalid"),
                        capabilities=_list_capabilities(),
                        list_hook_factory=cast(Any, "not-callable"),
                    )
                },
            ),
            "list_hook_factory must be callable",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers={"invalid": lambda _settings: object()},
                url_pull_providers={
                    "invalid": PluginUrlPullRegistration(
                        target_parser=_parse("invalid"),
                        capabilities=_native_capabilities(),
                        native_get_hook_factory=cast(Any, "not-callable"),
                    )
                },
            ),
            "native_get_hook_factory must be callable",
        ),
        (
            PluginContribution(
                metadata=PluginMetadata(name="invalid", version="1.0.0"),
                job_providers=cast(Any, ["not-a-mapping"]),
            ),
            "must be a mapping",
        ),
    ],
)
def test_load_plugins_reports_remaining_contribution_validation_errors(
    contribution: PluginContribution,
    message: str,
) -> None:
    registry = load_plugins(
        entry_points=[FakeEntryPoint("invalid", lambda _context: contribution)],
        allowed={"invalid"},
    )

    assert registry.as_dict()["failed"] == 1
    assert message in (registry.as_dict()["plugins"][0]["error"] or "")


def test_native_only_bound_provider_does_not_expose_list_hook() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "native-only",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="native-only", version="1.0.0"),
                    job_providers={"native_only": lambda _settings: object()},
                    url_pull_providers={
                        "native_only": PluginUrlPullRegistration(
                            target_parser=_parse("native_only"),
                            capabilities=_native_capabilities(),
                            native_get_hook_factory=lambda _provider: (
                                _contract_native_get_hook
                            ),
                        )
                    },
                ),
            )
        ],
        allowed={"native-only"},
        builtin_provider_ids=(),
    )
    bound = build_url_pull_provider(
        "native_only",
        OpenOppsSettings(),
        plugin_registry=registry,
    )

    assert bound is not None
    assert not hasattr(bound, "pull_list")
    assert callable(bound.pull_get)


def test_bind_rejects_non_callable_factory_and_raising_native_hook() -> None:
    list_registration = PluginUrlPullRegistration(
        target_parser=_parse("broken"),
        capabilities=_list_capabilities(),
        list_hook_factory=lambda _provider: _contract_list_hook,
    )
    with pytest.raises(PluginUrlPullBindingError) as factory_type:
        bind_plugin_url_pull_provider(
            "broken",
            list_registration,
            cast(Any, "not-callable"),
            OpenOppsSettings(),
        )
    with pytest.raises(PluginUrlPullBindingError) as native_error:
        bind_plugin_url_pull_provider(
            "broken",
            PluginUrlPullRegistration(
                target_parser=_parse("broken"),
                capabilities=_native_capabilities(),
                native_get_hook_factory=lambda _provider: (_ for _ in ()).throw(
                    RuntimeError("native hook")
                ),
            ),
            lambda _settings: object(),
            OpenOppsSettings(),
        )

    assert factory_type.value.code == "invalid_registration"
    assert native_error.value.code == "invalid_native_get_hook"


def test_resolve_skips_non_registration_url_pull_mapping_values() -> None:
    registry = PluginRegistry(
        contributions=(
            PluginContribution(
                metadata=PluginMetadata(name="skip", version="1.0.0"),
                job_providers={"skip": lambda _settings: object()},
                url_pull_providers={"skip": cast(Any, object())},
            ),
        ),
        load_results=(),
        conflicts=(),
    ).resolve_url_pulls(builtin_provider_ids=())

    assert registry.url_pull_registrations == ()


def test_entry_point_package_returns_none_without_distribution_identity() -> None:
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "anon",
                lambda _context: PluginContribution(
                    metadata=PluginMetadata(name="anon", version="1.0.0"),
                    job_providers={"anon": lambda _settings: object()},
                ),
                dist=FakeDistribution(name=None, metadata=None),
            )
        ],
        allowed={"anon"},
        builtin_provider_ids=(),
    )

    assert registry.as_dict()["plugins"][0]["metadata"]["package"] is None
