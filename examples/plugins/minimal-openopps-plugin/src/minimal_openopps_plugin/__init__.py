from __future__ import annotations

import httpx

from openopps.models import BoardProviderRecord, BoardRecord
from openopps.plugins import (
    PluginCapability,
    PluginContribution,
    PluginContext,
    PluginMetadata,
)
from openopps.providers import JobFetchResult


class MinimalJobProvider:
    """Safe no-op example that never claims a complete board snapshot."""

    provider_id = "minimal_jobs"

    async def fetch_jobs(
        self,
        _client: httpx.AsyncClient,
        _board: BoardRecord,
        _route: BoardProviderRecord,
    ) -> JobFetchResult:
        return JobFetchResult(jobs=[], authoritative=False)

    async def check_jobs(
        self,
        _client: httpx.AsyncClient,
        _board: BoardRecord,
        _route: BoardProviderRecord,
    ) -> int:
        return 200


def plugin(_context: PluginContext) -> PluginContribution:
    return PluginContribution(
        metadata=PluginMetadata(
            name="minimal-openopps-plugin",
            version="0.1.0",
            description="Minimal OpenOpps v0.1 plugin template.",
        ),
        capabilities=(
            PluginCapability(
                kind="job_provider",
                name=MinimalJobProvider.provider_id,
                description="Non-authoritative no-op job provider contract example.",
            ),
            PluginCapability(
                kind="metadata_enricher",
                name="minimal_metadata",
                description="Example metadata enricher registration.",
            ),
            PluginCapability(
                kind="cache_policy",
                name="minimal_cache",
                description="Example cache policy registration.",
            ),
            PluginCapability(
                kind="cli_command",
                name="minimal_cli",
                description="Example CLI command registration.",
            ),
        ),
        job_providers={
            MinimalJobProvider.provider_id: lambda _settings: MinimalJobProvider()
        },
        metadata_enrichers={"minimal_metadata": enrich_metadata},
        cache_policies={"minimal_cache": cache_policy},
        cli_commands={"minimal_cli": cli_command},
    )


def enrich_metadata(record: object) -> object:
    return record


def cache_policy(_namespace: str) -> dict[str, int]:
    return {"ttlSeconds": 3600}


def cli_command() -> None:
    return None
