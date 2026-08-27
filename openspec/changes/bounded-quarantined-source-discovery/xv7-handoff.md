# XV701–XV799 shared-surface handoff

Recorded by the Wave 1 scout lane against HEAD
`fd7bab3b4ddfad59dc4138e05905f891bcb1f44a` on 2026-08-22.

`production-hardening-static-data-v7` is still active. Remaining v7 tasks are
live Workers 5.4–5.7, v6 dual-read 2.10, and ordinary-removal / rewrite-prep
7.1–7.7. Those writers have already stopped on ingest, storage, models, and
Alembic. They have **not** stopped on source-policy evidence, public
`SourceSelector`, Kaggle, committed v6/v7 publication trees, Justfile, or
public workflows.

## XV701 — overlapping paths

v7 retains exclusive write ownership of:

| Surface | Paths |
| --- | --- |
| Ingestion / cache / CLI | `src/openopps/ingest.py`, `src/openopps/cache.py`, `src/openopps/cli.py` |
| Storage / models / migrations | `src/openopps/storage.py`, `src/openopps/models.py`, `src/openopps/alembic/` |
| Providers | `src/openopps/providers/` (tree) |
| Source-policy + public selector | `src/openopps/source_policy.py` (`SourceSelector`), `src/openopps/providers/sources/data/source_policy_evidence.json`, `src/openopps/providers/sources/data/source_policy_evidence.schema.json`, `src/openopps/providers/sources/data/portfolio_source_catalog.json`, `deployment/openopps-data/source-corpus-v6.json` |
| Shared generated / public v7 | `web/lib/generated/openopps-data.json`, `web/public/data/openopps-search/`, `deployment/openopps-data/` |
| Kaggle | `kaggle/`, `scripts/openopps_kaggle/` |
| Shared delivery | `Justfile`, `.github/workflows/` |
| Live publication scripts | `scripts/source_policy_review.py`, `scripts/docs_search_delivery.py`, `scripts/docs_search_bootstrap.py`, `scripts/verify_docs_search_artifacts.py` |

Discovery exclusive paths (`src/openopps/discovery/**`, matching discovery
tests, this OpenSpec change) were never in that set.

## XV702 — path-level handoff after prior writers stop

v7 is **not** archived.

**Handed off** to `W-STORAGE` / `W-INGEST` only (ledger zone after this
barrier). v7 remaining tasks do not write these files:

- `src/openopps/ingest.py`
- `src/openopps/storage.py`
- `src/openopps/models.py`
- `src/openopps/alembic/env.py`
- `src/openopps/alembic/script.py.mako`
- `src/openopps/alembic/versions/0001_initial_app_sqlite.py`
- `src/openopps/alembic/versions/0002_data_model_integrity.py`
- `src/openopps/alembic/versions/0003_jobs_current_version_fk.py`
- `src/openopps/alembic/versions/0004_job_sync_run_lifecycle.py`

**Not handed off.** v7 / LIVE-POLICY / LIVE-WORKERS / LIVE-KAGGLE keep
exclusive write:

- `src/openopps/cache.py`
- `src/openopps/cli.py`
- `src/openopps/source_policy.py` and the policy/catalog/corpus files above
- `src/openopps/providers/`
- Kaggle, web generated/public-data, `deployment/openopps-data/`
- `Justfile`, `.github/workflows/`
- docs-search and source-policy scripts

## XV703 — handoff-time digests

Working-tree SHA-256 matched `HEAD` for every overlapping file below at
record time (empty dirty set). Git blob IDs are `HEAD:<path>`.

| Path | git blob | sha256 |
| --- | --- | --- |
| `src/openopps/ingest.py` | `5b109884200be45ffef37c8ff16e0b9cadec24d7` | `bebb23b0801908d9e0f0ff81b4fbccbbc0f1c4d158e5531d0db900015f85ab3a` |
| `src/openopps/storage.py` | `6364c645538993572697d8855b517fc9063e022e` | `3e3854457e52b63e6353b024dee40ee53926870b72a24eb03d6257bb5e00dc20` |
| `src/openopps/models.py` | `bf887be650cae71372148a1fabe362d084ef8884` | `c2425042329d3cd8ddb7c7f53d0ea087ab991fa72cf528ccc521e9a83baff1c8` |
| `src/openopps/cache.py` | `f7debbdc41c75735eac159365e1d894f95a80e09` | `76ef0e788746f31ce98f8624f458ac4ec75ced35ddee3e62c901e1b4bd072757` |
| `src/openopps/cli.py` | `d31234213df4d3e68bb02255adb916284fa466f2` | `6d10d6c86e562182af2ef524db09b1e7672265e4a0cfc93155f9e5f39124d804` |
| `src/openopps/source_policy.py` | `68f7581daf730feaf6c01f68e4138ae296f0e4c4` | `6a21c11541353524dd4ce73a63a0f20cdbb11d28d02640cbe94fcdeb8e02347f` |
| `src/openopps/alembic/env.py` | `ce4b863c9ead1fb2111a04ec0c303daefab8e685` | `5ce7e592b80c7081183f602f9c6877b520a158444114c36ae6249eb502dbcbc8` |
| `src/openopps/alembic/script.py.mako` | `2d8e5a04ba3dfee6a1acfbac5f7216301652a75d` | `5902e5ea5b6640c9235e7810bb0bd5d50b5b6c8e8b6c30106138f6cbc55ec1ca` |
| `src/openopps/alembic/versions/0001_initial_app_sqlite.py` | `20ea0127a3d691cf8e70a7b5c9ddd1cf4ed2f756` | `fd0b09d2934ab26a429be985baf7e44f8023894731388750c6d807c6563c94d7` |
| `src/openopps/alembic/versions/0002_data_model_integrity.py` | `8338bc8c582e8a61115dc0b00605ec63e509d523` | `2391e643a669664978a43871d0f196c93499d9de4b8490b7369aca9ea7de3463` |
| `src/openopps/alembic/versions/0003_jobs_current_version_fk.py` | `f6b5bb77668882c898f785b49dbb796e9b1c67b2` | `a882ed4948f07be43868d9a1107634e7d1dc58ac723006f4adc80c5cfb33e61d` |
| `src/openopps/alembic/versions/0004_job_sync_run_lifecycle.py` | `cf478aad7deca4cc0f4eb875d11836b2fb4068d2` | `e625d0c496e2163b39225f56f01ce7640a897c6c28d1969e64ae1810032fda05` |
| `src/openopps/providers/sources/data/source_policy_evidence.json` | `6a761622186641dc4ada5a87e463f5c98321f3df` | `0ec5b9ad2897f3a00dbaa07c1c132941d97d169e41668f786c8f58bf11840b22` |
| `src/openopps/providers/sources/data/source_policy_evidence.schema.json` | `492aa849ce93102996e2bb21b4d5587bbc3e3524` | `14b4c2a6ec4b1ade2d0a5860acd24180f6e23b8ee088bff6eeecf17e5a3a0089` |
| `src/openopps/providers/sources/data/portfolio_source_catalog.json` | `6e1e3d36d570fb9244dae978b55c19c78d19cf98` | `22fe30ff977509b08ee0306bf00dc03c832ce3a0c1472375e582dd948525110c` |
| `deployment/openopps-data/source-corpus-v6.json` | `58db3b1a0be4ac29520b5ecb2f04c91dc5d163a3` | `f087deb3bb4644e74cd1786f9309464ceeb3eea8527b25c549d49ad3299a9f6a` |
| `web/lib/generated/openopps-data.json` | `ceb589c4f26d793265b8a0de721002626e723f24` | `0dd26acd756d5fc1c65a6654ee2a03d2c9e7264156e7aec3cc146c36187c68e7` |
| `Justfile` | `f4a547f3035b7a946208b4487f87152b8a79cc77` | `982f50c983587dc23264ed0899145db3f86bfdc4bd0f60b93bd917791563f206` |
| `scripts/source_policy_review.py` | `eb35b3de555df48d51652171178cb3ef866cefa9` | `1ed40c448f6ec016a35f115bb5c0e52ea5bc99300d540d3892f1daef4f4e289c` |
| `scripts/docs_search_delivery.py` | `fb2a7d124438716746672444a93a7943416c4901` | `52519ec4b14d0147d3b707cf446b706015a0d9a6f2b46bdfcfcd5f62972c0227` |
| `scripts/docs_search_bootstrap.py` | `9ed261ee4a530c4f2dcf633c8da9ac6e34d8dc8b` | `76ec83e542e0b65aead2dccc220d61b09d5170ea0df0f1605337db39c6d869fb` |
| `scripts/verify_docs_search_artifacts.py` | `57e4272872a57ef7ffe596b0ef9ec47b08e8a45a` | `fd3287dacfdc251c6802d78dfeba0e7c7c42d3165027ebaa4392bcc4a7a332cd` |
| `.github/workflows/ci.yml` | `7375307c73d719713cfff0374ccefd31e5c23bfc` | `a14a5b6f4e7c97a7e77fb1669a2c38e76fa294105dddb4fcf51e5ccd3ca23e65` |
| `.github/workflows/public-data-archive.yml` | `41339b2738e4561b7cc28cd2689e02266e7985be` | `e6d0a2b0dd6cc3cf9efc090c81fa8f15c8df03e59db4a979cf08d77cf6ec4442` |

HEAD tree IDs:

| Path | git tree |
| --- | --- |
| `src/openopps/providers` | `2763a7330782732b17036f82a378df37ad98de6a` |
| `src/openopps/alembic` | `49a5c81a4726184cb3537e1737904a05a7aa5968` |
| `src/openopps/alembic/versions` | `7ca3877bff173ff8abf4c03dd22012e707179dfe` |
| `kaggle` | `f1cf47f83f9980584f67b44f5cba090a4ac2aa1b` |
| `scripts/openopps_kaggle` | `237eaa6532f64a014a2ca81707e4034f66db3a67` |
| `web/public/data/openopps-search` | `76408278d3e8ef1280c854cc9f9765592d7a1c12` |
| `deployment/openopps-data` | `96652fb04d6d3e3b142dbf3fcef3847cd702fceb` |
| `.github/workflows` | `03c632adee3dadade6042b2614b43bcce1bfd870` |

Wave 1 discovery edits are confined to `src/openopps/discovery/`,
`tests/unit/openopps/discovery/`, this OpenSpec change, and
`goals/ingest-pipeline-overhaul/maps/discovery-remainder.md`. They do not
mutate the non-handed-off rows above.

## XV799 — barrier close

- Shared-surface barrier is closed for this record.
- `W-SHARED-DELIVERY` stays **inactive**: Justfile, public workflows, and
  shared generated data were not handed off.
- `W-STORAGE` / `W-INGEST` may write only the handed-off ingest / storage /
  models / Alembic paths. Do not add `snapshot_id` to existing live tables.
  Do not create Alembic `0005` from the scout lane.
- Discovery continues to read-and-hash v7 policy, selector, catalog, and
  generated surfaces only.
- Copy this record into the v7 OpenSpec change when `W-OS` is free; this
  lane cannot write that change root.
