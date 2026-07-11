from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from openopps.models import validate_public_host, validate_public_https_url


@pytest.mark.parametrize(
    ("url", "kwargs"),
    [
        ("https://example.com", {}),
        ("https://jobs.lever.co/acme", {}),
        ("https://boards.greenhouse.io/openai", {}),
        ("https://www.example.org/jobs?q=1", {}),
        ("https://sub.domain.example.net/path/to/job", {}),
        ("manual://source", {"allow_manual": True}),
        ("  manual://nasdaq100  ", {"allow_manual": True}),
    ],
    ids=[
        "example-com",
        "lever-board",
        "greenhouse-board",
        "query-string",
        "nested-subdomain",
        "manual-allow",
        "manual-allow-stripped",
    ],
)
def test_validate_public_https_url_accepts_safe_urls(url: str, kwargs: dict) -> None:
    assert validate_public_https_url(url, **kwargs) == url


@pytest.mark.parametrize(
    ("url", "kwargs"),
    [
        ("http://example.com", {}),
        ("ftp://example.com/file", {}),
        ("https://localhost/", {}),
        ("https://app.localhost/jobs", {}),
        ("https://127.0.0.1/", {}),
        ("https://192.168.1.10/", {}),
        ("https://10.0.0.5/", {}),
        ("https://user:secret@example.com/", {}),
        ("https://user@example.com/", {}),
        ("not-a-url", {}),
        ("manual://source", {}),
        ("https://[::1]/", {}),
    ],
    ids=[
        "http-scheme",
        "ftp-scheme",
        "localhost",
        "localhost-subdomain",
        "loopback-ipv4",
        "private-ipv4",
        "private-ipv4-10",
        "userinfo-password",
        "userinfo-user",
        "invalid-url",
        "manual-without-flag",
        "ipv6-loopback",
    ],
)
def test_validate_public_https_url_rejects_unsafe_urls(url: str, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        validate_public_https_url(url, **kwargs)


@pytest.mark.parametrize(
    ("host", "message_fragment"),
    [
        ("localhost", "localhost"),
        ("api.localhost", "localhost"),
        ("127.0.0.1", "IP literal"),
        ("192.168.0.1", "IP literal"),
        ("", "empty"),
        ("evil.com/path", "hostname"),
        ("has space.com", "whitespace"),
    ],
    ids=[
        "localhost",
        "localhost-suffix",
        "ipv4-literal",
        "private-ipv4-literal",
        "empty-host",
        "path-in-host",
        "whitespace-in-host",
    ],
)
def test_validate_public_host_rejects_unsafe_hosts(host: str, message_fragment: str) -> None:
    with pytest.raises(ValueError, match=message_fragment):
        validate_public_host(host)


def test_validate_public_host_accepts_public_hostname() -> None:
    assert validate_public_host("Example.COM.") == "example.com"


_label = st.from_regex(r"[a-z][a-z0-9]{0,12}", fullmatch=True)
_public_hostname = st.builds(lambda a, b: f"{a}.{b}", _label, _label)


@settings(deadline=None, max_examples=30)
@given(host=_public_hostname, path=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-_", max_size=12))
def test_validate_public_https_url_accepts_generated_https_urls(host: str, path: str) -> None:
    url = f"https://{host}/{path}".rstrip("/") if path else f"https://{host}/"
    assert validate_public_https_url(url) == url


@settings(deadline=None, max_examples=30)
@given(
    scheme=st.sampled_from(["http", "ftp", "file", "javascript"]),
    host=_public_hostname,
)
def test_validate_public_https_url_rejects_non_https_schemes(scheme: str, host: str) -> None:
    with pytest.raises(ValueError):
        validate_public_https_url(f"{scheme}://{host}/")


@settings(deadline=None, max_examples=30)
@given(host=_public_hostname)
def test_validate_public_host_normalizes_trailing_dot(host: str) -> None:
    assert validate_public_host(f"{host}.") == host.rstrip(".")