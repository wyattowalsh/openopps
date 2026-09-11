from __future__ import annotations

from collections.abc import Callable

import pytest

from openopps.models import ProviderSupport
from openopps.providers.base import ProviderDefinition, ProviderKind, ProviderRouteMatch
from openopps.providers.boards import BOARD_URL_PULL_PROVIDERS
from openopps.providers.pull import (
    InterfaceStability,
    ProviderPullCapabilities,
    ProviderRouteIdentity,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.providers.registry import ProviderRegistry


def _capabilities(**updates: bool) -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        interface_stability=InterfaceStability.DOCUMENTED,
        **updates,
    )


def _definition(
    provider_id: str,
    parser: Callable[[str], ProviderUrlTarget | None],
) -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        label=provider_id,
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.JOBS,
        description=f"{provider_id} test provider.",
        target_parser=parser,
        pull_capabilities=_capabilities(list_supported=True),
    )


def test_typed_detection_retains_board_and_posting_identity() -> None:
    def parse(url: str) -> ProviderUrlTarget | None:
        if url != "https://jobs.example.test/acme/jobs/job-123":
            return None
        return ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.POSTING,
            url=url,
            board_identity="acme",
            posting_identity="job-123",
            route=ProviderRouteIdentity(token="acme"),
        )

    registry = ProviderRegistry([_definition("example", parse)])

    assert registry.detect_targets("https://jobs.example.test/acme/jobs/job-123") == (
        ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.POSTING,
            url="https://jobs.example.test/acme/jobs/job-123",
            board_identity="acme",
            posting_identity="job-123",
            route=ProviderRouteIdentity(token="acme"),
        ),
    )


@pytest.mark.parametrize(
    (
        "provider_id",
        "native_get",
        "board_scan_get",
        "enumerate_unlisted",
        "stability",
    ),
    [
        ("ashbyhq", False, True, True, InterfaceStability.DOCUMENTED),
        ("bamboohr", True, False, False, InterfaceStability.BEST_EFFORT),
        ("consider_jobs", False, True, False, InterfaceStability.BEST_EFFORT),
        ("greenhouse", True, False, False, InterfaceStability.DOCUMENTED),
        ("lever", True, False, False, InterfaceStability.DOCUMENTED),
        ("rippling", True, False, False, InterfaceStability.BEST_EFFORT),
        ("teamtailor", False, True, False, InterfaceStability.BEST_EFFORT),
        ("workable", False, True, False, InterfaceStability.BEST_EFFORT),
        ("workday", True, False, False, InterfaceStability.BEST_EFFORT),
        ("wpjobmanager", True, False, False, InterfaceStability.BEST_EFFORT),
    ],
)
def test_all_builtin_url_pull_capabilities_are_operation_honest(
    provider_id: str,
    native_get: bool,
    board_scan_get: bool,
    enumerate_unlisted: bool,
    stability: InterfaceStability,
) -> None:
    provider = BOARD_URL_PULL_PROVIDERS[provider_id]
    capabilities = provider.pull_capabilities

    assert callable(provider.parse_url_target)
    assert callable(provider.pull_list)
    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is native_get
    assert callable(getattr(provider, "pull_get", None)) is native_get
    assert capabilities.board_scan_get_supported is board_scan_get
    assert capabilities.enumerate_unlisted_supported is enumerate_unlisted
    assert capabilities.interface_stability == stability


def test_typed_detection_returns_every_competing_match_deterministically() -> None:
    def parser(provider_id: str) -> Callable[[str], ProviderUrlTarget]:
        def parse(url: str) -> ProviderUrlTarget:
            return ProviderUrlTarget(
                provider_id=provider_id,
                target_kind=ProviderTargetKind.BOARD,
                url=url,
                board_identity="acme",
            )

        return parse

    registry = ProviderRegistry(
        [
            _definition("zeta", parser("zeta")),
            _definition("alpha", parser("alpha")),
        ]
    )

    assert [
        target.provider_id
        for target in registry.detect_targets("https://careers.example.test/jobs")
    ] == ["alpha", "zeta"]


def test_legacy_route_detection_does_not_imply_typed_pull_support() -> None:
    definition = ProviderDefinition(
        id="legacy",
        label="Legacy",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.JOBS,
        description="Legacy provider.",
        route_detector=lambda _url: ProviderRouteMatch(token="acme"),
    )
    registry = ProviderRegistry([definition])

    assert registry.detect_url("https://legacy.example.test/acme") is not None
    assert registry.detect_targets("https://legacy.example.test/acme") == ()
    assert registry.pull_capabilities("legacy") is None


def test_probe_candidates_use_only_explicit_validated_builders() -> None:
    def parse(url: str) -> ProviderUrlTarget | None:
        if url != "https://jobs.example.test/acme":
            return None
        return ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.BOARD,
            url=url,
            board_identity="acme",
        )

    registry = ProviderRegistry(
        [_definition("example", parse)],
        probe_url_builders={
            "example": lambda slug: (
                f"https://jobs.example.test/{slug}",
                f"http://jobs.example.test/{slug}",
                "https://other.example.test/acme",
            )
        },
    )

    assert [
        (candidate.provider_id, candidate.url)
        for candidate in registry.probe_candidates("acme")
    ] == [("example", "https://jobs.example.test/acme")]


def test_duplicate_provider_definitions_keep_the_first_registration() -> None:
    def parser(label: str) -> Callable[[str], ProviderUrlTarget]:
        def parse(url: str) -> ProviderUrlTarget:
            return ProviderUrlTarget(
                provider_id="same",
                target_kind=ProviderTargetKind.BOARD,
                url=url,
                board_identity=label,
            )

        return parse

    registry = ProviderRegistry(
        [
            _definition("same", parser("built-in")),
            _definition("same", parser("plugin")),
        ],
        builtin_ids={"same"},
    )

    assert (
        registry.detect_targets("https://jobs.example.test/acme")[0].board_identity
        == "built-in"
    )


def test_probe_candidates_bound_infinite_builder_output_per_provider() -> None:
    yielded: list[int] = []

    def parse(url: str) -> ProviderUrlTarget:
        return ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.BOARD,
            url=url,
            board_identity=url.rsplit("/", 1)[-1],
        )

    def infinite_builder(_slug: str):
        index = 0
        while True:
            yielded.append(index)
            yield f"https://jobs.example.test/{index}"
            index += 1

    registry = ProviderRegistry(
        [_definition("example", parse)],
        probe_url_builders={"example": infinite_builder},
        max_probe_candidates_per_provider=3,
    )

    assert [candidate.url for candidate in registry.probe_candidates("acme")] == [
        "https://jobs.example.test/0",
        "https://jobs.example.test/1",
        "https://jobs.example.test/2",
    ]
    assert yielded == [0, 1, 2]


def test_probe_candidate_cap_counts_invalid_raw_yields() -> None:
    def parse(url: str) -> ProviderUrlTarget:
        return ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.BOARD,
            url=url,
            board_identity="acme",
        )

    registry = ProviderRegistry(
        [_definition("example", parse)],
        probe_url_builders={
            "example": lambda _slug: iter(
                (
                    "not-a-url",
                    "still-not-a-url",
                    "https://jobs.example.test/acme",
                )
            )
        },
        max_probe_candidates_per_provider=2,
    )

    assert registry.probe_candidates("acme") == ()


def test_probe_candidates_enforce_total_raw_yield_cap() -> None:
    def parser(provider_id: str) -> Callable[[str], ProviderUrlTarget]:
        def parse(url: str) -> ProviderUrlTarget:
            return ProviderUrlTarget(
                provider_id=provider_id,
                target_kind=ProviderTargetKind.BOARD,
                url=url,
                board_identity=url.rsplit("/", 1)[-1],
            )

        return parse

    registry = ProviderRegistry(
        [
            _definition("alpha", parser("alpha")),
            _definition("zeta", parser("zeta")),
        ],
        probe_url_builders={
            "alpha": lambda _slug: (
                "https://jobs.example.test/alpha-1",
                "https://jobs.example.test/alpha-2",
            ),
            "zeta": lambda _slug: (
                "https://jobs.example.test/zeta-1",
                "https://jobs.example.test/zeta-2",
            ),
        },
        max_probe_candidates_per_provider=2,
        max_probe_candidates_total=3,
    )

    assert [
        (candidate.provider_id, candidate.url)
        for candidate in registry.probe_candidates("acme")
    ] == [
        ("alpha", "https://jobs.example.test/alpha-1"),
        ("alpha", "https://jobs.example.test/alpha-2"),
        ("zeta", "https://jobs.example.test/zeta-1"),
    ]


def test_probe_candidates_discard_partial_provider_output_on_iterator_error() -> None:
    def parse(url: str) -> ProviderUrlTarget:
        return ProviderUrlTarget(
            provider_id="example",
            target_kind=ProviderTargetKind.BOARD,
            url=url,
            board_identity="acme",
        )

    def broken_builder(_slug: str):
        yield "https://jobs.example.test/acme"
        raise RuntimeError("plugin iterator failed")

    registry = ProviderRegistry(
        [_definition("example", parse)],
        probe_url_builders={"example": broken_builder},
        max_probe_candidates_per_provider=2,
        max_probe_candidates_total=2,
    )

    assert registry.probe_candidates("acme") == ()
