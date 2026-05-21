from __future__ import annotations

from collections.abc import Callable

from openopps.models import SourceRecord
from openopps.providers.base import BoardSourceAdapter
from openopps.providers.sources.consider import (
    DEFAULT_CONSIDER_SOURCES,
    ConsiderA16zSourceAdapter,
    ConsiderSourceAdapter,
)
from openopps.providers.sources.getro import DEFAULT_GETRO_SOURCES, GetroSourceAdapter
from openopps.providers.sources.ycombinator import (
    DEFAULT_YCOMBINATOR_SOURCE,
    YCombinatorSourceAdapter,
)
from openopps.plugins import PluginContext, PluginRegistry, load_plugins
from openopps.settings import OpenOppsSettings

BoardSourceAdapterFactory = Callable[[OpenOppsSettings], BoardSourceAdapter]

BOARD_SOURCE_ADAPTERS: dict[str, BoardSourceAdapterFactory] = {
    "consider_a16z": ConsiderA16zSourceAdapter,
    "consider": ConsiderSourceAdapter,
    "getro": GetroSourceAdapter,
    "ycombinator": YCombinatorSourceAdapter,
}

DEFAULT_BOARD_SOURCES: dict[str, SourceRecord] = (
    DEFAULT_CONSIDER_SOURCES
    | DEFAULT_GETRO_SOURCES
    | {"yc": DEFAULT_YCOMBINATOR_SOURCE}
)


def build_source_adapter(
    provider_id: str,
    settings: OpenOppsSettings,
    plugin_registry: PluginRegistry | None = None,
) -> BoardSourceAdapter | None:
    adapter_cls = BOARD_SOURCE_ADAPTERS.get(provider_id)
    if adapter_cls:
        return adapter_cls(settings)
    registry = plugin_registry or load_plugins(context=PluginContext(settings=settings))
    for contribution in registry.contributions:
        adapter_factory = contribution.source_adapters.get(provider_id)
        if adapter_factory:
            return adapter_factory(settings)
    return None


__all__ = [
    "BOARD_SOURCE_ADAPTERS",
    "DEFAULT_BOARD_SOURCES",
    "BoardSourceAdapterFactory",
    "ConsiderA16zSourceAdapter",
    "ConsiderSourceAdapter",
    "DEFAULT_CONSIDER_SOURCES",
    "DEFAULT_GETRO_SOURCES",
    "DEFAULT_YCOMBINATOR_SOURCE",
    "GetroSourceAdapter",
    "YCombinatorSourceAdapter",
    "build_source_adapter",
]
