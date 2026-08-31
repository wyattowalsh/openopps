#!/usr/bin/env python3
"""Canonical offline source-discovery gates for Just recipes and public CI.

Every subcommand is read-only with respect to Git remotes, operational SQLite,
Kaggle, Cloudflare, and the promotion lock. Scout replay writes only an explicit
temporary quarantine directory. Live network access is refused.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import pkgutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "discovery"
CORPUS_PATH = FIXTURE_ROOT / "benchmark" / "corpus.json"
SCHEMA_SCRIPT = REPO_ROOT / "scripts" / "generate_discovery_schemas.py"
FIXTURE_SCRIPT = REPO_ROOT / "scripts" / "generate_discovery_fixtures.py"
SKILL_SCRIPTS = (
    REPO_ROOT
    / "agent-plugins"
    / "openopps.dev"
    / "skills"
    / "openopps-source-scout"
    / "scripts"
    / "validate_evals.py",
    REPO_ROOT
    / "agent-plugins"
    / "openopps.dev"
    / "skills"
    / "openopps-source-scout"
    / "scripts"
    / "validate_frontmatter.py",
    REPO_ROOT
    / "agent-plugins"
    / "openopps.dev"
    / "skills"
    / "openopps-source-scout"
    / "scripts"
    / "dry_run_projection.py",
    REPO_ROOT
    / "agent-plugins"
    / "openopps.dev"
    / "skills"
    / "openopps-source-scout"
    / "scripts"
    / "resolve_docs_steward.py",
)
FRESHNESS_DIGEST = "0" * 64
CI_GATES = (
    "schema",
    "fixtures",
    "replay-bundle",
    "promotion-preview",
    "private-envelope",
    "accounting",
    "skill-eval",
    "benchmark",
)


class GateError(RuntimeError):
    """A discovery gate failed without mutating shared surfaces."""


def _require_offline() -> None:
    network = os.environ.get("OPENOPPS_DISCOVERY_NETWORK", "disabled")
    if network != "disabled":
        raise GateError(
            "discovery gates require OPENOPPS_DISCOVERY_NETWORK=disabled"
        )


def _emit(payload: dict[str, object], *, ok: bool) -> int:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    sys.stdout.write("\n")
    return 0 if ok else 1


def _run_python_script(script: Path, args: list[str] | None = None) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(script), *(args or [])],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout or ""
    payload: object
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout": stdout.strip()}
    if completed.returncode != 0:
        detail = (completed.stderr or stdout).strip()
        raise GateError(
            f"{script.relative_to(REPO_ROOT)} failed"
            + (f": {detail}" if detail else "")
        )
    if not isinstance(payload, dict):
        raise GateError(f"{script.relative_to(REPO_ROOT)} did not emit a JSON object")
    return {
        "ok": True,
        "returncode": completed.returncode,
        "script": str(script.relative_to(REPO_ROOT)),
        "result": payload,
    }


def gate_schema() -> dict[str, object]:
    from openopps.discovery.api import assure_discovery_schemas

    delegated = _run_python_script(SCHEMA_SCRIPT, ["--check"])
    assure_discovery_schemas()
    return {
        "gate": "schema",
        "library": "openopps.discovery.api.assure_discovery_schemas",
        **delegated,
    }


def gate_fixtures() -> dict[str, object]:
    delegated = _run_python_script(FIXTURE_SCRIPT, ["--check"])
    result = delegated["result"]
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise GateError("sanitized fixture tree drifted from the generator")
    return {
        "gate": "fixtures",
        "library": "scripts/generate_discovery_fixtures.py",
        "network": "disabled",
        **delegated,
    }


def gate_manifest(manifest: Path) -> dict[str, object]:
    from openopps.discovery.api import verify_scout_manifest_path

    payload = verify_scout_manifest_path(manifest)
    return {
        "activated": False,
        "gate": "manifest",
        "library": "openopps.discovery.api.verify_scout_manifest_path",
        "ok": True,
        "promoted": False,
        "result": payload,
        "rewritten": False,
    }


def _symlink_free_tempdir(prefix: str) -> tempfile.TemporaryDirectory[str]:
    # Bundle writes walk from / with O_NOFOLLOW, so macOS /var -> /private/var
    # tempfile roots are unsafe until resolved to the real directory.
    return tempfile.TemporaryDirectory(
        prefix=prefix,
        dir=str(Path(tempfile.gettempdir()).resolve()),
    )


def gate_replay_bundle() -> dict[str, object]:
    from openopps.discovery.api import (
        ScoutCommandError,
        run_offline_quarantine_scout,
        verify_scout_manifest_path,
    )

    try:
        with _symlink_free_tempdir("openopps-discovery-replay-") as tmp:
            output = Path(tmp).resolve() / "quarantine"
            scouted = run_offline_quarantine_scout(
                output,
                repository_root=REPO_ROOT,
            )
            manifest = Path(str(scouted["manifestPath"]))
            verified = verify_scout_manifest_path(manifest)
    except ScoutCommandError as error:
        raise GateError(f"replay-bundle failed: {error}") from error
    return {
        "activated": False,
        "gate": "replay-bundle",
        "library": "openopps.discovery.api.run_offline_quarantine_scout",
        "ok": True,
        "promoted": False,
        "scout": {
            "eligibleForReview": scouted["eligibleForReview"],
            "manifestId": scouted["manifestId"],
            "status": scouted["status"],
        },
        "verified": {
            "manifestId": verified.get("manifestId"),
            "status": verified.get("status"),
        },
    }


def gate_promotion_preview(manifest: Path | None) -> dict[str, object]:
    from openopps.discovery.api import preview_repository_promotion

    payload = preview_repository_promotion(REPO_ROOT, manifest=manifest)
    if payload.get("applied") is not False or payload.get("grantsAuthority") is True:
        raise GateError("promotion preview must remain non-applying")
    return {
        "applied": False,
        "gate": "promotion-preview",
        "grantsAuthority": payload.get("grantsAuthority"),
        "identityClosure": payload.get("identityClosure"),
        "library": "openopps.discovery.api.preview_repository_promotion",
        "ok": True,
        "onDiskMatch": payload.get("onDiskMatch"),
        "sourceCount": payload.get("sourceCount"),
        "status": payload.get("status"),
    }


def gate_private_envelope() -> dict[str, object]:
    from openopps.discovery.canonical import decode_canonical_json
    from openopps.discovery.inventory import read_packaged_catalog_bytes
    from openopps.discovery.models import ApprovedIngestionSelectorEnvelope
    from openopps.discovery.promotion import compute_envelope_id
    from openopps.discovery.promotion_runtime import (
        CATALOG_RELATIVE_PATH,
        ENVELOPE_RELATIVE_PATH,
    )

    envelope_bytes = (REPO_ROOT / ENVELOPE_RELATIVE_PATH).read_bytes()
    catalog_bytes = (REPO_ROOT / CATALOG_RELATIVE_PATH).read_bytes()
    payload = decode_canonical_json(envelope_bytes)
    if not isinstance(payload, dict):
        raise GateError("approved-ingestion envelope must be a JSON object")
    try:
        envelope = ApprovedIngestionSelectorEnvelope.model_validate_json(
            envelope_bytes,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except (TypeError, ValueError) as error:
        raise GateError(f"private envelope is invalid: {error}") from error
    recomputed = compute_envelope_id(payload)
    if recomputed != envelope.envelope_id:
        raise GateError("envelopeId does not match canonical payload digest")
    catalog = read_packaged_catalog_bytes(catalog_bytes)
    if envelope.source_count != catalog.count:
        raise GateError("envelope sourceCount does not match packaged catalog count")
    if envelope.packaged_catalog_fingerprint != catalog.fingerprint:
        raise GateError("envelope packagedCatalogFingerprint does not match catalog")
    if "sourceSelector" in payload:
        raise GateError("private envelope must not carry the v7 public SourceSelector")
    return {
        "envelopeId": envelope.envelope_id,
        "gate": "private-envelope",
        "library": "openopps.discovery.models.ApprovedIngestionSelectorEnvelope",
        "ok": True,
        "publicSelector": False,
        "sourceCount": envelope.source_count,
    }


def gate_accounting() -> dict[str, object]:
    from openopps.discovery.accounting import (
        OPERATION_TERMINALS,
        SOURCE_DISPOSITIONS,
        build_route_accounting,
        build_source_accounting,
        classify_typed_degraded,
        validate_operation_conservation,
    )
    from openopps.discovery.canonical import decode_canonical_json
    from openopps.discovery.models import RouteOutcome, SourceOutcome
    from openopps.discovery.promotion_runtime import ENVELOPE_RELATIVE_PATH

    payload = decode_canonical_json((REPO_ROOT / ENVELOPE_RELATIVE_PATH).read_bytes())
    if not isinstance(payload, dict):
        raise GateError("approved-ingestion envelope must be a JSON object")
    keys = payload.get("sourceKeys")
    if not isinstance(keys, list) or not keys:
        raise GateError("envelope sourceKeys must be a non-empty array")
    planned = tuple(str(key) for key in keys)
    outcomes = tuple(
        SourceOutcome(source_id=key, disposition="unstarted", started=False)
        for key in planned
    )
    source = build_source_accounting(
        planned_source_ids=planned,
        outcomes=outcomes,
        run_state="cancelled",
        freshness_context_digest=FRESHNESS_DIGEST,
    )
    route = build_route_accounting(
        planned_route_ids=("scout-evaluation",),
        outcomes=(
            RouteOutcome(
                route_id="scout-evaluation",
                disposition="unstarted",
                started=False,
            ),
        ),
        run_state="cancelled",
        freshness_context_digest=FRESHNESS_DIGEST,
    )
    terminals = {name: 0 for name in OPERATION_TERMINALS}
    terminals["unstarted"] = 1
    validate_operation_conservation(1, terminals)
    completeness, degraded_class = classify_typed_degraded(
        source=source,
        route=route,
        operation_terminals=terminals,
        operation_channel_state="incomplete",
        run_state="cancelled",
    )
    conserved = (
        source.planned
        == sum(getattr(source, name) for name in SOURCE_DISPOSITIONS)
        == len(planned)
    )
    if not conserved or source.complete or completeness != "degraded":
        raise GateError("selector accounting did not conserve unstarted terminals")
    return {
        "complete": False,
        "completeness": completeness,
        "degradedClass": degraded_class,
        "gate": "accounting",
        "library": "openopps.discovery.accounting.build_source_accounting",
        "ok": True,
        "planned": source.planned,
        "unstarted": source.unstarted,
    }


def gate_skill_eval() -> dict[str, object]:
    results = [_run_python_script(script) for script in SKILL_SCRIPTS]
    return {
        "gate": "skill-eval",
        "library": "agent-plugins/openopps.dev/skills/openopps-source-scout/scripts",
        "ok": True,
        "results": results,
    }


def _benchmark_inputs():
    from openopps.discovery.benchmark import BenchmarkInputs
    from openopps.discovery.inventory import (
        DEFAULT_PACKAGED_CATALOG_PATH,
        DEFAULT_V7_POLICY_PATHS,
        read_repository_resources,
    )
    from openopps.models import SourceRecord
    from openopps.providers import sources as source_package
    from openopps.providers.sources import BOARD_SOURCE_ADAPTERS, BOARD_SOURCE_RECORDS

    owner_rows: list[tuple[str, str]] = []
    for module_info in pkgutil.iter_modules(
        source_package.__path__, f"{source_package.__name__}."
    ):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        owner_rows.extend(
            (record.key, module.__name__)
            for record in getattr(module, "SOURCE_RECORDS", ())
            if isinstance(record, SourceRecord)
        )
    adapter_rows = tuple(
        (provider_id, adapter.__module__, adapter.__qualname__)
        for provider_id, adapter in BOARD_SOURCE_ADAPTERS.items()
    )
    resources = read_repository_resources(REPO_ROOT, DEFAULT_V7_POLICY_PATHS)
    return BenchmarkInputs(
        source_records=tuple(BOARD_SOURCE_RECORDS),
        source_owner_rows=tuple(owner_rows),
        adapter_identity_rows=adapter_rows,
        packaged_catalog=(REPO_ROOT / DEFAULT_PACKAGED_CATALOG_PATH).read_bytes(),
        v7_policy_code=resources["policy_code"],
        v7_policy_schema=resources["policy_schema"],
        v7_policy_evidence=resources["policy_evidence"],
        v7_policy_corpus=resources["policy_corpus"],
        public_selector=None,
    )


def gate_benchmark() -> dict[str, object]:
    from openopps.discovery.benchmark import (
        DEFAULT_REPEAT_COUNT,
        assert_receipt_matches_adr,
        load_benchmark_adr,
        load_benchmark_implementation_receipt,
        run_offline_promotion_benchmark,
    )

    report = run_offline_promotion_benchmark(
        corpus_bytes=CORPUS_PATH.read_bytes(),
        inputs=_benchmark_inputs(),
        repeat_count=DEFAULT_REPEAT_COUNT,
    )
    assert_receipt_matches_adr(
        adr=load_benchmark_adr(),
        receipt=load_benchmark_implementation_receipt(),
    )
    if report.http_request_count != 0 or report.sqlite_statement_count != 0:
        raise GateError("benchmark must stay HTTP-free and SQLite-free")
    return {
        "corpusSha256": report.corpus_sha256,
        "gate": "benchmark",
        "httpRequestCount": report.http_request_count,
        "library": "openopps.discovery.benchmark.run_offline_promotion_benchmark",
        "numericRegressionThreshold": None,
        "ok": True,
        "repeatCount": report.repeat_count,
        "sqliteStatementCount": report.sqlite_statement_count,
    }


def gate_ci() -> dict[str, object]:
    results = [DISPATCH[name]() for name in CI_GATES]
    return {"gate": "ci", "gates": list(CI_GATES), "ok": True, "results": results}


def dispatch_manifest() -> dict[str, object]:
    if MANIFEST_PATH is None:
        raise GateError("manifest gate requires --manifest")
    return gate_manifest(MANIFEST_PATH)


def dispatch_preview() -> dict[str, object]:
    return gate_promotion_preview(MANIFEST_PATH)


DISPATCH = {
    "schema": gate_schema,
    "fixtures": gate_fixtures,
    "manifest": dispatch_manifest,
    "replay-bundle": gate_replay_bundle,
    "promotion-preview": dispatch_preview,
    "private-envelope": gate_private_envelope,
    "accounting": gate_accounting,
    "skill-eval": gate_skill_eval,
    "benchmark": gate_benchmark,
    "ci": gate_ci,
}

MANIFEST_PATH: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "gate",
        choices=tuple(DISPATCH),
        help="offline discovery gate to run",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="quarantine manifest path for manifest-check and promotion-preview",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    global MANIFEST_PATH
    args = _parser().parse_args(argv)
    _require_offline()
    MANIFEST_PATH = args.manifest
    try:
        payload = DISPATCH[args.gate]()
    except GateError as error:
        return _emit(
            {"error": str(error), "gate": args.gate, "ok": False},
            ok=False,
        )
    return _emit(payload, ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
