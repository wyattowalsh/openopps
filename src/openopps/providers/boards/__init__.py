from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterable
from types import ModuleType
from typing import Any, cast

from openopps.providers.base import BoardJobProvider, ProviderDefinition, ProviderKind
from openopps.models import ProviderSupport
from openopps.plugins import (
    PluginContext,
    PluginRegistry,
    default_builtin_provider_ids,
    load_plugins,
)
from openopps.providers.pull import (
    ProviderPullCapabilities,
    ProviderTargetParser,
)
from openopps.settings import OpenOppsSettings

BoardJobProviderFactory = Callable[[OpenOppsSettings], BoardJobProvider]
ProviderProbeUrlBuilder = Callable[[str], Iterable[str]]


def _provider_modules() -> tuple[ModuleType, ...]:
    return tuple(
        importlib.import_module(module_info.name)
        for module_info in pkgutil.iter_modules(__path__, f"{__name__}.")
        if not module_info.ispkg
    )


def _provider_id(candidate: type) -> str | None:
    provider_id = getattr(candidate, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        return None
    if not callable(getattr(candidate, "fetch_jobs", None)):
        return None
    if not callable(getattr(candidate, "check_jobs", None)):
        return None
    return provider_id


def _discover_board_job_providers() -> dict[str, BoardJobProviderFactory]:
    providers: dict[str, BoardJobProviderFactory] = {}
    for module in _provider_modules():
        for _name, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module.__name__:
                continue
            provider_id = _provider_id(candidate)
            if provider_id:
                providers[provider_id] = cast(BoardJobProviderFactory, candidate)
    return dict(sorted(providers.items()))


BOARD_JOB_PROVIDERS: dict[str, BoardJobProviderFactory] = (
    _discover_board_job_providers()
)


def _url_pull_metadata(
    provider_id: str,
    provider_cls: BoardJobProviderFactory,
) -> (
    tuple[
        ProviderTargetParser,
        ProviderPullCapabilities,
        ProviderProbeUrlBuilder | None,
    ]
    | None
):
    target_parser = getattr(provider_cls, "parse_url_target", None)
    capabilities = getattr(provider_cls, "pull_capabilities", None)
    list_hook = getattr(provider_cls, "pull_list", None)
    native_get_hook = getattr(provider_cls, "pull_get", None)
    probe_builder = getattr(provider_cls, "build_probe_urls", None)
    declarations = (
        target_parser,
        capabilities,
        list_hook,
        native_get_hook,
        probe_builder,
    )
    if all(declaration is None for declaration in declarations):
        return None
    if not callable(target_parser):
        raise TypeError(f"{provider_id} URL-pull target parser must be callable")
    if not isinstance(capabilities, ProviderPullCapabilities):
        raise TypeError(
            f"{provider_id} URL-pull capabilities must be ProviderPullCapabilities"
        )
    if not capabilities.detect_supported:
        raise ValueError(f"{provider_id} URL-pull registration must support detection")

    has_list_hook = callable(list_hook)
    if has_list_hook != capabilities.list_supported:
        raise ValueError(f"{provider_id} list capability and pull_list hook must agree")
    has_native_get_hook = callable(native_get_hook)
    if has_native_get_hook != capabilities.native_get_supported:
        raise ValueError(
            f"{provider_id} native-get capability and pull_get hook must agree"
        )
    if probe_builder is not None and not callable(probe_builder):
        raise TypeError(f"{provider_id} URL probe builder must be callable")
    return (
        target_parser,
        capabilities,
        cast(ProviderProbeUrlBuilder | None, probe_builder),
    )


def _discover_url_pull_providers() -> dict[str, BoardJobProviderFactory]:
    return {
        provider_id: provider_cls
        for provider_id, provider_cls in BOARD_JOB_PROVIDERS.items()
        if _url_pull_metadata(provider_id, provider_cls) is not None
    }


BOARD_URL_PULL_PROVIDERS: dict[str, BoardJobProviderFactory] = (
    _discover_url_pull_providers()
)


def board_probe_url_builders() -> dict[str, ProviderProbeUrlBuilder]:
    builders: dict[str, ProviderProbeUrlBuilder] = {}
    for provider_id, provider_cls in BOARD_URL_PULL_PROVIDERS.items():
        metadata = _url_pull_metadata(provider_id, provider_cls)
        if metadata is not None and metadata[2] is not None:
            builders[provider_id] = metadata[2]
    return builders


def board_provider_definitions() -> tuple[ProviderDefinition, ...]:
    definitions: list[ProviderDefinition] = []
    for provider_id, provider_cls in BOARD_JOB_PROVIDERS.items():
        pull_metadata = _url_pull_metadata(provider_id, provider_cls)
        definitions.append(
            ProviderDefinition(
                id=provider_id,
                label=getattr(provider_cls, "provider_label", provider_id),
                kind=ProviderKind.BOARD_PROVIDER,
                support_level=ProviderSupport.JOBS,
                description=getattr(
                    provider_cls, "provider_description", "Public job provider."
                ),
                route_detector=getattr(provider_cls, "detect_route", None),
                target_parser=pull_metadata[0] if pull_metadata else None,
                pull_capabilities=pull_metadata[1] if pull_metadata else None,
            )
        )
    return tuple(definitions)


def build_job_provider(
    provider_id: str,
    settings: OpenOppsSettings,
    plugin_registry: PluginRegistry | None = None,
) -> BoardJobProvider | None:
    provider_cls = BOARD_JOB_PROVIDERS.get(provider_id)
    if provider_cls:
        return provider_cls(settings)
    registry = plugin_registry or load_plugins(context=PluginContext(settings=settings))
    for contribution in registry.contributions:
        provider_factory = contribution.job_providers.get(provider_id)
        if provider_factory:
            return provider_factory(settings)
    return None


def build_url_pull_provider(
    provider_id: str,
    settings: OpenOppsSettings,
    plugin_registry: PluginRegistry | None = None,
) -> Any | None:
    """Build only providers with an explicit validated URL-pull registration."""

    if provider_id in BOARD_JOB_PROVIDERS:
        provider_cls = BOARD_URL_PULL_PROVIDERS.get(provider_id)
        return provider_cls(settings) if provider_cls is not None else None
    registry = plugin_registry or load_plugins(context=PluginContext(settings=settings))
    registry = registry.resolve_url_pulls(
        builtin_provider_ids=default_builtin_provider_ids(),
        settings=settings,
    )
    state = registry.active_url_pull_state(provider_id)
    return state.bound_provider if state is not None else None


__all__ = [
    "BOARD_JOB_PROVIDERS",
    "BOARD_URL_PULL_PROVIDERS",
    "BoardJobProviderFactory",
    "ProviderProbeUrlBuilder",
    "board_probe_url_builders",
    "board_provider_definitions",
    "build_job_provider",
    "build_url_pull_provider",
]
