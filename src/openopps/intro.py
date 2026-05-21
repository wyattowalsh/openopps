from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Mapping

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text


INTRO_MESSAGES = (
    "opening opportunity portal",
    "validating workspace",
    "ready",
)


def should_show_intro(console: Console, enabled: bool) -> bool:
    if not enabled:
        return False
    if os.environ.get("OPENOPPS_NO_INTRO"):
        return False
    if os.environ.get("CI"):
        return False
    if _completion_is_running(os.environ):
        return False
    if os.environ.get("TERM", "").lower() in {"", "dumb"}:
        return False
    if not console.is_interactive:
        return False
    return sys.stdout.isatty()


def render_intro_frame(frame_index: int, message: str) -> RenderableType:
    if frame_index < 0:
        frame_index = 0

    return Group(*_portal_lines(frame_index, message))


def play_intro(enabled: bool = True, duration: float = 0.9, fps: float = 12.0) -> None:
    console = Console(stderr=True)
    if not should_show_intro(console, enabled):
        return

    try:
        _play_intro(console=console, duration=duration, fps=fps, sleep=time.sleep)
    except Exception:
        return


def _completion_is_running(env: Mapping[str, str]) -> bool:
    for key, value in env.items():
        normalized_key = key.upper()
        normalized_value = value.lower()
        if normalized_key == "_OPENOPPS_COMPLETE":
            return True
        if normalized_key.startswith("_OPENOPPS") and normalized_key.endswith(
            "COMPLETE"
        ):
            return True
        if normalized_key.endswith("_COMPLETE") and (
            "complete" in normalized_value or "source" in normalized_value
        ):
            return True
    return False


def _play_intro(
    *,
    console: Console,
    duration: float,
    fps: float,
    sleep: Callable[[float], None],
) -> None:
    frame_count = max(3, round(duration * fps))
    interval = duration / frame_count
    messages = _intro_messages(frame_count)

    with Live(
        render_intro_frame(0, messages[0]),
        console=console,
        refresh_per_second=fps,
        transient=True,
        screen=False,
        redirect_stdout=False,
        redirect_stderr=False,
    ) as live:
        for frame_index, message in enumerate(messages):
            live.update(render_intro_frame(frame_index, message))
            sleep(interval)


def _intro_messages(frame_count: int) -> list[str]:
    ready_start = max(1, frame_count - 2)
    validate_start = max(1, frame_count // 2)
    messages = []
    for index in range(frame_count):
        if index >= ready_start:
            messages.append(INTRO_MESSAGES[2])
        elif index >= validate_start:
            messages.append(INTRO_MESSAGES[1])
        else:
            messages.append(INTRO_MESSAGES[0])
    return messages


def _portal_lines(frame_index: int, message: str) -> list[Text]:
    phase = frame_index % 11
    glow = _glow_chars(phase)
    check = "✓" if frame_index >= 8 else " "
    check_style = "bold #fff7cc" if frame_index >= 9 else "#fbbf24"

    lines = [
        _styled_line("            ╭──────────────╮", "#172554"),
        _styled_line("         ╭──╯              ╰──╮", "#1e3a8a"),
        _styled_line("       ╭─╯   ╭──────────╮     ╰─╮", "#1e3a8a"),
        _door_line(
            f"      ╭╯    ╭╯  {glow[0]}{glow[1]}{glow[2]}{glow[1]}{glow[0]}   ╰╮      ╰╮",
            phase,
            12,
        ),
        _door_line("      │     │   ╭────╮   │       │╲", phase, 16),
        _door_line("      │     │   │╲   │   │       │ ╲", phase, 18),
        _door_line(
            f"      │     │   │ ╲__│   │   {check}   │  │", phase, 20, check_style
        ),
        _door_line("      │     │      ▲     │       │  │", phase, 22),
        _door_line("      │     │     ╱│╲    │       │  │  ●", phase, 24),
        _door_line("      ╰╮    ╰────╱─│─╲───╯     ╭╯ ╭╯", phase, 26),
        _styled_line("       ╰──╮       ═╧═       ╭──╯ ╭╯", "#1e3a8a"),
        _styled_line("          ╰════════════════╯", "bold #172554"),
        _wordmark_line(),
        _caption_line(message),
    ]
    return lines


def _glow_chars(phase: int) -> tuple[str, str, str]:
    if phase in {3, 4, 5, 6, 7}:
        return ("▒", "▓", "█")
    if phase in {8, 9, 10}:
        return ("░", "▒", "▓")
    return (" ", "░", "▒")


def _styled_line(value: str, style: str) -> Text:
    return Text(value, style=style)


def _door_line(
    value: str, phase: int, shimmer_column: int, check_style: str | None = None
) -> Text:
    text = Text(value, style="#172554")
    _style_portal_parts(text, value)
    _style_door_parts(text, value)
    _style_gold_parts(text, value)
    _style_light_sweep(text, value, phase, shimmer_column)
    if "✓" in value:
        text.stylize(
            check_style or "bold #fde68a", value.index("✓"), value.index("✓") + 1
        )
    return text


def _style_portal_parts(text: Text, value: str) -> None:
    for char in "╭╮╯╰─│═":
        start = 0
        while True:
            index = value.find(char, start)
            if index == -1:
                break
            text.stylize("bold #1e3a8a", index, index + 1)
            start = index + 1


def _style_door_parts(text: Text, value: str) -> None:
    for char in "╲╱●":
        start = 0
        while True:
            index = value.find(char, start)
            if index == -1:
                break
            style = "bold #38bdf8" if char != "●" else "bold #fbbf24"
            text.stylize(style, index, index + 1)
            start = index + 1


def _style_gold_parts(text: Text, value: str) -> None:
    for char in "░▒▓█▲╧":
        start = 0
        while True:
            index = value.find(char, start)
            if index == -1:
                break
            text.stylize("#fbbf24", index, index + 1)
            start = index + 1


def _style_light_sweep(text: Text, value: str, phase: int, shimmer_column: int) -> None:
    if phase not in {3, 4, 5, 6, 7}:
        return
    column = shimmer_column + (phase - 3)
    if 0 <= column < len(value) and value[column] != " ":
        text.stylize("bold #fff7cc", column, column + 1)
    if 0 <= column + 1 < len(value) and value[column + 1] != " ":
        text.stylize("bold #fde68a", column + 1, column + 2)


def _wordmark_line() -> Text:
    text = Text("                ")
    text.append("Open", style="bold #fff7cc")
    text.append("Opps", style="bold #fbbf24")
    return text


def _caption_line(message: str) -> Text:
    text = Text("         ")
    text.append(message, style="#94a3b8")
    return text
