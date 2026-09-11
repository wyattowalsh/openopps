from __future__ import annotations

from collections import Counter

from openopps.models import ProviderSupport
from openopps.providers.base import ProviderDefinition, ProviderKind, ProviderRouteMatch
from openopps.providers.registry import ProviderRegistry
from openopps.providers.sources import overlay_outcomes as overlay_outcomes_module
from openopps.providers.sources.overlay_outcomes import (
    OverlayOutcome,
    OverlayWorklistEntry,
    YcPublicAtsBoard,
    classify_overlay_locator,
    load_overlay_worklist,
    overlay_worklist_outcomes,
)

_OVERLAY_TIERS = frozenset({"core", "expand", "growth"})
_HTML_CAREERS_URL = "https://www.janestreet.com/careers"
_GREENHOUSE_URL = "https://boards.greenhouse.io/stripe"


def test_overlay_outcome_enum_is_closed() -> None:
    assert {item.value for item in OverlayOutcome} == {
        "fetchable_packaged",
        "no_public_ats",
        "duplicate",
        "policy_blocked",
    }


def test_every_core_expand_and_growth_id_has_exactly_one_outcome() -> None:
    worklist = load_overlay_worklist()
    assert worklist
    tiers = {entry.tier for entry in worklist}
    assert _OVERLAY_TIERS <= tiers
    ids = tuple(entry.overlay_id for entry in worklist)
    assert len(ids) == len(set(ids))
    outcomes = overlay_worklist_outcomes(worklist)
    assert set(outcomes) == set(ids)
    assert len(outcomes) == len(worklist)
    for overlay_id in ids:
        assert outcomes[overlay_id] in OverlayOutcome
    counts = Counter(outcome.value for outcome in outcomes.values())
    assert set(counts) <= {item.value for item in OverlayOutcome}
    assert sum(counts.values()) == len(worklist)
    growth_ids = tuple(
        entry.overlay_id for entry in worklist if entry.tier == "growth"
    )
    assert growth_ids
    assert all(outcomes[overlay_id] in OverlayOutcome for overlay_id in growth_ids)


def test_html_careers_without_ats_host_are_no_public_ats() -> None:
    assert (
        classify_overlay_locator(_HTML_CAREERS_URL)
        is OverlayOutcome.NO_PUBLIC_ATS
    )
    assert (
        classify_overlay_locator("https://careers.valve.com/")
        is OverlayOutcome.NO_PUBLIC_ATS
    )


def test_greenhouse_url_is_fetchable_packaged() -> None:
    assert classify_overlay_locator(_GREENHOUSE_URL) is OverlayOutcome.FETCHABLE_PACKAGED
    assert (
        classify_overlay_locator("https://job-boards.greenhouse.io/anthropic")
        is OverlayOutcome.FETCHABLE_PACKAGED
    )


def test_policy_blocked_locator_hosts() -> None:
    blocked = (
        "https://wellfound.com/company/acme/jobs",
        "https://angel.co/company/acme",
        "https://www.linkedin.com/company/acme/jobs",
        "https://www.workatastartup.com/companies/acme",
        "https://www.indeed.com/cmp/acme/jobs",
        "https://www.glassdoor.com/Jobs/acme-jobs-SRCH.htm",
    )
    for locator in blocked:
        assert classify_overlay_locator(locator) is OverlayOutcome.POLICY_BLOCKED


def test_duplicate_when_yc_board_has_the_same_public_ats_token() -> None:
    yc_boards = (
        YcPublicAtsBoard(company_id="stripe", name="Stripe", token="stripe"),
    )
    assert (
        classify_overlay_locator(
            _GREENHOUSE_URL,
            overlay_id="stripe",
            overlay_name="Stripe",
            yc_boards=yc_boards,
        )
        is OverlayOutcome.DUPLICATE
    )
    assert (
        classify_overlay_locator(
            _GREENHOUSE_URL,
            overlay_id="stripe",
            overlay_name="Stripe",
            yc_boards=(
                YcPublicAtsBoard(company_id="stripe", name="Stripe", token="other"),
            ),
        )
        is OverlayOutcome.FETCHABLE_PACKAGED
    )


def test_does_not_invent_an_ats_token_from_a_bare_company_domain() -> None:
    assert (
        classify_overlay_locator("https://stripe.com") is OverlayOutcome.NO_PUBLIC_ATS
    )


def test_detect_only_route_match_is_not_fetchable_packaged() -> None:
    registry = ProviderRegistry(
        [
            ProviderDefinition(
                id="detect-only",
                label="Detect Only",
                kind=ProviderKind.BOARD_PROVIDER,
                support_level=ProviderSupport.DETECT,
                description="Detect-only fixture.",
                route_detector=lambda _url: ProviderRouteMatch(token="acme"),
            )
        ]
    )
    assert (
        classify_overlay_locator(
            "https://careers.example.test/acme",
            registry=registry,
        )
        is OverlayOutcome.NO_PUBLIC_ATS
    )


def test_facts_fallback_covers_core_and_expand_when_json_is_missing(
    tmp_path,
) -> None:
    missing = tmp_path / "overlay.json"
    facts = tmp_path / "facts.md"
    facts.write_text(
        "- Overlay core names are Stripe, and OpenAI.\n"
        "- Overlay B-tier names are Figma, and Grafana Labs.\n",
        encoding="utf-8",
    )
    entries = load_overlay_worklist(overlay_json=missing, facts_path=facts)
    assert [(entry.overlay_id, entry.tier, entry.locator) for entry in entries] == [
        ("stripe", "core", ""),
        ("openai", "core", ""),
        ("figma", "expand", ""),
        ("grafana", "expand", ""),
    ]
    outcomes = overlay_worklist_outcomes(entries)
    assert outcomes == {
        "stripe": OverlayOutcome.NO_PUBLIC_ATS,
        "openai": OverlayOutcome.NO_PUBLIC_ATS,
        "figma": OverlayOutcome.NO_PUBLIC_ATS,
        "grafana": OverlayOutcome.NO_PUBLIC_ATS,
    }


def test_injected_worklist_records_one_outcome_per_id() -> None:
    entries = (
        OverlayWorklistEntry(
            overlay_id="stripe",
            name="Stripe",
            locator=_GREENHOUSE_URL,
            tier="core",
        ),
        OverlayWorklistEntry(
            overlay_id="jane-street",
            name="Jane Street",
            locator=_HTML_CAREERS_URL,
            tier="core",
        ),
    )
    outcomes = overlay_worklist_outcomes(entries)
    assert outcomes == {
        "stripe": OverlayOutcome.FETCHABLE_PACKAGED,
        "jane-street": OverlayOutcome.NO_PUBLIC_ATS,
    }


def test_overlay_outcomes_module_does_not_register_source_records() -> None:
    assert not hasattr(overlay_outcomes_module, "SOURCE_RECORDS")
