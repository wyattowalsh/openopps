from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx

from openopps.http import (
    HttpOperationClosedError,
    HttpOperationCounters,
    HttpRequestLimitError,
    HttpResponseLimitError,
    PublicFetchSafetyError,
    http_cache_identity_scope,
    http_operation_budget,
    http_operation_observability,
)
from openopps.pull_coverage import (
    CatalogRoutePredicate,
    catalog_lookup_from_store,
    classify_pull_coverage,
)
from openopps.pull_models import (
    DiscoveryMethod,
    PullDetailCoverageEvidence,
    PullDomainError,
    PullErrorCode,
    PullExecutionEvidence,
    PullHttpObservability,
    PullMembershipEvidence,
    PullMembershipScope,
    PullOperation,
    PullPersistenceFailureReason,
    PullPersistenceHandoffState,
    PullProvenance,
    PullRawPosting,
    PullResult,
    PullRetrievalMechanism,
    PullTerminalObservability,
    PullTerminalState,
    sanitize_public_pull_url,
)
from openopps.pull_resolver import PullResolution, PullResolver
from openopps.providers.pull import (
    MembershipScope,
    ProviderGetMethod,
    ProviderGetResult,
    ProviderListHook,
    ProviderListResult,
    ProviderNativeGetHook,
    ProviderPosting,
    ProviderPullBudgetError,
    ProviderPullCapabilities,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings

if TYPE_CHECKING:
    from openopps.plugins import PluginRegistry


class PullResolverPort(Protocol):
    """Narrow resolver seam used by the URL-pull orchestration service."""

    async def resolve(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation,
        direct: bool,
        probe: bool,
    ) -> PullResolution: ...


class PullCapabilityRegistry(Protocol):
    """Read-only capability view required after URL resolution."""

    def pull_capabilities(
        self,
        provider_id: str,
    ) -> ProviderPullCapabilities | None: ...


class PullPersistencePort(Protocol):
    """Storage join for one fully validated provider-neutral result."""

    async def persist(self, result: PullResult) -> None: ...


class NullPullPersistence:
    """No-op persistence port for explicitly ephemeral callers and tests."""

    async def persist(self, result: PullResult) -> None:
        del result


class _UnavailablePullPersistence:
    async def persist(self, result: PullResult) -> None:
        del result
        raise RuntimeError("persistence_unavailable")


class UrlPullStorePort(Protocol):
    """Narrow store apply seam used by the opt-in URL-pull persist port."""

    def apply_url_pull_list(self, result: PullResult) -> object: ...

    def apply_url_pull_get(self, result: PullResult) -> object: ...


class OpenOppsStorePullPersistence:
    """Apply a validated list or get through the reserved URL-pull store APIs."""

    def __init__(self, store: UrlPullStorePort) -> None:
        self._store = store

    async def persist(self, result: PullResult) -> None:
        result.assert_valid()
        operation = result.provenance.resolved_operation
        if operation is PullOperation.LIST:
            self._store.apply_url_pull_list(result)
            return
        if operation is PullOperation.GET:
            self._store.apply_url_pull_get(result)
            return
        raise ValueError("persist requires a resolved list or get result")


PullProviderFactory = Callable[[str, OpenOppsSettings], object | None]

_REQUIRED_DETAIL_PROVIDER_IDS = frozenset({"bamboohr", "rippling", "workday"})
_LIST_BUDGET_FAILURE_MARKERS = (
    "page budget",
    "page limit",
)
_LIST_INCOMPLETE_FAILURE_MARKERS = (
    "advertised",
    "continuation",
    "duplicate",
    "empty page",
    "ended before",
    "more jobs than the requested page size",
    "pagination",
    "repeated",
    "sequence cursor",
    "totalcount",
    "traversal failed after the first page",
)


@dataclass
class _PullObservationState:
    """Mutable in-flight evidence copied into one immutable terminal snapshot."""

    requested_operation: PullOperation
    resolved_operation: PullOperation | None = None
    retrieval_mechanism: PullRetrievalMechanism | None = None
    provider_id: str | None = None
    board_identity: str | None = None
    discovery_method: DiscoveryMethod | None = None
    resolver_visited_url_count: int | None = None
    resolver_probe_count: int | None = None
    membership: PullMembershipEvidence | None = None
    detail_coverage: PullDetailCoverageEvidence | None = None
    duplicate_identity_count: int | None = None
    provider_attempted: bool = False
    provider_result_received: bool = False
    catalog_has_route: CatalogRoutePredicate | None = None

    def observe_resolution(self, resolution: PullResolution) -> None:
        provenance = resolution.provenance
        self.resolved_operation = provenance.resolved_operation
        self.provider_id = provenance.provider_id
        self.board_identity = provenance.board_identity
        self.discovery_method = provenance.discovery_method
        self.resolver_visited_url_count = len(provenance.visited_urls)
        self.resolver_probe_count = len(provenance.probed_slugs)

    def observe_list_result(
        self,
        result: ProviderListResult,
        *,
        mechanism: PullRetrievalMechanism,
    ) -> None:
        membership, detail_coverage = _copy_list_evidence(result)
        identities = tuple(posting.job.remote_id for posting in result.postings)
        self.retrieval_mechanism = mechanism
        self.membership = membership
        self.detail_coverage = detail_coverage
        self.duplicate_identity_count = len(identities) - len(set(identities))
        self.provider_result_received = True

    def observe_native_get(self) -> None:
        self.retrieval_mechanism = PullRetrievalMechanism.NATIVE_GET
        self.provider_result_received = True

    @property
    def provider_error_count(self) -> int | None:
        if not self.provider_attempted:
            return None
        return 0 if self.provider_result_received else 1


class PullService:
    """Resolve, retrieve, validate, and optionally persist one public URL pull."""

    def __init__(
        self,
        settings: OpenOppsSettings,
        *,
        resolver: PullResolverPort,
        registry: PullCapabilityRegistry,
        provider_factory: PullProviderFactory,
        persistence: PullPersistencePort | None = None,
        catalog_has_route: CatalogRoutePredicate | None = None,
    ) -> None:
        self.settings = settings
        self._resolver = resolver
        self._registry = registry
        self._provider_factory = provider_factory
        self._persistence = (
            persistence if persistence is not None else _UnavailablePullPersistence()
        )
        self._catalog_has_route = catalog_has_route

    @classmethod
    def from_settings(
        cls,
        settings: OpenOppsSettings,
        *,
        plugin_registry: PluginRegistry | None = None,
        persistence: PullPersistencePort | None = None,
        persist: bool = False,
        catalog_has_route: CatalogRoutePredicate | None = None,
    ) -> PullService:
        """Build the production resolver/registry/provider seams once per service.

        ``persist=False`` may construct a store for catalog coverage class, but
        that lookup reads an already-initialized sqlite only and never migrates.
        """

        from openopps.plugins import PluginContext, load_plugins
        from openopps.providers.boards import build_url_pull_provider
        from openopps.providers.registry import provider_registry
        from openopps.storage import OpenOppsStore

        plugins = plugin_registry or load_plugins(
            context=PluginContext(settings=settings)
        )
        registry = provider_registry(plugins, settings)
        # PullResolver's private structural protocol declares writable probe
        # attributes, while the concrete frozen candidate is intentionally
        # read-only. Runtime behavior is structurally compatible.
        resolver = PullResolver.from_settings(cast(Any, registry), settings)

        def build_provider(
            provider_id: str,
            provider_settings: OpenOppsSettings,
        ) -> object | None:
            return build_url_pull_provider(
                provider_id,
                provider_settings,
                plugin_registry=plugins,
            )

        lookup = catalog_has_route
        store = OpenOppsStore(settings) if persist or lookup is None else None
        if lookup is None:
            lookup = catalog_lookup_from_store(store)
        if persistence is None:
            persistence = (
                OpenOppsStorePullPersistence(store)
                if persist and store is not None
                else NullPullPersistence()
            )

        return cls(
            settings,
            resolver=resolver,
            registry=registry,
            provider_factory=build_provider,
            persistence=persistence,
            catalog_has_route=lookup,
        )

    async def pull(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation = PullOperation.AUTO,
        direct: bool = False,
        probe: bool = True,
        no_board_scan: bool = False,
        include_unlisted: bool = False,
        no_save: bool = False,
    ) -> PullResult:
        """Run one URL pull with no output side effects and an atomic save handoff."""

        requested_operation = PullOperation(operation)
        started_monotonic = monotonic()
        observation = _PullObservationState(
            requested_operation=requested_operation,
            catalog_has_route=self._catalog_has_route,
        )
        http_counters: HttpOperationCounters | None = None
        deadline_monotonic = monotonic() + float(
            self.settings.pull_provider_timeout_seconds
        )
        try:
            with http_operation_observability(replace_existing=True) as http_counters:
                async with asyncio.timeout_at(deadline_monotonic):
                    result = await self._resolve_and_retrieve(
                        client,
                        url,
                        operation=requested_operation,
                        direct=direct,
                        probe=probe,
                        no_board_scan=no_board_scan,
                        include_unlisted=include_unlisted,
                        deadline_monotonic=deadline_monotonic,
                        observation=observation,
                    )
                    result.assert_valid()
                    if http_counters.cache_stale_fallback_count > 0:
                        if (
                            result.execution.mechanism
                            != PullRetrievalMechanism.NATIVE_GET
                        ):
                            raise _domain_error(
                                PullErrorCode.NON_AUTHORITATIVE,
                                "Stale cache evidence cannot prove current board membership.",
                                "Retry with --refresh-cache before using list-backed evidence.",
                            )
                        if not no_save:
                            raise _domain_error(
                                PullErrorCode.NON_AUTHORITATIVE,
                                "Stale exact-detail evidence is available for inspection only.",
                                "Retry with --refresh-cache or pass --no-save for inspection.",
                            )
        except asyncio.CancelledError:
            raise
        except PullDomainError as exc:
            exc.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=exc.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise
        except TimeoutError as exc:
            error = _domain_error(
                PullErrorCode.BUDGET_EXCEEDED,
                "The URL pull exceeded its wall-clock budget.",
                "Retry later, narrow the operation, or raise the trusted deadline.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except (
            HttpOperationClosedError,
            HttpRequestLimitError,
            ProviderPullBudgetError,
        ) as exc:
            error = _domain_error(
                PullErrorCode.BUDGET_EXCEEDED,
                "The provider pull exhausted a configured operation budget.",
                "Narrow the operation or raise the corresponding trusted limit.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except HttpResponseLimitError as exc:
            code = (
                PullErrorCode.BUDGET_EXCEEDED
                if exc.reason == "aggregate"
                else PullErrorCode.RESPONSE_TOO_LARGE
            )
            message = (
                "The provider pull exhausted its aggregate response budget."
                if code == PullErrorCode.BUDGET_EXCEEDED
                else "A provider response exceeded its configured size limit."
            )
            error = _domain_error(
                code,
                message,
                "Narrow the operation or raise the corresponding trusted byte limit.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except PublicFetchSafetyError as exc:
            error = _domain_error(
                PullErrorCode.UNSAFE_URL,
                "The provider pull rejected an unsafe public URL destination.",
                "Use a public HTTPS provider URL without credentials or private hosts.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except httpx.HTTPStatusError as exc:
            error = _http_status_domain_error(exc)
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except httpx.TransportError as exc:
            error = _domain_error(
                PullErrorCode.TRANSPORT_FAILED,
                "A bounded provider request failed.",
                "Retry later or inspect the provider target and public endpoint.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc
        except Exception as exc:
            error = _domain_error(
                PullErrorCode.PROVIDER_FAILED,
                "The provider returned an invalid or unusable pull result.",
                "Inspect provider capabilities and retry with a supported native URL.",
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=(
                        PullPersistenceHandoffState.NOT_REQUESTED
                        if no_save
                        else PullPersistenceHandoffState.NOT_ATTEMPTED
                    ),
                )
            )
            raise error from exc

        if no_save:
            return _with_terminal_observability(
                result,
                persisted=False,
                observability=_terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.SUCCEEDED,
                    error_code=None,
                    persistence_handoff=PullPersistenceHandoffState.NOT_REQUESTED,
                ),
            )

        try:
            await self._persistence.persist(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason, message, hint = _persistence_failure(exc)
            error = _domain_error(
                PullErrorCode.PERSISTENCE_FAILED,
                message,
                hint,
            )
            error.attach_observability(
                _terminal_observability(
                    observation,
                    http_counters,
                    started_monotonic=started_monotonic,
                    terminal_state=PullTerminalState.FAILED,
                    error_code=error.code,
                    persistence_handoff=PullPersistenceHandoffState.FAILED,
                    persistence_reason=reason,
                )
            )
            raise error from exc

        return _with_terminal_observability(
            result,
            persisted=True,
            observability=_terminal_observability(
                observation,
                http_counters,
                started_monotonic=started_monotonic,
                terminal_state=PullTerminalState.SUCCEEDED,
                error_code=None,
                persistence_handoff=PullPersistenceHandoffState.SUCCEEDED,
            ),
        )

    async def _resolve_and_retrieve(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation,
        direct: bool,
        probe: bool,
        no_board_scan: bool,
        include_unlisted: bool,
        deadline_monotonic: float,
        observation: _PullObservationState,
    ) -> PullResult:
        with http_cache_identity_scope(
            {
                "surface": "url_pull",
                "phase": "resolution",
                "requestedOperation": operation.value,
                "direct": direct,
                "probe": probe,
            }
        ):
            resolution = await self._resolver.resolve(
                client,
                url,
                operation=operation,
                direct=direct,
                probe=probe,
            )
        _validate_resolution(
            resolution,
            requested_operation=operation,
            requested_url=url,
        )
        observation.observe_resolution(resolution)

        target = resolution.target
        capabilities = self._registry.pull_capabilities(target.provider_id)
        if capabilities is None or not capabilities.detect_supported:
            raise _domain_error(
                PullErrorCode.UNSUPPORTED_TARGET,
                "The resolved provider has no executable URL-pull registration.",
                "Inspect provider capabilities or choose another supported URL.",
            )

        if monotonic() >= deadline_monotonic:
            raise TimeoutError

        with http_operation_budget(
            maximum_requests=int(self.settings.pull_provider_max_requests),
            maximum_response_bytes=int(self.settings.pull_provider_max_response_bytes),
            replace_existing=True,
            deadline_monotonic=deadline_monotonic,
        ) as operation_budget:
            observation.provider_attempted = True
            try:
                provider = self._provider_factory(target.provider_id, self.settings)
            except Exception as exc:
                raise _untrusted_provider_error() from exc
            if provider is None:
                raise _domain_error(
                    PullErrorCode.UNSUPPORTED_TARGET,
                    "The resolved provider cannot be constructed for URL pulling.",
                    "Inspect provider or plugin registration before retrying.",
                )
            if resolution.provenance.resolved_operation == PullOperation.LIST:
                result = await self._retrieve_list(
                    client,
                    provider,
                    target,
                    capabilities,
                    resolution.provenance,
                    include_unlisted=include_unlisted,
                    observation=observation,
                )
            else:
                result = await self._retrieve_get(
                    client,
                    provider,
                    target,
                    capabilities,
                    resolution.provenance,
                    no_board_scan=no_board_scan,
                    observation=observation,
                )
            operation_budget.ensure_open()
            return result

    async def _retrieve_list(
        self,
        client: httpx.AsyncClient,
        provider: object,
        target: ProviderUrlTarget,
        capabilities: ProviderPullCapabilities,
        provenance: PullProvenance,
        *,
        include_unlisted: bool,
        observation: _PullObservationState,
    ) -> PullResult:
        if target.target_kind != ProviderTargetKind.BOARD:
            raise _unsupported_operation(
                "A list operation requires a provider board URL."
            )
        if not capabilities.list_supported:
            raise _unsupported_operation(
                "This provider does not support full-board URL pulls."
            )
        if include_unlisted and not capabilities.enumerate_unlisted_supported:
            raise _unsupported_operation(
                "This provider cannot enumerate unlisted public postings."
            )

        observation.retrieval_mechanism = PullRetrievalMechanism.LIST
        hook = _provider_hook(provider, "pull_list")
        membership_scope = (
            MembershipScope.ALL_PUBLIC if include_unlisted else MembershipScope.LISTED
        )
        with http_cache_identity_scope(
            _provider_cache_identity(
                target,
                operation=provenance.resolved_operation,
                mechanism=PullRetrievalMechanism.LIST,
                membership_scope=membership_scope.value,
            )
        ):
            list_result = await _call_list_hook(
                cast(ProviderListHook, hook),
                client,
                target,
                include_unlisted=include_unlisted,
            )
        if not isinstance(list_result, ProviderListResult):
            raise TypeError("provider list hook returned the wrong result type")
        observation.observe_list_result(
            list_result,
            mechanism=PullRetrievalMechanism.LIST,
        )
        _validate_list_result(
            list_result,
            target,
            expected_scope=membership_scope,
        )
        return _build_pull_result(
            provenance,
            list_result.postings,
            execution=_list_execution_evidence(
                list_result,
                mechanism=PullRetrievalMechanism.LIST,
            ),
        )

    async def _retrieve_get(
        self,
        client: httpx.AsyncClient,
        provider: object,
        target: ProviderUrlTarget,
        capabilities: ProviderPullCapabilities,
        provenance: PullProvenance,
        *,
        no_board_scan: bool,
        observation: _PullObservationState,
    ) -> PullResult:
        posting_identity = target.posting_identity
        if target.target_kind != ProviderTargetKind.POSTING or posting_identity is None:
            raise _unsupported_operation(
                "A get operation requires an exact provider posting URL."
            )

        if capabilities.native_get_supported:
            observation.retrieval_mechanism = PullRetrievalMechanism.NATIVE_GET
            hook = _provider_hook(provider, "pull_get")
            with http_cache_identity_scope(
                _provider_cache_identity(
                    target,
                    operation=provenance.resolved_operation,
                    mechanism=PullRetrievalMechanism.NATIVE_GET,
                    membership_scope="exact",
                )
            ):
                get_result = await _call_native_get_hook(
                    cast(ProviderNativeGetHook, hook),
                    client,
                    target,
                )
            if not isinstance(get_result, ProviderGetResult):
                raise TypeError("provider get hook returned the wrong result type")
            observation.observe_native_get()
            _validate_get_result(
                get_result,
                target,
                capabilities=capabilities,
                expected_method=ProviderGetMethod.NATIVE,
            )
            return _build_pull_result(
                provenance,
                (get_result.posting,),
                execution=PullExecutionEvidence(
                    mechanism=PullRetrievalMechanism.NATIVE_GET
                ),
            )

        if no_board_scan:
            raise _unsupported_operation(
                "Native exact retrieval is unavailable and board scanning is disabled."
            )
        if not capabilities.board_scan_get_supported:
            raise _unsupported_operation(
                "This provider has no supported exact-posting retrieval method."
            )
        if not capabilities.list_supported:
            raise _unsupported_operation(
                "This provider cannot perform the required authoritative board scan."
            )

        include_unlisted = (
            capabilities.exact_unlisted_get_supported
            and capabilities.enumerate_unlisted_supported
        )
        observation.retrieval_mechanism = PullRetrievalMechanism.BOARD_SCAN_GET
        hook = _provider_hook(provider, "pull_list")
        board_target = target.for_board_scan()
        membership_scope = (
            MembershipScope.ALL_PUBLIC if include_unlisted else MembershipScope.LISTED
        )
        with http_cache_identity_scope(
            _provider_cache_identity(
                target,
                operation=provenance.resolved_operation,
                mechanism=PullRetrievalMechanism.BOARD_SCAN_GET,
                membership_scope=membership_scope.value,
            )
        ):
            list_result = await _call_list_hook(
                cast(ProviderListHook, hook),
                client,
                board_target,
                include_unlisted=include_unlisted,
            )
        if not isinstance(list_result, ProviderListResult):
            raise TypeError("provider list hook returned the wrong result type")
        observation.observe_list_result(
            list_result,
            mechanism=PullRetrievalMechanism.BOARD_SCAN_GET,
        )

        _validate_list_origin(list_result, board_target)
        expected_scope = membership_scope
        _validate_list_barriers(list_result)
        matches = tuple(
            posting
            for posting in list_result.postings
            if posting.job.provider_id == target.provider_id
            and posting.job.board_key == target.board_identity
            and posting.job.remote_id == posting_identity
        )
        if not matches:
            raise _domain_error(
                PullErrorCode.POSTING_NOT_FOUND,
                "The complete provider board did not contain the exact posting.",
                "Check that the posting is still public or use a current posting URL.",
            )
        if len(matches) > 1:
            raise _domain_error(
                PullErrorCode.AMBIGUOUS_TARGET,
                "The provider board returned multiple exact posting matches.",
                "Inspect the provider result before retrying the exact retrieval.",
            )
        _validate_list_result(
            list_result,
            target.for_board_scan(),
            expected_scope=expected_scope,
        )
        get_result = ProviderGetResult.from_board_scan(
            list_result,
            provider_id=target.provider_id,
            board_identity=target.board_identity,
            posting_identity=posting_identity,
        )
        _validate_get_result(
            get_result,
            target,
            capabilities=capabilities,
            expected_method=ProviderGetMethod.BOARD_SCAN,
        )
        return _build_pull_result(
            provenance,
            (get_result.posting,),
            execution=_list_execution_evidence(
                list_result,
                mechanism=PullRetrievalMechanism.BOARD_SCAN_GET,
            ),
        )


def _validate_resolution(
    resolution: PullResolution,
    *,
    requested_operation: PullOperation,
    requested_url: str,
) -> None:
    if not isinstance(resolution, PullResolution):
        raise TypeError("resolver returned the wrong result type")
    target = resolution.target
    provenance = resolution.provenance
    if (
        provenance.provider_id != target.provider_id
        or provenance.board_identity != target.board_identity
        or provenance.posting_identity != target.posting_identity
        or provenance.resolved_url != target.url
        or provenance.requested_url != sanitize_public_pull_url(requested_url)
        or provenance.requested_operation != requested_operation
    ):
        raise ValueError("resolver target and provenance do not agree")
    if provenance.resolved_operation == PullOperation.LIST:
        if target.target_kind != ProviderTargetKind.BOARD:
            raise _unsupported_operation(
                "The resolved target is incompatible with a list operation."
            )
    elif target.target_kind != ProviderTargetKind.POSTING:
        raise _unsupported_operation(
            "The resolved target is incompatible with a get operation."
        )


def _provider_hook(provider: object, name: str) -> object:
    try:
        hook = getattr(provider, name, None)
    except Exception as exc:
        raise _untrusted_provider_error() from exc
    if not callable(hook):
        raise _domain_error(
            PullErrorCode.PROVIDER_FAILED,
            "The provider registration is missing its declared pull hook.",
            "Inspect provider or plugin capability registration before retrying.",
        )
    return hook


def _provider_cache_identity(
    target: ProviderUrlTarget,
    *,
    operation: PullOperation,
    mechanism: PullRetrievalMechanism,
    membership_scope: str,
) -> dict[str, object]:
    """Return URL-free semantic dimensions shared by every provider HTTP read."""

    native_target: dict[str, object] = {
        "kind": target.target_kind.value,
        "board": target.board_identity,
    }
    if target.posting_identity is not None:
        native_target["posting"] = target.posting_identity
    route = target.route.model_dump(mode="json", exclude_none=True)
    if route:
        native_target["route"] = route
    return {
        "surface": "url_pull",
        "phase": "provider",
        "provider": target.provider_id,
        "operation": operation.value,
        "mechanism": mechanism.value,
        "nativeTarget": native_target,
        "membershipScope": membership_scope,
    }


async def _call_list_hook(
    hook: ProviderListHook,
    client: httpx.AsyncClient,
    target: ProviderUrlTarget,
    *,
    include_unlisted: bool,
) -> ProviderListResult:
    try:
        return await hook(
            client,
            target,
            include_unlisted=include_unlisted,
        )
    except PullDomainError as exc:
        raise _untrusted_provider_error() from exc
    except (
        HttpOperationClosedError,
        HttpRequestLimitError,
        HttpResponseLimitError,
        ProviderPullBudgetError,
        PublicFetchSafetyError,
        httpx.HTTPStatusError,
        httpx.TransportError,
    ):
        raise
    except ValueError as exc:
        code = _list_value_error_code(target.provider_id, exc)
        if code is None:
            raise
        message = {
            PullErrorCode.BUDGET_EXCEEDED: (
                "The provider exhausted its finite listing-page budget."
            ),
            PullErrorCode.INCOMPLETE_RESULT: (
                "The provider could not prove complete board membership."
            ),
            PullErrorCode.REQUIRED_DETAIL_MISSING: (
                "The provider did not complete every required posting detail."
            ),
        }[code]
        raise _domain_error(
            code,
            message,
            "Retry later or inspect provider evidence and trusted pull limits.",
        ) from exc


async def _call_native_get_hook(
    hook: ProviderNativeGetHook,
    client: httpx.AsyncClient,
    target: ProviderUrlTarget,
) -> ProviderGetResult:
    try:
        return await hook(client, target)
    except PullDomainError as exc:
        raise _untrusted_provider_error() from exc


def _list_value_error_code(
    provider_id: str,
    exc: ValueError,
) -> PullErrorCode | None:
    message = str(exc).casefold()
    if any(marker in message for marker in _LIST_BUDGET_FAILURE_MARKERS) or (
        "listing traversal exceeded" in message and " pages" in message
    ):
        return PullErrorCode.BUDGET_EXCEEDED
    if provider_id in _REQUIRED_DETAIL_PROVIDER_IDS and (
        "detail" in message or "listing omitted" in message
    ):
        return PullErrorCode.REQUIRED_DETAIL_MISSING
    if any(marker in message for marker in _LIST_INCOMPLETE_FAILURE_MARKERS):
        return PullErrorCode.INCOMPLETE_RESULT
    return None


def _validate_list_barriers(result: ProviderListResult) -> None:
    membership = result.membership
    details = result.detail_coverage
    if not membership.complete or not membership.terminal_page_seen:
        raise _domain_error(
            PullErrorCode.INCOMPLETE_RESULT,
            "The provider could not prove complete board membership.",
            "Retry later or use a provider interface with complete pagination evidence.",
        )
    if not membership.authoritative:
        raise _domain_error(
            PullErrorCode.NON_AUTHORITATIVE,
            "The provider result is not authoritative for board membership.",
            "Use a supported complete provider route before saving or exact matching.",
        )
    required_details_missing = details.required and (
        not details.complete
        or details.requested_count != membership.observed_count
        or details.completed_count != membership.observed_count
        or details.failed_count != 0
    )
    required_details_undeclared = (
        result.provider_id in _REQUIRED_DETAIL_PROVIDER_IDS and not details.required
    )
    if required_details_missing or required_details_undeclared:
        raise _domain_error(
            PullErrorCode.REQUIRED_DETAIL_MISSING,
            "The provider did not prove full required posting detail coverage.",
            "Retry later or inspect provider detail availability and trusted limits.",
        )


def _validate_list_result(
    result: ProviderListResult,
    target: ProviderUrlTarget,
    *,
    expected_scope: MembershipScope,
) -> None:
    _validate_list_origin(result, target)
    _validate_list_barriers(result)
    result.assert_valid()
    if result.membership.scope != expected_scope:
        raise ValueError("provider membership scope does not match the request")
    for posting in result.postings:
        if (
            posting.job.provider_id != target.provider_id
            or posting.job.board_key != target.board_identity
        ):
            raise ValueError("provider list result does not match the resolved target")


def _validate_list_origin(
    result: ProviderListResult,
    target: ProviderUrlTarget,
) -> None:
    if (
        result.provider_id != target.provider_id
        or result.board_identity != target.board_identity
    ):
        raise ValueError(
            "provider list result origin does not match the resolved target"
        )


def _validate_get_result(
    result: ProviderGetResult,
    target: ProviderUrlTarget,
    *,
    capabilities: ProviderPullCapabilities,
    expected_method: ProviderGetMethod,
) -> None:
    result.assert_valid()
    if result.method != expected_method:
        raise ValueError("provider get method does not match the selected operation")
    posting_identity = target.posting_identity
    job = result.posting.job
    if (
        posting_identity is None
        or result.matched_identity != posting_identity
        or job.remote_id != posting_identity
        or job.provider_id != target.provider_id
        or job.board_key != target.board_identity
    ):
        raise ValueError("provider get result does not match the resolved target")
    if job.posting_kind == "unlisted" and not capabilities.exact_unlisted_get_supported:
        raise _unsupported_operation(
            "This provider does not declare exact retrieval for unlisted postings."
        )


def _build_pull_result(
    provenance: PullProvenance,
    postings: tuple[ProviderPosting, ...],
    *,
    execution: PullExecutionEvidence,
) -> PullResult:
    return PullResult(
        provenance=provenance,
        execution=execution,
        jobs=tuple(posting.job for posting in postings),
        raw_postings=tuple(
            PullRawPosting(
                job_id=posting.job.id,
                listing=posting.listing,
                detail=posting.detail,
            )
            for posting in postings
        ),
    )


def _with_terminal_observability(
    result: PullResult,
    *,
    persisted: bool,
    observability: PullTerminalObservability,
) -> PullResult:
    return PullResult(
        provenance=result.provenance,
        execution=result.execution,
        jobs=result.jobs,
        raw_postings=result.raw_postings,
        persisted=persisted,
        observability=observability,
    )


def _terminal_observability(
    state: _PullObservationState,
    http_counters: HttpOperationCounters | None,
    *,
    started_monotonic: float,
    terminal_state: PullTerminalState,
    error_code: PullErrorCode | None,
    persistence_handoff: PullPersistenceHandoffState,
    persistence_reason: PullPersistenceFailureReason | None = None,
) -> PullTerminalObservability:
    http_snapshot = http_counters.snapshot() if http_counters is not None else None
    coverage_class = classify_pull_coverage(
        provider_id=state.provider_id,
        board_identity=state.board_identity,
        terminal_state=terminal_state,
        catalog_has_route=state.catalog_has_route,
    )
    return PullTerminalObservability(
        terminal_state=terminal_state,
        error_code=error_code,
        requested_operation=state.requested_operation,
        resolved_operation=state.resolved_operation,
        retrieval_mechanism=state.retrieval_mechanism,
        provider_id=state.provider_id,
        discovery_method=state.discovery_method,
        resolver_visited_url_count=state.resolver_visited_url_count,
        resolver_probe_count=state.resolver_probe_count,
        http=PullHttpObservability(
            **(
                {
                    "logical_read_count": http_snapshot.logical_read_count,
                    "request_count": http_snapshot.request_count,
                    "redirect_count": http_snapshot.redirect_count,
                    "retry_count": http_snapshot.retry_count,
                    "cache_hit_count": http_snapshot.cache_hit_count,
                    "cache_miss_count": http_snapshot.cache_miss_count,
                    "cache_revalidation_count": http_snapshot.cache_revalidation_count,
                    "cache_stale_fallback_count": (
                        http_snapshot.cache_stale_fallback_count
                    ),
                    "cache_write_count": http_snapshot.cache_write_count,
                    "cache_bypass_count": http_snapshot.cache_bypass_count,
                    "encoded_bytes": http_snapshot.encoded_bytes,
                    "decoded_bytes": http_snapshot.decoded_bytes,
                }
                if http_snapshot is not None
                else {}
            )
        ),
        membership=state.membership,
        detail_coverage=state.detail_coverage,
        duplicate_identity_count=state.duplicate_identity_count,
        provider_error_count=state.provider_error_count,
        persistence_handoff=persistence_handoff,
        coverage_class=coverage_class,
        persistence_reason=persistence_reason,
        elapsed_milliseconds=max(
            0,
            int((monotonic() - started_monotonic) * 1_000),
        ),
    )


def _copy_list_evidence(
    result: ProviderListResult,
) -> tuple[PullMembershipEvidence, PullDetailCoverageEvidence]:
    membership = result.membership
    details = result.detail_coverage
    return (
        PullMembershipEvidence(
            scope=PullMembershipScope(membership.scope.value),
            authoritative=membership.authoritative,
            complete=membership.complete,
            terminal_page_seen=membership.terminal_page_seen,
            pages_fetched=membership.pages_fetched,
            observed_count=membership.observed_count,
            advertised_count=membership.advertised_count,
        ),
        PullDetailCoverageEvidence(
            required=details.required,
            requested_count=details.requested_count,
            completed_count=details.completed_count,
            failed_count=details.failed_count,
        ),
    )


def _list_execution_evidence(
    result: ProviderListResult,
    *,
    mechanism: PullRetrievalMechanism,
) -> PullExecutionEvidence:
    membership, detail_coverage = _copy_list_evidence(result)
    return PullExecutionEvidence(
        mechanism=mechanism,
        membership=membership,
        detail_coverage=detail_coverage,
    )


def _unsupported_operation(message: str) -> PullDomainError:
    return _domain_error(
        PullErrorCode.UNSUPPORTED_OPERATION,
        message,
        "Inspect provider capabilities or choose a compatible URL and operation.",
    )


def _untrusted_provider_error() -> PullDomainError:
    return _domain_error(
        PullErrorCode.PROVIDER_FAILED,
        "The provider failed during URL-pull execution.",
        "Inspect provider or plugin health before retrying the pull.",
    )


def _http_status_domain_error(exc: httpx.HTTPStatusError) -> PullDomainError:
    if exc.response.status_code == 429:
        return _domain_error(
            PullErrorCode.RATE_LIMITED,
            "The provider rate-limited this URL pull after retries.",
            "Wait and retry later, or reduce concurrent public requests.",
        )
    return _untrusted_provider_error()


def _persistence_failure(
    exc: BaseException,
) -> tuple[PullPersistenceFailureReason, str, str]:
    unavailable = (
        isinstance(exc, RuntimeError) and str(exc) == "persistence_unavailable"
    )
    if unavailable:
        return (
            PullPersistenceFailureReason.PERSISTENCE_UNAVAILABLE,
            "The validated pull could not be saved because persistence is unavailable.",
            "Omit --save to keep the ephemeral default.",
        )
    return (
        PullPersistenceFailureReason.LEDGER_WRITE_FAILED,
        "The validated pull could not be saved to the local ledger.",
        (
            "Retry --save after the ledger is writable, or omit --save to keep "
            "the ephemeral default."
        ),
    )


def _domain_error(
    code: PullErrorCode,
    message: str,
    hint: str,
) -> PullDomainError:
    return PullDomainError(code, message, hint=hint)
