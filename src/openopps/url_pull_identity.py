"""Reserved URL-pull identity helpers.

Digest identity is not `stable_id` or `slugify`. Punctuation-distinct natives
such as `acme.co` and `acme-co` remain distinct. Fetch-time native board keys
are rebound onto the digest key before ledger writes.
"""

from __future__ import annotations

import hashlib
import json

from openopps.models import JobRecord

URL_PULL_RESERVED_SOURCE_KEY = "url-pull"
URL_PULL_OWNED_PROVIDER_ID = "url-pull"
URL_PULL_OWNED_BY = "url-pull"
URL_PULL_SOURCE_URL = "manual://url-pull"
_IDENTITY_VERSION = 1

JOB_MEMBERSHIP_LISTED = "listed"
JOB_MEMBERSHIP_DIRECT_ONLY = "direct_only"
LIST_MEMBERSHIP_SCOPE_LISTED = "listed"
LIST_MEMBERSHIP_SCOPE_ALL_PUBLIC = "all_public"


def is_url_pull_reserved_source_key(source_key: str | None) -> bool:
    """Return whether a source key is the reserved URL-pull namespace."""

    return (source_key or "").strip() == URL_PULL_RESERVED_SOURCE_KEY


def url_pull_board_digest(
    *,
    provider_id: str,
    native_board_identity: str,
    canonical_board_material: str,
) -> str:
    """Return a punctuation-preserving digest for one reserved board identity.

    The digest is SHA-256 over a versioned JSON object. It must not slugify
    or otherwise fold `acme.co` into `acme-co`.
    """

    provider = _required_identity_part("provider_id", provider_id)
    native = _required_identity_part("native_board_identity", native_board_identity)
    material = _required_identity_part(
        "canonical_board_material", canonical_board_material
    )
    payload = json.dumps(
        {
            "v": _IDENTITY_VERSION,
            "provider_id": provider,
            "native_board_identity": native,
            "canonical_board_material": material,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def url_pull_board_key(digest: str) -> str:
    """Return the reserved operational board key for a digest."""

    token = _required_identity_part("digest", digest)
    return f"{URL_PULL_RESERVED_SOURCE_KEY}:{token}"


def url_pull_board_remote_id(*, provider_id: str, native_board_identity: str) -> str:
    """Return a punctuation-preserving source-scoped remote board id."""

    provider = _required_identity_part("provider_id", provider_id)
    native = _required_identity_part("native_board_identity", native_board_identity)
    return f"{provider}:{native}"


def url_pull_route_id(*, board_key: str, provider_id: str) -> str:
    """Return the reserved route id without slug normalization."""

    key = _required_identity_part("board_key", board_key)
    provider = _required_identity_part("provider_id", provider_id)
    return f"{key}:{provider}"


def url_pull_job_id(*, board_key: str, provider_id: str, remote_id: str) -> str:
    """Return a ledger job id bound to the digest board key."""

    key = _required_identity_part("board_key", board_key)
    provider = _required_identity_part("provider_id", provider_id)
    remote = _required_identity_part("remote_id", remote_id)
    return f"{key}:{provider}:{remote}"


def canonical_board_material(
    *,
    provider_id: str,
    native_board_identity: str,
) -> str:
    """Return board-scoped canonical material, never a pasted posting URL."""

    provider = _required_identity_part("provider_id", provider_id)
    native = _required_identity_part("native_board_identity", native_board_identity)
    return f"{provider}\n{native}"


def rebound_job_record(
    job: JobRecord,
    *,
    board_key: str,
    membership: str,
) -> JobRecord:
    """Rebind fetch-time native board_key/id onto the reserved digest key."""

    key = _required_identity_part("board_key", board_key)
    if membership not in {JOB_MEMBERSHIP_LISTED, JOB_MEMBERSHIP_DIRECT_ONLY}:
        raise ValueError("job membership must be listed or direct_only")
    return job.model_copy(
        update={
            "id": url_pull_job_id(
                board_key=key,
                provider_id=job.provider_id,
                remote_id=job.remote_id,
            ),
            "board_key": key,
            "membership": membership,
        }
    )


def job_membership_for_posting(job: JobRecord) -> str:
    """Return listed vs direct_only from posting visibility, not slug identity."""

    if job.posting_kind == "unlisted":
        return JOB_MEMBERSHIP_DIRECT_ONLY
    return JOB_MEMBERSHIP_LISTED


def _required_identity_part(name: str, value: str) -> str:
    token = value.strip() if isinstance(value, str) else ""
    if not token:
        raise ValueError(f"{name} must be a non-empty string")
    if token != value:
        raise ValueError(f"{name} must not include surrounding whitespace")
    return token
