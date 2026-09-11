from __future__ import annotations

import pytest
from pydantic import ValidationError

from openopps.models import JobRecord
from openopps.pull_models import (
    DiscoveryMethod,
    PullCoverageClass,
    PullDetailCoverageEvidence,
    PullDetailCoverageStatus,
    PullDomainError,
    PullErrorCode,
    PullExecutionEvidence,
    PullHttpObservability,
    PullMembershipEvidence,
    PullMembershipScope,
    PullOperation,
    PullPersistenceFailureReason,
    PullPersistenceHandoffState,
    PullProcessStatus,
    PullProvenance,
    PullRawPosting,
    PullResult,
    PullRetrievalMechanism,
    PullTerminalObservability,
    PullTerminalState,
    process_status_for_error,
    sanitize_public_pull_url,
)


def _job(
    remote_id: str = "123",
    *,
    board_key: str = "acme",
    provider_id: str = "greenhouse",
) -> JobRecord:
    return JobRecord(
        id=f"{board_key}:{provider_id}:{remote_id}",
        board_key=board_key,
        provider_id=provider_id,
        remote_id=remote_id,
        title="Engineer",
        posting_url=f"https://boards.greenhouse.io/acme/jobs/{remote_id}",
        raw_listing={"id": remote_id, "title": "Engineer"},
        raw_detail={"content": "Build reliable systems."},
    )


def _raw(job: JobRecord) -> PullRawPosting:
    return PullRawPosting(
        job_id=job.id,
        listing=job.raw_listing,
        detail=job.raw_detail,
    )


def _native_execution() -> PullExecutionEvidence:
    return PullExecutionEvidence(
        mechanism=PullRetrievalMechanism.NATIVE_GET,
    )


def _list_execution(
    *,
    mechanism: PullRetrievalMechanism = PullRetrievalMechanism.LIST,
    scope: PullMembershipScope = PullMembershipScope.LISTED,
    observed_count: int = 0,
    requested_details: int = 0,
    completed_details: int = 0,
    failed_details: int = 0,
    required_details: bool = False,
) -> PullExecutionEvidence:
    return PullExecutionEvidence(
        mechanism=mechanism,
        membership=PullMembershipEvidence(
            scope=scope,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=observed_count,
            advertised_count=observed_count,
        ),
        detail_coverage=PullDetailCoverageEvidence(
            required=required_details,
            requested_count=requested_details,
            completed_count=completed_details,
            failed_count=failed_details,
        ),
    )


def _provenance(
    *,
    requested_operation: PullOperation = PullOperation.AUTO,
    resolved_operation: PullOperation = PullOperation.GET,
) -> PullProvenance:
    return PullProvenance(
        requested_url="https://careers.example.com/jobs?token=secret#apply",
        resolved_url="https://boards.greenhouse.io/acme/jobs/123?gh_jid=123",
        discovery_method=DiscoveryMethod.PAGE_LINK,
        provider_id="greenhouse",
        requested_operation=requested_operation,
        resolved_operation=resolved_operation,
        board_identity="acme",
        posting_identity="123" if resolved_operation == PullOperation.GET else None,
        visited_urls=(
            "https://careers.example.com/jobs?token=secret",
            "https://boards.greenhouse.io/acme/jobs/123?gh_jid=123",
        ),
        probed_slugs=("acme",),
    )


def _native_terminal_observability(
    *,
    persistence_handoff: PullPersistenceHandoffState = (
        PullPersistenceHandoffState.NOT_REQUESTED
    ),
) -> PullTerminalObservability:
    return PullTerminalObservability(
        terminal_state=PullTerminalState.SUCCEEDED,
        requested_operation=PullOperation.AUTO,
        resolved_operation=PullOperation.GET,
        retrieval_mechanism=PullRetrievalMechanism.NATIVE_GET,
        provider_id="greenhouse",
        discovery_method=DiscoveryMethod.PAGE_LINK,
        resolver_visited_url_count=2,
        resolver_probe_count=1,
        http=PullHttpObservability(
            logical_read_count=3,
            request_count=2,
            redirect_count=1,
            retry_count=1,
            cache_miss_count=1,
            cache_write_count=1,
            encoded_bytes=128,
            decoded_bytes=256,
        ),
        provider_error_count=0,
        persistence_handoff=persistence_handoff,
        coverage_class=PullCoverageClass.EPHEMERAL_NEW,
        elapsed_milliseconds=25,
    )


def test_pull_enums_have_stable_public_values() -> None:
    assert [item.value for item in PullOperation] == ["auto", "list", "get"]
    assert [item.value for item in PullCoverageClass] == [
        "catalog_route",
        "overlay_packaged",
        "url_pull_reserved",
        "ephemeral_new",
        "not_applicable",
    ]
    assert [item.value for item in PullPersistenceFailureReason] == [
        "persistence_unavailable",
        "ledger_write_failed",
    ]
    assert PullErrorCode.RATE_LIMITED.value == "rate_limited"


def test_pull_provenance_sanitizes_query_and_fragment_material() -> None:
    provenance = _provenance()

    assert provenance.requested_url == "https://careers.example.com/jobs"
    assert provenance.resolved_url == "https://boards.greenhouse.io/acme/jobs/123"
    assert provenance.visited_urls == (
        "https://careers.example.com/jobs",
        "https://boards.greenhouse.io/acme/jobs/123",
    )


def test_pull_url_sanitizer_has_query_and_fragment_equivalent_identity() -> None:
    assert sanitize_public_pull_url(
        "HTTPS://CAREERS.EXAMPLE.COM/jobs?token=secret#apply"
    ) == sanitize_public_pull_url("https://careers.example.com/jobs")
    assert sanitize_public_pull_url("https://careers.example.com") == (
        "https://careers.example.com/"
    )


def test_resolved_get_provenance_requires_exact_posting_identity() -> None:
    with pytest.raises(ValidationError, match="posting identity"):
        PullProvenance(
            requested_url="https://careers.example.com/jobs/123",
            resolved_url="https://boards.greenhouse.io/acme/jobs/123",
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="greenhouse",
            requested_operation=PullOperation.GET,
            resolved_operation=PullOperation.GET,
            board_identity="acme",
        )

    with pytest.raises(ValidationError, match="explicit requested operation"):
        _provenance(
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.GET,
        )

    with pytest.raises(ValidationError, match="resolved operation"):
        PullProvenance(
            requested_url="https://careers.example.com/jobs",
            resolved_url="https://boards.greenhouse.io/acme",
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="greenhouse",
            requested_operation=PullOperation.AUTO,
            resolved_operation=PullOperation.AUTO,
            board_identity="acme",
        )


def test_pull_provenance_rejects_duplicate_trace_entries() -> None:
    payload = _provenance().model_dump(mode="python")
    payload["visited_urls"] = (
        "https://careers.example.com/jobs",
        "https://careers.example.com/jobs",
    )

    with pytest.raises(ValidationError, match="visited URLs"):
        PullProvenance.model_validate(payload)


def test_pull_result_raw_envelope_preserves_listing_and_detail_roles() -> None:
    job = _job()
    result = PullResult(
        provenance=_provenance(),
        execution=_native_execution(),
        jobs=(job,),
        raw_postings=(_raw(job),),
    )

    raw = result.raw_envelope()
    assert set(raw) == {"provenance", "execution", "postings"}
    assert raw["execution"] == {
        "mechanism": "native_get",
        "membership": None,
        "detail_coverage": None,
    }
    assert raw["postings"] == [
        {
            "listing": {"id": "123", "title": "Engineer"},
            "detail": {"content": "Build reliable systems."},
        }
    ]
    assert result.normalized_jobs()[0]["provider_id"] == "greenhouse"


def test_terminal_observability_is_machine_readable_and_payload_free() -> None:
    job = _job()
    observability = _native_terminal_observability()
    result = PullResult(
        provenance=_provenance(),
        execution=_native_execution(),
        jobs=(job,),
        raw_postings=(_raw(job),),
        observability=observability,
    )

    raw = result.raw_envelope()
    assert raw["observability"] == observability.model_dump(mode="json")
    serialized = str(raw["observability"])
    assert "token=secret" not in serialized
    assert "boards.greenhouse.io" not in serialized
    assert observability.http.request_count == 2
    assert observability.http.cache_miss_count == 1
    assert observability.http.encoded_bytes == 128
    assert observability.http.decoded_bytes == 256


def test_domain_error_accepts_one_bounded_terminal_failure_snapshot() -> None:
    observability = PullTerminalObservability(
        terminal_state=PullTerminalState.FAILED,
        error_code=PullErrorCode.TRANSPORT_FAILED,
        requested_operation=PullOperation.GET,
        resolved_operation=PullOperation.GET,
        retrieval_mechanism=PullRetrievalMechanism.NATIVE_GET,
        provider_id="greenhouse",
        discovery_method=DiscoveryMethod.NATIVE_URL,
        resolver_visited_url_count=1,
        resolver_probe_count=0,
        http=PullHttpObservability(request_count=2, retry_count=1),
        provider_error_count=1,
        persistence_handoff=PullPersistenceHandoffState.NOT_ATTEMPTED,
        elapsed_milliseconds=10,
    )
    error = PullDomainError(
        PullErrorCode.TRANSPORT_FAILED,
        "Pull failed.",
        hint="Retry later.",
    )

    assert error.attach_observability(observability) is error
    assert error.observability == observability
    assert "Retry later" not in str(observability.model_dump(mode="json"))


def test_pull_result_rejects_observability_that_disagrees_with_evidence() -> None:
    job = _job()
    mismatched = _native_terminal_observability().model_copy(
        update={"provider_id": "lever"}
    )

    with pytest.raises(ValidationError, match="observability provider"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(job,),
            raw_postings=(_raw(job),),
            observability=mismatched,
        )


def test_raw_posting_represents_unavailable_and_captured_empty_separately() -> None:
    unavailable = PullRawPosting(job_id="job-1", listing=None, detail=None)
    captured_empty = PullRawPosting(job_id="job-2", listing={}, detail={})

    assert unavailable.model_dump(mode="json") == {
        "job_id": "job-1",
        "listing": None,
        "detail": None,
    }
    assert captured_empty.model_dump(mode="json") == {
        "job_id": "job-2",
        "listing": {},
        "detail": {},
    }


def test_get_result_requires_exactly_one_job_and_matching_raw_evidence() -> None:
    with pytest.raises(ValidationError, match="exactly one job"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(),
            raw_postings=(),
        )

    job = _job()
    with pytest.raises(ValidationError, match="raw evidence"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(job,),
            raw_postings=(PullRawPosting(job_id="different", listing={}, detail={}),),
        )


def test_pull_result_binds_provider_board_and_exact_posting_identity() -> None:
    wrong_provider = _job(provider_id="lever")
    with pytest.raises(ValidationError, match="provenance provider"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(wrong_provider,),
            raw_postings=(_raw(wrong_provider),),
        )

    wrong_board = _job(board_key="other")
    with pytest.raises(ValidationError, match="provenance board identity"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(wrong_board,),
            raw_postings=(_raw(wrong_board),),
        )

    wrong_identity = _job("different")
    with pytest.raises(ValidationError, match="provenance posting identity"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(wrong_identity,),
            raw_postings=(_raw(wrong_identity),),
        )


@pytest.mark.parametrize(
    "raw",
    [
        PullRawPosting(
            job_id="acme:greenhouse:123",
            listing={"id": "different"},
            detail={"content": "Build reliable systems."},
        ),
        PullRawPosting(
            job_id="acme:greenhouse:123",
            listing={"id": "123", "title": "Engineer"},
            detail={"content": "different"},
        ),
        PullRawPosting(
            job_id="acme:greenhouse:123",
            listing=None,
            detail={"content": "Build reliable systems."},
        ),
        PullRawPosting(
            job_id="acme:greenhouse:123",
            listing={"id": "123", "title": "Engineer"},
            detail=None,
        ),
    ],
)
def test_pull_result_rejects_unbound_raw_evidence(raw: PullRawPosting) -> None:
    with pytest.raises(ValidationError, match="raw (listing|detail) evidence"):
        PullResult(
            provenance=_provenance(),
            execution=_native_execution(),
            jobs=(_job(),),
            raw_postings=(raw,),
        )


def test_pull_result_rechecks_unchecked_copies_and_nested_raw_mutation() -> None:
    job = _job()
    result = PullResult(
        provenance=_provenance(),
        execution=_native_execution(),
        jobs=(job,),
        raw_postings=(_raw(job),),
    )
    result.jobs[0].raw_listing["id"] = "mutated"

    with pytest.raises(ValueError, match="raw listing evidence"):
        result.raw_envelope()

    fresh_job = _job()
    copied = PullResult(
        provenance=_provenance(),
        execution=_native_execution(),
        jobs=(fresh_job,),
        raw_postings=(_raw(fresh_job),),
    ).model_copy(
        update={"provenance": _provenance().model_copy(update={"provider_id": "lever"})}
    )

    with pytest.raises(ValueError, match="provenance provider"):
        copied.normalized_jobs()


def test_list_result_accepts_empty_complete_normalized_projection() -> None:
    result = PullResult(
        provenance=_provenance(
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
        ),
        execution=_list_execution(),
        jobs=(),
        raw_postings=(),
    )

    assert result.normalized_jobs() == []
    assert result.raw_envelope()["postings"] == []


@pytest.mark.parametrize(
    "scope",
    [PullMembershipScope.LISTED, PullMembershipScope.ALL_PUBLIC],
)
def test_empty_list_preserves_membership_scope(scope: PullMembershipScope) -> None:
    result = PullResult(
        provenance=_provenance(
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
        ),
        execution=_list_execution(scope=scope),
    )

    execution = result.raw_envelope()["execution"]
    assert isinstance(execution, dict)
    assert execution["membership"] == {
        "scope": scope.value,
        "authoritative": True,
        "complete": True,
        "terminal_page_seen": True,
        "pages_fetched": 1,
        "observed_count": 0,
        "advertised_count": 0,
    }


def test_optional_partial_detail_coverage_has_deterministic_status() -> None:
    first = _job("123")
    second = _job("456")
    result = PullResult(
        provenance=_provenance(
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
        ),
        execution=_list_execution(
            observed_count=2,
            requested_details=2,
            completed_details=1,
            failed_details=1,
        ),
        jobs=(first, second),
        raw_postings=(_raw(first), _raw(second)),
    )

    assert result.execution.detail_coverage is not None
    assert result.execution.detail_coverage.status == PullDetailCoverageStatus.PARTIAL
    serialized = result.raw_envelope()["execution"]
    assert isinstance(serialized, dict)
    assert serialized["detail_coverage"] == {
        "required": False,
        "requested_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "status": "partial",
    }


def test_empty_required_detail_membership_is_vacuously_complete() -> None:
    result = PullResult(
        provenance=_provenance(
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
        ),
        execution=_list_execution(required_details=True),
    )

    assert result.execution.detail_coverage is not None
    assert result.execution.detail_coverage.status == PullDetailCoverageStatus.COMPLETE
    serialized = result.raw_envelope()["execution"]
    assert isinstance(serialized, dict)
    assert serialized["detail_coverage"] == {
        "required": True,
        "requested_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "status": "complete",
    }


def test_board_scan_get_preserves_full_membership_but_returns_exact_job() -> None:
    job = _job()
    result = PullResult(
        provenance=_provenance(),
        execution=_list_execution(
            mechanism=PullRetrievalMechanism.BOARD_SCAN_GET,
            observed_count=3,
        ),
        jobs=(job,),
        raw_postings=(_raw(job),),
    )

    assert result.execution.membership is not None
    assert result.execution.membership.observed_count == 3
    assert result.execution.mechanism == PullRetrievalMechanism.BOARD_SCAN_GET


def test_execution_evidence_must_match_operation_and_required_detail_barrier() -> None:
    job = _job()
    with pytest.raises(ValidationError, match="resolved list requires list"):
        PullResult(
            provenance=_provenance(
                requested_operation=PullOperation.LIST,
                resolved_operation=PullOperation.LIST,
            ),
            execution=_list_execution(
                mechanism=PullRetrievalMechanism.BOARD_SCAN_GET,
                observed_count=1,
            ),
            jobs=(job,),
            raw_postings=(_raw(job),),
        )

    with pytest.raises(ValidationError, match="native get cannot carry"):
        PullExecutionEvidence(
            mechanism=PullRetrievalMechanism.NATIVE_GET,
            membership=_list_execution().membership,
        )

    with pytest.raises(ValidationError, match="complete required detail"):
        PullResult(
            provenance=_provenance(
                requested_operation=PullOperation.LIST,
                resolved_operation=PullOperation.LIST,
            ),
            execution=_list_execution(
                observed_count=1,
                requested_details=1,
                failed_details=1,
                required_details=True,
            ),
            jobs=(job,),
            raw_postings=(_raw(job),),
        )

    second = _job("456")
    with pytest.raises(ValidationError, match="span full membership"):
        PullResult(
            provenance=_provenance(
                requested_operation=PullOperation.LIST,
                resolved_operation=PullOperation.LIST,
            ),
            execution=_list_execution(
                observed_count=2,
                requested_details=1,
                completed_details=1,
                required_details=True,
            ),
            jobs=(job, second),
            raw_postings=(_raw(job), _raw(second)),
        )


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (PullErrorCode.UNRECOGNIZED_TARGET, PullProcessStatus.TARGET_FAILED),
        (PullErrorCode.UNSUPPORTED_TARGET, PullProcessStatus.UNSUPPORTED),
        (PullErrorCode.UNSUPPORTED_OPERATION, PullProcessStatus.UNSUPPORTED),
        (PullErrorCode.AMBIGUOUS_TARGET, PullProcessStatus.TARGET_FAILED),
        (PullErrorCode.POSTING_NOT_FOUND, PullProcessStatus.TARGET_FAILED),
        (PullErrorCode.INCOMPLETE_RESULT, PullProcessStatus.EVIDENCE_FAILED),
        (PullErrorCode.NON_AUTHORITATIVE, PullProcessStatus.EVIDENCE_FAILED),
        (PullErrorCode.REQUIRED_DETAIL_MISSING, PullProcessStatus.EVIDENCE_FAILED),
        (PullErrorCode.UNSAFE_URL, PullProcessStatus.SAFETY_REJECTED),
        (PullErrorCode.BUDGET_EXCEEDED, PullProcessStatus.BUDGET_EXCEEDED),
        (PullErrorCode.RESPONSE_TOO_LARGE, PullProcessStatus.BUDGET_EXCEEDED),
        (PullErrorCode.TRANSPORT_FAILED, PullProcessStatus.UPSTREAM_FAILED),
        (PullErrorCode.PROVIDER_FAILED, PullProcessStatus.UPSTREAM_FAILED),
        (PullErrorCode.RATE_LIMITED, PullProcessStatus.UPSTREAM_FAILED),
        (PullErrorCode.PERSISTENCE_FAILED, PullProcessStatus.PERSISTENCE_FAILED),
    ],
)
def test_domain_errors_have_stable_process_statuses(
    code: PullErrorCode,
    status: PullProcessStatus,
) -> None:
    assert process_status_for_error(code) is status
    error = PullDomainError(code, "Pull failed.", hint="Inspect provider capabilities.")
    assert error.exit_code == int(status)
    assert str(error) == "Pull failed."
    assert error.hint == "Inspect provider capabilities."


def test_successful_observability_requires_a_non_failure_coverage_class() -> None:
    payload = _native_terminal_observability().model_dump()
    payload["coverage_class"] = PullCoverageClass.NOT_APPLICABLE
    with pytest.raises(ValidationError, match="coverage class"):
        PullTerminalObservability.model_validate(payload)


def test_persistence_failure_requires_closed_reason_not_exception_text() -> None:
    observability = PullTerminalObservability(
        terminal_state=PullTerminalState.FAILED,
        error_code=PullErrorCode.PERSISTENCE_FAILED,
        requested_operation=PullOperation.GET,
        resolved_operation=PullOperation.GET,
        retrieval_mechanism=PullRetrievalMechanism.NATIVE_GET,
        provider_id="greenhouse",
        discovery_method=DiscoveryMethod.NATIVE_URL,
        resolver_visited_url_count=1,
        resolver_probe_count=0,
        provider_error_count=0,
        persistence_handoff=PullPersistenceHandoffState.FAILED,
        coverage_class=PullCoverageClass.NOT_APPLICABLE,
        persistence_reason=PullPersistenceFailureReason.PERSISTENCE_UNAVAILABLE,
        elapsed_milliseconds=4,
    )

    dumped = observability.model_dump(mode="json")
    assert dumped["coverage_class"] == "not_applicable"
    assert dumped["persistence_reason"] == "persistence_unavailable"
    assert "RuntimeError" not in str(dumped)

    with pytest.raises(ValidationError, match="closed persistence reason"):
        PullTerminalObservability(
            terminal_state=PullTerminalState.FAILED,
            error_code=PullErrorCode.PERSISTENCE_FAILED,
            requested_operation=PullOperation.GET,
            persistence_handoff=PullPersistenceHandoffState.FAILED,
            elapsed_milliseconds=4,
        )


def test_provider_error_count_is_a_zero_one_latch() -> None:
    field = PullTerminalObservability.model_fields["provider_error_count"]
    assert field.metadata
    assert "0/1 latch" in (field.description or "")
    with pytest.raises(ValidationError):
        PullTerminalObservability(
            terminal_state=PullTerminalState.FAILED,
            error_code=PullErrorCode.PROVIDER_FAILED,
            requested_operation=PullOperation.GET,
            provider_error_count=2,
            persistence_handoff=PullPersistenceHandoffState.NOT_ATTEMPTED,
            elapsed_milliseconds=1,
        )
