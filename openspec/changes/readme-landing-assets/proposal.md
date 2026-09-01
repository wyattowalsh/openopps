## Why

Root `README.md` is still a long operator runbook with a relative logo and no live badges. GitHub, Camo, and PyPI cannot render a Route Ledger landing until committed rasters, hybrid shields, `<picture>` URLs, and a drift-checked generator lane exist. Those surfaces are public workflow contracts; they must be specified before Just, CI, and README chrome change.

## What Changes

- Treat `assets/readme/` as a committed generated artifact tree: visual-contract card and chip PNGs (light + dark) plus local light/dark README preview screenshots under `assets/readme/previews/`.
- Add `just readme-assets`, `just readme-previews`, and `just readme-assets-check`, and fold the check into `just ci-artifacts`.
- Extend the existing GitHub Actions `artifacts` job (not a new job) with Node from `.node-version`, pnpm 11.24.0, a frozen `scripts/readme-art` install, and Chromium-only Playwright for previews. Do not fetch `github.com`.
- Lock the root README hybrid-badge and picture URL contract: `BADGES:START`/`END` dynamic `for-the-badge` shields, Takumi chips outside that block, repo-relative `assets/readme/` image URLs, and `<picture>` dark sources with light `img` fallbacks.
- Keep `pyproject.toml` `readme = "README.md"`. Do not change CLI behavior, Jobs/Explorer UI, `web/package.json`, nested README restyles, Workers, or Kaggle.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-workflows`: Generated `assets/readme/` layout, `just readme-assets` / `readme-previews` / `readme-assets-check`, `ci-artifacts` membership, and Node on the existing artifacts CI job.
- `docs-product-boundary`: Root README `BADGES` marker block, Takumi chips outside it, and repo-relative `<picture>` URL contract.

## Impact

- Isolated renderer remains `scripts/readme-art/` (Node 24.20.0 / pnpm 11.24.0). Takumi is not added to `web/package.json`.
- Justfile, `.github/workflows/ci.yml` `artifacts` job, root `AGENTS.md` validation commands, and governance tests that pin `ci-artifacts` / Node / pnpm counts.
- Root `README.md` badge markers and image embeds only in this contract. Full landing copy, pytest retarget, and preview screenshot generation are sibling work, not extra capabilities.
- No new GitHub Actions job, no archive of this change, no live Worker/Kaggle/bootstrap, no CLI behavior change.

## Acceptance summary

1. `assets/readme/` holds the named light/dark card and chip PNGs; `assets/readme/previews/` holds local `readme-light.png` and `readme-dark.png`.
2. `just --list` shows `readme-assets`, `readme-previews`, and `readme-assets-check`; `just ci-artifacts` runs the check; the check fails on raster or preview drift.
3. The existing artifacts job installs Node 24.20.0 and pnpm 11.24.0, frozen-installs `scripts/readme-art`, uses Chromium-only Playwright, and never loads `github.com`.
4. README live shields sit between `BADGES` markers; chips and Takumi cards use repo-relative `assets/readme/...` URLs inside `<picture>` with `prefers-color-scheme: dark`.
5. `pyproject.toml` still sets `readme = "README.md"`. `rtk npx -y @fission-ai/openspec@1.6.0 validate --all --strict` passes. This change is not archived here.
