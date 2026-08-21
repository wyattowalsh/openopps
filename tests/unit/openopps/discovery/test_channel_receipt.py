from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from openopps.discovery.api import (
    decode_channel_replay_receipt,
    discovery_schema_bytes,
    encode_channel_replay_receipt,
)
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.identity import normalize_candidate_identity
from openopps.discovery.models import (
    BoundedReason,
    CandidateOccurrence,
    ChannelOperationAccounting,
    ChannelReplayReceipt,
    ObservedResource,
    ProvenanceClaim,
    RequestReceipt,
)
from openopps.discovery.schemas import (
    DEFAULT_SCHEMA_ROOT,
    discovery_schema_models,
    schema_file_name,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _resource(resource_id: str, digest: str) -> ObservedResource:
    return ObservedResource(
        resource_id=resource_id,
        role="captured-response",
        media_type="application/json",
        content_sha256=digest,
        size_bytes=10,
        observed_at=OBSERVED_AT,
        final_locator=f"https://public.example.test/{resource_id}",
        validated_address="192.0.2.1",
    )


def _claim(claim_id: str, resource_id: str) -> ProvenanceClaim:
    return ProvenanceClaim(
        claim_id=claim_id,
        resource_id=resource_id,
        field_name="repositoryPath",
        value=f"data/{claim_id}.json",
        source="local_observation",
        accepted=True,
    )


def _occurrence(
    occurrence_id: str,
    provenance_ids: tuple[str, ...],
    *,
    channel: str = "official",
) -> CandidateOccurrence:
    identity = normalize_candidate_identity(
        key=occurrence_id,
        url=f"https://jobs.example.test/{occurrence_id}",
        provider_id="greenhouse",
        provider_token=f"Token-{occurrence_id}",
        owner="official",
        candidate_kind="board_route",
        adapter_id="greenhouse_source",
    )
    return CandidateOccurrence(
        occurrence_id=occurrence_id,
        channel=channel,
        identity=identity,
        provenance_ids=provenance_ids,
    )


def _request(
    request_id: str,
    *,
    attempt_kind: str,
    outcome: str,
    resource_id: str | None,
    admitted_bytes: int,
) -> RequestReceipt:
    return RequestReceipt(
        request_id=request_id,
        attempt_kind=attempt_kind,
        outcome=outcome,
        locator_id="operation-a",
        resource_id=resource_id,
        response_status=200 if outcome == "succeeded" else 503,
        admitted_bytes=admitted_bytes,
        elapsed_ms=5,
        validated_addresses=("192.0.2.1",),
        redirect_hops=(),
        reason_code=(
            BoundedReason.NONE
            if outcome == "succeeded"
            else BoundedReason.CONTENT_REJECTED
        ),
    )


def _accounting(**updates: object) -> ChannelOperationAccounting:
    values: dict[str, object] = {
        "channel": "official",
        "channel_state": "partial",
        "planned_operations": 3,
        "succeeded": 1,
        "blocked": 1,
        "rate_limited": 0,
        "timed_out": 0,
        "failed": 0,
        "cancelled": 0,
        "unstarted": 1,
        "request_limit": 3,
        "request_consumed": 2,
        "request_in_flight": 0,
        "request_remaining": 1,
        "byte_limit": 20,
        "admitted_bytes": 10,
        "remaining_bytes": 10,
        "unfinished_operation_ids": ("operation-c",),
    }
    values.update(updates)
    return ChannelOperationAccounting(**values)


def _receipt(**updates: object) -> ChannelReplayReceipt:
    values: dict[str, object] = {
        "schema_version": 1,
        "enumerator_version": "official-fixture-v1",
        "channel": "official",
        "input_set_sha256": SHA_A,
        "operation_ids": ("operation-a", "operation-b", "operation-c"),
        "operation_outcomes": ("succeeded", "blocked", "unstarted"),
        "operation_request_ids": (
            ("request-a", "request-b"),
            (),
            (),
        ),
        "occurrences": (
            _occurrence("occurrence-a", ("claim-a", "resource-a")),
            _occurrence("occurrence-b", ("claim-b",)),
        ),
        "resources": (
            _resource("resource-a", SHA_A),
            _resource("resource-b", SHA_B),
        ),
        "request_receipts": (
            _request(
                "request-a",
                attempt_kind="initial",
                outcome="failed",
                resource_id=None,
                admitted_bytes=0,
            ),
            _request(
                "request-b",
                attempt_kind="retry",
                outcome="succeeded",
                resource_id="resource-a",
                admitted_bytes=10,
            ),
        ),
        "provenance_claims": (
            _claim("claim-a", "resource-a"),
            _claim("claim-b", "resource-b"),
        ),
        "accounting": _accounting(),
    }
    values.update(updates)
    return ChannelReplayReceipt(**values)


def test_channel_receipt_round_trips_canonical_alias_only_bytes() -> None:
    receipt = _receipt()

    first = encode_channel_replay_receipt(receipt)
    second = encode_channel_replay_receipt(receipt)
    assert first == second
    assert decode_channel_replay_receipt(first) == receipt
    payload = decode_canonical_json(first)
    assert set(payload) == {
        "accounting",
        "channel",
        "enumeratorVersion",
        "inputSetSha256",
        "occurrences",
        "operationIds",
        "operationOutcomes",
        "operationRequestIds",
        "provenanceClaims",
        "requestReceipts",
        "resources",
        "schemaVersion",
    }
    assert "input_set_sha256" not in payload

    snake_case = canonical_json_bytes(
        receipt.model_dump(mode="json", by_alias=False, round_trip=True)
    )
    with pytest.raises(ValidationError):
        decode_channel_replay_receipt(snake_case)
    with pytest.raises(ValidationError):
        receipt.channel = "search"


def test_channel_receipt_is_registered_and_generated_schema_is_byte_current() -> None:
    assert discovery_schema_models()["ChannelReplayReceipt"] is ChannelReplayReceipt
    schema_bytes = discovery_schema_bytes("ChannelReplayReceipt")
    schema = decode_canonical_json(schema_bytes)
    assert set(schema["properties"]) == {
        "accounting",
        "channel",
        "enumeratorVersion",
        "inputSetSha256",
        "occurrences",
        "operationIds",
        "operationOutcomes",
        "operationRequestIds",
        "provenanceClaims",
        "requestReceipts",
        "resources",
        "schemaVersion",
    }
    assert set(schema["required"]) == set(schema["properties"])
    schema_path = DEFAULT_SCHEMA_ROOT / schema_file_name("ChannelReplayReceipt")
    assert schema_path.read_bytes() == schema_bytes


@pytest.mark.parametrize(
    "field",
    ("occurrences", "resources", "request_receipts", "provenance_claims"),
)
def test_channel_receipt_rejects_unsorted_or_duplicate_entity_ids(field: str) -> None:
    receipt = _receipt()
    values = getattr(receipt, field)
    with pytest.raises(ValidationError, match="sorted and unique"):
        _receipt(**{field: tuple(reversed(values))})
    with pytest.raises(ValidationError, match="sorted and unique"):
        _receipt(**{field: (values[0], values[0])})


def test_channel_receipt_requires_channel_tags_to_agree() -> None:
    receipt = _receipt()
    wrong_occurrence = _occurrence(
        "occurrence-a",
        ("claim-a", "resource-a"),
        channel="search",
    )
    with pytest.raises(ValidationError, match="occurrence channel"):
        _receipt(occurrences=(wrong_occurrence, receipt.occurrences[1]))
    with pytest.raises(ValidationError, match="accounting tag"):
        _receipt(accounting=_accounting(channel="search"))


@pytest.mark.parametrize(
    "channel",
    ("official", "public_code", "search", "targeted_ats"),
)
def test_channel_receipt_contract_is_generic_across_all_channels(channel: str) -> None:
    receipt = _receipt(
        channel=channel,
        occurrences=(
            _occurrence(
                "occurrence-a",
                ("claim-a", "resource-a"),
                channel=channel,
            ),
            _occurrence("occurrence-b", ("claim-b",), channel=channel),
        ),
        accounting=_accounting(channel=channel),
    )

    assert receipt.channel == channel
    assert all(occurrence.channel == channel for occurrence in receipt.occurrences)


def test_channel_receipt_requires_closed_unambiguous_provenance() -> None:
    receipt = _receipt()
    unknown = _occurrence("occurrence-a", ("unknown-provenance",))
    with pytest.raises(ValidationError, match="occurrence provenance"):
        _receipt(occurrences=(unknown, receipt.occurrences[1]))

    unresolved_receipt = _request(
        "request-b",
        attempt_kind="retry",
        outcome="succeeded",
        resource_id="resource-unknown",
        admitted_bytes=10,
    )
    with pytest.raises(ValidationError, match="request receipt resource"):
        _receipt(request_receipts=(receipt.request_receipts[0], unresolved_receipt))

    unresolved_claim = _claim("claim-a", "resource-unknown")
    with pytest.raises(ValidationError, match="claim resource"):
        _receipt(provenance_claims=(unresolved_claim, receipt.provenance_claims[1]))

    ambiguous_claim = _claim("resource-a", "resource-a")
    with pytest.raises(ValidationError, match="unambiguous"):
        _receipt(
            provenance_claims=(receipt.provenance_claims[1], ambiguous_claim),
        )


def test_operation_mapping_is_sorted_aligned_and_assigns_each_request_once() -> None:
    with pytest.raises(ValidationError, match="operation IDs"):
        _receipt(operation_ids=("operation-b", "operation-a", "operation-c"))
    with pytest.raises(ValidationError, match="operation IDs"):
        _receipt(operation_ids=("operation-a", "operation-a", "operation-c"))
    with pytest.raises(ValidationError, match="outcomes must align"):
        _receipt(operation_outcomes=("succeeded", "blocked"))
    with pytest.raises(ValidationError, match="request IDs must align"):
        _receipt(operation_request_ids=(("request-a", "request-b"), ()))
    with pytest.raises(ValidationError, match="sorted and unique per operation"):
        _receipt(operation_request_ids=(("request-b", "request-a"), (), ()))
    with pytest.raises(ValidationError, match="sorted and unique per operation"):
        _receipt(operation_request_ids=(("request-a", "request-a"), (), ()))
    with pytest.raises(ValidationError, match="more than once"):
        _receipt(
            operation_outcomes=("succeeded", "failed", "unstarted"),
            operation_request_ids=(
                ("request-a", "request-b"),
                ("request-a",),
                (),
            ),
        )
    with pytest.raises(ValidationError, match="assigned exactly once"):
        _receipt(operation_request_ids=(("request-b",), (), ()))
    with pytest.raises(ValidationError, match="does not resolve"):
        _receipt(
            operation_request_ids=(
                ("request-a", "request-b", "request-z"),
                (),
                (),
            )
        )


def test_operation_outcomes_are_explicit_for_receipt_and_no_receipt_states() -> None:
    receipt = _receipt()
    assert receipt.operation_outcomes[1:] == ("blocked", "unstarted")
    assert receipt.operation_request_ids[1:] == ((), ())

    no_receipt = _receipt(
        operation_ids=("operation-a", "operation-c"),
        operation_outcomes=("blocked", "unstarted"),
        operation_request_ids=((), ()),
        occurrences=(),
        resources=(),
        request_receipts=(),
        provenance_claims=(),
        accounting=_accounting(
            planned_operations=2,
            succeeded=0,
            request_consumed=0,
            request_remaining=3,
            admitted_bytes=0,
            remaining_bytes=20,
        ),
    )
    assert no_receipt.operation_outcomes == ("blocked", "unstarted")
    assert no_receipt.accounting.request_consumed == 0

    with pytest.raises(ValidationError, match="not represented"):
        _receipt(operation_outcomes=("blocked", "blocked", "unstarted"))
    with pytest.raises(ValidationError, match="successful operation requires"):
        _receipt(operation_request_ids=((), (), ()))
    with pytest.raises(ValidationError, match="unstarted operation"):
        _receipt(
            operation_request_ids=(
                ("request-a", "request-b"),
                (),
                ("request-b",),
            )
        )


def test_operation_accounting_is_bound_to_declared_operations_and_requests() -> None:
    with pytest.raises(ValidationError, match="planned operations"):
        _receipt(
            operation_ids=("operation-a", "operation-b"),
            operation_outcomes=("succeeded", "blocked"),
            operation_request_ids=(("request-a", "request-b"), ()),
        )
    with pytest.raises(ValidationError, match="outcomes do not match"):
        _receipt(
            accounting=_accounting(
                succeeded=0,
                blocked=2,
            )
        )
    with pytest.raises(ValidationError, match="consumed request accounting"):
        _receipt(
            accounting=_accounting(
                request_consumed=1,
                request_remaining=2,
            )
        )
    with pytest.raises(ValidationError, match="admitted accounting"):
        _receipt(
            accounting=_accounting(
                admitted_bytes=9,
                remaining_bytes=11,
            )
        )
    with pytest.raises(ValidationError, match="identify unstarted work"):
        _receipt(accounting=_accounting(unfinished_operation_ids=()))


def test_nonterminal_state_cannot_claim_a_replay_receipt() -> None:
    with pytest.raises(ValidationError, match="nonterminal"):
        _receipt(
            accounting=_accounting(
                channel_state="nonterminal",
                request_in_flight=1,
                request_remaining=0,
            )
        )


def test_channel_receipt_api_rejects_the_wrong_model_type() -> None:
    with pytest.raises(TypeError, match="ChannelReplayReceipt"):
        encode_channel_replay_receipt(_accounting())  # type: ignore[arg-type]


def test_generated_schema_path_is_package_relative() -> None:
    path = Path(schema_file_name("ChannelReplayReceipt"))
    assert path == Path("channel-replay-receipt.schema.json")
    assert not path.is_absolute()
