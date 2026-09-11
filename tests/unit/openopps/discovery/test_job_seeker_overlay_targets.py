from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.models import ChannelBudget, ChannelProfile
from openopps.discovery.targeted_ats import enumerate_targeted_ats_channel
from openopps.discovery.transport import validate_public_locator
from openopps.providers.sources.overlay_targets import (
    load_overlay_targets,
    overlay_json_path,
)


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_OVERLAY_DOCUMENT = {
    "version": 1,
    "outcomes": [
        "duplicate",
        "fetchable_packaged",
        "no_public_ats",
        "policy_blocked",
    ],
    "core": [
        {
            "id": "zeta",
            "name": "Zeta",
            "locator": "https://jobs.lever.co/zeta",
            "claimed_provider_hint": "lever",
        }
    ],
    "expand": [
        {
            "id": "acme",
            "name": "Acme",
            "locator": "https://boards.greenhouse.io/acme",
        }
    ],
    "b_tier": [
        {
            "id": "beta",
            "name": "Beta",
            "locator": "https://jobs.ashbyhq.com/beta",
        },
    ],
    "growth": [],
}


def _write_goal_overlay(root: Path) -> Path:
    path = root / "goals" / "expand-job-seeker-coverage" / "overlay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_OVERLAY_DOCUMENT, indent=2), encoding="utf-8")
    return path


def _budget() -> ChannelBudget:
    return ChannelBudget(
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
    )


def test_overlay_targets_are_sorted_unique(tmp_path: Path) -> None:
    overlay = _write_goal_overlay(tmp_path)
    start = tmp_path / "src" / "openopps" / "providers" / "sources" / "module.py"
    start.parent.mkdir(parents=True)
    start.write_text("", encoding="utf-8")
    resolved = overlay_json_path(start=start)
    assert resolved == overlay
    targets = load_overlay_targets(overlay_path=resolved)
    identities = tuple(item.target_id for item in targets)
    assert identities == tuple(sorted(set(identities)))
    assert identities == ("acme", "beta", "zeta")
    assert targets[0].public_page_locator == "https://boards.greenhouse.io/acme"
    assert targets[1].public_page_locator == "https://jobs.ashbyhq.com/beta"
    assert targets[2].public_page_locator == "https://jobs.lever.co/zeta"
    assert targets[2].claimed_provider_hint == "lever"


def test_enumerate_targeted_ats_accepts_overlay_subset_without_network(
    tmp_path: Path,
) -> None:
    overlay = _write_goal_overlay(tmp_path)
    targets = load_overlay_targets(overlay_path=overlay)
    subset = targets[:2]
    seed_ids = tuple(item.target_id for item in subset)
    origins = tuple(
        sorted(
            {
                validate_public_locator(item.public_page_locator).origin
                for item in subset
            }
        )
    )
    page_html = b"<!doctype html><html><body><p>Board</p></body></html>"
    receipt = enumerate_targeted_ats_channel(
        profile=ChannelProfile(
            channel="targeted_ats",
            budget=_budget(),
            seed_ids=seed_ids,
            allowed_origins=origins,
            allowed_query_keys=("board",),
            parser_ids=("html-links-v1",),
        ),
        targets=subset,
        observations=tuple(
            CapturedObservation(
                locator=item.public_page_locator,
                status_code=200,
                body=page_html,
                media_type="text/html",
            )
            for item in subset
        ),
        observed_at=OBSERVED_AT,
    )
    assert seed_ids == ("acme", "beta")
    assert receipt.operation_outcomes == ("succeeded", "succeeded")
    providers = {
        item.occurrence_id.split(":")[1]: item.identity.provider_id
        for item in receipt.occurrences
        if item.occurrence_id.endswith("supported")
    }
    assert providers == {"acme": "greenhouse", "beta": "ashbyhq"}
    assert all(
        item.identity.provider_token is not None for item in receipt.occurrences
    )


def test_shipped_overlay_json_loads_core_and_expand() -> None:
    path = overlay_json_path()
    assert path is not None
    targets = load_overlay_targets(overlay_path=path)
    ids = {item.target_id for item in targets}
    assert "stripe" in ids
    assert "figma" in ids
    assert len(ids) >= 62
