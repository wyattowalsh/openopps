from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import openopps.cli as cli_module
from openopps.models import ProviderSupport
from openopps.pull_models import (
    DiscoveryMethod,
    PullDomainError,
    PullErrorCode,
    PullOperation,
    PullProvenance,
)
from openopps.pull_resolver import PullResolution
from openopps.providers.base import (
    ProviderDefinition,
    ProviderKind,
    ProviderRouteMatch,
)
from openopps.providers.pull import (
    InterfaceStability,
    ProviderPullCapabilities,
    ProviderRouteIdentity,
    ProviderTargetKind,
    ProviderUrlTarget,
)
from openopps.providers.registry import ProviderRegistry


runner = CliRunner()
BOARD_URL = "https://boards.example.test/acme"
POSTING_URL = "https://boards.example.test/acme/jobs/101"


def _invoke(tmp_path: Path, *args: str):
    return runner.invoke(
        cli_module.app,
        list(args),
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )


def _capabilities(
    *,
    native_get: bool = True,
    board_scan: bool = False,
) -> ProviderPullCapabilities:
    return ProviderPullCapabilities(
        list_supported=True,
        native_get_supported=native_get,
        board_scan_get_supported=board_scan,
        exact_unlisted_get_supported=native_get,
        interface_stability=InterfaceStability.DOCUMENTED,
    )


def _target(*, posting: bool = True) -> ProviderUrlTarget:
    return ProviderUrlTarget(
        provider_id="typed",
        target_kind=(
            ProviderTargetKind.POSTING if posting else ProviderTargetKind.BOARD
        ),
        url=POSTING_URL if posting else BOARD_URL,
        board_identity="acme",
        posting_identity="101" if posting else None,
        route=ProviderRouteIdentity(token="acme"),
    )


def _typed_definition() -> ProviderDefinition:
    return ProviderDefinition(
        id="typed",
        label="Typed provider",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.JOBS,
        description="Typed pull provider.",
        target_parser=lambda url: _target(posting="/jobs/" in url),
        pull_capabilities=_capabilities(),
    )


def _legacy_definition(provider_id: str) -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        label=f"{provider_id.title()} provider",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.DETECT,
        description="Legacy route detector.",
        route_detector=lambda _url: ProviderRouteMatch(token=f"{provider_id}-token"),
    )


class _AsyncClientContext:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def __aenter__(self) -> object:
        client = object()
        self.calls.append(client)
        return client

    async def __aexit__(self, *args: object) -> None:
        return None


class _Resolver:
    def __init__(
        self,
        resolution: PullResolution | None = None,
        error: PullDomainError | None = None,
    ) -> None:
        self.resolution = resolution
        self.error = error
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    async def resolve(
        self,
        client: object,
        url: str,
        **kwargs: object,
    ) -> PullResolution:
        self.calls.append((client, url, kwargs))
        if self.error is not None:
            raise self.error
        assert self.resolution is not None
        return self.resolution


def _install_inspect_seams(
    monkeypatch: pytest.MonkeyPatch,
    registry: ProviderRegistry,
    resolver: _Resolver,
) -> list[object]:
    clients: list[object] = []
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)
    monkeypatch.setattr(
        cli_module.PullResolver,
        "from_settings",
        staticmethod(
            lambda received, _settings: resolver if received is registry else None
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "build_async_client",
        lambda _settings: _AsyncClientContext(clients),
    )
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(
            lambda _settings: pytest.fail("inspect must not build PullService")
        ),
    )
    return clients


def test_providers_detect_prefers_typed_target_and_reports_origin_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)
    monkeypatch.setattr(
        cli_module,
        "build_async_client",
        lambda _settings: pytest.fail("detect must not open an HTTP client"),
    )

    result = _invoke(tmp_path, "providers", "detect", POSTING_URL, "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["recognized"] is True
    assert payload["ambiguous"] is False
    assert payload["detection"] == "typed"
    assert payload["providerId"] == "typed"
    assert payload["targetKind"] == "posting"
    assert payload["boardIdentity"] == "acme"
    assert payload["postingIdentity"] == "101"
    assert payload["targetPullCapable"] is True
    assert payload["origin"] == "builtin"
    assert payload["builtin"] is True
    assert payload["plugin"] is False


def test_providers_detect_uses_legacy_detect_only_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy = ProviderDefinition(
        id="legacy",
        label="Legacy provider",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.DETECT,
        description="Legacy route detector.",
        route_detector=lambda _url: ProviderRouteMatch(token="acme"),
    )
    registry = ProviderRegistry([legacy])
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = _invoke(tmp_path, "providers", "detect", BOARD_URL, "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["recognized"] is True
    assert payload["detection"] == "legacy"
    assert payload["providerId"] == "legacy"
    assert payload["targetKind"] is None
    assert payload["targetPullCapable"] is False
    assert payload["pullStatus"] == "detect_only"
    assert payload["origin"] == "plugin"
    assert payload["builtin"] is False
    assert payload["plugin"] is True
    assert payload["route"] == {"token": "acme"}


def test_providers_detect_reports_every_legacy_match_without_url_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry(
        [_legacy_definition("zeta"), _legacy_definition("alpha")]
    )
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)
    secret_url = f"{BOARD_URL}?token=super-secret#private"

    result = _invoke(tmp_path, "providers", "detect", secret_url, "--json")

    assert result.exit_code == 0, result.output
    assert "super-secret" not in result.output
    assert "private" not in result.output
    payload = json.loads(result.output)
    assert payload["recognized"] is True
    assert payload["ambiguous"] is True
    assert [target["providerId"] for target in payload["targets"]] == [
        "alpha",
        "zeta",
    ]
    assert {target["url"] for target in payload["targets"]} == {BOARD_URL}
    assert [target["route"] for target in payload["targets"]] == [
        {"token": "alpha-token"},
        {"token": "zeta-token"},
    ]


def test_providers_detect_reports_unrecognized_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([])
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = _invoke(
        tmp_path,
        "providers",
        "detect",
        "https://careers.example.test/jobs?token=super-secret#private",
        "--json",
    )

    assert result.exit_code == 0, result.output
    assert "super-secret" not in result.output
    assert "private" not in result.output
    assert json.loads(result.output) == {
        "recognized": False,
        "ambiguous": False,
        "url": "https://careers.example.test/jobs",
    }


def test_provider_json_remains_plain_when_rich_console_is_forced_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)
    rich_output = StringIO()
    monkeypatch.setattr(
        cli_module,
        "console",
        Console(file=rich_output, force_terminal=True),
    )

    result = _invoke(tmp_path, "providers", "detect", POSTING_URL, "--json")

    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.stdout
    assert json.loads(result.stdout)["providerId"] == "typed"
    assert rich_output.getvalue() == ""


def test_providers_detect_human_output_includes_parsed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = runner.invoke(
        cli_module.app,
        ["providers", "detect", POSTING_URL],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    for evidence in (
        "provider",
        "detection",
        "posting",
        "route token",
        "101",
        "acme",
    ):
        assert evidence in result.output


def test_providers_capabilities_reports_exact_builtin_plugin_and_support_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    builtin = _typed_definition()
    plugin = ProviderDefinition(
        id="plugin_jobs",
        label="Plugin jobs",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.JOBS,
        description="Plugin URL pull.",
        target_parser=lambda _url: ProviderUrlTarget(
            provider_id="plugin_jobs",
            target_kind=ProviderTargetKind.BOARD,
            url="https://plugin.example.test/board",
            board_identity="board",
        ),
        pull_capabilities=_capabilities(native_get=False, board_scan=True),
    )
    detect_only = ProviderDefinition(
        id="route_only",
        label="Route only",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.DETECT,
        description="Detect only.",
        route_detector=lambda _url: ProviderRouteMatch(site="site"),
    )
    unsupported = ProviderDefinition(
        id="unsupported",
        label="Unsupported",
        kind=ProviderKind.BOARD_PROVIDER,
        support_level=ProviderSupport.UNSUPPORTED,
        description="Unsupported.",
    )
    registry = ProviderRegistry(
        [builtin, plugin, detect_only, unsupported],
        builtin_ids={"typed", "route_only", "unsupported"},
    )
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = _invoke(tmp_path, "providers", "capabilities", "--json")

    assert result.exit_code == 0, result.output
    payload = {item["providerId"]: item for item in json.loads(result.output)}
    assert payload["typed"] == {
        "providerId": "typed",
        "label": "Typed provider",
        "supportLevel": "jobs",
        "origin": "builtin",
        "builtin": True,
        "plugin": False,
        "pullStatus": "pull",
        "pullCapable": True,
        "detectSupported": True,
        "listSupported": True,
        "nativeGetSupported": True,
        "boardScanGetSupported": False,
        "exactUnlistedGetSupported": True,
        "enumerateUnlistedSupported": False,
        "interfaceStability": "documented",
    }
    assert payload["plugin_jobs"]["origin"] == "plugin"
    assert payload["plugin_jobs"]["builtin"] is False
    assert payload["plugin_jobs"]["plugin"] is True
    assert payload["plugin_jobs"]["nativeGetSupported"] is False
    assert payload["plugin_jobs"]["boardScanGetSupported"] is True
    assert payload["route_only"]["pullStatus"] == "detect_only"
    assert payload["route_only"]["pullCapable"] is False
    assert payload["unsupported"]["pullStatus"] == "unsupported"
    assert payload["unsupported"]["detectSupported"] is False


def test_providers_inspect_uses_only_resolver_and_reports_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    target = _target(posting=False)
    resolution = PullResolution(
        target=target,
        provenance=PullProvenance(
            requested_url=BOARD_URL,
            resolved_url=BOARD_URL,
            discovery_method=DiscoveryMethod.NATIVE_URL,
            provider_id="typed",
            requested_operation=PullOperation.LIST,
            resolved_operation=PullOperation.LIST,
            board_identity="acme",
        ),
    )
    resolver = _Resolver(resolution=resolution)
    clients = _install_inspect_seams(monkeypatch, registry, resolver)

    result = _invoke(
        tmp_path,
        "providers",
        "inspect",
        BOARD_URL,
        "--operation",
        "list",
        "--direct",
        "--no-probe",
        "--refresh-cache",
        "--json",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target"]["providerId"] == "typed"
    assert payload["target"]["targetKind"] == "board"
    assert payload["target"]["origin"] == "builtin"
    assert payload["provenance"]["resolved_operation"] == "list"
    assert len(clients) == 1
    assert resolver.calls == [
        (
            clients[0],
            BOARD_URL,
            {
                "operation": PullOperation.LIST,
                "direct": True,
                "probe": False,
            },
        )
    ]


def test_providers_inspect_maps_domain_errors_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    resolver = _Resolver(
        error=PullDomainError(
            PullErrorCode.UNSAFE_URL,
            "Unsafe target.",
            hint="Use a public HTTPS URL.",
        )
    )
    _install_inspect_seams(monkeypatch, registry, resolver)

    result = _invoke(tmp_path, "providers", "inspect", BOARD_URL, "--json")

    assert result.exit_code == 6
    assert result.stdout == ""
    assert "Error [unsafe_url]: Unsafe target." in result.stderr
    assert "Hint: Use a public HTTPS URL." in result.stderr


def test_providers_inspect_human_output_includes_full_resolution_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    resolution = PullResolution(
        target=_target(),
        provenance=PullProvenance(
            requested_url=f"{POSTING_URL}?token=secret#private",
            resolved_url=POSTING_URL,
            discovery_method=DiscoveryMethod.PAGE_LINK,
            provider_id="typed",
            requested_operation=PullOperation.AUTO,
            resolved_operation=PullOperation.GET,
            board_identity="acme",
            posting_identity="101",
            visited_urls=(f"{BOARD_URL}?token=secret",),
            probed_slugs=("acme",),
        ),
    )
    resolver = _Resolver(resolution=resolution)
    _install_inspect_seams(monkeypatch, registry, resolver)

    result = runner.invoke(
        cli_module.app,
        ["providers", "inspect", POSTING_URL],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "secret" not in result.output
    assert "private" not in result.output
    for evidence in (
        "requested URL",
        "resolved URL",
        "discovery method",
        "resolved operation",
        "posting",
        "route",
        "visited URLs",
        "probed slugs",
        "page_link",
        "101",
    ):
        assert evidence in result.output


def test_providers_capabilities_human_output_includes_interface_and_unlisted_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = runner.invoke(
        cli_module.app,
        ["providers", "capabilities"],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    for evidence in (
        "interface stability",
        "documented",
        "exact unlisted get",
        "enumerate unlisted",
    ):
        assert evidence in result.output


def test_provider_human_tables_render_plugin_text_literally(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider_id = "[red]plugin[/red]"
    registry = ProviderRegistry([_legacy_definition(provider_id)])
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = _invoke(tmp_path, "providers", "capabilities")

    assert result.exit_code == 0, result.output
    assert provider_id in result.output


def test_provider_pull_commands_have_semantic_help_and_preserve_existing_surfaces() -> (
    None
):
    public_help = runner.invoke(
        cli_module.app,
        ["providers", "--help"],
        terminal_width=140,
    )
    admin_help = runner.invoke(
        cli_module.app,
        ["admin", "providers", "--help"],
        terminal_width=140,
    )

    assert public_help.exit_code == 0
    for command in ("detect", "inspect", "capabilities", "health", "coverage", "audit"):
        assert command in public_help.output
    assert admin_help.exit_code == 0
    for command in ("list", "detect", "explain", "probe-routes", "registry"):
        assert command in admin_help.output


def test_public_provider_list_remains_unregistered() -> None:
    result = runner.invoke(cli_module.app, ["providers", "list"])

    assert result.exit_code == 2
    assert "No such command 'list'" in result.stderr


def test_providers_detect_rejects_non_https_urls(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "providers", "detect", "http://example.test/jobs")

    assert result.exit_code == 2
    assert "public HTTPS URL" in result.output


def test_providers_detect_human_unrecognized_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_pull_registry",
        lambda _settings: ProviderRegistry([]),
    )

    result = _invoke(tmp_path, "providers", "detect", BOARD_URL)

    assert result.exit_code == 0, result.output
    assert "recognized" in result.output
    assert BOARD_URL in result.output


def test_providers_capabilities_unknown_provider_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_pull_registry",
        lambda _settings: ProviderRegistry([_typed_definition()], builtin_ids={"typed"}),
    )

    result = _invoke(
        tmp_path,
        "providers",
        "capabilities",
        "--provider",
        "missing",
    )

    assert result.exit_code == 2
    assert "Unknown job provider: missing" in result.output


def test_providers_capabilities_can_filter_to_one_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ProviderRegistry([_typed_definition()], builtin_ids={"typed"})
    monkeypatch.setattr(cli_module, "_pull_registry", lambda _settings: registry)

    result = _invoke(
        tmp_path,
        "providers",
        "capabilities",
        "--provider",
        "typed",
        "--json",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["providerId"] == "typed"


def test_jobs_export_writes_empty_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "jobs.jsonl"
    result = _invoke(tmp_path, "jobs", "export", "--output", str(output))

    assert result.exit_code == 0, result.output
    assert "Exported 0 jobs" in result.output
    assert output.exists()


def test_jobs_pull_raw_pretty_is_usage_error_before_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module.PullService,
        "from_settings",
        staticmethod(
            lambda _settings, **_kwargs: pytest.fail("service must not be built")
        ),
    )

    result = _invoke(
        tmp_path,
        "jobs",
        "pull",
        BOARD_URL,
        "--raw",
        "--format",
        "pretty",
    )

    assert result.exit_code == 2
    assert "--raw requires auto, json, or jsonl output" in result.output


def test_write_pull_metrics_file_oserror_is_click_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def boom(_observability: object, _path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli_module, "write_pull_metrics_file", boom)

    with pytest.raises(cli_module.ClickException, match="Unable to write pull metrics"):
        cli_module._write_pull_metrics_file(tmp_path / "metrics.json", None)


def test_write_pull_metrics_file_none_path_is_noop() -> None:
    cli_module._write_pull_metrics_file(None, None)


def test_emit_pull_domain_error_prints_hint_and_optional_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        cli_module.typer,
        "echo",
        lambda message, err=False: messages.append(str(message)),
    )

    with pytest.raises(cli_module.typer.Exit) as quiet:
        cli_module._emit_pull_domain_error(
            PullDomainError(
                PullErrorCode.UNSAFE_URL,
                "Unsafe target.",
                hint="Use a public HTTPS URL.",
            ),
            quiet=True,
            verbosity=2,
        )

    assert quiet.value.exit_code == 6
    assert messages == [
        "Error [unsafe_url]: Unsafe target.",
        "Hint: Use a public HTTPS URL.",
    ]
