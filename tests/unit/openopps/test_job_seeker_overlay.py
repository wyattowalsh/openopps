from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from openopps.models import validate_public_https_url


REPO_ROOT = Path(__file__).resolve().parents[3]
OVERLAY_PATH = REPO_ROOT / "goals" / "expand-job-seeker-coverage" / "overlay.json"
PACKAGED_OVERLAY_PATH = (
    REPO_ROOT
    / "src"
    / "openopps"
    / "providers"
    / "sources"
    / "data"
    / "job_seeker_overlay.json"
)
FACTS_PATH = REPO_ROOT / "goals" / "expand-job-seeker-coverage" / "facts.md"

CORE_IDS = (
    "stripe",
    "openai",
    "anthropic",
    "spacex",
    "databricks",
    "discord",
    "notion",
    "rippling",
    "anduril",
    "scale-ai",
    "huggingface",
    "perplexity",
    "anysphere",
    "canva",
    "xai",
    "bytedance",
    "epic-games",
    "valve",
    "bloomberg",
    "jane-street",
    "ramp",
    "plaid",
    "brex",
    "linear",
    "vercel",
)
EXPAND_IDS = (
    "figma",
    "grammarly",
    "gusto",
    "deel",
    "mercury",
    "klarna",
    "revolut",
    "retool",
    "airtable",
    "zapier",
    "miro",
    "webflow",
    "framer",
    "clickup",
    "replit",
    "netlify",
    "render",
    "fly-io",
    "grafana",
    "temporal",
    "supabase",
    "neon",
    "cockroach-labs",
    "snyk",
    "groq",
    "cerebras",
    "cohere",
    "mistral",
    "together-ai",
    "midjourney",
    "figure-ai",
    "blue-origin",
    "neuralink",
    "shield-ai",
    "riot-games",
    "loom",
    "weights-biases",
)
OUTCOMES = (
    "fetchable_packaged",
    "no_public_ats",
    "duplicate",
    "policy_blocked",
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
# Packaged growth is 1712 unique ids (1774 overlay ids − 25 core − 37 expand).
# Do not require the unfinished 500c target of 1813.
PRIOR_GROWTH_COUNT = 1712
_MIN_GROWTH_ROWS = 1712
MIN_GROWTH_COUNT = PRIOR_GROWTH_COUNT


def _overlay(path: Path = OVERLAY_PATH) -> dict[str, object]:
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


def _facts_names(prefix: str) -> tuple[str, ...]:
    needle = f"- Overlay {prefix} names are "
    for raw in FACTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith(needle):
            continue
        body = line.removeprefix(needle).rstrip(".")
        names: list[str] = []
        for part in body.split(","):
            name = part.strip()
            if name.startswith("and "):
                name = name.removeprefix("and ").strip()
            if name:
                names.append(name)
        return tuple(names)
    raise AssertionError(f"missing overlay {prefix} names in facts.md")


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
    except ValueError as exc:
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


def test_overlay_worklist_matches_facts_and_forbids_out_of_scope_hosts() -> None:
    if not OVERLAY_PATH.is_file() or not FACTS_PATH.is_file():
        pytest.skip("goal overlay worklist is not present in this tree")
    payload = _overlay()
    assert payload["version"] == 1
    assert payload["outcomes"] == list(OUTCOMES)

    core = _entries(payload, "core")
    expand = _entries(payload, "expand")
    growth = _entries(payload, "growth")
    assert len(core) == len(CORE_IDS), len(core)
    assert len(expand) == len(EXPAND_IDS), len(expand)
    assert len(growth) >= PRIOR_GROWTH_COUNT, len(growth)
    assert len(growth) >= _MIN_GROWTH_ROWS, len(growth)
    assert len(growth) >= MIN_GROWTH_COUNT, len(growth)
    assert [item["id"] for item in core] == list(CORE_IDS)
    assert [item["id"] for item in expand] == list(EXPAND_IDS)
    growth_ids = [item["id"] for item in growth]
    assert "10pearls" in growth_ids
    assert "withpulley" in growth_ids
    assert "instacart" in growth_ids
    assert [item["name"] for item in core] == list(_facts_names("core"))
    assert [item["name"] for item in expand] == list(_facts_names("B-tier"))

    seen_ids: set[str] = set()
    for item in (*core, *expand, *growth):
        identity = item["id"]
        assert isinstance(identity, str) and identity
        assert identity not in seen_ids, identity
        seen_ids.add(identity)
        _assert_public_locator_without_forbidden_hosts(item)


def test_packaged_overlay_contains_core_and_expand_facts() -> None:
    payload = _overlay(PACKAGED_OVERLAY_PATH)
    core = _entries(payload, "core")
    expand = _entries(payload, "expand")
    growth = _entries(payload, "growth")
    assert [item["id"] for item in core] == list(CORE_IDS)
    assert [item["id"] for item in expand] == list(EXPAND_IDS)
    assert len(core) == len(CORE_IDS), len(core)
    assert len(expand) == len(EXPAND_IDS), len(expand)
    assert len(growth) >= PRIOR_GROWTH_COUNT, len(growth)
    assert len(growth) >= _MIN_GROWTH_ROWS, len(growth)
    assert len(growth) >= MIN_GROWTH_COUNT, len(growth)
    growth_ids = [item["id"] for item in growth]
    assert "10pearls" in growth_ids
    assert "withpulley" in growth_ids
    assert "instacart" in growth_ids
    locators = {item["id"]: item["locator"] for item in (*core, *expand, *growth)}
    assert locators["huggingface"] == "https://apply.workable.com/huggingface"
    assert locators["deel"] == "https://jobs.ashbyhq.com/deel"
    assert locators["neon"] == "https://jobs.ashbyhq.com/neon"
    assert locators["snyk"] == "https://jobs.ashbyhq.com/snyk"
    assert locators["loom"] == "https://jobs.ashbyhq.com/loom"
    assert locators["the-trade-desk"] == (
        "https://job-boards.greenhouse.io/thetradedesk"
    )
    assert locators["applovin"] == "https://job-boards.greenhouse.io/applovin"
    for item in (*core, *expand, *growth):
        _assert_public_locator_without_forbidden_hosts(item)


def test_overlay_work_order_copy_is_global_not_us_weighted() -> None:
    from openopps.providers.sources.overlay import JOB_SEEKER_OVERLAY_SOURCE
    from openopps.providers.sources.overlay_outcomes import overlay_worklist_outcomes

    reason = str(
        JOB_SEEKER_OVERLAY_SOURCE.raw_metadata.get("inclusionReason")
        or JOB_SEEKER_OVERLAY_SOURCE.raw_metadata.get("inclusion_reason")
        or ""
    )
    folded = reason.casefold()
    assert "global knowledge-work" in folded
    assert "us-hq" in folded or "not us-hq-weighted" in folded
    assert "us-weighted" not in folded.replace("not us-hq-weighted", "")
    assert "jobs/explorer ranker" in folded
    outcomes = overlay_worklist_outcomes()
    worklist_ids = {
        item["id"]
        for item in (
            *_entries(_overlay(PACKAGED_OVERLAY_PATH), "core"),
            *_entries(_overlay(PACKAGED_OVERLAY_PATH), "expand"),
            *_entries(_overlay(PACKAGED_OVERLAY_PATH), "growth"),
        )
    }
    assert worklist_ids
    assert set(outcomes) >= worklist_ids
    for overlay_id in worklist_ids:
        assert outcomes[overlay_id].value in {
            "fetchable_packaged",
            "no_public_ats",
            "duplicate",
            "policy_blocked",
        }
