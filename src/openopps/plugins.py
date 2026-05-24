from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from io import StringIO
from importlib import metadata as importlib_metadata
from typing import Any


ENTRY_POINT_GROUP = "openopps.plugins"
PLUGIN_API_VERSION = "0.1"
_CAPABILITY_MAPPING_KINDS = {
    "source_adapter": "source_adapters",
    "job_provider": "job_providers",
    "route_detector": "route_detectors",
    "metadata_enricher": "metadata_enrichers",
    "cache_policy": "cache_policies",
    "export_contributor": "export_contributors",
    "cli_command": "cli_commands",
}


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str
    api_version: str = PLUGIN_API_VERSION
    description: str = ""
    package: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "version": self.version,
            "apiVersion": self.api_version,
            "description": self.description,
            "package": self.package,
        }


@dataclass(frozen=True)
class PluginCapability:
    kind: str
    name: str
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "key": self.key,
            "description": self.description,
        }


@dataclass(frozen=True)
class PluginContribution:
    metadata: PluginMetadata
    capabilities: tuple[PluginCapability, ...] = ()
    source_adapters: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    job_providers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    route_detectors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    metadata_enrichers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    cache_policies: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    export_contributors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    cli_commands: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    def all_capabilities(self) -> tuple[PluginCapability, ...]:
        inferred: list[PluginCapability] = []
        for kind, attr in _CAPABILITY_MAPPING_KINDS.items():
            mapping = getattr(self, attr)
            inferred.extend(PluginCapability(kind=kind, name=name) for name in mapping)
        explicit_keys = {capability.key for capability in self.capabilities}
        return self.capabilities + tuple(
            capability for capability in inferred if capability.key not in explicit_keys
        )


@dataclass(frozen=True)
class PluginConflict:
    capability: str
    existing_plugin: str
    plugin: str

    def as_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "existingPlugin": self.existing_plugin,
            "plugin": self.plugin,
        }


@dataclass(frozen=True)
class PluginLoadResult:
    entry_point: str
    metadata: PluginMetadata | None
    loaded: bool
    capabilities: tuple[PluginCapability, ...] = ()
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "entryPoint": self.entry_point,
            "metadata": self.metadata.as_dict() if self.metadata else None,
            "loaded": self.loaded,
            "capabilities": [capability.as_dict() for capability in self.capabilities],
            "error": self.error,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PluginRegistry:
    contributions: tuple[PluginContribution, ...]
    load_results: tuple[PluginLoadResult, ...]
    conflicts: tuple[PluginConflict, ...]
    disabled: tuple[str, ...] = ()
    allowed: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugins": [result.as_dict() for result in self.load_results],
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "loaded": sum(1 for result in self.load_results if result.loaded),
            "failed": sum(1 for result in self.load_results if not result.loaded),
            "filters": {
                "disabled": list(self.disabled),
                "allowed": list(self.allowed) if self.allowed is not None else None,
            },
        }

    def capabilities(self, kind: str | None = None) -> dict[str, PluginCapability]:
        selected: dict[str, PluginCapability] = {}
        for contribution in self.contributions:
            for capability in contribution.all_capabilities():
                if kind is None or capability.kind == kind:
                    selected[capability.key] = capability
        return selected


@dataclass(frozen=True)
class PluginContext:
    settings: Any = None
    http: Any = None
    cache: Any = None
    metrics: Any = None


def load_plugins(
    *,
    entry_points: Iterable[Any] | None = None,
    disabled: Iterable[str] = (),
    allowed: Iterable[str] | None = None,
    context: PluginContext | None = None,
) -> PluginRegistry:
    context = context or PluginContext()
    settings = context.settings
    configured_disabled = _setting_names(settings, "plugin_disabled_names")
    configured_allowed = _setting_names(settings, "plugin_allowed_names")
    disabled_names = set(disabled) | set(configured_disabled)
    allowed_names = set(allowed) if allowed is not None else None
    if allowed_names is None and configured_allowed:
        allowed_names = set(configured_allowed)
    if allowed_names is None and not getattr(settings, "plugin_autoload", False):
        allowed_names = set()
    contributions: list[PluginContribution] = []
    results: list[PluginLoadResult] = []
    conflicts: list[PluginConflict] = []
    claimed: dict[str, str] = {}

    selected_entry_points = _entry_points() if entry_points is None else entry_points
    for entry_point in selected_entry_points:
        entry_name = getattr(entry_point, "name", str(entry_point))
        if entry_name in disabled_names:
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error="disabled",
                )
            )
            continue
        if allowed_names is not None and entry_name not in allowed_names:
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error="not_allowed",
                )
            )
            continue
        try:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                factory = entry_point.load()
                contribution = factory(context)
            contribution = _validate_contribution(contribution, entry_point)
            capability_conflicts = _collect_conflicts(
                contribution, claimed=claimed, plugin_name=contribution.metadata.name
            )
            conflicts.extend(capability_conflicts)
            output_warnings = _captured_output_warnings(stdout, stderr)
            contributions.append(contribution)
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=contribution.metadata,
                    loaded=True,
                    capabilities=contribution.all_capabilities(),
                    warnings=output_warnings
                    + tuple(
                        f"conflict:{conflict.capability}"
                        for conflict in capability_conflicts
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - plugin failures must be isolated.
            results.append(
                PluginLoadResult(
                    entry_point=entry_name,
                    metadata=None,
                    loaded=False,
                    error=str(exc),
                )
            )
    return PluginRegistry(
        contributions=tuple(contributions),
        load_results=tuple(results),
        conflicts=tuple(conflicts),
        disabled=tuple(sorted(disabled_names)),
        allowed=tuple(sorted(allowed_names)) if allowed_names is not None else None,
    )


def _entry_points() -> tuple[Any, ...]:
    entry_points = importlib_metadata.entry_points()
    return tuple(entry_points.select(group=ENTRY_POINT_GROUP))


def _validate_contribution(
    contribution: object,
    entry_point: object,
) -> PluginContribution:
    if not isinstance(contribution, PluginContribution):
        raise TypeError("plugin factory must return PluginContribution")
    package = _entry_point_package(entry_point)
    metadata = contribution.metadata
    if not metadata.name:
        raise ValueError("plugin metadata name is required")
    if not metadata.version:
        raise ValueError("plugin metadata version is required")
    if metadata.api_version != PLUGIN_API_VERSION:
        raise ValueError(
            f"unsupported plugin api version {metadata.api_version!r}; "
            f"expected {PLUGIN_API_VERSION!r}"
        )
    seen_capability_keys: set[str] = set()
    for capability in contribution.capabilities:
        if capability.kind not in _CAPABILITY_MAPPING_KINDS:
            raise ValueError(f"unsupported plugin capability kind {capability.kind!r}")
        if not capability.name:
            raise ValueError("plugin capability name is required")
        if capability.key in seen_capability_keys:
            raise ValueError(f"duplicate plugin capability {capability.key!r}")
        seen_capability_keys.add(capability.key)
    for attr in _CAPABILITY_MAPPING_KINDS.values():
        mapping = getattr(contribution, attr)
        if not isinstance(mapping, Mapping):
            raise TypeError(f"{attr} must be a mapping")
        for name, value in mapping.items():
            if not name:
                raise ValueError(f"{attr} contains an empty name")
            if not callable(value):
                raise TypeError(f"{attr}.{name} must be callable")
    if package and metadata.package is None:
        return replace(contribution, metadata=replace(metadata, package=package))
    return contribution


def _captured_output_warnings(stdout: StringIO, stderr: StringIO) -> tuple[str, ...]:
    warnings: list[str] = []
    if stdout.getvalue():
        warnings.append("captured_stdout")
    if stderr.getvalue():
        warnings.append("captured_stderr")
    return tuple(warnings)


def _setting_names(settings: object, attr: str) -> tuple[str, ...]:
    values = getattr(settings, attr, ()) if settings is not None else ()
    return tuple(str(value) for value in values)


def _entry_point_package(entry_point: object) -> str | None:
    dist = getattr(entry_point, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    if isinstance(name, str):
        return name
    metadata = getattr(dist, "metadata", None)
    if metadata is not None:
        return metadata.get("Name")
    return None


def _collect_conflicts(
    contribution: PluginContribution,
    *,
    claimed: dict[str, str],
    plugin_name: str,
) -> list[PluginConflict]:
    conflicts: list[PluginConflict] = []
    for capability in contribution.all_capabilities():
        existing_plugin = claimed.get(capability.key)
        if existing_plugin is None:
            claimed[capability.key] = plugin_name
            continue
        conflicts.append(
            PluginConflict(
                capability=capability.key,
                existing_plugin=existing_plugin,
                plugin=plugin_name,
            )
        )
    return conflicts
