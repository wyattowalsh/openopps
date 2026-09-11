from __future__ import annotations

from click import unstyle
from typer.testing import CliRunner

from openopps.cli import app
from openopps.job_profiles import DEFAULT_CLI_PROFILE, PROFILE_NAMES

runner = CliRunner()
HELP_TERMINAL_WIDTH = 120


def _help(*args: str) -> str:
    result = runner.invoke(app, [*args, "--help"], terminal_width=HELP_TERMINAL_WIDTH)
    assert result.exit_code == 0, result.output
    return unstyle(result.output)


def test_jobs_export_help_documents_profile_choices_and_full_default() -> None:
    output = _help("jobs", "export")

    assert "--profile" in output
    for name in PROFILE_NAMES:
        assert name in output
    assert DEFAULT_CLI_PROFILE == "full"
    assert "full" in output
    assert "jobs sync" in output or "sync, list, show, or history" in output


def test_jobs_pull_help_documents_profile_and_keeps_metrics_file() -> None:
    output = _help("jobs", "pull")

    assert "--profile" in output
    for name in PROFILE_NAMES:
        assert name in output
    assert "full" in output
    assert "--metrics-file" in output


def test_jobs_pull_help_does_not_advertise_metrics_json_channel() -> None:
    output = _help("jobs", "pull")

    assert "--metrics-file" in output
    if "--metrics-json" in output:
        assert "catalog sync" in output.casefold()


def test_jobs_sync_help_keeps_boolean_profile_summary_flag() -> None:
    output = _help("jobs", "sync")

    assert "--profile" in output
    assert "human-readable sync" in output
    assert "core, search, full, or raw" not in output
    assert "Job JSON profile" not in output


def test_jobs_list_show_history_do_not_advertise_job_json_profile() -> None:
    for command in ("list", "show", "history"):
        output = _help("jobs", command)
        assert "Job JSON profile" not in output
        assert "core, search, full, or raw" not in output
