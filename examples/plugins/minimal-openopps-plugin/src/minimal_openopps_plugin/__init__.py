from __future__ import annotations

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
