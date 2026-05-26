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
    "tracing public routes",
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


def play_intro(enabled: bool = True, duration: float = 0.72, fps: float = 10.0) -> None:
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
    safe_duration = max(0.1, duration)
    safe_fps = max(1.0, fps)
    frame_count = max(3, round(safe_duration * safe_fps))
    interval = safe_duration / frame_count
    messages = _intro_messages(frame_count)

    with Live(
        render_intro_frame(0, messages[0]),
        console=console,
        refresh_per_second=safe_fps,
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
    phase = frame_index % 8
    glow = _glow_chars(phase)
    check = "✓" if frame_index >= 5 else "·"

    return [
        _portal_line("          ╭──────────────╮", phase, 10),
        _portal_line(
            f"      ╭───╯   {glow[0]}{glow[1]}{glow[2]}{glow[1]}   ╰───╮", phase, 14
        ),
        _portal_line("     ╱    ╭────────╮      ╲", phase, 18),
        _portal_line(f"    │     │   ▲    │   {check}   │", phase, 20),
        _portal_line("     ╲    ╰───╥────╯      ╱", phase, 22),
        _portal_line("      ╰───────╨──────────╯", phase, 24),
        _wordmark_line(),
        _caption_line(message),
    ]


def _glow_chars(phase: int) -> tuple[str, str, str]:
    if phase in {2, 3, 4}:
        return ("▒", "▓", "█")
    if phase in {5, 6, 7}:
        return ("░", "▒", "▓")
    return (" ", "░", "▒")


def _portal_line(value: str, phase: int, shimmer_column: int) -> Text:
    text = Text(value, style="#172554")
    _style_chars(text, value, "╭╮╯╰─│", "bold #1e3a8a")
    _style_chars(text, value, "╲╱", "bold #38bdf8")
    _style_chars(text, value, "░▒▓█▲╥╨", "#fbbf24")
    _style_light_sweep(text, value, phase, shimmer_column)
    if "✓" in value:
        text.stylize("bold #fff7cc", value.index("✓"), value.index("✓") + 1)
    return text


def _style_chars(text: Text, value: str, chars: str, style: str) -> None:
    for char in chars:
        start = 0
        while True:
            index = value.find(char, start)
            if index == -1:
                break
            text.stylize(style, index, index + 1)
            start = index + 1


def _style_light_sweep(text: Text, value: str, phase: int, shimmer_column: int) -> None:
    if phase not in {2, 3, 4, 5}:
        return
    column = shimmer_column + (phase - 2)
    if 0 <= column < len(value) and value[column] != " ":
        text.stylize("bold #fff7cc", column, column + 1)
    if 0 <= column + 1 < len(value) and value[column + 1] != " ":
        text.stylize("bold #fde68a", column + 1, column + 2)


def _wordmark_line() -> Text:
    text = Text("              ")
    text.append("Open", style="bold #fff7cc")
    text.append("Opps", style="bold #fbbf24")
    return text


def _caption_line(message: str) -> Text:
    text = Text("       ")
    text.append(message, style="#94a3b8")
    return text
