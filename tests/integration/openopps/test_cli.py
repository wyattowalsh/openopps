import json
from pathlib import Path
import sqlite3

from click import unstyle
import pytest
import openopps.cli as cli_module
from typer.testing import CliRunner

from openopps import __version__
from openopps.cli import app
from openopps.models import BoardProviderRecord, BoardRecord, JobRecord, ProviderSupport
from openopps.models import SourceRecord
from openopps.metrics import ProgressUpdate, SyncMetrics
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import source_board_key, stable_id


runner = CliRunner()
HELP_TERMINAL_WIDTH = 120


def invoke(tmp_path: Path, *args: str):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    return runner.invoke(app, list(args), env={"OPENOPPS_DB_URL": db_url})


def plain(text: str) -> str:
    return unstyle(text)


def test_cli_root_help_shows_intro_art_at_top():
    result = runner.invoke(app, ["--help"], terminal_width=HELP_TERMINAL_WIDTH)
    output = plain(result.output)

    assert result.exit_code == 0
    assert "opening opportunity portal" in output
    assert output.index("opening opportunity portal") < output.index("Usage:")
    assert "--intro" in output
    assert "--no-intro" in output


def test_cli_root_help_respects_no_intro_option():
    result = runner.invoke(app, ["--no-intro", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "opening opportunity portal" not in result.output


def test_cli_no_command_behavior_stays_clean():
    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "Missing command" in result.stderr
    assert result.stdout == ""
    assert "opening opportunity portal" not in result.output


def test_cli_version_option_exits_cleanly():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"openopps {__version__}"
    assert "opening opportunity portal" not in result.output


def test_cli_subcommand_help_skips_intro_art():
    result = runner.invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert "Inspect persisted route readiness" in result.output
    assert "opening opportunity portal" not in result.output


def test_cli_nested_command_help_skips_intro_art():
    result = runner.invoke(
        app,
        ["admin", "providers", "list", "--help"],
        terminal_width=HELP_TERMINAL_WIDTH,
    )
    output = plain(result.output)

    assert result.exit_code == 0
    assert "--json" in output
    assert "opening opportunity portal" not in output


def test_sync_commands_expose_cache_refresh_option():
    top_level_result = runner.invoke(
        app, ["sync", "--help"], terminal_width=HELP_TERMINAL_WIDTH
    )
    sources_result = runner.invoke(
        app, ["sources", "sync", "--help"], terminal_width=HELP_TERMINAL_WIDTH
    )
    boards_result = runner.invoke(
        app, ["boards", "sync", "--help"], terminal_width=HELP_TERMINAL_WIDTH
    )
    jobs_result = runner.invoke(
        app, ["jobs", "sync", "--help"], terminal_width=HELP_TERMINAL_WIDTH
    )

    assert top_level_result.exit_code == 0
    assert sources_result.exit_code == 0
    assert boards_result.exit_code == 0
    assert jobs_result.exit_code == 0
    top_level_output = plain(top_level_result.output)
    sources_output = plain(sources_result.output)
    boards_output = plain(boards_result.output)
    jobs_output = plain(jobs_result.output)
    for flag in [
        "--metrics-json",
        "--refresh-cache",
        "--strict",
        "--verbose",
        "-M",
        "-R",
        "-V",
        "-m",
        "-r",
        "-v",
    ]:
        assert flag in top_level_output
        assert flag in sources_output
        assert flag in boards_output
        assert flag in jobs_output


def test_top_level_help_examples_prefer_stable_commands():
    epilog = app.info.epilog or ""

    assert "openopps status" in epilog
    assert "providers coverage" in epilog
    assert "--metrics-json" in epilog
    assert "admin providers probe-routes" not in epilog


def test_root_help_groups_commands_by_user_journey():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Everyday workflow" in result.output
    assert "Operational surfaces" in result.output
    assert "Advanced admin" in result.output
    assert "local-first route ledger" in result.output
    assert "Automation" in result.output


def test_filter_help_describes_actual_scope_semantics():
    boards_result = runner.invoke(app, ["boards", "list", "--help"])
    jobs_result = runner.invoke(app, ["jobs", "list", "--help"])

    assert boards_result.exit_code == 0
    assert jobs_result.exit_code == 0
    assert "remove" in boards_result.output
    assert "provider filter" in boards_result.output
    assert "source job hint" in boards_result.output
    assert "provider job" in boards_result.output
    assert "synced job" in boards_result.output
    assert "normalized salary range" in jobs_result.output
    assert "overlaps this lower bound" in jobs_result.output or (
        "salary range" in jobs_result.output and "overlap" in jobs_result.output
    )
    assert "Inclusive YYYY-MM-DD" in jobs_result.output


def test_cli_default_intro_skips_non_interactive_runner(tmp_path: Path):
    result = invoke(tmp_path, "admin", "providers", "list", "--json")

    assert result.exit_code == 0
    assert json.loads(result.output)
    assert "opening opportunity portal" not in result.output


def test_status_json_reports_empty_local_state(tmp_path: Path):
    result = invoke(tmp_path, "status", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["database"]["counts"] == {
        "sources": 0,
        "boards": 0,
        "boardProviders": 0,
        "jobs": 0,
    }
    assert payload["cache"]["total"] == 0
    assert payload["readiness"] == {
        "executableRoutes": 0,
        "missingRouteMetadata": 0,
        "duplicateRoutesSkipped": 0,
        "detectOnlyRoutes": 0,
        "unsupportedRoutes": 0,
    }
    assert payload["plugins"]["loaded"] == 0
    assert payload["plugins"]["failed"] == 0
    assert payload["coverage"]["boards"]["total"] == 0
    assert payload["issues"] == ["no_sources", "no_boards"]
    assert "sources" in payload["nextAction"]


def test_cli_settings_validation_error_is_redacted_for_json_command():
    raw_db_url = "openoppsdb.sqlite?password=supersecret"

    result = runner.invoke(
        app,
        ["status", "--json"],
        env={"OPENOPPS_DB_URL": raw_db_url},
    )
    output = plain(result.output)

    assert result.exit_code != 0
    assert result.stdout == ""
    assert "Invalid OpenOpps configuration" in output
    assert "OPENOPPS_DB_URL" in output
    assert raw_db_url not in output
    assert "supersecret" not in output
    assert "Traceback" not in output


def test_doctor_json_is_parseable_status_output(tmp_path: Path):
    result = invoke(tmp_path, "doctor", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["database"]["counts"]["sources"] == 0
    assert "readiness" in payload
    assert "nextAction" in payload


def test_plugins_list_json_reports_no_plugins_by_default(tmp_path: Path):
    result = invoke(tmp_path, "plugins", "list", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "plugins": [],
        "conflicts": [],
        "loaded": 0,
        "failed": 0,
        "filters": {"disabled": [], "allowed": []},
    }


def test_plugins_list_json_reports_settings_filters(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    result = runner.invoke(
        app,
        ["plugins", "list", "--json"],
        env={
            "OPENOPPS_DB_URL": db_url,
            "OPENOPPS_PLUGIN_DISABLED": "broken",
            "OPENOPPS_PLUGIN_ALLOWED": "trusted",
        },
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["filters"] == {
        "disabled": ["broken"],
        "allowed": ["trusted"],
    }


def test_examples_seed_populates_database_and_cache(tmp_path: Path):
    seed_result = invoke(
        tmp_path,
        "examples",
        "seed",
        "--seed",
        "42",
        "--boards",
        "2",
        "--jobs-per-board",
        "1",
        "--json",
    )
    status_result = invoke(tmp_path, "status", "--json")
    cache_result = invoke(tmp_path, "cache", "status", "--json")

    assert seed_result.exit_code == 0
    assert json.loads(seed_result.output) == {
        "sources": 1,
        "boards": 2,
        "routes": 2,
        "jobs": 2,
        "cacheRecords": 2,
        "plugins": 1,
        "seed": 42,
    }
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["database"]["counts"] == {
        "sources": 1,
        "boards": 2,
        "boardProviders": 2,
        "jobs": 2,
    }
    assert status_payload["cache"]["total"] == 2
    assert status_payload["cache"]["fresh"] == 2
    assert cache_result.exit_code == 0
    cache_payload = json.loads(cache_result.output)
    assert cache_payload["path"] == str(tmp_path / "openopps.db")
    assert cache_payload["byNamespace"] == {"example-source": 2}
    assert not (tmp_path / "openopps.cache.db").exists()
    with sqlite3.connect(tmp_path / "openopps.db") as conn:
        count = conn.execute("select count(*) from http_cache").fetchone()[0]
    assert count == 2


def test_sources_sync_unknown_source_is_actionable_typer_error(tmp_path: Path):
    result = invoke(tmp_path, "sources", "sync", "definitelymissing")

    assert result.exit_code == 2
    assert "Unknown source: definitelymissing" in result.output


def test_cli_bad_parameter_errors_stay_distinct(tmp_path: Path):
    result = invoke(tmp_path, "jobs", "list", "--status", "archived", "--json")
    output = plain(result.output)

    assert result.exit_code == 2
    assert "invalid value" in output.lower()
    assert "open, closed, or all" in output
    assert "OpenOpps configuration" not in output


def test_sources_sync_reports_compact_warning_for_skips(tmp_path: Path):
    add_result = invoke(
        tmp_path,
        "admin",
        "sources",
        "add",
        "broken",
        "--url",
        "https://example.com/boards",
        "--provider",
        "missing-provider",
    )
    sync_result = invoke(tmp_path, "sources", "sync", "broken")

    assert add_result.exit_code == 0
    assert sync_result.exit_code == 0
    assert "sources.sync completed" in sync_result.stdout
    assert "Warning: sources.sync completed with skipped=1" in sync_result.stderr
    assert "--verbose" in sync_result.stderr


def test_sources_sync_uses_progress_for_human_output(monkeypatch, tmp_path: Path):
    calls = []

    async def fake_sync_sources(**_kwargs):
        return SyncMetrics(name="sources.sync").finish()

    def fake_run_sync_with_progress(label, run, *, enabled, verbose=False):
        calls.append((label, enabled, verbose))
        return run(lambda _message: None)

    monkeypatch.setattr(cli_module, "sync_sources", fake_sync_sources)
    monkeypatch.setattr(
        cli_module, "_run_sync_with_progress", fake_run_sync_with_progress
    )

    result = invoke(tmp_path, "sources", "sync")

    assert result.exit_code == 0
    assert calls == [("Syncing sources", True, False)]


def test_sources_sync_skips_progress_for_json_metrics(monkeypatch, tmp_path: Path):
    calls = []

    async def fake_sync_sources(**_kwargs):
        return SyncMetrics(name="sources.sync", boards=1).finish()

    def fake_run_sync_with_progress(label, run, *, enabled, verbose=False):
        calls.append((label, enabled, verbose))
        return run(lambda _message: None)

    monkeypatch.setattr(cli_module, "sync_sources", fake_sync_sources)
    monkeypatch.setattr(
        cli_module, "_run_sync_with_progress", fake_run_sync_with_progress
    )

    result = invoke(tmp_path, "sources", "sync", "--metrics-json")

    assert result.exit_code == 0
    assert calls == [("Syncing sources", False, False)]
    assert json.loads(result.output)["boards"] == 1
    assert "Traceback" not in result.output


def test_boards_sync_uses_progress_for_human_output(monkeypatch, tmp_path: Path):
    calls = []

    async def fake_sync_boards(**_kwargs):
        return SyncMetrics(name="boards.sync").finish()

    def fake_run_sync_with_progress(label, run, *, enabled, verbose=False):
        calls.append((label, enabled, verbose))
        return run(lambda _message: None)

    monkeypatch.setattr(cli_module, "sync_boards", fake_sync_boards)
    monkeypatch.setattr(
        cli_module, "_run_sync_with_progress", fake_run_sync_with_progress
    )

    result = invoke(tmp_path, "boards", "sync")

    assert result.exit_code == 0
    assert calls == [("Syncing boards", True, False)]


def test_top_level_sync_runs_sources_boards_and_jobs_in_order(
    monkeypatch, tmp_path: Path
):
    calls = []

    async def fake_sync_sources(**_kwargs):
        calls.append("sources")
        return SyncMetrics(name="sources.sync", boards=2).finish()

    async def fake_sync_boards(**_kwargs):
        calls.append("boards")
        return SyncMetrics(name="boards.sync", board_providers=1).finish()

    async def fake_sync_jobs(**_kwargs):
        calls.append("jobs")
        return SyncMetrics(name="jobs.sync", jobs=3).finish()

    def fake_run_sync_with_progress(label, run, *, enabled, verbose=False):
        calls.append((label, enabled, verbose))
        return run(lambda _message: None)

    monkeypatch.setattr(cli_module, "sync_sources", fake_sync_sources)
    monkeypatch.setattr(cli_module, "sync_boards", fake_sync_boards)
    monkeypatch.setattr(cli_module, "sync_jobs", fake_sync_jobs)
    monkeypatch.setattr(
        cli_module, "_run_sync_with_progress", fake_run_sync_with_progress
    )

    result = invoke(tmp_path, "sync", "a16z", "--metrics-json")

    assert result.exit_code == 0
    assert calls == [("Syncing OpenOpps", False, False), "sources", "boards", "jobs"]
    payload = json.loads(result.output)
    assert payload["name"] == "sync"
    assert payload["boards"] == 2
    assert payload["boardProviders"] == 1
    assert payload["jobs"] == 3


def test_combined_sync_metrics_span_stage_timings():
    sources = SyncMetrics(name="sources.sync", boards=2)
    boards = SyncMetrics(name="boards.sync", board_providers=1)
    jobs = SyncMetrics(
        name="jobs.sync",
        jobs=3,
        jobs_persisted=2,
        job_sync_runs=1,
        jobs_deduped=1,
    )
    sources.started_at = 10.0
    sources.finished_at = 12.0
    boards.started_at = 12.0
    boards.finished_at = 13.0
    jobs.started_at = 13.0
    jobs.finished_at = 15.0

    combined = cli_module._combine_sync_metrics("sync", sources, boards, jobs)

    assert combined.as_dict()["elapsedSeconds"] == 5.0
    assert combined.as_dict()["boards"] == 2
    assert combined.as_dict()["boardProviders"] == 1
    assert combined.as_dict()["jobs"] == 3
    assert combined.as_dict()["jobsPersisted"] == 2
    assert combined.as_dict()["jobSyncRuns"] == 1
    assert combined.as_dict()["jobsDeduped"] == 1


def test_jobs_sync_passes_route_limit_and_freshness(monkeypatch, tmp_path: Path):
    calls = {}

    async def fake_sync_jobs(**kwargs):
        calls.update(kwargs)
        return SyncMetrics(name="jobs.sync", job_sync_runs=2).finish()

    def fake_run_sync_with_progress(label, run, *, enabled, verbose=False):
        calls["progress"] = (label, enabled, verbose)
        return run(lambda _message: None)

    monkeypatch.setattr(cli_module, "sync_jobs", fake_sync_jobs)
    monkeypatch.setattr(
        cli_module, "_run_sync_with_progress", fake_run_sync_with_progress
    )

    result = invoke(
        tmp_path,
        "jobs",
        "sync",
        "--metrics-json",
        "--limit",
        "2",
        "--freshness-seconds",
        "3600",
    )

    assert result.exit_code == 0
    assert calls["progress"] == ("Syncing jobs", False, False)
    assert calls["limit"] == 2
    assert calls["freshness_seconds"] == 3600.0
    assert json.loads(result.output)["jobSyncRuns"] == 2


def test_run_sync_with_progress_renders_update_message(monkeypatch):
    calls = []
    columns = []

    class FakeConsole:
        is_interactive = True

        def __init__(self, *_args, **_kwargs):
            return

    class FakeProgress:
        def __init__(self, *progress_columns, **_kwargs):
            columns.extend(progress_columns)
            return

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def add_task(self, description, total=None, **_kwargs):
            calls.append(("add", description, total))
            return 1

        def update(self, task_id, **kwargs):
            calls.append(("update", task_id, kwargs))

    monkeypatch.setattr(cli_module, "Console", FakeConsole)
    monkeypatch.setattr(cli_module, "Progress", FakeProgress)

    def run(report):
        report(
            ProgressUpdate(
                stage="sources",
                message="[bold cyan on grey11] SRC [/] [dim]|[/] [dim]done[/] [bold]1/2 sources[/]",
                completed=1,
                total=2,
            )
        )
        return "done"

    result = cli_module._run_sync_with_progress(
        "Syncing sources",
        run,
        enabled=True,
    )

    assert result == "done"
    bar_column = next(
        column for column in columns if column.__class__.__name__ == "BarColumn"
    )
    assert bar_column.bar_width == 18
    assert calls == [
        ("add", "Syncing sources", 1),
        (
            "update",
            1,
            {
                "description": "[bold cyan on grey11] SRC [/] [dim]|[/] [dim]done[/] [bold]1/2 sources[/]",
                "completed": 1,
                "total": 2,
            },
        ),
    ]


def test_metrics_summary_always_prints_for_human_output(capsys):
    metrics = SyncMetrics(name="sources.sync", boards=2, jobs=3)
    metrics.jobs_persisted = 1
    metrics.finish()

    cli_module._metrics(metrics, metrics_json=False, profile=False)
    captured = capsys.readouterr()

    assert "sources.sync completed in" in captured.out
    assert "boards=2 jobs=3 jobsPersisted=1" in captured.out
    assert captured.err == ""


def test_profile_metrics_include_provider_errors_and_warning(capsys):
    metrics = SyncMetrics(name="jobs.sync")
    metrics.error("ashbyhq")
    metrics.finish()

    cli_module._metrics(metrics, metrics_json=False, profile=True)
    captured = capsys.readouterr()

    assert "jobs.sync completed in" in captured.out
    assert "providerErrors=1" in captured.out
    assert "skipped=0" in captured.out
    assert "Warning: jobs.sync completed with skipped=0" in captured.err
    assert "ashbyhq" in captured.err
    assert "--verbose" in captured.err


def test_strict_metrics_exit_nonzero_on_provider_errors():
    metrics = SyncMetrics(name="jobs.sync")
    metrics.error("ashbyhq")
    metrics.finish()

    with pytest.raises(SystemExit) as exc:
        cli_module._metrics(metrics, metrics_json=False, profile=False, strict=True)

    assert exc.value.code == 1


def test_status_human_output_lists_issues(tmp_path: Path):
    result = invoke(tmp_path, "status")

    assert result.exit_code == 0
    assert "Issues: no_sources, no_boards" in result.output


def test_doctor_human_output_includes_setup_checklist(tmp_path: Path):
    result = invoke(tmp_path, "doctor")

    assert result.exit_code == 0
    assert "Setup checklist:" in result.output
    assert "openopps sources sync" in result.output


def test_cli_reports_stale_stamped_database_without_traceback(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES ('0001_initial_app_sqlite')")
        conn.execute(
            """
            CREATE TABLE boards (
                key VARCHAR NOT NULL PRIMARY KEY,
                source_key VARCHAR NOT NULL,
                remote_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL
            )
            """
        )

    result = invoke(tmp_path, "status", "--json")

    assert result.exit_code != 0
    assert "does not match the OpenOpps v0.1.0 schema" in result.output
    assert "Reset that local DB" in result.output
    assert "Traceback" not in result.output


def test_admin_db_export_writes_integrity_checked_sqlite_snapshot(tmp_path: Path):
    seed_result = invoke(tmp_path, "examples", "seed", "--boards", "2", "--json")
    output = tmp_path / "snapshot.sqlite"

    result = invoke(tmp_path, "admin", "db", "export", "--output", str(output))

    assert seed_result.exit_code == 0
    assert result.exit_code == 0
    assert output.exists()
    with sqlite3.connect(f"file:{output}?mode=ro&immutable=1", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] > 0


def test_cache_purge_json_deletes_selected_namespace(tmp_path: Path):
    seed_result = invoke(tmp_path, "examples", "seed", "--boards", "2", "--json")
    purge_result = invoke(
        tmp_path,
        "admin",
        "cache",
        "purge",
        "--namespace",
        "example-source",
        "--json",
    )
    status_result = invoke(tmp_path, "cache", "status", "--json")

    assert seed_result.exit_code == 0
    assert purge_result.exit_code == 0
    assert json.loads(purge_result.output) == {
        "deleted": 2,
        "namespace": "example-source",
    }
    assert status_result.exit_code == 0
    assert json.loads(status_result.output)["total"] == 0


def seed_filter_cli_db(tmp_path: Path) -> None:
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(key="a16z", url="https://a16z.com/jobs", provider_id="consider")
    )
    store.upsert_source(
        SourceRecord(
            key="yc", url="https://www.ycombinator.com/companies", provider_id="yc"
        )
    )
    acme_key = source_board_key("a16z", "acme")
    bravo_key = source_board_key("yc", "bravo")
    store.upsert_boards(
        [
            BoardRecord(
                key=acme_key,
                source_key="a16z",
                remote_id="acme",
                remote_slug="acme",
                name="Acme AI",
                domain="acme.ai",
                markets=["Developer Tools"],
                locations=["Remote"],
                staff_count=42,
                num_jobs_hint=2,
            ),
            BoardRecord(
                key=bravo_key,
                source_key="yc",
                remote_id="bravo",
                remote_slug="bravo",
                name="Bravo Health",
                domain="bravo.health",
                markets=["Healthcare"],
                locations=["Boston"],
                staff_count=12,
                num_jobs_hint=0,
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=stable_id("a16z", acme_key, "ashbyhq"),
                source_key="a16z",
                board_key=acme_key,
                provider_id="ashbyhq",
                support_level=ProviderSupport.JOBS,
                count_hint=2,
            ),
            BoardProviderRecord(
                id=stable_id("yc", bravo_key, "lever"),
                source_key="yc",
                board_key=bravo_key,
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                count_hint=0,
            ),
        ]
    )
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": stable_id(acme_key, "ashbyhq", "1"),
                    "board_key": acme_key,
                    "provider_id": "ashbyhq",
                    "remote_id": "1",
                    "title": "Senior Platform Engineer",
                    "company": "Acme AI",
                    "locations": ["Remote"],
                    "department": "Engineering",
                    "team": "Platform",
                    "workplace_type": "Remote",
                    "employment_type": "Full-time",
                    "description": "Build Python developer tools.",
                    "remote": "Full",
                    "salary_min": 120000,
                    "salary_max": 180000,
                    "skills": [{"name": "Backend", "keywords": ["Python"]}],
                    "posted_at": "2026-05-10T12:00:00Z",
                }
            ),
            JobRecord.model_validate(
                {
                    "id": stable_id(bravo_key, "lever", "1"),
                    "board_key": bravo_key,
                    "provider_id": "lever",
                    "remote_id": "1",
                    "title": "Care Designer",
                    "company": "Bravo Health",
                    "locations": ["Boston"],
                    "department": "Design",
                    "team": "Care",
                    "workplace_type": "Onsite",
                    "employment_type": "Contract",
                    "description": "Design care workflows.",
                    "remote": "None",
                    "salary_min": 70000,
                    "salary_max": 90000,
                    "skills": [{"name": "Design", "keywords": ["Figma"]}],
                    "posted_at": "2026-04-01",
                }
            ),
        ]
    )


def test_cli_provider_and_board_flow(tmp_path: Path):
    result = invoke(tmp_path, "admin", "providers", "list", "--json")
    assert result.exit_code == 0
    assert "greenhouse" in result.output
    providers = json.loads(result.output)
    greenhouse = next(
        provider for provider in providers if provider["id"] == "greenhouse"
    )
    assert greenhouse["detectsRoutes"] is True
    assert greenhouse["supportLevel"]
    assert "route_detector" not in greenhouse
    assert "detects_routes" not in greenhouse

    result = invoke(tmp_path, "admin", "db", "init")
    assert result.exit_code == 0

    result = invoke(tmp_path, "admin", "boards", "add", "acme", "--name", "Acme")
    assert result.exit_code == 0

    result = invoke(
        tmp_path,
        "admin",
        "boards",
        "add-provider",
        "acme",
        "lever",
        "--token",
        "acme",
    )
    assert result.exit_code == 0
    assert "lever" in result.output

    result = invoke(tmp_path, "boards", "list", "--json")
    assert result.exit_code == 0
    assert "Acme" in result.output

    result = invoke(tmp_path, "admin", "providers", "registry", "--json")
    assert result.exit_code == 0
    registry = json.loads(result.output)
    assert registry["routeCount"] == 1
    assert registry["routes"][0]["requestKey"] == "lever:token:acme"


def test_low_level_commands_are_under_admin_namespace(tmp_path: Path):
    old_result = invoke(tmp_path, "providers", "list", "--json")
    admin_result = invoke(tmp_path, "admin", "providers", "list", "--json")

    assert old_result.exit_code != 0
    assert admin_result.exit_code == 0
    assert json.loads(admin_result.output)


def test_boards_enrich_json_dry_run_and_apply(tmp_path: Path):
    board_key = source_board_key("a16z", "acme")
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key=board_key,
                source_key="a16z",
                remote_id="acme",
                name="Acme",
                raw_payload={"website": {"url": "https://acme.com"}},
            )
        ]
    )

    dry_run = invoke(tmp_path, "admin", "boards", "enrich", "--json")
    applied = invoke(tmp_path, "admin", "boards", "enrich", "--apply", "--json")
    board = store.get_board(board_key)

    assert dry_run.exit_code == 0
    assert json.loads(dry_run.output)["applied"] is False
    assert applied.exit_code == 0
    assert json.loads(applied.output)["applied"] is True
    assert board is not None
    assert board.website_url == "https://acme.com"


def test_cli_superset_lists_empty_db(tmp_path: Path):
    result = invoke(tmp_path, "jobs", "list", "--json")
    assert result.exit_code == 0
    assert "[]" in result.output


def test_sources_show_prefers_persisted_source_over_catalog(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(
            key="a16z",
            url="https://custom.example/companies",
            provider_id="consider",
        )
    )

    result = invoke(tmp_path, "sources", "show", "a16z")

    assert result.exit_code == 0
    row = json.loads(result.output)
    assert row["url"] == "https://custom.example/companies"
    assert row["provider_id"] == "consider"


def test_sources_add_rejects_private_or_deceptive_urls(tmp_path: Path):
    private_result = invoke(
        tmp_path,
        "admin",
        "sources",
        "add",
        "bad",
        "--url",
        "http://127.0.0.1/companies",
    )
    deceptive_result = invoke(
        tmp_path,
        "admin",
        "providers",
        "detect",
        "https://greenhouse.io.evil.example/acme",
    )

    assert private_result.exit_code != 0
    assert deceptive_result.exit_code != 0


def test_cli_provider_any_alias(tmp_path: Path):
    assert invoke(tmp_path, "admin", "db", "init").exit_code == 0
    assert (
        invoke(tmp_path, "admin", "boards", "add", "acme", "--name", "Acme").exit_code
        == 0
    )
    assert (
        invoke(
            tmp_path,
            "admin",
            "boards",
            "add-provider",
            "acme",
            "lever",
            "--token",
            "acme",
        ).exit_code
        == 0
    )

    result = invoke(tmp_path, "jobs", "list", "--provider", "any", "--json")

    assert result.exit_code == 0
    assert "[]" in result.output


def test_cli_board_list_filters_json(tmp_path: Path):
    seed_filter_cli_db(tmp_path)

    result = invoke(
        tmp_path,
        "boards",
        "list",
        "--provider",
        "ashbyhq",
        "--market",
        "developer",
        "--location",
        "remote",
        "--domain",
        "acme",
        "--has-jobs",
        "--min-staff",
        "10",
        "--max-staff",
        "50",
        "--json",
    )

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert [row["key"] for row in rows] == [source_board_key("a16z", "acme")]


def test_cli_job_list_filters_json(tmp_path: Path):
    seed_filter_cli_db(tmp_path)

    result = invoke(
        tmp_path,
        "jobs",
        "list",
        "--source",
        "a16z",
        "--provider",
        "ashbyhq",
        "--location",
        "remote",
        "--department",
        "engineer",
        "--team",
        "platform",
        "--workplace-type",
        "remote",
        "--remote",
        "Full",
        "--type",
        "full",
        "--salary-min",
        "150000",
        "--skill",
        "python",
        "--query",
        "developer tools",
        "--posted-after",
        "2026-05-01",
        "--posted-before",
        "2026-05-31",
        "--json",
    )

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert [row["id"] for row in rows] == [
        stable_id(source_board_key("a16z", "acme"), "ashbyhq", "1")
    ]


def test_cli_board_export_uses_list_filters(tmp_path: Path):
    seed_filter_cli_db(tmp_path)
    output = tmp_path / "boards.jsonl"

    result = invoke(
        tmp_path,
        "boards",
        "export",
        "--output",
        str(output),
        "--provider",
        "ashbyhq",
        "--market",
        "developer",
        "--has-jobs",
    )

    assert result.exit_code == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["key"] for row in rows] == [source_board_key("a16z", "acme")]


def test_cli_job_export_uses_list_filters(tmp_path: Path):
    seed_filter_cli_db(tmp_path)
    output = tmp_path / "jobs.jsonl"

    result = invoke(
        tmp_path,
        "jobs",
        "export",
        "--output",
        str(output),
        "--provider",
        "ashbyhq",
        "--remote",
        "Full",
        "--skill",
        "python",
        "--salary-min",
        "150000",
    )

    assert result.exit_code == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["id"] for row in rows] == [
        stable_id(source_board_key("a16z", "acme"), "ashbyhq", "1")
    ]


def test_cli_jobs_status_filter_and_history(tmp_path: Path):
    seed_filter_cli_db(tmp_path)
    acme_job_id = stable_id(source_board_key("a16z", "acme"), "ashbyhq", "1")
    bravo_job_id = stable_id(source_board_key("yc", "bravo"), "lever", "1")
    store = OpenOppsStore(
        OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    )

    store.sync_jobs_for_route(source_board_key("a16z", "acme"), "ashbyhq", [])

    default_result = invoke(tmp_path, "jobs", "list", "--json")
    all_result = invoke(tmp_path, "jobs", "list", "--status", "all", "--json")
    history_result = invoke(tmp_path, "jobs", "history", acme_job_id, "--json")

    assert default_result.exit_code == 0
    assert all_result.exit_code == 0
    assert history_result.exit_code == 0
    assert [row["id"] for row in json.loads(default_result.output)] == [bravo_job_id]
    assert {row["id"] for row in json.loads(all_result.output)} == {
        acme_job_id,
        bravo_job_id,
    }
    history = json.loads(history_result.output)
    assert [row["version"] for row in history] == [1]
    assert history[0]["content_hash"]


def test_cli_common_short_options_accept_lowercase_and_uppercase(tmp_path: Path):
    seed_filter_cli_db(tmp_path)
    board_key = source_board_key("a16z", "acme")
    output = tmp_path / "short-jobs.jsonl"

    boards_result = invoke(
        tmp_path,
        "boards",
        "list",
        "-p",
        "ashbyhq",
        "-n",
        "1",
        "-j",
    )
    jobs_result = invoke(
        tmp_path,
        "jobs",
        "list",
        "-S",
        "a16z",
        "-B",
        board_key,
        "-P",
        "ashbyhq",
        "-N",
        "1",
        "-J",
    )
    export_result = invoke(
        tmp_path,
        "jobs",
        "export",
        "-O",
        str(output),
        "-F",
        "jsonl",
        "-S",
        "a16z",
        "-P",
        "ashbyhq",
        "-N",
        "1",
    )

    assert boards_result.exit_code == 0
    assert jobs_result.exit_code == 0
    assert export_result.exit_code == 0
    assert [row["key"] for row in json.loads(boards_result.output)] == [board_key]
    assert [row["id"] for row in json.loads(jobs_result.output)] == [
        stable_id(board_key, "ashbyhq", "1")
    ]
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["id"] for row in rows] == [stable_id(board_key, "ashbyhq", "1")]


def test_cli_provider_any_all_aliases_return_all_jobs(tmp_path: Path):
    seed_filter_cli_db(tmp_path)

    any_result = invoke(tmp_path, "jobs", "list", "--provider", "any", "--json")
    all_result = invoke(tmp_path, "jobs", "list", "--provider", "all", "--json")
    lever_result = invoke(tmp_path, "jobs", "list", "--provider", "lever", "--json")

    assert any_result.exit_code == 0
    assert all_result.exit_code == 0
    assert lever_result.exit_code == 0
    assert {row["id"] for row in json.loads(any_result.output)} == {
        stable_id(source_board_key("a16z", "acme"), "ashbyhq", "1"),
        stable_id(source_board_key("yc", "bravo"), "lever", "1"),
    }
    assert {row["id"] for row in json.loads(all_result.output)} == {
        stable_id(source_board_key("a16z", "acme"), "ashbyhq", "1"),
        stable_id(source_board_key("yc", "bravo"), "lever", "1"),
    }
    assert [row["id"] for row in json.loads(lever_result.output)] == [
        stable_id(source_board_key("yc", "bravo"), "lever", "1")
    ]


def test_cli_probe_routes_empty_db(tmp_path: Path):
    result = invoke(tmp_path, "admin", "providers", "probe-routes", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["checked"] == 0
    assert result.stderr == ""


def test_cli_provider_health_json(monkeypatch, tmp_path: Path):
    class FakeSummary:
        not_covered = {}

        def as_dict(self):
            return {
                "sources": [],
                "routes": [],
                "notCovered": [],
                "sourceStatus": {},
                "routeStatus": {},
                "duplicateRoutesSkipped": 0,
                "sourceCount": 0,
                "routeCount": 0,
                "notCoveredCount": 0,
                "applied": False,
            }

    async def fake_check_provider_health(**_kwargs):
        return FakeSummary()

    monkeypatch.setattr(cli_module, "check_provider_health", fake_check_provider_health)

    result = invoke(tmp_path, "providers", "health", "--json")

    assert result.exit_code == 0
    assert json.loads(result.output)["routeCount"] == 0


def test_cli_detects_ashby_hosted_board_url(tmp_path: Path):
    result = invoke(
        tmp_path, "admin", "providers", "detect", "https://jobs.ashbyhq.com/acme"
    )

    assert result.exit_code == 0
    detected = json.loads(result.output)
    assert detected["provider_id"] == "ashbyhq"
    assert detected["token"] == "acme"


def test_cli_probe_routes_accepts_ashby_provider(tmp_path: Path):
    result = invoke(
        tmp_path,
        "admin",
        "providers",
        "probe-routes",
        "--provider",
        "ashbyhq",
        "--limit",
        "1",
        "--json",
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["checked"] == 0
