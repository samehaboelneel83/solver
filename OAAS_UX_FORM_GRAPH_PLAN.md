# OaaS navigation, user experience, and dual problem builder

**Project:** D:\solver  
**Review date:** 27 September 2026  
**Deliverable:** implementation proposal with code examples; application code is not changed by this document.  
**Deployment constraint:** the product must operate inside an isolated environment without internet access.

## 1. Recommended direction

Build one coherent **Problem Workspace** around the user's journey: understand the problem, connect reliable data, describe decisions and rules, validate, solve, and explain the result. Provide two views of the same editable model:

1. **Guided Form** — the requested “soft form”: approachable questions, domain vocabulary, reusable rule patterns, and progressive access to mathematical expressions.
2. **Visual Graph** — the requested “soft graph”: editable cards for decisions, rules, and goals, with typed connections and a shared properties panel.

These are interaction modes, not competing model formats. The canonical problem IR remains the semantic authority. Changing views must never change the optimization problem, discard unsupported constructs, or create a second unsynchronized draft.

“Soft” here means easy to use. It must not imply that all constraints are soft. The interface must clearly distinguish **Required rule (hard constraint)** from **Preference (soft constraint)**.

The platform already has substantial foundations. Improve and unify them instead of replacing the editor, router, graph libraries, or solver stack wholesale. The strongest opportunity is trustworthy modeling and understandable results. No UI redesign can guarantee superiority on every optimization problem; solver quality and performance must be established through reproducible benchmarks by problem family.

## 2. Review scope and evidence

### 2.1 Browser review status

I opened the running platform in Chrome at `http://localhost:3010`. It redirected to `/login?next=%2F`. The visible accessibility tree contains the product name, “Welcome back,” labeled Username and Password fields, and a Sign in button. This confirms the local frontend and unauthenticated entry screen are reachable.

**The authenticated end-user walkthrough is incomplete:** the review browser has no authenticated session, and sign-in was requested from the user. No authenticated page layout, task completion time, responsive behavior, or keyboard journey is claimed as browser-verified in this document. Findings below are explicitly source-based unless marked otherwise. This is a concrete review limitation, not evidence that the application itself has a login defect.

### 2.2 Source findings

| Evidence | Current behavior or risk | Recommendation | Priority |
|---|---|---|---|
| [App router](frontend/src/App.tsx), [navigation registry](frontend/src/nav/registry.ts) | Domain and problem routes and contextual groups already exist, alongside legacy routes. Remembered domain context can influence navigation outside a domain route. | Make route scope authoritative; keep a recent-domain shortcut separate from active scope. Preserve old bookmarks through explicit redirects. | P0 |
| [Problem readiness](frontend/src/components/ProblemReadiness.tsx) | Readiness links use legacy query routes; the run/review step has `done: false`; fetch errors can resemble missing prerequisites. | Use canonical links and server-derived readiness states with distinct error/retry behavior. | P0 |
| [Model editor](frontend/src/pages/ModelEditor.tsx) | Forms and Blocks already edit one draft; problem and version selection depend on bounded lists of 500 and 50 items. | Retain shared semantics; fetch selected resources directly and paginate/search pickers. | P0 |
| [Draft store](frontend/src/model/draftStore.ts) | LocalStorage drafts have base-version conflict handling, memory fallback, and cross-tab synchronization, but no durable server draft or compare-and-swap revision. | Add authorized server drafts and revisions; keep local recovery as a cache with explicit status. | P0 |
| [Draft IR adapters](frontend/src/model/draftIr.ts) | Form updates preserve extra top-level data and publishing normalizes constraints. | Reuse and strengthen adapters with lossless coverage tests; do not regenerate the entire IR from graph nodes. | P0 |
| [Term types](frontend/src/model/terms.ts) | Arithmetic AST and boolean filters are correctly separated. | Keep this architecture; add plain-language patterns above it. | P1 |
| [Flow view](frontend/src/components/modelStyles/FlowView.tsx) | React Flow is currently a visualization: connection editing is disabled. It uses default nodes/edges, with a key based on IDs. | Build controlled editing; regression-test updates when content changes but IDs do not. Staleness is a source-level risk to verify, not a reproduced browser defect. | P1 |
| [Rete view](frontend/src/components/modelStyles/ReteView.tsx) | Controls are intentionally read-only. | Keep it as an advanced visualization during migration; do not present it as an editable builder. | P1 |
| [Domain graph](frontend/src/pages/GraphDemo.tsx) | The domain graph covers entities, relationships, schema, and model-related views. | Separate the navigation concepts “Data relationships” and “Problem builder” while preserving existing features. | P1 |
| [IR contract](docs/contracts/problem-ir.md) | The contract supports advanced constructs, including hard/soft constraints; soft weight is a positive integer. | Declare editor coverage explicitly. Preserve advanced rules and expose an advanced inspector rather than flattening them. | P0 |
| [Router](frontend/src/App.tsx), [database extraction runbook](docs/runbooks/database-extraction.md) | Backend ingestion capability exists, but the inspected router does not provide a dedicated Connections/Imports user journey. | Add a data-steward workflow over existing backend capabilities, with operational health and provenance. | P1 |

These findings do not imply that every listed risk is an observed production failure. Source inspection identifies likely friction and implementation gaps; the walkthrough and tests in section 14 must validate them.

### 2.3 External research and practical implications

The research used official documentation, not authenticated trials or performance benchmarks of competing products. Links are design references only; none becomes a runtime dependency.

| Reference | Useful principle for this platform |
|---|---|
| [GOV.UK: completing multiple tasks](https://design-system.service.gov.uk/patterns/complete-multiple-tasks/) | A long workflow needs a resumable task overview with meaningful progress states. Use this on Problem Overview; avoid forcing every visit through a wizard. |
| [GOV.UK: question pages](https://design-system.service.gov.uk/patterns/question-pages/) | Ask focused questions with useful hints. Apply this to first-time modeling while retaining a compact expert editing mode. |
| [GOV.UK: check answers](https://design-system.service.gov.uk/patterns/check-answers/) | Provide a review page with clear change actions before publishing or starting consequential work. |
| [IBM Decision Optimization client documentation](https://ibmdecisionoptimization.github.io/decision-optimization-client-doc/) | Scenario-oriented work connects data, models, solving, and comparison. Make those relationships visible and reproducible in this platform. |
| [Timefold score analysis](https://docs.timefold.ai/employee-shift-scheduling/1.33.x/user-guide/score-analysis) | Explain results through rule contributions and the affected business objects. Users need more than one aggregate objective value. |
| [React Flow accessibility](https://reactflow.dev/learn/advanced-use/accessibility) | Reuse the library's focus, keyboard, and ARIA facilities, then test custom nodes and inspectors. Library support alone does not establish application accessibility. |
| [React Flow connection validation](https://reactflow.dev/examples/interaction/validation) | Validate connections during interaction, with the application supplying type and domain rules. |
| [W3C: dragging movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html) | Provide a single-pointer alternative to dragging as well as keyboard operation. A keyboard shortcut alone is insufficient for this requirement. |

Accessed during this review on 27 September 2026. These sources inform the proposal; they do not establish that another product is faster or that this product already meets an accessibility standard.

## 3. End users and success criteria

| Persona | Primary job | Default experience |
|---|---|---|
| Planner / business user | Produce a useful plan and understand trade-offs | Existing problem, scenario inputs, solve, results, comparison |
| Modeler | Define and maintain decisions, constraints, and goals | Guided Form, Visual Graph, advanced expression inspector |
| Data steward | Deliver trustworthy input data | Sources, mapping, validation, immutable snapshots, refresh history |
| Operator / administrator | Keep execution and access reliable | Worker health, queues, policies, users, audit |

Navigation visibility should reflect capabilities, but server authorization remains mandatory. A planner must not need to understand solver internals or database credentials to use an approved model. An expert must still be able to inspect exact expressions, solver support, and provenance.

Set measurable targets after collecting a baseline:

- At least 90% of representative users complete “find a problem and open its latest usable result” without help.
- At least 80% of target business users build a supported template scenario and explain one preference violation without a developer.
- Reduce median time to first valid template model by 30% against the current application, using equivalent tasks and data.
- Zero silent semantic changes when switching editors or reopening a draft.
- Zero invalid solver submissions in compatibility regression fixtures; the server must still reject races and bypassed clients.
- Every blocking issue has a specific message, an actionable destination, and a stable identifier.
- No external network requests during the deployed product's full modeled workflow.

These are proposed acceptance targets, not measured results. Track confidence and participant counts alongside percentages.

## 4. Navigation architecture — first delivery priority

### 4.1 Proposed tree

```text
Home
  Continue working
  Recent results
  Attention needed
Domains
  [Domain]
    Overview
    Problems
      [Problem]
        Overview
        Inputs
        Build model
          Guided Form | Visual Graph
          Advanced: Blocks / exact IR / legacy visualizations
        Versions
        Scenarios
        Runs & results
    Data
      Records & relationships
      Data structure
      Data relationships (graph)
      Sources & imports
      Quality checks
Operations                         [operator capability]
  Runs & queues
  Workers & solver availability
Administration                     [admin capability]
  Access & policies
  Audit
Help                               [local, context-sensitive]
```

Only one contextual level is expanded at a time. In a problem, the main sidebar presents the six problem tasks; a compact context header identifies its domain and problem. Domain management is reached through the breadcrumb or a “Domain data” link. Keep Help and authorized operational utilities visually separate from the current task list.

“Inputs” means bindings and a chosen data snapshot for the problem; “Domain data” means reusable data assets. Explain this distinction in empty states. Do not put credential administration into the planner's scenario screen.

### 4.2 Route rules

- Keep existing `/domains/:domainId/problems/:problemId/...` paths as the foundation.
- Add `inputs`, `data/sources`, and `data/quality` only as their screens become usable.
- Use `model?view=form` and `model?view=graph` for views of the same resource. Preserve existing Blocks bookmarks through an adapter.
- A focused rule may use `?view=graph&rule=weekly_capacity`; switching to Form retains rule selection.
- URL scope wins over stored domain preferences. A recent domain is a suggestion, not an implicit reassignment of the current page.
- Validate that the problem belongs to the domain on the server and show a clear unavailable/mismatch page.
- Fetch a directly addressed problem/version by ID. Searchable paginated lists must not determine whether a deep link is valid.
- Browser Back restores scope, view, selected item, and relevant list filters without resurrecting another problem's draft.
- Retain compatibility redirects for legacy routes; centralize them and test them. Do not scatter query-to-path conversions across components.

### 4.3 Overview and readiness

Problem Overview should answer: What is this problem? What can I do next? What changed? Which result can I trust?

Show the problem description, owner, active draft/published version, chosen snapshot, last usable result, and a small task list. Example tasks: Connect inputs, Build model, Publish version, Create scenario, Run and review. Do not imply a successful run has been reviewed: store an explicit review event if the product needs that distinction.

Use readiness states `not_started`, `in_progress`, `ready`, `blocked`, and `unknown`. Fetch failures are `unknown`, with Retry and diagnostic detail. A missing model is `not_started`; unsupported solver requirements are `blocked`. Empty, loading, denied, missing, stale, and failed are different states.

## 5. Visual and interaction system

Use the project's existing design system and local assets. Establish shared components before redesigning individual screens:

- **PageHeader:** breadcrumb, title, one-sentence purpose, scoped metadata, one primary action.
- **ContextHeader:** domain/problem names, scoped switcher, draft/version status.
- **TaskStatus:** text plus icon, with color as an additional cue.
- **IssueSummary:** severity, affected rule/input, explanation, and “Go to issue.”
- **EmptyState:** why the page is empty and a specific next action.
- **SaveStatus:** distinguish “Saved to server,” “Saved on this device,” “Saving,” and “Save failed.”
- **Inspector:** reusable labeled controls shared between form and graph.
- **ResultSummary:** feasibility, objective, runtime, best bound/gap when available, termination reason, provenance.

Use a consistent spacing scale, readable body text around 16px, clear heading levels, and restrained borders. Use dense tables where useful, but keep editing controls legible. Do not shrink an entire graph or form to fit all content. Essential labels must wrap or have an accessible full-name alternative; hover-only tooltips are insufficient.

Provide visible focus, inline errors plus an error summary, stable focus after list edits, and status announcements that do not fire on every keystroke. Drawers need logical focus management and a close action; route changes need a meaningful document title. Avoid uncontrolled replacement of a form card while someone is typing.

At narrow widths, replace the graph-plus-inspector arrangement with a task list and a full-width inspector. The graph remains available, but the user can complete all supported editing tasks through forms and lists. Test 200% zoom, reflow, touch, keyboard-only use, and screen readers. Support localized labels and RTL layout in shared primitives; only commit to full translations after glossary and localization tests exist.

## 6. Guided Form: plain-language problem encoding

### 6.1 Progressive workflow

1. **Describe the outcome:** problem name, purpose, planning horizon, template or blank start.
2. **Choose inputs:** approved snapshot, entities, relationships, parameter mappings, units, and missing-data policy.
3. **Define decisions:** what is chosen, for which objects, and the allowed values/bounds.
4. **Add required rules:** facts every acceptable solution must satisfy.
5. **Add preferences:** desirable outcomes that may be violated with a documented penalty.
6. **Choose goals:** minimize/maximize supported objective terms; explain weights and units.
7. **Review:** natural-language summary, exact expressions, coverage, solver compatibility, and data readiness.
8. **Publish:** immutable version with a meaningful change note; then create or update a scenario explicitly.

This is a first-time path, not eight mandatory pages on every visit. After initial creation, show a compact section navigator with completion and issue counts. Expert users can jump directly to a rule.

### 6.2 Pattern library

| Pattern | Questions | Exact semantics to expose |
|---|---|---|
| Assignment | What is assigned? To what? Exactly one, at most one, or at least one? | Binary variables, index sets, sum and relation |
| Capacity | Which resource? Which period? What consumes capacity? | Aggregation scope, demand units, bound |
| Coverage | What must be covered? Minimum amount? | Required total and missing-demand behavior |
| Balance | Which groups should be comparable? | Chosen deviation formulation; no hidden nonlinear expression |
| Scheduling | Which activities? Duration? Resource? | No-overlap/cumulative semantics and supported adapter requirements |
| Connectivity | Which units must form one connected group? | Relationship, group binding, connectivity requirement |
| Routing | Stops, depot, vehicles, costs? | Route semantics and solver support |

Start with assignment, capacity, and coverage. Advanced patterns are released only after their IR coverage and solver tests pass. A pattern must explicitly declare what it can edit. An imported rule that does not match its shape opens in the advanced editor; never approximate it to fit a simple form.

Example sentence:

> For each employee and day, assign at most one shift. This is required.

The form has selectors for employee/day/shift sets and decision, plus a limit. “Show exact expression” reveals the IR-derived equation. Changing “Required” to “Preference” explains the consequence and asks for a positive integer penalty. It does not silently relax other rules or retry a failed solve with different semantics.

Use catalog-derived choices, unique index bindings, datatype checks, and units where supplied. Labels are human-readable; stable IDs remain internal references. Allow structured assistance offline; free-text notes must never become executable constraints without a reviewable compiled representation.

## 7. Visual Graph: editable, understandable, and accessible

### 7.1 Two different graph concepts

**Data relationships** shows business objects and links: factories, jobs, employees, roads. Cycles may be meaningful. **Problem builder** shows model dependencies: data sets and parameters feed decisions, rules, and goals. Do not use a blanket “graphs must be acyclic” rule across the product. Restrict recursive expression dependencies where required by the compiler, while allowing valid business-network cycles.

### 7.2 Graph composition

Use React Flow already present in the application. Default to a compact semantic graph, not a node for every arithmetic operation:

- Input/set card: source, type, coverage status.
- Decision card: business question, allowed values, dimensionality.
- Rule card: plain-language summary, Required/Preference label, issue count.
- Goal card: objective direction and contribution.
- Optional advanced expression subgraph inside a selected rule.

Node selection opens the same inspector controls used by Guided Form. Group cards by purpose, support collapse and search, and highlight the selected rule's dependencies. A layout change must never alter solver semantics or the model hash.

### 7.3 Editing operations

- Add via a toolbar button or keyboard command; dragging from a palette is optional.
- Connect via a typed port or “Connect input” dialog with searchable compatible choices.
- Explain rejected connections: wrong datatype, missing binding, incompatible units, unresolved reference, or forbidden expression recursion.
- Edit a rule through the shared inspector; support undo/redo for semantic actions.
- Delete through dependency inspection; identify impacted rules and require a specific resolution. Do not silently cascade-delete model content.
- Move via drag, keyboard controls, and clickable move/layout commands.
- Provide “Show as list” with the same selection and actions, plus screen-reader descriptions of relationships.

Typed edge proposals are semantic commands, not arbitrary canvas edges. A visual edge may summarize multiple IR references; disconnecting it needs a specific reference selection rather than deleting all uses of a variable.

Keep nodes/edges controlled from the latest draft projection. Store positions separately. Avoid rendering a node for every data record or variable instance; summarize counts and drill into a filtered preview. Benchmark realistic and large model fixtures before setting node limits.

## 8. Shared model architecture and data safety

```text
Guided Form ──┐
             ├─ validated semantic commands ─ draft IR + revision ─ server draft
Visual Graph ┘                                  │
                                                ├─ validation issues
                                                ├─ graph projection + separate layout
                                                └─ publish → immutable version
```

Retain `formDraftOf`, `withFormDraft`, `publishable`, and the existing IR contract as integration points. Add command-level adapters and tests rather than creating a parallel schema that competes with the IR.

Drafts may contain incomplete fields, so distinguish an editing envelope from a publishable IR. Keep temporary invalid text in field state or explicit draft-only slots; never coerce an empty numeric input to zero. Backend validation is authoritative at publication and execution.

### Required invariants

1. Form and graph share one draft identity, revision, base version, selection, and issue index.
2. Stable rule IDs drive React keys and graph IDs; array position is not identity.
3. Unknown or unsupported IR constructs survive view changes unchanged and appear as read-only advanced cards.
4. View/layout metadata does not enter the solve payload or semantic fingerprint.
5. Save uses expected revision; a conflict does not overwrite another editor's work.
6. Validation results apply only to the revision and snapshot they validated.
7. Publish names the draft revision; retries use an idempotency key and cannot create duplicate versions.
8. Local recovery is namespaced by installation/tenant/user/problem/draft. Apply the platform's data retention policy; do not cache credentials.
9. Server draft access is authorized against problem ownership/capability on every request.
10. Reload, logout, session expiry, and cross-tab edits have explicit recovery behavior.

For unsupported constructs, maintain a coverage matrix with columns for read, create, edit, round-trip, and solver support. Never claim “full graph support” merely because every constraint has a visible card.

## 9. Proposed code

The following examples are implementation starting points, **not installed application changes**. The pure helper functions illustrate concrete TypeScript behavior; framework/controller snippets are integration skeletons. They have not been compiled or executed during this documentation review. Resolve imports against the existing project, add the tests below, and pass normal project checks before merging implementation.

### 9.1 Canonical route helpers

Proposed file: `frontend/src/nav/problemPaths.ts`.

```ts
type ProblemScope = { domainId: number; problemId: number };
type ProblemPage = "overview" | "inputs" | "model" |
  "versions" | "scenarios" | "runs";

export function problemPath(scope: ProblemScope, page: ProblemPage): string {
  for (const id of [scope.domainId, scope.problemId]) {
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error("Invalid scope");
  }
  return `/domains/${scope.domainId}/problems/${scope.problemId}/${page}`;
}

export function modelPath(
  scope: ProblemScope,
  view: "form" | "graph",
  ruleId?: string,
): string {
  const query = new URLSearchParams({ view });
  if (ruleId) query.set("rule", ruleId);
  return `${problemPath(scope, "model")}?${query.toString()}`;
}
```

Verify exact existing overview conventions during implementation and adapt in one location. Helpers do not replace authorization. Do not enable a route in navigation until its screen exists.

### 9.2 One guided pattern compiles into the existing IR

Proposed file: `frontend/src/model/patterns/assignmentLimit.ts`. The selected variable must already be a declared binary decision indexed in the supplied order. Catalog validation is a required caller responsibility; the compiler validates its local inputs.

```ts
import type { Constraint } from "../terms";

export type AssignmentLimit = {
  id: string;
  note?: string;
  employeeSet: string;
  daySet: string;
  shiftSet: string;
  decision: string;
  limit: number;
  enforcement:
    | { kind: "required" }
    | { kind: "preference"; penalty: number };
};

export function compileAssignmentLimit(p: AssignmentLimit): Constraint {
  if (![p.id, p.employeeSet, p.daySet, p.shiftSet, p.decision]
      .every(value => value.trim().length > 0)) {
    throw new Error("Choose all sets and the decision");
  }
  if (!Number.isSafeInteger(p.limit) || p.limit < 0) {
    throw new Error("The limit must be a non-negative whole number");
  }
  if (p.enforcement.kind === "preference" &&
      (!Number.isSafeInteger(p.enforcement.penalty) ||
       p.enforcement.penalty < 1)) {
    throw new Error("The penalty must be a positive whole number");
  }
  return {
    id: p.id,
    ...(p.note === undefined ? {} : { note: p.note }),
    forall: [
      { index: "e", set: p.employeeSet },
      { index: "d", set: p.daySet },
    ],
    left: {
      sum: { var: p.decision, index: ["e", "d", "s"] },
      over: [{ index: "s", set: p.shiftSet }],
    },
    relation: "<=",
    right: { const: p.limit },
    ...(p.enforcement.kind === "required"
      ? { severity: "hard" as const }
      : { severity: "soft" as const, weight: p.enforcement.penalty }),
  };
}
```

The inverse recognizer must return either `editable(pattern)` or `advanced(originalRule)`. It must reject extra conditions, filters, traversals, unknown fields, incompatible index shapes, and other semantics it cannot reproduce. Keep the original rule until a supported edit commits. Round-trip tests must compare semantics, including severity and penalty, not just rule counts.

### 9.3 Transactional update without dropping other model fields

Proposed file: `frontend/src/model/commands/replaceRule.ts`. This example deliberately rejects rule keys outside the simple arithmetic pattern rather than stripping them. It is not a general-purpose advanced-rule editor.

```ts
import type { Constraint } from "../terms";

type Rule = Constraint & Record<string, unknown>;
type Draft = {
  revision: number;
  ir: Record<string, unknown> & { constraints: Rule[] };
};
type ReplaceRule = {
  expectedRevision: number;
  ruleId: string;
  replacement: Constraint;
};

const simpleKeys = new Set([
  "id", "note", "forall", "left", "relation", "right", "severity", "weight",
]);

export function replaceRule(draft: Draft, command: ReplaceRule): Draft {
  if (draft.revision !== command.expectedRevision) {
    throw new Error("The draft changed. Review the latest revision.");
  }
  const matches = draft.ir.constraints.filter(r => r.id === command.ruleId);
  if (matches.length !== 1) throw new Error("Rule ID is missing or ambiguous");
  const current = matches[0];
  if (command.replacement.id !== current.id) throw new Error("Rule ID changed");
  if (Object.keys(current).some(key => !simpleKeys.has(key))) {
    throw new Error("Use the advanced editor for this rule");
  }
  // Caller must also use the exact-shape recognizer before enabling this edit.
  // Replacing a recognized simple rule removes obsolete soft weight when hard.
  return {
    ...draft,
    revision: draft.revision + 1,
    ir: {
      ...draft.ir,
      constraints: draft.ir.constraints.map(rule =>
        rule.id === current.id ? { ...command.replacement } : rule),
    },
  };
}
```

Wrap this in the shared controller's undo/redo transaction. A graph inspector and a form card dispatch the same command. Creating, renaming, and deleting declarations require separate dependency-aware commands. Do not make the full store available for arbitrary canvas writes.

### 9.4 Shared issue contract and stale-result protection

Proposed file: `frontend/src/model/validation/types.ts`.

```ts
export type ModelIssue = {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  target:
    | { kind: "rule"; id: string; field?: string }
    | { kind: "input"; id: string; field?: string }
    | { kind: "model" };
};

export type ValidationResult = {
  draftId: string;
  revision: number;
  snapshotId: number | null;
  issues: ModelIssue[];
};

export function validationApplies(
  result: ValidationResult,
  current: Pick<ValidationResult, "draftId" | "revision" | "snapshotId">,
): boolean {
  return result.draftId === current.draftId &&
    result.revision === current.revision &&
    result.snapshotId === current.snapshotId;
}
```

Map stable rule IDs to fields and graph cards. Translate backend JSON paths to these IDs at the boundary; array offsets alone become stale after reordering. Show client checks immediately, then replace/augment them with revision-matched server checks. Validation errors must not prevent saving an incomplete draft, but must block publication where required.

### 9.5 Controlled graph integration skeleton

Proposed file: `frontend/src/components/model/VisualModelEditor.tsx`.

```tsx
import { ReactFlow, Background, Controls } from "@xyflow/react";

// Integration skeleton: controller, projection, inspectors and typed port
// validation are application modules to implement, not existing APIs.
export function VisualModelEditor({ controller }: EditorProps) {
  const projection = useModelProjection(controller.draft, controller.layout);
  return (
    <section aria-label="Visual problem builder">
      <ModelToolbar
        onAddRule={controller.openAddRule}
        onConnect={controller.openConnectionDialog}
        onShowList={controller.openAccessibleList}
      />
      <ReactFlow
        nodes={projection.nodes}
        edges={projection.edges}
        nodeTypes={modelNodeTypes}
        onNodeClick={(_, node) => controller.select(node.id)}
        onNodesChange={controller.applyPresentationChanges}
        isValidConnection={controller.canConnect}
        onConnect={controller.proposeConnection}
        nodesDraggable
        nodesConnectable
        deleteKeyCode={null}
      >
        <Background />
        <Controls />
      </ReactFlow>
      <SharedModelInspector controller={controller} />
    </section>
  );
}
```

The controller must handle React Flow selection/dimension/position changes, persist layout separately, and route semantic operations through validated commands. Custom nodes need the correct typed handles and accessible labels. `proposeConnection` opens the binding dialog when semantics are ambiguous; it must not call a generic `addEdge` and assume that edits the IR. Edge deletion likewise goes through an explicit semantic action. The accessible list and connect dialog are required deliverables, not placeholders for a later accessibility pass.

### 9.6 Durable draft API proposal

These endpoints are **proposed**, not asserted to exist. Reconcile the prefix with the backend's existing versioned router conventions during implementation.

```http
POST /api/v1/problems/{problem_id}/drafts
Content-Type: application/json

{"base_version_id": 42}

GET /api/v1/problems/{problem_id}/drafts/{draft_id}
→ 200, ETag: "draft-7"

PATCH /api/v1/problems/{problem_id}/drafts/{draft_id}
If-Match: "draft-7"
Content-Type: application/json

{"ir": {"version": 2, "...": "complete draft document"}}

POST /api/v1/problems/{problem_id}/drafts/{draft_id}/publish
If-Match: "draft-8"
Idempotency-Key: <unique-publication-request-id>
Content-Type: application/json

{"note": "Adjust daily assignment limit", "expected_revision": 8}
```

The ellipsis payload above is schematic, not valid IR for submission. Store layout through a separate presentation endpoint/revision so arranging nodes cannot change a semantic revision or cause a model conflict unnecessarily.

Inside a database transaction, update the draft only where its ID, authorized scope, and expected revision match. Return `412 Precondition Failed` for an ETag mismatch; include the latest revision and a safe reload/compare path. Publish validates and creates the immutable version in the same transaction, with an idempotency record scoped to the actor/problem and request digest. A reused key with different content must fail. Add body-size limits, retention, and audit consistent with the application.

The local store remains useful for disconnected browser-to-server recovery. Clearly distinguish that temporary disconnection from the normal isolated deployment: a healthy isolated server does not need internet to save drafts.

### 9.7 Meaningful tests to add

```ts
it("a required pattern has no penalty", () => {
  const rule = compileAssignmentLimit({
    id: "daily_limit", employeeSet: "employees", daySet: "days",
    shiftSet: "shifts", decision: "assign", limit: 1,
    enforcement: { kind: "required" },
  });
  expect(rule.severity).toBe("hard");
  expect(rule).not.toHaveProperty("weight");
  expect(rule.left).toEqual({
    sum: { var: "assign", index: ["e", "d", "s"] },
    over: [{ index: "s", set: "shifts" }],
  });
});

it("does not apply validation from a previous snapshot", () => {
  expect(validationApplies(
    { draftId: "a", revision: 3, snapshotId: 10, issues: [] },
    { draftId: "a", revision: 3, snapshotId: 11 },
  )).toBe(false);
});
```

Beyond these examples, use fixture-based round-trip and integration tests: form → graph edit → form → publish; unknown advanced rule unchanged; two tabs editing revision 7; undo across view changes; disconnected save and recovery; reference rename; selected version outside page one; hard/soft transition; stale validation; rejected solver; and complete keyboard/non-drag graph editing. Test compiled semantics with existing compiler fixtures, not screenshots alone.

## 10. Inputs and database integration experience

The user-facing capability should be “Use reliable data,” supported by a source registry with explicit adapter availability. Do not advertise “any database” without a supported and tested adapter matrix.

For each installed adapter, expose:

1. Connection definition with a human-readable name and allowed source scope.
2. Credential reference and transport requirements, without displaying stored secrets.
3. Connection test that distinguishes policy denial, TLS/CA failure, authentication failure, unavailable worker, and unreachable source.
4. Schema selection and a bounded preview with redaction where needed.
5. Mapping to platform entity/relationship/parameter structures, including datatype, keys, units, null policy, and timezone.
6. Validation of duplicates, broken references, missing values, and incompatible units before import.
7. Import progress, cancellation semantics, row counts, warnings, and actionable failures.
8. Immutable snapshot with source, extraction time, mapping revision, counts, and checksum/provenance.

A planner selects approved snapshots; a data steward manages refreshes. Show freshness separately from validity. Do not replace the inputs of a published scenario or completed run when a source refreshes. A new snapshot is a new deliberate choice.

The existing ingestion operational runbook should feed an administrator readiness panel: encryption configured, policy ready, CA configured where required, worker heartbeat, adapter available. Report states without disclosing key values or internal credentials. This makes a configured-but-unavailable ingestion service understandable from the UI.

## 11. Solver selection and results users can trust

Before submission, show model requirements derived from the compiled model and selected snapshot. Compare them against available adapter capabilities. Default to a compatible automatic policy; allow an expert to choose an engine with a clear explanation of supported and unsupported requirements.

For an incompatible PSO selection, use specific language such as: “This model requires connectivity constraints that this PSO adapter does not support. Choose a compatible solver.” The exact message must come from the actual capability result, not a hard-coded assumption about all PSO implementations. Do not silently change solver, weaken constraints, or declare a failed historical run successful.

Recheck compatibility on the server when queuing the run. Include model version, snapshot, scenario overrides, solver configuration, seed where applicable, and environment provenance in the run record. A compatibility check is not a feasibility proof.

Results should distinguish:

- Optimal solution, with the backend's evidence.
- Feasible solution with remaining gap/bound when available.
- No solution found within limits.
- Proven infeasible, when the engine can establish that.
- Unsupported model, invalid input, infrastructure failure, or cancellation.

Show objective decomposition, violated preferences, affected objects, and rule explanations. A feasible solution should have no violated required rules after validation. Provide comparisons on the same definitions/units; explicitly flag changed versions or snapshots. Infeasibility diagnosis must indicate whether it is a certified conflict set or a heuristic explanation.

Offer planner-oriented tables, schedules, or maps only for problem types with suitable result schemas. Generic JSON remains an expert export, not the primary result experience. Do not treat a numeric objective alone as evidence of business quality.

## 12. Delivery milestones and ownership

Illustrative sequence for a small team: one frontend engineer, one backend/modeling engineer, shared designer/product owner, and QA/accessibility support. Estimates assume existing tests and infrastructure remain usable; refine after milestone 0. Work should be gated by outcomes, not by calendar alone.

| Milestone | Approximate duration | Deliverables and likely files | Exit gate |
|---|---|---|---|
| M0 — complete evidence | 3–5 days | Authenticated walkthrough, route inventory, representative IR fixtures, measured baseline | Browser evidence and user task failures recorded; no invented observations |
| M1 — navigation and states | 1 week | `nav/registry.ts`, route helpers, `App.tsx`, `ProblemReadiness.tsx`, direct resource loading in `ModelEditor.tsx` | Deep links/back/refresh work; readiness error and completion states truthful |
| M2 — safe shared drafts | 1–2 weeks | `model/draftStore.ts`, command adapters, validation contract, backend draft model/migration/API | Conflict, recovery, unsupported-IR preservation, revision-matched validation pass |
| M3 — Guided Form | 1–2 weeks | Shared inspector, pattern registry, assignment/capacity/coverage forms, review page | Representative users create a valid model; exact IR matches intended semantics |
| M4 — editable Visual Graph | 2 weeks | Controlled React Flow editor, projection, ports, layout store, accessible list/dialogs | Form/graph round-trip and all editing alternatives pass |
| M5 — inputs and run confidence | 1–2 weeks | Sources/imports UI over existing API, snapshot selection, solver preflight, result explanations | An approved-source-to-explained-result journey succeeds without developer help |
| M6 — release qualification | 1 week | Accessibility review, offline packaging, performance and benchmark report, local help | No semantic loss, external requests, or unresolved critical task blockers |

Plan approximately 8–12 weeks depending on advanced-pattern coverage. Do not delay navigation fixes until graph editing is complete. Do not promise every advanced IR construct in the first graph release.

### Immediate next milestone: M1 backlog

1. Centralize canonical domain/problem path creation and legacy redirects.
2. Make route scope authoritative in the navigation registry; keep recent context as an explicit shortcut.
3. Replace readiness legacy links and hard-coded completion with real data; add loading/error/denied states.
4. Resolve selected problem/version independently from paginated options.
5. Introduce consistent page headers, empty states, and save-status language.
6. Rename user-facing concepts to “Guided Form,” “Visual Graph,” and “Data relationships”; label existing non-editable views truthfully until replacement is ready.
7. Test one domain/problem journey, direct deep links, Back, refresh, missing resources, and capability filtering.
8. Review with a planner and a modeler before proceeding to the larger editor work.

Do not rename current routes or remove legacy visualizations abruptly. Release behind configuration where appropriate, migrate bookmarks, and retain a recovery path to the existing editor until coverage is proven.

## 13. Benchmarking improvement honestly

Separate four measures: ease of use, semantic correctness, solve quality, and operational reliability. A modern appearance does not establish superiority on the latter three.

Build a versioned benchmark set for assignment, scheduling, routing, connectivity, and representative customer models. Record hardware, adapter versions, time/memory budgets, model size, feasibility checks, objective/gap, and seeds for stochastic methods. Use repeated runs where randomness matters and report distributions, failures, and unsupported classes. Compare only configurations with equivalent semantics and budgets. Never “win” by removing constraints.

For UX, observe representative users on equivalent tasks in this application and, where access is available, selected alternatives. Measure success, errors, time, and ability to explain the result. Competitor documentation review in this proposal is inspiration; it is not a comparative usability study.

Use local, opt-in or policy-approved event collection for task analysis. No external analytics are required. Avoid capturing raw model data or credentials in telemetry.

## 14. Authenticated walkthrough and release checklist

The following is the outstanding browser audit and later release acceptance script. Record observed behavior, not just pass/fail assertions from source code.

| Task | Evidence to collect | Acceptance |
|---|---|---|
| Sign in and resume work | Landing page, active scope, visible next action | User recognizes where they are and can resume a relevant problem |
| Find another problem | Navigation choices, search/filter behavior, breadcrumb | No accidental domain switch or lost draft |
| Open an older version by URL | Direct resource resolution | Works even when the version is outside the first list page |
| Build a daily assignment rule | Labels, errors, preview, published IR | Business intent and exact rule agree |
| Switch Form → Graph → Form | Content, selection, saved status | No semantic changes or lost fields |
| Edit without dragging | Connect dialog, move controls, keyboard/list | All supported graph operations remain available |
| Load an advanced imported model | Unsupported-rule handling | No dropped/rewritten constraints |
| Simulate save conflict/disconnection | Recovery choices and draft integrity | No silent overwrite or false saved status |
| Choose an incompatible solver | Preflight and server response | Specific explanation, preserved model, valid alternatives |
| Inspect a finished/failed run | Status, provenance, explanation | User can distinguish solution quality from execution failure |
| Use source/import workflow | Mapping, TLS/policy/worker errors, snapshot | Data provenance and next action are clear |
| Use narrow viewport and 200% zoom | Focus, labels, controls, reflow | Core tasks complete without inaccessible hidden controls |
| Block external network access | Browser request log and full workflow | All deployed assets/help/features required for workflow remain usable |

Use a designated review account and test fixtures for write operations. Capture baseline task timings before redesign, then repeat after each milestone. Include permission-limited accounts, empty domains, populated domains, and large lists. Test save/publish failures, not only successful paths.

## 15. Decision and release boundaries

Approve the architecture first: one canonical IR, two synchronized editors, one problem workspace, explicit data lineage, and server-enforced solver compatibility. Deliver navigation and truthful states before expanding the modeling surface.

Defer a new graph engine, mandatory cloud AI, a wholesale frontend rewrite, and claims of universal database or solver coverage. Each would increase scope without first resolving the observed workflow fragmentation.

The next concrete implementation should be **M1**, followed by the draft/command foundation in **M2**. Authenticated browsing remains necessary to validate visual judgments and usability priorities. This file is ready as an engineering proposal, with that evidence gap explicitly retained.
