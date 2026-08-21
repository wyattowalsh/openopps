"""Fixed data-only worker used by the discovery isolation boundary."""

from __future__ import annotations

import re
import sys

from openopps.discovery.canonical import (
    CanonicalJSONError,
    canonical_json_bytes,
    decode_canonical_json,
)


_MAX_INPUT_BYTES = 16_777_216
_MAX_SEED = (1 << 63) - 1
_PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _trusted_arguments(argv: list[str]) -> tuple[str, int]:
    if len(argv) != 4 or argv[0] != "--profile-id" or argv[2] != "--seed":
        raise ValueError
    profile_id = argv[1]
    seed_text = argv[3]
    if not _PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError
    if not seed_text.isascii() or not seed_text.isdecimal():
        raise ValueError
    seed = int(seed_text)
    if not 0 <= seed <= _MAX_SEED or str(seed) != seed_text:
        raise ValueError
    return profile_id, seed


def main() -> int:
    """Validate canonical stdin and return one closed canonical envelope."""

    try:
        profile_id, seed = _trusted_arguments(sys.argv[1:])
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if len(raw) > _MAX_INPUT_BYTES:
            return 2
        result = decode_canonical_json(raw)
        output = canonical_json_bytes(
            {"profileId": profile_id, "result": result, "seed": seed}
        )
    except (CanonicalJSONError, TypeError, ValueError):
        return 2
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a fresh process
    raise SystemExit(main())
