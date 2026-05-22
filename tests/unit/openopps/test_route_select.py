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
