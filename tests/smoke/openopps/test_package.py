from __future__ import annotations

from typer import Typer

from openopps.cli import app


def test_cli_entrypoint_imports():
    assert isinstance(app, Typer)
    assert app.registered_commands
