# UI/UX Fixes — Design

**Date:** 2026-09-17
**Scope:** the 54 findings from the UI/UX audit of 2026-09-17 (real-browser pass over the admin UI and graph editor at commit `25929e0`, with an axe-core scan and a keyboard-only pass). Findings are identified `A-1 … H-12` in that report; every one is addressed here or listed as out of scope at the end.

**Principle guiding every decision below:** the platform already does what it promises. What it lacks is the behaviour of a product — it shows the user its database, never confirms success, and looks broken when it is merely slow. Fixes favour one shared mechanism over per-page patches, because the UI is metadata-driven: a change in the meta layer or in `EntityForm`/`DataTable` reaches all 31 tables at once.

## 1. Foundations (A-3, D-2, D-3, G-1, H-4, H-6, H-10, H-11)

- `AppShell`'s `<main>` gains `min-w-0`. A flex child defaults to `min-width:auto`, which is why the table's `overflow-x-auto` never engaged and the document scrolled sideways, dragging the sidebar off-screen.
- `QueryClient` gets an explicit retry policy: no retry for 4xx (a 404 is not transient), one retry for 5xx and network failures. This removes the 7.1s "Loading…" before any error surfaces.
- A catch-all `<Route path="*">` inside the shell renders a not-found page with a link home. Today an unmatched path renders an empty document.
- A visually-hidden "Skip to content" link is the first focusable element; `<main id="main" tabIndex={-1}>` is its target. Measured cost today: 34 tab presses to reach content.
- Sidebar links become `NavLink` with an active style and `aria-current="page"`.
- Per-route `document.title` (see §2 for the label source), set in one `useDocumentTitle` hook; focus moves to the page `<h1>` on route change.
- Muted text token moves from `text-slate-400` (#94a3b8, 2.45–2.56:1) to `text-slate-500` (#64748b, 4.76:1 on white); the health green from `#059669` to `#047857`.

## 2. Vocabulary (B-1, B-2, B-3)

The backend already owns the schema, so labels come from `/api/meta/schema` rather than a hand-kept frontend map:

- Each table gains `label` (`"Relationship"`) and `label_plural` (`"Relationships"`); each field gains `label` (`"From"` for `source_entity_id`).
- Derivation: an explicit override table in `backend/app/api/meta.py` for the terms that matter (`source_entity_id → From`, `target_entity_id → To`, `entity_type_id → Type`, `organization_id → Organization`, `is_abstract → Abstract type`, `parent_type_id → Parent type`, `valid_from/valid_to → Valid from/Valid to`, `code → Code`, `hierarchy_node → Placement`, …), falling back to a humanise function: strip a trailing `_id`, replace underscores, sentence-case.
- The frontend uses `label` everywhere it currently prints a raw name: page titles ("New relationship"), form labels, table headers, sidebar items, the not-found message, and `document.title`.
- Raw names stay available (`name`), and the edit page shows `schema.table` as a small subtitle so the mapping to the database is never lost.

## 3. Feedback (D-1, D-4, D-5, C-4, D-6)

- A `ToastProvider` at the app root renders a polite live region (`role="status"`, `aria-live="polite"`) and an assertive one for errors. `useToast()` exposes `success(message)` / `error(message)`.
- Every mutation reports: "Nurse saved", "Relationship deleted", "Problem created". Delete toasts name the record.
- Error states gain a **Retry** button that refetches; the list, the detail page and the graph all use it.
- Loading: a `Skeleton` row component for tables and a spinner inside pending buttons. Submit buttons are disabled while their mutation is pending and read "Saving…".
- The delete confirmation names the record ("Delete Alice Nguyen? This cannot be undone.") and stays a native `confirm` for now — replacing it with a modal is out of scope, but naming the row is not.

## 4. Forms (C-1 … C-10, H-3, H-5)

- `EntityForm` generates an `id` per field and each `<label htmlFor>` points at it. The two bare `<select>`s (`is_abstract`, `is_runtime`) and the login inputs get the same treatment; login fields also get `name` and `autocomplete`.
- The form sets `noValidate` and runs one validation pass of its own, so native bubbles never pre-empt the app's messages (today an empty required FK blocks submit with a browser bubble and the app's "invalid JSON" never renders). Failures render an error summary at the top, set `aria-invalid` and `aria-describedby` on each offending field, and move focus to the summary.
- JSON fields validate on blur as well as submit, and render monospace.
- FK picker: a placeholder ("Search types…"), a chevron, and a selected value shown as a token with the existing clear button. On blur with text typed and nothing chosen, the text is kept and the field shows "No match — choose from the list" rather than silently emptying. `aria-activedescendant` tracks the highlighted option; `aria-controls` is only set while the listbox exists.
- Unsaved-changes guard: dirty forms block in-app navigation (React Router `useBlocker`) and set `beforeunload`.
- The edit page is titled with the record's own label, carries a breadcrumb back to the list, and offers Cancel beside Save.
- Conflict errors map the constraint to its fields where possible and are worded for a person: "This code is already used in this organization."

## 5. Lists (E-1 … E-6, G-3, H-2, H-9, H-12)

- The first cell of each row becomes a link to the record — this is the fix for both discoverability and keyboard access; the whole-row click stays as a convenience.
- Delete moves out of the row into a small actions menu, with a ≥32px target; sort buttons reach ≥24px.
- Sort affordance: a caret on hover, the active direction shown, `aria-sort` on the active column.
- Rendering by type: dates and datetimes through `Intl.DateTimeFormat` in local time (full value in `title`), booleans as ✓/— with an accessible name, `id`/UUID columns hidden behind a "Show identifiers" toggle.
- Table semantics: `<caption class="sr-only">`, `scope="col"` on every header, a label for the actions column, and the "1-20 of N" count in a live region.
- Empty state per table: "No entity types yet" plus the New action.
- Related records sorts non-empty first and collapses empty children behind "Show N empty".

## 6. Graph (F-1 … F-6, H-1, H-7)

- Below 1024px the property panel stacks under the canvas instead of squeezing it to 167px; the canvas fills the available height rather than a fixed 600px.
- Every toolbar control gets a `title` and an accessible name, and a single help line under the toolbar explains the current mode — it changes when Connect is on ("Drag from one node to another to connect them").
- Node labels get their own colour plus a text outline so they stay legible over neighbours.
- Keyboard access: the canvas is focusable, arrow keys move a roving selection between nodes, Enter opens the property panel for the focused node, and Escape returns focus to the toolbar. Pressing Enter in the search box selects the first matching node. This does not attempt full edge-drawing by keyboard; creating an edge remains a pointer gesture, and that limitation is documented.
- The "Types:" panel gets `aria-expanded`/`aria-controls`, closes on Escape, returns focus to its toggle, and lists types alphabetically.
- Empty canvas shows an empty state with a "Create the first node" action.

## 7. Dashboard & navigation (A-1, A-2, A-4, A-5, A-6, G-2, G-5, G-6)

- The dashboard leads with three entry points (Domain model, Problems, Graph), then recent problems and recently updated entities, then row counts as a secondary panel where each row links to its list. Service health becomes a single status line.
- Row counts come from one new `GET /api/meta/counts` instead of 31 parallel list requests.
- The sidebar scrolls independently, groups are collapsible, and a filter box narrows the 31 tables. Below 900px it becomes a drawer behind a menu button, which is what makes phone widths usable at all.
- Tables reflow to a stacked card layout below ~700px so the list is usable rather than merely scrollable sideways.

## Out of scope (disclosed, not fixed)

- Full keyboard edge-creation on the canvas (selection and editing are covered; drawing an edge stays a pointer gesture).
- Replacing native `confirm()` with an in-app modal, and undo for deletes — both need a design decision beyond this pass.
- Optimistic locking for concurrent edits (already a known limitation).
- A real screen-reader QA session; this pass fixes what static inspection and axe can verify.
