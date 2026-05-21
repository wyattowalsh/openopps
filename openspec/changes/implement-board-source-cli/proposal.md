## Why

OpenOpps is currently a scaffold and needs a durable CLI/data contract for discovering hiring boards from aggregate sources and fetching jobs from supported provider APIs. The requested first source is the a16z companies board, with performance-sensitive sync paths and both DB-backed and file-backed operation.

## What Changes

- Add a Typer CLI organized around `sources`, `boards`, `jobs`, `providers`, and `db`.
- Add Pydantic contracts and SQLModel tables for sources, boards, board-provider relationships, and jobs.
- Add high-performance async ingestion with bounded HTTPX concurrency, Tenacity retries, streaming JSONL sinks, batched SQLite upserts, and Polars exports.
- Add provider support levels plus V1 job fetching for Ashby, Greenhouse, Lever, and public Workday CXS boards.
- Add Consider and Getro source adapters that fetch default investor-company board catalogs and preserve available provider hints.
- Add tests, docs, and nested package instructions for the implemented public surface.

## Capabilities

### New Capabilities
- `cli-domain`: Public CLI commands and scope semantics for sources, boards, jobs, providers, and DB operations.
- `provider-ingestion`: Provider registry and source/job ingestion behavior for Consider/Getro sources, Ashby, Greenhouse, Lever, Workday CXS, and detect-only providers.
- `storage-export`: DB-backed and no-DB storage, streaming JSONL, and Polars-backed exports.
- `performance-observability`: Bounded concurrency, streaming/batch performance behavior, metrics output, and profile summaries.

### Modified Capabilities

## Impact

- Adds runtime dependencies in `pyproject.toml` and CLI entry point `openopps`.
- Replaces the hello-world package with models, settings, provider adapters, ingestion services, storage/export code, and Typer commands.
- Adds tests for CLI, providers, storage/export, and pipeline behavior.
- Adds project-local OpenSpec files and updates `src/openopps/AGENTS.md` and README/docs.
