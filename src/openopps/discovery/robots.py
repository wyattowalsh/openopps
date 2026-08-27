"""Bounded RFC 9309 robots parsing and fail-closed access observations.

Scout-zone module for OpenSpec T133 captured-robots fixtures and E413.
Untrusted robots bytes remain access observations only: they never grant
legal, sync, or publication rights. Keep this module in
``src/openopps/discovery/``; it is not a stray file.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Literal
from urllib.parse import urlsplit

from openopps.discovery.models import BoundedReason
from openopps.discovery.transport import (
    DiscoveryTransportError,
    SafeLocator,
    validate_public_locator,
)


ROBOTS_RFC_MINIMUM_BYTES = 500 * 1024
ROBOTS_MAX_CACHE_AGE_SECONDS = 86_400
_MAX_ROBOTS_BYTES = 10_485_760
_PRODUCT_TOKEN = re.compile(r"^[A-Za-z_-]+$")
_UNRESERVED = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)

RobotsTransportState = Literal[
    "response",
    "network_unreachable",
    "security_rejected_redirect",
    "verified_cache",
]


class RobotsParseError(ValueError):
    """Raised when a hostile robots body exceeds the trusted parser contract."""


@dataclass(frozen=True, slots=True)
class RobotsRule:
    directive: Literal["allow", "disallow"]
    pattern: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class RobotsGroup:
    user_agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    """Parsed rules remain untrusted observations and grant no rights."""

    groups: tuple[RobotsGroup, ...]
    sitemap_locators: tuple[str, ...]

    def access_for(self, *, product_token: str, request_target: str) -> bool:
        """Return RFC 9309 access using exact product-token groups."""

        if _PRODUCT_TOKEN.fullmatch(product_token) is None:
            raise ValueError("robots product token is invalid")
        normalized_agent = product_token.casefold()
        exact = tuple(
            group for group in self.groups if normalized_agent in group.user_agents
        )
        selected = exact or tuple(
            group for group in self.groups if "*" in group.user_agents
        )
        rules = tuple(rule for group in selected for rule in group.rules)
        if not rules:
            return True

        target = _request_target(request_target)
        matches: list[tuple[int, bool, int]] = []
        for rule in rules:
            matched, specificity = _rule_matches(rule.pattern, target)
            if matched:
                matches.append(
                    (specificity, rule.directive == "allow", -rule.ordinal)
                )
        if not matches:
            return True
        # Longest octet match wins; Allow wins an equivalent tie. The final
        # ordinal key makes duplicate rules deterministic without changing access.
        _specificity, allowed, _ordinal = max(matches)
        return allowed


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    access: Literal["allowed", "blocked"]
    reason_code: BoundedReason
    reused: bool
    policy: RobotsPolicy | None

    @property
    def allowed(self) -> bool:
        return self.access == "allowed"


def _without_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def parse_robots(
    body: bytes,
    *,
    parse_limit_bytes: int = ROBOTS_RFC_MINIMUM_BYTES,
    sitemap_limit: int = 64,
) -> RobotsPolicy:
    """Parse bounded UTF-8 robots bytes using RFC groups and parseable rules."""

    if (
        isinstance(parse_limit_bytes, bool)
        or not isinstance(parse_limit_bytes, int)
        or parse_limit_bytes < ROBOTS_RFC_MINIMUM_BYTES
        or parse_limit_bytes > _MAX_ROBOTS_BYTES
    ):
        raise ValueError("robots parse limit is outside the trusted range")
    if (
        isinstance(sitemap_limit, bool)
        or not isinstance(sitemap_limit, int)
        or sitemap_limit <= 0
        or sitemap_limit > 1_000
    ):
        raise ValueError("robots Sitemap limit is outside the trusted range")
    if not isinstance(body, bytes) or len(body) > parse_limit_bytes:
        raise RobotsParseError("robots body exceeds its trusted byte limit")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RobotsParseError("robots body is not valid UTF-8") from error

    groups: list[RobotsGroup] = []
    active_agents: list[str] = []
    active_rules: list[RobotsRule] = []
    rules_started = False
    sitemap_locators: list[str] = []
    ordinal = 0

    def finish_group() -> None:
        nonlocal active_agents, active_rules, rules_started
        if active_agents:
            groups.append(
                RobotsGroup(
                    user_agents=tuple(dict.fromkeys(active_agents)),
                    rules=tuple(active_rules),
                )
            )
        active_agents = []
        active_rules = []
        rules_started = False

    for raw_line in text.splitlines():
        line = _without_comment(raw_line)
        if not line or ":" not in line:
            continue
        raw_field, raw_value = line.split(":", 1)
        field = raw_field.strip().casefold()
        value = raw_value.strip()

        if field == "user-agent":
            if value != "*" and _PRODUCT_TOKEN.fullmatch(value) is None:
                continue
            if active_agents and rules_started:
                finish_group()
            active_agents.append(value.casefold())
            continue

        if field in {"allow", "disallow"}:
            if not active_agents:
                continue
            rules_started = True
            # RFC empty patterns express no restriction and are ignored.
            if not value:
                continue
            ordinal += 1
            active_rules.append(
                RobotsRule(
                    directive=field,
                    pattern=value,
                    ordinal=ordinal,
                )
            )
            continue

        if field == "sitemap" and value:
            if len(sitemap_locators) >= sitemap_limit:
                raise RobotsParseError("robots body exceeds its Sitemap limit")
            sitemap_locators.append(value)

    finish_group()
    return RobotsPolicy(
        groups=tuple(groups),
        sitemap_locators=tuple(sorted(set(sitemap_locators))),
    )


def admit_public_sitemap_locators(
    observations: Iterable[str],
) -> tuple[SafeLocator, ...]:
    """Admit Sitemap observations only after public-locator validation.

    ``parse_robots`` records raw ``Sitemap:`` values as untrusted observations.
    This helper is the fail-closed gate before any later fetch. It does not
    retrieve bytes, walk indexes, or enumerate documents.
    """

    if isinstance(observations, (str, bytes)) or not isinstance(observations, Iterable):
        raise ValueError("sitemap observations must be a string iterable")
    admitted: dict[str, SafeLocator] = {}
    for value in observations:
        if not isinstance(value, str):
            raise ValueError("sitemap observation is not a string")
        if not value:
            continue
        try:
            locator = validate_public_locator(value)
        except DiscoveryTransportError:
            continue
        admitted[locator.url] = locator
    return tuple(admitted[url] for url in sorted(admitted))


def evaluate_robots(
    *,
    transport_state: RobotsTransportState,
    status_code: int | None,
    body: bytes | None,
    product_token: str,
    request_target: str,
    cached_age_seconds: int | None = None,
    maximum_cache_age_seconds: int = ROBOTS_MAX_CACHE_AGE_SECONDS,
    parse_limit_bytes: int = ROBOTS_RFC_MINIMUM_BYTES,
    sitemap_limit: int = 64,
) -> RobotsDecision:
    """Classify one captured robots observation without network or cache access."""

    if (
        isinstance(maximum_cache_age_seconds, bool)
        or not isinstance(maximum_cache_age_seconds, int)
        or maximum_cache_age_seconds <= 0
        or maximum_cache_age_seconds > ROBOTS_MAX_CACHE_AGE_SECONDS
    ):
        raise ValueError("robots cache age exceeds 24 hours")
    if transport_state == "verified_cache":
        if (
            isinstance(cached_age_seconds, bool)
            or not isinstance(cached_age_seconds, int)
            or cached_age_seconds < 0
            or cached_age_seconds > maximum_cache_age_seconds
            or body is None
        ):
            return RobotsDecision(
                access="blocked",
                reason_code=BoundedReason.EVIDENCE_STALE,
                reused=False,
                policy=None,
            )
        return _decision_from_body(
            body,
            product_token=product_token,
            request_target=request_target,
            reused=True,
            parse_limit_bytes=parse_limit_bytes,
            sitemap_limit=sitemap_limit,
        )

    if transport_state == "network_unreachable":
        return RobotsDecision(
            access="blocked",
            reason_code=BoundedReason.TRANSPORT_REJECTED,
            reused=False,
            policy=None,
        )
    if transport_state == "security_rejected_redirect":
        return RobotsDecision(
            access="blocked",
            reason_code=BoundedReason.REDIRECT_REJECTED,
            reused=False,
            policy=None,
        )
    if status_code is None or isinstance(status_code, bool):
        return RobotsDecision(
            access="blocked",
            reason_code=BoundedReason.TRANSPORT_REJECTED,
            reused=False,
            policy=None,
        )
    if 400 <= status_code <= 499:
        return RobotsDecision(
            access="allowed",
            reason_code=BoundedReason.NONE,
            reused=False,
            policy=RobotsPolicy(groups=(), sitemap_locators=()),
        )
    if not 200 <= status_code <= 299:
        return RobotsDecision(
            access="blocked",
            reason_code=(
                BoundedReason.REDIRECT_REJECTED
                if 300 <= status_code <= 399
                else BoundedReason.ACCESS_BLOCKED
            ),
            reused=False,
            policy=None,
        )
    if body is None:
        return RobotsDecision(
            access="blocked",
            reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
            reused=False,
            policy=None,
        )
    return _decision_from_body(
        body,
        product_token=product_token,
        request_target=request_target,
        reused=False,
        parse_limit_bytes=parse_limit_bytes,
        sitemap_limit=sitemap_limit,
    )


def _decision_from_body(
    body: bytes,
    *,
    product_token: str,
    request_target: str,
    reused: bool,
    parse_limit_bytes: int,
    sitemap_limit: int,
) -> RobotsDecision:
    try:
        policy = parse_robots(
            body,
            parse_limit_bytes=parse_limit_bytes,
            sitemap_limit=sitemap_limit,
        )
        allowed = policy.access_for(
            product_token=product_token,
            request_target=request_target,
        )
    except (RobotsParseError, ValueError):
        return RobotsDecision(
            access="blocked",
            reason_code=BoundedReason.PARSER_REJECTED,
            reused=reused,
            policy=None,
        )
    return RobotsDecision(
        access="allowed" if allowed else "blocked",
        reason_code=BoundedReason.NONE if allowed else BoundedReason.ACCESS_BLOCKED,
        reused=reused,
        policy=policy,
    )


def _request_target(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("robots request target is invalid")
    if value.startswith("https://"):
        locator = validate_public_locator(value)
        parsed = urlsplit(locator.url)
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if not value.startswith("/") or "#" in value:
        raise ValueError("robots request target must be an origin-form path")
    return value


def _normalize_octets(value: str, *, pattern: bool) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "%" and index + 2 < len(value):
            encoded = value[index + 1 : index + 3]
            if re.fullmatch(r"[0-9A-Fa-f]{2}", encoded):
                octet = int(encoded, 16)
                if octet in _UNRESERVED:
                    output.append(chr(octet))
                else:
                    output.append(f"%{octet:02X}")
                index += 3
                continue
        if pattern and character == "*":
            output.append("*")
        elif ord(character) < 128 and 0x21 <= ord(character) <= 0x7E:
            output.append(character)
        else:
            output.extend(f"%{octet:02X}" for octet in character.encode("utf-8"))
        index += 1
    return "".join(output)


def _rule_matches(pattern: str, request_target: str) -> tuple[bool, int]:
    terminal = pattern.endswith("$") and not pattern.endswith("%24")
    raw_pattern = pattern[:-1] if terminal else pattern
    normalized_pattern = _normalize_octets(raw_pattern, pattern=True)
    normalized_target = _normalize_octets(request_target, pattern=False)
    expression = "".join(
        ".*" if part == "*" else re.escape(part)
        for part in normalized_pattern
    )
    if terminal:
        expression += "$"
    matched = re.match(f"^{expression}", normalized_target) is not None
    specificity = _octet_length(normalized_pattern.replace("*", ""))
    return matched, specificity


def _octet_length(value: str) -> int:
    count = 0
    index = 0
    while index < len(value):
        if value[index] == "%" and re.fullmatch(
            r"[0-9A-F]{2}", value[index + 1 : index + 3]
        ):
            index += 3
        else:
            index += 1
        count += 1
    return count
