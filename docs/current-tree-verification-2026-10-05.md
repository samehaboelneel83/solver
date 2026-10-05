# Current-tree verification — 5 October 2026

## Outcome

The current working tree passes the full frontend suite, frontend production build and ESLint, plus focused backend checks covering drafts, the Assistant and recent data/export work.

| Check | Result | Evidence |
| --- | --- | --- |
| Full frontend suite | **3,382 tests passed in 220 files**; no final unhandled errors | `../verification-frontend-tests.log` |
| Focused frontend rerun | 23 tests passed in five files | `../verification-frontend-focused.log` |
| Frontend production build | Passed; 1m 39s in this run | `../verification-frontend-build.log` |
| Frontend lint | Passed | `../verification-frontend-lint.log` |
| Focused backend | **59 tests passed**; 221 deprecation warnings | `../verification-backend-tests.log` |

Backend files tested: `test_api_drafts.py`, `test_agent.py`, `test_agent_store.py`, `test_agent_compact.py`, `test_auto_records.py`, `test_run_dxf.py`. The current backend source was mounted read-only into the installed backend image. A dedicated Docker network and fresh PostgreSQL 16 container were used; the test database was `verification_test`. Disposable JWT/admin configuration was supplied. The container and network were removed afterward. The full backend suite and live local-model calls were not run.

## Findings and corrections

The initial frontend run reported five failing assertions and two unhandled errors.

- Goal breakdown, map counts and import previews correctly localized numbers using the host locale, while tests assumed English digits and grouping. Assertions now compare the localized representations, preserving the existing product behavior.
- The relationship editor test fixture returned a relationship-write object for the entity-tree read endpoint. It now supplies the correct `{entity_id, trees}` response, eliminating unhandled render errors.
- Only the five affected test files were changed for these corrections. Other agents' application changes and deletions remain in place.

A sandbox denial prevented Vitest from writing its results cache. Tests were rerun with approved access. The initial disposable backend setup lacked a required JWT secret; the corrected configuration passed. These setup failures were not application defects.

## Build observations

The application now uses split bundles. The main index bundle was approximately 127 KB before gzip; ModelEditor approximately 318 KB, Blockly approximately 698 KB and the graph library bundle approximately 1.92 MB. These figures describe emitted files, not measured first-load transfer or user-perceived performance. A clean-machine offline installation was not tested.

## Deployment observations and remaining checks

At review time, Docker listed frontend, backend, solver worker, PostgreSQL, ClickHouse and tileserver containers. The ingestion worker/reference containers from the September installation were absent. Their intended deployment must be reconciled with the modified Compose configuration before rollout.

Inspecting the installed backend test runtime reported a PostgreSQL collation-version mismatch. This should be investigated and resolved using a database maintenance plan; it was not altered here.

Before a release:

1. Review the substantial uncommitted Assistant/solver/configuration changes, camp removals and migrations 0106–0110 as coherent changesets.
2. Run the full backend suite and confirm installed dependencies match the modified requirements.
3. Verify migration state and data-retention implications; do not apply camp-removal migrations solely because tests pass.
4. Exercise authenticated browser journeys and the configured local model, including approval, failure/retry, file import, server drafts and graph editing.
5. Reconcile ingestion deployment and PostgreSQL collation maintenance, then build/deploy an identified revision and verify health.

No commit, production migration, deployment, data wipe or production-data cleanup was performed in this verification increment. The live-model field-test scores in other documents remain separately reported historical evidence.

## Follow-up check — after commits `90a60fc` and `bfe0880`

The frontend suite still passes all **3,382 tests in 220 files**, and its production build and lint pass. Vitest writes the results cache under an ignored workspace-local directory so the suite exits cleanly where `node_modules` is read-only. Docker BuildKit's static check passed for the offline backend build path, and in-memory compilation accepted all 610 Python files.

The broad backend suite recorded 4,860 passes and 25 skips, with 8 failures and 4 errors. The affected checks were rerun in a properly isolated setup: the repository's `scripts/` and `deploy/` paths were mounted where the tests expect them, ClickHouse used disposable test credentials, and the exact connected-grid CP-SAT test was restricted to one worker to avoid timeout noise under full-suite load. All 64 rerun checks passed. The first run did not alter application data; its databases and internal-only Docker network were disposable and removed afterward.

The Assistant sandbox now defaults off, and the running backend was recreated with `AGENT_RUN_PYTHON=0`. `/api/health/details` reports PostgreSQL, migration **0110**, the solver worker, and ClickHouse healthy.

PostgreSQL still warns that databases were created at collation version 2.41 while the running image provides 2.31. This is an image/data-version mismatch, not an application health failure. Reindexing affected objects must precede refreshing the recorded collation versions. The live `solver` database is about 191 MB and has 27 valid collation-dependent indexes; no index maintenance was run during this check.

Offline image rebuild documentation and Dockerfile behavior now agree: `OFFLINE=1` skips apt, base images and Python/npm caches must already be local, and PDF export falls back to the printable report if the supplied backend base image lacks Pango. The standard offline bundle path transfers prebuilt images.

The corrected full backend run has now completed: **4,872 passed, 25 skipped** in 1,695.59 seconds. It used disposable PostgreSQL and ClickHouse services and an internal-only Docker network; those resources were removed after the run. The only reported test warnings were deprecations and inability to write pytest cache files in the read-only container. This supersedes the earlier incomplete full-suite result above. The live PostgreSQL collation mismatch remains untouched.
