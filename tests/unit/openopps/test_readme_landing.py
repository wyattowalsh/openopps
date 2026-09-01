from __future__ import annotations

import re
import struct
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
README_PATH = REPO_ROOT / "README.md"
ASSET_URL_PREFIX = "assets/readme/"
LANDING_HEADINGS = ("Install", "CLI", "Providers", "Validation")
DOCS_INDEX_SLUGS = (
    "cli",
    "providers",
    "operations",
    "public-data-releases",
    "contributing",
    "configuration",
    "agent-plugins",
    "data-model",
)
POLICY_STRINGS = (
    "source-policy-check",
    "source-policy-audit",
    "0 are independently verified",
    "1780 are blocked",
)
FORBIDDEN_PHRASES = (
    "live Worker cutover",
    "production corpus published",
    "openopps.git@main",
)
RASTER_STEMS = (
    "hero",
    "architecture",
    "path-to-value",
    "nouns",
    "cli-terminal",
    "providers",
)
CHIP_STEMS = (
    "chip-cli",
    "chip-uv",
    "chip-typer",
    "chip-python",
    "chip-route-ledger",
)
RASTER_SIZES = {
    "hero": (1280, 480),
    "architecture": (1280, 520),
    "path-to-value": (1280, 280),
    "nouns": (1280, 200),
    "cli-terminal": (1280, 360),
    "providers": (1280, 400),
    "chip-cli": (96, 44),
    "chip-uv": (84, 44),
    "chip-typer": (116, 44),
    "chip-python": (128, 44),
    "chip-route-ledger": (188, 44),
}
BADGES_START = "<!-- BADGES:START -->"
BADGES_END = "<!-- BADGES:END -->"
URL_RE = re.compile(r"https?://[^\s)\"'<>]+")
PICTURE_RE = re.compile(r"<picture\b.*?</picture>", re.DOTALL | re.IGNORECASE)


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _badge_block(readme: str) -> str:
    assert BADGES_START in readme
    assert BADGES_END in readme
    start = readme.index(BADGES_START)
    end = readme.index(BADGES_END)
    assert start < end
    return readme[start + len(BADGES_START) : end]


def test_readme_has_install_cli_providers_validation_headings() -> None:
    readme = _readme()
    for heading in LANDING_HEADINGS:
        assert re.search(
            rf"^## {re.escape(heading)}\s*$",
            readme,
            re.MULTILINE,
        ), heading


def test_readme_badges_use_shieldcn_markers_and_dynamic_urls() -> None:
    block = _badge_block(_readme())
    assert "https://shieldcn.dev/" in block
    assert "img.shields.io" not in block
    assert "style=for-the-badge" not in block
    for needle in (
        "github/ci/wyattowalsh/openopps",
        "pypi/openopps",
        "github/license/wyattowalsh/openopps",
        "pypi/python/openopps",
    ):
        assert needle in block, needle
    image_urls = re.findall(r'(?:src|srcset)="(https://[^"]+)"', block)
    assert image_urls
    for url in image_urls:
        assert "0.1.1" not in url
        assert url.startswith("https://shieldcn.dev/")


def test_readme_images_use_repo_relative_asset_urls() -> None:
    readme = _readme()
    assert "raw.githubusercontent.com" not in readme
    assert ASSET_URL_PREFIX in readme
    for stem in RASTER_STEMS:
        assert f"{ASSET_URL_PREFIX}{stem}-light.png" in readme
        assert f"{ASSET_URL_PREFIX}{stem}-dark.png" in readme
        assert (REPO_ROOT / "assets" / "readme" / f"{stem}-light.png").is_file()
        assert (REPO_ROOT / "assets" / "readme" / f"{stem}-dark.png").is_file()
    for stem in CHIP_STEMS:
        assert (REPO_ROOT / "assets" / "readme" / f"{stem}-light.png").is_file()
        assert (REPO_ROOT / "assets" / "readme" / f"{stem}-dark.png").is_file()


def test_readme_stack_chips_use_shieldcn() -> None:
    readme = _readme()
    block = _badge_block(readme)
    for label in ("CLI", "uv", "Typer", "Route Ledger"):
        assert f'alt="{label}"' in readme
    block = _badge_block(readme)
    assert "https://shieldcn.dev/badge/CLI-Typer-green.svg" in block
    assert "https://shieldcn.dev/badge/uv-Astral-green.svg" in block
    assert "https://shieldcn.dev/badge/Typer-CLI-green.svg" in block
    assert "https://shieldcn.dev/badge/Python-3.12%2B-green.svg" in block
    assert "https://shieldcn.dev/badge/Route_Ledger-DESIGN.md-green.svg" in block


def test_readme_takumi_rasters_use_picture_prefers_color_scheme_dark() -> None:
    readme = _readme()
    assert "<picture>" in readme
    assert "prefers-color-scheme: dark" in readme
    pictures = PICTURE_RE.findall(readme)
    assert pictures
    for picture in pictures:
        assert "prefers-color-scheme: dark" in picture
        assert re.search(r"<img\b", picture, re.IGNORECASE)


def test_readme_includes_fail_closed_source_policy_sentence() -> None:
    readme = _readme()
    for needle in POLICY_STRINGS:
        assert needle in readme


def test_readme_docs_index_links_canonical_routes() -> None:
    readme = _readme()
    for slug in DOCS_INDEX_SLUGS:
        assert f"https://openopps.dev/docs/{slug}" in readme, slug


def test_readme_lists_openoppsdb_kaggle_notebooks() -> None:
    readme = _readme()
    for kernel in (
        "openoppsdb-starter-notebook",
        "openoppsdb-explorer",
        "openoppsdb-advanced-usage",
        "openoppsdb-sql-playground",
        "openoppsdb-hiring-market-map",
        "openoppsdb-skills-radar",
        "openoppsdb-snapshot-health",
    ):
        assert kernel in readme, kernel


def test_readme_forbids_live_authority_claims() -> None:
    readme = _readme()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in readme, phrase


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_readme_rasters_exist_at_visual_contract_sizes() -> None:
    assets = REPO_ROOT / "assets" / "readme"
    for stem, expected in RASTER_SIZES.items():
        for theme in ("light", "dark"):
            path = assets / f"{stem}-{theme}.png"
            assert path.is_file(), path
            assert _png_size(path) == expected, path.name


def test_readme_preview_screenshots_exist() -> None:
    previews = REPO_ROOT / "assets" / "readme" / "previews"
    for name in ("readme-light.png", "readme-dark.png"):
        path = previews / name
        assert path.is_file(), path
        width, height = _png_size(path)
        assert width == 1280, name
        assert height >= 800, name
