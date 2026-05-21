from __future__ import annotations

from typing import Any

from openopps.plugins import (
    PluginCapability,
    PluginContribution,
    PluginContext,
    PluginMetadata,
)


def plugin(_context: PluginContext) -> PluginContribution:
    return PluginContribution(
        metadata=PluginMetadata(
            name="minimal-openopps-plugin",
            version="0.1.0",
            description="Minimal OpenOpps v0.1 plugin template.",
        ),
        capabilities=(
            PluginCapability(
                kind="source_adapter",
                name="minimal_source",
                description="Example source adapter registration.",
            ),
            PluginCapability(
                kind="job_provider",
                name="minimal_jobs",
                description="Example job provider registration.",
            ),
            PluginCapability(
                kind="route_detector",
                name="minimal_route",
                description="Example route detector registration.",
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
        source_adapters={"minimal_source": MinimalSourceAdapter},
        job_providers={"minimal_jobs": MinimalJobProvider},
        route_detectors={"minimal_route": detect_route},
        metadata_enrichers={"minimal_metadata": enrich_metadata},
        cache_policies={"minimal_cache": cache_policy},
        cli_commands={"minimal_cli": cli_command},
    )


class MinimalSourceAdapter:
    provider_id = "minimal_source"

    def __init__(self, _settings: Any):
        self.settings = _settings


class MinimalJobProvider:
    provider_id = "minimal_jobs"

    def __init__(self, _settings: Any):
        self.settings = _settings


def detect_route(_url: str) -> None:
    return None


def enrich_metadata(record: Any) -> Any:
    return record


def cache_policy(_namespace: str) -> dict[str, int]:
    return {"ttlSeconds": 3600}


def cli_command() -> None:
    return None
