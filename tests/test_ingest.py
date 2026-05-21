import json
import re
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

from openopps.ingest import sync_jobs, sync_sources
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.providers.sources.consider import DEFAULT_CONSIDER_SOURCES
from openopps.route_probe import probe_routes
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def _mock_greenhouse_jobs(token: str, jobs: list[dict[str, object]]) -> Any:
    return respx.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": jobs})
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_dedupes_same_provider_route_across_sources(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}", board_concurrency=2
    )
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="source-b", url="source-b://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a-acme",
                source_key="source-a",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
            BoardRecord(
                key="source-b-acme",
                source_key="source-b",
                remote_id="Acme",
                name="Acme",
                domain="acme.com",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="source-a:source-a-acme:greenhouse",
                source_key="source-a",
                board_key="source-a-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="source-b:source-b-acme:greenhouse",
                source_key="source-b",
                board_key="source-b-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
        ]
    )
    route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="all")

    assert route.call_count == 1
    assert metrics.duplicate_routes_skipped == 1
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_skips_route_hints_without_executable_metadata(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="manual", url="manual://source", provider_id="manual")
    )
    store.upsert_boards(
        [BoardRecord(key="acme", source_key="manual", remote_id="Acme", name="Acme")]
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
    route = _mock_greenhouse_jobs("acme", [])

    metrics = await sync_jobs(settings=settings, store=store, provider_id="greenhouse")

    assert route.call_count == 0
    assert metrics.skipped == 1
    assert metrics.jobs == 0


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_uses_configured_default_sources(tmp_path: Path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        job_sync_sources="source-b",
    )
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs("acme", [])
    source_b_route = _mock_greenhouse_jobs(
        "beta",
        [
            {
                "id": 2,
                "title": "Designer",
                "absolute_url": "https://boards.greenhouse.io/beta/jobs/2",
            }
        ],
    )

    metrics = await sync_jobs(settings=settings, store=store, provider_id="all")

    assert source_a_route.call_count == 0
    assert source_b_route.call_count == 1
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_source_argument_overrides_configured_default_sources(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        job_sync_sources="source-b",
    )
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )
    source_b_route = _mock_greenhouse_jobs("beta", [])

    metrics = await sync_jobs(
        settings=settings, store=store, source_key="source-a", provider_id="all"
    )

    assert source_a_route.call_count == 1
    assert source_b_route.call_count == 0
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_jobs_board_argument_overrides_configured_default_sources(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        job_sync_sources="source-b",
    )
    store = OpenOppsStore(settings)
    _seed_two_source_routes(store)
    source_a_route = _mock_greenhouse_jobs(
        "acme",
        [
            {
                "id": 1,
                "title": "Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        ],
    )
    source_b_route = _mock_greenhouse_jobs("beta", [])

    metrics = await sync_jobs(
        settings=settings,
        store=store,
        board_key="source-a-acme",
        provider_id="all",
    )

    assert source_a_route.call_count == 1
    assert source_b_route.call_count == 0
    assert metrics.jobs == 1


@pytest.mark.asyncio
@respx.mock
async def test_sync_sources_preserves_route_metadata_across_repeated_syncs(
    tmp_path: Path,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        source_concurrency=1,
        cache_enabled=False,
    )
    store = OpenOppsStore(settings)
    store.upsert_source(DEFAULT_CONSIDER_SOURCES["lsvp"])
    route = respx.post("https://jobs.lsvp.com/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200, json={"companies": [], "total": 0, "meta": {"size": 1}}
        )
    )

    first_metrics = await sync_sources(
        settings=settings, store=store, source_key="lsvp", page_size=1
    )
    second_metrics = await sync_sources(
        settings=settings, store=store, source_key="lsvp", page_size=1
    )

    assert first_metrics.provider_errors == {}
    assert second_metrics.provider_errors == {}
    assert route.call_count == 2
    request_bodies = [json.loads(call.request.content) for call in route.calls]
    assert [body["query"]["parent"] for body in request_bodies] == [
        "lightspeed",
        "lightspeed",
    ]
    stored = store.get_source("lsvp")
    assert stored is not None
    assert stored.raw_metadata["board"] == "lightspeed"
    last_page = cast(dict[str, Any], stored.raw_metadata["lastPage"])
    assert last_page["total"] == 0
    assert "rawResponse" not in last_page


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("source_key", "source_origin", "board_slug"),
    [
        ("battery", "https://jobs.battery.com", "battery-ventures"),
        ("costanoavc", "https://jobs.costanoavc.com", "costanoa-ventures"),
        (
            "forerunnerventures",
            "https://jobs.forerunnerventures.com",
            "forerunner-ventures",
        ),
        ("fincapital", "https://jobs.fin.capital", "fin-capital"),
        ("nextview", "https://jobs.nextview.vc", "nextview-ventures"),
        ("qedinvestors", "https://careers.qedinvestors.com", "qed-investors"),
        ("balderton", "https://careers.balderton.com", "balderton-capital"),
        ("creandum", "https://careers.creandum.com", "creandum"),
        (
            "amplifypartners",
            "https://talent.amplifypartners.com",
            "amplify-partners",
        ),
        ("gv", "https://jobs.gv.com", "gv"),
        ("nvp", "https://careers.nvp.com", "norwest-venture-partners"),
        ("anthemis", "https://jobs.anthemis.com", "anthemis-group"),
        ("fiftyyears", "https://jobs.fiftyyears.com", "fifty-years"),
        ("initialized", "https://jobs.initialized.com", "initialized"),
        ("crv", "https://jobs.crv.com", "crv"),
        ("zettavp", "https://careers.zettavp.com", "zetta-venture-partners"),
        ("contrary", "https://jobs.contrary.com", "contrary"),
        ("goldenventures", "https://jobs.golden.ventures", "golden-ventures"),
        ("necessary", "https://jobs.necessary.vc", "necessary-ventures"),
        ("5amventures", "https://jobs.5amventures.com", "5am-ventures"),
        (
            "illuminatefinancial",
            "https://jobs.illuminatefinancial.com",
            "illuminate-financial",
        ),
        ("xange", "https://jobs.xange.vc", "xange"),
        ("sosv", "https://techjobs.sosv.com", "sosv"),
        ("hardyaka", "https://jobs.hardyaka.com", "hard-yaka"),
        ("panteracapital", "https://jobs.panteracapital.com", "pantera-capital"),
        (
            "vuventurepartners",
            "https://jobs.vuventurepartners.com",
            "vu-venture-partners",
        ),
        ("linkventures", "https://jobs.linkventures.com", "link-ventures"),
        ("aixventures", "https://careers.aixventures.com", "aix-ventures"),
        ("woven", "https://portfoliojobs.woven.vc", "woven-capital"),
        ("playground", "https://careers.playground.global", "playground-global"),
        ("hoxtonventures", "https://jobs.hoxtonventures.com", "hoxton-ventures"),
        (
            "conversioncapital",
            "https://jobs.conversioncapital.com",
            "conversion-capital",
        ),
        ("alter", "https://careers.alter.vc", "alter-global"),
        ("iconventures", "https://jobs.iconventures.com", "icon-ventures"),
        ("gaingels", "https://jobs.gaingels.com", "gaingels"),
        ("nexusvp", "https://jobs.nexusvp.com", "nexus-venture-partners"),
        ("mvp", "https://talent.mvp-vc.com", "mvp-ventures"),
        ("offline", "https://jobs.offline.vc", "offline-ventures"),
        (
            "hitachiventures",
            "https://jobs.hitachi-ventures.com",
            "hitachi-ventures",
        ),
        ("atlasventure", "https://careers.atlasventure.com", "atlas-venture"),
        ("transition", "https://jobs.transition.vc", "transition-ventures"),
        ("age1", "https://careers.age1.com", "age1"),
        ("bakarlabs", "https://jobs.bakarlabs.org", "bakar-bio-labs"),
        ("startx", "https://jobs.startx.com", "startx"),
        ("e14", "https://jobs.e14.vc", "e14-fund"),
        ("notion", "https://jobs.notion.vc", "notion-capital"),
        ("notation", "https://consider.com", "notation-capital"),
        ("threshold", "https://jobs.threshold.vc", "threshold-ventures"),
        ("atoneventures", "https://jobs.atoneventures.com", "at-one-ventures"),
        ("mantisvc", "https://careers.mantisvc.com", "mantis"),
        (
            "fenbushicapital",
            "https://careers.fenbushicapital.vc",
            "fenbushi-capital",
        ),
        ("f2vc", "https://jobs.f2vc.com", "f2-venture-capital"),
        ("abstractvc", "https://jobs.abstractvc.com", "abstract-ventures"),
        (
            "urbaninnovationfund",
            "https://jobs.urbaninnovationfund.com",
            "urban-innovation-fund",
        ),
        ("extantia", "https://careers.extantia.com", "extantia"),
        ("oneragtime", "https://careers.oneragtime.com", "oneragtime"),
        ("adverb", "https://jobs.adverb.vc", "adverb-ventures"),
        ("expa", "https://jobs.expa.com", "expa"),
        ("qplusequality", "https://jobs.qplusequality.org", "q-plus-equality"),
    ],
)
async def test_default_consider_source_feeds_downstream_route_probe(
    tmp_path: Path,
    source_key: str,
    source_origin: str,
    board_slug: str,
):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        provider_concurrency=1,
        source_concurrency=1,
    )
    store = OpenOppsStore(settings)
    source_route = respx.post(f"{source_origin}/api-boards/search-companies").mock(
        return_value=httpx.Response(
            200,
            json={
                "companies": [
                    {
                        "id": "Acme",
                        "slug": "acme",
                        "name": "Acme",
                        "domain": "acme.com",
                        "numJobs": 2,
                        "jobSources": [
                            {"id": "greenhouse", "label": "Greenhouse", "count": 2}
                        ],
                        "website": {"url": "https://acme.com/"},
                    }
                ],
                "total": 1,
                "meta": {"size": 1},
            },
        )
    )
    greenhouse_route = respx.get(
        re.compile(r"https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*")
    ).mock(return_value=httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}))

    source_metrics = await sync_sources(
        settings=settings, store=store, source_key=source_key, page_size=1
    )
    probe_summary = await probe_routes(
        settings=settings,
        store=store,
        source_key=source_key,
        provider_id="greenhouse",
        apply=True,
    )

    assert source_metrics.boards == 1
    assert source_metrics.board_providers == 1
    assert source_route.call_count == 1
    assert (
        json.loads(source_route.calls[0].request.content)["query"]["parent"]
        == board_slug
    )
    assert greenhouse_route.call_count == 1
    assert probe_summary.matched_by_provider == {"greenhouse": 1}
    persisted = store.list_board_providers(
        source_key=source_key, provider_id="greenhouse"
    )[0]
    assert persisted.token == "acme"
    assert persisted.board_url == "https://boards.greenhouse.io/acme"


def _seed_two_source_routes(store: OpenOppsStore) -> None:
    store.upsert_source(
        SourceRecord(key="source-a", url="source-a://source", provider_id="manual")
    )
    store.upsert_source(
        SourceRecord(key="source-b", url="source-b://source", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="source-a-acme",
                source_key="source-a",
                remote_id="Acme",
                name="Acme",
            ),
            BoardRecord(
                key="source-b-beta",
                source_key="source-b",
                remote_id="Beta",
                name="Beta",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="source-a:source-a-acme:greenhouse",
                source_key="source-a",
                board_key="source-a-acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="source-b:source-b-beta:greenhouse",
                source_key="source-b",
                board_key="source-b-beta",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="beta",
            ),
        ]
    )
