from __future__ import annotations

from hypothesis import assume, given, settings, strategies as st

from openopps.utils import slugify, source_board_key, stable_id


def test_stable_id_is_stable_for_same_parts() -> None:
    left = stable_id("acme", "lever", "remote-42")
    right = stable_id("acme", "lever", "remote-42")
    assert left == right
    assert left == "acme:lever:remote-42"


def test_stable_id_slugifies_unicode_and_special_characters() -> None:
    assert stable_id("Café", "München") == f"{slugify('Café')}:{slugify('München')}"
    assert stable_id("Hello World", 2024) == "hello-world:2024"


def test_stable_id_skips_none_and_empty_parts() -> None:
    assert stable_id("only", None, "", "tail") == "only:tail"


def test_stable_id_hashes_overlong_visible_keys() -> None:
    long_part = "a" * 200
    result = stable_id(long_part)
    assert len(result) < len(long_part)
    assert "-" in result
    assert stable_id(long_part) == result


def test_source_board_key_matches_stable_id_pair() -> None:
    source_key = "yc-source"
    remote_key = "Acme Corp"
    assert source_board_key(source_key, remote_key) == stable_id(source_key, remote_key)
    assert source_board_key(source_key, remote_key) == "yc-source:acme-corp"


@settings(deadline=None, max_examples=40)
@given(parts=st.lists(st.text(min_size=0, max_size=40), min_size=0, max_size=6))
def test_stable_id_is_idempotent_for_same_parts(parts: list[str]) -> None:
    assert stable_id(*parts) == stable_id(*parts)


@settings(deadline=None, max_examples=40)
@given(
    left=st.text(min_size=1, max_size=30),
    right=st.text(min_size=1, max_size=30),
)
def test_source_board_key_matches_stable_id(left: str, right: str) -> None:
    assert source_board_key(left, right) == stable_id(left, right)


@settings(deadline=None, max_examples=40)
@given(
    prefix=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48, max_codepoint=122),
        min_size=1,
        max_size=20,
    )
)
def test_stable_id_omits_none_and_blank_parts(prefix: str) -> None:
    assume(prefix.strip() != "")
    with_blank = stable_id(prefix, None, "", "tail")
    assert with_blank == stable_id(prefix, "tail")
    assert "tail" in with_blank