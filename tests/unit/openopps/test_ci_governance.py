from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ACTION_REF = re.compile(r"^\s*uses:\s*[^\s#]+@([0-9a-f]{40})(?:\s+#.*)?$", re.MULTILINE)
ANY_ACTION = re.compile(r"^\s*uses:\s*([^\s#]+)(?:\s+#.*)?$", re.MULTILINE)
UNSAFE_JUST_PARAMETER = re.compile(
    r"\{\{\s*(?:allow_stale|change|dataset|db|message|output|page_size|timeout|version)\s*\}\}"
)


def test_dependency_update_ownership_is_disjoint() -> None:
    renovate = json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))
    dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert set(renovate["enabledManagers"]) == {"pep621", "npm"}
    assert dependabot.count("package-ecosystem: github-actions") == 1
    assert "package-ecosystem: npm" not in dependabot
    assert "package-ecosystem: pip" not in dependabot


def test_ci_uses_the_repo_pinned_pnpm_version() -> None:
    package = json.loads(
        (REPO_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    package_manager = package["packageManager"]
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+", package_manager)
    pnpm_version = package_manager.removeprefix("pnpm@")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert workflow.count(f"version: {pnpm_version}") == 2


def test_workflow_actions_are_sha_pinned_and_checkouts_drop_credentials() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    actions = ANY_ACTION.findall(workflow)

    assert actions
    assert len(ACTION_REF.findall(workflow)) == len(actions)
    assert workflow.count("persist-credentials: false") == workflow.count(
        "uses: actions/checkout@"
    )


def test_workflow_uses_supported_python_matrix_and_shared_just_lanes() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    for recipe in (
        "ci-artifacts",
        "ci-openspec",
        "ci-python",
        "ci-python-compat",
        "ci-web",
        "security-audit",
        "test-lowest-direct",
    ):
        assert f"run: just {recipe}" in workflow
    assert workflow.count("timeout-minutes:") == 8


def test_web_gate_installs_and_runs_all_supported_browser_engines() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")

    assert "playwright install --with-deps chromium firefox webkit" in workflow
    assert "--project=chromium --project=firefox --project=webkit" in justfile


def test_attestation_is_non_pr_least_privilege_and_post_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    supply_chain = workflow.split("  supply-chain:\n", maxsplit=1)[1]

    assert "if: github.event_name != 'pull_request'" in supply_chain
    assert (
        "needs: [python, lowest-direct, openspec, security, web, artifacts]"
        in supply_chain
    )
    assert "attestations: write" in supply_chain
    assert "contents: read" in supply_chain
    assert "id-token: write" in supply_chain
    assert "uses: actions/attest@" in supply_chain


def test_just_uses_positional_transport_and_locked_kaggle_tooling() -> None:
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")

    assert "set positional-arguments" in justfile
    assert UNSAFE_JUST_PARAMETER.search(justfile) is None
    assert 'kaggle := "uv run --frozen --group ops kaggle"' in justfile
    assert "--with kaggle" not in justfile
    assert (
        "ci-artifacts: kaggle-generated-diff-check kaggle-bundle-smoke diff-check"
    ) in justfile
    assert "kaggle-generated-diff-check: kaggle-meta" in justfile
    assert "git diff --exit-code -- kaggle" in justfile
    assert "git ls-files --others --exclude-standard -- kaggle" in justfile
    assert "diff-check:\n    git diff --check" in justfile
    assert "cd web && pnpm audit --audit-level high" in justfile
    assert "pnpm audit --prod" not in justfile


def test_lowest_direct_gate_installs_project_and_all_tested_dependency_groups() -> None:
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")
    recipe = justfile.split("test-lowest-direct:", maxsplit=1)[1].split(
        "\n# Run focused CLI integration tests.", maxsplit=1
    )[0]

    assert 'cp -R src "$work/src"' in recipe
    assert 'cp examples/examples.py "$work/examples/"' in recipe
    assert "uv sync --python 3.12 --all-extras --all-groups" in recipe
    assert "--no-install-project" not in recipe


def test_scoped_git_probe_detects_untracked_generated_artifacts(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    generated_root = tmp_path / "kaggle"
    generated_root.mkdir()
    tracked = generated_root / "dataset-metadata.json"
    tracked.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "-C", tmp_path, "add", str(tracked)], check=True)
    untracked = generated_root / "new-notebook.ipynb"
    untracked.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            "git",
            "-C",
            tmp_path,
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "kaggle",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["kaggle/new-notebook.ipynb"]


def test_python_quality_and_operational_tools_are_locked() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    groups = pyproject["dependency-groups"]

    assert "pip-audit==2.10.1" in groups["dev"]
    assert "ruff==0.16.2" in groups["dev"]
    assert "ty==0.0.71" in groups["dev"]
    assert "kaggle==2.2.4" in groups["ops"]
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"
    assert pyproject["tool"]["ty"]["src"]["include"] == ["src/openopps"]


def test_operator_docs_match_kaggle_and_offline_release_contract() -> None:
    notebook = json.loads(
        (REPO_ROOT / "kaggle" / "openoppsdb-manager.ipynb").read_text(encoding="utf-8")
    )
    notebook_source = "".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )
    runtime_digest_match = re.search(
        r'"OPENOPPS_RUNTIME_PACKAGE_SHA256",\s*"([0-9a-f]{64})"',
        notebook_source,
    )
    assert runtime_digest_match is not None
    runtime_digest = runtime_digest_match.group(1)

    operator_docs = [
        (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
        (REPO_ROOT / "web" / "content" / "docs" / "operations.mdx").read_text(
            encoding="utf-8"
        ),
    ]
    for document in operator_docs:
        assert "openopps.git@main" not in document
        assert runtime_digest in document
        assert "dry-run by default" in document
        assert "expected_current_version=<n>" in document
        assert "execute=1" in document
        assert "allow_no_rollback=1" in document
        assert "metadata repair" in document
        assert "separate" in document

    public_release_docs = "\n".join(
        [
            operator_docs[1],
            (
                REPO_ROOT / "web" / "content" / "docs" / "public-data-releases.mdx"
            ).read_text(encoding="utf-8"),
        ]
    )
    assert "default-off offline-search installer" in public_release_docs
    assert "Chromium/Firefox/WebKit" in public_release_docs
    assert "production-snapshot rights approval" in public_release_docs
