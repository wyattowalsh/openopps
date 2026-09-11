from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from openopps.models import ProviderSupport
from openopps.providers.sources import BOARD_SOURCE_ADAPTERS, BOARD_SOURCE_CATALOG
from openopps.providers.sources import overlay as overlay_module
from openopps.providers.sources.overlay import (
    JOB_SEEKER_OVERLAY_SOURCE,
    JOB_SEEKER_OVERLAY_SOURCE_KEY,
    JobSeekerOverlaySourceAdapter,
    SOURCE_RECORDS,
    load_packaged_overlay_entries,
)
from openopps.settings import OpenOppsSettings
from openopps.source_scope import OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS
from openopps.utils import source_board_key


REPO_ROOT = Path(__file__).resolve().parents[3]
GOAL_OVERLAY_PATH = REPO_ROOT / "goals" / "expand-job-seeker-coverage" / "overlay.json"
DENIED_SOURCE_KEYS = frozenset(
    {
        "wellfound",
        "angel",
        "linkedin",
        "workatastartup",
        "work-at-a-startup",
        "work_at_a_startup",
    }
)
_GREENHOUSE_FIXTURE_URL = "https://job-boards.greenhouse.io/acme"
_CAREERS_FIXTURE_URL = "https://www.valvesoftware.com/en/jobs"


def _reject_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network: {request.method} {request.url}")


async def _iter_boards(source=JOB_SEEKER_OVERLAY_SOURCE):
    adapter = JobSeekerOverlaySourceAdapter(OpenOppsSettings())
    transport = httpx.MockTransport(_reject_network)
    async with httpx.AsyncClient(transport=transport) as client:
        pages = [
            page async for page in adapter.iter_boards(client, source, page_size=25)
        ]
    assert len(pages) == 1
    return pages[0]


def test_board_source_catalog_contains_job_seeker_overlay() -> None:
    assert JOB_SEEKER_OVERLAY_SOURCE_KEY in BOARD_SOURCE_CATALOG
    record = BOARD_SOURCE_CATALOG[JOB_SEEKER_OVERLAY_SOURCE_KEY]
    assert record is JOB_SEEKER_OVERLAY_SOURCE
    assert SOURCE_RECORDS == (JOB_SEEKER_OVERLAY_SOURCE,)
    assert record.provider_id == "job_seeker_overlay"
    assert record.raw_metadata["licenseStatus"] == "needs_review"
    assert record.provider_id in BOARD_SOURCE_ADAPTERS
    assert BOARD_SOURCE_ADAPTERS[record.provider_id] is JobSeekerOverlaySourceAdapter


def test_denied_startup_source_keys_are_absent() -> None:
    assert DENIED_SOURCE_KEYS.isdisjoint(BOARD_SOURCE_CATALOG)
    assert OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS.isdisjoint(BOARD_SOURCE_CATALOG)


def test_packaged_overlay_json_is_a_copy_of_the_goal_worklist() -> None:
    if not GOAL_OVERLAY_PATH.is_file():
        pytest.skip("goal overlay worklist is not present in this tree")
    goal = json.loads(GOAL_OVERLAY_PATH.read_text(encoding="utf-8"))
    payload = json.loads(
        Path(overlay_module.__file__)
        .resolve()
        .parent.joinpath("data", "job_seeker_overlay.json")
        .read_text(encoding="utf-8")
    )
    assert payload == goal
    entries = load_packaged_overlay_entries()
    assert any(entry["tier"] == "core" for entry in entries)
    assert any(entry["tier"] == "expand" for entry in entries)


@pytest.mark.asyncio
async def test_adapter_yields_greenhouse_provider_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        overlay_module,
        "load_packaged_overlay_entries",
        lambda: (
            {
                "id": "acme",
                "name": "Acme",
                "locator": _GREENHOUSE_FIXTURE_URL,
                "tier": "core",
            },
            {
                "id": "valve",
                "name": "Valve",
                "locator": _CAREERS_FIXTURE_URL,
                "tier": "core",
            },
        ),
    )
    boards, providers, meta = await _iter_boards()
    boards_by_id = {board.remote_id: board for board in boards}
    providers_by_board = {route.board_key: route for route in providers}
    acme = boards_by_id["acme"]
    valve = boards_by_id["valve"]
    assert meta["total"] == 2
    assert acme.key == source_board_key(JOB_SEEKER_OVERLAY_SOURCE_KEY, "acme")
    route = providers_by_board[acme.key]
    assert route.provider_id == "greenhouse"
    assert route.token == "acme"
    assert route.board_url == _GREENHOUSE_FIXTURE_URL
    assert route.support_level == ProviderSupport.JOBS
    assert valve.key not in providers_by_board
    assert len(providers) == 1


@pytest.mark.asyncio
async def test_packaged_overlay_attaches_jobs_capable_routes_offline() -> None:
    boards, providers, meta = await _iter_boards()
    boards_by_id = {board.remote_id: board for board in boards}
    providers_by_board = {route.board_key: route for route in providers}
    assert meta["total"] == len(boards) == len(load_packaged_overlay_entries())
    stripe = boards_by_id["stripe"]
    valve = boards_by_id["valve"]
    huggingface = boards_by_id["huggingface"]
    stripe_route = providers_by_board[stripe.key]
    assert stripe_route.provider_id == "greenhouse"
    assert stripe_route.token == "stripe"
    assert stripe_route.support_level == ProviderSupport.JOBS
    huggingface_route = providers_by_board[huggingface.key]
    assert huggingface_route.provider_id == "workable"
    assert huggingface_route.token == "huggingface"
    assert huggingface_route.support_level == ProviderSupport.JOBS
    assert valve.key not in providers_by_board
