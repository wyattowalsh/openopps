## ADDED Requirements

### Requirement: README landing rasters are a committed generated artifact surface

OpenOpps SHALL commit generated README landing rasters under `assets/readme/`, produced by the isolated `scripts/readme-art/` package rather than by `web/`. The tree SHALL include light and dark PNGs for card stems `hero`, `architecture`, `path-to-value`, `nouns`, `cli-terminal`, and `providers`, and for chip stems `chip-cli`, `chip-uv`, `chip-typer`, `chip-python`, and `chip-route-ledger`. Local README preview screenshots SHALL live at `assets/readme/previews/readme-light.png` and `assets/readme/previews/readme-dark.png`. OpenOpps MAY commit at most one animated WebP under `assets/readme/` and SHALL pair it with a static PNG fallback.

#### Scenario: Contributor inspects the generated tree

- **WHEN** a contributor lists `assets/readme/`
- **THEN** each required card and chip stem has `-light.png` and `-dark.png`
- **AND** `assets/readme/previews/readme-light.png` and `readme-dark.png` exist
- **AND** `web/package.json` is not the home of the Takumi README renderer

#### Scenario: Optional motion asset

- **WHEN** a motion README asset is present
- **THEN** it is a single WebP
- **AND** a static PNG fallback for that surface exists in the same tree

### Requirement: Just recipes generate and drift-check README landing assets

OpenOpps SHALL provide root Justfile recipes `readme-assets`, `readme-previews`, and `readme-assets-check`. `just readme-assets` SHALL write rasters into `assets/readme/`. `just readme-previews` SHALL render GitHub-flavored markdown to local HTML and capture Chromium screenshots with `color-scheme` light and dark into `assets/readme/previews/`. `just readme-assets-check` SHALL regenerate Takumi rasters and fail when `git diff --exit-code` reports changes under `assets/readme/` excluding `assets/readme/previews/`. Preview PNGs SHALL exist as committed evidence; Playwright screenshots are not byte-stable, so CI SHALL NOT require a preview byte match. `just ci-artifacts` SHALL include `readme-assets-check` while still running `source-policy-check`, `kaggle-generated-diff-check`, `kaggle-bundle-smoke`, and `diff-check`.

#### Scenario: Contributor discovers README asset recipes

- **WHEN** a contributor runs `just --list`
- **THEN** the output includes `readme-assets`, `readme-previews`, and `readme-assets-check`

#### Scenario: Committed rasters drift

- **WHEN** a committed Takumi raster under `assets/readme/` differs from regeneration
- **THEN** `just readme-assets-check` fails
- **AND** `git diff --exit-code` covers `assets/readme/` excluding `assets/readme/previews/`
- **AND** the preview PNGs still exist on disk

#### Scenario: Preview screenshots are generated

- **WHEN** a contributor runs `just readme-previews`
- **THEN** the recipe writes `assets/readme/previews/readme-light.png` and `readme-dark.png` from local GitHub-flavored HTML
- **AND** it does not load `github.com`

#### Scenario: Full artifact gate includes README drift-check

- **WHEN** a contributor runs `just ci-artifacts`
- **THEN** `readme-assets-check` runs
- **AND** `source-policy-check`, `kaggle-generated-diff-check`, `kaggle-bundle-smoke`, and `diff-check` still run

### Requirement: The generated-artifacts CI job installs Node to drift-check README assets

The existing GitHub Actions `artifacts` job SHALL install Node from `.node-version`, pnpm 11.24.0, and `pnpm --dir scripts/readme-art install --frozen-lockfile`, then run `just ci-artifacts`. OpenOpps SHALL NOT add a separate GitHub Actions job for README assets and SHALL NOT fetch `github.com` to produce or check previews. Chromium Playwright is a local `just readme-previews` dependency, not a required artifacts-job install.

#### Scenario: Artifacts job runs on a pull request

- **WHEN** CI runs the Generated artifacts job
- **THEN** it uses Node 24.20.0 from `.node-version` and pnpm 11.24.0
- **AND** it installs `scripts/readme-art` with `--frozen-lockfile`
- **AND** the job does not load `github.com`
- **AND** the workflow still has a single `artifacts` job rather than a new README-assets job
