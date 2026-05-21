from pathlib import Path

import httpx
import pytest
import respx

from openopps.health import check_provider_health
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import source_board_key


@pytest.mark.asyncio
@respx.mock
async def test_provider_health_checks_sources_routes_and_not_covered(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(
            key="a16z",
            url="https://jobs.a16z.com/companies",
            provider_id="consider_a16z",
            raw_metadata={"board": "andreessen-horowitz"},
        )
    )
    board_key = source_board_key("a16z", "acme")
    store.upsert_boards(
        [
            BoardRecord(
                key=board_key,
                source_key="a16z",
                remote_id="acme",
                remote_slug="acme",
                name="Acme",
                domain="acme.com",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=f"a16z:{board_key}:lever",
                source_key="a16z",
                board_key=board_key,
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id=f"a16z:{board_key}:teamtailor",
                source_key="a16z",
                board_key=board_key,
                provider_id="teamtailor",
                support_level=ProviderSupport.DETECT,
            ),
        ]
    )
    respx.post("https://jobs.a16z.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "acme",
                        "slug": "acme",
                        "name": "Acme",
                        "domain": "acme.com",
                        "website": {"url": "https://acme.com"},
                        "jobSources": [
                            {"id": "teamtailor", "label": "Teamtailor", "count": 2}
                        ],
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
            },
        )
    )
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "job-1",
                    "text": "Engineer",
                    "hostedUrl": "https://jobs.lever.co/acme/job-1",
                }
            ],
        )
    )

    summary = await check_provider_health(
        settings=settings,
        store=store,
        source_key="a16z",
        page_size=1,
        apply=True,
    )
    data = summary.as_dict()

    assert data["sourceStatus"] == {"active": 1}
    assert data["routeStatus"] == {"active": 1}
    assert data["notCovered"] == [
        {
            "provider_id": "teamtailor",
            "support_level": "detect",
            "discovered": 1,
            "examples": [board_key],
        }
    ]
    stored_source = store.get_source("a16z")
    assert stored_source is not None
    health = stored_source.raw_metadata["health"]
    assert isinstance(health, dict)
    assert health["status"] == "active"
    routes = store.list_board_providers(provider_id="lever")
    assert routes[0].last_status == "active"
    not_covered = store.list_board_providers(provider_id="teamtailor")
    assert not_covered[0].last_status == "not_covered"


@pytest.mark.asyncio
async def test_provider_health_reports_missing_routes(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme:greenhouse",
                source_key="manual",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )

    summary = await check_provider_health(
        settings=settings, store=store, source_key="manual"
    )

    assert summary.as_dict()["routeStatus"] == {"missing_route": 1}


@pytest.mark.asyncio
@respx.mock
async def test_workday_provider_health_uses_listing_count_without_detail_fetches(
    tmp_path: Path,
):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme-workday",
                source_key="manual",
                remote_id="acme-workday",
                name="Acme Workday",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="manual:acme-workday:workday",
                source_key="manual",
                board_key="acme-workday",
                provider_id="workday",
                support_level=ProviderSupport.JOBS,
                host="acme.wd1.myworkdayjobs.com",
                tenant="acme",
                site="External",
            )
        ]
    )
    listing_route = respx.post(
        "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/jobs"
    ).mock(return_value=httpx.Response(200, json={"total": 3, "jobPostings": [{}]}))
    detail_route = respx.get(
        "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/job/abc"
    ).mock(return_value=httpx.Response(500, json={"error": "should not call"}))

    summary = await check_provider_health(
        settings=settings, store=store, source_key="manual", provider_id="workday"
    )

    assert summary.as_dict()["routeStatus"] == {"active": 1}
    assert summary.routes[0].jobs == 3
    assert listing_route.call_count == 1
    assert detail_route.call_count == 0
