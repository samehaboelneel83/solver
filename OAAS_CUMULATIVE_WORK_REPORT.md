# OaaS cumulative report — reconciliation after the other agent's work

**Reviewed:** 5 October 2026
**Current Git HEAD:** `31210c7` (3 October)
**Earlier baseline:** `472c060` (28 September)
**Review scope:** Git history, source files and documents only. No tests, build, migrations or deployment were performed during this review.

## 1. Revised current position

There are **234 commits after the previous baseline**, plus substantial uncommitted changes. The other agent has implemented several features previously listed as missing. The September report below is retained as historical evidence; its remaining-work list and deployment state are no longer current.

| Area | Evidence found | Revised status |
| --- | --- | --- |
| Server drafts | `backend/app/api/drafts.py`, migration `0086_model_drafts.py`, `frontend/src/model/ServerDraftSync.tsx`, draft API and tests | Implemented source: per-person/problem ownership, organization isolation, revision checks and synchronization |
| Publication protection | Draft publish endpoint validates the locked revision and records publication transactionally; accepts `Idempotency-Key` | Already implemented; needs current runtime/concurrency verification, not reimplementation |
| Legacy recovery | `LegacyDraftRecovery.tsx` and tests | Recovery workflow exists; independently review ownership safeguards |
| Visual graph | `ModelGraphPreview.tsx`, `graphCommands.ts`, tests and `graphLayout.ts` | Editable connections, keyboard controls and browser/server layout persistence now exist; September preview-only limitations are superseded |
| Workspace | `Workbench.tsx`, workbench API and components; commits `7eae6c0`, `b3d28bd` | Unified tree, collection and selected-record experience |
| Imports and quality | Column mapping, composite keys, field/label matching, joins, computed values and quality-check commits | Expanded substantially; this does not certify arbitrary database connectors |
| Guided modeling | `DescribeToDraft.tsx`, `draftFromWords.ts`, recipe/editor commits | Words-to-draft and recipes expanded across coverage, budgets, supply networks, traffic, routing and periods |
| Forecasts | Commits integrating predictors into rules/goals, linked-record predictions and time-derived data | Implemented in committed history; full coverage not independently retested |
| GIS and networks | Road-aware travel/cost, unreachable pairs, temporal travel, derived layers and result maps | Major committed additions, with further local edits pending |
| Results and correctness | Goal directions, trade-offs, breakdowns, scenario map snapshots, run refresh and publication-base fixes | Multiple delivered source changes after September |
| Frontend performance | Commit `87d65f5` splits pages into lazy-loaded chunks | Reassess with a new build; do not repeat the old bundle warning as a verified current finding |

Source presence is not proof that migrations are applied or the running containers contain these changes.

## 2. Uncommitted work to preserve and review

The working tree contains significant modifications, additions and deletions. This review did not alter them or infer authorship solely from Git status.

- **Assistant:** new backend agent modules, API, frontend assistant components, tests and migration `0109_agent_conversation.py`. Documentation describes Ask and Describe-a-problem flows using a local vLLM model, file input, model approval and result explanation.
- **Modeling, GIS and exports:** new `model_spec.py`, `run_dxf.py`, `auto_records.py` and tests; modified solver, worker, preflight, GIS and export paths.
- **Migrations:** untracked `0106_drop_camp_solves.py` through `0110_faster_record_triggers.py`. Review upgrade ordering and data-retention impact before applying them.
- **Camp-specific removal:** tracked backend/frontend modules, examples and tests are marked deleted. Verify replacement workflows and compatibility; do not treat these deletions as routine cleanup.
- **Deployment:** Dockerfile, Compose, nginx, requirements and environment-example changes. Check the older rollout instructions against these changes before reuse.
- **Local artifacts:** agent kits, evaluation documents, logs, temporary Vite files and data-wipe scripts. Classify before staging. Do not blanket-add this working tree or execute wipe scripts.

## 3. Later evidence supplied in the repository

These are **reported results from the other agent's documents**, not tests rerun on 5 October:

- The benchmark gap analysis reports five rounds across five problem classes. Round 5 reports **92.2% coverage** and **79.8% navigation/UX**, under its own rubric. These are internal task-evaluation scores, not proof of superiority over competing platforms.
- Its round-5 checklist retains explicit exceptions: road conditions per period from a separate table, and units of each type deployed at bases. A post-publication draft warning also retains a qualification about the exact path not being reproduced.
- The 4 October assistant field test reports a final warehouse solution matching an independent HiGHS reference: **1,338,765 EGP/month**, with the same warehouse choices and assignments. Earlier attempts recorded modeling/runtime failures before fixes.
- The solver-system evaluation reports two final problems matching reference solutions and **4,779 backend / 3,379 frontend tests** passing on its evaluated build. That evaluation is untracked, and the working tree contains additional changes. These counts are not freshly verified for the current tree.
- The evaluation identifies words-to-model semantic mistakes and local-model response time as continuing limitations. Review of the proposed model remains necessary in that workflow.

Current Docker image revision, service health, model-server availability, database migration state and live browser workflows were **not verified** in this review. September deployment evidence below remains historical only.

## 4. Revised next-work order

1. **Reconcile the working tree.** Review assistant additions, camp removals, migrations, solver changes and deployment configuration as coherent changesets. Preserve other work and exclude incidental/private artifacts from commits.
2. **Establish a reproducible baseline.** Run frontend build/lint/tests and backend tests against an isolated database. Check migration progression and source/deployed-image alignment. Do not run destructive test fixtures against production data.
3. **Verify safety features already implemented.** Exercise draft ownership, concurrent saves, cross-browser recovery, idempotent publishing, legacy recovery, graph command preservation and saved-layout fallback. Fix demonstrated defects rather than duplicating features.
4. **Review the Assistant before release.** Verify authorization propagation, approval boundaries, attachments, model validation/read-back, cancellation, retries and conversation persistence with the configured local model.
5. **Retest end-user journeys.** Workspace → data/import → Describe/recipe/forms/graph → validation → scenario/run → map/report. Include large data, constrained roles, keyboard use and failures.
6. **Close remaining benchmark gaps.** Start with explicit round-5 exceptions and assistant semantic/performance issues. Checked items with documented exclusions are not universal coverage.
7. **Complete release evidence.** Verify clean-machine offline installation, backup/restore, migration/data retention and rollback; record exact commit, images and tests. Broader database certification and external user studies remain evidence gaps unless separately demonstrated.

## 5. Current reference documents

- [Benchmark gap analysis and round-5 results](docs/plans/2026-10-02-benchmark-gap-analysis.md)
- [Enterprise gap analysis](docs/plans/2026-09-28-enterprise-plan-gap-analysis.md) — historical; reconcile missing-feature claims with later commits
- [Assistant documentation](docs/assistant.md) — currently untracked
- [Assistant field test](docs/assistant-field-test-2026-10.md) — currently untracked
- [Solver-system evaluation](docs/solver-system-evaluation.md) — currently untracked
- [Original navigation and dual-builder proposal](OAAS_UX_FORM_GRAPH_PLAN.md)

---

# Historical baseline — 28 September 2026

**Everything below is the preserved September report. Its “current,” “latest,” deployment and “remaining” statements apply to that date. Use the reconciliation above for current priorities.**

# OaaS platform — cumulative implementation and delivery report

**Updated:** 28 September 2026  
**Workspace:** `D:/solver`  
**Latest implementation commit:** `472c0605453e2ca78a9a050101000e1ee891a929`  
**Previous consolidated implementation commit:** `3589cb0`  
**Local application:** <http://localhost:3010>

## 1. Purpose and scope

This document consolidates the work completed during the platform enhancement initiative: navigation, end-user modeling, the shared form/graph builder, draft recovery and account separation, template usability, database ingestion, solver diagnosis, testing, and offline deployment. It also gives a reconciled remaining-work list.

This is a current-state report, not a statement that the entire roadmap is complete. Earlier release notes are historical snapshots. Where those notes describe graph editing, undo/redo or account scoping as unavailable, the later increments summarized here take precedence. Existing repository capabilities outside this initiative have not been exhaustively audited here.

The product is intended for an isolated environment. Recent deployment builds used local dependencies and installed container images without fetching packages. No evidence currently establishes superiority over every competing platform or support for every optimization problem or database.

## 2. Current delivery status

| Area | Delivered | Still incomplete |
| --- | --- | --- |
| Navigation | Domain/problem context, navigation hubs, canonical routes, editor deep-link recovery, searchable problem picker and direct-ID problem links on the model editor, Versions, Scenarios and Runs | Searchable scenario and version pickers, remaining legacy-route migration, full permission/deep-link matrix |
| Guided Form | Decision variables, hard/soft rules, parameter limits and weighted objectives | Broader guided patterns, units guidance and a complete model-review workflow |
| Visual Graph | Current-draft graph, focused rule/objective editing through shared forms, accessible parts list, layouts kept per account in the browser | Typed connection authoring, individual declaration inspectors, server-saved layouts |
| Draft recovery | Local persistence, 30-edit undo/redo, backup download and confirmed restoration; server-saved drafts with revision checks, conflict choice and cross-browser recovery; idempotent publication of the exact saved revision | Automatic background saving, revision history and comparison, a dedicated recovery entry point for backups |
| Account separation | Account-specific browser keys, memory and history; API-cache clearing; server drafts owned by the stable account ID; attested one-account claim of legacy browser drafts | Browser drafts are still keyed by the JWT subject (username) |
| Templates | Compact summaries and bounded technical-detail panels | Broader end-user template onboarding and usability evaluation |
| Database ingestion | Authenticated service and operational PostgreSQL/TLS reference extraction | Business-source onboarding, mapping/import UI and validated dataset publication |
| Solvers/results | Specific failed-run diagnosis and verification of a compatible successful run | Unified pre-run review, richer result confidence and comparative benchmarks |
| Deployment | Offline frontend build and Compose rollout, ingestion overlays preserved | Complete reproducible offline dependency bundle and broader release certification |

## 3. Navigation and end-user workflow

### 3.1 Delivered navigation

```text
Home
  Continue working
  Recent results
  Attention needed
All domains
  [Domain]
    Overview
    Problems
      [Problem]
        Overview
        Inputs
        Build model
          Guided Form
          Visual Graph
          Advanced: Blocks / Exact IR / published-model visualizations
        Versions
        Scenarios
        Runs & results
    Data
      Records & relationships
      Data structure
      Data relationships (graph)
      Sources & imports
      Quality checks
Templates
Operations                         [capability-dependent]
  Runs & queues
  Workers & solver availability
Administration                     [capability-dependent]
  Access & policies
  Audit history
  Platform settings
Help                               [local]
```

This tree describes available destinations and contextual grouping. Some destinations are hubs linking to existing tools rather than complete new workflows.

### 3.2 Context and navigation corrections

- Canonical route IDs take precedence over remembered domain selection.
- Global pages do not inherit the selected domain's sidebar.
- Problem selection on a canonical model route navigates to the newly selected problem's canonical URL.
- Parent navigation entries no longer remain highlighted beside an active child.
- Problem readiness links retain the correct canonical problem context.
- Inputs, records, structure, quality and access hubs reuse existing tools.
- Legacy routes remain available for compatibility; migration is not complete.

### 3.3 Reliable model-editor links

- A requested problem missing from the first list page is retrieved directly and checked against the selected domain.
- A requested model version is fetched directly, including versions older than the latest 50 listed entries.
- The selected version must belong to the selected problem.
- Explicit malformed IDs or ownership mismatches never silently select a different model.
- Loaded out-of-page records appear in their selectors.
- Failed reads show retry controls; paused initial reads show an offline notice.
- Loading failures are no longer presented as empty domains or invitations to create a new model.

These direct-ID guarantees currently apply to ModelEditor; equivalent coverage across every other selector is still required.

### 3.4 Home and capability visibility

Home displays recent results and attention items using the latest six runs. Attention is limited to that sample, not a complete operational alert feed.

Navigation uses existing capabilities: `solver.configure` for operational navigation, `iam.manage` for Access/Audit, `settings.edit` for settings and `integration.run` for sources. These visibility rules do not add or replace backend authorization.

## 4. Guided Form problem encoding

### 4.1 Decision variables

Users can create binary, integer and continuous decisions, either scalar or indexed by domain entity types. Optional lower/upper bounds are supported. Choosing dimensions declares the necessary sets. Names, duplicate declarations and invalid bounds are checked before creation.

### 4.2 Rules

Users choose a decision, retain selected dimensions as “for each” bindings, and sum the remaining dimensions. Rules support at most, exactly or at least comparisons, with constant or declared numeric-parameter limits.

Required rules become hard constraints. Preferences become soft constraints with positive integer penalties. Notes and readable summaries explain the resulting expression.

### 4.3 Objectives and parameter mapping

- Objectives can total a decision or multiply it by a numeric parameter before summing, such as `sum(cost[feed] * quantity[feed])`.
- Each term has a positive integer weight.
- Adding a term preserves existing terms, objective direction and combination mode.
- Parameter dimensions map explicitly to decision dimensions.
- Unique matches can be preselected; ambiguous/repeated dimensions require selection.
- Rule-limit parameters may only reference dimensions retained in the rule's binding scope.
- Missing parameters, entity-valued parameters and invalid/stale mappings are rejected.
- Units are not automatically inferred or converted.

### 4.4 Shared model integrity

Guided commands update the current shared draft. Existing advanced IR content is preserved by the shared update path. Detailed forms and Blocks remain available for advanced expressions and existing scheduling/routing constructs. Exact IR is read-only. Normal validation still applies before publishing an immutable version.

This is structured guided encoding, not unrestricted natural-language translation or universal problem coverage.

## 5. Visual Graph and dual-builder behavior

- The graph is derived from the current shared IR and shows model parts and dependencies.
- Selecting a rule focuses its existing detailed editor; selecting the objective focuses its editor.
- Selecting a declaration focuses the declarations section, not yet an individual variable/parameter inspector.
- A keyboard-accessible model-parts list offers equivalent selection with pressed-state feedback.
- Rule renaming preserves the focused editor; removal clears focus.
- “Show all model editors” restores the complete editing view.
- Changes remain available when switching between graph, Guided Form, Blocks and Exact IR.
- Dragged positions survive model edits while the graph remains mounted.
- Reset graph layout restores automatic arrangement.

Graph positions are view state and do not modify solver IR. They are not saved across reloads or view changes. Connections currently visualize model expressions; drawing or deleting semantic connections is not implemented. Shared model undo/redo exists, but a separate graph-layout undo system does not.

## 6. Draft safety, recovery and account handling

### 6.1 Local storage and undo/redo

There is one local unpublished draft per account/problem namespace. It records its starting version, full IR and edit timestamp.

Undo/redo retains up to 30 edits in the current tab, including the first edit from a published version. Forms, graph editors and Blocks use the same history. New edits clear redo history; discard clears history. History does not survive reloads. Undo refuses to replay over a different draft written by another tab; this is not an atomic server concurrency mechanism.

A storage-full defect was fixed: if a later write fails after an older draft was saved, the newest in-memory draft remains visible and is marked unsaved, instead of the editor falling back to the older stored copy.

### 6.2 Backup and restoration

- Download draft backup exports full IR and starting-version metadata as JSON.
- Restore accepts supported backup files up to 5 MB for the same problem and starting version.
- Selecting a file does not immediately overwrite work; confirmation is required.
- If the current draft changes after the preview opens, restoration is refused until the file is selected again.
- Restoration is undoable and remains unpublished.
- Normal validation is still required before publishing.

Current usability limitation: restoration controls require an existing local draft. If none exists, open the backup's starting version and make an edit first. A dedicated recovery entry point remains outstanding.

### 6.3 Account-specific namespaces

New saved drafts, memory fallback and undo history are keyed by JWT subject and problem. Login/logout clears cached API data. Cross-tab authentication changes reload the application to avoid leaving an editor on the previous account's loaded screen.

This provides UI-level separation, not encryption. Same-origin code can read browser storage, and backend permissions remain the authorization boundary. Stable server user/organization IDs should replace reliance on the current username-based JWT subject in the durable draft design. Unrecognized token formats receive distinct temporary namespaces without reliable reload persistence.

### 6.4 Legacy draft preservation and recovery

Older unscoped browser drafts are not automatically assigned to the next signed-in account. The editor displays a notice without showing their contents, including on problems with no published version.

A signed-in account can now recover such a draft explicitly: it attests “I wrote this draft in this browser”, and the draft becomes that account's unpublished draft, subject to normal validation before publishing. The original browser entry is never changed or removed. The claim is recorded, so only one account in the browser can recover it; other accounts are told it was recovered by another account. Recovery is refused when signed out or with an unrecognized session, when the account already has a draft for the problem, and when the entry is unreadable. The browser cannot prove authorship; the attestation and single claim are the safeguards, and server-saved drafts are the durable ownership mechanism from here on.

### 6.5 Server-saved drafts and publication safety

Migration `0086` adds `model_draft` (one draft per account per problem, owned by the stable `iam.user_account.id`, with a `revision`) and `model_publication` (which version a keyed publish request created). Both are tenant tables under row-level security, with the organization inherited from the problem and account.

- `GET/PUT/DELETE /api/v1/problems/{id}/draft` and `POST …/draft/publish` require `model.publish`. A draft is visible only to its owner, not to colleagues or other organizations.
- Every save and discard names the revision it was built on; any other is the platform's stale-record 409. Rows are locked for the comparison, so concurrent saves cannot both succeed.
- Drafts may be incomplete (object and 5 MB limits only). Publication validates the exact locked revision against the IR contract, inserts the version, deletes the draft and records the request in one transaction.
- With an `Idempotency-Key`, a retried publish returns the first attempt's version (200); a reused key with a different request is refused. Without a key, the deleted draft still prevents a second publication.
- The proposal suggested ETag/If-Match with 412; the implementation keeps the platform's existing 409 body shape, which the browser already recognizes.

The model editor keeps the browser draft as the working copy and shows its server status: “Saved on this device only”, “Changes not saved to the server”, or “Saved to the server · revision N”. **Save to server** sends the last known revision. When another tab or browser saved in between, the editor asks whether to use the server copy or keep this draft and replace it. A browser with no local draft is offered the server draft. A draft linked to the server publishes through the server under one idempotency key per attempt, reused on retry; discarding also discards the server copy.

## 7. Templates UI/UX correction

The Templates table previously rendered full domain-seed and model JSON inside cells, producing oversized rows and obscuring names and actions.

Delivered corrections:

- Sample-data summaries show record-type, sample-record and parameter counts, with a short description where supplied.
- Model summaries show decision, rule and set counts and the objective direction.
- Column labels read “Sample data,” “Model summary” and “Model format.”
- Technical JSON is rendered only when expanded and appears in a bounded scrollable panel.
- Expanding details does not trigger row navigation.
- Desktop cell contents align to the top.
- The same summary renderer is reused by desktop and small-screen table presentations.

The fix was covered by component/table tests and deployed. A comprehensive visual/responsive audit is still outstanding.

## 8. Database integration and ingestion

### 8.1 Implemented service

The authenticated ingestion increment includes migration 0085, domain-owned connections, persisted jobs, tenant-inheritance triggers, row-level security and one active job per connection.

Existing API capabilities `integration.manage` and `integration.run` protect management/execution. Credentials use AES-GCM envelopes bound to organization/connection identity. Management includes create, rotate and disable; execution includes submit, status and cancel.

A dedicated worker claims jobs with row locking, supervises extraction children, enforces limits and fences completion with attempt identifiers. Extraction artifacts contain counts, checksums, source metadata and timestamps. Decimal precision is preserved. Extracted artifacts explicitly require mapping validation before optimization use.

### 8.2 Operational findings resolved

The installation was configured with an external private keyring, trusted CA, source-network policy and a dedicated ingestion worker. Private credentials and keys remain outside the repository at `D:/solver-private/ingestion`; this report contains no secret values.

Historical live verification:

| Item | Recorded result |
| --- | --- |
| Reference source | Local PostgreSQL 16 with synthetic sample data |
| Verification domain | 203 — Ingestion verification |
| Connection | 1 — Local TLS reference |
| Job | 1, completed as `extracted` |
| Transport | TLS 1.3 with hostname and CA verification |
| Source privileges | Read-only transaction; INSERT privilege absent |
| Artifact | Three rows; checksum and byte count verified |
| Numeric precision | Decimal values retained exactly |

This validates the local reference path, not arbitrary business databases or every PostgreSQL version.

### 8.3 Docker restart correction

After a Docker restart, the ingestion worker dynamically received the database's fixed address, preventing the reference database from starting. The reference overlay now explicitly assigns:

- Reference database: `172.29.89.2`.
- Ingestion worker on the source network: `172.29.89.3`.

The database address and its `/32` allowlist remain unchanged. Both services subsequently started successfully. The source network is internal and the reference database has no published host port.

## 9. Solver failure diagnosis

Run **589** failed because its explicit PSO selection did not support the model's required connectivity/integrality capabilities.

An existing run **590** used **CP-SAT** on the same scenario **246** and frozen dataset **154**, reporting **optimal** with objective **2564**. This was verified rather than submitting a duplicate solve. Run 589 remains in history.

This is evidence of a compatible solution for that model, not an extension of PSO's capabilities. Automatic selection or a compatible solver remains necessary; an explicitly selected incompatible solver is not silently substituted.

## 10. Verification evidence

Test counts below refer to distinct historical runs with overlapping suites. They must not be added together as a unique-test total.

| Increment | Recorded verification |
| --- | --- |
| Navigation delivery | 144 focused tests; 39 AppShell tests rerun after an active-link correction |
| Parameter-based guided creation | 69 tests; build and lint |
| Focused graph workflow | 61 ModelEditor tests and three graph-component tests |
| Template summaries | 54 table/summary tests |
| Draft recovery | 81 tests across store, recovery, ModelEditor and Blocks |
| Account separation | 102 tests across six suites; expanded App suite later passed 14 tests |
| Latest committed deployment | **157 tests across eight targeted suites**, production build and lint |
| Ingestion service historical checks | 37 PostgreSQL-backed tests in an isolated container and 19 pure integration tests |

The latest 157-test run covered draft storage, recovery, ModelEditor, Blocks integration, App/authentication, API client, DataTable and template summaries. It was not a full repository test run. Build output still reports the existing large frontend bundle advisory. Some tests emit existing React Router/jsdom warnings despite passing.

### Browser evidence from earlier increments

Authenticated walkthroughs verified Home, contextual navigation, Inputs, domain data and graph rendering.

A dedicated test problem, **191** in domain **5**, was created as “Guided forms verification.” Forms created integer `staff_count` bounded 0–20, rule `staff_count >= 3`, and a minimization objective. Publication succeeded as version 1, model-version ID **276**.

A later browser check added indexed `feed_quantity[feed]`, declared `cost[feed]` and a cost-weighted objective while retaining the original model content. Those additions were recorded as an unpublished local draft. No solve was submitted for this demonstration. Current access to that older unscoped draft requires the legacy recovery work described above.

Later increments were verified with automated tests, build/lint and deployment health checks; a full authenticated browser regression after every increment has not been recorded.

## 11. Commits and deployment

| Commit | Scope |
| --- | --- |
| `fe10915` | URL-authoritative domain context, planning overviews and canonical Runs routes |
| `2b9b95b` | Encrypted connections, ingestion jobs and PostgreSQL extraction pilot, migration 0085 |
| `3589cb0` | Consolidated navigation, guided forms, shared graph modeling and related operational documentation |
| `472c060` | Account draft separation, undo/backup/recovery, readable templates and ingestion address correction |

The latest frontend image is tagged `solver-frontend:472c060` and `solver-frontend:latest`. Its revision label was verified as `472c060`. The Compose deployment completed with ingestion overlays retained, and frontend-proxied PostgreSQL and ClickHouse health checks returned `ok`.

A subsequent container inventory while preparing this report showed frontend, backend, solver worker and ingestion worker running, with PostgreSQL, ClickHouse and the ingestion reference source healthy. The separate tileserver was also running and healthy. A running container alone does not certify all application workflows.

### Offline build and rollout method

The frontend was compiled using installed local dependencies, then packaged from `dist` using the locally installed `nginx:1.27-alpine` image, with Docker build networking disabled and image pulling disabled. Temporary build contexts were outside the repository.

An earlier backend rebuild reused an installed backend dependency image only after comparing its requirements-file hash with the repository. The last release changed frontend/Compose configuration and did not require reinstalling backend dependencies.

The npm cache and backend wheelhouse were not populated as complete installation bundles. These successful local builds therefore do not establish reproducibility on a clean air-gapped machine.

For an installed image rollout, retain the integration overlays:

```powershell
docker compose --env-file .env --env-file D:/solver-private/ingestion/compose.env -f docker-compose.yml -f deploy/compose/integrations.yml -f deploy/compose/ingestion-reference.yml up -d --no-build --pull never --wait --wait-timeout 60
```

This command deploys existing images; it does not compile source. Do not recreate the backend using only the base Compose file, which omits the integration configuration. Do not remove the ingestion services as orphan containers. Never commit private keyrings, passwords or CA private keys.

## 12. Remaining work and acceptance criteria

| Priority | Work package | Acceptance criteria |
| --- | --- | --- |
| P0 — delivered | Legacy draft ownership recovery | Explicit attested claim by one signed-in account; contents hidden until claimed; original entry preserved (section 6.4) |
| P0 — delivered | Durable server drafts | Delivered as in section 6.5. Remaining: automatic background saving and revision history/comparison |
| P0 — delivered | Publication safety | Delivered for server-linked drafts (section 6.5); drafts never saved to the server still publish through the direct version route |
| P1 — delivered (Epic UX U-1) | Navigation completion | Delivered: server-side `q` search on scenarios, runs, versions, parameters, entity and relationship types, and a searchable domain chooser at `/domains`; one `LoadFailure` with distinct no-access / not-found / retry states across the pages that load by id; `?parameter=` fetched by id; `CapabilityGate` guards every registry destination and a 4-role × every-destination deep-link matrix test passes; legacy unscoped links resolve `?problem=` / `?domain=` (or the chosen domain) to their scoped page in one step |
| P1 — delivered (Epic UX U-2) | Complete graph authoring | Delivered: per-card inspectors (decision kind, bounds, rename that follows every reference; parameter and set facts); typed connections (set→decision index, set→rule for-each, decision/parameter→rule, decision→goal) by drag or a Connect dialog, refused with a reason otherwise; deletion shows what goes and what is trimmed first and leaves unrelated rules untouched (tested); keyboard: C connects, Delete deletes, Enter inspects (`model/graphCommands.ts`) |
| P1 — delivered in browser | Durable graph layout | Kept per account and problem, apart from the IR; survives reloads and view changes; reset and undo behaviour specified and tested; cards can be moved without dragging. Remaining: server storage |
| P1 — delivered (Epic UX U-3) | Guided pattern expansion | Delivered: task with a duration, one at a time, shared capacity, vehicle routes and connected regions patterns (`model/patterns.ts`, each validated against the IR contract); units from the domain in guided fields with a mismatch warning; a plain mapping preview naming why a dimension is unmapped; stable rule identities across rename and deletion; a Review tab with every rule in words and what looks unfinished |
| P1 — delivered (Epic UX U-4) | Import/mapping workflow | Delivered: source setup form, extraction run/cancel, job history with failure explanations; import wizard with preview, column mapping (guessed), row/column validation through the bulk-upload code, and a one-time load recording artifact SHA-256 and mapping hash (`import_validation`, `import_load`, migration 0089) |
| P1 — delivered (Epic UX U-5) | Pre-run and result experience | Delivered: `GET /scenarios/{id}/preflight` (blockers and warnings from compiling on live data, the model class, every solver's fit and why not) shown as "Before you solve", gating Solve; worker heartbeat (`worker_heartbeat`, migration 0090) and `GET /workers`; the Solver list shows why each unfit solver is unfit; comparisons show each side's claim, gap, solver, time and class, and warn when claims differ |
| P2 | Professional release validation | Keyboard/screen-reader and responsive audits; offline browser matrix; recovery exercises; measured bundle/performance budgets |
| P2 | Product and solver benchmarks | Representative user studies and timed tasks; repeatable model/data/hardware comparisons; documented limitations and measured outcomes |
| P2 | Portable offline distribution | Versioned dependency caches, image bundle, install/upgrade/rollback procedures and successful clean-machine installation test |

Recommended sequence: with the P0 draft work and the P1 packages delivered (Epic UX, branch `epic/ux`, plan `docs/plans/2026-09-29-ux-epic-design.md`), the P2 packages come next. Accessibility and focused regression testing should accompany each delivery, not be deferred entirely to the end.

## 13. Key implementation files

| Concern | Files |
| --- | --- |
| Routing and session lifecycle | `frontend/src/App.tsx`, `frontend/src/api/client.ts` |
| Sidebar and registry | `frontend/src/components/AppShell.tsx`, `frontend/src/nav/registry.ts` |
| Home, hubs and readiness | `frontend/src/components/HomeResults.tsx`, `frontend/src/pages/NavigationHub.tsx`, `frontend/src/components/ProblemReadiness.tsx` |
| Model editor | `frontend/src/pages/ModelEditor.tsx` |
| Guided creation | `frontend/src/model/GuidedCreation.tsx`, `frontend/src/model/guidedCommands.ts` |
| Graph presentation | `frontend/src/components/ModelGraphPreview.tsx`, `frontend/src/components/modelStyles/FlowView.tsx` |
| Draft storage/recovery | `frontend/src/model/draftStore.ts`, `frontend/src/model/DraftBar.tsx`, `frontend/src/model/DraftRecovery.tsx` |
| Blocks integration | `frontend/src/components/modelStyles/BlocklyEdit.tsx` |
| Template summaries | `frontend/src/components/DataTable.tsx`, `frontend/src/components/TemplateSummary.tsx` |
| Ingestion deployment | `deploy/compose/integrations.yml`, `deploy/compose/ingestion-reference.yml` |
| Reference provisioning | `scripts/prepare-ingestion-reference.py` |

## 14. Source documents and maintenance

- [Navigation, UX and dual-builder proposal](OAAS_UX_FORM_GRAPH_PLAN.md)
- [Enhancement and database integration plan](OAAS_ENHANCEMENT_PLAN.md)
- [Incremental delivery ledger](docs/recommendation-delivery-status.md)
- [Historical navigation release](docs/navigation-release.md)
- [Guided forms release](docs/guided-forms-release.md)
- [Database extraction runbook](docs/runbooks/database-extraction.md)
- [Ingestion service runbook](docs/runbooks/ingestion-service.md)
- [Operational ingestion evidence](docs/runbooks/ingestion-operational-check.md)

Maintain this report after each milestone by updating current status and remaining acceptance criteria, recording the commit/image revision and exact verification performed. Keep historical evidence labeled as historical. This report itself is a new documentation artifact created after commit `472c060`; that commit identifies the implementation baseline, not the commit containing this file.


## Verification update — 5 October 2026

Fresh checks now supersede the earlier statement that no tests/build were performed during reconciliation: the full frontend suite passed **3,382 tests across 220 files**, production build and lint passed, and **59 focused backend tests** passed using a fresh disposable PostgreSQL container and the current source. Five frontend test files were corrected for locale portability and the relationship-tree API fixture. No application code was changed for those corrections.

The full backend suite, live Assistant/model-server behavior, production migration state and browser journeys remain unverified. The current Docker inventory omitted the September ingestion containers, and the installed backend emitted a database collation-version warning. No production deployment or migration was performed.

See [current-tree verification and release checks](docs/current-tree-verification-2026-10-05.md) for scope, evidence and next steps.

## Verification and hardening follow-up — 5 October 2026

The reviewed work was committed as `90a60fc` (cumulative report and five test-fixture/assertion corrections) and `bfe0880` (Assistant, GIS, migration, and related platform changes). A further hardening pass found and corrected a mismatch in the Assistant's Python-execution default: the Compose comment said it was opt-in while the environment default enabled it. The sample environment, Compose default, and Assistant guide now default `AGENT_RUN_PYTHON` to `0`; the running backend was recreated with only that setting changed and reports `AGENT_RUN_PYTHON=0`.

The offline rebuild path was also corrected. `OFFLINE=1` now skips the backend Dockerfile's apt install; operators must stage Python wheels and base images locally. Without Pango in the supplied base image, PDF export uses the existing printable-report fallback. The offline-install runbook and dependency manifest now distinguish transferring the prebuilt release images from rebuilding an image on an air-gapped host.

Fresh frontend verification passed 3,382 tests in 220 files, the production build, and lint. Vitest's result cache now writes into a workspace-local ignored directory because `node_modules` is read-only in this managed Windows environment. BuildKit's Dockerfile static check passed. In-memory Python compilation checked 610 backend files. After mounting the expected repository paths, supplying disposable ClickHouse credentials, and making the tiny exact connected-model check single-worker, the full backend suite passed **4,872 tests with 25 skipped** in 1,695.59 seconds. Its only reported warnings were dependency deprecations and pytest's inability to write cache files in the read-only container.

The live platform is healthy: PostgreSQL, migration 0110, the worker, and ClickHouse all pass `/api/health/details`. A separate PostgreSQL collation mismatch remains. The cluster records collation version 2.41 while its current library reports 2.31; all eight accessible databases show the mismatch, including the 191 MB application database. `template1` and `postgres` each contain 13 valid indexes using collations; `solver` contains 27. Do not refresh the recorded version alone: the affected indexes must be rebuilt first. This maintenance was left unapplied because it affects live database indexes and needs a maintenance window and a verified backup.
