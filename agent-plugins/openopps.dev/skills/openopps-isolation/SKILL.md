---
name: openopps-isolation
description: >-
  Validate untrusted scout suggestions only via launch_isolated_scout. Use when accepting fixture or suggestion bytes. NOT for direct parsers, wagents apply, network, or OS-sandbox claims.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps isolation

Application-level isolated scout. Not an OS sandbox claim.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | State the only acceptance path and what isolation is not. |
| `accept` / `launch` / fixture | Route through `openopps.discovery.isolation.launch_isolated_scout` (committed fixtures: `validate_fixture.py`). |
| `validate_data_only_suggestion` as acceptance | Refuse; that is not the acceptance path. |
| `wagents --apply` / install / sync | Refuse. |
| `sync` | Refuse. |

## Permission posture

Credential-free, allowlisted worker, bounded pipes/time, parent-owned new quarantine file only. No Git, DB, plugins, or credentials.

## Critical Rules

1. Always submit acceptance only through `openopps.discovery.isolation.launch_isolated_scout`.
2. Never treat skill prose as confining the parent harness.
3. Do not import `openopps.cli`, storage, providers, or HTTP from fixture validators beyond the isolated path.
4. Do not claim OS-wide writable-path guarantees.
5. Never write `.agents/skills/` or `.cursor/skills/` harness projections.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `launch_isolated_scout` | Only acceptance path. |
| `validate_data_only_suggestion` | Not an acceptance path. |
| `OS sandbox` | Do not claim this isolation is one. |

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
| `references/recipes.md` | Isolation invocation | After dispatch |
