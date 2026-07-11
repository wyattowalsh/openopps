from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import cast

from openopps.models import SourceRecord
from openopps.models import ProviderSupport
from openopps.providers.base import BoardSourceAdapter, ProviderDefinition, ProviderKind
from openopps.plugins import PluginContext, PluginRegistry, load_plugins
from openopps.settings import OpenOppsSettings
from openopps.source_scope import validate_packaged_source_catalog

BoardSourceAdapterFactory = Callable[[OpenOppsSettings], BoardSourceAdapter]


def _source_modules() -> tuple[ModuleType, ...]:
    return tuple(
        importlib.import_module(module_info.name)
        for module_info in pkgutil.iter_modules(__path__, f"{__name__}.")
        if not module_info.ispkg
    )


def _adapter_provider_id(candidate: type) -> str | None:
    provider_id = getattr(candidate, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        return None
    if not callable(getattr(candidate, "iter_boards", None)):
        return None
    return provider_id


def _discover_source_adapters() -> dict[str, BoardSourceAdapterFactory]:
    adapters: dict[str, BoardSourceAdapterFactory] = {}
    for module in _source_modules():
        for _name, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module.__name__:
                continue
            provider_id = _adapter_provider_id(candidate)
            if provider_id:
                adapters[provider_id] = cast(BoardSourceAdapterFactory, candidate)
    return dict(sorted(adapters.items()))


def _discover_source_records() -> tuple[SourceRecord, ...]:
    records: dict[str, SourceRecord] = {}
    for module in _source_modules():
        for source in getattr(module, "SOURCE_RECORDS", ()):
            if isinstance(source, SourceRecord):
                records[source.key] = source
    return tuple(records[key] for key in sorted(records))


BOARD_SOURCE_ADAPTERS: dict[str, BoardSourceAdapterFactory] = (
    _discover_source_adapters()
)
BOARD_SOURCE_RECORDS: tuple[SourceRecord, ...] = _discover_source_records()
BOARD_SOURCE_CATALOG: dict[str, SourceRecord] = {
    source.key: source for source in BOARD_SOURCE_RECORDS
}

validate_packaged_source_catalog(BOARD_SOURCE_CATALOG)


def source_provider_definitions() -> tuple[ProviderDefinition, ...]:
    return tuple(
        ProviderDefinition(
            id=provider_id,
            label=getattr(adapter_cls, "provider_label", provider_id),
            kind=ProviderKind.BOARD_SOURCE,
            support_level=ProviderSupport.DETECT,
            description=getattr(
                adapter_cls, "provider_description", "Aggregate source adapter."
            ),
        )
        for provider_id, adapter_cls in BOARD_SOURCE_ADAPTERS.items()
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
    "BoardSourceAdapterFactory",
    "BOARD_SOURCE_CATALOG",
    "BOARD_SOURCE_RECORDS",
    "build_source_adapter",
    "source_provider_definitions",
]
