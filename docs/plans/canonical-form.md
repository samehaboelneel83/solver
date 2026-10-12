# The canonical form — inventory of every repair (build-protocol plan, Phase 1.1)

**12 October 2026.** Everything the platform does to a spec between the model's reply and the contract check,
listed with where it lives, the incident it came from, and its class:

- **C — canonicalisation:** one spelling the model uses, one meaning, rewritten to the contract's spelling.
  Keep; becomes a rule of `canonical()` with a test and a corpus example.
- **I — inference:** something the model left implicit that the spec itself determines. Keep, with a test
  that the inference is the only reading; the model is told.
- **H — heuristic:** a guess about what the model meant that the spec does not determine. Demote to a note
  to the model (never a silent edit), or delete.
- **K — check, not a repair** (listed so the boundary is explicit; moves to the checks, untouched here).

## `app/agent/toolcall.py` — the reply as JSON

| What | Incident | Class |
|---|---|---|
| `strict_loads`: duplicate keys joined (last wins, noted) | roster field test | C |
| `mend_brackets`, `_repair`, `fix_spec`: unbalanced brackets, trailing commas, an invalid `\` escape | several local-model replies | C |
| a tool call left inside the model's thinking, taken as the call | roster field test (empty replies) | I |

## `app/agent/repair.py` — the spec's shape

| Function | What | Class |
|---|---|---|
| `spec_of` | the spec as a string → parsed; the spec's parts beside the summary → taken as the spec; a part beside `spec` joins it; a model under `seed` or `model` → lifted to `ir` | C |
| `misplaced` | parts written in the wrong section (a rule under seed, an entity type under ir) moved to theirs | C |
| `joined_keys` | records named by a joined key (`"job-step"`) where two columns were the key | C |
| `repair`: uncertainty on a seed parameter → `ir.parameters` | bakery retest | C |
| `repair`: a parameter with values in the seed but declared only in `ir` → declared in the seed | Nile Juice | I |
| `repair`: a 0/1 list typed as 1 on a default of 1, naming every record → default 0; a partial list → a note | 11 Oct (p02, p04) | I (complete) / note (partial) |
| `repair`: relationships written as objects → their names | 10 Oct | C |
| `repair`: `sets` missing → `[]` | bakery | C |
| `repair`: empty or dict `forall` → left out / a list | feed blend | C |
| `repair`: a decision with no `index` → `[]`; interval parts written as terms → names; `null` bounds → left out | job-shop, paper-cutting | C |
| `repair`: a rule with no severity and no weight → hard | fibre | I |
| `_scalar_indices`: one number read with an index, or with no `index` key → `[]` (IR- and seed-declared) | job-shop, 11 Oct (p10) | C |
| `_walk`: a term with `over` and no `sum` → a sum of the term over the binding | 11 Oct (p07) | C |
| `_walk`/`_lift_sum`: a sum's `over` inside its body, or as `for`/`forall`/`index`+`set` beside it → beside `sum` | feed blend | C |
| `_walk`: `"default": 0` on a sum → left out | Nile Juice | C |
| `_walk`: `sub`/`neg` → `add` with `-1 ×` | production plan | C |
| `_walk`: a `mul`/`add` of one part → the part; bare numbers → `const`; a product of 3+ factors → nested pairs | Delta Pharma, fibre | C |
| `_bound_rules`: a bound given as a field or parameter name → a rule over the records | feed blend | C |

## `app/agent/core.py` — around the spec

| What | Incident | Class |
|---|---|---|
| `bind_literal_keys`: a record's key written where an index belongs → a `where` binding to that record | 10 Oct | C |
| `_platform_order_faults`: map data, records per set, links per relationship, numbers the person never gave | camp retest | K |
| `claims_result` / `RESULT_WITHOUT_RUN`: a result claimed with no run → the claim replaced | 10 Oct | K (a guard) |
| `_GO_AHEAD`: the person's "go ahead" counts as the discussion | routing test | K |
| `agent_draft.complete`: a partial plan completed from the last one; a repeated refusal → the rules held, then the whole plan | 12 Oct | C (merge) / K (the hints) |

## `app/agent/files.py` — the data as loaded

| What | Incident | Class |
|---|---|---|
| `_numeric`: yes/no → 1/0; a number with its unit or currency → the number; `35%` → 0.35 | 10–11 Oct | C |
| `_rows`: a load's `where` honoured | 10 Oct (p02 L) | C (it was a defect) |
| `_wide`: a wide table (`"*"` for the column kind) → cells | 11 Oct | C |
| a list loaded as a constant on a default of the same value, naming every record → default 0; partial → a note | 11 Oct | I / note |
| `pasted_tables`: tables in a message → attached files | 11 Oct (p05) | C |
| a repeated key with the same fields → one record; with different fields → refused | retest | I / K |

## `app/agent/idioms.py` — expansions

| What | Class |
|---|---|
| `carried`, `only_if`, `largest_of`, `exactly_one`/`at_most_one` → the rules they stand for | C (the constructs of Phase 2; inert without the instructions) |

## `app/agent/compact.py` — what a summary keeps

| What | Class |
|---|---|
| the person's first message (clipped), the numbers given, the build, the pasted tables, the plan draft | K (state carried, not a repair) |

## What this says

- **Almost everything is C**: one spelling, one meaning. These move into `app/agent/canon.py` as an ordered
  list of small functions, each with a docstring, the corpus case it came from, and a unit test; the fixed-point
  test (`canonical(gold) == gold`) guards the set.
- **Three inferences** (a parameter declared from its values; a rule hard by default; a complete list's default
  flipped) stay, each with a test that the spec determines the reading.
- **No pure heuristic silently edits a spec today**: the two partial-list cases are notes already. The step 3
  idioms are expansions the model opts into, not repairs.
- **Order of the pass** (what `canonical()` will do, top to bottom): JSON mending → `spec_of` (where the spec
  is) → `misplaced` → `joined_keys` → the draft merge → file loading (`expand`) → the idiom expansions →
  the seed-level rules of `repair` → the IR-level rules (`_scalar_indices`, `_walk`, `_bound_rules`) →
  `bind_literal_keys` → the contract. Today's code runs in this order already across `Agent._spec`; Phase 1.2
  makes it one function with one note list and one test file, and `repair.py` goes.
