"""Guards for expand-job-seeker-coverage: discovery isolation, ATS policy, scope."""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from click import unstyle
from typer.testing import CliRunner

from openopps.cli import (
    DISCOVERY_PREVIEW_HELP,
    DISCOVERY_SCOUT_HELP,
    DISCOVERY_VERIFY_HELP,
    app,
)
from openopps.discovery.targeted_ats import classify_public_route
from openopps.providers.boards import BOARD_JOB_PROVIDERS
from openopps.providers.registry import provider_registry
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.source_scope import (
    OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS,
    UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES,
    validate_packaged_source_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
OVERLAY_MODULE_PATHS = (
    REPO_ROOT / "src" / "openopps" / "providers" / "sources" / "overlay.py",
    REPO_ROOT / "src" / "openopps" / "providers" / "sources" / "overlay_targets.py",
    REPO_ROOT / "src" / "openopps" / "providers" / "sources" / "overlay_outcomes.py",
)
FORBIDDEN_IMPORT_PREFIXES = ("openopps.cli", "wrangler", "kaggle", "kagglehub")
FORBIDDEN_JOB_SEEKER_HOSTS = frozenset(
    {
        "wellfound.com",
        "angel.co",
        "angellist.com",
        "linkedin.com",
        "workatastartup.com",
    }
)
KNOWN_PUBLIC_ATS_HOST_SUFFIXES = frozenset(
    {
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "myworkdayjobs.com",
        "bamboohr.com",
        "teamtailor.com",
        "apply.workable.com",
        "ats.rippling.com",
        "consider.com",
    }
)
DENIED_STARTUP_SOURCE_KEYS = frozenset(
    {
        "wellfound",
        "angel",
        "linkedin",
        "workatastartup",
        "work-at-a-startup",
        "work_at_a_startup",
    }
)
HTML_SCRAPER_PROVIDER_IDS = frozenset(
    {
        "html",
        "html-careers",
        "careers",
        "career-site",
        "public_page",
        "wellfound",
        "angel",
        "angellist",
        "linkedin",
        "workatastartup",
        "work-at-a-startup",
        "work_at_a_startup",
    }
)
HELP_WIDTH = 120
runner = CliRunner()


def _plain(text: str) -> str:
    return unstyle(text)


def _help(*args: str) -> str:
    result = runner.invoke(app, list(args), terminal_width=HELP_WIDTH)
    assert result.exit_code == 0, result.output
    return _plain(result.output)


def _locator_host(locator: str) -> str:
    return (urlsplit(locator).hostname or "").casefold().removeprefix("www.")


def _host_matches(host: str, suffixes: frozenset[str]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def ats_policy_job_provider_id(
    locator: str,
    *,
    existing_ids: frozenset[str],
    detected_id: str | None,
) -> str | None:
    """Reuse a jobs-capable id already in BOARD_JOB_PROVIDERS, or return None.

    One-off HTML careers, bare company domains, and Wellfound/Angel/LinkedIn/
    WorkAtAStartup locators never mint a new provider id. A detected id that is
    not already registered is treated as a refused new BOARD_JOB_PROVIDERS row.
    A bare company host never invents an ATS token or provider.
    """

    host = _locator_host(locator)
    if not host or _host_matches(host, FORBIDDEN_JOB_SEEKER_HOSTS):
        return None
    if not _host_matches(host, KNOWN_PUBLIC_ATS_HOST_SUFFIXES):
        return None
    if not detected_id or detected_id not in existing_ids:
        return None
    return detected_id


def _imported_modules(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(
                f"{node.module}.{alias.name}" for alias in node.names
            )
    return imported


def test_discovery_help_constants_forbid_catalog_candidates_and_same_run_sync() -> (
    None
):
    scout = DISCOVERY_SCOUT_HELP.casefold()
    verify = DISCOVERY_VERIFY_HELP.casefold()
    preview = DISCOVERY_PREVIEW_HELP.casefold()
    assert "does not mutate sqlite, catalogs, git, or kaggle" in scout
    assert "not same-run with ingest or promotion" in scout
    assert "has no apply option" in scout
    assert "activating candidates" in verify
    assert "same invocation" in verify
    assert "without rewriting" in verify
    assert "without applying" in preview
    assert "has no apply option" in preview
    assert "does not mutate" in preview
    assert "kaggle" in preview


def test_discovery_cli_help_never_adds_catalog_candidates_or_shares_sync_run() -> (
    None
):
    output = _help("discovery", "--help")
    folded = " ".join(output.casefold().split())
    assert "scout" in folded
    assert "verify-scout" in folded
    assert "preview-promotion" in folded
    assert "never add candidates to the catalog" in folded
    assert "source sync in the same invocation" in folded
    assert "not same-run with ingest" in folded
    assert "does not promote, sync, or activate candidates" in folded
    assert "--apply" not in output


@pytest.mark.parametrize(
    ("args", "help_text"),
    (
        (("discovery", "scout", "--help"), DISCOVERY_SCOUT_HELP),
        (("discovery", "verify-scout", "--help"), DISCOVERY_VERIFY_HELP),
        (("discovery", "preview-promotion", "--help"), DISCOVERY_PREVIEW_HELP),
        (("admin", "sources", "scout", "--help"), DISCOVERY_SCOUT_HELP),
        (("admin", "sources", "verify-scout", "--help"), DISCOVERY_VERIFY_HELP),
        (
            ("admin", "sources", "preview-promotion", "--help"),
            DISCOVERY_PREVIEW_HELP,
        ),
    ),
)
def test_scout_verify_preview_help_uses_discovery_help_constants(
    args: tuple[str, ...],
    help_text: str,
) -> None:
    output = _help(*args)
    folded = " ".join(output.casefold().split())
    command = args[-2]
    assert "--apply" not in output
    if command == "scout":
        assert "does not mutate sqlite, catalogs" in folded
        assert "not same-run with ingest or promotion" in folded
        assert "has no apply option" in folded
    elif command == "verify-scout":
        assert "without rewriting it or activating candidates" in folded
        assert "same invocation" in folded
    else:
        assert command == "preview-promotion"
        assert "without applying" in folded
        assert "has no apply option" in folded
        assert "does not mutate" in folded
    assert help_text.split(".")[0].casefold() in folded


def test_overlay_modules_do_not_import_sync_or_live_upload() -> None:
    for path in OVERLAY_MODULE_PATHS:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _imported_modules(tree)
        forbidden = {
            item
            for item in imported
            if any(
                item == prefix or item.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            )
        }
        assert not forbidden, (path.name, forbidden)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "sync" not in imported_names
        assert "wrangler" not in imported_names
        assert "upload" not in imported_names


def test_source_scope_excludes_denied_startup_boards() -> None:
    validate_packaged_source_catalog(BOARD_SOURCE_CATALOG)
    assert OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS.isdisjoint(BOARD_SOURCE_CATALOG)
    assert DENIED_STARTUP_SOURCE_KEYS.isdisjoint(BOARD_SOURCE_CATALOG)
    assert "workatastartup" in OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS
    assert "wellfound" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "angel" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES


@pytest.mark.parametrize(
    "locator",
    (
        "https://www.janestreet.com/careers/",
        "https://www.valvesoftware.com/en/jobs",
        "https://www.bloomberg.com/company/careers/",
        "https://stripe.com",
        "https://careers.acme.example.test/jobs",
    ),
)
def test_one_off_html_careers_do_not_register_a_new_board_job_provider(
    locator: str,
) -> None:
    existing = frozenset(BOARD_JOB_PROVIDERS)
    detected = provider_registry().detect_url(locator)
    detected_id = None if detected is None else detected.provider_id
    assert detected is None
    assert classify_public_route(locator) is None
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=existing,
            detected_id=detected_id,
        )
        is None
    )
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=existing,
            detected_id="html-careers",
        )
        is None
    )
    assert HTML_SCRAPER_PROVIDER_IDS.isdisjoint(existing)
    assert existing == frozenset(BOARD_JOB_PROVIDERS)


@pytest.mark.parametrize(
    "locator",
    (
        "https://wellfound.com/company/acme/jobs",
        "https://angel.co/company/acme/jobs",
        "https://www.linkedin.com/company/acme/jobs",
        "https://www.workatastartup.com/companies/acme",
    ),
)
def test_ats_policy_rejects_forbidden_hosts_even_if_detected(
    locator: str,
) -> None:
    existing = frozenset(BOARD_JOB_PROVIDERS)
    host = _locator_host(locator)
    claimed = host.split(".")[0]
    assert _host_matches(host, FORBIDDEN_JOB_SEEKER_HOSTS)
    assert provider_registry().detect_url(locator) is None
    assert classify_public_route(locator) is None
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=existing,
            detected_id=claimed,
        )
        is None
    )


def test_ats_policy_reuses_existing_public_ats_provider() -> None:
    locator = "https://boards.greenhouse.io/stripe"
    existing = frozenset(BOARD_JOB_PROVIDERS)
    detected = provider_registry().detect_url(locator)
    assert detected is not None
    assert detected.provider_id == "greenhouse"
    assert detected.token == "stripe"
    hint = classify_public_route(locator)
    assert hint is not None
    assert hint.provider_id == "greenhouse"
    assert hint.token == "stripe"
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=existing,
            detected_id=detected.provider_id,
        )
        == "greenhouse"
    )
    assert "greenhouse" in existing
    assert "html-careers" not in existing


def test_bare_company_domain_does_not_invent_an_ats_token() -> None:
    locator = "https://openai.com"
    detected = provider_registry().detect_url(locator)
    assert detected is None
    assert classify_public_route(locator) is None
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=frozenset(BOARD_JOB_PROVIDERS),
            detected_id=None,
        )
        is None
    )
    assert (
        ats_policy_job_provider_id(
            locator,
            existing_ids=frozenset(BOARD_JOB_PROVIDERS),
            detected_id="greenhouse",
        )
        is None
    )
