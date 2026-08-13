# OpenOpps Web App

This directory contains the OpenOpps web app (Fumadocs docs + jobs/explorer) built with Next.js, Fumadocs, MDX, Tailwind CSS, and shadcn/ui.

## Commands

Use pnpm from this directory:

```bash
pnpm install
pnpm data:generate
pnpm data:generate:search
pnpm dev
pnpm types:check
pnpm build
pnpm lint
pnpm test
```

The development server opens at `http://localhost:3000`.

From the repository root, prefer the canonical `just web-*` shortcuts (transitional `just docs-*` aliases call the same recipes):

```bash
just web-check
just web-build
just web-function-trace-check
just web-search-index
just web-search-index-check
just web-lint
just web-test
just web-rtk-lint
```

`pnpm types:check` and `pnpm build` both refresh `lib/generated/openopps-data.json` through `pnpm data:generate`, so treat generated docs data as part of the docs validation surface.
`just web-build` runs the production Next.js build and then `just web-function-trace-check`, which verifies API route traces do not bundle the committed `public/data/openopps-search/` tree into a server function.
`pnpm data:generate:search` refreshes the legacy version 6 snapshot used by Jobs (`/`) and Explorer (`/explorer`) from `../kaggle/openoppsdb.sqlite`; it is explicit because that SQLite file is local and ignored by Git. Run `just web-search-index-check` from the repository root when intentionally refreshing that transition snapshot; it requires a **clean** local public `kaggle/openoppsdb.sqlite`, regenerates the index, and fails if `public/data/openopps-search/` remains dirty. CI does not open SQLite—it validates the committed artifact tree only.

Version 7 generation is additive and writes immutable releases plus a channel pointer to a separate publication root:

```bash
uv run python scripts/generate_docs_search_index.py \
  --data-db kaggle/openoppsdb.sqlite \
  --release-root /absolute/path/to/openopps-search-v7 \
  --channel production \
  --max-snapshot-age-hours 48
uv run python scripts/verify_docs_search_artifacts.py \
  --root /absolute/path/to/openopps-search-v7 \
  --channel production \
  --max-snapshot-age-hours 48
```

With a configured public-data origin/channel, Jobs/Explorer, details, metadata, and sitemaps read through the shared release-pinned snapshot client. Browser search runs in a dedicated Web Worker; `/api/jobs/search` is a fail-closed `410` compatibility endpoint and does not scan the corpus server-side. See [`content/docs/public-data-releases.mdx`](content/docs/public-data-releases.mdx) and [`../deployment/openopps-data/README.md`](../deployment/openopps-data/README.md) for governance, delivery, rollback, and the v6 exit criteria. No current local command or CI job proves a live v7 rollout.

Job previews show full description text only when the snapshot contains normalized description fields; otherwise they remain metadata-first and link back to the source posting.
`just web-rtk-lint` is the optional maintainer lint surface for `rtk`; it is explicit and outside the default `just ci`/GitHub Actions path.

Current docs IA routes are `index`, `cli`, `configuration`, `data-model`, `providers`, `operations`, `public-data-releases`, and `contributing`. The jobs workbench lives at `/`; the data dashboard lives at `/explorer`.

## Telemetry

Web telemetry is disabled by default. The browser client only sends events when `NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED=true`; the API route accepts sanitized batches at `/api/telemetry` and noops unless a server-side sink or mirror is configured.

For a local zero-cost event lake, run the web app with a writable telemetry directory:

```bash
NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED=true \
OPENOPPS_TELEMETRY_SINK=local-event-lake \
OPENOPPS_TELEMETRY_DIR="$PWD/.telemetry" \
pnpm dev
```

The local sink appends newline-delimited JSON under `OPENOPPS_TELEMETRY_DIR/YYYY/MM/DD/events.ndjson`. Events include route context, viewport and browser metadata, selected interaction properties, request metadata, optional hashed IPs, and redaction counters. Secret-like fields and values are redacted before writing. Use `OPENOPPS_TELEMETRY_IP_MODE=drop|hash|raw` to control IP handling; `hash` is the default, and `raw` should only be used in controlled local analysis. IP headers are ignored unless `OPENOPPS_TELEMETRY_TRUSTED_PROXY` explicitly selects `cloudflare`, `vercel`, or `forwarded`.

For a free hosted product-analytics mirror, set `OPENOPPS_POSTHOG_PROJECT_API_KEY` and optionally `OPENOPPS_POSTHOG_HOST`. PostHog forwarding happens server-side after the OpenOpps allowlist/sanitizer runs, so raw posting bodies, request headers, secrets, and direct identifiers are not forwarded. The local event lake remains the canonical raw sink when configured, and PostHog forwarding is bounded by `OPENOPPS_POSTHOG_TIMEOUT_MS` so a slow mirror cannot block the canonical write.

For hosted browser session replay, set `NEXT_PUBLIC_OPENOPPS_POSTHOG_PROJECT_API_KEY`, enable `NEXT_PUBLIC_OPENOPPS_POSTHOG_RECORDING=true`, and optionally `NEXT_PUBLIC_OPENOPPS_POSTHOG_HOST`. The PostHog client still requires `NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED=true`; the browser SDK disables automatic pageview/autocapture events, masks all input and page text, disables network body/header capture, and leaves sampling plus URL/event/linked-flag controls to the PostHog project configuration. OpenOpps first-party telemetry continues to send only compact allowlisted events such as searches, selections, pagination, and page engagement counters.

Useful limits:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED` | unset | Enables the browser telemetry client and optional browser PostHog replay. |
| `NEXT_PUBLIC_OPENOPPS_POSTHOG_PROJECT_API_KEY` | unset | Optional browser PostHog key; initializes the masked client when telemetry is enabled. |
| `NEXT_PUBLIC_OPENOPPS_POSTHOG_RECORDING` | unset | When `true`, starts browser session recording (default off). |
| `NEXT_PUBLIC_OPENOPPS_POSTHOG_HOST` | `https://us.i.posthog.com` | Optional browser PostHog host, for example the EU ingestion host. |
| `OPENOPPS_TELEMETRY_MAX_REQUEST_BYTES` | `524288` | Maximum accepted telemetry batch body size. |
| `OPENOPPS_TELEMETRY_MAX_EVENT_BYTES` | `65536` | Maximum sanitized event/context payload before truncation metadata replaces oversized properties. |
| `OPENOPPS_TELEMETRY_SALT` | built-in default | Salt used when hashing IP addresses. Set this in deployed environments for stable private hashes. |
| `OPENOPPS_TELEMETRY_TRUSTED_PROXY` | `none` | Trusted client-IP source: `cloudflare`, `vercel`, or `forwarded`; leave unset unless your ingress owns and strips that header. |
| `OPENOPPS_POSTHOG_PROJECT_API_KEY` | unset | Optional PostHog project key for sanitized hosted analytics. |
| `OPENOPPS_POSTHOG_HOST` | `https://us.i.posthog.com` | Optional PostHog host, for example the EU ingestion host. |
| `OPENOPPS_POSTHOG_TIMEOUT_MS` | `1500` | Maximum time spent on best-effort PostHog forwarding, clamped to 100-10000 ms. |

## Layout

| Path                            | Purpose                                                                  |
| ------------------------------- | ------------------------------------------------------------------------ |
| `content/docs/`                 | MDX documentation pages.                                                 |
| `content/docs/meta.json`        | Fumadocs navigation order and section title.                             |
| `source.config.ts`              | Fumadocs MDX collection configuration.                                   |
| `lib/source.ts`                 | Fumadocs content loader, LLM text helpers, and Open Graph image helpers. |
| `lib/shared.ts`                 | Project name, docs routes, and GitHub repository metadata.               |
| `lib/layout.shared.tsx`         | Shared Fumadocs layout options.                                          |
| `app/(home)/page.tsx`           | Jobs workbench route for the web app home (`/`).                         |
| `app/docs/[[...slug]]/page.tsx` | Fumadocs documentation page renderer.                                    |
| `app/api/search/route.ts`       | Fumadocs search route.                                                   |
| `app/api/telemetry/route.ts`    | Telemetry intake route with noop, local event-lake, and optional PostHog forwarding. |
| `components/`                   | MDX and shadcn/ui component wiring.                                      |
| `lib/telemetry.ts`              | Browser telemetry queue, sanitizer, and shared event types.              |
| `lib/openopps-snapshot-client.ts` | Release-pinned v7 verification and bounded v6 transition reads.        |
| `lib/jobs-search.worker.ts`     | Dedicated browser search worker; no production server full-corpus scan.  |
| `lib/generated/openopps-data.json` | Package-derived provider/source metadata generated by `pnpm data:generate`. |
| `public/data/openopps-search/`  | Legacy v6 transition tree generated by `pnpm data:generate:search`.       |
| `docs/adr/0001-browser-jobs-search-engine.md` | Search-engine decision and reproducible benchmark.           |

## Editing Docs

- Add or update pages in `content/docs/*.mdx`.
- Keep `content/docs/meta.json` synchronized whenever pages are added, removed, or reordered.
- Keep docs IA and `content/docs/meta.json` aligned with the route set documented above.
- Keep examples runnable from the repository root unless the command first changes into `web/` (this package directory).
- Keep web command references aligned with the root `Justfile` (`web-*` preferred; `docs-*` aliases), GitHub Actions workflow names, and OpenSpec task names.
- Keep local credential examples non-secret; real `.env`, Kaggle, registry, and token files are ignored from the repository root.
- Keep telemetry guidance no-op by default, local event lake as canonical raw sink, and optional hosted adapters as sanitized mirrors.
- Keep v7 docs explicit about release/channel schema, source-rights gates, exact current+previous retention, v6 exit criteria, and the difference between local preparation and live rollout evidence.
- Use Fumadocs-native components for cards, callouts, tables, code blocks, and tabs when they improve scannability.
- Add shadcn/ui components with `pnpm dlx shadcn@latest add <component>` from this directory.
