from openopps.models import JobRecord


def test_job_record_builds_json_resume_description():
    job = JobRecord.model_validate(
        {
            "id": "acme:ashbyhq:1",
            "board_key": "acme",
            "provider_id": "ashbyhq",
            "remote_id": "1",
            "title": "Senior Engineer",
            "company": "Acme",
            "employment_type": "Full-time",
            "locations": ["Remote", "New York, NY"],
            "description": "Build reliable systems.",
            "remote": "Full",
            "salary": "USD 100000 - 160000",
            "salary_min": 100000,
            "salary_max": 160000,
            "salary_currency": "USD",
            "experience": "Senior",
            "responsibilities": ["Build APIs"],
            "qualifications": ["5+ years Python"],
            "skills": [{"name": "Backend", "level": "Senior", "keywords": ["Python"]}],
            "posted_at": "2026-05-16T12:34:56Z",
            "posting_url": "https://jobs.ashbyhq.com/acme/1",
        }
    )

    assert job.job_description is not None
    payload = job.job_description.model_dump(mode="json")
    assert payload["title"] == "Senior Engineer"
    assert payload["company"] == "Acme"
    assert payload["type"] == "Full-time"
    assert payload["date"] == "2026-05-16"
    assert payload["description"] == "Build reliable systems."
    assert payload["location"] == {
        "address": "Remote\nNew York, NY",
        "postalCode": None,
        "city": None,
        "countryCode": None,
        "region": None,
    }
    assert payload["remote"] == "Full"
    assert payload["salary"] == "USD 100000 - 160000"
    assert payload["experience"] == "Senior"
    assert payload["responsibilities"] == ["Build APIs"]
    assert payload["qualifications"] == ["5+ years Python"]
    assert payload["skills"] == [
        {"name": "Backend", "level": "Senior", "keywords": ["Python"]}
    ]
    assert payload["meta"]["canonical"] == "https://jobs.ashbyhq.com/acme/1"
