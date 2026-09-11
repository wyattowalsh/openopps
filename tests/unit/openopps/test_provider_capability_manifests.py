from __future__ import annotations

import pytest

from openopps.providers.boards import BOARD_URL_PULL_PROVIDERS
from openopps.providers.pull import InterfaceStability, ProviderPullCapabilities

BUILTIN_ATS_FAMILY_IDS = frozenset(
    {
        "greenhouse",
        "lever",
        "ashbyhq",
        "workable",
        "workday",
        "rippling",
        "teamtailor",
        "bamboohr",
        "consider_jobs",
        "wpjobmanager",
    }
)


def _capabilities(provider_id: str) -> ProviderPullCapabilities:
    provider = BOARD_URL_PULL_PROVIDERS[provider_id]
    capabilities = provider.pull_capabilities
    assert isinstance(capabilities, ProviderPullCapabilities)
    return capabilities


def test_builtin_url_pull_providers_are_exactly_the_ten_ats_families() -> None:
    assert frozenset(BOARD_URL_PULL_PROVIDERS) == BUILTIN_ATS_FAMILY_IDS


@pytest.mark.parametrize(
    (
        "provider_id",
        "native_get",
        "board_scan_get",
        "enumerate_unlisted",
        "stability",
    ),
    [
        ("ashbyhq", False, True, True, InterfaceStability.DOCUMENTED),
        ("bamboohr", True, False, False, InterfaceStability.BEST_EFFORT),
        ("consider_jobs", False, True, False, InterfaceStability.BEST_EFFORT),
        ("greenhouse", True, False, False, InterfaceStability.DOCUMENTED),
        ("lever", True, False, False, InterfaceStability.DOCUMENTED),
        ("rippling", True, False, False, InterfaceStability.BEST_EFFORT),
        ("teamtailor", False, True, False, InterfaceStability.BEST_EFFORT),
        ("workable", False, True, False, InterfaceStability.BEST_EFFORT),
        ("workday", True, False, False, InterfaceStability.BEST_EFFORT),
        ("wpjobmanager", True, False, False, InterfaceStability.BEST_EFFORT),
    ],
)
def test_builtin_ats_capability_manifests_match_list_and_get_hooks(
    provider_id: str,
    native_get: bool,
    board_scan_get: bool,
    enumerate_unlisted: bool,
    stability: InterfaceStability,
) -> None:
    provider = BOARD_URL_PULL_PROVIDERS[provider_id]
    capabilities = _capabilities(provider_id)

    assert capabilities.list_supported is True
    assert callable(provider.pull_list)
    assert capabilities.native_get_supported is native_get
    assert callable(getattr(provider, "pull_get", None)) is native_get
    assert capabilities.board_scan_get_supported is board_scan_get
    assert capabilities.enumerate_unlisted_supported is enumerate_unlisted
    assert capabilities.interface_stability == stability


@pytest.mark.parametrize("provider_id", ("ashbyhq", "workable", "teamtailor"))
def test_ashby_workable_teamtailor_do_not_fake_native_get(provider_id: str) -> None:
    provider = BOARD_URL_PULL_PROVIDERS[provider_id]
    capabilities = _capabilities(provider_id)

    assert capabilities.native_get_supported is False
    assert callable(getattr(provider, "pull_get", None)) is False
    assert capabilities.board_scan_get_supported is True


@pytest.mark.parametrize("provider_id", ("greenhouse", "lever"))
def test_greenhouse_and_lever_report_documented_native_get(provider_id: str) -> None:
    capabilities = _capabilities(provider_id)

    assert capabilities.native_get_supported is True
    assert capabilities.interface_stability == InterfaceStability.DOCUMENTED


@pytest.mark.parametrize(
    "provider_id",
    ("workday", "rippling", "bamboohr", "wpjobmanager"),
)
def test_best_effort_families_report_native_get(provider_id: str) -> None:
    capabilities = _capabilities(provider_id)

    assert capabilities.native_get_supported is True
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT


def test_ashbyhq_reports_documented_board_scan_without_native_get() -> None:
    capabilities = _capabilities("ashbyhq")

    assert capabilities.interface_stability == InterfaceStability.DOCUMENTED
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is True
    assert capabilities.native_get_supported is False


def test_consider_jobs_has_exact_get() -> None:
    """G2 T038: Consider exact-get is honest board-scan, not a fake native get."""

    provider = BOARD_URL_PULL_PROVIDERS["consider_jobs"]
    capabilities = _capabilities("consider_jobs")

    assert capabilities.list_supported is True
    assert capabilities.native_get_supported is False
    assert callable(getattr(provider, "pull_get", None)) is False
    assert capabilities.board_scan_get_supported is True
    assert capabilities.enumerate_unlisted_supported is False
    assert capabilities.interface_stability == InterfaceStability.BEST_EFFORT


def test_one_off_html_and_denied_hosts_do_not_register_a_jobs_provider() -> None:
    from openopps.providers.boards import BOARD_JOB_PROVIDERS, board_provider_definitions
    from openopps.providers.registry import ProviderRegistry

    registry = ProviderRegistry(list(board_provider_definitions()))
    for url in (
        "https://www.janestreet.com/careers",
        "https://www.indeed.com/jobs?q=engineer",
        "https://www.glassdoor.com/Job/index.htm",
        "https://www.linkedin.com/jobs/",
    ):
        assert registry.detect_url_matches(url) == ()
    for denied in ("indeed", "glassdoor", "linkedin", "wellfound"):
        assert denied not in BOARD_URL_PULL_PROVIDERS
        assert denied not in BOARD_JOB_PROVIDERS
    for candidate in (
        "smartrecruiters",
        "recruitee",
        "icims",
        "jobvite",
        "jazzhr",
    ):
        assert candidate not in BOARD_URL_PULL_PROVIDERS
        assert candidate not in BOARD_JOB_PROVIDERS
