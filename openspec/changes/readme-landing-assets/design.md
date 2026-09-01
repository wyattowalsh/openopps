## Context

`just ci-artifacts` today is `source-policy-check kaggle-generated-diff-check kaggle-bundle-smoke diff-check`. The GitHub Actions `artifacts` job is Python-only (uv, Just, `just ci-artifacts`) with a 25-minute timeout. Root `README.md` has a relative `web/public/brand/openopps-logo.png` and no `BADGES` markers. `pyproject.toml` already sets `readme = "README.md"`.

The isolated renderer at `scripts/readme-art/` (package `openopps-readme-art`, Node 24.20.0, pnpm 11.24.0, `takumi-js`) writes visual-contract stems into `assets/readme/`. That package is not a `web/` dependency. Preview screenshots and Just/CI wiring are not yet a release-workflow contract.

Grill, facts, and `goals/readme-awesomeify/visual-contract.md` are locked. This change specifies only asset layout, just recipes, artifacts-job Node, and the README badge/picture URL contract.

## Goals / Non-Goals

**Goals:**

- Name the committed `assets/readme/` tree, including preview screenshots.
- Make generate and drift-check recipes discoverable through Just and part of `ci-artifacts`.
- Give the existing artifacts CI job the Node toolchain needed to run that check without adding a job or fetching `github.com`.
- Lock hybrid live badges, chips-outside-markers, absolute raster URLs, and `<picture>` dark mode so GitHub, Camo, and PyPI can render the same `README.md`.

**Non-Goals:**

- CLI behavior, Jobs/Explorer UI, `web/package.json`, or nested README restyles (`CONTRIBUTING.md`, `web/README.md`, `deployment/openopps-data/README.md`) except pointer/link fixes.
- Cloudflare Workers upload, Kaggle mutation, production bootstrap, or a live v7 cutover claim.
- Archiving this change.
- Changing the pinned OpenSpec version (`@fission-ai/openspec@1.6.0`).
- Authoring Takumi JSX, choosing the npm entry, or rewriting operator README prose beyond the badge/picture contract (sibling leases).

## Decisions

### Isolated generator, committed rasters

Rasters are produced by `scripts/readme-art/` and committed under `assets/readme/`. `web/package.json` stays free of Takumi. Card stems and sizes follow the visual contract: `hero` 1280×480, `architecture` 1280×520, `path-to-value` 1280×280, `nouns` 1280×200, `cli-terminal` 1280×360, `providers` 1280×400. Chip stems are `chip-cli`, `chip-uv`, `chip-typer`, `chip-python`, `chip-route-ledger` at height 40–48. Each stem has `-light.png` and `-dark.png`. At most one optional animated WebP may exist, and it MUST have a static PNG fallback. Previews are `assets/readme/previews/readme-light.png` and `readme-dark.png`.

### Just recipes and `ci-artifacts`

| Recipe | Role |
| --- | --- |
| `just readme-assets` | Render committed rasters into `assets/readme/` |
| `just readme-previews` | Local GFM→HTML, Playwright Chromium `color-scheme` light and dark |
| `just readme-assets-check` | Regenerate (or check-mode) and `git diff --exit-code` on `assets/readme/` |

`just ci-artifacts` gains `readme-assets-check` while keeping `source-policy-check`, `kaggle-generated-diff-check`, `kaggle-bundle-smoke`, and `diff-check`. Insert the new check before `diff-check`. Governance tests that snapshot the exact `ci-artifacts:` line MUST be updated in the same change as the Justfile.

Previews render GitHub-flavored markdown to local HTML. They MUST NOT load `github.com`.

### Existing artifacts job, not a new job

Keep the current `artifacts` job and its 25-minute timeout. Do not add a GitHub Actions job (workflow `timeout-minutes` count is pinned). Add:

1. `actions/setup-node` with `node-version-file: .node-version` (keeps the existing pairing with `uses: actions/setup-node@`).
2. `pnpm/action-setup` at **11.24.0**. Cache `scripts/readme-art/pnpm-lock.yaml`, not `web/pnpm-lock.yaml`.
3. `pnpm --dir scripts/readme-art install --frozen-lockfile`.
4. Chromium-only Playwright for previews (`chromium`, not Firefox/WebKit).

The web/security jobs already pin pnpm 11.24.0 twice. Adding the artifacts job makes that count three; `test_ci_uses_the_repo_pinned_pnpm_version` MUST be updated with the workflow.

Reuse SHA-pinned `actions/setup-node` and `pnpm/action-setup` already used by web/security. Checkout keeps `persist-credentials: false`.

### Hybrid badges and repo-relative `<picture>` URLs

Live status shields (native CI `ci.yml`, PyPI/`openopps` version, license, Python 3.12+) live between `<!-- BADGES:START -->` and `<!-- BADGES:END -->`, `style=for-the-badge`, logos on, dynamic endpoints only. Package version, coverage, and CI status are never hardcoded in badge URLs.

Takumi chips (CLI, uv, Typer, Python, Route Ledger) sit outside the marker block and are images, not version shields.

Takumi cards and chips in README use:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/readme/<stem>-dark.png">
  <img src="assets/readme/<stem>-light.png" alt="...">
</picture>
```

Repo-relative URLs load in local preview and on GitHub from the viewed commit. Absolute `raw.githubusercontent.com/.../main/` URLs 404 until the rasters exist on origin/main. PyPI ignores `<picture>` and shows the light `img`. `readme = "README.md"` stays.

### Parallel task graph

| Lane | Owns | Conflict |
| --- | --- | --- |
| OpenSpec | `openspec/changes/readme-landing-assets/**` | none |
| Just/CI/AGENTS | `Justfile`, `.github/workflows/ci.yml` artifacts job, root `AGENTS.md` | serialize Justfile vs governance tests that parse it |
| README chrome | `README.md` badge markers and picture URLs | none vs Just/CI |
| Tests | `tests/unit/openopps/test_readme_landing.py`, `test_ci_governance.py` assertions for this contract | after Justfile/`README.md` exist |
| Previews | `assets/readme/previews/` | after README rewrite |

Same-file edits stay sequential. This change does not archive.

## Risks / Trade-offs

- **GitHub.com vs local:** relative `assets/readme/` URLs resolve from the viewed commit; they 404 on github.com until those files are pushed. Do not point at `raw.githubusercontent.com/.../main/` before the files exist there.
- **PyPI `<picture>`:** only the light `img` fallback appears on PyPI; dark art is GitHub-only.
- **Artifacts timeout:** Chromium-only Playwright is required so the 25-minute job still holds. Installing Firefox/WebKit on this job is a regression.
- **Governance pins:** `ci-artifacts:` exact line and `version: 11.24.0` count will fail until tests move with Just/CI.
- **Binary weight:** six dual-theme cards, five dual-theme chips, two previews; keep PNGs reasonably compressed; at most one WebP.
- **Sibling leases:** generator templates and landing prose can land in parallel; this spec names layout and chrome, not JSX or section essays.

## Open Questions

None. Grill is complete; facts are accepted.
