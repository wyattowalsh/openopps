from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_KERNEL_IDS = (
    "wyattowalsh/openoppsdb-starter-notebook",
    "wyattowalsh/openoppsdb-explorer",
    "wyattowalsh/openoppsdb-advanced-usage",
    "wyattowalsh/openoppsdb-sql-playground",
    "wyattowalsh/openoppsdb-hiring-market-map",
    "wyattowalsh/openoppsdb-skills-radar",
    "wyattowalsh/openoppsdb-snapshot-health",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_public_data_releases_lists_kaggle_notebooks() -> None:
    text = _read("web/content/docs/public-data-releases.mdx")
    assert "## Related Kaggle notebooks" in text
    for kernel_id in PUBLIC_KERNEL_IDS:
        assert kernel_id in text, kernel_id
    assert "openoppsdb-manager" not in text.split("## Publication layout", 1)[0]


def test_operations_lists_kaggle_notebooks() -> None:
    text = _read("web/content/docs/operations.mdx")
    for kernel_id in PUBLIC_KERNEL_IDS:
        assert kernel_id in text, kernel_id


def test_readme_lists_kaggle_notebooks() -> None:
    text = _read("README.md")
    for kernel_id in PUBLIC_KERNEL_IDS:
        slug = kernel_id.rsplit("/", 1)[1]
        assert slug in text, slug
