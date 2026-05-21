from __future__ import annotations

import io

from rich.console import Console

from openopps.intro import (
    _completion_is_running,
    _play_intro,
    render_intro_frame,
    should_show_intro,
)


def test_should_show_intro_false_when_disabled() -> None:
    console = Console(file=io.StringIO(), force_terminal=False)

    assert should_show_intro(console, enabled=False) is False


def test_should_show_intro_false_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "1")
    console = Console(file=io.StringIO(), force_terminal=True)

    assert should_show_intro(console, enabled=True) is False


def test_should_show_intro_false_when_env_disables(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("OPENOPPS_NO_INTRO", "1")
    console = Console(file=io.StringIO(), force_terminal=True)

    assert should_show_intro(console, enabled=True) is False


def test_should_show_intro_false_when_term_dumb(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    console = Console(file=io.StringIO(), force_terminal=True)

    assert should_show_intro(console, enabled=True) is False


def test_should_show_intro_false_for_non_interactive_console(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    console = Console(file=io.StringIO(), force_terminal=False)

    assert should_show_intro(console, enabled=True) is False


def test_completion_env_is_detected() -> None:
    assert _completion_is_running({"_OPENOPPS_COMPLETE": "bash_complete"}) is True
    assert _completion_is_running({"_FOO_COMPLETE": "zsh_source"}) is True
    assert _completion_is_running({"PATH": "/bin"}) is False


def test_render_intro_frame_returns_renderable() -> None:
    frame = render_intro_frame(0, "opening opportunity portal")
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=80)

    console.print(frame)

    assert "OpenOpps" in buffer.getvalue()


def test_render_intro_frame_contains_icon_motifs() -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=80)

    console.print(render_intro_frame(10, "ready"))
    rendered = buffer.getvalue()

    assert "╭" in rendered
    assert "╲" in rendered
    assert "▲" in rendered
    assert "✓" in rendered
    assert "OpenOpps" in rendered


def test_internal_play_intro_uses_injected_sleep_without_real_delay() -> None:
    sleeps: list[float] = []
    console = Console(file=io.StringIO(), force_terminal=True, width=80)

    _play_intro(console=console, duration=0.3, fps=10.0, sleep=sleeps.append)

    assert len(sleeps) == 3
    assert all(duration > 0 for duration in sleeps)
