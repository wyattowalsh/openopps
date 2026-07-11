from __future__ import annotations

from pathlib import Path

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def seeded_coverage_store(tmp_path: Path) -> tuple[OpenOppsSettings, OpenOppsStore]:
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_source(
        SourceRecord(key="lsvp", url="https://jobs.lsvp.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme",
                domain="acme.com",
            ),
            BoardRecord(
                key="beta",
                source_key="a16z",
                remote_id="beta",
                name="Beta",
                domain="beta.com",
            ),
            BoardRecord(
                key="gamma",
                source_key="a16z",
                remote_id="gamma",
                name="Gamma",
                domain="gamma.com",
            ),
            BoardRecord(
                key="dupe-acme",
                source_key="lsvp",
                remote_id="acme",
                name="Acme",
                domain="acme.com",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:lever",
                source_key="a16z",
                board_key="acme",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="lsvp:dupe-acme:lever",
                source_key="lsvp",
                board_key="dupe-acme",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                token="acme",
            ),
            BoardProviderRecord(
                id="a16z:beta:greenhouse",
                source_key="a16z",
                board_key="beta",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
                token="beta",
                last_status="route_ready",
            ),
            BoardProviderRecord(
                id="a16z:gamma:greenhouse",
                source_key="a16z",
                board_key="gamma",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            ),
            BoardProviderRecord(
                id="a16z:gamma:teamtailor",
                source_key="a16z",
                board_key="gamma",
                provider_id="teamtailor",
                support_level=ProviderSupport.DETECT,
            ),
        ]
    )
    store.upsert_jobs(
        [
            JobRecord(
                id="beta:greenhouse:1",
                board_key="beta",
                provider_id="greenhouse",
                remote_id="1",
                title="Engineer",
                locations=["Remote"],
                department="Engineering",
                employment_type="Full-time",
                description="Build systems.",
                remote="Full",
                compensation={"currency": "USD"},
                salary="USD 100000 - 160000",
                posting_url="https://boards.greenhouse.io/beta/jobs/1",
            ),
            JobRecord(
                id="beta:greenhouse:2",
                board_key="beta",
                provider_id="greenhouse",
                remote_id="2",
                title="Designer",
            ),
        ]
    )
    return settings, store


def seeded_enrichment_store(tmp_path: Path) -> OpenOppsStore:
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


def seeded_filter_store(tmp_path: Path) -> OpenOppsStore:
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(key="a16z", url="https://a16z.com/jobs", provider_id="consider")
    )
    store.upsert_source(
        SourceRecord(
            key="yc",
            url="https://www.ycombinator.com/companies",
            provider_id="ycombinator",
        )
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme AI",
                domain="acme.ai",
                markets=["Artificial Intelligence", "Developer Tools"],
                locations=["San Francisco", "Remote"],
                staff_count=42,
                num_jobs_hint=3,
            ),
            BoardRecord(
                key="bravo",
                source_key="yc",
                remote_id="bravo",
                name="Bravo Health",
                domain="bravo.health",
                markets=["Healthcare"],
                locations=["Boston"],
                staff_count=12,
                num_jobs_hint=0,
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:ashbyhq",
                source_key="a16z",
                board_key="acme",
                provider_id="ashbyhq",
                support_level=ProviderSupport.JOBS,
                count_hint=3,
                token="acme",
            ),
            BoardProviderRecord(
                id="yc:bravo:lever",
                source_key="yc",
                board_key="bravo",
                provider_id="lever",
                support_level=ProviderSupport.JOBS,
                count_hint=0,
                token="bravo",
            ),
        ]
    )
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": "acme:ashbyhq:1",
                    "board_key": "acme",
                    "provider_id": "ashbyhq",
                    "remote_id": "1",
                    "title": "Senior Platform Engineer",
                    "company": "Acme AI",
                    "locations": ["Remote", "San Francisco"],
                    "department": "Engineering",
                    "team": "Platform",
                    "workplace_type": "Remote",
                    "employment_type": "Full-time",
                    "description": "Build reliable AI developer infrastructure.",
                    "remote": "Full",
                    "salary_min": 120000,
                    "salary_max": 180000,
                    "skills": [
                        {"name": "Backend", "level": "Senior", "keywords": ["Python"]}
                    ],
                    "posted_at": "2026-05-10T12:00:00Z",
                }
            ),
            JobRecord.model_validate(
                {
                    "id": "bravo:lever:1",
                    "board_key": "bravo",
                    "provider_id": "lever",
                    "remote_id": "1",
                    "title": "Care Designer",
                    "company": "Bravo Health",
                    "locations": ["Boston"],
                    "department": "Design",
                    "team": "Care",
                    "workplace_type": "Onsite",
                    "employment_type": "Contract",
                    "description": "Design patient care workflows.",
                    "remote": "None",
                    "salary_min": 70000,
                    "salary_max": 90000,
                    "skills": [
                        {"name": "Design", "level": "Mid", "keywords": ["Figma"]}
                    ],
                    "posted_at": "2026-04-01",
                }
            ),
        ]
    )
    return store