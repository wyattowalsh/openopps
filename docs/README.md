# OpenOpps Docs Site

This directory contains the OpenOpps developer documentation site built with Next.js, Fumadocs, MDX, Tailwind CSS, and shadcn/ui.

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

From the repository root, the equivalent contributor shortcuts are:

```bash
just docs-check
just docs-build
just docs-function-trace-check
just docs-search-index
just docs-search-index-check
just docs-lint
just docs-test
just docs-rtk-lint
```

`pnpm types:check` and `pnpm build` both refresh `lib/generated/openopps-data.json` through `pnpm data:generate`, so treat generated docs data as part of the docs validation surface.
`just docs-build` runs the production Next.js build and then `just docs-function-trace-check`, which verifies API route traces do not bundle the committed `public/data/openopps-search/` tree into a server function.
`pnpm data:generate:search` refreshes the committed static snapshot used by Jobs (`/`) and Explorer (`/explorer`) from `../kaggle/openoppsdb.sqlite`; it is explicit because that SQLite file is local and ignored by git. Run `just docs-search-index-check` from the repository root before release when refreshing the committed snapshot; it requires the local SQLite file, regenerates the search index, and fails if `public/data/openopps-search/` remains dirty. The generated `public/data/openopps-search/` tree is intentionally committed and can be tens of megabytes so the hosted docs can search, dashboard, and preview jobs without a live backend. Job previews show full description text only when the snapshot contains normalized description fields; otherwise they remain metadata-first and link back to the source posting.
`just docs-rtk-lint` is the optional maintainer lint surface for `rtk`; it is explicit and outside the default `just ci`/GitHub Actions path.

Current docs IA routes are `index`, `cli`, `configuration`, `data-model`, `providers`, `operations`, and `contributing`. The jobs workbench lives at `/`; the data dashboard lives at `/explorer`.

## Telemetry

Docs telemetry is disabled by default. The browser client only sends events when `NEXT_PUBLIC_OPENOPPS_TELEMETRY_ENABLED=true`; the API route accepts sanitized batches at `/api/telemetry` and noops unless a server-side sink or mirror is configured.

For a local zero-cost event lake, run the docs app with a writable telemetry directory:

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
| `app/(home)/page.tsx`           | Jobs workbench route for the docs app root.                              |
| `app/docs/[[...slug]]/page.tsx` | Fumadocs documentation page renderer.                                    |
| `app/api/search/route.ts`       | Fumadocs search route.                                                   |
| `app/api/telemetry/route.ts`    | Telemetry intake route with noop, local event-lake, and optional PostHog forwarding. |
| `components/`                   | MDX and shadcn/ui component wiring.                                      |
| `lib/telemetry.ts`              | Browser telemetry queue, sanitizer, and shared event types.              |
| `lib/generated/openopps-data.json` | Package-derived provider/source metadata generated by `pnpm data:generate`. |
| `public/data/openopps-search/`  | Static board, provider, latest-job, and job-detail index generated by `pnpm data:generate:search`. |

## Editing Docs

- Add or update pages in `content/docs/*.mdx`.
- Keep `content/docs/meta.json` synchronized whenever pages are added, removed, or reordered.
- Keep docs IA to the route set documented above unless a product change explicitly expands it.
- Keep examples runnable from the repository root unless the command first changes into `docs/`.
- Keep docs command references aligned with the root `Justfile`, GitHub Actions workflow names, and OpenSpec task names.
- Keep local credential examples non-secret; real `.env`, Kaggle, registry, and token files are ignored from the repository root.
- Keep telemetry guidance no-op by default, local event lake as canonical raw sink, and optional hosted adapters as sanitized mirrors.
- Use Fumadocs-native components for cards, callouts, tables, code blocks, and tabs when they improve scannability.
- Add shadcn/ui components with `pnpm dlx shadcn@latest add <component>` from this directory.
