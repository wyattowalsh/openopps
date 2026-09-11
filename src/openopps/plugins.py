from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from enum import StrEnum
from io import StringIO
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Any

from openopps.settings import OpenOppsSettings

if TYPE_CHECKING:
    import httpx

    from openopps.providers.pull import (
        PluginProviderListHook,
        PluginProviderNativeGetHook,
        ProviderGetResult,
        ProviderListHook,
        ProviderListResult,
        ProviderNativeGetHook,
        ProviderPullCapabilities,
        ProviderTargetParser,
        ProviderUrlTarget,
    )


ENTRY_POINT_GROUP = "openopps.plugins"
PLUGIN_API_VERSION = "0.1"
_CAPABILITY_MAPPING_KINDS = {
    "source_adapter": "source_adapters",
    "job_provider": "job_providers",
    "url_pull_provider": "url_pull_providers",
    "route_detector": "route_detectors",
    "metadata_enricher": "metadata_enrichers",
    "cache_policy": "cache_policies",
    "export_contributor": "export_contributors",
    "cli_command": "cli_commands",
}

PluginListHookFactory = Callable[[Any], "PluginProviderListHook"]
PluginNativeGetHookFactory = Callable[[Any], "PluginProviderNativeGetHook"]
PluginProbeUrlBuilder = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str
    api_version: str = PLUGIN_API_VERSION
    description: str = ""
    package: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "version": self.version,
            "apiVersion": self.api_version,
            "description": self.description,
            "package": self.package,
        }


@dataclass(frozen=True)
class PluginCapability:
    kind: str
    name: str
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "key": self.key,
            "description": self.description,
        }


@dataclass(frozen=True)
class PluginUrlPullRegistration:
    """Explicit typed URL-pull seam associated with one job-provider factory."""

    target_parser: ProviderTargetParser
    capabilities: ProviderPullCapabilities
    list_hook_factory: PluginListHookFactory | None = None
    native_get_hook_factory: PluginNativeGetHookFactory | None = None
    probe_url_builder: PluginProbeUrlBuilder | None = None

    def as_dict(self, *, plugin: str, provider_id: str) -> dict[str, Any]:
        return {
            "plugin": plugin,
            "providerId": provider_id,
            "capabilities": self.capabilities.model_dump(mode="json"),
            "hasListHook": self.list_hook_factory is not None,
            "hasNativeGetHook": self.native_get_hook_factory is not None,
            "hasProbeBuilder": self.probe_url_builder is not None,
        }


class PluginUrlPullStatus(StrEnum):
    """Whether a declared plugin URL-pull seam is executable."""

    ACTIVE = "active"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BoundPluginUrlPullProvider:
    """One provider instance exposing only its validated explicit pull hooks."""

    provider_id: str
    provider: Any
    pull_capabilities: ProviderPullCapabilities
    list_hook: ProviderListHook | None = None
    native_get_hook: ProviderNativeGetHook | None = None

    def __getattr__(self, name: str) -> Any:
        if name == "pull_list":
            hook = object.__getattribute__(self, "list_hook")
            if hook is None:
                raise AttributeError(name)
            return hook
        if name == "pull_get":
            hook = object.__getattribute__(self, "native_get_hook")
            if hook is None:
                raise AttributeError(name)
            return hook
        return getattr(object.__getattribute__(self, "provider"), name)


@dataclass(frozen=True)
class PluginUrlPullRegistrationState:
    """Deterministic inspection and execution state for one plugin registration."""

    plugin: str
    provider_id: str
    registration: PluginUrlPullRegistration
    status: PluginUrlPullStatus
    resolution: str
    blocked_by: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    bound_provider: BoundPluginUrlPullProvider | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def as_dict(self) -> dict[str, Any]:
        data = {
            **self.registration.as_dict(
                plugin=self.plugin,
                provider_id=self.provider_id,
            ),
            "status": self.status.value,
            "resolution": self.resolution,
            "blockedBy": list(self.blocked_by),
        }
        if self.warnings:
            data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class PluginContribution:
    metadata: PluginMetadata
    capabilities: tuple[PluginCapability, ...] = ()
    source_adapters: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    job_providers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    url_pull_providers: Mapping[str, PluginUrlPullRegistration] = field(
        default_factory=dict
    )
    route_detectors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    metadata_enrichers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    cache_policies: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    export_contributors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    cli_commands: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    def all_capabilities(self) -> tuple[PluginCapability, ...]:
        inferred: list[PluginCapability] = []
        for kind, attr in _CAPABILITY_MAPPING_KINDS.items():
            mapping = getattr(self, attr)
            inferred.extend(PluginCapability(kind=kind, name=name) for name in mapping)
        explicit_keys = {capability.key for capability in self.capabilities}
        return self.capabilities + tuple(
            capability for capability in inferred if capability.key not in explicit_keys
        )


@dataclass(frozen=True)
class PluginConflict:
    capability: str
    existing_plugin: str
    plugin: str

    def as_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "existingPlugin": self.existing_plugin,
            "plugin": self.plugin,
        }


@dataclass(frozen=True)
class PluginLoadResult:
    entry_point: str
    metadata: PluginMetadata | None
    loaded: bool
    capabilities: tuple[PluginCapability, ...] = ()
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "entryPoint": self.entry_point,
            "metadata": self.metadata.as_dict() if self.metadata else None,
            "loaded": self.loaded,
            "capabilities": [capability.as_dict() for capability in self.capabilities],
            "error": self.error,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PluginRegistry:
    contributions: tuple[PluginContribution, ...]
    load_results: tuple[PluginLoadResult, ...]
    conflicts: tuple[PluginConflict, ...]
    disabled: tuple[str, ...] = ()
    allowed: tuple[str, ...] | None = None
    url_pull_registrations: tuple[PluginUrlPullRegistrationState, ...] = ()
    url_pull_resolution_builtin_ids: tuple[str, ...] | None = None
    url_pull_resolution_settings: Any = field(
        default=None,
        repr=False,
        compare=False,
    )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "plugins": [result.as_dict() for result in self.load_results],
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "loaded": sum(1 for result in self.load_results if result.loaded),
            "failed": sum(1 for result in self.load_results if not result.loaded),
            "filters": {
                "disabled": list(self.disabled),
                "allowed": list(self.allowed) if self.allowed is not None else None,
            },
        }
        url_pull_providers = [
            registration.as_dict() for registration in self.url_pull_registrations
        ]
        if url_pull_providers:
            data["urlPullProviders"] = url_pull_providers
        return data

    def capabilities(self, kind: str | None = None) -> dict[str, PluginCapability]:
        selected: dict[str, PluginCapability] = {}
        active_url_pulls = {
            (state.plugin, state.provider_id)
            for state in self.url_pull_registrations
            if state.status == PluginUrlPullStatus.ACTIVE
        }
        for contribution in self.contributions:
            for capability in contribution.all_capabilities():
                if (
                    capability.kind == "url_pull_provider"
                    and (
                        contribution.metadata.name,
                        capability.name,
                    )
                    not in active_url_pulls
                ):
                    continue
                if kind is None or capability.kind == kind:
                    selected[capability.key] = capability
        return selected

    def url_pull_registration(
        self, provider_id: str
    ) -> PluginUrlPullRegistration | None:
        """Return the sole validated active registration for a provider."""

        for state in self.url_pull_registrations:
            if (
                state.provider_id == provider_id
                and state.status == PluginUrlPullStatus.ACTIVE
            ):
                return state.registration
        return None

    def active_url_pull_state(
        self, provider_id: str
    ) -> PluginUrlPullRegistrationState | None:
        """Return the single active, bound registration state."""

        for state in self.url_pull_registrations:
            if (
                state.provider_id == provider_id
                and state.status == PluginUrlPullStatus.ACTIVE
            ):
                return state
        return None

    def resolve_url_pulls(
        self,
        *,
        builtin_provider_ids: Iterable[str],
        settings: Any = None,
    ) -> PluginRegistry:
        """Resolve and validate URL-pull ownership without trusting load order."""

        builtin_ids = tuple(sorted(set(builtin_provider_ids)))
        if (
            self.url_pull_resolution_builtin_ids == builtin_ids
            and self.url_pull_resolution_settings is settings
        ):
            return self
        states, conflicts = _resolve_url_pull_registrations(
            self.contributions,
            builtin_provider_ids=frozenset(builtin_ids),
            settings=settings,
        )
        base_conflicts = tuple(
            conflict
            for conflict in self.conflicts
            if not conflict.capability.startswith("url_pull_provider:")
        )
        blocked_by_plugin: dict[str, list[str]] = {}
        for state in states:
            if state.status == PluginUrlPullStatus.BLOCKED:
                blocked_by_plugin.setdefault(state.plugin, []).append(
                    f"url_pull_blocked:{state.provider_id}:{state.resolution}"
                )
            blocked_by_plugin.setdefault(state.plugin, []).extend(
                f"url_pull_{warning}:{state.provider_id}" for warning in state.warnings
            )
        for conflict in conflicts:
            blocked_by_plugin.setdefault(conflict.plugin, []).append(
                f"conflict:{conflict.capability}"
            )
        active_url_pulls = {
            (state.plugin, state.provider_id)
            for state in states
            if state.status == PluginUrlPullStatus.ACTIVE
        }
        results = tuple(
            replace(
                result,
                capabilities=tuple(
                    capability
                    for capability in result.capabilities
                    if capability.kind != "url_pull_provider"
                    or (
                        result.metadata.name if result.metadata else "",
                        capability.name,
                    )
                    in active_url_pulls
                ),
                warnings=tuple(
                    warning
                    for warning in result.warnings
                    if not warning.startswith("url_pull_blocked:")
                    and not warning.startswith("url_pull_captured_")
                    and not warning.startswith("conflict:url_pull_provider:")
                )
                + tuple(
                    sorted(
                        blocked_by_plugin.get(
                            result.metadata.name if result.metadata else "",
                            (),
                        )
                    )
                ),
            )
            for result in self.load_results
        )
        return replace(
            self,
            load_results=results,
            conflicts=base_conflicts + conflicts,
            url_pull_registrations=states,
            url_pull_resolution_builtin_ids=builtin_ids,
            url_pull_resolution_settings=settings,
        )


@dataclass(frozen=True)
class PluginContext:
    settings: Any = None
    http: Any = None
    cache: Any = None
    metrics: Any = None


def load_plugins(
    *,
    entry_points: Iterable[Any] | None = None,
    disabled: Iterable[str] = (),
    allowed: Iterable[str] | None = None,
    context: PluginContext | None = None,
    builtin_provider_ids: Iterable[str] | None = None,
) -> PluginRegistry:
    context = context or PluginContext()
    settings = context.settings
    configured_disabled = _setting_names(settings, "plugin_disabled_names")
    configured_allowed = _setting_names(settings, "plugin_allowed_names")
    disabled_names = set(disabled) | set(configured_disabled)
    allowed_names = set(allowed) if allowed is not None else None
    if allowed_names is None and configured_allowed:
        allowed_names = set(configured_allowed)
    if allowed_names is None and not getattr(settings, "plugin_autoload", False):
        allowed_names = set()
    contributions: list[PluginContribution] = []
    results: list[PluginLoadResult] = []

    selected_entry_points = _entry_points() if entry_points is None else entry_points
    for entry_point in selected_entry_points:
        entry_name = getattr(entry_point, "name", str(entry_point))
        if entry_name in disabled_names:
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error="disabled",
                )
            )
            continue
        if allowed_names is not None and entry_name not in allowed_names:
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error="not_allowed",
                )
            )
            continue
        try:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                factory = entry_point.load()
                contribution = factory(context)
            contribution = _validate_contribution(contribution, entry_point)
            output_warnings = _captured_output_warnings(stdout, stderr)
            contributions.append(contribution)
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=contribution.metadata,
                    loaded=True,
                    capabilities=contribution.all_capabilities(),
                    warnings=output_warnings,
                )
            )
        except Exception as exc:  # noqa: BLE001 - plugin failures must be isolated.
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error=str(exc),
                )
            )
    conflicts = _deterministic_capability_conflicts(tuple(contributions))
    conflict_warnings: dict[str, list[str]] = {}
    for conflict in conflicts:
        conflict_warnings.setdefault(conflict.plugin, []).append(
            f"conflict:{conflict.capability}"
        )
    results = [
        replace(
            result,
            warnings=result.warnings
            + tuple(
                sorted(
                    conflict_warnings.get(
                        result.metadata.name if result.metadata else "",
                        (),
                    )
                )
            ),
        )
        for result in results
    ]
    registry = PluginRegistry(
        contributions=tuple(contributions),
        load_results=tuple(results),
        conflicts=tuple(conflicts),
        disabled=tuple(sorted(disabled_names)),
        allowed=tuple(sorted(allowed_names)) if allowed_names is not None else None,
    )
    resolved_builtin_ids = (
        default_builtin_provider_ids()
        if builtin_provider_ids is None
        else tuple(builtin_provider_ids)
    )
    return registry.resolve_url_pulls(
        builtin_provider_ids=resolved_builtin_ids,
        settings=settings,
    )


def _entry_points() -> tuple[Any, ...]:
    entry_points = importlib_metadata.entry_points()
    return tuple(entry_points.select(group=ENTRY_POINT_GROUP))


def _validate_contribution(
    contribution: object,
    entry_point: object,
) -> PluginContribution:
    if not isinstance(contribution, PluginContribution):
        raise TypeError("plugin factory must return PluginContribution")
    package = _entry_point_package(entry_point)
    metadata = contribution.metadata
    if not metadata.name:
        raise ValueError("plugin metadata name is required")
    if not metadata.version:
        raise ValueError("plugin metadata version is required")
    if metadata.api_version != PLUGIN_API_VERSION:
        raise ValueError(
            f"unsupported plugin api version {metadata.api_version!r}; "
            f"expected {PLUGIN_API_VERSION!r}"
        )
    seen_capability_keys: set[str] = set()
    for capability in contribution.capabilities:
        if capability.kind not in _CAPABILITY_MAPPING_KINDS:
            raise ValueError(f"unsupported plugin capability kind {capability.kind!r}")
        if not capability.name:
            raise ValueError("plugin capability name is required")
        if capability.key in seen_capability_keys:
            raise ValueError(f"duplicate plugin capability {capability.key!r}")
        seen_capability_keys.add(capability.key)
        if (
            capability.kind == "url_pull_provider"
            and capability.name not in contribution.url_pull_providers
        ):
            raise ValueError(
                "url_pull_provider capability requires a typed registration"
            )
    for attr in _CAPABILITY_MAPPING_KINDS.values():
        mapping = getattr(contribution, attr)
        if not isinstance(mapping, Mapping):
            raise TypeError(f"{attr} must be a mapping")
        for name, value in mapping.items():
            if not name:
                raise ValueError(f"{attr} contains an empty name")
            if attr == "url_pull_providers":
                if not isinstance(value, PluginUrlPullRegistration):
                    raise TypeError(f"{attr}.{name} must be PluginUrlPullRegistration")
                continue
            if not callable(value):
                raise TypeError(f"{attr}.{name} must be callable")
    for provider_id, registration in contribution.url_pull_providers.items():
        _validate_url_pull_registration(
            provider_id,
            registration,
            job_providers=contribution.job_providers,
        )
    if package and metadata.package is None:
        return replace(contribution, metadata=replace(metadata, package=package))
    return contribution


def _validate_url_pull_registration(
    provider_id: str,
    registration: PluginUrlPullRegistration,
    *,
    job_providers: Mapping[str, Callable[..., Any]],
) -> None:
    from openopps.providers.pull import ProviderPullCapabilities

    if provider_id not in job_providers:
        raise ValueError(
            f"url_pull_providers.{provider_id} requires a matching job provider factory"
        )
    if not callable(registration.target_parser):
        raise TypeError(
            f"url_pull_providers.{provider_id}.target_parser must be callable"
        )
    if not isinstance(registration.capabilities, ProviderPullCapabilities):
        raise TypeError(
            f"url_pull_providers.{provider_id}.capabilities must be "
            "ProviderPullCapabilities"
        )
    if not registration.capabilities.detect_supported:
        raise ValueError(
            f"url_pull_providers.{provider_id} must declare target detection"
        )

    has_list_hook = registration.list_hook_factory is not None
    if has_list_hook != registration.capabilities.list_supported:
        if registration.capabilities.list_supported:
            raise ValueError(
                f"url_pull_providers.{provider_id} list capability requires "
                "a list hook factory"
            )
        raise ValueError(
            f"url_pull_providers.{provider_id} list hook factory requires "
            "list capability"
        )
    if has_list_hook and not callable(registration.list_hook_factory):
        raise TypeError(
            f"url_pull_providers.{provider_id}.list_hook_factory must be callable"
        )

    has_native_get_hook = registration.native_get_hook_factory is not None
    if has_native_get_hook != registration.capabilities.native_get_supported:
        if registration.capabilities.native_get_supported:
            raise ValueError(
                f"url_pull_providers.{provider_id} native-get capability requires "
                "a native-get hook factory"
            )
        raise ValueError(
            f"url_pull_providers.{provider_id} native-get hook factory requires "
            "native-get capability"
        )
    if has_native_get_hook and not callable(registration.native_get_hook_factory):
        raise TypeError(
            f"url_pull_providers.{provider_id}.native_get_hook_factory must be callable"
        )
    if registration.probe_url_builder is not None and not callable(
        registration.probe_url_builder
    ):
        raise TypeError(
            f"url_pull_providers.{provider_id}.probe_url_builder must be callable"
        )


class PluginUrlPullBindingError(ValueError):
    """Controlled plugin binding failure safe for structured inspection."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def bind_plugin_url_pull_provider(
    provider_id: str,
    registration: PluginUrlPullRegistration,
    provider_factory: Callable[..., Any],
    settings: Any,
) -> BoundPluginUrlPullProvider:
    """Instantiate a plugin provider and bind only its explicit validated hooks."""

    try:
        if not callable(provider_factory):
            raise TypeError("provider factory must be callable")
        _validate_url_pull_registration(
            provider_id,
            registration,
            job_providers={provider_id: provider_factory},
        )
    except Exception as exc:  # noqa: BLE001 - manual registries are untrusted.
        raise PluginUrlPullBindingError("invalid_registration") from exc
    try:
        provider = provider_factory(settings)
    except Exception as exc:  # noqa: BLE001 - plugin failures stay quarantined.
        raise PluginUrlPullBindingError("provider_factory_failed") from exc
    if provider is None:
        raise PluginUrlPullBindingError("provider_factory_returned_none")

    if settings is None:
        pull_settings = OpenOppsSettings()
    elif isinstance(settings, OpenOppsSettings):
        pull_settings = settings
    else:
        raise PluginUrlPullBindingError("invalid_settings")

    list_hook: ProviderListHook | None = None
    if registration.list_hook_factory is not None:
        try:
            plugin_list_hook = registration.list_hook_factory(provider)
        except Exception as exc:  # noqa: BLE001 - plugin failures stay quarantined.
            raise PluginUrlPullBindingError("invalid_list_hook") from exc
        if not callable(plugin_list_hook):
            raise PluginUrlPullBindingError("invalid_list_hook")

        async def list_hook(
            client: httpx.AsyncClient,
            target: ProviderUrlTarget,
            *,
            include_unlisted: bool,
        ) -> ProviderListResult:
            from openopps.providers.pull import ProviderPullHttpClient

            plugin_http = ProviderPullHttpClient(
                client,
                pull_settings,
                provider_id=provider_id,
            )
            return await plugin_list_hook(
                plugin_http,
                target,
                include_unlisted=include_unlisted,
            )

    native_get_hook: ProviderNativeGetHook | None = None
    if registration.native_get_hook_factory is not None:
        try:
            plugin_native_get_hook = registration.native_get_hook_factory(provider)
        except Exception as exc:  # noqa: BLE001 - plugin failures stay quarantined.
            raise PluginUrlPullBindingError("invalid_native_get_hook") from exc
        if not callable(plugin_native_get_hook):
            raise PluginUrlPullBindingError("invalid_native_get_hook")

        async def native_get_hook(
            client: httpx.AsyncClient,
            target: ProviderUrlTarget,
        ) -> ProviderGetResult:
            from openopps.providers.pull import ProviderPullHttpClient

            plugin_http = ProviderPullHttpClient(
                client,
                pull_settings,
                provider_id=provider_id,
            )
            return await plugin_native_get_hook(plugin_http, target)

    return BoundPluginUrlPullProvider(
        provider_id=provider_id,
        provider=provider,
        pull_capabilities=registration.capabilities,
        list_hook=list_hook,
        native_get_hook=native_get_hook,
    )


@dataclass(frozen=True)
class _PluginUrlPullCandidate:
    plugin: str
    owner_identity: str
    provider_id: str
    registration: PluginUrlPullRegistration
    provider_factory: Callable[..., Any]


def _resolve_url_pull_registrations(
    contributions: tuple[PluginContribution, ...],
    *,
    builtin_provider_ids: frozenset[str],
    settings: Any,
) -> tuple[
    tuple[PluginUrlPullRegistrationState, ...],
    tuple[PluginConflict, ...],
]:
    candidates: list[_PluginUrlPullCandidate] = []
    for contribution in contributions:
        plugin_name = contribution.metadata.name
        owner_identity = _plugin_owner_identity(contribution)
        for provider_id, registration in contribution.url_pull_providers.items():
            provider_factory = contribution.job_providers.get(provider_id)
            if provider_factory is None or not isinstance(
                registration, PluginUrlPullRegistration
            ):
                continue
            candidates.append(
                _PluginUrlPullCandidate(
                    plugin=plugin_name,
                    owner_identity=owner_identity,
                    provider_id=provider_id,
                    registration=registration,
                    provider_factory=provider_factory,
                )
            )

    candidates.sort(
        key=lambda candidate: (
            candidate.provider_id,
            candidate.owner_identity,
            candidate.plugin,
        )
    )
    states: list[PluginUrlPullRegistrationState] = []
    conflicts: list[PluginConflict] = []
    candidates_by_provider: dict[str, list[_PluginUrlPullCandidate]] = {}
    for candidate in candidates:
        candidates_by_provider.setdefault(candidate.provider_id, []).append(candidate)

    for provider_id, provider_candidates in sorted(candidates_by_provider.items()):
        if provider_id in builtin_provider_ids:
            blocker = f"builtin:{provider_id}"
            for candidate in provider_candidates:
                states.append(
                    _blocked_url_pull_state(
                        candidate,
                        resolution="built_in_precedence",
                        blocked_by=(blocker,),
                    )
                )
                conflicts.append(
                    PluginConflict(
                        capability=f"url_pull_provider:{provider_id}",
                        existing_plugin=blocker,
                        plugin=candidate.plugin,
                    )
                )
            continue

        validated: list[
            tuple[
                _PluginUrlPullCandidate,
                BoundPluginUrlPullProvider,
                tuple[str, ...],
            ]
        ] = []
        for candidate in provider_candidates:
            stdout = StringIO()
            stderr = StringIO()
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    bound_provider = bind_plugin_url_pull_provider(
                        provider_id,
                        candidate.registration,
                        candidate.provider_factory,
                        settings,
                    )
            except PluginUrlPullBindingError as exc:
                states.append(
                    _blocked_url_pull_state(
                        candidate,
                        resolution=exc.code,
                        blocked_by=(),
                        warnings=_captured_output_warnings(stdout, stderr),
                    )
                )
                continue
            validated.append(
                (
                    candidate,
                    bound_provider,
                    _captured_output_warnings(stdout, stderr),
                )
            )

        if len(validated) > 1:
            blockers = tuple(
                f"plugin:{candidate.owner_identity}"
                for candidate, _bound_provider, _warnings in validated
            )
            for candidate, _bound_provider, warnings in validated:
                states.append(
                    _blocked_url_pull_state(
                        candidate,
                        resolution="ambiguous_plugin_ownership",
                        blocked_by=blockers,
                        warnings=warnings,
                    )
                )
            existing_plugin = validated[0][0].plugin
            conflicts.extend(
                PluginConflict(
                    capability=f"url_pull_provider:{provider_id}",
                    existing_plugin=existing_plugin,
                    plugin=candidate.plugin,
                )
                for candidate, _bound_provider, _warnings in validated[1:]
            )
            continue
        if not validated:
            continue
        candidate, bound_provider, warnings = validated[0]
        states.append(
            PluginUrlPullRegistrationState(
                plugin=candidate.plugin,
                provider_id=provider_id,
                registration=candidate.registration,
                status=PluginUrlPullStatus.ACTIVE,
                resolution="active_plugin",
                warnings=warnings,
                bound_provider=bound_provider,
            )
        )
    states.sort(
        key=lambda state: (
            state.provider_id,
            state.plugin,
            state.resolution,
        )
    )
    return tuple(states), tuple(conflicts)


def _blocked_url_pull_state(
    candidate: _PluginUrlPullCandidate,
    *,
    resolution: str,
    blocked_by: tuple[str, ...],
    warnings: tuple[str, ...] = (),
) -> PluginUrlPullRegistrationState:
    return PluginUrlPullRegistrationState(
        plugin=candidate.plugin,
        provider_id=candidate.provider_id,
        registration=candidate.registration,
        status=PluginUrlPullStatus.BLOCKED,
        resolution=resolution,
        blocked_by=blocked_by,
        warnings=warnings,
    )


def _plugin_owner_identity(contribution: PluginContribution) -> str:
    metadata = contribution.metadata
    if metadata.package:
        return f"{metadata.name}@{metadata.package}"
    return f"{metadata.name}@{metadata.version}"


def default_builtin_provider_ids() -> tuple[str, ...]:
    from openopps.providers.boards import BOARD_JOB_PROVIDERS
    from openopps.providers.sources import BOARD_SOURCE_ADAPTERS

    return tuple(sorted({*BOARD_JOB_PROVIDERS, *BOARD_SOURCE_ADAPTERS}))


def _captured_output_warnings(stdout: StringIO, stderr: StringIO) -> tuple[str, ...]:
    warnings: list[str] = []
    if stdout.getvalue():
        warnings.append("captured_stdout")
    if stderr.getvalue():
        warnings.append("captured_stderr")
    return tuple(warnings)


def _setting_names(settings: object, attr: str) -> tuple[str, ...]:
    values = getattr(settings, attr, ()) if settings is not None else ()
    return tuple(str(value) for value in values)


def _entry_point_package(entry_point: object) -> str | None:
    dist = getattr(entry_point, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    if isinstance(name, str):
        return name
    metadata = getattr(dist, "metadata", None)
    if metadata is not None:
        return metadata.get("Name")
    return None


def _deterministic_capability_conflicts(
    contributions: tuple[PluginContribution, ...],
) -> tuple[PluginConflict, ...]:
    claims: dict[str, set[str]] = {}
    for contribution in contributions:
        for capability in contribution.all_capabilities():
            if capability.kind == "url_pull_provider":
                continue
            claims.setdefault(capability.key, set()).add(contribution.metadata.name)

    conflicts: list[PluginConflict] = []
    for capability, plugin_names in sorted(claims.items()):
        ordered_names = sorted(plugin_names)
        if len(ordered_names) < 2:
            continue
        conflicts.extend(
            PluginConflict(
                capability=capability,
                existing_plugin=ordered_names[0],
                plugin=plugin_name,
            )
            for plugin_name in ordered_names[1:]
        )
    return tuple(conflicts)
