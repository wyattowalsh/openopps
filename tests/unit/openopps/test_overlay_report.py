from __future__ import annotations

import ast
from pathlib import Path

from openopps.overlay_report import overlay_outcomes_report
from openopps.providers.sources.overlay_outcomes import (
    OverlayOutcome,
    OverlayWorklistEntry,
    load_overlay_worklist,
)


ROOT = Path(__file__).resolve().parents[3]
_PACKAGED_STRIPE = OverlayWorklistEntry(
    overlay_id="stripe",
    name="Stripe",
    locator="https://job-boards.greenhouse.io/stripe",
    tier="core",
)
_PACKAGED_OVERLAY_JSON = (
    ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "job_seeker_overlay.json"
)
_EPHEMERAL_URL_PULL = {
    "kind": "url-pull",
    "source_key": "url-pull",
    "url": "https://job-boards.greenhouse.io/openopps-ephemeral-not-packaged",
    "jobs": (
        {"id": "ephemeral-1", "title": "Engineer"},
        {"id": "ephemeral-2", "title": "Designer"},
    ),
    "success": True,
}
_SCOUT_CANDIDATE = {
    "kind": "scout",
    "source_key": "discovery",
    "candidate": {
        "id": "scout-candidate-acme",
        "locator": "https://jobs.ashbyhq.com/quarantined-not-packaged",
        "quarantined": True,
    },
}


def test_overlay_outcomes_report_conserves_closed_classes_and_growth_tier() -> None:
    entries = (
        OverlayWorklistEntry(
            overlay_id="stripe",
            name="Stripe",
            locator="https://job-boards.greenhouse.io/stripe",
            tier="core",
        ),
        OverlayWorklistEntry(
            overlay_id="valve",
            name="Valve",
            locator="https://www.valvesoftware.com/en/jobs",
            tier="expand",
        ),
        OverlayWorklistEntry(
            overlay_id="blocked",
            name="Blocked",
            locator="https://www.linkedin.com/company/blocked/jobs",
            tier="growth",
        ),
        OverlayWorklistEntry(
            overlay_id="careers-html",
            name="Careers HTML",
            locator="https://www.janestreet.com/careers",
            tier="growth",
        ),
    )

    payload = overlay_outcomes_report(entries)

    assert payload["schemaVersion"] == 1
    assert payload["entryCount"] == 4
    outcomes = payload["outcomes"]
    assert set(outcomes) == {item.value for item in OverlayOutcome}
    assert sum(outcomes.values()) == 4
    assert outcomes["fetchable_packaged"] == 1
    assert outcomes["policy_blocked"] == 1
    assert outcomes["no_public_ats"] == 2
    assert outcomes["duplicate"] == 0
    growth = payload["byTier"]["growth"]
    assert growth["policy_blocked"] == 1
    assert growth["no_public_ats"] == 1
    assert payload["byTier"]["core"]["fetchable_packaged"] == 1
    assert payload["byTier"]["expand"]["no_public_ats"] == 1


def test_packaged_overlay_outcomes_conserve_core_expand_and_growth() -> None:
    worklist = load_overlay_worklist()
    payload = overlay_outcomes_report(worklist)
    closed = {item.value for item in OverlayOutcome}
    by_tier = payload["byTier"]

    assert payload["entryCount"] == len(worklist)
    assert set(payload["outcomes"]) == closed
    assert sum(payload["outcomes"].values()) == len(worklist)
    assert set(by_tier) >= {"core", "expand", "growth"}
    assert sum(by_tier["core"].values()) > 0
    assert sum(by_tier["expand"].values()) > 0
    assert sum(by_tier["growth"].values()) > 0
    assert sum(sum(counts.values()) for counts in by_tier.values()) == len(worklist)


def test_overlay_report_does_not_import_discovery() -> None:
    tree = ast.parse(
        (ROOT / "src" / "openopps" / "overlay_report.py").read_text(encoding="utf-8")
    )
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert not any(
        name == "openopps.discovery" or name.startswith("openopps.discovery.")
        for name in names
    )


def test_packaged_gain_exclusions_include_url_pull_and_scout() -> None:
    from openopps.overlay_report import PACKAGED_GAIN_EXCLUSIONS

    names = {str(item).casefold() for item in PACKAGED_GAIN_EXCLUSIONS}
    assert "url-pull" in names
    assert "scout" in names
    assert "url_pull" in names
    assert "discovery" in names


def test_ephemeral_url_pull_success_does_not_increment_packaged_overlay_totals() -> None:
    from openopps.overlay_report import PACKAGED_GAIN_EXCLUSIONS, packaged_overlay_gain

    names = {str(item).casefold() for item in PACKAGED_GAIN_EXCLUSIONS}
    assert "url-pull" in names
    before_overlay = _PACKAGED_OVERLAY_JSON.read_bytes()
    entries = (_PACKAGED_STRIPE,)
    baseline = overlay_outcomes_report(entries)
    after = packaged_overlay_gain(
        entries,
        extra_sources=(_EPHEMERAL_URL_PULL,),
    )

    assert after["entryCount"] == baseline["entryCount"] == 1
    assert after["outcomes"]["fetchable_packaged"] == (
        baseline["outcomes"]["fetchable_packaged"]
    )
    assert after["outcomes"]["fetchable_packaged"] == 1
    assert after["byTier"]["core"]["fetchable_packaged"] == (
        baseline["byTier"]["core"]["fetchable_packaged"]
    )
    assert _PACKAGED_OVERLAY_JSON.read_bytes() == before_overlay


def test_scout_candidate_does_not_count_as_packaged_gain() -> None:
    from openopps.overlay_report import PACKAGED_GAIN_EXCLUSIONS, packaged_overlay_gain

    names = {str(item).casefold() for item in PACKAGED_GAIN_EXCLUSIONS}
    assert "scout" in names
    entries = (_PACKAGED_STRIPE,)
    baseline = overlay_outcomes_report(entries)
    after = packaged_overlay_gain(
        entries,
        extra_sources=(_SCOUT_CANDIDATE,),
    )

    assert after["entryCount"] == baseline["entryCount"]
    assert after["outcomes"]["fetchable_packaged"] == (
        baseline["outcomes"]["fetchable_packaged"]
    )
    assert after["outcomes"]["fetchable_packaged"] == 1
    assert after["byTier"]["core"]["fetchable_packaged"] == 1


def test_converted_html_and_new_growth_ats_locators_are_fetchable_packaged() -> None:
    payload = overlay_outcomes_report(
        (
            OverlayWorklistEntry(
                overlay_id="huggingface",
                name="Hugging Face",
                locator="https://apply.workable.com/huggingface",
                tier="core",
            ),
            OverlayWorklistEntry(
                overlay_id="deel",
                name="Deel",
                locator="https://jobs.ashbyhq.com/deel",
                tier="expand",
            ),
            OverlayWorklistEntry(
                overlay_id="the-trade-desk",
                name="The Trade Desk",
                locator="https://job-boards.greenhouse.io/thetradedesk",
                tier="growth",
            ),
            OverlayWorklistEntry(
                overlay_id="applovin",
                name="AppLovin",
                locator="https://job-boards.greenhouse.io/applovin",
                tier="growth",
            ),
        )
    )

    assert payload["entryCount"] == 4
    assert payload["outcomes"]["fetchable_packaged"] == 4
    assert payload["byTier"]["core"]["fetchable_packaged"] == 1
    assert payload["byTier"]["expand"]["fetchable_packaged"] == 1
    assert payload["byTier"]["growth"]["fetchable_packaged"] == 2
    assert payload["byFamily"]["workable"]["fetchable_packaged"] == 1
    assert payload["byFamily"]["ashbyhq"]["fetchable_packaged"] == 1
    assert payload["byFamily"]["greenhouse"]["fetchable_packaged"] == 2
