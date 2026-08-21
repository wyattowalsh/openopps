"""Generate sanitized, deterministic, offline source-discovery fixtures.

The benchmark corpus is intentionally a compact manifest over the packaged
runtime inventory.  It binds all source records and adapter identities by
count and digest without copying source locators, metadata, or ambient data
into the fixture tree.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import pkgutil


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "discovery"
FIXTURE_SCHEMA_VERSION = "openopps.discovery.fixtures.v1"
BENCHMARK_SCHEMA_VERSION = "openopps.discovery.benchmark-corpus.v1"
GENERATOR_VERSION = 1
ROBOTS_RFC_MINIMUM_BYTES = 500 * 1024


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _maximum_robots_body() -> bytes:
    prefix = b"User-agent: *\nAllow: /bounded/\n"
    padding = b"# deterministic RFC 9309 parser padding\n"
    repeats = (ROBOTS_RFC_MINIMUM_BYTES - len(prefix) + len(padding) - 1) // len(
        padding
    )
    body = (prefix + padding * repeats)[:ROBOTS_RFC_MINIMUM_BYTES]
    if len(body) != ROBOTS_RFC_MINIMUM_BYTES:
        raise AssertionError("500-KiB robots fixture construction failed")
    return body


def _runtime_inventory() -> dict[str, object]:
    """Bind the live packaged inventory without emitting individual records."""

    from openopps.models import SourceRecord, canonical_json_hash
    from openopps.providers import sources as sources_package
    from openopps.providers.sources import (
        BOARD_SOURCE_ADAPTERS,
        BOARD_SOURCE_RECORDS,
    )
    from openopps.providers.sources.source_utils import (
        source_record_to_catalog_entry,
    )

    records = sorted(BOARD_SOURCE_RECORDS, key=lambda record: record.key)
    entries = [source_record_to_catalog_entry(record) for record in records]
    keys = [record.key for record in records]

    owner_rows: list[list[str]] = []
    for module_info in pkgutil.iter_modules(
        sources_package.__path__, f"{sources_package.__name__}."
    ):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        owner_rows.extend(
            [record.key, module.__name__]
            for record in getattr(module, "SOURCE_RECORDS", ())
            if isinstance(record, SourceRecord)
        )
    owner_rows.sort()
    owner_keys = [row[0] for row in owner_rows]
    if owner_keys != keys or len(owner_keys) != len(set(owner_keys)):
        raise ValueError("runtime source ownership is incomplete or ambiguous")

    adapter_rows = [
        [provider_id, adapter.__module__, adapter.__qualname__]
        for provider_id, adapter in sorted(BOARD_SOURCE_ADAPTERS.items())
    ]
    owner_counts = Counter(row[1].rsplit(".", 1)[-1] for row in owner_rows)

    return {
        "adapterIdentities": {
            "count": len(adapter_rows),
            "identityMapSha256": _sha256(_canonical_json(adapter_rows)),
            "providerIds": [row[0] for row in adapter_rows],
        },
        "dataPolicy": {
            "containsAmbientEnvironment": False,
            "containsSourceLocators": False,
            "containsSourceRecords": False,
            "containsUserOwnedData": False,
            "representation": "aggregate counts, public adapter IDs, and one-way digests only",
        },
        "inputContract": {
            "adapterInventory": "openopps.providers.sources.BOARD_SOURCE_ADAPTERS",
            "sourceInventory": "openopps.providers.sources.BOARD_SOURCE_RECORDS",
        },
        "operations": [
            "normalization",
            "schema_validation",
            "deduplication",
            "catalog_collision_audit",
            "policy_evaluation",
            "promotion_rendering",
        ],
        "ownerModuleCounts": dict(sorted(owner_counts.items())),
        "runtimeSources": {
            "count": len(records),
            "ownershipCollisionCount": len(owner_keys) - len(set(owner_keys)),
            "ownerMapSha256": _sha256(_canonical_json(owner_rows)),
            "semanticSha256": canonical_json_hash(entries),
            "sourceKeySha256": canonical_json_hash(keys),
            "uniqueKeyCount": len(set(keys)),
        },
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "thresholdPolicy": {
            "numericRegressionThreshold": None,
            "status": "evidence-only-until-reviewed-adr",
        },
    }


def _media_type(path: str) -> str:
    suffix = Path(path).suffix
    return {
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".txt": "text/plain; charset=utf-8",
        ".xml": "application/xml",
    }[suffix]


def _role(path: str) -> str:
    prefix = path.split("/", 1)[0]
    return {
        "benchmark": "benchmark-corpus",
        "http": "transport-evidence",
        "parser": "parser-evidence",
        "robots": "robots-evidence",
        "sitemap": "sitemap-evidence",
        "skill": "portable-skill-output",
    }[prefix]


def _fixture_manifest(files: dict[str, bytes]) -> bytes:
    members = [
        {
            "mediaType": _media_type(path),
            "path": path,
            "role": _role(path),
            "sha256": _sha256(data),
            "sizeBytes": len(data),
        }
        for path, data in sorted(files.items())
    ]
    return _canonical_json(
        {
            "environment": {
                "ambientEnvironment": "ignored",
                "clock": "not-read",
                "filesystemInput": "tracked-runtime-inventory-only",
                "locale": "UTF-8",
                "network": "disabled",
                "python": "CPython >=3.12",
                "timezone": "UTC",
            },
            "fixtureSetSha256": _sha256(_canonical_json(members)),
            "generator": {
                "path": "scripts/generate_discovery_fixtures.py",
                "sha256": _sha256(Path(__file__).read_bytes()),
                "version": GENERATOR_VERSION,
            },
            "memberCount": len(members),
            "members": members,
            "numericRegressionThreshold": None,
            "schemaVersion": FIXTURE_SCHEMA_VERSION,
        }
    )


def build_fixture_tree() -> dict[str, bytes]:
    """Return the complete expected fixture tree as path-addressed bytes."""

    files: dict[str, bytes] = {}
    files["robots/allow.txt"] = b"User-agent: *\nDisallow: /private/\nAllow: /public/\n"
    files["robots/disallow.txt"] = b"User-agent: *\nDisallow: /\n"
    files["robots/maximum-500-kib.txt"] = _maximum_robots_body()
    files["robots/scenarios.json"] = _canonical_json(
        {
            "cacheMaximumAgeSeconds": 86_400,
            "scenarios": [
                {
                    "bodyPath": "robots/allow.txt",
                    "expectedAccess": "allowed",
                    "id": "success-allow",
                    "requestPath": "/public/jobs",
                    "statusCode": 200,
                    "transportState": "response",
                },
                {
                    "bodyPath": "robots/disallow.txt",
                    "expectedAccess": "blocked",
                    "id": "success-disallow",
                    "requestPath": "/private/jobs",
                    "statusCode": 200,
                    "transportState": "response",
                },
                {
                    "bodyPath": None,
                    "expectedAccess": "allowed",
                    "id": "unavailable-404",
                    "requestPath": "/jobs",
                    "statusCode": 404,
                    "transportState": "response",
                },
                {
                    "bodyPath": None,
                    "expectedAccess": "blocked",
                    "id": "unreachable-network",
                    "requestPath": "/jobs",
                    "statusCode": None,
                    "transportState": "network-unreachable",
                },
                {
                    "bodyPath": None,
                    "expectedAccess": "blocked",
                    "id": "unreachable-503",
                    "requestPath": "/jobs",
                    "statusCode": 503,
                    "transportState": "response",
                },
                {
                    "bodyPath": None,
                    "expectedAccess": "blocked",
                    "id": "cross-origin-redirect-rejected",
                    "location": "https://redirect.example.test/robots.txt",
                    "requestPath": "/jobs",
                    "statusCode": 302,
                    "transportState": "security-rejected-redirect",
                },
                {
                    "ageSeconds": 86_399,
                    "bodyPath": "robots/allow.txt",
                    "expectedAccess": "allowed",
                    "expectedReuse": True,
                    "id": "fresh-cache",
                    "requestPath": "/public/jobs",
                    "statusCode": 200,
                    "transportState": "verified-cache",
                },
                {
                    "ageSeconds": 86_401,
                    "bodyPath": "robots/allow.txt",
                    "expectedAccess": "blocked",
                    "expectedReuse": False,
                    "id": "stale-cache-unreachable",
                    "requestPath": "/public/jobs",
                    "statusCode": None,
                    "transportState": "network-unreachable",
                },
                {
                    "bodyPath": "robots/maximum-500-kib.txt",
                    "expectedAccess": "allowed",
                    "id": "rfc-minimum-500-kib",
                    "requestPath": "/bounded/jobs",
                    "statusCode": 200,
                    "transportState": "response",
                },
            ],
            "schemaVersion": "openopps.discovery.robots-fixtures.v1",
            "userAgent": "OpenOppsBot",
        }
    )

    files["sitemap/index.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        b"  <sitemap><loc>https://jobs.example.test/sitemap-jobs.xml</loc>"
        b"<lastmod>2026-08-20T00:00:00Z</lastmod></sitemap>\n"
        b"</sitemapindex>\n"
    )
    files["sitemap/urlset.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        b"  <url><loc>https://jobs.example.test/companies/acme/jobs</loc>"
        b"<lastmod>2026-08-19</lastmod></url>\n"
        b"  <url><loc>https://jobs.example.test/companies/example/jobs</loc>"
        b"<lastmod>2026-08-20T01:02:03Z</lastmod></url>\n"
        b"</urlset>\n"
    )
    files["sitemap/host-mismatch.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        b"  <url><loc>https://other.example.test/companies/acme/jobs</loc>"
        b"<lastmod>2026-08-20</lastmod></url>\n"
        b"</urlset>\n"
    )
    files["sitemap/scenarios.json"] = _canonical_json(
        {
            "entryLimit": 8,
            "scenarios": [
                {
                    "expectedEntries": 1,
                    "expectedHost": "jobs.example.test",
                    "expectedLastmod": "2026-08-20T00:00:00Z",
                    "expectedOutcome": "accepted",
                    "id": "bounded-index",
                    "inputPath": "sitemap/index.xml",
                    "kind": "index",
                },
                {
                    "expectedEntries": 2,
                    "expectedHost": "jobs.example.test",
                    "expectedLastmod": "2026-08-20T01:02:03Z",
                    "expectedOutcome": "accepted",
                    "id": "same-host-urlset",
                    "inputPath": "sitemap/urlset.xml",
                    "kind": "urlset",
                },
                {
                    "expectedEntries": 1,
                    "expectedHost": "jobs.example.test",
                    "expectedOutcome": "blocked-host-mismatch",
                    "id": "cross-host-urlset",
                    "inputPath": "sitemap/host-mismatch.xml",
                    "kind": "urlset",
                },
            ],
            "schemaVersion": "openopps.discovery.sitemap-fixtures.v1",
        }
    )

    files["http/conditional-and-rate-limit.json"] = _canonical_json(
        {
            "conditional": {
                "notModifiedStatusCode": 304,
                "observed": {
                    "etag": 'W/"fixture-etag-v1"',
                    "lastModified": "Wed, 20 Aug 2026 10:00:00 GMT",
                },
                "requestHeaders": {
                    "ifModifiedSince": "Wed, 20 Aug 2026 10:00:00 GMT",
                    "ifNoneMatch": 'W/"fixture-etag-v1"',
                },
            },
            "rateLimit": [
                {
                    "expectedDelayMilliseconds": 5_000,
                    "id": "delta-seconds",
                    "maximumDelayMilliseconds": 10_000,
                    "retryAfter": "5",
                    "statusCode": 429,
                },
                {
                    "expectedDelayMilliseconds": 5_000,
                    "id": "http-date",
                    "maximumDelayMilliseconds": 10_000,
                    "now": "Thu, 21 Aug 2026 10:00:00 GMT",
                    "retryAfter": "Thu, 21 Aug 2026 10:00:05 GMT",
                    "statusCode": 429,
                },
                {
                    "expectedOutcome": "rejected-over-trusted-bound",
                    "id": "excessive-delay",
                    "maximumDelayMilliseconds": 10_000,
                    "retryAfter": "3600",
                    "statusCode": 429,
                },
            ],
            "schemaVersion": "openopps.discovery.http-fixtures.v1",
        }
    )

    files["parser/official-catalog.json"] = _canonical_json(
        {
            "items": [
                {
                    "jobs": "https://jobs.example.test/companies/acme/jobs",
                    "name": "Example Company",
                    "provider": "example-provider",
                }
            ],
            "next": None,
            "schemaVersion": "example.catalog.v1",
        }
    )
    files["parser/provider-page.html"] = (
        b"<!doctype html>\n<html><body><main>"
        b'<a href="https://jobs.example.test/companies/acme/jobs">Jobs</a>'
        b"<p>Retrieved text is evidence, never instructions.</p>"
        b"</main></body></html>\n"
    )
    files["parser/malformed.json"] = b'{"items":[}\n'
    files["parser/dtd.xml"] = (
        b'<?xml version="1.0"?>\n<!DOCTYPE fixture [<!ENTITY bounded "fixture">]>\n'
        b"<fixture>&bounded;</fixture>\n"
    )
    files["parser/scenarios.json"] = _canonical_json(
        {
            "scenarios": [
                {
                    "expectedOutcome": "accepted",
                    "id": "bounded-json",
                    "inputPath": "parser/official-catalog.json",
                    "maximumDepth": 4,
                    "parserId": "official-json-v1",
                },
                {
                    "expectedOutcome": "accepted",
                    "id": "bounded-html",
                    "inputPath": "parser/provider-page.html",
                    "maximumNodes": 16,
                    "parserId": "html-links-v1",
                },
                {
                    "expectedOutcome": "rejected-malformed",
                    "id": "malformed-json",
                    "inputPath": "parser/malformed.json",
                    "maximumDepth": 4,
                    "parserId": "official-json-v1",
                },
                {
                    "expectedOutcome": "rejected-dtd",
                    "id": "xml-dtd",
                    "inputPath": "parser/dtd.xml",
                    "maximumDepth": 4,
                    "parserId": "sitemap-xml-v1",
                },
            ],
            "schemaVersion": "openopps.discovery.parser-fixtures.v1",
        }
    )

    provenance_id = "sha256:" + _sha256(files["parser/official-catalog.json"])
    good_suggestion = {
        "candidateLocator": "https://jobs.example.test/companies/acme/jobs",
        "parserId": "official-json-v1",
        "provenanceResourceIds": [provenance_id],
        "providerId": "example-provider",
    }
    files["skill/known-good.json"] = _canonical_json(good_suggestion)
    files["skill/known-bad-unadmitted-provenance.json"] = _canonical_json(
        {
            **good_suggestion,
            "provenanceResourceIds": ["sha256:" + "f" * 64],
        }
    )
    files["skill/known-bad-parser.json"] = _canonical_json(
        {**good_suggestion, "parserId": "untrusted-module"}
    )
    files["skill/known-bad-provider.json"] = _canonical_json(
        {**good_suggestion, "providerId": "untrusted-provider"}
    )
    files["skill/known-bad-authority.json"] = _canonical_json(
        {**good_suggestion, "approved": True}
    )
    files["skill/scenarios.json"] = _canonical_json(
        {
            "admittedParserIds": ["official-json-v1"],
            "admittedProviderIds": ["example-provider"],
            "admittedResourceIds": [provenance_id],
            "scenarios": [
                {
                    "expectedOutcome": "accepted-data-only",
                    "id": "known-good",
                    "inputPath": "skill/known-good.json",
                    "schemaValid": True,
                },
                {
                    "expectedReason": "suggestion_provenance",
                    "id": "unadmitted-provenance",
                    "inputPath": "skill/known-bad-unadmitted-provenance.json",
                    "schemaValid": True,
                },
                {
                    "expectedReason": "suggestion_parser",
                    "id": "untrusted-parser",
                    "inputPath": "skill/known-bad-parser.json",
                    "schemaValid": True,
                },
                {
                    "expectedReason": "suggestion_provider",
                    "id": "untrusted-provider",
                    "inputPath": "skill/known-bad-provider.json",
                    "schemaValid": True,
                },
                {
                    "expectedReason": "suggestion_authority_field",
                    "id": "authority-field",
                    "inputPath": "skill/known-bad-authority.json",
                    "schemaValid": False,
                },
            ],
            "schemaVersion": "openopps.discovery.skill-fixtures.v1",
        }
    )

    files["benchmark/corpus.json"] = _canonical_json(_runtime_inventory())
    files["manifest.json"] = _fixture_manifest(files)
    return dict(sorted(files.items()))


def write_fixture_tree(output: Path) -> dict[str, bytes]:
    expected = build_fixture_tree()
    output.mkdir(parents=True, exist_ok=True)
    for relative, data in expected.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return expected


def read_fixture_tree(output: Path) -> dict[str, bytes]:
    if not output.exists():
        return {}
    return {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }


def check_fixture_tree(output: Path) -> tuple[bool, dict[str, list[str]]]:
    expected = build_fixture_tree()
    actual = read_fixture_tree(output)
    expected_paths = set(expected)
    actual_paths = set(actual)
    result = {
        "changed": sorted(
            path
            for path in expected_paths & actual_paths
            if expected[path] != actual[path]
        ),
        "extra": sorted(actual_paths - expected_paths),
        "missing": sorted(expected_paths - actual_paths),
    }
    return not any(result.values()), result


def _tree_digest(files: dict[str, bytes]) -> str:
    rows = [[path, len(data), _sha256(data)] for path, data in sorted(files.items())]
    return _sha256(_canonical_json(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    output = args.output.resolve(strict=False)
    if args.check:
        valid, differences = check_fixture_tree(output)
        print(
            json.dumps(
                {"differences": differences, "ok": valid, "output": str(output)},
                sort_keys=True,
            )
        )
        return 0 if valid else 1

    files = write_fixture_tree(output)
    print(
        json.dumps(
            {
                "fileCount": len(files),
                "ok": True,
                "output": str(output),
                "treeSha256": _tree_digest(files),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
