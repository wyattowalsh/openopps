# provider-source-scope-hygiene — tasks

- [ ] Keep WorkAtAStartup out of the packaged source catalog; document YC as the preferred startup-board source and add regression coverage where the catalog is enumerated.
- [ ] Document or test Wellfound/Angel: either static no-auth source support with tests, or explicit unsupported release rationale in provider/source docs and coverage output.
- [ ] Audit `Editorial` and `Editiorial` source labels across persisted boards and source payloads; record findings before adding any provider identity.
- [ ] Add provider detection for Editorial-labeled boards only when a generic public provider route is proven through route probe evidence.
- [ ] Update README, docs providers/operations pages, and OpenSpec provider-ingestion requirements after decisions are locked.
- [ ] Run `uv run pytest` for touched provider/source tests and `npx -y @fission-ai/openspec@1.6.0 validate --all --strict`.