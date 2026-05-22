from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import cast

from openopps.providers.base import BoardJobProvider, ProviderDefinition, ProviderKind
from openopps.models import ProviderSupport
from openopps.plugins import PluginContext, PluginRegistry, load_plugins
from openopps.settings import OpenOppsSettings

BoardJobProviderFactory = Callable[[OpenOppsSettings], BoardJobProvider]


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


def board_provider_definitions() -> tuple[ProviderDefinition, ...]:
    return tuple(
        ProviderDefinition(
            id=provider_id,
            label=getattr(provider_cls, "provider_label", provider_id),
            kind=ProviderKind.BOARD_PROVIDER,
            support_level=ProviderSupport.JOBS,
            description=getattr(
                provider_cls, "provider_description", "Public job provider."
            ),
            route_detector=getattr(provider_cls, "detect_route", None),
        )
        for provider_id, provider_cls in BOARD_JOB_PROVIDERS.items()
    )


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


__all__ = [
    "BOARD_JOB_PROVIDERS",
    "BoardJobProviderFactory",
    "board_provider_definitions",
    "build_job_provider",
]
