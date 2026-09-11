from __future__ import annotations

import builtins
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import islice

from openopps.models import (
    BoardProviderRecord,
    ProviderSupport,
    utc_now,
    validate_public_https_url,
)
from openopps.plugins import (
    PluginContext,
    PluginRegistry,
    PluginUrlPullRegistration,
    load_plugins,
)
from openopps.providers.base import ProviderDefinition, ProviderKind
from openopps.providers.boards import (
    ProviderProbeUrlBuilder,
    board_probe_url_builders,
    board_provider_definitions,
)
from openopps.providers.pull import ProviderPullCapabilities, ProviderUrlTarget
from openopps.providers.sources import source_provider_definitions
from openopps.settings import OpenOppsSettings
from openopps.utils import stable_id


DEFAULT_MAX_PROBE_CANDIDATES_PER_PROVIDER = 4
DEFAULT_MAX_PROBE_CANDIDATES_TOTAL = 12


@dataclass(frozen=True)
class ProviderProbeCandidate:
    """One trusted provider-declared URL probe candidate."""

    provider_id: str
    url: str


class ProviderRegistry:
    def __init__(
        self,
        definitions: builtins.list[ProviderDefinition],
        *,
        builtin_ids: Iterable[str] = (),
        probe_url_builders: Mapping[str, ProviderProbeUrlBuilder] | None = None,
        max_probe_candidates_per_provider: int = (
            DEFAULT_MAX_PROBE_CANDIDATES_PER_PROVIDER
        ),
        max_probe_candidates_total: int = DEFAULT_MAX_PROBE_CANDIDATES_TOTAL,
    ):
        for label, limit in (
            ("per provider", max_probe_candidates_per_provider),
            ("total", max_probe_candidates_total),
        ):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ValueError(f"max probe candidates {label} must be positive")
        self._definitions: dict[str, ProviderDefinition] = {}
        for definition in definitions:
            self._validate_definition(definition)
            self._definitions.setdefault(definition.id, definition)
        self._builtin_ids = frozenset(builtin_ids) & self._definitions.keys()
        self._probe_url_builders = {
            provider_id: builder
            for provider_id, builder in (probe_url_builders or {}).items()
            if provider_id in self._definitions and callable(builder)
        }
        self._max_probe_candidates_per_provider = max_probe_candidates_per_provider
        self._max_probe_candidates_total = max_probe_candidates_total

    @staticmethod
    def _validate_definition(definition: ProviderDefinition) -> None:
        has_parser = definition.target_parser is not None
        has_capabilities = definition.pull_capabilities is not None
        if has_parser != has_capabilities:
            raise ValueError(
                f"provider {definition.id!r} must register target parser and "
                "pull capabilities together"
            )
        if has_parser and not callable(definition.target_parser):
            raise TypeError(
                f"provider {definition.id!r} target parser must be callable"
            )

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

    def pull_capabilities(self, provider_id: str) -> ProviderPullCapabilities | None:
        definition = self.get(provider_id)
        return definition.pull_capabilities if definition is not None else None

    def is_builtin(self, provider_id: str) -> bool:
        return provider_id in self._builtin_ids

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
        """Return the first legacy route match in deterministic provider order."""

        return next(
            self._iter_url_matches(
                url,
                board_key=board_key,
                source_key=source_key,
            ),
            None,
        )

    def detect_url_matches(
        self,
        url: str,
        *,
        board_key: str = "manual",
        source_key: str = "manual",
    ) -> tuple[BoardProviderRecord, ...]:
        """Return every legacy route match in deterministic provider order."""

        return tuple(
            self._iter_url_matches(
                url,
                board_key=board_key,
                source_key=source_key,
            )
        )

    def _iter_url_matches(
        self,
        url: str,
        *,
        board_key: str,
        source_key: str,
    ) -> Iterator[BoardProviderRecord]:
        try:
            validate_public_https_url(url)
        except ValueError:
            return
        for candidate in self.list_board_providers():
            if candidate.route_detector is None:
                continue
            try:
                match = candidate.route_detector(url)
            except ValueError:
                continue
            if match is None:
                continue
            yield BoardProviderRecord(
                id=stable_id(source_key, board_key, candidate.id),
                source_key=source_key,
                board_key=board_key,
                provider_id=candidate.id,
                label=candidate.label,
                support_level=candidate.support_level,
                board_url=url,
                token=match.token,
                host=match.host,
                tenant=match.tenant,
                site=match.site,
                detected_at=utc_now(),
            )

    def detect_targets(self, url: str) -> tuple[ProviderUrlTarget, ...]:
        """Return every typed native match without silently choosing a provider."""

        try:
            validate_public_https_url(url)
        except ValueError:
            return ()

        detected: dict[
            tuple[str, str, str, str, str, str, str, str, str],
            ProviderUrlTarget,
        ] = {}
        for definition in self.list_board_providers():
            parser = definition.target_parser
            if parser is None or definition.pull_capabilities is None:
                continue
            try:
                target = parser(url)
            except Exception:  # noqa: BLE001 - plugin parsers fail closed in isolation.
                continue
            if not isinstance(target, ProviderUrlTarget):
                continue
            if target.provider_id != definition.id:
                continue
            key = self._target_key(target)
            detected.setdefault(key, target)
        return tuple(
            sorted(
                detected.values(),
                key=lambda target: (
                    0 if target.provider_id in self._builtin_ids else 1,
                    *self._target_key(target),
                ),
            )
        )

    @staticmethod
    def _target_key(
        target: ProviderUrlTarget,
    ) -> tuple[str, str, str, str, str, str, str, str, str]:
        return (
            target.provider_id,
            target.target_kind.value,
            str(target.url),
            target.board_identity,
            target.posting_identity or "",
            target.route.token or "",
            target.route.host or "",
            target.route.tenant or "",
            target.route.site or "",
        )

    def probe_candidates(self, slug: str) -> tuple[ProviderProbeCandidate, ...]:
        """Build public candidates only from explicit capability-owned builders."""

        normalized_slug = slug.strip()
        if not normalized_slug:
            return ()
        candidates: dict[tuple[str, str], ProviderProbeCandidate] = {}
        raw_candidates_seen = 0
        builder_items = sorted(
            self._probe_url_builders.items(),
            key=lambda item: (0 if item[0] in self._builtin_ids else 1, item[0]),
        )
        for provider_id, builder in builder_items:
            remaining_candidates = (
                self._max_probe_candidates_total - raw_candidates_seen
            )
            if remaining_candidates <= 0:
                break
            provider_candidates: dict[tuple[str, str], ProviderProbeCandidate] = {}
            definition = self.get(provider_id)
            if (
                definition is None
                or definition.target_parser is None
                or definition.pull_capabilities is None
            ):
                continue
            try:
                urls = builder(normalized_slug)
                bounded_urls = (urls,) if isinstance(urls, str) else urls
                for candidate_url in islice(
                    iter(bounded_urls),
                    min(
                        self._max_probe_candidates_per_provider,
                        remaining_candidates,
                    ),
                ):
                    raw_candidates_seen += 1
                    if not isinstance(candidate_url, str):
                        continue
                    try:
                        validate_public_https_url(candidate_url)
                        target = definition.target_parser(candidate_url)
                    except Exception:  # noqa: BLE001 - untrusted plugin candidate.
                        continue
                    if (
                        not isinstance(target, ProviderUrlTarget)
                        or target.provider_id != provider_id
                    ):
                        continue
                    sanitized_candidate_url = str(target.url)
                    key = (provider_id, sanitized_candidate_url)
                    provider_candidates.setdefault(
                        key,
                        ProviderProbeCandidate(
                            provider_id=provider_id,
                            url=sanitized_candidate_url,
                        ),
                    )
            except Exception:  # noqa: BLE001 - plugin builders fail closed in isolation.
                continue
            candidates.update(provider_candidates)
        return tuple(candidates.values())


def provider_registry(
    plugin_registry: PluginRegistry | None = None,
    settings: OpenOppsSettings | None = None,
) -> ProviderRegistry:
    builtin_board_definitions = list(board_provider_definitions())
    builtin_definitions = [
        *source_provider_definitions(),
        *builtin_board_definitions,
    ]
    definitions = list(builtin_definitions)
    builtin_ids = {definition.id for definition in builtin_definitions}
    probe_builders = board_probe_url_builders()
    registry = plugin_registry or load_plugins(context=PluginContext(settings=settings))
    resolution_settings = (
        registry.url_pull_resolution_settings
        if settings is None and registry.url_pull_resolution_builtin_ids is not None
        else settings
    )
    registry = registry.resolve_url_pulls(
        builtin_provider_ids=builtin_ids,
        settings=resolution_settings,
    )
    known_ids = {definition.id for definition in definitions}
    plugin_capability_claims = [
        (contribution, capability)
        for contribution in registry.contributions
        for capability in contribution.all_capabilities()
    ]
    plugin_capability_claims.sort(
        key=lambda claim: (
            0
            if claim[0].url_pull_providers.get(claim[1].name)
            is registry.url_pull_registration(claim[1].name)
            else 1,
            claim[1].kind,
            claim[1].name,
            claim[0].metadata.name,
            claim[0].metadata.version,
            claim[0].metadata.package or "",
        )
    )
    for contribution, capability in plugin_capability_claims:
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
            registration = contribution.url_pull_providers.get(capability.name)
            active_registration = registry.url_pull_registration(capability.name)
            if (
                not isinstance(registration, PluginUrlPullRegistration)
                or registration is not active_registration
            ):
                registration = None
            definitions.append(
                ProviderDefinition(
                    capability.name,
                    capability.name,
                    ProviderKind.BOARD_PROVIDER,
                    ProviderSupport.JOBS,
                    capability.description or "Plugin job provider.",
                    route_detector=route_detector,
                    target_parser=(
                        registration.target_parser if registration else None
                    ),
                    pull_capabilities=(
                        registration.capabilities if registration else None
                    ),
                )
            )
            known_ids.add(capability.name)
            if registration and registration.probe_url_builder:
                probe_builders[capability.name] = registration.probe_url_builder
    return ProviderRegistry(
        definitions,
        builtin_ids=builtin_ids,
        probe_url_builders=probe_builders,
        max_probe_candidates_per_provider=(
            int(settings.pull_resolver_max_probes_per_provider)
            if settings is not None
            else DEFAULT_MAX_PROBE_CANDIDATES_PER_PROVIDER
        ),
        max_probe_candidates_total=(
            int(settings.pull_resolver_max_probes)
            if settings is not None
            else DEFAULT_MAX_PROBE_CANDIDATES_TOTAL
        ),
    )
