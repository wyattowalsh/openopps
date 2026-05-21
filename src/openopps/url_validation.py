from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse


def host_matches(host: str | None, domain: str) -> bool:
    normalized_host = (host or "").strip().lower().removeprefix("www.")
    normalized_domain = domain.strip().lower().removeprefix("www.")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def validate_public_https_url(url: str, *, allow_manual: bool = False) -> str:
    parsed = urlparse(url)
    if allow_manual and parsed.scheme == "manual":
        return url
    if parsed.scheme != "https":
        raise ValueError("URL must use https")
    if not parsed.hostname:
        raise ValueError("URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include credentials")
    validate_public_host(parsed.hostname)
    return url


def validate_public_host(host: str) -> str:
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        raise ValueError("Host must not be empty")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError("Host must not be localhost")
    try:
        ip_address(normalized.strip("[]"))
    except ValueError:
        return normalized
    raise ValueError("Host must not be an IP literal")


def validate_provider_host(host: str, domain: str) -> str:
    normalized = validate_public_host(host)
    if not host_matches(normalized, domain):
        raise ValueError(f"Host must be {domain} or a subdomain")
    return normalized
