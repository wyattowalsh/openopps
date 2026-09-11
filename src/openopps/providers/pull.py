from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import StrEnum
import re
from typing import TYPE_CHECKING, Annotated, Protocol, TypeVar, cast
from urllib.parse import unquote_to_bytes

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from openopps.http import (
    JsonResponseData,
    _bind_http_cache_identity_scope,
    _bind_http_operation_budget,
    _bind_http_operation_counters,
    _capture_http_cache_identity_scope,
    _capture_http_operation_budget,
    _capture_http_operation_counters,
    retrying_json_request,
    retrying_text_request,
)
from openopps.models import JobRecord, JsonDict
from openopps.pull_models import SanitizedPublicHttpsUrlStr
from openopps.settings import OpenOppsSettings

if TYPE_CHECKING:
    from openopps.providers.base import JobFetchResult


BoundedIdentity = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]

_ItemT = TypeVar("_ItemT")
_ResultT = TypeVar("_ResultT")
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_MAX_PLUGIN_REDIRECTS = 5


def _bounded_pull_http_identity(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError(f"{label} must contain between 1 and 500 characters")
    return normalized


def _bounded_pull_redirects(max_redirects: int) -> int:
    if isinstance(max_redirects, bool) or not isinstance(max_redirects, int):
        raise TypeError("max_redirects must be an integer")
    if not 0 <= max_redirects <= _MAX_PLUGIN_REDIRECTS:
        raise ValueError(f"max_redirects must be between 0 and {_MAX_PLUGIN_REDIRECTS}")
    return max_redirects


class ProviderPullHttpClient:
    """Credential-free plugin HTTP facade over OpenOpps' bounded transport.

    The facade intentionally exposes no raw ``httpx`` client, generic request,
    header, cookie, or authentication surface. Every response therefore crosses
    the shared public-URL, retry, cache, per-response, and active operation-budget
    boundaries before untrusted plugin code can inspect its body.
    """

    __slots__ = (
        "__cache_identity_scope",
        "__json_request",
        "__operation_budget",
        "__operation_counters",
        "__provider_id",
        "__text_request",
    )

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: OpenOppsSettings,
        *,
        provider_id: str,
    ) -> None:
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client must be an httpx.AsyncClient")
        if not isinstance(settings, OpenOppsSettings):
            raise TypeError("settings must be OpenOppsSettings")
        self.__provider_id = _bounded_pull_http_identity(
            provider_id,
            label="provider_id",
        )
        self.__cache_identity_scope = _capture_http_cache_identity_scope()
        self.__operation_budget = _capture_http_operation_budget()
        self.__operation_counters = _capture_http_operation_counters()
        request_json = retrying_json_request(settings)
        request_text = retrying_text_request(settings)

        async def bounded_json_request(
            method: str,
            url: str,
            **kwargs: object,
        ) -> JsonResponseData:
            with (
                _bind_http_operation_budget(self.__operation_budget),
                _bind_http_operation_counters(self.__operation_counters),
                _bind_http_cache_identity_scope(self.__cache_identity_scope),
            ):
                return await request_json(client, method, url, **kwargs)

        async def bounded_text_request(
            method: str,
            url: str,
            **kwargs: object,
        ) -> str:
            with (
                _bind_http_operation_budget(self.__operation_budget),
                _bind_http_operation_counters(self.__operation_counters),
                _bind_http_cache_identity_scope(self.__cache_identity_scope),
            ):
                return await request_text(client, method, url, **kwargs)

        self.__json_request = bounded_json_request
        self.__text_request = bounded_text_request

    async def get_json(
        self,
        url: str,
        *,
        role: str,
        params: Mapping[str, object] | None = None,
        max_redirects: int = 0,
    ) -> JsonResponseData:
        """Fetch one public JSON resource under a provider/role cache identity."""

        return await self.__json_request(
            "GET",
            url,
            **self._request_kwargs(
                role=role,
                params=params,
                max_redirects=max_redirects,
            ),
        )

    async def post_json(
        self,
        url: str,
        *,
        role: str,
        params: Mapping[str, object] | None = None,
        json_body: object | None = None,
        max_redirects: int = 0,
    ) -> JsonResponseData:
        """POST JSON-compatible data and admit only a bounded JSON response."""

        kwargs = self._request_kwargs(
            role=role,
            params=params,
            max_redirects=max_redirects,
        )
        kwargs["json"] = json_body
        return await self.__json_request("POST", url, **kwargs)

    async def get_text(
        self,
        url: str,
        *,
        role: str,
        params: Mapping[str, object] | None = None,
        max_redirects: int = 0,
    ) -> str:
        """Fetch one public text resource under a provider/role cache identity."""

        return await self.__text_request(
            "GET",
            url,
            **self._request_kwargs(
                role=role,
                params=params,
                max_redirects=max_redirects,
            ),
        )

    async def post_text(
        self,
        url: str,
        *,
        role: str,
        params: Mapping[str, object] | None = None,
        json_body: object | None = None,
        max_redirects: int = 0,
    ) -> str:
        """POST JSON-compatible data and admit only a bounded text response."""

        kwargs = self._request_kwargs(
            role=role,
            params=params,
            max_redirects=max_redirects,
        )
        kwargs["json"] = json_body
        return await self.__text_request("POST", url, **kwargs)

    def _request_kwargs(
        self,
        *,
        role: str,
        params: Mapping[str, object] | None,
        max_redirects: int,
    ) -> dict[str, object]:
        normalized_role = _bounded_pull_http_identity(role, label="role")
        bounded_redirects = _bounded_pull_redirects(max_redirects)
        return {
            "cache_identity": {
                "provider": self.__provider_id,
                "role": normalized_role,
            },
            "cache_namespace": "provider-pull-plugin",
            "follow_redirects": bounded_redirects > 0,
            "max_redirects": bounded_redirects,
            "params": dict(params) if params is not None else None,
        }


class ProviderPullBudgetError(ValueError):
    """Bounded provider-operation failure caused by a trusted local limit."""

    def __init__(self, reason: str, *, limit: int, observed: int) -> None:
        self.reason = reason
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"Provider pull exceeded the configured {reason} limit ({limit})"
        )


def ensure_detail_fanout_within_budget(
    count: int,
    *,
    maximum_details: int,
) -> None:
    """Reject untrusted detail cardinality before any worker tasks are created."""

    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("detail count must be a non-negative integer")
    if (
        isinstance(maximum_details, bool)
        or not isinstance(maximum_details, int)
        or maximum_details < 1
    ):
        raise ValueError("maximum details must be a positive integer")
    if count > maximum_details:
        raise ProviderPullBudgetError(
            "detail fan-out",
            limit=maximum_details,
            observed=count,
        )


def decode_url_identity_segment(value: str) -> str | None:
    """Decode one bounded path identity without admitting path/query delimiters."""

    if not value or _INVALID_PERCENT_ESCAPE_RE.search(value):
        return None
    try:
        identity = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        not identity
        or identity in {".", ".."}
        or len(identity) > 500
        or "%" in identity
        or any(character in identity for character in "/\\?#")
        or any(character.isspace() for character in identity)
        or any(ord(character) < 32 or ord(character) == 127 for character in identity)
    ):
        return None
    return identity


async def bounded_async_map(
    items: Sequence[_ItemT],
    worker: Callable[[_ItemT], Awaitable[_ResultT]],
    *,
    max_concurrency: int,
) -> list[_ResultT]:
    """Map async work in input order while creating only bounded worker tasks."""

    if (
        isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or max_concurrency <= 0
    ):
        raise ValueError("max_concurrency must be a positive integer")
    if not items:
        return []

    sentinel = object()
    results: list[_ResultT | object] = [sentinel] * len(items)
    indexed_items = iter(enumerate(items))

    async def consume() -> None:
        while True:
            try:
                index, item = next(indexed_items)
            except StopIteration:
                return
            results[index] = await worker(item)

    tasks = [
        asyncio.create_task(consume()) for _ in range(min(max_concurrency, len(items)))
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    if any(result is sentinel for result in results):
        raise RuntimeError("bounded async map did not produce every result")
    return cast(list[_ResultT], results)


class ProviderTargetKind(StrEnum):
    """Whether a provider-native URL identifies a board or one posting."""

    BOARD = "board"
    POSTING = "posting"


class InterfaceStability(StrEnum):
    """Evidence tier for a provider's public URL-pull interface."""

    DOCUMENTED = "documented"
    BEST_EFFORT = "best_effort"


class MembershipScope(StrEnum):
    """Provider membership represented by a complete list result."""

    LISTED = "listed"
    ALL_PUBLIC = "all_public"


class ProviderGetMethod(StrEnum):
    """Evidence path used to retrieve one exact posting."""

    NATIVE = "native"
    BOARD_SCAN = "board_scan"


class _ProviderPullModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
        validate_default=True,
    )


class ProviderRouteIdentity(_ProviderPullModel):
    """Provider-native route fields retained independently from stored routes."""

    token: BoundedIdentity | None = None
    host: BoundedIdentity | None = None
    tenant: BoundedIdentity | None = None
    site: BoundedIdentity | None = None


class ProviderUrlTarget(_ProviderPullModel):
    """Typed provider-native URL target that never discards posting identity."""

    provider_id: BoundedIdentity
    target_kind: ProviderTargetKind
    url: SanitizedPublicHttpsUrlStr
    board_identity: BoundedIdentity
    posting_identity: BoundedIdentity | None = None
    route: ProviderRouteIdentity = Field(default_factory=ProviderRouteIdentity)

    @model_validator(mode="after")
    def _validate_target_identity(self) -> ProviderUrlTarget:
        if self.target_kind == ProviderTargetKind.BOARD:
            if self.posting_identity is not None:
                raise ValueError("board target must not carry a posting identity")
        elif self.posting_identity is None:
            raise ValueError("posting target requires a posting identity")
        return self

    def for_board_scan(self) -> ProviderUrlTarget:
        """Project an exact target to its retained board route for list fallback."""

        if self.target_kind == ProviderTargetKind.BOARD:
            return self
        return ProviderUrlTarget(
            provider_id=self.provider_id,
            target_kind=ProviderTargetKind.BOARD,
            url=self.url,
            board_identity=self.board_identity,
            route=self.route,
        )


ProviderTargetParser = Callable[[str], ProviderUrlTarget | None]


class ProviderPullCapabilities(_ProviderPullModel):
    """Independent URL detection and execution capabilities for one provider."""

    detect_supported: bool = True
    list_supported: bool = False
    native_get_supported: bool = False
    board_scan_get_supported: bool = False
    exact_unlisted_get_supported: bool = False
    enumerate_unlisted_supported: bool = False
    interface_stability: InterfaceStability

    @model_validator(mode="after")
    def _validate_capability_dependencies(self) -> ProviderPullCapabilities:
        if self.board_scan_get_supported and not self.list_supported:
            raise ValueError("board-scan get requires list support")
        if self.enumerate_unlisted_supported and not self.list_supported:
            raise ValueError("unlisted enumeration requires list support")
        if self.exact_unlisted_get_supported and not (
            self.native_get_supported
            or (self.board_scan_get_supported and self.enumerate_unlisted_supported)
        ):
            raise ValueError(
                "exact unlisted get requires native get or all-public board scan"
            )
        if not self.detect_supported and any(
            (
                self.list_supported,
                self.native_get_supported,
                self.board_scan_get_supported,
                self.exact_unlisted_get_supported,
                self.enumerate_unlisted_supported,
            )
        ):
            raise ValueError("executable pull capabilities require target detection")
        return self


class ProviderPosting(_ProviderPullModel):
    """One normalized job bound to explicit provider-native evidence roles."""

    job: JobRecord
    listing: JsonDict | None
    detail: JsonDict | None

    @model_validator(mode="after")
    def _validate_evidence_binding(self) -> ProviderPosting:
        self.assert_valid()
        return self

    def assert_valid(self) -> None:
        """Recheck mutable job/raw state before provider result use."""

        if self.listing is None:
            if self.job.raw_listing:
                raise ValueError(
                    "listing evidence is missing for a populated normalized job"
                )
        elif self.listing != self.job.raw_listing:
            raise ValueError("listing evidence must match the normalized job")
        if self.detail is None:
            if self.job.raw_detail:
                raise ValueError(
                    "detail evidence is missing for a populated normalized job"
                )
        elif self.detail != self.job.raw_detail:
            raise ValueError("detail evidence must match the normalized job")


class MembershipEvidence(_ProviderPullModel):
    """Completeness and authority evidence for a provider board membership set."""

    scope: MembershipScope
    authoritative: bool
    complete: bool
    terminal_page_seen: bool
    pages_fetched: PositiveInt
    observed_count: NonNegativeInt
    advertised_count: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _validate_authority(self) -> MembershipEvidence:
        if self.authoritative and not (self.complete and self.terminal_page_seen):
            raise ValueError(
                "authoritative membership requires complete terminal-page evidence"
            )
        if (
            self.authoritative
            and self.advertised_count is not None
            and self.advertised_count != self.observed_count
        ):
            raise ValueError(
                "authoritative membership must reconcile advertised and observed counts"
            )
        return self


class DetailCoverageEvidence(_ProviderPullModel):
    """Detail fan-out coverage independent from board membership authority."""

    required: bool = False
    requested_count: NonNegativeInt = 0
    completed_count: NonNegativeInt = 0
    failed_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def _validate_counts(self) -> DetailCoverageEvidence:
        if self.completed_count + self.failed_count > self.requested_count:
            raise ValueError("detail outcomes cannot exceed requested details")
        return self

    @property
    def complete(self) -> bool:
        return self.completed_count == self.requested_count and self.failed_count == 0


class ProviderListResult(_ProviderPullModel):
    """Identity-bound full-board result with membership and detail evidence."""

    provider_id: BoundedIdentity
    board_identity: BoundedIdentity
    postings: tuple[ProviderPosting, ...]
    membership: MembershipEvidence
    detail_coverage: DetailCoverageEvidence = Field(
        default_factory=DetailCoverageEvidence
    )

    @model_validator(mode="after")
    def _validate_result_counts(self) -> ProviderListResult:
        self.assert_valid()
        return self

    def assert_valid(self) -> None:
        """Recheck target identity, authority, raw evidence, and detail coverage."""

        for posting in self.postings:
            posting.assert_valid()
        if self.membership.observed_count != len(self.postings):
            raise ValueError(
                "membership observed count must equal returned posting count"
            )
        identities = [posting.job.remote_id for posting in self.postings]
        if len(set(identities)) != len(identities):
            raise ValueError("provider list result posting identities must be unique")
        if any(
            posting.job.provider_id != self.provider_id for posting in self.postings
        ):
            raise ValueError(
                "provider list result cannot mix providers or mismatch its provider identity"
            )
        if any(
            posting.job.board_key != self.board_identity for posting in self.postings
        ):
            raise ValueError(
                "provider list result cannot mix board identities or mismatch its board identity"
            )
        if self.membership.scope == MembershipScope.LISTED and any(
            posting.job.posting_kind == "unlisted" for posting in self.postings
        ):
            raise ValueError("listed membership cannot include unlisted postings")
        evidence_details = sum(posting.detail is not None for posting in self.postings)
        if self.detail_coverage.completed_count > evidence_details:
            raise ValueError("completed detail count exceeds captured detail evidence")
        if self.detail_coverage.required and (
            self.detail_coverage.requested_count != self.membership.observed_count
            or self.detail_coverage.requested_count != len(self.postings)
        ):
            raise ValueError(
                "required detail coverage must request every returned posting"
            )
        if (
            self.detail_coverage.required
            and self.detail_coverage.complete
            and self.detail_coverage.completed_count != evidence_details
        ):
            raise ValueError(
                "complete required detail coverage must match captured evidence"
            )

    @property
    def ready_for_apply(self) -> bool:
        self.assert_valid()
        return self.membership.authoritative and (
            not self.detail_coverage.required or self.detail_coverage.complete
        )

    def exact_match(
        self,
        *,
        provider_id: str,
        board_identity: str,
        posting_identity: str,
    ) -> ProviderPosting:
        """Return one punctuation-preserving native identity match or fail closed."""

        self.assert_valid()
        if provider_id != self.provider_id:
            raise ValueError(
                "exact board scan provider identity does not match the source list"
            )
        if board_identity != self.board_identity:
            raise ValueError(
                "exact board scan board identity does not match the source list"
            )
        if not self.ready_for_apply:
            raise ValueError("exact board scan requires authoritative membership")
        matches = [
            posting
            for posting in self.postings
            if posting.job.provider_id == provider_id
            and posting.job.board_key == board_identity
            and posting.job.remote_id == posting_identity
        ]
        if len(matches) != 1:
            raise ValueError("exact board scan must match exactly one posting identity")
        return matches[0]

    def to_job_fetch_result(self) -> JobFetchResult:
        """Project a compatible listed snapshot to the unchanged sync contract."""

        self.assert_valid()
        if not self.ready_for_apply:
            raise ValueError(
                "only an authoritative complete result can project to sync"
            )
        if self.membership.scope != MembershipScope.LISTED:
            raise ValueError("current sync projection accepts listed membership only")
        from openopps.providers.base import JobFetchResult

        return JobFetchResult(
            jobs=[posting.job for posting in self.postings],
            authoritative=True,
        )


class ProviderGetResult(_ProviderPullModel):
    """One exact posting without conflating native get and board membership."""

    posting: ProviderPosting
    method: ProviderGetMethod
    matched_identity: BoundedIdentity
    source_list: ProviderListResult | None = Field(default=None, exclude=True)

    @property
    def membership(self) -> MembershipEvidence | None:
        return self.source_list.membership if self.source_list is not None else None

    @model_validator(mode="after")
    def _validate_exact_get(self) -> ProviderGetResult:
        self.assert_valid()
        return self

    def assert_valid(self) -> None:
        """Recheck exact identity and authoritative list binding."""

        self.posting.assert_valid()
        if self.posting.job.remote_id != self.matched_identity:
            raise ValueError("get result must match the exact posting identity")
        if self.method == ProviderGetMethod.NATIVE:
            if self.source_list is not None:
                raise ValueError("native get cannot carry board membership evidence")
            return
        if self.source_list is None:
            raise ValueError("board-scan get requires an authoritative source list")
        self.source_list.assert_valid()
        matched = self.source_list.exact_match(
            provider_id=self.posting.job.provider_id,
            board_identity=self.posting.job.board_key,
            posting_identity=self.matched_identity,
        )
        if matched != self.posting:
            raise ValueError(
                "board-scan get posting must come from its authoritative source list"
            )

    @classmethod
    def from_board_scan(
        cls,
        source_list: ProviderListResult,
        *,
        provider_id: str,
        board_identity: str,
        posting_identity: str,
    ) -> ProviderGetResult:
        posting = source_list.exact_match(
            provider_id=provider_id,
            board_identity=board_identity,
            posting_identity=posting_identity,
        )
        return cls(
            posting=posting,
            method=ProviderGetMethod.BOARD_SCAN,
            matched_identity=posting_identity,
            source_list=source_list,
        )


class ProviderListHook(Protocol):
    async def __call__(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult: ...


class ProviderNativeGetHook(Protocol):
    async def __call__(
        self,
        client: httpx.AsyncClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult: ...


class PluginProviderListHook(Protocol):
    """Plugin list hook limited to the bounded public HTTP facade."""

    async def __call__(
        self,
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
        *,
        include_unlisted: bool,
    ) -> ProviderListResult: ...


class PluginProviderNativeGetHook(Protocol):
    """Plugin native-get hook limited to the bounded public HTTP facade."""

    async def __call__(
        self,
        client: ProviderPullHttpClient,
        target: ProviderUrlTarget,
    ) -> ProviderGetResult: ...
