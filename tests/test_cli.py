import json
import os
import subprocess
import sys
from pathlib import Path

import openopps.cli as cli_module
from typer.testing import CliRunner

from openopps.cli import app
from openopps.models import BoardProviderRecord, BoardRecord, JobRecord, ProviderSupport
from openopps.models import SourceRecord
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import source_board_key, stable_id


runner = CliRunner()


def invoke(tmp_path: Path, *args: str):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    return runner.invoke(app, list(args), env={"OPENOPPS_DB_URL": db_url})


def test_cli_help_exposes_intro_option():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--intro" in result.output
    assert "--no-intro" in result.output
    assert "opening opportunity portal" not in result.output


def test_cli_no_command_behavior_stays_clean():
    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "Missing command" in result.stderr
    assert result.stdout == ""
    assert "opening opportunity portal" not in result.output


def test_cli_subcommand_help_skips_intro(monkeypatch):
    calls = []

    def fake_play_intro(
        *, enabled: bool = True, duration: float = 0.9, fps: float = 12.0
    ):
        calls.append(enabled)

    monkeypatch.setattr(cli_module, "play_intro", fake_play_intro)
    monkeypatch.setattr(sys, "argv", ["openopps", "providers", "--help"])

    result = runner.invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert calls == []
    assert "Inspect provider readiness" in result.output


def test_cli_nested_command_help_skips_intro(monkeypatch):
    calls = []

    def fake_play_intro(
        *, enabled: bool = True, duration: float = 0.9, fps: float = 12.0
    ):
        calls.append(enabled)

    monkeypatch.setattr(cli_module, "play_intro", fake_play_intro)
    monkeypatch.setattr(
        sys, "argv", ["openopps", "admin", "providers", "list", "--help"]
    )

    result = runner.invoke(app, ["admin", "providers", "list", "--help"])

    assert result.exit_code == 0
    assert calls == []
    assert "--json" in result.output


def test_sync_commands_expose_cache_refresh_option():
    sources_result = runner.invoke(app, ["sources", "sync", "--help"])
    jobs_result = runner.invoke(app, ["jobs", "sync", "--help"])

    assert sources_result.exit_code == 0
    assert jobs_result.exit_code == 0
    assert "--refresh-cache" in sources_result.output
    assert "--refresh-cache" in jobs_result.output


def test_cli_no_intro_disables_animation(monkeypatch, tmp_path: Path):
    calls = []

    def fake_play_intro(
        *, enabled: bool = True, duration: float = 0.9, fps: float = 12.0
    ):
        calls.append(enabled)

    monkeypatch.setattr(cli_module, "play_intro", fake_play_intro)

    result = invoke(tmp_path, "--no-intro", "admin", "providers", "list", "--json")

    assert result.exit_code == 0
    assert calls == [False]
    assert json.loads(result.output)


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
    assert payload["plugins"]["loaded"] == 0
    assert payload["plugins"]["failed"] == 0
    assert "sources" in payload["nextAction"]


def test_doctor_json_is_parseable_status_output(tmp_path: Path):
    result = invoke(tmp_path, "doctor", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["database"]["counts"]["sources"] == 0
    assert "nextAction" in payload


def test_plugins_list_json_reports_no_plugins_by_default(tmp_path: Path):
    result = invoke(tmp_path, "plugins", "list", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {"plugins": [], "conflicts": [], "loaded": 0, "failed": 0}


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
    assert cache_result.exit_code == 0
    assert json.loads(cache_result.output)["byNamespace"] == {"example-source": 2}


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


def test_stdout_remains_clean_when_intro_callable_runs(monkeypatch, tmp_path: Path):
    def fake_play_intro(
        *, enabled: bool = True, duration: float = 0.9, fps: float = 12.0
    ):
        sys.stderr.write("INTRO_SENTINEL")

    monkeypatch.setattr(cli_module, "play_intro", fake_play_intro)

    result = invoke(tmp_path, "admin", "providers", "list", "--json")

    assert result.exit_code == 0
    assert "INTRO_SENTINEL" not in result.stdout
    assert json.loads(result.stdout)


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
    assert '"routeCount": 1' in result.output
    assert '"requestKey": "lever:token:acme"' in result.output


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
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme",
                raw_payload={"website": {"url": "https://acme.com"}},
            )
        ]
    )

    dry_run = invoke(tmp_path, "boards", "enrich", "--json")
    applied = invoke(tmp_path, "boards", "enrich", "--apply", "--json")
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


def test_sources_show_prefers_persisted_default_key_override(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(
            key="a16z",
            url="https://custom.example/companies",
            provider_id="consider",
            enabled=False,
        )
    )

    result = invoke(tmp_path, "sources", "show", "a16z")

    assert result.exit_code == 0
    row = json.loads(result.output)
    assert row["url"] == "https://custom.example/companies"
    assert row["provider_id"] == "consider"
    assert row["enabled"] is False


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
    assert '"routeCount": 0' in result.output


def test_cli_detects_ashby_hosted_board_url(tmp_path: Path):
    result = invoke(
        tmp_path, "admin", "providers", "detect", "https://jobs.ashbyhq.com/acme"
    )

    assert result.exit_code == 0
    assert '"provider_id": "ashbyhq"' in result.output
    assert '"token": "acme"' in result.output


def test_probe_script_accepts_ashby_provider(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "probe_provider_routes.py"),
            "--provider",
            "ashbyhq",
            "--limit",
            "1",
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert '"checked": 0' in result.stdout
