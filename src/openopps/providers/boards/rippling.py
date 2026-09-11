from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, cast
from urllib.parse import urlparse

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
from openopps.providers.boards.url_targets import (
    strict_decoded_path_parts as _strict_path_parts,
    synthetic_url_pull_board,
)
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

_RIPPLING_MAX_PAGES = 500


@dataclass(frozen=True, slots=True)
class RipplingListingSnapshot:
    listings: tuple[dict[str, Any], ...]
    pages_fetched: int
    advertised_count: int | None


class RipplingProvider:
    provider_id = "rippling"
    provider_label = "Rippling"
    provider_description = "Public Rippling ATS board JSON endpoints."
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
        validate_public_https_url(url)
        parsed = urlparse(url)
        try:
            host = validate_provider_host(parsed.hostname or "", "rippling.com")
        except ValueError:
            return None
        if host != "ats.rippling.com":
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if parts[:3] == ["api", "v2", "board"] and len(parts) > 3:
            return ProviderRouteMatch(token=parts[3], host=host, tenant=parts[3])
        if len(parts) >= 2 and parts[1] == "jobs":
            return ProviderRouteMatch(token=parts[0], host=host, tenant=parts[0])
        return None

    @staticmethod
    def parse_url_target(url: str) -> ProviderUrlTarget | None:
        try:
            validate_public_https_url(url)
            parsed = urlparse(url)
            if (
                parsed.netloc.casefold() != "ats.rippling.com"
                or parsed.query
                or parsed.fragment
                or parsed.params
            ):
                return None
            parts = _strict_path_parts(parsed.path)
            if parts is None:
                return None
            if parts[:3] == ("api", "v2", "board"):
                tail = parts[3:]
                if len(tail) not in {2, 3} or tail[1] != "jobs":
                    return None
                slug = tail[0]
                posting_id = tail[2] if len(tail) == 3 else None
            elif len(parts) in {2, 3} and parts[1] == "jobs":
                slug = parts[0]
                posting_id = parts[2] if len(parts) == 3 else None
            else:
                return None
            return ProviderUrlTarget(
                provider_id=RipplingProvider.provider_id,
                target_kind=(
                    ProviderTargetKind.POSTING
                    if posting_id is not None
                    else ProviderTargetKind.BOARD
                ),
                url=url,
                board_identity=slug,
                posting_identity=posting_id,
                route=ProviderRouteIdentity(token=slug, tenant=slug),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def build_probe_urls(slug: str) -> tuple[str, ...]:
        return (f"https://ats.rippling.com/{slug}/jobs",)

    async def pull_list(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult:
        slug = _require_rippling_target(target, ProviderTargetKind.BOARD)
        kernel = await self._list_public_membership(
            client,
            slug,
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
        slug = _require_rippling_target(target, ProviderTargetKind.POSTING)
        posting_id = target.posting_identity
        assert posting_id is not None
        detail = await self._fetch_detail(client, slug, posting_id)
        detail_id = _listing_id(detail)
        if detail_id is not None and detail_id != posting_id:
            raise ValueError("Rippling detail identity did not match the requested job")
        board = _pull_board(target)
        job = self._normalize(
            board,
            slug,
            {},
            detail,
            remote_id_override=posting_id,
        )
        return ProviderGetResult(
            posting=ProviderPosting(job=job, listing=None, detail=job.raw_detail),
            method=ProviderGetMethod.NATIVE,
            matched_identity=posting_id,
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult:
        slug = rippling_slug(route)
        if not slug:
            return JobFetchResult(jobs=[], authoritative=False)
        kernel = await self._list_public_membership(
            client,
            slug,
            identity_mode="ingest",
            include_unlisted=False,
            detail_budget=None,
        )
        return kernel.to_job_fetch_result(board, provider_id=self.provider_id)

    async def _list_public_membership(
        self,
        client: httpx.AsyncClient,
        slug: str,
        *,
        identity_mode: ListingIdentityMode,
        include_unlisted: bool,
        detail_budget: int | None,
    ) -> BoardListingKernelResult:
        if include_unlisted:
            raise ValueError("Rippling cannot enumerate unlisted postings")
        snapshot = await self._fetch_listing_snapshot(client, slug)
        if detail_budget is not None:
            ensure_detail_fanout_within_budget(
                len(snapshot.listings),
                maximum_details=detail_budget,
            )
        native_board = synthetic_url_pull_board(slug)

        async def posting_for(listing: dict[str, Any]) -> ListingPosting:
            if identity_mode == "pull":
                job_id = _listing_id(listing)
                if not job_id:
                    raise ValueError("Rippling listing omitted an exact job identity")
                detail = await self._fetch_detail(client, slug, job_id)
                detail_id = _listing_id(detail)
                if detail_id is not None and detail_id != job_id:
                    raise ValueError(
                        "Rippling detail identity did not match its listing"
                    )
                job = self._normalize(
                    native_board,
                    slug,
                    listing,
                    detail,
                    remote_id_override=job_id,
                )
                return ListingPosting(
                    job=job,
                    listing=job.raw_listing,
                    detail=job.raw_detail,
                )
            job_id = _string(first_present(listing.get("id"), listing.get("uuid")))
            detail = (
                {} if not job_id else await self._fetch_detail(client, slug, job_id)
            )
            job = self._normalize(native_board, slug, listing, detail)
            return ListingPosting(
                job=job,
                listing=job.raw_listing,
                detail=job.raw_detail or None,
            )

        postings = tuple(
            await bounded_async_map(
                snapshot.listings,
                posting_for,
                max_concurrency=int(self.settings.board_concurrency),
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
            native_board_identity=slug,
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

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int:
        slug = rippling_slug(route)
        if not slug:
            return 0
        data = await self._request_json(
            client,
            "GET",
            f"https://ats.rippling.com/api/v2/board/{slug}/jobs",
            params={"page": 0, "pageSize": 1},
        )
        if not isinstance(data, dict):
            raise ValueError("Rippling board jobs endpoint returned invalid JSON")
        total = data.get("totalItems")
        if isinstance(total, int):
            return total
        items = data.get("items")
        if isinstance(items, list):
            return len(items)
        raise ValueError("Rippling board jobs endpoint returned invalid JSON")

    async def _fetch_listings(
        self, client: httpx.AsyncClient, slug: str
    ) -> list[dict[str, Any]]:
        return list((await self._fetch_listing_snapshot(client, slug)).listings)

    async def _fetch_listing_snapshot(
        self, client: httpx.AsyncClient, slug: str
    ) -> RipplingListingSnapshot:
        listings: list[dict[str, Any]] = []
        page = 0
        page_size = 100
        total_pages: int | None = None
        total_items: int | None = None
        seen_pages: set[str] = set()
        seen_listing_ids: set[str] = set()
        while True:
            if page >= _RIPPLING_MAX_PAGES:
                raise ValueError("Rippling pagination exceeded its page budget")
            data = await self._request_json(
                client,
                "GET",
                f"https://ats.rippling.com/api/v2/board/{slug}/jobs",
                params={"page": page, "pageSize": page_size},
                cache_identity={"role": "membership_page"},
            )
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("Rippling board jobs endpoint returned invalid JSON")
            if any(not isinstance(item, dict) for item in data["items"]):
                raise ValueError("Rippling board jobs endpoint returned invalid JSON")
            page_listings = cast(list[dict[str, Any]], data["items"])
            reported_pages = _optional_non_negative_int(
                data, "totalPages", provider="Rippling"
            )
            reported_items = _optional_non_negative_int(
                data, "totalItems", provider="Rippling"
            )
            total_pages = _consistent_total(
                total_pages, reported_pages, label="Rippling totalPages"
            )
            total_items = _consistent_total(
                total_items, reported_items, label="Rippling totalItems"
            )
            if total_pages == 0 and page_listings:
                raise ValueError("Rippling advertised totalPages does not match jobs")
            if total_pages is not None and total_pages > 0 and page >= total_pages:
                raise ValueError("Rippling pagination exceeded advertised totalPages")
            page_signature = json.dumps(
                page_listings, sort_keys=True, separators=(",", ":"), default=str
            )
            if page_listings and page_signature in seen_pages:
                raise ValueError("Rippling repeated pagination page")
            seen_pages.add(page_signature)
            for listing in page_listings:
                listing_id = _listing_id(listing)
                if listing_id and listing_id in seen_listing_ids:
                    raise ValueError("Rippling repeated pagination listing")
                if listing_id:
                    seen_listing_ids.add(listing_id)
            if not page_listings and (
                page > 0
                or (total_pages is not None and page + 1 < total_pages)
                or (total_items is not None and len(listings) < total_items)
            ):
                raise ValueError(
                    "Rippling incomplete pagination returned an empty page"
                )
            listings.extend(page_listings)
            if total_items is not None and len(listings) > total_items:
                raise ValueError("Rippling advertised total does not match jobs")
            if total_pages is not None:
                if page + 1 >= total_pages:
                    break
            elif total_items is not None:
                if len(listings) == total_items:
                    break
                if not page_listings:
                    raise ValueError("Rippling incomplete pagination before totalItems")
            elif len(page_listings) < page_size:
                break
            page += 1
        if total_items is not None and len(listings) != total_items:
            raise ValueError("Rippling advertised total does not match jobs")
        return RipplingListingSnapshot(
            listings=tuple(listings),
            pages_fetched=page + 1,
            advertised_count=total_items,
        )

    async def _fetch_detail(
        self, client: httpx.AsyncClient, slug: str, job_id: str
    ) -> dict[str, Any]:
        data = await self._request_json(
            client,
            "GET",
            f"https://ats.rippling.com/api/v2/board/{slug}/jobs/{job_id}",
            cache_identity={"role": "detail"},
        )
        if not isinstance(data, dict):
            raise ValueError("Rippling board detail endpoint returned invalid JSON")
        return data

    def _normalize(
        self,
        board: BoardRecord,
        slug: str,
        listing: dict[str, Any],
        detail: dict[str, Any],
        *,
        remote_id_override: str | None = None,
    ) -> JobRecord:
        merged = listing | detail
        remote_id = remote_id_override or str(
            first_present(
                merged.get("uuid"),
                merged.get("id"),
                merged.get("url"),
                merged.get("name"),
            )
        )
        locations = _locations(merged)
        description_html = _description_html(merged.get("description"))
        employment_type = _employment_type(merged.get("employmentType"))
        department = _name(merged.get("department"))
        compensation = _pay_range(merged.get("payRangeDetails"))
        salary_min, salary_max, salary_currency = salary_components(
            compensation,
            min_keys=("min", "minValue"),
            max_keys=("max", "maxValue"),
        )
        posting_url = (
            _string(merged.get("url"))
            or f"https://ats.rippling.com/{slug}/jobs/{remote_id}"
        )
        return JobRecord(
            id=stable_id(board.key, self.provider_id, remote_id),
            board_key=board.key,
            provider_id=self.provider_id,
            remote_id=remote_id,
            title=_string(merged.get("name")) or remote_id,
            locations=locations,
            department=department,
            workplace_type=_workplace_type(merged),
            company=_string(merged.get("companyName")) or board.name,
            employment_type=employment_type,
            description=strip_html(description_html),
            description_html=description_html,
            remote=normalize_remote_level(_workplace_type(merged), locations),
            compensation=compensation,
            salary=salary_display(salary_min, salary_max, salary_currency),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            posting_url=posting_url,
            apply_url=posting_url,
            posted_at=_string(merged.get("createdOn")),
            raw_listing=_raw(listing),
            raw_detail=_raw(detail),
        )


def rippling_slug(route: BoardProviderRecord) -> str | None:
    if route.tenant:
        return route.tenant.strip()
    if route.token:
        return route.token.strip()
    if not route.board_url:
        return None
    parsed = urlparse(route.board_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts[:3] == ["api", "v2", "board"] and len(parts) > 3:
        return parts[3]
    if len(parts) >= 2 and parts[1] == "jobs":
        return parts[0]
    return None


def _locations(value: dict[str, Any]) -> list[str]:
    raw_locations = value.get("locations") or value.get("workLocations")
    locations: list[str] = []
    if isinstance(raw_locations, list):
        for location in raw_locations:
            if isinstance(location, dict):
                locations.append(_location_label(location))
            elif isinstance(location, str):
                locations.append(location)
    return [location for location in dict.fromkeys(locations) if location]


def _location_label(location: dict[str, Any]) -> str:
    return (
        ", ".join(
            part
            for part in (
                _string(location.get("city")),
                _string(location.get("state") or location.get("stateCode")),
                _string(location.get("country") or location.get("countryCode")),
            )
            if part
        )
        or _string(location.get("name"))
        or ""
    )


def _description_html(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [
            part for part in value.values() if isinstance(part, str) and part.strip()
        ]
        return "\n".join(parts) or None
    return None


def _employment_type(value: object) -> str | None:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        return _string(data.get("label") or data.get("id"))
    return _string(value)


def _workplace_type(value: dict[str, Any]) -> str | None:
    for location in value.get("locations") or []:
        if isinstance(location, dict) and _string(location.get("workplaceType")):
            return _string(location.get("workplaceType"))
    return None


def _name(value: object) -> str | None:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        return _string(data.get("name"))
    return _string(value)


def _pay_range(value: object) -> JsonDict | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return cast(JsonDict, dict(value[0]))
    if isinstance(value, dict):
        return cast(JsonDict, value)
    return None


def _raw(value: dict[str, Any]) -> JsonDict:
    return cast(JsonDict, dict(value))


def _optional_non_negative_int(
    data: dict[str, Any], key: str, *, provider: str
) -> int | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{provider} {key} must be a non-negative integer")
    return value


def _consistent_total(
    expected: int | None, reported: int | None, *, label: str
) -> int | None:
    if reported is None:
        return expected
    if expected is not None and reported != expected:
        raise ValueError(f"{label} changed during pagination")
    return reported


def _listing_id(listing: dict[str, Any]) -> str | None:
    value = first_present(listing.get("id"), listing.get("uuid"), listing.get("url"))
    return str(value) if value is not None else None


def _require_rippling_target(
    target: ProviderUrlTarget,
    kind: ProviderTargetKind,
) -> str:
    if target.provider_id != RipplingProvider.provider_id or target.target_kind != kind:
        raise ValueError("Rippling pull received an incompatible target")
    slug = target.route.tenant or target.route.token or target.board_identity
    if slug != target.board_identity:
        raise ValueError("Rippling target route does not match its board identity")
    return slug


def _pull_board(target: ProviderUrlTarget) -> BoardRecord:
    return synthetic_url_pull_board(target.board_identity)
