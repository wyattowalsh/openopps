# OpenOpps v0.1 Release Smoke Log

Date: 2026-05-21

This smoke run used a temporary SQLite database and deterministic example data so it does not depend on live source or provider endpoints. It validates the CLI-only v0.1 release flow. Representative live provider percentages are a post-v0.1 follow-up that requires a persisted live-source snapshot run.

## Environment

- Database: `sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db`
- Cache: `http_cache` table inside the configured SQLite database
- Seed: `42`
- Boards: `4`
- Jobs per job-capable board: `2`

## Commands

```bash
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps status --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps plugins list --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps cache status --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps examples seed --seed 42 --boards 4 --jobs-per-board 2 --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps jobs list --source example --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps providers coverage --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps providers audit --json
OPENOPPS_DB_URL=sqlite:////var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/openopps.db uv run openopps jobs export --format jsonl --output /var/folders/z9/yr58561n1rj8_lqtzwkjt24m0000gp/T/opencode/openopps-v01-smoke/jobs.jsonl
```

## Outcomes

| Check                               | Result                                                                                                                                          |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Empty `status --json`               | Parsed JSON; reported zero database/cache/plugin counts and route readiness fields.                                                             |
| `plugins list --json`               | Parsed JSON; reported zero loaded/failed plugins and visible disabled/allowed filters.                                                          |
| `cache status --json`               | Parsed JSON; reported total/fresh/expired/stale-on-error fields.                                                                                |
| `examples seed --json`              | Parsed JSON; seeded 1 source, 4 boards, 4 routes, 6 jobs, and 4 cache records.                                                                  |
| `jobs list --source example --json` | Parsed JSON; returned 6 deterministic synthetic jobs.                                                                                           |
| `providers coverage --json`         | Parsed JSON; denominator 4 boards, 3 job-capable provider boards, 1 non-supported provider board, 25.0% non-supported provider coverage.        |
| `providers audit --json`            | Parsed JSON; source set `example`, denominator 4, Teamtailor candidate coverage 1 board / 25.0%, all candidate do-not-adopt rationales present. |
| `jobs export --format jsonl`        | Wrote 6 jobs to the requested JSONL path.                                                                                                       |

## Residual Live-Data Note

This smoke log proves the release flow and provider audit machinery against deterministic persisted data. Publishing real provider-audit percentages is a post-v0.1 follow-up once a representative persisted live source snapshot exists, because coverage commands intentionally do not fetch sources or providers while reporting.
