"""In-process coverage for the isolation worker stdin and argv contract."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.worker import main

MAX_INPUT_BYTES = 16_777_216
MAX_SEED = (1 << 63) - 1
MAX_PROFILE_ID = "a" + "b" * 63
WORKER_ARGV0 = "openopps.discovery.worker"
VALID_ARGV = ["--profile-id", "offline", "--seed", "17"]
CANONICAL_SUGGESTIONS = canonical_json_bytes({"suggestions": []})


def _run(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    stdin: bytes,
) -> tuple[int, bytes]:
    stdout_buffer = io.BytesIO()
    monkeypatch.setattr(sys, "argv", [WORKER_ARGV0, *argv])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(stdin)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=stdout_buffer))
    return main(), stdout_buffer.getvalue()


def test_main_returns_canonical_envelope_for_valid_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, stdout = _run(monkeypatch, VALID_ARGV, CANONICAL_SUGGESTIONS)

    assert code == 0
    assert stdout == canonical_json_bytes(
        {"profileId": "offline", "result": {"suggestions": []}, "seed": 17}
    )
    assert decode_canonical_json(stdout) == {
        "profileId": "offline",
        "result": {"suggestions": []},
        "seed": 17,
    }


@pytest.mark.parametrize(
    ("profile_id", "seed", "result"),
    (
        ("a", 0, {}),
        ("offline-v1_test", MAX_SEED, {"ok": True, "items": [1, None]}),
        (MAX_PROFILE_ID, 1, {"nested": {"k": "v"}}),
    ),
)
def test_main_echoes_profile_result_and_seed_in_canonical_envelope(
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
    seed: int,
    result: object,
) -> None:
    stdin = canonical_json_bytes(result)
    argv = ["--profile-id", profile_id, "--seed", str(seed)]

    code, stdout = _run(monkeypatch, argv, stdin)

    assert code == 0
    assert stdout == canonical_json_bytes(
        {"profileId": profile_id, "result": result, "seed": seed}
    )


@pytest.mark.parametrize(
    "argv",
    (
        pytest.param([], id="empty-argv"),
        pytest.param(["--profile-id", "offline"], id="missing-seed"),
        pytest.param(["--seed", "17"], id="missing-profile"),
        pytest.param(
            ["--seed", "17", "--profile-id", "offline"],
            id="swapped-flags",
        ),
        pytest.param(
            ["--profile-id", "offline", "--seed", "17", "extra"],
            id="extra-argument",
        ),
        pytest.param(
            ["--profile-id", "offline", "--seed"],
            id="seed-flag-without-value",
        ),
        pytest.param(
            ["profile-id", "offline", "--seed", "17"],
            id="profile-flag-missing-dashes",
        ),
        pytest.param(
            ["--profile-id", "offline", "--seed-value", "17"],
            id="wrong-seed-flag",
        ),
    ),
)
def test_main_rejects_bad_argv(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    code, stdout = _run(monkeypatch, argv, CANONICAL_SUGGESTIONS)

    assert code == 2
    assert stdout == b""


@pytest.mark.parametrize(
    "profile_id",
    (
        pytest.param("", id="empty"),
        pytest.param("Offline", id="uppercase"),
        pytest.param("1offline", id="leading-digit"),
        pytest.param("-offline", id="leading-hyphen"),
        pytest.param("_offline", id="leading-underscore"),
        pytest.param("off.line", id="dot"),
        pytest.param("off line", id="space"),
        pytest.param("off/line", id="slash"),
        pytest.param("a" + "b" * 64, id="too-long"),
        pytest.param("é", id="non-ascii"),
    ),
)
def test_main_rejects_bad_profile_id(
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
) -> None:
    argv = ["--profile-id", profile_id, "--seed", "17"]
    code, stdout = _run(monkeypatch, argv, CANONICAL_SUGGESTIONS)

    assert code == 2
    assert stdout == b""


@pytest.mark.parametrize(
    "seed_text",
    (
        pytest.param("", id="empty"),
        pytest.param("01", id="leading-zero"),
        pytest.param("00", id="double-zero"),
        pytest.param("-1", id="negative"),
        pytest.param("+1", id="plus-prefix"),
        pytest.param("1.0", id="decimal-point"),
        pytest.param("1e2", id="scientific"),
        pytest.param("1a", id="trailing-letter"),
        pytest.param(" 17", id="leading-space"),
        pytest.param("17 ", id="trailing-space"),
        pytest.param("1_7", id="underscore"),
        pytest.param("0x11", id="hex"),
        pytest.param("١", id="non-ascii-decimal"),
        pytest.param(str(MAX_SEED + 1), id="above-int64-max"),
    ),
)
def test_main_rejects_non_decimal_leading_zero_and_oversize_seed(
    monkeypatch: pytest.MonkeyPatch,
    seed_text: str,
) -> None:
    argv = ["--profile-id", "offline", "--seed", seed_text]
    code, stdout = _run(monkeypatch, argv, CANONICAL_SUGGESTIONS)

    assert code == 2
    assert stdout == b""


def test_main_rejects_oversize_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    code, stdout = _run(
        monkeypatch,
        VALID_ARGV,
        bytes(MAX_INPUT_BYTES + 1),
    )

    assert code == 2
    assert stdout == b""


@pytest.mark.parametrize(
    "stdin",
    (
        pytest.param(b"", id="empty"),
        pytest.param(b"{not json", id="invalid-json"),
        pytest.param(b"[]", id="missing-trailing-lf"),
        pytest.param(b"{}\n\n", id="extra-trailing-lf"),
        pytest.param(b"{ }\n", id="non-canonical-whitespace"),
        pytest.param(b'{"b":1,"a":2}\n', id="unsorted-keys"),
        pytest.param(b"1.5\n", id="float"),
        pytest.param(b"\xef\xbb\xbf{}\n", id="utf8-bom"),
        pytest.param(b'{"a":1,"a":2}\n', id="duplicate-keys"),
    ),
)
def test_main_rejects_invalid_and_noncanonical_json(
    monkeypatch: pytest.MonkeyPatch,
    stdin: bytes,
) -> None:
    code, stdout = _run(monkeypatch, VALID_ARGV, stdin)

    assert code == 2
    assert stdout == b""
