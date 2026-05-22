from datetime import datetime, timedelta, timezone

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
