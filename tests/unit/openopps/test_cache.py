import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openopps.cache import HttpCache, cache_key


def test_cache_key_distinguishes_namespace_identity_and_body():
    base = cache_key(
        "post",
        "https://api.example.com/jobs?b=2&a=1",
        namespace="jobs",
        params={"page": 1},
        json_body={"q": "engineer"},
        headers={"Accept": "application/json", "User-Agent": "ignored"},
        identity={"provider": "greenhouse", "route": "acme"},
    )

    assert base == cache_key(
        "POST",
        "https://API.example.com/jobs?a=1&b=2",
        namespace="jobs",
        params={"page": 1},
        json_body={"q": "engineer"},
        headers={"accept": "application/json", "user-agent": "different"},
        identity={"route": "acme", "provider": "greenhouse"},
    )
    assert base != cache_key(
        "post",
        "https://api.example.com/jobs?a=1&b=2",
        namespace="jobs",
        params={"page": 2},
        json_body={"q": "engineer"},
        headers={"accept": "application/json"},
        identity={"provider": "greenhouse", "route": "acme"},
    )
    assert base != cache_key(
        "post",
        "https://api.example.com/jobs?a=1&b=2",
        namespace="jobs",
        params={"page": 1},
        json_body={"q": "designer"},
        headers={"accept": "application/json"},
        identity={"provider": "greenhouse", "route": "acme"},
    )


def test_http_cache_stores_and_returns_fresh_json(tmp_path):
    cache = HttpCache(tmp_path / "cache.db")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    key = cache.put_json(
        "get",
        "https://api.example.com/jobs",
        {"jobs": [1]},
        namespace="jobs",
        ttl_seconds=60,
        now=now,
    )
    hit = cache.get_json(
        "get",
        "https://api.example.com/jobs",
        namespace="jobs",
        now=now + timedelta(seconds=30),
    )

    assert hit is not None
    assert hit.key == key
    assert hit.data == {"jobs": [1]}
    assert hit.stale is False
    assert cache.status()["byNamespace"] == {"jobs": 1}


def test_http_cache_expiry_and_refresh_bypass(tmp_path):
    cache = HttpCache(tmp_path / "cache.db")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache.put_json(
        "get",
        "https://api.example.com/jobs",
        {"jobs": [1]},
        ttl_seconds=1,
        now=now,
    )

    assert (
        cache.get_json(
            "get",
            "https://api.example.com/jobs",
            now=now + timedelta(seconds=2),
        )
        is None
    )
    assert (
        cache.get_json(
            "get",
            "https://api.example.com/jobs",
            now=now,
            refresh=True,
        )
        is None
    )


def test_http_cache_returns_stale_json_when_requested(tmp_path):
    cache = HttpCache(tmp_path / "cache.db")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache.put_json(
        "get",
        "https://api.example.com/jobs",
        [{"id": 1}],
        ttl_seconds=1,
        stale_on_error=True,
        now=now,
    )

    hit = cache.get_stale_json("get", "https://api.example.com/jobs")

    assert hit is not None
    assert hit.data == [{"id": 1}]
    assert hit.stale is True


def test_http_cache_purges_by_namespace(tmp_path):
    cache = HttpCache(tmp_path / "cache.db")
    cache.put_json("get", "https://api.example.com/a", {"a": 1}, namespace="a")
    cache.put_json("get", "https://api.example.com/b", {"b": 1}, namespace="b")

    assert cache.purge(namespace="a") == 1

    status = cache.status()
    assert status["total"] == 1
    assert status["byNamespace"] == {"b": 1}


def test_http_cache_v2_persists_only_opaque_locator_and_hashed_request_identity(
    tmp_path,
):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)

    cache.put_json(
        "post",
        (
            "https://user:password@example.com/queries"
            "?x-algolia-api-key=query-secret&facet=company"
        ),
        {"ok": True},
        json_body={"requests": [{"params": "query=engineer&token=body-secret"}]},
        identity={"provider": "yc", "credential": "identity-secret"},
    )

    with sqlite3.connect(cache_path) as conn:
        row = conn.execute(
            "SELECT schema_version, url, request_identity FROM http_cache"
        ).fetchone()

    assert row is not None
    schema_version, stored_url, stored_identity = row
    assert schema_version == "v2"
    assert stored_url == "redacted://request/"
    assert stored_identity.startswith("sha256:")
    assert len(stored_identity) == len("sha256:") + 64
    persisted = "\n".join((stored_url, stored_identity))
    for secret in (
        "example.com",
        "queries",
        "company",
        "password",
        "query-secret",
        "body-secret",
        "identity-secret",
    ):
        assert secret not in persisted


def test_http_cache_v2_purges_incompatible_v1_rows_on_open(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    cache.put_json("get", "https://api.example.com/jobs", {"jobs": [1]})
    with sqlite3.connect(cache_path) as conn:
        conn.execute(
            "UPDATE http_cache SET schema_version = 'v1', request_identity = ?",
            ('{"json":{"token":"legacy-secret"}}',),
        )

    reopened = HttpCache(cache_path)

    assert reopened.status()["total"] == 0


def test_http_cache_v2_purges_rows_with_legacy_durable_url_locator(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    cache.put_json("get", "https://example.test/path?value=secret", {"ok": True})

    with sqlite3.connect(cache_path) as conn:
        conn.execute(
            "UPDATE http_cache SET url = ?",
            ("https://example.test/path?value=secret",),
        )

    reopened = HttpCache(cache_path)

    assert reopened.status()["total"] == 0


def test_http_cache_securely_erases_legacy_rows_created_with_secure_delete_off(
    tmp_path,
):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    cache.put_json("get", "https://example.test/initial", {"ok": True})
    marker = "legacy-userinfo-query-body-secret-9f2c7a6e"

    keeper = sqlite3.connect(cache_path)
    try:
        keeper.execute("PRAGMA journal_mode=WAL")
        assert keeper.execute("PRAGMA secure_delete=OFF").fetchone() == (0,)
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute(
            """
            UPDATE http_cache
            SET schema_version = 'v1', url = ?, request_identity = ?, payload = ?
            """,
            (
                f"https://user:{marker}@example.test/{marker}?value={marker}",
                marker,
                json.dumps({"secret": marker}),
            ),
        )
        keeper.commit()

        reopened = HttpCache(cache_path)

        assert reopened.status()["total"] == 0
        persisted = b"".join(
            candidate.read_bytes()
            for candidate in (
                cache_path,
                Path(f"{cache_path}-wal"),
                Path(f"{cache_path}-shm"),
            )
            if candidate.exists()
        )
        assert marker.encode() not in persisted
    finally:
        keeper.close()


def test_http_cache_retries_an_interrupted_physical_legacy_scrub(
    tmp_path,
    monkeypatch,
):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    cache.put_json("get", "https://example.test/initial", {"ok": True})
    marker = "legacy-interrupted-scrub-secret-e4b75931"
    with sqlite3.connect(cache_path) as conn:
        assert conn.execute("PRAGMA secure_delete=OFF").fetchone() == (0,)
        conn.execute(
            """
            UPDATE http_cache
            SET schema_version = 'v1', url = ?, request_identity = ?, payload = ?
            """,
            (marker, marker, json.dumps({"secret": marker})),
        )

    original_compact = HttpCache._compact_deleted_content
    attempts = 0

    def fail_once(self):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected physical scrub interruption")
        original_compact(self)

    monkeypatch.setattr(HttpCache, "_compact_deleted_content", fail_once)
    with pytest.raises(RuntimeError, match="injected physical scrub interruption"):
        HttpCache(cache_path)

    with sqlite3.connect(cache_path) as conn:
        assert conn.execute("SELECT count(*) FROM http_cache").fetchone() == (0,)
        assert conn.execute(
            "SELECT value FROM http_cache_metadata WHERE key = ?",
            ("physical_scrub_pending_generation",),
        ).fetchone() == ("2",)
        assert conn.execute(
            "SELECT value FROM http_cache_metadata WHERE key = ?",
            ("physical_scrub_completed_generation",),
        ).fetchone() == ("1",)

    reopened = HttpCache(cache_path)

    assert attempts == 2
    assert reopened.status()["total"] == 0
    with sqlite3.connect(cache_path) as conn:
        assert conn.execute(
            "SELECT value FROM http_cache_metadata WHERE key = ?",
            ("physical_scrub_pending_generation",),
        ).fetchone() == ("2",)
        assert conn.execute(
            "SELECT value FROM http_cache_metadata WHERE key = ?",
            ("physical_scrub_completed_generation",),
        ).fetchone() == ("2",)
    persisted = b"".join(
        candidate.read_bytes()
        for candidate in (
            cache_path,
            Path(f"{cache_path}-wal"),
            Path(f"{cache_path}-shm"),
        )
        if candidate.exists()
    )
    assert marker.encode() not in persisted


def test_http_cache_purge_retries_pending_scrub_after_logical_delete(
    tmp_path,
    monkeypatch,
):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    marker = "purge-retry-secret-459d7e21"
    cache.put_json("get", "https://example.test/data", {"secret": marker})
    original_compact = HttpCache._compact_deleted_content
    attempts = 0

    def fail_once(self):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected purge scrub interruption")
        original_compact(self)

    monkeypatch.setattr(HttpCache, "_compact_deleted_content", fail_once)
    with pytest.raises(RuntimeError, match="injected purge scrub interruption"):
        cache.purge()

    assert cache.status()["total"] == 0
    assert cache.purge() == 0
    assert attempts == 2
    persisted = b"".join(
        candidate.read_bytes()
        for candidate in (
            cache_path,
            Path(f"{cache_path}-wal"),
            Path(f"{cache_path}-shm"),
        )
        if candidate.exists()
    )
    assert marker.encode() not in persisted


def test_http_cache_older_scrubber_cannot_complete_a_later_generation(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    with sqlite3.connect(cache_path) as conn:
        first_generation = cache._advance_scrub_generation(conn)
        second_generation = cache._advance_scrub_generation(conn)
        cache._complete_scrub_generation(conn, first_generation)

        assert first_generation == 2
        assert second_generation == 3
        assert cache._pending_scrub_generation(conn) == 3
        assert cache._completed_scrub_generation(conn) == 1

        cache._complete_scrub_generation(conn, second_generation)
        assert cache._completed_scrub_generation(conn) == 3


def test_http_cache_scrub_generation_recovers_from_missing_pending_state(tmp_path):
    cache_path = tmp_path / "cache.db"
    cache = HttpCache(cache_path)
    with sqlite3.connect(cache_path) as conn:
        conn.execute(
            "DELETE FROM http_cache_metadata WHERE key = ?",
            ("physical_scrub_pending_generation",),
        )
        conn.execute(
            "UPDATE http_cache_metadata SET value = '7' WHERE key = ?",
            ("physical_scrub_completed_generation",),
        )

        assert cache._advance_scrub_generation(conn) == 8
        assert cache._pending_scrub_generation(conn) == 8
        assert cache._completed_scrub_generation(conn) == 7
