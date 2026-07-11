from pathlib import Path

from openopps.enrichment import enrich_metadata
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

from _fixtures.store import seeded_enrichment_store as seeded_store


def test_enrich_metadata_dry_run_reports_changes_without_mutating(tmp_path: Path):
    store = seeded_store(tmp_path)

    summary = enrich_metadata(store, apply=False).as_dict()
    board = store.get_board("acme")

    assert summary["checkedBoards"] == 1
    assert summary["boardChangeCount"] == 1
    assert summary["routeChangeCount"] == 1
    assert summary["applied"] is False
    assert board is not None
    assert board.website_url is None
    assert board.raw_payload["description"] == "Builds developer infrastructure."


def test_enrich_metadata_apply_promotes_payload_fields(tmp_path: Path):
    store = seeded_store(tmp_path)

    summary = enrich_metadata(store, apply=True).as_dict()
    board = store.get_board("acme")
    route = store.list_board_providers(board_key="acme")[0]

    assert summary["applied"] is True
    assert board is not None
    assert board.website_url == "https://www.acme.com"
    assert board.domain == "acme.com"
    assert board.description == "Builds developer infrastructure."
    assert board.markets == ["Developer Tools"]
    assert board.locations == ["San Francisco"]
    assert board.staff_count == 42
    assert board.num_jobs_hint == 3
    assert board.raw_payload["website"] == {"url": "https://www.acme.com"}
    assert route.label == "SmartRecruiters"
    assert route.count_hint == 3
    assert route.board_url == "https://jobs.smartrecruiters.com/Acme"


def test_enrich_metadata_ignores_invalid_payload_website(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="getro", url="https://jobs.example.com", provider_id="getro")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="getro:media-co",
                source_key="getro",
                remote_id="media-co",
                name="Media Co",
                raw_payload={
                    "domain": '[\n\t"Entertainment",\n\t"Broadcast Media"\n]',
                    "website": {"url": '[\n\t"Entertainment",\n\t"Broadcast Media"\n]'},
                },
            )
        ]
    )

    summary = enrich_metadata(store, apply=True).as_dict()
    board = store.get_board("getro:media-co")

    assert summary["applied"] is True
    assert summary["boardChangeCount"] == 0
    assert board is not None
    assert board.domain is None
    assert board.website_url is None
