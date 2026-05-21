import httpx
import pytest
import respx

from openopps.http import build_async_client
from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.providers.boards.ashby import AshbyProvider, ashby_token
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.boards.workday import WorkdayProvider
from openopps.settings import OpenOppsSettings


def board() -> BoardRecord:
    return BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "true"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Engineer",
                        "location": {"name": "Remote"},
                        "departments": [{"name": "Engineering"}],
                        "offices": [{"name": "United States"}],
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                        "content": "<p>Build reliable APIs.</p>",
                        "metadata": [{"name": "level", "value": "staff"}],
                    }
                ]
            },
        )
    )
    route = BoardProviderRecord(
        id="manual:acme:greenhouse",
        source_key="manual",
        board_key="acme",
        provider_id="greenhouse",
        support_level=ProviderSupport.JOBS,
        token="acme",
    )
    async with build_async_client(settings) as client:
        jobs = await GreenhouseProvider(settings).fetch_jobs(client, board(), route)

    assert jobs[0].title == "Engineer"
    assert jobs[0].company == "Acme"
    assert jobs[0].locations == ["Remote", "United States"]
    assert jobs[0].department == "Engineering"
    assert jobs[0].description == "Build reliable APIs."
    assert jobs[0].description_html == "<p>Build reliable APIs.</p>"
    assert jobs[0].remote == "Full"
    assert jobs[0].job_description is not None
    assert jobs[0].job_description.type is None
    assert (
        jobs[0].job_description.meta["canonical"]
        == "https://boards.greenhouse.io/acme/jobs/123"
    )
    assert jobs[0].raw_listing["metadata"] == [{"name": "level", "value": "staff"}]


@pytest.mark.asyncio
@respx.mock
async def test_lever_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "text": "Designer",
                    "hostedUrl": "https://jobs.lever.co/acme/abc",
                    "applyUrl": "https://jobs.lever.co/acme/abc/apply",
                    "categories": {
                        "location": "New York",
                        "department": "Design",
                        "team": "Product Design",
                        "commitment": "Full-time",
                        "customCategory": "preserved",
                    },
                    "description": "<p>Design useful workflows.</p>",
                    "lists": [
                        {
                            "text": "Responsibilities",
                            "content": "<ul><li>Ship clear flows</li></ul>",
                        },
                        {
                            "text": "Qualifications",
                            "content": "<ul><li>5+ years design</li></ul>",
                        },
                    ],
                    "additional": "<p>Equal opportunity employer.</p>",
                    "customField": {"remote": True},
                }
            ],
        )
    )
    route = BoardProviderRecord(
        id="manual:acme:lever",
        source_key="manual",
        board_key="acme",
        provider_id="lever",
        support_level=ProviderSupport.JOBS,
        token="acme",
    )
    async with build_async_client(settings) as client:
        jobs = await LeverProvider(settings).fetch_jobs(client, board(), route)

    assert jobs[0].title == "Designer"
    assert jobs[0].company == "Acme"
    assert jobs[0].locations == ["New York"]
    assert jobs[0].team == "Product Design"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].job_description is not None
    assert jobs[0].job_description.type == "Full-time"
    assert (
        jobs[0].description
        == "Design useful workflows.\nShip clear flows\n5+ years design\nEqual opportunity employer."
    )
    assert jobs[0].responsibilities == ["Ship clear flows"]
    assert jobs[0].qualifications == ["5+ years design"]
    assert jobs[0].raw_listing["categories"] == {
        "location": "New York",
        "department": "Design",
        "team": "Product Design",
        "commitment": "Full-time",
        "customCategory": "preserved",
    }
    assert jobs[0].raw_listing["customField"] == {"remote": True}


@pytest.mark.asyncio
@respx.mock
async def test_ashby_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=httpx.Response(
            200,
            json={
                "apiVersion": "1",
                "jobs": [
                    {
                        "title": "Product Manager",
                        "location": "Houston, TX",
                        "secondaryLocations": [{"location": "San Francisco"}],
                        "department": "Product",
                        "team": "Growth",
                        "workplaceType": "Remote",
                        "employmentType": "Full-time",
                        "isRemote": True,
                        "descriptionPlain": "Own the product roadmap.",
                        "descriptionHtml": "<p>Own the product roadmap.</p>",
                        "publishedAt": "2021-04-30T16:21:55.393+00:00",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                        "applyUrl": "https://jobs.ashbyhq.com/acme/abc/application",
                        "compensation": {
                            "currency": "USD",
                            "minValue": 100000,
                            "maxValue": 160000,
                        },
                        "customQuestionCount": 3,
                    }
                ],
            },
        )
    )
    route = BoardProviderRecord(
        id="manual:acme:ashbyhq",
        source_key="manual",
        board_key="acme",
        provider_id="ashbyhq",
        support_level=ProviderSupport.JOBS,
        token="acme",
    )
    async with build_async_client(settings) as client:
        jobs = await AshbyProvider(settings).fetch_jobs(client, board(), route)

    assert jobs[0].title == "Product Manager"
    assert jobs[0].locations == ["Houston, TX", "San Francisco"]
    assert jobs[0].department == "Product"
    assert jobs[0].team == "Growth"
    assert jobs[0].workplace_type == "Remote"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].remote == "Full"
    assert jobs[0].description == "Own the product roadmap."
    assert jobs[0].description_html == "<p>Own the product roadmap.</p>"
    assert jobs[0].salary == "USD 100000 - 160000"
    assert jobs[0].salary_min == 100000
    assert jobs[0].salary_max == 160000
    assert jobs[0].salary_currency == "USD"
    assert jobs[0].job_description is not None
    assert jobs[0].job_description.date == "2021-04-30"
    assert jobs[0].raw_listing["compensation"] == {
        "currency": "USD",
        "minValue": 100000,
        "maxValue": 160000,
    }
    assert jobs[0].raw_listing["customQuestionCount"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_ashby_fetch_jobs_skips_unlisted_postings():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=httpx.Response(
            200,
            json={
                "apiVersion": "1",
                "jobs": [
                    {
                        "title": "Listed",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/listed",
                        "isListed": True,
                    },
                    {
                        "title": "Direct Link",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/hidden",
                        "isListed": False,
                    },
                    {
                        "title": "Missing Flag",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/missing",
                    },
                ],
            },
        )
    )
    route = BoardProviderRecord(
        id="manual:acme:ashbyhq",
        source_key="manual",
        board_key="acme",
        provider_id="ashbyhq",
        support_level=ProviderSupport.JOBS,
        token="acme",
    )
    async with build_async_client(settings) as client:
        jobs = await AshbyProvider(settings).fetch_jobs(client, board(), route)

    assert [job.title for job in jobs] == ["Listed", "Missing Flag"]


def test_ashby_token_accepts_posting_api_url():
    route = BoardProviderRecord(
        id="manual:acme:ashbyhq",
        source_key="manual",
        board_key="acme",
        provider_id="ashbyhq",
        support_level=ProviderSupport.JOBS,
        board_url="https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true",
    )

    assert ashby_token(route) == "acme"


@pytest.mark.asyncio
@respx.mock
async def test_workday_fetches_listing_and_detail():
    settings = OpenOppsSettings(workday_concurrency=1)
    respx.post(
        "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/US_Experienced_Careers/jobs"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "jobPostings": [
                    {
                        "title": "AI Engineer",
                        "externalPath": "FL-Tampa/NGA-AI_712369WD",
                        "locationsText": "Tampa",
                        "jobFamily": "Engineering",
                        "customListing": "preserved",
                    }
                ],
            },
        )
    )
    respx.get(
        "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/US_Experienced_Careers/job/FL-Tampa/NGA-AI_712369WD"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "timeType": "Full time",
                "workerSubType": "Regular",
                "jobDescription": "<p>Build trusted AI systems.</p>",
                "customDetail": {"travel": "low"},
            },
        )
    )
    route = BoardProviderRecord(
        id="manual:pwc:workday",
        source_key="manual",
        board_key="pwc",
        provider_id="workday",
        support_level=ProviderSupport.JOBS,
        host="pwc.wd3.myworkdayjobs.com",
        tenant="pwc",
        site="US_Experienced_Careers",
    )
    async with build_async_client(settings) as client:
        jobs = await WorkdayProvider(settings).fetch_jobs(
            client,
            BoardRecord(key="pwc", source_key="manual", remote_id="pwc", name="PwC"),
            route,
        )

    assert jobs[0].title == "AI Engineer"
    assert jobs[0].company == "PwC"
    assert jobs[0].locations == ["Tampa"]
    assert jobs[0].department == "Engineering"
    assert jobs[0].workplace_type == "Full time"
    assert jobs[0].employment_type == "Full time"
    assert jobs[0].description == "Build trusted AI systems."
    assert jobs[0].description_html == "<p>Build trusted AI systems.</p>"
    assert (
        jobs[0].posting_url
        == "https://pwc.wd3.myworkdayjobs.com/US_Experienced_Careers/job/FL-Tampa/NGA-AI_712369WD"
    )
    assert jobs[0].raw_listing["customListing"] == "preserved"
    assert jobs[0].raw_detail == {
        "timeType": "Full time",
        "workerSubType": "Regular",
        "jobDescription": "<p>Build trusted AI systems.</p>",
        "customDetail": {"travel": "low"},
    }
