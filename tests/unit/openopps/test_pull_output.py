from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from openopps.job_profiles import DEFAULT_CLI_PROFILE, project_job
from openopps.models import JobRecord
from openopps.pull_models import (
    DiscoveryMethod,
    PullCoverageClass,
    PullDetailCoverageEvidence,
    PullExecutionEvidence,
    PullHttpObservability,
    PullMembershipEvidence,
    PullMembershipScope,
    PullOperation,
    PullOutputFormat,
    PullPersistenceHandoffState,
    PullProvenance,
    PullRawPosting,
    PullResult,
    PullRetrievalMechanism,
    PullTerminalObservability,
    PullTerminalState,
)
from openopps.pull_output import (
    PullOutputDiagnostic,
    pull_result_diagnostics,
    write_pull_output,
)


class _Stream(io.StringIO):
    def __init__(self, *, interactive: bool = False) -> None:
        super().__init__()
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


def _job(remote_id: str, *, title: str, company: str = "Acme") -> JobRecord:
    return JobRecord(
        id=f"acme:greenhouse:{remote_id}",
        board_key="acme",
        provider_id="greenhouse",
        remote_id=remote_id,
        title=title,
        company=company,
        locations=["Remote", "New York, NY"],
        posting_url=f"https://boards.greenhouse.io/acme/jobs/{remote_id}",
        raw_listing={"id": remote_id, "title": title},
        raw_detail={"content": f"Details for {title}"},
    )


def _result(*, operation: PullOperation = PullOperation.LIST) -> PullResult:
    jobs = (
        (_job("101", title="Platform Engineer"),)
        if operation == PullOperation.GET
        else (
            _job("101", title="Platform Engineer"),
            _job("202", title="Data Engineer"),
        )
    )
    return PullResult(
        provenance=PullProvenance(
            requested_url="https://careers.example.com/jobs?token=secret#fragment",
            resolved_url=(
                "https://boards.greenhouse.io/acme/jobs/101?gh_jid=101"
                if operation == PullOperation.GET
                else "https://boards.greenhouse.io/acme?source=careers"
            ),
            discovery_method=DiscoveryMethod.PAGE_LINK,
            provider_id="greenhouse",
            requested_operation=PullOperation.AUTO,
            resolved_operation=operation,
            board_identity="acme",
            posting_identity="101" if operation == PullOperation.GET else None,
            visited_urls=("https://careers.example.com/jobs?token=secret",),
            probed_slugs=("acme",),
        ),
        execution=(
            PullExecutionEvidence(
                mechanism=PullRetrievalMechanism.NATIVE_GET,
            )
            if operation == PullOperation.GET
            else PullExecutionEvidence(
                mechanism=PullRetrievalMechanism.LIST,
                membership=PullMembershipEvidence(
                    scope=PullMembershipScope.LISTED,
                    authoritative=True,
                    complete=True,
                    terminal_page_seen=True,
                    pages_fetched=1,
                    observed_count=len(jobs),
                    advertised_count=len(jobs),
                ),
                detail_coverage=PullDetailCoverageEvidence(
                    requested_count=len(jobs),
                    completed_count=len(jobs),
                ),
            )
        ),
        jobs=jobs,
        raw_postings=tuple(
            PullRawPosting(
                job_id=job.id,
                listing=job.raw_listing,
                detail=job.raw_detail,
            )
            for job in jobs
        ),
    )


def _result_with_coverage(
    *,
    coverage_class: PullCoverageClass = PullCoverageClass.EPHEMERAL_NEW,
    persisted: bool = False,
) -> PullResult:
    result = _result()
    observability = PullTerminalObservability(
        terminal_state=PullTerminalState.SUCCEEDED,
        requested_operation=result.provenance.requested_operation,
        resolved_operation=result.provenance.resolved_operation,
        retrieval_mechanism=result.execution.mechanism,
        provider_id=result.provenance.provider_id,
        discovery_method=result.provenance.discovery_method,
        resolver_visited_url_count=len(result.provenance.visited_urls),
        resolver_probe_count=len(result.provenance.probed_slugs),
        http=PullHttpObservability(request_count=1),
        membership=result.execution.membership,
        detail_coverage=result.execution.detail_coverage,
        duplicate_identity_count=0,
        provider_error_count=0,
        persistence_handoff=(
            PullPersistenceHandoffState.SUCCEEDED
            if persisted
            else PullPersistenceHandoffState.NOT_REQUESTED
        ),
        coverage_class=coverage_class,
        elapsed_milliseconds=9,
    )
    return PullResult(
        provenance=result.provenance,
        execution=result.execution,
        jobs=result.jobs,
        raw_postings=result.raw_postings,
        persisted=persisted,
        observability=observability,
    )


def _temporary_siblings(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def _projected_jobs(
    result: PullResult,
    profile: str = DEFAULT_CLI_PROFILE,
) -> list[dict[str, object]]:
    return [project_job(job, profile) for job in result.jobs]


def test_auto_format_uses_rich_pretty_for_tty_and_indented_json_for_pipe() -> None:
    result = _result()
    terminal = _Stream(interactive=True)

    terminal_receipt = write_pull_output(result, stdout=terminal)

    assert terminal_receipt.format == PullOutputFormat.PRETTY
    assert "OpenOpps pull" in terminal.getvalue()
    assert "Platform Engineer" in terminal.getvalue()
    assert "\x1b[" in terminal.getvalue()

    pipe = _Stream()
    pipe_receipt = write_pull_output(result, stdout=pipe)

    assert pipe_receipt.format == PullOutputFormat.JSON
    assert json.loads(pipe.getvalue()) == _projected_jobs(result)
    assert pipe.getvalue().startswith("[\n  {")
    assert pipe.getvalue().endswith("\n")


@pytest.mark.parametrize("format_", [PullOutputFormat.PRETTY, PullOutputFormat.TABLE])
def test_human_formats_render_semantic_job_fields(format_: PullOutputFormat) -> None:
    stdout = _Stream()

    receipt = write_pull_output(_result(), format_=format_, stdout=stdout)

    assert receipt.format == format_
    rendered = stdout.getvalue()
    assert "Title" in rendered
    assert "Provider" in rendered
    assert "Platform Engineer" in rendered
    assert "greenhouse" in rendered
    if format_ == PullOutputFormat.PRETTY:
        assert "OpenOpps pull" in rendered
        assert "2 jobs" in rendered
        assert "board=acme" in rendered
        assert "persisted=false" in rendered
    else:
        assert "OpenOpps jobs" in rendered


def test_json_is_deterministic_and_jsonl_is_one_normalized_job_per_line() -> None:
    result = _result()
    first = _Stream()
    second = _Stream()
    jsonl = _Stream()

    write_pull_output(result, format_=PullOutputFormat.JSON, stdout=first)
    write_pull_output(result, format_=PullOutputFormat.JSON, stdout=second)
    write_pull_output(result, format_=PullOutputFormat.JSONL, stdout=jsonl)

    assert first.getvalue() == second.getvalue()
    assert json.loads(first.getvalue()) == _projected_jobs(result)
    lines = jsonl.getvalue().splitlines()
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == _projected_jobs(result)
    assert all("\n" not in line for line in lines)


@pytest.mark.parametrize("raw", [False, True])
def test_machine_formats_reject_non_finite_numbers(raw: bool) -> None:
    result = _result()
    if raw:
        result.jobs[0].raw_listing["score"] = float("inf")
        assert result.raw_postings[0].listing is not None
        result.raw_postings[0].listing["score"] = float("inf")
    else:
        result.jobs[0].salary_min = float("nan")
    stdout = _Stream()

    with pytest.raises(ValueError, match="Out of range float values"):
        write_pull_output(
            result,
            format_=PullOutputFormat.JSON,
            raw=raw,
            stdout=stdout,
        )

    assert stdout.getvalue() == ""


@pytest.mark.parametrize("format_", [PullOutputFormat.PRETTY, PullOutputFormat.TABLE])
def test_human_formats_render_provider_text_literally(
    format_: PullOutputFormat,
) -> None:
    result = _result()
    result.jobs[0].title = "[bold]literal[/bold]"
    stdout = _Stream()

    write_pull_output(result, format_=format_, stdout=stdout)

    assert "[bold]literal[/bold]" in stdout.getvalue()


def test_jsonl_get_is_one_line_and_empty_list_is_an_empty_stream() -> None:
    get_output = _Stream()
    write_pull_output(
        _result(operation=PullOperation.GET),
        format_=PullOutputFormat.JSONL,
        stdout=get_output,
    )
    assert len(get_output.getvalue().splitlines()) == 1

    empty = PullResult(
        provenance=PullProvenance(
            requested_url="https://boards.greenhouse.io/empty",
            resolved_url="https://boards.greenhouse.io/empty",
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="greenhouse",
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
            board_identity="empty",
        ),
        execution=PullExecutionEvidence(
            mechanism=PullRetrievalMechanism.LIST,
            membership=PullMembershipEvidence(
                scope=PullMembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=1,
                observed_count=0,
                advertised_count=0,
            ),
            detail_coverage=PullDetailCoverageEvidence(),
        ),
    )
    empty_output = _Stream()
    write_pull_output(
        empty,
        format_=PullOutputFormat.JSONL,
        stdout=empty_output,
    )
    assert empty_output.getvalue() == ""


@pytest.mark.parametrize("format_", [PullOutputFormat.JSON, PullOutputFormat.JSONL])
def test_raw_machine_formats_emit_one_stable_envelope(
    format_: PullOutputFormat,
) -> None:
    result = _result()
    stdout = _Stream()

    receipt = write_pull_output(result, format_=format_, raw=True, stdout=stdout)

    documents = (
        [json.loads(stdout.getvalue())]
        if format_ == PullOutputFormat.JSON
        else [json.loads(line) for line in stdout.getvalue().splitlines()]
    )
    assert len(documents) == 1
    assert documents[0] == result.raw_envelope()
    assert documents[0]["provenance"]["requested_url"] == (
        "https://careers.example.com/jobs"
    )
    assert receipt.format == format_


def test_raw_auto_is_json_even_on_tty_and_raw_human_formats_fail_closed() -> None:
    stdout = _Stream(interactive=True)
    receipt = write_pull_output(_result(), raw=True, stdout=stdout)

    assert receipt.format == PullOutputFormat.JSON
    assert json.loads(stdout.getvalue()) == _result().raw_envelope()

    for format_ in (PullOutputFormat.PRETTY, PullOutputFormat.TABLE):
        blocked = _Stream()
        with pytest.raises(ValueError, match="requires json or jsonl"):
            write_pull_output(_result(), format_=format_, raw=True, stdout=blocked)
        assert blocked.getvalue() == ""


def test_output_file_is_complete_atomic_and_auto_selects_json(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "jobs.json"
    output.parent.mkdir()
    output.write_text("previous\n", encoding="utf-8")
    stdout = _Stream(interactive=True)
    result = _result()

    receipt = write_pull_output(result, output=output, stdout=stdout)

    assert receipt.format == PullOutputFormat.JSON
    assert receipt.output_path == output
    assert receipt.bytes_written == len(output.read_bytes())
    assert json.loads(output.read_text(encoding="utf-8")) == _projected_jobs(result)
    assert stdout.getvalue() == ""
    assert _temporary_siblings(output) == []


def test_render_validation_failure_preserves_destination_and_creates_no_temp(
    tmp_path: Path,
) -> None:
    output = tmp_path / "jobs.json"
    output.write_text("previous\n", encoding="utf-8")
    result = _result()
    result.jobs[0].raw_listing["id"] = "mutated"

    with pytest.raises(ValueError, match="raw listing evidence"):
        write_pull_output(result, output=output)

    assert output.read_text(encoding="utf-8") == "previous\n"
    assert _temporary_siblings(output) == []


@pytest.mark.parametrize("failure", [OSError("write failed"), KeyboardInterrupt()])
def test_write_failure_or_cancellation_cleans_temp_and_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    from openopps import pull_output

    output = tmp_path / "jobs.json"
    output.write_text("previous\n", encoding="utf-8")

    def fail_after_partial_write(descriptor: int, payload: bytes) -> None:
        pull_output.os.write(descriptor, payload[:17])
        raise failure

    monkeypatch.setattr(pull_output, "_write_all", fail_after_partial_write)

    with pytest.raises(type(failure), match=str(failure) or None):
        write_pull_output(_result(), output=output)

    assert output.read_text(encoding="utf-8") == "previous\n"
    assert _temporary_siblings(output) == []


def test_replace_failure_preserves_destination_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openopps import pull_output

    output = tmp_path / "jobs.json"
    output.write_text("previous\n", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(pull_output.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_pull_output(_result(), output=output)

    assert output.read_text(encoding="utf-8") == "previous\n"
    assert _temporary_siblings(output) == []


def test_write_failure_does_not_create_a_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openopps import pull_output

    output = tmp_path / "jobs.json"

    def fail_write(_descriptor: int, _payload: bytes) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(pull_output, "_write_all", fail_write)

    with pytest.raises(OSError, match="write failed"):
        write_pull_output(_result(), output=output)

    assert not output.exists()
    assert _temporary_siblings(output) == []


@pytest.mark.parametrize(
    ("format_", "interactive", "output_file", "expected_paged"),
    [
        (PullOutputFormat.PRETTY, True, False, True),
        (PullOutputFormat.PRETTY, False, False, False),
        (PullOutputFormat.JSON, True, False, False),
        (PullOutputFormat.PRETTY, True, True, False),
    ],
)
def test_pager_is_only_eligible_for_interactive_pretty_stdout(
    tmp_path: Path,
    format_: PullOutputFormat,
    interactive: bool,
    output_file: bool,
    expected_paged: bool,
) -> None:
    stdout = _Stream(interactive=interactive)
    paged: list[str] = []
    output = tmp_path / "jobs.txt" if output_file else None

    receipt = write_pull_output(
        _result(),
        format_=format_,
        output=output,
        pager=True,
        stdout=stdout,
        pager_writer=paged.append,
    )

    assert receipt.paged is expected_paged
    if expected_paged:
        assert len(paged) == 1
        assert "Platform Engineer" in paged[0]
        assert stdout.getvalue() == ""
    else:
        assert paged == []
        if output is None:
            assert stdout.getvalue()
        else:
            assert output.read_text(encoding="utf-8")


def test_diagnostics_use_stderr_respect_verbosity_and_never_change_json() -> None:
    result = _result()
    stdout = _Stream()
    stderr = _Stream()
    diagnostics = (
        PullOutputDiagnostic("cache hit"),
        PullOutputDiagnostic("resolver detail", verbosity=1),
        PullOutputDiagnostic("provider payload detail", verbosity=2),
        PullOutputDiagnostic("stale evidence", essential=True),
    )

    write_pull_output(
        result,
        format_=PullOutputFormat.JSON,
        diagnostics=diagnostics,
        verbosity=1,
        stdout=stdout,
        stderr=stderr,
    )

    assert json.loads(stdout.getvalue()) == _projected_jobs(result)
    assert stderr.getvalue().splitlines() == [
        "cache hit",
        "resolver detail",
        "stale evidence",
    ]

    quiet_stdout = _Stream()
    quiet_stderr = _Stream()
    write_pull_output(
        result,
        format_=PullOutputFormat.JSON,
        diagnostics=diagnostics,
        quiet=True,
        verbosity=2,
        stdout=quiet_stdout,
        stderr=quiet_stderr,
    )
    assert quiet_stdout.getvalue() == stdout.getvalue()
    assert quiet_stderr.getvalue().splitlines() == ["stale evidence"]


def test_diagnostics_are_single_line_and_bounded() -> None:
    stderr = _Stream()

    write_pull_output(
        _result(),
        format_=PullOutputFormat.JSON,
        diagnostics=(PullOutputDiagnostic("line one\n" + "x" * 600),),
        stdout=_Stream(),
        stderr=stderr,
    )

    diagnostic = stderr.getvalue().rstrip("\n")
    assert "\n" not in diagnostic
    assert len(diagnostic) == 500
    assert diagnostic.endswith("...")


def test_pretty_panel_shows_coverage_persisted_and_board() -> None:
    stdout = _Stream(interactive=True)
    result = _result_with_coverage(
        coverage_class=PullCoverageClass.OVERLAY_PACKAGED,
        persisted=False,
    )

    write_pull_output(result, format_=PullOutputFormat.PRETTY, stdout=stdout)
    rendered = stdout.getvalue()

    assert "coverage=overlay_packaged" in rendered
    assert "persisted=false" in rendered
    assert "board=acme" in rendered


def test_result_diagnostics_use_resolution_and_verbosity_one_coverage() -> None:
    result = _result_with_coverage()
    messages = [(item.message, item.verbosity) for item in pull_result_diagnostics(result)]

    assert any(
        message.startswith("resolution=page_link") and verbosity == 2
        for message, verbosity in messages
    )
    assert all(not message.startswith("discovery=") for message, _verbosity in messages)
    assert ("coverage=ephemeral_new", 1) in messages


def test_raw_envelope_stays_snake_case_for_coverage_class() -> None:
    result = _result_with_coverage()
    envelope = result.raw_envelope()
    observability = envelope["observability"]
    assert isinstance(observability, dict)
    assert observability["coverage_class"] == "ephemeral_new"
    assert "coverageClass" not in observability


def test_json_jobs_identify_profile_and_exclude_observability() -> None:
    result = _result_with_coverage()
    stdout = _Stream()

    write_pull_output(result, format_=PullOutputFormat.JSON, stdout=stdout)
    jobs = json.loads(stdout.getvalue())

    assert jobs == _projected_jobs(result)
    assert jobs
    for job in jobs:
        assert job["profile"] == DEFAULT_CLI_PROFILE
        assert job["schemaVersion"] == 1
        assert "coverageClass" not in job
        assert "coverage_class" not in job
        assert "observability" not in job
        assert "RunMetrics" not in job


def test_json_jobs_honor_named_profile() -> None:
    result = _result()
    stdout = _Stream()

    write_pull_output(
        result,
        format_=PullOutputFormat.JSON,
        profile="core",
        stdout=stdout,
    )
    jobs = json.loads(stdout.getvalue())

    assert jobs == _projected_jobs(result, profile="core")
    assert jobs
    for job in jobs:
        assert job["profile"] == "core"
        assert job["schemaVersion"] == 1
        assert "raw_listing" not in job
        assert "raw_detail" not in job
