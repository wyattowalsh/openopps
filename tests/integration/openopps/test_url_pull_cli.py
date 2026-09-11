from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import httpx
import pytest
import respx
from typer.testing import CliRunner

import openopps.cli as cli_module
from openopps import __version__
from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.pull_models import (
    DiscoveryMethod,
    PullCoverageClass,
    PullDetailCoverageEvidence,
    PullDomainError,
    PullErrorCode,
    PullExecutionEvidence,
    PullHttpObservability,
    PullMembershipEvidence,
    PullMembershipScope,
    PullOperation,
    PullPersistenceFailureReason,
    PullPersistenceHandoffState,
    PullProvenance,
    PullRawPosting,
    PullResult,
    PullRetrievalMechanism,
    PullTerminalObservability,
    PullTerminalState,
)
from openopps.job_profiles import DEFAULT_CLI_PROFILE, project_job
from openopps.pull_service import OpenOppsStorePullPersistence
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore
from openopps.utils import stable_id


runner = CliRunner()
PULL_URL = "https://boards.greenhouse.io/acme/jobs/101"
CACHE_URL = "https://cache.example.test/openopps-pull"


def _projected_jobs(result: PullResult) -> list[dict[str, object]]:
    return [project_job(job, DEFAULT_CLI_PROFILE) for job in result.jobs]


def _invoke(tmp_path: Path, *args: str):
    return runner.invoke(
        cli_module.app,
        list(args),
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )


def _pull_result() -> PullResult:
    job = JobRecord(
        id="acme:greenhouse:101",
        board_key="acme",
        provider_id="greenhouse",
        remote_id="101",
        title="Platform Engineer",
        company="Acme",
        locations=["Remote"],
        posting_url=PULL_URL,
        raw_listing={"id": "101", "title": "Platform Engineer"},
        raw_detail={"content": "Build reliable systems."},
    )
    return PullResult(
        provenance=PullProvenance(
            requested_url=PULL_URL,
            resolved_url=PULL_URL,
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="greenhouse",
            requested_operation=PullOperation.AUTO,
            resolved_operation=PullOperation.GET,
            board_identity="acme",
            posting_identity="101",
            visited_urls=("https://boards.greenhouse.io/acme",),
            probed_slugs=("acme",),
        ),
        execution=PullExecutionEvidence(
            mechanism=PullRetrievalMechanism.NATIVE_GET,
        ),
        jobs=(job,),
        raw_postings=(
            PullRawPosting(
                job_id=job.id,
                listing=job.raw_listing,
                detail=job.raw_detail,
            ),
        ),
    )


def _list_pull_result() -> PullResult:
    native_get = _pull_result()
    return PullResult(
        provenance=PullProvenance(
            requested_url="https://boards.greenhouse.io/acme",
            resolved_url="https://boards.greenhouse.io/acme",
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="greenhouse",
            requested_operation=PullOperation.AUTO,
            resolved_operation=PullOperation.LIST,
            board_identity="acme",
            visited_urls=("https://boards.greenhouse.io/acme",),
        ),
        execution=PullExecutionEvidence(
            mechanism=PullRetrievalMechanism.LIST,
            membership=PullMembershipEvidence(
                scope=PullMembershipScope.LISTED,
                authoritative=True,
                complete=True,
                terminal_page_seen=True,
                pages_fetched=1,
                observed_count=1,
                advertised_count=1,
            ),
            detail_coverage=PullDetailCoverageEvidence(
                requested_count=1,
                completed_count=1,
            ),
        ),
        jobs=native_get.jobs,
        raw_postings=native_get.raw_postings,
    )


def _with_observability(
    result: PullResult,
    *,
    stale_fallbacks: int = 0,
) -> PullResult:
    observability = PullTerminalObservability(
        terminal_state=PullTerminalState.SUCCEEDED,
        requested_operation=result.provenance.requested_operation,
        resolved_operation=result.provenance.resolved_operation,
        retrieval_mechanism=result.execution.mechanism,
        provider_id=result.provenance.provider_id,
        discovery_method=result.provenance.discovery_method,
        resolver_visited_url_count=len(result.provenance.visited_urls),
        resolver_probe_count=len(result.provenance.probed_slugs),
        http=PullHttpObservability(
            logical_read_count=3,
            request_count=2,
            redirect_count=1,
            retry_count=1,
            cache_hit_count=1,
            cache_miss_count=1,
            cache_revalidation_count=1,
            cache_stale_fallback_count=stale_fallbacks,
            cache_write_count=1,
            encoded_bytes=128,
            decoded_bytes=256,
        ),
        membership=result.execution.membership,
        detail_coverage=result.execution.detail_coverage,
        duplicate_identity_count=(
            0 if result.execution.membership is not None else None
        ),
        provider_error_count=0,
        persistence_handoff=PullPersistenceHandoffState.NOT_REQUESTED,
        coverage_class=PullCoverageClass.EPHEMERAL_NEW,
        elapsed_milliseconds=37,
    )
    return PullResult(
        provenance=result.provenance,
        execution=result.execution,
        jobs=result.jobs,
        raw_postings=result.raw_postings,
        observability=observability,
    )


def _failed_observability(code: PullErrorCode) -> PullTerminalObservability:
    persistence_failed = code is PullErrorCode.PERSISTENCE_FAILED
    return PullTerminalObservability(
        terminal_state=PullTerminalState.FAILED,
        error_code=code,
        requested_operation=PullOperation.AUTO,
        resolved_operation=PullOperation.GET,
        retrieval_mechanism=PullRetrievalMechanism.NATIVE_GET,
        provider_id="greenhouse",
        discovery_method=DiscoveryMethod.NATIVE_URL,
        resolver_visited_url_count=1,
        resolver_probe_count=0,
        http=PullHttpObservability(
            logical_read_count=2,
            request_count=2,
            retry_count=1,
            cache_miss_count=1,
            encoded_bytes=64,
            decoded_bytes=128,
        ),
        provider_error_count=0 if persistence_failed else 1,
        persistence_handoff=(
            PullPersistenceHandoffState.FAILED
            if persistence_failed
            else PullPersistenceHandoffState.NOT_ATTEMPTED
        ),
        coverage_class=PullCoverageClass.NOT_APPLICABLE,
        persistence_reason=(
            PullPersistenceFailureReason.PERSISTENCE_UNAVAILABLE
            if persistence_failed
            else None
        ),
        elapsed_milliseconds=23,
    )


class _AsyncClientContext:
    def __init__(
        self,
        settings: object,
        calls: list[tuple[object, object]],
    ) -> None:
        self.settings = settings
        self.calls = calls

    async def __aenter__(self) -> object:
        client = object()
        self.calls.append((self.settings, client))
        return client

    async def __aexit__(self, *args: object) -> None:
        return None


class _PullService:
    def __init__(
        self,
        result: PullResult | None = None,
        error: PullDomainError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    async def pull(
        self,
        client: object,
        url: str,
        **kwargs: object,
    ) -> PullResult:
        self.calls.append((client, url, kwargs))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class _CachedPullService:
    """Exercise the real shared HTTP cache through the CLI client seam."""

    def __init__(self, result: PullResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def pull(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs: object,
    ) -> PullResult:
        settings = getattr(client, "_openopps_settings")
        assert isinstance(settings, OpenOppsSettings)
        assert await retrying_json_request(settings)(client, "GET", CACHE_URL) == {
            "cached": True
        }
        self.calls.append({"url": url, **kwargs})
        return self.result


def _install_pull_seams(
    monkeypatch: pytest.MonkeyPatch,
    service: _PullService,
) -> tuple[list[object], list[tuple[object, object]], list[bool]]:
    settings_calls: list[object] = []
    client_calls: list[tuple[object, object]] = []
    persist_calls: list[bool] = []

    def from_settings(
        settings: object,
        *,
        persist: bool = False,
        persistence: object | None = None,
        **kwargs: object,
    ) -> _PullService:
        del persistence, kwargs
        settings_calls.append(settings)
        persist_calls.append(persist)
        return service

    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(from_settings),
    )
    monkeypatch.setattr(
        cli_module,
        "build_async_client",
        lambda settings: _AsyncClientContext(settings, client_calls),
    )
    return settings_calls, client_calls, persist_calls


def test_jobs_pull_forwards_every_control_and_keeps_raw_stdout_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _pull_result()
    service = _PullService(result=result)
    settings_calls, client_calls, persist_calls = _install_pull_seams(
        monkeypatch, service
    )

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--operation",
        "get",
        "--direct",
        "--no-probe",
        "--no-board-scan",
        "--include-unlisted",
        "--no-save",
        "--raw",
        "--format",
        "json",
        "--pager",
        "--refresh-cache",
        "--quiet",
        "-v",
        "-v",
    )

    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.stdout) == result.raw_envelope()
    assert invocation.stderr == ""
    assert persist_calls == [False]
    assert len(settings_calls) == 1
    assert getattr(settings_calls[0], "cache_refresh") is True
    assert len(client_calls) == 1
    client = client_calls[0][1]
    assert service.calls == [
        (
            client,
            PULL_URL,
            {
                "operation": PullOperation.GET,
                "direct": True,
                "probe": False,
                "no_board_scan": True,
                "include_unlisted": True,
                "no_save": True,
            },
        )
    ]


def test_jobs_pull_defaults_ephemeral_without_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _PullService(result=_pull_result())
    settings_calls, _client_calls, persist_calls = _install_pull_seams(
        monkeypatch, service
    )

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--format",
        "json",
    )

    assert invocation.exit_code == 0, invocation.output
    assert service.calls[0][2]["no_save"] is True
    assert persist_calls == [False]
    assert getattr(settings_calls[0], "cache_refresh") is False


def test_jobs_pull_explicit_save_reaches_the_persistence_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _PullService(result=_pull_result())
    _settings_calls, _client_calls, persist_calls = _install_pull_seams(
        monkeypatch, service
    )

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--save",
        "--format",
        "json",
    )

    assert invocation.exit_code == 0, invocation.output
    assert service.calls[0][2]["no_save"] is False
    assert persist_calls == [True]


def test_root_url_shorthand_and_explicit_command_share_the_same_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _PullService(result=_pull_result())
    _install_pull_seams(monkeypatch, service)

    shorthand = _invoke(
        tmp_path,
        "--no-intro",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
    )
    explicit = _invoke(
        tmp_path,
        "--no-intro",
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
    )

    assert shorthand.exit_code == 0, shorthand.output
    assert explicit.exit_code == 0, explicit.output
    assert shorthand.stdout == explicit.stdout
    assert shorthand.stderr == explicit.stderr == ""
    assert len(service.calls) == 2
    assert service.calls[0][1:] == service.calls[1][1:]


def test_root_url_dispatch_preserves_existing_jobs_show_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.init_db()
    store.upsert_source(
        SourceRecord(
            key="manual",
            url="https://careers.example.test/acme",
            provider_id="manual",
        )
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="manual",
                remote_id="acme",
                name="Acme",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id=stable_id("manual", "acme", "greenhouse"),
                source_key="manual",
                board_key="acme",
                provider_id="greenhouse",
                support_level=ProviderSupport.JOBS,
            )
        ]
    )
    job = _pull_result().jobs[0]
    store.upsert_jobs([job])
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(
            lambda _settings, **_kwargs: pytest.fail("URL pull must not be built")
        ),
    )

    invocation = _invoke(tmp_path, "jobs", "show", job.id)

    assert invocation.exit_code == 0, invocation.output
    shown = json.loads(invocation.stdout)
    assert shown["id"] == job.id
    assert shown["title"] == "Platform Engineer"


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    [
        (PullErrorCode.UNRECOGNIZED_TARGET, 3),
        (PullErrorCode.UNSUPPORTED_OPERATION, 4),
        (PullErrorCode.INCOMPLETE_RESULT, 5),
        (PullErrorCode.UNSAFE_URL, 6),
        (PullErrorCode.BUDGET_EXCEEDED, 7),
        (PullErrorCode.TRANSPORT_FAILED, 8),
        (PullErrorCode.PERSISTENCE_FAILED, 9),
    ],
)
def test_pull_domain_errors_use_stable_process_statuses_and_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: PullErrorCode,
    expected_exit: int,
) -> None:
    service = _PullService(
        error=PullDomainError(code, "Bounded pull failure.", hint="Use a safe retry.")
    )
    _install_pull_seams(monkeypatch, service)

    invocation = _invoke(tmp_path, "jobs", "pull", PULL_URL, "--no-save")

    assert invocation.exit_code == expected_exit
    assert invocation.stdout == ""
    assert f"Error [{code.value}]: Bounded pull failure." in invocation.stderr
    assert "Hint: Use a safe retry." in invocation.stderr


@pytest.mark.parametrize("format_", ["pretty", "table"])
def test_raw_human_format_is_usage_error_before_service_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    format_: str,
) -> None:
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(
            lambda _settings, **_kwargs: pytest.fail("service must not be built")
        ),
    )

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--raw",
        "--format",
        format_,
    )

    assert invocation.exit_code == 2
    assert invocation.stdout == ""
    assert "--raw requires auto, json, or jsonl output" in invocation.stderr


def test_pull_output_file_is_atomic_output_boundary_not_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _pull_result()
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)
    output = tmp_path / "pull.json"

    invocation = _invoke(
        tmp_path,
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "--output",
        str(output),
    )

    assert invocation.exit_code == 0, invocation.output
    assert invocation.stdout == ""
    assert invocation.stderr == ""
    assert json.loads(output.read_text()) == _projected_jobs(result)
    assert list(tmp_path.glob(".pull.json.*.tmp")) == []


def test_pull_output_file_failure_is_concise_and_leaves_no_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _PullService(result=_pull_result())
    _install_pull_seams(monkeypatch, service)
    output_directory = tmp_path / "already-a-directory"
    output_directory.mkdir()

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "--output",
        str(output_directory),
    )

    assert invocation.exit_code == 1
    assert invocation.stdout == ""
    assert "Error: Unable to render or write pull output:" in invocation.stderr
    assert "Traceback" not in invocation.stderr
    assert output_directory.is_dir()
    assert list(tmp_path.glob(".already-a-directory.*.tmp")) == []


def test_pull_verbosity_uses_stderr_without_corrupting_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _pull_result()
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "-v",
        "-v",
    )

    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.stdout) == _projected_jobs(result)
    assert (
        "provider=greenhouse operation=get jobs=1 persisted=false" in invocation.stderr
    )
    assert (
        "resolution=native_url mechanism=native_get visited=1 probed=1"
        in invocation.stderr
    )
    assert "cache" not in invocation.stderr.lower()
    assert "retry" not in invocation.stderr.lower()


def test_list_pull_diagnostics_only_report_validated_execution_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _list_pull_result()
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        "https://boards.greenhouse.io/acme",
        "--no-save",
        "--format",
        "json",
        "-v",
        "-v",
    )

    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.stdout) == _projected_jobs(result)
    assert invocation.stderr.splitlines() == [
        "provider=greenhouse operation=list jobs=1 persisted=false",
        "resolution=native_url mechanism=list visited=1 probed=0",
        (
            "membership=listed authoritative=true complete=true pages=1 "
            "observed=1 advertised=1"
        ),
        "details=complete required=false requested=1 completed=1 failed=0",
    ]


def test_pull_observability_is_raw_machine_evidence_and_progressive_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _with_observability(_pull_result())
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)

    verbose = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--raw",
        "--format",
        "json",
        "-v",
    )
    very_verbose = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--raw",
        "--format",
        "json",
        "-v",
        "-v",
    )

    assert verbose.exit_code == very_verbose.exit_code == 0
    assert (
        json.loads(verbose.stdout)
        == json.loads(very_verbose.stdout)
        == (result.raw_envelope())
    )
    assert "terminal=succeeded elapsed_ms=37 persistence=not_requested" in (
        verbose.stderr
    )
    assert "coverage=ephemeral_new" in verbose.stderr
    assert "http=" not in verbose.stderr
    assert "cache=" not in verbose.stderr
    assert (
        "http=logical_reads:3 requests:2 redirects:1 retries:1 "
        "encoded_bytes:128 decoded_bytes:256"
    ) in very_verbose.stderr
    assert (
        "cache=hits:1 misses:1 revalidations:1 stale_fallbacks:0 writes:1 bypasses:0"
    ) in very_verbose.stderr


def test_stale_cache_warning_is_essential_even_when_quiet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _with_observability(_pull_result(), stale_fallbacks=1)
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)

    normal = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
    )
    quiet = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "--quiet",
        "-v",
        "-v",
    )

    assert normal.exit_code == quiet.exit_code == 0
    assert (
        json.loads(normal.stdout)
        == json.loads(quiet.stdout)
        == (_projected_jobs(result))
    )
    assert "Warning: URL pull used stale cache fallback count=1" in normal.stderr
    assert "Warning: URL pull used stale cache fallback count=1" in quiet.stderr
    assert "terminal=" not in quiet.stderr
    assert "http=" not in quiet.stderr
    assert "cache=" not in quiet.stderr


def test_failed_pull_observability_respects_verbosity_and_quiet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    error = PullDomainError(
        PullErrorCode.TRANSPORT_FAILED,
        "Bounded pull failure.",
        hint="Use a safe retry.",
        observability=_failed_observability(PullErrorCode.TRANSPORT_FAILED),
    )
    service = _PullService(error=error)
    _install_pull_seams(monkeypatch, service)

    verbose = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "-v",
        "-v",
    )
    quiet = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--quiet",
        "-v",
        "-v",
    )

    assert verbose.exit_code == quiet.exit_code == 8
    assert verbose.stdout == quiet.stdout == ""
    assert "Error [transport_failed]: Bounded pull failure." in verbose.stderr
    assert "terminal=failed elapsed_ms=23 persistence=not_attempted" in verbose.stderr
    assert "http=logical_reads:2 requests:2" in verbose.stderr
    assert "cache=hits:0 misses:1" in verbose.stderr
    assert "Error [transport_failed]: Bounded pull failure." in quiet.stderr
    assert "Hint: Use a safe retry." in quiet.stderr
    assert "terminal=" not in quiet.stderr
    assert "http=" not in quiet.stderr


@respx.mock
def test_no_save_keeps_operational_ledger_empty_while_shared_cache_writes_and_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _pull_result()
    service = _CachedPullService(result)
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(lambda _settings, **_kwargs: service),
    )
    route = respx.get(CACHE_URL).mock(
        return_value=httpx.Response(200, json={"cached": True})
    )

    first = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
    )
    second = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
    )

    assert first.exit_code == second.exit_code == 0
    assert (
        json.loads(first.stdout)
        == json.loads(second.stdout)
        == _projected_jobs(result)
    )
    assert route.call_count == 1
    assert [call["no_save"] for call in service.calls] == [True, True]
    with sqlite3.connect(tmp_path / "openopps.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' "
                "and name not like 'sqlite_%'"
            )
        }
        cached_rows = connection.execute("select count(*) from http_cache").fetchone()
    assert tables == {"http_cache", "http_cache_metadata"}
    assert cached_rows == (1,)


def test_root_dispatch_preserves_help_version_empty_and_unknown_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(
            lambda _settings, **_kwargs: pytest.fail("service must not be built")
        ),
    )

    root_help = _invoke(tmp_path, "--help")
    url_help = _invoke(tmp_path, PULL_URL, "--help")
    version = _invoke(tmp_path, "--version", PULL_URL)
    empty = _invoke(tmp_path)
    malformed = _invoke(tmp_path, "http://example.com/jobs")
    unsafe = _invoke(tmp_path, "https://localhost/jobs")
    unknown = _invoke(tmp_path, "pulll")

    assert root_help.exit_code == 0
    assert "jobs" in root_help.output
    assert url_help.exit_code == 0
    assert "--operation" in url_help.output
    assert "--no-board-scan" in url_help.output
    assert version.exit_code == 0
    assert version.output.strip() == f"openopps {__version__}"
    assert empty.exit_code == 2
    assert "Missing command" in empty.stderr
    for result in (malformed, unsafe, unknown):
        assert result.exit_code == 2
        assert "No such command" in result.stderr


def test_pull_help_lists_every_public_control() -> None:
    result = runner.invoke(
        cli_module.app,
        ["jobs", "pull", "--help"],
        terminal_width=140,
    )

    assert result.exit_code == 0
    for control in (
        "--operation",
        "--direct",
        "--probe",
        "--no-probe",
        "--board-scan",
        "--no-board-scan",
        "--include-unlisted",
        "--save",
        "--no-save",
        "--raw",
        "--format",
        "--output",
        "--pager",
        "--refresh-cache",
        "--quiet",
        "--verbose",
        "--metrics-file",
    ):
        assert control in result.output
    assert "--metrics-file" in result.output
    assert "catalog sync only" in result.output
    flat_help = " ".join(result.output.split())
    assert "default: no-save" in flat_help
    assert "save/no-save is independent of HTTP cache reads and writes" in flat_help
    assert "--refresh-cache controls only cache freshness" in flat_help
    assert "exit with status 3-9" in flat_help
    assert "ephemeral" in result.output.lower()
    assert "until local pull persistence is enabled" not in result.output
    assert "overlay-outcomes" not in result.output


def test_metrics_file_is_camel_case_and_quiet_still_writes_without_changing_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _with_observability(_pull_result())
    service = _PullService(result=result)
    _install_pull_seams(monkeypatch, service)
    metrics_path = tmp_path / "nested" / "pull-metrics.json"

    verbose = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "--metrics-file",
        str(metrics_path),
    )
    quiet = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--no-save",
        "--format",
        "json",
        "--quiet",
        "--metrics-file",
        str(metrics_path),
    )

    assert verbose.exit_code == quiet.exit_code == 0, verbose.output
    assert json.loads(verbose.stdout) == _projected_jobs(result)
    assert quiet.stdout == verbose.stdout
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["coverageClass"] == "ephemeral_new"
    assert payload["terminalState"] == "succeeded"
    assert "coverage_class" not in payload
    assert "jobs" not in payload
    assert list(metrics_path.parent.glob(f".{metrics_path.name}.*.tmp")) == []


def test_failed_save_hint_names_ledger_write_not_raw_unavailable_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    error = PullDomainError(
        PullErrorCode.PERSISTENCE_FAILED,
        "The validated pull could not be saved to the local ledger.",
        hint=(
            "Retry --save after the ledger is writable, or omit --save to keep "
            "the ephemeral default."
        ),
        observability=_failed_observability(PullErrorCode.PERSISTENCE_FAILED),
    )
    service = _PullService(error=error)
    _install_pull_seams(monkeypatch, service)

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--save",
        "--format",
        "json",
    )

    assert invocation.exit_code == 9
    assert "persistence_unavailable" not in invocation.stderr
    assert "storage join" not in invocation.stderr.lower()
    assert "local ledger" in invocation.stderr.lower()
    assert "Hint:" in invocation.stderr


def test_jobs_pull_save_applies_get_through_store_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _pull_result()
    applied: list[str] = []

    class _PersistingService:
        def __init__(self, persistence: OpenOppsStorePullPersistence) -> None:
            self.persistence = persistence

        async def pull(self, client: httpx.AsyncClient, url: str, **kwargs: object):
            del client, url
            assert kwargs["no_save"] is False
            await self.persistence.persist(result)
            return result.model_copy(update={"persisted": True})

    def from_settings(
        settings: OpenOppsSettings,
        *,
        persist: bool = False,
        persistence: object | None = None,
        **kwargs: object,
    ) -> _PersistingService:
        del persistence, kwargs
        assert persist is True
        store = OpenOppsStore(settings)
        original_get = store.apply_url_pull_get

        def spy_get(payload: PullResult) -> object:
            applied.append("get")
            return original_get(payload)

        store.apply_url_pull_get = spy_get  # type: ignore[method-assign]
        return _PersistingService(OpenOppsStorePullPersistence(store))

    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(from_settings),
    )

    invocation = _invoke(
        tmp_path,
        "jobs",
        "pull",
        PULL_URL,
        "--save",
        "--format",
        "json",
    )

    db_path = tmp_path / "openopps.db"
    assert invocation.exit_code == 0, invocation.output
    assert applied == ["get"]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM url_pull_runs").fetchone()[
            0
        ] == 1
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM job_sync_runs").fetchone()[
            0
        ] == 0


def test_admin_sources_help_omits_overlay_outcomes() -> None:
    result = runner.invoke(
        cli_module.app,
        ["admin", "sources", "--help"],
        terminal_width=140,
    )

    assert result.exit_code == 0
    assert "overlay-outcomes" not in result.output
    assert "overlay_outcomes" not in result.output
