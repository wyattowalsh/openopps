import json
from pathlib import Path

from typer.testing import CliRunner

from openopps.cli import app
from openopps.coverage import (
    AUDIT_PROVIDER_TARGETS,
    build_coverage_report,
    build_provider_audit_report,
    build_source_yield_report,
)
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

from _fixtures.store import seeded_coverage_store as seeded_store


runner = CliRunner()


def test_coverage_report_counts_persisted_records_and_routes(tmp_path: Path):
    _settings, store = seeded_store(tmp_path)

    data = build_coverage_report(store).as_dict()

    assert data["sources"]["total"] == 2
    assert data["boards"]["total"] == 3
    assert data["boards"]["withProviderHints"] == 3
    assert data["boards"]["withJobCapableProviderHints"] == 3
    assert data["boards"]["withBaselineJobCapableProviderHints"] == 3
    assert data["boards"]["withAdoptedV01ProviderHints"] == 3
    assert data["boards"]["withDetectOnlyProviderHints"] == 1
    assert data["boards"]["withUnsupportedOrUnknownProviderHints"] == 0
    assert data["boards"]["withNonSupportedProviderHints"] == 1
    assert data["boards"]["withOnlyNonSupportedProviderHints"] == 0
    assert data["boards"]["nonSupportedProviderCoverage"] == {
        "present": 1,
        "missing": 2,
        "total": 3,
        "percentage": 33.33,
    }
    assert data["routes"]["total"] == 5
    assert data["routes"]["byProvider"] == {
        "greenhouse": 2,
        "lever": 2,
        "teamtailor": 1,
    }
    assert data["routes"]["bySupportLevel"] == {"detect": 1, "jobs": 4}
    assert data["routes"]["nonSupportedTotal"] == 1
    assert data["routes"]["nonSupportedByProvider"] == {"teamtailor": 1}
    assert data["routes"]["byLastStatus"] == {"route_ready": 1, "unknown": 4}
    assert data["routes"]["executable"] == 2
    assert data["routes"]["missingRouteMetadata"] == 1
    assert data["routes"]["duplicateRoutesSkipped"] == 1
    assert data["jobs"]["total"] == 2
    assert data["jobs"]["byProvider"] == {"greenhouse": 2}
    assert data["jobs"]["bySource"] == {"a16z": 2}
    assert data["jobs"]["byBoard"] == {"beta": 2}
    assert data["sources"]["yield"] == {
        "companyCandidates": 4,
        "canonicalBoards": 3,
        "providerHints": 5,
        "jobCapableRoutes": 4,
        "routeReady": 3,
        "activeJobRoutes": 1,
        "duplicateBoardRate": 0.25,
        "uniqueActiveBoardsAdded": 1,
        "yieldScore": 0.25,
        "byProviderType": {"unknown": 2},
        "byAccessType": {"unknown": 2},
    }


def test_coverage_report_detect_only_and_gap_summaries(tmp_path: Path):
    _settings, store = seeded_store(tmp_path)

    data = build_coverage_report(store).as_dict()

    assert data["gaps"]["detectOnlyProviders"] == [
        {
            "provider": "teamtailor",
            "supportLevel": "detect",
            "count": 1,
            "examples": ["gamma"],
        }
    ]
    assert data["gaps"]["nonSupportedProviders"] == [
        {
            "provider": "teamtailor",
            "supportLevel": "detect",
            "routes": 1,
            "boards": 1,
            "examples": ["gamma"],
        }
    ]
    assert data["gaps"]["boardsWithOnlyNonSupportedProviderHints"] == []
    assert data["gaps"]["boardsWithJobCapableProviderHintsButNoExecutableRoute"] == [
        {"board": "gamma", "source": "a16z", "providers": ["greenhouse"]}
    ]
    assert data["gaps"]["boardsWithExecutableRouteButZeroJobs"] == [
        {
            "board": "acme",
            "source": "a16z",
            "provider": "lever",
            "route": "acme",
            "verified": False,
        }
    ]


def test_coverage_report_enrichment_completeness_metrics(tmp_path: Path):
    _settings, store = seeded_store(tmp_path)

    data_quality = build_coverage_report(store).as_dict()["dataQuality"]

    assert data_quality["totalJobs"] == 2
    assert data_quality["missing"] == {
        "postingUrl": 1,
        "applyUrl": 2,
        "locations": 1,
        "department": 1,
        "description": 1,
        "compensationSalary": 1,
        "remote": 1,
        "employmentType": 1,
    }
    assert data_quality["completeness"]["postingUrl"] == {
        "present": 1,
        "missing": 1,
        "total": 2,
        "percentage": 50.0,
    }
    assert data_quality["completeness"]["applyUrl"]["percentage"] == 0.0


def test_providers_coverage_json_cli_output(tmp_path: Path):
    _settings, _store = seeded_store(tmp_path)
    result = runner.invoke(
        app,
        ["providers", "coverage", "--source", "a16z", "--provider", "any", "--json"],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["filters"] == {"source": "a16z", "provider": None}
    assert data["sources"]["total"] == 1
    assert data["boards"]["total"] == 3
    assert data["boards"]["withNonSupportedProviderHints"] == 1
    assert data["boards"]["withOnlyNonSupportedProviderHints"] == 0
    assert data["boards"]["withDetectOnlyProviderHints"] == 1
    assert data["boards"]["withUnsupportedOrUnknownProviderHints"] == 0
    assert data["boards"]["nonSupportedProviderCoverage"] == {
        "present": 1,
        "missing": 2,
        "total": 3,
        "percentage": 33.33,
    }
    assert data["routes"]["total"] == 4
    assert data["routes"]["nonSupportedByProvider"] == {"teamtailor": 1}
    assert data["routes"]["duplicateRoutesSkipped"] == 0
    assert data["jobs"]["total"] == 2


def test_providers_coverage_table_exits_successfully(tmp_path: Path):
    _settings, _store = seeded_store(tmp_path)
    result = runner.invoke(
        app,
        ["providers", "coverage", "--source", "a16z", "--provider", "greenhouse"],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )

    assert result.exit_code == 0
    assert "Provider Coverage Summary" in result.output
    assert "Data Quality Missing Fields" in result.output


def test_coverage_report_counts_only_non_supported_boards_once(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="unsupported-only",
                source_key="a16z",
                remote_id="unsupported-only",
                name="Unsupported Only",
            ),
            BoardRecord(
                key="no-hints",
                source_key="a16z",
                remote_id="no-hints",
                name="No Hints",
            ),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:unsupported-only:teamtailor",
                source_key="a16z",
                board_key="unsupported-only",
                provider_id="teamtailor",
                support_level=ProviderSupport.DETECT,
            ),
            BoardProviderRecord(
                id="a16z:unsupported-only:unknown",
                source_key="a16z",
                board_key="unsupported-only",
                provider_id="unknownats",
                support_level=ProviderSupport.UNSUPPORTED,
            ),
        ]
    )

    data = build_coverage_report(store).as_dict()

    assert data["boards"]["total"] == 2
    assert data["boards"]["withNonSupportedProviderHints"] == 1
    assert data["boards"]["withOnlyNonSupportedProviderHints"] == 1
    assert data["boards"]["withDetectOnlyProviderHints"] == 1
    assert data["boards"]["withUnsupportedOrUnknownProviderHints"] == 1
    assert data["boards"]["nonSupportedProviderCoverage"] == {
        "present": 1,
        "missing": 1,
        "total": 2,
        "percentage": 50.0,
    }
    assert data["routes"]["nonSupportedTotal"] == 2
    assert data["routes"]["nonSupportedByProvider"] == {
        "teamtailor": 1,
        "unknownats": 1,
    }
    assert data["gaps"]["boardsWithOnlyNonSupportedProviderHints"] == [
        {
            "board": "unsupported-only",
            "source": "a16z",
            "providers": ["teamtailor", "unknownats"],
        }
    ]


def test_provider_audit_reports_candidate_provider_deltas(tmp_path: Path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    store = OpenOppsStore(settings)
    store.upsert_source(
        SourceRecord(key="a16z", url="https://jobs.a16z.com", provider_id="consider")
    )
    store.upsert_boards(
        [
            BoardRecord(key="acme", source_key="a16z", remote_id="acme", name="Acme"),
            BoardRecord(key="beta", source_key="a16z", remote_id="beta", name="Beta"),
        ]
    )
    store.upsert_board_providers(
        [
            BoardProviderRecord(
                id="a16z:acme:smartrecruiters",
                source_key="a16z",
                board_key="acme",
                provider_id="smartrecruiters",
                support_level=ProviderSupport.UNSUPPORTED,
            )
        ]
    )

    data = build_provider_audit_report(store).as_dict()
    smartrecruiters = next(
        item for item in data["candidates"] if item["provider"] == "smartrecruiters"
    )

    assert data["snapshot"]["denominator"] == 2
    assert data["snapshot"]["hasPersistedBoards"] is True
    assert data["snapshot"]["representative"] is False
    assert data["snapshot"]["snapshotKind"] == "persisted-scope"
    assert smartrecruiters["boards"] == 1
    assert smartrecruiters["observedSupportLevels"] == ["unsupported"]
    assert smartrecruiters["observedUnsupportedBoards"] == 1
    assert smartrecruiters["coverage"]["percentage"] == 50.0
    assert smartrecruiters["adoptedForV01"] is False
    assert "smartrecruiters" in data["doNotAdoptRationales"]


def test_source_yield_report_counts_source_family_metrics(tmp_path: Path):
    _settings, store = seeded_store(tmp_path)

    data = build_source_yield_report(store, source_key="a16z").as_dict()

    assert data["snapshot"]["scope"] == {"source": "a16z"}
    assert data["snapshot"]["sourceCount"] == 1
    assert data["totals"] == {
        "companyCandidates": 3,
        "canonicalBoards": 3,
        "providerHints": 4,
        "jobCapableRoutes": 3,
        "routeReady": 2,
        "activeJobRoutes": 1,
        "duplicateBoardRate": 0.0,
        "uniqueActiveBoardsAdded": 1,
        "yieldScore": 0.3333,
        "byProviderType": {"unknown": 1},
        "byAccessType": {"unknown": 1},
    }
    assert data["sources"] == [
        {
            "source": "a16z",
            "providerId": "consider",
            "taxonomy": {},
            "companyCandidates": 3,
            "canonicalBoards": 3,
            "providerHints": 4,
            "jobCapableRoutes": 3,
            "routeReady": 2,
            "activeJobRoutes": 1,
            "duplicateBoardRate": 0.0,
            "uniqueActiveBoardsAdded": 1,
            "yieldScore": 0.3333,
        }
    ]


def test_admin_sources_yield_json_cli_output(tmp_path: Path):
    _settings, _store = seeded_store(tmp_path)
    result = runner.invoke(
        app,
        ["admin", "sources", "yield", "--source", "a16z", "--json"],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["snapshot"]["scope"] == {"source": "a16z"}
    assert data["totals"]["companyCandidates"] == 3
    assert data["sources"][0]["source"] == "a16z"


def test_providers_audit_json_cli_output(tmp_path: Path):
    _settings, _store = seeded_store(tmp_path)
    result = runner.invoke(
        app,
        ["providers", "audit", "--source", "a16z", "--json"],
        env={"OPENOPPS_DB_URL": f"sqlite:///{tmp_path / 'openopps.db'}"},
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["snapshot"]["denominator"] == 3
    providers = [item["provider"] for item in data["candidates"]]
    assert len(providers) == len(AUDIT_PROVIDER_TARGETS)
    assert set(providers) == set(AUDIT_PROVIDER_TARGETS)
