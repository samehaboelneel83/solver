# The traversal gap — evidence and a recommendation

**Written for:** whoever takes this decision, which the roadmap places before
model authoring. It is a decision note, not a plan: it ends in a
recommendation, not a task list.

## What cannot be expressed today

The IR contract (`docs/contracts/problem-ir.md`, §9) lists *"traversal cannot
be expressed"* under **derived** — meaning it was not chosen. It follows from
`snapshot_dataset()`, which freezes entities and parameters and **no
relationships at all**. The frozen document a solver reads therefore contains
no edges, so no term can refer to one.

The consequences, in the seeded demo's own vocabulary:

| a planner would say | expressible today |
|---|---|
| "each shift needs `demand[day, shift]` people" | **yes** — it is `c_cover_demand` |
| "nobody works two shifts in a day" | **yes** |
| "North Region needs 3 people on lates, counting its depots" | **no** — needs `reports_to` |
| "an employee's unit must be inside the division they report to" | **no** |
| "no unit may be staffed only by people who report to one manager" | **no** |

The demo's own hierarchy — `head_office → north_region → north_depot` — is
drawn in the graph, nests correctly, and is invisible to every constraint.
The spec anticipated otherwise: it names `unit.descendants` as something the
IR would call, and `docs/schema/2026-09-18-schema-v1.sql:162` carries the
comment *"node + everything beneath it (what `unit.descendants` in the IR will
call)"*. The helper it refers to exists:

```
entity_descendants(p_entity bigint, p_rel_type bigint) returns TABLE(entity_id bigint, depth int)
```

It is used by nothing in the product. It was built for this and then never
reached, because the snapshot it would have fed does not carry edges.

## What it would cost — measured, not estimated

Against the live database (the seeded Workforce demo plus the rows added by
hand while testing):

| | count |
|---|---|
| entities | 29 |
| relationship types | 3 (`reports_to` hierarchy, `works_in`, `has_rank`) |
| relationships | 15 |

Edges are *fewer* than entities here, and that is the normal shape: a
relationship row is two ids and a type, where an entity row carries its whole
attribute object. **Payload size is not the reason to hesitate.** The cost of
freezing edges is contract surface — new term forms, new refusals, new
fixtures, a contract version bump — not bytes.

## The three options

### 1. Freeze the edges, add a traversal term

`snapshot_dataset()` emits a `relationships` key alongside `sets` and
`parameters`, keyed by relationship type name, each a list of `{from, to}`
pairs in entity-key terms (the same key vocabulary `sets` already uses). The
term algebra gains a form that binds an index over the other end of a named
relationship.

- **General.** Covers every question in the table above, not only hierarchies.
- **Reproducible.** Edges freeze with everything else and hash with it, so a
  run's input stays exactly what it was.
- **Honest about depth.** A raw edge list is one hop; "everything beneath"
  needs either a recursive term (which a CP model must unroll anyway) or
  option 2's closure emitted beside it.
- **Cost:** a migration replacing `snapshot_dataset()`, contract v2 with new
  term forms and refusals, fixtures on both sides, and the dataset hash
  changing for everyone (acceptable: `dataset` is immutable and nothing has
  taken a snapshot on the live database — `dataset` holds **0 rows** today).

### 2. Precompute closures only

For each hierarchy relationship type, emit `entity_descendants()` output as
derived sets: `descendants_of[unit] -> [unit, ...]`.

- **Cheap.** The engine exists and is tested; this is a query plus a key in
  the document.
- **Answers the common case** — "counting its sub-units" — which is most of
  what a planner asks.
- **Does not answer** the non-hierarchical ones: `works_in`, `has_rank`, "in
  the same division as". Those are the second question a planner asks.
- **Risk:** it looks like traversal without being traversal, so the first
  question it cannot answer arrives as a surprise rather than a documented
  limit.

### 3. Leave it

Constraints stay flat; hierarchy remains presentational.

- Defensible **only** while there is no solver — which is true today.
- But every model authored before traversal exists is authored in a language
  that cannot say what its author means, and those models are immutable once
  published.

## Recommendation

**Option 1, and before the model editor is built** — but sequenced as two
commits, not one.

The reasoning:

- The editor is the forcing function. A term algebra without traversal is not
  a smaller version of one with it: the binding forms differ, and an editor's
  field pickers, validation messages and fixtures are all shaped by them.
  Building the editor first means reworking it, and reworking a *published*
  contract means a v2 migration for documents users already saved.
- Option 2 is not a cheaper version of option 1; it is a subset that
  advertises more than it delivers. If it ships first, "why can't I say *in
  the same division*?" is the first question, and the answer is "that is a
  different feature" — which is exactly the kind of surprise the contract
  exists to prevent.
- Nothing has been snapshotted yet (`dataset` is empty), so changing the
  frozen document's shape is free **right now** and gets steadily more
  expensive as real runs accumulate.

Sequence:

1. **Freeze the edges.** `snapshot_dataset()` emits `relationships`; contract
   v2 admits the key; fixtures and the parity test follow. No new term forms
   yet — the data is present and unused, which is safe and reversible.
2. **Add the traversal term**, with the closure form (option 2's output) as a
   convenience built on top rather than a separate mechanism.

Step 1 alone unblocks the decision on the editor, because the editor's algebra
can then be designed against a document that will not change underneath it.

## What this does not decide

- **Whether relationship attributes travel too.** `relationship.attrs`,
  `valid_from` and `valid_to` exist and are unexposed in the UI. A
  time-bounded edge is a real modelling need ("this reporting line starts in
  March") and freezing edges without their validity dates would quietly commit
  the platform to ignoring it.
- **Cardinality in the frozen form.** A `many_to_one` edge list and a
  `one_to_many` one have different natural shapes; emitting both as pair lists
  is simplest and may be enough.
