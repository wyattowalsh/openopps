---
version: "alpha"
name: "OpenOpps Route Ledger"
description: "A Monaspace-first docs interface for a CLI that discovers public hiring boards, resolves provider routes, and exports normalized jobs."
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
    fontSize: "4.5rem"
    fontWeight: "700"
    lineHeight: "0.9"
    letterSpacing: "-0.075em"
    fontFeature: "ss01, ss02, calt, liga"
  h1:
    fontFamily: "Monaspace Argon"
    fontSize: "3.25rem"
    fontWeight: "700"
    lineHeight: "0.95"
    letterSpacing: "-0.065em"
  h2:
    fontFamily: "Monaspace Argon"
    fontSize: "2rem"
    fontWeight: "700"
    lineHeight: "1.05"
    letterSpacing: "-0.055em"
  body:
    fontFamily: "Monaspace Neon"
    fontSize: "1rem"
    fontWeight: "400"
    lineHeight: "1.7"
    letterSpacing: "-0.018em"
    fontFeature: "ss01, ss02, ss03, calt, liga"
  label-caps:
    fontFamily: "Monaspace Neon"
    fontSize: "0.75rem"
    fontWeight: "600"
    lineHeight: "1.1"
    letterSpacing: "0.28em"
  code:
    fontFamily: "Monaspace Xenon"
    fontSize: "0.9375rem"
    fontWeight: "400"
    lineHeight: "1.6"
rounded:
  sm: "5px"
  md: "8px"
  lg: "12px"
  xl: "18px"
  panel: "28px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "48px"
  3xl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.md}"
    padding: "12px"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.md}"
    padding: "12px"
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.panel}"
    padding: "24px"
  muted-panel:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.xl}"
    padding: "16px"
  badge-accent:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.lg}"
    padding: "8px"
  rule-border:
    backgroundColor: "{colors.border}"
    textColor: "{colors.foreground}"
    height: "1px"
  code-block:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.background}"
    typography: "{typography.code}"
    rounded: "{rounded.lg}"
    padding: "16px"
  status-success:
    backgroundColor: "{colors.success}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "4px"
  status-warning:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.sm}"
    padding: "4px"
  status-error:
    backgroundColor: "{colors.error}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "4px"
  status-info:
    backgroundColor: "{colors.info}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.sm}"
    padding: "4px"
---

# Design System — OpenOpps Route Ledger

## Overview

OpenOpps should feel like a field instrument for the public hiring web: part route map, part terminal ledger, part analyst workbench. The design is not a generic SaaS docs site. It should make the messy provider landscape feel inspectable and controllable.

The visual thesis is **warm terminal cartography**. Monospace typography carries the interface, a parchment-and-pine palette keeps the product grounded, and small data-console details make the docs feel close to the CLI without turning the page into a gimmick.

## Colors

The palette is intentionally restrained: warm paper, pine ink, brass highlights, and provider-status semantic colors.

- **Primary (#2f6f50):** Pine route green. Use for CTAs, active states, route health, and successful provider matches.
- **Accent (#d99629):** Brass marker. Use sparingly for highlights, export modes, and important metadata.
- **Background (#f7f1df):** Warm ledger paper. Avoid pure white; the docs should feel worked-in and durable.
- **Foreground (#1d281f):** Deep green-black ink for body copy and headlines.
- **Card (#fff9ea):** Elevated paper surface for panels, cards, and callouts.
- **Border (#cfc1a6):** Muted ruled-line color. Borders should feel drawn, not chrome.
- **Error (#b84832):** Clay red for route failures or destructive states.
- **Info (#336d8f):** Blue registry signal for neutral diagnostics and route metadata.

Dark mode should invert the material: pine-black background, warm cream text, brighter green active states, and reduced saturation for large fills. Keep brass accents, but avoid neon-on-black cyberpunk.

## Typography

The product should be all-Monaspace by default because the domain is CLI-first and table-heavy. This is a deliberate risk: most docs sites use proportional sans fonts for comfort. OpenOpps should instead own the developer-tool feel and make tables, flags, provider IDs, and route tokens visually native.

- **Display:** Monaspace Argon, 700. Use for hero headlines and major page titles. It has enough personality to make all-mono feel designed rather than accidental.
- **Body/UI:** Monaspace Neon, 400-600. Use for navigation, prose, buttons, cards, and labels.
- **Code/Data:** Monaspace Xenon, 400-600. Use for code blocks, command snippets, provider IDs, status rows, and metrics.

Use contextual alternates and ligatures: `ss01`, `ss02`, `ss03`, `calt`, and `liga`. Tracking should be tighter than default for large type and slightly tighter for body text. Caps labels should be widely tracked.

## Layout

The layout approach is **grid-disciplined with editorial hero moments**.

Docs pages should remain predictable: readable content width, stable side navigation, visible table of contents, and Fumadocs-native content components. Landing and overview pages can be more expressive, using asymmetric panels, data cards, and terminal-like provider tables.

Guidelines:

- Use a 12-column mental grid for landing pages.
- Keep docs prose comfortable, roughly 70-85 characters per line.
- Use dense panels for CLI examples and provider status, but do not let dense UI invade long-form prose.
- Prefer ruled borders, inset dividers, scanline textures, and subtle grid backgrounds over blobs or glossy gradients.
- Radius should be hierarchical: small controls at 8px, cards at 18px, major panels at 28px.

## Elevation & Depth

Depth should feel like layered paper and terminal glass, not floating app chrome.

- Use translucent cards over the ledger-grid background.
- Use large, soft shadows only for major panels.
- Prefer inner shadows on command consoles and route tables.
- Avoid generic drop shadows on every component.

## Shapes

OpenOpps uses soft utility shapes rather than bubbly SaaS shapes.

- Buttons: medium radius, clear borders, tiny lift on hover.
- Panels: large radius, ruled border, translucent paper fill.
- Badges: pill radius only for metadata chips.
- Code blocks: medium radius with strong contrast.

## Components

Component behavior should reinforce the CLI/workbench feeling.

- **Primary buttons:** Pine fill, warm text, small upward hover movement, visible focus ring.
- **Secondary buttons:** Paper fill with ruled border, no gradient fill.
- **Cards:** Use `opps-panel` treatment when a card represents a system object: provider, source, export, route probe, or storage mode.
- **Tables:** Use tabular-feeling rhythm, visible row separation, and status color only where it carries meaning.
- **Code blocks:** Always show runnable commands. Avoid decorative code that cannot be pasted.
- **Callouts:** Prefer Fumadocs-native callouts, but tune content to operational guidance: risk, constraint, workaround, or verification.

## Do's and Don'ts

Do:

- Use Monaspace fonts for all UI surfaces unless a concrete readability issue appears.
- Make route/provider/status data feel first-class.
- Use warm neutrals and pine/brass accents consistently.
- Keep CLI examples runnable from the repository root.
- Add visual detail with grids, ruled lines, scanlines, and data panels.

Don't:

- Use purple gradients, generic three-card feature grids, or centered-everything SaaS sections.
- Mix in Inter, Roboto, Arial, or other default proportional fonts without explicit approval.
- Add decoration that competes with code examples and tables.
- Use color as the only indicator for route health or provider support.
- Make docs pages so expressive that they become harder to scan.

## Decisions Log

| Date       | Decision                                   | Rationale                                                                                                          |
| ---------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 2026-05-16 | Created Google `design.md`-style DESIGN.md | Gives coding agents machine-readable tokens plus prose guidance before future UI work.                             |
| 2026-05-16 | Adopted Monaspace Argon, Neon, and Xenon   | User prefers Monaspace fonts; the CLI/provider/table-heavy product benefits from an all-mono identity.             |
| 2026-05-16 | Chose warm terminal cartography            | Distinguishes OpenOpps from generic SaaS docs while matching route probing, source catalogs, and job-data exports. |
