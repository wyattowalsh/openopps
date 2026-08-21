from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlparse
from xml.etree import ElementTree

import pytest

from generate_discovery_fixtures import (
    ROBOTS_RFC_MINIMUM_BYTES,
    build_fixture_tree,
    check_fixture_tree,
    read_fixture_tree,
    write_fixture_tree,
)
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.isolation import IsolationError, validate_data_only_suggestion
from openopps.discovery.secrets import admit_scanned_content
from openopps.discovery.transport import bounded_retry_delay_ms
from openopps.providers.sources import BOARD_SOURCE_CATALOG, BOARD_SOURCE_RECORDS


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "discovery"
GENERATOR = ROOT / "scripts" / "generate_discovery_fixtures.py"
DISCOVERY_PACKAGE = ROOT / "src" / "openopps" / "discovery"
OPERATIONAL_DATA_PATHS = (
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "portfolio_source_catalog.json",
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "source_policy_evidence.json",
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "source_policy_evidence.schema.json",
    ROOT / "web" / "lib" / "generated" / "openopps-data.json",
)
FORBIDDEN_DISCOVERY_IMPORTS = (
    "openopps.cache",
    "openopps.cli",
    "openopps.ingest",
    "openopps.plugins",
    "openopps.providers",
    "openopps.storage",
)
URL_PATTERN = re.compile(rb"https://[^\s\"'<>]+")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture_json(relative: str) -> object:
    return decode_canonical_json((FIXTURE_ROOT / relative).read_bytes())


def _operational_snapshot() -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(ROOT).as_posix(): (
            path.stat().st_size,
            _sha256(path.read_bytes()),
        )
        for path in OPERATIONAL_DATA_PATHS
    }


def _catalog_snapshot() -> tuple[tuple[str, int, str, str], ...]:
    return tuple(
        (key, id(record), record.provider_id, record.url)
        for key, record in sorted(BOARD_SOURCE_CATALOG.items())
    )


# T133/T136: the committed tree is an exact digest-closed set of bounded fixtures.
def test_fixture_manifest_closes_the_exact_canonical_tree() -> None:
    tree = read_fixture_tree(FIXTURE_ROOT)
    manifest = _fixture_json("manifest.json")
    assert isinstance(manifest, dict)
    members = manifest["members"]
    assert isinstance(members, list)

    expected_paths = {member["path"] for member in members}
    assert set(tree) == {*expected_paths, "manifest.json"}
    assert manifest["memberCount"] == len(members)
    assert manifest["fixtureSetSha256"] == _sha256(canonical_json_bytes(members))
    assert manifest["numericRegressionThreshold"] is None
    assert manifest["environment"] == {
        "ambientEnvironment": "ignored",
        "clock": "not-read",
        "filesystemInput": "tracked-runtime-inventory-only",
        "locale": "UTF-8",
        "network": "disabled",
        "python": "CPython >=3.12",
        "timezone": "UTC",
    }
    assert manifest["generator"]["sha256"] == _sha256(GENERATOR.read_bytes())

    for member in members:
        path = member["path"]
        content = tree[path]
        assert member["sizeBytes"] == len(content)
        assert member["sha256"] == _sha256(content)
        assert not path.startswith(("/", "../"))
        assert "\\" not in path
        if (
            member["mediaType"] == "application/json"
            and path != "parser/malformed.json"
        ):
            assert canonical_json_bytes(decode_canonical_json(content)) == content


def test_robots_sitemap_conditional_and_parser_fixtures_are_bounded() -> None:
    robots = _fixture_json("robots/scenarios.json")
    assert isinstance(robots, dict)
    scenarios = {item["id"]: item for item in robots["scenarios"]}
    assert set(scenarios) == {
        "cross-origin-redirect-rejected",
        "fresh-cache",
        "rfc-minimum-500-kib",
        "stale-cache-unreachable",
        "success-allow",
        "success-disallow",
        "unavailable-404",
        "unreachable-503",
        "unreachable-network",
    }
    assert robots["cacheMaximumAgeSeconds"] == 86_400
    assert (FIXTURE_ROOT / "robots" / "maximum-500-kib.txt").stat().st_size == (
        ROBOTS_RFC_MINIMUM_BYTES
    )
    assert scenarios["unavailable-404"]["expectedAccess"] == "allowed"
    for identifier in (
        "cross-origin-redirect-rejected",
        "stale-cache-unreachable",
        "unreachable-503",
        "unreachable-network",
    ):
        assert scenarios[identifier]["expectedAccess"] == "blocked"
    assert scenarios["fresh-cache"]["expectedReuse"] is True
    assert scenarios["stale-cache-unreachable"]["expectedReuse"] is False

    sitemap = _fixture_json("sitemap/scenarios.json")
    assert isinstance(sitemap, dict)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for scenario in sitemap["scenarios"]:
        root = ElementTree.fromstring(
            (FIXTURE_ROOT / scenario["inputPath"]).read_bytes()
        )
        locations = [element.text for element in root.findall(".//sm:loc", namespace)]
        lastmods = [
            element.text for element in root.findall(".//sm:lastmod", namespace)
        ]
        assert len(locations) == scenario["expectedEntries"] <= sitemap["entryLimit"]
        assert all(location is not None for location in locations)
        if scenario["expectedOutcome"] == "accepted":
            assert {
                urlparse(location).hostname for location in locations if location
            } == {scenario["expectedHost"]}
            assert scenario["expectedLastmod"] in lastmods
        else:
            assert any(
                urlparse(location).hostname != scenario["expectedHost"]
                for location in locations
                if location
            )

    http_fixture = _fixture_json("http/conditional-and-rate-limit.json")
    assert isinstance(http_fixture, dict)
    conditional = http_fixture["conditional"]
    assert conditional["requestHeaders"] == {
        "ifModifiedSince": conditional["observed"]["lastModified"],
        "ifNoneMatch": conditional["observed"]["etag"],
    }
    delta = next(
        item for item in http_fixture["rateLimit"] if item["id"] == "delta-seconds"
    )
    assert (
        bounded_retry_delay_ms(
            delta["retryAfter"],
            now_ms=0,
            deadline_ms=60_000,
            max_delay_ms=delta["maximumDelayMilliseconds"],
        )
        == delta["expectedDelayMilliseconds"]
    )
    assert any(item["id"] == "http-date" for item in http_fixture["rateLimit"])
    assert any(
        item["expectedOutcome"] == "rejected-over-trusted-bound"
        for item in http_fixture["rateLimit"]
        if "expectedOutcome" in item
    )

    parser_fixture = _fixture_json("parser/scenarios.json")
    assert isinstance(parser_fixture, dict)
    outcomes = {
        item["id"]: item["expectedOutcome"] for item in parser_fixture["scenarios"]
    }
    assert outcomes == {
        "bounded-html": "accepted",
        "bounded-json": "accepted",
        "malformed-json": "rejected-malformed",
        "xml-dtd": "rejected-dtd",
    }


# T134/T132: suggestions stay data-only and cannot activate the runtime catalog.
def test_skill_fixtures_are_data_only_and_have_no_same_run_activation_path() -> None:
    skill = _fixture_json("skill/scenarios.json")
    assert isinstance(skill, dict)
    admitted_resources = frozenset(skill["admittedResourceIds"])
    admitted_parsers = frozenset(skill["admittedParserIds"])
    admitted_providers = frozenset(skill["admittedProviderIds"])
    catalog_before = _catalog_snapshot()

    for scenario in skill["scenarios"]:
        payload = _fixture_json(scenario["inputPath"])
        if scenario.get("expectedOutcome") == "accepted-data-only":
            accepted = validate_data_only_suggestion(
                payload,
                admitted_resource_ids=admitted_resources,
                allowed_parser_ids=admitted_parsers,
                allowed_provider_ids=admitted_providers,
            )
            assert dict(accepted) == payload
            with pytest.raises(TypeError):
                accepted["providerId"] = "replacement"  # type: ignore[index]
        else:
            with pytest.raises(IsolationError) as caught:
                validate_data_only_suggestion(
                    payload,
                    admitted_resource_ids=admitted_resources,
                    allowed_parser_ids=admitted_parsers,
                    allowed_provider_ids=admitted_providers,
                )
            assert caught.value.reason_code == scenario["expectedReason"]

    assert _catalog_snapshot() == catalog_before
    good = _fixture_json("skill/known-good.json")
    assert isinstance(good, dict)
    assert good["candidateLocator"] not in {
        record.url for record in BOARD_SOURCE_CATALOG.values()
    }
    import openopps.discovery as discovery

    assert discovery.__all__ == ()


# T131: importing/validating discovery contracts cannot reach operational modules.
def test_discovery_contract_import_graph_is_operationally_neutral() -> None:
    module_names = [
        f"openopps.discovery.{path.stem}"
        for path in sorted(DISCOVERY_PACKAGE.glob("*.py"))
        if path.name != "__init__.py"
    ]
    for path in sorted(DISCOVERY_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        assert not {
            name for name in imported if name.startswith(FORBIDDEN_DISCOVERY_IMPORTS)
        }, path.name

    program = (
        "import importlib,json,sys\n"
        f"modules={module_names!r}\n"
        "before=set(sys.modules)\n"
        "for name in modules: importlib.import_module(name)\n"
        "loaded=sorted(set(sys.modules)-before)\n"
        "print(json.dumps(loaded))\n"
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-I", "-c", program],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)
    assert not {name for name in loaded if name.startswith(FORBIDDEN_DISCOVERY_IMPORTS)}


# T131/T137: offline regeneration performs no operational or ambient-data writes.
def test_regeneration_is_byte_identical_secret_free_and_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operational_before = _operational_snapshot()
    catalog_before = _catalog_snapshot()
    connection_attempts: list[tuple[object, ...]] = []

    def reject_sqlite(*args: object, **kwargs: object) -> object:
        connection_attempts.append((*args, kwargs))
        raise AssertionError("fixture generation must not open SQLite")

    ambient_canary = "ambient-fixture-canary-value-must-not-appear"
    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setenv("OPENOPPS_DISCOVERY_FIXTURE_CANARY", ambient_canary)

    first_built = build_fixture_tree()
    second_built = build_fixture_tree()
    assert first_built == second_built
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    write_fixture_tree(first_root)
    write_fixture_tree(second_root)
    assert read_fixture_tree(first_root) == read_fixture_tree(second_root)
    assert read_fixture_tree(first_root) == first_built
    valid, differences = check_fixture_tree(FIXTURE_ROOT)
    assert valid, differences

    assert connection_attempts == []
    assert _catalog_snapshot() == catalog_before
    assert _operational_snapshot() == operational_before
    aggregate = b"\n".join(first_built.values())
    assert ambient_canary.encode() not in aggregate
    for content in first_built.values():
        written: list[bytes] = []
        admitted = admit_scanned_content(
            [content],
            max_bytes=max(1, len(content)),
            write=written.append,
            digest=_sha256,
        )
        assert admitted.content_sha256 == _sha256(content)
        assert written == [content]
    for match in URL_PATTERN.findall(aggregate):
        hostname = urlparse(match.decode("utf-8")).hostname
        assert hostname is not None and hostname.endswith(".example.test")


# T135/T136: the compact corpus binds every frozen input without copying it.
def test_benchmark_corpus_binds_all_runtime_records_and_adapter_identities() -> None:
    raw = (FIXTURE_ROOT / "benchmark" / "corpus.json").read_bytes()
    corpus = decode_canonical_json(raw)
    assert isinstance(corpus, dict)
    assert len(raw) < 4_096
    assert corpus["runtimeSources"] == {
        "count": 2_870,
        "ownershipCollisionCount": 0,
        "ownerMapSha256": "6121e07d3313b561fcde023ac181e8721c7f31a516d4ded693e634dcbe9384ed",
        "semanticSha256": "35655ea36568cf0a05ceb51fb7b757126e96d6fc5402b596c140a322baef10e7",
        "sourceKeySha256": corpus["runtimeSources"]["sourceKeySha256"],
        "uniqueKeyCount": 2_870,
    }
    assert len(corpus["runtimeSources"]["sourceKeySha256"]) == 64
    assert corpus["adapterIdentities"] == {
        "count": 16,
        "identityMapSha256": "3458c6e6fced46c20f55cba5f57c89489c19744dbebd150fa3f3e23ad3380de4",
        "providerIds": [
            "ashby",
            "cncf_landscape",
            "consider",
            "consider_a16z",
            "getro",
            "greenhouse_source",
            "lever_source",
            "public_index_csv",
            "public_page",
            "ranking_csv",
            "sec_company_tickers",
            "southparkcommons",
            "venturecapitalcareers",
            "ventureloop",
            "workable_source",
            "ycombinator",
        ],
    }
    assert corpus["ownerModuleCounts"] == {
        "consider": 184,
        "getro": 435,
        "landscapes": 1,
        "public_indexes": 2,
        "rankings": 1,
        "sec": 1,
        "special": 2_246,
    }
    assert corpus["thresholdPolicy"]["numericRegressionThreshold"] is None
    assert corpus["dataPolicy"] == {
        "containsAmbientEnvironment": False,
        "containsSourceLocators": False,
        "containsSourceRecords": False,
        "containsUserOwnedData": False,
        "representation": "aggregate counts, public adapter IDs, and one-way digests only",
    }
    serialized = raw.decode("utf-8")
    assert all(record.url not in serialized for record in BOARD_SOURCE_RECORDS)
    assert all(field not in corpus for field in ("entries", "records", "urls"))


def test_generator_cli_reports_committed_fixtures_are_current() -> None:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt == {
        "differences": {"changed": [], "extra": [], "missing": []},
        "ok": True,
        "output": str(FIXTURE_ROOT),
    }
