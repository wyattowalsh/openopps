from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from openopps.models import ProviderSupport
from openopps.pull_coverage import (
    catalog_store_has_route,
    classify_pull_coverage,
    overlay_route_is_packaged,
    url_pull_reserved_enabled,
)
from openopps.pull_models import PullCoverageClass, PullTerminalState


ROOT = Path(__file__).resolve().parents[3]
_UNKNOWN_TOKEN = "uncovered-board-zz-not-packaged"


@dataclass(frozen=True)
class _Route:
    provider_id: str
    token: str | None = None
    board_key: str = "board"
    support_level: ProviderSupport = ProviderSupport.JOBS
    source_key: str = "catalog"


class _Store:
    def __init__(self, routes: tuple[_Route, ...]) -> None:
        self.routes = routes

    def list_board_providers(
        self,
        *,
        source_key: str | None = None,
        board_key: str | None = None,
        provider_id: str | None = None,
        job_capable_only: bool = False,
    ) -> tuple[_Route, ...]:
        del source_key, board_key
        selected = []
        for route in self.routes:
            if provider_id is not None and route.provider_id != provider_id:
                continue
            if job_capable_only and route.support_level != ProviderSupport.JOBS:
                continue
            selected.append(route)
        return tuple(selected)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_overlay_known_greenhouse_token_is_packaged_without_http() -> None:
    assert overlay_route_is_packaged("greenhouse", "stripe")
    assert (
        classify_pull_coverage(
            provider_id="greenhouse",
            board_identity="stripe",
            terminal_state=PullTerminalState.SUCCEEDED,
        )
        is PullCoverageClass.OVERLAY_PACKAGED
    )


def test_unknown_token_is_url_pull_reserved_after_store_join() -> None:
    assert not overlay_route_is_packaged("greenhouse", _UNKNOWN_TOKEN)
    assert url_pull_reserved_enabled() is True
    assert (
        classify_pull_coverage(
            provider_id="greenhouse",
            board_identity=_UNKNOWN_TOKEN,
            terminal_state=PullTerminalState.SUCCEEDED,
        )
        is PullCoverageClass.URL_PULL_RESERVED
    )


def test_catalog_route_fixture_wins_over_overlay_and_ephemeral() -> None:
    store = _Store(
        (
            _Route(provider_id="greenhouse", token="stripe"),
            _Route(provider_id="greenhouse", token=_UNKNOWN_TOKEN),
        )
    )

    def has_route(provider_id: str, board_identity: str) -> bool:
        return catalog_store_has_route(store, provider_id, board_identity)

    assert (
        classify_pull_coverage(
            provider_id="greenhouse",
            board_identity="stripe",
            terminal_state=PullTerminalState.SUCCEEDED,
            catalog_has_route=has_route,
        )
        is PullCoverageClass.CATALOG_ROUTE
    )
    assert (
        classify_pull_coverage(
            provider_id="greenhouse",
            board_identity=_UNKNOWN_TOKEN,
            terminal_state=PullTerminalState.SUCCEEDED,
            catalog_has_route=has_route,
        )
        is PullCoverageClass.CATALOG_ROUTE
    )


def test_failures_are_not_applicable_even_for_packaged_tokens() -> None:
    assert (
        classify_pull_coverage(
            provider_id="greenhouse",
            board_identity="stripe",
            terminal_state=PullTerminalState.FAILED,
        )
        is PullCoverageClass.NOT_APPLICABLE
    )


def test_catalog_store_ignores_reserved_url_pull_source_key() -> None:
    store = _Store(
        (
            _Route(
                provider_id="greenhouse",
                token=_UNKNOWN_TOKEN,
                source_key="url-pull",
            ),
        )
    )

    assert catalog_store_has_route(store, "greenhouse", _UNKNOWN_TOKEN) is False


def test_catalog_store_ignores_detect_only_routes() -> None:
    store = _Store(
        (
            _Route(
                provider_id="greenhouse",
                token=_UNKNOWN_TOKEN,
                support_level=ProviderSupport.DETECT,
            ),
        )
    )

    assert catalog_store_has_route(store, "greenhouse", _UNKNOWN_TOKEN) is False


def test_pull_coverage_and_service_do_not_import_discovery() -> None:
    for relative in (
        "src/openopps/pull_coverage.py",
        "src/openopps/pull_service.py",
        "src/openopps/pull_metrics.py",
    ):
        names = _imported_modules(ROOT / relative)
        assert not any(
            name == "openopps.discovery" or name.startswith("openopps.discovery.")
            for name in names
        )
