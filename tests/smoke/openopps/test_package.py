from __future__ import annotations

import json
from pathlib import Path

from typer import Typer
from typer.testing import CliRunner

import openopps
from openopps.cli import app


runner = CliRunner()


def test_openopps_package_imports():
    assert openopps.__version__


def test_cli_entrypoint_imports():
    assert isinstance(app, Typer)
    assert app.registered_commands


def test_status_help_exits_zero():
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "database" in result.output.lower() or "local" in result.output.lower()


def test_status_json_with_empty_tmp_db(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    result = runner.invoke(app, ["status", "--json"], env={"OPENOPPS_DB_URL": db_url})
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "database" in payload
    assert payload["database"]["counts"]["sources"] == 0


def test_doctor_invokes_successfully(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    result = runner.invoke(app, ["doctor", "--json"], env={"OPENOPPS_DB_URL": db_url})
    assert result.exit_code == 0
    assert json.loads(result.output)


def test_plugins_list_json(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'openopps.db'}"
    result = runner.invoke(
        app, ["plugins", "list", "--json"], env={"OPENOPPS_DB_URL": db_url}
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["loaded"] >= 0
    assert "plugins" in payload


def test_admin_db_init_creates_schema(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    db_url = f"sqlite:///{db_path}"
    result = runner.invoke(
        app, ["admin", "db", "init"], env={"OPENOPPS_DB_URL": db_url}
    )
    assert result.exit_code == 0
    assert "initialized" in result.output.lower()
    assert db_path.exists()