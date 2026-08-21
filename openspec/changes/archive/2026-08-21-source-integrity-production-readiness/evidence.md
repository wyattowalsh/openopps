# source-integrity-production-readiness - release evidence

## Exact source revision

- Git revision: `8e3c797b975a1f79844c1906e96c0993d88ab1f1`
- Conventional commit: `fix(kaggle): harden partial timeout recovery`
- Local `HEAD`, `origin/main`, and remote `main` matched this exact revision.

## Release gates

- GitHub Actions run `32494813709` completed successfully for the exact revision.
- Python 3.12 wheel/catalog smoke built and installed `openopps-0.1.0-py3-none-any.whl` and reported `wheel-catalog-smoke ok`.
- Python 3.12, 3.13, 3.14, lowest-direct, Web, Security, OpenSpec, generated-artifact, and wheel/SBOM/attestation jobs completed successfully. The direct-push dependency-review job was expectedly skipped.
- GitHub production deployments `6023829105` (`openopps`) and `6023807551` (`openopps-hla2`) completed successfully for the exact revision.

## Production smoke

The stable aliases `https://www.openopps.dev` and `https://openopps-hla2.vercel.app` each passed the Chromium semantic route suites in `web/tests/e2e/routes.spec.ts` and `web/tests/e2e/seo-static.spec.ts` (5 tests per alias). The checks covered the home route, canonical redirects, one rich job detail page and API response, robots, root sitemap, and job sitemap behavior.

Both aliases also passed explicit public GET assertions for `/`, `/explorer`, `/docs`, `/docs/public-data-releases`, `/llms.txt`, `/llms-full.txt`, `/llms.mdx/docs/content.md`, `/llms.mdx/docs/providers/content.md`, `/robots.txt`, `/sitemap.xml`, and `/data/openopps-search/manifest.json`. The stale-client `/api/jobs/search` boundary returned its required fail-closed `410` response.

The route `/llms.mdx` is intentionally not an aggregate index and correctly returns `404`. Per-page Markdown is served under `/llms.mdx/docs/<slug>/content.md`; aggregate LLM exports remain `/llms.txt` and `/llms-full.txt`.

These checks were read-only. They did not mutate Cloudflare, Kaggle, Vercel configuration, or public data.
