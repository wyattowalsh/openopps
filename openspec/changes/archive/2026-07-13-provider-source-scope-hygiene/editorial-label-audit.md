# Editorial / Editiorial label audit

## Scope

Audit upstream Consider `job_sources` labels and persisted provider-hint exports before
registering any `editorial` provider identity.

## Evidence (2026-07-10)

- Packaged adapters: no `editorial` or `editiorial` board provider or source adapter in
  `src/openopps/providers/`.
- Provider registry: `provider_registry().get("editorial")` is `None`.
- Committed docs search snapshot (`docs/public/data/openopps-search/providers.json`):
  regression test `test_committed_providers_snapshot_editorial_hints_are_metadata_only`
  scans all provider rows; any `Editorial` / `Editiorial` hints remain unsupported
  metadata with `registerProviderIdentity: false`.
- Misspelling `Editiorial`: no packaged detection path; treated the same as `Editorial`.

## Decision

- Preserve `Editorial` / `Editiorial` hints as detect-only metadata via
  `source_hint_support_level` (unsupported registry ids downgrade to `detect`).
- Do **not** add a job-capable `editorial` provider or URL route detector until route-probe
  evidence proves a generic public fetch path across multiple boards.