import httpx
import pytest
import respx

import openopps.providers.boards.workable as workable_module
from openopps.http import build_async_client, retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ProviderSupport,
    validate_provider_host,
)
from openopps.providers.boards.ashby import AshbyProvider, ashby_token
from openopps.providers.boards.bamboohr import (
    BambooHRProvider,
    bamboohr_route,
    parse_bamboohr_board_url,
)
from openopps.providers.boards.greenhouse import GreenhouseProvider
from openopps.providers.boards.lever import LeverProvider
from openopps.providers.boards.rippling import RipplingProvider, rippling_slug
from openopps.providers.boards.teamtailor import TeamtailorProvider, teamtailor_host
from openopps.providers.boards.workable import WorkableProvider, workable_token
from openopps.providers.boards.workday import WorkdayProvider
from openopps.providers.boards.wpjobmanager import (
    WPJobManagerProvider,
    wpjobmanager_endpoint,
    wpjobmanager_is_ajax_endpoint,
    wpjobmanager_is_rest_endpoint,
)
from openopps.settings import OpenOppsSettings


def board() -> BoardRecord:
    return BoardRecord(key="acme", source_key="manual", remote_id="acme", name="Acme")


def route(provider_id: str, **updates: object) -> BoardProviderRecord:
    data: dict[str, object] = {
        "id": f"manual:acme:{provider_id}",
        "source_key": "manual",
        "board_key": "acme",
        "provider_id": provider_id,
        "support_level": ProviderSupport.JOBS,
    }
    data.update(updates)
    return BoardProviderRecord.model_validate(data)


def test_validate_provider_host_rejects_url_like_host_spoofing() -> None:
    assert validate_provider_host("acme.bamboohr.com", "bamboohr.com") == (
        "acme.bamboohr.com"
    )

    for host in (
        "evil.example/acme.bamboohr.com",
        "https://acme.bamboohr.com",
        "acme.bamboohr.com:443",
        "user@acme.bamboohr.com",
        "acme .bamboohr.com",
        "-acme.bamboohr.com",
    ):
        with pytest.raises(ValueError):
            validate_provider_host(host, "bamboohr.com")


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
                        "internal_job_id": 987,
                        "title": "Engineer",
                        "location": {"name": "Remote"},
                        "departments": [{"id": 1, "name": "Engineering"}],
                        "offices": [{"id": 2, "name": "United States"}],
                        "absolute_url": "http://boards.greenhouse.io/acme/jobs/123",
                        "content": "<p>Build reliable APIs.</p>",
                        "metadata": [{"name": "level", "value": "staff"}],
                        "requisition_id": "50",
                        "language": "en",
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
    assert jobs[0].posting_url == "https://boards.greenhouse.io/acme/jobs/123"
    assert jobs[0].raw_listing["metadata"] == [{"name": "level", "value": "staff"}]
    assert jobs[0].posting_kind == "standard"
    assert jobs[0].provider_extras == {
        "greenhouse": {
            "requisitionId": "50",
            "language": "en",
            "metadata": [{"name": "level", "value": "staff"}],
            "departments": [{"id": 1, "name": "Engineering"}],
            "offices": [{"id": 2, "name": "United States"}],
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_marks_prospect_posts_without_internal_job_id():
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
                        "id": 456,
                        "title": "Future Role",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/456",
                        "content": "<p>Join our talent network.</p>",
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

    assert jobs[0].posting_kind == "prospect"


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_synthesizes_public_url_when_absolute_url_missing():
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
                        "content": "<p>Build reliable APIs.</p>",
                    }
                ]
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await GreenhouseProvider(settings).fetch_jobs(
            client, board(), route("greenhouse", token="acme")
        )

    assert jobs[0].posting_url == "https://boards.greenhouse.io/acme/jobs/123"
    assert jobs[0].apply_url == "https://boards.greenhouse.io/acme/jobs/123"


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_drops_unsafe_public_job_urls():
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
                        "absolute_url": "https://greenhouse.io.evil.example/jobs/123",
                    }
                ]
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await GreenhouseProvider(settings).fetch_jobs(
            client, board(), route("greenhouse", token="acme")
        )

    assert jobs[0].posting_url is None
    assert jobs[0].apply_url is None


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_accepts_public_api_route_url():
    settings = OpenOppsSettings(cache_enabled=False)
    api_url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    match = GreenhouseProvider.detect_route(api_url)
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        params={"content": "false"},
    ).mock(return_value=httpx.Response(200, json={"jobs": [{"id": 123}]}))

    assert match is not None
    assert match.token == "acme"
    assert (
        GreenhouseProvider.detect_route(
            "https://boards-api.greenhouse.io/v1/boards/acme"
        )
        is None
    )
    assert (
        GreenhouseProvider.detect_route(
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123"
        )
        is None
    )

    async with build_async_client(settings) as client:
        count = await GreenhouseProvider(settings).check_jobs(
            client, board(), route("greenhouse", board_url=api_url)
        )

    assert count == 1


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
                    "createdAt": 1781953756907,
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
    assert jobs[0].workplace_type is None
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].posted_at == "2026-06-20T11:09:16.907000+00:00"
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
async def test_lever_accepts_public_api_route_url():
    settings = OpenOppsSettings(cache_enabled=False)
    api_url = "https://api.lever.co/v0/postings/acme?mode=json"
    match = LeverProvider.detect_route(api_url)
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(200, json=[{"id": "abc"}])
    )

    assert match is not None
    assert match.token == "acme"
    assert LeverProvider.detect_route("https://api.lever.co/v0/postings") is None
    assert LeverProvider.detect_route("https://api.lever.co/v1/postings/acme") is None

    async with build_async_client(settings) as client:
        count = await LeverProvider(settings).check_jobs(
            client, board(), route("lever", board_url=api_url)
        )

    assert count == 1


@pytest.mark.asyncio
@respx.mock
async def test_lever_extracts_structured_sections_with_empty_headings():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "text": "Designer",
                    "hostedUrl": "https://jobs.lever.co/acme/abc",
                    "categories": {},
                    "lists": [
                        {
                            "text": "",
                            "content": (
                                "<h3>Responsibilities</h3>"
                                "<ul><li>Ship clear flows</li></ul>"
                            ),
                        },
                        {
                            "text": "",
                            "content": (
                                "<h3>Requirements</h3><ul><li>5+ years design</li></ul>"
                            ),
                        },
                    ],
                }
            ],
        )
    )

    async with build_async_client(settings) as client:
        jobs = await LeverProvider(settings).fetch_jobs(
            client, board(), route("lever", token="acme")
        )

    assert jobs[0].responsibilities == ["Ship clear flows"]
    assert jobs[0].qualifications == ["5+ years design"]


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


@pytest.mark.asyncio
@respx.mock
async def test_workable_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://apply.workable.com/api/v3/accounts/acme/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "shortcode": "abc123",
                        "title": "Support Engineer",
                        "department": ["Support"],
                        "type": "Full-time",
                        "remote": True,
                        "locations": [{"city": "Austin", "country": "US"}],
                        "published": "2026-05-18T00:00:00.000Z",
                    }
                ],
            },
        )
    )
    respx.get("https://apply.workable.com/api/v2/accounts/acme/jobs/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "shortcode": "abc123",
                "description": "<p>Help customers.</p>",
                "url": "https://apply.workable.com/acme/j/abc123",
                "application_url": "https://apply.workable.com/acme/j/abc123/apply",
                "salary": {
                    "minValue": 90000,
                    "maxValue": 110000,
                    "currency": "USD",
                },
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await WorkableProvider(settings).fetch_jobs(
            client, board(), route("workable", token="acme")
        )

    assert jobs[0].title == "Support Engineer"
    assert jobs[0].locations == ["Austin, US"]
    assert jobs[0].department == "Support"
    assert jobs[0].remote == "Full"
    assert jobs[0].description == "Help customers."
    assert jobs[0].salary == "USD 90000 - 110000"
    assert jobs[0].raw_listing["shortcode"] == "abc123"
    assert "description" not in jobs[0].raw_listing
    assert jobs[0].raw_detail["description"] == "<p>Help customers.</p>"


@pytest.mark.asyncio
@respx.mock
async def test_workable_fetch_jobs_reuses_route_probe_listing_cache(tmp_path):
    settings = OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    listing_url = "https://apply.workable.com/api/v3/accounts/acme/jobs"
    listing_route = respx.post(listing_url).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "total": 1,
                    "results": [{"shortcode": "abc123", "title": "Support"}],
                },
            ),
            httpx.Response(429, json={"error": "rate limited"}),
        ]
    )
    respx.get("https://apply.workable.com/api/v2/accounts/acme/jobs/abc123").mock(
        return_value=httpx.Response(200, json={"shortcode": "abc123"})
    )

    async with build_async_client(settings) as client:
        await retrying_json_request(settings)(
            client,
            "POST",
            listing_url,
            json={},
            cache_namespace="route_probe",
            cache_identity={"provider": "workable", "route": "acme"},
        )
        jobs = await WorkableProvider(settings).fetch_jobs(
            client, board(), route("workable", token="acme")
        )

    assert [job.title for job in jobs] == ["Support"]
    assert listing_route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_workable_fetch_jobs_uses_shared_rate_limiter(monkeypatch):
    class RecordingLimiter:
        calls = 0

        async def wait(self):
            self.calls += 1

    limiter = RecordingLimiter()
    monkeypatch.setattr(workable_module, "_WORKABLE_RATE_LIMITER", limiter)
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://apply.workable.com/api/v3/accounts/acme/jobs").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "results": [{"shortcode": "abc123", "title": "Support"}]},
        )
    )
    respx.get("https://apply.workable.com/api/v2/accounts/acme/jobs/abc123").mock(
        return_value=httpx.Response(200, json={"shortcode": "abc123"})
    )

    async with build_async_client(settings) as client:
        await WorkableProvider(settings).fetch_jobs(
            client, board(), route("workable", token="acme")
        )

    assert limiter.calls == 2


def test_workable_route_detection_and_token_derivation():
    hosted = WorkableProvider.detect_route("https://apply.workable.com/acme/")
    api = WorkableProvider.detect_route("https://www.workable.com/api/accounts/acme")
    listing_api = WorkableProvider.detect_route(
        "https://apply.workable.com/api/v3/accounts/bravo/jobs"
    )
    detail_api = WorkableProvider.detect_route(
        "https://apply.workable.com/api/v2/accounts/charlie/jobs/abc123"
    )

    assert hosted is not None
    assert hosted.token == "acme"
    assert api is not None
    assert api.token == "acme"
    assert listing_api is not None
    assert listing_api.token == "bravo"
    assert detail_api is not None
    assert detail_api.token == "charlie"
    assert WorkableProvider.detect_route("https://apply.workable.com/j/abc123") is None
    assert (
        WorkableProvider.detect_route(
            "https://apply.workable.com/api/v3/accounts/bravo"
        )
        is None
    )
    assert (
        WorkableProvider.detect_route(
            "https://apply.workable.com/api/v3/accounts/bravo/jobs/extra"
        )
        is None
    )
    assert workable_token(route("workable", token=" acme ")) == "acme"
    assert (
        workable_token(
            route("workable", board_url="https://www.workable.com/api/accounts/bravo")
        )
        == "bravo"
    )
    assert (
        workable_token(
            route("workable", board_url="https://apply.workable.com/charlie/")
        )
        == "charlie"
    )
    assert (
        workable_token(
            route(
                "workable",
                board_url="https://apply.workable.com/api/v3/accounts/delta/jobs",
            )
        )
        == "delta"
    )
    assert workable_token(route("workable")) is None


@pytest.mark.asyncio
@respx.mock
async def test_workable_check_jobs_and_invalid_payload():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.post("https://apply.workable.com/api/v3/accounts/acme/jobs").mock(
        return_value=httpx.Response(200, json={"total": 2, "results": [{}, {}]})
    )
    respx.post("https://apply.workable.com/api/v3/accounts/broken/jobs").mock(
        return_value=httpx.Response(200, json={"results": "bad"})
    )

    async with build_async_client(settings) as client:
        assert (
            await WorkableProvider(settings).check_jobs(
                client, board(), route("workable", token="acme")
            )
            == 2
        )
        assert (
            await WorkableProvider(settings).check_jobs(
                client, board(), route("workable")
            )
            == 0
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            await WorkableProvider(settings).check_jobs(
                client, board(), route("workable", token="broken")
            )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://acme.teamtailor.com/jobs.rss").mock(
        return_value=httpx.Response(
            200,
            text="""
            <rss xmlns:teamtailor="https://teamtailor.com/locations">
              <channel>
                <item>
                  <title>Designer</title>
                  <link>https://acme.teamtailor.com/jobs/1</link>
                  <guid>job-1</guid>
                  <description><![CDATA[<p>Design workflows.</p>]]></description>
                  <remoteStatus>Hybrid</remoteStatus>
                  <teamtailor:department>Product</teamtailor:department>
                  <teamtailor:role>Design</teamtailor:role>
                  <teamtailor:locations>
                    <teamtailor:location><teamtailor:name>Stockholm</teamtailor:name></teamtailor:location>
                  </teamtailor:locations>
                </item>
              </channel>
            </rss>
            """,
        )
    )

    async with build_async_client(settings) as client:
        jobs = await TeamtailorProvider(settings).fetch_jobs(
            client, board(), route("teamtailor", host="acme.teamtailor.com")
        )

    assert jobs[0].title == "Designer"
    assert jobs[0].locations == ["Stockholm"]
    assert jobs[0].department == "Product"
    assert jobs[0].team == "Design"
    assert jobs[0].remote == "Hybrid"
    assert jobs[0].description == "Design workflows."
    assert jobs[0].raw_listing["locations"] == ["Stockholm"]


def test_teamtailor_route_detection_and_host_derivation():
    match = TeamtailorProvider.detect_route("https://acme.teamtailor.com/jobs")

    assert match is not None
    assert match.token == "acme"
    assert match.host == "acme.teamtailor.com"
    assert TeamtailorProvider.detect_route("https://example.com/jobs") is None
    assert teamtailor_host(route("teamtailor", host=" Acme.Teamtailor.com ")) == (
        "acme.teamtailor.com"
    )
    assert (
        teamtailor_host(
            route("teamtailor", board_url="https://bravo.teamtailor.com/jobs")
        )
        == "bravo.teamtailor.com"
    )
    assert teamtailor_host(route("teamtailor", token="charlie")) == (
        "charlie.teamtailor.com"
    )
    assert (
        teamtailor_host(route("teamtailor", host="evil.example/acme.teamtailor.com"))
        is None
    )
    assert teamtailor_host(route("teamtailor", token="evil/path")) is None
    assert teamtailor_host(route("teamtailor")) is None


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_check_jobs_and_missing_route():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://acme.teamtailor.com/jobs.rss").mock(
        return_value=httpx.Response(
            200,
            text="""
            <rss>
              <channel>
                <item><title>One</title></item>
                <item><title>Two</title></item>
              </channel>
            </rss>
            """,
        )
    )

    async with build_async_client(settings) as client:
        assert (
            await TeamtailorProvider(settings).check_jobs(
                client, board(), route("teamtailor", token="acme")
            )
            == 2
        )
        with pytest.raises(ValueError, match="missing a public board host"):
            await TeamtailorProvider(settings).fetch_jobs(
                client, board(), route("teamtailor")
            )


@pytest.mark.asyncio
@respx.mock
async def test_teamtailor_check_jobs_uses_cached_rss(tmp_path):
    settings = OpenOppsSettings(
        db_url=f"sqlite:///{tmp_path / 'openopps.db'}",
        retry_attempts=1,
        cache_ttl_seconds=60,
    )
    rss_route = respx.get("https://acme.teamtailor.com/jobs.rss").mock(
        return_value=httpx.Response(
            200,
            text="""
            <rss>
              <channel>
                <item><title>One</title></item>
              </channel>
            </rss>
            """,
        )
    )

    async with build_async_client(settings) as client:
        provider = TeamtailorProvider(settings)
        first = await provider.check_jobs(
            client, board(), route("teamtailor", token="acme")
        )
        second = await provider.check_jobs(
            client, board(), route("teamtailor", token="acme")
        )

    assert first == 1
    assert second == 1
    assert rss_route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_fetch_jobs_preserves_listing_and_detail():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://acme.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": 42,
                        "jobOpeningName": "Analyst",
                        "departmentLabel": "Operations",
                    }
                ]
            },
        )
    )
    respx.get("https://acme.bamboohr.com/careers/42/detail").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "jobOpening": {
                        "id": 42,
                        "description": "<p>Analyze operations.</p>",
                        "employmentStatusLabel": "Full-time",
                        "isRemote": False,
                        "atsLocation": {
                            "city": "Denver",
                            "state": "CO",
                            "country": "US",
                        },
                        "jobOpeningShareUrl": "https://acme.bamboohr.com/careers/42",
                    }
                }
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await BambooHRProvider(settings).fetch_jobs(
            client, board(), route("bamboohr", tenant="acme")
        )

    assert jobs[0].remote_id == "42"
    assert jobs[0].title == "Analyst"
    assert jobs[0].locations == ["Denver, CO, US"]
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].description == "Analyze operations."
    assert jobs[0].raw_listing["departmentLabel"] == "Operations"
    assert jobs[0].raw_detail["employmentStatusLabel"] == "Full-time"


def test_bamboohr_route_detection_and_route_derivation():
    parsed = parse_bamboohr_board_url("https://acme.bamboohr.com/careers")
    match = BambooHRProvider.detect_route("https://acme.bamboohr.com/careers")

    assert parsed.host == "acme.bamboohr.com"
    assert parsed.tenant == "acme"
    assert match is not None
    assert match.token == "acme"
    assert BambooHRProvider.detect_route("https://example.com/careers") is None
    with pytest.raises(ValueError, match="not a careers board"):
        parse_bamboohr_board_url("https://acme.bamboohr.com/jobs")
    assert bamboohr_route(route("bamboohr", host="acme.bamboohr.com")).tenant == "acme"
    assert (
        bamboohr_route(
            route("bamboohr", board_url="https://bravo.bamboohr.com/careers")
        ).tenant
        == "bravo"
    )
    assert bamboohr_route(route("bamboohr", token="charlie")).host == (
        "charlie.bamboohr.com"
    )
    assert bamboohr_route(route("bamboohr")) is None


@pytest.mark.asyncio
@respx.mock
async def test_bamboohr_check_jobs_count_paths_and_invalid_payload():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://meta.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json={"meta": {"totalCount": 3}, "result": []})
    )
    respx.get("https://items.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json={"result": [{}, {}]})
    )
    respx.get("https://broken.bamboohr.com/careers/list").mock(
        return_value=httpx.Response(200, json={"result": "bad"})
    )

    async with build_async_client(settings) as client:
        assert (
            await BambooHRProvider(settings).check_jobs(
                client, board(), route("bamboohr", token="meta")
            )
            == 3
        )
        assert (
            await BambooHRProvider(settings).check_jobs(
                client, board(), route("bamboohr", token="items")
            )
            == 2
        )
        assert (
            await BambooHRProvider(settings).check_jobs(
                client, board(), route("bamboohr")
            )
            == 0
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            await BambooHRProvider(settings).check_jobs(
                client, board(), route("bamboohr", token="broken")
            )


@pytest.mark.asyncio
@respx.mock
async def test_rippling_fetch_jobs_preserves_listing_and_detail():
    settings = OpenOppsSettings(cache_enabled=False, board_concurrency=1)
    respx.get("https://ats.rippling.com/api/v2/board/acme/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "totalPages": 1,
                "items": [
                    {
                        "id": "job-1",
                        "name": "Platform Engineer",
                        "locations": [{"city": "Toronto", "countryCode": "CA"}],
                    }
                ],
            },
        )
    )
    respx.get("https://ats.rippling.com/api/v2/board/acme/jobs/job-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "uuid": "job-1",
                "description": "<p>Build platform tools.</p>",
                "employmentType": {"label": "Full-time"},
                "department": {"name": "Engineering"},
                "payRangeDetails": [{"min": 100000, "max": 140000, "currency": "CAD"}],
                "url": "https://ats.rippling.com/acme/jobs/job-1",
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await RipplingProvider(settings).fetch_jobs(
            client, board(), route("rippling", token="acme")
        )

    assert jobs[0].title == "Platform Engineer"
    assert jobs[0].locations == ["Toronto, CA"]
    assert jobs[0].department == "Engineering"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].description == "Build platform tools."
    assert jobs[0].salary == "CAD 100000 - 140000"
    assert jobs[0].raw_listing["id"] == "job-1"
    assert jobs[0].raw_detail["uuid"] == "job-1"


def test_rippling_route_detection_and_slug_derivation():
    api = RipplingProvider.detect_route(
        "https://ats.rippling.com/api/v2/board/acme/jobs"
    )
    hosted = RipplingProvider.detect_route("https://ats.rippling.com/bravo/jobs")

    assert api is not None
    assert api.token == "acme"
    assert hosted is not None
    assert hosted.token == "bravo"
    assert RipplingProvider.detect_route("https://app.rippling.com/acme/jobs") is None
    assert rippling_slug(route("rippling", tenant=" tenant ")) == "tenant"
    assert rippling_slug(route("rippling", token=" token ")) == "token"
    assert (
        rippling_slug(
            route(
                "rippling", board_url="https://ats.rippling.com/api/v2/board/api/jobs"
            )
        )
        == "api"
    )
    assert (
        rippling_slug(
            route("rippling", board_url="https://ats.rippling.com/hosted/jobs")
        )
        == "hosted"
    )
    assert rippling_slug(route("rippling")) is None


@pytest.mark.asyncio
@respx.mock
async def test_rippling_check_jobs_count_paths_and_invalid_payload():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get(
        "https://ats.rippling.com/api/v2/board/total/jobs",
        params={"page": 0, "pageSize": 1},
    ).mock(return_value=httpx.Response(200, json={"totalItems": 4, "items": []}))
    respx.get(
        "https://ats.rippling.com/api/v2/board/items/jobs",
        params={"page": 0, "pageSize": 1},
    ).mock(return_value=httpx.Response(200, json={"items": [{}, {}]}))
    respx.get(
        "https://ats.rippling.com/api/v2/board/broken/jobs",
        params={"page": 0, "pageSize": 1},
    ).mock(return_value=httpx.Response(200, json={"items": "bad"}))

    async with build_async_client(settings) as client:
        assert (
            await RipplingProvider(settings).check_jobs(
                client, board(), route("rippling", token="total")
            )
            == 4
        )
        assert (
            await RipplingProvider(settings).check_jobs(
                client, board(), route("rippling", token="items")
            )
            == 2
        )
        assert (
            await RipplingProvider(settings).check_jobs(
                client, board(), route("rippling")
            )
            == 0
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            await RipplingProvider(settings).check_jobs(
                client, board(), route("rippling", token="broken")
            )


@pytest.mark.asyncio
@respx.mock
async def test_wpjobmanager_fetch_jobs():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://jobs.example.com/wp-json/wp/v2/job-listings").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 7,
                    "title": {"rendered": "WordPress Developer"},
                    "content": {"rendered": "<p>Maintain plugins.</p>"},
                    "link": "https://jobs.example.com/jobs/wordpress-developer",
                    "date": "2026-01-01T00:00:00",
                    "meta": {
                        "_job_location": "Remote",
                        "_company_name": "Acme Labs",
                        "_job_type": "Contract",
                        "_application": "https://jobs.example.com/apply/7",
                    },
                }
            ],
        )
    )

    async with build_async_client(settings) as client:
        jobs = await WPJobManagerProvider(settings).fetch_jobs(
            client,
            board(),
            route(
                "wpjobmanager",
                board_url="https://jobs.example.com/wp-json/wp/v2/job-listings",
            ),
        )

    assert jobs[0].title == "WordPress Developer"
    assert jobs[0].locations == ["Remote"]
    assert jobs[0].company == "Acme Labs"
    assert jobs[0].employment_type == "Contract"
    assert jobs[0].description == "Maintain plugins."
    assert jobs[0].apply_url == "https://jobs.example.com/apply/7"
    assert jobs[0].raw_listing["id"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_wpjobmanager_fetch_jobs_from_ajax_endpoint():
    settings = OpenOppsSettings(cache_enabled=False)
    respx.get("https://jobs.example.com/jm-ajax/get_listings/").mock(
        return_value=httpx.Response(
            200,
            json={
                "found_jobs": True,
                "max_num_pages": 1,
                "html": """
                <ul class="job_listings">
                  <li class="job_listing">
                    <a href="https://jobs.example.com/job/support-engineer/">
                      <div class="position"><h3>Support Engineer</h3></div>
                      <div class="company"><strong>Acme Labs</strong></div>
                      <div class="location">Remote</div>
                    </a>
                  </li>
                </ul>
                """,
            },
        )
    )

    async with build_async_client(settings) as client:
        jobs = await WPJobManagerProvider(settings).fetch_jobs(
            client,
            board(),
            route(
                "wpjobmanager",
                board_url="https://jobs.example.com/jm-ajax/get_listings/",
            ),
        )

    assert jobs[0].title == "Support Engineer"
    assert jobs[0].locations == ["Remote"]
    assert jobs[0].company == "Acme Labs"
    assert jobs[0].posting_url == "https://jobs.example.com/job/support-engineer/"
    assert jobs[0].raw_listing["source"] == "jm-ajax/get_listings"


def test_wpjobmanager_route_detection_and_endpoint_derivation():
    rest_url = "https://jobs.example.com/wp-json/wp/v2/job-listings"
    ajax_url = "https://jobs.example.com/jm-ajax/get_listings/"
    rest = WPJobManagerProvider.detect_route(rest_url)
    ajax = WPJobManagerProvider.detect_route(ajax_url)

    assert rest is not None
    assert rest.token == "https://jobs.example.com"
    assert ajax is not None
    assert ajax.host == "jobs.example.com"
    assert WPJobManagerProvider.detect_route("https://jobs.example.com/careers") is None
    assert wpjobmanager_is_rest_endpoint(rest_url)
    assert wpjobmanager_is_ajax_endpoint(ajax_url)
    assert wpjobmanager_endpoint(route("wpjobmanager", board_url=rest_url)) == rest_url
    assert wpjobmanager_endpoint(route("wpjobmanager", board_url=ajax_url)) == ajax_url
    assert (
        wpjobmanager_endpoint(
            route("wpjobmanager", board_url="https://jobs.example.com")
        )
        == rest_url
    )
    assert (
        wpjobmanager_endpoint(
            route("wpjobmanager", token="https://careers.example.com")
        )
        == "https://careers.example.com/wp-json/wp/v2/job-listings"
    )
    assert (
        wpjobmanager_endpoint(route("wpjobmanager", host="Jobs.Example.com"))
        == rest_url
    )
    assert (
        wpjobmanager_endpoint(
            route("wpjobmanager", host="evil.example/jobs.example.com")
        )
        is None
    )
    assert wpjobmanager_endpoint(route("wpjobmanager")) is None


@pytest.mark.asyncio
@respx.mock
async def test_wpjobmanager_check_jobs_count_paths_and_invalid_payload():
    settings = OpenOppsSettings(cache_enabled=False)
    rest_url = "https://jobs.example.com/wp-json/wp/v2/job-listings"
    ajax_url = "https://jobs.example.com/jm-ajax/get_listings/"
    respx.get(rest_url, params={"per_page": 1}).mock(
        return_value=httpx.Response(200, json=[{}], headers={"x-wp-total": "9"})
    )
    respx.get(ajax_url, params={"page": 1, "per_page": 1}).mock(
        return_value=httpx.Response(200, json={"total": "7", "html": ""})
    )
    respx.get("https://broken.example.com/wp-json/wp/v2/job-listings").mock(
        return_value=httpx.Response(200, json={"not": "a list"})
    )

    async with build_async_client(settings) as client:
        assert (
            await WPJobManagerProvider(settings).check_jobs(
                client, board(), route("wpjobmanager", board_url=rest_url)
            )
            == 9
        )
        assert (
            await WPJobManagerProvider(settings).check_jobs(
                client, board(), route("wpjobmanager", board_url=ajax_url)
            )
            == 7
        )
        assert (
            await WPJobManagerProvider(settings).check_jobs(
                client, board(), route("wpjobmanager")
            )
            == 0
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            await WPJobManagerProvider(settings).check_jobs(
                client,
                board(),
                route("wpjobmanager", host="broken.example.com"),
            )


def test_consider_normalize_companies_disambiguates_board_key_collisions() -> None:
    from openopps.models import ConsiderCompany
    from openopps.providers.sources.consider import ConsiderSourceAdapter

    adapter = ConsiderSourceAdapter(OpenOppsSettings())
    companies = [
        ConsiderCompany(id="company-1", slug="acme", name="Acme One"),
        ConsiderCompany(id="company-2", slug="acme", name="Acme Two"),
    ]

    boards, _providers = adapter._normalize_companies("yc", companies)

    assert len(boards) == 2
    assert boards[0].key != boards[1].key
    assert {board.key for board in boards} == {"yc:acme", "yc:acme-company-2"}


def test_public_page_normalize_candidates_counts_board_key_collisions() -> None:
    from openopps.models import SourceRecord
    from openopps.providers.sources.special import PublicPageSourceAdapter

    adapter = PublicPageSourceAdapter(OpenOppsSettings())
    source = SourceRecord(
        key="demo",
        url="https://demo.example/portfolio",
        provider_id="public_page",
    )
    candidates = [
        {
            "url": "https://acme.example/about",
            "name": "Acme",
            "host": "acme.example",
            "path": "/about",
            "text": "Acme",
        },
        {
            "url": "https://acme.example/jobs",
            "name": "Acme",
            "host": "acme.example",
            "path": "/jobs",
            "text": "Acme jobs",
        },
    ]

    boards, _providers, meta = adapter._normalize_candidates(source, candidates)

    assert len(boards) == 1
    assert meta["boardKeyCollisions"] == 1
