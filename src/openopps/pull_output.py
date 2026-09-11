from __future__ import annotations

import io
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import pydoc
import sys
import tempfile
from typing import TextIO

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from openopps.job_profiles import DEFAULT_CLI_PROFILE, project_job
from openopps.pull_models import (
    PullOutputFormat,
    PullResult,
    PullTerminalObservability,
)


@dataclass(frozen=True, slots=True)
class PullOutputDiagnostic:
    """A bounded non-result message eligible for stderr emission."""

    message: str
    verbosity: int = 0
    essential: bool = False


@dataclass(frozen=True, slots=True)
class PullOutputReceipt:
    """Observable facts about one completed result-output operation."""

    format: PullOutputFormat
    bytes_written: int
    output_path: Path | None
    paged: bool


def write_pull_output(
    result: PullResult,
    *,
    format_: PullOutputFormat = PullOutputFormat.AUTO,
    raw: bool = False,
    profile: str | None = None,
    output: Path | None = None,
    pager: bool = False,
    quiet: bool = False,
    verbosity: int = 0,
    diagnostics: Iterable[PullOutputDiagnostic] = (),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    interactive: bool | None = None,
    pager_writer: Callable[[str], None] | None = None,
    width: int = 120,
) -> PullOutputReceipt:
    """Validate, render, and emit one complete pull-result representation.

    Result bytes go only to ``stdout`` or ``output``. Bounded diagnostics use
    ``stderr`` and never affect the selected representation. File output is
    staged in an owned sibling temporary file before atomic replacement.
    """

    result.assert_valid()
    if verbosity < 0:
        raise ValueError("verbosity must not be negative")
    if width < 40:
        raise ValueError("render width must be at least 40 columns")

    stdout_stream = stdout if stdout is not None else sys.stdout
    stderr_stream = stderr if stderr is not None else sys.stderr
    terminal = output is None and (
        interactive if interactive is not None else _is_interactive(stdout_stream)
    )
    selected_format = _resolve_format(format_, raw=raw, interactive=terminal)
    rendered = _render_result(
        result,
        format_=selected_format,
        raw=raw,
        interactive=terminal,
        width=width,
        profile=profile or DEFAULT_CLI_PROFILE,
    )
    payload = rendered.encode("utf-8")

    _write_diagnostics(
        diagnostics,
        stderr=stderr_stream,
        quiet=quiet,
        verbosity=verbosity,
    )

    output_path = Path(output) if output is not None else None
    if output_path is not None:
        _atomic_write(output_path, payload)
        return PullOutputReceipt(
            format=selected_format,
            bytes_written=len(payload),
            output_path=output_path,
            paged=False,
        )

    should_page = pager and terminal and selected_format == PullOutputFormat.PRETTY
    if should_page:
        (pager_writer or pydoc.pager)(rendered)
    else:
        stdout_stream.write(rendered)
        stdout_stream.flush()
    return PullOutputReceipt(
        format=selected_format,
        bytes_written=len(payload),
        output_path=None,
        paged=should_page,
    )


def _resolve_format(
    format_: PullOutputFormat,
    *,
    raw: bool,
    interactive: bool,
) -> PullOutputFormat:
    selected = PullOutputFormat(format_)
    if selected == PullOutputFormat.AUTO:
        if raw:
            return PullOutputFormat.JSON
        return PullOutputFormat.PRETTY if interactive else PullOutputFormat.JSON
    if raw and selected not in {PullOutputFormat.JSON, PullOutputFormat.JSONL}:
        raise ValueError("raw pull output requires json or jsonl format")
    return selected


def _render_result(
    result: PullResult,
    *,
    format_: PullOutputFormat,
    raw: bool,
    interactive: bool,
    width: int,
    profile: str,
) -> str:
    if raw:
        envelope = result.raw_envelope()
        if format_ == PullOutputFormat.JSON:
            return _indented_json(envelope)
        if format_ == PullOutputFormat.JSONL:
            return _json_line(envelope)
        raise ValueError("raw pull output requires json or jsonl format")

    projected = [project_job(job, profile) for job in result.jobs]
    if format_ == PullOutputFormat.JSON:
        return _indented_json(projected)
    if format_ == PullOutputFormat.JSONL:
        return "".join(_json_line(job) for job in projected)
    jobs = result.normalized_jobs()
    if format_ == PullOutputFormat.TABLE:
        return _render_rich(
            _jobs_table(jobs, title="OpenOpps jobs"),
            interactive=interactive,
            width=width,
        )
    if format_ == PullOutputFormat.PRETTY:
        summary = Text.assemble(*_pretty_summary_parts(result, job_count=len(jobs)))
        renderable = Group(
            Panel(summary, title="OpenOpps pull", border_style="cyan"),
            _jobs_table(jobs, title=None),
        )
        return _render_rich(renderable, interactive=interactive, width=width)
    raise ValueError(f"unsupported pull output format: {format_.value}")


def _indented_json(value: object) -> str:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    )


def _json_line(value: object) -> str:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def pull_result_diagnostics(result: PullResult) -> tuple[PullOutputDiagnostic, ...]:
    """Build bounded stderr diagnostics from validated result evidence."""

    diagnostics = [
        PullOutputDiagnostic(
            "provider="
            f"{result.provenance.provider_id} "
            f"operation={result.provenance.resolved_operation.value} "
            f"jobs={len(result.jobs)} persisted={str(result.persisted).lower()}",
            verbosity=1,
        ),
        PullOutputDiagnostic(
            "resolution="
            f"{result.provenance.discovery_method.value} "
            f"mechanism={result.execution.mechanism.value} "
            f"visited={len(result.provenance.visited_urls)} "
            f"probed={len(result.provenance.probed_slugs)}",
            verbosity=2,
        ),
    ]
    membership = result.execution.membership
    detail_coverage = result.execution.detail_coverage
    if membership is not None:
        diagnostics.append(
            PullOutputDiagnostic(
                "membership="
                f"{membership.scope.value} "
                f"authoritative={str(membership.authoritative).lower()} "
                f"complete={str(membership.complete).lower()} "
                f"pages={membership.pages_fetched} "
                f"observed={membership.observed_count} "
                f"advertised={membership.advertised_count}",
                verbosity=2,
            )
        )
    if detail_coverage is not None:
        diagnostics.append(
            PullOutputDiagnostic(
                "details="
                f"{detail_coverage.status.value} "
                f"required={str(detail_coverage.required).lower()} "
                f"requested={detail_coverage.requested_count} "
                f"completed={detail_coverage.completed_count} "
                f"failed={detail_coverage.failed_count}",
                verbosity=2,
            )
        )
    if result.observability is not None:
        diagnostics.extend(pull_observability_diagnostics(result.observability))
    return tuple(diagnostics)


def pull_observability_diagnostics(
    observability: PullTerminalObservability,
) -> tuple[PullOutputDiagnostic, ...]:
    """Render only bounded terminal counters and closed enum labels to stderr."""

    http = observability.http
    diagnostics: list[PullOutputDiagnostic] = []
    if observability.coverage_class is not None:
        diagnostics.append(
            PullOutputDiagnostic(
                f"coverage={observability.coverage_class.value}",
                verbosity=1,
            )
        )
    if http.cache_stale_fallback_count:
        diagnostics.append(
            PullOutputDiagnostic(
                "Warning: URL pull used stale cache fallback "
                f"count={http.cache_stale_fallback_count}; "
                "retry with --refresh-cache for fresh evidence.",
                essential=True,
            )
        )
    diagnostics.extend(
        (
            PullOutputDiagnostic(
                f"terminal={observability.terminal_state.value} "
                f"elapsed_ms={observability.elapsed_milliseconds} "
                f"persistence={observability.persistence_handoff.value} "
                f"provider_errors={observability.provider_error_count} "
                f"duplicates={observability.duplicate_identity_count}",
                verbosity=1,
            ),
            PullOutputDiagnostic(
                f"http=logical_reads:{http.logical_read_count} "
                f"requests:{http.request_count} redirects:{http.redirect_count} "
                f"retries:{http.retry_count} encoded_bytes:{http.encoded_bytes} "
                f"decoded_bytes:{http.decoded_bytes}",
                verbosity=2,
            ),
            PullOutputDiagnostic(
                f"cache=hits:{http.cache_hit_count} misses:{http.cache_miss_count} "
                f"revalidations:{http.cache_revalidation_count} "
                f"stale_fallbacks:{http.cache_stale_fallback_count} "
                f"writes:{http.cache_write_count} bypasses:{http.cache_bypass_count}",
                verbosity=2,
            ),
        )
    )
    return tuple(diagnostics)


def write_atomic_bytes(path: Path, payload: bytes) -> None:
    """Stage ``payload`` in an owned sibling tempfile, then replace ``path``."""

    _atomic_write(path, payload)


def _pretty_summary_parts(
    result: PullResult,
    *,
    job_count: int,
) -> tuple[str | tuple[str, str], ...]:
    parts: list[str | tuple[str, str]] = [
        (result.provenance.provider_id, "bold cyan"),
        "  ",
        (result.provenance.resolved_operation.value, "bold"),
        "  ",
        (f"board={result.provenance.board_identity}", "magenta"),
        "  ",
        (f"{job_count} job{'s' if job_count != 1 else ''}", "green"),
        "  ",
        (f"persisted={str(result.persisted).lower()}", "yellow"),
    ]
    observability = result.observability
    if observability is not None and observability.coverage_class is not None:
        parts.extend(
            (
                "  ",
                (f"coverage={observability.coverage_class.value}", "cyan"),
            )
        )
    return tuple(parts)


def _jobs_table(
    jobs: list[dict[str, object]],
    *,
    title: str | None,
) -> Table:
    table = Table(title=title, expand=True)
    table.add_column("Title", style="bold", min_width=20)
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Remote ID", no_wrap=True)
    table.add_column("URL", overflow="fold")
    for job in jobs:
        raw_locations = job.get("locations")
        locations = (
            ", ".join(str(item) for item in raw_locations)
            if isinstance(raw_locations, list)
            else ""
        )
        table.add_row(
            Text(str(job.get("title", ""))),
            Text(str(job.get("company", ""))),
            Text(locations),
            Text(str(job.get("provider_id", ""))),
            Text(str(job.get("remote_id", ""))),
            Text(str(job.get("posting_url", ""))),
        )
    return table


def _render_rich(
    renderable: RenderableType,
    *,
    interactive: bool,
    width: int,
) -> str:
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        color_system="standard" if interactive else None,
        force_terminal=interactive,
        highlight=False,
        width=width,
    )
    console.print(renderable)
    return buffer.getvalue()


def _write_diagnostics(
    diagnostics: Iterable[PullOutputDiagnostic],
    *,
    stderr: TextIO,
    quiet: bool,
    verbosity: int,
) -> None:
    wrote = False
    for diagnostic in diagnostics:
        if quiet and not diagnostic.essential:
            continue
        if diagnostic.verbosity < 0:
            raise ValueError("diagnostic verbosity must not be negative")
        if diagnostic.verbosity > verbosity:
            continue
        message = _bounded_diagnostic(diagnostic.message)
        if not message:
            continue
        stderr.write(f"{message}\n")
        wrote = True
    if wrote:
        stderr.flush()


def _bounded_diagnostic(message: str) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= 500:
        return normalized
    return f"{normalized[:497]}..."


def _is_interactive(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temporary)
    try:
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("atomic pull output write did not make progress")
        remaining = remaining[written:]


__all__ = [
    "PullOutputDiagnostic",
    "PullOutputReceipt",
    "pull_observability_diagnostics",
    "pull_result_diagnostics",
    "write_atomic_bytes",
    "write_pull_output",
]
