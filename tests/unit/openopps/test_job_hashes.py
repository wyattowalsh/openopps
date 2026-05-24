from openopps.models import JobRecord, job_content_hash, job_payload_hash


def test_job_content_hash_ignores_sync_lifecycle_metadata():
    base = JobRecord(
        id="acme:lever:1",
        board_key="acme",
        provider_id="lever",
        remote_id="1",
        title="Engineer",
        description="Build systems.",
        raw_listing={"id": "1", "metadata": "a"},
    )
    resynced = base.model_copy(
        update={
            "status": "closed",
            "last_seen_at": "2026-05-22T00:00:00Z",
            "raw_listing": {"metadata": "b", "id": "1"},
        }
    )

    assert job_content_hash(base) == job_content_hash(resynced)
    assert job_payload_hash(base) != job_payload_hash(resynced)


def test_job_payload_hash_is_stable_for_raw_key_order():
    left = JobRecord(
        id="acme:lever:1",
        board_key="acme",
        provider_id="lever",
        remote_id="1",
        title="Engineer",
        raw_listing={"id": "1", "nested": {"a": 1, "b": 2}},
    )
    right = left.model_copy(
        update={"raw_listing": {"nested": {"b": 2, "a": 1}, "id": "1"}}
    )

    assert job_payload_hash(left) == job_payload_hash(right)
