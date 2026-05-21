from __future__ import annotations

import builtins
from urllib.parse import urlparse

from openopps.models import BoardProviderRecord, ProviderSupport, utc_now
from openopps.plugins import PluginRegistry, load_plugins
from openopps.providers.base import ProviderDefinition, ProviderKind
from openopps.providers.boards.workday import parse_workday_board_url
from openopps.url_validation import host_matches, validate_public_https_url
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
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path_parts = [part for part in parsed.path.split("/") if part]
        provider_id: str | None = None
        token: str | None = None
        tenant: str | None = None
        site: str | None = None

        if host_matches(host, "greenhouse.io"):
            provider_id = "greenhouse"
            token = path_parts[0] if path_parts else None
        elif host == "jobs.lever.co" or host.endswith(".lever.co"):
            provider_id = "lever"
            token = path_parts[0] if path_parts else None
        elif host == "jobs.ashbyhq.com":
            provider_id = "ashbyhq"
            token = path_parts[0] if path_parts else None
        elif host_matches(host, "myworkdayjobs.com"):
            try:
                parsed_workday = parse_workday_board_url(url)
            except ValueError:
                return None
            provider_id = "workday"
            token = parsed_workday.site
            tenant = parsed_workday.tenant
            site = parsed_workday.site
            host = parsed_workday.host

        if not provider_id:
            return None

        definition = self.get(provider_id)
        support = (
            definition.support_level if definition else ProviderSupport.UNSUPPORTED
        )
        return BoardProviderRecord(
            id=stable_id(source_key, board_key, provider_id),
            source_key=source_key,
            board_key=board_key,
            provider_id=provider_id,
            label=definition.label if definition else provider_id,
            support_level=support,
            board_url=url,
            token=token,
            host=host,
            tenant=tenant,
            site=site,
            detected_at=utc_now(),
        )


def default_registry(plugin_registry: PluginRegistry | None = None) -> ProviderRegistry:
    definitions = [
        ProviderDefinition(
            "consider_a16z",
            "Consider/a16z",
            ProviderKind.BOARD_SOURCE,
            ProviderSupport.DETECT,
            "Aggregate a16z source adapter that discovers boards and provider hints.",
        ),
        ProviderDefinition(
            "getro",
            "Getro",
            ProviderKind.BOARD_SOURCE,
            ProviderSupport.DETECT,
            "Aggregate Getro source adapter that discovers company boards.",
        ),
        ProviderDefinition(
            "ycombinator",
            "Y Combinator",
            ProviderKind.BOARD_SOURCE,
            ProviderSupport.DETECT,
            "Aggregate YC source adapter that discovers company boards from Algolia.",
        ),
        ProviderDefinition(
            "greenhouse",
            "Greenhouse",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.JOBS,
            "Public Greenhouse job board API.",
        ),
        ProviderDefinition(
            "lever",
            "Lever",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.JOBS,
            "Public Lever postings JSON API.",
        ),
        ProviderDefinition(
            "workday",
            "Workday",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.JOBS,
            "Public Workday CXS careers-site endpoints.",
        ),
        ProviderDefinition(
            "ashbyhq",
            "Ashby",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.JOBS,
            "Public Ashby job posting API.",
        ),
        ProviderDefinition(
            "teamtailor",
            "Teamtailor",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.DETECT,
            "Detect-only provider metadata.",
        ),
        ProviderDefinition(
            "manatal",
            "Manatal",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.DETECT,
            "Detect-only provider metadata.",
        ),
        ProviderDefinition(
            "gem",
            "Gem",
            ProviderKind.BOARD_PROVIDER,
            ProviderSupport.DETECT,
            "Detect-only provider metadata.",
        ),
        ProviderDefinition(
            "consider",
            "Consider",
            ProviderKind.BOARD_SOURCE,
            ProviderSupport.DETECT,
            "Detect-only Consider board metadata.",
        ),
    ]
    registry = plugin_registry or load_plugins()
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
                definitions.append(
                    ProviderDefinition(
                        capability.name,
                        capability.name,
                        ProviderKind.BOARD_PROVIDER,
                        ProviderSupport.JOBS,
                        capability.description or "Plugin job provider.",
                    )
                )
                known_ids.add(capability.name)
    return ProviderRegistry(definitions)
