from __future__ import annotations

import builtins

from openopps.models import BoardProviderRecord, ProviderSupport, utc_now
from openopps.plugins import PluginContext, PluginRegistry, load_plugins
from openopps.providers.base import ProviderDefinition, ProviderKind
from openopps.providers.boards import board_provider_definitions
from openopps.providers.sources import source_provider_definitions
from openopps.settings import OpenOppsSettings
from openopps.models import validate_public_https_url
from openopps.utils import stable_id


class ProviderRegistry:
    def __init__(self, definitions: builtins.list[ProviderDefinition]):
        self._definitions = {definition.id: definition for definition in definitions}

    def list(
        self, kind: ProviderKind | None = None
    ) -> builtins.list[ProviderDefinition]:
        definitions = self._definitions.values()
        if kind:
            definitions = [
                definition for definition in definitions if definition.kind == kind
            ]
        return sorted(definitions, key=lambda item: item.id)

    def list_sources(self) -> builtins.list[ProviderDefinition]:
        return self.list(ProviderKind.BOARD_SOURCE)

    def list_board_providers(self) -> builtins.list[ProviderDefinition]:
        return self.list(ProviderKind.BOARD_PROVIDER)

    def get(self, provider_id: str) -> ProviderDefinition | None:
        return self._definitions.get(provider_id)

    def support_level(self, provider_id: str) -> ProviderSupport:
        definition = self.get(provider_id)
        if definition:
            return definition.support_level
        return ProviderSupport.UNSUPPORTED

    def source_hint_support_level(self, provider_id: str) -> ProviderSupport:
        """Classify a provider id emitted by an upstream board source."""

        support_level = self.support_level(provider_id)
        if support_level == ProviderSupport.UNSUPPORTED:
            return ProviderSupport.DETECT
        return support_level

    def detect_url(
        self,
        url: str,
        *,
        board_key: str = "manual",
        source_key: str = "manual",
    ) -> BoardProviderRecord | None:
        try:
            validate_public_https_url(url)
        except ValueError:
            return None
        definition: ProviderDefinition | None = None
        match = None
        for candidate in self.list_board_providers():
            if candidate.route_detector is None:
                continue
            try:
                match = candidate.route_detector(url)
            except ValueError:
                continue
            if match is not None:
                definition = candidate
                break
        if definition is None or match is None:
            return None

        return BoardProviderRecord(
            id=stable_id(source_key, board_key, definition.id),
            source_key=source_key,
            board_key=board_key,
            provider_id=definition.id,
            label=definition.label,
            support_level=definition.support_level,
            board_url=url,
            token=match.token,
            host=match.host,
            tenant=match.tenant,
            site=match.site,
            detected_at=utc_now(),
        )


def provider_registry(
    plugin_registry: PluginRegistry | None = None,
    settings: OpenOppsSettings | None = None,
) -> ProviderRegistry:
    definitions = [*source_provider_definitions(), *board_provider_definitions()]
    registry = plugin_registry or load_plugins(context=PluginContext(settings=settings))
    known_ids = {definition.id for definition in definitions}
    for contribution in registry.contributions:
        for capability in contribution.all_capabilities():
            if capability.name in known_ids:
                continue
            if capability.kind == "source_adapter":
                definitions.append(
                    ProviderDefinition(
                        capability.name,
                        capability.name,
                        ProviderKind.BOARD_SOURCE,
                        ProviderSupport.DETECT,
                        capability.description or "Plugin source adapter.",
                    )
                )
                known_ids.add(capability.name)
            elif capability.kind == "job_provider":
                route_detector = contribution.route_detectors.get(capability.name)
                definitions.append(
                    ProviderDefinition(
                        capability.name,
                        capability.name,
                        ProviderKind.BOARD_PROVIDER,
                        ProviderSupport.JOBS,
                        capability.description or "Plugin job provider.",
                        route_detector=route_detector,
                    )
                )
                known_ids.add(capability.name)
    return ProviderRegistry(definitions)
