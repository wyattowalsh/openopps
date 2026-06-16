from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from html import unescape
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    AshbyJobBoardResponse,
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    SourceRecord,
    YCombinatorAlgoliaResponse,
    YCombinatorAlgoliaResult,
    YCombinatorCompanyHit,
    normalize_public_website_url,
    utc_now,
    validate_public_https_url,
)
from openopps.providers.sources.source_utils import source_taxonomy_metadata
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify, source_board_key, stable_id

APPLICATION_ID = "45BWZJ1SGC"
INDEX_NAME = "YCCompany_By_Launch_Date_production"
ALGOLIA_AGENT = "Algolia for JavaScript (3.35.1); Browser; JS Helper (3.16.1)"
ALGOLIA_FACETS = [
    "app_answers",
    "app_video_public",
    "batch",
    "demo_day_video_public",
    "highlight_black",
    "highlight_latinx",
    "highlight_women",
    "industries",
    "isHiring",
    "nonprofit",
    "question_answers",
    "regions",
    "subindustry",
    "tags",
    "top_company",
]

_ALGOLIA_OPTS_RE = re.compile(r"window\.AlgoliaOpts\s*=\s*({[^<]+})")
_SPC_JOBS_DATA_RE = re.compile(
    r"<script type=\"application/json\" id=\"jobs-data\">(?P<data>.*?)</script>",
    re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_VCC_COMPANY_LINK_RE = re.compile(
    r"<a href=\"(?P<href>/companies/[^\"]+)\"><h3[^>]*>(?P<name>.*?)</h3></a>",
    re.DOTALL,
)
_VCC_DESCRIPTION_RE = re.compile(
    r"<p data-slot=\"text\"[^>]*>(?P<text>.*?)</p>", re.DOTALL
)
_VCC_JOBS_RE = re.compile(r">(?P<count>\d[\d,]*) jobs?<", re.IGNORECASE)
_VCC_PAGE_RE = re.compile(r"href=\"/companies\?page=(?P<page>\d+)\"")


def _public_page_source(
    *,
    key: str,
    url: str,
    label: str,
    provider_type: str,
    coverage_mode: str = "portfolio",
    access_type: str = "public_page_html",
    observed_status: str = "verified_public_page",
) -> SourceRecord:
    return SourceRecord(
        key=key,
        url=url,
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            **source_taxonomy_metadata(
                provider_type=provider_type,
                coverage_mode=coverage_mode,
                access_type=access_type,
                license_status="needs_review",
                refresh_cadence="manual",
                source_category="startup_ecosystem",
                source_attribution=f"{label} public portfolio or jobs page.",
                default_enabled_reason="Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            ),
            "label": label,
            "observedStatus": observed_status,
        },
    )


PUBLIC_PAGE_SOURCES: tuple[SourceRecord, ...] = (
    _public_page_source(
        key="twobearcapital",
        url="https://jobs.twobearcapital.com/companies",
        label="Two Bear Capital",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="500global",
        url="https://jobs.500.co/jobs",
        label="500 Global",
        provider_type="accelerator",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="moonfire",
        url="https://www.moonfire.com/positions/",
        label="Moonfire",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="alchemistaccelerator",
        url="https://www.alchemistaccelerator.com/jobs",
        label="Alchemist Accelerator",
        provider_type="accelerator",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="gener8tor",
        url="https://www.gener8tor.com/career-seekers",
        label="gener8tor",
        provider_type="accelerator",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="bioct",
        url="https://careers.bioct.org/",
        label="BioCT",
        provider_type="job_directory",
        coverage_mode="ecosystem_jobs",
        access_type="cloudflare_protected_public_page",
        observed_status="cloudflare_challenge",
    ),
    _public_page_source(
        key="biobuzz",
        url="https://app.biobuzz.io/",
        label="BioBuzz",
        provider_type="job_directory",
        coverage_mode="ecosystem_jobs",
    ),
    _public_page_source(
        key="projecta",
        url="https://www.project-a.vc/companies",
        label="Project A",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="cathayinnovation",
        url="https://cathayinnovation.com/portfolio/",
        label="Cathay Innovation",
        provider_type="venture_firm",
        access_type="cloudflare_protected_public_page",
        observed_status="cloudflare_challenge",
    ),
    _public_page_source(
        key="omersventures",
        url="https://www.omersventures.com/companies/",
        label="OMERS Ventures",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="rtpglobal",
        url="https://rtp.vc/our-companies/",
        label="RTP Global",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="meritechcapital",
        url="https://www.meritechcapital.com/companies",
        label="Meritech Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="sparkcapital",
        url="https://www.sparkcapital.com/companies",
        label="Spark Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="salesforceventures",
        url="https://salesforceventures.com/companies/",
        label="Salesforce Ventures",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="dormroomfund",
        url="https://www.dormroomfund.com/companies",
        label="Dorm Room Fund",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="startupbootcamp",
        url="https://startupbootcamp.org/",
        label="Startupbootcamp",
        provider_type="accelerator",
    ),
    _public_page_source(
        key="endeavor",
        url="https://endeavor.org/",
        label="Endeavor",
        provider_type="startup_network",
        access_type="cloudflare_protected_public_page",
        observed_status="cloudflare_challenge",
    ),
    _public_page_source(
        key="techjobsforgood",
        url="https://techjobsforgood.com/",
        label="Tech Jobs for Good",
        provider_type="job_directory",
        coverage_mode="ecosystem_jobs",
    ),
    _public_page_source(
        key="mosaicventures",
        url="https://www.mosaicventures.com/portfolio",
        label="Mosaic Ventures",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="intelcapital",
        url="https://www.intelcapital.com/portfolio/",
        label="Intel Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="unusualventures",
        url="https://www.unusual.vc/",
        label="Unusual Ventures",
        provider_type="venture_firm",
        access_type="cloudflare_protected_public_page",
        observed_status="cloudflare_challenge",
    ),
    _public_page_source(
        key="matrix",
        url="https://matrix.vc/",
        label="Matrix",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="acrewcapital",
        url="https://www.acrewcapital.com/companies",
        label="Acrew Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="floodgate",
        url="https://www.floodgate.com/companies",
        label="Floodgate",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="cowboyventures",
        url="https://www.cowboy.vc/portfolio?sector=Fintech",
        label="Cowboy Ventures",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="rootventures",
        url="https://www.root.vc/",
        label="Root Ventures",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="globalfounderscapital",
        url="https://www.globalfounderscapital.com/",
        label="Global Founders Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="monashees",
        url="https://www.monashees.com/",
        label="Monashees",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="aforecapital",
        url="https://www.afore.vc/portfolio",
        label="Afore Capital",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="haystack",
        url="https://haystack.vc/portfolio",
        label="Haystack",
        provider_type="venture_firm",
    ),
    _public_page_source(
        key="bfnjobs",
        url="https://bfn-jobs.entrepreneurs.utoronto.ca/companies",
        label="BFN Jobs (U of T Entrepreneurs)",
        provider_type="job_directory",
        coverage_mode="ecosystem_jobs",
        observed_status="not_found",
    ),
    _public_page_source(
        key="closedlooppartners",
        url="https://jobs.closedlooppartners.com/companies",
        label="Closed Loop Partners",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
        observed_status="not_found",
    ),
    _public_page_source(
        key="2048vc",
        url="https://www.2048.vc/companies",
        label="2048 Ventures",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="defy",
        url="https://defy.vc/companies/",
        label="Defy VC",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="unshackledvc",
        url="https://www.unshackledvc.com/portfolio",
        label="Unshackled Ventures",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
    _public_page_source(
        key="boxgroup",
        url="https://www.boxgroup.com/portfolio",
        label="BoxGroup",
        provider_type="venture_firm",
        coverage_mode="portfolio",
    ),
    _public_page_source(
        key="flybridge",
        url="https://www.flybridge.com/portfolio",
        label="Flybridge",
        provider_type="venture_firm",
        coverage_mode="portfolio",
    ),
    _public_page_source(
        key="s2ginvestments",
        url="https://www.s2ginvestments.com/team/careers/open-positions",
        label="S2G Investments",
        provider_type="venture_firm",
        coverage_mode="portfolio_jobs",
    ),
)


class PublicPageSourceAdapter:
    provider_id = "public_page"
    provider_label = "Public Page"
    provider_description = "Metadata-only source adapter for public pages without a structured OpenOpps adapter."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        yield (
            [],
            [],
            {
                "sourceUrl": source.url,
                "total": 0,
                "note": "Metadata-only public page; no structured board adapter is available yet.",
            },
        )


class WorkableSourceAdapter:
    provider_id = "workable_source"
    provider_label = "Workable Source"
    provider_description = "Aggregate Workable source adapter that exposes a public Workable job board as one board route."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        token = str(
            source.raw_metadata.get("token") or self._token_from_url(source.url)
        )
        label = str(source.raw_metadata.get("label") or token)
        data = await self._request_json(
            client,
            "POST",
            f"https://apply.workable.com/api/v3/accounts/{token}/jobs",
            json={},
        )
        if not isinstance(data, dict):
            raise ValueError("Workable source API returned invalid JSON")
        jobs = data.get("results")
        total = data.get("total") if isinstance(data.get("total"), int) else None
        if total is None:
            total = len(jobs) if isinstance(jobs, list) else 0
        remote_slug = slugify(token)
        board_key = source_board_key(source.key, remote_slug)
        now = utc_now()
        boards = [
            BoardRecord(
                key=board_key,
                source_key=source.key,
                remote_id=token,
                remote_slug=remote_slug,
                name=label,
                num_jobs_hint=total,
                raw_payload={**data, "sourceUrl": source.url, "token": token},
                synced_at=now,
            )
        ]
        providers = [
            BoardProviderRecord(
                id=stable_id(source.key, board_key, "workable"),
                source_key=source.key,
                board_key=board_key,
                provider_id="workable",
                label="Workable",
                support_level=ProviderSupport.JOBS,
                count_hint=total,
                board_url=source.url,
                token=token,
                raw_payload={
                    "sourceUrl": source.url,
                    "token": token,
                    "jobCount": total,
                },
                detected_at=now,
            )
        ]
        yield boards, providers, {"token": token, "total": total}

    def _token_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() != "apply.workable.com":
            raise ValueError("Workable source URL must use apply.workable.com")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0] == "j":
            raise ValueError("Workable source URL must include an account token")
        return parts[0]


class AshbySourceAdapter:
    provider_id = "ashby"
    provider_label = "Ashby Source"
    provider_description = "Aggregate Ashby source adapter that exposes a public Ashby job board as one board route."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        token = str(
            source.raw_metadata.get("token") or self._token_from_url(source.url)
        )
        label = str(source.raw_metadata.get("label") or token)
        data = await self._request_json(
            client,
            "GET",
            f"https://api.ashbyhq.com/posting-api/job-board/{token}",
            params={"includeCompensation": "false"},
        )
        if not isinstance(data, dict):
            raise ValueError("Ashby source API returned invalid JSON")
        response = AshbyJobBoardResponse.model_validate(data)
        listed_jobs = [job for job in response.jobs if job.is_listed is not False]
        remote_slug = slugify(token)
        board_key = source_board_key(source.key, remote_slug)
        now = utc_now()
        boards = [
            BoardRecord(
                key=board_key,
                source_key=source.key,
                remote_id=token,
                remote_slug=remote_slug,
                name=label,
                num_jobs_hint=len(listed_jobs),
                raw_payload={
                    **response.as_raw_payload(),
                    "sourceUrl": source.url,
                    "token": token,
                    "jobCount": len(listed_jobs),
                },
                synced_at=now,
            )
        ]
        providers = [
            BoardProviderRecord(
                id=stable_id(source.key, board_key, "ashbyhq"),
                source_key=source.key,
                board_key=board_key,
                provider_id="ashbyhq",
                label="Ashby",
                support_level=ProviderSupport.JOBS,
                count_hint=len(listed_jobs),
                board_url=source.url,
                token=token,
                raw_payload={
                    "apiVersion": response.api_version,
                    "sourceUrl": source.url,
                    "token": token,
                    "jobCount": len(listed_jobs),
                },
                detected_at=now,
            )
        ]
        yield (
            boards,
            providers,
            {
                "apiVersion": response.api_version,
                "token": token,
                "total": len(listed_jobs),
            },
        )

    def _token_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() != "jobs.ashbyhq.com":
            raise ValueError("Ashby source URL must use jobs.ashbyhq.com")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            raise ValueError("Ashby source URL must include a board token")
        return parts[0]


class SouthParkCommonsSourceAdapter:
    provider_id = "southparkcommons"
    provider_label = "South Park Commons"
    provider_description = "Aggregate South Park Commons source adapter that discovers company boards and provider hints."

    def __init__(self, settings: OpenOppsSettings):
        from openopps.providers.registry import provider_registry

        self.settings = settings
        self.registry = provider_registry(settings=settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        response = await client.get(
            source.url, headers={"accept": "text/html", "user-agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        jobs = self._jobs_from_html(response.text, source.url)
        boards, providers = self._normalize_jobs(source.key, jobs)
        yield boards, providers, {"jobs": len(jobs), "total": len(boards)}

    def _jobs_from_html(self, html: str, url: str) -> list[dict[str, Any]]:
        match = _SPC_JOBS_DATA_RE.search(html)
        if not match:
            raise ValueError(f"Could not find South Park Commons jobs data in {url}")
        payload = json.loads(match.group("data"))
        if not isinstance(payload, list):
            raise ValueError("South Park Commons jobs data returned a non-list payload")
        return [item for item in payload if isinstance(item, dict)]

    def _normalize_jobs(
        self, source_key: str, jobs: list[dict[str, Any]]
    ) -> tuple[list[BoardRecord], list[BoardProviderRecord]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for job in jobs:
            slug = self._company_slug(job)
            if slug:
                grouped[slug].append(job)

        boards: list[BoardRecord] = []
        providers: list[BoardProviderRecord] = []
        now = utc_now()
        for remote_slug, company_jobs in sorted(grouped.items()):
            first = company_jobs[0]
            board_key = source_board_key(source_key, remote_slug)
            provider_counts: dict[str, int] = defaultdict(int)
            provider_routes: dict[str, BoardProviderRecord] = {}
            for job in company_jobs:
                route = self.registry.detect_url(
                    str(job.get("url") or ""),
                    board_key=board_key,
                    source_key=source_key,
                )
                if route is None:
                    continue
                provider_counts[route.provider_id] += 1
                provider_routes.setdefault(route.provider_id, route)

            boards.append(
                BoardRecord(
                    key=board_key,
                    source_key=source_key,
                    remote_id=str(
                        first.get("companyDomain")
                        or first.get("companySlug")
                        or first.get("companyName")
                        or remote_slug
                    ),
                    remote_slug=remote_slug,
                    name=str(first.get("companyName") or remote_slug),
                    domain=self._string(first.get("companyDomain")),
                    website_url=self._website_url(first.get("companyDomain")),
                    description=self._string(first.get("companyBio")),
                    markets=self._unique_strings(
                        job.get("industry")
                        for job in company_jobs
                        if job.get("industry")
                    ),
                    locations=self._unique_strings(
                        location
                        for job in company_jobs
                        for location in self._list_value(job.get("locations"))
                    ),
                    num_jobs_hint=len(company_jobs),
                    raw_payload={
                        "companyDomain": first.get("companyDomain"),
                        "companyName": first.get("companyName"),
                        "companySlug": first.get("companySlug"),
                        "jobCount": len(company_jobs),
                        "providerCounts": dict(provider_counts),
                    },
                    synced_at=now,
                )
            )
            for provider_id, route in sorted(provider_routes.items()):
                providers.append(
                    BoardProviderRecord(
                        id=stable_id(source_key, board_key, provider_id),
                        source_key=source_key,
                        board_key=board_key,
                        provider_id=provider_id,
                        label=route.label,
                        support_level=route.support_level,
                        count_hint=provider_counts[provider_id],
                        board_url=self._canonical_board_url(route),
                        token=route.token,
                        host=route.host,
                        tenant=route.tenant,
                        site=route.site,
                        raw_payload={
                            "count": provider_counts[provider_id],
                            "exampleUrl": route.board_url,
                        },
                        detected_at=now,
                    )
                )
        return boards, providers

    def _company_slug(self, job: dict[str, Any]) -> str | None:
        value = (
            job.get("companySlug") or job.get("companyName") or job.get("companyDomain")
        )
        if value is None:
            return None
        return slugify(str(value))

    def _canonical_board_url(self, route: BoardProviderRecord) -> str | None:
        if not route.token:
            return route.board_url
        if route.provider_id == "greenhouse":
            return f"https://boards.greenhouse.io/{route.token}"
        if route.provider_id == "lever":
            return f"https://jobs.lever.co/{route.token}"
        if route.provider_id == "ashbyhq":
            return f"https://jobs.ashbyhq.com/{route.token}"
        return route.board_url

    def _website_url(self, domain: object) -> str | None:
        return normalize_public_website_url(domain)

    def _string(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _list_value(self, value: object) -> list[Any]:
        return value if isinstance(value, list) else []

    def _unique_strings(self, values: Iterable[object]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            result.append(stripped)
        return result


class VentureCapitalCareersSourceAdapter:
    provider_id = "venturecapitalcareers"
    provider_label = "Venture Capital Careers"
    provider_description = (
        "Aggregate Venture Capital Careers adapter that discovers public firm profiles."
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        first_response = await self._fetch_page(client, source.url)
        first_html = first_response.text
        max_page = self._max_page(first_html)

        for page in range(1, max_page + 1):
            if page == 1:
                response = first_response
                html = first_html
            else:
                response = await self._fetch_page(
                    client, self._page_url(source.url, page)
                )
                html = response.text
            boards = self._boards_from_html(source, html, str(response.url))
            yield (
                boards,
                [],
                {
                    "page": page,
                    "pageSize": len(boards),
                    "sourceUrl": str(response.url),
                    "totalPages": max_page,
                },
            )
            if not boards:
                break

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        response = await client.get(
            url,
            headers={"accept": "text/html", "user-agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response

    def _page_url(self, source_url: str, page: int) -> str:
        return source_url if page == 1 else f"{source_url}?page={page}"

    def _max_page(self, html: str) -> int:
        pages = [int(match.group("page")) for match in _VCC_PAGE_RE.finditer(html)]
        return max(pages, default=1)

    def _boards_from_html(
        self, source: SourceRecord, html: str, source_url: str
    ) -> list[BoardRecord]:
        boards: list[BoardRecord] = []
        now = utc_now()
        for match in _VCC_COMPANY_LINK_RE.finditer(html):
            href = match.group("href")
            remote_slug = href.rsplit("/", 1)[-1]
            name = self._html_text(match.group("name"))
            if not remote_slug or not name:
                continue
            profile_url = urljoin(source.url, href)
            description = self._description_after(html, match.end())
            job_count = self._job_count_before(html, match.start())
            boards.append(
                BoardRecord(
                    key=source_board_key(source.key, remote_slug),
                    source_key=source.key,
                    remote_id=remote_slug,
                    remote_slug=remote_slug,
                    name=name,
                    description=description,
                    num_jobs_hint=job_count,
                    raw_payload={
                        "profileUrl": profile_url,
                        "sourceUrl": source_url,
                        "jobCount": job_count,
                    },
                    synced_at=now,
                )
            )
        return boards

    def _description_after(self, html: str, position: int) -> str | None:
        match = _VCC_DESCRIPTION_RE.search(html, position, position + 800)
        if not match:
            return None
        return self._html_text(match.group("text")) or None

    def _job_count_before(self, html: str, position: int) -> int | None:
        matches = list(_VCC_JOBS_RE.finditer(html, max(0, position - 1500), position))
        if not matches:
            return None
        value = matches[-1].group("count").replace(",", "")
        return int(value)

    def _html_text(self, value: str) -> str:
        return _WHITESPACE_RE.sub(" ", unescape(_HTML_TAG_RE.sub(" ", value))).strip()


class VentureLoopSourceAdapter:
    provider_id = "ventureloop"
    provider_label = "VentureLoop"
    provider_description = "Metadata-only VentureLoop source adapter."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        response = await client.get(
            source.url,
            headers={"accept": "text/html", "user-agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        response.raise_for_status()
        yield (
            [],
            [],
            {
                "sourceUrl": str(response.url),
                "total": 0,
                "note": (
                    "VentureLoop does not expose company records on the public landing page; "
                    "job-search result scraping is intentionally not used."
                ),
            },
        )


class YCombinatorSourceAdapter:
    provider_id = "ycombinator"
    provider_label = "Y Combinator"
    provider_description = (
        "Aggregate YC source adapter that discovers company boards from Algolia."
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        application_id = str(source.raw_metadata.get("applicationId") or APPLICATION_ID)
        index_name = str(source.raw_metadata.get("indexName") or INDEX_NAME)
        api_key = str(
            source.raw_metadata.get("apiKey")
            or await self._discover_api_key(client, source, application_id)
        )
        endpoint = (
            f"https://{application_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
        )

        facet_result = await self._query_algolia(
            client,
            source,
            endpoint=endpoint,
            application_id=application_id,
            api_key=api_key,
            index_name=index_name,
            params=self._algolia_params(page_size=page_size),
        )
        batch_counts = self._batch_counts(facet_result)
        for batch, count in batch_counts.items():
            page = 0
            fetched = 0
            while fetched < count:
                result = await self._query_algolia(
                    client,
                    source,
                    endpoint=endpoint,
                    application_id=application_id,
                    api_key=api_key,
                    index_name=index_name,
                    params=self._algolia_params(
                        page_size=page_size, batch=batch, page=page
                    ),
                )
                hits = self._hits(result, batch)
                boards = self._normalize_companies(source.key, hits)
                yield (
                    boards,
                    [],
                    {
                        "applicationId": application_id,
                        "indexName": index_name,
                        "batch": batch,
                        "page": page,
                        "pageSize": page_size,
                        "total": count,
                    },
                )
                if not hits:
                    break
                fetched += len(hits)
                page += 1

    async def _discover_api_key(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        application_id: str,
    ) -> str:
        response = await client.get(
            source.url, headers={"accept": "text/html", "user-agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        match = _ALGOLIA_OPTS_RE.search(response.text)
        if not match:
            raise ValueError("Could not find YC Algolia options on the source page")
        opts = json.loads(match.group(1))
        if (
            not isinstance(opts, dict)
            or opts.get("app") != application_id
            or not opts.get("key")
        ):
            raise ValueError("YC source page returned unexpected Algolia options")
        return str(opts["key"])

    async def _query_algolia(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        endpoint: str,
        application_id: str,
        api_key: str,
        index_name: str,
        params: str,
    ) -> YCombinatorAlgoliaResult:
        query = urlencode(
            {
                "x-algolia-agent": ALGOLIA_AGENT,
                "x-algolia-application-id": application_id,
                "x-algolia-api-key": api_key,
            }
        )
        response = await self._request_json(
            client,
            "POST",
            f"{endpoint}?{query}",
            json={"requests": [{"indexName": index_name, "params": params}]},
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://www.ycombinator.com",
                "referer": source.url,
            },
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("results"), list
        ):
            raise ValueError("YC Algolia endpoint returned invalid JSON")
        payload = YCombinatorAlgoliaResponse.model_validate(response)
        result = payload.results[0] if payload.results else None
        if result is None:
            raise ValueError("YC Algolia endpoint returned an invalid result payload")
        return result

    def _algolia_params(
        self, *, page_size: int, batch: str | None = None, page: int | None = None
    ) -> str:
        params: dict[str, str | int] = {
            "facets": json.dumps(ALGOLIA_FACETS, separators=(",", ":")),
            "hitsPerPage": page_size,
            "maxValuesPerFacet": 1000,
            "query": "",
            "tagFilters": "",
        }
        if batch is not None:
            params["facetFilters"] = f"batch:{batch}"
        if page is not None:
            params["page"] = page
        return urlencode(params)

    def _batch_counts(self, result: YCombinatorAlgoliaResult) -> dict[str, int]:
        batches = result.facets.get("batch")
        if not isinstance(batches, dict):
            raise ValueError("YC Algolia facets response did not include batch facets")
        return {str(batch): int(count) for batch, count in batches.items()}

    def _hits(
        self, result: YCombinatorAlgoliaResult, batch: str
    ) -> list[YCombinatorCompanyHit]:
        if not isinstance(result.hits, list):
            raise ValueError(
                f"YC Algolia batch response did not include hits for {batch}"
            )
        return result.hits

    def _normalize_companies(
        self, source_key: str, companies: list[YCombinatorCompanyHit]
    ) -> list[BoardRecord]:
        boards: list[BoardRecord] = []
        now = utc_now()
        for company in companies:
            remote_id = str(
                company.id or company.object_id or company.slug or company.name
            )
            remote_slug = str(company.slug or slugify(str(company.name or remote_id)))
            website_url = self._website_url(company.website)
            boards.append(
                BoardRecord(
                    key=source_board_key(source_key, remote_slug),
                    source_key=source_key,
                    remote_id=remote_id,
                    remote_slug=remote_slug,
                    name=company.name or remote_id,
                    domain=self._domain_from_url(website_url),
                    website_url=website_url,
                    description=company.long_description or company.one_liner,
                    markets=self._markets(company),
                    locations=self._locations(company),
                    staff_count=company.team_size,
                    raw_payload=company.as_raw_payload(),
                    synced_at=now,
                )
            )
        return boards

    def _website_url(self, website: str | None) -> str | None:
        return normalize_public_website_url(website)

    def _domain_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        return urlparse(url).netloc.lower() or None

    def _markets(self, company: YCombinatorCompanyHit) -> list[str]:
        if company.industries:
            return company.industries
        return [value for value in (company.industry, company.subindustry) if value]

    def _locations(self, company: YCombinatorCompanyHit) -> list[str]:
        all_locations = company.all_locations
        if all_locations and all_locations.strip():
            return [
                location.strip()
                for location in all_locations.split(";")
                if location.strip()
            ]
        return company.regions


FORUM_VENTURES_SOURCE = SourceRecord(
    key="forumventures",
    url="https://jobs.ashbyhq.com/forum-ventures",
    provider_id="ashby",
    enabled=True,
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="venture_firm",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="Forum Ventures public Ashby job board.",
            default_enabled_reason="Public venture firm job board with an existing Ashby job provider route.",
        ),
        "token": "forum-ventures",
        "label": "Forum Ventures",
    },
)

PEAR_VC_SOURCE = SourceRecord(
    key="pearvc",
    url="https://jobs.ashbyhq.com/Pear-VC",
    provider_id="ashby",
    enabled=True,
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="venture_firm",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="Pear VC public Ashby job board.",
            default_enabled_reason="Public venture firm job board with an existing Ashby job provider route.",
        ),
        "token": "Pear-VC",
        "label": "Pear VC",
    },
)

SOUTHPARKCOMMONS_SOURCE = SourceRecord(
    key="southparkcommons",
    url="https://www.southparkcommons.com/jobs",
    provider_id="southparkcommons",
    enabled=True,
    raw_metadata=source_taxonomy_metadata(
        provider_type="accelerator",
        coverage_mode="portfolio",
        access_type="public_page_embedded_json",
        license_status="public_attribution_required",
        refresh_cadence="periodic",
        source_category="startup_ecosystem",
        source_attribution="South Park Commons public jobs page embedded JSON payload.",
        default_enabled_reason="Public accelerator jobs page with direct provider route hints.",
    ),
)

VENTURE_CAPITAL_CAREERS_SOURCE = SourceRecord(
    key="venturecapitalcareers",
    url="https://venturecapitalcareers.com/companies",
    provider_id="venturecapitalcareers",
    enabled=True,
    raw_metadata=source_taxonomy_metadata(
        provider_type="job_directory",
        coverage_mode="venture_firm_directory",
        access_type="public_page_html",
        license_status="public_attribution_required",
        refresh_cadence="periodic",
        source_category="startup_ecosystem",
        source_attribution="Venture Capital Careers public companies directory HTML.",
        default_enabled_reason="Public venture capital firm directory with stable profile pages.",
    ),
)

VENTURE_LOOP_SOURCE = SourceRecord(
    key="ventureloop",
    url="https://www.ventureloop.com/",
    provider_id="ventureloop",
    enabled=False,
    raw_metadata=source_taxonomy_metadata(
        provider_type="job_directory",
        coverage_mode="portfolio_jobs",
        access_type="public_landing_page",
        license_status="needs_review",
        refresh_cadence="manual",
        source_category="startup_ecosystem",
        source_attribution="VentureLoop public landing page. Its robots.txt disallows job search result scraping.",
        default_enabled_reason="Disabled by default because the public home page does not expose a company-directory payload.",
    ),
)

YCOMBINATOR_SOURCE = SourceRecord(
    key="yc",
    url="https://www.ycombinator.com/companies",
    provider_id="ycombinator",
    enabled=True,
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="accelerator",
            coverage_mode="portfolio",
            access_type="public_page_embedded_json",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_directory",
            source_attribution="Y Combinator public companies page and discovered public Algolia index metadata.",
            default_enabled_reason="High-yield public startup directory already supported by OpenOpps.",
        ),
        "applicationId": APPLICATION_ID,
        "indexName": INDEX_NAME,
    },
)


WORKABLE_1871_SOURCE = SourceRecord(
    key="1871",
    url="https://apply.workable.com/1871/",
    provider_id="workable_source",
    enabled=True,
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="job_board",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="1871 public Workable job board.",
            default_enabled_reason="Public company job board powered by Workable.",
        ),
        "token": "1871",
        "label": "1871",
    },
)

SOURCE_RECORDS: tuple[SourceRecord, ...] = (
    FORUM_VENTURES_SOURCE,
    PEAR_VC_SOURCE,
    *PUBLIC_PAGE_SOURCES,
    SOUTHPARKCOMMONS_SOURCE,
    VENTURE_CAPITAL_CAREERS_SOURCE,
    VENTURE_LOOP_SOURCE,
    WORKABLE_1871_SOURCE,
    YCOMBINATOR_SOURCE,
    SourceRecord(
        key="clevelandtalent",
        url="https://jobs.clevelandtalent.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "clevelandtalent"},
    ),
    SourceRecord(
        key="highfivepartners",
        url="https://jobs.highfivepartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "highfivepartners"},
    ),
    SourceRecord(
        key="entrepreneurs",
        url="https://jobs.entrepreneurs.utoronto.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "entrepreneurs"},
    ),
    SourceRecord(
        key="morestartshere",
        url="https://careers.morestartshere.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "morestartshere"},
    ),
    SourceRecord(
        key="makeitcu",
        url="https://jobs.makeitcu.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "makeitcu"},
    ),
    SourceRecord(
        key="innovationworks",
        url="https://jobs.innovationworks.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "innovationworks"},
    ),
    SourceRecord(
        key="charlestonorg",
        url="https://jobs.charlestoncareers.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "charlestonorg"},
    ),
    SourceRecord(
        key="greatersatx",
        url="https://careers.greatersatx.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "greatersatx"},
    ),
    SourceRecord(
        key="inwomenshealth",
        url="https://jobs.inwomenshealth.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "inwomenshealth"},
    ),
    SourceRecord(
        key="skagit",
        url="https://jobs.skagit.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "skagit"},
    ),
    SourceRecord(
        key="workforceinnovationcenter",
        url="https://careers.workforceinnovationcenter.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "workforceinnovationcenter"},
    ),
    SourceRecord(
        key="jobswithnoboss",
        url="https://jobs.jobswithnoboss.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "jobswithnoboss"},
    ),
    SourceRecord(
        key="grandforksiscooler",
        url="https://jobs.grandforksiscooler.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "grandforksiscooler"},
    ),
    SourceRecord(
        key="spirittechcollective",
        url="https://jobs.spirit-tech-collective.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "spirittechcollective"},
    ),
    SourceRecord(
        key="imecistart",
        url="https://jobs.imecistart.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "imecistart"},
    ),
    SourceRecord(
        key="abundancenetwork",
        url="https://jobs.abundancenetwork.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "abundancenetwork"},
    ),
    SourceRecord(
        key="ablepartners",
        url="https://careers.ablepartners.nyc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ablepartners"},
    ),
    SourceRecord(
        key="sierraventures",
        url="https://careers.sierraventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "sierraventures"},
    ),
    SourceRecord(
        key="alkeon",
        url="https://jobs.alkeon.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "alkeon"},
    ),
    SourceRecord(
        key="vertexventures",
        url="https://jobs.vertexventures.co.il/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "vertexventures"},
    ),
    SourceRecord(
        key="kdtvc",
        url="https://jobs.kdtvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "kdtvc"},
    ),
    SourceRecord(
        key="moberlyedc",
        url="https://jobs.moberly-edc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "moberlyedc"},
    ),
    SourceRecord(
        key="weareadamarie",
        url="https://jobs.weareadamarie.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "weareadamarie"},
    ),
    SourceRecord(
        key="arbitrum",
        url="https://jobs.arbitrum.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "arbitrum"},
    ),
    SourceRecord(
        key="oneventures",
        url="https://jobs.one-ventures.com.au/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "oneventures"},
    ),
    SourceRecord(
        key="choosemketech",
        url="https://jobs.choosemketech.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "choosemketech"},
    ),
    SourceRecord(
        key="healthxventures",
        url="https://jobs.healthxventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "healthxventures"},
    ),
    SourceRecord(
        key="watershed",
        url="https://portfolio.watershed.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "watershed"},
    ),
    SourceRecord(
        key="13bookscapital",
        url="https://careers.13bookscapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13bookscapital"},
    ),
    SourceRecord(
        key="future",
        url="https://jobs.future.ventures/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "future"},
    ),
    SourceRecord(
        key="vamosventures",
        url="https://jobs.vamosventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "vamosventures"},
    ),
    SourceRecord(
        key="peoplefunction",
        url="https://jobs.peoplefunction.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "peoplefunction"},
    ),
    SourceRecord(
        key="ironspring",
        url="https://jobs.ironspring.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ironspring"},
    ),
    SourceRecord(
        key="forward",
        url="https://careers.forward.one/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "forward"},
    ),
    SourceRecord(
        key="noromoseley",
        url="https://careers.noromoseley.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "noromoseley"},
    ),
    SourceRecord(
        key="hopelab",
        url="https://hopelab.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "hopelab"},
    ),
    SourceRecord(
        key="seaeventures",
        url="https://careers.seaeventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "seaeventures"},
    ),
    SourceRecord(
        key="stventureslab",
        url="https://careers.stventureslab.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "stventureslab"},
    ),
    SourceRecord(
        key="buoyant",
        url="https://careers.buoyant.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "buoyant"},
    ),
    SourceRecord(
        key="sixty8",
        url="https://jobs.sixty8.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "sixty8"},
    ),
    SourceRecord(
        key="dcedc",
        url="https://careers.dcedc.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "dcedc"},
    ),
    SourceRecord(
        key="workinseguin",
        url="https://www.workinseguin.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "workinseguin"},
    ),
    SourceRecord(
        key="whatsupstateny",
        url="https://jobs.whatsupstateny.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "whatsupstateny"},
    ),
    SourceRecord(
        key="myjonesborocom",
        url="https://jobs.myjonesborojobs.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "myjonesborocom"},
    ),
    SourceRecord(
        key="uprotterdam",
        url="https://jobs.uprotterdam.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "uprotterdam"},
    ),
    SourceRecord(
        key="masscybercenter",
        url="https://jobs.masscybercenter.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "masscybercenter"},
    ),
    SourceRecord(
        key="toledoregion",
        url="https://jobs.toledoregion.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "toledoregion"},
    ),
    SourceRecord(
        key="workinba",
        url="https://careers.workinba.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "workinba"},
    ),
    SourceRecord(
        key="onewagonercounty",
        url="https://jobs.onewagonercounty.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "onewagonercounty"},
    ),
    SourceRecord(
        key="rockfordchamber",
        url="https://jobs.rockfordchamber.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "rockfordchamber"},
    ),
    SourceRecord(
        key="placetobelnk",
        url="https://jobs.placetobelnk.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "placetobelnk"},
    ),
    SourceRecord(
        key="maip",
        url="https://jobs.maip.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "maip"},
    ),
    SourceRecord(
        key="inovait",
        url="https://jobs.inovait.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "inovait"},
    ),
    SourceRecord(
        key="mehi",
        url="https://jobs.mehi.masstech.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "mehi"},
    ),
    SourceRecord(
        key="peak",
        url="https://jobs.peak.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "peak"},
    ),
    SourceRecord(
        key="vmgpartners",
        url="https://jobs.vmgpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "vmgpartners"},
    ),
    SourceRecord(
        key="nucleuscapital",
        url="https://careers.nucleus-capital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "nucleuscapital"},
    ),
    SourceRecord(
        key="swayvc",
        url="https://talent.swayvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "swayvc"},
    ),
    SourceRecord(
        key="fayettechamber",
        url="https://careers.fayettechamber.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fayettechamber"},
    ),
    SourceRecord(
        key="smartfinvc",
        url="https://jobs.smartfinvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "smartfinvc"},
    ),
    SourceRecord(
        key="saintjoseph",
        url="https://jobs.saintjoseph.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "saintjoseph"},
    ),
    SourceRecord(
        key="nbchamber",
        url="https://jobs.nbchamber.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "nbchamber"},
    ),
    SourceRecord(
        key="ssedc",
        url="https://jobs.ss-edc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ssedc"},
    ),
    SourceRecord(
        key="innovate",
        url="https://jobs.innovate.ms/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "innovate"},
    ),
    SourceRecord(
        key="kayyakventures",
        url="https://jobs.kayyakventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "kayyakventures"},
    ),
    SourceRecord(
        key="hetz",
        url="https://careers.hetz.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "hetz"},
    ),
    SourceRecord(
        key="connexacapital",
        url="https://careers.connexacapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "connexacapital"},
    ),
    SourceRecord(
        key="skale",
        url="https://jobs.skale.space/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "skale"},
    ),
    SourceRecord(
        key="georgetown",
        url="https://georgetown.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "georgetown"},
    ),
    SourceRecord(
        key="alpinesg",
        url="https://jobs.alpinesg.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "alpinesg"},
    ),
    SourceRecord(
        key="lumoscapitalgroup",
        url="https://lumoscapitalgroup.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "lumoscapitalgroup"},
    ),
    SourceRecord(
        key="southparkcommonsvc",
        url="https://consider.com/boards/vc/south-park-commons/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "southparkcommonsvc"},
    ),
    SourceRecord(
        key="lcattertonvc",
        url="https://consider.com/boards/vc/l-catterton/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "lcattertonvc"},
    ),
    SourceRecord(
        key="evpvc",
        url="https://consider.com/boards/vc/evp/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "evpvc"},
    ),
    SourceRecord(
        key="firstround",
        url="https://www.firstround.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "First Round public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "First Round",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="foundersfund",
        url="https://foundersfund.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Founders Fund public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Founders Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="slow",
        url="https://slow.co/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Slow Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Slow Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="gpv",
        url="https://www.gpv.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "GPV public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "GPV",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="villageglobal",
        url="https://www.villageglobal.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Village Global public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Village Global",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="foundercollective",
        url="https://foundercollective.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Founder Collective public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Founder Collective",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="bowerycap",
        url="https://bowerycap.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bowery Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Bowery Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="pillar",
        url="https://www.pillar.vc/companies/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Pillar public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Pillar",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="spero",
        url="https://spero.vc/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Spero Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Spero Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="felixcap",
        url="https://www.felixcap.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Felix Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Felix Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="blume",
        url="https://blume.vc/startups",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Blume Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Blume Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elevationcapital",
        url="https://www.elevationcapital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elevation Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Elevation Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="chiratae",
        url="https://www.chiratae.com/companies/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Chiratae Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Chiratae Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="endiya",
        url="https://www.endiya.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Endiya Partners public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Endiya Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="eqtgroup",
        url="https://eqtgroup.com/about/current-portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "EQT public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "EQT",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="heartcore",
        url="https://www.heartcore.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Heartcore public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Heartcore",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="hofcapital",
        url="https://hofcapital.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Hof Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Hof Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="plus",
        url="https://plus.vc/investments-portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Plus VC public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Plus VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="venturesouq",
        url="https://www.venturesouq.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Venturesouq public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Venturesouq",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="saviu",
        url="https://www.saviu.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Saviu Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Saviu Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="indiebio",
        url="https://indiebio.board.staging.consider.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "indiebio"},
    ),
    SourceRecord(
        key="vistria",
        url="https://consider.com/boards/vc/vistria/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "vistria"},
    ),
    SourceRecord(
        key="valtruis",
        url="https://careers.valtruis.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "valtruis"},
    ),
    SourceRecord(
        key="phxfwd",
        url="https://jobs.phxfwd.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "phxfwd"},
    ),
    SourceRecord(
        key="foodtechscout",
        url="https://jobs.foodtechscout.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "foodtechscout"},
    ),
    SourceRecord(
        key="i2bf",
        url="https://talent.i2bf.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "i2bf"},
    ),
    SourceRecord(
        key="narreach",
        url="https://careers.narreach.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "narreach"},
    ),
    SourceRecord(
        key="coinfund",
        url="https://jobs.coinfund.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "coinfund"},
    ),
    SourceRecord(
        key="matchstickventures",
        url="https://jobs.matchstickventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "matchstickventures"},
    ),
    SourceRecord(
        key="plugandplayfoundation",
        url="https://accessopportunities.plugandplayfoundation.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "plugandplayfoundation"},
    ),
    SourceRecord(
        key="castleisland",
        url="https://jobs.castleisland.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "castleisland"},
    ),
    SourceRecord(
        key="togethxr",
        url="https://jobs.togethxr.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "togethxr"},
    ),
    SourceRecord(
        key="edomarketplace",
        url="https://edomarketplace.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "edomarketplace"},
    ),
    SourceRecord(
        key="cantos",
        url="https://jobs.cantos.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "cantos"},
    ),
    SourceRecord(
        key="silvertonpartners",
        url="https://jobs.silvertonpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "silvertonpartners"},
    ),
    SourceRecord(
        key="gfrfund",
        url="https://jobs.gfrfund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "gfrfund"},
    ),
    SourceRecord(
        key="fortinocapital",
        url="https://talent.fortinocapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fortinocapital"},
    ),
    SourceRecord(
        key="ziggtalent",
        url="https://jobs.ziggtalent.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ziggtalent"},
    ),
    SourceRecord(
        key="drivetlv",
        url="https://jobs.drivetlv.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "drivetlv"},
    ),
    SourceRecord(
        key="startmunich",
        url="https://jobs.startmunich.de/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "startmunich"},
    ),
    SourceRecord(
        key="definitioncap",
        url="https://jobs.definitioncap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "definitioncap"},
    ),
    SourceRecord(
        key="almazcapital",
        url="https://jobs.almazcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "almazcapital"},
    ),
    SourceRecord(
        key="spartangroup",
        url="https://jobs.spartangroup.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "spartangroup"},
    ),
    SourceRecord(
        key="jdssports",
        url="https://jobs.jdssports.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "jdssports"},
    ),
    SourceRecord(
        key="lyragrowth",
        url="https://jobs.lyragrowth.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "lyragrowth"},
    ),
    SourceRecord(
        key="theadclub",
        url="https://careers.theadclub.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "theadclub"},
    ),
    SourceRecord(
        key="tnentertainment",
        url="https://jobs.tnentertainment.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "tnentertainment"},
    ),
    SourceRecord(
        key="rowanedc",
        url="https://jobs.rowanedc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "rowanedc"},
    ),
    SourceRecord(
        key="clarksvilleishiring",
        url="https://jobs.clarksvilleishiring.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "clarksvilleishiring"},
    ),
    SourceRecord(
        key="flintandgenesee",
        url="https://jobs.flintandgenesee.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "flintandgenesee"},
    ),
    SourceRecord(
        key="growingreenvillenc",
        url="https://jobs.growingreenvillenc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "growingreenvillenc"},
    ),
    SourceRecord(
        key="selectpriorinvestments",
        url="https://consider.com/boards/vc/select-prior-investments/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "selectpriorinvestments"},
    ),
    SourceRecord(
        key="fjlabs",
        url="https://fjlabs.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "FJ Labs public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "FJ Labs",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="climatecapital",
        url="https://www.climatecapital.co/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Climate Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Climate Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="shorooq",
        url="https://www.shorooq.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Shorooq public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Shorooq",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="picuscap",
        url="https://www.picuscap.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Picus Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Picus Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="portageinvest",
        url="https://portageinvest.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Portage public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Portage",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="canary",
        url="https://www.canary.com.br/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Canary public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Canary",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="raed",
        url="https://raed.vc/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Raed public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Raed",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tlcomcapital",
        url="https://tlcomcapital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "TLcom Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "TLcom Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="omnivore",
        url="https://omnivore.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Omnivore public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Omnivore",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="3one4capital",
        url="https://www.3one4capital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "3one4 Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "3one4 Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="jungle",
        url="https://www.jungle.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Jungle Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Jungle Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="qualgro",
        url="https://qualgro.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Qualgro public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Qualgro",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="earthshot",
        url="https://www.earthshot.vc/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Earthshot public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Earthshot",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="daphni",
        url="https://www.daphni.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Daphni public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Daphni",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elaia",
        url="https://www.elaia.com/companies/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elaia public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Elaia",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="carbonthirteen",
        url="https://carbonthirteen.com/our-portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Carbon Thirteen public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Carbon Thirteen",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="regeneration",
        url="https://regeneration.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Regeneration public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Regeneration",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="boldstart",
        url="https://boldstart.vc/companies/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Boldstart public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Boldstart",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="bedrockcap",
        url="https://bedrockcap.com/investments",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bedrock Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Bedrock Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="passioncapital",
        url="https://passioncapital.com/fund-portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Passion Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Passion Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="alignedclimatecapital",
        url="https://alignedclimatecapital.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Aligned Climate Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Aligned Climate Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="economicdevelopmentjobs",
        url="https://economicdevelopmentjobs.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "economicdevelopmentjobs"},
    ),
    SourceRecord(
        key="get2knownoke",
        url="https://jobs.get2knownoke.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "get2knownoke"},
    ),
    SourceRecord(
        key="whiteboardadvisors",
        url="https://jobs.whiteboardadvisors.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "whiteboardadvisors"},
    ),
    SourceRecord(
        key="firstroundcapital",
        url="https://consider.com/boards/vc/first-round-capital/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "firstroundcapital"},
    ),
    SourceRecord(
        key="impactsource",
        url="https://www.impactsource.ai/jobs",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "impactsource"},
    ),
    SourceRecord(
        key="growenid",
        url="https://jobs.growenid.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "growenid"},
    ),
    SourceRecord(
        key="techsquareventures",
        url="https://jobs.techsquareventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "techsquareventures"},
    ),
    SourceRecord(
        key="s32",
        url="https://s32.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "s32"},
    ),
    SourceRecord(
        key="peoria",
        url="https://jobs.peoria.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "peoria"},
    ),
    SourceRecord(
        key="amazingcolumbusga",
        url="https://work.amazingcolumbusga.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "amazingcolumbusga"},
    ),
    SourceRecord(
        key="portmuskogee",
        url="https://jobs.portmuskogee.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "portmuskogee"},
    ),
    SourceRecord(
        key="ton",
        url="https://jobs.ton.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ton"},
    ),
    SourceRecord(
        key="prospect",
        url="https://consider.com/boards/vc/prospect/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "prospect"},
    ),
    SourceRecord(
        key="riverside",
        url="https://consider.com/boards/vc/riverside/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "riverside"},
    ),
    SourceRecord(
        key="owlvc",
        url="https://careers.owlvc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "owlvc"},
    ),
    SourceRecord(
        key="joplincc",
        url="https://jobs.joplincc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "joplincc"},
    ),
    SourceRecord(
        key="powerlines",
        url="https://careers.powerlines.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "powerlines"},
    ),
    SourceRecord(
        key="thecentermemphis",
        url="https://jobs.thecentermemphis.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "thecentermemphis"},
    ),
    SourceRecord(
        key="silversmith",
        url="https://careers.silversmith.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "silversmith"},
    ),
    SourceRecord(
        key="limitlessdecatur",
        url="https://jobs.limitlessdecatur.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "limitlessdecatur"},
    ),
    SourceRecord(
        key="workupcoweta",
        url="https://careers.workupcoweta.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "workupcoweta"},
    ),
    SourceRecord(
        key="hellowestmichigan",
        url="https://jobs.hellowestmichigan.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "hellowestmichigan"},
    ),
    SourceRecord(
        key="portageinvestvc",
        url="https://careers.portageinvest.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "portageinvestvc"},
    ),
    SourceRecord(
        key="edbi",
        url="https://consider.com/boards/vc/edbi/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "edbi"},
    ),
    SourceRecord(
        key="firstmomentum",
        url="https://jobs.firstmomentum.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "firstmomentum"},
    ),
    SourceRecord(
        key="muus",
        url="https://consider.com/boards/vc/muus/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "muus"},
    ),
    SourceRecord(
        key="anthoscapital",
        url="https://consider.com/boards/vc/anthos-capital/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "anthoscapital"},
    ),
    SourceRecord(
        key="merantixaicampus",
        url="https://careers.merantix-aicampus.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "merantixaicampus"},
    ),
    SourceRecord(
        key="proptech1",
        url="https://consider.com/boards/vc/proptech1/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "proptech1"},
    ),
    SourceRecord(
        key="motherventures",
        url="https://jobs.mother-ventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "motherventures"},
    ),
    SourceRecord(
        key="spectrumequity",
        url="https://careers.spectrumequity.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "spectrumequity"},
    ),
    SourceRecord(
        key="ridgeline",
        url="https://jobs.ridgeline.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ridgeline"},
    ),
    SourceRecord(
        key="avax",
        url="https://jobs.avax.network/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "avax"},
    ),
    SourceRecord(
        key="omnivorevc",
        url="https://jobs.omnivore.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "omnivorevc"},
    ),
    SourceRecord(
        key="investnebraska",
        url="https://jobs.investnebraska.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "investnebraska"},
    ),
    SourceRecord(
        key="firstmilevc",
        url="https://jobs.firstmilevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "firstmilevc"},
    ),
    SourceRecord(
        key="dlcda",
        url="https://careers.dlcda.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "dlcda"},
    ),
    SourceRecord(
        key="leadershiptriangle",
        url="https://jobs.leadershiptriangle.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "leadershiptriangle"},
    ),
    SourceRecord(
        key="glasswing",
        url="https://jobs.glasswing.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "glasswing"},
    ),
    SourceRecord(
        key="fulcrumep",
        url="https://jobs.fulcrumep.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fulcrumep"},
    ),
    SourceRecord(
        key="prudence",
        url="https://jobs.prudence.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "prudence"},
    ),
    SourceRecord(
        key="fannindevelopment",
        url="https://jobs.fannindevelopment.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fannindevelopment"},
    ),
    SourceRecord(
        key="developmilledgeville",
        url="https://careers.developmilledgeville.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "developmilledgeville"},
    ),
    SourceRecord(
        key="swanandlegend",
        url="https://jobs.swanandlegend.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "swanandlegend"},
    ),
    SourceRecord(
        key="blackwellnow",
        url="https://jobs.blackwellnow.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "blackwellnow"},
    ),
    SourceRecord(
        key="emanuelchamber",
        url="https://careers.emanuelchamber.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "emanuelchamber"},
    ),
    SourceRecord(
        key="jvpvc",
        url="https://jobs.jvpvc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "jvpvc"},
    ),
    SourceRecord(
        key="psl",
        url="https://jobs.psl.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "psl"},
    ),
    SourceRecord(
        key="story",
        url="https://careers.story.foundation/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "story"},
    ),
    SourceRecord(
        key="hannahgrey",
        url="https://hannahgrey.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "hannahgrey"},
    ),
    SourceRecord(
        key="hax",
        url="https://jobs.hax.co/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "hax"},
    ),
    SourceRecord(
        key="compa",
        url="https://communityjobs.compa.ai/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "compa"},
    ),
    SourceRecord(
        key="localglobeall",
        url="https://consider.com/boards/vc/localglobe-all/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "localglobeall"},
    ),
    SourceRecord(
        key="soarky",
        url="https://jobs.soar-ky.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "soarky"},
    ),
    SourceRecord(
        key="fintechaustralia",
        url="https://jobs.fintechaustralia.org.au/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fintechaustralia"},
    ),
    SourceRecord(
        key="johotalent",
        url="https://jobs.johotalent.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "johotalent"},
    ),
    SourceRecord(
        key="bitkraft",
        url="https://careers.bitkraft.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "bitkraft"},
    ),
    SourceRecord(
        key="chirataevc",
        url="https://careers.chiratae.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "chirataevc"},
    ),
    SourceRecord(
        key="lifemultiplied",
        url="https://jobs.lifemultiplied.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "lifemultiplied"},
    ),
    SourceRecord(
        key="dutchtech",
        url="https://consider.com/boards/vc/dutchtech/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "dutchtech"},
    ),
    SourceRecord(
        key="mitalumnistartups",
        url="https://consider.com/boards/vc/mit-alumni-startups/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "mitalumnistartups"},
    ),
    SourceRecord(
        key="blumevc",
        url="https://jobs.blume.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "blumevc"},
    ),
    SourceRecord(
        key="springtide",
        url="https://jobs.springtide.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "springtide"},
    ),
    SourceRecord(
        key="collab",
        url="https://jobs.collab.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "collab"},
    ),
    SourceRecord(
        key="inflection",
        url="https://jobs.inflection.fund/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "inflection"},
    ),
    SourceRecord(
        key="terratalent",
        url="https://terratalent.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "terratalent"},
    ),
    SourceRecord(
        key="samaipata",
        url="https://samaipata.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "samaipata"},
    ),
    SourceRecord(
        key="xrpl",
        url="https://jobs.xrpl.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "xrpl"},
    ),
    SourceRecord(
        key="movementlabs",
        url="https://ecosystem.movementlabs.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "movementlabs"},
    ),
    SourceRecord(
        key="sui",
        url="https://jobs.sui.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "sui"},
    ),
    SourceRecord(
        key="cobalt",
        url="https://jobs.cobalt.la/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "cobalt"},
    ),
    SourceRecord(
        key="vimian",
        url="https://careers.vimian.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "vimian"},
    ),
    SourceRecord(
        key="wallstreetfriends",
        url="https://jobs.wallstreetfriends.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "wallstreetfriends"},
    ),
    SourceRecord(
        key="leedsilluminate",
        url="https://jobs.leedsilluminate.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "leedsilluminate"},
    ),
    SourceRecord(
        key="z2sixtyventures",
        url="https://jobs.z2sixtyventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "z2sixtyventures"},
    ),
    SourceRecord(
        key="animocabrands",
        url="https://careers.animocabrands.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "animocabrands"},
    ),
    SourceRecord(
        key="bluewing",
        url="https://careers.bluewing.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "bluewing"},
    ),
    SourceRecord(
        key="joulevc",
        url="https://jobs.joulevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "joulevc"},
    ),
    SourceRecord(
        key="tpycapital",
        url="https://jobs.tpycapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "tpycapital"},
    ),
    SourceRecord(
        key="reddot",
        url="https://careers.red-dot.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "reddot"},
    ),
    SourceRecord(
        key="arca",
        url="https://careers.ar.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "arca"},
    ),
    SourceRecord(
        key="sharpalphaadvisors",
        url="https://jobs.sharpalphaadvisors.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "sharpalphaadvisors"},
    ),
    SourceRecord(
        key="msivfund",
        url="https://jobs.msivfund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "msivfund"},
    ),
    SourceRecord(
        key="coefficientcap",
        url="https://jobs.coefficientcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "coefficientcap"},
    ),
    SourceRecord(
        key="superset",
        url="https://careers.superset.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "superset"},
    ),
    SourceRecord(
        key="dyrdekmachine",
        url="https://careers.dyrdekmachine.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "dyrdekmachine"},
    ),
    SourceRecord(
        key="wyvcjobs",
        url="https://wyvc-jobs.wyomingbusiness.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "wyvcjobs"},
    ),
    SourceRecord(
        key="octopusenergygeneration",
        url="https://portfoliojobs.octopusenergygeneration.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "octopusenergygeneration"},
    ),
    SourceRecord(
        key="colorintech",
        url="https://jobs.colorintech.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "colorintech"},
    ),
    SourceRecord(
        key="bwam",
        url="https://jobs.bwam.network/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "bwam"},
    ),
    SourceRecord(
        key="boomtownaccelerators",
        url="https://jobs.boomtownaccelerators.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "boomtownaccelerators"},
    ),
    SourceRecord(
        key="rallydaypartners",
        url="https://jobs.rallydaypartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "rallydaypartners"},
    ),
    SourceRecord(
        key="communitiesinschools",
        url="https://networkjobs.communitiesinschools.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "communitiesinschools"},
    ),
    SourceRecord(
        key="acgpartners",
        url="https://jobs.acgpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "acgpartners"},
    ),
    SourceRecord(
        key="rubiconfounders",
        url="https://careers.rubiconfounders.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "rubiconfounders"},
    ),
    SourceRecord(
        key="ovalpark",
        url="https://careers.ovalpark.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ovalpark"},
    ),
    SourceRecord(
        key="varsity",
        url="https://jobs.varsity.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "varsity"},
    ),
    SourceRecord(
        key="preludegrowth",
        url="https://talent.preludegrowth.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "preludegrowth"},
    ),
    SourceRecord(
        key="reddogcap",
        url="https://jobs.reddogcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "reddogcap"},
    ),
    SourceRecord(
        key="tezos",
        url="https://careers.tezos.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "tezos"},
    ),
    SourceRecord(
        key="ocaventures",
        url="https://careers.ocaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "ocaventures"},
    ),
    SourceRecord(
        key="senovo",
        url="https://jobs.senovo.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "senovo"},
    ),
    SourceRecord(
        key="edencp",
        url="https://careers.edencp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "edencp"},
    ),
    SourceRecord(
        key="bainpe",
        url="https://consider.com/boards/vc/bain-pe/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "bainpe"},
    ),
    SourceRecord(
        key="collercapital",
        url="https://consider.com/boards/vc/coller-capital/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "collercapital"},
    ),
    SourceRecord(
        key="generalcatalyst",
        url="https://www.generalcatalyst.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "General Catalyst public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "General Catalyst",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="coatue",
        url="https://www.coatue.com/privates-portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Coatue public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Coatue",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="visionfund",
        url="https://visionfund.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Vision Fund public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Vision Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="iconiqgrowth",
        url="https://www.iconiq.com/growth/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ICONIQ Growth public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "ICONIQ Growth",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="wellingtonprivateinvesting",
        url="https://www.wellington.com/en-us/institutional/capabilities/private-investing/our-investments",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Wellington Private Investing public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Wellington Private Investing",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="workinbiotech",
        url="https://workinbiotech.com/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Work in Biotech public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Work in Biotech",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="flagshippioneering",
        url="https://www.flagshippioneering.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Flagship Pioneering public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Flagship Pioneering",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="archventure",
        url="https://www.archventure.com/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ARCH Venture Partners public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "ARCH Venture Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tpb",
        url="https://www.tpb.co/businesses",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "The Production Board public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "The Production Board",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="airstreet",
        url="https://www.airstreet.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Air Street Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Air Street Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="boozallenventures",
        url="https://www.boozallen.com/expertise/tech-ecosystem/ventures.html",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Booz Allen Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Booz Allen Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="starburstaero",
        url="https://starburst.aero/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Starburst Aerospace public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Starburst Aerospace",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="1011vcportfolio",
        url="https://www.1011vc.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "10-11 Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "10-11 Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="japanenergyfundventures",
        url="https://www.japanenergyfund-ventures.com/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Japan Energy Fund Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Japan Energy Fund Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="conviction",
        url="https://www.conviction.com/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Conviction public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Conviction",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="stationf",
        url="https://stationf.co/startups",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Station F public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Station F",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="plugandplaytechcenter",
        url="https://www.plugandplaytechcenter.com/startups",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Plug and Play Tech Center public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Plug and Play Tech Center",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="angelpad",
        url="https://www.angelpad.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "AngelPad public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "AngelPad",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="iterative",
        url="https://www.iterative.vc/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Iterative public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Iterative",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tribecapital",
        url="https://www.tribe.capital/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Tribe Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Tribe Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="blingcapital",
        url="https://www.blingcapital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bling Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Bling Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="hackvc",
        url="https://hack.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Hack VC public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Hack VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="1kx",
        url="https://1kx.network/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "1kx public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "1kx",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="borderless",
        url="https://borderless.xyz/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Borderless Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Borderless Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="worldfund",
        url="https://www.worldfund.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "World Fund public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "World Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="paleblue",
        url="https://www.pale.blue/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Pale Blue Dot public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Pale Blue Dot",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="planetary",
        url="https://www.planetary.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Planetary public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Planetary",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="kikocapital",
        url="https://www.kikocapital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Kiko Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Kiko Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="civilizationventures",
        url="https://www.civilizationventures.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Civilization Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Civilization Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="sante",
        url="https://www.sante.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Sante Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Sante Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="venbio",
        url="https://www.venbio.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "VenBio public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "VenBio",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="lifeforcecapital",
        url="https://www.lifeforcecapital.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "LifeForce Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "LifeForce Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="2amvc",
        url="https://www.2am.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "2am VC public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "2am VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="indiaquotient",
        url="https://www.indiaquotient.in/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "India Quotient public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "India Quotient",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="waterbridge",
        url="https://www.waterbridge.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "WaterBridge Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "WaterBridge Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="btvvc",
        url="https://www.btv.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bullpen Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Bullpen Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="rebelfund",
        url="https://www.rebel-fund.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Rebel Fund public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Rebel Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="shrug",
        url="https://www.shrug.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Shrug Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Shrug Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elefund",
        url="https://www.elefund.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elefund public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Elefund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="k9ventures",
        url="https://www.k9ventures.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "K9 Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "K9 Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="mach37",
        url="https://www.mach37.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Mach37 public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Mach37",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="operatorcollective",
        url="https://www.operatorcollective.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Operator Collective public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Operator Collective",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="moxxievc",
        url="https://www.moxxie.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Moxxie Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Moxxie Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tuskvc",
        url="https://tusk.vc/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Tusk Venture Partners public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Tusk Venture Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="industrialinnovationfund",
        url="https://jobs.industrialinnovationfund.amazon/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "industrialinnovationfund"},
    ),
    SourceRecord(
        key="theproductionboard",
        url="https://jobs.theproductionboard.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "theproductionboard"},
    ),
    SourceRecord(
        key="joinwoven",
        url="https://careers.joinwoven.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "joinwoven"},
    ),
    SourceRecord(
        key="bpc",
        url="https://jobs.bpc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "bpc"},
    ),
    SourceRecord(
        key="wesleyclover",
        url="https://careers.wesleyclover.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "wesleyclover"},
    ),
    SourceRecord(
        key="voltaventures",
        url="https://jobs.voltaventures.eu/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "voltaventures"},
    ),
    SourceRecord(
        key="kompas",
        url="https://careers.kompas.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "kompas"},
    ),
    SourceRecord(
        key="endeit",
        url="https://careers.endeit.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "endeit"},
    ),
    SourceRecord(
        key="fov",
        url="https://jobs.fov.ventures/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "fov"},
    ),
    SourceRecord(
        key="entradaventures",
        url="https://careers.entradaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "entradaventures"},
    ),
    SourceRecord(
        key="jibevc",
        url="https://jobs.jibevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "jibevc"},
    ),
    SourceRecord(
        key="prelude",
        url="https://talent.prelude.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "prelude"},
    ),
    SourceRecord(
        key="apeiron",
        url="https://jobs.apeiron.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "apeiron"},
    ),
    SourceRecord(
        key="haass",
        url="https://jobs.haass.network/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "haass"},
    ),
    SourceRecord(
        key="karmijnkapitaal",
        url="https://jobs.karmijnkapitaal.nl/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "karmijnkapitaal"},
    ),
    SourceRecord(
        key="logoslabs",
        url="https://jobs.logoslabs.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "logoslabs"},
    ),
    SourceRecord(
        key="akmazocapital",
        url="https://careers.akmazocapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "akmazocapital"},
    ),
    SourceRecord(
        key="merylbreidbart",
        url="https://network.merylbreidbart.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "merylbreidbart"},
    ),
    SourceRecord(
        key="thecenterbham",
        url="https://jobs.thecenterbham.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "thecenterbham"},
    ),
    SourceRecord(
        key="boydinnovationcenter",
        url="https://talent.boydinnovationcenter.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "boydinnovationcenter"},
    ),
    SourceRecord(
        key="transtech",
        url="https://jobs.trans-tech.net/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "transtech"},
    ),
    SourceRecord(
        key="sofindev",
        url="https://sofindev.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "sofindev"},
    ),
    SourceRecord(
        key="jlive",
        url="https://jobs.jlive.app/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "jlive"},
    ),
    SourceRecord(
        key="wctfct",
        url="https://careers.wct-fct.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "wctfct"},
    ),
    SourceRecord(
        key="democracyfund",
        url="https://network-jobs.democracyfund.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "democracyfund"},
    ),
    SourceRecord(
        key="arena",
        url="https://careers.arena.run/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "arena"},
    ),
    SourceRecord(
        key="evanwalden",
        url="https://evanwalden.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "evanwalden"},
    ),
    SourceRecord(
        key="westportyouthcommission",
        url="https://jobbank.westportyouthcommission.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "westportyouthcommission"},
    ),
    SourceRecord(
        key="highlandeurope",
        url="https://careers.highlandeurope.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "highlandeurope"},
    ),
    SourceRecord(
        key="moc",
        url="https://jobs.moc.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "moc"},
    ),
    SourceRecord(
        key="airbusventures",
        url="https://consider.com/boards/vc/airbus-ventures/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "airbusventures"},
    ),
    SourceRecord(
        key="nightcreator",
        url="https://consider.com/boards/vc/night-creator/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "nightcreator"},
    ),
    SourceRecord(
        key="voyagervc",
        url="https://careers.voyagervc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "voyagervc"},
    ),
    SourceRecord(
        key="climactic",
        url="https://jobs.climactic.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "climactic"},
    ),
    SourceRecord(
        key="m12",
        url="https://m12.vc/portfolio/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "M12 public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "M12",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="amdventures",
        url="https://www.amd.com/en/ventures/portfolio.html",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "AMD Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "AMD Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="delltechnologiescapital",
        url="https://www.delltechnologiescapital.com/companies",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Dell Technologies Capital public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Dell Technologies Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="ciscoinvestments",
        url="https://www.ciscoinvestments.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Cisco Investments public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Cisco Investments",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="workdayventures",
        url="https://ventures.workday.com/en-us/partner-companies.html",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Workday Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Workday Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="servicenowventures",
        url="https://www.servicenow.com/company/ventures.html",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ServiceNow Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "ServiceNow Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="snowflakeventures",
        url="https://www.snowflake.com/en/why-snowflake/startup-program/snowflake-ventures/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Snowflake Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Snowflake Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="databricksventures",
        url="https://www.databricks.com/databricks-ventures",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Databricks Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Databricks Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="ibmventures",
        url="https://www.ibm.com/ventures",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "IBM Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "IBM Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="capitaloneventures",
        url="https://capitaloneventures.com/portfolio",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Capital One Ventures public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "Capital One Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="nvidiastartups",
        url="https://www.nvidia.com/en-us/startups/showcase/",
        provider_id="public_page",
        enabled=False,
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "NVIDIA Inception public portfolio or jobs page.",
            "defaultEnabledReason": "Disabled by default because OpenOpps does not yet have a structured adapter for this public page.",
            "label": "NVIDIA Inception",
            "observedStatus": "verified_public_page",
        },
    ),
)
