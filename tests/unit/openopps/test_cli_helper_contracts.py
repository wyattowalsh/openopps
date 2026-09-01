from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import openopps.cli as cli_module
from openopps.metrics import SyncMetrics
from openopps.models import BoardProviderRecord, ProviderSupport, SourceRecord
from openopps.settings import OpenOppsSettings


def _route(
    provider_id: str,
    board_key: str,
    support_level: ProviderSupport,
) -> BoardProviderRecord:
    return BoardProviderRecord(
        id=f"catalog:{board_key}:{provider_id}",
        source_key="catalog",
        board_key=board_key,
        provider_id=provider_id,
        support_level=support_level,
    )


def test_combine_sync_metrics_merges_every_counter_and_error_reason() -> None:
    first = SyncMetrics(
        name="sources",
        pages=1,
        boards=2,
        board_providers=3,
        jobs=4,
        jobs_persisted=3,
        job_sync_attempts=2,
        job_sync_runs=1,
        jobs_deduped=1,
        skipped=2,
        duplicate_routes_skipped=1,
        retries=2,
        provider_errors={"greenhouse": 2},
        provider_error_details={"greenhouse": {"timeout": 2}},
        started_at=10.0,
        finished_at=12.0,
    )
    second = SyncMetrics(
        name="jobs",
        pages=2,
        boards=3,
        board_providers=4,
        jobs=5,
        jobs_persisted=4,
        job_sync_attempts=3,
        job_sync_runs=2,
        jobs_deduped=2,
        skipped=3,
        duplicate_routes_skipped=2,
        retries=3,
        provider_errors={"greenhouse": 1, "lever": 1},
        provider_error_details={
            "greenhouse": {"timeout": 1, "invalid_payload": 1},
            "lever": {"timeout": 1},
        },
        started_at=12.0,
    )

    combined = cli_module._combine_sync_metrics("sync", first, second)

    assert combined.pages == 3
    assert combined.boards == 5
    assert combined.board_providers == 7
    assert combined.jobs == 9
    assert combined.jobs_persisted == 7
    assert combined.job_sync_attempts == 5
    assert combined.job_sync_runs == 3
    assert combined.jobs_deduped == 3
    assert combined.skipped == 5
    assert combined.duplicate_routes_skipped == 3
    assert combined.retries == 5
    assert combined.provider_errors == {"greenhouse": 3, "lever": 1}
    assert combined.provider_error_details == {
        "greenhouse": {"timeout": 3, "invalid_payload": 1},
        "lever": {"timeout": 1},
    }
    assert combined.started_at == 10.0
    assert combined.finished_at == 12.0


def test_combine_sync_metrics_finishes_an_empty_workflow() -> None:
    combined = cli_module._combine_sync_metrics("sync")

    assert combined.finished_at is not None
    assert combined.name == "sync"


def test_status_provider_gaps_filters_groups_sorts_and_bounds_examples() -> None:
    routes = [
        _route("zeta", f"zeta-{index}", ProviderSupport.JOBS) for index in range(7)
    ]
    routes.extend(
        [
            _route("alpha", "detect-one", ProviderSupport.DETECT),
            _route("alpha", "detect-one", ProviderSupport.DETECT),
            _route("beta", "unsupported-one", ProviderSupport.UNSUPPORTED),
        ]
    )

    job_gaps = cli_module._status_provider_gaps(
        routes,
        support_level=ProviderSupport.JOBS,
    )
    non_job_gaps = cli_module._status_provider_gaps(
        routes,
        exclude_support_level=ProviderSupport.JOBS,
    )

    assert job_gaps == [
        {
            "provider": "zeta",
            "supportLevel": "jobs",
            "count": 7,
            "examples": [f"zeta-{index}" for index in range(5)],
        }
    ]
    assert non_job_gaps == [
        {
            "provider": "alpha",
            "supportLevel": "detect",
            "count": 2,
            "examples": ["detect-one"],
        },
        {
            "provider": "beta",
            "supportLevel": "unsupported",
            "count": 1,
            "examples": ["unsupported-one"],
        },
    ]


@pytest.mark.parametrize(
    ("counts", "readiness", "expected_fragment"),
    [
        (
            {"sources": 0, "boards": 0, "boardProviders": 0, "jobs": 0},
            {"missingRouteMetadata": 0, "executableRoutes": 0},
            "sync a16z",
        ),
        (
            {"sources": 1, "boards": 0, "boardProviders": 0, "jobs": 0},
            {"missingRouteMetadata": 0, "executableRoutes": 0},
            "sources sync",
        ),
        (
            {"sources": 1, "boards": 1, "boardProviders": 0, "jobs": 0},
            {"missingRouteMetadata": 0, "executableRoutes": 0},
            "provider coverage",
        ),
        (
            {"sources": 1, "boards": 1, "boardProviders": 1, "jobs": 0},
            {"missingRouteMetadata": 2, "executableRoutes": 0},
            "attach route metadata",
        ),
        (
            {"sources": 1, "boards": 1, "boardProviders": 1, "jobs": 0},
            {"missingRouteMetadata": 0, "executableRoutes": 1},
            "jobs sync",
        ),
        (
            {"sources": 1, "boards": 1, "boardProviders": 1, "jobs": 1},
            {"missingRouteMetadata": 0, "executableRoutes": 1},
            "jobs list",
        ),
    ],
)
def test_next_action_covers_each_readiness_stage(
    counts: dict[str, int],
    readiness: dict[str, int],
    expected_fragment: str,
) -> None:
    assert expected_fragment in cli_module._next_action(counts, readiness)


def test_status_issues_reports_every_actionable_local_gap() -> None:
    issues = cli_module._status_issues(
        {"sources": 0, "boards": 0},
        {"missingRouteMetadata": 2, "detectOnlyRoutes": 3},
        {"boards": {"withOnlyNonSupportedProviderHints": 4}},
    )

    assert issues == [
        "no_sources",
        "no_boards",
        "missing_route_metadata",
        "detect_only_routes",
        "only_non_supported_provider_hints",
    ]


def test_cache_helpers_fail_closed_without_a_local_sqlite_database() -> None:
    settings = OpenOppsSettings.model_construct(db_url="postgresql://db/openopps")

    assert cli_module._cache_status(settings) == {
        "path": None,
        "total": 0,
        "fresh": 0,
        "expired": 0,
        "staleOnErrorEligible": 0,
        "byNamespace": {},
    }
    with pytest.raises(typer.BadParameter, match="local sqlite"):
        cli_module._cache(settings)


def test_cache_refresh_settings_copy_is_explicit_and_non_mutating(monkeypatch) -> None:
    settings = OpenOppsSettings(cache_refresh=False)
    monkeypatch.setattr(cli_module, "_settings", lambda: settings)

    unchanged = cli_module._settings_with_cache_refresh(False)
    refreshed = cli_module._settings_with_cache_refresh(True)

    assert unchanged is settings
    assert refreshed is not settings
    assert settings.cache_refresh is False
    assert refreshed.cache_refresh is True


def test_verbose_sync_logging_leaves_package_logging_enabled(monkeypatch) -> None:
    def unexpected_toggle(_name: str) -> None:
        pytest.fail("verbose logging must not toggle the package logger")

    monkeypatch.setattr(cli_module.logger, "disable", unexpected_toggle)
    monkeypatch.setattr(cli_module.logger, "enable", unexpected_toggle)

    with cli_module._sync_logging(verbose=True):
        pass


def test_example_dataset_loader_reports_missing_and_malformed_scripts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Path, "is_file", lambda _path: False)
    with pytest.raises(
        cli_module.ClickException,
        match="Example dataset script not found",
    ):
        cli_module._example_data_script_path()

    script_path = Path("examples/build_example_data.py")
    monkeypatch.setattr(cli_module, "_example_data_script_path", lambda: script_path)
    monkeypatch.setattr(cli_module.runpy, "run_path", lambda _path: {"other": object()})
    with pytest.raises(
        cli_module.ClickException,
        match="must define build_example_dataset",
    ):
        cli_module._load_example_dataset_builder()


def test_main_version_callback_prints_and_exits(capsys) -> None:
    with pytest.raises(cli_module.typer.Exit):
        cli_module.main(version=True)

    assert capsys.readouterr().out.strip().startswith("openopps ")


def test_root_intro_flag_is_parsed_before_help() -> None:
    result = CliRunner().invoke(cli_module.app, ["--intro", "--help"])

    assert result.exit_code == 0
    assert "opening opportunity portal" in result.output


def test_root_group_scopes_context_across_nested_invocation_and_failure() -> None:
    root = typer.Typer(cls=cli_module.OpenOppsRootGroup)
    nested = typer.Typer()
    observed_contexts: list[object | None] = []

    @nested.command("inspect")
    def inspect_context() -> None:
        observed_contexts.append(cli_module._ACTIVE_CLI_CONTEXT.get())

    @nested.command("fail")
    def fail_command() -> None:
        raise cli_module.ClickException("bounded failure")

    root.add_typer(nested, name="nested")

    success = CliRunner().invoke(root, ["nested", "inspect"])
    assert success.exit_code == 0
    assert len(observed_contexts) == 1
    assert observed_contexts[0] is not None
    assert cli_module._ACTIVE_CLI_CONTEXT.get() is None

    failure = CliRunner().invoke(root, ["nested", "fail"])
    assert failure.exit_code == 1
    assert "Error: bounded failure" in failure.output
    assert cli_module._ACTIVE_CLI_CONTEXT.get() is None


def test_sources_list_uses_stored_records_and_supports_human_and_json_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    db_path.touch()
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    source = SourceRecord(
        key="custom",
        url="https://example.com/catalog",
        provider_id="manual",
    )
    table_calls: list[tuple[object, ...]] = []
    json_calls: list[object] = []

    class FakeStore:
        def __init__(self, configured_settings: OpenOppsSettings) -> None:
            assert configured_settings is settings

        def list_sources(self) -> list[SourceRecord]:
            return [source]

    monkeypatch.setattr(cli_module, "_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "OpenOppsStore", FakeStore)
    monkeypatch.setattr(cli_module, "all_board_sources", lambda: [])
    monkeypatch.setattr(
        cli_module,
        "resolve_effective_sources",
        lambda _catalog, stored: stored,
    )
    monkeypatch.setattr(
        cli_module,
        "_table",
        lambda *args: table_calls.append(args),
    )
    monkeypatch.setattr(cli_module, "_json", json_calls.append)

    cli_module.sources_list(json_output=False)
    cli_module.sources_list(json_output=True)

    assert table_calls[0][0] == "Sources"
    assert table_calls[0][2] == [["custom", "manual", "https://example.com/catalog"]]
    assert json_calls == [[source.model_dump(mode="json")]]


def test_sources_show_rejects_unknown_keys_and_serializes_known_source(
    monkeypatch,
) -> None:
    source = SourceRecord(
        key="custom",
        url="https://example.com/catalog",
        provider_id="manual",
    )
    rendered: list[object] = []
    responses = iter([None, source])

    monkeypatch.setattr(cli_module, "_store", lambda: object())
    monkeypatch.setattr(
        cli_module,
        "_effective_source",
        lambda _store, _key: next(responses),
    )
    monkeypatch.setattr(cli_module, "_json", rendered.append)

    with pytest.raises(typer.BadParameter, match="Unknown source: missing"):
        cli_module.sources_show("missing")
    cli_module.sources_show("custom")

    assert rendered == [source.model_dump(mode="json")]
