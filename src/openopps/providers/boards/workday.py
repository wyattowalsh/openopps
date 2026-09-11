from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderNamedValue,
    WorkdayJobDetail,
    WorkdayJobPosting,
    WorkdayJobsResponse,
    normalize_remote_level,
    strip_html,
)
from openopps.settings import OpenOppsSettings
from openopps.models import validate_provider_host, validate_public_https_url
from openopps.providers.base import JobFetchResult, ProviderRouteMatch
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    DetailCoverageEvidence,
    ListingIdentityMode,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    bounded_async_map,
    optional_pull_attr,
    optional_pull_capabilities,
)
from openopps.providers.boards.url_targets import (
    strict_decoded_path_parts as _strict_path_parts,
    synthetic_url_pull_board,
)
from openopps.utils import first_present, stable_id


ProviderGetMethod = optional_pull_attr("ProviderGetMethod")
ProviderGetResult = optional_pull_attr("ProviderGetResult")
ensure_detail_fanout_within_budget = optional_pull_attr(
    "ensure_detail_fanout_within_budget"
)
ProviderListResult = optional_pull_attr("ProviderListResult")
ProviderPosting = optional_pull_attr("ProviderPosting", ListingPosting)
ProviderRouteIdentity = optional_pull_attr("ProviderRouteIdentity")
ProviderTargetKind = optional_pull_attr("ProviderTargetKind")
ProviderUrlTarget = optional_pull_attr("ProviderUrlTarget")

_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_WORKDAY_MAX_PAGES = 500


@dataclass(frozen=True)
class WorkdayRoute:
    host: str
    tenant: str
    site: str


@dataclass(frozen=True, slots=True)
class WorkdayListingSnapshot:
    listings: tuple[WorkdayJobPosting, ...]
    pages_fetched: int
    advertised_count: int | None


def parse_workday_board_url(url: str) -> WorkdayRoute:
    validate_public_https_url(url)
    parsed = urlparse(url)
    host = validate_provider_host(parsed.hostname or "", "myworkdayjobs.com")
    if not host:
        raise ValueError(f"Workday URL is missing host: {url}")
    tenant = host.split(".", 1)[0]
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        raise ValueError(f"Workday URL is missing site path: {url}")
    site_index = 1 if _LOCALE_RE.match(path_parts[0]) and len(path_parts) > 1 else 0
    site = path_parts[site_index]
    return WorkdayRoute(host=host, tenant=tenant, site=site)


class WorkdayProvider:
    provider_id = "workday"
    provider_label = "Workday"
    provider_description = "Public Workday CXS careers-site endpoints."
    pull_capabilities = optional_pull_capabilities(
        list_supported=True,
        native_get_supported=True,
        interface_stability="best_effort",
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    @staticmethod
    def detect_route(url: str) -> ProviderRouteMatch | None:
        try:
            parsed = parse_workday_board_url(url)
        except ValueError:
            return None
        return ProviderRouteMatch(
            token=parsed.site,
            host=parsed.host,
            tenant=parsed.tenant,
            site=parsed.site,
        )

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            host = validate_provider_host(parsed.hostname or "", "myworkdayjobs.com")
            if (
                parsed.netloc.casefold() != host.casefold()
                or parsed.query
                or parsed.fragment
                or parsed.params
            ):
                return None
            parts = _strict_path_parts(parsed.path)
            if parts is None:
                return None
            host_tenant = host.split(".", 1)[0]
            posting_identity: str | None = None
            if parts[:2] == ("wday", "cxs"):
                if len(parts) < 5:
                    return None
                tenant, site = parts[2], parts[3]
                if tenant.casefold() != host_tenant.casefold():
                    return None
                if len(parts) == 5 and parts[4] == "jobs":
                    pass
                elif len(parts) >= 6 and parts[4] == "job":
                    posting_identity = "/".join(parts[5:])
                else:
                    return None
            else:
                if not parts:
                    return None
                site_index = (
                    1 if _LOCALE_RE.fullmatch(parts[0]) and len(parts) > 1 else 0
                )
                site = parts[site_index]
                tenant = host_tenant
                tail = parts[site_index + 1 :]
                if not tail:
                    pass
                elif len(tail) >= 2 and tail[0] == "job":
                    posting_identity = "/".join(tail[1:])
                else:
                    return None
            board_identity = _workday_board_identity(host, tenant, site)
            return ProviderUrlTarget(
                provider_id=WorkdayProvider.provider_id,
                target_kind=(
                    ProviderTargetKind.POSTING
                    if posting_identity is not None
                    else ProviderTargetKind.BOARD
                ),
                url=url,
                board_identity=board_identity,
                posting_identity=posting_identity,
                route=ProviderRouteIdentity(
                    token=site,
                    host=host,
                    tenant=tenant,
                    site=site,
                ),
            )
        except (TypeError, ValueError):
            return None

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        route = _require_workday_target(target, ProviderTargetKind.BOARD)
        kernel = await self._list_public_membership(
            client,
            route,
            native_identity=target.board_identity,
            identity_mode="pull",
            include_unlisted=include_unlisted,
            detail_budget=int(self.settings.pull_provider_max_details),
        )
        return kernel.to_provider_list_result(target)

    async def pull_get(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        route = _require_workday_target(target, ProviderTargetKind.POSTING)
        posting_identity = target.posting_identity
        assert posting_identity is not None
        detail = await self._fetch_detail(client, route, posting_identity)
        detail_path = _workday_detail_external_path(detail)
        if detail_path is not None and detail_path != posting_identity:
            raise ValueError("Workday detail identity did not match the requested job")
        listing = WorkdayJobPosting(
            id=posting_identity,
            externalPath=posting_identity,
            title=detail.title or posting_identity,
        )
        job = self._normalize(
            _pull_board(target),
            route,
            listing,
            detail,
            remote_id_override=posting_identity,
            include_listing_evidence=False,
        )
        return ProviderGetResult(
            posting=ProviderPosting(job=job, listing=None, detail=job.raw_detail),
            method=ProviderGetMethod.NATIVE,
            matched_identity=posting_identity,
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        workday = self._route(route)
        if not workday:
            return JobFetchResult(jobs=[], authoritative=False)
        kernel = await self._list_public_membership(
            client,
            workday,
            native_identity=_workday_board_identity(
                workday.host, workday.tenant, workday.site
            ),
            identity_mode="ingest",
            include_unlisted=False,
            detail_budget=None,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        workday: WorkdayRoute,
        *,
        native_identity: str,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
        detail_budget: int | None,
    ) -> BoardListingKernelResult:
        if include_unlisted:
            raise ValueError("Workday cannot enumerate unlisted postings")
        snapshot = await self._fetch_listing_snapshot(client, workday)
        if detail_budget is not None:
            ensure_detail_fanout_within_budget(
                len(snapshot.listings),
                maximum_details=detail_budget,
            )
        native_board = synthetic_url_pull_board(native_identity)

        async def posting_for(listing: WorkdayJobPosting) -> ListingPosting:
            if identity_mode == "pull":
                external_path = listing.external_path
                if not external_path:
                    raise ValueError("Workday listing omitted its external path")
                detail = await self._fetch_detail(client, workday, external_path)
                detail_path = _workday_detail_external_path(detail)
                if detail_path is not None and detail_path != external_path:
                    raise ValueError(
                        "Workday detail identity did not match its listing"
                    )
                job = self._normalize(
                    native_board,
                    workday,
                    listing,
                    detail,
                    remote_id_override=external_path,
                )
                return ListingPosting(
                    job=job,
                    listing=job.raw_listing,
                    detail=job.raw_detail,
                )
            external_path = listing.external_path
            detail = (
                WorkdayJobDetail()
                if not external_path
                else await self._fetch_detail(client, workday, external_path)
            )
            job = self._normalize(native_board, workday, listing, detail)
            return ListingPosting(
                job=job,
                listing=job.raw_listing,
                detail=job.raw_detail or None,
            )

        postings = tuple(
            await bounded_async_map(
                snapshot.listings,
                posting_for,
                max_concurrency=int(self.settings.workday_concurrency),
            )
        )
        detail_coverage = DetailCoverageEvidence()
        if identity_mode == "pull":
            detail_coverage = DetailCoverageEvidence(
                required=True,
                requested_count=len(postings),
                completed_count=len(postings),
            )
        return BoardListingKernelResult(
            native_board_identity=native_identity,
            postings=postings,
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=snapshot.pages_fetched,
                observed_count=len(postings),
                advertised_count=snapshot.advertised_count,
            ),
            detail_coverage=detail_coverage,
        )

    def _route(self, route: BoardProviderRecord) -> WorkdayRoute | None:
        if route.host and route.tenant and route.site:
            return WorkdayRoute(
                host=validate_provider_host(route.host, "myworkdayjobs.com"),
                tenant=route.tenant,
                site=route.site,
            )
        if route.board_url:
            return parse_workday_board_url(route.board_url)
        return None

    async def _fetch_listings(
        self, client: httpx.AsyncClient, route: WorkdayRoute
    ) -> list[WorkdayJobPosting]:
        return list((await self._fetch_listing_snapshot(client, route)).listings)

    async def _fetch_listing_snapshot(
        self, client: httpx.AsyncClient, route: WorkdayRoute
    ) -> WorkdayListingSnapshot:
        url = f"https://{route.host}/wday/cxs/{route.tenant}/{route.site}/jobs"
        listings: list[WorkdayJobPosting] = []
        offset = 0
        limit = 20
        total: int | None = None
        seen_pages: set[tuple[str, ...]] = set()
        seen_listing_ids: set[str] = set()
        page_count = 0
        while True:
            page_count += 1
            if page_count > _WORKDAY_MAX_PAGES:
                raise ValueError("Workday pagination exceeded its page budget")
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }
            data = await self._request_json(
                client,
                "POST",
                url,
                json=payload,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "referer": f"https://{route.host}/{route.site}",
                },
                cache_identity={"role": "membership_page"},
            )
            if not isinstance(data, dict):
                raise ValueError("Workday listings endpoint returned invalid JSON")
            if isinstance(data.get("total"), bool):
                raise ValueError("Workday advertised total is malformed")
            raw_postings = data.get("jobPostings")
            if isinstance(raw_postings, list):
                for raw_posting in raw_postings:
                    if isinstance(raw_posting, dict) and isinstance(
                        raw_posting.get("id"), bool
                    ):
                        raise ValueError("Workday listing has a malformed id")
            response = WorkdayJobsResponse.model_validate(data)
            reported_total = int(response.total) if response.total is not None else None
            if (
                total is not None
                and reported_total is not None
                and reported_total != total
            ):
                raise ValueError("Workday advertised total changed during pagination")
            if reported_total is not None:
                total = reported_total
            page_postings = response.job_postings
            page_signature = tuple(
                posting.model_dump_json(by_alias=True) for posting in page_postings
            )
            if page_postings and page_signature in seen_pages:
                raise ValueError("Workday repeated pagination page")
            seen_pages.add(page_signature)
            for posting in page_postings:
                for listing_id in _workday_listing_identity_keys(posting):
                    if listing_id in seen_listing_ids:
                        raise ValueError("Workday repeated pagination listing")
                    seen_listing_ids.add(listing_id)
            listings.extend(page_postings)
            if total is not None and len(listings) > total:
                raise ValueError("Workday advertised total does not match jobs")
            if total is not None and len(listings) == total:
                break
            if not page_postings:
                if total is not None:
                    raise ValueError("Workday advertised total does not match jobs")
                break
            if len(page_postings) < limit:
                if total is not None:
                    raise ValueError("Workday advertised total does not match jobs")
                break
            offset += len(page_postings)
        if total is not None and len(listings) != total:
            raise ValueError("Workday advertised total does not match jobs")
        return WorkdayListingSnapshot(
            listings=tuple(listings),
            pages_fetched=page_count,
            advertised_count=total,
        )

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        workday = self._route(route)
        if not workday:
            return 0
        url = f"https://{workday.host}/wday/cxs/{workday.tenant}/{workday.site}/jobs"
        data = await self._request_json(
            client,
            "POST",
            url,
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "referer": f"https://{workday.host}/{workday.site}",
            },
        )
        if not isinstance(data, dict):
            raise ValueError("Workday listings endpoint returned invalid JSON")
        response = WorkdayJobsResponse.model_validate(data)
        return int(response.total or len(response.job_postings))

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        route: WorkdayRoute,
        external_path: str,
    ) -> WorkdayJobDetail:
        url = f"https://{route.host}/wday/cxs/{route.tenant}/{route.site}/job/{external_path}"
        data = await self._request_json(
            client,
            "GET",
            url,
            headers={
                "accept": "application/json",
                "referer": f"https://{route.host}/{route.site}/job/{external_path}",
            },
            cache_identity={"role": "detail"},
        )
        if not isinstance(data, dict):
            raise ValueError("Workday detail endpoint returned invalid JSON")
        return WorkdayJobDetail.model_validate(_cxs_job_detail_payload(data))

    def _normalize(
        self,
        board: BoardRecord,
        route: WorkdayRoute,
        listing: WorkdayJobPosting,
        detail: WorkdayJobDetail,
        *,
        remote_id_override: str | None = None,
        include_listing_evidence: bool = True,
    ) -> JobRecord:
        remote_id = remote_id_override or str(
            first_present(
                listing.id,
                listing.external_path,
                listing.title,
            )
        )
        title = first_present(listing.title, detail.title, remote_id)
        locations = _workday_location_labels(listing, detail)
        posting_url = None
        external_path = listing.external_path
        if external_path:
            posting_url = f"https://{route.host}/{route.site}/job/{external_path}"
        description_html = detail.job_description
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=str(title),
            locations=locations,
            department=first_present(listing.job_family, detail.job_family),
            workplace_type=first_present(
                detail.time_type,
                detail.worker_sub_type,
            ),
            company=board.name,
            employment_type=detail.time_type,
            description=detail.description or strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(locations),
            posting_url=posting_url,
            posted_at=first_present(listing.posted_on, detail.posted_on),
            raw_listing=(listing.as_raw_payload() if include_listing_evidence else {}),
            raw_detail=detail.as_raw_payload(),
        )


def _location_label(value: ProviderNamedValue | str | None) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, ProviderNamedValue):
        return value.display_name or value.name
    return None


def _workday_location_labels(
    listing: WorkdayJobPosting,
    detail: WorkdayJobDetail,
) -> list[str]:
    values: list[object] = [
        listing.locations_text,
        listing.location,
        detail.location,
    ]
    extra_locations = detail.as_raw_payload().get("additionalLocations")
    if isinstance(extra_locations, list):
        values.extend(extra_locations)
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, (str, ProviderNamedValue)):
            continue
        label = _location_label(value)
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _cxs_job_detail_payload(data: dict[str, object]) -> dict[str, object]:
    if "jobPostingInfo" not in data:
        return data
    info = data["jobPostingInfo"]
    if not isinstance(info, dict):
        raise ValueError("Workday detail endpoint returned invalid JSON")
    payload = dict(info)
    organization = data.get("hiringOrganization")
    if organization is not None and "hiringOrganization" not in payload:
        payload["hiringOrganization"] = organization
    return payload


def _workday_external_path_identity(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    path = str(value).strip().strip("/")
    if not path:
        return None
    if path[:4].casefold() == "job/":
        path = path[4:]
    return path or None


def _workday_listing_identity_keys(posting: WorkdayJobPosting) -> tuple[str, ...]:
    if isinstance(posting.id, bool):
        raise ValueError("Workday listing has a malformed id")
    keys: list[str] = []
    if posting.id not in (None, ""):
        keys.append(f"id:{posting.id}")
    path = _workday_external_path_identity(posting.external_path)
    if path is not None:
        keys.append(f"path:{path}")
    if keys:
        return tuple(keys)
    title = posting.title
    if title:
        return (f"title:{title}",)
    raise ValueError("Workday listing omitted a stable identity")


def _workday_board_identity(host: str, tenant: str, site: str) -> str:
    return f"{host.casefold()}:{tenant}:{site}"


def _require_workday_target(
    target: ProviderUrlTarget,
    kind: ProviderTargetKind,
) -> WorkdayRoute:
    if target.provider_id != WorkdayProvider.provider_id or target.target_kind != kind:
        raise ValueError("Workday pull received an incompatible target")
    host = target.route.host
    tenant = target.route.tenant
    site = target.route.site
    if not host or not tenant or not site:
        raise ValueError("Workday target omitted route identity")
    route = WorkdayRoute(
        host=validate_provider_host(host, "myworkdayjobs.com"),
        tenant=tenant,
        site=site,
    )
    if target.board_identity != _workday_board_identity(
        route.host, route.tenant, route.site
    ):
        raise ValueError("Workday target route does not match its board identity")
    return route


def _workday_detail_external_path(detail: WorkdayJobDetail) -> str | None:
    raw = detail.as_raw_payload()
    candidates: list[object] = [raw.get("externalPath")]
    info = raw.get("jobPostingInfo")
    if isinstance(info, dict):
        candidates.append(info.get("externalPath"))
    for value in candidates:
        path = _workday_external_path_identity(value)
        if path is not None:
            return path
    return None


def _pull_board(target: ProviderUrlTarget) -> BoardRecord:
    return synthetic_url_pull_board(
        target.board_identity,
        name=target.route.tenant or target.board_identity,
    )
