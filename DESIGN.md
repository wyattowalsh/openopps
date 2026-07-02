---
version: "alpha"
name: "OpenOpps Route Ledger"
description: "A compact Monaspace-first docs and data workbench for a CLI that discovers public hiring boards, resolves provider routes, and exports normalized jobs."
colors:
  primary: "#2f6f50"
  primary-foreground: "#fbf7e8"
  secondary: "#e8dcc0"
  secondary-foreground: "#263a28"
  accent: "#d99629"
  accent-foreground: "#231f15"
  background: "#f7f1df"
  foreground: "#1d281f"
  card: "#fff9ea"
  muted: "#e9dfca"
  muted-foreground: "#575044"
  border: "#cfc1a6"
  success: "#2f6f50"
  warning: "#d99629"
  error: "#b84832"
  info: "#336d8f"
typography:
  display:
    fontFamily: "Monaspace Argon"
    fontSize: "3rem"
    fontWeight: "700"
    lineHeight: "1"
    letterSpacing: "0"
    fontFeature: "ss01, ss02, calt, liga"
  h1:
    fontFamily: "Monaspace Argon"
    fontSize: "2.35rem"
    fontWeight: "700"
    lineHeight: "1.08"
    letterSpacing: "0"
  h2:
    fontFamily: "Monaspace Argon"
    fontSize: "1.55rem"
    fontWeight: "700"
    lineHeight: "1.16"
    letterSpacing: "0"
  body:
    fontFamily: "Monaspace Neon"
    fontSize: "0.95rem"
    fontWeight: "400"
    lineHeight: "1.62"
    letterSpacing: "0"
    fontFeature: "ss01, ss02, ss03, calt, liga"
  label:
    fontFamily: "Monaspace Neon"
    fontSize: "0.75rem"
    fontWeight: "600"
    lineHeight: "1.2"
    letterSpacing: "0"
  code:
    fontFamily: "Monaspace Xenon"
    fontSize: "0.9rem"
    fontWeight: "400"
    lineHeight: "1.5"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "10px"
  panel: "12px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "12px"
  lg: "18px"
  xl: "24px"
  2xl: "32px"
  3xl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.panel}"
    padding: "16px"
  muted-panel:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.lg}"
    padding: "12px"
  badge-accent:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "2px 8px"
  rule-border:
    backgroundColor: "{colors.border}"
    textColor: "{colors.foreground}"
    height: "1px"
  code-block:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.background}"
    typography: "{typography.code}"
    rounded: "{rounded.lg}"
    padding: "12px"
  status-success:
    backgroundColor: "{colors.success}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  status-warning:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  status-error:
    backgroundColor: "{colors.error}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  status-info:
    backgroundColor: "{colors.info}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
---

# Design System - OpenOpps Route Ledger

## Overview

OpenOpps should feel like a compact field instrument for the public hiring web: part route map, part terminal ledger, part analyst workbench. The interface is CLI-first and data-heavy, so density and scan rhythm matter more than marketing drama.

The visual thesis is warm terminal cartography. Monospace typography carries the interface, paper and pine colors keep the product grounded, and small data-console details make provider routes, jobs, sources, and exports feel inspectable.

## Design Principles

- Lead with usable surfaces. Jobs, explorer dashboards, provider ledgers, and CLI references should be operational on first view.
- Keep the interface compact. Prefer tighter padding, clear dividers, short labels, and stable grids over oversized cards.
- Make provenance visible. Counts, generated data, provider support, source URLs, and export formats should show where they came from.
- Use icons for compact actions and text labels for commands that need certainty.
- Do not use negative letter spacing. Letter spacing is `0` for headings, labels, buttons, body copy, tables, and controls.
- Avoid nested cards. Use sections, dividers, tables, and compact panels instead.

## Colors

The palette is restrained: warm paper, pine ink, brass highlights, blue diagnostics, and semantic provider-status colors. Avoid letting beige surfaces dominate an entire viewport; pair warm surfaces with pine structure, blue diagnostics, and visible data states.

- Primary `#2f6f50`: route green for CTAs, active states, route health, and success.
- Accent `#d99629`: brass marker for sparse highlights and export metadata.
- Background `#f7f1df`: warm ledger paper.
- Foreground `#1d281f`: deep green-black ink.
- Card `#fff9ea`: raised paper surface for compact panels.
- Border `#cfc1a6`: ruled-line color.
- Info `#336d8f`: neutral diagnostics and registry metadata.
- Error `#b84832`: failed routes and destructive states.

Dark mode should feel like pine-black terminal glass with warm cream text. Keep large fills low saturation and reserve strong color for state, focus, and charts.

## Typography

Use Monaspace across the product.

- Display and headings: Monaspace Argon, 600-700.
- Body and UI: Monaspace Neon, 400-600.
- Code and data: Monaspace Xenon, 400-600.

Use `ss01`, `ss02`, `ss03`, `calt`, and `liga` where available. Do not rely on letter spacing for hierarchy. Use font weight, size, color, separators, and icons instead.

## Layout and Density

- Docs prose should stay readable at roughly 70-85 characters per line.
- Workbench pages should use the full viewport and avoid centered marketing layouts.
- Primary panels use 12px radius. Repeated cards, controls, inputs, chips, and rows use 4-8px radius.
- Default panel padding is 12-16px. Large section padding should be earned by content, not used as a default.
- Prefer row separators and compact metric strips over card grids when comparing data.
- Keep buttons and inputs at stable heights so hover, labels, counts, and icons do not shift layout.

## Components

- Buttons: 6px radius, no uppercase transform by default, no letter spacing, visible focus ring.
- Badges: compact, border-backed, semantic tone variants, no pill treatment unless the chip is a removable filter.
- Separators: one-pixel ruled lines with muted border color.
- Tooltips: short operational labels for icon-only actions and dense controls.
- Tables: compact row rhythm, visible row separation, tabular data alignment.
- Code blocks: high contrast, pasteable commands only.
- Callouts: use Fumadocs-native callouts for risk, constraints, workarounds, and verification.

## Jobs and Explorer Patterns

- Jobs is a workbench, not a landing page. When no job is selected, results should use the available width.
- Filters should be compact, individually removable, and backed by suggestions where generated data exists.
- Explorer is an analytics dashboard. Lead with freshness, coverage, data quality, distributions, route health, and schema/index metadata.
- Dashboard cards should be compact data panels. Do not place cards inside cards.
- Source posting and apply actions should be visually distinct and easy to verify.

## Do and Do Not

Do:

- Keep route, provider, status, and export data first-class.
- Use warm neutrals with pine, brass, blue, and semantic accents.
- Prefer ruled borders, dense tables, and terminal-like metric panels.
- Keep CLI examples runnable from the repository root.
- Keep docs snippets, generated data, just recipes, and CI commands synchronized.

Do not:

- Use purple gradients, generic feature-card layouts, decorative blobs, or centered-only SaaS sections.
- Mix in proportional fonts without explicit approval.
- Use color as the only indicator for provider support or route health.
- Add large decorative shadows to repeated items.
- Use negative or excessive letter spacing.

## Decisions Log

| Date       | Decision                                      | Rationale                                                                                                          |
| ---------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 2026-05-16 | Created Google `design.md`-style DESIGN.md    | Gives coding agents machine-readable tokens plus prose guidance before future UI work.                             |
| 2026-05-16 | Adopted Monaspace Argon, Neon, and Xenon      | The CLI/provider/table-heavy product benefits from an all-mono identity.                                           |
| 2026-05-16 | Chose warm terminal cartography               | Distinguishes OpenOpps from generic SaaS docs while matching route probing, source catalogs, and job-data exports. |
| 2026-05-24 | Normalized heading and body letter spacing    | Keeps docs and UI text predictable across responsive containers.                                                   |
| 2026-06-30 | Compact theme contract and UI primitive rules | Supports jobs and explorer workbench surfaces without large card-heavy layouts.                                    |
