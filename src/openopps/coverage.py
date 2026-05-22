from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    utc_now,
)
from openopps.providers.registry import provider_registry
from openopps.route_registry import select_routes_from_records
from openopps.route_select import normalize_provider_filter, route_ready
from openopps.storage import OpenOppsStore


EXAMPLE_LIMIT = 5
BASELINE_JOB_PROVIDER_IDS = frozenset({"ashbyhq", "greenhouse", "lever", "workday"})
AUDIT_PROVIDER_TARGETS = (
    "smartrecruiters",
    "workable",
    "recruitee",
    "teamtailor",
    "bamboohr",
    "icims",
    "jobvite",
    "jazzhr",
)
DO_NOT_ADOPT_RATIONALES = {
    "smartrecruiters": "Keep detect-only until a stable public hosted-board JSON route is proven across multiple boards.",
    "workable": "Keep detect-only until generic public board URLs and pagination are validated without authenticated APIs.",
    "recruitee": "Keep detect-only until hosted-board payload stability and route token extraction are validated.",
    "teamtailor": "Detect-only in v0.1; public fetching needs a separate generic endpoint audit before adoption.",
    "bamboohr": "Keep unsupported for v0.1 because public job access varies by tenant and often lacks a stable JSON route.",
    "icims": "Keep unsupported for v0.1 because hosted pages vary widely and generic public fetching is brittle.",
    "jobvite": "Keep unsupported for v0.1 until modern hosted-board endpoints are proven generic and unauthenticated.",
    "jazzhr": "Keep unsupported for v0.1 until public board route extraction and pagination are proven generic.",
}


@dataclass(frozen=True)
class CoverageMetric:
    present: int
    missing: int
    total: int

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.present / self.total) * 100, 2)

    def as_dict(self) -> dict[str, int | float]:
        return {
            "present": self.present,
            "missing": self.missing,
            "total": self.total,
            "percentage": self.percentage,
        }


@dataclass(frozen=True)
class CoverageReport:
    filters: dict[str, str | None]
    sources: dict[str, Any]
    boards: dict[str, Any]
    routes: dict[str, Any]
    jobs: dict[str, Any]
    gaps: dict[str, Any]
    data_quality: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "filters": self.filters,
            "sources": self.sources,
            "boards": self.boards,
            "routes": self.routes,
            "jobs": self.jobs,
            "gaps": self.gaps,
            "dataQuality": self.data_quality,
        }


@dataclass(frozen=True)
class ProviderAuditReport:
    snapshot: dict[str, Any]
    coverage: dict[str, Any]
    candidates: list[dict[str, Any]]
    do_not_adopt_rationales: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "coverage": self.coverage,
            "candidates": self.candidates,
            "doNotAdoptRationales": self.do_not_adopt_rationales,
        }


def build_coverage_report(
    store: OpenOppsStore,
    *,
    source_key: str | None = None,
    provider_id: str | None = None,
) -> CoverageReport:
    """Build an offline coverage and data-quality report from persisted records."""

    provider_filter = normalize_provider_filter(provider_id)
    sources = [
        source
        for source in store.list_sources()
        if source_key is None or source.key == source_key
    ]
    boards = store.list_boards(source_key=source_key, with_providers=False)
    boards_by_key = {board.key: board for board in boards}
    routes = store.list_board_providers(
        source_key=source_key,
        provider_id=provider_filter,
    )

    jobs = _filter_jobs_by_source(
        store.list_jobs(provider_id=provider_filter), boards_by_key, source_key
    )
    selection = select_routes_from_records(
        boards=boards,
        routes=[
            route for route in routes if route.support_level == ProviderSupport.JOBS
        ],
    )
    jobs_by_board_provider = {(job.board_key, job.provider_id): 0 for job in jobs}
    for job in jobs:
        jobs_by_board_provider[(job.board_key, job.provider_id)] = (
            jobs_by_board_provider.get((job.board_key, job.provider_id), 0) + 1
        )
    routes_by_board = _routes_by_board(boards, routes)
    board_keys_with_provider_hints = set(routes_by_board)
    board_keys_with_job_capable_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(route.support_level == ProviderSupport.JOBS for route in board_routes)
    }
    board_keys_with_baseline_job_capable_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(
            route.support_level == ProviderSupport.JOBS
            and route.provider_id in BASELINE_JOB_PROVIDER_IDS
            for route in board_routes
        )
    }
    board_keys_with_detect_only_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(route.support_level == ProviderSupport.DETECT for route in board_routes)
    }
    board_keys_with_unsupported_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(
            route.support_level == ProviderSupport.UNSUPPORTED for route in board_routes
        )
    }
    board_keys_with_non_supported_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(_is_non_supported_route(route) for route in board_routes)
    }
    board_keys_with_only_non_supported_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if board_routes
        and all(_is_non_supported_route(route) for route in board_routes)
    }
    non_supported_routes = [route for route in routes if _is_non_supported_route(route)]
    non_supported_metric = CoverageMetric(
        present=len(board_keys_with_non_supported_hints),
        missing=len(boards) - len(board_keys_with_non_supported_hints),
        total=len(boards),
    )

    return CoverageReport(
        filters={"source": source_key, "provider": provider_filter},
        sources={
            "total": len(sources),
            "enabled": sum(1 for source in sources if source.enabled),
            "disabled": sum(1 for source in sources if not source.enabled),
            "byProvider": _count_by(source.provider_id for source in sources),
        },
        boards={
            "total": len(boards),
            "bySource": _count_by(board.source_key for board in boards),
            "withProviderHints": len(board_keys_with_provider_hints),
            "withJobCapableProviderHints": len(board_keys_with_job_capable_hints),
            "withBaselineJobCapableProviderHints": len(
                board_keys_with_baseline_job_capable_hints
            ),
            "withAdoptedV01ProviderHints": len(board_keys_with_job_capable_hints),
            "withDetectOnlyProviderHints": len(board_keys_with_detect_only_hints),
            "withUnsupportedOrUnknownProviderHints": len(
                board_keys_with_unsupported_hints
            ),
            "withNonSupportedProviderHints": len(board_keys_with_non_supported_hints),
            "withOnlyNonSupportedProviderHints": len(
                board_keys_with_only_non_supported_hints
            ),
            "nonSupportedProviderCoverage": non_supported_metric.as_dict(),
        },
        routes={
            "total": len(routes),
            "byProvider": _count_by(route.provider_id for route in routes),
            "bySupportLevel": _count_by(route.support_level.value for route in routes),
            "nonSupportedTotal": len(non_supported_routes),
            "nonSupportedByProvider": _count_by(
                route.provider_id for route in non_supported_routes
            ),
            "byLastStatus": _count_by(
                route.last_status or "unknown" for route in routes
            ),
            "executable": len(selection.entries),
            "missingRouteMetadata": len(selection.missing_route_metadata),
            "duplicateRoutesSkipped": len(selection.duplicate_routes),
        },
        jobs={
            "total": len(jobs),
            "byProvider": _count_by(job.provider_id for job in jobs),
            "bySource": _count_jobs_by_source(jobs, boards_by_key),
            "byBoard": _count_by(job.board_key for job in jobs),
        },
        gaps={
            "boardsWithJobCapableProviderHintsButNoExecutableRoute": (
                _boards_with_job_hints_but_no_executable_route(boards, routes)
            ),
            "boardsWithExecutableRouteButZeroJobs": (
                _boards_with_executable_route_but_zero_jobs(
                    selection.entries, jobs_by_board_provider
                )
            ),
            "detectOnlyProviders": _detect_only_providers(routes),
            "nonSupportedProviders": _non_supported_providers(non_supported_routes),
            "boardsWithOnlyNonSupportedProviderHints": (
                _boards_with_only_non_supported_provider_hints(
                    boards, routes_by_board, board_keys_with_only_non_supported_hints
                )
            ),
        },
        data_quality=_data_quality(jobs),
    )


def build_provider_audit_report(
    store: OpenOppsStore,
    *,
    source_key: str | None = None,
) -> ProviderAuditReport:
    """Build a persisted-board audit for candidate v0.1 provider adoption."""

    coverage = build_coverage_report(store, source_key=source_key).as_dict()
    sources = [
        source
        for source in store.list_sources()
        if source_key is None or source.key == source_key
    ]
    boards = store.list_boards(source_key=source_key, with_providers=False)
    routes = store.list_board_providers(source_key=source_key)
    routes_by_provider: dict[str, list[BoardProviderRecord]] = {}
    for route in routes:
        routes_by_provider.setdefault(route.provider_id, []).append(route)

    registry = provider_registry(settings=store.settings)
    denominator = len(boards)
    candidates = []
    for provider_id in AUDIT_PROVIDER_TARGETS:
        provider_routes = routes_by_provider.get(provider_id, [])
        board_keys = {route.board_key for route in provider_routes}
        observed_support_levels = sorted(
            {route.support_level.value for route in provider_routes}
        )
        metric = CoverageMetric(
            present=len(board_keys),
            missing=denominator - len(board_keys),
            total=denominator,
        ).as_dict()
        support_level = registry.support_level(provider_id).value
        candidates.append(
            {
                "provider": provider_id,
                "currentSupportLevel": support_level,
                "packagedSupportLevel": support_level,
                "observedSupportLevels": observed_support_levels,
                "observedDetectOnlyBoards": len(
                    {
                        route.board_key
                        for route in provider_routes
                        if route.support_level == ProviderSupport.DETECT
                    }
                ),
                "observedUnsupportedBoards": len(
                    {
                        route.board_key
                        for route in provider_routes
                        if route.support_level == ProviderSupport.UNSUPPORTED
                    }
                ),
                "routes": len(provider_routes),
                "boards": len(board_keys),
                "coverage": metric,
                "examples": sorted(board_keys)[:EXAMPLE_LIMIT],
                "adoptedForV01": support_level == ProviderSupport.JOBS.value,
                "deltaIfGenericFetchingAdopted": {
                    "boards": len(board_keys),
                    "percentagePoints": metric["percentage"],
                },
                "rationale": DO_NOT_ADOPT_RATIONALES[provider_id],
            }
        )

    return ProviderAuditReport(
        snapshot={
            "generatedAt": utc_now().isoformat(),
            "sourceSet": sorted(source.key for source in sources),
            "sourceCount": len(sources),
            "denominator": denominator,
            "scope": {"source": source_key},
            "hasPersistedBoards": denominator > 0,
            "representative": False,
            "snapshotKind": "persisted-scope",
            "note": (
                "Measured from persisted boards in the selected scope; run source syncs "
                "before release publication to refresh this snapshot."
            ),
        },
        coverage={
            "boards": coverage["boards"],
            "routes": coverage["routes"],
            "gaps": coverage["gaps"],
        },
        candidates=candidates,
        do_not_adopt_rationales=DO_NOT_ADOPT_RATIONALES,
    )


def _routes_by_board(
    boards: list[BoardRecord],
    routes: list[BoardProviderRecord],
) -> dict[str, list[BoardProviderRecord]]:
    board_keys = {board.key for board in boards}
    grouped: dict[str, list[BoardProviderRecord]] = {}
    for route in routes:
        if route.board_key not in board_keys:
            continue
        grouped.setdefault(route.board_key, []).append(route)
    return grouped


def _is_non_supported_route(route: BoardProviderRecord) -> bool:
    return route.support_level != ProviderSupport.JOBS


def _filter_jobs_by_source(
    jobs: list[JobRecord],
    boards_by_key: dict[str, BoardRecord],
    source_key: str | None,
) -> list[JobRecord]:
    if source_key is None:
        return jobs
    return [
        job
        for job in jobs
        if (board := boards_by_key.get(job.board_key))
        and board.source_key == source_key
    ]


def _boards_with_job_hints_but_no_executable_route(
    boards: list[BoardRecord],
    routes: list[BoardProviderRecord],
) -> list[dict[str, Any]]:
    job_routes_by_board: dict[str, list[BoardProviderRecord]] = {}
    for route in routes:
        if route.support_level == ProviderSupport.JOBS:
            job_routes_by_board.setdefault(route.board_key, []).append(route)

    gaps: list[dict[str, Any]] = []
    for board in sorted(boards, key=lambda item: item.key):
        job_routes = job_routes_by_board.get(board.key, [])
        if not job_routes:
            continue
        if any(route_ready(route) for route in job_routes):
            continue
        gaps.append(
            {
                "board": board.key,
                "source": board.source_key,
                "providers": sorted({route.provider_id for route in job_routes}),
            }
        )
    return gaps


def _boards_with_executable_route_but_zero_jobs(
    entries,
    jobs_by_board_provider: dict[tuple[str, str], int],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for entry in sorted(
        entries, key=lambda item: (item.board.key, item.route.provider_id)
    ):
        key = (entry.route.board_key, entry.route.provider_id)
        if jobs_by_board_provider.get(key, 0) > 0:
            continue
        gaps.append(
            {
                "board": entry.board.key,
                "source": entry.board.source_key,
                "provider": entry.route.provider_id,
                "route": entry.route.token
                or entry.route.site
                or entry.route.board_url
                or entry.request_key,
                "verified": entry.verified,
            }
        )
    return gaps


def _detect_only_providers(routes: list[BoardProviderRecord]) -> list[dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    seen_examples: set[tuple[str, str]] = set()
    for route in routes:
        if route.support_level != ProviderSupport.DETECT:
            continue
        item = providers.setdefault(
            route.provider_id,
            {
                "provider": route.provider_id,
                "supportLevel": route.support_level.value,
                "count": 0,
                "examples": [],
            },
        )
        item["count"] += 1
        example_key = (route.provider_id, route.board_key)
        if example_key not in seen_examples and len(item["examples"]) < EXAMPLE_LIMIT:
            seen_examples.add(example_key)
            item["examples"].append(route.board_key)
    return [providers[key] for key in sorted(providers)]


def _non_supported_providers(
    routes: list[BoardProviderRecord],
) -> list[dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    seen_examples: set[tuple[str, str]] = set()
    seen_boards: set[tuple[str, str]] = set()
    for route in routes:
        item = providers.setdefault(
            route.provider_id,
            {
                "provider": route.provider_id,
                "supportLevel": route.support_level.value,
                "routes": 0,
                "boards": 0,
                "examples": [],
            },
        )
        item["routes"] += 1
        board_seen_key = (route.provider_id, route.board_key)
        if board_seen_key not in seen_boards:
            seen_boards.add(board_seen_key)
            item["boards"] += 1
        if (
            board_seen_key not in seen_examples
            and len(item["examples"]) < EXAMPLE_LIMIT
        ):
            seen_examples.add(board_seen_key)
            item["examples"].append(route.board_key)
    return [providers[key] for key in sorted(providers)]


def _boards_with_only_non_supported_provider_hints(
    boards: list[BoardRecord],
    routes_by_board: dict[str, list[BoardProviderRecord]],
    board_keys: set[str],
) -> list[dict[str, Any]]:
    boards_by_key = {board.key: board for board in boards}
    gaps: list[dict[str, Any]] = []
    for board_key in sorted(board_keys):
        board = boards_by_key[board_key]
        gaps.append(
            {
                "board": board.key,
                "source": board.source_key,
                "providers": sorted(
                    {route.provider_id for route in routes_by_board.get(board_key, [])}
                ),
            }
        )
    return gaps


def _data_quality(jobs: list[JobRecord]) -> dict[str, Any]:
    checks = {
        "postingUrl": lambda job: bool(job.posting_url),
        "applyUrl": lambda job: bool(job.apply_url),
        "locations": lambda job: bool(job.locations),
        "department": lambda job: bool(job.department),
        "description": lambda job: bool(job.description or job.description_html),
        "compensationSalary": _has_compensation_or_salary,
        "remote": lambda job: bool(job.remote),
        "employmentType": _has_employment_type,
    }
    completeness: dict[str, dict[str, int | float]] = {}
    missing: dict[str, int] = {}
    total = len(jobs)
    for key, check in checks.items():
        present = sum(1 for job in jobs if check(job))
        metric = CoverageMetric(present=present, missing=total - present, total=total)
        completeness[key] = metric.as_dict()
        missing[key] = metric.missing
    return {"totalJobs": total, "missing": missing, "completeness": completeness}


def _has_compensation_or_salary(job: JobRecord) -> bool:
    return bool(
        job.compensation
        or job.salary
        or job.salary_min is not None
        or job.salary_max is not None
        or job.salary_currency
    )


def _has_employment_type(job: JobRecord) -> bool:
    return bool(
        job.employment_type or (job.job_description and job.job_description.type)
    )


def _count_jobs_by_source(
    jobs: list[JobRecord], boards_by_key: dict[str, BoardRecord]
) -> dict[str, int]:
    return _count_by(
        board.source_key
        for job in jobs
        if (board := boards_by_key.get(job.board_key)) is not None
    )


def _count_by(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
