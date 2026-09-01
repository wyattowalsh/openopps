## ADDED Requirements

### Requirement: Root README landing uses hybrid badges and repo-relative picture URLs

Root `README.md` SHALL wrap live status shields in `<!-- BADGES:START -->` and `<!-- BADGES:END -->`. Those shields SHALL use dynamic endpoints in `for-the-badge` style with logos for native CI (`.github/workflows/ci.yml`), the PyPI `openopps` version, license, and Python 3.12+. Badge URLs SHALL NOT hardcode a package version, coverage percent, or CI status. Takumi-rendered brand chips for CLI, uv, Typer, Python, and Route Ledger SHALL sit outside the marker block and SHALL NOT display version numbers. Takumi rasters in the README SHALL use `<picture>` with a `source` whose `media` is `(prefers-color-scheme: dark)` and a light `img` fallback. Image `src` and `srcset` values for those rasters SHALL be repo-relative `assets/readme/...` URLs so GitHub and local preview resolve them from the viewed tree. OpenOpps SHALL NOT point README rasters at `raw.githubusercontent.com/.../main/` (those URLs 404 until the files exist on the default branch). `pyproject.toml` SHALL keep `readme = "README.md"`.

#### Scenario: Live status badges are marked and dynamic

- **WHEN** a reader opens root `README.md`
- **THEN** `<!-- BADGES:START -->` and `<!-- BADGES:END -->` wrap the live shield row
- **AND** those shields use `style=for-the-badge` with logos for CI, PyPI/`openopps`, license, and Python
- **AND** badge URLs do not embed a hardcoded `0.1.1`, coverage percent, or CI status

#### Scenario: Takumi chips stay outside the badge markers

- **WHEN** the landing shows brand or stack chips
- **THEN** the chip images are Takumi rasters under `assets/readme/`
- **AND** they are not inside the `BADGES` marker block
- **AND** they do not display version numbers

#### Scenario: Takumi cards use picture and repo-relative asset URLs

- **WHEN** README embeds a Takumi card or chip raster
- **THEN** the embed is a `<picture>` element with `prefers-color-scheme: dark` as the dark `source` media
- **AND** the light `img` `src` is a repo-relative `assets/readme/` URL
- **AND** the README does not use `raw.githubusercontent.com` for those rasters
- **AND** `pyproject.toml` still sets `readme = "README.md"`
