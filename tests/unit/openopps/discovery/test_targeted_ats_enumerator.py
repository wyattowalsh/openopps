from __future__ import annotations

from datetime import UTC, datetime

from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.models import BoundedReason, ChannelBudget, ChannelProfile
from openopps.discovery.targeted_ats import (
    EmployerTarget,
    classify_public_route,
    enumerate_targeted_ats_channel,
)


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _profile(seed_ids: tuple[str, ...], origins: tuple[str, ...]) -> ChannelProfile:
    return ChannelProfile(
        channel="targeted_ats",
        budget=ChannelBudget(
            query_limit=8,
            request_limit=12,
            origin_limit=8,
            redirect_limit=2,
            page_limit=2,
            response_byte_limit=8_000,
            aggregate_byte_limit=40_000,
            candidate_limit=20,
            concurrency_limit=2,
            per_origin_concurrency_limit=1,
            retry_limit=2,
            parser_depth_limit=16,
            wall_clock_limit_ms=5_000,
        ),
        seed_ids=seed_ids,
        allowed_origins=tuple(sorted(origins)),
        allowed_query_keys=("board",),
        parser_ids=("html-links-v1",),
    )


def test_built_in_route_parsing_does_not_load_plugins_or_invent_from_domain() -> None:
    greenhouse = classify_public_route("https://boards.greenhouse.io/acme")
    assert greenhouse is not None
    assert greenhouse.provider_id == "greenhouse"
    assert greenhouse.support == "jobs"
    assert greenhouse.token == "acme"
    assert classify_public_route("https://careers.acme.example.test/jobs") is None


def test_targeted_ats_classifies_supported_detect_unsupported_unsafe_inconclusive() -> (
    None
):
    greenhouse_html = (
        b"<!doctype html><html><body>"
        b'<a href="https://boards.greenhouse.io/acme">Board</a>'
        b"</body></html>"
    )
    careers_html = (
        b"<!doctype html><html><body><p>Join us at /careers. No ATS.</p></body></html>"
    )
    detect_html = (
        b"<!doctype html><html><body>"
        b'<a href="https://jobs.smartrecruiters.com/acme">SmartRecruiters</a>'
        b"</body></html>"
    )
    icims_html = b"<!doctype html><html><body><p>iCIMS login wall</p></body></html>"
    receipt = enumerate_targeted_ats_channel(
        profile=_profile(
            ("detect-smart", "icims-login", "supported-greenhouse", "unknown-careers"),
            (
                "https://boards.greenhouse.io:443",
                "https://careers.acme.example.test:443",
                "https://jobs.smartrecruiters.com:443",
                "https://acme.icims.com:443",
            ),
        ),
        targets=(
            EmployerTarget(
                target_id="supported-greenhouse",
                public_page_locator="https://boards.greenhouse.io/acme",
            ),
            EmployerTarget(
                target_id="detect-smart",
                public_page_locator="https://jobs.smartrecruiters.com/acme",
            ),
            EmployerTarget(
                target_id="icims-login",
                public_page_locator="https://acme.icims.com/jobs",
            ),
            EmployerTarget(
                target_id="unknown-careers",
                public_page_locator="https://careers.acme.example.test/jobs",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://boards.greenhouse.io/acme",
                status_code=200,
                body=greenhouse_html,
                media_type="text/html",
            ),
            CapturedObservation(
                locator="https://jobs.smartrecruiters.com/acme",
                status_code=200,
                body=detect_html,
                media_type="text/html",
            ),
            CapturedObservation(
                locator="https://acme.icims.com/jobs",
                status_code=200,
                body=icims_html,
                media_type="text/html",
            ),
            CapturedObservation(
                locator="https://careers.acme.example.test/jobs",
                status_code=200,
                body=careers_html,
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    classes = {
        item.occurrence_id.split(":")[-1]: item.identity.provider_id
        for item in receipt.occurrences
    }
    assert classes["supported"] == "greenhouse"
    assert classes["detect_only"] == "smartrecruiters"
    assert classes["unsupported"] == "icims"
    assert classes["inconclusive"] == "unknown"
    assert "greenhouse" not in {
        item.identity.provider_id
        for item in receipt.occurrences
        if item.occurrence_id.startswith("targeted-ats:unknown-careers")
    }


def test_targeted_ats_does_not_invent_ats_from_employer_domain() -> None:
    receipt = enumerate_targeted_ats_channel(
        profile=_profile(
            ("acme-careers",),
            ("https://careers.acme.example.test:443",),
        ),
        targets=(
            EmployerTarget(
                target_id="acme-careers",
                public_page_locator="https://careers.acme.example.test/jobs",
                claimed_provider_hint="greenhouse",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://careers.acme.example.test/jobs",
                status_code=200,
                body=b"<!doctype html><html><body><p>Careers</p></body></html>",
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    occurrence = receipt.occurrences[0]
    assert occurrence.occurrence_id.endswith("detect_only")
    assert occurrence.identity.canonical_url == "https://careers.acme.example.test/jobs"
    assert occurrence.identity.provider_token is None


def test_targeted_ats_auth_required_is_unsupported_without_job_sync() -> None:
    receipt = enumerate_targeted_ats_channel(
        profile=_profile(
            ("private-board",),
            ("https://boards.greenhouse.io:443",),
        ),
        targets=(
            EmployerTarget(
                target_id="private-board",
                public_page_locator="https://boards.greenhouse.io/secret",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://boards.greenhouse.io/secret",
                status_code=401,
                body=b"login",
                media_type="text/plain",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert receipt.operation_outcomes == ("blocked",)
    assert receipt.request_receipts[0].reason_code is BoundedReason.AUTH_REQUIRED
    assert any(
        item.occurrence_id.endswith("unsupported") for item in receipt.occurrences
    )
