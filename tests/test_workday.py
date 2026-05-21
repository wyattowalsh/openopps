import pytest

from openopps.providers.boards.workday import parse_workday_board_url


def test_parse_workday_standard_url():
    route = parse_workday_board_url(
        "https://pwc.wd3.myworkdayjobs.com/US_Experienced_Careers/job/FL-Tampa/NGA-AI_712369WD"
    )

    assert route.host == "pwc.wd3.myworkdayjobs.com"
    assert route.tenant == "pwc"
    assert route.site == "US_Experienced_Careers"


def test_parse_workday_localized_url():
    route = parse_workday_board_url(
        "https://foo.wd1.myworkdayjobs.com/en-US/External_Careers/job/x/y"
    )

    assert route.tenant == "foo"
    assert route.site == "External_Careers"


def test_parse_workday_requires_site():
    with pytest.raises(ValueError):
        parse_workday_board_url("https://foo.wd1.myworkdayjobs.com")
