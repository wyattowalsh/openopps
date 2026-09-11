---
name: openopps-url-pull
description: >-
  Extract a public ATS board or posting from a URL. Use when the user pastes a careers URL or asks for jobs pull. NOT for catalog sync, board listing, or discovery.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps URL pull

Resolve `openopps <URL>` and `openopps jobs pull <URL>` to the same pull service.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| A public HTTPS URL | Run `openopps <URL>` (or `jobs pull`) with `--json` for machines. |
| `list` / `get` / `auto` | Pass `--operation auto|list|get`. |
| `save` | Add `--save` only when the user asked to persist a complete validated result. |
| `no-save` / ephemeral | Default. `--no-save` is the explicit alias. |
| Empty | Explain both spellings, operations, opt-in `--save`, and that this is not discovery. |
| `sync` / `discovery` / `scout` | Refuse and hand off. |

## Permission posture

May shell `openopps` / MCP `run` for URL pulls. Do not scout, mutate catalogs, or call `/api/`.

## Critical Rules

1. Always use the same workflow for `openopps <URL>` and `openopps jobs pull <URL>`.
2. Never treat this operational pull as quarantined discovery or catalog fill.
3. Identity is reserved `url-pull` plus a punctuation-preserving digest. Unscoped `jobs sync` excludes those routes.
4. `--save` is opt-in (default False). `--no-save` is ephemeral. HTTP cache is independent. Persist failure exits 9.
5. Complete-before-apply: membership and authority must validate before any ledger write.
6. Must prefer `--json`; use `--metrics-file` or `--raw` for pull observability, never `--metrics-json`.
7. Always fail closed on ambiguity, unsupported ATS, or incomplete board scans.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `jobs pull` | URL ingest of one board or posting. |
| `openopps <url>` | URL-first alias for jobs pull. |
| `--save` | Opt-in reserved `url-pull` ledger persist. |
| `catalog sync` | Staged sync; hand off, do not pull. |

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
| `references/recipes.md` | Pull command strings | After dispatch |
