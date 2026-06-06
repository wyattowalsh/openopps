from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from openopps.migrations import sqlite_database_lock


CACHE_SCHEMA_VERSION = "v1"
DEFAULT_CACHE_NAMESPACE = "http-json"
RESPONSE_AFFECTING_HEADERS = {"accept", "content-type", "origin", "referer"}


@dataclass(frozen=True)
class CacheHit:
    key: str
    namespace: str
    data: dict[str, Any] | list[Any]
    status_code: int
    fetched_at: datetime
    expires_at: datetime
    etag: str | None = None
    last_modified: str | None = None
    stale: bool = False
    stale_on_error: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "namespace": self.namespace,
            "statusCode": self.status_code,
            "fetchedAt": self.fetched_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "etag": self.etag,
            "lastModified": self.last_modified,
            "stale": self.stale,
            "staleOnError": self.stale_on_error,
        }


class HttpCache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_json(
        self,
        method: str,
        url: str,
        *,
        namespace: str = DEFAULT_CACHE_NAMESPACE,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        identity: dict[str, Any] | None = None,
        now: datetime | None = None,
        refresh: bool = False,
    ) -> CacheHit | None:
        if refresh:
            return None
        key = cache_key(
            method,
            url,
            namespace=namespace,
            params=params,
            json_body=json_body,
            headers=headers,
            identity=identity,
        )
        record = self._read(key)
        if record is None:
            return None
        current_time = now or _utc_now()
        if record.expires_at <= current_time:
            return None
        return record

    def get_stale_json(
        self,
        method: str,
        url: str,
        *,
        namespace: str = DEFAULT_CACHE_NAMESPACE,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        identity: dict[str, Any] | None = None,
        stale_on_error_only: bool = True,
    ) -> CacheHit | None:
        key = cache_key(
            method,
            url,
            namespace=namespace,
            params=params,
            json_body=json_body,
            headers=headers,
            identity=identity,
        )
        record = self._read(key)
        if record is None:
            return None
        if stale_on_error_only and not record.stale_on_error:
            return None
        return CacheHit(
            key=record.key,
            namespace=record.namespace,
            data=record.data,
            status_code=record.status_code,
            fetched_at=record.fetched_at,
            expires_at=record.expires_at,
            etag=record.etag,
            last_modified=record.last_modified,
            stale=True,
            stale_on_error=record.stale_on_error,
        )

    def put_json(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | list[Any],
        *,
        status_code: int = 200,
        namespace: str = DEFAULT_CACHE_NAMESPACE,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        request_headers: dict[str, str] | None = None,
        response_headers: dict[str, str] | None = None,
        identity: dict[str, Any] | None = None,
        ttl_seconds: int = 3600,
        stale_on_error: bool = False,
        request_duration_ms: int | None = None,
        now: datetime | None = None,
    ) -> str:
        current_time = now or _utc_now()
        expires_at = current_time + timedelta(seconds=ttl_seconds)
        payload = _canonical_json(data)
        normalized_response_headers = _normalize_headers(response_headers or {})
        response_header_values = {
            name.lower(): value for name, value in (response_headers or {}).items()
        }
        key = cache_key(
            method,
            url,
            namespace=namespace,
            params=params,
            json_body=json_body,
            headers=request_headers,
            identity=identity,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into http_cache (
                    key, namespace, method, url, request_identity, status_code,
                    response_headers, etag, last_modified, content_hash, fetched_at,
                    expires_at, stale_on_error, request_duration_ms, payload
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(key) do update set
                    namespace=excluded.namespace,
                    method=excluded.method,
                    url=excluded.url,
                    request_identity=excluded.request_identity,
                    status_code=excluded.status_code,
                    response_headers=excluded.response_headers,
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    content_hash=excluded.content_hash,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at,
                    stale_on_error=excluded.stale_on_error,
                    request_duration_ms=excluded.request_duration_ms,
                    payload=excluded.payload
                """,
                (
                    key,
                    namespace,
                    method.upper(),
                    _normalize_url(url, params),
                    _canonical_json(
                        _request_identity(json_body, request_headers, identity)
                    ),
                    status_code,
                    _canonical_json(normalized_response_headers),
                    response_header_values.get("etag"),
                    response_header_values.get("last-modified"),
                    _sha256(payload),
                    current_time.isoformat(),
                    expires_at.isoformat(),
                    int(stale_on_error),
                    request_duration_ms,
                    payload,
                ),
            )
        return key

    def refresh_json(
        self,
        key: str,
        *,
        ttl_seconds: int = 3600,
        now: datetime | None = None,
    ) -> None:
        current_time = now or _utc_now()
        expires_at = current_time + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            conn.execute(
                """
                update http_cache
                set fetched_at = ?, expires_at = ?
                where key = ?
                """,
                (current_time.isoformat(), expires_at.isoformat(), key),
            )

    def purge(self, *, namespace: str | None = None) -> int:
        with self._connect() as conn:
            if namespace is None:
                cursor = conn.execute("delete from http_cache")
            else:
                cursor = conn.execute(
                    "delete from http_cache where namespace = ?", (namespace,)
                )
            return int(cursor.rowcount or 0)

    def status(self) -> dict[str, Any]:
        current_time = _utc_now().isoformat()
        with self._connect() as conn:
            total = conn.execute("select count(*) from http_cache").fetchone()[0]
            fresh = conn.execute(
                "select count(*) from http_cache where expires_at > ?", (current_time,)
            ).fetchone()[0]
            stale_on_error = conn.execute(
                "select count(*) from http_cache where stale_on_error = 1"
            ).fetchone()[0]
            rows = conn.execute(
                "select namespace, count(*) from http_cache group by namespace"
            ).fetchall()
        return {
            "path": str(self.path),
            "total": int(total or 0),
            "fresh": int(fresh or 0),
            "expired": max(0, int(total or 0) - int(fresh or 0)),
            "staleOnErrorEligible": int(stale_on_error or 0),
            "byNamespace": {namespace: int(count) for namespace, count in rows},
        }

    def _read(self, key: str) -> CacheHit | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select key, namespace, status_code, fetched_at, expires_at, payload,
                    etag, last_modified, stale_on_error
                from http_cache
                where key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        return CacheHit(
            key=row[0],
            namespace=row[1],
            status_code=int(row[2]),
            fetched_at=datetime.fromisoformat(row[3]),
            expires_at=datetime.fromisoformat(row[4]),
            data=json.loads(row[5]),
            etag=row[6],
            last_modified=row[7],
            stale_on_error=bool(row[8]),
        )

    def _init_db(self) -> None:
        with sqlite_database_lock(self.path):
            with self._connect() as conn:
                conn.execute("pragma journal_mode=WAL")
                conn.execute("pragma synchronous=NORMAL")
                conn.execute(
                    """
                    create table if not exists http_cache (
                        key text primary key,
                        namespace text not null,
                        method text not null,
                        url text not null,
                        request_identity text not null,
                        status_code integer not null,
                        response_headers text not null,
                        etag text,
                        last_modified text,
                        content_hash text not null,
                        fetched_at text not null,
                        expires_at text not null,
                        stale_on_error integer not null default 0,
                        request_duration_ms integer,
                        payload text not null
                    )
                    """
                )
                conn.execute(
                    "create index if not exists ix_http_cache_namespace on http_cache(namespace)"
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def cache_key(
    method: str,
    url: str,
    *,
    namespace: str = DEFAULT_CACHE_NAMESPACE,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    identity: dict[str, Any] | None = None,
) -> str:
    parts = {
        "schema": CACHE_SCHEMA_VERSION,
        "namespace": namespace,
        "method": method.upper(),
        "url": _normalize_url(url, params),
        "request": _request_identity(json_body, headers, identity),
    }
    return _sha256(_canonical_json(parts))


def _request_identity(
    json_body: Any,
    headers: dict[str, str] | None,
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "json": json_body,
        "headers": _normalize_headers(headers or {}),
        "identity": identity or {},
    }


def _normalize_url(url: str, params: dict[str, Any] | None) -> str:
    split = urlsplit(url)
    query_pairs = parse_qsl(split.query, keep_blank_values=True)
    if params:
        for key, value in params.items():
            if isinstance(value, list | tuple):
                query_pairs.extend((key, str(item)) for item in value)
            elif value is not None:
                query_pairs.append((key, str(value)))
    query = urlencode(sorted(query_pairs), doseq=True)
    scheme = split.scheme.lower()
    host = split.netloc.lower()
    return urlunsplit((scheme, host, split.path or "/", query, ""))


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key.lower(): str(value)
        for key, value in sorted(headers.items())
        if key.lower() in RESPONSE_AFFECTING_HEADERS
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
