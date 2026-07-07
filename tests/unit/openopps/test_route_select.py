from __future__ import annotations

from openopps.models import BoardProviderRecord, BoardRecord, ProviderSupport
from openopps.route_select import (
    dedupe_routes,
    normalize_provider_filter,
    route_ready,
    route_request_key,
)


def board_record(**updates: object) -> BoardRecord:
    data: dict[str, object] = {
        "key": "manual:acme",
        "source_key": "manual",
        "remote_id": "Acme",
        "remote_slug": "acme",
        "name": "Acme",
        "domain": "acme.com",
        "website_url": "https://www.acme.com/careers",
    }
    data.update(updates)
    return BoardRecord.model_validate(data)


def route_record(**updates: object) -> BoardProviderRecord:
    data: dict[str, object] = {
        "id": "manual:acme:greenhouse",
        "source_key": "manual",
        "board_key": "manual:acme",
        "provider_id": "greenhouse",
        "support_level": ProviderSupport.JOBS,
    }
    data.update(updates)
    return BoardProviderRecord.model_validate(data)


def test_normalize_provider_filter_treats_any_all_as_unscoped():
    assert normalize_provider_filter(None) is None
    assert normalize_provider_filter("any") is None
    assert normalize_provider_filter(" ALL ") is None
    assert normalize_provider_filter("*") is None
    assert normalize_provider_filter("greenhouse") == "greenhouse"


def test_route_ready_accepts_provider_specific_metadata():
    assert route_ready(route_record(token="acme"))
    assert route_ready(route_record(board_url="https://boards.greenhouse.io/acme"))
    assert not route_ready(route_record())
    assert route_ready(
        route_record(
            provider_id="workday",
            host="wd1.myworkdayjobs.com",
            tenant="acme",
            site="External",
        )
    )


def test_route_ready_rejects_provider_host_spoofing():
    assert not route_ready(
        route_record(
            provider_id="workday",
            host="evil.example/acme.myworkdayjobs.com",
            tenant="acme",
            site="External",
        )
    )
    assert not route_ready(
        route_record(
            provider_id="bamboohr",
            host="evil.example/acme.bamboohr.com",
            tenant="acme",
        )
    )
    assert not route_ready(
        route_record(
            provider_id="teamtailor",
            host="evil.example/acme.teamtailor.com",
        )
    )
    assert not route_ready(
        route_record(provider_id="wpjobmanager", host="example.com/jobs")
    )


def test_route_request_key_prefers_provider_tokens_and_workday_cxs_fields():
    board = board_record()

    assert route_request_key(board, route_record(token="Acme")) == (
        "greenhouse:token:acme"
    )
    assert route_request_key(
        board,
        route_record(provider_id="lever", board_url="https://jobs.lever.co/Acme/123"),
    ) == ("lever:token:acme")
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="workday",
                host="wd1.myworkdayjobs.com",
                tenant="Acme",
                site="External",
            ),
        )
        == "workday:cxs:wd1.myworkdayjobs.com:acme:external"
    )


def test_route_request_key_extracts_known_provider_api_url_tokens():
    board = board_record()

    assert (
        route_request_key(
            board,
            route_record(
                provider_id="greenhouse",
                board_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs",
            ),
        )
        == "greenhouse:token:acme"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="lever",
                board_url="https://api.lever.co/v0/postings/acme?mode=json",
            ),
        )
        == "lever:token:acme"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="workable",
                board_url="https://apply.workable.com/api/v3/accounts/acme/jobs",
            ),
        )
        == "workable:token:acme"
    )


def test_route_request_key_uses_provider_hosts_and_origins():
    board = board_record()

    assert (
        route_request_key(
            board,
            route_record(
                provider_id="teamtailor",
                board_url="https://acme.teamtailor.com/jobs",
            ),
        )
        == "teamtailor:host:acme.teamtailor.com"
    )
    assert route_request_key(
        board,
        route_record(
            provider_id="teamtailor",
            host="evil.example/acme.teamtailor.com",
        ),
    ) == "teamtailor:domain:acme.com"
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="teamtailor",
                board_url="https://bravo.teamtailor.com/jobs",
            ),
        )
        == "teamtailor:host:bravo.teamtailor.com"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="bamboohr",
                board_url="https://acme.bamboohr.com/careers",
            ),
        )
        == "bamboohr:host:acme.bamboohr.com"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="bamboohr",
                board_url="https://bravo.bamboohr.com/careers",
            ),
        )
        == "bamboohr:host:bravo.bamboohr.com"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="rippling",
                board_url="https://ats.rippling.com/api/v2/board/acme/jobs",
            ),
        )
        == "rippling:host:ats.rippling.com:acme"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="rippling",
                board_url="https://ats.rippling.com/bravo/jobs",
            ),
        )
        == "rippling:host:ats.rippling.com:bravo"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="wpjobmanager",
                board_url="https://jobs.example.com/wp-json/wp/v2/job-listings",
            ),
        )
        == "wpjobmanager:rest:https://jobs.example.com/wp-json/wp/v2/job-listings"
    )
    assert (
        route_request_key(
            board,
            route_record(
                provider_id="wpjobmanager",
                board_url="https://careers.example.com/jm-ajax/get_listings/",
            ),
        )
        == "wpjobmanager:ajax:https://careers.example.com/jm-ajax/get_listings"
    )


def test_route_request_key_falls_back_to_url_domain_and_board_slug():
    board = board_record()

    assert (
        route_request_key(
            board,
            route_record(
                provider_id="workday", board_url="https://www.example.com/jobs/"
            ),
        )
        == "workday:url:example.com/jobs"
    )
    assert route_request_key(board, route_record(provider_id="custom")) == (
        "custom:domain:acme.com"
    )
    assert (
        route_request_key(
            board_record(domain=None, website_url=None),
            route_record(provider_id="custom"),
        )
        == "custom:board:acme"
    )


def test_dedupe_routes_preserves_missing_boards_and_splits_duplicate_requests():
    board = board_record()
    primary = route_record(id="primary", token="acme")
    duplicate = route_record(id="duplicate", token="ACME")
    missing_board = route_record(id="missing", board_key="missing", token="acme")

    unique, duplicates = dedupe_routes(
        [primary, duplicate, missing_board], {board.key: board}
    )

    assert unique == [primary, missing_board]
    assert duplicates == [duplicate]


def test_dedupe_routes_preserves_same_origin_wpjobmanager_rest_and_ajax_routes():
    board = board_record()
    rest = route_record(
        id="rest",
        provider_id="wpjobmanager",
        board_url="https://jobs.example.com/wp-json/wp/v2/job-listings",
    )
    ajax = route_record(
        id="ajax",
        provider_id="wpjobmanager",
        board_url="https://jobs.example.com/jm-ajax/get_listings/",
    )
    duplicate_rest = route_record(
        id="duplicate-rest",
        provider_id="wpjobmanager",
        board_url="https://jobs.example.com/wp-json/wp/v2/job-listings?per_page=100",
    )

    unique, duplicates = dedupe_routes(
        [rest, ajax, duplicate_rest], {board.key: board}
    )

    assert unique == [rest, ajax]
    assert duplicates == [duplicate_rest]
