from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from openopps.discovery.canonical import canonical_json_bytes
from openopps.ingest import (
    ApprovedIngestionPin,
    _PendingDuplicate,
    _RoutePin,
    _SourcePin,
    _ingest_freshness_digest,
)
from openopps.metrics import (
    ROUTE_CONSERVATION_TERMINALS,
    SOURCE_CONSERVATION_TERMINALS,
    SyncMetrics,
    combine_sync_metrics,
    empty_route_conservation,
    empty_source_conservation,
    source_conservation_payload,
    validate_conservation_counts,
)
from openopps.models import SourceRecord
from openopps.source_policy import (
    load_source_policy_evidence,
    match_source_policy_denials,
)


def _digest(payload: object) -> str:
    return sha256(canonical_json_bytes(payload)).hexdigest()


def test_conservation_counts_require_planned_equals_sum_of_terminals() -> None:
    terminals = {name: 0 for name in SOURCE_CONSERVATION_TERMINALS}
    terminals["succeeded"] = 2
    terminals["unstarted"] = 1
    validate_conservation_counts(3, terminals, names=SOURCE_CONSERVATION_TERMINALS)
    with pytest.raises(ValueError, match="conserved"):
        validate_conservation_counts(2, terminals, names=SOURCE_CONSERVATION_TERMINALS)


def test_source_pin_marks_cancelled_started_work_and_unstarted_remainder() -> None:
    digest = _ingest_freshness_digest("openopps.ingest.source", "test")
    pin = _SourcePin(planned_ids=("launched", "queued"), freshness_digest=digest)
    pin.mark_launched("launched")
    payload = pin.close(interrupted=True)

    assert payload["planned"] == 2
    assert payload["cancelled"] == 1
    assert payload["unstarted"] == 1
    assert payload["complete"] is False
    assert payload["planned"] == sum(
        payload[name]
        for name in (
            "succeeded",
            "failed",
            "timedOut",
            "freshSkipped",
            "policyBlocked",
            "rateLimited",
            "cancelled",
            "unstarted",
        )
    )


def test_route_pin_conserves_duplicate_when_representative_succeeds() -> None:
    digest = _ingest_freshness_digest("openopps.ingest.route", "test")
    pin = _RoutePin(planned_ids=("rep", "dup"), freshness_digest=digest)
    pin.record("rep", "succeeded", authoritative=True)
    pin.pending_duplicates.append(
        _PendingDuplicate(
            route_id="dup",
            representative_id="rep",
            request_key="greenhouse:token:acme",
        )
    )
    payload = pin.close(interrupted=False)
    assert payload["planned"] == 2
    assert payload["succeeded"] == 1
    assert payload["duplicateSkipped"] == 1
    assert payload["complete"] is True


def test_empty_conservation_payloads_are_closed_and_incomplete() -> None:
    source = empty_source_conservation()
    route = empty_route_conservation()
    assert source["planned"] == 0
    assert route["planned"] == 0
    assert source["complete"] is False
    assert route["complete"] is False
    validate_conservation_counts(
        0,
        {name: 0 for name in SOURCE_CONSERVATION_TERMINALS},
        names=SOURCE_CONSERVATION_TERMINALS,
    )
    validate_conservation_counts(
        0,
        {name: 0 for name in ROUTE_CONSERVATION_TERMINALS},
        names=ROUTE_CONSERVATION_TERMINALS,
    )


def test_sync_metrics_as_dict_omits_conservation_until_closed() -> None:
    payload = SyncMetrics(name="jobs.sync").as_dict()
    assert "conservation" not in payload
    assert "attestation" not in payload


def test_sync_metrics_as_dict_attestation_is_typed_and_redacted() -> None:
    metrics = SyncMetrics(name="sync")
    metrics.source_conservation = empty_source_conservation()
    metrics.route_conservation = empty_route_conservation()
    metrics.attestation = "degraded"
    metrics.degraded_class = "policy_blocked"
    metrics.run_id = "ingest-test"
    metrics.evidence_digest = "sha256:" + "a" * 64
    metrics.schema_version = 1
    payload = metrics.as_dict()
    redacted = {
        key: payload[key]
        for key in (
            "attestation",
            "conservation",
            "degradedClass",
            "evidenceDigest",
            "runId",
            "schemaVersion",
        )
        if key in payload
    }
    rendered = canonical_json_bytes(redacted).decode("utf-8")
    full = json.dumps(payload, default=str)

    assert payload["attestation"] == "degraded"
    assert payload["degradedClass"] == "policy_blocked"
    assert payload["attestation"] != payload["degradedClass"]
    assert "unaccounted" not in rendered
    assert "unaccounted" not in full
    assert "http://" not in full
    assert "https://" not in full
    assert "secret" not in full


def test_getro_provider_is_policy_denied_and_not_a_production_allow() -> None:
    catalog = {
        "pin-getro-blocked": SourceRecord(
            key="pin-getro-blocked",
            url="https://example.test/getro",
            provider_id="getro",
        )
    }
    matches = match_source_policy_denials(
        source_keys=("pin-getro-blocked",),
        evidence=load_source_policy_evidence(),
        catalog=catalog,
    )
    assert "pin-getro-blocked" in matches


def _make_pin(source_ids: tuple[str, ...], *, denied: frozenset[str] = frozenset()):
    envelope_id = _digest({"keys": list(source_ids)})
    return ApprovedIngestionPin(
        frozen_source_ids=source_ids,
        denied_source_keys=denied,
        envelope_id=envelope_id,
        catalog_content_digest=_digest("catalog"),
        catalog_tree_digest=_digest("catalog"),
        selector_digest=_digest(list(source_ids)),
        policy_digest=_digest("policy"),
        promotion_digest=_digest("promotion"),
        checkout_sha="a" * 40,
    )


def test_test_pin_factory_uses_sha256_digests() -> None:
    pin = _make_pin(("greenhouse-pin", "lever-pin"))
    assert len(pin.envelope_id) == 64
    assert pin.denied_source_keys == frozenset()


def test_combine_sync_metrics_keeps_first_source_and_route_pins() -> None:
    first = SyncMetrics(name="sources.sync")
    first.source_conservation = source_conservation_payload(
        planned=2,
        terminals={
            "succeeded": 1,
            "failed": 0,
            "timed_out": 0,
            "fresh_skipped": 0,
            "policy_blocked": 0,
            "rate_limited": 0,
            "cancelled": 0,
            "unstarted": 1,
        },
        terminal=True,
        complete=False,
    )
    second = SyncMetrics(name="jobs.sync")
    second.route_conservation = empty_route_conservation()
    combined = combine_sync_metrics("sync", first, second).as_dict()["conservation"]
    assert combined["sources"]["unstarted"] == 1
    assert combined["routes"]["planned"] == 0


def test_empty_pins_close_zero_planned_accounting() -> None:
    digest = _ingest_freshness_digest("openopps.ingest.source", "empty")
    source = _SourcePin(planned_ids=(), freshness_digest=digest)
    route = _RoutePin(planned_ids=(), freshness_digest=digest)
    source_payload = source.close(interrupted=False)
    route_payload = route.close(interrupted=False)
    assert source.accounting is not None
    assert route.accounting is not None
    assert source_payload["planned"] == 0
    assert route_payload["planned"] == 0
    assert source_payload["complete"] is True
    assert route_payload["complete"] is True


def test_prepare_ingest_pin_rejects_missing_catalog_key_without_echo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from openopps.ingest import prepare_ingest_pin

    envelope = SimpleNamespace(
        envelope_id="e" * 64,
        catalog_content_digest="c" * 64,
        catalog_tree_digest="c" * 64,
        source_key_digest="s" * 64,
        promotion_digest="p" * 64,
        v7_policy_code_digest="a" * 64,
        v7_policy_corpus_digest="b" * 64,
        v7_policy_evidence_digest="d" * 64,
        v7_policy_schema_digest="f" * 64,
        supplementary_policy_digest="g" * 64,
    )
    scout = SimpleNamespace(
        frozen_source_ids=("missing-source-key",),
        envelope=envelope,
        checkout_sha="0" * 40,
    )
    monkeypatch.setattr(
        "openopps.discovery.diagnostics.prepare_selector_bound_scout",
        lambda *_args, **_kwargs: scout,
    )
    with pytest.raises(
        ValueError, match="approved-ingestion pin does not match catalog"
    ) as exc_info:
        prepare_ingest_pin(tmp_path, catalog={})
    assert "missing-source-key" not in str(exc_info.value)


def test_prepare_ingest_pin_denies_getro_without_production_allow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from openopps.ingest import prepare_ingest_pin

    catalog = {
        "pin-getro-blocked": SourceRecord(
            key="pin-getro-blocked",
            url="https://example.test/getro",
            provider_id="getro",
        )
    }
    envelope = SimpleNamespace(
        envelope_id="e" * 64,
        catalog_content_digest="c" * 64,
        catalog_tree_digest="c" * 64,
        source_key_digest="s" * 64,
        promotion_digest="p" * 64,
        v7_policy_code_digest="a" * 64,
        v7_policy_corpus_digest="b" * 64,
        v7_policy_evidence_digest="d" * 64,
        v7_policy_schema_digest="f" * 64,
        supplementary_policy_digest="g" * 64,
    )
    scout = SimpleNamespace(
        frozen_source_ids=("pin-getro-blocked",),
        envelope=envelope,
        checkout_sha="0" * 40,
    )
    monkeypatch.setattr(
        "openopps.discovery.diagnostics.prepare_selector_bound_scout",
        lambda *_args, **_kwargs: scout,
    )
    pin = prepare_ingest_pin(tmp_path, catalog=catalog)
    assert pin.frozen_source_ids == ("pin-getro-blocked",)
    assert "pin-getro-blocked" in pin.denied_source_keys
