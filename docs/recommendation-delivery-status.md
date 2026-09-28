# OaaS recommendation delivery status

Updated: 2026-09-28. This is an implementation ledger for OAAS_UX_FORM_GRAPH_PLAN.md, not a claim that all milestones are complete.

## Delivered in this increment

- The Visual Graph workspace now includes the same guided creation, declarations, rule and objective editors as Guided Form.
- Selecting a graph card exposes a link to its corresponding editor section. Keyboard users can select the same parts through the model-parts list.
- Both views use the existing shared draft update path. Graph dependencies refresh from the edited model; unknown IR fields remain governed by the existing preservation logic.
- Selecting another problem from a canonical problem route now navigates to that problem's canonical model route instead of changing only a query parameter that conflicts with the route.
- Automated coverage checks graph editor links, read-only graph consumers and retention of graph-workspace edits when switching to Guided Form and Exact IR.

## Milestone ledger

| Milestone | Current state | Remaining acceptance criteria |
| --- | --- | --- |
| M0: end-user baseline | Basic authenticated flows reviewed in earlier increments | Representative-user sessions, timed completion and recorded accessibility baseline |
| M1: navigation | Scoped navigation, contextual hubs, model views and canonical chooser implemented | Searchable large-list selection; complete permission and deep-link matrix |
| M2: durable drafts | Local shared draft, preservation and base conflict handling exist | Account-scoped storage; server draft revisions; compare-and-swap conflicts; explicit recovery; validation tied to revision; idempotent publish |
| M3: guided model creation | Scalar/indexed decisions, hard/soft rules, parameter limits and weighted objectives implemented | Broader guided scheduling/routing patterns; richer units and data mapping guidance; stable editing identities; guided review summary |
| M4: visual authoring | Graph inspection and forms coexist and edit the same draft | Selected-node inspector; typed semantic connections; independently saved layout; undo/redo; accessible connection authoring |
| M5: data and execution | Source listing and existing ingestion/solver APIs are available | Source setup/import wizard; mapping preview; consolidated quality report; complete solver readiness and result-confidence experience |
| M6: professional release | Targeted regression tests and offline frontend build pass | Measured performance budget; accessibility audit; offline browser regression matrix; recovery tests; reproducible solver benchmarks |

## Next implementation order

1. Direct-ID resolution and failure/retry states are implemented in ModelEditor. Extend the same behavior to remaining selectors, and add searchable selection for large collections.
2. Add server draft schema/API with tenant and user isolation, revision checks and tests in a disposable database. Wire explicit recovery before introducing automatic synchronization.
3. Add a selected-node inspector backed by the same model commands. Persist layout separately from solver IR. Do not interpret visual edge deletion as safe removal of all expression references.
4. Add source configuration and ingestion status screens over existing authorized APIs. Never store credentials in browser drafts or logs.
5. Add a pre-run review that reports missing inputs, supported solvers, constraints and data-quality failures. Keep solver suitability distinct from worker availability.
6. Measure accessibility, offline behavior and representative solver benchmarks. Publish measured results rather than claims of superiority for every problem class.

## Verification for this increment

- Existing modeling suite: 69 tests passed before the new graph integration regression was added.
- Updated ModelEditor and graph component suites: 54 tests passed, including the new regression and two graph component checks.
- Production build and ESLint passed. Build retains the existing large-bundle warning.
- This increment does not add server draft persistence, semantic connection editing or a completed import wizard.


## Navigation reliability increment

- ModelEditor retrieves a requested problem missing from its first list page by ID and verifies domain ownership.
- Explicit version links fetch the selected version directly, including versions older than the first 50 results. The version must belong to the selected problem.
- Retrieved records appear in their selectors. Malformed explicit IDs never fall back to the first item.
- Failed list/detail reads show retry controls; paused initial reads show the offline notice. Failure is not presented as an empty domain or a model ready to create.
- Verification: all 60 ModelEditor tests pass, including eight new cases for out-of-page records, invalid IDs, ownership mismatches and failure recovery. ESLint passes.
- This completes direct-ID loading for the model editor only. Searchable selectors and the remaining draft, graph, import and release milestones remain open.

## Focused graph editing increment

- Selecting a rule card focuses the existing rule editor on that rule; selecting the objective focuses the objective editor. Declaration cards focus the shared declarations section.
- Graph selection is also available through the keyboard-accessible model-parts list, with pressed-state feedback.
- Rule selection follows renaming without remounting its input. Removing a selected rule clears the focus. Show all model editors restores the full view.
- Edits continue through the shared draft path. Regression coverage verifies that a renamed rule and its edited note remain available in Guided Form.
- Dragged card positions survive semantic edits while the graph remains mounted. Reset graph layout restores automatic arrangement. Positions are view state, are not part of solver IR, and are not persisted across reloads or view changes.
- Verification: 61 model-editor tests and three graph-component tests pass; production build and ESLint pass. The existing large-bundle warning remains.
- Remaining graph work: individual variable/parameter inspectors, typed connection commands, durable layout storage, undo/redo and broader accessibility evaluation.

## Draft recovery increment

- Shared draft controls now offer undo and redo for up to 30 edits in the current tab, including the first edit from a published version. Forms, graph editors and Blocks use the same store.
- A new edit clears redo history; discard clears history. Undo refuses to overwrite a different draft written by another tab. This is not server-side concurrency protection.
- Fixed a storage-full regression: if a previous saved draft exists but a later write fails, the latest in-memory draft now remains visible and is marked unsaved.
- Download draft backup exports the full IR and starting-version metadata. Restore accepts backups up to 5 MB for the same problem and starting version, requires confirmation, refuses stale previews and can be undone. Restored work remains unpublished and must pass normal validation before publishing.
- To restore when no local draft exists, open the backup's starting version and make an edit to create a local draft first. A dedicated recovery entry point remains to be added.
- Validation: 81 tests passed across draft store, recovery UI, model editor and Blocks integration. Build and lint pass; the existing bundle-size warning remains.
- Still pending: authenticated ownership migration for legacy drafts, account-scoped storage, server persistence and revision conflicts, idempotent publication, and the remaining navigation/data/graph/release milestones. Undo history does not survive reloads.

Deployment note: Docker Desktop was started and the recovery frontend was built offline and deployed. Frontend-proxied PostgreSQL and ClickHouse health checks returned `ok`. A restart revealed that the ingestion worker could dynamically take the reference database's fixed address; the reference overlay now reserves `.3` for the worker while the database keeps `.2`.

## Account-scoped browser drafts

- New drafts, in-memory fallback and undo history are keyed by the signed-in JWT subject and problem. This is UI-level account separation, not encryption or a server authorization boundary; localStorage remains readable by code running on this origin.
- Login/logout clears cached API data. Cross-tab token changes reload the application so an editor cannot remain on the former account's loaded screen.
- Drafts with old unscoped keys remain untouched and are not automatically loaded into any account. A notice identifies their presence without displaying model contents. A verified ownership recovery/migration workflow remains outstanding; do not clear browser data before recovery.
- Standard password and SSO sessions use the JWT subject as supplied by the current authentication contract. Unrecognized token formats receive a distinct temporary namespace; persistence across reloads for such sessions is not supported.
- Validation: 102 tests passed across six authentication/modeling suites, followed by the expanded 14-test App suite including account-cache invalidation. Production build and lint pass.
- Still outstanding: server-saved drafts with revisions, stable server user/organization identifiers for draft ownership, legacy ownership recovery, conflict resolution and duplicate-publish protection.

## Legacy draft recovery and server-saved drafts

- Legacy unscoped browser drafts can be recovered by one signed-in account through an attested, explicit claim. Contents stay hidden until then; the original entry is never modified; other accounts see that it was recovered elsewhere. Refused when signed out, over an existing account draft, or for an unreadable entry.
- Migration `0086`: `model_draft` (per account and problem, stable account-ID ownership, revision) and `model_publication` (idempotency records). Both use row-level security with inherited organization.
- API: `GET/PUT/DELETE /api/v1/problems/{id}/draft`, `POST /api/v1/problems/{id}/draft/publish` with optional `Idempotency-Key`. Stale revisions get the platform's 409; publication validates the exact locked revision and is transactional; a retried keyed publish returns the same version.
- Editor: server-save status, Save to server, conflict choice (use server copy or replace it), server-draft offer in a browser without a local draft, server publication with one key per attempt reused on retry, and server discard alongside local discard.
- Verification: 13 backend draft tests (including concurrent keyed retries creating one version and cross-tenant isolation) and 317 tests across tenancy, problem, audit and concurrency suites; migration downgrade/upgrade exercised. Frontend: 2268 tests, lint and production build pass (existing bundle-size warning remains).
- Still outstanding: automatic background saving, revision history/compare, browser-draft keys based on stable account IDs rather than the JWT subject, and a dedicated backup recovery entry point.

## Searchable problem picker (model editor)

- The model editor loads the first 50 problems by name instead of up to 500. When a domain has more, a "Find a problem" box searches all of them through the list API's `q`, 50 matches at a time, with the count stated ("Showing 50 of 812 matches").
- The chosen problem always remains an option, so a deep-linked problem outside the first page or the current matches is never replaced. Direct-ID loading and ownership checks are unchanged.
- Small domains look as before: the search box and count appear only when the first page is not everything.
- `useEntityList` accepts `enabled`, so the search query waits for input.
- Follow-up: `useDomainProblem` now resolves the page's problem for the model editor, Versions, Scenarios and Runs: the first page for the picker, and a linked problem outside it fetched by ID and checked against the domain. Before this, Versions, Scenarios and Runs reported a valid link to a problem past the 500th as "not available here". Scenarios also showed a failed problem list as an empty domain; it now reports the failure with a retry (`LoadFailure`, shared with the editor).
- Settings keeps its own list: it has no deep link and lists every domain's problems when none is selected.
- Verification: 3 picker tests and 6 new deep-link/failure tests across Versions, Scenarios and Runs; full frontend suite (2277), lint and production build pass. One unrelated GraphDemo test timed out once under full-suite load and passes on rerun, with or without these changes.

## Durable graph layout

- Visual Graph card positions are kept per account and problem in this browser (`frontend/src/model/graphLayout.ts`), keyed by the cards' stable ids. They survive reloads, switching views and model edits.
- Layout is presentation only: never in the draft or IR, so it cannot change the model, its hash, publication or the draft's undo history. **Undo edit** does not move cards; **Reset graph layout** returns to automatic arrangement and forgets the kept positions.
- Accounts do not see each other's layouts (same namespace as account-scoped drafts). If storage refuses a save, the page says the positions last only until leaving the graph.
- Non-drag moves (WCAG 2.5.7): with a card selected, ← ↑ ↓ → buttons move it 40 px per press, named for the card ("Move c_cover right"). Moves go through the same kept layout as drags, without remounting or refitting the canvas.
- Not yet: server-side layout storage (a separate presentation endpoint, per plan §9.6). The canvas's application of a move is typechecked but not exercised in jsdom; the buttons and the requests they send are tested.
- Verification: 4 new layout and move tests; full frontend suite (2281), lint and production build pass.

## Dark theme and stable sidebar

- Dark theme moved to neutral charcoal (page `rgb(17 18 21)`, surfaces a step lighter) with measured contrast: muted text about 6:1, secondary about 8:1, control borders 3:1 (WCAG 1.4.3, 1.4.11). `color-scheme: dark` makes native selects and scrollbars dark; placeholders, focus outline and loading shimmers follow the theme.
- Opening a platform page (Runs & queues, Settings, Help) no longer rebuilds the sidebar into a different tree. The top group is "Navigate" everywhere, and the last domain or problem opened by URL is offered as a "Recent problem" / "Recent domain" group linking back to its own routes. The platform page itself stays unscoped, and the shortcut is dropped once another domain is selected.
- Operations, Help, hub and overview pages are left-aligned like the rest of the application instead of centred.
- Verification: 5 new navigation tests (registry and shell); full frontend suite (2286), lint and production build pass; checked in Chromium on the sign-in, Runs and Runs & queues pages in dark mode.

## Home redesign

- One card style and one section header (title, purpose line, optional "View all") across Home, replacing tinted boxes, small-caps labels and large bordered panels.
- Entry points, recent problems, recent and failed runs, and templates are icon cards. Problems show owner and "created 2 hours ago"; runs show a status badge (green usable, amber infeasible, red failed), objective and when they finished.
- Templates are outlined cards stating what they do ("Create a starting model" or, marked "In use", "Open your problem made from it") instead of a row of solid accent buttons.
- Service health and row counts move to a compact "System" section at the bottom.
- Verification: full frontend suite (2288), lint and production build pass; checked in Chromium in dark and light themes with representative data.

## Domain switch keeps the page

- Choosing another domain in the sidebar no longer always opens its problem list. A problem page opens the same page (Runs, Build model, ...) of the problem last opened in the new domain, or the problem list if none was; a domain page opens the same page in the new domain, cut before any record id; a platform page (Home, operations, help) stays where it is.
- On platform pages the "Recent" shortcut follows the selected domain: its last problem, or the domain itself.
- The last problem per domain is remembered in this browser (`frontend/src/nav/recentScope.ts`); it is a shortcut only, and server permissions still govern every page.
- Verification: switch-rule unit test and 2 shell tests; full frontend suite (2291), lint and production build pass.

## Rules and goals as equations

- Each rule on Build model is one editable equation in the IR's own terms, e.g. `for each d in day: sum(assign[e, d] for e in employee) >= demand[d]`, beside its strength (required / preferred). Condition, chance and the full structure tree fold under "More options". Goals are `weight` + equation, and the whole objective reads as one line (`minimize 1 × (…) + …`).
- `frontend/src/model/formula.ts` prints and parses the equations: sums with `for i in set`, `where` filters, parameters, variables, attributes, `+ - *`, the contract's functions and `for each …:`. It checks names, index counts and bound indices, with plain messages ("did you mean “assign”?") and the offending span highlighted.
- The equation form is offered only when printing and parsing give back the identical IR; walks, curves, conditional, scheduling, connected and route rules keep the structure editor. Every template's rules and goals that have an equation are checked to round-trip exactly.
- Typing is applied on Enter or leaving the field, only when it reads; Esc restores. Name chips insert variables, parameters and a `sum(… for … in …)` skeleton.
- A binding's filter sits beside its Index and Set, and the filter's add controls are icons beside its last condition, with and/or between conditions only.
- Also fixed: shade-950 status text (warning boxes) was unreadable in dark mode.
- Verification: formula round-trip and error tests, EquationField tests, 3 editor tests for equations; full frontend suite (2306), lint and build pass; checked in Chromium in dark and light.
