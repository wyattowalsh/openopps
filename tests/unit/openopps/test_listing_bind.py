from __future__ import annotations

import inspect
import sys
from typing import Any

import pytest

from openopps.models import BoardRecord, JobRecord
from openopps.providers.boards.ashby import AshbyProvider
from openopps.providers.boards.bamboohr import BambooHRProvider
from openopps.providers.boards.consider import ConsiderJobsProvider
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.boards.listing import (
    BoardListingKernelResult,
    ListingPosting,
    MembershipEvidence,
    MembershipScope,
    bind_listing_jobs,
    load_optional_pull,
)
from openopps.providers.boards.rippling import RipplingProvider
from openopps.providers.boards.teamtailor import TeamtailorProvider
from openopps.providers.boards.url_targets import (
    URL_PULL_SOURCE_KEY,
    decode_url_identity_segment,
    strict_decoded_path_parts,
    synthetic_url_pull_board,
)
from openopps.providers.boards.workable import WorkableProvider
from openopps.providers.boards.workday import WorkdayProvider
from openopps.providers.boards.wpjobmanager import WPJobManagerProvider
from openopps.utils import stable_id


def _posting(*, remote_id: str, board_key: str, provider_id: str) -> ListingPosting:
    job = JobRecord(
        id=stable_id(board_key, provider_id, remote_id),
        board_key=board_key,
        provider_id=provider_id,
        remote_id=remote_id,
        title=f"Job {remote_id}",
        company=board_key,
        raw_listing={"id": remote_id},
    )
    return ListingPosting(job=job, listing=job.raw_listing, detail=None)


def _kernel(*, native_id: str, provider_id: str) -> BoardListingKernelResult:
    return BoardListingKernelResult(
        native_board_identity=native_id,
        postings=(
            _posting(remote_id="job-1", board_key=native_id, provider_id=provider_id),
        ),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=True,
            complete=True,
            terminal_page_seen=True,
            pages_fetched=1,
            observed_count=1,
        ),
    )


def test_load_optional_pull_returns_none_when_spec_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "openopps.providers.pull", raising=False)
    monkeypatch.setattr(
        "openopps.providers.boards.listing.importlib.util.find_spec",
        lambda _name: None,
    )

    assert load_optional_pull() is None


def test_strict_decoded_path_parts_match_decode_url_identity_segment() -> None:
    assert strict_decoded_path_parts("/acme/jobs") == ("acme", "jobs")
    assert strict_decoded_path_parts("/acme/jobs/") == ("acme", "jobs")
    assert strict_decoded_path_parts("acme/jobs") is None
    assert strict_decoded_path_parts("/acme//jobs") is None
    assert strict_decoded_path_parts("/acme%2Fother/jobs") is None
    encoded = decode_url_identity_segment("Pear-VC")
    assert encoded == "Pear-VC"
    assert strict_decoded_path_parts("/Pear-VC/jobs") == ("Pear-VC", "jobs")


def test_bind_listing_jobs_rewrites_catalog_identity() -> None:
    kernel = _kernel(native_id="ashby-token", provider_id="ashbyhq")
    catalog = BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme Corp",
    )

    jobs = bind_listing_jobs(kernel, catalog, provider_id="ashbyhq")

    assert jobs[0].board_key == "manual:acme"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].id == stable_id("manual:acme", "ashbyhq", "job-1")
    assert jobs[0].remote_id == "job-1"


def test_bind_listing_jobs_keeps_url_pull_native_identity() -> None:
    kernel = _kernel(native_id="acme", provider_id="greenhouse")
    pull_board = synthetic_url_pull_board("acme")

    jobs = bind_listing_jobs(kernel, pull_board, provider_id="greenhouse")

    assert pull_board.source_key == URL_PULL_SOURCE_KEY
    assert jobs[0].board_key == "acme"
    assert jobs[0].company == "acme"
    assert jobs[0].id == stable_id("acme", "greenhouse", "job-1")


def test_bind_listing_jobs_rejects_url_pull_identity_mix() -> None:
    kernel = _kernel(native_id="acme", provider_id="greenhouse")
    mixed = synthetic_url_pull_board("other-token")

    with pytest.raises(ValueError, match="native board identity"):
        bind_listing_jobs(kernel, mixed, provider_id="greenhouse")


def test_bind_listing_jobs_rejects_foreign_provider() -> None:
    kernel = _kernel(native_id="acme", provider_id="greenhouse")
    catalog = BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme",
    )

    with pytest.raises(ValueError, match="mix providers"):
        bind_listing_jobs(kernel, catalog, provider_id="lever")


def test_incomplete_kernel_cannot_project_authoritative_snapshot() -> None:
    kernel = BoardListingKernelResult(
        native_board_identity="acme",
        postings=(),
        membership=MembershipEvidence(
            scope=MembershipScope.LISTED,
            authoritative=False,
            complete=False,
            terminal_page_seen=False,
            pages_fetched=1,
            observed_count=0,
        ),
    )
    catalog = BoardRecord(
        key="manual:acme",
        source_key="manual",
        remote_id="acme",
        name="Acme",
    )

    with pytest.raises(ValueError, match="incomplete listing"):
        kernel.to_job_fetch_result(
            catalog, provider_id="greenhouse", authoritative=True
        )


@pytest.mark.parametrize(
    "provider_cls",
    [
        AshbyProvider,
        BambooHRProvider,
        ConsiderJobsProvider,
        GreenhouseProvider,
        LeverProvider,
        RipplingProvider,
        TeamtailorProvider,
        WorkableProvider,
        WorkdayProvider,
        WPJobManagerProvider,
    ],
)
def test_fetch_jobs_does_not_wrap_pull_list(provider_cls: Any) -> None:
    fetch_source = inspect.getsource(provider_cls.fetch_jobs)
    list_source = inspect.getsource(provider_cls.pull_list)
    check_source = inspect.getsource(provider_cls.check_jobs)
    assert "self.pull_list(" not in fetch_source
    assert "await self.pull_list" not in fetch_source
    assert "_list_public_membership" in fetch_source
    assert "_list_public_membership" in list_source
    assert "_list_public_membership" not in check_source
    assert "self.pull_list(" not in check_source
