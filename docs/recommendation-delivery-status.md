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
