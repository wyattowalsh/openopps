from __future__ import annotations

from openopps.metrics import (
    SyncMetrics,
    bind_http_retry_metrics,
    record_http_retry,
    reset_http_retry_metrics,
)

EXPECTED_AS_DICT_CAMEL_KEYS = frozenset(
    {
        "name",
        "pages",
        "boards",
        "boardProviders",
        "jobs",
        "jobsPersisted",
        "jobSyncAttempts",
        "jobSyncRuns",
        "jobsDeduped",
        "skipped",
        "duplicateRoutesSkipped",
        "retries",
        "providerErrors",
        "providerErrorDetails",
        "elapsedSeconds",
        "boardsPerSecond",
        "jobsPerSecond",
    }
)


def test_sync_metrics_as_dict_exposes_stable_camel_case_keys() -> None:
    metrics = SyncMetrics(name="jobs.sync", boards=3, jobs=12)
    metrics.error("lever", reason="timeout")
    metrics.finish()

    payload = metrics.as_dict()

    assert set(payload.keys()) == EXPECTED_AS_DICT_CAMEL_KEYS
    assert payload["name"] == "jobs.sync"
    assert payload["boardProviders"] == 0
    assert payload["jobsPersisted"] == 0
    assert payload["jobSyncAttempts"] == 0
    assert payload["jobSyncRuns"] == 0
    assert payload["jobsDeduped"] == 0
    assert payload["duplicateRoutesSkipped"] == 0
    assert payload["providerErrors"] == {"lever": 1}
    assert payload["providerErrorDetails"] == {"lever": {"timeout": 1}}
    assert payload["elapsedSeconds"] >= 0
    assert payload["boardsPerSecond"] >= 0
    assert payload["jobsPerSecond"] >= 0


def test_record_http_retry_increments_bound_sync_metrics() -> None:
    metrics = SyncMetrics(name="jobs.sync")
    token = bind_http_retry_metrics(metrics)
    try:
        record_http_retry()
        record_http_retry()
    finally:
        reset_http_retry_metrics(token)

    assert metrics.retries == 2
    assert metrics.as_dict()["retries"] == 2
