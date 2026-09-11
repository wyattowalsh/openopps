from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, TypeVar, cast

from openopps.models import BoardRecord, JobRecord, JsonDict
from openopps.providers.base import JobFetchResult
from openopps.providers.boards.url_targets import (
    URL_PULL_SOURCE_KEY,
    synthetic_url_pull_board,
)
from openopps.utils import stable_id

ListingIdentityMode = Literal["ingest", "pull"]

_ItemT = TypeVar("_ItemT")
_ResultT = TypeVar("_ResultT")


class MembershipScope(StrEnum):
    """Provider membership represented by a complete listing snapshot."""

    LISTED = "listed"
    ALL_PUBLIC = "all_public"


@dataclass(frozen=True, slots=True)
class MembershipEvidence:
    """Completeness and authority evidence for one board membership set."""

    scope: MembershipScope
    authoritative: bool
    complete: bool
    terminal_page_seen: bool
    pages_fetched: int
    observed_count: int
    advertised_count: int | None = None


@dataclass(frozen=True, slots=True)
class DetailCoverageEvidence:
    """Detail fan-out coverage independent from board membership authority."""

    required: bool = False
    requested_count: int = 0
    completed_count: int = 0
    failed_count: int = 0

    @property
    def complete(self) -> bool:
        return self.completed_count == self.requested_count and self.failed_count == 0


@dataclass(frozen=True, slots=True)
class ListingPosting:
    """One normalized job bound to listing and optional detail evidence."""

    job: JobRecord
    listing: JsonDict | None
    detail: JsonDict | None


@dataclass(frozen=True, slots=True)
class BoardListingKernelResult:
    """Native membership evidence before catalog or URL-pull identity bind."""

    native_board_identity: str
    postings: tuple[ListingPosting, ...]
    membership: MembershipEvidence
    detail_coverage: DetailCoverageEvidence = field(
        default_factory=DetailCoverageEvidence
    )

    def to_job_fetch_result(
        self,
        board: BoardRecord,
        *,
        provider_id: str,
        authoritative: bool | None = None,
    ) -> JobFetchResult:
        """Bind onto a catalog board after membership evidence is complete."""

        if authoritative is None:
            authoritative = (
                self.membership.authoritative
                and self.membership.complete
                and self.membership.terminal_page_seen
            )
        if authoritative and not (
            self.membership.complete and self.membership.terminal_page_seen
        ):
            raise ValueError("incomplete listing cannot be authoritative")
        return JobFetchResult(
            jobs=bind_listing_jobs(self, board, provider_id=provider_id),
            authoritative=authoritative,
        )

    def to_provider_list_result(
        self,
        target: Any,
        *,
        board: BoardRecord | None = None,
    ) -> Any:
        """Bind onto the synthetic URL-pull board and wrap existing list evidence."""

        pull = load_optional_pull()
        if pull is None:
            raise ModuleNotFoundError("openopps.providers.pull")
        pull_board = board or synthetic_url_pull_board(self.native_board_identity)
        jobs = bind_listing_jobs(self, pull_board, provider_id=target.provider_id)
        postings = tuple(
            pull.ProviderPosting(
                job=job,
                listing=original.listing,
                detail=original.detail,
            )
            for job, original in zip(jobs, self.postings, strict=True)
        )
        return pull.ProviderListResult(
            provider_id=target.provider_id,
            board_identity=target.board_identity,
            postings=postings,
            membership=pull.MembershipEvidence(
                scope=pull.MembershipScope(str(self.membership.scope)),
                authoritative=self.membership.authoritative,
                complete=self.membership.complete,
                terminal_page_seen=self.membership.terminal_page_seen,
                pages_fetched=self.membership.pages_fetched,
                observed_count=self.membership.observed_count,
                advertised_count=self.membership.advertised_count,
            ),
            detail_coverage=pull.DetailCoverageEvidence(
                required=self.detail_coverage.required,
                requested_count=self.detail_coverage.requested_count,
                completed_count=self.detail_coverage.completed_count,
                failed_count=self.detail_coverage.failed_count,
            ),
        )


def bind_listing_jobs(
    kernel: BoardListingKernelResult,
    board: BoardRecord,
    *,
    provider_id: str,
) -> list[JobRecord]:
    """Assign catalog or URL-pull identity after membership evidence is complete."""

    if board.source_key == URL_PULL_SOURCE_KEY and (
        board.key != kernel.native_board_identity
    ):
        raise ValueError(
            "url-pull bind requires board.key to equal the native board identity"
        )
    rebound: list[JobRecord] = []
    for posting in kernel.postings:
        job = posting.job
        if job.provider_id != provider_id:
            raise ValueError("listing kernel cannot mix providers during identity bind")
        if job.board_key != kernel.native_board_identity:
            raise ValueError(
                "listing kernel postings must use the native board identity until bind"
            )
        company = job.company
        if company is None or company == job.board_key:
            company = board.name
        rebound.append(
            job.model_copy(
                update={
                    "id": stable_id(board.key, provider_id, job.remote_id),
                    "board_key": board.key,
                    "company": company,
                }
            )
        )
    return rebound


def rebound_provider_postings(
    kernel: BoardListingKernelResult,
    jobs: Sequence[JobRecord],
) -> tuple[ListingPosting, ...]:
    """Re-wrap rebound jobs while preserving listing and detail evidence."""

    return tuple(
        ListingPosting(job=job, listing=original.listing, detail=original.detail)
        for job, original in zip(jobs, kernel.postings, strict=True)
    )


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


def load_optional_pull() -> Any:
    """Return providers.pull when present; otherwise None."""

    try:
        from openopps.providers import pull as pull_module
    except ModuleNotFoundError:
        return None
    return pull_module


def optional_pull_attr(name: str, default: Any = None) -> Any:
    """Return one providers.pull attribute, or default when pull is absent."""

    pull = load_optional_pull()
    if pull is None:
        return default
    return getattr(pull, name, default)


def optional_pull_capabilities(
    *,
    interface_stability: str,
    list_supported: bool = False,
    native_get_supported: bool = False,
    board_scan_get_supported: bool = False,
    exact_unlisted_get_supported: bool = False,
    enumerate_unlisted_supported: bool = False,
    detect_supported: bool = True,
) -> Any | None:
    """Return URL-pull capabilities when providers.pull is importable."""

    pull = load_optional_pull()
    if pull is None:
        return None
    return pull.ProviderPullCapabilities(
        detect_supported=detect_supported,
        list_supported=list_supported,
        native_get_supported=native_get_supported,
        board_scan_get_supported=board_scan_get_supported,
        exact_unlisted_get_supported=exact_unlisted_get_supported,
        enumerate_unlisted_supported=enumerate_unlisted_supported,
        interface_stability=pull.InterfaceStability(interface_stability),
    )


__all__ = [
    "BoardListingKernelResult",
    "DetailCoverageEvidence",
    "ListingIdentityMode",
    "ListingPosting",
    "MembershipEvidence",
    "MembershipScope",
    "bind_listing_jobs",
    "bounded_async_map",
    "load_optional_pull",
    "optional_pull_attr",
    "optional_pull_capabilities",
    "rebound_provider_postings",
]
