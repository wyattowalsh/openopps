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


def test_job_record_derives_deterministic_skills_when_missing():
    job = JobRecord.model_validate(
        {
            "id": "acme:greenhouse:1",
            "board_key": "acme",
            "provider_id": "greenhouse",
            "remote_id": "1",
            "title": "Senior Platform Engineer",
            "description": (
                "Build Python and TypeScript services with Kubernetes, "
                "PostgreSQL, React, and machine learning workflows."
            ),
            "qualifications": ["Experience with AWS and Terraform."],
        }
    )

    skills = {
        skill.name: skill.model_dump(mode="python", exclude_none=True)
        for skill in job.skills
    }

    assert skills["Programming Languages"]["keywords"] == ["Python", "TypeScript"]
    assert skills["Frontend"]["keywords"] == ["React"]
    assert skills["Data and AI"]["keywords"] == ["Machine Learning"]
    assert skills["Cloud and Infrastructure"]["keywords"] == [
        "AWS",
        "Kubernetes",
        "Terraform",
    ]
    assert skills["Databases"]["keywords"] == ["PostgreSQL"]
    assert all(skill["level"] == "Senior" for skill in skills.values())
    assert job.job_description is not None
    assert job.job_description.skills == job.skills


def test_job_record_preserves_explicit_skills():
    job = JobRecord.model_validate(
        {
            "id": "acme:greenhouse:2",
            "board_key": "acme",
            "provider_id": "greenhouse",
            "remote_id": "2",
            "title": "Engineer",
            "description": "Build Python services.",
            "skills": [{"name": "Backend", "keywords": ["Python"]}],
        }
    )

    assert [skill.name for skill in job.skills] == ["Backend"]
    assert job.job_description is not None
    assert [skill.name for skill in job.job_description.skills] == ["Backend"]


def test_job_record_skill_extraction_avoids_go_to_market_false_positive():
    job = JobRecord.model_validate(
        {
            "id": "acme:greenhouse:3",
            "board_key": "acme",
            "provider_id": "greenhouse",
            "remote_id": "3",
            "title": "Go-to-market Operations Manager",
            "description": "Own CRM workflows, Salesforce hygiene, and RevOps.",
        }
    )

    keywords = [keyword for skill in job.skills for keyword in skill.keywords]

    assert "Golang" not in keywords
    assert "CRM" in keywords
    assert "Salesforce" in keywords
    assert "RevOps" in keywords
