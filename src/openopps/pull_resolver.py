from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import re
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from openopps.http import PublicFetchSafetyError
from openopps.models import validate_public_https_url
from openopps.pull_models import (
    DiscoveryMethod,
    PullDomainError,
    PullErrorCode,
    PullOperation,
    PullProvenance,
)
from openopps.providers.pull import (
    ProviderPullCapabilities,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.settings import OpenOppsSettings

if TYPE_CHECKING:
    from openopps.http import ResponseByteBudget


_ABSOLUTE_URL_RE = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)
_RAW_CANDIDATE_MULTIPLIER = 8
_SLUG_TITLE_CHARS_PER_CANDIDATE = 128
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,98}[a-z0-9])?", re.IGNORECASE)
_IGNORED_SLUGS = frozenset(
    {
        "www",
        "careers",
        "career",
        "jobs",
        "job",
        "work",
        "openings",
        "opportunities",
        "com",
        "org",
        "net",
        "io",
        "co",
        "example",
    }
)


@dataclass(frozen=True)
class PullResolverLimits:
    """Finite one-page resolution budgets independent from remote input."""

    max_candidates: int = 32
    max_probes: int = 12
    max_probes_per_provider: int = 4
    max_origins: int = 8
    max_redirects: int = 5
    max_requests: int = 24
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        values = (
            self.max_candidates,
            self.max_probes,
            self.max_probes_per_provider,
            self.max_origins,
            self.max_redirects,
            self.max_requests,
        )
        if any(value < 1 for value in values):
            raise ValueError("pull resolver limits must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("pull resolver timeout must be positive")

    @classmethod
    def from_settings(cls, settings: OpenOppsSettings) -> PullResolverLimits:
        return cls(
            max_candidates=int(settings.pull_resolver_max_candidates),
            max_probes=int(settings.pull_resolver_max_probes),
            max_probes_per_provider=int(settings.pull_resolver_max_probes_per_provider),
            max_origins=int(settings.pull_resolver_max_origins),
            max_redirects=int(settings.pull_resolver_max_redirects),
            max_requests=int(settings.pull_resolver_max_requests),
            timeout_seconds=float(settings.pull_resolver_timeout_seconds),
        )


@dataclass(frozen=True)
class PullFetchedPage:
    """Bounded page body plus validated redirect provenance from shared HTTP."""

    body: str
    url: str
    redirect_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class PullResolution:
    target: ProviderUrlTarget
    provenance: PullProvenance


class _ProbeCandidate(Protocol):
    provider_id: str
    url: str


class _ResolverRegistry(Protocol):
    def detect_targets(self, url: str) -> tuple[ProviderUrlTarget, ...]: ...

    def pull_capabilities(
        self, provider_id: str
    ) -> ProviderPullCapabilities | None: ...

    def probe_candidates(self, slug: str) -> Sequence[_ProbeCandidate]: ...


class PullRequestBudgetGuard(Protocol):
    """Callable request guard carrying resolution-local response accounting."""

    state: _BudgetState

    def __call__(self, url: str, is_redirect: bool) -> None: ...


PullPageFetcher = Callable[
    [httpx.AsyncClient, str, PullRequestBudgetGuard], Awaitable[PullFetchedPage]
]


@dataclass
class _BudgetState:
    limits: PullResolverLimits
    response_byte_budget: ResponseByteBudget | None = None
    requests: int = 0
    candidates: int = 0
    probes: int = 0
    probes_by_provider: dict[str, int] = field(default_factory=dict)
    redirects: int = 0
    origins: set[tuple[str, str, int]] = field(default_factory=set)
    visited_urls: list[str] = field(default_factory=list)
    probed_slugs: list[str] = field(default_factory=list)

    def add_candidate(self) -> None:
        self.candidates += 1
        if self.candidates > self.limits.max_candidates:
            _raise_budget("The careers page exposed too many candidate URLs.")

    def add_probe(self, provider_id: str) -> None:
        self.probes += 1
        if self.probes > self.limits.max_probes:
            _raise_budget("Provider slug probes exhausted the configured budget.")
        provider_probes = self.probes_by_provider.get(provider_id, 0) + 1
        self.probes_by_provider[provider_id] = provider_probes
        if provider_probes > self.limits.max_probes_per_provider:
            _raise_budget(
                "A provider exhausted its configured URL-resolution probe budget."
            )

    def add_request(self, url: str) -> None:
        self.requests += 1
        if self.requests > self.limits.max_requests:
            _raise_budget("URL resolution exhausted the configured request budget.")
        self.add_url(url)

    def add_url(self, url: str) -> None:
        try:
            validate_public_https_url(url)
        except ValueError as exc:
            raise _unsafe_url_error() from exc
        sanitized = _sanitize_url(url)
        if sanitized not in self.visited_urls:
            self.visited_urls.append(sanitized)
        parsed = urlsplit(url)
        host = parsed.hostname
        if host is None:
            raise ValueError("URL must include a host")
        port = parsed.port or 443
        self.origins.add((parsed.scheme.lower(), host.lower(), port))
        if len(self.origins) > self.limits.max_origins:
            _raise_budget("URL resolution exhausted the configured origin budget.")

    def add_redirect(self) -> None:
        self.redirects += 1
        if self.redirects > self.limits.max_redirects:
            _raise_budget("URL resolution exhausted the configured redirect budget.")

    def begin_fetch(self, url: str) -> _FetchBudgetGuard:
        self.add_request(url)
        return _FetchBudgetGuard(state=self)


@dataclass
class _FetchBudgetGuard:
    state: _BudgetState
    initial_request_precharged: bool = True
    redirects_charged: int = 0

    def __call__(self, url: str, is_redirect: bool) -> None:
        if self.initial_request_precharged:
            self.initial_request_precharged = False
        else:
            self.state.add_request(url)
        if is_redirect:
            self.state.add_redirect()
            self.redirects_charged += 1


class PullResolver:
    """Resolve one public URL without recursion, scouting, or catalog mutation."""

    def __init__(
        self,
        registry: _ResolverRegistry,
        *,
        fetch_page: PullPageFetcher,
        limits: PullResolverLimits | None = None,
        response_byte_budget_factory: Callable[[], ResponseByteBudget] | None = None,
    ) -> None:
        self._registry = registry
        self._fetch_page = fetch_page
        self.limits = limits or PullResolverLimits()
        self._response_byte_budget_factory = response_byte_budget_factory

    @classmethod
    def from_settings(
        cls,
        registry: _ResolverRegistry,
        settings: OpenOppsSettings,
    ) -> PullResolver:
        """Build a resolver on the shared retry/cache/redirect/limit HTTP path."""

        limits = PullResolverLimits.from_settings(settings)
        from openopps.http import ResponseByteBudget, retrying_text_response

        request = retrying_text_response(settings)

        def response_byte_budget_factory() -> ResponseByteBudget:
            return ResponseByteBudget(
                maximum_bytes=(
                    settings.http_max_decoded_response_bytes * limits.max_requests
                )
            )

        async def fetch_page(
            client: httpx.AsyncClient,
            url: str,
            request_budget_guard: PullRequestBudgetGuard,
        ) -> PullFetchedPage:
            response = await request(
                client,
                "GET",
                url,
                follow_redirects=True,
                max_redirects=limits.max_redirects,
                request_budget_guard=request_budget_guard,
                response_byte_budget=request_budget_guard.state.response_byte_budget,
                cache_namespace="url-pull-resolution",
                cache_identity={"operation": "careers_resolution"},
            )
            return PullFetchedPage(
                body=cast(str, response.body),
                url=response.url,
                redirect_urls=response.redirect_urls,
            )

        return cls(
            registry,
            fetch_page=fetch_page,
            limits=limits,
            response_byte_budget_factory=response_byte_budget_factory,
        )

    async def resolve(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation = PullOperation.AUTO,
        direct: bool = False,
        probe: bool = True,
    ) -> PullResolution:
        try:
            validate_public_https_url(url)
        except ValueError as exc:
            raise _unsafe_url_error() from exc
        state = _BudgetState(
            self.limits,
            response_byte_budget=(
                self._response_byte_budget_factory()
                if self._response_byte_budget_factory is not None
                else None
            ),
        )
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                return await self._resolve(
                    client,
                    url,
                    operation=operation,
                    direct=direct,
                    probe=probe,
                    state=state,
                )
        except TimeoutError as exc:
            raise PullDomainError(
                PullErrorCode.BUDGET_EXCEEDED,
                "URL resolution exceeded its wall-clock budget.",
                hint="Use --direct with a supported ATS URL or raise the trusted limit.",
            ) from exc

    async def _resolve(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        operation: PullOperation,
        direct: bool,
        probe: bool,
        state: _BudgetState,
    ) -> PullResolution:
        native = [
            (target, DiscoveryMethod.NATIVE_URL)
            for target in self._registry.detect_targets(url)
        ]
        if native:
            return self._finish(
                requested_url=url,
                requested_operation=operation,
                candidates=native,
                state=state,
            )
        if direct:
            raise PullDomainError(
                PullErrorCode.UNRECOGNIZED_TARGET,
                "The URL is not a recognized native provider target.",
                hint="Remove --direct to allow one bounded careers-page pass.",
            )

        page = await self._fetch(client, url, state)
        redirected_candidates: list[tuple[ProviderUrlTarget, DiscoveryMethod]] = []
        for visited_url in (*page.redirect_urls, page.url):
            redirected_candidates.extend(
                (target, DiscoveryMethod.REDIRECT)
                for target in self._registry.detect_targets(visited_url)
            )
        if redirected_candidates:
            return self._finish(
                requested_url=url,
                requested_operation=operation,
                candidates=redirected_candidates,
                state=state,
            )

        extracted = _extract_candidate_urls(
            page.body,
            base_url=page.url,
            state=state,
            is_native_target=lambda candidate_url: bool(
                self._registry.detect_targets(candidate_url)
            ),
        )
        page_candidates: list[tuple[ProviderUrlTarget, DiscoveryMethod]] = []
        for candidate_url, method in extracted:
            page_candidates.extend(
                (target, method)
                for target in self._registry.detect_targets(candidate_url)
            )
        if page_candidates:
            return self._finish(
                requested_url=url,
                requested_operation=operation,
                candidates=page_candidates,
                state=state,
            )

        if probe:
            probed = await self._probe(
                client,
                page,
                operation=operation,
                state=state,
            )
            if probed:
                return self._finish(
                    requested_url=url,
                    requested_operation=operation,
                    candidates=probed,
                    state=state,
                )

        raise PullDomainError(
            PullErrorCode.UNRECOGNIZED_TARGET,
            "No supported provider target was found in the bounded careers-page pass.",
            hint="Use providers inspect for provenance or pass a native ATS URL.",
        )

    async def _probe(
        self,
        client: httpx.AsyncClient,
        page: PullFetchedPage,
        *,
        operation: PullOperation,
        state: _BudgetState,
    ) -> list[tuple[ProviderUrlTarget, DiscoveryMethod]]:
        matches: list[tuple[ProviderUrlTarget, DiscoveryMethod]] = []
        for slug in _slug_candidates(
            page.url,
            page.body,
            max_candidates=state.limits.max_candidates,
        ):
            probe_candidates = self._registry.probe_candidates(slug)
            if not probe_candidates:
                continue
            if slug not in state.probed_slugs:
                state.probed_slugs.append(slug)
            for candidate in probe_candidates:
                capabilities = self._registry.pull_capabilities(candidate.provider_id)
                if not _provider_might_support_probe(capabilities, operation):
                    continue
                state.add_probe(candidate.provider_id)
                state.add_candidate()
                try:
                    probed_page = await self._fetch(client, candidate.url, state)
                except PullDomainError as exc:
                    if exc.code == PullErrorCode.TRANSPORT_FAILED:
                        continue
                    raise
                detected: list[ProviderUrlTarget] = []
                for detected_url in (
                    candidate.url,
                    *probed_page.redirect_urls,
                    probed_page.url,
                ):
                    detected.extend(self._registry.detect_targets(detected_url))
                matches.extend(
                    (target, DiscoveryMethod.SLUG_PROBE)
                    for target in detected
                    if target.provider_id == candidate.provider_id
                    and (
                        (resolved := _resolved_operation(target, operation)) is not None
                    )
                    and _supports(capabilities, target, resolved)
                )
        return matches

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        state: _BudgetState,
    ) -> PullFetchedPage:
        request_budget_guard = state.begin_fetch(url)
        try:
            page = await self._fetch_page(client, url, request_budget_guard)
            for redirect_url in page.redirect_urls[
                request_budget_guard.redirects_charged :
            ]:
                state.add_request(redirect_url)
                state.add_redirect()
            state.add_url(page.url)
            return page
        except PullDomainError:
            raise
        except PublicFetchSafetyError as exc:
            raise _unsafe_url_error() from exc
        except Exception as exc:
            if type(exc).__name__ == "HttpResponseLimitError":
                raise PullDomainError(
                    PullErrorCode.RESPONSE_TOO_LARGE,
                    "A URL-resolution response exceeded its configured size limit.",
                    hint="Use a native ATS URL or adjust the trusted response limit.",
                ) from exc
            raise PullDomainError(
                PullErrorCode.TRANSPORT_FAILED,
                "A bounded URL-resolution request failed.",
                hint="Retry later or use providers inspect to review the target.",
            ) from exc

    def _finish(
        self,
        *,
        requested_url: str,
        requested_operation: PullOperation,
        candidates: Sequence[tuple[ProviderUrlTarget, DiscoveryMethod]],
        state: _BudgetState,
    ) -> PullResolution:
        recognized = bool(candidates)
        executable: dict[
            tuple[str, ProviderTargetKind, str, str | None],
            tuple[ProviderUrlTarget, DiscoveryMethod, PullOperation],
        ] = {}
        for target, method in candidates:
            resolved_operation = _resolved_operation(target, requested_operation)
            if resolved_operation is None:
                continue
            capabilities = self._registry.pull_capabilities(target.provider_id)
            if not _supports(capabilities, target, resolved_operation):
                continue
            key = (
                target.provider_id,
                target.target_kind,
                target.board_identity,
                target.posting_identity,
            )
            executable.setdefault(key, (target, method, resolved_operation))

        if not executable:
            code = (
                PullErrorCode.UNSUPPORTED_OPERATION
                if recognized
                else PullErrorCode.UNRECOGNIZED_TARGET
            )
            raise PullDomainError(
                code,
                "The recognized provider target cannot perform the requested operation.",
                hint="Inspect provider capabilities or choose a compatible URL and operation.",
            )
        if len(executable) > 1:
            raise PullDomainError(
                PullErrorCode.AMBIGUOUS_TARGET,
                "The bounded resolution pass found multiple provider targets.",
                hint="Pass one native ATS URL or use --direct to avoid discovery.",
            )

        target, method, resolved_operation = next(iter(executable.values()))
        provenance = PullProvenance(
            requested_url=requested_url,
            resolved_url=target.url,
            discovery_method=method,
            provider_id=target.provider_id,
            requested_operation=requested_operation,
            resolved_operation=resolved_operation,
            board_identity=target.board_identity,
            posting_identity=target.posting_identity,
            visited_urls=tuple(state.visited_urls),
            probed_slugs=tuple(state.probed_slugs),
        )
        return PullResolution(target=target, provenance=provenance)


class _CareersPageParser(HTMLParser):
    def __init__(
        self,
        *,
        max_candidates: int | None = None,
        collect_candidates: bool = True,
        max_title_characters: int | None = None,
        candidate_sink: Callable[[str, DiscoveryMethod], None] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[tuple[str, DiscoveryMethod]] = []
        self.title_parts: list[str] = []
        self._max_candidates = max_candidates
        self._collect_candidates = collect_candidates
        self._max_title_characters = max_title_characters
        self._candidate_sink = candidate_sink
        self._title_characters = 0
        self._in_title = False
        self._script_method: DiscoveryMethod | None = None

    def _record_candidate(self, url: str, method: DiscoveryMethod) -> None:
        if self._candidate_sink is not None:
            self._candidate_sink(url, method)
            return
        if not self._collect_candidates:
            return
        if (
            self._max_candidates is not None
            and len(self.candidates) >= self._max_candidates
        ):
            _raise_budget("The careers page exposed too many raw candidate URLs.")
        self.candidates.append((url, method))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value for key, value in attrs if value}
        normalized_tag = tag.casefold()
        if normalized_tag == "a" and "href" in attributes:
            self._record_candidate(attributes["href"], DiscoveryMethod.PAGE_LINK)
        elif normalized_tag == "link" and "href" in attributes:
            rel = attributes.get("rel", "").casefold().split()
            method = (
                DiscoveryMethod.CANONICAL_LINK
                if "canonical" in rel
                else DiscoveryMethod.METADATA_LINK
            )
            self._record_candidate(attributes["href"], method)
        elif normalized_tag == "meta" and "content" in attributes:
            name = (
                attributes.get("property") or attributes.get("name") or ""
            ).casefold()
            if "url" in name or "job" in name or "career" in name:
                self._record_candidate(
                    attributes["content"], DiscoveryMethod.METADATA_LINK
                )
        elif normalized_tag == "script":
            script_url = (
                attributes.get("src")
                or attributes.get("data-src")
                or attributes.get("data-rocket-src")
            )
            if script_url:
                self._record_candidate(script_url, DiscoveryMethod.EMBEDDED_URL)
            script_type = attributes.get("type", "").casefold()
            self._script_method = (
                DiscoveryMethod.JSON_LD
                if script_type == "application/ld+json"
                else DiscoveryMethod.EMBEDDED_URL
            )
        elif normalized_tag == "iframe":
            frame_url = attributes.get("src") or attributes.get("data-src")
            if frame_url:
                self._record_candidate(frame_url, DiscoveryMethod.EMBEDDED_URL)
        elif normalized_tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "script":
            self._script_method = None
        elif normalized_tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self._max_title_characters is not None:
            self._title_characters += len(data)
            if self._title_characters > self._max_title_characters:
                _raise_budget("The careers-page title exceeded its probe scan budget.")
            self.title_parts.append(data)
        if self._script_method is not None:
            for match in _ABSOLUTE_URL_RE.finditer(unescape(data)):
                self._record_candidate(match.group(0), self._script_method)


def _extract_candidate_urls(
    body: str,
    *,
    base_url: str,
    state: _BudgetState,
    is_native_target: Callable[[str], bool],
) -> list[tuple[str, DiscoveryMethod]]:
    native = _extract_native_candidate_urls(
        body,
        base_url=base_url,
        state=state,
        is_native_target=is_native_target,
    )
    if native:
        return native

    raw_candidate_limit = state.limits.max_candidates * _RAW_CANDIDATE_MULTIPLIER
    parser = _CareersPageParser(max_candidates=raw_candidate_limit)
    parser.feed(body)

    raw_candidates = list(parser.candidates)
    raw_candidates_seen = len(parser.candidates)
    decoded = unescape(body)
    for _ in range(2):
        for match in _ABSOLUTE_URL_RE.finditer(decoded):
            raw_candidates_seen += 1
            if raw_candidates_seen > raw_candidate_limit:
                _raise_budget("The careers page exposed too many raw candidate URLs.")
            raw_candidates.append((match.group(0), DiscoveryMethod.EMBEDDED_URL))
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded

    normalized: list[tuple[str, DiscoveryMethod]] = []
    seen: set[str] = set()
    for raw_url, method in raw_candidates:
        candidate_url = _clean_candidate_url(urljoin(base_url, raw_url))
        try:
            validate_public_https_url(candidate_url)
        except ValueError:
            continue
        if candidate_url in seen:
            continue
        seen.add(candidate_url)
        normalized.append((candidate_url, method))

    admitted: list[tuple[str, DiscoveryMethod]] = []
    for candidate in normalized:
        state.add_candidate()
        admitted.append(candidate)
    return admitted


def _extract_native_candidate_urls(
    body: str,
    *,
    base_url: str,
    state: _BudgetState,
    is_native_target: Callable[[str], bool],
) -> list[tuple[str, DiscoveryMethod]]:
    admitted: list[tuple[str, DiscoveryMethod]] = []
    seen: set[str] = set()

    def admit(raw_url: str, method: DiscoveryMethod) -> None:
        candidate_url = _clean_candidate_url(urljoin(base_url, raw_url))
        try:
            validate_public_https_url(candidate_url)
        except ValueError:
            return
        if candidate_url in seen or not is_native_target(candidate_url):
            return
        seen.add(candidate_url)
        state.add_candidate()
        admitted.append((candidate_url, method))

    parser = _CareersPageParser(
        collect_candidates=False,
        candidate_sink=admit,
    )
    parser.feed(body)

    decoded = unescape(body)
    for _ in range(2):
        for match in _ABSOLUTE_URL_RE.finditer(decoded):
            admit(match.group(0), DiscoveryMethod.EMBEDDED_URL)
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    return admitted


def _slug_candidates(
    url: str,
    body: str,
    *,
    max_candidates: int,
) -> tuple[str, ...]:
    parser = _CareersPageParser(
        collect_candidates=False,
        max_title_characters=(max_candidates * _SLUG_TITLE_CHARS_PER_CANDIDATE),
    )
    parser.feed(body)
    parsed = urlsplit(url)
    parts: list[str] = []
    if parsed.hostname:
        parts.extend(parsed.hostname.casefold().split("."))
    parts.extend(" ".join(parser.title_parts).casefold().split())
    candidates: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip("-_.:,;()[]{}")
        if cleaned in _IGNORED_SLUGS or not _SLUG_RE.fullmatch(cleaned):
            continue
        if cleaned in seen:
            continue
        if len(candidates) >= max_candidates:
            _raise_budget("The careers page exposed too many slug candidates.")
        seen.add(cleaned)
        candidates.append(cleaned)
    return tuple(candidates)


def _resolved_operation(
    target: ProviderUrlTarget,
    requested: PullOperation,
) -> PullOperation | None:
    if requested == PullOperation.AUTO:
        return (
            PullOperation.GET
            if target.target_kind == ProviderTargetKind.POSTING
            else PullOperation.LIST
        )
    if requested == PullOperation.LIST:
        return requested if target.target_kind == ProviderTargetKind.BOARD else None
    return requested if target.target_kind == ProviderTargetKind.POSTING else None


def _supports(
    capabilities: ProviderPullCapabilities | None,
    target: ProviderUrlTarget,
    operation: PullOperation,
) -> bool:
    if capabilities is None or not capabilities.detect_supported:
        return False
    if operation == PullOperation.LIST:
        return (
            capabilities.list_supported
            and target.target_kind == ProviderTargetKind.BOARD
        )
    if operation == PullOperation.GET:
        return target.target_kind == ProviderTargetKind.POSTING and (
            capabilities.native_get_supported or capabilities.board_scan_get_supported
        )
    return False


def _provider_might_support_probe(
    capabilities: ProviderPullCapabilities | None,
    operation: PullOperation,
) -> bool:
    if capabilities is None or not capabilities.detect_supported:
        return False
    if operation == PullOperation.LIST:
        return capabilities.list_supported
    if operation == PullOperation.GET:
        return (
            capabilities.native_get_supported or capabilities.board_scan_get_supported
        )
    return any(
        (
            capabilities.list_supported,
            capabilities.native_get_supported,
            capabilities.board_scan_get_supported,
        )
    )


def _clean_candidate_url(url: str) -> str:
    return url.rstrip('.,;:!?)]}"')


def _sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _raise_budget(message: str) -> None:
    raise PullDomainError(
        PullErrorCode.BUDGET_EXCEEDED,
        message,
        hint="Use a native ATS URL or adjust the trusted resolver limits.",
    )


def _unsafe_url_error() -> PullDomainError:
    return PullDomainError(
        PullErrorCode.UNSAFE_URL,
        "URL resolution rejected an unsafe public-fetch target.",
        hint="Use a public HTTPS URL whose host resolves only to global addresses.",
    )
