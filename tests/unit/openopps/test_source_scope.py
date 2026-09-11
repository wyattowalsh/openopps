from __future__ import annotations

import json
from pathlib import Path

import pytest

from openopps.models import BoardProviderRecord, ProviderSupport
from openopps.providers.registry import provider_registry
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.source_scope import (
    JOB_SEEKER_OVERLAY_SOURCE_KEY,
    OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS,
    PREFERRED_STARTUP_BOARD_ADAPTER_ID,
    PREFERRED_STARTUP_BOARD_SOURCE_KEY,
    UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES,
    audit_editorial_provider_hints,
    validate_packaged_source_catalog,
)
from openopps.coverage import build_coverage_report
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

from _fixtures.store import seeded_coverage_store as seeded_store


def test_packaged_source_catalog_excludes_workatastartup_and_prefers_yc() -> None:
    validate_packaged_source_catalog(BOARD_SOURCE_CATALOG)
    assert OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS.isdisjoint(BOARD_SOURCE_CATALOG)
    assert "workatastartup" not in BOARD_SOURCE_CATALOG
    assert "work-at-a-startup" not in BOARD_SOURCE_CATALOG
    assert "work_at_a_startup" not in BOARD_SOURCE_CATALOG
    yc = BOARD_SOURCE_CATALOG[PREFERRED_STARTUP_BOARD_SOURCE_KEY]
    assert yc.provider_id == PREFERRED_STARTUP_BOARD_ADAPTER_ID
    assert yc.url == "https://www.ycombinator.com/companies"


def test_validate_packaged_source_catalog_rejects_workatastartup() -> None:
    catalog = {
        PREFERRED_STARTUP_BOARD_SOURCE_KEY: object(),
        "workatastartup": object(),
    }
    with pytest.raises(ValueError, match="workatastartup"):
        validate_packaged_source_catalog(catalog)


def test_wellfound_angel_linkedin_are_unsupported() -> None:
    assert "wellfound" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "angel" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "linkedin" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "linkedin.com" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    linkedin = UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["linkedin"]
    assert "linkedin.com" in linkedin.casefold()
    assert "career" in linkedin.casefold()
    assert linkedin == UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["linkedin.com"]
    assert "wellfound" not in BOARD_SOURCE_CATALOG
    assert "angel" not in BOARD_SOURCE_CATALOG
    assert "linkedin" not in BOARD_SOURCE_CATALOG
    assert "linkedin.com" not in BOARD_SOURCE_CATALOG


def test_indeed_glassdoor_are_unsupported_like_linkedin_wellfound(
    tmp_path: Path,
) -> None:
    assert "indeed" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "indeed.com" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "glassdoor" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    assert "glassdoor.com" in UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES
    indeed = UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["indeed"]
    glassdoor = UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["glassdoor"]
    indeed_folded = indeed.casefold()
    glassdoor_folded = glassdoor.casefold()
    assert "indeed.com" in indeed_folded
    assert "glassdoor.com" in glassdoor_folded
    assert "unsupported" in indeed_folded
    assert "unsupported" in glassdoor_folded
    assert "career" in indeed_folded or "job" in indeed_folded
    assert "career" in glassdoor_folded or "job" in glassdoor_folded
    assert indeed == UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["indeed.com"]
    assert glassdoor == UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["glassdoor.com"]
    for folded in (indeed_folded, glassdoor_folded):
        assert "session" in folded or "anti-bot" in folded
        assert "adapter" in folded
        assert "package" in folded
        assert "stable static no-auth" in folded
    assert "indeed" not in BOARD_SOURCE_CATALOG
    assert "indeed.com" not in BOARD_SOURCE_CATALOG
    assert "glassdoor" not in BOARD_SOURCE_CATALOG
    assert "glassdoor.com" not in BOARD_SOURCE_CATALOG
    registry = provider_registry(settings=OpenOppsSettings())
    jobs_provider_ids = {
        definition.id for definition in registry.list_board_providers()
    }
    for key in ("indeed", "indeed.com", "glassdoor", "glassdoor.com"):
        assert key not in jobs_provider_ids
        assert registry.get(key) is None
    _settings, store = seeded_store(tmp_path)
    unsupported = build_coverage_report(store).as_dict()["gaps"]["sourceScope"][
        "unsupportedSourceDiscovery"
    ]
    assert "indeed" in unsupported
    assert "indeed.com" in unsupported
    assert "glassdoor" in unsupported
    assert "glassdoor.com" in unsupported


def test_job_seeker_overlay_source_key_is_allowed() -> None:
    from openopps.providers.sources.overlay import (
        JOB_SEEKER_OVERLAY_SOURCE_KEY as OVERLAY_OWNED_KEY,
    )

    assert JOB_SEEKER_OVERLAY_SOURCE_KEY is OVERLAY_OWNED_KEY
    assert JOB_SEEKER_OVERLAY_SOURCE_KEY == "job-seeker-overlay"
    assert JOB_SEEKER_OVERLAY_SOURCE_KEY not in OUT_OF_SCOPE_PACKAGED_SOURCE_KEYS
    catalog = {
        PREFERRED_STARTUP_BOARD_SOURCE_KEY: object(),
        JOB_SEEKER_OVERLAY_SOURCE_KEY: object(),
    }
    validate_packaged_source_catalog(catalog)


def test_registry_has_no_editorial_job_provider() -> None:
    registry = provider_registry(settings=OpenOppsSettings())
    assert registry.get("editorial") is None
    assert registry.get("editiorial") is None


def test_coverage_report_includes_source_scope_rationales(tmp_path: Path) -> None:
    _settings, store = seeded_store(tmp_path)
    gaps = build_coverage_report(store).as_dict()["gaps"]
    source_scope = gaps["sourceScope"]
    assert source_scope["preferredStartupBoardSource"] == "yc"
    assert "workatastartup" in source_scope["excludedPackagedSources"]
    assert "wellfound" in source_scope["unsupportedSourceDiscovery"]
    assert "angel" in source_scope["unsupportedSourceDiscovery"]
    assert "linkedin" in source_scope["unsupportedSourceDiscovery"]
    assert "linkedin.com" in source_scope["unsupportedSourceDiscovery"]
    assert source_scope["editorialLabelAudit"]["registerProviderIdentity"] is False


def test_committed_providers_snapshot_editorial_hints_are_metadata_only() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    providers_path = repo_root / "web" / "public" / "data" / "openopps-search" / "providers.json"
    if not providers_path.is_file():
        return
    chunk = json.loads(providers_path.read_text())
    columns = chunk["columns"]
    label_index = columns.index("label")
    provider_id_index = columns.index("providerId")
    audit = audit_editorial_provider_hints(
        provider_rows=chunk["rows"],
        label_index=label_index,
        provider_id_index=provider_id_index,
    )
    assert audit["registerProviderIdentity"] is False
    if audit["labelsObserved"]:
        assert set(audit["labelsObserved"]).issubset({"Editorial", "Editiorial"})


def test_editorial_hints_from_routes_stay_detect_only(tmp_path: Path) -> None:
    from openopps.models import BoardRecord, SourceRecord

    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="acme",
                source_key="a16z",
                remote_id="acme",
                name="Acme",
                domain="acme.com",
            )
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:editorial",
                source_key="a16z",
                board_key="acme",
                provider_id="editorial",
                label="Editorial",
                support_level=ProviderSupport.DETECT,
            )
        ]
    )
    registry = provider_registry(settings=settings)
    assert registry.source_hint_support_level("editorial") == ProviderSupport.DETECT
    audit = audit_editorial_provider_hints(routes=store.list_board_providers())
    assert audit["boardCount"] == 1
    assert "Editorial" in audit["labelsObserved"]
    assert UNSUPPORTED_SOURCE_DISCOVERY_RATIONALES["wellfound"]
