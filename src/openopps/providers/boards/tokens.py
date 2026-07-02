from __future__ import annotations

from urllib.parse import urlparse


def _host_belongs_to(host: str, domain: str) -> bool:
    """Return whether a host equals or belongs to a domain, ignoring `www.`."""

    normalized_host = host.strip().lower().removeprefix("www.")
    normalized_domain = domain.strip().lower().removeprefix("www.")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def greenhouse_token_from_url(url: str) -> str | None:
    """Extract a Greenhouse board token from a public board or API URL."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "boards-api.greenhouse.io":
        if len(parts) == 4 and parts[:2] == ["v1", "boards"] and parts[3] == "jobs":
            return parts[2]
        return None
    if not _host_belongs_to(host, "greenhouse.io"):
        return None
    return parts[0] if parts else None


def lever_token_from_url(url: str) -> str | None:
    """Extract a Lever posting token from a public postings or API URL."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "api.lever.co":
        if len(parts) >= 3 and parts[:2] == ["v0", "postings"]:
            return parts[2]
        return None
    if host != "jobs.lever.co":
        return None
    return parts[0] if parts else None


def workable_token_from_url(url: str) -> str | None:
    """Extract a Workable account token from a public board or API URL."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "apply.workable.com":
        if (
            len(parts) == 5
            and parts[:3] == ["api", "v3", "accounts"]
            and parts[4] == "jobs"
        ):
            return parts[3]
        if (
            len(parts) == 6
            and parts[:3] == ["api", "v2", "accounts"]
            and parts[4] == "jobs"
        ):
            return parts[3]
        if parts and parts[0] == "api":
            return None
        if parts and parts[0] != "j":
            return parts[0]
    if host == "www.workable.com":
        if len(parts) >= 3 and parts[:2] == ["api", "accounts"]:
            return parts[2]
        if parts and parts[0] == "api":
            return None
    return None


def ashby_token_from_url(url: str) -> str | None:
    """Extract an Ashby job-board token from a public board or posting API URL."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "api.ashbyhq.com":
        if parts[:2] == ["posting-api", "job-board"] and len(parts) > 2:
            return parts[2]
        return None
    if host != "jobs.ashbyhq.com":
        return None
    return parts[0] if parts else None
