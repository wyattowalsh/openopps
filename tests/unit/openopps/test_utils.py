from __future__ import annotations

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