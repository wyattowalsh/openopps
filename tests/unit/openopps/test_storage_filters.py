from __future__ import annotations

from openopps.models import JobDescriptionSkill, JobRecord
from openopps.storage import JobFilters, _job_matches_filters, _salary_overlaps


def _job(**overrides: object) -> JobRecord:
    base = {
        "id": "acme:greenhouse:1",
        "board_key": "acme",
        "provider_id": "greenhouse",
        "remote_id": "1",
        "title": "Platform Engineer",
        "company": "Acme",
        "department": "Engineering",
        "team": "Platform",
        "workplace_type": "Remote",
        "remote": "Full",
        "employment_type": "Full-time",
        "locations": ["San Francisco, CA"],
        "salary_min": 140000.0,
        "salary_max": 180000.0,
        "skills": [
            JobDescriptionSkill(name="Python", level="expert", keywords=["django"])
        ],
        "posted_at": "2026-06-01T00:00:00Z",
    }
    base.update(overrides)
    return JobRecord.model_validate(base)


def test_salary_overlaps_uses_single_bound_when_other_missing() -> None:
    max_only = _job(salary_min=None, salary_max=160000.0)
    min_only = _job(salary_min=120000.0, salary_max=None)

    assert _salary_overlaps(max_only, 150000.0, None) is True
    assert _salary_overlaps(max_only, 170000.0, None) is False
    assert _salary_overlaps(min_only, None, 130000.0) is True
    assert _salary_overlaps(min_only, None, 110000.0) is False


def test_salary_overlaps_rejects_jobs_without_salary_when_filter_active() -> None:
    no_salary = _job(salary_min=None, salary_max=None)
    assert _salary_overlaps(no_salary, 100000.0, None) is False
    assert _salary_overlaps(no_salary, None, None) is True


def test_job_matches_filters_checks_department_team_and_workplace() -> None:
    job = _job()
    assert _job_matches_filters(job, JobFilters(department="engineer")) is True
    assert _job_matches_filters(job, JobFilters(department="sales")) is False
    assert _job_matches_filters(job, JobFilters(team="platform")) is True
    assert _job_matches_filters(job, JobFilters(workplace_type="remote")) is True
    assert _job_matches_filters(job, JobFilters(employment_type="full")) is True
    assert _job_matches_filters(job, JobFilters(remote="Full")) is True
    assert _job_matches_filters(job, JobFilters(remote="Hybrid")) is False


def test_job_matches_filters_checks_location_source_skill_and_dates() -> None:
    job = _job()
    board_source_keys = {"acme": ["a16z", "accel"]}

    assert (
        _job_matches_filters(
            job,
            JobFilters(source_key="accel"),
            board_source_keys=board_source_keys,
        )
        is True
    )
    assert (
        _job_matches_filters(
            job,
            JobFilters(source_key="sequoia"),
            board_source_keys=board_source_keys,
        )
        is False
    )
    assert _job_matches_filters(job, JobFilters(location="san francisco")) is True
    assert _job_matches_filters(job, JobFilters(skill="python")) is True
    assert _job_matches_filters(job, JobFilters(skill="rust")) is False
    assert _job_matches_filters(job, JobFilters(query="platform")) is True
    assert (
        _job_matches_filters(
            job,
            JobFilters(posted_after="2026-06-01", posted_before="2026-06-30"),
        )
        is True
    )
