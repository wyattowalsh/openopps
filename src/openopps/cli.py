from __future__ import annotations

import asyncio
import json
import runpy
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from click import ClickException, Context, get_current_context
from loguru import logger
from pydantic import ValidationError
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from typer.core import TyperGroup

from openopps import __version__
from openopps.cache import HttpCache
from openopps.coverage import (
    build_coverage_report,
    build_provider_audit_report,
    build_source_yield_report,
)
from openopps.enrichment import enrich_metadata
from openopps.export import export_records
from openopps.health import check_provider_health
from openopps.http import build_async_client
from openopps.ingest import all_board_sources, sync_boards, sync_jobs, sync_sources
from openopps.metrics import ProgressReporter, ProgressUpdate, SyncMetrics
from openopps.intro import play_intro, render_intro_frame
from openopps.migrations import DatabaseSchemaError
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ExportFormat,
    ProviderSupport,
    SourceRecord,
    validate_provider_host,
    validate_public_https_url,
    utc_now,
)
from openopps.plugins import PluginContext, load_plugins
from openopps.providers.base import ProviderDefinition
from openopps.providers.registry import provider_registry
from openopps.providers.sources import build_source_adapter
from openopps.route_registry import BoardRouteRegistry
from openopps.route_probe import probe_routes
from openopps.route_select import normalize_provider_filter
from openopps.settings import OpenOppsSettings, format_settings_validation_error
from openopps.source_resolution import (
    resolve_effective_source,
    resolve_effective_sources,
)
from openopps.storage import OpenOppsStore
from openopps.storage import BoardFilters, JobFilters
from openopps.utils import slugify, stable_id


console = Console()
EXAMPLES_DATA_SCRIPT = Path("examples") / "examples.py"
PANEL_OUTPUT = "Output"
PANEL_SCOPE = "Scope filters"
PANEL_ROUTE = "Route metadata"
PANEL_SYNC = "Sync controls"
PANEL_DIAGNOSTICS = "Diagnostics"
PANEL_STORAGE = "Storage"
PANEL_WORKFLOW = "Everyday workflow"
PANEL_OPERATIONS = "Operational surfaces"
PANEL_ADMIN = "Advanced admin"

JSON_HELP = "Emit machine-readable JSON for scripting and automation."
PROVIDER_FILTER_HELP = (
    "Provider id to filter to. Use 'any' or 'all' to remove the provider filter."
)
SOURCE_FILTER_HELP = "Limit results to one aggregate source key, such as a16z or yc."
BOARD_FILTER_HELP = "Limit results to one board key."
LIMIT_HELP = "Maximum records to return after filters are applied."
EXPORT_FORMAT_HELP = "Export file format: jsonl, csv, parquet, or sqlite."
EXPORT_OUTPUT_FILE_HELP = "Destination file path to create or replace."
SYNC_OUTPUT_FILE_HELP = "Append synced JSONL records to this file path."
BOARD_HAS_JOBS_HELP = (
    "Only include boards with a source job hint, provider job hint, or synced job."
)
MARKET_FILTER_HELP = "Case-insensitive substring match against board market tags."
LOCATION_FILTER_HELP = "Case-insensitive substring match against normalized locations."
DOMAIN_FILTER_HELP = "Case-insensitive substring match against company domains."
DEPARTMENT_FILTER_HELP = "Case-insensitive substring match against departments."
TEAM_FILTER_HELP = "Case-insensitive substring match against teams."

WORKPLACE_FILTER_HELP = "Case-insensitive substring match, such as Remote or Onsite."
REMOTE_FILTER_HELP = "Case-insensitive exact remote level: Full, Hybrid, or None."
EMPLOYMENT_TYPE_FILTER_HELP = (
    "Case-insensitive substring match, such as full-time or contract."
)
SALARY_MIN_FILTER_HELP = (
    "Keep jobs whose normalized salary range overlaps this lower bound."
)
SALARY_MAX_FILTER_HELP = (
    "Keep jobs whose normalized salary range overlaps this upper bound."
)
STRICT_SYNC_HELP = (
    "Exit with a non-zero status when sync skips records or reports provider errors."
)
SKILL_FILTER_HELP = "Match normalized skill names, levels, or keywords."
QUERY_FILTER_HELP = "Search normalized title, company, and plain-text description."
POSTED_AFTER_FILTER_HELP = "Inclusive YYYY-MM-DD lower bound for normalized posted_at."
POSTED_BEFORE_FILTER_HELP = "Inclusive YYYY-MM-DD upper bound for normalized posted_at."
JOB_STATUS_FILTER_HELP = "Job lifecycle filter: open, closed, or all. Defaults to open."

BOARD_OPTION_FLAGS = ("--board", "-b", "-B")
FORMAT_OPTION_FLAGS = ("--format", "-f", "-F")
JSON_OPTION_FLAGS = ("--json", "-j", "-J")
LIMIT_OPTION_FLAGS = ("--limit", "-n", "-N")
METRICS_JSON_OPTION_FLAGS = ("--metrics-json", "-m", "-M")
OUTPUT_OPTION_FLAGS = ("--output", "-o", "-O")
PROVIDER_OPTION_FLAGS = ("--provider", "-p", "-P")
REFRESH_CACHE_OPTION_FLAGS = ("--refresh-cache", "-r", "-R")
SOURCE_OPTION_FLAGS = ("--source", "-s", "-S")
VERBOSE_OPTION_FLAGS = ("--verbose", "-v", "-V")
SETTINGS_CONTEXT_KEY = "openopps_settings"


def _example_data_script_path() -> Path:
    module_path = Path(__file__).resolve()
    candidates = (
        module_path.parents[2] / EXAMPLES_DATA_SCRIPT,
        module_path.parents[1] / EXAMPLES_DATA_SCRIPT,
        Path.cwd() / EXAMPLES_DATA_SCRIPT,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ClickException(f"Example dataset script not found at {EXAMPLES_DATA_SCRIPT}.")


def _load_example_dataset_builder() -> Callable[..., Any]:
    namespace = runpy.run_path(str(_example_data_script_path()))
    builder = namespace.get("build_example_dataset")
    if not callable(builder):
        raise ClickException(
            f"Example dataset script must define build_example_dataset: "
            f"{EXAMPLES_DATA_SCRIPT}"
        )
    return cast("Callable[..., Any]", builder)


class OpenOppsRootGroup(TyperGroup):
    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        # Handle --version before command validation so bare
        # `openopps --version` does not require a subcommand (exit 2).
        if "--version" in args:
            typer.echo(f"openopps {__version__}")
            ctx.exit()
        show_intro = True
        for arg in args:
            if arg == "--no-intro":
                show_intro = False
            elif arg == "--intro":
                show_intro = True
        ctx.meta["openopps_show_help_intro"] = show_intro
        return super().parse_args(ctx, args)

    def get_help(self, ctx: Context) -> str:
        if ctx.parent is None and ctx.meta.get("openopps_show_help_intro", True):
            Console(
                color_system=None,
                force_terminal=False,
                width=ctx.terminal_width or console.width,
            ).print(render_intro_frame(0, "opening opportunity portal"))
        return super().get_help(ctx)

    def invoke(self, ctx: Context) -> Any:
        try:
            return super().invoke(ctx)
        except DatabaseSchemaError as exc:
            raise ClickException(str(exc)) from exc


app = typer.Typer(
    cls=OpenOppsRootGroup,
    help=(
        "[bold]OpenOpps[/bold] is a local-first route ledger for public hiring "
        "boards. Discover source catalogs, resolve executable provider routes, "
        "sync normalized jobs, then inspect coverage and export clean data."
    ),
    epilog=(
        "[dim]Start here:[/dim] "
        "[bold]openopps status[/bold] to inspect local state, "
        "[bold]openopps sync a16z --metrics-json[/bold] to populate one source, "
        "[bold]openopps providers coverage --source a16z --provider any --json[/bold] "
        "to inspect route readiness, and "
        "[bold]openopps jobs list --remote Full --skill Python --json[/bold] "
        "to query normalized jobs. "
        "[dim]Automation:[/dim] use [bold]--json[/bold] or "
        "[bold]--metrics-json[/bold] for parseable stdout."
    ),
)
sources_app = typer.Typer(
    help="Discover, test, and sync aggregate company catalogs such as a16z, YC, SEC, indexes, and Getro boards."
)
boards_app = typer.Typer(
    help="Inspect discovered company boards, enrich metadata, resolve routes, and export board records."
)
jobs_app = typer.Typer(
    help="Sync, filter, inspect history for, and export normalized public job postings."
)
providers_app = typer.Typer(
    help="Inspect persisted route readiness, live health samples, coverage gaps, and adoption evidence."
)
plugins_app = typer.Typer(
    help="Inspect trusted plugin entry points, loaded capabilities, conflicts, and failures."
)
cache_app = typer.Typer(
    help="Inspect the local SQLite request cache used by shared HTTP paths."
)
examples_app = typer.Typer(help="Seed deterministic synthetic example data for demos.")
admin_app = typer.Typer(
    help="Advanced dry-run diagnostics, manual route edits, and local maintenance."
)
admin_sources_app = typer.Typer(
    help="Advanced source registration, adapter sampling, and offline yield reports."
)
admin_boards_app = typer.Typer(
    help="Advanced board registration, enrichment, and explicit route metadata."
)
admin_providers_app = typer.Typer(
    help="Advanced provider detection, dry-run route probing, and route-registry inspection."
)
admin_cache_app = typer.Typer(help="Advanced cache maintenance commands.")
admin_db_app = typer.Typer(
    help="Initialize, inspect, and maintain the local SQLite ledger."
)

app.add_typer(sources_app, name="sources", rich_help_panel=PANEL_WORKFLOW)
app.add_typer(boards_app, name="boards", rich_help_panel=PANEL_WORKFLOW)
app.add_typer(jobs_app, name="jobs", rich_help_panel=PANEL_WORKFLOW)
app.add_typer(providers_app, name="providers", rich_help_panel=PANEL_WORKFLOW)
app.add_typer(cache_app, name="cache", rich_help_panel=PANEL_OPERATIONS)
app.add_typer(plugins_app, name="plugins", rich_help_panel=PANEL_OPERATIONS)
app.add_typer(examples_app, name="examples", rich_help_panel=PANEL_OPERATIONS)
app.add_typer(admin_app, name="admin", rich_help_panel=PANEL_ADMIN)
admin_app.add_typer(admin_sources_app, name="sources")
admin_app.add_typer(admin_boards_app, name="boards")
admin_app.add_typer(admin_providers_app, name="providers")
admin_app.add_typer(admin_cache_app, name="cache")
admin_app.add_typer(admin_db_app, name="db")


@app.callback()
def main(
    intro: Annotated[
        bool,
        typer.Option(
            "--intro/--no-intro",
            help="Show the startup portal animation when the terminal is interactive.",
            rich_help_panel="Experience",
        ),
    ] = True,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the OpenOpps version and exit.",
            is_eager=True,
            rich_help_panel="Experience",
        ),
    ] = False,
) -> None:
    if version:
        typer.echo(f"openopps {__version__}")
        raise typer.Exit()
    play_intro(enabled=intro)


def _settings() -> OpenOppsSettings:
    ctx = get_current_context(silent=True)
    if ctx is not None:
        cached = ctx.meta.get(SETTINGS_CONTEXT_KEY)
        if isinstance(cached, OpenOppsSettings):
            return cached
    try:
        settings = OpenOppsSettings()
    except ValidationError as exc:
        raise ClickException(format_settings_validation_error(exc)) from exc
    if ctx is not None:
        ctx.meta[SETTINGS_CONTEXT_KEY] = settings
    return settings


def _store(settings: OpenOppsSettings | None = None) -> OpenOppsStore:
    return OpenOppsStore(settings or _settings())


def _cache(settings: OpenOppsSettings | None = None) -> HttpCache:
    settings = settings or _settings()
    if settings.sqlite_path is None:
        raise typer.BadParameter(
            "Cache commands require a local sqlite:/// OPENOPPS_DB_URL because "
            "OpenOpps stores HTTP cache records in the application SQLite database."
        )
    return HttpCache(settings.sqlite_path)


def _cache_status(settings: OpenOppsSettings) -> dict[str, Any]:
    if settings.sqlite_path is None:
        return {
            "path": None,
            "total": 0,
            "fresh": 0,
            "expired": 0,
            "staleOnErrorEligible": 0,
            "byNamespace": {},
        }
    return HttpCache(settings.sqlite_path).status()


def _settings_with_cache_refresh(refresh_cache: bool) -> OpenOppsSettings:
    settings = _settings()
    if not refresh_cache:
        return settings
    return settings.model_copy(update={"cache_refresh": True})


def _catalog_source(key: str) -> SourceRecord | None:
    return next((source for source in all_board_sources() if source.key == key), None)


def _effective_source(store: OpenOppsStore, key: str) -> SourceRecord | None:
    return resolve_effective_source(_catalog_source(key), store.get_source(key))


def _json(data: object) -> None:
    console.print_json(json.dumps(data, default=str))


def _export_metadata(entity: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity": entity,
        "filters": {key: value for key, value in filters.items() if value is not None},
        "generated_at": utc_now().isoformat(),
    }


def _metrics(
    metrics: SyncMetrics,
    metrics_json: bool,
    profile: bool,
    *,
    strict: bool = False,
) -> None:
    if metrics_json:
        _json(metrics.as_dict())
    else:
        data = metrics.as_dict()
        summary = (
            f"{data['name']} completed in {data['elapsedSeconds']:.2f}s "
            f"boards={data['boards']} jobs={data['jobs']} "
            f"jobsPersisted={data['jobsPersisted']}"
        )
        if profile:
            provider_error_count = sum(data["providerErrors"].values())
            summary = (
                f"{summary} jobSyncRuns={data['jobSyncRuns']} "
                f"jobsDeduped={data['jobsDeduped']} pages={data['pages']} "
                f"skipped={data['skipped']} "
                f"duplicateRoutesSkipped={data['duplicateRoutesSkipped']} "
                f"providerErrors={provider_error_count}"
            )
        console.print(summary)
        if metrics.skipped or metrics.provider_errors:
            Console(stderr=True).print(
                f"Warning: {metrics.name} completed with skipped={metrics.skipped} "
                f"provider_errors={metrics.provider_errors}. "
                "Re-run with --verbose for details."
            )
    if strict and (metrics.skipped or metrics.provider_errors):
        raise SystemExit(1)


def _run_sync_with_progress[T](
    label: str,
    run: Callable[[ProgressReporter], T],
    *,
    enabled: bool,
    verbose: bool = False,
) -> T:
    progress_console = Console(stderr=True)
    if not enabled or verbose or not progress_console.is_interactive:
        with _sync_logging(verbose):
            return run(_ignore_progress)

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(
            bar_width=18,
            complete_style="bold cyan",
            finished_style="bold green",
            pulse_style="bold magenta",
        ),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=progress_console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(label, completed=0, total=1)

        def report(update: ProgressUpdate) -> None:
            progress_kwargs: dict[str, Any] = {"description": update.message}
            if update.completed is not None:
                progress_kwargs["completed"] = update.completed
            if update.total is not None:
                progress_kwargs["total"] = update.total
            progress.update(task_id, **progress_kwargs)

        with _sync_logging(verbose):
            return run(report)


def _ignore_progress(_update: ProgressUpdate) -> None:
    return


def _combine_sync_metrics(name: str, *metrics: SyncMetrics) -> SyncMetrics:
    combined = SyncMetrics(name=name)
    for item in metrics:
        combined.pages += item.pages
        combined.boards += item.boards
        combined.board_providers += item.board_providers
        combined.jobs += item.jobs
        combined.jobs_persisted += item.jobs_persisted
        combined.job_sync_runs += item.job_sync_runs
        combined.jobs_deduped += item.jobs_deduped
        combined.skipped += item.skipped
        combined.duplicate_routes_skipped += item.duplicate_routes_skipped
        combined.retries += item.retries
        for provider_id, count in item.provider_errors.items():
            combined.provider_errors[provider_id] = (
                combined.provider_errors.get(provider_id, 0) + count
            )
        for provider_id, details in item.provider_error_details.items():
            combined_details = combined.provider_error_details.setdefault(
                provider_id, {}
            )
            for reason, count in details.items():
                combined_details[reason] = combined_details.get(reason, 0) + count
    if metrics:
        combined.started_at = min(item.started_at for item in metrics)
        combined.finished_at = max(
            item.finished_at or item.started_at for item in metrics
        )
        return combined
    return combined.finish()


@contextmanager
def _sync_logging(verbose: bool):
    if verbose:
        yield
        return
    logger.disable("openopps")
    try:
        yield
    finally:
        logger.enable("openopps")


def _table(title: str, columns: list[str], rows: list[list[object]]) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(str(value) if value is not None else "" for value in row))
    console.print(table)


def _status_payload() -> dict[str, Any]:
    settings = _settings()
    store = _store(settings)
    counts = store.status()
    readiness = _readiness_payload(store)
    coverage = _status_coverage_payload(store)
    issues = _status_issues(counts, readiness, coverage)
    return {
        "database": {
            "url": settings.db_url,
            "path": str(settings.sqlite_path) if settings.sqlite_path else None,
            "counts": counts,
        },
        "cache": _cache_status(settings),
        "plugins": _plugin_registry(settings).as_dict(),
        "readiness": readiness,
        "coverage": {
            "boards": coverage["boards"],
            "gaps": coverage["gaps"],
        },
        "issues": issues,
        "nextAction": _next_action(counts, readiness),
    }


def _readiness_payload(store: OpenOppsStore) -> dict[str, Any]:
    routes = store.list_board_providers()
    route_selection = BoardRouteRegistry(store).select(ready_only=True)
    return {
        "executableRoutes": len(route_selection.entries),
        "missingRouteMetadata": len(route_selection.missing_route_metadata),
        "duplicateRoutesSkipped": len(route_selection.duplicate_routes),
        "detectOnlyRoutes": sum(
            1 for route in routes if route.support_level == ProviderSupport.DETECT
        ),
        "unsupportedRoutes": sum(
            1 for route in routes if route.support_level == ProviderSupport.UNSUPPORTED
        ),
    }


def _status_coverage_payload(store: OpenOppsStore) -> dict[str, Any]:
    boards = store.list_boards(with_providers=False)
    routes = store.list_board_providers()
    routes_by_board: dict[str, list[BoardProviderRecord]] = {}
    for route in routes:
        routes_by_board.setdefault(route.board_key, []).append(route)

    board_keys_with_provider_hints = set(routes_by_board)
    board_keys_with_job_capable_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if any(route.support_level == ProviderSupport.JOBS for route in board_routes)
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
        if any(route.support_level != ProviderSupport.JOBS for route in board_routes)
    }
    board_keys_with_only_non_supported_hints = {
        board_key
        for board_key, board_routes in routes_by_board.items()
        if board_routes
        and all(route.support_level != ProviderSupport.JOBS for route in board_routes)
    }
    board_total = len(boards)
    non_supported_present = len(board_keys_with_non_supported_hints)
    return {
        "boards": {
            "total": board_total,
            "withProviderHints": len(board_keys_with_provider_hints),
            "withJobCapableProviderHints": len(board_keys_with_job_capable_hints),
            "withDetectOnlyProviderHints": len(board_keys_with_detect_only_hints),
            "withUnsupportedOrUnknownProviderHints": len(
                board_keys_with_unsupported_hints
            ),
            "withNonSupportedProviderHints": non_supported_present,
            "withOnlyNonSupportedProviderHints": len(
                board_keys_with_only_non_supported_hints
            ),
            "nonSupportedProviderCoverage": {
                "present": non_supported_present,
                "missing": board_total - non_supported_present,
                "total": board_total,
                "percentage": (
                    round((non_supported_present / board_total) * 100, 2)
                    if board_total
                    else 0.0
                ),
            },
        },
        "gaps": {
            "detectOnlyProviders": _status_provider_gaps(
                routes, support_level=ProviderSupport.DETECT
            ),
            "nonSupportedProviders": _status_provider_gaps(
                routes,
                support_level=None,
                exclude_support_level=ProviderSupport.JOBS,
            ),
        },
    }


def _status_provider_gaps(
    routes: list[BoardProviderRecord],
    *,
    support_level: ProviderSupport | None = None,
    exclude_support_level: ProviderSupport | None = None,
) -> list[dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for route in routes:
        if support_level is not None and route.support_level != support_level:
            continue
        if (
            exclude_support_level is not None
            and route.support_level == exclude_support_level
        ):
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
        if len(item["examples"]) < 5 and route.board_key not in item["examples"]:
            item["examples"].append(route.board_key)
    return [providers[key] for key in sorted(providers)]


def _plugin_registry(settings: OpenOppsSettings | None = None):
    settings = settings or _settings()
    return load_plugins(context=PluginContext(settings=settings))


def _next_action(counts: dict[str, int], readiness: dict[str, Any]) -> str:
    if counts["sources"] == 0:
        return (
            "Run `openopps sources list` to inspect the source catalog, then sync one."
        )
    if counts["boards"] == 0:
        return "Run `openopps sources sync <source>` to discover boards."
    if counts["boardProviders"] == 0:
        return "Run provider coverage or route probing to inspect provider readiness."
    if readiness["missingRouteMetadata"] > 0 and readiness["executableRoutes"] == 0:
        return (
            "Run `openopps boards sync` or attach route metadata before syncing jobs."
        )
    if counts["jobs"] == 0:
        return "Run `openopps jobs sync` after routes are ready."
    return "Run `openopps jobs list` or export filtered results."


def _status_issues(
    counts: dict[str, int], readiness: dict[str, Any], coverage: dict[str, Any]
) -> list[str]:
    issues: list[str] = []
    if counts["sources"] == 0:
        issues.append("no_sources")
    if counts["boards"] == 0:
        issues.append("no_boards")
    if readiness["missingRouteMetadata"]:
        issues.append("missing_route_metadata")
    if readiness["detectOnlyRoutes"]:
        issues.append("detect_only_routes")
    if coverage["boards"].get("withOnlyNonSupportedProviderHints"):
        issues.append("only_non_supported_provider_hints")
    return issues


@app.command(
    "sync",
    help="Run the everyday sources, boards, and jobs sync workflow in order.",
    rich_help_panel=PANEL_WORKFLOW,
)
def sync_all(
    source_key: Annotated[
        str | None,
        typer.Argument(
            help="Optional source key; omit to sync every configured source."
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help="Optional JSONL path for jobs synced during the jobs stage.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = None,
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            min=1,
            max=500,
            help="Maximum upstream page size for source adapters that support paging.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = 100,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            min=1,
            max=50,
            help="Maximum route candidate slugs or sites to try per board.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = 12,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS,
            min=1,
            help="Maximum boards/routes to enrich and probe during the boards stage.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    metrics_json: Annotated[
        bool,
        typer.Option(
            *METRICS_JSON_OPTION_FLAGS,
            help="Print combined sync metrics as JSON.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    profile: Annotated[
        bool,
        typer.Option(
            "--profile",
            help="Print an extended human-readable sync summary with page and error counts.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help=STRICT_SYNC_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            *REFRESH_CACHE_OPTION_FLAGS,
            help="Bypass cache reads and update cache records from fresh responses.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            *VERBOSE_OPTION_FLAGS,
            help="Show detailed sync warnings instead of brief progress messages only.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
) -> None:
    settings = _settings_with_cache_refresh(refresh_cache)
    store = OpenOppsStore(settings)
    provider_filter = normalize_provider_filter(provider)

    def run(report: ProgressReporter) -> SyncMetrics:
        async def _run() -> SyncMetrics:
            source_metrics = await sync_sources(
                settings=settings,
                store=store,
                source_key=source_key,
                page_size=page_size,
                verbose=verbose,
                report=report,
            )
            board_metrics = await sync_boards(
                settings=settings,
                store=store,
                source_key=source_key,
                board_key=board,
                provider_id=provider_filter,
                max_candidates=max_candidates,
                limit=limit,
                verbose=verbose,
                report=report,
            )
            job_metrics = await sync_jobs(
                settings=settings,
                store=store,
                source_key=source_key,
                board_key=board,
                provider_id=provider_filter,
                output=output,
                freshness_seconds=settings.job_route_freshness_seconds,
                limit=settings.job_route_limit,
                verbose=verbose,
                report=report,
            )
            return _combine_sync_metrics(
                "sync", source_metrics, board_metrics, job_metrics
            )

        return asyncio.run(_run())

    try:
        metrics = _run_sync_with_progress(
            "Syncing OpenOpps",
            run,
            enabled=not metrics_json,
            verbose=verbose,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _metrics(metrics, metrics_json, profile, strict=strict)


def _board_filters(
    *,
    source: str | None = None,
    provider: str | None = None,
    market: str | None = None,
    location: str | None = None,
    domain: str | None = None,
    has_jobs: bool = False,
    min_staff: int | None = None,
    max_staff: int | None = None,
    limit: int | None = None,
) -> BoardFilters:
    return BoardFilters(
        source_key=source,
        provider_id=normalize_provider_filter(provider),
        market=market,
        location=location,
        domain=domain,
        has_jobs=has_jobs,
        min_staff=min_staff,
        max_staff=max_staff,
        limit=limit,
    )


def _job_filters(
    *,
    source: str | None = None,
    board: str | None = None,
    provider: str | None = None,
    location: str | None = None,
    department: str | None = None,
    team: str | None = None,
    workplace_type: str | None = None,
    remote: str | None = None,
    employment_type: str | None = None,
    salary_min: float | None = None,
    salary_max: float | None = None,
    skill: str | None = None,
    query: str | None = None,
    posted_after: str | None = None,
    posted_before: str | None = None,
    status: str = "open",
    limit: int | None = None,
) -> JobFilters:
    if status not in {"open", "closed", "all"}:
        raise typer.BadParameter("--status must be open, closed, or all")
    return JobFilters(
        source_key=source,
        board_key=board,
        provider_id=normalize_provider_filter(provider),
        location=location,
        department=department,
        team=team,
        workplace_type=workplace_type,
        remote=remote,
        employment_type=employment_type,
        salary_min=salary_min,
        salary_max=salary_max,
        skill=skill,
        query=query,
        posted_after=posted_after,
        posted_before=posted_before,
        status=status,
        limit=limit,
    )


def _render_status_human(data: dict[str, Any]) -> None:
    counts = data["database"]["counts"]
    cache = data["cache"]
    plugins = data["plugins"]
    readiness = data["readiness"]
    _table(
        "OpenOpps Status",
        [
            "sources",
            "boards",
            "routes",
            "jobs",
            "cache_records",
            "plugins",
            "failed_plugins",
            "executable_routes",
            "missing_route_metadata",
        ],
        [
            [
                counts["sources"],
                counts["boards"],
                counts["boardProviders"],
                counts["jobs"],
                cache["total"],
                plugins["loaded"],
                plugins["failed"],
                readiness["executableRoutes"],
                readiness["missingRouteMetadata"],
            ]
        ],
    )
    if data["issues"]:
        console.print(f"Issues: {', '.join(data['issues'])}")
    console.print(f"Next action: {data['nextAction']}")


@app.command(
    "status",
    help="Show local OpenOpps database, cache, plugin, and next-action status.",
    rich_help_panel=PANEL_OPERATIONS,
)
def status(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    data = _status_payload()
    if json_output:
        _json(data)
        return
    _render_status_human(data)


@app.command(
    "doctor",
    help=(
        "Show the same local status view as `openopps status` plus a short "
        "first-time setup checklist."
    ),
    rich_help_panel=PANEL_OPERATIONS,
)
def doctor(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    data = _status_payload()
    if json_output:
        _json(data)
        return
    _render_status_human(data)
    console.print(
        "Setup checklist: set OPENOPPS_DB_URL, run `openopps sources sync <source>`, "
        "then `openopps boards sync` and `openopps jobs sync`."
    )


@plugins_app.command("list", help="List installed OpenOpps plugins and load status.")
def plugins_list(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    data = _plugin_registry().as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "OpenOpps Plugins",
        [
            "entry_point",
            "plugin",
            "version",
            "loaded",
            "capabilities",
            "warnings",
            "error",
        ],
        [
            [
                plugin["entryPoint"],
                (plugin["metadata"] or {}).get("name", ""),
                (plugin["metadata"] or {}).get("version", ""),
                plugin["loaded"],
                len(plugin["capabilities"]),
                ", ".join(plugin.get("warnings") or []),
                plugin["error"] or "",
            ]
            for plugin in data["plugins"]
        ],
    )


@cache_app.command("status", help="Show local cache record count and namespaces.")
def cache_status(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    data = _cache_status(_settings())
    if json_output:
        _json(data)
        return
    _table(
        "OpenOpps Cache",
        ["database", "records", "fresh", "expired", "stale_on_error", "namespaces"],
        [
            [
                data["path"],
                data["total"],
                data["fresh"],
                data["expired"],
                data["staleOnErrorEligible"],
                len(data["byNamespace"]),
            ]
        ],
    )


@admin_cache_app.command("purge", help="Delete local cache records.")
def cache_purge(
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", help="Limit purge to one cache namespace."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    deleted = _cache().purge(namespace=namespace)
    data = {"deleted": deleted, "namespace": namespace}
    if json_output:
        _json(data)
        return
    console.print(f"Deleted {deleted} cache record(s).")


@examples_app.command(
    "seed", help="Seed deterministic synthetic example data into the local database."
)
def examples_seed(
    seed: Annotated[
        int, typer.Option("--seed", help="Deterministic Faker seed.")
    ] = 1001,
    boards: Annotated[
        int, typer.Option("--boards", min=1, help="Number of synthetic boards.")
    ] = 4,
    jobs_per_board: Annotated[
        int,
        typer.Option("--jobs-per-board", min=0, help="Jobs per job-capable board."),
    ] = 2,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    build_example_dataset = _load_example_dataset_builder()
    dataset = build_example_dataset(
        seed=seed, board_count=boards, jobs_per_board=jobs_per_board
    )
    settings = _settings()
    store = _store(settings)
    for source in dataset.sources:
        store.upsert_source(source)
    store.upsert_boards(dataset.boards)
    store.upsert_board_providers(dataset.routes)
    store.upsert_jobs(dataset.jobs)
    cache = _cache(settings)
    for record in dataset.cache_records:
        cache.put_json(
            "get",
            record.url,
            record.payload,
            namespace=record.namespace,
            status_code=record.status_code,
            ttl_seconds=86_400,
            now=datetime.fromisoformat(record.fetched_at),
        )
    data = {
        "sources": len(dataset.sources),
        "boards": len(dataset.boards),
        "routes": len(dataset.routes),
        "jobs": len(dataset.jobs),
        "cacheRecords": len(dataset.cache_records),
        "plugins": len(dataset.plugins),
        "seed": seed,
    }
    if json_output:
        _json(data)
        return
    console.print(
        f"Seeded {data['boards']} boards, {data['routes']} routes, "
        f"{data['jobs']} jobs, and {data['cacheRecords']} cache records."
    )


@admin_sources_app.command(
    "add", help="Register a custom source catalog in the local OpenOpps ledger."
)
def sources_add(
    key: Annotated[str, typer.Argument(help="Stable source key, for example a16z.")],
    url: Annotated[str, typer.Option("--url", help="Public source catalog URL.")],
    provider: Annotated[
        str,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help="Source adapter id used to parse the catalog.",
        ),
    ] = "consider_a16z",
) -> None:
    try:
        validate_public_https_url(url, allow_manual=True)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    store = _store()
    store.upsert_source(SourceRecord(key=key, url=url, provider_id=provider))
    console.print(f"Added source {key}")


@sources_app.command(
    "list", help="List configured sources, falling back to the source catalog."
)
def sources_list(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    settings = _settings()
    stored_records: list[SourceRecord] = []
    if not settings.sqlite_path or settings.sqlite_path.exists():
        stored_records = OpenOppsStore(settings).list_sources()
    records = resolve_effective_sources(all_board_sources(), stored_records)
    if json_output:
        _json([record.model_dump(mode="json") for record in records])
        return
    _table(
        "Sources",
        ["key", "provider", "url"],
        [[record.key, record.provider_id, record.url] for record in records],
    )


@sources_app.command("show", help="Show one source record as JSON.")
def sources_show(
    key: Annotated[str, typer.Argument(help="Source key to inspect, such as a16z.")],
) -> None:
    record = _effective_source(_store(), key)
    if not record:
        raise typer.BadParameter(f"Unknown source: {key}")
    _json(record.model_dump(mode="json"))


@admin_sources_app.command(
    "test", help="Sample a source adapter without writing boards to storage."
)
def sources_test(
    key: Annotated[str, typer.Argument(help="Source key to sample.")] = "a16z",
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            min=1,
            max=200,
            help="Maximum source page size to request during the sample.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = 5,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            *REFRESH_CACHE_OPTION_FLAGS,
            help="Bypass cache reads and update cache records from fresh responses.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            *VERBOSE_OPTION_FLAGS,
            help="Show detailed source adapter warnings instead of compact progress only.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
) -> None:
    async def _run() -> None:
        settings = _settings_with_cache_refresh(refresh_cache)
        store = _store(settings)
        source = _effective_source(store, key)
        if not source:
            raise typer.BadParameter(f"Unknown source: {key}")
        adapter = build_source_adapter(source.provider_id, settings)
        if not adapter:
            raise typer.BadParameter(
                f"No source adapter for provider: {source.provider_id}"
            )
        async with build_async_client(settings) as client:
            async for boards, providers, meta in adapter.iter_boards(
                client, source, page_size=page_size
            ):
                _json(
                    {
                        "boards": len(boards),
                        "boardProviders": len(providers),
                        "meta": meta,
                    }
                )
                return

    with _sync_logging(verbose):
        asyncio.run(_run())


@admin_sources_app.command(
    "yield", help="Report offline source-yield metrics from persisted records."
)
def sources_yield(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    report = build_source_yield_report(_store(), source_key=source)
    data = report.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Source Yield Snapshot",
        [
            "sources",
            "company_candidates",
            "canonical_boards",
            "provider_hints",
            "job_routes",
            "active_job_routes",
            "yield_score",
        ],
        [
            [
                data["snapshot"]["sourceCount"],
                data["totals"]["companyCandidates"],
                data["totals"]["canonicalBoards"],
                data["totals"]["providerHints"],
                data["totals"]["jobCapableRoutes"],
                data["totals"]["activeJobRoutes"],
                f"{data['totals']['yieldScore']:.2%}",
            ]
        ],
    )
    _table(
        "Source Yield By Source",
        ["source", "type", "access", "companies", "routes", "active", "score"],
        [
            [
                item["source"],
                item["taxonomy"].get("providerType", "unknown"),
                item["taxonomy"].get("accessType", "unknown"),
                item["companyCandidates"],
                item["jobCapableRoutes"],
                item["activeJobRoutes"],
                f"{item['yieldScore']:.2%}",
            ]
            for item in data["sources"]
        ],
    )


@sources_app.command(
    "sync", help="Discover boards from one source or every configured source."
)
def sources_sync(
    source_key: Annotated[
        str | None,
        typer.Argument(
            help="Optional source key; omit to sync every configured source."
        ),
    ] = None,
    no_db: Annotated[
        bool,
        typer.Option(
            "--no-db",
            help="Skip SQLite writes and require --output for JSONL records.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help=SYNC_OUTPUT_FILE_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = None,
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            min=1,
            max=500,
            help="Maximum upstream page size for source adapters that support paging.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = 100,
    metrics_json: Annotated[
        bool,
        typer.Option(
            *METRICS_JSON_OPTION_FLAGS,
            help="Print sync metrics as JSON.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    profile: Annotated[
        bool,
        typer.Option(
            "--profile",
            help="Print an extended human-readable sync summary with page and error counts.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help=STRICT_SYNC_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            *REFRESH_CACHE_OPTION_FLAGS,
            help="Bypass cache reads and update cache records from fresh responses.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            *VERBOSE_OPTION_FLAGS,
            help="Show detailed sync warnings instead of brief progress messages only.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
) -> None:
    if no_db and output is None:
        raise typer.BadParameter("--output is required with --no-db")
    settings = _settings_with_cache_refresh(refresh_cache)
    store = None if no_db else _store(settings)
    try:
        metrics = _run_sync_with_progress(
            "Syncing sources",
            lambda report: asyncio.run(
                sync_sources(
                    settings=settings,
                    store=store,
                    source_key=source_key,
                    output=output,
                    page_size=page_size,
                    verbose=verbose,
                    report=report,
                )
            ),
            enabled=not metrics_json,
            verbose=verbose,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _metrics(metrics, metrics_json, profile, strict=strict)


@admin_boards_app.command(
    "add", help="Create a manual company board record for ad hoc route testing."
)
def boards_add(
    key: Annotated[str, typer.Argument(help="Stable board key to create.")],
    name: Annotated[str, typer.Option("--name", help="Firm or company name.")],
    source: Annotated[
        str,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = "manual",
    website_url: Annotated[
        str | None,
        typer.Option(
            "--website-url",
            help="Public careers or company website URL for provider detection.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            help="Company domain used by filters and route hints.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
) -> None:
    store = _store()
    if not store.get_source(source):
        store.upsert_source(
            SourceRecord(key=source, url="manual://source", provider_id="manual")
        )
    board = BoardRecord(
        key=slugify(key),
        source_key=source,
        remote_id=key,
        remote_slug=key,
        name=name,
        website_url=website_url,
        domain=domain,
        synced_at=utc_now(),
    )
    store.upsert_boards([board])
    console.print(f"Added board {board.key}")


@admin_boards_app.command(
    "add-provider", help="Attach explicit provider route metadata to a board."
)
def boards_add_provider(
    board_key: Annotated[str, typer.Argument(help="Board key to update.")],
    provider_id: Annotated[
        str, typer.Argument(help="Provider adapter id, such as greenhouse or ashbyhq.")
    ],
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            help="Public hosted board URL to detect or store for this provider.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="Provider board token or slug, when the adapter requires one.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Provider host for routes that need a careers-site hostname.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    tenant: Annotated[
        str | None,
        typer.Option(
            "--tenant",
            help="Provider tenant identifier for adapters that expose one.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    site: Annotated[
        str | None,
        typer.Option(
            "--site",
            help="Provider site identifier, such as a Workday CXS site name.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
) -> None:
    try:
        if url:
            validate_public_https_url(url)
        if provider_id == "workday" and host:
            host = validate_provider_host(host, "myworkdayjobs.com")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    settings = _settings()
    store = _store(settings)
    board = store.get_board(board_key)
    if not board:
        raise typer.BadParameter(f"Unknown board: {board_key}")
    registry = provider_registry(settings=settings)
    detected = (
        registry.detect_url(url, board_key=board.key, source_key=board.source_key)
        if url
        else None
    )
    support_level = registry.support_level(provider_id)
    record = detected or BoardProviderRecord(
        id=stable_id(board.source_key, board.key, provider_id),
        source_key=board.source_key,
        board_key=board.key,
        provider_id=provider_id,
        support_level=support_level,
        detected_at=utc_now(),
    )
    record = record.model_copy(
        update={
            "provider_id": provider_id,
            "support_level": support_level,
            "board_url": url or record.board_url,
            "token": token or record.token,
            "host": host or record.host,
            "tenant": tenant or record.tenant,
            "site": site or record.site,
        }
    )
    store.upsert_board_providers([record])
    _json(record.model_dump(mode="json"))


@boards_app.command(
    "list", help="List boards with source, provider, and company filters."
)
def boards_list(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    market: Annotated[
        str | None,
        typer.Option(
            "--market",
            help=MARKET_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            help=LOCATION_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            help=DOMAIN_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    has_jobs: Annotated[
        bool,
        typer.Option(
            "--has-jobs",
            help=BOARD_HAS_JOBS_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = False,
    min_staff: Annotated[
        int | None,
        typer.Option(
            "--min-staff",
            min=0,
            help="Only include boards with at least this staff count.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    max_staff: Annotated[
        int | None,
        typer.Option(
            "--max-staff",
            min=0,
            help="Only include boards with at most this staff count.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    boards = _store().list_boards(
        filters=_board_filters(
            source=source,
            provider=provider,
            market=market,
            location=location,
            domain=domain,
            has_jobs=has_jobs,
            min_staff=min_staff,
            max_staff=max_staff,
            limit=limit,
        )
    )
    if json_output:
        _json([board.model_dump(mode="json") for board in boards])
        return
    _table(
        "Boards",
        ["key", "source", "name", "providers", "jobs_hint"],
        [
            [
                board.key,
                board.source_key,
                board.name,
                ",".join(provider.provider_id for provider in board.providers),
                board.num_jobs_hint,
            ]
            for board in boards
        ],
    )


@boards_app.command("show", help="Show one board record as JSON, including routes.")
def boards_show(
    board_key: Annotated[str, typer.Argument(help="Board key to inspect.")],
) -> None:
    board = _store().get_board(board_key)
    if not board:
        raise typer.BadParameter(f"Unknown board: {board_key}")
    _json(board.model_dump(mode="json"))


@boards_app.command(
    "sync",
    help="Enrich discovered boards and resolve missing executable provider routes.",
)
def boards_sync(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            min=1,
            max=50,
            help="Maximum route candidate slugs or sites to try per board.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = 12,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    metrics_json: Annotated[
        bool,
        typer.Option(
            *METRICS_JSON_OPTION_FLAGS,
            help="Print sync metrics as JSON.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    profile: Annotated[
        bool,
        typer.Option(
            "--profile",
            help="Print an extended human-readable sync summary with page and error counts.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help=STRICT_SYNC_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            *REFRESH_CACHE_OPTION_FLAGS,
            help="Bypass cache reads and update cache records from fresh responses.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            *VERBOSE_OPTION_FLAGS,
            help="Show detailed sync warnings instead of brief progress messages only.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
) -> None:
    settings = _settings_with_cache_refresh(refresh_cache)
    metrics = _run_sync_with_progress(
        "Syncing boards",
        lambda report: asyncio.run(
            sync_boards(
                settings=settings,
                store=OpenOppsStore(settings),
                source_key=source,
                board_key=board,
                provider_id=normalize_provider_filter(provider),
                max_candidates=max_candidates,
                limit=limit,
                verbose=verbose,
                report=report,
            )
        ),
        enabled=not metrics_json,
        verbose=verbose,
    )
    _metrics(metrics, metrics_json, profile, strict=strict)


@admin_boards_app.command(
    "enrich", help="Promote preserved payload metadata into normalized board fields."
)
def boards_enrich(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Persist enriched board and route metadata.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    summary = enrich_metadata(
        _store(), source_key=source, board_key=board, limit=limit, apply=apply
    )
    data = summary.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Board Metadata Enrichment",
        ["checked", "board_changes", "route_changes", "applied"],
        [
            [
                data["checkedBoards"],
                data["boardChangeCount"],
                data["routeChangeCount"],
                data["applied"],
            ]
        ],
    )


@admin_boards_app.command(
    "detect-provider", help="Detect provider metadata for one board URL."
)
def boards_detect_provider(
    board_key: Annotated[str, typer.Argument(help="Board key to inspect.")],
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            help="Override the board website URL before detecting its provider.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Persist detected provider metadata.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
) -> None:
    settings = _settings()
    store = _store(settings)
    board = store.get_board(board_key)
    if not board:
        raise typer.BadParameter(f"Unknown board: {board_key}")
    detected = provider_registry(settings=settings).detect_url(
        url or board.website_url or "", board_key=board.key, source_key=board.source_key
    )
    if not detected:
        raise typer.BadParameter("No provider detected")
    if apply:
        store.upsert_board_providers([detected])
    data = detected.model_dump(mode="json")
    data["applied"] = apply
    _json(data)


@boards_app.command(
    "export", help="Export filtered board records to JSONL, CSV, or Parquet."
)
def boards_export(
    output: Annotated[
        Path,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help=EXPORT_OUTPUT_FILE_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ],
    format_: Annotated[
        ExportFormat,
        typer.Option(
            *FORMAT_OPTION_FLAGS, help=EXPORT_FORMAT_HELP, rich_help_panel=PANEL_OUTPUT
        ),
    ] = ExportFormat.JSONL,
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    market: Annotated[
        str | None,
        typer.Option(
            "--market",
            help=MARKET_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            help=LOCATION_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            help=DOMAIN_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    has_jobs: Annotated[
        bool,
        typer.Option(
            "--has-jobs",
            help=BOARD_HAS_JOBS_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = False,
    min_staff: Annotated[
        int | None,
        typer.Option(
            "--min-staff",
            min=0,
            help="Only include boards with at least this staff count.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    max_staff: Annotated[
        int | None,
        typer.Option(
            "--max-staff",
            min=0,
            help="Only include boards with at most this staff count.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
) -> None:
    count = export_records(
        _store().list_boards(
            filters=_board_filters(
                source=source,
                provider=provider,
                market=market,
                location=location,
                domain=domain,
                has_jobs=has_jobs,
                min_staff=min_staff,
                max_staff=max_staff,
                limit=limit,
            )
        ),
        output,
        format_,
        sqlite_table="boards",
        metadata=_export_metadata(
            "boards",
            {
                "source": source,
                "provider": provider,
                "market": market,
                "location": location,
                "domain": domain,
                "has_jobs": has_jobs,
                "min_staff": min_staff,
                "max_staff": max_staff,
                "limit": limit,
            },
        ),
    )
    console.print(f"Exported {count} boards to {output}")


@jobs_app.command("sync", help="Fetch normalized jobs from ready provider routes.")
def jobs_sync(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help=SYNC_OUTPUT_FILE_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS,
            min=1,
            help="Maximum stale or never-synced provider routes to refresh.",
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    freshness_seconds: Annotated[
        float | None,
        typer.Option(
            "--freshness-seconds",
            min=0,
            help=(
                "Skip routes with a successful job sync newer than this many seconds; "
                "0 refreshes every selected route."
            ),
            rich_help_panel=PANEL_SYNC,
        ),
    ] = None,
    metrics_json: Annotated[
        bool,
        typer.Option(
            *METRICS_JSON_OPTION_FLAGS,
            help="Print sync metrics as JSON.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    profile: Annotated[
        bool,
        typer.Option(
            "--profile",
            help="Print an extended human-readable sync summary with page and error counts.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help=STRICT_SYNC_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            *REFRESH_CACHE_OPTION_FLAGS,
            help="Bypass cache reads and update cache records from fresh responses.",
            rich_help_panel=PANEL_SYNC,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            *VERBOSE_OPTION_FLAGS,
            help="Show detailed sync warnings instead of brief progress messages only.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
) -> None:
    settings = _settings_with_cache_refresh(refresh_cache)
    store = _store(settings)
    metrics = _run_sync_with_progress(
        "Syncing jobs",
        lambda report: asyncio.run(
            sync_jobs(
                settings=settings,
                store=store,
                source_key=source,
                board_key=board,
                provider_id=normalize_provider_filter(provider),
                output=output,
                freshness_seconds=freshness_seconds,
                limit=limit,
                verbose=verbose,
                report=report,
            )
        ),
        enabled=not metrics_json,
        verbose=verbose,
    )
    _metrics(metrics, metrics_json, profile, strict=strict)


@jobs_app.command("list", help="List jobs with normalized metadata filters.")
def jobs_list(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            help=LOCATION_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    department: Annotated[
        str | None,
        typer.Option(
            "--department",
            help=DEPARTMENT_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    team: Annotated[
        str | None,
        typer.Option(
            "--team",
            help=TEAM_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    workplace_type: Annotated[
        str | None,
        typer.Option(
            "--workplace-type",
            help=WORKPLACE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    remote: Annotated[
        str | None,
        typer.Option(
            "--remote",
            help=REMOTE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    employment_type: Annotated[
        str | None,
        typer.Option(
            "--employment-type",
            help=EMPLOYMENT_TYPE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    employment_type_alias: Annotated[
        str | None,
        typer.Option(
            "--type",
            hidden=True,
            help=EMPLOYMENT_TYPE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    salary_min: Annotated[
        float | None,
        typer.Option(
            "--salary-min",
            help=SALARY_MIN_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    salary_max: Annotated[
        float | None,
        typer.Option(
            "--salary-max",
            help=SALARY_MAX_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    skill: Annotated[
        str | None,
        typer.Option(
            "--skill",
            help=SKILL_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            help=QUERY_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    posted_after: Annotated[
        str | None,
        typer.Option(
            "--posted-after",
            help=POSTED_AFTER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    posted_before: Annotated[
        str | None,
        typer.Option(
            "--posted-before",
            help=POSTED_BEFORE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    status: Annotated[
        str,
        typer.Option(
            "--status",
            help=JOB_STATUS_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = "open",
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    jobs = _store().list_jobs(
        filters=_job_filters(
            source=source,
            board=board,
            provider=provider,
            location=location,
            department=department,
            team=team,
            workplace_type=workplace_type,
            remote=remote,
            employment_type=employment_type or employment_type_alias,
            salary_min=salary_min,
            salary_max=salary_max,
            skill=skill,
            query=query,
            posted_after=posted_after,
            posted_before=posted_before,
            status=status,
            limit=limit,
        )
    )
    if json_output:
        _json([job.model_dump(mode="json") for job in jobs])
        return
    _table(
        "Jobs",
        ["id", "board", "provider", "title", "locations"],
        [
            [j.id, j.board_key, j.provider_id, j.title, ", ".join(j.locations)]
            for j in jobs
        ],
    )


@jobs_app.command("show", help="Show one normalized job record as JSON.")
def jobs_show(
    job_id: Annotated[str, typer.Argument(help="Job id to inspect.")],
) -> None:
    job = _store().get_job(job_id)
    if not job:
        raise typer.BadParameter(f"Unknown job: {job_id}")
    _json(job.model_dump(mode="json"))


@jobs_app.command("history", help="Show normalized content versions for one job.")
def jobs_history(
    job_id: Annotated[str, typer.Argument(help="Job id to inspect.")],
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    versions = _store().list_job_versions(job_id)
    if not versions:
        raise typer.BadParameter(f"Unknown job: {job_id}")
    rows = [version.model_dump(mode="json") for version in versions]
    if json_output:
        _json(rows)
        return
    _table(
        "Job history",
        ["version", "content_hash", "first_seen", "last_seen", "title"],
        [
            [
                row.get("version"),
                str(row.get("content_hash") or "")[:12],
                row.get("first_seen_at") or "",
                row.get("last_seen_at") or "",
                row.get("title") or "",
            ]
            for row in rows
        ],
    )


@jobs_app.command("export", help="Export filtered jobs to JSONL, CSV, or Parquet.")
def jobs_export(
    output: Annotated[
        Path,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help=EXPORT_OUTPUT_FILE_HELP,
            rich_help_panel=PANEL_OUTPUT,
        ),
    ],
    format_: Annotated[
        ExportFormat,
        typer.Option(
            *FORMAT_OPTION_FLAGS, help=EXPORT_FORMAT_HELP, rich_help_panel=PANEL_OUTPUT
        ),
    ] = ExportFormat.JSONL,
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            help=LOCATION_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    department: Annotated[
        str | None,
        typer.Option(
            "--department",
            help=DEPARTMENT_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    team: Annotated[
        str | None,
        typer.Option(
            "--team",
            help=TEAM_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    workplace_type: Annotated[
        str | None,
        typer.Option(
            "--workplace-type",
            help=WORKPLACE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    remote: Annotated[
        str | None,
        typer.Option(
            "--remote",
            help=REMOTE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    employment_type: Annotated[
        str | None,
        typer.Option(
            "--employment-type",
            help=EMPLOYMENT_TYPE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    employment_type_alias: Annotated[
        str | None,
        typer.Option(
            "--type",
            hidden=True,
            help=EMPLOYMENT_TYPE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    salary_min: Annotated[
        float | None,
        typer.Option(
            "--salary-min",
            help=SALARY_MIN_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    salary_max: Annotated[
        float | None,
        typer.Option(
            "--salary-max",
            help=SALARY_MAX_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    skill: Annotated[
        str | None,
        typer.Option(
            "--skill",
            help=SKILL_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            help=QUERY_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    posted_after: Annotated[
        str | None,
        typer.Option(
            "--posted-after",
            help=POSTED_AFTER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    posted_before: Annotated[
        str | None,
        typer.Option(
            "--posted-before",
            help=POSTED_BEFORE_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    status: Annotated[
        str,
        typer.Option(
            "--status",
            help=JOB_STATUS_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = "open",
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
) -> None:
    count = export_records(
        _store().list_jobs(
            filters=_job_filters(
                source=source,
                board=board,
                provider=provider,
                location=location,
                department=department,
                team=team,
                workplace_type=workplace_type,
                remote=remote,
                employment_type=employment_type or employment_type_alias,
                salary_min=salary_min,
                salary_max=salary_max,
                skill=skill,
                query=query,
                posted_after=posted_after,
                posted_before=posted_before,
                status=status,
                limit=limit,
            )
        ),
        output,
        format_,
        sqlite_table="jobs",
        metadata=_export_metadata(
            "jobs",
            {
                "source": source,
                "board": board,
                "provider": provider,
                "location": location,
                "department": department,
                "team": team,
                "workplace_type": workplace_type,
                "remote": remote,
                "employment_type": employment_type,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "skill": skill,
                "query": query,
                "posted_after": posted_after,
                "posted_before": posted_before,
                "status": status,
                "limit": limit,
            },
        ),
    )
    console.print(f"Exported {count} jobs to {output}")


@admin_providers_app.command(
    "list", help="List packaged source and job provider adapters."
)
def providers_list(
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    providers = provider_registry(settings=_settings()).list()
    if json_output:
        _json([_provider_definition_payload(provider) for provider in providers])
        return
    _table(
        "Providers",
        ["id", "kind", "support", "label"],
        [[p.id, p.kind.value, p.support_level.value, p.label] for p in providers],
    )


def _provider_definition_payload(provider: ProviderDefinition) -> dict[str, object]:
    return {
        "id": provider.id,
        "label": provider.label,
        "kind": provider.kind.value,
        "supportLevel": provider.support_level.value,
        "description": provider.description,
        "detectsRoutes": provider.route_detector is not None,
    }


@admin_providers_app.command(
    "detect", help="Detect a provider adapter from a public board URL."
)
def providers_detect(
    url: Annotated[str, typer.Argument(help="Public board URL to inspect.")],
) -> None:
    detected = provider_registry(settings=_settings()).detect_url(url)
    if not detected:
        raise typer.BadParameter("No provider detected")
    _json(detected.model_dump(mode="json"))


@admin_providers_app.command(
    "explain", help="Describe one provider adapter and support level."
)
def providers_explain(
    provider_id: Annotated[str, typer.Argument(help="Provider adapter id to explain.")],
) -> None:
    provider = provider_registry(settings=_settings()).get(provider_id)
    if not provider:
        _json(
            {
                "id": provider_id,
                "supportLevel": ProviderSupport.UNSUPPORTED.value,
                "description": "Unknown provider",
            }
        )
        return
    _json(
        {
            "id": provider.id,
            "label": provider.label,
            "supportLevel": provider.support_level.value,
            "description": provider.description,
        }
    )


@admin_providers_app.command(
    "probe-routes",
    help="Try provider route candidates and report which boards can fetch jobs.",
)
def providers_probe_routes(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Persist matched token, URL, or site metadata.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
    include_existing: Annotated[
        bool,
        typer.Option(
            "--include-existing",
            help="Also probe routes that already have token, URL, or site metadata.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            min=1,
            max=50,
            help="Maximum candidate slugs or sites to try per board.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = 12,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    settings = _settings()
    store = _store(settings)
    summary = asyncio.run(
        probe_routes(
            settings=settings,
            store=store,
            source_key=source,
            board_key=board,
            provider_id=normalize_provider_filter(provider),
            only_missing=not include_existing,
            apply=apply,
            max_candidates=max_candidates,
            limit=limit,
        )
    )
    data = summary.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Route Probe Summary",
        ["checked", "matched", "unknown", "errors"],
        [
            [
                data["checked"],
                data["matchedCount"],
                data["unknownCount"],
                json.dumps(data["errors"]),
            ]
        ],
    )
    if summary.matched:
        _table(
            "Matched Routes",
            ["board", "provider", "token/site", "observed_jobs"],
            [
                [
                    match.board_key,
                    match.provider_id,
                    match.token or match.site or match.board_url,
                    match.observed_jobs,
                ]
                for match in summary.matched
            ],
        )
    if summary.unknown:
        _table(
            "Unknown Routes",
            ["board", "provider", "reason", "candidates"],
            [
                [
                    item.board_key,
                    item.provider_id,
                    item.reason,
                    ", ".join(item.candidates[:8]),
                ]
                for item in summary.unknown
            ],
        )


@admin_providers_app.command(
    "registry", help="Inspect executable board route metadata."
)
def providers_registry(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    passed_probe_only: Annotated[
        bool,
        typer.Option(
            "--passed-probe-only",
            help="Show only routes persisted by a successful probe-routes --apply run.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
    include_missing: Annotated[
        bool,
        typer.Option(
            "--include-missing",
            help="Include job-capable routes that still lack executable metadata.",
            rich_help_panel=PANEL_ROUTE,
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    selection = BoardRouteRegistry(_store()).select(
        source_key=source,
        board_key=board,
        provider_id=normalize_provider_filter(provider),
        ready_only=not include_missing,
        verified_only=passed_probe_only,
        limit=limit,
    )
    data = selection.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Board Route Registry",
        ["board", "source", "provider", "route", "verified", "status"],
        [
            [
                entry.board.key,
                entry.board.source_key,
                entry.route.provider_id,
                entry.route.token or entry.route.site or entry.route.board_url,
                entry.verified,
                entry.route.last_status,
            ]
            for entry in selection.entries
        ],
    )
    if data["missingRouteMetadataSkipped"] or data["unverifiedRoutesSkipped"]:
        _table(
            "Registry Skips",
            ["missing_route_metadata", "unverified", "duplicates"],
            [
                [
                    data["missingRouteMetadataSkipped"],
                    data["unverifiedRoutesSkipped"],
                    data["duplicateRoutesSkipped"],
                ]
            ],
        )


@providers_app.command(
    "health", help="Dry-run provider routes and summarize live fetch readiness."
)
def providers_health(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    board: Annotated[
        str | None,
        typer.Option(
            *BOARD_OPTION_FLAGS, help=BOARD_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            min=1,
            max=50,
            help="Maximum provider page size for health probes.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = 5,
    limit: Annotated[
        int | None,
        typer.Option(
            *LIMIT_OPTION_FLAGS, min=1, help=LIMIT_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Persist source and board-provider health statuses.",
            rich_help_panel=PANEL_DIAGNOSTICS,
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    settings = _settings()
    store = _store(settings)
    summary = asyncio.run(
        check_provider_health(
            settings=settings,
            store=store,
            source_key=source,
            board_key=board,
            provider_id=normalize_provider_filter(provider),
            page_size=page_size,
            limit=limit,
            apply=apply,
        )
    )
    data = summary.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Provider Health Summary",
        ["sources", "routes", "not_covered", "duplicates", "applied"],
        [
            [
                data["sourceStatus"],
                data["routeStatus"],
                data["notCoveredCount"],
                data["duplicateRoutesSkipped"],
                data["applied"],
            ]
        ],
    )
    if summary.not_covered:
        _table(
            "Not Covered Providers",
            ["provider", "support", "discovered", "examples"],
            [
                [
                    item.provider_id,
                    item.support_level,
                    item.discovered,
                    ", ".join(item.examples),
                ]
                for item in sorted(
                    summary.not_covered.values(), key=lambda value: value.provider_id
                )
            ],
        )


@providers_app.command(
    "coverage", help="Summarize provider coverage, route gaps, and data completeness."
)
def providers_coverage(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            *PROVIDER_OPTION_FLAGS,
            help=PROVIDER_FILTER_HELP,
            rich_help_panel=PANEL_SCOPE,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    report = build_coverage_report(
        _store(), source_key=source, provider_id=normalize_provider_filter(provider)
    )
    data = report.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Provider Coverage Summary",
        [
            "sources",
            "boards",
            "routes",
            "executable",
            "jobs",
            "detect_only",
            "non_supported_boards",
            "non_supported_pct",
            "only_non_supported_boards",
        ],
        [
            [
                data["sources"]["total"],
                data["boards"]["total"],
                data["routes"]["total"],
                data["routes"]["executable"],
                data["jobs"]["total"],
                len(data["gaps"]["detectOnlyProviders"]),
                data["boards"]["withNonSupportedProviderHints"],
                f"{data['boards']['nonSupportedProviderCoverage']['percentage']:.2f}%",
                data["boards"]["withOnlyNonSupportedProviderHints"],
            ]
        ],
    )
    _table(
        "Data Quality Missing Fields",
        ["field", "missing", "complete"],
        [
            [field, metric["missing"], f"{metric['percentage']:.2f}%"]
            for field, metric in data["dataQuality"]["completeness"].items()
        ],
    )


@providers_app.command(
    "audit", help="Publish persisted-board audit evidence for candidate providers."
)
def providers_audit(
    source: Annotated[
        str | None,
        typer.Option(
            *SOURCE_OPTION_FLAGS, help=SOURCE_FILTER_HELP, rich_help_panel=PANEL_SCOPE
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(*JSON_OPTION_FLAGS, help=JSON_HELP, rich_help_panel=PANEL_OUTPUT),
    ] = False,
) -> None:
    report = build_provider_audit_report(_store(), source_key=source)
    data = report.as_dict()
    if json_output:
        _json(data)
        return
    _table(
        "Provider Audit Snapshot",
        ["sources", "boards", "representative"],
        [
            [
                data["snapshot"]["sourceCount"],
                data["snapshot"]["denominator"],
                data["snapshot"]["representative"],
            ]
        ],
    )
    _table(
        "Candidate Providers",
        ["provider", "support", "boards", "coverage", "adopted"],
        [
            [
                item["provider"],
                item["currentSupportLevel"],
                item["boards"],
                f"{item['coverage']['percentage']:.2f}%",
                item["adoptedForV01"],
            ]
            for item in data["candidates"]
        ],
    )


@admin_db_app.command(
    "init", help="Create the local SQLite schema if it does not exist."
)
def db_init() -> None:
    _store().init_db()
    console.print("Database initialized")


@admin_db_app.command(
    "status", help="Show local database path and record counts as JSON."
)
def db_status() -> None:
    _json(_store().status())


@admin_db_app.command(
    "export",
    help="Export a portable snapshot of the local SQLite database.",
)
def db_export(
    output: Annotated[
        Path,
        typer.Option(
            *OUTPUT_OPTION_FLAGS,
            help="Destination SQLite database file to create or replace.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ],
) -> None:
    settings = _settings()
    source = settings.sqlite_path
    if source is None:
        raise typer.BadParameter(
            "Database export requires a local sqlite:/// OPENOPPS_DB_URL."
        )
    _store(settings).init_db()
    if not source.exists():
        raise typer.BadParameter(f"SQLite database does not exist: {source}")
    _backup_sqlite_database(source, output)
    console.print(f"Exported SQLite database snapshot to {output}")


@admin_db_app.command("vacuum", help="Compact the local SQLite database file.")
def db_vacuum() -> None:
    _store().vacuum()
    console.print("Database vacuumed")


def _backup_sqlite_database(source: Path, output: Path) -> None:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if source == output:
        raise typer.BadParameter("Database export output must differ from the source.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    _remove_sqlite_sidecars(output)
    try:
        with sqlite3.connect(source) as checkpoint_conn:
            checkpoint_conn.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src:
            with sqlite3.connect(output) as dst:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                integrity = dst.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        f"SQLite integrity check failed: {integrity!r}"
                    )
    except sqlite3.Error as exc:
        if output.exists():
            output.unlink()
        _remove_sqlite_sidecars(output)
        raise ClickException(f"Unable to export SQLite database: {exc}") from exc


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
