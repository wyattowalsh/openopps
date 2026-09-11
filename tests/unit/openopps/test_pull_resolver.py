from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
import sys
import textwrap

import httpx
import pytest

import openopps.pull_resolver as pull_resolver_module
from openopps.pull_models import PullDomainError, PullErrorCode, PullOperation
from openopps.pull_resolver import (
    PullFetchedPage,
    PullResolver,
    PullResolverLimits,
)
from openopps.providers.pull import (
    InterfaceStability,
    ProviderPullCapabilities,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.settings import OpenOppsSettings


def _target(
    *,
    provider_id: str = "greenhouse",
    board: str = "acme",
    posting: str | None = None,
    url: str | None = None,
) -> ProviderUrlTarget:
    return ProviderUrlTarget(
        provider_id=provider_id,
        target_kind=(
            ProviderTargetKind.POSTING
            if posting is not None
            else ProviderTargetKind.BOARD
        ),
        url=url
        or (
            f"https://boards.greenhouse.io/{board}/jobs/{posting}"
            if posting is not None
            else f"https://boards.greenhouse.io/{board}"
        ),
        board_identity=board,
        posting_identity=posting,
    )


def _capabilities(
    *,
    list_supported: bool = True,
    native_get_supported: bool = True,
    board_scan_get_supported: bool = True,
) -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        list_supported=list_supported,
        native_get_supported=native_get_supported,
        board_scan_get_supported=board_scan_get_supported,
        interface_stability=InterfaceStability.DOCUMENTED,
    )


@dataclass(frozen=True)
class _Probe:
    provider_id: str
    url: str


class _Registry:
    def __init__(
        self,
        *,
        targets: dict[str, tuple[ProviderUrlTarget, ...]],
        capabilities: dict[str, ProviderPullCapabilities],
        probes: dict[str, tuple[_Probe, ...]] | None = None,
    ) -> None:
        self.targets = targets
        self.capabilities = capabilities
        self.probes = probes or {}
        self.detected_urls: list[str] = []
        self.probed_slugs: list[str] = []

    def detect_targets(self, url: str) -> tuple[ProviderUrlTarget, ...]:
        self.detected_urls.append(url)
        return self.targets.get(url, ())

    def pull_capabilities(self, provider_id: str) -> ProviderPullCapabilities | None:
        return self.capabilities.get(provider_id)

    def probe_candidates(self, slug: str) -> tuple[_Probe, ...]:
        self.probed_slugs.append(slug)
        return self.probes.get(slug, ())


class _Fetcher:
    def __init__(self, pages: dict[str, PullFetchedPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def __call__(
        self,
        _client: httpx.AsyncClient,
        url: str,
        _request_budget_guard: object,
    ) -> PullFetchedPage:
        self.calls.append(url)
        return self.pages[url]


async def _resolve(
    resolver: PullResolver,
    url: str,
    **kwargs: object,
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        )
    ) as client:
        return await resolver.resolve(client, url, **kwargs)


@pytest.mark.asyncio
async def test_native_posting_resolves_without_network_and_auto_selects_get() -> None:
    url = "https://boards.greenhouse.io/acme/jobs/123"
    registry = _Registry(
        targets={url: (_target(posting="123", url=url),)},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher({})
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, url)

    assert resolution.target.posting_identity == "123"
    assert resolution.provenance.resolved_operation == PullOperation.GET
    assert resolution.provenance.discovery_method == "native_url"
    assert resolution.provenance.visited_urls == ()
    assert fetcher.calls == []


@pytest.mark.asyncio
async def test_direct_rejects_non_native_url_without_network() -> None:
    url = "https://careers.example.com/jobs"
    registry = _Registry(targets={}, capabilities={})
    fetcher = _Fetcher({})
    resolver = PullResolver(registry, fetch_page=fetcher)

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, url, direct=True)

    assert exc_info.value.code == PullErrorCode.UNRECOGNIZED_TARGET
    assert fetcher.calls == []


@pytest.mark.asyncio
async def test_initial_unsafe_url_uses_safety_domain_error() -> None:
    resolver = PullResolver(
        _Registry(targets={}, capabilities={}),
        fetch_page=_Fetcher({}),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, "http://careers.example.com/jobs")

    assert exc_info.value.code == PullErrorCode.UNSAFE_URL
    assert exc_info.value.process_status == 6


@pytest.mark.asyncio
async def test_private_redirect_uses_safety_domain_error_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    careers = "https://careers.example.test/jobs"
    private = "https://private.example.test/jobs"
    requested_hosts: list[str] = []

    def controlled_dns(
        host: str,
        port: int,
        **_kwargs: object,
    ) -> list[tuple[object, ...]]:
        address = "10.0.0.5" if host == "private.example.test" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(str(request.url.host))
        return httpx.Response(
            302,
            headers={"location": private},
            request=request,
        )

    monkeypatch.setattr("openopps.http.socket.getaddrinfo", controlled_dns)
    resolver = PullResolver.from_settings(
        _Registry(targets={}, capabilities={}),
        OpenOppsSettings(cache_enabled=False, retry_attempts=1),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await resolver.resolve(client, careers)

    assert exc_info.value.code == PullErrorCode.UNSAFE_URL
    assert requested_hosts == ["careers.example.test"]


@pytest.mark.asyncio
async def test_recognized_detect_only_target_fails_as_unsupported() -> None:
    url = "https://jobs.example.com/acme"
    registry = _Registry(
        targets={url: (_target(url=url),)},
        capabilities={
            "greenhouse": _capabilities(
                list_supported=False,
                native_get_supported=False,
                board_scan_get_supported=False,
            )
        },
    )
    resolver = PullResolver(registry, fetch_page=_Fetcher({}))

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, url)

    assert exc_info.value.code == PullErrorCode.UNSUPPORTED_OPERATION


@pytest.mark.asyncio
async def test_one_page_link_resolution_records_sanitized_provenance() -> None:
    careers = "https://careers.example.com/jobs?campaign=private"
    native = "https://boards.greenhouse.io/acme"
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=f'<html><a href="{native}">Open roles</a></html>',
                url="https://careers.example.com/jobs?campaign=private",
                redirect_urls=(),
            )
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers)

    assert resolution.target.board_identity == "acme"
    assert resolution.provenance.discovery_method == "page_link"
    assert resolution.provenance.requested_url == "https://careers.example.com/jobs"
    assert resolution.provenance.visited_urls == ("https://careers.example.com/jobs",)
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_method"),
    [
        (
            '<link rel="canonical" href="https://boards.greenhouse.io/acme">',
            "canonical_link",
        ),
        (
            '<link rel="alternate" href="https://boards.greenhouse.io/acme">',
            "metadata_link",
        ),
        (
            '<meta property="og:url" content="https://boards.greenhouse.io/acme">',
            "metadata_link",
        ),
        (
            '<script type="application/ld+json">'
            '{"url":"https://boards.greenhouse.io/acme"}'
            "</script>",
            "json_ld",
        ),
    ],
)
async def test_structured_page_metadata_resolves_with_exact_provenance_method(
    body: str,
    expected_method: str,
) -> None:
    careers = "https://careers.example.com/jobs"
    native = "https://boards.greenhouse.io/acme"
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher({careers: PullFetchedPage(body=body, url=careers)})
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers)

    assert resolution.target.url == native
    assert resolution.provenance.discovery_method == expected_method
    assert resolution.provenance.visited_urls == (careers,)
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_relative_links_use_validated_final_redirect_url() -> None:
    requested = "https://example.com/careers"
    redirected = "https://careers.example.com/openings"
    native = "https://careers.example.com/ats/acme"
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher(
        {
            requested: PullFetchedPage(
                body='<a href="/ats/acme">ATS</a>',
                url=redirected,
                redirect_urls=(redirected,),
            )
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, requested)

    assert resolution.target.url == native
    assert resolution.provenance.visited_urls == (
        "https://example.com/careers",
        redirected,
    )


@pytest.mark.asyncio
async def test_encoded_ats_link_is_inspected_without_recursive_fetch() -> None:
    careers = "https://careers.example.com/jobs"
    native = "https://boards.greenhouse.io/acme"
    encoded = "https%3A%2F%2Fboards.greenhouse.io%2Facme"
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=f'<script>window.jobs = "{encoded}";</script>',
                url=careers,
            )
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers)

    assert resolution.target.url == native
    assert resolution.provenance.discovery_method == "embedded_url"
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_discovered_non_ats_page_is_not_fetched_recursively() -> None:
    careers = "https://careers.example.com/jobs"
    second_page = "https://careers.example.com/departments/engineering"
    registry = _Registry(targets={}, capabilities={})
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=f'<a href="{second_page}">Engineering</a>',
                url=careers,
            ),
            second_page: PullFetchedPage(
                body='<a href="https://boards.greenhouse.io/acme">ATS</a>',
                url=second_page,
            ),
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    with pytest.raises(PullDomainError):
        await _resolve(resolver, careers, probe=False)

    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_no_probe_keeps_page_inspection_but_skips_slug_candidates() -> None:
    careers = "https://careers.acme.example/jobs"
    registry = _Registry(
        targets={},
        capabilities={"greenhouse": _capabilities()},
        probes={"acme": (_Probe("greenhouse", "https://boards.greenhouse.io/acme"),)},
    )
    fetcher = _Fetcher({careers: PullFetchedPage(body="<html></html>", url=careers)})
    resolver = PullResolver(registry, fetch_page=fetcher)

    with pytest.raises(PullDomainError):
        await _resolve(resolver, careers, probe=False)

    assert registry.probed_slugs == []
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_capability_declared_slug_probe_is_fetched_within_budget() -> None:
    careers = "https://careers.acme.example/jobs"
    probe_url = "https://boards.greenhouse.io/acme"
    registry = _Registry(
        targets={probe_url: (_target(url=probe_url),)},
        capabilities={"greenhouse": _capabilities()},
        probes={"acme": (_Probe("greenhouse", probe_url),)},
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(body="<title>Acme Careers</title>", url=careers),
            probe_url: PullFetchedPage(body='{"jobs": []}', url=probe_url),
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers)

    assert resolution.target.url == probe_url
    assert resolution.provenance.discovery_method == "slug_probe"
    assert resolution.provenance.probed_slugs == ("acme",)
    assert fetcher.calls == [careers, probe_url]


@pytest.mark.asyncio
async def test_multiple_non_equivalent_executable_targets_are_ambiguous() -> None:
    careers = "https://careers.example.com/jobs"
    first = "https://boards.greenhouse.io/acme"
    second = "https://jobs.lever.co/acme"
    registry = _Registry(
        targets={
            first: (_target(url=first),),
            second: (_target(provider_id="lever", url=second),),
        },
        capabilities={
            "greenhouse": _capabilities(),
            "lever": _capabilities(),
        },
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=f'<a href="{first}">One</a><a href="{second}">Two</a>',
                url=careers,
            )
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.AMBIGUOUS_TARGET


@pytest.mark.asyncio
async def test_candidate_budget_exhaustion_fails_before_probe() -> None:
    careers = "https://careers.example.com/jobs"
    registry = _Registry(targets={}, capabilities={})
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=(
                    '<a href="https://one.example/jobs">One</a>'
                    '<a href="https://two.example/jobs">Two</a>'
                ),
                url=careers,
            )
        }
    )
    resolver = PullResolver(
        registry,
        fetch_page=fetcher,
        limits=PullResolverLimits(max_candidates=1),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert registry.probed_slugs == []


@pytest.mark.asyncio
async def test_native_ats_url_is_prioritized_over_noisy_page_candidates() -> None:
    careers = "https://tenex.example/careers/open-positions/"
    native = "https://jobs.ashbyhq.com/tenex/embed?version=2"
    noise = "".join(
        f'<a href="https://asset-{index}.example/resource">Asset</a>'
        for index in range(400)
    )
    target = _target(provider_id="ashby", board="tenex", url=native)
    registry = _Registry(
        targets={native: (target,)},
        capabilities={"ashby": _capabilities()},
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=(
                    f"{noise}"
                    f'<script data-rocket-src="{native}"></script>'
                ),
                url=careers,
            )
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers)

    assert resolution.target == target
    assert resolution.provenance.discovery_method == "embedded_url"
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_raw_candidate_parsing_stops_at_bounded_multiple() -> None:
    careers = "https://careers.example.com/jobs"
    body = "".join(
        f'<a href="https://candidate-{index}.example/jobs">Job</a>'
        for index in range(100)
    )
    registry = _Registry(targets={}, capabilities={})
    fetcher = _Fetcher({careers: PullFetchedPage(body=body, url=careers)})
    resolver = PullResolver(
        registry,
        fetch_page=fetcher,
        limits=PullResolverLimits(max_candidates=1),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert fetcher.calls == [careers]


@pytest.mark.asyncio
async def test_slug_enumeration_stops_at_candidate_budget_before_builders() -> None:
    careers = "https://careers.example.com/jobs"
    registry = _Registry(
        targets={},
        capabilities={"greenhouse": _capabilities()},
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body="<title>alpha beta gamma</title>",
                url=careers,
            )
        }
    )
    resolver = PullResolver(
        registry,
        fetch_page=fetcher,
        limits=PullResolverLimits(max_candidates=2),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert registry.probed_slugs == []


@pytest.mark.asyncio
async def test_slug_title_scan_rejects_excess_remote_text_synchronously() -> None:
    careers = "https://careers.example.com/jobs"
    registry = _Registry(targets={}, capabilities={})
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body=f"<title>{'!' * 1024}</title>",
                url=careers,
            )
        }
    )
    resolver = PullResolver(
        registry,
        fetch_page=fetcher,
        limits=PullResolverLimits(max_candidates=1),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert registry.probed_slugs == []


@pytest.mark.asyncio
async def test_per_provider_probe_budget_is_independent_from_global_budget() -> None:
    careers = "https://careers.alpha.example/jobs"
    first = "https://failed.example.test/one"
    second = "https://failed.example.test/two"
    registry = _Registry(
        targets={},
        capabilities={"greenhouse": _capabilities()},
        probes={
            "alpha": (
                _Probe("greenhouse", first),
                _Probe("greenhouse", second),
            )
        },
    )
    fetcher = _Fetcher({careers: PullFetchedPage(body="<html></html>", url=careers)})
    resolver = PullResolver(
        registry,
        fetch_page=fetcher,
        limits=PullResolverLimits(
            max_probes=10,
            max_probes_per_provider=1,
        ),
    )

    with pytest.raises(PullDomainError) as exc_info:
        await _resolve(resolver, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert first in fetcher.calls
    assert second not in fetcher.calls


@pytest.mark.asyncio
async def test_request_budget_blocks_retry_before_second_network_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    careers = "https://careers.example.test/jobs"
    native = "https://boards.greenhouse.io/acme"
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    calls = 0

    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            text=f'<a href="{native}">Jobs</a>',
            request=request,
        )

    monkeypatch.setattr("openopps.http.assert_public_fetch_url", allow_public_url)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=2,
        pull_resolver_max_requests=1,
    )
    resolver = PullResolver.from_settings(registry, settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await resolver.resolve(client, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert calls == 1


@pytest.mark.asyncio
async def test_response_byte_budget_is_fresh_for_each_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    careers = "https://careers.example.test/jobs"
    native = "https://boards.greenhouse.io/acme"
    body = f'<a href="{native}">Jobs</a>'
    assert len(body.encode()) < 100
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )

    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, request=request)

    monkeypatch.setattr("openopps.http.assert_public_fetch_url", allow_public_url)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        http_max_encoded_response_bytes=100,
        http_max_decoded_response_bytes=100,
        pull_resolver_max_requests=1,
    )
    resolver = PullResolver.from_settings(registry, settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await resolver.resolve(client, careers)
        second = await resolver.resolve(client, careers)

    assert first.target == second.target
    assert first.target.url == native


@pytest.mark.asyncio
async def test_origin_budget_blocks_redirect_destination_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    careers = "https://careers.example.test/jobs"
    redirected = "https://other.example.test/jobs"
    registry = _Registry(targets={}, capabilities={})
    requested_hosts: list[str] = []

    async def allow_public_url(url: str) -> str:
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(str(request.url.host))
        if str(request.url) == careers:
            return httpx.Response(
                302,
                headers={"location": redirected},
                request=request,
            )
        return httpx.Response(200, text="<html></html>", request=request)

    monkeypatch.setattr("openopps.http.assert_public_fetch_url", allow_public_url)
    settings = OpenOppsSettings(
        cache_enabled=False,
        retry_attempts=1,
        pull_resolver_max_origins=1,
    )
    resolver = PullResolver.from_settings(registry, settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PullDomainError) as exc_info:
            await resolver.resolve(client, careers)

    assert exc_info.value.code == PullErrorCode.BUDGET_EXCEEDED
    assert requested_hosts == ["careers.example.test"]


def test_pull_resolver_import_graph_excludes_discovery_storage_and_catalog() -> None:
    assert pull_resolver_module.__file__ is not None
    source_path = Path(pull_resolver_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    forbidden_prefixes = (
        "openopps.discovery",
        "openopps.storage",
        "openopps.providers.sources",
    )
    assert not {name for name in imported if name.startswith(forbidden_prefixes)}


@pytest.mark.asyncio
async def test_pull_resolution_does_not_import_discovery_or_mutate_source_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = "https://boards.greenhouse.io/acme"
    catalog_before = tuple(
        (key, record.model_dump_json())
        for key, record in sorted(BOARD_SOURCE_CATALOG.items())
    )
    original_import = builtins.__import__

    def reject_discovery_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name.startswith("openopps.discovery"):
            raise AssertionError(
                "URL resolution must not import discovery or promotion"
            )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_discovery_import)
    registry = _Registry(
        targets={native: (_target(url=native),)},
        capabilities={"greenhouse": _capabilities()},
    )
    resolver = PullResolver(registry, fetch_page=_Fetcher({}))

    resolution = await _resolve(resolver, native)

    catalog_after = tuple(
        (key, record.model_dump_json())
        for key, record in sorted(BOARD_SOURCE_CATALOG.items())
    )
    assert resolution.target.url == native
    assert resolution.provenance.discovery_method == "native_url"
    assert catalog_after == catalog_before


def test_fresh_process_careers_resolution_preserves_discovery_isolation() -> None:
    script = textwrap.dedent(
        """
        import asyncio
        import builtins
        import sys

        import httpx

        from openopps.providers.sources import BOARD_SOURCE_CATALOG

        assert not any(
            name.startswith("openopps.discovery") for name in sys.modules
        )
        catalog_before = tuple(
            (key, record.model_dump_json())
            for key, record in sorted(BOARD_SOURCE_CATALOG.items())
        )
        original_import = builtins.__import__

        def reject_discovery_import(
            name,
            globals=None,
            locals=None,
            fromlist=(),
            level=0,
        ):
            if name.startswith("openopps.discovery"):
                raise AssertionError(
                    "careers resolution must not import discovery or promotion"
                )
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = reject_discovery_import

        from openopps.pull_resolver import PullFetchedPage, PullResolver
        from openopps.providers.pull import (
            InterfaceStability,
            ProviderPullCapabilities,
            ProviderTargetKind,
            ProviderUrlTarget,
        )

        careers = "https://careers.example.test/jobs"
        native = "https://boards.greenhouse.io/acme"
        target = ProviderUrlTarget(
            provider_id="greenhouse",
            target_kind=ProviderTargetKind.BOARD,
            url=native,
            board_identity="acme",
        )
        capabilities = ProviderPullCapabilities(
            list_supported=True,
            interface_stability=InterfaceStability.DOCUMENTED,
        )

        class Registry:
            def detect_targets(self, url):
                return (target,) if url == native else ()

            def pull_capabilities(self, provider_id):
                return capabilities if provider_id == "greenhouse" else None

            def probe_candidates(self, slug):
                return ()

        async def fetch_page(client, url, request_budget_guard):
            del client, request_budget_guard
            assert url == careers
            return PullFetchedPage(
                body=f'<a href="{native}">Open roles</a>',
                url=careers,
            )

        async def main():
            resolver = PullResolver(Registry(), fetch_page=fetch_page)
            async with httpx.AsyncClient() as client:
                resolution = await resolver.resolve(
                    client,
                    careers,
                    probe=False,
                )
            assert str(resolution.target.url) == native
            assert resolution.provenance.discovery_method == "page_link"

        asyncio.run(main())

        catalog_after = tuple(
            (key, record.model_dump_json())
            for key, record in sorted(BOARD_SOURCE_CATALOG.items())
        )
        assert catalog_after == catalog_before
        assert not any(
            name.startswith("openopps.discovery") for name in sys.modules
        )
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.asyncio
async def test_probe_continues_after_incompatible_and_failed_candidates() -> None:
    careers = "https://careers.alpha.example/jobs"
    incompatible = "https://boards.greenhouse.io/alpha"
    failed = "https://failed.example.test/alpha"
    valid = "https://jobs.lever.co/beta/posting-1"
    registry = _Registry(
        targets={
            incompatible: (_target(url=incompatible),),
            valid: (
                _target(
                    provider_id="lever",
                    board="beta",
                    posting="posting-1",
                    url=valid,
                ),
            ),
        },
        capabilities={
            "greenhouse": _capabilities(
                native_get_supported=False,
                board_scan_get_supported=False,
            ),
            "lever": _capabilities(),
        },
        probes={
            "alpha": (
                _Probe("greenhouse", incompatible),
                _Probe("lever", failed),
            ),
            "beta": (_Probe("lever", valid),),
        },
    )
    fetcher = _Fetcher(
        {
            careers: PullFetchedPage(
                body="<title>Beta Careers</title>",
                url=careers,
            ),
            incompatible: PullFetchedPage(body="{}", url=incompatible),
            valid: PullFetchedPage(body="{}", url=valid),
        }
    )
    resolver = PullResolver(registry, fetch_page=fetcher)

    resolution = await _resolve(resolver, careers, operation=PullOperation.GET)

    assert resolution.target.url == valid
    assert incompatible not in fetcher.calls
    assert failed in fetcher.calls
    assert valid in fetcher.calls
