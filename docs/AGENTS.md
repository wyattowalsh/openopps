Fumadocs/Next.js developer docs site with a Tailwind CSS v4 and shadcn/ui theme layer.

- Treat Fumadocs as the docs framework and Tailwind/shadcn/ui as the theme layer; do not replace either without an explicit migration request.
- Write docs content in `content/docs/*.mdx` and keep the content graph in `content/docs/meta.json` aligned whenever pages are added, removed, or reordered.
- Keep frontmatter titles/descriptions concise and source-grounded. Current pages are `index`, `cli-reference`, `configuration`, `providers`, and `operations`.
- Keep project-specific site metadata in `lib/shared.ts`, shared layout options in `lib/layout.shared.tsx`, and Fumadocs source loading plus LLM-text helpers in `lib/source.ts`.
- Keep package-derived docs data in `lib/generated/openopps-data.json`; it is generated from `../src/openopps/docs_data.py` by `pnpm data:generate` and is refreshed automatically before `pnpm types:check` and `pnpm build`.
- Keep Fumadocs MDX collection settings in `source.config.ts`; `includeProcessedMarkdown` supports `app/llms.txt/`, `app/llms-full.txt/`, and per-page markdown routes under `app/llms.mdx/`.
- Read `../DESIGN.md` before changing theme tokens, typography, colors, spacing, or shadcn/ui component variants.
- Add shadcn/ui components with `pnpm dlx shadcn@latest add <component>` from `docs/`, then import or expose them through MDX as needed.
- Prefer Fumadocs-native MDX components for callouts, cards, tables, code blocks, and tabs.
- Keep custom MDX component wiring in `components/mdx.tsx`; expose project-specific components there instead of importing ad hoc implementations from content pages.
- Keep examples runnable from the repository root unless a command explicitly starts with `cd docs`.
- Keep image and favicon assets under `public/`; use existing `public/brand/openopps-logo.png` for OpenOpps identity unless replacing the full asset set.
- Use path alias imports such as `@/lib/source` and `@/components/ui/button` in docs app code.

Validation commands from `docs/`:

```bash
pnpm install
pnpm data:generate
pnpm dev
pnpm types:check
pnpm build
pnpm lint
```

Use `pnpm types:check` after MDX/content graph edits because it runs `fumadocs-mdx`, `next typegen`, and `tsc --noEmit`.
