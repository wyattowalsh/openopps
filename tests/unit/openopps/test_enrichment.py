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


def seeded_store(tmp_path: Path) -> OpenOppsStore:
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme",
                raw_payload={
                    "website": {"url": "https://www.acme.com"},
                    "description": "Builds developer infrastructure.",
                    "markets": [{"name": "Developer Tools"}],
                    "officeLocations": ["San Francisco"],
                    "staffCount": "42",
                },
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:smartrecruiters",
                source_key="a16z",
                board_key="acme",
                provider_id="smartrecruiters",
                support_level=ProviderSupport.UNSUPPORTED,
                raw_payload={
                    "label": "SmartRecruiters",
                    "count": 3,
                    "url": "https://jobs.smartrecruiters.com/Acme",
                },
            )
        ]
    )
    store.upsert_jobs(
        [
            JobRecord(
                id="acme:smartrecruiters:1",
                board_key="acme",
                provider_id="smartrecruiters",
                remote_id="1",
                title="Engineer",
                locations=["Remote"],
            )
        ]
    )
    return store


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
