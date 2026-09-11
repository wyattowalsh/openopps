from __future__ import annotations

import json
from pathlib import Path

import pytest

from openopps.pull_metrics import (
    PULL_METRICS_SCHEMA_VERSION,
    pull_metrics_payload,
    write_pull_metrics_file,
)
from openopps.pull_models import (
    DiscoveryMethod,
    PullCoverageClass,
    PullErrorCode,
    PullHttpObservability,
    PullOperation,
    PullPersistenceHandoffState,
    PullRetrievalMechanism,
    PullTerminalObservability,
    PullTerminalState,
)


def _observability(
    *,
    coverage_class: PullCoverageClass = PullCoverageClass.EPHEMERAL_NEW,
    error_code: PullErrorCode | None = None,
) -> PullTerminalObservability:
    failed = error_code is not None
    return PullTerminalObservability(
        terminal_state=(
            PullTerminalState.FAILED if failed else PullTerminalState.SUCCEEDED
        ),
        error_code=error_code,
        requested_operation=PullOperation.GET,
        resolved_operation=PullOperation.GET,
        retrieval_mechanism=PullRetrievalMechanism.NATIVE_GET,
        provider_id="greenhouse",
        discovery_method=DiscoveryMethod.NATIVE_URL,
        resolver_visited_url_count=1,
        resolver_probe_count=0,
        http=PullHttpObservability(request_count=2, retry_count=1),
        provider_error_count=1 if failed else 0,
        persistence_handoff=(
            PullPersistenceHandoffState.NOT_ATTEMPTED
            if failed
            else PullPersistenceHandoffState.NOT_REQUESTED
        ),
        coverage_class=(
            PullCoverageClass.NOT_APPLICABLE if failed else coverage_class
        ),
        elapsed_milliseconds=11,
    )


def test_metrics_payload_is_camel_case_with_schema_version() -> None:
    payload = pull_metrics_payload(
        _observability(coverage_class=PullCoverageClass.OVERLAY_PACKAGED)
    )

    assert payload["schemaVersion"] == PULL_METRICS_SCHEMA_VERSION
    assert payload["coverageClass"] == "overlay_packaged"
    assert payload["terminalState"] == "succeeded"
    assert payload["providerErrorCount"] == 0
    assert payload["http"]["requestCount"] == 2
    assert payload["http"]["retryCount"] == 1
    assert "coverage_class" not in payload
    assert "schema_version" not in payload


def test_metrics_file_is_atomic_compact_json_and_replaces_destination(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "pull-metrics.json"
    path.parent.mkdir()
    path.write_text("previous\n", encoding="utf-8")

    write_pull_metrics_file(_observability(), path)

    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "\n  " not in raw
    payload = json.loads(raw)
    assert payload["schemaVersion"] == 1
    assert payload["coverageClass"] == "ephemeral_new"
    assert payload["elapsedMilliseconds"] == 11


def test_metrics_payload_bounds_long_diagnostic_strings() -> None:
    observability = _observability()
    dumped = observability.model_dump(mode="json")
    dumped["hint"] = "x" * 600
    from openopps.pull_metrics import _camelize

    camelized = _camelize(dumped)
    assert isinstance(camelized, dict)
    assert len(camelized["hint"]) == 500
    assert str(camelized["hint"]).endswith("...")


def test_missing_observability_still_writes_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    write_pull_metrics_file(None, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"schemaVersion": 1}


def test_write_failure_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openopps import pull_output

    path = tmp_path / "metrics.json"
    path.write_text("previous\n", encoding="utf-8")

    def fail_replace(source: str | Path, dest: str | Path) -> None:
        del source, dest
        raise OSError("replace failed")

    monkeypatch.setattr(pull_output.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_pull_metrics_file(_observability(), path)
    assert path.read_text(encoding="utf-8") == "previous\n"
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
