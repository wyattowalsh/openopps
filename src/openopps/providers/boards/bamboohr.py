from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, cast
from urllib.parse import quote, unquote_to_bytes, urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JsonDict,
    JobRecord,
    normalize_remote_level,
    strip_html,
    validate_provider_host,
    validate_public_https_url,
)
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
from openopps.providers.boards.url_targets import synthetic_url_pull_board
from openopps.providers.normalize import (
    salary_components,
    salary_display,
    string as _string,
)
from openopps.settings import OpenOppsSettings
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


@dataclass(frozen=True)
class BambooHRRoute:
    host: str
    tenant: str


class BambooHRProvider:
    provider_id = "bamboohr"
    provider_label = "BambooHR"
    provider_description = "Public BambooHR careers board JSON endpoints."
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
            route = parse_bamboohr_board_url(url)
        except ValueError:
            return None
        return ProviderRouteMatch(
            token=route.tenant, host=route.host, tenant=route.tenant
        )

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        """Parse an exact BambooHR careers board or public posting URL."""

        if len(url.strip()) > 2_000:
            return None
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            if (
                parsed.query
                or parsed.fragment
                or parsed.params
                or parsed.port is not None
            ):
                return None
            host = validate_provider_host(parsed.hostname or "", "bamboohr.com")
            if not host.endswith(".bamboohr.com"):
                return None
            tenant = host.removesuffix(".bamboohr.com")
            if not _valid_identity(tenant):
                return None
            parts = _strict_bamboohr_parts(parsed.path)
        except ValueError:
            return None

        if parts in (["careers"], ["careers", "list"]):
            return ProviderUrlTarget(
                provider_id=BambooHRProvider.provider_id,
                target_kind=ProviderTargetKind.BOARD,
                url=url,
                board_identity=tenant,
                route=ProviderRouteIdentity(
                    token=tenant,
                    host=host,
                    tenant=tenant,
                ),
            )
        if len(parts) not in {2, 3} or parts[0] != "careers":
            return None
        if len(parts) == 3 and parts[2] != "detail":
            return None
        posting_identity = _decode_identity(parts[1])
        if posting_identity is None:
            return None
        return ProviderUrlTarget(
            provider_id=BambooHRProvider.provider_id,
            target_kind=ProviderTargetKind.POSTING,
            url=url,
            board_identity=tenant,
            posting_identity=posting_identity,
            route=ProviderRouteIdentity(
                token=tenant,
                host=host,
                tenant=tenant,
            ),
        )

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        tenant = quote(slug.strip().lower(), safe="-._~")
        return (f"https://{tenant}.bamboohr.com/careers",) if tenant else ()

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        if include_unlisted:
            raise ValueError("BambooHR does not support unlisted enumeration")
        bamboohr = _require_bamboohr_target(target, ProviderTargetKind.BOARD)
        kernel = await self._list_public_membership(
            client,
            bamboohr,
            identity_mode="pull",
            include_unlisted=False,
            detail_budget=int(self.settings.pull_provider_max_details),
        )
        return kernel.to_provider_list_result(target)

    async def pull_get(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult:
        bamboohr = _require_bamboohr_target(target, ProviderTargetKind.POSTING)
        posting_identity = target.posting_identity
        if posting_identity is None:
            raise ValueError("BambooHR posting target is missing an identity")
        detail = await self._fetch_detail(client, bamboohr, posting_identity)
        detail_id = detail.get("id")
        if detail_id is not None and str(detail_id).strip() != posting_identity:
            raise ValueError("BambooHR detail response did not match the requested job")
        job = self._normalize(
            _pull_board(bamboohr.tenant),
            bamboohr,
            {},
            detail,
            remote_id_override=posting_identity,
        )
        return ProviderGetResult(
            posting=ProviderPosting(
                job=job,
                listing=None,
                detail=job.raw_detail,
            ),
            method=ProviderGetMethod.NATIVE,
            matched_identity=posting_identity,
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        bamboohr = bamboohr_route(route)
        if not bamboohr:
            return JobFetchResult(jobs=[], authoritative=False)
        kernel = await self._list_public_membership(
            client,
            bamboohr,
            identity_mode="ingest",
            include_unlisted=False,
            detail_budget=None,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        bamboohr: BambooHRRoute,
        *,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
        detail_budget: int | None,
    ) -> BoardListingKernelResult:
        del identity_mode
        if include_unlisted:
            raise ValueError("BambooHR does not support unlisted enumeration")
        listings, advertised_count = await self._fetch_listings_with_total(
            client, bamboohr
        )
        if detail_budget is not None:
            ensure_detail_fanout_within_budget(
                len(listings),
                maximum_details=detail_budget,
            )
        details = await self._fetch_required_details(client, bamboohr, listings)
        native_board = _pull_board(bamboohr.tenant)
        postings = tuple(
            ListingPosting(
                job=(job := self._normalize(native_board, bamboohr, listing, detail)),
                listing=job.raw_listing,
                detail=job.raw_detail,
            )
            for listing, detail in zip(listings, details, strict=True)
        )
        return BoardListingKernelResult(
            native_board_identity=bamboohr.tenant,
            postings=postings,
            membership=MembershipEvidence(
                scope=MembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=1,
                observed_count=len(postings),
                advertised_count=advertised_count,
            ),
            detail_coverage=DetailCoverageEvidence(
                required=True,
                requested_count=len(postings),
                completed_count=len(postings),
                failed_count=0,
            ),
        )

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        bamboohr = bamboohr_route(route)
        if not bamboohr:
            return 0
        data = await self._request_json(
            client, "GET", f"https://{bamboohr.host}/careers/list"
        )
        if not isinstance(data, dict):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        meta = data.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("totalCount"), int):
            return int(meta["totalCount"])
        result = data.get("result")
        if not isinstance(result, list):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        return len(result)

    async def _fetch_listings(
        self, client: httpx.AsyncClient, route: BambooHRRoute
    ) -> list[dict[str, Any]]:
        listings, _advertised_count = await self._fetch_listings_with_total(
            client, route
        )
        return listings

    async def _fetch_listings_with_total(
        self, client: httpx.AsyncClient, route: BambooHRRoute
    ) -> tuple[list[dict[str, Any]], int | None]:
        data = await self._request_json(
            client,
            "GET",
            f"https://{route.host}/careers/list",
            cache_identity={"role": "membership"},
        )
        if not isinstance(data, dict):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        result = data.get("result")
        if not isinstance(result, list):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        if any(not isinstance(item, dict) for item in result):
            raise ValueError("BambooHR careers list endpoint returned invalid JSON")
        listings = cast(list[dict[str, Any]], result)
        meta = data.get("meta")
        total = meta.get("totalCount") if isinstance(meta, dict) else None
        if total is not None:
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise ValueError("BambooHR totalCount must be a non-negative integer")
            if len(listings) != total:
                raise ValueError("BambooHR advertised total does not match jobs")
        listing_ids = [_required_job_id(item) for item in listings]
        if len(listing_ids) != len(set(listing_ids)):
            raise ValueError("BambooHR careers list returned duplicate jobs")
        return listings, total

    async def _fetch_required_details(
        self,
        client: httpx.AsyncClient,
        route: BambooHRRoute,
        listings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        async def detail_for(listing: dict[str, Any]) -> dict[str, Any]:
            job_id = _required_job_id(listing)
            detail = await self._fetch_detail(client, route, job_id)
            detail_id = detail.get("id")
            if detail_id is not None and str(detail_id).strip() != job_id:
                raise ValueError("BambooHR detail response did not match its listing")
            return detail

        return await bounded_async_map(
            listings,
            detail_for,
            max_concurrency=int(self.settings.board_concurrency),
        )

    async def _fetch_detail(
        self, client: httpx.AsyncClient, route: BambooHRRoute, job_id: str
    ) -> dict[str, Any]:
        encoded_job_id = quote(job_id, safe="-._~")
        data = await self._request_json(
            client,
            "GET",
            f"https://{route.host}/careers/{encoded_job_id}/detail",
            cache_identity={"role": "detail"},
        )
        result = data.get("result") if isinstance(data, dict) else None
        job_opening = result.get("jobOpening") if isinstance(result, dict) else None
        if not isinstance(job_opening, dict):
            raise ValueError("BambooHR careers detail endpoint returned invalid JSON")
        return job_opening

    def _normalize(
        self,
        board: BoardRecord,
        route: BambooHRRoute,
        listing: dict[str, Any],
        detail: dict[str, Any],
        *,
        remote_id_override: str | None = None,
    ) -> JobRecord:
        remote_id = str(
            first_present(
                remote_id_override,
                listing.get("id"),
                detail.get("id"),
                listing.get("jobOpeningName"),
            )
        )
        merged = listing | detail
        description_html = _string(merged.get("description"))
        locations = _locations(merged)
        compensation = _json_dict(merged.get("compensation"))
        salary_min, salary_max, salary_currency = salary_components(
            compensation,
            min_keys=("minValue", "minimum"),
            max_keys=("maxValue", "maximum"),
        )
        posting_url = (
            _string(merged.get("jobOpeningShareUrl"))
            or f"https://{route.host}/careers/{remote_id}"
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(merged.get("jobOpeningName")) or remote_id,
            locations=locations,
            department=_string(merged.get("departmentLabel")),
            workplace_type=_string(merged.get("locationType")),
            company=board.name,
            employment_type=_string(merged.get("employmentStatusLabel")),
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(
                locations, is_remote=_bool(merged.get("isRemote"))
            ),
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            experience=_string(merged.get("minimumExperience")),
            posting_url=posting_url,
            apply_url=posting_url,
            posted_at=_string(merged.get("datePosted")),
            raw_listing=_raw(listing),
            raw_detail=_raw(detail),
        )


def parse_bamboohr_board_url(url: str) -> BambooHRRoute:
    validate_public_https_url(url)
    parsed = urlparse(url)
    host = validate_provider_host(parsed.hostname or "", "bamboohr.com")
    if not host.endswith(".bamboohr.com"):
        raise ValueError(f"BambooHR URL is missing tenant subdomain: {url}")
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] != "careers":
        raise ValueError(f"BambooHR URL is not a careers board URL: {url}")
    tenant = host.removesuffix(".bamboohr.com")
    return BambooHRRoute(host=host, tenant=tenant)


def bamboohr_route(route: BoardProviderRecord) -> BambooHRRoute | None:
    if route.host:
        host = validate_provider_host(route.host, "bamboohr.com")
        return BambooHRRoute(host=host, tenant=route.tenant or host.split(".", 1)[0])
    if route.board_url:
        return parse_bamboohr_board_url(route.board_url)
    if route.tenant:
        tenant = route.tenant.strip().lower()
        return BambooHRRoute(host=f"{tenant}.bamboohr.com", tenant=tenant)
    if route.token:
        token = route.token.strip().lower()
        return BambooHRRoute(host=f"{token}.bamboohr.com", tenant=token)
    return None


def _locations(value: dict[str, Any]) -> list[str]:
    location = (
        value.get("atsLocation")
        if isinstance(value.get("atsLocation"), dict)
        else value.get("location")
    )
    if not isinstance(location, dict):
        return []
    label = ", ".join(
        part
        for part in (
            _string(location.get("city")),
            _string(location.get("state") or location.get("province")),
            _string(location.get("country") or location.get("addressCountry")),
        )
        if part
    )
    return [label] if label else []


def _json_dict(value: object) -> JsonDict | None:
    return cast(JsonDict, value) if isinstance(value, dict) else None


def _raw(value: dict[str, Any]) -> JsonDict:
    return cast(JsonDict, dict(value))


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _require_bamboohr_target(
    target: ProviderUrlTarget,
    kind: ProviderTargetKind,
) -> BambooHRRoute:
    if target.provider_id != BambooHRProvider.provider_id:
        raise ValueError("BambooHR pull target has the wrong provider")
    if target.target_kind != kind:
        label = "board" if kind == ProviderTargetKind.BOARD else "posting"
        raise ValueError(f"BambooHR pull requires a {label} target")
    host = target.route.host
    tenant = target.route.tenant
    if (
        not host
        or not tenant
        or tenant != target.board_identity
        or host != f"{tenant}.bamboohr.com"
    ):
        raise ValueError("BambooHR pull target has inconsistent route identity")
    return BambooHRRoute(host=host, tenant=tenant)


def _pull_board(tenant: str) -> BoardRecord:
    return synthetic_url_pull_board(tenant, remote_slug=tenant)


def _required_job_id(listing: dict[str, Any]) -> str:
    raw_job_id = listing.get("id")
    if raw_job_id is None or isinstance(raw_job_id, bool):
        raise ValueError("BambooHR careers list job is missing an id")
    job_id = str(raw_job_id).strip()
    if not job_id:
        raise ValueError("BambooHR careers list job is missing an id")
    return job_id


def _strict_bamboohr_parts(path: str) -> list[str]:
    normalized = path[:-1] if path.endswith("/") and path != "/" else path
    if not normalized.startswith("/"):
        raise ValueError("BambooHR URL path must be absolute")
    raw = normalized[1:]
    if not raw or any(not part for part in raw.split("/")):
        raise ValueError("BambooHR URL path contains an empty segment")
    return raw.split("/")


def _decode_identity(value: str) -> str | None:
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return None
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    return decoded if _valid_identity(decoded) else None


def _valid_identity(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 500
        and value not in {".", ".."}
        and not any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            or character in "/\\"
            for character in value
        )
    )
