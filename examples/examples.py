from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from faker import Faker

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)


EXAMPLE_BASE_TIME = datetime(2030, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ExampleCacheRecord:
    namespace: str
    key: str
    status_code: int
    url: str
    fetched_at: str
    expires_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ExamplePluginRecord:
    name: str
    version: str
    api_version: str
    capabilities: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "apiVersion": self.api_version,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class ExampleDataset:
    sources: tuple[SourceRecord, ...]
    boards: tuple[BoardRecord, ...]
    routes: tuple[BoardProviderRecord, ...]
    jobs: tuple[JobRecord, ...]
    cache_records: tuple[ExampleCacheRecord, ...]
    plugins: tuple[ExamplePluginRecord, ...]

    def as_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "sources": [source.model_dump(mode="json") for source in self.sources],
            "boards": [board.model_dump(mode="json") for board in self.boards],
            "routes": [route.model_dump(mode="json") for route in self.routes],
            "jobs": [job.model_dump(mode="json") for job in self.jobs],
            "cacheRecords": [record.__dict__ for record in self.cache_records],
            "plugins": [plugin.as_dict() for plugin in self.plugins],
        }


def build_example_dataset(
    *,
    seed: int = 1001,
    board_count: int = 4,
    jobs_per_board: int = 2,
) -> ExampleDataset:
    """Build deterministic synthetic records for docs, smoke tests, and demos."""

    fake = Faker()
    fake.seed_instance(seed)
    synced_at = EXAMPLE_BASE_TIME + timedelta(seconds=seed)
    source = SourceRecord(
        key="example",
        url="example://openopps/synthetic",
        provider_id="example",
        version={"seed": seed, "kind": "synthetic"},
        raw_metadata={"description": "Synthetic OpenOpps v0.1 example source."},
        synced_at=synced_at,
    )
    boards: list[BoardRecord] = []
    routes: list[BoardProviderRecord] = []
    jobs: list[JobRecord] = []
    cache_records: list[ExampleCacheRecord] = []
    providers = ("greenhouse", "lever", "ashbyhq", "gem")

    for index in range(board_count):
        company = fake.unique.company().replace(",", "")
        slug = _slug(company)
        domain = f"{slug}.example.com"
        provider_id = providers[index % len(providers)]
        support_level = (
            ProviderSupport.DETECT if provider_id == "gem" else ProviderSupport.JOBS
        )
        board_key = f"example-{slug}"
        route = BoardProviderRecord(
            id=f"example:{board_key}:{provider_id}",
            source_key=source.key,
            board_key=board_key,
            provider_id=provider_id,
            label=provider_id.title(),
            support_level=support_level,
            count_hint=jobs_per_board
            if support_level == ProviderSupport.JOBS
            else None,
            board_url=f"https://jobs.example.com/{slug}",
            token=slug,
            raw_payload={"provider": provider_id, "synthetic": True},
            detected_at=synced_at,
        )
        board = BoardRecord(
            key=board_key,
            source_key=source.key,
            remote_id=slug,
            remote_slug=slug,
            name=company,
            domain=domain,
            website_url=f"https://{domain}",
            description=fake.catch_phrase(),
            markets=[fake.bs().split()[0].title(), "Developer Tools"],
            locations=[fake.city(), "Remote"],
            staff_count=25 + index * 15,
            num_jobs_hint=jobs_per_board,
            raw_payload={"company": company, "seed": seed, "index": index},
            providers=[route],
            synced_at=synced_at,
        )
        boards.append(board)
        routes.append(route)

        if support_level == ProviderSupport.JOBS:
            for job_index in range(jobs_per_board):
                remote_id = f"{slug}-{job_index + 1}"
                title = fake.job()
                salary_min = 100_000 + (index * 5_000) + (job_index * 10_000)
                salary_max = salary_min + 45_000
                jobs.append(
                    JobRecord(
                        id=f"{board_key}:{provider_id}:{remote_id}",
                        board_key=board_key,
                        provider_id=provider_id,
                        remote_id=remote_id,
                        title=title,
                        company=company,
                        locations=["Remote", fake.city()],
                        department="Engineering",
                        team="Platform",
                        workplace_type="Remote",
                        employment_type="Full-time",
                        description=f"Build {fake.bs()} for {company}.",
                        remote="Full",
                        compensation={
                            "currency": "USD",
                            "minValue": salary_min,
                            "maxValue": salary_max,
                        },
                        salary=f"USD {salary_min} - {salary_max}",
                        salary_min=salary_min,
                        salary_max=salary_max,
                        salary_currency="USD",
                        skills=[],
                        posting_url=f"https://jobs.example.com/{slug}/{remote_id}",
                        posted_at=(synced_at - timedelta(days=job_index)).isoformat(),
                        raw_listing={"id": remote_id, "synthetic": True},
                        raw_detail={"body": "Synthetic job detail."},
                        synced_at=synced_at,
                    )
                )

        cache_records.append(
            ExampleCacheRecord(
                namespace="example-source",
                key=f"example-source:{slug}",
                status_code=200,
                url=f"https://jobs.example.com/{slug}",
                fetched_at=synced_at.isoformat(),
                expires_at=(synced_at + timedelta(hours=24)).isoformat(),
                payload={"board": board_key, "provider": provider_id},
            )
        )

    return ExampleDataset(
        sources=(source,),
        boards=tuple(boards),
        routes=tuple(routes),
        jobs=tuple(jobs),
        cache_records=tuple(cache_records),
        plugins=(
            ExamplePluginRecord(
                name="example-openopps-plugin",
                version="0.1.0",
                api_version="0.1",
                capabilities=(
                    {
                        "kind": "source_adapter",
                        "name": "example_source",
                    },
                    {
                        "kind": "job_provider",
                        "name": "example_jobs",
                    },
                ),
            ),
        ),
    )


def _slug(value: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() else "-" for character in value
    )
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "example-company"
