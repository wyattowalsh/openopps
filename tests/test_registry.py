from openopps.models import ProviderSupport
from openopps.plugins import (
    PluginCapability,
    PluginContribution,
    PluginMetadata,
    PluginRegistry,
)
from openopps.providers.base import ProviderKind
from openopps.providers.registry import default_registry


def test_registry_separates_board_sources_from_board_providers():
    registry = default_registry()

    assert {definition.id for definition in registry.list_sources()} >= {
        "consider",
        "getro",
        "ycombinator",
    }
    assert {definition.id for definition in registry.list_board_providers()} >= {
        "ashbyhq",
        "greenhouse",
        "lever",
        "workday",
    }
    ycombinator = registry.get("ycombinator")
    greenhouse = registry.get("greenhouse")

    assert ycombinator is not None
    assert greenhouse is not None
    assert ycombinator.kind == ProviderKind.BOARD_SOURCE
    assert greenhouse.kind == ProviderKind.BOARD_PROVIDER


def test_registry_detects_ashby_hosted_board_url():
    detected = default_registry().detect_url("https://jobs.ashbyhq.com/acme")

    assert detected is not None
    assert detected.provider_id == "ashbyhq"
    assert detected.token == "acme"
    assert detected.board_url == "https://jobs.ashbyhq.com/acme"


def test_registry_does_not_treat_arbitrary_ashby_subdomain_as_board_url():
    detected = default_registry().detect_url("https://example.ashbyhq.com/acme")

    assert detected is None


def test_registry_includes_plugin_provider_capabilities():
    plugin_registry = PluginRegistry(
        contributions=(
            PluginContribution(
                metadata=PluginMetadata(name="Example", version="1.0.0"),
                capabilities=(
                    PluginCapability(
                        kind="source_adapter",
                        name="custom_source",
                        description="Custom source adapter.",
                    ),
                    PluginCapability(
                        kind="job_provider",
                        name="custom_jobs",
                        description="Custom jobs provider.",
                    ),
                ),
            ),
        ),
        load_results=(),
        conflicts=(),
    )

    registry = default_registry(plugin_registry=plugin_registry)

    custom_source = registry.get("custom_source")
    custom_jobs = registry.get("custom_jobs")
    assert custom_source is not None
    assert custom_jobs is not None
    assert custom_source.kind == ProviderKind.BOARD_SOURCE
    assert custom_source.support_level == ProviderSupport.DETECT
    assert custom_jobs.kind == ProviderKind.BOARD_PROVIDER
    assert custom_jobs.support_level == ProviderSupport.JOBS
