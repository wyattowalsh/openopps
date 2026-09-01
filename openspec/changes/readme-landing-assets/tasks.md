# readme-landing-assets - tasks

Checked tasks require named local proof. They do not authorize archive, tag, publication, Workers upload, Kaggle mutation, production bootstrap, commit, or push.

## 1. Contract

- [x] 1.1 Record asset layout, just recipes, artifacts-job Node, and README `BADGES`/picture URL requirements in proposal, design, and delta specs for `release-workflows` and `docs-product-boundary`.
- [x] 1.2 Strict-validate this change and all active changes with pinned `@fission-ai/openspec@1.6.0` (`rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict`). Do not archive this change.

## 2. Generated layout and Just recipes

- [x] 2.1 Keep committed `assets/readme/{stem}-{light,dark}.png` for card stems `hero`, `architecture`, `path-to-value`, `nouns`, `cli-terminal`, `providers` and chip stems `chip-cli`, `chip-uv`, `chip-typer`, `chip-python`, `chip-route-ledger`.
- [x] 2.2 Add `just readme-assets` that renders those rasters via `scripts/readme-art/` into `assets/readme/`.
- [x] 2.3 Add `just readme-previews` that writes local GFM HTML screenshots to `assets/readme/previews/readme-light.png` and `readme-dark.png` without loading `github.com`.
- [x] 2.4 Add `just readme-assets-check` that regenerates or verifies and fails on `git diff --exit-code` under `assets/readme/`. Fold it into `just ci-artifacts` while keeping `source-policy-check`, `kaggle-generated-diff-check`, `kaggle-bundle-smoke`, and `diff-check`.
- [x] 2.5 List the three recipes and `just readme-assets-check` on the root `AGENTS.md` validation command list.

## 3. Artifacts CI job

- [x] 3.1 On the existing `artifacts` job only, install Node from `.node-version`, pnpm 11.24.0 (cache `scripts/readme-art/pnpm-lock.yaml`), and `pnpm --dir scripts/readme-art install --frozen-lockfile`. Do not add a job. Do not fetch `github.com`. Playwright stays a local `just readme-previews` dependency.
- [x] 3.2 Update governance tests so `ci-artifacts` includes `readme-assets-check`, the artifacts workflow installs Node with `node-version-file: .node-version`, and the pinned pnpm 11.24.0 occurrence count matches the workflow.

## 4. README badge and picture URL contract

- [x] 4.1 Put live `for-the-badge` shields (native CI `ci.yml`, PyPI/`openopps`, license, Python 3.12+) between `<!-- BADGES:START -->` and `<!-- BADGES:END -->` with no hardcoded version, coverage, or CI status in badge URLs.
- [x] 4.2 Place Takumi chips outside that marker block. Embed Takumi rasters with `<picture>`, `prefers-color-scheme: dark`, and repo-relative `assets/readme/...` URLs.
- [x] 4.3 Keep `pyproject.toml` `readme = "README.md"`. Do not restyle nested READMEs except pointer/link fixes.
- [x] 4.4 Assert the marker, `for-the-badge`, repo-relative `assets/readme/` URL, and `<picture>` contract in `tests/unit/openopps/test_readme_landing.py`.

## 5. Local / CI parity

- [x] 5.1 `just --list` shows `readme-assets`, `readme-previews`, and `readme-assets-check`.
- [x] 5.2 `uv run pytest tests/unit/openopps/test_readme_landing.py tests/unit/openopps/test_ci_governance.py -q` covers this contract.
- [x] 5.3 Re-run `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict`. Leave this change unarchived.
