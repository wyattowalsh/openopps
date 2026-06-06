# OpenOppsDB Kaggle Dataset Plan

## Solution Approach

Treat `scripts/generate_kaggle_metadata.py` as the source of truth for the Kaggle upload root and manager notebook. Extend it so the generated notebook performs the daily full sync, records private run evidence, validates snapshot quality before publishing, exports every table, prunes private evidence, and versions the Kaggle dataset only after hard gates pass.

Keep credentialed Kaggle deployment as an explicit local/live step, not a CI step. CI should prove deterministic generation, schema coverage, and non-live validation. The live deployment pass should use Kaggle CLI credentials, publish the dataset and connected manager notebook, then verify the live dataset status, files, metadata, and manager notebook availability.

## Ordered Steps

1. Reconfirm repo state, classify dirty work, and set the cleanup path.
   - Touches: git worktree only.
   - Check `git status --short --branch` and preserve the existing dirty work in `scripts/generate_kaggle_metadata.py`, `tests/unit/openopps/test_kaggle_metadata.py`, provider/cache/migration files, and generated docs data.
   - Check the active OpenSpec change with `just openspec-status` or `OPENOPPS_OPENSPEC='pnpm dlx @fission-ai/openspec@latest' just openspec-status`.
   - Classify current dirty changes as either part of this Kaggle/dataset hardening path or separate already-started release-hardening work, then clean them up without reverting user work.
   - Verification: branch is still an approved work branch for mutation, unrelated dirty files are not reverted, the OpenSpec surface for this workflow is identified before edits, and the final implementation will leave a validated clean worktree except for explicitly ignored local artifacts.

2. Add or update OpenSpec requirements for the Kaggle dataset workflow.
   - Touches: `openspec/changes/prepare-v0-1-release/specs/...`, `openspec/changes/prepare-v0-1-release/tasks.md`.
   - Add requirements for a daily full OpenOppsDB dataset run, generated SQLite/CSV/Parquet artifacts, field-level Kaggle metadata, private quality-gated evidence, provider-error classification, and live post-deploy verification.
   - Keep CI non-secret and live Kaggle deployment local/manual.
   - Verification: `rtk npx -y @fission-ai/openspec@latest validate "prepare-v0-1-release" --strict` and `rtk npx -y @fission-ai/openspec@latest validate --all --strict`.

3. Align the generated manager notebook around a daily full snapshot.
   - Touches: `scripts/generate_kaggle_metadata.py`, generated `kaggle/openoppsdb-manager.ipynb`.
   - Replace the current multi-daily example text with one explicit daily cron target.
   - Preserve the default `OPENOPPS_PACKAGE_SPEC=git+https://github.com/wyattowalsh/openopps.git@main` and the override for controlled testing.
   - Preserve the prior-ledger copy into `/kaggle/working/openoppsdb/openoppsdb.sqlite`.
   - Ensure the sync command remains unfiltered: `openopps sync --metrics-json`.
   - Verification: focused notebook metadata tests assert the dataset id, manager id, daily cadence text, GitHub package install, prior DB copy, `admin db init`, unfiltered sync, artifact generation before publish, and no wheel-only path.

4. Capture private run evidence during the manager run.
   - Touches: `scripts/generate_kaggle_metadata.py`, generated `kaggle/dataset-metadata.json`, generated notebook.
   - Capture `sync_metrics.json` from `openopps sync --metrics-json`.
   - Capture `status.json` from `openopps status --json`.
   - Capture `coverage.json` from `openopps providers coverage --json` if the local command remains persisted-data-only and useful for quality gating.
   - Keep the evidence files private to the manager quality gate and prune them before dataset publication.
   - Verification: tests assert private evidence files are not declared as dataset resources and the notebook writes them before pruning.

5. Implement snapshot quality gates before publishing.
   - Touches: `scripts/generate_kaggle_metadata.py`, likely a focused helper function embedded in the generated notebook or a generated helper script.
   - Hard-block on subprocess failures, unreadable/missing SQLite DB, missing required tables, missing required generated files, schema/export failures, invalid metadata JSON, failed Kaggle dataset version/create, failed manager notebook push, or failed post-upload status/version check.
   - Hard-block on structurally unusable data: no enabled source evidence, no boards, no executable route evidence after a prior healthy ledger, or no current/persisted jobs without a documented first-run or upstream-outage explanation.
   - Treat provider/source errors as non-blocking only when they are classified in `providerErrors` and `providerErrorDetails`, the dataset remains internally consistent, and successful evidence still supports a defensible full-dataset snapshot.
   - Block hidden, unclassified, or dominant provider failures. A conservative initial rule should block when executable routes exist but `jobSyncRuns` is zero, when current jobs are zero without an explicit explanation, or when provider failures make the status/coverage evidence contradict a full-dataset claim.
   - Write a private `snapshot-quality.json` report that records pass/fail status, hard blockers, warnings, counts, metrics excerpts, provider error summaries, required-file checks, and any explicit empty/outage explanation.
   - Verification: unit tests cover passing quality data, structural blockers, empty-job blockers, classified provider warnings, and hidden/unclassified/dominant provider blockers.

6. Keep full table export and metadata coverage complete.
   - Touches: `scripts/generate_kaggle_metadata.py`, generated `kaggle/dataset-metadata.json`, generated SQLite metadata tables.
   - Preserve the existing behavior that drops `http_cache`, writes `openopps_tables` and `openopps_columns`, checkpoints SQLite, and exports every table to CSV and Parquet.
   - Ensure every SQLite table still has CSV/Parquet exports and table/column metadata, and every CSV/Parquet resource has field names, titles, descriptions, and supported Kaggle field types.
   - Verification: `uv run pytest tests/unit/openopps/test_kaggle_metadata.py -q` plus an export test against a temporary SQLite DB verifying every declared public data artifact exists and every CSV/Parquet field is described.

7. Add local deployment and verification recipes.
   - Touches: `Justfile`, `README.md`, `docs/content/docs/operations.mdx`.
   - Add or document recipes for local bundle validation, live dataset create/version, manager notebook push, and live verification.
   - Keep commands thin wrappers around Kaggle CLI and existing generation commands.
   - Use the local credential pattern already documented: `KAGGLE_API_TOKEN="$(kaggle auth print-access-token)" ...`.
   - Verification: `just --list` shows the recipes; non-live recipes run without Kaggle credentials; live recipes fail clearly when credentials are missing.

8. Update generated artifacts and docs.
   - Touches: `kaggle/dataset-metadata.json`, `kaggle/kernel-metadata.json`, `kaggle/openoppsdb-manager.ipynb`, `docs/content/docs/operations.mdx`, `README.md`, possibly `docs/lib/generated/openopps-data.json` if docs generation changes it.
   - Regenerate with `uv run python scripts/generate_kaggle_metadata.py`.
   - If a data DB is available, regenerate and inspect the full bundle with `uv run python scripts/generate_kaggle_metadata.py --data-db kaggle/openoppsdb.sqlite`.
   - Verification: `git diff --check`, generated artifact parity tests, and manual inspection of the generated notebook cells and dataset metadata descriptions.

9. Run local validation gates.
   - Touches: no new files unless generated artifacts update.
   - Run focused checks first:
     - `uv run pytest tests/unit/openopps/test_kaggle_metadata.py -q`
     - any new snapshot-quality tests
     - `uv run python scripts/generate_kaggle_metadata.py`
     - `just kaggle-meta`
     - `just --list`
   - Run broader checks:
     - `uv run pytest --cov=openopps --cov-report=term-missing`
     - `cd docs && pnpm types:check`
     - `cd docs && pnpm build`
     - `cd docs && pnpm lint`
     - `just ci`
   - Verification: record exact pass/fail output, and if `just ci` is not feasible, document the blocker and all completed substitute checks.

10. Deploy and verify live Kaggle surfaces.
    - Touches: live Kaggle dataset and manager notebook.
    - Before publishing, verify credentials without printing secrets.
    - Create the dataset if absent, otherwise version it:
      - `KAGGLE_API_TOKEN="$(kaggle auth print-access-token)" kaggle datasets create -p kaggle --public -q -t -r zip`
      - `KAGGLE_API_TOKEN="$(kaggle auth print-access-token)" kaggle datasets version -p kaggle -m "<message>" -q -t -r zip`
    - Push the connected manager notebook:
      - `KAGGLE_API_TOKEN="$(kaggle auth print-access-token)" kaggle kernels push -p kaggle`
    - Verify live status and files:
      - `kaggle datasets status wyattowalsh/openoppsdb --format json`
      - `kaggle datasets files wyattowalsh/openoppsdb --page-size 200`
      - `kaggle datasets metadata wyattowalsh/openoppsdb -p <tmpdir>`
      - `kaggle kernels status wyattowalsh/openoppsdb-manager`
      - `kaggle kernels files wyattowalsh/openoppsdb-manager --page-size 200`
    - Use Browser tools to inspect the Kaggle dataset page and manager notebook page directly, including the visible dataset files/metadata and the notebook schedule/status UI after the push.
    - Download or inspect the live dataset artifacts, then verify SQLite readability, required SQLite/CSV/Parquet files, field-level metadata, and absence of private evidence/datapackage files from the live public list.
    - Verification: final evidence includes live current version/status, file list, metadata inspection, notebook status, browser-inspected schedule/status evidence, and local read checks against downloaded live artifacts.

11. Commit the cleaned, verified implementation.
    - Touches: git history.
    - Stage only the intended implementation, generated artifacts, tests, docs, OpenSpec updates, and goal-relevant cleanup.
    - Keep commits atomic if the current dirty work separates into multiple logical changes.
    - Use conventional commit messages such as `feat: harden openoppsdb kaggle pipeline` or `fix: validate openoppsdb snapshot exports`.
    - Verification: rerun `git diff --cached --check`, confirm no unrelated files are staged, create the commit or commits, and record the final commit SHA.

## Risks And Open Questions

- The current working tree already has dirty changes and the local branch is ahead of and behind `origin/main`; the implementation should clean up, validate, manually inspect, and commit the finished work instead of leaving this state unresolved.
- Public upstream boards can produce transient rate limits and route removals. The quality gate must distinguish normal classified provider degradation from a misleading dataset version.
- Kaggle notebook scheduling must be verified through Browser tools against the live Kaggle UI after the manager notebook is pushed.
- Live deployment depends on valid Kaggle CLI credentials and may need a create-versus-version branch depending on whether `wyattowalsh/openoppsdb` already exists.
- Evidence files are intentionally private to the manager quality gate. If any evidence file is intentionally made public later, that becomes a dataset file-format change and must be described, tested, documented, and explicitly approved.
