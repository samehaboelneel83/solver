# Problem Solver: UX & Navigation Audit

**Date:** 30 Sep 2026 · **Build:** http://localhost:3010 · **Tested by:** Claude (in Chrome)

**Scope:** end-to-end walkthrough as three personas:

1. **Domain administrator:** users, roles, settings, domains, data, audit, solvers
2. **Problem encoder:** created `ux_audit_timetable` from the *Lecture timetable* example, added a rule, and published v2
3. **Problem solver:** solve, read the result, *Why not?*, scenarios, versions, runs, Simple mode

> **How it was tested:** every persona used the `admin` account. The other accounts (`planner-*`, `modeller-check`) need passwords I don't have, and they also have **0 role assignments** (see A-1), so a real role-restricted view could not be seen. Mobile width was not tested because the browser window would not resize.

**Test data created:** problem `ux_audit_timetable` (id 193) with model version 2, runs 690–691. You can delete it afterwards.

---

## Summary

The platform is powerful and the writing is unusually clear. The best parts are the plain-English result summaries, the equation error hints, *Why not?*, and the 5-step problem checklist. The main problems are **navigation depth and consistency**. There are too many "hub" pages that only hold 2–4 cards. The sidebar changes shape from page to page. Simple and Expert modes leak into each other. The same concept has several names (Domain/Workspace, Objective/Goal/Morning, Record/Entity/Kind of record). Admin screens expose internal fields and raw configuration keys.

| Area | Score (1–5) | One-line verdict |
|---|---|---|
| Domain administrator | 2.5 | Works, but it feels like a database console. Role assignment is buried. |
| Problem encoder | 3.5 | Very capable editor with great error feedback, but one very long page, tiny diagrams and a hidden draft risk. |
| Problem solver | 4 | Excellent result explanation. A few truncation, sorting and defaulting bugs. |
| Navigation overall | 2.5 | Command palette is great. The sidebar is inconsistent and there are too many intermediate pages. |

---

## Top 10 fixes (priority order)

| # | Severity | Issue | Where |
|---|---|---|---|
| 1 | 🔴 High | Users named "Planner" / "Modeller" have **no roles**. Role assignment is a small link at the bottom of the user form. | A-1 |
| 2 | 🔴 High | Model drafts are **saved in this browser only** ("drafts are not yet saved on the server"). Switching the *Problem* dropdown or closing the tab can lose work. | B-6 |
| 3 | 🔴 High | Review tab says *"The data it reads: late"*, but the model also reads `enrollment` and `capacity`. The review summary is incomplete. | B-7 |
| 4 | 🟠 Med | The sidebar sections change on every page (Navigate / Recent problem / This domain / Data / Recent domain…). Simple mode shows the full Expert menu on `/runs`. | N-1, N-3 |
| 5 | 🟠 Med | Hub pages (Records & relationships, Data structure, Inputs, Quality checks, Access & policies) add an extra click and repeat sidebar links. | N-2 |
| 6 | 🟠 Med | Terminology drift: Domain↔Workspace, Objective↔Goal, Entity↔Record↔Kind of record, "Runs & queues" vs "Run queue". | N-4 |
| 7 | 🟠 Med | Two different Problem Overview designs (asd1 has cards; new problems have a checklist). | N-5 |
| 8 | 🟠 Med | *Add a rule* appends the rule off-screen without scrolling or focusing it. Its placeholder `0 <= 0` is a valid rule that could be published by accident. | B-4 |
| 9 | 🟡 Low | Result grid columns sort as text (Customer 1, 10, 11 … 2) instead of by number. | C-4 |
| 10 | 🟡 Low | The *Why isn't … on?* button text overflows before the answer appears. The global `/runs` page opens on the first problem alphabetically, not the current one. | C-2, C-5 |

---

## 1. Domain administrator

### A-1 Users & roles 🔴
![Users](screenshots/a03-users.jpg)
![User edit](screenshots/a06-user-edit-no-roles.jpg)

- The users table has **no Roles column**, but it shows internal fields (`External sub`, `Token version`).
- `planner-muboc1ol` and `planner-mubobprg` both have the display name "Planner", so they can't be told apart. Both have **Role assignments (0)**. The Home page reports only 2 role assignments across 4 users.
- The row menu only has **Delete**. There is no Edit, Assign role or Deactivate. ![Row menu](screenshots/a05-user-row-menu.jpg)
- The *Active* dropdown offers "(use default)", which makes no sense for an on/off state.
- **Fix:** add a Roles column and a role multi-select at the top of the user form. Add "Assign role" and "Deactivate" to the row menu. Warn when a user has no role.

### A-2 Roles 🟠
![Roles](screenshots/a04-roles.jpg)
- The list shows only code, name and date. Add a description, a user count and a capability count so an admin can tell *planner* from *modeller* without opening each one.

### A-3 Platform settings 🟠
![Settings](screenshots/a01-platform-settings.jpg)
- 36 raw keys (`solve.cpsat_scaling`, `shadow.rate`…) sit in one flat list, each with its own **Save** button. There is no grouping, search or "changed only" filter.
- Yes/no settings are free text boxes, not toggles.
- "Your account" (including a password field) sits at the top of *platform* settings. It belongs under the avatar menu.
- **Fix:** group the settings (Retention · Solver choice · Solver techniques · Spatial · Governance), use proper controls, add one sticky Save, and show the inherited value next to each setting.

### A-4 Domains & data 🟠
![Domains](screenshots/a07-domains-list.jpg) ![Domain overview](screenshots/a08-domain-overview.jpg)
- The Domains list has no description or problem count, and its breadcrumb reads just **"Page"**. Its URL is `/public/domain`.
- The Records table shows **raw GeoJSON** in a cell, and the map preview has a blank background. ![Records](screenshots/a13-records-table.jpg)
- "New entity" sits next to "+ New kind of record", and "+ Add a field to area": three words for related ideas.
- The ERD graph is unreadable at its default zoom and the top row is clipped. ![ERD](screenshots/a14-domain-graph-erd.jpg)
- Sources & imports is empty and its only help is "Local API reference". ![Sources](screenshots/a11-sources-imports.jpg)
- Quality checks admits *"A consolidated domain quality report is not available yet"*. The page is only three links. ![Quality](screenshots/a12-quality-checks.jpg)

### A-5 Operations & audit 🟡
![Audit](screenshots/a15-audit.jpg)
- The date format (`9/30/2026, 7:22 PM`) differs from the rest of the app (`Sep 30, 2026`).
- Objects such as `scenario 271` are not links. The only filter is a free-text action box. Add actor, object and date filters.
- The Solvers table loads as a skeleton. When loaded it is good, but it mixes dev notes (`docs/solver-adapters.md`) into the UI. ![Solvers](screenshots/a16-solvers-loading.jpg)
- The Run queue empty state tells users to run `docker compose up --scale worker=N`. That is an operator instruction, not a user one. ![Queue](screenshots/a17-run-queue.jpg)

---

## 2. Problem encoder (complex model: lecture timetable, 5 sets, 4-index decision, 5 rules)

### B-1 Starting a problem ✅ / 🟡
![Start](screenshots/b01-start-a-problem.jpg) ![Checklist](screenshots/b02-problem-checklist.jpg)
- ✅ The three start paths (example, spreadsheet, scratch) are clear, and the resulting **5-step checklist** (Data → Model → Check → Solve → Results) is the best navigation aid in the app.
- 🟡 The breadcrumb on *Start a problem* reads "Domains > **All domains**", which is wrong.

### B-2 Model editor layout 🟠
![Editor top](screenshots/b03-model-editor-top.jpg)
- There are five editor tabs (Guided Form, Visual Graph, Blocks, Exact IR, Review) plus "Advanced views". Every item then has its own four sub-views (Sentence/Boxes/Diagram/Equation). That is a lot of choice.
- A **Problem** dropdown inside a problem's own page lets you switch problems while holding an unsaved draft.
- "2 of 3 steps done" here does not match the 5-step checklist on the overview.
- The whole model is one very long scroll with no outline. **Fix:** add a sticky left outline (Sets · Decisions · Data · Rules · Goal) with counts and jump links.

### B-3 Record types list 🟡
![Record types](screenshots/b04-record-types-checklist.jpg)
- Every record type in the domain appears (feed, customer, cell…), even ones unrelated to timetabling. Show the used ones first and collapse the rest.

### B-4 Adding a rule 🟠
![New rule](screenshots/b07-new-rule-placeholder.jpg)
- *Add a rule* adds `c_1` below the fold with no scroll or focus. It defaults to `for each s in section: 0 <= 0`, which is valid and publishable. Default to an empty equation that must be filled in.
- ✅ **Error feedback is excellent:** *"assgn" is not a variable… did you mean "assign"?* with the problem highlighted and helper chips. ![Error](screenshots/b08-equation-error-hint.jpg)
- 🟡 The Sentence view is powerful but dense. It packs 15+ inline controls into one paragraph, and the fonts are small. ![Sentence](screenshots/b09-sentence-view-zoom.png)

### B-5 Visual Graph & Blocks 🟡
![Graph](screenshots/b10-visual-graph.jpg) ![Blocks](screenshots/b11-blocks.jpg)
- Node text in the graph is too small to read without zooming.
- In Blocks, the `decide assign…` block runs past the canvas edge.

### B-6 Draft safety 🔴
- The footer says: *"Download a backup before closing the browser; drafts are not yet saved on the server… Saved on this device only."* On a complex model this is a data-loss trap. **Fix:** autosave drafts to the server, and warn with `beforeunload` or on problem switch.

### B-7 Review & publish 🔴 / ✅
![Review](screenshots/b12-review.jpg) ![Published](screenshots/b13-after-publish.jpg)
- ✅ The plain-language review is excellent.
- 🔴 **"The data it reads: late"** leaves out `enrollment[s]` and `capacity[r]`, which the rules use.
- 🟡 The "What this model is" block appears twice.
- 🟡 After publishing, the page jumps to the top and resets to the Guided Form tab. The only feedback is a small toast. Link to the new version and offer "Solve v2 now".

---

## 3. Problem solver

### C-1 Solve & result ✅
![Result](screenshots/c01-run-result.jpg)
- One click leads to a proven optimum, explained in plain words ("The best plan possible was found… Every required rule holds"), with a day grid and plan approval. This is very good.
- 🟡 "**Morning** came to 0": the goal is labelled with the objective's internal name. Use the meaning text or "Late-slot penalty". The button "Solve **Base**" is also unclear; "Solve (Base scenario)" reads better.
- 🟡 In the rules panel, "no room left" and "room 10" are hard to follow. Say "tight (at its limit)" or "10 spare".

### C-2 Plan again / Why not? / What-if ✅ / 🟡
![Why not](screenshots/c02-plan-again-why-not.jpg) ![Answer](screenshots/c03-why-not-answer.jpg)
- ✅ *Why not?* returns a clear answer ("Possible, at no extra cost — the closest plan moves 4 cells").
- 🟡 The button label is truncated before it is clicked (the "?" is cut off).
- 🟡 What-if needs a parameter name and a comma-separated index typed as free text. Offer dropdowns like the ones *Why not?* uses.
- 🟡 Asking *Why not?* seems to create a run (run 691), which then becomes "the latest result" on the overview. Label these as "question runs" or keep them out of the main history.

### C-3 Inputs, Scenarios, Versions 🟡
![Inputs](screenshots/c04-inputs-hub.jpg) ![Scenarios](screenshots/c05-scenarios.jpg) ![Versions](screenshots/c06-versions.jpg)
- Inputs is another card hub that points back to domain-level pages.
- Scenarios is clean. It could show the latest result per scenario.
- Versions puts a 64-character **IR hash** up front but has no **diff between versions**, which is the thing an encoder needs. The "Candidate comparison" help links to the page you are already on.

### C-4 Result grids 🟡
- Columns and rows sort as text: `Customer 1, 10, 11 … 19, 2, 20`. Use natural sort.

### C-5 Global runs page 🟡
![Runs](screenshots/c08-simple-mode-runs-full-nav.jpg)
- `/runs` opens on **facility_coverage**, the first problem alphabetically, instead of the problem you were working on.
- Many identical runs are listed ("Answered by run 674…"). Collapse cached re-runs.
- The column is called **Goal** here and **Objective** on Home.

---

## 4. Navigation & consistency (all personas)

### N-1 Sidebar changes on every page 🟠
Compare the admin pages (NAVIGATE / RECENT PROBLEM / OPERATIONS / ADMINISTRATION), the domain pages (THIS DOMAIN / DATA) and the audit page (RECENT DOMAIN / HELP). Items move, so muscle memory never forms. **Fix:** use a fixed top-level order (Home · Domain · Problem · Operations · Admin · Help). Collapse sections that don't apply instead of removing them.

### N-2 Too many hub pages 🟠
![Records hub](screenshots/a09-records-hub.jpg) ![Structure hub](screenshots/a10-data-structure-hub.jpg) ![Access hub](screenshots/a02-access-policies.jpg)
Records & relationships, Data structure, Inputs, Quality checks and Access & policies are each 2–6 cards that repeat sidebar links. Link the sidebar straight to the real pages, or make each hub a useful dashboard with counts, warnings and recent changes.

### N-3 Simple vs Expert mode 🟠
![Simple](screenshots/c07-simple-mode-overview.jpg)
- ✅ The Simple sidebar on a problem is excellent: *Overview & solve · Data · Model · Results*.
- 🔴 On `/runs` the full Expert sidebar comes back while the toggle still says Simple.
- Simple renames **Domain → Workspace**, but pages still say "All problems in this **domain**". Pick one term.

### N-4 Terminology glossary needed 🟠
| Concept | Names seen |
|---|---|
| Business area | Domain, Workspace |
| Thing being optimised | Objective, Goal, "What to make best", internal name ("Morning") |
| Data row | Record, Entity, Kind of record, Record type |
| Queue page | Runs & queues, Run queue |
| Latest answer | Runs & results, Results, Runs |

### N-5 Two problem-overview designs 🟠
![Old overview](screenshots/c10-asd1-overview-old-layout.jpg)
`/problems/192/overview` (asd1) shows Model/Scenarios/Runs cards, while `/problems/193` shows the checklist. Use the checklist everywhere.

### N-6 What works well ✅
- **Ctrl K command palette** finds any page fast. ![Palette](screenshots/c09-command-palette.jpg)
- The header breadcrumb chip "Domain: Workforce / Problem: …" always shows where you are.
- EN/RTL, light/dark, and notifications are all one click from the header.
- Help text is honest and specific throughout.

### N-7 Smaller polish items
- Collapse "Right to left" into the language menu instead of a permanent sidebar item.
- The sidebar scroll area clips the Administration section on 836 px-tall screens.
- URLs carry redundant parameters (`/problems/193?problem=193`).

---

## Suggested next steps
1. Fix the data-safety and correctness items (A-1, B-6, B-7).
2. Stabilise the sidebar and remove the hub pages (N-1, N-2, N-3).
3. Publish a glossary and rename to one term per concept (N-4).
4. Re-test with real **planner** and **modeller** accounts once they have roles, and test at phone width.
