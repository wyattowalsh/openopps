from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from openopps.discovery.canonical import decode_canonical_json
from openopps.discovery.models import BoundedReason
from openopps.discovery.robots import (
    ROBOTS_MAX_CACHE_AGE_SECONDS,
    ROBOTS_RFC_MINIMUM_BYTES,
    RobotsParseError,
    admit_public_sitemap_locators,
    evaluate_robots,
    parse_robots,
)
from openopps.discovery.transport import SafeLocator, validate_public_locator


ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "discovery"
SCENARIOS_FILE = FIXTURE_ROOT / "robots" / "scenarios.json"
TransportName = Literal[
    "response",
    "network_unreachable",
    "security_rejected_redirect",
    "verified_cache",
]
_TRANSPORT: dict[str, TransportName] = {
    "response": "response",
    "network-unreachable": "network_unreachable",
    "security-rejected-redirect": "security_rejected_redirect",
    "verified-cache": "verified_cache",
}


def _scenarios() -> tuple[dict[str, Any], ...]:
    payload = decode_canonical_json(SCENARIOS_FILE.read_bytes())
    assert isinstance(payload, dict)
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    return tuple(item for item in scenarios if isinstance(item, dict))


def _body(relative: str | None) -> bytes | None:
    if relative is None:
        return None
    path = (FIXTURE_ROOT / relative).resolve(strict=True)
    assert path.is_relative_to(FIXTURE_ROOT.resolve(strict=True))
    return path.read_bytes()


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda item: str(item["id"]))
def test_captured_robots_fixtures_evaluate_without_network(
    scenario: dict[str, Any],
) -> None:
    body = _body(scenario.get("bodyPath"))
    decision = evaluate_robots(
        transport_state=_TRANSPORT[str(scenario["transportState"])],
        status_code=scenario.get("statusCode"),
        body=body,
        product_token="OpenOppsBot",
        request_target=str(scenario["requestPath"]),
        cached_age_seconds=scenario.get("ageSeconds"),
    )

    assert decision.access == scenario["expectedAccess"]
    assert decision.reused is bool(scenario.get("expectedReuse", False))
    if decision.access == "allowed":
        assert decision.reason_code is BoundedReason.NONE
        assert decision.allowed is True
    else:
        assert decision.reason_code is not BoundedReason.NONE
        assert decision.allowed is False


def test_rfc_minimum_robots_body_is_exactly_500_kib() -> None:
    body = _body("robots/maximum-500-kib.txt")
    assert body is not None
    assert len(body) == ROBOTS_RFC_MINIMUM_BYTES
    policy = parse_robots(body)
    assert policy.access_for(
        product_token="OpenOppsBot",
        request_target="/bounded/jobs",
    )


def test_stale_verified_cache_is_complete_disallow() -> None:
    body = _body("robots/allow.txt")
    decision = evaluate_robots(
        transport_state="verified_cache",
        status_code=200,
        body=body,
        product_token="OpenOppsBot",
        request_target="/public/jobs",
        cached_age_seconds=ROBOTS_MAX_CACHE_AGE_SECONDS + 1,
    )

    assert decision.access == "blocked"
    assert decision.reused is False
    assert decision.reason_code is BoundedReason.EVIDENCE_STALE
    assert decision.policy is None


def test_security_rejected_redirect_does_not_weaken_destination_policy() -> None:
    decision = evaluate_robots(
        transport_state="security_rejected_redirect",
        status_code=302,
        body=_body("robots/allow.txt"),
        product_token="OpenOppsBot",
        request_target="/public/jobs",
    )

    assert decision.access == "blocked"
    assert decision.reason_code is BoundedReason.REDIRECT_REJECTED
    assert decision.policy is None


def test_empty_disallow_is_ignored_and_longest_match_wins() -> None:
    policy = parse_robots(
        b"User-agent: OpenOppsBot\n"
        b"Disallow:\n"
        b"Disallow: /jobs\n"
        b"Allow: /jobs/public\n"
    )

    assert policy.access_for(
        product_token="OpenOppsBot",
        request_target="/jobs/public",
    )
    assert not policy.access_for(
        product_token="OpenOppsBot",
        request_target="/jobs/secret",
    )


def test_exact_product_token_group_beats_wildcard() -> None:
    policy = parse_robots(
        b"User-agent: *\n"
        b"Disallow: /\n"
        b"User-agent: OpenOppsBot\n"
        b"Allow: /public/\n"
    )

    assert policy.access_for(
        product_token="OpenOppsBot",
        request_target="/public/jobs",
    )
    assert not policy.access_for(product_token="OtherBot", request_target="/public/jobs")


def test_parse_robots_rejects_oversize_and_non_utf8_bodies() -> None:
    with pytest.raises(RobotsParseError, match="trusted byte limit"):
        parse_robots(b"x" * (ROBOTS_RFC_MINIMUM_BYTES + 1))
    with pytest.raises(RobotsParseError, match="not valid UTF-8"):
        parse_robots(b"User-agent: *\nDisallow: /\xff\n")


def test_invalid_product_token_and_request_target_fail_closed() -> None:
    policy = parse_robots(b"User-agent: *\nAllow: /\n")
    with pytest.raises(ValueError, match="product token"):
        policy.access_for(product_token="Open Opps", request_target="/jobs")
    with pytest.raises(ValueError, match="origin-form"):
        policy.access_for(product_token="OpenOppsBot", request_target="jobs")


def test_client_error_robots_response_is_unrestricted_observation() -> None:
    decision = evaluate_robots(
        transport_state="response",
        status_code=404,
        body=None,
        product_token="OpenOppsBot",
        request_target="/jobs",
    )

    assert decision.access == "allowed"
    assert decision.reason_code is BoundedReason.NONE
    assert decision.policy is not None
    assert decision.policy.groups == ()


def test_sitemap_locators_are_bounded_observations_not_instructions() -> None:
    policy = parse_robots(
        b"User-agent: *\n"
        b"Allow: /\n"
        b"Sitemap: https://jobs.example.test/sitemap.xml\n"
        b"Sitemap: https://jobs.example.test/sitemap.xml\n"
    )

    assert policy.sitemap_locators == (
        "https://jobs.example.test/sitemap.xml",
    )
    with pytest.raises(RobotsParseError, match="Sitemap limit"):
        parse_robots(
            b"User-agent: *\nAllow: /\nSitemap: https://a.test/s.xml\n"
            b"Sitemap: https://b.test/s.xml\n",
            sitemap_limit=1,
        )

def test_raw_sitemap_observations_are_not_fetchable_until_validated() -> None:
    policy = parse_robots(
        b"User-agent: *\n"
        b"Allow: /\n"
        b"Sitemap: https://jobs.example.test/sitemap.xml\n"
        b"Sitemap: file:///etc/passwd\n"
        b"Sitemap: http://jobs.example.test/cleartext.xml\n"
        b"Sitemap: https://127.0.0.1/sitemap.xml\n"
    )

    assert policy.sitemap_locators == (
        "file:///etc/passwd",
        "http://jobs.example.test/cleartext.xml",
        "https://127.0.0.1/sitemap.xml",
        "https://jobs.example.test/sitemap.xml",
    )
    admitted = admit_public_sitemap_locators(policy.sitemap_locators)
    expected = validate_public_locator("https://jobs.example.test/sitemap.xml")
    assert admitted == (expected,)
    assert isinstance(admitted[0], SafeLocator)
    assert all(
        locator.url.startswith("https://") and "://" in locator.url
        for locator in admitted
    )


def test_sitemap_admission_rejects_non_iterable_observations() -> None:
    with pytest.raises(ValueError, match="string iterable"):
        admit_public_sitemap_locators("https://jobs.example.test/sitemap.xml")
    with pytest.raises(ValueError, match="not a string"):
        admit_public_sitemap_locators((None,))  # type: ignore[arg-type]


def test_robots_module_does_not_fetch_or_import_weaker_http_seams() -> None:
    import ast

    source = Path(
        Path(__file__).resolve().parents[4]
        / "src"
        / "openopps"
        / "discovery"
        / "robots.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "httpx" not in imported
    assert "httpcore" not in imported
    assert "openopps.http" not in imported
    assert "openopps.discovery.http_client" not in imported
    assert "openopps.cache" not in imported
    assert "openopps.plugins" not in imported
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "admit_public_sitemap_locators" in function_names
    assert "fetch" not in function_names

