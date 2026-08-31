---
name: openopps-providers
description: >-
  Audit public OpenOpps providers: detect, capabilities, health, coverage. Use when asking what an ATS URL is. NOT for admin probe-routes, catalog scout, or Workers.
license: MIT
metadata:
  author: OpenOpps
  version: "1.0.0"
---

# OpenOpps providers

Public provider surface: detect, inspect, capabilities, health, coverage, audit.

## Dispatch

| `$ARGUMENTS` | Action |
| --- | --- |
| Empty | Summarize public provider commands vs admin diagnostics. |
| `detect <url>` | `openopps providers detect`. |
| `inspect <url>` | `openopps providers inspect` (no persist, no job fetch). |
| `capabilities` | `openopps providers capabilities --json`. |
| `health` | `openopps providers health` (dry-run unless `--apply`). |
| `coverage` | `openopps providers coverage` (persisted SQLite only). |
| `audit` | `openopps providers audit`. |
| `probe-routes` / `registry` | Hand off to `openopps-admin`. |
| `discovery` | Refuse. |

## Permission posture

Detect/inspect/capabilities/coverage/audit are non-mutating or local-evidence. Health/probe persist only with `--apply`.

## Critical Rules

1. Always treat coverage and audit as local reads; they do not fetch live jobs.
2. Never persist health without `--apply`.
3. Do not overclaim support levels (`detect` vs `jobs`).
4. Must treat `--provider any`/`all` as no filter.
5. Never run `admin providers probe-routes` from this skill.

## Canonical vocabulary

Use these exactly. Canonical vocabulary for this skill:

| Term | Meaning |
| --- | --- |
| `providers detect` | Identify an ATS from a public URL. |
| `providers coverage` | Persisted coverage summary. |
| `probe-routes` | Admin-only; not this skill. |

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
| `references/recipes.md` | Provider command strings | After dispatch |
