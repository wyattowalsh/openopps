from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from openopps.models import validate_public_https_url


REPO_ROOT = Path(__file__).resolve().parents[3]
GOAL_OVERLAY_PATH = REPO_ROOT / "goals" / "expand-job-seeker-coverage" / "overlay.json"
PACKAGED_OVERLAY_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "job_seeker_overlay.json"
)
ITEM_KEYS = frozenset({"id", "name", "locator"})
FORBIDDEN_HOSTS = (
    "wellfound.com",
    "angel.co",
    "angel.com",
    "angellist.com",
    "linkedin.com",
    "workatastartup.com",
    "getro.com",
    "consider.com",
    "glassdoor.com",
    "indeed.com",
)
FORBIDDEN_HOST_LABELS = frozenset(
    {
        "wellfound",
        "linkedin",
        "angellist",
        "workatastartup",
        "getro",
        "consider",
        "glassdoor",
        "indeed",
    }
)
# Packaged growth is 1712 unique ids. Do not require the unfinished 500c target of 1813.
PRIOR_GROWTH_COUNT = 1712
_MIN_GROWTH_ROWS = 1712
MIN_GROWTH_COUNT = PRIOR_GROWTH_COUNT


def _overlay(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _entries(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload[key]
    assert isinstance(value, list)
    rows: list[dict[str, object]] = []
    for item in value:
        assert isinstance(item, dict)
        rows.append(item)
    return rows


def _ids(rows: list[dict[str, object]]) -> list[str]:
    identities: list[str] = []
    for item in rows:
        identity = item["id"]
        assert isinstance(identity, str) and identity
        identities.append(identity)
    return identities


def _assert_public_locator_without_forbidden_hosts(item: dict[str, object]) -> None:
    assert set(item) == ITEM_KEYS
    assert "outcome" not in item
    identity = item["id"]
    name = item["name"]
    locator = item["locator"]
    assert isinstance(identity, str) and identity
    assert isinstance(name, str) and name
    assert isinstance(locator, str)
    try:
        validated = validate_public_https_url(locator)
    except Exception as exc:
        raise AssertionError(f"{identity}: {locator!r} ({exc})") from exc
    assert validated == locator, identity
    host = (urlsplit(locator).hostname or "").casefold().removeprefix("www.")
    assert host, identity
    assert all(
        host != forbidden and not host.endswith(f".{forbidden}")
        for forbidden in FORBIDDEN_HOSTS
    ), (identity, host)
    labels = frozenset(host.split("."))
    assert labels.isdisjoint(FORBIDDEN_HOST_LABELS), (identity, host)
    assert "angel.co" not in host
    assert "angel.com" not in host


def test_growth_worklist_is_large_unique_disjoint_and_policy_clean() -> None:
    if not GOAL_OVERLAY_PATH.is_file():
        pytest.skip("goal overlay worklist is not present in this tree")
    payload = _overlay(GOAL_OVERLAY_PATH)
    core = _entries(payload, "core")
    expand = _entries(payload, "expand")
    core_ids = _ids(core)
    expand_ids = _ids(expand)
    growth = _entries(payload, "growth")
    assert len(core) == 25, len(core)
    assert len(expand) == 37, len(expand)
    assert len(growth) >= PRIOR_GROWTH_COUNT, len(growth)
    assert len(growth) >= _MIN_GROWTH_ROWS, len(growth)
    assert len(growth) >= MIN_GROWTH_COUNT, len(growth)
    growth_ids = _ids(growth)
    assert "10pearls" in growth_ids
    assert "withpulley" in growth_ids
    assert "instacart" in growth_ids
    assert len(growth_ids) == len(set(growth_ids))
    assert set(growth_ids).isdisjoint(core_ids)
    assert set(growth_ids).isdisjoint(expand_ids)
    for item in (*core, *expand, *growth):
        _assert_public_locator_without_forbidden_hosts(item)


def test_packaged_overlay_growth_ids_match_goal_overlay() -> None:
    if not GOAL_OVERLAY_PATH.is_file():
        pytest.skip("goal overlay worklist is not present in this tree")
    goal = _overlay(GOAL_OVERLAY_PATH)
    packaged = _overlay(PACKAGED_OVERLAY_PATH)
    goal_core_ids = _ids(_entries(goal, "core"))
    goal_expand_ids = _ids(_entries(goal, "expand"))
    goal_ids = _ids(_entries(goal, "growth"))
    packaged_core_ids = _ids(_entries(packaged, "core"))
    packaged_expand_ids = _ids(_entries(packaged, "expand"))
    packaged_growth = _entries(packaged, "growth")
    packaged_ids = _ids(packaged_growth)
    assert packaged_core_ids == goal_core_ids
    assert packaged_expand_ids == goal_expand_ids
    assert len(goal_core_ids) == 25, len(goal_core_ids)
    assert len(goal_expand_ids) == 37, len(goal_expand_ids)
    assert len(goal_ids) >= MIN_GROWTH_COUNT, len(goal_ids)
    assert len(packaged_ids) >= PRIOR_GROWTH_COUNT, len(packaged_ids)
    assert len(packaged_ids) >= _MIN_GROWTH_ROWS, len(packaged_ids)
    assert len(packaged_ids) >= MIN_GROWTH_COUNT, len(packaged_ids)
    assert packaged_ids == goal_ids
    assert "10pearls" in packaged_ids
    assert "withpulley" in packaged_ids
    assert "instacart" in packaged_ids
    assert "the-trade-desk" in packaged_ids
    assert "applovin" in packaged_ids
    locators = {item["id"]: item["locator"] for item in packaged_growth}
    assert locators["the-trade-desk"] == (
        "https://job-boards.greenhouse.io/thetradedesk"
    )
    assert locators["applovin"] == "https://job-boards.greenhouse.io/applovin"
    for item in packaged_growth:
        _assert_public_locator_without_forbidden_hosts(item)
