# Blockly edit mode — design

**Date:** 2026-09-24 · **Status:** decisions and Section 1 approved in conversation; Sections 2–7 are
Claude's recommendations, taken on the user's instruction "go with your recommendations". For the
user's review before an implementation plan is written.

## 1. Goal and decisions

Let a planner **build and change the whole model by snapping blocks together**, as a visual
alternative to the Model editor's forms, with the result the same valid IR and published as a new
version exactly as the forms publish it.

| Question | Decision |
|---|---|
| What is editable | **Everything**: sets, decisions (domain, bounds, intervals), parameters (with uncertainty), rules (scope, relation, hard/soft, weight, `when`, scheduling rules, `connected` once it exists), the goal (sense, mode, terms). |
| Advanced constructs | **All editable in the first release**: conditional rules, piecewise curves, catalogue functions, intervals, `no_overlap`/`cumulative`, uncertainty, lexicographic goals. |
| Where | **Both**: an Edit toggle in the optimization view's Blockly style, and a Blocks tab beside the forms in the Model editor — over **one shared draft**. |
| Source of truth | **Approach A**: the draft IR is the only truth; blocks are a live view of it, rebuilt from the IR and written back to it on every change. Block positions are not saved (auto-laid out). |
| Rejected | Storing the Blockly workspace beside versions (B: two truths that drift); blocks as their own document converted only at publish (C: forms would not see block edits). |

## 2. One shared draft, and publishing (approved)

- `frontend/src/model/draftStore.ts`: at most one draft per problem — the **whole IR document** (every
  top-level key, including `relationships`, which today's form draft drops) and the version it was
  seeded from — read and written by the Model editor's forms, its Blocks tab, and the optimization
  view's Edit mode, each subscribing only to what it shows (`useSyncExternalStore`, as the GenUI store).
- Kept in the browser's local storage (per person, per browser, never on the server until published),
  so a draft survives changing page and reloading; every read and write wrapped in try/catch, and
  the pages work without storage.
- **Edit** (optimization view) or opening the Model editor seeds a draft from the version on screen,
  or resumes the existing one. A draft seeded from another version is never swapped silently: the page
  offers **Continue the draft** or **Start again from version N**.
- **Publish** (either place) validates, posts a new version (`createVersion`), clears the draft, and
  moves both views to the new version. **Discard** clears it after confirmation. Both pages show an
  "Unpublished changes · edited 14:02" badge.
- Validation on every change: `checkIrShape` at once, and the server's domain check (`POST
  /api/v1/versions/validate` if it exists, else the publish endpoint's dry run — see §6) debounced to
  500 ms. Publish is disabled while anything is refused, and says why.

## 3. The blocks and the toolbox

**One block per IR construct**, each editable through Blockly field types, never free text where a
choice exists:

| Construct | Block | Fields |
|---|---|---|
| model | `ir_model` (root, not deletable) | title (read-only), `sense`, `mode` dropdowns; statement inputs *declare*, *rules*, *goal* |
| set | `ir_set` | dropdown of the domain's entity types not yet used |
| decision | `ir_variable` | name (text, validated `^[a-z][a-z0-9_]*$` and unique), index list (a mutator adding set slots), domain dropdown, lower/upper number fields; for `interval`: start/end/size/presence fields |
| parameter | `ir_parameter` | dropdown of the domain's parameter defs (index filled from the def), uncertainty dropdown (`exact`/`interval`/`scenarios`) with deviation % and budget fields |
| rule (expression) | `ir_rule` | id (text), severity dropdown, weight (shown when soft), relation dropdown; value inputs LEFT, RIGHT; a statement input *for every* taking binding blocks; an optional *only while* input taking a `when` block |
| binding | `ir_binding` | index name, set dropdown, optional *where* (filter blocks) and *via* (relationship dropdown, anchor dropdown, depth dropdown) |
| filter | `ir_filter` | attribute dropdown (of the bound set), operator dropdown (by attribute type, from the expression catalogue), value field typed by the attribute |
| when | `ir_when` | binary decision dropdown, index slots, is yes/no |
| scheduling | `ir_no_overlap`, `ir_cumulative` | interval decision, bindings; for cumulative, value inputs DEMAND and CAPACITY |
| connected | `ir_connected` (once the spatial plan lands it) | assignment decision, relationship, empty allowed |
| goal term | `ir_goal_term` | id, weight, value input EXPRESSION |
| number | `ir_const` | number field |
| data | `ir_par` | parameter dropdown, index slots (dropdowns of bound indices of the right set) |
| attribute | `ir_attr` | bound index dropdown, numeric attribute dropdown |
| decision value | `ir_var` | non-interval decision dropdown, index slots |
| sum | `ir_sum` | statement input *over* (bindings), value input BODY |
| add | `ir_add` | a mutator for 2..n inputs (the IR's `add` is n-ary; the read-only view's nested `a + (b + c)` is replaced) |
| product | `ir_mul` | two value inputs |
| curve | `ir_pwl` | decision dropdown, index slots, a points mutator (x, y number pairs) |
| function | `ir_fn` | catalogue dropdown labelled with curvature, value input OF |

**Index slots** are dropdowns offering only the indices bound, at that point, to the set the
declaration expects at that position — computed from the block's ancestors (the enclosing rule's
*for every*, enclosing sums' *over*), the same rule the form editor's `ReferencePicker` applies.

**The toolbox** is categorised: *Declare* (set, decision, parameter), *Rules* (rule, scheduling,
connected, binding, filter, when), *Goal* (goal term), *Values* (number, data, attribute, decision),
*Arithmetic* (sum, add, product, curve, function). A category offers a block only when the domain has
something to fill it with (no *data* block without a parameter).

## 4. From blocks back to the IR

- `frontend/src/lib/blocksToIr.ts`: `blocksToIr(workspaceJson) -> IR`, the inverse of
  `modelToBlocks` (which gains an `editable` flag; read-only mode keeps today's fixed blocks).
- Runs on every change event that alters meaning (create, delete, change, move into/out of an
  input), debounced to one animation frame, and writes the draft store.
- **An incomplete block is not dropped.** An empty input becomes a sentinel the validators refuse by
  name (`{"const": null}` → `const_not_a_number` at that location), so an unfinished model is
  visibly unfinished, never silently different.
- **The round trip is exact:** a test runs every IR in `backend/tests/ir_fixtures.json` (valid ones)
  and every showcase template through `blocksToIr(modelToBlocks(ir))` and requires deep equality
  (key order aside). Any construct without a block fails this test, which is what makes "all of it at
  once" checkable.

## 5. Refusals on the blocks

A refusal's `loc` (e.g. `["constraints", 2, "left", "sum", "mul", 1]`) is mapped to the block that
produced it: `modelToBlocks` records, per block, the IR path it came from (`blockPaths: Map<blockId,
Loc>`), and `blocksToIr` preserves block ids across rebuilds. The block gets Blockly's warning icon
with the refusal's text; the Publish button lists the first refusal and scrolls to its block.

## 6. Where it appears, and how it behaves

- **Optimization view** (`BlocklyView`): an **Edit** toggle in the style bar. Off: today's read-only
  view of the published version. On: the draft, editable, with the toolbox, a trashcan, undo/redo
  (Blockly's own, Ctrl+Z / Ctrl+Shift+Z), the badge, Publish and Discard. Selecting a block still
  opens the side panel.
- **Model editor**: tabs **Forms | Blocks** over the same draft; switching tabs loses nothing.
- **Layout**: `modelToBlocks` lays blocks out top to bottom (model root, declarations, rules, goal); a
  structural change re-lays out only when a block is added from outside the root (a dropped block is
  kept where it was dropped until the next rebuild).
- **Server domain check**: if no dry-run validation endpoint exists, add `POST
  /api/v1/problems/{id}/versions/validate` returning the same refusal body as publish without writing
  anything (the validator already exists; this is a thin route).
- **Accessibility**: Blockly's keyboard navigation plugin is not in the build; the Blocks editor is
  an alternative to the forms, which remain the fully keyboard- and screen-reader-accessible path, and
  both pages say so beside the tab.

## 7. Testing and delivery

**Tests:** the round trip over every fixture and template; each block's fields offer only admissible
choices (a data block inside a sum over `day` offers only indices bound to `day`); an incomplete
block produces the named refusal at the right `loc` and the warning on the right block; the draft
store survives a reload and refuses a silent re-seed; publish from Blocks posts the same IR the forms
would; a browser check builds the feed-blend model from an empty draft by blocks alone, publishes it,
and solves it to the known optimum 43.5317.

**Queue items (in order):**

1. (Blocks 1) Shared draft store — the Model editor moved onto it; nothing visible changes but the
   badge and Continue/Start again.
2. (Blocks 2) Editable blocks for declarations and plain expression rules and goal terms, `blocksToIr`,
   the round trip for fixtures using only those constructs, the Model editor's Blocks tab.
3. (Blocks 3) The advanced constructs' blocks (when, curve, function, intervals, scheduling,
   uncertainty, lexicographic goals) — the round trip now over every fixture and template.
4. (Blocks 4) Refusals on blocks, the dry-run validate route, Edit mode in the optimization view,
   the live browser check.
