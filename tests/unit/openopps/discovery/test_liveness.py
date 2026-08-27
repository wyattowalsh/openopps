"""V511-V516 objective liveness: uncached jobs-capable GET, never permanent absence."""

from __future__ import annotations

from datetime import UTC, datetime

from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.evaluation import classify_liveness
from openopps.discovery.liveness import (
    PERMANENT_ABSENCE_ENABLED,
    InjectedTransportResult,
    jobs_capable_structure,
    probe_liveness,
)
from openopps.discovery.models import LivenessEvidence


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)
GREENHOUSE_JOBS = b'{"jobs":[{"id":1,"title":"Engineer","absolute_url":"https://boards.greenhouse.io/acme/jobs/1"}]}'
LISTING = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"


def _obs(**updates: object) -> CapturedObservation:
    values: dict[str, object] = {
        "locator": LISTING,
        "transport_state": "response",
        "status_code": 200,
        "body": GREENHOUSE_JOBS,
        "media_type": "application/json",
        "cached_age_seconds": None,
    }
    values.update(updates)
    return CapturedObservation(**values)


def test_jobs_capable_json_listing_is_live() -> None:
    evidence, probe = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(),
    )
    assert classify_liveness(evidence).value == "live"
    assert probe.expected_structure is True
    assert probe.observed_at == NOW
    assert probe.response_class == "expected_payload"
    assert "json_jobs" in probe.structural_markers
    assert probe.receipt_id is not None
    assert probe.permanent_absence is False
    assert probe.cached is False


def test_empty_jobs_array_is_still_jobs_capable() -> None:
    capable, markers = jobs_capable_structure(
        provider_id="greenhouse",
        media_type="application/json",
        body=b'{"jobs":[]}',
    )
    assert capable is True
    assert "empty_job_array" in markers


def test_landing_page_and_challenge_are_not_live() -> None:
    landing, _ = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(
            body=b"<html><h1>Careers at Acme</h1></html>", media_type="text/html"
        ),
    )
    challenge, _ = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(
            body=b"<html>just a moment... cf-challenge</html>", media_type="text/html"
        ),
    )
    assert classify_liveness(landing).value == "inconclusive"
    assert landing.response_class == "landing_page"
    assert classify_liveness(challenge).value == "inconclusive"
    assert challenge.response_class == "challenge"


def test_cached_or_conditional_observation_never_proves_live() -> None:
    evidence, probe = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(transport_state="not_modified", cached_age_seconds=12),
    )
    assert classify_liveness(evidence).value == "inconclusive"
    assert evidence.response_class == "cached_or_conditional"
    assert probe.cached is True


def test_transient_failures_are_inconclusive_not_absence(
    response_class: str | None = None,
) -> None:
    del response_class
    cases = {
        "timeout": InjectedTransportResult(
            status_code=None,
            body=None,
            media_type=None,
            cached=False,
            transport_error="timeout",
            redirect_loop=False,
            elapsed_ms=5,
            request_id="t",
        ),
        "dns_error": InjectedTransportResult(
            status_code=None,
            body=None,
            media_type=None,
            cached=False,
            transport_error="dns_error",
            redirect_loop=False,
            elapsed_ms=5,
            request_id="d",
        ),
        "tls_error": InjectedTransportResult(
            status_code=None,
            body=None,
            media_type=None,
            cached=False,
            transport_error="tls_error",
            redirect_loop=False,
            elapsed_ms=5,
            request_id="s",
        ),
        "rate_limited": InjectedTransportResult(
            status_code=429,
            body=b"slow",
            media_type="text/plain",
            cached=False,
            transport_error=None,
            redirect_loop=False,
            elapsed_ms=5,
            request_id="r",
        ),
        "http_5xx": InjectedTransportResult(
            status_code=503,
            body=b"down",
            media_type="text/plain",
            cached=False,
            transport_error=None,
            redirect_loop=False,
            elapsed_ms=5,
            request_id="5",
        ),
        "auth_required": InjectedTransportResult(
            status_code=401,
            body=b"auth",
            media_type="text/plain",
            cached=False,
            transport_error=None,
            redirect_loop=False,
            elapsed_ms=5,
            request_id="a",
        ),
    }
    for name, result in cases.items():

        class _Client:
            def get_uncached(self, url: str) -> InjectedTransportResult:
                del url
                return result

        evidence, probe = probe_liveness(
            LISTING,
            observed_at=NOW,
            provider_id="greenhouse",
            transport_client=_Client(),
        )
        assert classify_liveness(evidence).value == "inconclusive", name
        assert probe.permanent_absence is False, name
    assert PERMANENT_ABSENCE_ENABLED is False


def test_replay_is_required_without_observation_or_injected_client() -> None:
    evidence, probe = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
    )
    assert classify_liveness(evidence).value == "inconclusive"
    assert evidence.response_class == "evidence_incomplete"
    assert "replay_required" in probe.structural_markers


def test_liveness_evidence_model_still_rejects_unrelated_http_200() -> None:
    live = LivenessEvidence(
        response_class="expected_payload",
        expected_structure=True,
        observed_at=NOW,
    )
    unrelated = LivenessEvidence(
        response_class="http_200_unrelated",
        expected_structure=False,
        observed_at=NOW,
    )
    assert classify_liveness(live).value == "live"
    assert classify_liveness(unrelated).value == "inconclusive"


def test_observation_locator_must_match_the_listing_endpoint() -> None:
    evidence, probe = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(locator="https://boards-api.greenhouse.io/v1/boards/other/jobs"),
    )
    assert classify_liveness(evidence).value == "inconclusive"
    assert evidence.response_class == "evidence_incomplete"
    assert "locator_mismatch" in probe.structural_markers


def test_secret_bearing_jobs_json_is_not_live() -> None:
    evidence, probe = probe_liveness(
        LISTING,
        observed_at=NOW,
        provider_id="greenhouse",
        observation=_obs(
            body=b'{"jobs":[{"id":1,"title":"Eng","authorization":"Bearer supersecrettokenvalue"}]}'
        ),
    )
    assert classify_liveness(evidence).value == "inconclusive"
    assert "secret_detected" in probe.structural_markers
    assert probe.permanent_absence is False
