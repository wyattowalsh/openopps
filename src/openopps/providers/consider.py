from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse

from pydantic import Field, NonNegativeInt

from openopps.models import (
    JsonDict,
    NonEmptyStr,
    OptionalNonEmptyStr,
    ProviderPayload,
    validate_public_https_url,
)


class ConsiderRouteMode(StrEnum):
    COMPANY_JOBS = "company_jobs"
    PORTFOLIO = "portfolio"


@dataclass(frozen=True)
class ConsiderRoute:
    origin: str
    board_url: str
    token: str
    mode: ConsiderRouteMode

    @property
    def endpoint(self) -> str:
        resource = (
            "search-jobs"
            if self.mode == ConsiderRouteMode.COMPANY_JOBS
            else "search-companies"
        )
        return f"{self.origin}/api-boards/{resource}"

    @property
    def is_parent(self) -> bool:
        return self.mode == ConsiderRouteMode.PORTFOLIO


class ConsiderLabelValue(ProviderPayload):
    label: OptionalNonEmptyStr = None
    value: OptionalNonEmptyStr = None


class ConsiderSalary(ProviderPayload):
    min_value: float | None = Field(default=None, alias="minValue")
    max_value: float | None = Field(default=None, alias="maxValue")
    currency: ConsiderLabelValue | None = None
    period: ConsiderLabelValue | None = None


class ConsiderJob(ProviderPayload):
    job_id: NonEmptyStr = Field(alias="jobId")
    title: NonEmptyStr
    company_name: OptionalNonEmptyStr = Field(default=None, alias="companyName")
    company_slug: OptionalNonEmptyStr = Field(default=None, alias="companySlug")
    locations: list[NonEmptyStr] = Field(default_factory=list)
    departments: list[ConsiderLabelValue] = Field(default_factory=list)
    job_functions: list[ConsiderLabelValue] = Field(
        default_factory=list, alias="jobFunctions"
    )
    remote: bool | None = None
    hybrid: bool | None = None
    salary: ConsiderSalary | None = None
    timestamp: OptionalNonEmptyStr = Field(default=None, alias="timeStamp")
    url: OptionalNonEmptyStr = None
    apply_url: OptionalNonEmptyStr = Field(default=None, alias="applyUrl")


class ConsiderJobsResponse(ProviderPayload):
    jobs: list[ConsiderJob]
    total: NonNegativeInt | None = None
    meta: JsonDict = Field(default_factory=dict)
    version: JsonDict = Field(default_factory=dict)
    errors: list[Any] = Field(default_factory=list)


def parse_consider_route(
    url: str,
    *,
    portfolio_board: str | None = None,
) -> ConsiderRoute:
    """Classify a supported Consider URL without rewriting its board token."""

    validate_public_https_url(url)
    parsed = urlparse(url)
    if parsed.query or parsed.fragment or parsed.params or parsed.port is not None:
        raise ValueError("Consider board URLs must not include query, fragment, or port")
    host = (parsed.hostname or "").lower().rstrip(".")
    segments = _strict_path_segments(parsed.path)
    origin = f"https://{host}"

    if host == "consider.com":
        if len(segments) == 3 and segments[:2] == ["boards", "co"]:
            token = _decode_token(segments[2])
            return ConsiderRoute(
                origin=origin,
                board_url=f"{origin}/boards/co/{segments[2]}",
                token=token,
                mode=ConsiderRouteMode.COMPANY_JOBS,
            )
        if (
            len(segments) == 4
            and segments[:2] == ["boards", "vc"]
            and segments[3] == "companies"
        ):
            return ConsiderRoute(
                origin=origin,
                board_url=f"{origin}/boards/vc/{segments[2]}/companies",
                token=_decode_token(segments[2]),
                mode=ConsiderRouteMode.PORTFOLIO,
            )
        raise ValueError("Unsupported consider.com board URL shape")

    staging_suffix = ".board.staging.consider.com"
    if host.endswith(staging_suffix):
        token = host[: -len(staging_suffix)]
        if "." in token or segments != ["companies"]:
            raise ValueError("Unsupported Consider staging board URL shape")
        return ConsiderRoute(
            origin=origin,
            board_url=f"{origin}/companies",
            token=_validate_token(token),
            mode=ConsiderRouteMode.PORTFOLIO,
        )

    if portfolio_board is None:
        raise ValueError("Custom Consider hosts require an explicit portfolio board")
    return ConsiderRoute(
        origin=origin,
        board_url=url.rstrip("/"),
        token=_validate_token(portfolio_board),
        mode=ConsiderRouteMode.PORTFOLIO,
    )


def detect_consider_company_route(url: str) -> ConsiderRoute | None:
    try:
        route = parse_consider_route(url)
    except ValueError:
        return None
    return route if route.mode == ConsiderRouteMode.COMPANY_JOBS else None


def consider_search_payload(
    route: ConsiderRoute,
    *,
    page_size: int,
    sequence: str | None = None,
) -> JsonDict:
    meta: JsonDict = {"size": page_size}
    if sequence is not None:
        meta["sequence"] = sequence
    return {
        "query": {"parent": route.token},
        "meta": meta,
        "board": {"id": route.token, "isParent": route.is_parent},
    }


def consider_next_sequence(meta: JsonDict) -> str | None:
    sequence = meta.get("sequence")
    if sequence is None:
        return None
    if not isinstance(sequence, str) or not sequence.strip():
        raise ValueError("Consider pagination returned an invalid sequence cursor")
    return sequence


def raise_for_consider_errors(errors: object, *, endpoint: str) -> None:
    if errors:
        raise ValueError(f"Consider {endpoint} endpoint returned errors")


def validate_consider_empty_board_html(html: str) -> None:
    parser = _ConsiderTitleParser()
    parser.feed(html)
    titles = [*parser.open_graph_titles, *parser.document_titles]
    if not any(_is_specific_jobs_title(title) for title in titles):
        raise ValueError("Consider returned an unrecognized generic page for an empty board")


def safe_consider_job_url(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    try:
        validate_public_https_url(candidate)
    except ValueError:
        return None
    return candidate


def _strict_path_segments(path: str) -> list[str]:
    normalized = path[:-1] if path.endswith("/") and path != "/" else path
    if not normalized.startswith("/"):
        raise ValueError("Consider board URL path must be absolute")
    raw = normalized[1:]
    if not raw or any(not segment for segment in raw.split("/")):
        raise ValueError("Consider board URL path contains an empty segment")
    return raw.split("/")


def _decode_token(segment: str) -> str:
    if re.search(r"%(?![0-9a-fA-F]{2})", segment):
        raise ValueError("Consider board token contains an invalid escape")
    try:
        token = unquote_to_bytes(segment).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Consider board token is not valid UTF-8") from exc
    return _validate_token(token)


def _validate_token(token: str) -> str:
    if not token or token in {".", ".."}:
        raise ValueError("Consider board token must not be empty")
    if "/" in token or "\\" in token:
        raise ValueError("Consider board token must be one path segment")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in token):
        raise ValueError("Consider board token must not contain whitespace or controls")
    return token


def _is_specific_jobs_title(value: str) -> bool:
    normalized = " ".join(value.split()).casefold()
    return normalized.startswith("jobs at ") and normalized not in {
        "jobs at | consider",
        "jobs at consider",
    }


class _ConsiderTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.document_titles: list[str] = []
        self.open_graph_titles: list[str] = []
        self._title_parts: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() == "title":
            self._title_parts = []
            return
        if tag.casefold() != "meta":
            return
        values = {
            key.casefold(): value
            for key, value in attrs
            if value is not None
        }
        if values.get("property", "").casefold() == "og:title" and values.get(
            "content"
        ):
            self.open_graph_titles.append(values["content"])

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "title" or self._title_parts is None:
            return
        self.document_titles.append("".join(self._title_parts))
        self._title_parts = None
