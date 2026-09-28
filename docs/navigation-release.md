# Navigation delivery — 27 September 2026

Implemented the first navigation architecture delivery from `OAAS_UX_FORM_GRAPH_PLAN.md`.

- Home exposes Continue working, Recent results, and Attention needed. Recent results use the latest six runs; attention is explicitly limited to that sample.
- The canonical domain sidebar contains Overview, Problems, Records & relationships, Data structure, Data relationships (graph), Sources & imports, and Quality checks.
- The canonical problem sidebar contains Overview, Inputs, Build model, Versions, Scenarios, and Runs & results.
- Route IDs override remembered context. Global pages no longer inherit a domain sidebar. Existing legacy routes remain available.
- Inputs, data, structure, quality, and access hubs link to existing tools without duplicating their editing logic.
- Sources lists configured connections with domain-scoped pagination, access checking, and loading/error states.
- Build model exposes Guided Form, a read-only graph preview of the same current draft, Blocks, Exact IR, and an advanced link to published-model visualizations.
- Operational navigation uses the existing `solver.configure` capability. Access and Audit navigation use `iam.manage`; settings use `settings.edit`; sources use `integration.run`. These are navigation visibility rules, not new backend authorization policies.
- Readiness links stay in the canonical problem route and fetch failures no longer appear as missing prerequisites.
- Parent problem/data hubs do not highlight as the active page alongside a more specific child.

## Validation

144 focused tests passed across nine files, including routing, navigation, model editing, dashboard, solver UI, hubs, and readiness. After the browser-discovered active-link correction, all 39 AppShell tests passed again. TypeScript/production build and lint passed. The build retains its existing large-chunk advisory.

Authenticated Chrome walkthrough verified Home, problem navigation, Inputs, domain data navigation, and the graph preview on the running local app. The preview visibly rendered model nodes and connections. No model was published and no solve was submitted during this walkthrough.

The frontend image was built from the locally compiled distribution and the already-installed nginx image with build networking disabled. Only the frontend container was recreated; database, solver workers, and ingestion services were not recreated.

## Explicit remaining work

This is a navigation delivery, not the complete dual-editor implementation. Graph authoring remains unavailable; the graph is labeled as a preview. The import wizard, consolidated domain quality report, and per-worker heartbeat display remain unavailable and are labeled accordingly. Sources currently lists configuration; extraction remains accessible through the existing API. The broader draft, validation, and guided-pattern milestones remain in the proposal.

Legacy pages retain their compatibility sidebar. Migrating those pages completely to canonical routes is subsequent work. The existing Guided Form is relabeled and integrated, not replaced by the full proposed plain-language pattern library.
