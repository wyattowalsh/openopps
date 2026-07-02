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
from openopps.providers.boards.workable import workable_token_from_url
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
_ANCHOR_RE = re.compile(
    r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL
)
_HREF_RE = re.compile(r"""href\s*=\s*["'](?P<href>[^"']+)["']""", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(
    r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
    re.IGNORECASE | re.DOTALL,
)
_FILE_LINK_RE = re.compile(
    r"\.(?:avif|css|csv|docx?|gif|ico|jpe?g|js|json|pdf|png|svg|webp|xlsx?)(?:$|[?#])",
    re.IGNORECASE,
)
_GENERIC_PUBLIC_PAGE_LINK_TEXT = {
    "",
    "about",
    "all",
    "apply",
    "back",
    "blog",
    "careers",
    "companies",
    "company",
    "contact",
    "home",
    "jobs",
    "learn more",
    "more",
    "next",
    "portfolio",
    "read more",
    "see all",
    "view",
    "view all",
    "view jobs",
    "visit",
    "visit website",
    "website",
}
_NOISE_PUBLIC_PAGE_HOSTS = {
    "angel.co",
    "calendly.com",
    "discord.gg",
    "facebook.com",
    "github.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "notion.so",
    "t.me",
    "twitter.com",
    "x.com",
    "youtube.com",
}
_PUBLIC_PAGE_COMPANY_PATH_HINTS = (
    "/companies/",
    "/company/",
    "/portfolio/",
    "/startups/",
    "/startup/",
)
_PUBLIC_PAGE_JOB_PATH_HINTS = (
    "/careers",
    "/jobs",
    "/job",
    "/open-roles",
    "/positions",
)
_PUBLIC_PAGE_PROVIDER_HOST_HINTS = (
    "apply.workable.com",
    "boards.greenhouse.io",
    "careers.rippling.com",
    "jobs.ashbyhq.com",
    "jobs.breezy.hr",
    "jobs.gem.com",
    "jobs.jobvite.com",
    "jobs.lever.co",
    "jobs.smartrecruiters.com",
)


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
        raw_metadata={
            **source_taxonomy_metadata(
                provider_type=provider_type,
                coverage_mode=coverage_mode,
                access_type=access_type,
                license_status="needs_review",
                refresh_cadence="manual",
                source_category="startup_ecosystem",
                source_attribution=f"{label} public portfolio or jobs page.",
                inclusion_reason="Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
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
    provider_description = "Best-effort source adapter for public pages without a dedicated structured adapter."

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
            source.url,
            headers={
                "accept": "text/html,application/xhtml+xml",
                "user-agent": "Mozilla/5.0",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        candidates = _public_page_link_candidates(
            response.text, source.url, limit=page_size
        )
        boards, providers = self._normalize_candidates(source, candidates)
        yield (
            boards,
            providers,
            {
                "sourceUrl": source.url,
                "candidateLinks": len(candidates),
                "total": len(boards),
                "note": "Best-effort public page extraction; add a dedicated source adapter for higher fidelity.",
            },
        )

    def _normalize_candidates(
        self, source: SourceRecord, candidates: list[dict[str, str]]
    ) -> tuple[list[BoardRecord], list[BoardProviderRecord]]:
        boards_by_key: dict[str, BoardRecord] = {}
        providers_by_id: dict[str, BoardProviderRecord] = {}
        now = utc_now()
        for candidate in candidates:
            url = candidate["url"]
            route = self.registry.detect_url(
                url,
                source_key=source.key,
                board_key=source_board_key(source.key, _candidate_slug(candidate)),
            )
            slug = _candidate_slug(candidate, route=route)
            board_key = source_board_key(source.key, slug)
            name = (
                _public_page_route_name(route, candidate["name"])
                if route
                else candidate["name"]
            )
            boards_by_key.setdefault(
                board_key,
                BoardRecord(
                    key=board_key,
                    source_key=source.key,
                    remote_id=url,
                    remote_slug=slug,
                    name=name,
                    domain=_domain_from_public_page_url(url),
                    website_url=url,
                    raw_payload={
                        "sourceUrl": source.url,
                        "linkUrl": url,
                        "linkText": candidate.get("text") or None,
                        "extraction": "public_page_anchor",
                    },
                    synced_at=now,
                ),
            )
            if route:
                providers_by_id.setdefault(
                    stable_id(source.key, board_key, route.provider_id),
                    BoardProviderRecord(
                        id=stable_id(source.key, board_key, route.provider_id),
                        source_key=source.key,
                        board_key=board_key,
                        provider_id=route.provider_id,
                        label=route.label,
                        support_level=route.support_level,
                        board_url=route.board_url,
                        token=route.token,
                        host=route.host,
                        tenant=route.tenant,
                        site=route.site,
                        raw_payload={
                            "sourceUrl": source.url,
                            "linkUrl": url,
                            "extraction": "public_page_anchor",
                        },
                        detected_at=now,
                    ),
                )
        return (
            [boards_by_key[key] for key in sorted(boards_by_key)],
            [providers_by_id[key] for key in sorted(providers_by_id)],
        )


def _public_page_link_candidates(
    html: str, source_url: str, *, limit: int
) -> list[dict[str, str]]:
    source_host = (urlparse(source_url).hostname or "").lower().removeprefix("www.")
    candidates: dict[str, dict[str, str]] = {}
    for match in _ANCHOR_RE.finditer(html):
        href = _anchor_href(match.group("attrs"))
        if not href:
            continue
        url = normalize_public_website_url(urljoin(source_url, href))
        if not url or _FILE_LINK_RE.search(url):
            continue
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if not host or host in _NOISE_PUBLIC_PAGE_HOSTS:
            continue
        text = _clean_anchor_text(match.group("body"))
        if not _is_public_page_candidate_url(
            source_host=source_host,
            host=host,
            path=parsed.path,
            text=text,
        ):
            continue
        name = _public_page_candidate_name(text, parsed)
        candidates.setdefault(
            url,
            {
                "url": url,
                "name": name,
                "text": text,
                "host": host,
                "path": parsed.path,
            },
        )
        if len(candidates) >= limit:
            break
    return list(candidates.values())


def _anchor_href(attrs: str) -> str | None:
    match = _HREF_RE.search(attrs)
    if not match:
        return None
    href = unescape(match.group("href")).strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    return href


def _clean_anchor_text(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", unescape(text)).strip()


def _is_public_page_candidate_url(
    *, source_host: str, host: str, path: str, text: str
) -> bool:
    normalized_text = text.strip().lower()
    path_lower = path.lower()
    has_company_path = any(
        hint in path_lower for hint in _PUBLIC_PAGE_COMPANY_PATH_HINTS
    )
    has_job_path = any(hint in path_lower for hint in _PUBLIC_PAGE_JOB_PATH_HINTS)
    has_provider_host = any(
        host == hint or host.endswith(f".{hint}")
        for hint in _PUBLIC_PAGE_PROVIDER_HOST_HINTS
    )
    is_external = host != source_host
    if has_job_path or has_provider_host:
        return True
    if is_external and normalized_text not in _GENERIC_PUBLIC_PAGE_LINK_TEXT:
        return True
    if has_company_path and normalized_text not in _GENERIC_PUBLIC_PAGE_LINK_TEXT:
        return True
    return False


def _public_page_candidate_name(text: str, parsed_url) -> str:
    if text and text.lower() not in _GENERIC_PUBLIC_PAGE_LINK_TEXT:
        return text[:160]
    host = (parsed_url.hostname or "").lower().removeprefix("www.")
    label = host.split(".")[0] if host else parsed_url.path.strip("/")
    return label.replace("-", " ").replace("_", " ").title() or "Public page"


def _public_page_route_name(route: BoardProviderRecord, fallback: str) -> str:
    if route.token:
        return route.token.replace("-", " ").replace("_", " ").title()
    return fallback


def _candidate_slug(
    candidate: dict[str, str], *, route: BoardProviderRecord | None = None
) -> str:
    if route and route.token:
        return slugify(route.token)
    host = candidate.get("host") or _domain_from_public_page_url(candidate["url"]) or ""
    path = candidate.get("path") or urlparse(candidate["url"]).path
    return slugify(host or path or candidate["name"])


def _domain_from_public_page_url(url: str) -> str | None:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().removeprefix("www.") or None


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
        token = workable_token_from_url(url)
        if not token:
            raise ValueError("Workable source URL must include an account token")
        return token


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
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="venture_firm",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="Forum Ventures public Ashby job board.",
            inclusion_reason="Public venture firm job board with an existing Ashby job provider route.",
        ),
        "token": "forum-ventures",
        "label": "Forum Ventures",
    },
)

PEAR_VC_SOURCE = SourceRecord(
    key="pearvc",
    url="https://jobs.ashbyhq.com/Pear-VC",
    provider_id="ashby",
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="venture_firm",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="Pear VC public Ashby job board.",
            inclusion_reason="Public venture firm job board with an existing Ashby job provider route.",
        ),
        "token": "Pear-VC",
        "label": "Pear VC",
    },
)

SOUTHPARKCOMMONS_SOURCE = SourceRecord(
    key="southparkcommons",
    url="https://www.southparkcommons.com/jobs",
    provider_id="southparkcommons",
    raw_metadata=source_taxonomy_metadata(
        provider_type="accelerator",
        coverage_mode="portfolio",
        access_type="public_page_embedded_json",
        license_status="public_attribution_required",
        refresh_cadence="periodic",
        source_category="startup_ecosystem",
        source_attribution="South Park Commons public jobs page embedded JSON payload.",
        inclusion_reason="Public accelerator jobs page with direct provider route hints.",
    ),
)

VENTURE_CAPITAL_CAREERS_SOURCE = SourceRecord(
    key="venturecapitalcareers",
    url="https://venturecapitalcareers.com/companies",
    provider_id="venturecapitalcareers",
    raw_metadata=source_taxonomy_metadata(
        provider_type="job_directory",
        coverage_mode="venture_firm_directory",
        access_type="public_page_html",
        license_status="public_attribution_required",
        refresh_cadence="periodic",
        source_category="startup_ecosystem",
        source_attribution="Venture Capital Careers public companies directory HTML.",
        inclusion_reason="Public venture capital firm directory with stable profile pages.",
    ),
)

VENTURE_LOOP_SOURCE = SourceRecord(
    key="ventureloop",
    url="https://www.ventureloop.com/",
    provider_id="ventureloop",
    raw_metadata=source_taxonomy_metadata(
        provider_type="job_directory",
        coverage_mode="portfolio_jobs",
        access_type="public_landing_page",
        license_status="needs_review",
        refresh_cadence="manual",
        source_category="startup_ecosystem",
        source_attribution="VentureLoop public landing page. Its robots.txt disallows job search result scraping.",
        inclusion_reason="Included through the VentureLoop adapter; public availability still depends on the live site exposing directory data.",
    ),
)

YCOMBINATOR_SOURCE = SourceRecord(
    key="yc",
    url="https://www.ycombinator.com/companies",
    provider_id="ycombinator",
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="accelerator",
            coverage_mode="portfolio",
            access_type="public_page_embedded_json",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_directory",
            source_attribution="Y Combinator public companies page and discovered public Algolia index metadata.",
            inclusion_reason="High-yield public startup directory already supported by OpenOpps.",
        ),
        "applicationId": APPLICATION_ID,
        "indexName": INDEX_NAME,
    },
)


WORKABLE_1871_SOURCE = SourceRecord(
    key="1871",
    url="https://apply.workable.com/1871/",
    provider_id="workable_source",
    raw_metadata={
        **source_taxonomy_metadata(
            provider_type="job_board",
            coverage_mode="portfolio_jobs",
            access_type="public_json_api",
            license_status="public_attribution_required",
            refresh_cadence="periodic",
            source_category="startup_ecosystem",
            source_attribution="1871 public Workable job board.",
            inclusion_reason="Public company job board powered by Workable.",
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
        raw_metadata={},
    ),
    SourceRecord(
        key="highfivepartners",
        url="https://jobs.highfivepartners.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="entrepreneurs",
        url="https://jobs.entrepreneurs.utoronto.ca/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="morestartshere",
        url="https://careers.morestartshere.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="makeitcu",
        url="https://jobs.makeitcu.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="innovationworks",
        url="https://jobs.innovationworks.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="charlestonorg",
        url="https://jobs.charlestoncareers.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="greatersatx",
        url="https://careers.greatersatx.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="inwomenshealth",
        url="https://jobs.inwomenshealth.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="skagit",
        url="https://jobs.skagit.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="workforceinnovationcenter",
        url="https://careers.workforceinnovationcenter.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="jobswithnoboss",
        url="https://jobs.jobswithnoboss.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="grandforksiscooler",
        url="https://jobs.grandforksiscooler.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="spirittechcollective",
        url="https://jobs.spirit-tech-collective.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="imecistart",
        url="https://jobs.imecistart.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="abundancenetwork",
        url="https://jobs.abundancenetwork.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ablepartners",
        url="https://careers.ablepartners.nyc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sierraventures",
        url="https://careers.sierraventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="alkeon",
        url="https://jobs.alkeon.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vertexventures",
        url="https://jobs.vertexventures.co.il/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="kdtvc",
        url="https://jobs.kdtvc.com/companies",
        provider_id="getro",
        raw_metadata={"collectionId": "kdtvc"},
    ),
    SourceRecord(
        key="moberlyedc",
        url="https://jobs.moberly-edc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="weareadamarie",
        url="https://jobs.weareadamarie.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="arbitrum",
        url="https://jobs.arbitrum.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="oneventures",
        url="https://jobs.one-ventures.com.au/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="choosemketech",
        url="https://jobs.choosemketech.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="healthxventures",
        url="https://jobs.healthxventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="watershed",
        url="https://portfolio.watershed.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="13bookscapital",
        url="https://careers.13bookscapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="future",
        url="https://jobs.future.ventures/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vamosventures",
        url="https://jobs.vamosventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="peoplefunction",
        url="https://jobs.peoplefunction.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ironspring",
        url="https://jobs.ironspring.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="forward",
        url="https://careers.forward.one/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="noromoseley",
        url="https://careers.noromoseley.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hopelab",
        url="https://hopelab.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="seaeventures",
        url="https://careers.seaeventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="stventureslab",
        url="https://careers.stventureslab.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="buoyant",
        url="https://careers.buoyant.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sixty8",
        url="https://jobs.sixty8.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="dcedc",
        url="https://careers.dcedc.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="workinseguin",
        url="https://www.workinseguin.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="whatsupstateny",
        url="https://jobs.whatsupstateny.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="myjonesborocom",
        url="https://jobs.myjonesborojobs.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="uprotterdam",
        url="https://jobs.uprotterdam.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="masscybercenter",
        url="https://jobs.masscybercenter.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="toledoregion",
        url="https://jobs.toledoregion.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="workinba",
        url="https://careers.workinba.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="onewagonercounty",
        url="https://jobs.onewagonercounty.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="rockfordchamber",
        url="https://jobs.rockfordchamber.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="placetobelnk",
        url="https://jobs.placetobelnk.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="maip",
        url="https://jobs.maip.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="inovait",
        url="https://jobs.inovait.ca/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="mehi",
        url="https://jobs.mehi.masstech.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="peak",
        url="https://jobs.peak.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vmgpartners",
        url="https://jobs.vmgpartners.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="nucleuscapital",
        url="https://careers.nucleus-capital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="swayvc",
        url="https://talent.swayvc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fayettechamber",
        url="https://careers.fayettechamber.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="smartfinvc",
        url="https://jobs.smartfinvc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="saintjoseph",
        url="https://jobs.saintjoseph.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="nbchamber",
        url="https://jobs.nbchamber.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ssedc",
        url="https://jobs.ss-edc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="innovate",
        url="https://jobs.innovate.ms/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="kayyakventures",
        url="https://jobs.kayyakventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hetz",
        url="https://careers.hetz.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="connexacapital",
        url="https://careers.connexacapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="skale",
        url="https://jobs.skale.space/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="georgetown",
        url="https://georgetown.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="alpinesg",
        url="https://jobs.alpinesg.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="lumoscapitalgroup",
        url="https://lumoscapitalgroup.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="southparkcommonsvc",
        url="https://consider.com/boards/vc/south-park-commons/companies",
        provider_id="consider",
        raw_metadata={"board": "southparkcommonsvc"},
    ),
    SourceRecord(
        key="lcattertonvc",
        url="https://consider.com/boards/vc/l-catterton/companies",
        provider_id="consider",
        raw_metadata={"board": "lcattertonvc"},
    ),
    SourceRecord(
        key="evpvc",
        url="https://consider.com/boards/vc/evp/companies",
        provider_id="consider",
        raw_metadata={"board": "evpvc"},
    ),
    SourceRecord(
        key="firstround",
        url="https://www.firstround.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "First Round public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "First Round",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="foundersfund",
        url="https://foundersfund.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Founders Fund public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Founders Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="slow",
        url="https://slow.co/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Slow Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Slow Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="gpv",
        url="https://www.gpv.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "GPV public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "GPV",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="villageglobal",
        url="https://www.villageglobal.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Village Global public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Village Global",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="foundercollective",
        url="https://foundercollective.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Founder Collective public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Founder Collective",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="bowerycap",
        url="https://bowerycap.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bowery Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Bowery Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="pillar",
        url="https://www.pillar.vc/companies/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Pillar public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Pillar",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="spero",
        url="https://spero.vc/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Spero Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Spero Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="felixcap",
        url="https://www.felixcap.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Felix Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Felix Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="blume",
        url="https://blume.vc/startups",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Blume Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Blume Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elevationcapital",
        url="https://www.elevationcapital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elevation Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Elevation Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="chiratae",
        url="https://www.chiratae.com/companies/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Chiratae Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Chiratae Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="endiya",
        url="https://www.endiya.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Endiya Partners public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Endiya Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="eqtgroup",
        url="https://eqtgroup.com/about/current-portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "EQT public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "EQT",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="heartcore",
        url="https://www.heartcore.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Heartcore public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Heartcore",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="hofcapital",
        url="https://hofcapital.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Hof Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Hof Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="plus",
        url="https://plus.vc/investments-portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Plus VC public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Plus VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="venturesouq",
        url="https://www.venturesouq.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Venturesouq public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Venturesouq",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="saviu",
        url="https://www.saviu.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Saviu Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Saviu Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="indiebio",
        url="https://indiebio.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "indiebio"},
    ),
    SourceRecord(
        key="vistria",
        url="https://consider.com/boards/vc/vistria/companies",
        provider_id="consider",
        raw_metadata={"board": "vistria"},
    ),
    SourceRecord(
        key="valtruis",
        url="https://careers.valtruis.com/companies",
        provider_id="consider",
        raw_metadata={"board": "valtruis"},
    ),
    SourceRecord(
        key="phxfwd",
        url="https://jobs.phxfwd.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="foodtechscout",
        url="https://jobs.foodtechscout.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="i2bf",
        url="https://talent.i2bf.com/companies",
        provider_id="getro",
        raw_metadata={"collectionId": "i2bf"},
    ),
    SourceRecord(
        key="narreach",
        url="https://careers.narreach.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="coinfund",
        url="https://jobs.coinfund.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="matchstickventures",
        url="https://jobs.matchstickventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="plugandplayfoundation",
        url="https://accessopportunities.plugandplayfoundation.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="castleisland",
        url="https://jobs.castleisland.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="togethxr",
        url="https://jobs.togethxr.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="edomarketplace",
        url="https://edomarketplace.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="cantos",
        url="https://jobs.cantos.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="silvertonpartners",
        url="https://jobs.silvertonpartners.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="gfrfund",
        url="https://jobs.gfrfund.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fortinocapital",
        url="https://talent.fortinocapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ziggtalent",
        url="https://jobs.ziggtalent.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="drivetlv",
        url="https://jobs.drivetlv.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="startmunich",
        url="https://jobs.startmunich.de/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="definitioncap",
        url="https://jobs.definitioncap.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="almazcapital",
        url="https://jobs.almazcapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="spartangroup",
        url="https://jobs.spartangroup.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="jdssports",
        url="https://jobs.jdssports.co/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="lyragrowth",
        url="https://jobs.lyragrowth.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="theadclub",
        url="https://careers.theadclub.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="tnentertainment",
        url="https://jobs.tnentertainment.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="rowanedc",
        url="https://jobs.rowanedc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="clarksvilleishiring",
        url="https://jobs.clarksvilleishiring.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="flintandgenesee",
        url="https://jobs.flintandgenesee.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="growingreenvillenc",
        url="https://jobs.growingreenvillenc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="selectpriorinvestments",
        url="https://consider.com/boards/vc/select-prior-investments/companies",
        provider_id="consider",
        raw_metadata={"board": "selectpriorinvestments"},
    ),
    SourceRecord(
        key="fjlabs",
        url="https://fjlabs.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "FJ Labs public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "FJ Labs",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="climatecapital",
        url="https://www.climatecapital.co/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Climate Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Climate Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="shorooq",
        url="https://www.shorooq.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Shorooq public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Shorooq",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="picuscap",
        url="https://www.picuscap.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Picus Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Picus Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="portageinvest",
        url="https://portageinvest.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Portage public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Portage",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="canary",
        url="https://www.canary.com.br/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Canary public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Canary",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="raed",
        url="https://raed.vc/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Raed public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Raed",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tlcomcapital",
        url="https://tlcomcapital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "TLcom Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "TLcom Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="omnivore",
        url="https://omnivore.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Omnivore public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Omnivore",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="3one4capital",
        url="https://www.3one4capital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "3one4 Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "3one4 Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="jungle",
        url="https://www.jungle.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Jungle Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Jungle Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="qualgro",
        url="https://qualgro.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Qualgro public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Qualgro",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="earthshot",
        url="https://www.earthshot.vc/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Earthshot public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Earthshot",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="daphni",
        url="https://www.daphni.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Daphni public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Daphni",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elaia",
        url="https://www.elaia.com/companies/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elaia public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Elaia",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="carbonthirteen",
        url="https://carbonthirteen.com/our-portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Carbon Thirteen public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Carbon Thirteen",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="regeneration",
        url="https://regeneration.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Regeneration public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Regeneration",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="boldstart",
        url="https://boldstart.vc/companies/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Boldstart public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Boldstart",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="bedrockcap",
        url="https://bedrockcap.com/investments",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bedrock Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Bedrock Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="passioncapital",
        url="https://passioncapital.com/fund-portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Passion Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Passion Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="alignedclimatecapital",
        url="https://alignedclimatecapital.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Aligned Climate Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Aligned Climate Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="economicdevelopmentjobs",
        url="https://economicdevelopmentjobs.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="get2knownoke",
        url="https://jobs.get2knownoke.com/companies",
        provider_id="consider",
        raw_metadata={"board": "get2knownoke"},
    ),
    SourceRecord(
        key="whiteboardadvisors",
        url="https://jobs.whiteboardadvisors.com/companies",
        provider_id="consider",
        raw_metadata={"board": "whiteboardadvisors"},
    ),
    SourceRecord(
        key="firstroundcapital",
        url="https://consider.com/boards/vc/first-round-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "firstroundcapital"},
    ),
    SourceRecord(
        key="impactsource",
        url="https://www.impactsource.ai/jobs",
        provider_id="consider",
        raw_metadata={"board": "impactsource"},
    ),
    SourceRecord(
        key="growenid",
        url="https://jobs.growenid.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="techsquareventures",
        url="https://jobs.techsquareventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="s32",
        url="https://s32.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="peoria",
        url="https://jobs.peoria.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="amazingcolumbusga",
        url="https://work.amazingcolumbusga.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="portmuskogee",
        url="https://jobs.portmuskogee.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ton",
        url="https://jobs.ton.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="prospect",
        url="https://consider.com/boards/vc/prospect/companies",
        provider_id="consider",
        raw_metadata={"board": "prospect"},
    ),
    SourceRecord(
        key="riverside",
        url="https://consider.com/boards/vc/riverside/companies",
        provider_id="consider",
        raw_metadata={"board": "riverside"},
    ),
    SourceRecord(
        key="owlvc",
        url="https://careers.owlvc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "owlvc"},
    ),
    SourceRecord(
        key="joplincc",
        url="https://jobs.joplincc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="powerlines",
        url="https://careers.powerlines.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="thecentermemphis",
        url="https://jobs.thecentermemphis.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="silversmith",
        url="https://careers.silversmith.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="limitlessdecatur",
        url="https://jobs.limitlessdecatur.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="workupcoweta",
        url="https://careers.workupcoweta.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hellowestmichigan",
        url="https://jobs.hellowestmichigan.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="portageinvestvc",
        url="https://careers.portageinvest.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="edbi",
        url="https://consider.com/boards/vc/edbi/companies",
        provider_id="consider",
        raw_metadata={"board": "edbi"},
    ),
    SourceRecord(
        key="firstmomentum",
        url="https://jobs.firstmomentum.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="muus",
        url="https://consider.com/boards/vc/muus/companies",
        provider_id="consider",
        raw_metadata={"board": "muus"},
    ),
    SourceRecord(
        key="anthoscapital",
        url="https://consider.com/boards/vc/anthos-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "anthoscapital"},
    ),
    SourceRecord(
        key="merantixaicampus",
        url="https://careers.merantix-aicampus.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="proptech1",
        url="https://consider.com/boards/vc/proptech1/companies",
        provider_id="consider",
        raw_metadata={"board": "proptech1"},
    ),
    SourceRecord(
        key="motherventures",
        url="https://jobs.mother-ventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="spectrumequity",
        url="https://careers.spectrumequity.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ridgeline",
        url="https://jobs.ridgeline.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="avax",
        url="https://jobs.avax.network/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="omnivorevc",
        url="https://jobs.omnivore.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="investnebraska",
        url="https://jobs.investnebraska.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="firstmilevc",
        url="https://jobs.firstmilevc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="dlcda",
        url="https://careers.dlcda.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="leadershiptriangle",
        url="https://jobs.leadershiptriangle.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="glasswing",
        url="https://jobs.glasswing.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fulcrumep",
        url="https://jobs.fulcrumep.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="prudence",
        url="https://jobs.prudence.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fannindevelopment",
        url="https://jobs.fannindevelopment.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="developmilledgeville",
        url="https://careers.developmilledgeville.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="swanandlegend",
        url="https://jobs.swanandlegend.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="blackwellnow",
        url="https://jobs.blackwellnow.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="emanuelchamber",
        url="https://careers.emanuelchamber.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="jvpvc",
        url="https://jobs.jvpvc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "jvpvc"},
    ),
    SourceRecord(
        key="psl",
        url="https://jobs.psl.com/companies",
        provider_id="consider",
        raw_metadata={"board": "psl"},
    ),
    SourceRecord(
        key="story",
        url="https://careers.story.foundation/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hannahgrey",
        url="https://hannahgrey.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hax",
        url="https://jobs.hax.co/companies",
        provider_id="consider",
        raw_metadata={"board": "hax"},
    ),
    SourceRecord(
        key="compa",
        url="https://communityjobs.compa.ai/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="localglobeall",
        url="https://consider.com/boards/vc/localglobe-all/companies",
        provider_id="consider",
        raw_metadata={"board": "localglobeall"},
    ),
    SourceRecord(
        key="soarky",
        url="https://jobs.soar-ky.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fintechaustralia",
        url="https://jobs.fintechaustralia.org.au/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="johotalent",
        url="https://jobs.johotalent.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bitkraft",
        url="https://careers.bitkraft.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="chirataevc",
        url="https://careers.chiratae.com/companies",
        provider_id="consider",
        raw_metadata={"board": "chirataevc"},
    ),
    SourceRecord(
        key="lifemultiplied",
        url="https://jobs.lifemultiplied.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="dutchtech",
        url="https://consider.com/boards/vc/dutchtech/companies",
        provider_id="consider",
        raw_metadata={"board": "dutchtech"},
    ),
    SourceRecord(
        key="mitalumnistartups",
        url="https://consider.com/boards/vc/mit-alumni-startups/companies",
        provider_id="consider",
        raw_metadata={"board": "mitalumnistartups"},
    ),
    SourceRecord(
        key="blumevc",
        url="https://jobs.blume.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="springtide",
        url="https://jobs.springtide.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="collab",
        url="https://jobs.collab.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="inflection",
        url="https://jobs.inflection.fund/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="terratalent",
        url="https://terratalent.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="samaipata",
        url="https://samaipata.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="xrpl",
        url="https://jobs.xrpl.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="movementlabs",
        url="https://ecosystem.movementlabs.xyz/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sui",
        url="https://jobs.sui.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="cobalt",
        url="https://jobs.cobalt.la/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vimian",
        url="https://careers.vimian.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wallstreetfriends",
        url="https://jobs.wallstreetfriends.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="leedsilluminate",
        url="https://jobs.leedsilluminate.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="z2sixtyventures",
        url="https://jobs.z2sixtyventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="animocabrands",
        url="https://careers.animocabrands.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bluewing",
        url="https://careers.bluewing.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="joulevc",
        url="https://jobs.joulevc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="tpycapital",
        url="https://jobs.tpycapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="reddot",
        url="https://careers.red-dot.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="arca",
        url="https://careers.ar.ca/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sharpalphaadvisors",
        url="https://jobs.sharpalphaadvisors.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="msivfund",
        url="https://jobs.msivfund.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="coefficientcap",
        url="https://jobs.coefficientcap.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="superset",
        url="https://careers.superset.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="dyrdekmachine",
        url="https://careers.dyrdekmachine.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wyvcjobs",
        url="https://wyvc-jobs.wyomingbusiness.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="octopusenergygeneration",
        url="https://portfoliojobs.octopusenergygeneration.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="colorintech",
        url="https://jobs.colorintech.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bwam",
        url="https://jobs.bwam.network/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="boomtownaccelerators",
        url="https://jobs.boomtownaccelerators.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="rallydaypartners",
        url="https://jobs.rallydaypartners.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="communitiesinschools",
        url="https://networkjobs.communitiesinschools.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="acgpartners",
        url="https://jobs.acgpartners.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="rubiconfounders",
        url="https://careers.rubiconfounders.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ovalpark",
        url="https://careers.ovalpark.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="varsity",
        url="https://jobs.varsity.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="preludegrowth",
        url="https://talent.preludegrowth.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="reddogcap",
        url="https://jobs.reddogcap.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="tezos",
        url="https://careers.tezos.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ocaventures",
        url="https://careers.ocaventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="senovo",
        url="https://jobs.senovo.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="edencp",
        url="https://careers.edencp.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bainpe",
        url="https://consider.com/boards/vc/bain-pe/companies",
        provider_id="consider",
        raw_metadata={"board": "bainpe"},
    ),
    SourceRecord(
        key="collercapital",
        url="https://consider.com/boards/vc/coller-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "collercapital"},
    ),
    SourceRecord(
        key="generalcatalyst",
        url="https://www.generalcatalyst.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "General Catalyst public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "General Catalyst",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="coatue",
        url="https://www.coatue.com/privates-portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Coatue public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Coatue",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="visionfund",
        url="https://visionfund.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Vision Fund public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Vision Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="iconiqgrowth",
        url="https://www.iconiq.com/growth/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ICONIQ Growth public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "ICONIQ Growth",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="wellingtonprivateinvesting",
        url="https://www.wellington.com/en-us/institutional/capabilities/private-investing/our-investments",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Wellington Private Investing public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Wellington Private Investing",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="workinbiotech",
        url="https://workinbiotech.com/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Work in Biotech public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Work in Biotech",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="flagshippioneering",
        url="https://www.flagshippioneering.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Flagship Pioneering public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Flagship Pioneering",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="archventure",
        url="https://www.archventure.com/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ARCH Venture Partners public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "ARCH Venture Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tpb",
        url="https://www.tpb.co/businesses",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "The Production Board public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "The Production Board",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="airstreet",
        url="https://www.airstreet.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Air Street Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Air Street Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="boozallenventures",
        url="https://www.boozallen.com/expertise/tech-ecosystem/ventures.html",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Booz Allen Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Booz Allen Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="starburstaero",
        url="https://starburst.aero/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Starburst Aerospace public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Starburst Aerospace",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="1011vcportfolio",
        url="https://www.1011vc.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "10-11 Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "10-11 Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="japanenergyfundventures",
        url="https://www.japanenergyfund-ventures.com/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Japan Energy Fund Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Japan Energy Fund Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="conviction",
        url="https://www.conviction.com/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Conviction public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Conviction",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="stationf",
        url="https://stationf.co/startups",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Station F public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Station F",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="plugandplaytechcenter",
        url="https://www.plugandplaytechcenter.com/startups",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Plug and Play Tech Center public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Plug and Play Tech Center",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="angelpad",
        url="https://www.angelpad.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "AngelPad public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "AngelPad",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="iterative",
        url="https://www.iterative.vc/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Iterative public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Iterative",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tribecapital",
        url="https://www.tribe.capital/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Tribe Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Tribe Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="blingcapital",
        url="https://www.blingcapital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bling Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Bling Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="hackvc",
        url="https://hack.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Hack VC public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Hack VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="1kx",
        url="https://1kx.network/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "1kx public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "1kx",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="borderless",
        url="https://borderless.xyz/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Borderless Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Borderless Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="worldfund",
        url="https://www.worldfund.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "World Fund public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "World Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="paleblue",
        url="https://www.pale.blue/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Pale Blue Dot public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Pale Blue Dot",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="planetary",
        url="https://www.planetary.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Planetary public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Planetary",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="kikocapital",
        url="https://www.kikocapital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Kiko Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Kiko Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="civilizationventures",
        url="https://www.civilizationventures.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Civilization Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Civilization Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="sante",
        url="https://www.sante.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Sante Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Sante Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="venbio",
        url="https://www.venbio.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "VenBio public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "VenBio",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="lifeforcecapital",
        url="https://www.lifeforcecapital.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "LifeForce Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "LifeForce Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="2amvc",
        url="https://www.2am.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "2am VC public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "2am VC",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="indiaquotient",
        url="https://www.indiaquotient.in/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "India Quotient public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "India Quotient",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="waterbridge",
        url="https://www.waterbridge.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "WaterBridge Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "WaterBridge Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="btvvc",
        url="https://www.btv.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Bullpen Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Bullpen Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="rebelfund",
        url="https://www.rebel-fund.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Rebel Fund public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Rebel Fund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="shrug",
        url="https://www.shrug.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Shrug Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Shrug Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="elefund",
        url="https://www.elefund.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Elefund public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Elefund",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="k9ventures",
        url="https://www.k9ventures.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "K9 Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "K9 Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="mach37",
        url="https://www.mach37.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Mach37 public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Mach37",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="operatorcollective",
        url="https://www.operatorcollective.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Operator Collective public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Operator Collective",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="moxxievc",
        url="https://www.moxxie.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Moxxie Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Moxxie Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="tuskvc",
        url="https://tusk.vc/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Tusk Venture Partners public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Tusk Venture Partners",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="industrialinnovationfund",
        url="https://jobs.industrialinnovationfund.amazon/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="theproductionboard",
        url="https://jobs.theproductionboard.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="joinwoven",
        url="https://careers.joinwoven.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bpc",
        url="https://jobs.bpc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wesleyclover",
        url="https://careers.wesleyclover.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="voltaventures",
        url="https://jobs.voltaventures.eu/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="kompas",
        url="https://careers.kompas.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="endeit",
        url="https://careers.endeit.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fov",
        url="https://jobs.fov.ventures/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="entradaventures",
        url="https://careers.entradaventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="jibevc",
        url="https://jobs.jibevc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="prelude",
        url="https://talent.prelude.xyz/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="apeiron",
        url="https://jobs.apeiron.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="haass",
        url="https://jobs.haass.network/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="karmijnkapitaal",
        url="https://jobs.karmijnkapitaal.nl/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="logoslabs",
        url="https://jobs.logoslabs.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="akmazocapital",
        url="https://careers.akmazocapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="merylbreidbart",
        url="https://network.merylbreidbart.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="thecenterbham",
        url="https://jobs.thecenterbham.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="boydinnovationcenter",
        url="https://talent.boydinnovationcenter.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="transtech",
        url="https://jobs.trans-tech.net/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sofindev",
        url="https://sofindev.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="jlive",
        url="https://jobs.jlive.app/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wctfct",
        url="https://careers.wct-fct.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="democracyfund",
        url="https://network-jobs.democracyfund.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="arena",
        url="https://careers.arena.run/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="evanwalden",
        url="https://evanwalden.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="westportyouthcommission",
        url="https://jobbank.westportyouthcommission.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="highlandeurope",
        url="https://careers.highlandeurope.com/companies",
        provider_id="consider",
        raw_metadata={"board": "highlandeurope"},
    ),
    SourceRecord(
        key="moc",
        url="https://jobs.moc.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "moc"},
    ),
    SourceRecord(
        key="airbusventures",
        url="https://consider.com/boards/vc/airbus-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "airbusventures"},
    ),
    SourceRecord(
        key="nightcreator",
        url="https://consider.com/boards/vc/night-creator/companies",
        provider_id="consider",
        raw_metadata={"board": "nightcreator"},
    ),
    SourceRecord(
        key="voyagervc",
        url="https://careers.voyagervc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "voyagervc"},
    ),
    SourceRecord(
        key="climactic",
        url="https://jobs.climactic.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "climactic"},
    ),
    SourceRecord(
        key="m12",
        url="https://m12.vc/portfolio/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "M12 public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "M12",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="amdventures",
        url="https://www.amd.com/en/ventures/portfolio.html",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "AMD Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "AMD Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="delltechnologiescapital",
        url="https://www.delltechnologiescapital.com/companies",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Dell Technologies Capital public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Dell Technologies Capital",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="ciscoinvestments",
        url="https://www.ciscoinvestments.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Cisco Investments public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Cisco Investments",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="workdayventures",
        url="https://ventures.workday.com/en-us/partner-companies.html",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Workday Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Workday Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="servicenowventures",
        url="https://www.servicenow.com/company/ventures.html",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "ServiceNow Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "ServiceNow Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="snowflakeventures",
        url="https://www.snowflake.com/en/why-snowflake/startup-program/snowflake-ventures/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Snowflake Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Snowflake Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="databricksventures",
        url="https://www.databricks.com/databricks-ventures",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Databricks Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Databricks Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="ibmventures",
        url="https://www.ibm.com/ventures",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "IBM Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "IBM Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="capitaloneventures",
        url="https://capitaloneventures.com/portfolio",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "Capital One Ventures public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "Capital One Ventures",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="nvidiastartups",
        url="https://www.nvidia.com/en-us/startups/showcase/",
        provider_id="public_page",
        raw_metadata={
            "providerType": "venture_firm",
            "coverageMode": "portfolio",
            "accessType": "public_page_html",
            "licenseStatus": "needs_review",
            "refreshCadence": "manual",
            "sourceCategory": "startup_ecosystem",
            "sourceAttribution": "NVIDIA Inception public portfolio or jobs page.",
            "inclusionReason": "Included through best-effort public-page extraction; add a dedicated adapter when the page exposes structured data.",
            "label": "NVIDIA Inception",
            "observedStatus": "verified_public_page",
        },
    ),
    SourceRecord(
        key="fcventures",
        url="https://careers.fcventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="thembafund",
        url="https://jobs.thembafund.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="blacknova",
        url="https://jobs.blacknova.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vertexventuresvc",
        url="https://jobs.vertexventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="vistaequitypartners",
        url="https://vistaequitypartners.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="graduate",
        url="https://jobs.graduate.nl/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="borderlesscapital",
        url="https://careers.borderlesscapital.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="glynncapital",
        url="https://jobs.glynncapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="csaccelerator",
        url="https://jobs.csaccelerator.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="crossbeam",
        url="https://jobs.crossbeam.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="gtrlink",
        url="https://jobs.gtrlink.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="406ventures",
        url="https://jobs.406ventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="januarycapital",
        url="https://jobs.january.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="beepartners",
        url="https://jobs.beepartners.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="democapital",
        url="https://www.democapital.xyz/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="saascapital",
        url="https://careers.saas-capital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="assembledbrands",
        url="https://jobs.assembledbrands.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="acadianventures",
        url="https://jobs.acadianventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="raleighfounded",
        url="https://jobs.raleighfounded.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="voltcapital",
        url="https://opportunities.volt.capital/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="sequel",
        url="https://jobs.sequel.co/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="calibratevc",
        url="https://jobs.calibratevc.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="catalyticcapital",
        url="https://careers.catalyticcapital.amazon/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="panache",
        url="https://portfoliojobs.panache.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="7pc",
        url="https://jobs.7pc.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="doen",
        url="https://impactjobs.doen.nl/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="chemstars",
        url="https://jobs.chemstars.de/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="daphnivc",
        url="https://talent.daphni.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="photonjobs",
        url="https://find.photonjobs.nl/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="imaginablefutures",
        url="https://jobs.imaginablefutures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="cintrifuse",
        url="https://jobs.cintrifuse.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="mazeimpact",
        url="https://jobs.maze-impact.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="structure",
        url="https://jobs.structure.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="runacap",
        url="https://talent.runacap.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="dnx",
        url="https://jobs.dnx.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fintopcapital",
        url="https://jobs.fintopcapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ethicsinsociety",
        url="https://ethicsinsociety.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="mystartupgig",
        url="https://au.mystartupgig.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="heartcorevc",
        url="https://jobs.heartcore.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="safe",
        url="https://jobs.safe.global/",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="cre",
        url="https://jobs.cre.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="inflectionvc",
        url="https://jobs.inflection.xyz/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="near",
        url="https://careers.near.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hedera",
        url="https://careers.hedera.community/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="pennyjar",
        url="https://jobs.pennyjar.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="magnify",
        url="https://jobs.magnify.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="moonfirevc",
        url="https://positions.moonfire.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="tekfenventures",
        url="https://careers.tekfenventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="optimism",
        url="https://jobs.optimism.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="monad",
        url="https://eco-jobs.monad.xyz/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="discovertechnata",
        url="https://jobs.discovertechnata.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="shieurope",
        url="https://shi-europe.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="getro",
        url="https://www.getro.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="itspronounceddata",
        url="https://itspronounceddata.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="pillarvc",
        url="https://jobs.pillar.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ritualcapital",
        url="https://careers.ritualcapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="theclimatepledge",
        url="https://portfoliojobs.theclimatepledge.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="shakopeemn",
        url="https://jobs.shakopeemn.gov/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="zilliqa",
        url="https://jobs.zilliqa.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="lorimerventures",
        url="https://jobs.lorimerventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="ritualcapitaljobs",
        url="https://jobs.ritualcapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="shakopeemnjobs",
        url="https://jobs.shakopeemn.gov/jobs",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="theclimatepledgejobs",
        url="https://portfoliojobs.theclimatepledge.com/jobs",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="draperstartuphouse",
        url="https://jobs.draperstartuphouse.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="nebari",
        url="https://jobs.nebari.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="zilliqajobs",
        url="https://jobs.zilliqa.com/jobs",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="consider",
        url="https://consider.com/boards/vc/consider/companies",
        provider_id="consider",
        raw_metadata={"board": "consider"},
    ),
    SourceRecord(
        key="workinthehague",
        url="https://jobs.workinthehague.nl/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="spacecapital",
        url="https://jobs.spacecapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bdb",
        url="https://jobs.bdb.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="solana",
        url="https://jobs.solana.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bartowcareers",
        url="https://bartowcareers.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="pfgrowth",
        url="https://jobs.pfgrowth.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="startuplab",
        url="https://jobs.startuplab.no/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="eifo",
        url="https://jobs.eifo.dk/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="collabcurrency",
        url="https://jobs.collabcurrency.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="fintechbelgium",
        url="https://careers.fintechbelgium.be/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="joinimagine",
        url="https://jobs.joinimagine.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="longhash",
        url="https://careers.longhash.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="chicagoquantum",
        url="https://jobs.chicagoquantum.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="bullpencap",
        url="https://talent.bullpencap.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="compound",
        url="https://jobs.compound.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="knoxtech",
        url="https://jobs.knoxtech.org/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="burntislandventures",
        url="https://jobs.burntislandventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="americanhospitalityta",
        url="https://careers.americanhospitalityta.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="camford",
        url="https://jobs.camford.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="tscp",
        url="https://careers.tscp.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="mainshares",
        url="https://jobs.mainshares.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="asugsvsummit",
        url="https://jobs.asugsvsummit.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="avemaria",
        url="https://jobs.avemaria.edu/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="merantix",
        url="https://careers.merantix.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="group11",
        url="https://jobs.group11.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="hl",
        url="https://careers.h-l.vc/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wayfinder",
        url="https://careers.wayfinder.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="prefaceventures",
        url="https://careers.prefaceventures.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="mtechcapital",
        url="https://jobs.mtechcapital.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="rampersand",
        url="https://rampersand.getro.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="nolavateblack",
        url="https://jobs.nolavateblack.com/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="syfy",
        url="https://jobs.syfy.io/companies",
        provider_id="getro",
        raw_metadata={},
    ),
    SourceRecord(
        key="wintermute",
        url="https://consider.com/boards/vc/wintermute/companies",
        provider_id="consider",
        raw_metadata={"board": "wintermute"},
    ),
    SourceRecord(
        key="celesta",
        url="https://consider.com/boards/vc/celesta/companies",
        provider_id="consider",
        raw_metadata={"board": "celesta"},
    ),
    SourceRecord(
        key="dfjgrowth",
        url="https://consider.com/boards/vc/dfj-growth/companies",
        provider_id="consider",
        raw_metadata={"board": "dfjgrowth"},
    ),
    SourceRecord(
        key="jetblueventures",
        url="https://consider.com/boards/vc/jetblue-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "jetblueventures"},
    ),
    SourceRecord(
        key="myriadventures",
        url="https://jobs.myriadventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "myriadventures"},
    ),
    SourceRecord(
        key="partnersgroup",
        url="https://consider.com/boards/vc/partners-group/companies",
        provider_id="consider",
        raw_metadata={"board": "partnersgroup"},
    ),
    SourceRecord(
        key="localglobesolar",
        url="https://consider.com/boards/vc/localglobe-solar/companies",
        provider_id="consider",
        raw_metadata={"board": "localglobesolar"},
    ),
    SourceRecord(
        key="dimensioncap",
        url="https://talent.dimensioncap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "dimensioncap"},
    ),
    SourceRecord(
        key="bipventures",
        url="https://jobs.bipventures.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "bipventures"},
    ),
    SourceRecord(
        key="fast",
        url="https://consider.com/boards/vc/fast/companies",
        provider_id="consider",
        raw_metadata={"board": "fast"},
    ),
    SourceRecord(
        key="inflexion",
        url="https://consider.com/boards/vc/inflexion/companies",
        provider_id="consider",
        raw_metadata={"board": "inflexion"},
    ),
    SourceRecord(
        key="tcg",
        url="https://consider.com/boards/vc/tcg/companies",
        provider_id="consider",
        raw_metadata={"board": "tcg"},
    ),
    SourceRecord(
        key="marketonecapital",
        url="https://consider.com/boards/vc/market-one-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "marketonecapital"},
    ),
    SourceRecord(
        key="blueheron",
        url="https://consider.com/boards/vc/blue-heron/companies",
        provider_id="consider",
        raw_metadata={"board": "blueheron"},
    ),
    SourceRecord(
        key="mvpventures",
        url="https://consider.com/boards/vc/mvp-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "mvpventures"},
    ),
    SourceRecord(
        key="manaventures",
        url="https://consider.com/boards/vc/mana-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "manaventures"},
    ),
    SourceRecord(
        key="newfundcap",
        url="https://jobs.newfundcap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "newfundcap"},
    ),
    SourceRecord(
        key="intuitivesurgical",
        url="https://consider.com/boards/vc/intuitive-surgical/companies",
        provider_id="consider",
        raw_metadata={"board": "intuitivesurgical"},
    ),
    SourceRecord(
        key="redcedarventures",
        url="https://consider.com/boards/vc/red-cedar-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "redcedarventures"},
    ),
    SourceRecord(
        key="greenfieldcapital",
        url="https://consider.com/boards/vc/greenfield-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "greenfieldcapital"},
    ),
    SourceRecord(
        key="geek",
        url="https://jobs.geek.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "geek"},
    ),
    SourceRecord(
        key="cometa",
        url="https://jobs.cometa.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "cometa"},
    ),
    SourceRecord(
        key="crewcapital",
        url="https://consider.com/boards/vc/crew-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "crewcapital"},
    ),
    SourceRecord(
        key="spidercapital",
        url="https://careers.spidercapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "spidercapital"},
    ),
    SourceRecord(
        key="silverlake",
        url="https://consider.com/boards/vc/silver-lake/companies",
        provider_id="consider",
        raw_metadata={"board": "silverlake"},
    ),
    SourceRecord(
        key="kickstartventures",
        url="https://consider.com/boards/vc/kickstart-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "kickstartventures"},
    ),
    SourceRecord(
        key="deshaw",
        url="https://consider.com/boards/vc/deshaw/companies",
        provider_id="consider",
        raw_metadata={"board": "deshaw"},
    ),
    SourceRecord(
        key="loftyventures",
        url="https://jobs.loftyventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "loftyventures"},
    ),
    SourceRecord(
        key="ngc",
        url="https://consider.com/boards/vc/ngc/companies",
        provider_id="consider",
        raw_metadata={"board": "ngc"},
    ),
    SourceRecord(
        key="petersonpartners",
        url="https://consider.com/boards/vc/peterson-partners/companies",
        provider_id="consider",
        raw_metadata={"board": "petersonpartners"},
    ),
    SourceRecord(
        key="fikaventures",
        url="https://consider.com/boards/vc/fika-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "fikaventures"},
    ),
    SourceRecord(
        key="playfair",
        url="https://careers.playfair.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "playfair"},
    ),
    SourceRecord(
        key="krealo",
        url="https://krealo.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "krealo"},
    ),
    SourceRecord(
        key="berachain",
        url="https://berachain.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "berachain"},
    ),
    SourceRecord(
        key="civ",
        url="https://civ.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "civ"},
    ),
    SourceRecord(
        key="beemok",
        url="https://consider.com/boards/vc/beemok/companies",
        provider_id="consider",
        raw_metadata={"board": "beemok"},
    ),
    SourceRecord(
        key="baincapitalinsurance",
        url="https://bain-capital-insurance.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "baincapitalinsurance"},
    ),
    SourceRecord(
        key="auxxo",
        url="https://consider.com/boards/vc/auxxo/companies",
        provider_id="consider",
        raw_metadata={"board": "auxxo"},
    ),
    SourceRecord(
        key="cardumencapital",
        url="https://consider.com/boards/vc/cardumen-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "cardumencapital"},
    ),
    SourceRecord(
        key="nobic",
        url="https://nobic.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "nobic"},
    ),
    SourceRecord(
        key="genoa",
        url="https://genoa.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "genoa"},
    ),
    SourceRecord(
        key="goodwatercapital",
        url="https://goodwater-capital.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "goodwatercapital"},
    ),
    SourceRecord(
        key="mantis",
        url="https://mantis.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "mantis"},
    ),
    SourceRecord(
        key="etherealventuresvc",
        url="https://ethereal-ventures.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "etherealventuresvc"},
    ),
    SourceRecord(
        key="mozillaventures",
        url="https://mozilla-ventures.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "mozillaventures"},
    ),
    SourceRecord(
        key="reventvc",
        url="https://revent.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "reventvc"},
    ),
    SourceRecord(
        key="resolutionventures",
        url="https://resolution-ventures.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "resolutionventures"},
    ),
    SourceRecord(
        key="aixventuresvc",
        url="https://aix-ventures.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "aixventuresvc"},
    ),
    SourceRecord(
        key="hcvcvc",
        url="https://hcvc.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "hcvcvc"},
    ),
    SourceRecord(
        key="gtmfundvc",
        url="https://gtmfund.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gtmfundvc"},
    ),
    SourceRecord(
        key="serenavc",
        url="https://serena.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "serenavc"},
    ),
    SourceRecord(
        key="lemniscapvc",
        url="https://lemniscap.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "lemniscapvc"},
    ),
    SourceRecord(
        key="uada",
        url="https://uada.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "uada"},
    ),
    SourceRecord(
        key="dimensioncapital",
        url="https://dimension-capital.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "dimensioncapital"},
    ),
    SourceRecord(
        key="courtside",
        url="https://courtside.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "courtside"},
    ),
    SourceRecord(
        key="gigascalevc",
        url="https://gigascale.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gigascalevc"},
    ),
    SourceRecord(
        key="360capital",
        url="https://360-capital.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "360capital"},
    ),
    SourceRecord(
        key="amplifylavc",
        url="https://amplify-la.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "amplifylavc"},
    ),
    SourceRecord(
        key="age1vc",
        url="https://age1.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "age1vc"},
    ),
    SourceRecord(
        key="baincryptovc",
        url="https://bain-crypto.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "baincryptovc"},
    ),
    SourceRecord(
        key="eonio",
        url="https://consider.com/boards/co/eon.io",
        provider_id="consider",
        raw_metadata={"board": "eonio"},
    ),
    SourceRecord(
        key="archetypeai",
        url="https://consider.com/boards/co/archetype-ai",
        provider_id="consider",
        raw_metadata={"board": "archetypeai"},
    ),
    SourceRecord(
        key="sheltonai",
        url="https://consider.com/boards/co/shelton-ai",
        provider_id="consider",
        raw_metadata={"board": "sheltonai"},
    ),
    SourceRecord(
        key="arctisai",
        url="https://consider.com/boards/co/arctis-ai",
        provider_id="consider",
        raw_metadata={"board": "arctisai"},
    ),
    SourceRecord(
        key="enterai",
        url="https://consider.com/boards/co/enter-ai",
        provider_id="consider",
        raw_metadata={"board": "enterai"},
    ),
    SourceRecord(
        key="overhypedai",
        url="https://consider.com/boards/co/overhyped-ai",
        provider_id="consider",
        raw_metadata={"board": "overhypedai"},
    ),
    SourceRecord(
        key="tomatoai",
        url="https://consider.com/boards/co/tomato.ai",
        provider_id="consider",
        raw_metadata={"board": "tomatoai"},
    ),
    SourceRecord(
        key="schoolai",
        url="https://consider.com/boards/co/schoolai",
        provider_id="consider",
        raw_metadata={"board": "schoolai"},
    ),
    SourceRecord(
        key="getvantage",
        url="https://consider.com/boards/co/getvantage",
        provider_id="consider",
        raw_metadata={"board": "getvantage"},
    ),
    SourceRecord(
        key="protecttai",
        url="https://consider.com/boards/co/protectt.ai",
        provider_id="consider",
        raw_metadata={"board": "protecttai"},
    ),
    SourceRecord(
        key="theeverycompany",
        url="https://consider.com/boards/co/the-every-company",
        provider_id="consider",
        raw_metadata={"board": "theeverycompany"},
    ),
    SourceRecord(
        key="monami",
        url="https://consider.com/boards/co/mon-ami",
        provider_id="consider",
        raw_metadata={"board": "monami"},
    ),
    SourceRecord(
        key="enduratherapeutics",
        url="https://consider.com/boards/co/endura-therapeutics",
        provider_id="consider",
        raw_metadata={"board": "enduratherapeutics"},
    ),
    SourceRecord(
        key="profluentbio",
        url="https://consider.com/boards/co/profluent-bio",
        provider_id="consider",
        raw_metadata={"board": "profluentbio"},
    ),
    SourceRecord(
        key="cradle",
        url="https://consider.com/boards/co/cradle",
        provider_id="consider",
        raw_metadata={"board": "cradle"},
    ),
    SourceRecord(
        key="openevidence",
        url="https://consider.com/boards/co/openevidence",
        provider_id="consider",
        raw_metadata={"board": "openevidence"},
    ),
    SourceRecord(
        key="iorganbio",
        url="https://consider.com/boards/co/iorganbio",
        provider_id="consider",
        raw_metadata={"board": "iorganbio"},
    ),
    SourceRecord(
        key="cellsbin",
        url="https://consider.com/boards/co/cellsbin",
        provider_id="consider",
        raw_metadata={"board": "cellsbin"},
    ),
    SourceRecord(
        key="transfyrbio",
        url="https://consider.com/boards/co/transfyr-bio",
        provider_id="consider",
        raw_metadata={"board": "transfyrbio"},
    ),
    SourceRecord(
        key="manifoldbio",
        url="https://consider.com/boards/co/manifold-bio",
        provider_id="consider",
        raw_metadata={"board": "manifoldbio"},
    ),
    SourceRecord(
        key="gctherapeutics",
        url="https://consider.com/boards/co/gc-therapeutics",
        provider_id="consider",
        raw_metadata={"board": "gctherapeutics"},
    ),
    SourceRecord(
        key="climaterobotics",
        url="https://consider.com/boards/co/climate-robotics",
        provider_id="consider",
        raw_metadata={"board": "climaterobotics"},
    ),
    SourceRecord(
        key="bezerocarbon",
        url="https://consider.com/boards/co/bezero-carbon",
        provider_id="consider",
        raw_metadata={"board": "bezerocarbon"},
    ),
    SourceRecord(
        key="buildspace",
        url="https://consider.com/boards/co/buildspace",
        provider_id="consider",
        raw_metadata={"board": "buildspace"},
    ),
    SourceRecord(
        key="spaceandtime",
        url="https://consider.com/boards/co/space-and-time",
        provider_id="consider",
        raw_metadata={"board": "spaceandtime"},
    ),
    SourceRecord(
        key="whitebit",
        url="https://consider.com/boards/co/whitebit",
        provider_id="consider",
        raw_metadata={"board": "whitebit"},
    ),
    SourceRecord(
        key="physicalintelligence",
        url="https://consider.com/boards/co/physical-intelligence",
        provider_id="consider",
        raw_metadata={"board": "physicalintelligence"},
    ),
    SourceRecord(
        key="withintrinsic",
        url="https://consider.com/boards/co/with-intrinsic",
        provider_id="consider",
        raw_metadata={"board": "withintrinsic"},
    ),
    SourceRecord(
        key="tactasystems",
        url="https://consider.com/boards/co/tacta-systems",
        provider_id="consider",
        raw_metadata={"board": "tactasystems"},
    ),
    SourceRecord(
        key="frodobotsai",
        url="https://consider.com/boards/co/frodobots-ai",
        provider_id="consider",
        raw_metadata={"board": "frodobotsai"},
    ),
    SourceRecord(
        key="zocks",
        url="https://consider.com/boards/co/zocks",
        provider_id="consider",
        raw_metadata={"board": "zocks"},
    ),
    SourceRecord(
        key="maxinsights",
        url="https://consider.com/boards/co/maxinsights",
        provider_id="consider",
        raw_metadata={"board": "maxinsights"},
    ),
    SourceRecord(
        key="biatechcorporation",
        url="https://consider.com/boards/co/biatech-corporation",
        provider_id="consider",
        raw_metadata={"board": "biatechcorporation"},
    ),
    SourceRecord(
        key="motorq",
        url="https://consider.com/boards/co/motorq",
        provider_id="consider",
        raw_metadata={"board": "motorq"},
    ),
    SourceRecord(
        key="fleetrobotics",
        url="https://consider.com/boards/co/fleet-robotics",
        provider_id="consider",
        raw_metadata={"board": "fleetrobotics"},
    ),
    SourceRecord(
        key="runwayml",
        url="https://consider.com/boards/co/runwayml",
        provider_id="consider",
        raw_metadata={"board": "runwayml"},
    ),
    SourceRecord(
        key="develophealth",
        url="https://consider.com/boards/co/develop-health",
        provider_id="consider",
        raw_metadata={"board": "develophealth"},
    ),
    SourceRecord(
        key="valaratomics",
        url="https://consider.com/boards/co/valar-atomics",
        provider_id="consider",
        raw_metadata={"board": "valaratomics"},
    ),
    SourceRecord(
        key="orolabs",
        url="https://consider.com/boards/co/oro-labs",
        provider_id="consider",
        raw_metadata={"board": "orolabs"},
    ),
    SourceRecord(
        key="saronictechnologies",
        url="https://consider.com/boards/co/saronic-technologies",
        provider_id="consider",
        raw_metadata={"board": "saronictechnologies"},
    ),
    SourceRecord(
        key="runetechnologies",
        url="https://consider.com/boards/co/rune-technologies",
        provider_id="consider",
        raw_metadata={"board": "runetechnologies"},
    ),
    SourceRecord(
        key="knoxsystems",
        url="https://consider.com/boards/co/knox-systems",
        provider_id="consider",
        raw_metadata={"board": "knoxsystems"},
    ),
    SourceRecord(
        key="castelion",
        url="https://consider.com/boards/co/castelion",
        provider_id="consider",
        raw_metadata={"board": "castelion"},
    ),
    SourceRecord(
        key="northwoodspace",
        url="https://consider.com/boards/co/northwood-space",
        provider_id="consider",
        raw_metadata={"board": "northwoodspace"},
    ),
    SourceRecord(
        key="aaloatomics",
        url="https://consider.com/boards/co/aalo-atomics",
        provider_id="consider",
        raw_metadata={"board": "aaloatomics"},
    ),
    SourceRecord(
        key="sayari",
        url="https://consider.com/boards/co/sayari",
        provider_id="consider",
        raw_metadata={"board": "sayari"},
    ),
    SourceRecord(
        key="bullmoose",
        url="https://consider.com/boards/vc/bull-moose/companies",
        provider_id="consider",
        raw_metadata={"board": "bullmoose"},
    ),
    SourceRecord(
        key="xai",
        url="https://consider.com/boards/co/xai",
        provider_id="consider",
        raw_metadata={"board": "xai"},
    ),
    SourceRecord(
        key="cursor",
        url="https://consider.com/boards/co/cursor",
        provider_id="consider",
        raw_metadata={"board": "cursor"},
    ),
    SourceRecord(
        key="supabase",
        url="https://consider.com/boards/co/supabase",
        provider_id="consider",
        raw_metadata={"board": "supabase"},
    ),
    SourceRecord(
        key="blackforestlabs",
        url="https://consider.com/boards/co/black-forest-labs",
        provider_id="consider",
        raw_metadata={"board": "blackforestlabs"},
    ),
    SourceRecord(
        key="worldlabs",
        url="https://consider.com/boards/co/world-labs",
        provider_id="consider",
        raw_metadata={"board": "worldlabs"},
    ),
    SourceRecord(
        key="bedrockrobotics",
        url="https://consider.com/boards/co/bedrock-robotics",
        provider_id="consider",
        raw_metadata={"board": "bedrockrobotics"},
    ),
    SourceRecord(
        key="pavespacesa",
        url="https://consider.com/boards/co/pave-space-sa",
        provider_id="consider",
        raw_metadata={"board": "pavespacesa"},
    ),
    SourceRecord(
        key="proximafusion",
        url="https://consider.com/boards/co/proxima-fusion",
        provider_id="consider",
        raw_metadata={"board": "proximafusion"},
    ),
    SourceRecord(
        key="inertia",
        url="https://consider.com/boards/co/inertia",
        provider_id="consider",
        raw_metadata={"board": "inertia"},
    ),
    SourceRecord(
        key="geminienergy",
        url="https://consider.com/boards/co/gemini-energy",
        provider_id="consider",
        raw_metadata={"board": "geminienergy"},
    ),
    SourceRecord(
        key="haffnerenergy",
        url="https://consider.com/boards/co/haffner-energy",
        provider_id="consider",
        raw_metadata={"board": "haffnerenergy"},
    ),
    SourceRecord(
        key="entolabs",
        url="https://consider.com/boards/co/ento-labs",
        provider_id="consider",
        raw_metadata={"board": "entolabs"},
    ),
    SourceRecord(
        key="cabalettabio",
        url="https://consider.com/boards/co/cabaletta-bio",
        provider_id="consider",
        raw_metadata={"board": "cabalettabio"},
    ),
    SourceRecord(
        key="sporebio",
        url="https://consider.com/boards/co/spore.bio",
        provider_id="consider",
        raw_metadata={"board": "sporebio"},
    ),
    SourceRecord(
        key="ambiencehealthcare",
        url="https://consider.com/boards/co/ambience-healthcare",
        provider_id="consider",
        raw_metadata={"board": "ambiencehealthcare"},
    ),
    SourceRecord(
        key="synapticure",
        url="https://consider.com/boards/co/synapticure",
        provider_id="consider",
        raw_metadata={"board": "synapticure"},
    ),
    SourceRecord(
        key="kyanhealth",
        url="https://consider.com/boards/co/kyan-health",
        provider_id="consider",
        raw_metadata={"board": "kyanhealth"},
    ),
    SourceRecord(
        key="mazenanimalhealth",
        url="https://consider.com/boards/co/mazen-animal-health",
        provider_id="consider",
        raw_metadata={"board": "mazenanimalhealth"},
    ),
    SourceRecord(
        key="npowermedicine",
        url="https://consider.com/boards/co/n-power-medicine",
        provider_id="consider",
        raw_metadata={"board": "npowermedicine"},
    ),
    SourceRecord(
        key="genecehealth",
        url="https://consider.com/boards/co/genece-health",
        provider_id="consider",
        raw_metadata={"board": "genecehealth"},
    ),
    SourceRecord(
        key="aiprise",
        url="https://consider.com/boards/co/aiprise",
        provider_id="consider",
        raw_metadata={"board": "aiprise"},
    ),
    SourceRecord(
        key="paretoai",
        url="https://consider.com/boards/co/pareto.ai",
        provider_id="consider",
        raw_metadata={"board": "paretoai"},
    ),
    SourceRecord(
        key="kai",
        url="https://consider.com/boards/co/kai",
        provider_id="consider",
        raw_metadata={"board": "kai"},
    ),
    SourceRecord(
        key="viggle",
        url="https://consider.com/boards/co/viggle",
        provider_id="consider",
        raw_metadata={"board": "viggle"},
    ),
    SourceRecord(
        key="gumloop",
        url="https://consider.com/boards/co/gumloop",
        provider_id="consider",
        raw_metadata={"board": "gumloop"},
    ),
    SourceRecord(
        key="lmarena",
        url="https://consider.com/boards/co/lmarena",
        provider_id="consider",
        raw_metadata={"board": "lmarena"},
    ),
    SourceRecord(
        key="prophecy",
        url="https://consider.com/boards/co/prophecy",
        provider_id="consider",
        raw_metadata={"board": "prophecy"},
    ),
    SourceRecord(
        key="devtron",
        url="https://consider.com/boards/co/devtron",
        provider_id="consider",
        raw_metadata={"board": "devtron"},
    ),
    SourceRecord(
        key="workwize",
        url="https://consider.com/boards/co/workwize",
        provider_id="consider",
        raw_metadata={"board": "workwize"},
    ),
    SourceRecord(
        key="veridooh",
        url="https://consider.com/boards/co/veridooh",
        provider_id="consider",
        raw_metadata={"board": "veridooh"},
    ),
    SourceRecord(
        key="soteranalytics",
        url="https://consider.com/boards/co/soter-analytics",
        provider_id="consider",
        raw_metadata={"board": "soteranalytics"},
    ),
    SourceRecord(
        key="mercor",
        url="https://consider.com/boards/co/mercor",
        provider_id="consider",
        raw_metadata={"board": "mercor"},
    ),
    SourceRecord(
        key="yieldstreet",
        url="https://consider.com/boards/co/yieldstreet",
        provider_id="consider",
        raw_metadata={"board": "yieldstreet"},
    ),
    SourceRecord(
        key="pavebank",
        url="https://consider.com/boards/co/pave-bank",
        provider_id="consider",
        raw_metadata={"board": "pavebank"},
    ),
    SourceRecord(
        key="nomba",
        url="https://consider.com/boards/co/nomba",
        provider_id="consider",
        raw_metadata={"board": "nomba"},
    ),
    SourceRecord(
        key="telda",
        url="https://consider.com/boards/co/telda",
        provider_id="consider",
        raw_metadata={"board": "telda"},
    ),
    SourceRecord(
        key="wetravel",
        url="https://consider.com/boards/co/wetravel",
        provider_id="consider",
        raw_metadata={"board": "wetravel"},
    ),
    SourceRecord(
        key="k12coalition",
        url="https://consider.com/boards/co/k12-coalition",
        provider_id="consider",
        raw_metadata={"board": "k12coalition"},
    ),
    SourceRecord(
        key="stemscopes",
        url="https://consider.com/boards/co/stemscopes",
        provider_id="consider",
        raw_metadata={"board": "stemscopes"},
    ),
    SourceRecord(
        key="edconnective",
        url="https://consider.com/boards/co/edconnective",
        provider_id="consider",
        raw_metadata={"board": "edconnective"},
    ),
    SourceRecord(
        key="curipod",
        url="https://consider.com/boards/co/curipod",
        provider_id="consider",
        raw_metadata={"board": "curipod"},
    ),
    SourceRecord(
        key="moxiebeauty",
        url="https://consider.com/boards/co/moxie-beauty",
        provider_id="consider",
        raw_metadata={"board": "moxiebeauty"},
    ),
    SourceRecord(
        key="larq",
        url="https://consider.com/boards/co/larq",
        provider_id="consider",
        raw_metadata={"board": "larq"},
    ),
    SourceRecord(
        key="suger",
        url="https://consider.com/boards/co/suger",
        provider_id="consider",
        raw_metadata={"board": "suger"},
    ),
    SourceRecord(
        key="azuna",
        url="https://consider.com/boards/co/azuna",
        provider_id="consider",
        raw_metadata={"board": "azuna"},
    ),
    SourceRecord(
        key="risepoint",
        url="https://consider.com/boards/co/risepoint",
        provider_id="consider",
        raw_metadata={"board": "risepoint"},
    ),
    SourceRecord(
        key="plugmotors",
        url="https://consider.com/boards/co/plug-motors",
        provider_id="consider",
        raw_metadata={"board": "plugmotors"},
    ),
    SourceRecord(
        key="podfoods",
        url="https://consider.com/boards/co/pod-foods",
        provider_id="consider",
        raw_metadata={"board": "podfoods"},
    ),
    SourceRecord(
        key="yardzen",
        url="https://consider.com/boards/co/yardzen",
        provider_id="consider",
        raw_metadata={"board": "yardzen"},
    ),
    SourceRecord(
        key="thunes",
        url="https://consider.com/boards/co/thunes",
        provider_id="consider",
        raw_metadata={"board": "thunes"},
    ),
    SourceRecord(
        key="karmanspacedefense",
        url="https://consider.com/boards/co/karman-space-defense",
        provider_id="consider",
        raw_metadata={"board": "karmanspacedefense"},
    ),
    SourceRecord(
        key="havocai",
        url="https://consider.com/boards/co/havocai",
        provider_id="consider",
        raw_metadata={"board": "havocai"},
    ),
    SourceRecord(
        key="bluewaterautonomy",
        url="https://consider.com/boards/co/blue-water-autonomy",
        provider_id="consider",
        raw_metadata={"board": "bluewaterautonomy"},
    ),
    SourceRecord(
        key="furientis",
        url="https://consider.com/boards/co/furientis",
        provider_id="consider",
        raw_metadata={"board": "furientis"},
    ),
    SourceRecord(
        key="rohirrim",
        url="https://consider.com/boards/co/rohirrim",
        provider_id="consider",
        raw_metadata={"board": "rohirrim"},
    ),
    SourceRecord(
        key="greptile",
        url="https://consider.com/boards/co/greptile",
        provider_id="consider",
        raw_metadata={"board": "greptile"},
    ),
    SourceRecord(
        key="mechanicalorchard",
        url="https://consider.com/boards/co/mechanical-orchard",
        provider_id="consider",
        raw_metadata={"board": "mechanicalorchard"},
    ),
    SourceRecord(
        key="appwrite",
        url="https://consider.com/boards/co/appwrite",
        provider_id="consider",
        raw_metadata={"board": "appwrite"},
    ),
    SourceRecord(
        key="spacelift",
        url="https://consider.com/boards/co/spacelift",
        provider_id="consider",
        raw_metadata={"board": "spacelift"},
    ),
    SourceRecord(
        key="namespace",
        url="https://consider.com/boards/co/namespace",
        provider_id="consider",
        raw_metadata={"board": "namespace"},
    ),
    SourceRecord(
        key="copilotkit",
        url="https://consider.com/boards/co/copilotkit",
        provider_id="consider",
        raw_metadata={"board": "copilotkit"},
    ),
    SourceRecord(
        key="composio",
        url="https://consider.com/boards/co/composio",
        provider_id="consider",
        raw_metadata={"board": "composio"},
    ),
    SourceRecord(
        key="jamsocket",
        url="https://consider.com/boards/co/jamsocket",
        provider_id="consider",
        raw_metadata={"board": "jamsocket"},
    ),
    SourceRecord(
        key="shuttle",
        url="https://consider.com/boards/co/shuttle",
        provider_id="consider",
        raw_metadata={"board": "shuttle"},
    ),
    SourceRecord(
        key="nivoda",
        url="https://consider.com/boards/co/nivoda",
        provider_id="consider",
        raw_metadata={"board": "nivoda"},
    ),
    SourceRecord(
        key="capimoney",
        url="https://consider.com/boards/co/capi-money",
        provider_id="consider",
        raw_metadata={"board": "capimoney"},
    ),
    SourceRecord(
        key="cleva",
        url="https://consider.com/boards/co/cleva",
        provider_id="consider",
        raw_metadata={"board": "cleva"},
    ),
    SourceRecord(
        key="mnzl",
        url="https://consider.com/boards/co/mnzl",
        provider_id="consider",
        raw_metadata={"board": "mnzl"},
    ),
    SourceRecord(
        key="bondfinancialtechnologies",
        url="https://consider.com/boards/co/bond-financial-technologies",
        provider_id="consider",
        raw_metadata={"board": "bondfinancialtechnologies"},
    ),
    SourceRecord(
        key="tomocredit",
        url="https://consider.com/boards/co/tomocredit",
        provider_id="consider",
        raw_metadata={"board": "tomocredit"},
    ),
    SourceRecord(
        key="pdtpartners",
        url="https://consider.com/boards/co/pdt-partners",
        provider_id="consider",
        raw_metadata={"board": "pdtpartners"},
    ),
    SourceRecord(
        key="cascadeclimate",
        url="https://consider.com/boards/co/cascade-climate",
        provider_id="consider",
        raw_metadata={"board": "cascadeclimate"},
    ),
    SourceRecord(
        key="octaviacarbon",
        url="https://consider.com/boards/co/octavia-carbon",
        provider_id="consider",
        raw_metadata={"board": "octaviacarbon"},
    ),
    SourceRecord(
        key="sylvera",
        url="https://consider.com/boards/co/sylvera",
        provider_id="consider",
        raw_metadata={"board": "sylvera"},
    ),
    SourceRecord(
        key="firststreet",
        url="https://consider.com/boards/co/first-street",
        provider_id="consider",
        raw_metadata={"board": "firststreet"},
    ),
    SourceRecord(
        key="rhizome",
        url="https://consider.com/boards/co/rhizome",
        provider_id="consider",
        raw_metadata={"board": "rhizome"},
    ),
    SourceRecord(
        key="carbonsifr",
        url="https://consider.com/boards/co/carbonsifr",
        provider_id="consider",
        raw_metadata={"board": "carbonsifr"},
    ),
    SourceRecord(
        key="southpole",
        url="https://consider.com/boards/co/south-pole",
        provider_id="consider",
        raw_metadata={"board": "southpole"},
    ),
    SourceRecord(
        key="tem",
        url="https://consider.com/boards/co/tem.",
        provider_id="consider",
        raw_metadata={"board": "tem"},
    ),
    SourceRecord(
        key="glyphicbiotechnologies",
        url="https://consider.com/boards/co/glyphic-biotechnologies",
        provider_id="consider",
        raw_metadata={"board": "glyphicbiotechnologies"},
    ),
    SourceRecord(
        key="antarestherapeutics",
        url="https://consider.com/boards/co/antares-therapeutics",
        provider_id="consider",
        raw_metadata={"board": "antarestherapeutics"},
    ),
    SourceRecord(
        key="azarahealthcare",
        url="https://consider.com/boards/co/azara-healthcare",
        provider_id="consider",
        raw_metadata={"board": "azarahealthcare"},
    ),
    SourceRecord(
        key="isaachealth",
        url="https://consider.com/boards/co/isaac-health",
        provider_id="consider",
        raw_metadata={"board": "isaachealth"},
    ),
    SourceRecord(
        key="nexhealth",
        url="https://consider.com/boards/co/nexhealth",
        provider_id="consider",
        raw_metadata={"board": "nexhealth"},
    ),
    SourceRecord(
        key="nourishedrx",
        url="https://consider.com/boards/co/nourishedrx",
        provider_id="consider",
        raw_metadata={"board": "nourishedrx"},
    ),
    SourceRecord(
        key="firststophealth",
        url="https://consider.com/boards/co/first-stop-health",
        provider_id="consider",
        raw_metadata={"board": "firststophealth"},
    ),
    SourceRecord(
        key="ambirobotics",
        url="https://consider.com/boards/co/ambi-robotics",
        provider_id="consider",
        raw_metadata={"board": "ambirobotics"},
    ),
    SourceRecord(
        key="foundryrobotics",
        url="https://consider.com/boards/co/foundry-robotics",
        provider_id="consider",
        raw_metadata={"board": "foundryrobotics"},
    ),
    SourceRecord(
        key="civrobotics",
        url="https://consider.com/boards/co/civ-robotics",
        provider_id="consider",
        raw_metadata={"board": "civrobotics"},
    ),
    SourceRecord(
        key="togglerobotics",
        url="https://consider.com/boards/co/toggle-robotics",
        provider_id="consider",
        raw_metadata={"board": "togglerobotics"},
    ),
    SourceRecord(
        key="kerriganrobotics",
        url="https://consider.com/boards/co/kerrigan-robotics",
        provider_id="consider",
        raw_metadata={"board": "kerriganrobotics"},
    ),
    SourceRecord(
        key="coco",
        url="https://consider.com/boards/co/coco",
        provider_id="consider",
        raw_metadata={"board": "coco"},
    ),
    SourceRecord(
        key="gatherai",
        url="https://consider.com/boards/co/gather-ai",
        provider_id="consider",
        raw_metadata={"board": "gatherai"},
    ),
    SourceRecord(
        key="louisaai",
        url="https://consider.com/boards/co/louisa-ai",
        provider_id="consider",
        raw_metadata={"board": "louisaai"},
    ),
    SourceRecord(
        key="qai",
        url="https://consider.com/boards/co/q.ai",
        provider_id="consider",
        raw_metadata={"board": "qai"},
    ),
    SourceRecord(
        key="fyxerai",
        url="https://consider.com/boards/co/fyxer-ai",
        provider_id="consider",
        raw_metadata={"board": "fyxerai"},
    ),
    SourceRecord(
        key="apfusion",
        url="https://consider.com/boards/co/apfusion",
        provider_id="consider",
        raw_metadata={"board": "apfusion"},
    ),
    SourceRecord(
        key="crafteducationsystem",
        url="https://consider.com/boards/co/craft-education-system",
        provider_id="consider",
        raw_metadata={"board": "crafteducationsystem"},
    ),
    SourceRecord(
        key="metaschool",
        url="https://consider.com/boards/co/metaschool",
        provider_id="consider",
        raw_metadata={"board": "metaschool"},
    ),
)
