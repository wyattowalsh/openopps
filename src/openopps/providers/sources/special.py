from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from html import unescape
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from loguru import logger

from openopps.http import (
    request_with_public_redirect_validation,
    retrying_json_request,
    retrying_text_request,
)
from openopps.models import (
    AshbyJobBoardResponse,
    BoardProviderRecord,
    BoardRecord,
    GreenhouseJobsResponse,
    ProviderSupport,
    SourceRecord,
    YCombinatorAlgoliaResponse,
    YCombinatorAlgoliaResult,
    YCombinatorCompanyHit,
    normalize_public_website_url,
    utc_now,
    validate_public_https_url,
)
from openopps.providers.boards.tokens import (
    greenhouse_token_from_url,
    lever_token_from_url,
)
from openopps.providers.boards.workable import (
    WorkablePublicClient,
    workable_page_budget,
    workable_token_from_url,
)
from openopps.providers.sources.source_utils import (
    load_packaged_portfolio_source_records,
    source_taxonomy_metadata,
)
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


class PublicPageSourceAdapter:
    provider_id = "public_page"
    provider_label = "Public Page"
    provider_description = "Best-effort source adapter for public pages without a dedicated structured adapter."

    def __init__(self, settings: OpenOppsSettings):
        from openopps.providers.registry import provider_registry

        self.settings = settings
        self.registry = provider_registry(settings=settings)
        self._request_text = retrying_text_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        html = await self._request_text(
            client,
            "GET",
            source.url,
            headers={"accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
        )
        candidates = _public_page_link_candidates(html, source.url, limit=page_size)
        boards, providers, normalize_meta = self._normalize_candidates(
            source, candidates
        )
        yield (
            boards,
            providers,
            {
                "sourceUrl": source.url,
                "candidateLinks": len(candidates),
                "total": len(boards),
                "boardKeyCollisions": normalize_meta["boardKeyCollisions"],
                "note": "Best-effort public page extraction; add a dedicated source adapter for higher fidelity.",
            },
        )

    def _normalize_candidates(
        self, source: SourceRecord, candidates: list[dict[str, str]]
    ) -> tuple[list[BoardRecord], list[BoardProviderRecord], dict[str, int]]:
        boards_by_key: dict[str, BoardRecord] = {}
        providers_by_id: dict[str, BoardProviderRecord] = {}
        board_key_collisions = 0
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
            if board_key in boards_by_key:
                board_key_collisions += 1
                logger.debug(
                    "Skipping public page board-key collision for {} ({})",
                    board_key,
                    url,
                )
            else:
                boards_by_key[board_key] = BoardRecord(
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
        if board_key_collisions:
            logger.debug(
                "Public page extraction skipped {} duplicate board keys for {}",
                board_key_collisions,
                source.key,
            )
        return (
            [boards_by_key[key] for key in sorted(boards_by_key)],
            [providers_by_id[key] for key in sorted(providers_by_id)],
            {"boardKeyCollisions": board_key_collisions},
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


class _StaticJobBoardSourceAdapter(ABC):
    """Shared board/route yield for single-token public job boards (GH, Lever, …)."""

    route_provider_id: str
    route_provider_label: str

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
        del page_size
        validate_public_https_url(source.url)
        token = str(
            source.raw_metadata.get("token") or self._token_from_url(source.url)
        )
        label = str(source.raw_metadata.get("label") or token)
        remote_slug = slugify(token)
        board_key = source_board_key(source.key, remote_slug)
        total = await self._job_count(client, token)
        now = utc_now()
        board = BoardRecord(
            key=board_key,
            source_key=source.key,
            remote_id=token,
            remote_slug=remote_slug,
            name=label,
            num_jobs_hint=total,
            raw_payload={"sourceUrl": source.url, "token": token},
            synced_at=now,
        )
        provider = BoardProviderRecord(
            id=stable_id(source.key, board_key, self.route_provider_id),
            source_key=source.key,
            board_key=board_key,
            provider_id=self.route_provider_id,
            label=self.route_provider_label,
            support_level=ProviderSupport.JOBS,
            count_hint=total,
            board_url=source.url,
            token=token,
            raw_payload={"sourceUrl": source.url, "token": token},
            detected_at=now,
        )
        yield [board], [provider], {"token": token, "total": total}

    @abstractmethod
    def _token_from_url(self, url: str) -> str:
        """Extract the public board token/slug from a source URL."""

    @abstractmethod
    async def _job_count(self, client: httpx.AsyncClient, token: str) -> int:
        """Return the public job count for a board token."""


class GreenhouseSourceAdapter(_StaticJobBoardSourceAdapter):
    provider_id = "greenhouse_source"
    provider_label = "Greenhouse Source"
    provider_description = (
        "Direct Greenhouse source adapter that exposes a public job board as one route."
    )
    route_provider_id = "greenhouse"
    route_provider_label = "Greenhouse"

    def _token_from_url(self, url: str) -> str:
        token = greenhouse_token_from_url(url)
        if not token:
            raise ValueError("Greenhouse source URL must include a board token")
        return token

    async def _job_count(self, client: httpx.AsyncClient, token: str) -> int:
        data = await self._request_json(
            client,
            "GET",
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            params={"content": "false"},
        )
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs endpoint returned invalid JSON")
        return len(GreenhouseJobsResponse.model_validate(data).jobs)


class LeverSourceAdapter(_StaticJobBoardSourceAdapter):
    provider_id = "lever_source"
    provider_label = "Lever Source"
    provider_description = (
        "Direct Lever source adapter that exposes a public job board as one route."
    )
    route_provider_id = "lever"
    route_provider_label = "Lever"

    def _token_from_url(self, url: str) -> str:
        token = lever_token_from_url(url)
        if not token:
            raise ValueError("Lever source URL must include a board token")
        return token

    async def _job_count(self, client: httpx.AsyncClient, token: str) -> int:
        data = await self._request_json(
            client,
            "GET",
            f"https://api.lever.co/v0/postings/{token}",
            params={"mode": "json"},
        )
        if not isinstance(data, list):
            raise ValueError("Lever postings endpoint returned invalid JSON")
        return len(data)


class WorkableSourceAdapter:
    provider_id = "workable_source"
    provider_label = "Workable Source"
    provider_description = "Aggregate Workable source adapter that exposes a public Workable job board as one board route."

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)
        self._public_client = WorkablePublicClient(
            self._request_json,
            max_pages=workable_page_budget(settings.source_timeout_seconds),
            refresh=settings.cache_refresh,
        )

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
        snapshot = await self._public_client.fetch_listing_snapshot(client, token)
        total = snapshot.total
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
                raw_payload={
                    "sourceUrl": source.url,
                    "token": token,
                    "total": total,
                    "pageCount": snapshot.page_count,
                },
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
        yield boards, providers, {
            "token": token,
            "total": total,
            "pageCount": snapshot.page_count,
        }

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
        # Use public redirect validation (credential strip + URL allowlist) rather
        # than raw client.get(follow_redirects=True).
        response = await request_with_public_redirect_validation(
            client,
            "GET",
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
        response = await request_with_public_redirect_validation(
            client,
            "GET",
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
    SOUTHPARKCOMMONS_SOURCE,
    VENTURE_CAPITAL_CAREERS_SOURCE,
    VENTURE_LOOP_SOURCE,
    WORKABLE_1871_SOURCE,
    YCOMBINATOR_SOURCE,
    *load_packaged_portfolio_source_records(),
)
