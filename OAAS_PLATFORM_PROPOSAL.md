# Proposal: a professional, fully offline optimization platform

**Date:** 26 September 2026  
**Status:** Phase 0–5 (`cff508a`) and scale S01–S03 (optional ClickHouse, Idempotency-Key, execution-attempt fencing) on `master`. See `docs/plans/2026-09-26-oaas-phase0-baseline.md`.
**Primary priority:** Navigation, readability, and a complete planning workflow  
**Deployment assumption:** An isolated installation with no public internet. Browsers can reach the platform over localhost or a private network.

## 1. Product direction

Build a platform where a planner can understand a problem, prepare its data, describe decisions and rules, compare alternatives, and adopt a defensible plan without learning database structure or solver internals.

The strongest opportunity is to combine:

1. A clear, problem-centered user experience.
2. Broad mathematical coverage through a shared model contract and verified solver adapters.
3. Explainable results, controlled re-optimization, and reproducible evidence.
4. Dependable installation, operation, and support entirely inside an isolated environment.

The project already has substantial foundations for these goals. Its next major investment should be making those foundations coherent and usable, rather than adding another long list of isolated solver features.

**Recommended positioning:** “An offline decision platform that turns operational data into verifiable plans, explains the trade-offs, and improves decisions as conditions change.”

### What “outperform other platforms” should mean

No credible platform can guarantee that it solves every possible optimization problem, proves every optimum, or beats every competing solver on every instance. A supported formulation may still be infeasible, unbounded, numerically difficult, or too large for the available resources.

Replace that promise with a measurable objective: outperform selected baselines on agreed workload families, under equal resource budgets, while reducing the time users spend preparing, understanding, and applying a result.

Track both **optimization performance** and **decision workflow performance**. A faster solve is of limited value if users cannot construct the right model or interpret the answer.

This proposal does not claim a current market ranking. It uses local source code, repository documentation, and recorded benchmarks; no external competitor research was performed.

## 2. Assessment of the current project

### Review scope and evidence limits

This is a source-level assessment of the React application, navigation and context hooks, API and worker structure, solver selection and result handling, container configuration, existing plans, handover notes, and selected benchmark reports. Test files were inventoried, but the full test suites, deployment, visual interface, and performance benchmarks were not rerun for this proposal. Historical test and deployment statements remain repository-reported evidence.

The current `handover.md` is more recent than the September 22 platform report and describes completed work that older plans still present as future tasks. Source files confirm that several of those capabilities now exist. Implementation planning must reconcile these documents before assigning new work.

### Existing strengths to preserve

| Area | Evidence in the repository | Product implication |
|---|---|---|
| Common modeling contract | `docs/contracts/problem-ir.md`, backend IR models and validation, frontend IR validation and parity tests | Preserve one meaning across forms, blocks, visualization, and execution. |
| Solver independence | `backend/app/solve/classify.py`, `compile.py`, `backends.py`, `adapters.py` | Users can model decisions without choosing a mathematical engine first. |
| Broad execution capabilities | LP/IP/MILP, quadratic and supported nonlinear classes, scheduling, routing, network, spatial, robust and stochastic modules | Build a verified coverage catalog instead of presenting the product as only a scheduling tool. |
| Result honesty | `backends.py` distinguishes global, local, and approximate guarantees; `result.py` includes bounds and ranging | Make these distinctions prominent in the result experience. |
| Reproducibility foundations | Immutable model versions, frozen datasets, solution records, result cache | Preserve lineage when navigation and workflow change. Run lifecycle rows themselves remain mutable while execution progresses. |
| Planner tools | Locks, stay-close penalties, comparison, why-not probes, LP ranges, `PlannerPanel.tsx` | Improve discoverability and interaction rather than rebuilding these services. |
| Model quality gates | Suite cases, version checks, shadow runs, nightly regression infrastructure | Turn these into a readable model release workflow. |
| Multi-user operations | Organization scoping, capabilities, quotas, fair PostgreSQL queue, subprocess isolation, audit and backup modules | Extend the existing architecture before introducing new infrastructure. |
| UX groundwork | Sidebar groups, command palette, breadcrumbs, mobile drawer, focus handling, unsaved-change guard, themes | Refactor the information architecture while retaining these protections. |
| Local spatial assets | Tile configuration, road and terrain processing | Offline geospatial planning can be a distinctive product capability. |

### Main issues and priorities

| Priority | Finding | Recommended response |
|---|---|---|
| P0 | Navigation mirrors data structures and technical administration more than a planner's task. | Introduce the navigation hierarchy in Section 3. |
| P0 | Domain selection is persisted globally, while problem/version/scenario selection varies by page and URL. | Make explicit URL context authoritative and validate its ownership chain. |
| P0 | `useModelTarget.ts` and `Workspace.tsx` can fall back to the first available object when an explicit selection does not resolve. | For explicit links, show an unavailable or mismatched-context state instead of silently substituting another problem. |
| P0 | There are separate Runs and Workspace entry points for closely related solving/results activities. | Give each run one canonical detail page; make guided cards a view within it. |
| P0 | Air-gapped runtime is not the same as a reproducible air-gapped installation. Dockerfiles use `pip install` and `npm install`; images use tags. | Deliver complete, versioned offline installation and upgrade bundles. |
| P1 | Planner follow-ups remain uneven: the handover identifies missing cell-click locking, a what-if form, and a shadow report UI. | Finish these high-value workflow gaps before new mathematical research. |
| P1 | Administrative navigation exposes Users, User roles, Roles, Role capabilities, and Capabilities separately. | Provide user and role detail screens with assignments and permissions inside them. |
| P1 | Large non-binary results can lose stored amounts above the cap in `_kept_amounts`. | Introduce chunked result storage and paginated access before promising large-scale replay and re-optimization. |
| P1 | Solver improvements have workload-dependent benefits. | Retain conservative defaults and promote changes only through benchmark gates. |
| P1 | Operational capabilities exist, but the main router lacks dedicated queue, audit, backup, and shadow-report pages. | Add a focused Operations area, reusing existing APIs where possible. |
| P2 | The solve service coordinates many policies in a file of more than 2,000 lines. | Extract explicit stages gradually, protected by existing regression cases. |

### What the recorded benchmarks actually establish

- The September 24 portfolio report records gains on some families and roughly two-to-four-fold slowdowns on some scheduling/districting cases. Its overall recommendation is to leave the feature off by default.
- The September 25 selector report contains 66 examples, 50 with a proof. It improves fastest-solver selection in that experiment, but only 16 of 25 confident picks are correct. Confidence is a neighbor vote share, not a calibrated probability of success. It remains in shadow mode.
- The September 23 MIPLIB report covers ten instances and two backends at 60 seconds each. Each backend proves two instances, and the report records zero wrong results under its checks. This is useful regression evidence, not evidence of universal superiority.
- Commercial adapter examples are documented, but the handover and adapter documentation explicitly identify vendor integrations that have not been tested with a license.

These are reasons to build a disciplined performance program, not reasons to discard the engine.

## 3. First priority: redesign the navigation tree

### 3.1 A consistent object hierarchy

Use the following hierarchy throughout the application:

```text
Organization
└── Domain: shared operational data and vocabulary
    ├── Data: records, relationships, parameters, maps
    └── Problem: a decision to optimize
        ├── Model versions: immutable published definitions
        ├── Scenarios: alternative assumptions and rule changes
        └── Runs: executions using a specific version and frozen data
            └── Results: decisions, explanations, comparisons, exports
```

Do not add a new “Project” or “Workspace” database entity simply to modernize the terminology. The existing organization/domain/problem hierarchy is a useful foundation. Explain **Domain** as “shared data for a business area,” with examples such as Workforce, Fleet, or Distribution.

An approved plan would be a new business object referencing a result. It must not be confused with a model version being published or a solver reporting optimality.

### 3.2 Global navigation

The global sidebar should have five main destinations, with Administration separated at the bottom. The expanded tree below describes destination ownership; it is not a requirement to show every child simultaneously.

```text
[Organization selector, if the account has multiple organizations]

Home
Domains
├── All domains
└── Recently opened / pinned domains
Template Library
Operations                                      [authorized operators]
├── Run queue
├── Workers & capacity
├── Solver health & licenses
├── Audit history
└── Backups & recovery
Help
├── Getting started
├── Modeling guide
├── Problem coverage & limitations
├── API reference
└── Release notes

Administration                                  [authorized administrators]
├── Organization settings
├── Users
├── Roles & permissions
├── API access
├── Platform settings
└── Installation & updates

[Account menu: profile, theme, language when available, sign out]
```

Home should offer “Continue planning,” recent problems, runs needing attention, and “Start from a template.” It should not lead with database counts or infrastructure status for ordinary planners.

Template Library contains locally installed, versioned templates. Installation & updates imports approved local bundles; it is not an online marketplace.

### 3.3 Domain navigation

Selecting a domain opens a contextual sidebar with an explicit “All domains” return link.

```text
< All domains
[Domain: Workforce]

Overview
Problems
Data
├── Records
├── Relationships
├── Parameters
├── Map & graph
└── Imports & validation
Data Structure                                  [modelers / data stewards]
├── Record types
└── Relationship types
Domain Settings                                 [authorized users]

[Global destinations remain accessible through a labeled menu]
```

“Record types” maps to the existing `entity_type` concept. “Records” maps to `entity`. Keep technical terms in API documentation and an expert glossary, but use clear business examples in the UI: Employees, Vehicles, Depots, Products.

Map, graph, and table are views of the same scoped data. Preserve selection and filters where their semantics are compatible. Do not turn every visualization into a global navigation item.

### 3.4 Problem navigation: the everyday planning experience

Inside a problem, show six primary destinations and keep Settings secondary:

```text
< Workforce / Problems
[Problem: Weekly staffing]

Overview
Inputs
Model
Scenarios
Runs & Results
Quality Checks                                  [authorized modelers]

Problem Settings                                [secondary]
```

Use page tabs for the next level:

| Destination | Page tabs or sections | Main action |
|---|---|---|
| Overview | Readiness, recent activity, latest accepted plan | Continue next incomplete step |
| Inputs | Required data, parameter values, validation, source lineage | Validate inputs |
| Model | Decisions, Rules, Goals, Validation, Versions | Publish version |
| Scenarios | Scenario list; selected scenario assumptions and comparison | Create scenario / Run scenario |
| Runs & Results | Run history; selected run detail | Open result / Compare runs |
| Quality Checks | Test cases, version checks, shadow comparisons | Check candidate version |
| Problem Settings | Defaults, solve budgets, ownership | Save settings |

Inputs references the domain's shared data. It must distinguish shared-data edits from scenario-specific overrides. A planner should never unknowingly change every scenario while exploring one alternative.

Within **Model**, Forms should be the default editing experience. Blocks and advanced JSON are alternate representations of the same draft, not separate models or independent navigation branches. Graphical styles should remain views unless they offer a fully supported edit round-trip.

### 3.5 Run detail structure

```text
Workforce / Weekly staffing / Runs / Run 482

[Status] [Scenario] [Model version] [Data snapshot] [Submitted by]

Summary | Plan | Rules & Explanations | Compare | Execution Details

Contextual actions:
  Stop                         while running
  Re-run                       when permitted
  Create scenario from result
  Ask “Why not?”
  Export
  Submit for approval          after the approval workflow is implemented
```

The Summary should answer: Is there a usable plan? What does it achieve? Is it proven best, approximate, or locally optimal? What remains uncertain? What should I do next?

Put solver names, parameter dumps, and detailed logs in Execution Details. Keep objective values, business units, critical violations, proof status, and data freshness visible in Summary.

Reuse the existing guided GenUI cards inside this page. They are generated from run events; they should not imply that a conversational AI understands arbitrary user questions.

### 3.6 Navigation behavior contract

1. **Context is always visible.** Show the domain and problem name in the page header even when the sidebar is collapsed. Add scenario and version where relevant.
2. **URLs identify the object.** A bookmark opens the same problem and run in another authorized user's browser, regardless of that browser's previous domain selection.
3. **Explicit invalid selections never silently switch.** Show a clear unavailable/context-mismatch page with links to authorized parent objects. Default selection is acceptable only when no explicit selection was requested.
4. **Keep the primary navigation shallow.** Use sidebar groups and page tabs, not a permanently expanded organization/domain/problem/scenario/run tree.
5. **Preserve meaningful state.** Back/Forward restores filters, selected tabs, comparison choices, and pagination. Persist optional display preferences per user, without allowing them to override URL identity.
6. **Protect drafts on every exit.** Sidebar links, command palette, breadcrumbs, context switchers, and browser navigation share the same draft protection contract.
7. **Permissions control both visibility and actions.** A hidden link is not an authorization boundary; APIs must still enforce scope and capability checks.
8. **Separate missing prerequisites from missing permission.** Explain “Publish a model version first” and link to that step. Do not display unexplained disabled controls.
9. **Search is specific.** Label the existing function “Go to page.” Extend it later to “Search this organization,” with grouped authorized results for domains, problems, scenarios, and runs. Search runs locally.
10. **Use consistent focus and keyboard behavior.** Preserve mobile drawer focus handling, add complete dialog focus containment/restoration, and keep the active destination visible when groups collapse or filters change.

### 3.7 Route design and migration

Proposed canonical routes:

```text
/home
/domains
/domains/:domainId/overview
/domains/:domainId/data/records
/domains/:domainId/data/relationships
/domains/:domainId/data/parameters
/domains/:domainId/data/explore
/domains/:domainId/data/imports
/domains/:domainId/structure/record-types
/domains/:domainId/structure/relationship-types
/domains/:domainId/problems
/domains/:domainId/problems/:problemId/overview
/domains/:domainId/problems/:problemId/inputs
/domains/:domainId/problems/:problemId/model
/domains/:domainId/problems/:problemId/versions/:versionId
/domains/:domainId/problems/:problemId/scenarios/:scenarioId
/domains/:domainId/problems/:problemId/runs/:runId
/domains/:domainId/problems/:problemId/quality
/templates
/operations/queue
/administration/users
/help
```

Use query parameters for view state such as `tab`, `q`, `sort`, and `compare`. Verify the domain/problem/scenario/version/run relationship on the server. Do not infer authorization from a valid-looking URL.

| Current destination | New ownership |
|---|---|
| `/` | Home |
| `/public/domain` | Domains |
| `/entities`, `/relationships`, `/parameters` | Selected domain → Data |
| `/entity-types`, `/relationship-types` | Selected domain → Data Structure |
| `/graph` | Selected domain → Data → Map & graph; model-specific views belong in Model |
| `/public/problem` | Selected domain → Problems |
| `/model`, `/versions` | Selected problem → Model and version detail |
| `/scenarios` | Selected problem → Scenarios |
| `/runs`, `/workspace` | Selected problem → Runs & Results; Workspace becomes the guided run view |
| `/public/template` | Template Library |
| `/solvers` | Operations → Solver health & licenses |
| `/settings` | Split by platform/domain/problem scope; account preferences stay in the account menu |
| `/iam/*`, `/api-keys` | Administration; personal API access can remain available by capability |

Keep old URLs as compatibility entry points during migration. Resolve scope from referenced objects when authorized. If an old link has no identifying context, ask the user to choose a domain/problem in-page. Preserve supported filters and give an explicit message for unsupported old view state.

Implement a shared route/navigation registry used by the sidebar, command palette, breadcrumbs, page titles, and compatibility mapping. `AppShell.tsx` currently supplies groups to the command palette, but routes and icons are still separately maintained. The new registry should make destination ownership and capabilities explicit.

### 3.8 Navigation acceptance criteria

The following are proposed release targets, not measured current results:

- At least 90% of representative users complete “find a problem,” “change a scenario,” and “open the latest result” without assistance in a moderated pilot.
- A returning planner reaches the latest relevant result from Home in no more than three navigation actions.
- At least 8 of 10 first-time pilot users reach a sample result within ten minutes using a bundled template and sample data.
- Every old supported deep link is covered by a migration test; none silently selects a different explicit object.
- Cross-domain links, stale IDs, expired sessions, browser Back/Forward, two browser tabs, and draft exits have integration coverage.
- Sidebar, dialogs, editor controls, and results remain usable by keyboard and at narrow widths and enlarged text. Target WCAG 2.2 AA as a design and verification objective, not a certification claim.

## 4. Make the interface readable and professional

### One visual system

Review and reuse the repository's `MCAIT Design System` assets when implementing the UI. First establish a token mapping for colors, spacing, typography, borders, and interaction states; do not copy an unrelated visual style onto individual screens.

- Use readable body text, typically 14–16 px, and a clear heading hierarchy. Reserve small text for supporting metadata.
- Keep primary navigation in sentence case. Avoid small uppercase headings as the main way to communicate hierarchy.
- Give every page a title, one sentence of purpose, visible context, and one primary next action.
- Provide comfortable and compact table density, sticky headers, column selection, saved views, units, and clear empty states.
- Show human labels by default, with copyable identifiers available in details.
- Communicate state through words and icons as well as color. Distinguish Draft, Published, Running, Feasible, Proven optimal, Infeasible, and Failed.
- Treat loading, no data, validation failure, stale data, permission denied, and server unavailable as different states with different recovery actions.
- Keep accessibility and reduced motion behavior through the redesign. An RTL layout toggle is not an Arabic translation; only offer a language once labels, dates, numbers, help, and layouts have been implemented and checked.

### Guided setup without trapping experienced users

A new problem should offer a short checklist:

```text
Choose a template or blank model
→ Connect or import inputs
→ Define decisions, rules, and goals
→ Validate and publish
→ Create a scenario
→ Run and review
```

Each step opens the corresponding ordinary page. Experienced users can navigate directly. The checklist records readiness; it must not become a second editor with different behavior.

### Complete the operational planning loop

Prioritize the existing handover gaps:

1. Click a decision cell to lock it; show what is locked and the source run. Retain accessible picker controls.
2. Offer a what-if form for parameter changes with units, validation, and a clear scope summary.
3. Present run comparison in business terms: cost, coverage, delay, resource use, and number of changed assignments.
4. Explain why-not outcomes as feasible with trade-offs, infeasible with evidence, or unresolved within the budget.
5. Expose shadow comparisons and version check failures inside Quality Checks.
6. Keep generated suite scenarios out of ordinary scenario lists by default, with an explicit technical filter.

For scenario data editing, propose **typed scenario overrides over a named base snapshot**, rather than cloning and silently changing the domain. Validate keys, units, types, and scope; include override content in reproducibility and cache identity. Review this schema decision before implementation because the handover identifies it as unresolved.

## 5. Optimization strategy: broad coverage with measurable advantages

### 5.1 Publish a capability catalog

For each supported family, document the IR constructs, supported combinations, available installed solvers, expected proof semantics, practical limits, and a working example. A backend's advertised mathematical class is not proof that every formulation in that class is expressible through the current IR.

| Family | Current foundation | Next product investment |
|---|---|---|
| Linear allocation and blending | LP backends, quantities, duals and ranges | Units, data validation, sensitivity presentation, large sparse data paths |
| Integer and mixed-integer planning | CP-SAT, HiGHS, MILP wrapper, SCIP | Stronger tested formulations, useful warm starts, family-specific solve budgets |
| Scheduling | Scheduling IR/editor and CP-SAT facilities | Calendars, timeline interaction, locked commitments, explainable rescheduling |
| Routing and distribution | Routing, distance, road and spatial modules | Offline map packages, route feasibility checks, realistic time/capacity examples |
| Facility location and territory design | Facility, partitioning and connectivity modules | Scalable templates and business trade-off views |
| Quadratic and supported nonlinear models | SCIP, IPOPT, convexity/function classification | Numerical diagnostics, explicit supported expressions, local/global result distinctions |
| Robust, stochastic and multi-objective models | Robust/stochastic and Pareto modules | Assumption editors, reproducible sample sets, understandable risk/trade-off views |
| Heuristic search | Existing search methods and fallbacks | Explicit feasible-solution checks and honest lack of optimality proof |
| Customer-supplied solvers | Manifest adapters, conformance and license handling | Offline integration certification for each actual binary/version/license combination |

Keep unsupported combinations explicit. For example, the handover states that locks and stay-close are refused on stochastic solves. Surface this before submission rather than suggesting that every feature composes automatically.

### 5.2 Improve formulations before adding infrastructure

Measure data loading, compilation, model construction, queue wait, solve time, result verification, persistence, and rendering separately. Optimize the dominant phase for each family.

Prioritize tighter valid bounds, sparse index sets, appropriate scheduling/routing formulations, safe presolve, symmetry handling, tested warm starts, and reuse of unchanged inputs. These improvements often benefit the whole workflow without requiring another engine.

Every transformation needs a declared guarantee: equivalent reformulation, relaxation providing a bound, or heuristic providing a candidate. Verify recovered decisions against the original model semantics, not just transformed solver rows.

### 5.3 Conservative automatic strategy selection

Retain capability and license eligibility checks as mandatory gates. Add selection intelligence only after those checks.

Proposed strategy hierarchy:

1. Respect an authorized explicit solver request; reject unsupported requests clearly.
2. Use validated family defaults under a declared time, memory, and CPU budget.
3. Reuse a compatible prior solution when it improves time to a feasible answer.
4. Permit a limited portfolio only for families where measured gains justify it.
5. Promote the learned selector from shadow mode only after it beats the baseline on held-out local workloads and meets regression limits.
6. Fall back conservatively for unfamiliar structures, low evidence, missing licenses, or worker resource shortages.

Portfolio budgets must include all concurrent and sequential attempts. Eight solvers each using eight threads is not a fair comparison with one eight-thread baseline. Reserve resources for the likely winner and evaluate delayed challengers rather than automatically dividing capacity equally.

### 5.4 Result verification and large results

The result recording path stores solver status and computes constraint reporting. Establish a documented, independent acceptance boundary covering every execution path before a result is presented as usable:

- Check finite numeric values, variable bounds, integrality, hard-rule residuals, and objective reconstruction with declared tolerances.
- Verify the original model after transformations and map failures to original rule labels.
- Preserve “unknown,” “no feasible result yet,” “infeasible,” and “unbounded” as different outcomes. Infeasibility requires evidence, not merely a timeout.
- Report proof scope, objective, best bound and gap consistently. A proof applies to the encoded model and tolerances, not necessarily the real-world process.
- Make verification failures visible and retain diagnostics without presenting the candidate as an accepted plan.

The current non-binary amount cap is a specific scale concern: above 200,000 non-zero cells, the service can omit stored amounts and mark truncation. Replace that path with local chunked artifacts, checksums, pagination, and streaming exports when the scale track begins. Re-optimization must reject unavailable base values, not assume omitted quantities are zero.

### 5.5 An offline benchmark program

Maintain three locally available suites:

1. **Correctness:** hand-solvable examples, known edge cases, unsupported combinations, invalid inputs, and cross-backend agreement checks.
2. **Performance:** representative small, medium and large instances across supported families, including difficult and timed-out cases.
3. **Customer acceptance:** frozen operational inputs with agreed feasibility, quality, stability, and runtime requirements.

Import benchmark data through approved bundles with provenance and checksums. Do not make a benchmark downloader part of normal isolated operation.

Compare the current release, the candidate release, and the relevant native solver baseline. Add competing platforms only where a runnable offline evaluation and authorized licenses are available. Record precisely which versions and configurations were evaluated.

Report:

- Time to first feasible solution and time to target gap.
- Final quality, best bound, and unresolved cases at a fixed deadline.
- End-to-end latency, queue latency, peak memory, and total CPU consumption.
- Primal integral or another stated quality-over-time measure.
- Per-family results, repeated seeds where applicable, hardware details, cache conditions, failures, and regressions.
- Separate model preparation time from solver execution time.

Use held-out families and time-separated customer cases for selector evaluation. Do not select a policy and report its performance on the same small set used to tune it.

Suggested promotion gate: zero correctness regressions; at least a 15% improvement in the agreed primary metric on target families; no unexplained greater-than-10% regression in critical supported workloads. Treat these as initial product targets to calibrate against benchmark variability, not as achieved performance.

## 6. Fully isolated operation as a core product feature

### 6.1 Define the isolation boundary

All required services must operate inside the approved boundary: authentication, database, solver binaries and licenses, maps, documentation, metrics, backups, package sources if rebuilding, and update verification.

Distinguish three states in the UI:

| State | Expected behavior |
|---|---|
| Public internet unavailable, platform reachable | Normal operation; no warning suggesting this is a fault |
| Browser cannot reach the local platform | Explain server/network reachability and provide retry/reconnect behavior |
| Platform reachable, optional internal dependency unavailable | Identify the affected feature; preserve other available workflows |

`main.tsx` does not override the query library's network policy, and `OfflineNotice.tsx` relies on paused/offline behavior. Validate this in the target network: browser connectivity hints must not suppress requests to an otherwise reachable local API. Do not assume this source observation proves an actual deployment outage.

### 6.2 Offline installation and updates

Deliver one release manifest plus approved local artifacts:

- Container images pinned by digest for frontend, API/worker, databases, and any required local services.
- A compose/deployment definition that loads those images without reaching a public registry.
- Database migrations, preflight validation, upgrade instructions, and compatibility constraints.
- Local help, API documentation assets, fonts, icons, map resources, and template/sample packs.
- Solver binaries and conformance reports; customer-provided licensed components remain separately controlled.
- Software inventory, artifact checksums, and signed release metadata verified against an offline trust root.
- Backup, restore, rollback, and installation acceptance procedures.

If source rebuilding is required inside the environment, supply a compatible wheelhouse, locked npm dependencies and package cache or local registry, base images, and necessary native build tools. Prefer deterministic locked installs; the current frontend Dockerfile's `npm install` should become an explicitly reproducible build path.

Updates follow: verify bundle → check disk space and compatibility → back up → rehearse migrations on a copy → deploy coordinated API/worker/frontend versions → run smoke and acceptance cases → record the installed manifest. Rollback must account for schema compatibility; it is not simply loading an older container image.

### 6.3 Runtime dependencies to audit

- Block public egress during acceptance testing and observe attempted requests from browsers and services.
- Check FastAPI interactive documentation assets as well as the main frontend; default documentation rendering may need locally hosted assets.
- Verify all basemap, terrain, vector, style, sprite and font resources resolve internally. Record geographic coverage and package version.
- Keep telemetry and tracing exporters on approved internal endpoints or explicitly disabled.
- Use local authentication first. If SSO becomes necessary, integrate an identity provider reachable within the isolated network; cloud-only identity is not a suitable default.
- Verify commercial license activation and renewal work under the actual isolation policy. Adapter support alone does not establish license availability.
- Package a local time synchronization and certificate-expiry operating procedure where the installation requires it.

### 6.4 Recovery and service operations

Build on the existing backup scripts, WAL configuration, queue metrics, audit writers, and worker runbook.

- Store at least one approved recovery copy outside the primary host's failure domain, using an internal server or controlled removable media as appropriate.
- Back up encryption keys separately and test recovery of encrypted solver licenses. The handover warns that changing `JWT_SECRET` without an independent solver secrets key can make licenses unreadable.
- Make installed versions, disk pressure, queue age, worker availability, license state, last backup, and last successful restore rehearsal visible to operators.
- Set recovery point and recovery time objectives per installation. Existing handover figures are reported baselines, not automatic guarantees for larger deployments.
- Test with public networking blocked: installation, login, template creation, import, solve, map viewing, result export, worker restart, backup, and restore.

## 7. Architecture and enterprise maturity

### Keep the existing architecture until evidence requires change

Continue with React, FastAPI, PostgreSQL as the system of record and work queue, isolated solve subprocesses, and the existing analytics path. Do not introduce Redis, Kubernetes, GPUs, or an LLM merely to make the platform appear modern.

Split the growing solve orchestration into explicit stages while retaining the existing contract:

```text
Validate request and scope
→ Freeze inputs and resolve scenario
→ Classify and compile
→ Plan execution and reserve resources
→ Solve
→ Verify and explain
→ Persist results and lineage
→ Publish events and analytics
```

Persist the resolved execution policy, solver/build versions, seed, tolerances, transforms, input hashes, and environment manifest. Explain that rerunning a multithreaded solver may produce a different equally valid result; reproducible inputs and attributable execution do not imply bitwise-identical output.

### Reliability improvements to verify before scaling

- Add or confirm submission idempotency for client retries, scoped by organization and request content.
- Validate stale-worker recovery under network delays. Use execution-attempt IDs and fencing so an old attempt cannot overwrite a reclaimed run's result.
- Reserve CPU, memory, and license seats before starting portfolios or retries. Account for shadow and quality-check workloads separately from planner work.
- Bound retries for repeatable failures and expose the reason instead of repeatedly consuming quota.
- Make event reconnect/resume and final-state retrieval reliable even when progress messages expire.
- Check whether analytics startup dependencies are intentionally mandatory: Compose currently makes backend startup depend on ClickHouse health, while workers depend on PostgreSQL. Decide which analytics failures should degrade reporting rather than prevent planning.
- Preserve database-enforced organization boundaries and test export, comparison, search, cached results, and object navigation across organizations.

### Business governance

After the core workflow is coherent, add a separate approval lifecycle:

```text
Candidate result → Submitted for review → Approved plan → Superseded / Archived
```

Record the approver, reason, business effective dates, and exact immutable result reference. A new solve never silently replaces an approved plan. A gate exception, if supported, must be a narrowly authorized, audited action against a specific version; a broad setting that disables all checks is not an equivalent workflow.

Expose users and roles as understandable forms. API access should offer scoped credentials, expiry, rotation and usage visibility as requirements to confirm or extend against existing support. Keep local API documentation and sample integrations available without internet access.

Retain the current decision to defer SSO/provisioning, cluster deployment, tiered pricing, and more advanced retention workflows until a concrete installation needs them. Update those plans for internal identity and offline administration rather than carrying over cloud assumptions.

## 8. Implementation roadmap

The estimates below are indicative engineering weeks for a small team with frontend, backend/optimization, and QA/operations coverage. They are not a delivery commitment. Re-estimate after the first milestone; prioritize exit criteria over dates.

| Phase | Priority / estimate | Deliverables | Exit criteria |
|---|---|---|---|
| 0. Establish the baseline | P0 / 1 week | Reconciled capability inventory, route inventory, representative user tasks, offline dependency inventory, baseline timings | Every item marked implemented, partial, proposed, or unverified; representative workflows agreed |
| 1. Navigation foundation | P0 / 2–3 weeks | Shared route registry, context header, scoped URLs, new sidebars, clearer labels, old-link resolver | Navigation criteria pass; no scope confusion or draft loss; existing capabilities remain reachable |
| 2. Coherent planning workflow | P1 / 3–4 weeks | Problem overview and readiness, Inputs view, consolidated run detail, what-if form, cell locks, readable comparison and checks | A planner completes import → scenario → solve → explanation → re-plan using bundled examples |
| 3. Offline product release | P1 / 2–3 weeks | Verified image bundle, local assets/docs/maps, reachability states, operations pages, installation and recovery procedures | A clean isolated host installs and completes acceptance cases with public egress blocked |
| 4. Verified performance | P1 / 3–5 weeks | Coverage catalog, representative offline suites, phase timing, verification boundary, family-specific policies | Target-family gains demonstrated under equal budgets with no correctness regressions |
| 5. Scale and governance | P2 / 3–5 weeks | Chunked results, execution-attempt hardening, resource reservations, approval lifecycle, measured capacity limits | Representative large runs remain inspectable/replayable; failover and approval cases pass |
| 6. Demand-led extensions | P3 / separately scoped | Internal SSO, provisioning, cluster deployment, additional certified solver integrations | A named use case, operating owner, and benchmark/acceptance case justify each addition |

Offline dependency discovery begins in Phase 0. Correctness or security defects found during any phase are fixed before shipping affected features; the schedule is not a reason to defer them to a later track.

### First implementation backlog

| ID | Task | Main code areas | Dependency |
|---|---|---|---|
| N01 | Define destination ownership, user terminology, and route metadata | `frontend/src/App.tsx`, `components/AppShell.tsx` | Baseline |
| N02 | Establish URL-driven domain/problem context and ownership validation | `hooks/useDomain.ts`, `useModelTarget.ts`, API lookup paths | N01 |
| N03 | Build global, domain, and problem shells with context breadcrumbs | App shell, domain selector, route components | N01–N02 |
| N04 | Add compatibility routing and preserve relevant old query state | App routes, `lib/routeId.ts`, deep-link tests | N02 |
| N05 | Unify navigation/search metadata and draft-exit handling | `CommandPalette.tsx`, unsaved-change guard | N03 |
| N06 | Consolidate Runs and Workspace around one run detail | `pages/Runs.tsx`, `Workspace.tsx`, `RunViews.tsx`, GenUI | N03–N04 |
| N07 | Build purpose-specific domain/problem overview screens | Generic list/detail pages, Dashboard, existing problem APIs | N03 |
| W01 | Complete what-if and interactive locking | `PlannerPanel.tsx`, scenarios, why-not/locks APIs | N06; override schema decision |
| W02 | Expose suite and shadow comparisons without technical list noise | Versions, checks components, suites API | N06 |
| O01 | Produce an offline installation contract and dependency manifest | Dockerfiles, Compose, local docs/maps, release process | Baseline |
| O02 | Validate local reachability behavior and recovery states | `main.tsx`, API client, `OfflineNotice.tsx` | O01 |
| Q01 | Publish coverage and benchmark acceptance matrix | Solver registry, conformance, benchmark suites | Baseline |
| Q02 | Document and enforce independent result verification | `app/solve/verify.py`, run persist path | Q01 |
| Q03 | Record per-phase timings on runs | `params.phases` in `service._execute` | Q02 |
| Q04 | Family policies + equal-budget comparison gate | `docs/contracts/family-policies.md`, `bench/equal_budget.py` | Q01 |
| Q05 | Offline representative suite path (no MIPLIB required) | `bench.suites`, family generators | O01, Q01 |
| S01 | ClickHouse optional for API startup (analytics degrade) | `docker-compose.yml`, health | Phase 5 |
| S02 | Idempotency-Key on run submit | `runs.py`, migration 0083 | Phase 5 |
| S03 | Execution-attempt fencing for stale workers | `claim_next` / `_record`, migration 0084 | S02 |
| S04 | Reserve CPU/memory/licence seats; check pool for shadow/suite | `app/solve/reserve.py`, `claim_next`, portfolio path | S03 |
| S05 | Document and enforce measured host capacity limits | `docs/contracts/scale-reliability.md`, reserve defaults | S04 |

Do not renumber or overwrite the existing R-series execution history. Link completed work from the new backlog and track new work with distinct identifiers.

## 9. Success measures and release gates

| Dimension | Proposed measure |
|---|---|
| Discoverability | At least 90% success on core navigation tasks in a representative user pilot |
| Onboarding | At least 8/10 first-time pilot users obtain and understand a bundled sample result within ten minutes |
| Context safety | No silent substitution of an explicitly requested domain/problem/version/scenario/run in migration and integration tests |
| Performance | Demonstrated family-specific gain against a pinned baseline under equal budgets; publish regressions as well as wins |
| Correctness | Every supported execution path has acceptance verification; zero known correctness regressions in release suites |
| Offline readiness | Clean installation and core acceptance workflow pass with all public egress blocked |
| Scale | Document maximum tested model/data/result sizes, concurrent load, memory envelope, and p95 latency for the reference hardware |
| Reproducibility | Exported evidence links model, scenario, inputs, execution policy, solver version, and result artifacts |
| Recovery | Restore rehearsals meet the installation's agreed objectives and recover encrypted assets |

A release claim should be specific: “On the agreed workforce suite, this release reaches the target quality faster at the same CPU and memory budget.” Avoid “solves all problems” and “fastest platform” without a defined scope and reproducible evidence.

## 10. Decisions and trade-offs

### Recommended decisions now

1. Adopt the organization → domain → problem hierarchy and the proposed contextual navigation.
2. Keep existing domain objects and backend routes initially; migrate the user-facing route structure incrementally.
3. Prioritize navigation, result clarity, and the missing planner interactions over new solver families.
4. Treat offline installation and lifecycle operations as release requirements.
5. Keep learned selection and broad solver portfolios conservative until the local evidence supports promotion.
6. Maintain the no-cloud-dependency and no-LLM direction for this roadmap.

### Decisions to resolve at the relevant milestone

| Decision | Recommended starting point | Why it matters |
|---|---|---|
| First target users | Planners, modelers/data stewards, operators/administrators | Validate navigation with each; capability roles remain configurable. |
| First flagship workloads | Workforce planning and facility/distribution planning | Existing templates and spatial features provide useful starting coverage; confirm with actual users. |
| Scenario data semantics | Typed overrides over a named frozen base | Prevent shared-data changes from silently altering what-if experiments. |
| Large result artifacts | Chunked local storage with hashes and authorization through the API | Preserve quantities and avoid enormous JSON responses. |
| Approval scope | Approve a specific result and effective period | Distinguish business acceptance from solver proof and model publication. |
| Installation scale | Publish a single-host reference first | Establish measurable limits before committing to a cluster architecture. |

### Main delivery risks

- **Navigation scope grows into a backend rewrite.** Keep the hierarchy and existing objects; move pages incrementally behind compatibility routes.
- **Renaming obscures expert terminology.** Add glossary mappings and retain technical identifiers in advanced views.
- **A new editor view changes model meaning.** Require IR equivalence/round-trip checks and explicit refusal of unsupported edits.
- **Offline packaging misses secondary assets.** Test on a clean host and inspect blocked outbound attempts, including help and maps.
- **Automatic solver tuning overfits examples.** Hold out families and customer periods; retain rollbackable policies.
- **Large results undermine re-planning.** Make result completeness explicit until chunked storage is delivered.
- **Visual modernization hides important status.** Keep feasibility, proof scope, units, active context, and limitations visible in every relevant view.

## 11. Repository evidence index

Paths are relative to the repository root so this proposal remains portable with an offline copy.

| Evidence | Paths |
|---|---|
| Current delivery status and acknowledged gaps | `handover.md`; `docs/plans/2026-09-26-planner-ops-scale-plan.md` |
| Historical roadmap and execution history | `docs/plans/2026-09-22-execution-queue.md`; `docs/plans/2026-09-22-optimization-target-roadmap.md` |
| Routes, navigation, breadcrumbs and palette | `frontend/src/App.tsx`; `frontend/src/components/AppShell.tsx`; `frontend/src/components/CommandPalette.tsx` |
| Context selection | `frontend/src/hooks/useDomain.ts`; `frontend/src/hooks/useModelTarget.ts`; `frontend/src/pages/Workspace.tsx` |
| Home and planning UI | `frontend/src/pages/Dashboard.tsx`; `frontend/src/components/PlannerPanel.tsx`; `frontend/src/components/VersionChecks.tsx` |
| Connectivity and map configuration | `frontend/src/main.tsx`; `frontend/src/components/OfflineNotice.tsx`; `frontend/src/hooks/useBasemaps.ts`; `frontend/src/lib/tiles.ts` |
| IR and solver contracts | `docs/contracts/problem-ir.md`; `backend/app/solve/classify.py`; `backend/app/solve/backends.py`; `backend/app/solve/result.py` |
| Execution, storage, and recovery | `backend/app/solve/service.py`; `backend/app/worker.py`; `backend/app/solve/locks.py` |
| API capabilities | `backend/app/api/runs.py`; `backend/app/api/suites.py`; `backend/app/api/audit.py` |
| Selector and performance evidence | `backend/app/solve/selector.py`; `backend/bench/results/2026-09-25-selector.md`; `backend/bench/results/2026-09-24-portfolio.md`; `backend/bench/results/2026-09-23-miplib.md` |
| Adapter support and caveats | `docs/solver-adapters.md`; `backend/adapters/reference/` |
| Deployment and dependencies | `docker-compose.yml`; `backend/Dockerfile`; `frontend/Dockerfile`; `backend/requirements.txt`; `frontend/package.json` |
| Existing operational procedures | `docs/runbooks/workers.md`; `docs/runbooks/backups.md`; `scripts/check.sh`; `scripts/backup.sh` |
| Visual foundation | `MCAIT Design System/` |

**First deliverable to implement:** a tested navigation and context layer that makes the existing platform understandable. That creates the foundation for a coherent planner workflow, a dependable offline release, and performance improvements that can be demonstrated rather than merely claimed.
