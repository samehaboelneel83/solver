# Cursor prompt — simplify the model editor into a sentence-based rule editor

Paste everything below into Cursor (Composer / Agent mode, with the repo open).

---

## Context

We have a React + FastAPI optimization platform. `/model` is where a user writes a
model: declarations (sets, parameters, variables), rules (constraints), and an
objective. Publishing writes an immutable `model_version` via
`POST /api/v1/problems/{id}/versions`. The document is our Problem IR, defined in
`docs/contracts/problem-ir.md` and validated by `backend/app/ir/contract.json`;
the browser runs the shape half in `checkIrShape`.

Today the rule editor is a **tree editor over the IR**. Every IR node gets its own
nested fieldset: "For every" → Index → Over → "Only some of X (optional)" with an
always-open react-querybuilder, then "This" → a term-kind dropdown → "Summed over"
→ another index → another querybuilder. One constraint fills more than a full
screen, and the user has to understand `forall` bindings, term kinds and arity
before they can write "every shift must be covered."

**Goal: a non-specialist writes that rule in one line, and an expert can still reach
every corner of the IR.**

## Hard rules for this work

1. **Do not change the IR, the contract, or the API.** No new term kinds, no new
   constraint fields, no migration. This is purely a new authoring surface over the
   same document.
2. **Round-trip is mandatory.** Every existing `model_version` in the database must
   open in the new editor and, if untouched, re-publish byte-identical IR (same key
   order, same omissions — a missing `objective` stays missing, an unexpressed
   constraint stays unexpressed and stays unpublishable).
3. **Keep `TermBuilder` and `ExpressionBuilder`.** They become the deepest layer,
   not the default one. Do not rewrite `frontend/src/model/TermBuilder.tsx` or
   `whereFilter.ts`; wrap them.
4. Keep `checkIrShape` as the only client-side gate on Publish.

## What to build

### 1. Three layers over the same rule, switchable per rule

Each rule card has a mode selector (`Guided` / `Sentence` / `Expression`). All three
read and write the same IR object. Switching mode never loses information; if a rule
cannot be represented at a shallower layer, that layer is disabled with a one-line
reason ("this rule multiplies two variables — edit it as an expression").

**Layer 1 — Guided (default for new rules).**
"Add a rule" opens a picker of rule *patterns*, grouped by intent, not by
mathematics:

| Group | Patterns |
|---|---|
| Coverage | must be covered by at least / exactly / at most N |
| Limits | total per entity ≤ capacity; total per period ≤ N |
| One-of | at most one X per Y; exactly one X per Y |
| Eligibility | only assign where an attribute or parameter allows it |
| Conflicts | these two choices cannot both be taken |
| Linking | if A then B; A only if B |
| Balance (soft) | keep totals within N of each other |
| Custom | empty rule, opens straight in Expression mode |

Picking a pattern renders a **sentence with filled-in blanks**, and the user only
edits the blanks:

> Every **day**, **shift** must be covered by at least **demand[d, s]** **employee**.
> This rule is **required**.

Blanks are inline chips. Clicking a chip opens a small popover with the legal
choices for that slot only (sets for a set slot; parameters of matching arity for a
parameter slot; variables for a variable slot). Illegal choices are not listed
rather than rejected afterwards.

**Layer 2 — Sentence.** Same sentence, but the structure is editable: add "only
when …" to any index (opens the existing querybuilder in a popover, closed by
default), add "under …" for a `via` walk, change the relation, switch required/
preferred, edit either side. This is where the current form's power lives, minus the
nesting.

**Layer 3 — Expression.** A single-line text DSL with a live parse to IR and inline
errors:

```
for all d in day, s in shift where d.is_weekend:
  sum(assign[e, d, s] for e in employee) >= demand[d, s]
```

Parser and printer live in `frontend/src/model/dsl/`. The printer must be total (any
valid IR prints) and the parser's output must equal the IR it was printed from.
Property-test this round-trip.

### 2. Pattern registry

```ts
// frontend/src/model/patterns/types.ts
export interface RulePattern<P> {
  id: string;                                  // "coverage_at_least"
  group: "coverage" | "limits" | "one_of" | "eligibility"
       | "conflicts" | "linking" | "balance";
  title: string;                               // "Must be covered"
  slots: Slot[];                               // typed blanks
  prose: (p: P, ctx: DomainCtx) => Sentence;   // chips + text
  toIR: (p: P, ctx: DomainCtx) => Constraint;  // emits existing IR
  fromIR: (c: Constraint, ctx: DomainCtx) => P | null; // recognizer
  explain: (p: P, ctx: DomainCtx) => string;   // one-line plain English
}
```

`fromIR` is what makes progressive disclosure work: when a version is loaded, try
every pattern's recognizer; the first match renders the rule at Guided level, and an
unmatched rule falls back to Sentence, then to Expression. Recognizers must be
strict — never show a sentence that does not mean exactly what the IR says.

Ship these patterns in the first pass: `coverage_at_least`, `coverage_exactly`,
`capacity_at_most`, `at_most_one_per`, `eligibility_mask`, `pair_conflict`,
`implies`. Each one is a file under `frontend/src/model/patterns/` with unit tests
covering `fromIR(toIR(p)) === p` and a golden IR snapshot.

### 3. Declarations become mostly implicit

Today the user must declare sets, parameters and variables before writing a rule.
Invert it: while filling a chip, offer the domain's entity types and
`parameter_def`s directly, and when the user picks one that is not yet declared,
declare it as a side effect and show a quiet note in the Declarations panel
("`demand` was added because rule `c_cover_demand` reads it"). Keep the Declarations
panel as a reviewable list, not a required first step. Removing a declaration a rule
still uses stays refused, with the rule named, exactly as today.

### 4. Rule list, not rule wall

The Rules section becomes a list of one-line cards: name, the plain-English
sentence, a required/preferred badge, and the expansion count. Only one card is
expanded at a time. The screen-eating empty querybuilder boxes disappear from the
default view entirely.

### 5. Live expansion preview

Beside the expanded rule, show what it actually produces against the current
dataset or sample data:

- "Expands to 21 constraints (7 days × 3 shifts)."
- A table of the first 5 instances with the `forall` values substituted.
- A warning when expansion is 0 (empty set or a filter that matches nothing) or
  larger than a configurable threshold.

This is the single highest-value addition for non-specialists: it proves the rule
means what they think before they publish.

### 6. Copy

Rewrite the section headings in the user's language, not the IR's:
- Declarations → "What this model talks about"
- Rules → "What must be true"
- Objective → "What to make best"
- `hard` / `soft` → "Required" / "Preferred", with weight shown as "how much it
  matters" only after Preferred is chosen.

Errors name the chip and say what to do. Empty states are invitations: "No rules
yet. Start with a coverage rule."

## Visual direction

Quiet, dense, document-like. This is a tool an analyst stares at for hours, so no
card kit, no shadows, no gradient accents, no all-caps labels. One sans family for
the interface and one mono family used *only* for identifiers inside sentences, so a
chip is visibly a machine name. Single accent colour used only for interactive
chips and validation state. Sentences set at a readable measure; the sentence is the
hero of the page.

## Plan

Work in this order and keep each step shippable:

1. `dsl/` printer + parser + round-trip property tests (no UI).
2. Pattern registry + the seven patterns + recognizer tests.
3. Rule list and the collapsed one-line card.
4. Guided and Sentence layers, with chips and popovers wrapping the existing
   querybuilder and `TermBuilder`.
5. Expression layer wired to the DSL.
6. Implicit declarations.
7. Expansion preview.

Put the Expression layer behind the existing editor for one release: keep the old
nested form reachable from a "classic editor" link so nothing is lost while the new
one settles.

## Acceptance criteria

- Writing `c_cover_demand` (sum over employees ≥ demand, for all day × shift) takes
  one pattern pick and three chip selections, and fits on one screen.
- Loading every existing version in the seeded demo renders without falling all the
  way to Expression, except the two known legacy cases (constraint with no
  `left`/`right`, objective term with no `expression`), which still show "named but
  not expressed" and "Start expressing it" and still refuse to publish.
- For 200 randomly generated valid IR documents: print → parse → deep-equals the
  original, and `toIR(fromIR(c))` deep-equals `c` wherever `fromIR` returns non-null.
- Publish produces the same bytes as the old editor for the same model.
- No changes under `backend/app/ir/` other than tests.

Before writing code, read `frontend/src/model/terms.ts`, `TermBuilder.tsx`,
`whereFilter.ts` and `docs/contracts/problem-ir.md`, then reply with the pattern
registry types and the DSL grammar you propose, and wait for my confirmation.
