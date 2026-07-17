from __future__ import annotations

import json
from pathlib import Path

from openopps.models import BoardProviderRecord, ProviderSupport
from openopps.providers.registry import provider_registry
from openopps.providers.sources import BOARD_SOURCE_CATALOG
from openopps.source_scope import (
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
    yc = BOARD_SOURCE_CATALOG[PREFERRED_STARTUP_BOARD_SOURCE_KEY]
    assert yc.provider_id == PREFERRED_STARTUP_BOARD_ADAPTER_ID
    assert yc.url == "https://www.ycombinator.com/companies"


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