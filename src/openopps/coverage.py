from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
    utc_now,
)
from openopps.providers.registry import provider_registry
from openopps.route_registry import select_routes_from_records
from openopps.route_select import normalize_provider_filter, route_ready
from openopps.storage import OpenOppsStore


EXAMPLE_LIMIT = 5
BASELINE_JOB_PROVIDER_IDS = frozenset({"ashbyhq", "greenhouse", "lever", "workday"})
ADOPTED_V01_PROVIDER_IDS = frozenset(
    {
        "ashbyhq",
        "bamboohr",
        "greenhouse",
        "lever",
        "rippling",
        "teamtailor",
        "workable",
        "workday",
        "wpjobmanager",
    }
)
AUDIT_PROVIDER_TARGETS = (
    "smartrecruiters",
    "workable",
    "recruitee",
    "teamtailor",
    "bamboohr",
    "rippling",
    "wpjobmanager",
    "icims",
    "jobvite",
    "jazzhr",
)
ADOPTED_PROVIDER_RATIONALES = {
    "workable": "Adopted for v0.1 using Workable's public no-auth account jobs endpoint.",
    "teamtailor": "Adopted for v0.1 using Teamtailor's public jobs RSS feed.",
    "bamboohr": "Adopted for v0.1 using BambooHR's public careers board JSON endpoints only.",
    "rippling": "Adopted for v0.1 using Rippling's public ATS board JSON endpoints.",
    "wpjobmanager": "Adopted for v0.1 only when an explicit WP Job Manager REST or AJAX endpoint is available.",
}
DO_NOT_ADOPT_RATIONALES = {
    "smartrecruiters": "Keep detect-only until a stable public hosted-board JSON route is proven across multiple boards.",
    "recruitee": "Keep detect-only until hosted-board payload stability and route token extraction are validated.",
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


@dataclass(frozen=True)
class SourceYieldReport:
    snapshot: dict[str, Any]
    totals: dict[str, Any]
    sources: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "totals": self.totals,
            "sources": self.sources,
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

    job_summary = store.coverage_job_summary(
        provider_id=provider_filter,
        board_keys=boards_by_key if source_key is not None else None,
    )
    selection = select_routes_from_records(
        boards=boards,
        routes=[
            route for route in routes if route.support_level == ProviderSupport.JOBS
        ],
    )
    jobs_by_board = _string_int_dict(job_summary["byBoard"])
    jobs_by_board_provider = _tuple_int_dict(job_summary["byBoardProvider"])
    routes_by_board = _routes_by_board(boards, routes)
    board_keys_with_provider_hints = set(routes_by_board)
    board_keys_with_job_capable_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(route.support_level == ProviderSupport.JOBS for route in board_routes)
    }
    board_keys_with_adopted_v01_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(
            route.support_level == ProviderSupport.JOBS
            and route.provider_id in ADOPTED_V01_PROVIDER_IDS
            for route in board_routes
        )
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
            "byProvider": _count_by(source.provider_id for source in sources),
            "yield": build_source_yield_report(store, source_key=source_key).totals,
        },
        boards={
            "total": len(boards),
            "bySource": _count_by(board.source_key for board in boards),
            "withProviderHints": len(board_keys_with_provider_hints),
            "withJobCapableProviderHints": len(board_keys_with_job_capable_hints),
            "withBaselineJobCapableProviderHints": len(
                board_keys_with_baseline_job_capable_hints
            ),
            "withAdoptedV01ProviderHints": len(board_keys_with_adopted_v01_hints),
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
            "total": int(job_summary["total"]),
            "byProvider": _string_int_dict(job_summary["byProvider"]),
            "bySource": _count_jobs_by_source(jobs_by_board, boards_by_key),
            "byBoard": jobs_by_board,
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
        data_quality=job_summary["dataQuality"],
    )


def build_source_yield_report(
    store: OpenOppsStore,
    *,
    source_key: str | None = None,
) -> SourceYieldReport:
    """Build an offline source-yield report from persisted sources, boards, routes, and jobs."""

    sources = [
        source
        for source in store.list_sources()
        if source_key is None or source.key == source_key
    ]
    selected_source_keys = {source.key for source in sources}
    boards = store.list_boards(with_providers=False)
    routes = store.list_board_providers()
    job_summary = store.coverage_job_summary(status="open")
    jobs_by_board_provider = _tuple_int_dict(job_summary["byBoardProvider"])

    boards_by_source: dict[str, list[BoardRecord]] = {
        key: [] for key in selected_source_keys
    }
    for board in boards:
        for key in _board_source_keys(board) & selected_source_keys:
            boards_by_source.setdefault(key, []).append(board)

    routes_by_source: dict[str, list[BoardProviderRecord]] = {
        key: [] for key in selected_source_keys
    }
    for route in routes:
        if route.source_key in selected_source_keys:
            routes_by_source.setdefault(route.source_key, []).append(route)

    board_source_keys = {board.key: _board_source_keys(board) for board in boards}
    jobs_by_source_board_provider: dict[str, dict[tuple[str, str], int]] = {
        key: {} for key in selected_source_keys
    }
    for (board_key, provider_id), count in jobs_by_board_provider.items():
        for key in board_source_keys.get(board_key, set()) & selected_source_keys:
            jobs_by_source_board_provider.setdefault(key, {})[
                (board_key, provider_id)
            ] = count

    source_items = [
        _source_yield_item(
            source,
            boards_by_source.get(source.key, []),
            routes_by_source.get(source.key, []),
            jobs_by_source_board_provider.get(source.key, {}),
        )
        for source in sorted(sources, key=lambda item: item.key)
    ]
    totals = _source_yield_totals(source_items, boards, selected_source_keys)
    return SourceYieldReport(
        snapshot={
            "generatedAt": utc_now().isoformat(),
            "scope": {"source": source_key},
            "sourceCount": len(sources),
            "snapshotKind": "persisted-scope",
            "note": (
                "Offline source-yield metrics are measured from persisted SQLite records; "
                "run source sync, route probing, and job sync before comparing source families."
            ),
        },
        totals=totals,
        sources=source_items,
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
                "rationale": ADOPTED_PROVIDER_RATIONALES.get(provider_id)
                or DO_NOT_ADOPT_RATIONALES[provider_id],
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


def _source_yield_item(
    source: SourceRecord,
    boards: list[BoardRecord],
    routes: list[BoardProviderRecord],
    jobs_by_board_provider: dict[tuple[str, str], int],
) -> dict[str, Any]:
    company_candidates = len(boards)
    canonical_boards = len({board.key for board in boards})
    provider_hints = len(routes)
    job_capable_routes = [
        route for route in routes if route.support_level == ProviderSupport.JOBS
    ]
    route_ready_count = sum(1 for route in job_capable_routes if route_ready(route))
    active_job_routes = sum(1 for count in jobs_by_board_provider.values() if count > 0)
    unique_active_boards = len(
        {
            board_key
            for (board_key, _provider_id), count in jobs_by_board_provider.items()
            if count > 0
        }
    )
    duplicate_board_rate = _safe_ratio(
        max(company_candidates - canonical_boards, 0), company_candidates
    )
    yield_score = _safe_ratio(unique_active_boards, company_candidates)
    return {
        "source": source.key,
        "providerId": source.provider_id,
        "taxonomy": _source_taxonomy(source.raw_metadata),
        "companyCandidates": company_candidates,
        "canonicalBoards": canonical_boards,
        "providerHints": provider_hints,
        "jobCapableRoutes": len(job_capable_routes),
        "routeReady": route_ready_count,
        "activeJobRoutes": active_job_routes,
        "duplicateBoardRate": duplicate_board_rate,
        "uniqueActiveBoardsAdded": unique_active_boards,
        "yieldScore": yield_score,
    }


def _source_yield_totals(
    source_items: list[dict[str, Any]],
    boards: list[BoardRecord],
    selected_source_keys: set[str],
) -> dict[str, Any]:
    company_candidates = sum(int(item["companyCandidates"]) for item in source_items)
    canonical_board_keys = {
        board.key
        for board in boards
        if _board_source_keys(board) & selected_source_keys
    }
    unique_active_boards = sum(
        int(item["uniqueActiveBoardsAdded"]) for item in source_items
    )
    return {
        "companyCandidates": company_candidates,
        "canonicalBoards": len(canonical_board_keys),
        "providerHints": sum(int(item["providerHints"]) for item in source_items),
        "jobCapableRoutes": sum(int(item["jobCapableRoutes"]) for item in source_items),
        "routeReady": sum(int(item["routeReady"]) for item in source_items),
        "activeJobRoutes": sum(int(item["activeJobRoutes"]) for item in source_items),
        "duplicateBoardRate": _safe_ratio(
            max(company_candidates - len(canonical_board_keys), 0), company_candidates
        ),
        "uniqueActiveBoardsAdded": unique_active_boards,
        "yieldScore": _safe_ratio(unique_active_boards, company_candidates),
        "byProviderType": _count_by(
            str(item["taxonomy"].get("providerType") or "unknown")
            for item in source_items
        ),
        "byAccessType": _count_by(
            str(item["taxonomy"].get("accessType") or "unknown")
            for item in source_items
        ),
    }


def _source_taxonomy(raw_metadata: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "providerType",
        "coverageMode",
        "accessType",
        "licenseStatus",
        "refreshCadence",
        "sourceYear",
        "sourceCategory",
        "sourceAttribution",
        "inclusionReason",
    }
    return {key: raw_metadata[key] for key in sorted(keys) if key in raw_metadata}


def _board_source_keys(board: BoardRecord) -> set[str]:
    keys = {board.source_key, *board.source_keys, *board.source_board_keys.keys()}
    return {key for key in keys if key}


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


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
    jobs_by_board: dict[str, int], boards_by_key: dict[str, BoardRecord]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for board_key, count in jobs_by_board.items():
        board = boards_by_key.get(board_key)
        if board is None:
            continue
        counts[board.source_key] = counts.get(board.source_key, 0) + count
    return dict(sorted(counts.items()))


def _string_int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return dict(sorted((str(key), int(count)) for key, count in value.items()))


def _tuple_int_dict(value: object) -> dict[tuple[str, str], int]:
    if not isinstance(value, dict):
        return {}
    output: dict[tuple[str, str], int] = {}
    for key, count in value.items():
        if isinstance(key, tuple) and len(key) == 2:
            output[(str(key[0]), str(key[1]))] = int(count)
    return output


def _count_by(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
