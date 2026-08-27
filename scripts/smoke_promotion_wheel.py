#!/usr/bin/env python3
"""Read B699 promotion artifacts from the newest local wheel without live Workers."""

from __future__ import annotations

import sys
import tempfile
import venv
from pathlib import Path


def main() -> int:
    wheel_dir = Path("/tmp/openopps-wheels")
    wheels = sorted(wheel_dir.glob("openopps-*.whl"))
    if not wheels:
        print(
            "no openopps wheels in /tmp/openopps-wheels; run: "
            "uv build --wheel -o /tmp/openopps-wheels",
            file=sys.stderr,
        )
        return 1
    wheel = wheels[-1]
    with tempfile.TemporaryDirectory(prefix="openopps-promotion-wheel-") as tmp:
        env_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        import subprocess

        subprocess.check_call([str(python), "-m", "pip", "install", "--quiet", str(wheel)])
        code = """
from importlib import resources
import json
root = resources.files('openopps.discovery.data')
envelope = json.loads(root.joinpath('approved_ingestion_selector_envelope.json').read_text(encoding='utf-8'))
receipt = json.loads(root.joinpath('evidence_only_decision_receipt.json').read_text(encoding='utf-8'))
decision = json.loads(root.joinpath('discovery_promotion_policy_decision.json').read_text(encoding='utf-8'))
ledger = root.joinpath('promotion_decision_ledger.jsonl').read_text(encoding='utf-8').splitlines()
catalog = json.loads(resources.files('openopps.providers.sources.data').joinpath('portfolio_source_catalog.json').read_text(encoding='utf-8'))
assert envelope['schemaVersion'] == 1
assert envelope['sourceCount'] == catalog['count'] == 2239
assert envelope['packagedCatalogFingerprint'] == catalog['fingerprint']
assert receipt['grantsAuthority'] is False
assert decision['decisionId'] == 'b699-identity-closure-20260822'
assert 'positivePolicyAxes' not in decision
assert len(ledger) == 2
states = [json.loads(line)['state'] for line in ledger]
assert states == ['reserved', 'applied']
print(envelope['sourceCount'], decision['decisionId'], states)
"""
        subprocess.check_call([str(python), "-c", code])
    print("promotion-wheel-readback ok", wheel.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
