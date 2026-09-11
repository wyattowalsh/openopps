from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

import httpx
import pytest

import openopps.pull_service as pull_service_module
from openopps.http import (
    HttpOperationCounters,
    HttpOperationClosedError,
    HttpRequestLimitError,
    HttpResponseLimitError,
    PublicFetchSafetyError,
    http_operation_budget,
)
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.plugins import PluginRegistry
from openopps.pull_models import (
    DiscoveryMethod,
    PullCoverageClass,
    PullDetailCoverageStatus,
    PullDomainError,
    PullErrorCode,
    PullOperation,
    PullPersistenceFailureReason,
    PullPersistenceHandoffState,
    PullProcessStatus,
    PullProvenance,
    PullResult,
    PullRetrievalMechanism,
    PullTerminalState,
)
from openopps.pull_resolver import PullResolution
from openopps.pull_service import (
    NullPullPersistence,
    OpenOppsStorePullPersistence,
    PullService,
)
from openopps.providers.pull import (
    DetailCoverageEvidence,
    InterfaceStability,
    MembershipEvidence,
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderListResult,
    ProviderPosting,
    ProviderPullBudgetError,
    ProviderPullCapabilities,
    ProviderPullHttpClient,
    ProviderRouteIdentity,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import stable_id


@dataclass
class StubResolver:
    resolution: PullResolution
    delay: float = 0.0
    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def resolve(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation,
        direct: bool,
        probe: bool,
    ) -> PullResolution:
        del client
        self.calls.append(
            {
                "url": url,
                "operation": operation,
                "direct": direct,
                "probe": probe,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.resolution


@dataclass(frozen=True)
class StubRegistry:
    capabilities: ProviderPullCapabilities | None

    def pull_capabilities(
        self,
        provider_id: str,
    ) -> ProviderPullCapabilities | None:
        del provider_id
        return self.capabilities


class StubProvider:
    def __init__(
        self,
        *,
        list_result: ProviderListResult | None = None,
        get_result: ProviderGetResult | None = None,
        list_error: Exception | None = None,
        get_error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.list_result = list_result
        self.get_result = get_result
        self.list_error = list_error
        self.get_error = get_error
        self.delay = delay
        self.list_calls: list[tuple[ProviderUrlTarget, bool]] = []
        self.get_calls: list[ProviderUrlTarget] = []

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        del client
        self.list_calls.append((target, include_unlisted))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.list_error is not None:
            raise self.list_error
        if self.list_result is None:
            raise AssertionError("unexpected list call")
        return self.list_result

    async def pull_get(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        del client
        self.get_calls.append(target)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.get_error is not None:
            raise self.get_error
        if self.get_result is None:
            raise AssertionError("unexpected get call")
        return self.get_result


class RaisingHookLookupProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __getattribute__(self, name: str) -> object:
        if name in {"pull_list", "pull_get"}:
            raise object.__getattribute__(self, "error")
        return object.__getattribute__(self, name)


class RecordingPersistence:
    def __init__(
        self,
        *,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.delay = delay
        self.error = error
        self.results: list[PullResult] = []

    async def persist(self, result: PullResult) -> None:
        self.results.append(result)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error


def _target(
    *,
    kind: ProviderTargetKind = ProviderTargetKind.BOARD,
    provider_id: str = "greenhouse",
    board_identity: str = "acme",
    posting_identity: str = "job.1",
) -> ProviderUrlTarget:
    is_posting = kind == ProviderTargetKind.POSTING
    url = (
        f"https://boards.example.test/{board_identity}/jobs/{posting_identity}"
        if is_posting
        else f"https://boards.example.test/{board_identity}"
    )
    return ProviderUrlTarget(
        provider_id=provider_id,
        target_kind=kind,
        url=url,
        board_identity=board_identity,
        posting_identity=posting_identity if is_posting else None,
    )


def _resolution(
    *,
    requested: PullOperation = PullOperation.AUTO,
    resolved: PullOperation = PullOperation.LIST,
    provider_id: str = "greenhouse",
    board_identity: str = "acme",
    posting_identity: str = "job.1",
    visited_urls: tuple[str, ...] = (),
    probed_slugs: tuple[str, ...] = (),
) -> PullResolution:
    target = _target(
        kind=(
            ProviderTargetKind.POSTING
            if resolved == PullOperation.GET
            else ProviderTargetKind.BOARD
        ),
        provider_id=provider_id,
        board_identity=board_identity,
        posting_identity=posting_identity,
    )
    return PullResolution(
        target=target,
        provenance=PullProvenance(
            requested_url=target.url,
            resolved_url=target.url,
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id=provider_id,
            requested_operation=requested,
            resolved_operation=resolved,
            board_identity=board_identity,
            posting_identity=(
                posting_identity if resolved == PullOperation.GET else None
            ),
            visited_urls=visited_urls,
            probed_slugs=probed_slugs,
        ),
    )


def _job(
    remote_id: str,
    *,
    provider_id: str = "greenhouse",
    board_identity: str = "acme",
    unlisted: bool = False,
    unique_suffix: str = "",
    with_detail: bool = False,
) -> JobRecord:
    listing = {"id": remote_id, "title": "Engineer"}
    detail = {"description": "Build reliable systems."} if with_detail else {}
    return JobRecord(
        id=f"{board_identity}:{provider_id}:{remote_id}{unique_suffix}",
        board_key=board_identity,
        provider_id=provider_id,
        remote_id=remote_id,
        title="Engineer",
        posting_url=(f"https://boards.example.test/{board_identity}/jobs/{remote_id}"),
        raw_listing=listing,
        raw_detail=detail,
        posting_kind="unlisted" if unlisted else "standard",
    )


def _posting(
    remote_id: str,
    *,
    provider_id: str = "greenhouse",
    board_identity: str = "acme",
    unlisted: bool = False,
    unique_suffix: str = "",
    with_detail: bool = False,
) -> ProviderPosting:
    job = _job(
        remote_id,
        provider_id=provider_id,
        board_identity=board_identity,
        unlisted=unlisted,
        unique_suffix=unique_suffix,
        with_detail=with_detail,
    )
    return ProviderPosting(
        job=job,
        listing=job.raw_listing,
        detail=job.raw_detail if with_detail else None,
    )


def _list_result(
    *postings: ProviderPosting,
    provider_id: str | None = None,
    board_identity: str | None = None,
    scope: MembershipScope = MembershipScope.LISTED,
    complete: bool = True,
    authoritative: bool = True,
    terminal_page_seen: bool = True,
    pages_fetched: int = 1,
    required_details: bool = False,
    requested_details: int | None = None,
    completed_details: int | None = None,
    failed_details: int = 0,
) -> ProviderListResult:
    bound_provider = (
        provider_id
        if provider_id is not None
        else postings[0].job.provider_id
        if postings
        else "greenhouse"
    )
    bound_board = (
        board_identity
        if board_identity is not None
        else postings[0].job.board_key
        if postings
        else "acme"
    )
    detail_requests = (
        len(postings)
        if required_details and requested_details is None
        else requested_details or 0
    )
    completed = detail_requests if completed_details is None else completed_details
    return ProviderListResult(
        provider_id=bound_provider,
        board_identity=bound_board,
        postings=postings,
        membership=MembershipEvidence(
            scope=scope,
            authoritative=authoritative,
            complete=complete,
            terminal_page_seen=terminal_page_seen,
            pages_fetched=pages_fetched,
            observed_count=len(postings),
            advertised_count=len(postings) if authoritative else None,
        ),
        detail_coverage=DetailCoverageEvidence(
            required=required_details,
            requested_count=detail_requests,
            completed_count=completed,
            failed_count=failed_details,
        ),
    )


def _native_get(
    remote_id: str = "job.1",
    *,
    unlisted: bool = False,
) -> ProviderGetResult:
    posting = _posting(remote_id, unlisted=unlisted, with_detail=True)
    return ProviderGetResult(
        posting=posting,
        method=ProviderGetMethod.NATIVE,
        matched_identity=remote_id,
    )


def _capabilities(
    *,
    list_supported: bool = True,
    native_get_supported: bool = False,
    board_scan_get_supported: bool = False,
    exact_unlisted_get_supported: bool = False,
    enumerate_unlisted_supported: bool = False,
) -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        list_supported=list_supported,
        native_get_supported=native_get_supported,
        board_scan_get_supported=board_scan_get_supported,
        exact_unlisted_get_supported=exact_unlisted_get_supported,
        enumerate_unlisted_supported=enumerate_unlisted_supported,
        interface_stability=InterfaceStability.DOCUMENTED,
    )


def _service(
    resolution: PullResolution,
    capabilities: ProviderPullCapabilities | None,
    provider: object,
    *,
    persistence: RecordingPersistence | None = None,
    resolver_delay: float = 0.0,
    settings: OpenOppsSettings | None = None,
    factory_error: Exception | None = None,
    catalog_has_route=None,
) -> tuple[PullService, StubResolver, list[str]]:
    resolver = StubResolver(resolution, delay=resolver_delay)
    factory_calls: list[str] = []

    def factory(provider_id: str, provider_settings: OpenOppsSettings) -> object:
        del provider_settings
        factory_calls.append(provider_id)
        if factory_error is not None:
            raise factory_error
        return provider

    service = PullService(
        settings or OpenOppsSettings(cache_enabled=False, retry_attempts=1),
        resolver=resolver,
        registry=StubRegistry(capabilities),
        provider_factory=factory,
        persistence=persistence,
        catalog_has_route=catalog_has_route,
    )
    return service, resolver, factory_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "resolved"),
    [
        (PullOperation.AUTO, PullOperation.LIST),
        (PullOperation.LIST, PullOperation.LIST),
        (PullOperation.AUTO, PullOperation.GET),
        (PullOperation.GET, PullOperation.GET),
    ],
)
async def test_service_preserves_auto_and_explicit_operation_selection(
    requested: PullOperation,
    resolved: PullOperation,
) -> None:
    resolution = _resolution(requested=requested, resolved=resolved)
    if resolved == PullOperation.LIST:
        provider = StubProvider(list_result=_list_result(_posting("job.1")))
        capabilities = _capabilities()
    else:
        provider = StubProvider(get_result=_native_get())
        capabilities = _capabilities(native_get_supported=True)
    service, resolver, _factory_calls = _service(
        resolution,
        capabilities,
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            operation=requested,
            direct=True,
            probe=False,
            no_save=True,
        )

    assert result.provenance.requested_operation == requested
    assert result.provenance.resolved_operation == resolved
    assert result.execution.mechanism == (
        PullRetrievalMechanism.LIST
        if resolved == PullOperation.LIST
        else PullRetrievalMechanism.NATIVE_GET
    )
    assert [job.remote_id for job in result.jobs] == ["job.1"]
    assert result.persisted is False
    assert resolver.calls == [
        {
            "url": str(resolution.target.url),
            "operation": requested,
            "direct": True,
            "probe": False,
        }
    ]


@pytest.mark.asyncio
async def test_service_binds_semantic_cache_scope_for_every_retrieval_mechanism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes: list[dict[str, object]] = []

    @contextmanager
    def record_scope(identity: dict[str, object]):
        scopes.append(identity)
        yield identity

    monkeypatch.setattr(
        pull_service_module,
        "http_cache_identity_scope",
        record_scope,
    )

    list_resolution = _resolution(
        requested=PullOperation.LIST,
        resolved=PullOperation.LIST,
    )
    list_service, _, _ = _service(
        list_resolution,
        _capabilities(),
        StubProvider(list_result=_list_result(_posting("job.1"))),
    )
    native_resolution = _resolution(
        requested=PullOperation.GET,
        resolved=PullOperation.GET,
    )
    native_service, _, _ = _service(
        native_resolution,
        _capabilities(native_get_supported=True),
        StubProvider(get_result=_native_get()),
    )
    scan_resolution = _resolution(
        requested=PullOperation.GET,
        resolved=PullOperation.GET,
    )
    scan_service, _, _ = _service(
        scan_resolution,
        _capabilities(
            board_scan_get_supported=True,
            exact_unlisted_get_supported=True,
            enumerate_unlisted_supported=True,
        ),
        StubProvider(
            list_result=_list_result(
                _posting("job.1"),
                scope=MembershipScope.ALL_PUBLIC,
            )
        ),
    )

    async with httpx.AsyncClient() as client:
        await list_service.pull(
            client,
            str(list_resolution.target.url),
            operation=PullOperation.LIST,
            no_save=True,
        )
        await native_service.pull(
            client,
            str(native_resolution.target.url),
            operation=PullOperation.GET,
            no_save=True,
        )
        await scan_service.pull(
            client,
            str(scan_resolution.target.url),
            operation=PullOperation.GET,
            no_save=True,
        )

    provider_scopes = [scope for scope in scopes if scope.get("phase") == "provider"]
    assert provider_scopes == [
        {
            "surface": "url_pull",
            "phase": "provider",
            "provider": "greenhouse",
            "operation": "list",
            "mechanism": "list",
            "nativeTarget": {"kind": "board", "board": "acme"},
            "membershipScope": "listed",
        },
        {
            "surface": "url_pull",
            "phase": "provider",
            "provider": "greenhouse",
            "operation": "get",
            "mechanism": "native_get",
            "nativeTarget": {
                "kind": "posting",
                "board": "acme",
                "posting": "job.1",
            },
            "membershipScope": "exact",
        },
        {
            "surface": "url_pull",
            "phase": "provider",
            "provider": "greenhouse",
            "operation": "get",
            "mechanism": "board_scan_get",
            "nativeTarget": {
                "kind": "posting",
                "board": "acme",
                "posting": "job.1",
            },
            "membershipScope": "all_public",
        },
    ]
    routed = ProviderUrlTarget(
        provider_id="greenhouse",
        target_kind=ProviderTargetKind.POSTING,
        url="https://boards.example.test/acme/jobs/job.1",
        board_identity="acme",
        posting_identity="job.1",
        route=ProviderRouteIdentity(token="tenant-1"),
    )
    assert pull_service_module._provider_cache_identity(
        routed,
        operation=PullOperation.GET,
        mechanism=PullRetrievalMechanism.NATIVE_GET,
        membership_scope="exact",
    )["nativeTarget"] == {
        "kind": "posting",
        "board": "acme",
        "posting": "job.1",
        "route": {"token": "tenant-1"},
    }


@pytest.mark.asyncio
async def test_service_preserves_resolver_explicit_incompatibility_error() -> None:
    resolution = _resolution(requested=PullOperation.LIST)
    resolver = StubResolver(
        resolution,
        error=PullDomainError(
            PullErrorCode.UNSUPPORTED_OPERATION,
            "The target is incompatible with the explicit operation.",
            hint="Choose a compatible operation.",
        ),
    )
    persistence = RecordingPersistence()
    service = PullService(
        OpenOppsSettings(),
        resolver=resolver,
        registry=StubRegistry(_capabilities()),
        provider_factory=lambda _provider_id, _settings: StubProvider(),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                operation=PullOperation.LIST,
            )

    assert exc_info.value.code == PullErrorCode.UNSUPPORTED_OPERATION
    assert persistence.results == []


@pytest.mark.asyncio
async def test_resolution_requested_url_accepts_sanitized_query_equivalence() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    service, resolver, factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
    )
    requested_url = f"{resolution.target.url}?token=secret#fragment"

    async with httpx.AsyncClient() as client:
        result = await service.pull(client, requested_url, no_save=True)

    assert result.provenance.requested_url == resolution.target.url
    assert resolver.calls[0]["url"] == requested_url
    assert factory_calls == ["greenhouse"]


@pytest.mark.asyncio
async def test_mismatched_resolution_requested_url_fails_before_provider() -> None:
    valid_resolution = _resolution(resolved=PullOperation.LIST)
    resolution = PullResolution(
        target=valid_resolution.target,
        provenance=valid_resolution.provenance.model_copy(
            update={"requested_url": "https://boards.example.test/other"}
        ),
    )
    persistence = RecordingPersistence()
    service, _resolver, factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(valid_resolution.target.url),
            )

    assert exc_info.value.code == PullErrorCode.PROVIDER_FAILED
    assert factory_calls == []
    assert persistence.results == []


@pytest.mark.asyncio
async def test_from_settings_joins_real_registry_resolver_and_native_provider(
    tmp_path: Path,
) -> None:
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    service = PullService.from_settings(
        settings,
        plugin_registry=PluginRegistry(
            contributions=(),
            load_results=(),
            conflicts=(),
        ),
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": 123,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "content": "<p>Build reliable systems.</p>",
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.pull(
            client,
            "https://boards.greenhouse.io/acme/jobs/123",
            no_save=True,
        )

    assert result.provenance.provider_id == "greenhouse"
    assert result.provenance.resolved_operation == PullOperation.GET
    assert result.execution.mechanism == PullRetrievalMechanism.NATIVE_GET
    assert [job.remote_id for job in result.jobs] == ["123"]
    assert [request.url.path for request in requests] == ["/v1/boards/acme/jobs/123"]


@pytest.mark.asyncio
async def test_native_get_is_preferred_over_available_board_scan() -> None:
    resolution = _resolution(resolved=PullOperation.GET)
    provider = StubProvider(
        list_result=_list_result(_posting("job.1")),
        get_result=_native_get(),
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(
            native_get_supported=True,
            board_scan_get_supported=True,
        ),
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert [job.remote_id for job in result.jobs] == ["job.1"]
    assert result.execution.mechanism == PullRetrievalMechanism.NATIVE_GET
    assert provider.get_calls == [resolution.target]
    assert provider.list_calls == []


@pytest.mark.asyncio
async def test_no_board_scan_fails_before_listing() -> None:
    resolution = _resolution(resolved=PullOperation.GET)
    provider = StubProvider(list_result=_list_result(_posting("job.1")))
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(board_scan_get_supported=True),
        provider,
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                no_board_scan=True,
            )

    assert exc_info.value.code == PullErrorCode.UNSUPPORTED_OPERATION
    assert provider.list_calls == []
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("list_result", "expected_code", "expected_jobs"),
    [
        (_list_result(), PullErrorCode.POSTING_NOT_FOUND, None),
        (_list_result(_posting("job.1")), None, ["job.1"]),
    ],
)
async def test_board_scan_requires_exactly_one_identity(
    list_result: ProviderListResult,
    expected_code: PullErrorCode | None,
    expected_jobs: list[str] | None,
) -> None:
    resolution = _resolution(resolved=PullOperation.GET)
    provider = StubProvider(list_result=list_result)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(board_scan_get_supported=True),
        provider,
    )

    async with httpx.AsyncClient() as client:
        if expected_code is not None:
            with pytest.raises(PullDomainError) as exc_info:
                await service.pull(
                    client,
                    str(resolution.target.url),
                    no_save=True,
                )
            assert exc_info.value.code == expected_code
        else:
            result = await service.pull(
                client,
                str(resolution.target.url),
                no_save=True,
            )
            assert [job.remote_id for job in result.jobs] == expected_jobs
            assert result.execution.mechanism == PullRetrievalMechanism.BOARD_SCAN_GET
            assert result.execution.membership is not None
            assert result.execution.membership.observed_count == 1

    assert provider.list_calls[0][0] == resolution.target.for_board_scan()


@pytest.mark.asyncio
async def test_board_scan_rejects_multiple_exact_matches_as_ambiguous() -> None:
    resolution = _resolution(resolved=PullOperation.GET)
    first = _posting("job.1", unique_suffix=":one")
    second = _posting("job.1", unique_suffix=":two")
    invalid_duplicate_result = ProviderListResult.model_construct(
        provider_id="greenhouse",
        board_identity="acme",
        postings=(first, second),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=2,
            advertised_count=2,
        ),
        detail_coverage=DetailCoverageEvidence(),
    )
    provider = StubProvider(list_result=invalid_duplicate_result)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(board_scan_get_supported=True),
        provider,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                no_save=True,
            )

    assert exc_info.value.code == PullErrorCode.AMBIGUOUS_TARGET
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.duplicate_identity_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("list_result", "list_error", "expected_code"),
    [
        (
            _list_result(
                _posting("job.1"),
                complete=False,
                authoritative=False,
                terminal_page_seen=False,
            ),
            None,
            PullErrorCode.INCOMPLETE_RESULT,
        ),
        (
            _list_result(_posting("job.1"), authoritative=False),
            None,
            PullErrorCode.NON_AUTHORITATIVE,
        ),
        (
            None,
            ValueError("listing page budget exhausted"),
            PullErrorCode.BUDGET_EXCEEDED,
        ),
    ],
)
async def test_explicit_get_board_scan_barriers_prevent_persistence(
    list_result: ProviderListResult | None,
    list_error: Exception | None,
    expected_code: PullErrorCode,
) -> None:
    resolution = _resolution(
        requested=PullOperation.GET,
        resolved=PullOperation.GET,
    )
    provider = StubProvider(list_result=list_result, list_error=list_error)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(board_scan_get_supported=True),
        provider,
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                operation=PullOperation.GET,
            )

    assert exc_info.value.code == expected_code
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.terminal_state == PullTerminalState.FAILED
    assert observability.error_code == expected_code
    assert observability.requested_operation == PullOperation.GET
    assert observability.resolved_operation == PullOperation.GET
    assert observability.retrieval_mechanism == PullRetrievalMechanism.BOARD_SCAN_GET
    assert observability.provider_id == "greenhouse"
    assert observability.persistence_handoff == (
        PullPersistenceHandoffState.NOT_ATTEMPTED
    )
    assert observability.provider_error_count == (0 if list_result is not None else 1)
    assert (observability.membership is not None) == (list_result is not None)
    assert observability.duplicate_identity_count == (
        0 if list_result is not None else None
    )
    assert provider.list_calls == [(resolution.target.for_board_scan(), False)]
    assert provider.get_calls == []
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_operation", [PullOperation.LIST, PullOperation.GET])
async def test_stale_cache_fallback_cannot_authorize_list_backed_results(
    monkeypatch: pytest.MonkeyPatch,
    resolved_operation: PullOperation,
) -> None:
    @contextmanager
    def stale_observability(*, replace_existing: bool = False):
        del replace_existing
        counters = HttpOperationCounters(cache_stale_fallback_count=1)
        try:
            yield counters
        finally:
            counters.close()

    monkeypatch.setattr(
        pull_service_module,
        "http_operation_observability",
        stale_observability,
    )
    resolution = _resolution(
        requested=resolved_operation,
        resolved=resolved_operation,
    )
    provider = StubProvider(list_result=_list_result(_posting("job.1")))
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(
            board_scan_get_supported=resolved_operation == PullOperation.GET,
        ),
        provider,
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                operation=resolved_operation,
            )

    assert exc_info.value.code == PullErrorCode.NON_AUTHORITATIVE
    assert "--refresh-cache" in exc_info.value.hint
    assert persistence.results == []
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.http.cache_stale_fallback_count == 1
    assert observability.membership is not None
    assert observability.retrieval_mechanism == (
        PullRetrievalMechanism.LIST
        if resolved_operation == PullOperation.LIST
        else PullRetrievalMechanism.BOARD_SCAN_GET
    )


@pytest.mark.asyncio
async def test_stale_native_get_is_inspectable_but_never_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def stale_observability(*, replace_existing: bool = False):
        del replace_existing
        counters = HttpOperationCounters(cache_stale_fallback_count=1)
        try:
            yield counters
        finally:
            counters.close()

    monkeypatch.setattr(
        pull_service_module,
        "http_operation_observability",
        stale_observability,
    )
    resolution = _resolution(
        requested=PullOperation.GET,
        resolved=PullOperation.GET,
    )
    provider = StubProvider(get_result=_native_get())
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(native_get_supported=True),
        provider,
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                operation=PullOperation.GET,
            )
        inspected = await service.pull(
            client,
            str(resolution.target.url),
            operation=PullOperation.GET,
            no_save=True,
        )

    assert exc_info.value.code == PullErrorCode.NON_AUTHORITATIVE
    assert "--no-save" in exc_info.value.hint
    assert persistence.results == []
    failed_observability = exc_info.value.observability
    assert failed_observability is not None
    assert failed_observability.http.cache_stale_fallback_count == 1
    assert (
        failed_observability.persistence_handoff
        == PullPersistenceHandoffState.NOT_ATTEMPTED
    )
    assert inspected.observability is not None
    assert inspected.observability.http.cache_stale_fallback_count == 1
    assert (
        inspected.observability.persistence_handoff
        == PullPersistenceHandoffState.NOT_REQUESTED
    )


@pytest.mark.asyncio
async def test_exact_unlisted_board_scan_requests_all_public_only_when_declared() -> (
    None
):
    resolution = _resolution(
        resolved=PullOperation.GET,
        provider_id="ashbyhq",
    )
    provider = StubProvider(
        list_result=_list_result(
            _posting("job.1", provider_id="ashbyhq", unlisted=True),
            scope=MembershipScope.ALL_PUBLIC,
        )
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(
            board_scan_get_supported=True,
            exact_unlisted_get_supported=True,
            enumerate_unlisted_supported=True,
        ),
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert result.jobs[0].posting_kind == "unlisted"
    assert result.execution.membership is not None
    assert result.execution.membership.scope.value == "all_public"
    assert provider.list_calls == [(resolution.target.for_board_scan(), True)]


@pytest.mark.asyncio
async def test_ordinary_list_honors_supported_unlisted_option() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    provider = StubProvider(
        list_result=_list_result(
            _posting("job.1", unlisted=True),
            scope=MembershipScope.ALL_PUBLIC,
        )
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(enumerate_unlisted_supported=True),
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            include_unlisted=True,
            no_save=True,
        )

    assert result.jobs[0].posting_kind == "unlisted"
    assert result.execution.mechanism == PullRetrievalMechanism.LIST
    assert result.execution.membership is not None
    assert result.execution.membership.scope.value == "all_public"
    assert provider.list_calls == [(resolution.target, True)]


@pytest.mark.asyncio
async def test_list_preserves_full_membership_and_optional_detail_evidence() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    provider = StubProvider(
        list_result=_list_result(
            _posting("job.1", with_detail=True),
            _posting("job.2"),
            pages_fetched=3,
            requested_details=2,
            completed_details=1,
            failed_details=1,
        )
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    execution = result.raw_envelope()["execution"]
    assert execution == {
        "mechanism": "list",
        "membership": {
            "scope": "listed",
            "authoritative": True,
            "complete": True,
            "terminal_page_seen": True,
            "pages_fetched": 3,
            "observed_count": 2,
            "advertised_count": 2,
        },
        "detail_coverage": {
            "required": False,
            "requested_count": 2,
            "completed_count": 1,
            "failed_count": 1,
            "status": "partial",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_id", "board_identity"),
    [("lever", "acme"), ("greenhouse", "other")],
)
async def test_empty_list_rejects_wrong_explicit_result_origin(
    provider_id: str,
    board_identity: str,
) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    provider = StubProvider(
        list_result=_list_result(
            provider_id=provider_id,
            board_identity=board_identity,
        )
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PROVIDER_FAILED
    assert provider.list_calls == [(resolution.target, False)]
    assert persistence.results == []


@pytest.mark.asyncio
async def test_required_detail_provider_accepts_authoritative_empty_board() -> None:
    resolution = _resolution(
        resolved=PullOperation.LIST,
        provider_id="bamboohr",
    )
    provider = StubProvider(
        list_result=_list_result(
            provider_id="bamboohr",
            required_details=True,
        )
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert result.jobs == ()
    assert result.execution.detail_coverage is not None
    assert result.execution.detail_coverage.status == PullDetailCoverageStatus.COMPLETE


@pytest.mark.asyncio
async def test_ordinary_list_rejects_unsupported_unlisted_option_before_hook() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    provider = StubProvider(list_result=_list_result())
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                include_unlisted=True,
                no_save=True,
            )

    assert exc_info.value.code == PullErrorCode.UNSUPPORTED_OPERATION
    assert provider.list_calls == []


@pytest.mark.asyncio
async def test_unsupported_list_capability_fails_before_provider_hook() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    provider = StubProvider(list_result=_list_result())
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(list_supported=False),
        provider,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(
                client,
                str(resolution.target.url),
                no_save=True,
            )

    assert exc_info.value.code == PullErrorCode.UNSUPPORTED_OPERATION
    assert provider.list_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("list_result", "expected_code"),
    [
        (
            _list_result(
                complete=False,
                authoritative=False,
                terminal_page_seen=False,
            ),
            PullErrorCode.INCOMPLETE_RESULT,
        ),
        (
            _list_result(authoritative=False),
            PullErrorCode.NON_AUTHORITATIVE,
        ),
        (
            _list_result(
                _posting("job.1"),
                required_details=True,
                completed_details=0,
                failed_details=1,
            ),
            PullErrorCode.REQUIRED_DETAIL_MISSING,
        ),
    ],
)
async def test_fail_closed_list_barriers_prevent_persistence(
    list_result: ProviderListResult,
    expected_code: PullErrorCode,
) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=list_result),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == expected_code
    assert persistence.results == []


@pytest.mark.asyncio
async def test_required_detail_coverage_must_span_full_membership() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    postings = tuple(
        _posting(f"job.{index}", with_detail=index == 0) for index in range(100)
    )
    mismatched = ProviderListResult.model_construct(
        provider_id="greenhouse",
        board_identity="acme",
        postings=postings,
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=100,
            advertised_count=100,
        ),
        detail_coverage=DetailCoverageEvidence(
            required=True,
            requested_count=1,
            completed_count=1,
        ),
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=mismatched),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.REQUIRED_DETAIL_MISSING
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ["bamboohr", "rippling", "workday"])
async def test_required_detail_provider_cannot_omit_requirement_flag(
    provider_id: str,
) -> None:
    resolution = _resolution(
        resolved=PullOperation.LIST,
        provider_id=provider_id,
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result(provider_id=provider_id)),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.REQUIRED_DETAIL_MISSING
    assert persistence.results == []


@pytest.mark.asyncio
async def test_no_save_bypasses_persistence_port_entirely() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence(error=AssertionError("must not be called"))
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result(_posting("job.1"))),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert result.persisted is False
    assert persistence.results == []


@pytest.mark.asyncio
async def test_success_emits_terminal_observability_from_preserved_evidence() -> None:
    resolution = _resolution(
        requested=PullOperation.LIST,
        resolved=PullOperation.LIST,
        visited_urls=(
            "https://careers.example.test/jobs?token=secret",
            "https://boards.example.test/acme",
        ),
        probed_slugs=("acme",),
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(
            list_result=_list_result(
                _posting("job.1", with_detail=True),
                pages_fetched=2,
                requested_details=1,
                completed_details=1,
            )
        ),
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            operation=PullOperation.LIST,
            no_save=True,
        )

    observability = result.observability
    assert observability is not None
    assert observability.terminal_state == PullTerminalState.SUCCEEDED
    assert observability.error_code is None
    assert observability.requested_operation == PullOperation.LIST
    assert observability.resolved_operation == PullOperation.LIST
    assert observability.retrieval_mechanism == PullRetrievalMechanism.LIST
    assert observability.resolver_visited_url_count == 2
    assert observability.resolver_probe_count == 1
    assert observability.membership is not None
    assert observability.membership.pages_fetched == 2
    assert observability.detail_coverage is not None
    assert observability.detail_coverage.requested_count == 1
    assert observability.duplicate_identity_count == 0
    assert observability.provider_error_count == 0
    assert observability.persistence_handoff == (
        PullPersistenceHandoffState.NOT_REQUESTED
    )
    assert observability.coverage_class is PullCoverageClass.URL_PULL_RESERVED
    assert observability.elapsed_milliseconds >= 0
    assert observability.http.request_count == 0
    assert "token=secret" not in str(observability.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_successful_persistence_happens_after_validation_and_marks_result() -> (
    None
):
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result(_posting("job.1"))),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(client, str(resolution.target.url))

    assert len(persistence.results) == 1
    persisted_input = persistence.results[0]
    persisted_input.assert_valid()
    assert persisted_input.persisted is False
    assert persisted_input.observability is None
    assert result.persisted is True
    assert result.observability is not None
    assert result.observability.persistence_handoff == (
        PullPersistenceHandoffState.SUCCEEDED
    )
    assert result.jobs == persisted_input.jobs
    assert result.raw_postings == persisted_input.raw_postings
    assert result.execution == persisted_input.execution


@pytest.mark.asyncio
async def test_constructor_without_port_still_fails_closed_on_save() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PERSISTENCE_FAILED
    assert "persistence_unavailable" not in str(exc_info.value)
    assert "persistence_unavailable" not in exc_info.value.hint
    assert "storage join" not in exc_info.value.hint.lower()
    assert "ephemeral default" in exc_info.value.hint.lower()
    assert exc_info.value.observability is not None
    assert exc_info.value.observability.persistence_reason is (
        PullPersistenceFailureReason.PERSISTENCE_UNAVAILABLE
    )


@pytest.mark.asyncio
async def test_outer_deadline_covers_resolution_and_provider_but_not_persistence() -> (
    None
):
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_timeout_seconds=0.01,
    )
    persistence = RecordingPersistence(delay=0.03)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=persistence,
        settings=settings,
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(client, str(resolution.target.url))

    assert result.persisted is True
    assert len(persistence.results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_phase", ["resolver", "provider"])
async def test_deadline_failure_never_reaches_persistence(timeout_phase: str) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_timeout_seconds=0.01,
    )
    persistence = RecordingPersistence()
    provider = StubProvider(
        list_result=_list_result(),
        delay=0.03 if timeout_phase == "provider" else 0.0,
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
        resolver_delay=0.03 if timeout_phase == "resolver" else 0.0,
        settings=settings,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert persistence.results == []


@pytest.mark.asyncio
async def test_provider_cannot_swallow_deadline_cancellation_and_return_success() -> (
    None
):
    class CancellationSwallowingProvider:
        async def pull_list(
            self,
            client: httpx.AsyncClient,
            target: ProviderUrlTarget,
            *,
            include_unlisted: bool,
        ) -> ProviderListResult:
            del client, include_unlisted
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                pass
            return _list_result(
                provider_id=target.provider_id,
                board_identity=target.board_identity,
            )

    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        CancellationSwallowingProvider(),
        persistence=persistence,
        settings=OpenOppsSettings(
            cache_enabled=False,
            retry_attempts=1,
            pull_provider_timeout_seconds=0.01,
        ),
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert persistence.results == []


class BoundedHttpProvider:
    def __init__(self, settings: OpenOppsSettings, *, reads: int) -> None:
        self.settings = settings
        self.reads = reads
        self.targets: list[ProviderUrlTarget] = []

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        assert include_unlisted is False
        self.targets.append(target)
        bounded = ProviderPullHttpClient(
            client,
            self.settings,
            provider_id="greenhouse",
        )
        for index in range(self.reads):
            await bounded.get_text(
                f"https://provider.example.test/{index}",
                role="listing",
            )
        return _list_result()


class LimitSwallowingHttpProvider:
    def __init__(
        self,
        settings: OpenOppsSettings,
        *,
        reads: int,
        swallowed_error: type[Exception],
    ) -> None:
        self.settings = settings
        self.reads = reads
        self.swallowed_error = swallowed_error

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        assert include_unlisted is False
        bounded = ProviderPullHttpClient(
            client,
            self.settings,
            provider_id=target.provider_id,
        )
        try:
            for index in range(self.reads):
                await bounded.get_text(
                    f"https://provider.example.test/{index}",
                    role="listing",
                )
        except self.swallowed_error:
            pass
        return _list_result(
            provider_id=target.provider_id,
            board_identity=target.board_identity,
        )


class DetachedHttpProvider:
    def __init__(
        self,
        settings: OpenOppsSettings,
        *,
        wait_for_timeout: bool,
    ) -> None:
        self.settings = settings
        self.wait_for_timeout = wait_for_timeout
        self.started = asyncio.Event()
        self.response_gate = asyncio.Event()
        self.provider_gate = asyncio.Event()
        self.tasks: list[asyncio.Task[str]] = []

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        assert include_unlisted is False
        bounded = ProviderPullHttpClient(
            client,
            self.settings,
            provider_id=target.provider_id,
        )
        task = asyncio.create_task(
            bounded.get_text(
                "https://provider.example.test/detached",
                role="listing",
            )
        )
        self.tasks.append(task)
        await self.started.wait()
        if self.wait_for_timeout:
            await self.provider_gate.wait()
        return _list_result(
            provider_id=target.provider_id,
            board_identity=target.board_identity,
        )


@pytest.mark.asyncio
async def test_plugin_style_provider_request_budget_maps_and_stops_before_save() -> (
    None
):
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_max_requests=1,
    )
    provider = BoundedHttpProvider(settings, reads=2)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
        settings=settings,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="x", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.http.logical_read_count == 2
    assert observability.http.request_count == 1
    assert observability.http.encoded_bytes == 1
    assert observability.http.decoded_bytes == 1
    assert observability.provider_error_count == 1
    assert len(requests) == 1
    assert persistence.results == []


@pytest.mark.asyncio
async def test_plugin_style_aggregate_byte_budget_maps_and_stops_before_save() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_max_requests=2,
        pull_provider_max_response_bytes=5,
    )
    provider = BoundedHttpProvider(settings, reads=2)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
        settings=settings,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="abc", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.http.logical_read_count == 2
    assert observability.http.request_count == 2
    assert observability.http.encoded_bytes == 6
    assert observability.http.decoded_bytes == 6
    assert observability.provider_error_count == 1
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings_overrides", "reads", "swallowed_error", "expected_code"),
    [
        (
            {"pull_provider_max_requests": 1},
            2,
            HttpRequestLimitError,
            PullErrorCode.BUDGET_EXCEEDED,
        ),
        (
            {"pull_provider_max_response_bytes": 1},
            1,
            HttpResponseLimitError,
            PullErrorCode.BUDGET_EXCEEDED,
        ),
        (
            {"http_max_decoded_response_bytes": 1},
            1,
            HttpResponseLimitError,
            PullErrorCode.RESPONSE_TOO_LARGE,
        ),
    ],
)
async def test_provider_cannot_swallow_terminal_http_limit_and_persist(
    settings_overrides: dict[str, int],
    reads: int,
    swallowed_error: type[Exception],
    expected_code: PullErrorCode,
) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings_values: dict[str, object] = {
        "cache_enabled": False,
        "retry_attempts": 1,
        "pull_provider_max_requests": 2,
        "pull_provider_max_response_bytes": 100,
    }
    settings_values.update(settings_overrides)
    settings = OpenOppsSettings.model_validate(settings_values)
    provider = LimitSwallowingHttpProvider(
        settings,
        reads=reads,
        swallowed_error=swallowed_error,
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
        settings=settings,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="abc", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == expected_code
    assert persistence.results == []


@pytest.mark.asyncio
async def test_sequential_pulls_receive_fresh_operation_budget_scopes() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_max_requests=1,
    )
    provider = BoundedHttpProvider(settings, reads=1)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        settings=settings,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="x", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )
        second = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert first.jobs == second.jobs == ()
    assert first.observability is not None
    assert second.observability is not None
    assert first.observability.http.request_count == 1
    assert second.observability.http.request_count == 1
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_service_replaces_a_looser_inherited_http_budget_scope() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_max_requests=1,
    )
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        BoundedHttpProvider(settings, reads=2),
        settings=settings,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="x", request=request)

    with http_operation_budget(
        maximum_requests=100,
        maximum_response_bytes=1_000,
    ) as inherited:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(PullDomainError) as exc_info:
                await service.pull(
                    client,
                    str(resolution.target.url),
                    no_save=True,
                )

        assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
        assert inherited.requests_used == 0
        assert inherited.response_byte_budget.used_bytes == 0
        assert inherited.closed is False

    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_for_timeout", [False, True])
async def test_detached_provider_http_work_cannot_outlive_scope_or_timeout(
    wait_for_timeout: bool,
) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_provider_timeout_seconds=0.02,
    )
    provider = DetachedHttpProvider(
        settings,
        wait_for_timeout=wait_for_timeout,
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        provider,
        persistence=persistence,
        settings=settings,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        provider.started.set()
        await provider.response_gate.wait()
        return httpx.Response(200, text="late", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if wait_for_timeout:
            with pytest.raises(PullDomainError) as exc_info:
                await service.pull(
                    client,
                    str(resolution.target.url),
                    no_save=True,
                )
            assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
        else:
            result = await service.pull(
                client,
                str(resolution.target.url),
                no_save=True,
            )
            assert result.jobs == ()

    assert len(provider.tasks) == 1
    with pytest.raises(HttpOperationClosedError):
        await provider.tasks[0]
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            ProviderPullBudgetError("detail fan-out", limit=1, observed=2),
            PullErrorCode.BUDGET_EXCEEDED,
        ),
        (
            HttpOperationClosedError(expired=False),
            PullErrorCode.BUDGET_EXCEEDED,
        ),
        (
            HttpResponseLimitError(
                "encoded",
                limit_bytes=10,
                observed_bytes=11,
            ),
            PullErrorCode.RESPONSE_TOO_LARGE,
        ),
        (
            HttpResponseLimitError(
                "decoded",
                limit_bytes=10,
                observed_bytes=11,
            ),
            PullErrorCode.RESPONSE_TOO_LARGE,
        ),
        (
            PublicFetchSafetyError("secret private destination"),
            PullErrorCode.UNSAFE_URL,
        ),
        (
            httpx.ConnectError("secret upstream host"),
            PullErrorCode.TRANSPORT_FAILED,
        ),
        (
            ValueError("secret pagination exhausted its finite page budget"),
            PullErrorCode.BUDGET_EXCEEDED,
        ),
        (
            ValueError("secret provider repeated pagination page"),
            PullErrorCode.INCOMPLETE_RESULT,
        ),
        (ValueError("secret upstream payload"), PullErrorCode.PROVIDER_FAILED),
    ],
)
async def test_provider_failures_map_to_sanitized_stable_domain_errors(
    error: Exception,
    expected_code: PullErrorCode,
) -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_error=error),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == expected_code
    assert "secret" not in str(exc_info.value)
    assert "secret" not in exc_info.value.hint
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["factory", "list", "get"])
async def test_untrusted_provider_domain_errors_cannot_impersonate_service_errors(
    phase: str,
) -> None:
    malicious = PullDomainError(
        PullErrorCode.UNSAFE_URL,
        "secret provider-controlled message",
        hint="secret provider-controlled hint",
    )
    resolved = PullOperation.GET if phase == "get" else PullOperation.LIST
    resolution = _resolution(resolved=resolved)
    provider = StubProvider(
        list_error=malicious if phase == "list" else None,
        get_error=malicious if phase == "get" else None,
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(native_get_supported=phase == "get"),
        provider,
        persistence=persistence,
        factory_error=malicious if phase == "factory" else None,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PROVIDER_FAILED
    assert "secret" not in str(exc_info.value)
    assert "secret" not in exc_info.value.hint
    assert persistence.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [PullOperation.LIST, PullOperation.GET])
async def test_provider_hook_lookup_domain_error_is_sanitized(
    resolved: PullOperation,
) -> None:
    malicious = PullDomainError(
        PullErrorCode.UNSAFE_URL,
        "secret descriptor-controlled message",
        hint="secret descriptor-controlled hint",
    )
    resolution = _resolution(resolved=resolved)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(native_get_supported=resolved == PullOperation.GET),
        RaisingHookLookupProvider(malicious),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PROVIDER_FAILED
    assert "secret" not in str(exc_info.value)
    assert "secret" not in exc_info.value.hint
    assert persistence.results == []


@pytest.mark.asyncio
async def test_provider_factory_typed_failure_cannot_impersonate_budget_error() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(),
        persistence=persistence,
        factory_error=HttpOperationClosedError(expired=True),
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PROVIDER_FAILED
    assert persistence.results == []


@pytest.mark.asyncio
async def test_required_detail_hook_failure_maps_before_persistence() -> None:
    resolution = _resolution(
        resolved=PullOperation.LIST,
        provider_id="bamboohr",
    )
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(
            list_error=ValueError(
                "BambooHR detail response did not match its listing secret"
            )
        ),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.REQUIRED_DETAIL_MISSING
    assert "secret" not in str(exc_info.value)
    assert persistence.results == []


@pytest.mark.asyncio
async def test_persistence_failure_is_sanitized_and_never_marks_success() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence(error=RuntimeError("secret database path"))
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PERSISTENCE_FAILED
    assert "secret" not in str(exc_info.value)
    observability = exc_info.value.observability
    assert observability is not None
    assert observability.terminal_state == PullTerminalState.FAILED
    assert observability.error_code == PullErrorCode.PERSISTENCE_FAILED
    assert observability.provider_error_count == 0
    assert observability.persistence_handoff == PullPersistenceHandoffState.FAILED
    assert observability.coverage_class is PullCoverageClass.NOT_APPLICABLE
    assert observability.persistence_reason is (
        PullPersistenceFailureReason.LEDGER_WRITE_FAILED
    )
    assert "persistence_unavailable" not in str(exc_info.value)
    assert "persistence_unavailable" not in exc_info.value.hint
    assert "secret" not in exc_info.value.hint
    assert len(persistence.results) == 1
    assert persistence.results[0].persisted is False


def _http_status_error(
    status: int = 429,
    *,
    url: str = "https://boards.example.test/acme",
) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(
        status,
        headers={"Retry-After": "90", "X-Request-Id": "secret-header"},
        text="secret rate limit body",
        request=request,
    )
    return httpx.HTTPStatusError(
        "429 secret upstream payload",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
async def test_exhausted_http_429_maps_to_rate_limited_without_header_dump() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    persistence = RecordingPersistence()
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_error=_http_status_error()),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url), no_save=True)

    error = exc_info.value
    assert error.code is PullErrorCode.RATE_LIMITED
    assert error.exit_code == int(PullProcessStatus.UPSTREAM_FAILED)
    assert "secret" not in str(error)
    assert "secret" not in error.hint
    assert "Retry-After" not in str(error)
    assert "Retry-After" not in error.hint
    assert "90" not in str(error)
    observability = error.observability
    assert observability is not None
    assert observability.error_code is PullErrorCode.RATE_LIMITED
    assert observability.coverage_class is PullCoverageClass.NOT_APPLICABLE
    assert observability.http is not None
    assert persistence.results == []


@pytest.mark.asyncio
async def test_overlay_known_token_attaches_overlay_packaged_coverage() -> None:
    resolution = _resolution(resolved=PullOperation.LIST, board_identity="stripe")
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(
            list_result=_list_result(
                _posting("job.1", board_identity="stripe"),
                board_identity="stripe",
            )
        ),
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert result.observability is not None
    assert result.observability.coverage_class is PullCoverageClass.OVERLAY_PACKAGED


@pytest.mark.asyncio
async def test_injected_catalog_lookup_attaches_catalog_route_coverage() -> None:
    resolution = _resolution(resolved=PullOperation.LIST)
    service, _resolver, _factory_calls = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        catalog_has_route=lambda provider_id, board_identity: (
            provider_id == "greenhouse" and board_identity == "acme"
        ),
    )

    async with httpx.AsyncClient() as client:
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert result.observability is not None
    assert result.observability.coverage_class is PullCoverageClass.CATALOG_ROUTE


class _FakeStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.lists: list[PullResult] = []
        self.gets: list[PullResult] = []

    def apply_url_pull_list(self, result: PullResult) -> None:
        if self.error is not None:
            raise self.error
        self.lists.append(result)

    def apply_url_pull_get(self, result: PullResult) -> None:
        if self.error is not None:
            raise self.error
        self.gets.append(result)


@pytest.mark.asyncio
async def test_store_port_persists_validated_list_and_get() -> None:
    store = _FakeStore()
    persistence = OpenOppsStorePullPersistence(store)
    list_resolution = _resolution(resolved=PullOperation.LIST)
    list_service, _resolver, _factory = _service(
        list_resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=persistence,
    )
    get_resolution = _resolution(resolved=PullOperation.GET)
    get_service, _get_resolver, _get_factory = _service(
        get_resolution,
        _capabilities(native_get_supported=True),
        StubProvider(get_result=_native_get()),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        listed = await list_service.pull(client, str(list_resolution.target.url))
        fetched = await get_service.pull(client, str(get_resolution.target.url))

    assert listed.persisted is True
    assert fetched.persisted is True
    assert len(store.lists) == 1
    assert len(store.gets) == 1
    store.lists[0].assert_valid()
    store.gets[0].assert_valid()
    assert store.lists[0].provenance.resolved_operation is PullOperation.LIST
    assert store.gets[0].provenance.resolved_operation is PullOperation.GET


@pytest.mark.asyncio
async def test_null_port_never_calls_store_apply() -> None:
    store = _FakeStore(error=AssertionError("must not apply"))
    resolution = _resolution(resolved=PullOperation.LIST)
    recording = RecordingPersistence()
    producer, _resolver, _factory = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=recording,
    )
    service, _null_resolver, _null_factory = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=NullPullPersistence(),
    )

    async with httpx.AsyncClient() as client:
        produced = await producer.pull(client, str(resolution.target.url))
        result = await service.pull(
            client,
            str(resolution.target.url),
            no_save=True,
        )

    assert produced.persisted is True
    assert result.persisted is False
    assert store.lists == []
    assert store.gets == []
    await NullPullPersistence().persist(recording.results[0])
    assert store.lists == []
    assert store.gets == []


def test_from_settings_wires_null_or_store_port_from_persist_flag(
    tmp_path: Path,
) -> None:
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        cache_enabled=False,
        retry_attempts=1,
    )
    plugins = PluginRegistry(
        contributions=(),
        load_results=(),
        conflicts=(),
    )
    ephemeral = PullService.from_settings(
        settings,
        plugin_registry=plugins,
        persist=False,
    )
    saved = PullService.from_settings(
        settings,
        plugin_registry=plugins,
        persist=True,
    )

    assert isinstance(ephemeral._persistence, NullPullPersistence)
    assert isinstance(saved._persistence, OpenOppsStorePullPersistence)


_CACHE_ONLY_TABLES = frozenset({"http_cache", "http_cache_metadata"})


def _sqlite_user_tables(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    with sqlite3.connect(db_path) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }


def _count_table(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )


def _empty_plugins() -> PluginRegistry:
    return PluginRegistry(
        contributions=(),
        load_results=(),
        conflicts=(),
    )


def _seed_catalog_route(settings: OpenOppsSettings, token: str) -> None:
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(
            key="manual",
            url="https://careers.example.test/catalog",
            provider_id="manual",
        )
    )
    store.upsert_boards(
        [
            BoardRecord(
                key=token,
                source_key="manual",
                remote_id=token,
                name=token,
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=stable_id("manual", token, "greenhouse"),
                source_key="manual",
                board_key=token,
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token=token,
            )
        ]
    )


def _reject_store_init_db(_self: OpenOppsStore) -> None:
    raise AssertionError("persist=False must not Alembic-bootstrap the ledger")


@pytest.mark.asyncio
async def test_from_settings_persist_false_does_not_migrate_fresh_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{db_path}",
        retry_attempts=1,
    )
    monkeypatch.setattr(
        "openopps.storage.OpenOppsStore.init_db",
        _reject_store_init_db,
    )
    service = PullService.from_settings(
        settings,
        plugin_registry=_empty_plugins(),
        persist=False,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": 123,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "content": "<p>Build reliable systems.</p>",
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.pull(
            client,
            "https://boards.greenhouse.io/acme/jobs/123",
            no_save=True,
        )

    tables = _sqlite_user_tables(db_path)
    assert result.persisted is False
    assert result.observability is not None
    assert result.observability.coverage_class is not PullCoverageClass.CATALOG_ROUTE
    assert [request.url.path for request in requests] == ["/v1/boards/acme/jobs/123"]
    assert tables <= _CACHE_ONLY_TABLES
    assert "alembic_version" not in tables
    assert "jobs" not in tables
    assert "url_pull_runs" not in tables
    assert not any(name.startswith("update_snapshot") for name in tables)


@pytest.mark.asyncio
async def test_from_settings_no_save_classifies_catalog_route_without_url_pull_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{db_path}",
        retry_attempts=1,
    )
    token = "w7catalog"
    _seed_catalog_route(settings, token)
    jobs_before = _count_table(db_path, "jobs")
    url_pull_before = _count_table(db_path, "url_pull_runs")
    monkeypatch.setattr(
        "openopps.storage.OpenOppsStore.init_db",
        _reject_store_init_db,
    )
    service = PullService.from_settings(
        settings,
        plugin_registry=_empty_plugins(),
        persist=False,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 123,
                "title": "Engineer",
                "absolute_url": f"https://boards.greenhouse.io/{token}/jobs/123",
                "content": "<p>Build reliable systems.</p>",
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.pull(
            client,
            f"https://boards.greenhouse.io/{token}/jobs/123",
            no_save=True,
        )

    assert result.observability is not None
    assert result.observability.coverage_class is PullCoverageClass.CATALOG_ROUTE
    assert result.persisted is False
    assert _count_table(db_path, "url_pull_runs") == url_pull_before == 0
    assert _count_table(db_path, "jobs") == jobs_before


@pytest.mark.asyncio
async def test_store_port_failure_is_sanitized_ledger_write() -> None:
    persistence = OpenOppsStorePullPersistence(
        _FakeStore(error=RuntimeError("secret database path"))
    )
    resolution = _resolution(resolved=PullOperation.LIST)
    service, _resolver, _factory = _service(
        resolution,
        _capabilities(),
        StubProvider(list_result=_list_result()),
        persistence=persistence,
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(PullDomainError) as exc_info:
            await service.pull(client, str(resolution.target.url))

    assert exc_info.value.code == PullErrorCode.PERSISTENCE_FAILED
    assert exc_info.value.exit_code == 9
    assert "secret" not in str(exc_info.value)
    assert "secret" not in exc_info.value.hint
    assert "persistence_unavailable" not in str(exc_info.value)
    assert "persistence_unavailable" not in exc_info.value.hint
    assert "storage join" not in exc_info.value.hint.lower()
    assert exc_info.value.observability is not None
    assert exc_info.value.observability.persistence_handoff is (
        PullPersistenceHandoffState.FAILED
    )
    assert exc_info.value.observability.persistence_reason is (
        PullPersistenceFailureReason.LEDGER_WRITE_FAILED
    )
