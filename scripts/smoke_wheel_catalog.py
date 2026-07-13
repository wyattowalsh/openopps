#!/usr/bin/env python3
"""Install the newest local wheel into a temp env and read packaged catalog JSON."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> int:
    wheel_dir = Path("/tmp/openopps-wheels")
    wheels = sorted(wheel_dir.glob("openopps-*.whl"))
    if not wheels:
        print("no openopps wheels in /tmp/openopps-wheels; run: uv build --wheel -o /tmp/openopps-wheels", file=sys.stderr)
        return 1
    wheel = wheels[-1]
    with tempfile.TemporaryDirectory(prefix="openopps-wheel-smoke-") as tmp:
        env_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.check_call([str(python), "-m", "pip", "install", "--quiet", str(wheel)])
        code = (
            "from importlib import resources; "
            "import json; "
            "text = resources.files('openopps.providers.sources.data')"
            ".joinpath('portfolio_source_catalog.json').read_text(encoding='utf-8'); "
            "payload = json.loads(text); "
            "assert isinstance(payload.get('version'), int) and payload['version'] >= 2; "
            "assert isinstance(payload.get('count'), int) and payload['count'] > 0; "
            "assert isinstance(payload.get('fingerprint'), str) and payload['fingerprint']; "
            "print(payload['version'], payload['count'], payload['fingerprint'][:12])"
        )
        subprocess.check_call([str(python), "-c", code])
    print("wheel-catalog-smoke ok", wheel.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())