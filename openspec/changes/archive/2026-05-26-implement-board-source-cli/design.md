## Overview

Implement the package as a streaming ingestion CLI. Public commands use the product nouns `sources`, `boards`, and `jobs`; providers remain implementation adapters with visible support levels.

## Data Flow

`sources sync` fetches pages from source adapters, validates page batches with Pydantic, normalizes boards and board-provider hints, and fans out to DB and optional JSONL sinks. `jobs sync` selects boards from DB or input JSONL, routes each board through job-capable providers, streams normalized jobs, and writes via the same sink interfaces.

## Provider Design

Providers implement a small async protocol with detection metadata and optional job fetching. Consider and Getro adapters are source providers for investor catalogs. Ashby, Greenhouse, and Lever are job providers using public posting APIs. Workday parses public career-site URLs into host/tenant/site, paginates CXS listings with conservative concurrency, and optionally fetches detail payloads by `externalPath`.

## Storage and Export

SQLModel tables store canonical records and raw JSON payloads. SQLite uses WAL mode and batched upserts. No-DB paths write Pydantic JSONL records using the same normalized models. Polars handles CSV and Parquet exports from record batches or lazy scans.

## Performance and Observability

HTTPX clients are reused, retries are bounded, provider fan-out is controlled by semaphores, and sync commands expose metrics and profile summaries. Tests guard against row-by-row commits, unbounded concurrency, and all-record accumulation.
