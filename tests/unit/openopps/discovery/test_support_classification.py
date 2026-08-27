"""V521-V525 built-in adapter/route support without ATS-from-domain invention."""

from __future__ import annotations

from openopps.discovery.evaluation import classify_support
from openopps.discovery.identity import normalize_candidate_identity
from openopps.discovery.support import classify_identity_support


ADAPTERS = ("greenhouse", "lever")


def _identity(**updates: object):
    values: dict[str, object] = {
        "key": "acme",
        "url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        "provider_id": "greenhouse",
        "provider_token": "acme",
        "owner": "targeted-ats",
        "candidate_kind": "board_route",
    }
    values.update(updates)
    return normalize_candidate_identity(**values)


def test_greenhouse_listing_is_authoritative_executable_support() -> None:
    evidence, classification = classify_identity_support(
        _identity(),
        source_adapter_ids=ADAPTERS,
    )
    assert classification.level == "authoritative_jobs"
    assert classification.built_in_route is True
    assert classification.route_metadata_complete is True
    assert classify_support(evidence).value == "supported"


def test_source_adapter_support_uses_closed_registry() -> None:
    identity = _identity(
        candidate_kind="source",
        url="https://jobs.example.test/acme",
        adapter_id="greenhouse",
    )
    evidence, classification = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
    )
    assert classification.level == "source_support"
    assert classify_support(evidence).value == "supported"


def test_detect_only_hint_is_not_executable_support() -> None:
    identity = _identity(
        url="https://jobs.smartrecruiters.com/acme",
        provider_id="smartrecruiters",
        provider_token="acme",
    )
    evidence, classification = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
    )
    assert classification.level == "detect_only"
    assert classification.job_fetch_validated is False
    assert classify_support(evidence).value == "inconclusive"


def test_unsupported_built_in_route_is_not_overclaimed() -> None:
    identity = _identity(
        url="https://acme.icims.com/jobs",
        provider_id="icims",
        provider_token="acme",
    )
    _evidence, classification = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
    )
    assert classification.level == "unsupported"
    assert classification.reason == "unsupported_built_in_route"


def test_employer_domain_does_not_invent_an_ats() -> None:
    identity = _identity(
        url="https://careers.example.test/acme",
        provider_id="unknown",
        provider_token=None,
        candidate_kind="source",
        adapter_id=None,
    )
    _evidence, classification = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
    )
    assert classification.level == "unsupported"
    assert classification.reason == "no_built_in_source_adapter"


def test_auth_required_and_transient_failure_preserve_reasons() -> None:
    identity = _identity()
    _auth, auth_class = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
        access_required=True,
    )
    _transient, transient_class = classify_identity_support(
        identity,
        source_adapter_ids=ADAPTERS,
        transient_failure=True,
    )
    assert auth_class.level == "unsupported"
    assert auth_class.reason == "access_required"
    assert transient_class.level == "inconclusive"
    assert transient_class.reason == "transient_failure"
