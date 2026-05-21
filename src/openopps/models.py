from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from html import unescape
import re
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


JsonDict = dict[str, JsonValue]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = NonEmptyStr | None
RemoteWorkLevel = Literal["Full", "Hybrid", "None"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderSupport(StrEnum):
    """Normalized capability level for a detected job-board provider route."""

    DETECT = "detect"
    JOBS = "jobs"
    UNSUPPORTED = "unsupported"


class ExportFormat(StrEnum):
    """Supported durable export formats for normalized records."""

    JSONL = "jsonl"
    CSV = "csv"
    PARQUET = "parquet"


class RemoteLevel(StrEnum):
    """JSON Resume-compatible remote-work level."""

    FULL = "Full"
    HYBRID = "Hybrid"
    NONE = "None"


class OpenOppsRecord(BaseModel):
    """Shared boundary model behavior for provider, storage, and export records.

    Provider APIs evolve often, so normalized records keep unknown top-level
    response fields as extras while raw upstream payloads remain available for
    audit and reprocessing.
    """

    model_config = ConfigDict(
        extra="allow",
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        validate_default=True,
        json_schema_extra={"additionalProperties": True},
    )


class ProviderPayload(OpenOppsRecord):
    """Provider-native payload with typed known fields and preserved unknown fields."""

    def as_raw_payload(self) -> JsonDict:
        """Return the provider payload using upstream field names and supplied fields only."""

        return cast(
            JsonDict,
            self.model_dump(mode="python", by_alias=True, exclude_unset=True),
        )


class JobDescriptionLocation(OpenOppsRecord):
    """JSON Resume-compatible job location shape."""

    model_config = ConfigDict(serialize_by_alias=True)

    address: str | None = None
    postal_code: str | None = Field(default=None, alias="postalCode")
    city: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")
    region: str | None = None


class JobDescriptionSkill(OpenOppsRecord):
    """JSON Resume-compatible job skill shape."""

    name: OptionalNonEmptyStr = None
    level: OptionalNonEmptyStr = None
    keywords: list[NonEmptyStr] = Field(default_factory=list)


class JobDescriptionRecord(OpenOppsRecord):
    """JSON Resume-compatible job description object.

    The upstream schema permits additional properties, so this model intentionally
    inherits OpenOppsRecord's extra-field behavior.
    """

    model_config = ConfigDict(serialize_by_alias=True)

    title: OptionalNonEmptyStr = None
    company: OptionalNonEmptyStr = None
    type: OptionalNonEmptyStr = None
    date: OptionalNonEmptyStr = None
    description: str | None = None
    location: JobDescriptionLocation | None = None
    remote: RemoteWorkLevel | None = None
    salary: str | None = None
    experience: str | None = None
    responsibilities: list[NonEmptyStr] = Field(default_factory=list)
    qualifications: list[NonEmptyStr] = Field(default_factory=list)
    skills: list[JobDescriptionSkill] = Field(default_factory=list)
    meta: JsonDict = Field(default_factory=dict)


def strip_html(value: str | None) -> str | None:
    """Convert provider HTML snippets into deterministic plain text."""

    if not value:
        return None
    with_breaks = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    with_breaks = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", with_breaks)
    text = re.sub(r"<[^>]+>", " ", with_breaks)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text or None


def normalize_remote_level(
    *values: object,
    is_remote: bool | None = None,
) -> RemoteWorkLevel | None:
    """Normalize provider workplace hints to JSON Resume's remote enum."""

    if is_remote is True:
        return RemoteLevel.FULL.value

    haystack = " ".join(_string_values(*values)).lower()
    if any(word in haystack for word in ("hybrid", "flexible")):
        return RemoteLevel.HYBRID.value
    if any(word in haystack for word in ("remote", "distributed", "virtual")):
        return RemoteLevel.FULL.value
    if any(
        word in haystack
        for word in ("onsite", "on-site", "in office", "office-based", "office based")
    ):
        return RemoteLevel.NONE.value
    if is_remote is False:
        return RemoteLevel.NONE.value
    return None


def _string_values(*values: object) -> list[str]:
    strings: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            strings.append(value)
            continue
        if isinstance(value, list):
            strings.extend(str(item) for item in value if item is not None)
            continue
        strings.append(str(value))
    return strings


def date_prefix(value: str | None) -> str | None:
    """Return a JSON Resume-compatible YYYY[-MM[-DD]] date prefix when present."""

    if not value:
        return None
    match = re.match(r"^([1-2][0-9]{3}(?:-[0-1][0-9](?:-[0-3][0-9])?)?)", value)
    return match.group(1) if match else None


def build_job_description(record: JobRecord) -> JobDescriptionRecord:
    """Build the JSON Resume-compatible description object for a job record."""

    location = None
    if record.locations:
        location = JobDescriptionLocation(address="\n".join(record.locations))

    meta: JsonDict = {
        "provider": record.provider_id,
        "board": record.board_key,
        "remoteId": record.remote_id,
    }
    if record.posting_url:
        meta["canonical"] = record.posting_url
    if record.synced_at:
        meta["lastModified"] = record.synced_at.isoformat()

    return JobDescriptionRecord(
        title=record.title,
        company=record.company,
        type=record.employment_type,
        date=date_prefix(record.posted_at),
        description=record.description,
        location=location,
        remote=record.remote,
        salary=record.salary,
        experience=record.experience,
        responsibilities=record.responsibilities,
        qualifications=record.qualifications,
        skills=record.skills,
        meta=meta,
    )


class SourceRecord(OpenOppsRecord):
    """A configured source of opportunity-board companies."""

    key: NonEmptyStr = Field(
        description="Stable local identifier for the source.",
        examples=["yc", "a16z", "lsvp"],
    )
    url: NonEmptyStr = Field(
        description="Canonical source URL or synthetic manual source URI.",
        examples=["https://www.ycombinator.com/companies", "manual://source"],
    )
    provider_id: NonEmptyStr = Field(
        description="Source adapter identifier used to fetch and normalize boards.",
        examples=["ycombinator", "consider", "getro", "manual"],
    )
    enabled: bool = Field(
        default=True,
        description="Whether scheduled or default source syncs should include this source.",
        examples=[True],
    )
    version: JsonDict = Field(
        default_factory=dict,
        description="Provider-supplied version or cursor metadata for incremental syncs.",
        examples=[{"etag": "W/123", "sequence": "abc"}],
    )
    raw_metadata: JsonDict = Field(
        default_factory=dict,
        description="Configuration and last-page metadata that must survive syncs unchanged.",
        examples=[{"board": "lightspeed", "lastPage": {"total": 100}}],
    )
    synced_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp for the last successful source sync.",
        examples=["2026-05-16T12:34:56Z"],
    )


class BoardProviderRecord(OpenOppsRecord):
    """A detected route from a board to a provider-specific job source."""

    id: NonEmptyStr = Field(
        description="Stable primary key for this source, board, and provider route.",
        examples=["yc:airbnb:greenhouse"],
    )
    source_key: NonEmptyStr = Field(
        description="Source key that reported this provider route.",
        examples=["yc"],
    )
    board_key: NonEmptyStr = Field(
        description="Normalized board key this route belongs to.",
        examples=["airbnb"],
    )
    provider_id: NonEmptyStr = Field(
        description="Provider adapter identifier for the detected job route.",
        examples=["greenhouse", "lever", "ashbyhq", "workday"],
    )
    label: OptionalNonEmptyStr = Field(
        default=None,
        description="Human-readable upstream label for the provider route.",
        examples=["Greenhouse"],
    )
    support_level: ProviderSupport = Field(
        default=ProviderSupport.UNSUPPORTED,
        description="Whether OpenOpps can only detect the route, fetch jobs from it, or cannot use it.",
        examples=[ProviderSupport.JOBS],
    )
    count_hint: NonNegativeInt | None = Field(
        default=None,
        description="Provider-reported approximate job count, when available.",
        examples=[42],
    )
    board_url: OptionalNonEmptyStr = Field(
        default=None,
        description="Public hosted job board URL used to derive provider route details.",
        examples=["https://boards.greenhouse.io/acme"],
    )
    token: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-specific board token, slug, or short identifier.",
        examples=["acme"],
    )
    host: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider host for multi-tenant routes such as Workday CXS.",
        examples=["acme.wd1.myworkdayjobs.com"],
    )
    tenant: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider tenant for multi-tenant routes such as Workday CXS.",
        examples=["acme"],
    )
    site: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider site path or career-site identifier for multi-site routes.",
        examples=["External"],
    )
    last_status: OptionalNonEmptyStr = Field(
        default=None,
        description="Last known route-probe or sync status for diagnostics.",
        examples=["200 OK", "unsupported"],
    )
    raw_payload: JsonDict = Field(
        default_factory=dict,
        description="Unmodified upstream route object for auditability.",
        examples=[{"id": "greenhouse", "label": "Greenhouse", "count": 12}],
    )
    detected_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp when the route was discovered or refreshed.",
        examples=["2026-05-16T12:34:56Z"],
    )


class BoardRecord(OpenOppsRecord):
    """A normalized company or organization board discovered from a source."""

    key: NonEmptyStr = Field(
        description="Stable normalized board key, usually derived from the upstream slug.",
        examples=["acme"],
    )
    source_key: NonEmptyStr = Field(
        description="Source key that emitted this board.",
        examples=["a16z"],
    )
    remote_id: NonEmptyStr = Field(
        description="Provider-native board or company identifier preserved as text.",
        examples=["12345", "acme"],
    )
    remote_slug: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-native slug when distinct from the local key.",
        examples=["acme-inc"],
    )
    name: NonEmptyStr = Field(
        description="Display name for the company or opportunity board.",
        examples=["Acme"],
    )
    domain: OptionalNonEmptyStr = Field(
        default=None,
        description="Normalized website domain without scheme, when known.",
        examples=["acme.com"],
    )
    website_url: OptionalNonEmptyStr = Field(
        default=None,
        description="Canonical company website URL, when available.",
        examples=["https://acme.com"],
    )
    description: str | None = Field(
        default=None,
        description="Provider-supplied company or board description.",
        examples=["Builds infrastructure for opportunity discovery."],
    )
    markets: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Industry, market, or category tags reported by the source.",
        examples=[["Developer Tools", "Infrastructure"]],
    )
    locations: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Company office, region, or hiring-location labels.",
        examples=[["San Francisco", "Remote"]],
    )
    staff_count: NonNegativeInt | None = Field(
        default=None,
        description="Provider-reported employee or team-size estimate.",
        examples=[120],
    )
    num_jobs_hint: NonNegativeInt | None = Field(
        default=None,
        description="Provider-reported approximate number of open jobs.",
        examples=[8],
    )
    raw_payload: JsonDict = Field(
        default_factory=dict,
        description="Unmodified upstream company or board object for auditability.",
        examples=[{"id": 123, "name": "Acme", "numJobs": 8}],
    )
    providers: list[BoardProviderRecord] = Field(
        default_factory=list,
        description="Detected provider routes associated with this board.",
    )
    synced_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp when the board was last fetched from its source.",
        examples=["2026-05-16T12:34:56Z"],
    )


class JobRecord(OpenOppsRecord):
    """A normalized public job posting fetched from a job-capable provider."""

    id: NonEmptyStr = Field(
        description="Stable OpenOpps job identifier derived from board, provider, and remote id.",
        examples=["acme:greenhouse:12345"],
    )
    board_key: NonEmptyStr = Field(
        description="Normalized board key this job belongs to.",
        examples=["acme"],
    )
    provider_id: NonEmptyStr = Field(
        description="Provider adapter identifier that produced this job.",
        examples=["greenhouse", "lever", "ashbyhq", "workday"],
    )
    remote_id: NonEmptyStr = Field(
        description="Provider-native job identifier preserved as text.",
        examples=["12345"],
    )
    title: NonEmptyStr = Field(
        description="Public job title.",
        examples=["Senior Software Engineer"],
    )
    locations: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Provider-reported job location labels, preserving original text.",
        examples=[["New York, NY", "Remote"]],
    )
    department: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-reported department or job family.",
        examples=["Engineering"],
    )
    team: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-reported team, subdepartment, or group.",
        examples=["Platform"],
    )
    workplace_type: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-reported workplace, commitment, or time-type label.",
        examples=["Remote", "Full-time"],
    )
    company: OptionalNonEmptyStr = Field(
        default=None,
        description="Board or company display name attached to the posting.",
        examples=["Acme"],
    )
    employment_type: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-reported employment or commitment type.",
        examples=["Full-time", "Contract"],
    )
    description: str | None = Field(
        default=None,
        description="Plain-text provider job description when deterministically available.",
        examples=["Build reliable systems for customers."],
    )
    description_html: str | None = Field(
        default=None,
        description="Provider HTML job description when available.",
        examples=["<p>Build reliable systems.</p>"],
    )
    remote: RemoteWorkLevel | None = Field(
        default=None,
        description="JSON Resume-compatible remote work level.",
        examples=["Full", "Hybrid", "None"],
    )
    compensation: JsonDict | None = Field(
        default=None,
        description="Provider compensation payload or deterministic normalized compensation details.",
        examples=[{"currency": "USD", "minValue": 100000, "maxValue": 160000}],
    )
    salary: str | None = Field(
        default=None,
        description="JSON Resume-compatible salary display string.",
        examples=["USD 100000 - 160000"],
    )
    salary_min: float | None = Field(
        default=None,
        description="Minimum salary or compensation value when provider supplies a deterministic range.",
        examples=[100000],
    )
    salary_max: float | None = Field(
        default=None,
        description="Maximum salary or compensation value when provider supplies a deterministic range.",
        examples=[160000],
    )
    salary_currency: OptionalNonEmptyStr = Field(
        default=None,
        description="Salary or compensation currency code when available.",
        examples=["USD"],
    )
    experience: str | None = Field(
        default=None,
        description="Provider-reported or deterministic experience label when available.",
        examples=["Senior"],
    )
    responsibilities: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Provider-structured responsibility bullets when deterministically available.",
    )
    qualifications: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Provider-structured qualification bullets when deterministically available.",
    )
    skills: list[JobDescriptionSkill] = Field(
        default_factory=list,
        description="JSON Resume-compatible skill objects when deterministically available.",
    )
    job_description: JobDescriptionRecord | None = Field(
        default=None,
        description="JSON Resume-compatible job-description object built from normalized fields.",
    )
    posting_url: OptionalNonEmptyStr = Field(
        default=None,
        description="Canonical public posting URL.",
        examples=["https://boards.greenhouse.io/acme/jobs/12345"],
    )
    apply_url: OptionalNonEmptyStr = Field(
        default=None,
        description="Direct application URL when distinct from the posting URL.",
        examples=["https://jobs.ashbyhq.com/acme/12345/application"],
    )
    posted_at: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-native posting timestamp or date string.",
        examples=["2026-05-16T12:34:56Z"],
    )
    updated_at: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-native update timestamp or date string.",
        examples=["2026-05-17T09:00:00Z"],
    )
    status: NonEmptyStr = Field(
        default="open",
        description="Normalized posting lifecycle status.",
        examples=["open", "closed"],
    )
    raw_listing: JsonDict = Field(
        default_factory=dict,
        description="Unmodified upstream list-entry payload for auditability.",
        examples=[{"id": 12345, "title": "Senior Software Engineer"}],
    )
    raw_detail: JsonDict = Field(
        default_factory=dict,
        description="Unmodified upstream detail payload fetched separately, when available.",
        examples=[{"description": "Build reliable systems."}],
    )
    synced_at: AwareDatetime = Field(
        default_factory=utc_now,
        description="UTC timestamp when the job was last fetched.",
        examples=["2026-05-16T12:34:56Z"],
    )

    @model_validator(mode="after")
    def _populate_job_description(self) -> Self:
        if self.job_description is None:
            object.__setattr__(self, "job_description", build_job_description(self))
        return self


class ProviderNamedValue(ProviderPayload):
    """Common provider object that carries an id/name/display label."""

    id: str | int | None = Field(
        default=None,
        description="Provider-native identifier for the nested value.",
        examples=[12345, "engineering"],
    )
    name: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-native display name for the nested value.",
        examples=["Engineering", "Remote"],
    )
    display_name: OptionalNonEmptyStr = Field(
        default=None,
        alias="displayName",
        description="Provider-native displayName variant used by Workday CXS payloads.",
        examples=["Tampa, FL"],
    )


class GreenhouseJobPosting(ProviderPayload):
    """Greenhouse board API job object from `/v1/boards/{token}/jobs`."""

    id: str | int | None = Field(
        default=None,
        description="Greenhouse public job id.",
        examples=[12345],
    )
    internal_job_id: str | int | None = Field(
        default=None,
        description="Greenhouse internal job id when exposed on the board feed.",
        examples=[98765],
    )
    title: OptionalNonEmptyStr = Field(
        default=None,
        description="Public Greenhouse job title.",
        examples=["Senior Software Engineer"],
    )
    absolute_url: OptionalNonEmptyStr = Field(
        default=None,
        description="Canonical Greenhouse-hosted public posting URL.",
        examples=["https://boards.greenhouse.io/acme/jobs/12345"],
    )
    location: ProviderNamedValue | None = Field(
        default=None,
        description="Primary Greenhouse job location object.",
        examples=[{"name": "Remote"}],
    )
    departments: list[ProviderNamedValue] = Field(
        default_factory=list,
        description="Greenhouse department hierarchy objects.",
        examples=[[{"id": 1, "name": "Engineering"}]],
    )
    offices: list[ProviderNamedValue] = Field(
        default_factory=list,
        description="Greenhouse office hierarchy objects.",
        examples=[[{"id": 2, "name": "New York"}]],
    )
    updated_at: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-native update timestamp string.",
        examples=["2026-05-16T12:34:56-04:00"],
    )
    content: str | None = Field(
        default=None,
        description="Greenhouse HTML job content when requested with content=true.",
        examples=["<p>Build systems.</p>"],
    )


class GreenhouseJobsResponse(ProviderPayload):
    """Greenhouse board jobs response envelope."""

    jobs: list[GreenhouseJobPosting] = Field(
        default_factory=list,
        description="Greenhouse job postings included in this board response.",
    )
    meta: JsonDict = Field(
        default_factory=dict,
        description="Greenhouse response metadata, if present.",
        examples=[{"total": 10}],
    )


class LeverPostingCategories(ProviderPayload):
    """Lever posting category labels nested under `categories`."""

    location: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever category location label.",
        examples=["New York"],
    )
    department: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever category department label.",
        examples=["Design"],
    )
    team: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever category team label.",
        examples=["Product Design"],
    )
    commitment: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever commitment or employment-type label.",
        examples=["Full-time"],
    )


class LeverPostingList(ProviderPayload):
    """Lever structured description list section."""

    text: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever section heading.",
        examples=["Responsibilities"],
    )
    content: str | None = Field(
        default=None,
        description="Lever HTML section content.",
        examples=["<li>Build APIs.</li>"],
    )


class LeverPosting(ProviderPayload):
    """Lever posting object from `/v0/postings/{token}?mode=json`."""

    id: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever posting id.",
        examples=["abc123"],
    )
    text: OptionalNonEmptyStr = Field(
        default=None,
        description="Lever public job title field.",
        examples=["Designer"],
    )
    hosted_url: OptionalNonEmptyStr = Field(
        default=None,
        alias="hostedUrl",
        description="Lever-hosted public posting URL.",
        examples=["https://jobs.lever.co/acme/abc123"],
    )
    apply_url: OptionalNonEmptyStr = Field(
        default=None,
        alias="applyUrl",
        description="Lever direct application URL.",
        examples=["https://jobs.lever.co/acme/abc123/apply"],
    )
    categories: LeverPostingCategories = Field(
        default_factory=LeverPostingCategories,
        description="Lever category labels used for normalized locations and teams.",
    )
    description: str | None = Field(
        default=None,
        description="Lever HTML job description.",
        examples=["<p>About the role.</p>"],
    )
    description_plain: str | None = Field(
        default=None,
        alias="descriptionPlain",
        description="Lever plain-text description when supplied.",
        examples=["About the role."],
    )
    lists: list[LeverPostingList] = Field(
        default_factory=list,
        description="Lever structured description sections.",
    )
    additional: str | None = Field(
        default=None,
        description="Lever additional HTML description content.",
        examples=["<p>Equal opportunity statement.</p>"],
    )
    created_at: str | int | None = Field(
        default=None,
        alias="createdAt",
        description="Lever provider-native created timestamp, often milliseconds since epoch.",
        examples=[1715880000000],
    )
    updated_at: str | int | None = Field(
        default=None,
        alias="updatedAt",
        description="Lever provider-native updated timestamp, often milliseconds since epoch.",
        examples=[1715880000000],
    )


class AshbySecondaryLocation(ProviderPayload):
    """Ashby secondary location object."""

    location: OptionalNonEmptyStr = Field(
        default=None,
        description="Secondary public location label.",
        examples=["San Francisco"],
    )


class AshbyJobPosting(ProviderPayload):
    """Ashby posting API job object."""

    id: OptionalNonEmptyStr = Field(
        default=None,
        description="Ashby job id when present.",
        examples=["018f4cb3-67b4-7fd5-a07d-3c0f00f31caa"],
    )
    title: OptionalNonEmptyStr = Field(
        default=None,
        description="Public Ashby job title.",
        examples=["Product Manager"],
    )
    location: OptionalNonEmptyStr = Field(
        default=None,
        description="Primary public location label.",
        examples=["Houston, TX"],
    )
    secondary_locations: list[AshbySecondaryLocation] = Field(
        default_factory=list,
        alias="secondaryLocations",
        description="Additional public locations for the Ashby posting.",
        examples=[[{"location": "San Francisco"}]],
    )
    department: OptionalNonEmptyStr = Field(
        default=None,
        description="Ashby department label.",
        examples=["Product"],
    )
    team: OptionalNonEmptyStr = Field(
        default=None,
        description="Ashby team label.",
        examples=["Growth"],
    )
    workplace_type: OptionalNonEmptyStr = Field(
        default=None,
        alias="workplaceType",
        description="Ashby workplace type label.",
        examples=["Remote"],
    )
    employment_type: OptionalNonEmptyStr = Field(
        default=None,
        alias="employmentType",
        description="Ashby employment type label.",
        examples=["Full-time"],
    )
    is_remote: bool | None = Field(
        default=None,
        alias="isRemote",
        description="Ashby boolean remote flag when supplied.",
        examples=[True],
    )
    description_plain: str | None = Field(
        default=None,
        alias="descriptionPlain",
        description="Ashby plain-text job description.",
        examples=["Build product experiences."],
    )
    description_html: str | None = Field(
        default=None,
        alias="descriptionHtml",
        description="Ashby HTML job description.",
        examples=["<p>Build product experiences.</p>"],
    )
    published_at: OptionalNonEmptyStr = Field(
        default=None,
        alias="publishedAt",
        description="Ashby provider-native published timestamp.",
        examples=["2021-04-30T16:21:55.393+00:00"],
    )
    job_url: OptionalNonEmptyStr = Field(
        default=None,
        alias="jobUrl",
        description="Ashby-hosted public posting URL.",
        examples=["https://jobs.ashbyhq.com/acme/abc"],
    )
    apply_url: OptionalNonEmptyStr = Field(
        default=None,
        alias="applyUrl",
        description="Ashby direct application URL.",
        examples=["https://jobs.ashbyhq.com/acme/abc/application"],
    )
    is_listed: bool | None = Field(
        default=None,
        alias="isListed",
        description="Whether Ashby lists this posting publicly on the board.",
        examples=[True],
    )
    compensation: JsonDict | None = Field(
        default=None,
        description="Ashby compensation object when includeCompensation is enabled.",
        examples=[{"currency": "USD", "minValue": 100000, "maxValue": 160000}],
    )


class AshbyJobBoardResponse(ProviderPayload):
    """Ashby public posting API response envelope."""

    api_version: OptionalNonEmptyStr = Field(
        default=None,
        alias="apiVersion",
        description="Ashby posting API version string.",
        examples=["1"],
    )
    jobs: list[AshbyJobPosting] = Field(
        default_factory=list,
        description="Ashby job postings returned for a public board token.",
    )


class WorkdayJobPosting(ProviderPayload):
    """Workday CXS search result job posting."""

    id: str | int | None = Field(
        default=None,
        description="Workday search result id when present.",
        examples=["JR-12345"],
    )
    title: OptionalNonEmptyStr = Field(
        default=None,
        description="Workday public posting title.",
        examples=["AI Engineer"],
    )
    external_path: OptionalNonEmptyStr = Field(
        default=None,
        alias="externalPath",
        description="Workday external path used to fetch detail and build posting URLs.",
        examples=["FL-Tampa/NGA-AI_712369WD"],
    )
    locations_text: OptionalNonEmptyStr = Field(
        default=None,
        alias="locationsText",
        description="Workday flattened location label from search results.",
        examples=["Tampa"],
    )
    location: ProviderNamedValue | str | None = Field(
        default=None,
        description="Workday structured or text location value.",
        examples=[{"displayName": "Tampa"}],
    )
    job_family: OptionalNonEmptyStr = Field(
        default=None,
        alias="jobFamily",
        description="Workday job-family label from search results.",
        examples=["Engineering"],
    )
    posted_on: OptionalNonEmptyStr = Field(
        default=None,
        alias="postedOn",
        description="Workday provider-native posted date label.",
        examples=["Posted 2 Days Ago"],
    )


class WorkdayJobsResponse(ProviderPayload):
    """Workday CXS paginated search response envelope."""

    total: NonNegativeInt | None = Field(
        default=None,
        description="Total Workday search results reported by the CXS response.",
        examples=[42],
    )
    job_postings: list[WorkdayJobPosting] = Field(
        default_factory=list,
        alias="jobPostings",
        description="Workday CXS search result postings for the current page.",
    )


class WorkdayJobDetail(ProviderPayload):
    """Workday CXS job detail response."""

    title: OptionalNonEmptyStr = Field(
        default=None,
        description="Workday detail title.",
        examples=["AI Engineer"],
    )
    location: ProviderNamedValue | str | None = Field(
        default=None,
        description="Workday detail location object or label.",
        examples=[{"displayName": "Tampa"}],
    )
    job_family: OptionalNonEmptyStr = Field(
        default=None,
        alias="jobFamily",
        description="Workday detail job-family label.",
        examples=["Engineering"],
    )
    time_type: OptionalNonEmptyStr = Field(
        default=None,
        alias="timeType",
        description="Workday time-type label.",
        examples=["Full time"],
    )
    worker_sub_type: OptionalNonEmptyStr = Field(
        default=None,
        alias="workerSubType",
        description="Workday worker subtype label.",
        examples=["Regular"],
    )
    posted_on: OptionalNonEmptyStr = Field(
        default=None,
        alias="postedOn",
        description="Workday detail posted date label.",
        examples=["Posted Yesterday"],
    )
    description: str | None = Field(
        default=None,
        description="Workday detail description when supplied.",
        examples=["Build data products."],
    )
    job_description: str | None = Field(
        default=None,
        alias="jobDescription",
        description="Workday detail jobDescription value when supplied.",
        examples=["<p>Build data products.</p>"],
    )


class ConsiderWebsite(ProviderPayload):
    """Consider portfolio company website object."""

    url: OptionalNonEmptyStr = Field(
        default=None,
        description="Company website URL reported by Consider.",
        examples=["https://fivetran.com/"],
    )

    @field_validator("url", mode="before")
    @classmethod
    def normalize_blank_url(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ConsiderJobSource(ProviderPayload):
    """Consider job source hint attached to a company."""

    id: OptionalNonEmptyStr = Field(
        default=None,
        description="Consider provider id for the job source hint.",
        examples=["greenhouse"],
    )
    value: OptionalNonEmptyStr = Field(
        default=None,
        description="Fallback provider value when `id` is not present.",
        examples=["ashbyhq"],
    )
    label: OptionalNonEmptyStr = Field(
        default=None,
        description="Human-readable job source label.",
        examples=["Greenhouse"],
    )
    count: NonNegativeInt | None = Field(
        default=None,
        description="Consider-reported job count for this source.",
        examples=[131],
    )


class ConsiderCompany(ProviderPayload):
    """Consider company object from `/api-boards/search-companies`."""

    id: str | int | None = Field(
        default=None,
        description="Consider company id or name-like identifier.",
        examples=["Fivetran"],
    )
    slug: OptionalNonEmptyStr = Field(
        default=None,
        description="Consider company slug.",
        examples=["fivetran"],
    )
    name: OptionalNonEmptyStr = Field(
        default=None,
        description="Company display name.",
        examples=["Fivetran"],
    )
    domain: OptionalNonEmptyStr = Field(
        default=None,
        description="Company domain reported by Consider.",
        examples=["fivetran.com"],
    )
    description: str | None = Field(
        default=None,
        description="Consider company description text.",
        examples=["Automated data movement platform."],
    )
    markets: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Consider market or industry labels.",
        examples=[["Data", "Infrastructure"]],
    )
    office_locations: list[NonEmptyStr] = Field(
        default_factory=list,
        alias="officeLocations",
        description="Consider office location labels.",
        examples=[["Oakland, CA"]],
    )
    staff_count: NonNegativeInt | None = Field(
        default=None,
        alias="staffCount",
        description="Consider employee count estimate.",
        examples=[1200],
    )
    num_jobs: NonNegativeInt | None = Field(
        default=None,
        alias="numJobs",
        description="Consider open-job count hint.",
        examples=[131],
    )
    website: ConsiderWebsite | None = Field(
        default=None,
        description="Consider website object.",
        examples=[{"url": "https://fivetran.com/"}],
    )
    job_sources: list[ConsiderJobSource] = Field(
        default_factory=list,
        alias="jobSources",
        description="Consider provider route hints for this company.",
    )


class ConsiderCompaniesResponse(ProviderPayload):
    """Consider companies search response envelope."""

    companies: list[ConsiderCompany] = Field(
        default_factory=list,
        description="Consider company records for this page.",
    )
    total: NonNegativeInt | None = Field(
        default=None,
        description="Total companies reported by the response.",
        examples=[1],
    )
    meta: JsonDict = Field(
        default_factory=dict,
        description="Consider pagination metadata such as sequence cursors.",
        examples=[{"size": 100, "sequence": "abc"}],
    )
    version: JsonDict = Field(
        default_factory=dict,
        description="Consider version metadata for incremental source tracking.",
        examples=[{"server": {"git": "abc"}}],
    )


class GetroCompany(ProviderPayload):
    """Getro company search result."""

    id: str | int | None = Field(
        default=None,
        description="Getro company id.",
        examples=[202755],
    )
    object_id: str | int | None = Field(
        default=None,
        alias="objectID",
        description="Algolia-style object id used by some Getro payloads.",
        examples=["202755"],
    )
    slug: OptionalNonEmptyStr = Field(
        default=None,
        description="Getro company slug.",
        examples=["100ms-2"],
    )
    name: OptionalNonEmptyStr = Field(
        default=None,
        description="Company display name.",
        examples=["100ms"],
    )
    domain: OptionalNonEmptyStr = Field(
        default=None,
        description="Company domain reported by Getro.",
        examples=["100ms.live"],
    )
    description: str | None = Field(
        default=None,
        description="Getro company description text.",
        examples=["Live video infrastructure."],
    )
    visible_industry_tags: list[NonEmptyStr] = Field(
        default_factory=list,
        alias="visibleIndustryTags",
        description="Public industry labels reported by Getro.",
        examples=[["Software"]],
    )
    industry_tags: list[NonEmptyStr] = Field(
        default_factory=list,
        alias="industryTags",
        description="Fallback industry labels reported by Getro.",
        examples=[["Developer Tools"]],
    )
    locations: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Getro company location labels.",
        examples=[["San Francisco, CA, USA"]],
    )
    head_count: NonNegativeInt | None = Field(
        default=None,
        alias="headCount",
        description="Getro employee count estimate.",
        examples=[2],
    )
    active_jobs_count: NonNegativeInt | None = Field(
        default=None,
        alias="activeJobsCount",
        description="Getro open-job count hint.",
        examples=[10],
    )


class GetroCompaniesResults(ProviderPayload):
    """Getro nested companies search result object."""

    companies: list[GetroCompany] = Field(
        default_factory=list,
        description="Getro companies in the current result page.",
    )
    count: NonNegativeInt | None = Field(
        default=None,
        description="Total Getro companies matching the current search.",
        examples=[581],
    )


class GetroCompaniesResponse(ProviderPayload):
    """Getro companies search response envelope."""

    results: GetroCompaniesResults = Field(
        default_factory=GetroCompaniesResults,
        description="Getro result envelope containing companies and counts.",
    )


class YCombinatorCompanyHit(ProviderPayload):
    """Y Combinator Algolia company hit."""

    id: str | int | None = Field(
        default=None,
        description="YC company id.",
        examples=[1],
    )
    object_id: str | int | None = Field(
        default=None,
        alias="objectID",
        description="Algolia object id for the YC company hit.",
        examples=["1"],
    )
    slug: OptionalNonEmptyStr = Field(
        default=None,
        description="YC company slug.",
        examples=["acme-ai"],
    )
    name: OptionalNonEmptyStr = Field(
        default=None,
        description="YC company display name.",
        examples=["Acme AI"],
    )
    website: OptionalNonEmptyStr = Field(
        default=None,
        description="YC company website value, with or without scheme.",
        examples=["https://acme.example"],
    )
    long_description: str | None = Field(
        default=None,
        description="Long YC company description.",
        examples=["AI for testing and validation."],
    )
    one_liner: str | None = Field(
        default=None,
        description="Short YC company tagline.",
        examples=["AI for testing."],
    )
    team_size: NonNegativeInt | None = Field(
        default=None,
        description="YC team size estimate.",
        examples=[12],
    )
    batch: OptionalNonEmptyStr = Field(
        default=None,
        description="YC batch label.",
        examples=["S24"],
    )
    industries: list[NonEmptyStr] = Field(
        default_factory=list,
        description="YC industry labels.",
        examples=[["B2B", "Artificial Intelligence"]],
    )
    industry: OptionalNonEmptyStr = Field(
        default=None,
        description="YC fallback industry label.",
        examples=["B2B"],
    )
    subindustry: OptionalNonEmptyStr = Field(
        default=None,
        description="YC fallback subindustry label.",
        examples=["Developer Tools"],
    )
    all_locations: OptionalNonEmptyStr = Field(
        default=None,
        description="YC semicolon-delimited all-locations label.",
        examples=["San Francisco; Remote"],
    )
    regions: list[NonEmptyStr] = Field(
        default_factory=list,
        description="YC region labels when all_locations is not present.",
        examples=[["United States", "Remote"]],
    )


class YCombinatorAlgoliaResult(ProviderPayload):
    """Single Algolia result object returned inside YC `results`."""

    hits: list[YCombinatorCompanyHit] = Field(
        default_factory=list,
        description="YC company hits for the requested query page.",
    )
    facets: JsonDict = Field(
        default_factory=dict,
        description="YC Algolia facet counts, including batch counts.",
        examples=[{"batch": {"S24": 1}}],
    )


class YCombinatorAlgoliaResponse(ProviderPayload):
    """YC Algolia multi-query response envelope."""

    results: list[YCombinatorAlgoliaResult] = Field(
        default_factory=list,
        description="Algolia query results returned by the YC companies endpoint.",
    )


SourceRecordAdapter = TypeAdapter(SourceRecord)
BoardBatchAdapter = TypeAdapter(list[BoardRecord])
BoardProviderBatchAdapter = TypeAdapter(list[BoardProviderRecord])
JobBatchAdapter = TypeAdapter(list[JobRecord])


class SourceRow(SQLModel, table=True):
    __tablename__ = "sources"

    key: str = SQLField(
        primary_key=True, min_length=1, description="Stable local source key."
    )
    url: str = SQLField(
        description="Canonical source URL or synthetic manual source URI."
    )
    provider_id: str = SQLField(
        index=True, min_length=1, description="Source adapter identifier."
    )
    enabled: bool = SQLField(
        default=True,
        index=True,
        description="Whether default syncs include this source.",
    )
    version: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Provider version metadata.",
    )
    raw_metadata: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Source configuration and sync metadata.",
    )
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level record fields preserved across storage round trips.",
    )
    synced_at: datetime | None = SQLField(
        default=None, index=True, description="Last successful source sync timestamp."
    )


class BoardRow(SQLModel, table=True):
    __tablename__ = "boards"
    __table_args__ = (
        UniqueConstraint("source_key", "remote_id", name="uq_board_source_remote"),
    )

    key: str = SQLField(
        primary_key=True,
        index=True,
        min_length=1,
        description="Stable normalized board key.",
    )
    source_key: str = SQLField(
        index=True, min_length=1, description="Source key that emitted this board."
    )
    remote_id: str = SQLField(
        index=True, min_length=1, description="Provider-native board identifier."
    )
    remote_slug: str | None = SQLField(
        default=None, index=True, description="Provider-native slug."
    )
    name: str = SQLField(
        index=True, min_length=1, description="Company or board display name."
    )
    domain: str | None = SQLField(
        default=None, index=True, description="Normalized website domain."
    )
    website_url: str | None = SQLField(
        default=None, description="Canonical company website URL."
    )
    description: str | None = SQLField(
        default=None, description="Provider-supplied board description."
    )
    markets: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="Industry or market tags.",
    )
    locations: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="Office or hiring locations.",
    )
    staff_count: int | None = SQLField(
        default=None, ge=0, description="Employee or team-size estimate."
    )
    num_jobs_hint: int | None = SQLField(
        default=None, ge=0, description="Approximate number of open jobs."
    )
    raw_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unmodified upstream board payload.",
    )
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level record fields preserved across storage round trips.",
    )
    synced_at: datetime | None = SQLField(
        default=None, index=True, description="Last successful board sync timestamp."
    )


class BoardProviderRow(SQLModel, table=True):
    __tablename__ = "board_providers"
    __table_args__ = (
        UniqueConstraint(
            "source_key", "board_key", "provider_id", name="uq_board_provider"
        ),
    )

    id: str = SQLField(
        primary_key=True, min_length=1, description="Stable route primary key."
    )
    source_key: str = SQLField(
        index=True, min_length=1, description="Source key that reported this route."
    )
    board_key: str = SQLField(
        index=True, min_length=1, description="Board key this route belongs to."
    )
    provider_id: str = SQLField(
        index=True, min_length=1, description="Provider adapter identifier."
    )
    label: str | None = SQLField(
        default=None, description="Human-readable upstream route label."
    )
    support_level: str = SQLField(
        index=True, min_length=1, description="Normalized provider support level."
    )
    count_hint: int | None = SQLField(
        default=None, ge=0, description="Approximate provider-reported job count."
    )
    board_url: str | None = SQLField(default=None, description="Hosted job board URL.")
    token: str | None = SQLField(
        default=None, index=True, description="Provider-specific board token or slug."
    )
    host: str | None = SQLField(
        default=None, index=True, description="Multi-tenant provider host."
    )
    tenant: str | None = SQLField(
        default=None, index=True, description="Multi-tenant provider tenant."
    )
    site: str | None = SQLField(
        default=None, index=True, description="Multi-tenant provider site path."
    )
    last_status: str | None = SQLField(
        default=None, description="Last probe or sync status."
    )
    raw_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unmodified upstream route payload.",
    )
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level record fields preserved across storage round trips.",
    )
    detected_at: datetime | None = SQLField(
        default=None, index=True, description="Route discovery timestamp."
    )


class JobRow(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("board_key", "provider_id", "remote_id", name="uq_job_remote"),
    )

    id: str = SQLField(
        primary_key=True, min_length=1, description="Stable normalized job primary key."
    )
    board_key: str = SQLField(
        index=True, min_length=1, description="Board key this job belongs to."
    )
    provider_id: str = SQLField(
        index=True, min_length=1, description="Provider adapter identifier."
    )
    remote_id: str = SQLField(
        index=True, min_length=1, description="Provider-native job identifier."
    )
    title: str = SQLField(index=True, min_length=1, description="Public job title.")
    locations: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="Provider-reported job locations.",
    )
    department: str | None = SQLField(
        default=None, index=True, description="Provider-reported department."
    )
    team: str | None = SQLField(
        default=None, index=True, description="Provider-reported team or group."
    )
    workplace_type: str | None = SQLField(
        default=None,
        index=True,
        description="Workplace, commitment, or time-type label.",
    )
    company: str | None = SQLField(
        default=None, index=True, description="Board or company display name."
    )
    employment_type: str | None = SQLField(
        default=None, index=True, description="Employment or commitment type."
    )
    description: str | None = SQLField(
        default=None, description="Plain-text provider job description."
    )
    description_html: str | None = SQLField(
        default=None, description="HTML provider job description."
    )
    remote: str | None = SQLField(
        default=None,
        index=True,
        description="JSON Resume-compatible remote work level.",
    )
    compensation: JsonDict | None = SQLField(
        default=None,
        sa_column=Column(JSON),
        description="Provider compensation payload or normalized compensation details.",
    )
    salary: str | None = SQLField(
        default=None, description="JSON Resume-compatible salary display string."
    )
    salary_min: float | None = SQLField(
        default=None, description="Minimum deterministic salary or compensation value."
    )
    salary_max: float | None = SQLField(
        default=None, description="Maximum deterministic salary or compensation value."
    )
    salary_currency: str | None = SQLField(
        default=None, index=True, description="Salary or compensation currency code."
    )
    experience: str | None = SQLField(
        default=None, description="Experience label when deterministically available."
    )
    responsibilities: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="Deterministic responsibility bullets.",
    )
    qualifications: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="Deterministic qualification bullets.",
    )
    skills: list[JsonDict] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="JSON Resume-compatible skill objects.",
    )
    job_description: JsonDict | None = SQLField(
        default=None,
        sa_column=Column(JSON),
        description="JSON Resume-compatible job-description object.",
    )
    posting_url: str | None = SQLField(
        default=None, description="Canonical public posting URL."
    )
    apply_url: str | None = SQLField(
        default=None, description="Direct application URL."
    )
    posted_at: str | None = SQLField(
        default=None, index=True, description="Provider-native posted timestamp."
    )
    updated_at: str | None = SQLField(
        default=None, index=True, description="Provider-native updated timestamp."
    )
    status: str = SQLField(
        default="open",
        index=True,
        min_length=1,
        description="Normalized posting status.",
    )
    raw_listing: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unmodified upstream listing payload.",
    )
    raw_detail: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unmodified upstream detail payload.",
    )
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level record fields preserved across storage round trips.",
    )
    synced_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="Last successful job sync timestamp.",
    )


def _record_to_row_data(
    record: OpenOppsRecord,
    row_model: type[SQLModel],
    *,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    data = record.model_dump(mode="python", exclude=exclude or set())
    row_fields = set(row_model.model_fields)
    row_data = {key: value for key, value in data.items() if key in row_fields}
    extra_payload = {key: value for key, value in data.items() if key not in row_fields}
    if "extra_payload" in row_fields:
        row_data["extra_payload"] = {
            **row_data.get("extra_payload", {}),
            **extra_payload,
        }
    return row_data


def _row_to_record_data(row: SQLModel) -> dict[str, Any]:
    data = row.model_dump()
    extra_payload = data.pop("extra_payload", {}) or {}
    for key, value in data.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            data[key] = value.replace(tzinfo=timezone.utc)
    if isinstance(extra_payload, dict):
        return {**extra_payload, **data}
    return data


def source_to_row(record: SourceRecord) -> SourceRow:
    return SourceRow(**_record_to_row_data(record, SourceRow))


def board_to_row(record: BoardRecord) -> BoardRow:
    data = _record_to_row_data(record, BoardRow, exclude={"providers"})
    return BoardRow(**data)


def board_provider_to_row(record: BoardProviderRecord) -> BoardProviderRow:
    data = _record_to_row_data(record, BoardProviderRow)
    data["support_level"] = record.support_level.value
    return BoardProviderRow(**data)


def job_to_row(record: JobRecord) -> JobRow:
    return JobRow(**_record_to_row_data(record, JobRow))


def source_from_row(row: SourceRow) -> SourceRecord:
    return SourceRecord.model_validate(_row_to_record_data(row))


def board_provider_from_row(row: BoardProviderRow) -> BoardProviderRecord:
    data = _row_to_record_data(row)
    data["support_level"] = ProviderSupport(data["support_level"])
    return BoardProviderRecord.model_validate(data)


def board_from_row(
    row: BoardRow, providers: list[BoardProviderRecord] | None = None
) -> BoardRecord:
    data = _row_to_record_data(row)
    data["providers"] = providers or []
    return BoardRecord.model_validate(data)


def job_from_row(row: JobRow) -> JobRecord:
    return JobRecord.model_validate(_row_to_record_data(row))
