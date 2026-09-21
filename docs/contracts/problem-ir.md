# The problem IR — what a model is

**Version 1.** Written 2026-09-20, as Phase 0 of
`docs/plans/2026-09-20-platform-roadmap.md`. Amended 2026-09-21 to admit
continuous variables and fractional numbers (§7); still version 1, for the
reason §10 now records.

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
  "relationships": ["reports_to", "works_in"],
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
    },
    {
      "id": "c_north_region_lates",
      "note": "North Region puts three people on the late shift every day, counting the depots under it",
      "forall": [
        { "index": "d", "set": "day" },
        { "index": "r", "set": "unit",
          "where": [{ "attr": "cost_centre", "op": "=", "value": "OPS-100" }] },
        { "index": "late", "set": "shift",
          "where": [{ "attr": "starts_at", "op": "=", "value": "14:00" }] }
      ],
      "left": {
        "sum": { "var": "assign", "index": ["e", "d", "late"] },
        "over": [
          { "index": "sub", "set": "unit",
            "via": { "rel": "reports_to", "from": "r", "depth": "any_or_self" } },
          { "index": "e", "set": "employee",
            "via": { "rel": "works_in", "to": "sub" } }
        ]
      },
      "relation": ">=",
      "right": { "const": 3 },
      "severity": "soft",
      "weight": 4
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

Read aloud: *there are employees, units, days and shifts, and units report to
units while employees work in units; demand is a number per day and shift;
`assign[e, d, s]` says whether employee e works shift s on day d. For every day
and shift, at least `demand` employees are assigned. For every employee and
day, at most one shift. For every employee, eight hours per assigned shift is
within their `hours_per_week`. North Region — the OPS-100 cost centre — puts
three people on the late shift each day, counting everyone in the units
beneath it, and pays 4 for each one it is short. Among the rotas that satisfy
all of that, prefer the one with the fewest shifts worked.*

That last rule is the one that needs §4.2. **Nobody works in North Region
itself** — its people are all in the depot one level down — so a constraint
written over the unit alone counts zero and is unsatisfiable for a reason that
has nothing to do with the roster. Two walks compose to fix that: down the
hierarchy, then out to the people.

It is soft and deliberately short by one, for the same reason the demand
figures are over-subscribed: the demo shows the platform reporting what a plan
costs, not a plan that happens to work.

---

## 3. The document

An IR is a JSON **object**. It carries exactly these keys and no others.

| key | required | what it is |
|---|---|---|
| `version` | yes | `1`. Present from the first document ever written, so a reader can refuse what it does not understand instead of misreading it. |
| `sets` | yes | An array of **entity type names**. What the dataset must freeze. |
| `relationships` | no | An array of **relationship type names**. Which edges the dataset must freeze, and the only ones a `via` may walk (§4.2). Omit it for a model that does not traverse. |
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

A set may be declared and never used in an expression. `sets` says what data
the dataset carries, not what the arithmetic touches, so carrying a set for
display or for a later version is legitimate. (`unit` used to be the example
here and no longer is: `c_north_region_lates` ranges over it.)

*Derived*: the array-of-names shape, and resolution against the domain, both
from `snapshot_dataset()`.

### 3.1.1 `relationships`

```json
"relationships": ["reports_to", "works_in"]
```

Optional, and absent means none — which is every model written before
traversal existed. Each entry names a `relationship_type` of the problem's own
domain, and `snapshot_dataset()` freezes the edges of exactly these and no
others (migration `0016`).

Unlike `sets`, there is no reason to declare one and not use it: you declare a
relationship to walk it. The model editor therefore does not ask — it writes
this key from the walks the model contains.

*Derived*: the freezing, from `snapshot_dataset()` as amended by `0011` and
`0016`. *Invented*: that the declaration is what the snapshot follows, rather
than the domain's own list.

### 3.2 `parameters`

```json
"parameters": { "demand": { "index": ["day", "shift"] } }
```

Each key names a `parameter_def` of the problem's domain. `index` is the
ordered, non-empty list of set names it is indexed by, and it must be **exactly**
the domain's own `index_type_ids` resolved to names, in that order.

That last rule is worth its weight. `snapshot_dataset()` emits a parameter's
cells keyed by entity **type name** when every index type is distinct, so an
IR that reads `demand` as `[shift, day]` snapshots without complaint, solves
a different model, and nothing downstream ever notices. Checking it at submit
time is the only place the mistake is visible. A repeated index type
(`distance[location, location]`) cannot use those names: both ends would be
the key `location`. Migration `0025` keys those cells by position (`"0"`,
`"1"`, …) instead. The compiler prefers positional keys when they are all
present, and falls back to type names so a dataset frozen before 0025 still
solves.

Parameter values are numbers — `parameter_value.value` and
`parameter_def.default_value` are `numeric(15, 6)` since migration `0015`; they
were `int` when this contract was first written, and §7 records why that
changed. A cell absent from the snapshot means the parameter's `default_value`,
which travels beside the data as `parameter_defaults` (migration `0009`). The
solver's rule is "look the cell up; if absent, use the default".

A whole value keeps its whole shape on the wire: `snapshot_dataset()` applies
`trim_scale`, so a model that has never used a decimal cannot tell that
decimals exist. `3` does not become `3.000000`.

*Derived*: the object-keyed shape, resolution, and the numeric values.
*Invented*: the `{"index": [...]}` declaration and the order check.

### 3.3 `variables`

```json
"variables": { "assign": { "index": ["employee", "day", "shift"], "domain": "binary" } }
```

| key | required | what it is |
|---|---|---|
| `index` | yes | Set names. **Empty** for a scalar variable. Up to 6. |
| `domain` | yes | `binary`, `integer` or `continuous`. Nothing defaults it — see §7. |
| `lower`, `upper` | no | Numbers, `lower <= upper`, only on an `integer` or `continuous` variable. A binary one's bounds are 0 and 1. An `integer` variable's bounds must be **whole**: a fractional bound would be rounded by every solver that took it, and differently by some. |

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

**`weight` is the only name for a penalty.** A scenario's `soften` verb sets
this key, and the compiler reads this key. They used not to: `soften` wrote a
`penalty` the contract does not have and the compiler read the same invented
name, so a weight written in a *model* was silently charged at 1. It went
unnoticed because every soft constraint ever compiled had come from a patch —
the seeded demo had none of its own until §4.2's traversal constraint.

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

`sense` is `minimize` or `maximize`. Optional `mode` is `weighted` (the
default, omit the key) or `lex`. `terms` is a non-empty array; each term has
a unique `id`, an integer `weight` and an `expression`. Omit the whole key for a
feasibility problem.

**`weighted` is scalarisation** — `run.objective` is the sum of `weight * term`.
**`lex` is term order** — the first term is made as good as it can be, then
frozen, then the next, and so on. Weights are still required (the term shape
does not change) but they are not mixed. Soft-constraint penalties are an
implicit last term, so bending a rule is never cheaper than meeting a
higher-priority goal.

Omitting `mode` is a widening: every document version 1 accepted still
means a weighted sum and still hashes the same (§10.1).

**Weights stayed integers** when §7 admitted fractional numbers everywhere
else, and that is a decision rather than an oversight. A weight is the modeller
saying *this matters three times as much as that*; it is a ratio between terms,
and any ratio a decimal expresses an integer pair expresses too. Admitting
`0.3333` would buy nothing and would invite a rounding argument about a number
that has no unit. The same holds for a soft constraint's penalty in §3.4.

Terms exist so a result can say which part of the objective cost what. An
objective term's expression is evaluated in an empty scope: it binds its own
indices with `sum`, and there is no `forall` at this level.

*Derived*: `run.objective` (one number) and the `o_cost` term id the seeded
sketch already had. It was `bigint` when this was written, which is where "one
*integral* number" came from; migration `0015` widened it to `numeric(15, 6)`.
*Invented*: that a term carries its own expression — which is exactly what the
sketch was missing.

---

## 4. Terms — the arithmetic

A **term** is an object naming exactly one kind. Seven kinds:

| kind | shape | means |
|---|---|---|
| `const` | `{"const": 8}` | A numeric literal. |
| `par` | `{"par": "demand", "index": ["d", "s"]}` | A parameter, subscripted by bound indices. |
| `var` | `{"var": "assign", "index": ["e", "d", "s"]}` | A variable, likewise. |
| `attr` | `{"attr": {"of": "e", "name": "hours_per_week"}}` | A numeric attribute of whatever `e` is bound to. |
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
- **Numbers throughout, and finite ones.** `const` is a number. Parameters are
  `numeric(15, 6)` by the schema. An `attr` used as a number must have data
  type `integer` or `number` — a `text` or `date` attribute is still refused,
  because it is not a quantity. NaN and infinity are refused too: JSON cannot
  carry them but a hand-built request can, and a coefficient of infinity is a
  model no solver answers usefully.
- **Fractional data is visible, not silent.** Nothing here refuses a decimal,
  but the platform records what one costs: a fractional number anywhere in the
  model or its data adds `fractional-data` to what a backend must provide, and
  CP-SAT does not provide it. See §7.
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

### 4.2 `via` — traversal

```json
{ "index": "sub", "set": "unit",
  "via": { "rel": "reports_to", "from": "r", "depth": "any_or_self" } }
```

A binding with a `via` ranges not over its whole set but over the members
**reached from an anchor** along a relationship.

| key | required | what it is |
|---|---|---|
| `rel` | yes | A relationship type named in `relationships`. |
| `from` *or* `to` | exactly one | The index the walk starts at, and **which end of the edge that index sits at**. The binding takes the other end. |
| `depth` | no | `one` (the default), `any`, or `any_or_self`. |

`from: "r"` therefore reads *"r is at the from end; bind the to end"*. Naming
the anchor's end rather than a direction means there is nothing to get
backwards: for `reports_to`, whose `from` is the parent, `from` walks down and
`to` walks up, and both are the same key doing the same thing.

**`any_or_self` includes the anchor; `any` does not.** `entity_descendants()`
has always returned "node + everything beneath it", and that reflexive shape
is what a planner means by "counting its sub-units" — so it has a name rather
than being conflated with the strict closure. `one` is a single edge.

**Traversal is a binding form, not an eighth term kind.** `termKinds` is
unchanged. The consequences are the point: `sum` already takes `over:
[bindings]` and `forall` already takes bindings, so "sum over everything
beneath this unit" and "for every unit, counting its depots" both come for
free, `where` composes with a walk unchanged, and `depth` makes the closure a
*mode* of one mechanism rather than a second one.

Rules on top of the table:

- **The anchor is bound before the walk starts** — by an enclosing `forall`,
  or by an earlier binding in the same list. This ordering rule is what makes
  the product well defined; without it a binding could walk from itself.
- **The two ends are the relationship's own entity types**, the right way
  round. Walking `works_in` from a unit is a `domain` rule, because only the
  relationship type's rows say which end is which.
- **A repeated walk needs a relationship that joins a type to itself.**
  Walking `works_in` twice would step from a unit to an employee and then look
  for an edge out of a unit again, so `any` and `any_or_self` are refused on
  it. Note the rule is about the *endpoint types*, not `is_hierarchy`: a
  self-joining type with a cycle is still walkable, and the compiler
  terminates on one rather than assuming acyclicity a frozen dataset is never
  re-checked for.

**The walk reads the frozen edges.** `data["relationships"]`, never
`entity_descendants()` against live rows — a run answers the question as it
was asked, and an org chart that changed after the snapshot must not change
what that snapshot solves.

---

## 5. What is deliberately not supported yet

Each of these was considered and left out for a reason, not overlooked.

**Relationship traversal.** *Was the sharpest contradiction between this
contract and the existing code, and is now §4.2.* The entry read: the schema
anticipates traversal (`docs/schema/2026-09-18-schema-v1.sql:162` introduces
`entity_descendants()` as "what `unit.descendants` in the IR will call"), but
`snapshot_dataset()` froze `sets`, `parameters` and `parameter_defaults` and
**no relationships** — so a traversal term would have referenced data the
frozen dataset did not contain, and "a run never reads live domain data, it
reads a frozen snapshot" is the reproducibility guarantee the whole RUN half
is built on. Unblocking it meant changing `snapshot_dataset()` and therefore
the dataset hash, which was called a deliberate decision rather than a detail.

It was taken in two steps, as migration `0011`'s docstring set out:
`0011` froze the edges, and `0016` narrowed them to what a model declares. The
guarantee held throughout — §4.2's walk reads the frozen edges and nothing
else. The one thing the original entry got wrong is worth recording: it
assumed traversal would be a term. It is a binding, and that is why the term
algebra did not grow.

**An edge's own data — `valid_from`, `valid_to` and `attrs`.** Migration
`0011` freezes all three when they are set, and §4.2 gives no way to read one.
**Deferred, deliberately, and this is the record of the decision.** A
time-bounded edge ("this reporting line starts in March") is a real need, and
an `fte` on a `works_in` edge is a real coefficient. Two things are missing
before either can be admitted, and neither is small:

- **A model has no notion of "now".** A `valid_from` filter has to be read
  against something, and the only honest candidates are a date on the scenario
  or a date on the run — both of which are new concepts in the RUN half, not
  new syntax here. Picking the wall clock instead would make a run
  irreproducible, which is the one thing traversal was careful not to do.
- **An edge attribute is a second attribute namespace.** `attr` reads an
  attribute of an *entity* bound to an index. An edge is not bound to an
  index; it is the thing a binding travelled along. Reading it needs either a
  way to bind an edge or a term that names the walk that produced a binding,
  and that is a term-algebra change — which §4.2 was specifically shaped to
  avoid needing.

So the data travels, unread, and a later version can use it without a
migration. That is the same position `0011` left traversal in, and it is a
better place to defer from than not freezing it at all.

**Strict inequalities**, for the reason in §3.4.

**Boolean structure inside a model** — indicator constraints, disjunctions,
`all_different`, `no_overlap`, precedence. The roadmap's Phase 2 classifies
"CP / scheduling" by exactly these; none is expressible in v1, so no model can
be classified into that family yet.

**Nested or negated filters**, `or`, and comparing one attribute to another.

**Named subexpressions**, quadratic terms, division, `min`/`max`, absolute
value, conditionals.

**Pareto**. `lex` is the other ordering this version expresses; a frontier of
answers is not one number, and `run.objective` is still one number.

---

## 6. Refusals

One refusal, not all of them, in a documented order, as the platform's standard
list-form 422:

```json
{"detail": [{"type": "value_error",
             "loc": ["body", "ir", "variables", "x", "domain"],
             "msg": "\"real\" is not a variable domain version 1 solves; …",
             "input": "real"}]}
```

`loc` points at the offending element, so a builder can highlight it
(Rulings 19, 30). The reason for one refusal rather than a list is the one
`app/expressions/parse.py` already records: the client validates the same
document against the same contract before sending, so a 422 from the server is
either a hand-written request or a client that has not reloaded the contract,
and naming one thing precisely beats listing several.

The 76 rules are in `contract.json`, each marked `shape` (66 of them: decidable
from the document alone, and both languages decide those) or `domain` (10: needs
the domain's rows, so the server only). The split mirrors `parse.py` /
`compiler.py`. `ir_fixtures.json` carries 12 valid documents and 86 invalid ones
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

**Decided 2026-09-21: the contract admits `continuous` variables and
fractional numbers throughout.** This section used to record the opposite, and
the reasoning that held then is kept below, because the thing that changed was
not the argument — it was one of its premises.

### 7.1 What the refusal actually rested on

The original decision was: *v1 admits `binary` and `integer` and refuses
`continuous` by name*. Three reasons were given, and they are worth re-reading
in order, because only the first was ever load-bearing:

1. **There was no solver.** Admitting a variable domain nothing can run and
   nothing can test would make the contract promise what the platform cannot
   keep — which is precisely the failure Phase 0 exists to end.
2. **A half-continuous model would arrive by accident.** Parameters were `int`,
   but entity attributes were not: `attr_type` has `number`, and the seed's own
   `employee.hourly_rate` is one. If `attr` terms admitted `number` attributes,
   a model could acquire fractional coefficients through the back door while
   its parameters stayed integral, and nobody would have decided that.
3. **The cost was visible and was paid in the demo.** The Workforce objective
   minimises *shifts worked*, not *cost*, because the only cost-bearing datum
   in that domain is a `number`. And `c_max_hours` multiplies by a literal `8`
   because a shift's length lives in `time` attributes.

Reason 1 was a fact about the repository, and it stopped being true: the
platform now has three backends. Reason 2 was never an argument for refusing
continuous — it was an argument for **not admitting it by accident**, which is
a different thing, and it is satisfied by admitting it on purpose. Reason 3 was
a description of the cost, not a defence of it.

So the refusal is lifted, and the back door reason 2 named stays shut in a
better way: a fractional number no longer leaks in unnoticed, it is *detected*
and recorded (§7.3).

### 7.2 The checklist, walked

§7 previously listed what admitting continuous would imply. Each line, against
what now exists:

| what it asked for | where it is |
|---|---|
| a numeric type for `parameter_def.default_value` and `parameter_value.value` | migration `0015`: both are `numeric(15, 6)` |
| `run.objective` widened from `bigint` | `0015`, to `numeric(15, 6)`, along with `constraint_result.total_violation` and `penalty_paid` |
| `number` attributes admitted as coefficients | `arithmeticAttrTypes` is now `["integer", "number"]` |
| `const` admitted as a decimal | `const_not_an_integer` became `const_not_a_number` |
| a decision about how decimals are *stored*, since a float in a hashed document makes the hash depend on a text rendering | taken: see §7.4 |
| a `continuous` domain with bounds, `lower`/`upper` no longer integers | `variableDomains` has it; bounds are numbers, and whole only where the domain is `integer` |
| a solver that can take them | `app/solve/lp.py` — GLOP; `app/solve/highs.py` — HiGHS in a child process when `highspy` is installed; mixed models still have the MILP fallback |
| the honesty rule about local optima | **not yet needed, and not yet written.** It belongs to nonconvexity, and every model this contract expresses is still linear (`mul` admits at most one variable factor). When a quadratic or nonlinear term is admitted, that rule is a precondition, not a follow-up |

### 7.3 Fractional data is classified, not assumed

The subtle half of this change is not the variable domain. It is that
**whether a model is solvable by CP-SAT is no longer decidable from the IR
alone**. A model whose variables are every one of them binary is still out of
CP-SAT's reach if a parameter is `2.5`, and the IR does not contain `2.5` — the
dataset does.

So `app/solve/classify.py` takes the frozen dataset as a second, optional
input, and can add one capability from it: `fractional-data`. It never changes
the model's *class*, which stays a property of the model. The class is the name
a person recognises (`LP`, `IP`, `MILP`); `fractional-data` is finer-grained
than any class name and is what actually keeps an integral-looking model away
from an integer solver.

It names the offending number rather than counting them — "the parameter
demand (2.5)" — because that tells a modeller which number made their model
continuous, where "it has fractional data" sends them looking through all of
them.

### 7.4 How a decimal is stored, and why the hash is safe

`numeric(15, 6)`, and the bridge to JSON is a **number**, not a string.

The two obvious alternatives are each wrong on their own. Pydantic's default
sends a `Decimal` as a string (`"0.000000"`): lossless, and it silently
changes the wire contract for every existing client — a field that was `0`
becomes `"0.000000"`, and arithmetic on it in a browser becomes string
concatenation. A bare `float` has the right JSON shape and loses precision on a
wide value.

Fifteen significant digits is what an IEEE-754 double round-trips without loss,
which is why the column is sized `numeric(15, 6)`: **the bridge is lossless
because the column was sized for it.** `app/api/quantity.py` holds that type,
and an out-of-range value is a 422 naming the field rather than SQLSTATE 22003
arriving as a 500.

The hash concern the old checklist raised is real and is answered by the same
choice. A value entering the platform is parsed through its own shortest
round-tripping text, never from a float directly — `Decimal(0.1)` faithfully
preserves binary floating point's error to fifty digits, `Decimal("0.1")` does
not. And a whole value is emitted whole (`trim_scale` in `snapshot_dataset()`,
`as_json_number` on the wire), so a model that never uses a decimal produces
byte-for-byte the document it produced before `0015`, and hashes to the same
thing. **No existing dataset or version hash moved.**

### 7.5 What this still does not admit

Admitting continuous variables does not admit nonlinearity. `mul` still refuses
a product of two variables, so every model here is linear, and the classifier
returns `LP`, `IP` or `MILP` and nothing else. QP, NLP and MINLP need new term
forms, and with them the local-optimum honesty rule from §7.2's last row.

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
| parameter values and defaults are numbers | spec §2 said `int`, "deliberate for CP-SAT", and that is what this row recorded. Migration **0015** made both `numeric(15, 6)`, so the evidence moved and this row moved with it (§7) |
| an absent cell means the parameter's default | migration `0009`'s `parameter_defaults` |
| entity attributes are readable from the frozen dataset | `snapshot_dataset()` emits `{"id": key} \|\| attrs` |
| constraints have string ids, unique per model | `scenario.patch`; `constraint_result` PK `(run_id, constraint_id)` |
| constraints are hard or soft, soft ones carry an integer penalty | `constraint_result.hard boolean`, `penalty_paid`; `patch.soften: {id: weight}`. The *penalty paid* is numeric since `0015`; the *weight a modeller writes* stayed an integer by decision (§3.5) |
| one objective, one number | `run.objective`, `bigint` when this was written and `numeric(15, 6)` since `0015` — which is where "one *integral* number" came from |
| `version` from the first document; one shared JSON artefact; a parity test; `loc`-shaped refusals | the expression core (Ruling 37, Rulings 19/30) |
| the frozen edges a walk reads, keyed by type name and by entity key | `snapshot_dataset()` as amended by **0011** and **0016**. This row used to read "traversal cannot be expressed in this version", which followed from the function freezing no relationships; both steps of `docs/plans/2026-09-20-traversal-decision.md` are now done and §4.2 is the result |
| a relationship's two endpoint entity types | `relationship_type.from_type_id` / `to_type_id` — which is what makes a `via`'s ends checkable at all |

**Invented** — decided here, and a later reader may reopen any of them:

- the term algebra: seven kinds, `forall`/`over` bindings, named indices;
- `{"index": …, "domain": …}` on a variable, and the three admitted domains;
- the parameter index *order* check against the domain;
- `left`/`relation`/`right` mandatory on every constraint (§8);
- objective terms carrying their own expressions;
- the linearity rule on `mul`;
- admitting fractional arithmetic, and detecting it from the dataset rather
  than assuming it from the model (§7) — this replaced the original
  integer-only rule, which was itself invented here;
- keeping objective and penalty **weights** integral while everything else
  became numeric (§3.5);
- the flat `where` filter, and narrowing the catalogue's operators for it;
- traversal as a **binding** rather than an eighth term kind; naming the
  anchor's end rather than a direction; the three depths, and `any_or_self`
  being distinct from `any` (§4.2);
- `relationships` being declared by the model and followed by the snapshot,
  rather than the snapshot carrying the domain's whole list (§3.1.1);
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

### 10.1 Widening, and why §7 did not bump the version

Rule 5 is stated in one direction on purpose, and §7 is the first change to
test it. **A change that only makes the platform accept more is an edit, not a
new version.**

Admitting `continuous`, admitting `number` attributes as coefficients and
admitting a fractional `const` all widen a vocabulary. Every document version 1
accepted before §7 is still accepted, still means the same thing, and still
hashes to the same bytes. There is nothing for a reader of an old document to
get wrong, which is the only thing the `version` field exists to prevent.

The test to apply, in this order:

1. **Would any document the previous version accepted now be refused?** If yes,
   it is a new version. No exceptions — this is rule 5.
2. **Would any document the previous version accepted now mean something
   different, or hash differently?** If yes, it is a new version, and this one
   is easier to miss than the first. §7 passes it only because `trim_scale`
   and `as_json_number` keep a whole number whole; had `3` started serialising
   as `3.000000`, every stored hash would have moved and the widening would
   have been a version bump whether or not any rule changed.
3. Otherwise it is a widening: edit in place, and record it in the section
   that owns the decision.

**Renaming a refusal `code` is a widening too**, awkward as that sounds.
`const_not_an_integer` became `const_not_a_number` in §7. Codes are not part of
a stored document — they appear only in a 422 about a document being submitted
*now*, against the contract as it stands now. Nothing immutable references one.

What this does **not** license: removing a domain, narrowing a limit, adding a
required key, or making an optional key mean something new. Each of those
refuses something that used to pass, and each is rule 5.
