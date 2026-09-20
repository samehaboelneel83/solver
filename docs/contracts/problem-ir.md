# The problem IR — what a model is

**Version 1.** Written 2026-09-20, as Phase 0 of
`docs/plans/2026-09-20-platform-roadmap.md`.

**Status:** in force. `POST /api/v1/problems/{id}/versions` refuses a document
that does not meet it.

| the contract | where |
|---|---|
| this document — what a model *means* | `docs/contracts/problem-ir.md` |
| the machine-readable half — what a validator may accept | `backend/app/ir/contract.json` |
| the validator, server side | `backend/app/ir/validate.py` |
| the validator, client side (shape rules only) | `frontend/src/ir/validate.ts` |
| the fixtures both sides assert | `backend/tests/ir_fixtures.json` |

Three files pin those to each other and none of them can be changed alone:
`frontend/src/ir/parity.test.ts` deep-compares the TypeScript against the JSON,
`backend/tests/test_ir_contract.py` asserts the rule list and the fixture codes
are the same set in both directions, and both fixture tests assert the `code`
and `loc` written in the fixture file rather than each other's output. This is
the mechanism the expression core already uses (Ruling 37); nothing here is new
about it.

---

## 1. Why this document exists, and what it is not

`model_version.ir` is `jsonb`. Its shape was defined by a solver — `ProblemIR`
in `psp/data.py` — that is **not in this repository**. The solver was asked for
twice and not supplied. So this contract was written here, and **the solver is
now the consumer that must adapt**.

That is not as arbitrary as it sounds, because part of the IR was already
committed, by accident rather than by design. `snapshot_dataset()` (migration
`0007`, amended in `0009`) reads `ir.sets` as an array of entity type names and
`ir.parameters` as an object keyed by parameter name, resolves both against the
live domain, and raises on anything else. Anything this contract said about
those two keys other than what that function does would have been a second
answer to a question that already had one.

Everything below is marked **derived** (it follows from evidence already in the
repository) or **invented** (it was decided here, and a later reader may
reopen it). Section 9 collects the list.

---

## 2. A model, in one example

This is the seeded Workforce demo, and it is the same document as the
`workforce` case in `backend/tests/ir_fixtures.json` and the `_IR` constant in
`backend/app/seed.py` — a test asserts all three are one document.

```json
{
  "version": 1,
  "sets": ["employee", "unit", "day", "shift"],
  "parameters": { "demand": { "index": ["day", "shift"] } },
  "variables": { "assign": { "index": ["employee", "day", "shift"], "domain": "binary" } },
  "constraints": [
    {
      "id": "c_cover_demand",
      "note": "each day/shift is staffed to at least demand[day, shift]",
      "forall": [{ "index": "d", "set": "day" }, { "index": "s", "set": "shift" }],
      "left": {
        "sum": { "var": "assign", "index": ["e", "d", "s"] },
        "over": [{ "index": "e", "set": "employee" }]
      },
      "relation": ">=",
      "right": { "par": "demand", "index": ["d", "s"] },
      "severity": "hard"
    },
    {
      "id": "c_one_shift_per_day",
      "note": "nobody works two shifts in a day",
      "forall": [{ "index": "e", "set": "employee" }, { "index": "d", "set": "day" }],
      "left": {
        "sum": { "var": "assign", "index": ["e", "d", "s"] },
        "over": [{ "index": "s", "set": "shift" }]
      },
      "relation": "<=",
      "right": { "const": 1 },
      "severity": "hard"
    },
    {
      "id": "c_max_hours",
      "note": "weekly hours stay within hours_per_week; every seeded shift is eight hours long",
      "forall": [{ "index": "e", "set": "employee" }],
      "left": {
        "mul": [
          { "const": 8 },
          {
            "sum": { "var": "assign", "index": ["e", "d", "s"] },
            "over": [{ "index": "d", "set": "day" }, { "index": "s", "set": "shift" }]
          }
        ]
      },
      "relation": "<=",
      "right": { "attr": { "of": "e", "name": "hours_per_week" } },
      "severity": "hard"
    }
  ],
  "objective": {
    "sense": "minimize",
    "terms": [
      {
        "id": "o_shifts_worked",
        "weight": 1,
        "expression": {
          "sum": { "var": "assign", "index": ["e", "d", "s"] },
          "over": [
            { "index": "e", "set": "employee" },
            { "index": "d", "set": "day" },
            { "index": "s", "set": "shift" }
          ]
        }
      }
    ]
  }
}
```

Read aloud: *there are employees, units, days and shifts; demand is a number per
day and shift; `assign[e, d, s]` says whether employee e works shift s on day d.
For every day and shift, at least `demand` employees are assigned. For every
employee and day, at most one shift. For every employee, eight hours per
assigned shift is within their `hours_per_week`. Among the rotas that satisfy
all of that, prefer the one with the fewest shifts worked.*

---

## 3. The document

An IR is a JSON **object**. It carries exactly these keys and no others.

| key | required | what it is |
|---|---|---|
| `version` | yes | `1`. Present from the first document ever written, so a reader can refuse what it does not understand instead of misreading it. |
| `sets` | yes | An array of **entity type names**. What the dataset must freeze. |
| `parameters` | yes | An object keyed by **parameter name**. What indexed data the model reads. |
| `variables` | yes | An object keyed by variable name. What the solver decides. At least one. |
| `constraints` | yes | An array. May be empty. |
| `objective` | no | Omit it for a pure feasibility problem. |

`sets`, `parameters`, `variables` and `constraints` are required **even when
empty**, because a `model_version` is frozen and hashed: a reader of one should
not have to know the platform's defaults to know what it says.

Every name — a set, a parameter, a variable, a constraint id, an objective term
id, an index, an attribute — matches `^[a-z][a-z0-9_]*$`. That is not a new
rule: it is the CHECK that `entity_type.name`, `attribute_def.name` and
`parameter_def.name` already carry, and migration `0006` says why — "used in IR
expressions". A test asserts the contract's pattern is that pattern.

### 3.1 `sets`

```json
"sets": ["employee", "unit", "day", "shift"]
```

Each entry names an entity type of **the problem's own domain**. At submit time
the platform resolves them; an unresolvable name is a 422 naming the element.

A set may be declared and never used in an expression — `unit` above is.
`sets` says what data the dataset carries, not what the arithmetic touches, so
carrying a set for display or for a later version is legitimate.

*Derived*: the array-of-names shape, and resolution against the domain, both
from `snapshot_dataset()`.

### 3.2 `parameters`

```json
"parameters": { "demand": { "index": ["day", "shift"] } }
```

Each key names a `parameter_def` of the problem's domain. `index` is the
ordered, non-empty list of set names it is indexed by, and it must be **exactly**
the domain's own `index_type_ids` resolved to names, in that order.

That last rule is worth its weight. `snapshot_dataset()` emits a parameter's
cells keyed by entity **type name**, so an IR that reads `demand` as
`[shift, day]` snapshots without complaint, solves a different model, and
nothing downstream ever notices. Checking it at submit time is the only place
the mistake is visible.

Parameter values are integers — `parameter_value.value` and
`parameter_def.default_value` are both `int`. A cell absent from the snapshot
means the parameter's `default_value`, which travels beside the data as
`parameter_defaults` (migration `0009`). The solver's rule is "look the cell up;
if absent, use the default".

*Derived*: the object-keyed shape, resolution, and the integer values.
*Invented*: the `{"index": [...]}` declaration and the order check.

### 3.3 `variables`

```json
"variables": { "assign": { "index": ["employee", "day", "shift"], "domain": "binary" } }
```

| key | required | what it is |
|---|---|---|
| `index` | yes | Set names. **Empty** for a scalar variable. Up to 6. |
| `domain` | yes | `binary` or `integer`. Nothing defaults it — see §7. |
| `lower`, `upper` | no | Integers, `lower <= upper`, only on an `integer` variable. A binary one's bounds are 0 and 1. |

*Invented*, all of it.

### 3.4 `constraints`

```json
{
  "id": "c_one_shift_per_day",
  "note": "nobody works two shifts in a day",
  "forall": [{ "index": "e", "set": "employee" }, { "index": "d", "set": "day" }],
  "left":  { "sum": { "var": "assign", "index": ["e", "d", "s"] },
             "over": [{ "index": "s", "set": "shift" }] },
  "relation": "<=",
  "right": { "const": 1 },
  "severity": "hard"
}
```

| key | required | what it is |
|---|---|---|
| `id` | yes | Unique within the model. |
| `note` | no | Prose, for a human. It is **not** the constraint. |
| `forall` | no | Index bindings; the constraint has one instance per combination. Omit the key when there is nothing to range over — an empty array is refused, because it is a constraint written as if it were indexed and is not. |
| `left`, `relation`, `right` | yes | The constraint itself. `relation` is `<=`, `=` or `>=`. |
| `severity` | yes | `hard` or `soft`. |
| `weight` | iff soft | A positive integer penalty. A hard constraint carries none. |

**The id is load-bearing in three places**, which is why it is unique and
spelled the platform's one way: `scenario.patch` names it, `constraint_result`
is keyed `(run_id, constraint_id)`, and `run.conflict` reports it.

Strict inequalities (`<`, `>`) are not in v1. Over integers they are the
non-strict relation shifted by one, and admitting both spellings would give one
model two IRs and two hashes.

*Derived*: the ids, from `scenario.patch` and `constraint_result`. The
hard/soft split, from `constraint_result.hard boolean` and `penalty_paid`.
*Invented*: everything else, including the decision that `left`/`relation`/
`right` are mandatory (§8).

### 3.5 `objective`

```json
"objective": { "sense": "minimize",
               "terms": [{ "id": "o_shifts_worked", "weight": 1, "expression": { … } }] }
```

`sense` is `minimize` or `maximize`. `terms` is a non-empty array; each term has
a unique `id`, an integer `weight` and an `expression`. Omit the whole key for a
feasibility problem.

Terms exist so a result can say which part of the objective cost what. An
objective term's expression is evaluated in an empty scope: it binds its own
indices with `sum`, and there is no `forall` at this level.

*Derived*: `run.objective bigint` (one number, integral) and the `o_cost` term
id the seeded sketch already had. *Invented*: that a term carries its own
expression — which is exactly what the sketch was missing.

---

## 4. Terms — the arithmetic

A **term** is an object naming exactly one kind. Seven kinds:

| kind | shape | means |
|---|---|---|
| `const` | `{"const": 8}` | An integer literal. |
| `par` | `{"par": "demand", "index": ["d", "s"]}` | A parameter, subscripted by bound indices. |
| `var` | `{"var": "assign", "index": ["e", "d", "s"]}` | A variable, likewise. |
| `attr` | `{"attr": {"of": "e", "name": "hours_per_week"}}` | An integer attribute of whatever `e` is bound to. |
| `sum` | `{"sum": <term>, "over": [<binding>, …]}` | The sum of the body over the bindings. |
| `add` | `{"add": [<term>, …]}` | A sum of terms. At least one. |
| `mul` | `{"mul": [<term>, <term>]}` | A product of exactly two factors. |

Rules the validator enforces on them:

- **Subscript arity and type.** A `par` or `var` is subscripted with as many
  indices as it was declared with, and the index at each position must be bound
  to the set declared at that position. `assign[s, d, e]` type-checks by arity
  and is a different model; it is refused.
- **Every index is bound.** By an enclosing `forall` or `over`. A free index has
  no range, so the constraint has no instances.
- **Products are linear.** At most one factor of a `mul` may contain a variable.
  `x * x` is refused here, so the platform says "v1 expresses linear models" —
  rather than a solver failing later with a message about the model class.
- **Integers throughout.** `const` is an integer. Parameters are integers by the
  schema. An `attr` used as a number must have data type `integer` — a `number`
  attribute such as `employee.hourly_rate` is refused, because admitting it
  would make a model continuous without anyone deciding to (§7).
- **Limits.** Depth 12, 500 terms, 6 indices per binding, 256 KiB serialised.

An `attr` is resolvable from the frozen dataset because `snapshot_dataset()`
emits each set row as `{"id": key} || attrs` — the attributes travel with the
entities. That is *derived*; the term itself is *invented*.

### 4.1 Bindings and `where`

```json
{ "index": "d", "set": "day", "where": [{ "attr": "is_weekend", "op": "=", "value": true }] }
```

A binding names an index and the set it ranges over, optionally filtered.
`where` is a flat AND-list of filters over attributes of **that binding's own
set**. There are no groups and no `or` in v1: the full boolean tree already
exists in the expression core and can be lifted here in v2 if a real model
needs it.

`op` comes from `filterOperators` in `contract.json`, which is a **subset of the
expression catalogue's `operators`** — `app/ir/contract.py` raises at import time
if any name is not in `app/expressions/catalogue.json`. Which operators a
particular attribute offers comes from that catalogue's `operatorsByType`, read
through the same `operators_for()` the entity filter uses. There is one operator
vocabulary on this platform, not two.

A filter's value must be a value of the attribute's data type — the same
judgement `entity_validate` makes when the value is stored.

---

## 5. What is deliberately not supported yet

Each of these was considered and left out for a reason, not overlooked.

**Relationship traversal — `unit.descendants`.** The schema anticipates it:
`docs/schema/2026-09-18-schema-v1.sql:162` introduces `entity_descendants()` as
"what `unit.descendants` in the IR will call". **v1 cannot express it, and the
reason is not in the IR at all.** `snapshot_dataset()` freezes `sets`,
`parameters` and `parameter_defaults` — and **no relationships**. A traversal
term would reference data the frozen dataset does not contain, and "a run never
reads live domain data, it reads a frozen snapshot" is the reproducibility
guarantee the whole RUN half is built on. Admitting a term the dataset cannot
answer would break that guarantee silently. Unblocking it means adding a
`relationships` key to the snapshot, which is a change to `snapshot_dataset()`
and therefore to the dataset hash — a deliberate decision, not a detail.
**This is the sharpest contradiction between the contract and the existing
code, and it is recorded rather than resolved.**

**Continuous variables and continuous coefficients.** §7.

**Strict inequalities**, for the reason in §3.4.

**Boolean structure inside a model** — indicator constraints, disjunctions,
`all_different`, `no_overlap`, precedence. The roadmap's Phase 2 classifies
"CP / scheduling" by exactly these; none is expressible in v1, so no model can
be classified into that family yet.

**Nested or negated filters**, `or`, and comparing one attribute to another.

**Named subexpressions**, quadratic terms, division, `min`/`max`, absolute
value, conditionals.

**Multi-objective**. `terms` with weights is scalarisation: one number comes
out, which is what `run.objective bigint` records.

---

## 6. Refusals

One refusal, not all of them, in a documented order, as the platform's standard
list-form 422:

```json
{"detail": [{"type": "value_error",
             "loc": ["body", "ir", "variables", "x", "domain"],
             "msg": "\"continuous\" is not a variable domain version 1 solves; …",
             "input": "continuous"}]}
```

`loc` points at the offending element, so a builder can highlight it
(Rulings 19, 30). The reason for one refusal rather than a list is the one
`app/expressions/parse.py` already records: the client validates the same
document against the same contract before sending, so a 422 from the server is
either a hand-written request or a client that has not reloaded the contract,
and naming one thing precisely beats listing several.

The 65 rules are in `contract.json`, each marked `shape` (58 of them: decidable
from the document alone, and both languages decide those) or `domain` (7: needs
the domain's rows, so the server only). The split mirrors `parse.py` /
`compiler.py`. `ir_fixtures.json` carries 8 valid documents and 75 invalid ones
— at least one per rule, several rules having more than one where the rule has
two halves or where a fault has to be reached through a construct no other case
goes through.

**Two of those rules used to be 500s.** `snapshot_dataset()` refuses an
unresolvable set or parameter with a bare `RAISE EXCEPTION`, i.e. SQLSTATE
`P0001`, which `translate_db_error` does not attribute to a field — so an IR
accepted at submit time surfaced as a 500 from whatever route eventually took a
snapshot. `set_not_in_domain` and `parameter_not_in_domain` now make the same
judgement at submit time, as a 422. `snapshot_dataset()` is unchanged and
remains the backstop for the case this cannot cover: a domain that loses an
entity type *after* a version was frozen.

---

## 7. The decision on continuous variables

**v1 admits `binary` and `integer` variables and refuses `continuous` by name.**
Refused by name, not merely absent, so the refusal can say what is missing.

The schema is integer-only by decision (spec §2: `parameter_value.value` and
`parameter_def.default_value` are `int`, `run.objective` is `bigint`, "deliberate
for CP-SAT"). Three things follow:

1. **There is no solver.** Admitting a variable domain nothing can run and
   nothing can test would make the contract promise what the platform cannot
   keep — which is precisely the failure Phase 0 exists to end.
2. **A half-continuous model would arrive by accident.** Parameters are `int`,
   but entity attributes are not: `attr_type` has `number`, and the seed's own
   `employee.hourly_rate` is one. If `attr` terms admitted `number` attributes,
   a model could acquire fractional coefficients through the back door while its
   parameters stayed integral, and nobody would have decided that. So v1
   restricts arithmetic `attr` terms to `integer` attributes and keeps the whole
   model integral. (`number` attributes are still usable in a `where` filter: a
   filter selects members, it does not enter the objective.)
3. **The cost is visible and was paid in the demo.** The Workforce objective
   minimises *shifts worked*, not *cost*, because the only cost-bearing datum in
   that domain is a `number`. And `c_max_hours` multiplies by a literal `8`
   because a shift's length lives in `time` attributes, which v1 arithmetic
   cannot read. Both are honest markers of the boundary, left in the seed on
   purpose.

**What admitting continuous later implies** — this is the list the roadmap's
Phase 2 asked for, made concrete:

- a numeric type for `parameter_def.default_value` and `parameter_value.value`
  (a schema migration, and a UI that stops saying "integers only");
- `run.objective` widened from `bigint`;
- `number` attributes admitted as coefficients, and `const` admitted as a
  rational or decimal — with a decision about how they are *stored*, since a
  float in an immutable hashed document makes the hash depend on a text
  rendering;
- a `continuous` variable domain with bounds, and `lower`/`upper` no longer
  integers;
- a solver that can take them (HiGHS or IPOPT, per the roadmap), because CP-SAT
  cannot;
- the honesty rule the roadmap already names: where convexity cannot be proven,
  a result is a *local* optimum and must say so.

Bumping the IR to version 2 is how all of that lands. The `version` field is
here from the first document for exactly this.

---

## 8. The decision on the seeded IR

The seeded IR **was** this:

```json
"constraints": [
  {"id": "c_cover_demand", "note": "each day/shift is staffed to at least demand[day, shift]"},
  {"id": "c_one_shift_per_day", "note": "nobody works two shifts in a day"},
  {"id": "c_max_hours", "note": "weekly hours stay within hours_per_week"}
],
"objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1}]}
```

Three constraints named and none expressed, and an objective term referencing an
id that nothing defines. The choice was: admit "declared but unexpressed" as a
legitimate draft state, or rewrite the seed.

**Decided: the contract admits no unexpressed constraint, and the seed was
rewritten.** The reasons, in order of weight:

1. **A `model_version` is not a draft.** It is immutable (`forbid_update()`), it
   is content-hashed (`set_hash()`), it is what a `run` points at for
   reproducibility, and there is deliberately no PUT, PATCH or DELETE on one.
   "Draft" is a state of something being edited; this row cannot be edited.
   Admitting a half-model here would mean the platform's one immutable,
   reproducible artefact could be a promise rather than a model.
2. **Drafting has a home, and it is Phase 1.** The roadmap already puts
   `variable_def`, `constraint_def` and `objective_def` rows in front of the IR,
   with the IR as "the compiled, frozen form" — authoring edits the rows,
   publishing compiles them. A constraint with an id and a note and no
   expression is a perfectly good `constraint_def` row. It is not a published
   version. Admitting it into the IR would build the draft state in the one
   place that cannot hold it, and Phase 1 would then have to take it back out.
3. **An unexpressed constraint defeats every consumer at once.** It cannot be
   solved, it cannot be classified (Phase 2 classifies from the expressions), it
   cannot be diffed meaningfully between versions, it cannot report into
   `constraint_result`, and `scenario.patch` can name it to no effect. A
   contract that admits it is a contract that guarantees nothing.
4. **It would have made the fixture set dishonest.** The point of Phase 0 is
   that an IR can be validated by a test. A rule of "constraints may or may not
   carry expressions" is not a rule.

The rewritten seed expresses what the three notes claimed, and the demo still
snapshots correctly — `sets` and `parameters` are byte-for-byte what they were,
so `snapshot_dataset()` produces exactly the same dataset it did before. What
changed is the `ir_hash`, which is correct: it is a different model.

One property of the rewritten demo is worth stating, because it looks like a
bug and is not. Five employees with 40/32/40/20/40 weekly hours can work at most
21 eight-hour shifts in a week; demand over the seeded week is 57. **The demo is
deliberately over-subscribed**, which is why the seeded scenario is called
`relaxed_cover` and softens `c_cover_demand`. The sketch could not have shown
that, because it had no arithmetic for anything to be infeasible in.

---

## 9. Derived and invented, in one list

**Derived** — these follow from evidence already in the repository, and changing
them means contradicting something that exists:

| what | from |
|---|---|
| `sets` is an array of entity type names | `snapshot_dataset()` |
| `parameters` is an object keyed by parameter name | `snapshot_dataset()` |
| both resolve against the problem's domain | `snapshot_dataset()` — this was a 500, now a 422 |
| names match `^[a-z][a-z0-9_]*$` | the CHECK on `entity_type` / `attribute_def` / `parameter_def`, whose stated reason is the IR |
| a parameter's index is ordered | `parameter_def.index_type_ids`, and `parameter_value.entity_ids` "same order as index_type_ids" |
| parameter values and defaults are integers | spec §2 |
| an absent cell means the parameter's default | migration `0009`'s `parameter_defaults` |
| entity attributes are readable from the frozen dataset | `snapshot_dataset()` emits `{"id": key} \|\| attrs` |
| constraints have string ids, unique per model | `scenario.patch`; `constraint_result` PK `(run_id, constraint_id)` |
| constraints are hard or soft, soft ones carry an integer penalty | `constraint_result.hard boolean`, `penalty_paid bigint`; `patch.soften: {id: weight}` |
| one objective, one integral number | `run.objective bigint` |
| `version` from the first document; one shared JSON artefact; a parity test; `loc`-shaped refusals | the expression core (Ruling 37, Rulings 19/30) |
| traversal cannot be expressed | `snapshot_dataset()` freezes no relationships |

**Invented** — decided here, and a later reader may reopen any of them:

- the term algebra: seven kinds, `forall`/`over` bindings, named indices;
- `{"index": …, "domain": …}` on a variable, and the two admitted domains;
- the parameter index *order* check against the domain;
- `left`/`relation`/`right` mandatory on every constraint (§8);
- objective terms carrying their own expressions;
- the linearity rule on `mul`;
- integer-only arithmetic, including the `integer`-attributes-only rule (§7);
- the flat `where` filter, and narrowing the catalogue's operators for it;
- all four limits (12 / 500 / 6 / 256 KiB);
- every top-level key being required, including empty ones;
- refusing unknown keys anywhere rather than ignoring them.

---

## 10. Changing this contract

1. Edit `contract.json` — it is the definition.
2. Edit `frontend/src/ir/contract.ts` to match, or `parity.test.ts` fails.
3. Add a fixture to `ir_fixtures.json` for any new rule, or
   `test_ir_contract.py` fails; the fixture must be wrong in exactly one way.
4. Implement it in `app/ir/validate.py`, and in `frontend/src/ir/validate.ts`
   if the rule is `shape`.
5. A change that would refuse a document version 1 accepts is a **new version**,
   not an edit. Stored versions are immutable and are never re-validated; only
   submission is judged.
