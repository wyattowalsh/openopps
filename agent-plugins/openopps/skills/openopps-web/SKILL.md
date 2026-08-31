---
name: openopps-web
description: >-
  Explore public OpenOpps Jobs and Explorer pages as read-only HTTPS. Use when the user wants docs or llm-text URLs. NOT for browser drive, Next.js edits, /api/, or Workers.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps web (read-only)

Public site companion. Fetch HTTPS documents; do not drive a browser or mutate the app.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | List public routes and llm-text URLs. |
| `jobs` / home / `/` | https://www.openopps.dev/ |
| `explorer` | https://www.openopps.dev/explorer |
| `docs` | https://www.openopps.dev/docs and `/docs/agent-plugins` |
| `llms` | `/llms.txt`, `/llms-full.txt`, `/llms.mdx/docs/...` |
| `api` / `/api/` / search worker | Refuse. `/api/jobs/search` is a stale-client boundary. |
| `edit` / Next / Fumadocs / `pnpm` | Refuse; this skill does not mutate `web/`. |
| `discovery` / Workers / Kaggle | Refuse. |

## Permission posture

Read-only public HTTPS GET of documented pages. No browser drive, no cookies, no POST, no `/api/`, no Wrangler, no Kaggle.

## Critical Rules

1. Allowed hosts: `https://www.openopps.dev` (canonical).
2. Do not call `/api/` including `/api/jobs/search`.
3. Do not launch Playwright/Puppeteer/Chrome to "use the site".
4. Do not edit `web/` or run `pnpm dev` as part of this skill.
5. Do not upload Workers or mutate Kaggle.

## Public URLs

| URL | Use |
| --- | --- |
| https://www.openopps.dev/ | Jobs search workbench |
| https://www.openopps.dev/explorer | Analytics explorer |
| https://www.openopps.dev/docs | Docs index |
| https://www.openopps.dev/docs/agent-plugins | Agent Plugins packages |
| https://www.openopps.dev/llms.txt | Site LLM index |
| https://www.openopps.dev/llms-full.txt | Full LLM text |
| https://www.openopps.dev/llms.mdx/docs/... | Per-page markdown |


## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `https://www.openopps.dev` | Canonical public site host. |
| `/llms.txt` | LLM index of public docs. |
| `/api/` | Stale-client boundary; refuse. |

## Loading

Read reference files as indicated by the dispatch table. Do not load all at once.

### Progressive disclosure

Frontmatter for discovery. Load recipes on demand after dispatch. Do not load all at once.

### Classification logic

1. Always follow the dispatch table before shelling a command.
2. Never expand scope into denied command families.
3. Require explicit user intent for write or delete classes.

## Reference File Index

| File | Content | Read when |
| --- | --- | --- |
| `references/recipes.md` | Exact public URLs | After dispatch |
