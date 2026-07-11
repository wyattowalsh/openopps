from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from functools import lru_cache
import hashlib
from html import unescape
from ipaddress import ip_address
import json
import re
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    StringConstraints,
    TypeAdapter,
    UrlConstraints,
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
PostingKind = Literal["standard", "prospect", "unlisted"]
_PublicHttpsUrl = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["https"])]
_PublicHttpsUrlAdapter = TypeAdapter(_PublicHttpsUrl)


def host_matches(host: str | None, domain: str) -> bool:
    """Return whether a host equals or belongs to a domain, ignoring `www.`."""

    normalized_host = (host or "").strip().lower().removeprefix("www.")
    normalized_domain = domain.strip().lower().removeprefix("www.")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def validate_public_https_url(url: str, *, allow_manual: bool = False) -> str:
    """Validate a public HTTPS URL with Pydantic's URL parser and local safety rules."""

    if allow_manual and url.strip().lower().startswith("manual://"):
        return url
    parsed = _PublicHttpsUrlAdapter.validate_python(url)
    host = parsed.host
    if not host:
        raise ValueError("URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include credentials")
    validate_public_host(host)
    return url


def normalize_public_website_url(value: object) -> str | None:
    """Return a safe public HTTPS website URL or None for unusable upstream values."""

    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url:
        return None
    lower_url = url.lower()
    if lower_url.startswith(("mailto:", "tel:", "javascript:")):
        return None
    if lower_url.startswith("http://"):
        url = f"https://{url[7:]}"
    elif lower_url.startswith("//"):
        url = f"https:{url}"
    elif "://" not in url:
        url = f"https://{url}"
    try:
        return validate_public_https_url(url)
    except ValueError:
        return None


def validate_public_host(host: str) -> str:
    """Validate a public hostname and reject localhost or IP literals."""

    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        raise ValueError("Host must not be empty")
    if "://" in normalized or any(char in normalized for char in "/\\@:#?[]"):
        raise ValueError("Host must be a hostname, not a URL or path")
    if any(char.isspace() for char in normalized):
        raise ValueError("Host must not contain whitespace")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", normalized):
        raise ValueError("Host must be a valid hostname")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError("Host must not be localhost")
    try:
        ip_address(normalized.strip("[]"))
    except ValueError:
        return normalized
    raise ValueError("Host must not be an IP literal")


def validate_provider_host(host: str, domain: str) -> str:
    """Validate that a host is public and belongs to a provider-owned domain."""

    normalized = validate_public_host(host)
    if not host_matches(normalized, domain):
        raise ValueError(f"Host must be {domain} or a subdomain")
    return normalized


PublicHttpsUrlStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(validate_public_https_url),
]
OptionalPublicHttpsUrlStr = PublicHttpsUrlStr | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json_hash(value: object) -> str:
    """Return a stable SHA-256 hash for canonical JSON-compatible data."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def job_content_hash(record: JobRecord) -> str:
    """Hash normalized job content that should create a visible version on change."""

    return canonical_json_hash(
        {
            "title": record.title,
            "company": record.company,
            "locations": record.locations,
            "department": record.department,
            "team": record.team,
            "workplace_type": record.workplace_type,
            "employment_type": record.employment_type,
            "description": record.description,
            "description_html": record.description_html,
            "remote": record.remote,
            "compensation": record.compensation,
            "salary": record.salary,
            "salary_min": record.salary_min,
            "salary_max": record.salary_max,
            "salary_currency": record.salary_currency,
            "experience": record.experience,
            "responsibilities": record.responsibilities,
            "qualifications": record.qualifications,
            "skills": [
                skill.model_dump(mode="python", exclude_none=True)
                for skill in record.skills
            ],
            "job_description": _job_description_hash_payload(record),
            "posting_url": record.posting_url,
            "apply_url": record.apply_url,
            "posted_at": record.posted_at,
            "updated_at": record.updated_at,
        }
    )


def _job_description_hash_payload(record: JobRecord) -> dict[str, object] | None:
    if record.job_description is None:
        return None
    payload = record.job_description.model_dump(mode="python", exclude_none=True)
    meta = payload.get("meta")
    if isinstance(meta, dict):
        stable_meta = {
            key: value for key, value in meta.items() if key != "lastModified"
        }
        if stable_meta:
            payload["meta"] = stable_meta
        else:
            payload.pop("meta", None)
    return payload


def job_payload_hash(record: JobRecord) -> str:
    """Hash raw upstream payloads independently from lifecycle metadata."""

    return canonical_json_hash(
        {"raw_detail": record.raw_detail, "raw_listing": record.raw_listing}
    )


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
    SQLITE = "sqlite"


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

    address: str | None = Field(
        default=None,
        description="Free-form address or joined provider location labels.",
        examples=["San Francisco, CA\nRemote"],
    )
    postal_code: str | None = Field(
        default=None,
        alias="postalCode",
        description="Postal or ZIP code when a provider exposes structured location data.",
        examples=["94105"],
    )
    city: str | None = Field(
        default=None,
        description="City name when a provider exposes structured location data.",
        examples=["San Francisco"],
    )
    country_code: str | None = Field(
        default=None,
        alias="countryCode",
        description="ISO-like country code when a provider exposes structured location data.",
        examples=["US"],
    )
    region: str | None = Field(
        default=None,
        description="State, province, or region label when available.",
        examples=["CA"],
    )


class JobDescriptionSkill(OpenOppsRecord):
    """JSON Resume-compatible job skill shape."""

    name: OptionalNonEmptyStr = Field(
        default=None,
        description="Skill category or display name.",
        examples=["Python"],
    )
    level: OptionalNonEmptyStr = Field(
        default=None,
        description="Provider-reported or normalized skill proficiency level.",
        examples=["Senior"],
    )
    keywords: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Specific skill keywords grouped under this skill object.",
        examples=[["FastAPI", "SQL"]],
    )


class JobDescriptionRecord(OpenOppsRecord):
    """JSON Resume-compatible job description object.

    The upstream schema permits additional properties, so this model intentionally
    inherits OpenOppsRecord's extra-field behavior.
    """

    model_config = ConfigDict(serialize_by_alias=True)

    title: OptionalNonEmptyStr = Field(
        default=None,
        description="JSON Resume title derived from the normalized job title.",
        examples=["Senior Software Engineer"],
    )
    company: OptionalNonEmptyStr = Field(
        default=None,
        description="JSON Resume company name derived from the normalized board or posting.",
        examples=["Acme"],
    )
    type: OptionalNonEmptyStr = Field(
        default=None,
        description="JSON Resume job type derived from normalized employment type.",
        examples=["Full-time"],
    )
    date: OptionalNonEmptyStr = Field(
        default=None,
        description="JSON Resume-compatible posted date prefix, usually YYYY-MM-DD.",
        examples=["2026-05-16"],
    )
    description: str | None = Field(
        default=None,
        description="Plain-text job description copied from normalized provider content.",
        examples=["Build reliable systems for customers."],
    )
    location: JobDescriptionLocation | None = Field(
        default=None,
        description="JSON Resume-compatible location object built from normalized locations.",
    )
    remote: RemoteWorkLevel | None = Field(
        default=None,
        description="JSON Resume-compatible remote work level.",
        examples=["Full", "Hybrid", "None"],
    )
    salary: str | None = Field(
        default=None,
        description="JSON Resume-compatible salary display string.",
        examples=["USD 100000 - 160000"],
    )
    experience: str | None = Field(
        default=None,
        description="Experience label when provider data can determine one.",
        examples=["Senior"],
    )
    responsibilities: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Responsibility bullets extracted from structured provider sections.",
    )
    qualifications: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Qualification bullets extracted from structured provider sections.",
    )
    skills: list[JobDescriptionSkill] = Field(
        default_factory=list,
        description="JSON Resume-compatible skill objects derived from deterministic enrichment.",
    )
    meta: JsonDict = Field(
        default_factory=dict,
        description="OpenOpps audit metadata such as provider, board, remote id, canonical URL, and last modified timestamp.",
        examples=[{"provider": "greenhouse", "board": "acme", "remoteId": "12345"}],
    )


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


_SKILL_CATALOG: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = (
    (
        "Programming Languages",
        (
            ("Python", ("python",)),
            ("JavaScript", ("javascript", "java script", "js")),
            ("TypeScript", ("typescript", "type script", "ts")),
            ("Java", ("java",)),
            ("C++", ("c++", "cplusplus")),
            ("C#", ("c#", "csharp")),
            ("Ruby", ("ruby",)),
            ("PHP", ("php",)),
            ("Swift", ("swift",)),
            ("Kotlin", ("kotlin",)),
            ("Rust", ("rust",)),
            ("Scala", ("scala",)),
            ("Golang", ("golang",)),
            ("HTML", ("html",)),
            ("CSS", ("css",)),
        ),
    ),
    (
        "Frontend",
        (
            ("React", ("react", "reactjs", "react.js")),
            ("React Native", ("react native",)),
            ("Angular", ("angular",)),
            ("Vue", ("vue", "vuejs", "vue.js")),
            ("Svelte", ("svelte",)),
            ("Next.js", ("next.js", "nextjs")),
            ("Tailwind CSS", ("tailwind", "tailwind css")),
            ("Web Components", ("web components",)),
        ),
    ),
    (
        "Backend",
        (
            ("Node.js", ("node.js", "nodejs")),
            ("Django", ("django",)),
            ("Flask", ("flask",)),
            ("FastAPI", ("fastapi", "fast api")),
            ("Ruby on Rails", ("ruby on rails", "rails")),
            ("Spring", ("spring boot", "spring framework")),
            ("GraphQL", ("graphql",)),
            ("REST APIs", ("rest api", "rest apis", "restful api", "restful apis")),
            ("Microservices", ("microservices", "micro-services")),
        ),
    ),
    (
        "Data and AI",
        (
            ("Machine Learning", ("machine learning",)),
            ("Deep Learning", ("deep learning",)),
            ("Generative AI", ("generative ai", "genai", "gen ai")),
            ("LLM", ("llm", "large language model", "large language models")),
            ("NLP", ("nlp", "natural language processing")),
            ("Computer Vision", ("computer vision",)),
            ("PyTorch", ("pytorch",)),
            ("TensorFlow", ("tensorflow",)),
            ("scikit-learn", ("scikit-learn", "sklearn")),
            ("Pandas", ("pandas",)),
            ("NumPy", ("numpy",)),
            ("Spark", ("apache spark", "spark")),
            ("Airflow", ("airflow", "apache airflow")),
            ("dbt", ("dbt",)),
            ("Analytics", ("analytics",)),
            ("Experimentation", ("experimentation", "a/b testing", "ab testing")),
        ),
    ),
    (
        "Cloud and Infrastructure",
        (
            ("AWS", ("aws", "amazon web services")),
            ("Azure", ("azure", "microsoft azure")),
            ("Google Cloud", ("google cloud", "gcp")),
            ("Kubernetes", ("kubernetes", "k8s")),
            ("Docker", ("docker",)),
            ("Terraform", ("terraform",)),
            ("Helm", ("helm",)),
            ("Linux", ("linux",)),
            ("DevOps", ("devops",)),
            ("SRE", ("sre", "site reliability")),
            ("CI/CD", ("ci/cd", "cicd", "continuous integration")),
            ("GitHub Actions", ("github actions",)),
            ("Jenkins", ("jenkins",)),
            ("Observability", ("observability",)),
            ("Prometheus", ("prometheus",)),
            ("Grafana", ("grafana",)),
        ),
    ),
    (
        "Databases",
        (
            ("SQL", ("sql",)),
            ("PostgreSQL", ("postgresql", "postgres")),
            ("MySQL", ("mysql",)),
            ("SQLite", ("sqlite",)),
            ("MongoDB", ("mongodb", "mongo")),
            ("Redis", ("redis",)),
            ("Elasticsearch", ("elasticsearch", "elastic search")),
            ("Kafka", ("kafka", "apache kafka")),
            ("DynamoDB", ("dynamodb", "dynamo db")),
            ("Snowflake", ("snowflake",)),
            ("BigQuery", ("bigquery", "big query")),
            ("Databricks", ("databricks",)),
        ),
    ),
    (
        "Security and Compliance",
        (
            ("Security", ("security", "cybersecurity", "cyber security")),
            ("SOC 2", ("soc 2", "soc2")),
            ("HIPAA", ("hipaa",)),
            ("GDPR", ("gdpr",)),
            ("IAM", ("iam", "identity and access management")),
            ("OAuth", ("oauth", "oauth2")),
            ("SAML", ("saml",)),
            ("Incident Response", ("incident response",)),
            ("Vulnerability Management", ("vulnerability management",)),
            ("Penetration Testing", ("penetration testing", "pentesting")),
        ),
    ),
    (
        "Product and Design",
        (
            ("Product Management", ("product management", "product manager")),
            ("Roadmapping", ("roadmap", "roadmapping")),
            ("User Research", ("user research", "ux research")),
            ("UX", ("ux", "user experience")),
            ("UI", ("ui", "user interface")),
            ("Figma", ("figma",)),
            ("Design Systems", ("design system", "design systems")),
            ("Prototyping", ("prototype", "prototyping")),
            ("Growth", ("growth",)),
        ),
    ),
    (
        "GTM and Customer",
        (
            ("Sales", ("sales",)),
            ("Marketing", ("marketing",)),
            ("Account Executive", ("account executive",)),
            ("Customer Success", ("customer success",)),
            ("CRM", ("crm",)),
            ("Salesforce", ("salesforce",)),
            ("HubSpot", ("hubspot",)),
            ("Demand Generation", ("demand generation",)),
            ("Partnerships", ("partnerships",)),
            ("Support", ("customer support", "technical support")),
        ),
    ),
    (
        "Operations and Finance",
        (
            ("Finance", ("finance",)),
            ("Accounting", ("accounting",)),
            ("FP&A", ("fp&a", "fpa")),
            ("Payroll", ("payroll",)),
            ("Recruiting", ("recruiting", "talent acquisition")),
            ("People Operations", ("people operations", "people ops")),
            ("Legal", ("legal",)),
            ("Procurement", ("procurement",)),
            ("Supply Chain", ("supply chain",)),
            ("RevOps", ("revops", "revenue operations")),
        ),
    ),
    (
        "Healthcare and Science",
        (
            ("Clinical", ("clinical",)),
            ("Healthcare", ("healthcare", "health care")),
            ("Biotech", ("biotech", "biotechnology")),
            ("Pharma", ("pharma", "pharmaceutical")),
            ("FDA", ("fda",)),
            ("Laboratory", ("laboratory", "lab operations")),
            ("Genomics", ("genomics",)),
        ),
    ),
)
_SKILL_TEXT_VALUE_LIMIT = 4000
_SKILL_LEVEL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Executive", ("chief", "c-level", "c suite", "vp", "vice president")),
    ("Principal", ("principal", "staff")),
    ("Senior", ("senior", "sr", "lead")),
    ("Manager", ("manager", "director", "head of")),
    ("Junior", ("junior", "jr", "entry level", "intern", "associate")),
)


def extract_job_skills(record: JobRecord) -> list[JobDescriptionSkill]:
    """Derive deterministic skill groups from normalized public job text."""

    description_text = record.description or record.description_html
    text = _normalized_skill_text(
        [
            record.title,
            record.department,
            record.team,
            record.employment_type,
            description_text,
            *record.responsibilities,
            *record.qualifications,
        ]
    )
    if not text.strip():
        return []

    level = _skill_level(record)
    text_tokens = frozenset(text.split())
    skills: list[JobDescriptionSkill] = []
    for group_name, keywords in _compiled_skill_catalog():
        matched = [
            keyword
            for keyword, single_tokens, phrases in keywords
            if _has_compiled_skill_alias(text, text_tokens, single_tokens, phrases)
        ]
        if matched:
            skills.append(
                JobDescriptionSkill(
                    name=group_name,
                    level=level,
                    keywords=matched[:12],
                )
            )
    return skills


def _normalized_skill_text(values: list[object]) -> str:
    raw = " ".join(str(value)[:_SKILL_TEXT_VALUE_LIMIT] for value in values if value)
    raw = strip_html(raw) or raw
    normalized = re.sub(r"[^a-z0-9+#]+", " ", raw.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return f" {normalized} "


@lru_cache(maxsize=1)
def _compiled_skill_catalog() -> tuple[
    tuple[str, tuple[tuple[str, frozenset[str], tuple[str, ...]], ...]], ...
]:
    return tuple(
        (
            group_name,
            tuple(
                (
                    keyword,
                    *_compile_skill_aliases(aliases),
                )
                for keyword, aliases in keywords
            ),
        )
        for group_name, keywords in _SKILL_CATALOG
    )


@lru_cache(maxsize=1)
def _compiled_level_aliases() -> tuple[
    tuple[str, frozenset[str], tuple[str, ...]], ...
]:
    return tuple(
        (label, *_compile_skill_aliases(aliases))
        for label, aliases in _SKILL_LEVEL_ALIASES
    )


@lru_cache(maxsize=256)
def _compile_skill_aliases(
    aliases: tuple[str, ...],
) -> tuple[frozenset[str], tuple[str, ...]]:
    normalized_aliases = tuple(
        sorted(
            {
                normalized_alias
                for alias in aliases
                if (normalized_alias := _normalized_skill_text([alias]).strip())
            },
            key=len,
            reverse=True,
        )
    )
    if not normalized_aliases:
        return frozenset(), ()
    single_tokens = frozenset(
        normalized_alias
        for normalized_alias in normalized_aliases
        if " " not in normalized_alias
    )
    phrases = tuple(
        normalized_alias
        for normalized_alias in normalized_aliases
        if " " in normalized_alias
    )
    return single_tokens, phrases


def _has_compiled_skill_alias(
    normalized_text: str,
    text_tokens: frozenset[str],
    single_tokens: frozenset[str],
    phrases: tuple[str, ...],
) -> bool:
    return (not text_tokens.isdisjoint(single_tokens)) or any(
        phrase in normalized_text for phrase in phrases
    )


def _has_skill_alias(normalized_text: str, alias: str) -> bool:
    single_tokens, phrases = _compile_skill_aliases((alias,))
    return _has_compiled_skill_alias(
        normalized_text,
        frozenset(normalized_text.split()),
        single_tokens,
        phrases,
    )


def _skill_level(record: JobRecord) -> str | None:
    return derive_seniority(record) or record.experience


def derive_seniority_from_fields(
    title: str | None, experience: str | None
) -> str | None:
    """Derive a normalized seniority label from title and experience text."""

    text = _normalized_skill_text([experience, title])
    text_tokens = frozenset(text.split())
    for label, single_tokens, phrases in _compiled_level_aliases():
        if _has_compiled_skill_alias(text, text_tokens, single_tokens, phrases):
            return label
    return None


def derive_seniority(record: JobRecord) -> str | None:
    """Derive a normalized seniority label from title and experience text."""

    return derive_seniority_from_fields(record.title, record.experience)


class SourceRecord(OpenOppsRecord):
    """A configured source of opportunity-board companies."""

    @model_validator(mode="after")
    def _reject_enablement_extras(self) -> Self:
        extra = self.model_extra or {}
        forbidden = set(extra) & {"disabled", "enabled"}
        extra_payload = extra.get("extra_payload")
        if isinstance(extra_payload, dict):
            forbidden.update(set(extra_payload) & {"disabled", "enabled"})
        forbidden = sorted(forbidden)
        if forbidden:
            joined = ", ".join(forbidden)
            raise ValueError(
                f"Source records do not support enablement fields: {joined}. "
                "Remove excluded sources instead of storing them as disabled."
            )
        return self

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
        description=(
            "detect means provider metadata only; jobs means public job fetching is "
            "available; unsupported means unknown or explicitly unusable."
        ),
        examples=[ProviderSupport.JOBS],
    )
    count_hint: NonNegativeInt | None = Field(
        default=None,
        description="Provider-reported approximate job count, when available.",
        examples=[42],
    )
    board_url: OptionalPublicHttpsUrlStr = Field(
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
    source_keys: list[NonEmptyStr] = Field(
        default_factory=list,
        description=(
            "All source keys that currently contain this company domain in the local ledger."
        ),
        examples=[["a16z", "yc"]],
    )
    source_board_keys: dict[NonEmptyStr, NonEmptyStr] = Field(
        default_factory=dict,
        description="Source-specific board keys merged into this canonical board record.",
        examples=[{"a16z": "a16z:acme", "yc": "yc:acme-ai"}],
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
    website_url: OptionalPublicHttpsUrlStr = Field(
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
    posting_url: OptionalPublicHttpsUrlStr = Field(
        default=None,
        description="Canonical public posting URL.",
        examples=["https://boards.greenhouse.io/acme/jobs/12345"],
    )
    apply_url: OptionalPublicHttpsUrlStr = Field(
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
    version: NonNegativeInt | None = Field(
        default=None,
        description="Current or historical normalized content version number.",
        examples=[2],
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of normalized user-visible job content.",
    )
    payload_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the canonical raw listing/detail payload pair.",
    )
    first_seen_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp when this job identity or version was first observed.",
    )
    last_seen_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp when this job identity or version was last observed.",
    )
    closed_at: AwareDatetime | None = Field(
        default=None,
        description="UTC timestamp when the job disappeared from a successful route sync.",
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
    posting_kind: PostingKind | None = Field(
        default=None,
        description="Normalized posting visibility class such as standard, prospect, or unlisted.",
        examples=["standard", "prospect"],
    )
    seniority: OptionalNonEmptyStr = Field(
        default=None,
        description="Deterministic seniority label derived from title and experience text.",
        examples=["Senior", "Principal"],
    )
    provider_extras: JsonDict | None = Field(
        default=None,
        description="Provider-promoted surplus fields not mapped to first-class columns.",
        examples=[{"greenhouse": {"requisitionId": "50", "language": "en"}}],
    )
    synced_at: AwareDatetime = Field(
        default_factory=utc_now,
        description="UTC timestamp when the job was last fetched.",
        examples=["2026-05-16T12:34:56Z"],
    )

    @model_validator(mode="after")
    def _populate_enriched_fields(self) -> Self:
        if not self.skills:
            if self.job_description and self.job_description.skills:
                object.__setattr__(self, "skills", list(self.job_description.skills))
            else:
                object.__setattr__(self, "skills", extract_job_skills(self))
        if self.job_description is None:
            object.__setattr__(self, "job_description", build_job_description(self))
        if not self.seniority:
            object.__setattr__(self, "seniority", derive_seniority(self))
        if not self.posting_kind:
            object.__setattr__(self, "posting_kind", "standard")
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
    metadata: list[JsonDict] = Field(
        default_factory=list,
        description="Greenhouse custom metadata name/value pairs from the list endpoint.",
        examples=[[{"name": "level", "value": "staff"}]],
    )
    requisition_id: str | int | None = Field(
        default=None,
        description="Greenhouse requisition identifier when exposed on the board feed.",
        examples=["50"],
    )
    language: OptionalNonEmptyStr = Field(
        default=None,
        description="Greenhouse posting language code when exposed on the board feed.",
        examples=["en"],
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

    @field_validator("text", mode="before")
    @classmethod
    def _blank_heading_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


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

    @field_validator(
        "website",
        "batch",
        "industry",
        "subindustry",
        "all_locations",
        mode="before",
    )
    @classmethod
    def _empty_strings_are_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


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
        foreign_key="sources.key",
        index=True,
        min_length=1,
        description="Source key that emitted this board.",
    )
    source_keys: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON),
        description="All sources that currently contain this board domain.",
    )
    source_board_keys: dict[str, str] = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Source-specific emitted board keys merged into this board.",
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
        foreign_key="sources.key",
        index=True,
        min_length=1,
        description="Source key that reported this route.",
    )
    board_key: str = SQLField(
        foreign_key="boards.key",
        index=True,
        min_length=1,
        description="Board key this route belongs to.",
    )
    provider_id: str = SQLField(
        index=True, min_length=1, description="Provider adapter identifier."
    )
    label: str | None = SQLField(
        default=None, description="Human-readable upstream route label."
    )
    support_level: str = SQLField(
        index=True,
        min_length=1,
        description=(
            "detect means provider metadata only; jobs means public job fetching is "
            "available; unsupported means unknown or explicitly unusable."
        ),
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
        primary_key=True, min_length=1, description="Stable normalized job identity."
    )
    board_key: str = SQLField(
        foreign_key="boards.key",
        index=True,
        min_length=1,
        description="Board key this job belongs to.",
    )
    provider_id: str = SQLField(
        index=True, min_length=1, description="Provider adapter identifier."
    )
    remote_id: str = SQLField(
        index=True, min_length=1, description="Provider-native job identifier."
    )
    status: str = SQLField(
        default="open",
        index=True,
        min_length=1,
        description="Current lifecycle status for the stable job identity.",
    )
    current_version_id: str | None = SQLField(
        default=None,
        foreign_key="job_versions.id",
        index=True,
        description="Current normalized job version id.",
    )
    current_content_hash: str | None = SQLField(
        default=None, index=True, description="Current normalized content hash."
    )
    current_payload_hash: str | None = SQLField(
        default=None, index=True, description="Current raw payload-pair hash."
    )
    first_seen_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="First successful route sync that observed this job identity.",
    )
    last_seen_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="Most recent successful route sync that observed this job identity.",
    )
    closed_at: datetime | None = SQLField(
        default=None,
        index=True,
        description="Route sync timestamp when this job disappeared while open.",
    )
    synced_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="Last successful lifecycle update timestamp.",
    )
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level identity fields preserved across storage round trips.",
    )


class JobVersionRow(SQLModel, table=True):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_job_version_content"),
        UniqueConstraint("job_id", "version", name="uq_job_version_number"),
    )

    id: str = SQLField(primary_key=True, min_length=1, description="Job version id.")
    job_id: str = SQLField(
        foreign_key="jobs.id", index=True, min_length=1, description="Stable job id."
    )
    version: int = SQLField(index=True, ge=1, description="Monotonic version number.")
    content_hash: str = SQLField(
        index=True, min_length=1, description="Normalized user-visible content hash."
    )
    payload_hash: str = SQLField(
        index=True,
        min_length=1,
        description="Raw payload-pair hash observed for version.",
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
    extra_payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unknown top-level version fields preserved across storage round trips.",
    )
    first_seen_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="First sync timestamp that observed this normalized content.",
    )
    last_seen_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="Most recent sync timestamp that observed this normalized content.",
    )

    created_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="UTC timestamp when this version row was created.",
    )


class JobVersionLocationRow(SQLModel, table=True):
    __tablename__ = "job_version_locations"
    __table_args__ = (
        UniqueConstraint(
            "job_version_id", "ordinal", "label", name="uq_job_version_location"
        ),
    )

    id: str = SQLField(
        primary_key=True,
        min_length=1,
        description="Stable job-version location row id.",
    )
    job_version_id: str = SQLField(
        foreign_key="job_versions.id",
        index=True,
        min_length=1,
        description="Job version this location belongs to.",
    )
    ordinal: int = SQLField(
        index=True,
        ge=0,
        description="Zero-based location order within the job version.",
    )
    label: str = SQLField(index=True, min_length=1, description="Location label text.")


class JobVersionSkillRow(SQLModel, table=True):
    __tablename__ = "job_version_skills"
    __table_args__ = (
        UniqueConstraint("job_version_id", "ordinal", name="uq_job_version_skill"),
    )

    id: str = SQLField(
        primary_key=True, min_length=1, description="Stable job-version skill row id."
    )
    job_version_id: str = SQLField(
        foreign_key="job_versions.id",
        index=True,
        min_length=1,
        description="Job version this skill group belongs to.",
    )
    ordinal: int = SQLField(
        index=True, ge=0, description="Zero-based skill order within the job version."
    )
    name: str | None = SQLField(
        default=None, index=True, description="Skill group display name."
    )
    level: str | None = SQLField(
        default=None, index=True, description="Skill group proficiency or level label."
    )


class JobVersionSkillKeywordRow(SQLModel, table=True):
    __tablename__ = "job_version_skill_keywords"
    __table_args__ = (
        UniqueConstraint("skill_id", "ordinal", "keyword", name="uq_job_skill_keyword"),
    )

    id: str = SQLField(
        primary_key=True,
        min_length=1,
        description="Stable job-version skill keyword row id.",
    )
    skill_id: str = SQLField(
        foreign_key="job_version_skills.id",
        index=True,
        min_length=1,
        description="Skill group this keyword belongs to.",
    )
    ordinal: int = SQLField(
        index=True, ge=0, description="Zero-based keyword order within the skill group."
    )
    keyword: str = SQLField(index=True, min_length=1, description="Skill keyword text.")


class JobVersionBulletRow(SQLModel, table=True):
    __tablename__ = "job_version_bullets"
    __table_args__ = (
        UniqueConstraint(
            "job_version_id", "kind", "ordinal", "text", name="uq_job_version_bullet"
        ),
    )

    id: str = SQLField(
        primary_key=True, min_length=1, description="Stable job-version bullet row id."
    )
    job_version_id: str = SQLField(
        foreign_key="job_versions.id",
        index=True,
        min_length=1,
        description="Job version this bullet belongs to.",
    )
    kind: str = SQLField(
        index=True,
        min_length=1,
        description="Bullet category, such as responsibility or qualification.",
    )
    ordinal: int = SQLField(
        index=True, ge=0, description="Zero-based bullet order within its category."
    )
    text: str = SQLField(min_length=1, description="Bullet text.")


class JobPayloadSnapshotRow(SQLModel, table=True):
    __tablename__ = "job_payload_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "payload_kind", "payload_hash", name="uq_job_payload_snapshot"
        ),
    )

    id: str = SQLField(
        primary_key=True,
        min_length=1,
        description="Stable raw payload snapshot row id.",
    )
    job_id: str = SQLField(
        foreign_key="jobs.id",
        index=True,
        min_length=1,
        description="Stable job identity this raw payload belongs to.",
    )
    payload_kind: str = SQLField(
        index=True,
        min_length=1,
        description="Raw payload source kind, such as listing or detail.",
    )
    payload_hash: str = SQLField(
        index=True,
        min_length=1,
        description="Canonical hash of the unmodified raw payload.",
    )
    payload: JsonDict = SQLField(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Unmodified upstream payload for audit and replay.",
    )
    observed_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="UTC sync timestamp when this raw payload was observed.",
    )


class JobSyncRunRow(SQLModel, table=True):
    __tablename__ = "job_sync_runs"

    id: str = SQLField(
        primary_key=True,
        min_length=1,
        description="Stable provider route sync run id.",
    )
    board_key: str = SQLField(
        foreign_key="boards.key",
        index=True,
        min_length=1,
        description="Board key synced during this provider route run.",
    )
    provider_id: str = SQLField(
        index=True,
        min_length=1,
        description="Provider route synced during this run.",
    )
    synced_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="UTC timestamp for this provider route sync attempt.",
    )
    success: bool = SQLField(
        default=True, index=True, description="Whether the route sync completed."
    )
    error: str | None = SQLField(
        default=None, description="Error message captured for failed route syncs."
    )
    job_count: int = SQLField(
        default=0, ge=0, description="Total jobs observed in the route sync."
    )
    new_count: int = SQLField(
        default=0, ge=0, description="Jobs newly created by the route sync."
    )
    unchanged_count: int = SQLField(
        default=0, ge=0, description="Jobs observed without content changes."
    )
    changed_count: int = SQLField(
        default=0, ge=0, description="Jobs with a new normalized content version."
    )
    reopened_count: int = SQLField(
        default=0,
        ge=0,
        description="Previously closed jobs reopened by the route sync.",
    )
    closed_count: int = SQLField(
        default=0, ge=0, description="Previously open jobs closed by the route sync."
    )


class JobSyncObservationRow(SQLModel, table=True):
    __tablename__ = "job_sync_observations"

    id: str = SQLField(
        primary_key=True, min_length=1, description="Stable sync observation row id."
    )
    sync_run_id: str = SQLField(
        foreign_key="job_sync_runs.id",
        index=True,
        min_length=1,
        description="Route sync run that recorded this observation.",
    )
    job_id: str = SQLField(
        foreign_key="jobs.id",
        index=True,
        min_length=1,
        description="Stable job identity observed during sync.",
    )
    job_version_id: str | None = SQLField(
        default=None,
        foreign_key="job_versions.id",
        index=True,
        description="Normalized job version associated with this observation.",
    )
    observation_kind: str = SQLField(
        index=True,
        min_length=1,
        description="Observation category, such as new, unchanged, changed, reopened, or closed.",
    )
    content_hash: str | None = SQLField(
        default=None,
        index=True,
        description="Normalized content hash observed during sync.",
    )
    payload_hash: str | None = SQLField(
        default=None,
        index=True,
        description="Raw payload-pair hash observed during sync.",
    )
    observed_at: datetime = SQLField(
        default_factory=utc_now,
        index=True,
        description="UTC timestamp when the observation was recorded.",
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
