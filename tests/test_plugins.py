from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openopps.plugins import (
    ENTRY_POINT_GROUP,
    PluginCapability,
    PluginContribution,
    PluginContext,
    PluginMetadata,
    PluginRegistry,
    load_plugins,
)
from openopps.providers.boards import build_job_provider
from openopps.providers.sources import build_source_adapter
from openopps.settings import OpenOppsSettings


@dataclass(frozen=True)
class FakeDistribution:
    name: str


@dataclass(frozen=True)
class FakeEntryPoint:
    name: str
    factory: Any
    dist: FakeDistribution | None = None
    group: str = ENTRY_POINT_GROUP

    def load(self):
        return self.factory


def _plugin(
    context: PluginContext,
    *,
    name: str = "example",
    provider: str = "exampleats",
) -> PluginContribution:
    assert isinstance(context, PluginContext)
    return PluginContribution(
        metadata=PluginMetadata(name=name, version="1.0.0"),
        job_providers={provider: lambda settings: object()},
        route_detectors={provider: lambda url: None},
    )


def test_load_plugins_discovers_valid_contribution():
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                name="example",
                factory=lambda context: _plugin(context),
                dist=FakeDistribution("openopps-example"),
            )
        ]
    )

    data = registry.as_dict()

    assert data["loaded"] == 1
    assert data["failed"] == 0
    assert data["plugins"][0]["metadata"] == {
        "name": "example",
        "version": "1.0.0",
        "apiVersion": "0.1",
        "description": "",
        "package": "openopps-example",
    }
    assert sorted(registry.capabilities()) == [
        "job_provider:exampleats",
        "route_detector:exampleats",
    ]


def test_load_plugins_isolates_import_failure():
    def broken(_context: PluginContext) -> PluginContribution:
        raise RuntimeError("boom")

    registry = load_plugins(entry_points=[FakeEntryPoint("broken", broken)])

    data = registry.as_dict()

    assert data["loaded"] == 0
    assert data["failed"] == 1
    assert data["plugins"][0]["error"] == "boom"


def test_load_plugins_reports_validation_errors():
    registry = load_plugins(
        entry_points=[FakeEntryPoint("invalid", lambda _context: {"not": "valid"})]
    )

    data = registry.as_dict()

    assert data["failed"] == 1
    assert "PluginContribution" in data["plugins"][0]["error"]


def test_load_plugins_supports_disabled_and_allow_list():
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint("blocked", lambda context: _plugin(context, name="blocked")),
            FakeEntryPoint("allowed", lambda context: _plugin(context, name="allowed")),
        ],
        disabled={"blocked"},
        allowed={"allowed"},
    )

    data = registry.as_dict()

    assert data["loaded"] == 1
    assert data["failed"] == 1
    assert [item["entryPoint"] for item in data["plugins"]] == ["blocked", "allowed"]
    assert data["plugins"][0]["error"] == "disabled"


def test_load_plugins_reports_duplicate_capability_conflicts():
    registry = load_plugins(
        entry_points=[
            FakeEntryPoint(
                "one",
                lambda context: PluginContribution(
                    metadata=PluginMetadata(name="one", version="1.0.0"),
                    capabilities=(PluginCapability("source_adapter", "same"),),
                ),
            ),
            FakeEntryPoint(
                "two",
                lambda context: PluginContribution(
                    metadata=PluginMetadata(name="two", version="1.0.0"),
                    capabilities=(PluginCapability("source_adapter", "same"),),
                ),
            ),
        ]
    )

    data = registry.as_dict()

    assert data["loaded"] == 2
    assert data["conflicts"] == [
        {
            "capability": "source_adapter:same",
            "existingPlugin": "one",
            "plugin": "two",
        }
    ]
    assert data["plugins"][1]["warnings"] == ["conflict:source_adapter:same"]


def test_plugin_source_and_job_provider_factories_are_buildable(tmp_path):
    class FakeSourceAdapter:
        provider_id = "custom_source"

    class FakeJobProvider:
        provider_id = "custom_jobs"

    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    plugin_registry = PluginRegistry(
        contributions=(
            PluginContribution(
                metadata=PluginMetadata(name="example", version="1.0.0"),
                source_adapters={
                    "custom_source": lambda _settings: FakeSourceAdapter()
                },
                job_providers={"custom_jobs": lambda _settings: FakeJobProvider()},
            ),
        ),
        load_results=(),
        conflicts=(),
    )

    source_adapter = build_source_adapter(
        "custom_source", settings, plugin_registry=plugin_registry
    )
    job_provider = build_job_provider(
        "custom_jobs", settings, plugin_registry=plugin_registry
    )

    assert isinstance(source_adapter, FakeSourceAdapter)
    assert isinstance(job_provider, FakeJobProvider)
