# OpenOpps Docs Site

This directory contains the OpenOpps developer documentation site built with Next.js, Fumadocs, MDX, Tailwind CSS, and shadcn/ui.

## Commands

Use pnpm from this directory:

```bash
pnpm install
pnpm dev
pnpm types:check
pnpm build
pnpm lint
```

The development server opens at `http://localhost:3000`.

## Layout

| Path                            | Purpose                                                                  |
| ------------------------------- | ------------------------------------------------------------------------ |
| `content/docs/`                 | MDX documentation pages.                                                 |
| `content/docs/meta.json`        | Fumadocs navigation order and section title.                             |
| `source.config.ts`              | Fumadocs MDX collection configuration.                                   |
| `lib/source.ts`                 | Fumadocs content loader, LLM text helpers, and Open Graph image helpers. |
| `lib/shared.ts`                 | Project name, docs routes, and GitHub repository metadata.               |
| `lib/layout.shared.tsx`         | Shared Fumadocs layout options.                                          |
| `app/(home)/page.tsx`           | Landing page for the docs app.                                           |
| `app/docs/[[...slug]]/page.tsx` | Fumadocs documentation page renderer.                                    |
| `app/api/search/route.ts`       | Fumadocs search route.                                                   |
| `components/`                   | MDX and shadcn/ui component wiring.                                      |

## Editing Docs

- Add or update pages in `content/docs/*.mdx`.
- Keep `content/docs/meta.json` synchronized whenever pages are added, removed, or reordered.
- Keep examples runnable from the repository root unless the command first changes into `docs/`.
- Use Fumadocs-native components for cards, callouts, tables, code blocks, and tabs when they improve scannability.
- Add shadcn/ui components with `pnpm dlx shadcn@latest add <component>` from this directory.
