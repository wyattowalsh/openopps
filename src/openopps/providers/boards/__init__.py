from __future__ import annotations

from collections.abc import Callable

from openopps.providers.base import BoardJobProvider
from openopps.providers.boards.ashby import AshbyProvider
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.boards.workday import WorkdayProvider
from openopps.plugins import PluginContext, PluginRegistry, load_plugins
from openopps.settings import OpenOppsSettings

BoardJobProviderFactory = Callable[[OpenOppsSettings], BoardJobProvider]

BOARD_JOB_PROVIDERS: dict[str, BoardJobProviderFactory] = {
    "ashbyhq": AshbyProvider,
    "greenhouse": GreenhouseProvider,
    "lever": LeverProvider,
    "workday": WorkdayProvider,
}


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
    "AshbyProvider",
    "BoardJobProviderFactory",
    "GreenhouseProvider",
    "LeverProvider",
    "WorkdayProvider",
    "build_job_provider",
]
