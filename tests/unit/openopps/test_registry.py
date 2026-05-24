from openopps.models import ProviderSupport
from openopps.plugins import (
    PluginContext,
    PluginCapability,
    PluginContribution,
    PluginMetadata,
    PluginRegistry,
)
from openopps.providers.boards import BOARD_JOB_PROVIDERS
from openopps.providers.base import ProviderKind
from openopps.providers.sources import BOARD_SOURCE_ADAPTERS
from openopps.providers.registry import provider_registry
from openopps.settings import OpenOppsSettings


def test_registry_separates_board_sources_from_board_providers():
    registry = provider_registry()

    assert {definition.id for definition in registry.list_sources()} >= {
        "consider",
        "getro",
        "ycombinator",
    }
    assert {definition.id for definition in registry.list_board_providers()} >= {
        "ashbyhq",
        "bamboohr",
        "greenhouse",
        "lever",
        "rippling",
        "teamtailor",
        "workable",
        "workday",
        "wpjobmanager",
    }
    ycombinator = registry.get("ycombinator")
    greenhouse = registry.get("greenhouse")

    assert ycombinator is not None
    assert greenhouse is not None
    assert ycombinator.kind == ProviderKind.BOARD_SOURCE
    assert greenhouse.kind == ProviderKind.BOARD_PROVIDER


def test_registry_indexes_packaged_adapters_programmatically():
    registry = provider_registry(plugin_registry=PluginRegistry((), (), ()))

    assert {definition.id for definition in registry.list_sources()} == set(
        BOARD_SOURCE_ADAPTERS
    )
    assert {definition.id for definition in registry.list_board_providers()} == set(
        BOARD_JOB_PROVIDERS
    )


def test_registry_detects_ashby_hosted_board_url():
    detected = provider_registry().detect_url("https://jobs.ashbyhq.com/acme")

    assert detected is not None
    assert detected.provider_id == "ashbyhq"
    assert detected.token == "acme"
    assert detected.board_url == "https://jobs.ashbyhq.com/acme"


def test_registry_detects_provider_urls_from_indexed_provider_metadata():
    registry = provider_registry(plugin_registry=PluginRegistry((), (), ()))

    greenhouse = registry.detect_url("https://boards.greenhouse.io/acme")
    lever = registry.detect_url("https://jobs.lever.co/acme")
    workday = registry.detect_url("https://acme.wd1.myworkdayjobs.com/en-US/External")
    workable = registry.detect_url("https://apply.workable.com/acme")
    teamtailor = registry.detect_url("https://acme.teamtailor.com/jobs")
    bamboohr = registry.detect_url("https://acme.bamboohr.com/careers")
    rippling = registry.detect_url("https://ats.rippling.com/acme/jobs")
    wpjobmanager = registry.detect_url(
        "https://acme.example.com/wp-json/wp/v2/job-listings"
    )
    wpjobmanager_ajax = registry.detect_url(
        "https://acme.example.com/jm-ajax/get_listings/"
    )

    assert greenhouse is not None
    assert lever is not None
    assert workday is not None
    assert workable is not None
    assert teamtailor is not None
    assert bamboohr is not None
    assert rippling is not None
    assert wpjobmanager is not None
    assert wpjobmanager_ajax is not None
    assert greenhouse.provider_id == "greenhouse"
    assert lever.provider_id == "lever"
    assert workday.provider_id == "workday"
    assert workable.provider_id == "workable"
    assert teamtailor.provider_id == "teamtailor"
    assert bamboohr.provider_id == "bamboohr"
    assert rippling.provider_id == "rippling"
    assert wpjobmanager.provider_id == "wpjobmanager"
    assert wpjobmanager_ajax.provider_id == "wpjobmanager"
    assert bamboohr.tenant == "acme"
    assert rippling.tenant == "acme"
    assert wpjobmanager.token == "https://acme.example.com"
    assert wpjobmanager_ajax.token == "https://acme.example.com"


def test_registry_does_not_treat_arbitrary_ashby_subdomain_as_board_url():
    detected = provider_registry().detect_url("https://example.ashbyhq.com/acme")

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

    registry = provider_registry(plugin_registry=plugin_registry)

    custom_source = registry.get("custom_source")
    custom_jobs = registry.get("custom_jobs")
    assert custom_source is not None
    assert custom_jobs is not None
    assert custom_source.kind == ProviderKind.BOARD_SOURCE
    assert custom_source.support_level == ProviderSupport.DETECT
    assert custom_jobs.kind == ProviderKind.BOARD_PROVIDER
    assert custom_jobs.support_level == ProviderSupport.JOBS


def test_registry_loads_plugins_with_settings_context(monkeypatch):
    captured_contexts: list[PluginContext | None] = []

    def fake_load_plugins(*, context: PluginContext | None = None):
        captured_contexts.append(context)
        return PluginRegistry(contributions=(), load_results=(), conflicts=())

    settings = OpenOppsSettings(plugin_disabled="blocked")
    monkeypatch.setattr("openopps.providers.registry.load_plugins", fake_load_plugins)

    provider_registry(settings=settings)

    assert captured_contexts == [PluginContext(settings=settings)]
