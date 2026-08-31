---
name: openopps-sources
description: >-
  Check configured OpenOpps source catalogs with list and show. Use when the user asks which sources exist. NOT for scout, verify-scout, preview-promotion, or admin registration.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps sources

Public source catalogs. Listing is not scouting.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | `openopps sources list --json`. |
| `show <key>` | `openopps sources show`. |
| `sync` | `openopps sources sync` (hand off to sync skill if the run is broader). |
| `scout` / `verify-scout` / `preview-promotion` | Refuse; those are quarantined (`openopps-dev`). |
| `add` / `admin` | Hand off to `openopps-admin` (not discovery aliases). |

## Permission posture

List/show are reads. Sync writes boards from catalogs. Never run scout aliases from this skill.

## Critical Rules

1. Always treat `sources list/show` as catalog reads, not discovery.
2. Never run `admin sources scout|verify-scout|preview-promotion`.
3. Do not perform source-policy 1780 publication.
4. Must refuse scout aliases even if the user says "find sources".
5. Never share this work with `openopps sync` as if it were scout.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `sources list` | Show configured source catalog rows. |
| `sources sync` | Public catalog refresh; not scout. |
| `admin sources scout` | Quarantined alias; refuse. |

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
| `references/recipes.md` | Sources command strings | After dispatch |
