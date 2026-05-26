## Why

OpenOpps v0.1 needs broader company discovery than VC portfolio boards alone, but the expansion must stay low-friction, auditable, and CLI-first. Public company indexes, rankings, and ecosystem landscapes can increase source coverage without promoting brittle ATS integrations or changing the storage schema.

## What Changes

- Add source adapters for SEC company tickers, opt-in public index CSVs, opt-in ranking CSVs, and CNCF landscape data.
- Preserve source taxonomy metadata in existing source raw metadata fields.
- Add offline source-yield reporting under `openopps admin sources yield` and compact totals in provider coverage JSON.
- Document source families, yield semantics, and the new admin command.

## Impact

- No schema migration or new canonicalization tables.
- No new job-provider support or SmartRecruiters promotion.
- Network access remains explicit through source sync/test commands; yield reporting is persisted-data-only.
