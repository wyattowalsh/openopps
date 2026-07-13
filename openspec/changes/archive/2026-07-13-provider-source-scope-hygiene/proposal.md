## Summary

Close deferred v0.1 provider and source-scope hygiene: keep WorkAtAStartup out of scope, document Wellfound/Angel outcomes, and audit Editorial source labels before any new provider identity.

## Motivation

`prepare-v0-1-release` deferred tasks 27–28 so v0.1 ship lanes could finish without blocking on marginal source providers. YC remains the preferred startup-board source; WorkAtAStartup must not duplicate that surface. Wellfound/Angel and Editorial/Editiorial labels need explicit release rationale or proven public routes before adoption.

## Scope

- Confirm WorkAtAStartup stays out of the packaged source catalog in favor of the existing YC source provider.
- Document or test Wellfound/Angel as static no-auth source support or record explicit unsupported release rationale.
- Audit `Editorial` / `Editiorial` source labels and add provider detection only when a real public provider route is proven.

## Non-goals

- Browser-driven, authenticated, or anti-bot bypass extraction in core CLI.
- Promoting detect-only providers to job-capable without a coverage audit pass.

## Success criteria

1. Release docs and tests reflect WorkAtAStartup exclusion and YC preference.
2. Wellfound/Angel outcome is documented with tests or explicit unsupported rationale.
3. Editorial label audit is complete with a recorded decision before any new provider id.