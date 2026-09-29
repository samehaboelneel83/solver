# Nested blocks: a typed, hierarchical way to build and read an optimization model

**Status:** the Boxes and Sentence views (§14) are built
(`frontend/src/model/NestedBlocks.tsx`, `blockCheck.ts`, `ruleSentence.ts`).
Units checking (§8), the logical layer (§5.4) and natural-language extraction
(§11) are **proposed**, and are marked as such wherever they appear.
Everything else describes how this repository already works, and names the
file that does it.

**Why this exists.** People who are not modellers found the two ways a rule
was shown, an equation line and a drill-down diagram, hard to follow. This
document answers the design brief ("a visual system that converts a
natural-language problem into a structured mathematical model, as nested
typed rectangles") against this codebase. It adds two simpler views beside
the existing two without removing either.

---

## 0. Summary of the recommendation

1. **The source of truth is one canonical, versioned JSON document: the
   problem IR** (`docs/contracts/problem-ir.md`, `backend/app/ir/contract.json`).
   Every view, whether sentence, boxes, diagram, equation, Blockly blocks,
   graph or raw JSON, is a projection of it and edits it. None of them is
   stored.
2. **The expression tree is the IR's `Term` union** (`frontend/src/model/terms.ts`,
   `backend/app/ir/models.py`). The IR is already an AST: every node has one
   semantic type, fixed children, and a validator.
3. **Validation is deterministic and layered.** The server's contract check
   (`backend/app/ir/validate.py`) is the only judge; the browser mirrors its
   shape rules (`frontend/src/ir/validate.ts`, pinned by `parity.test.ts`).
   The per-box checker (`blockCheck.ts`) is an early, local reading that
   explains problems in place. It never accepts what the server refuses.
4. **Natural language never produces an equation.** It may only propose
   *edits to the canonical model*. Each proposal is validated like a human
   edit, shown as a diff, and accepted or rejected by a person (§11).
5. **The UX is a hybrid.** Nested boxes are for one rule or goal, a graph is
   for how the model's parts connect, and a list or outline is for scale. A
   plain-language sentence is always one click away (§14).

---

## 1. Conceptual architecture

```
 Natural language ──► Semantic extraction ──► Proposed edits ─┐     (proposed, §11)
                                                              ▼
 Person ─────────────► Views (sentence · boxes · diagram ·  edits ──► Canonical model (IR, JSON)
                       equation · blocks · graph · form)               │  draft, revisioned
                                                                       ▼
                                             Validation engine (contract check, levels 1–7)
                                                                       │  refused ⇢ explained
                                                                       ▼
                                             Publish ──► immutable model_version (hash)
                                                                       ▼
                                             Compiler ──► Compiled (linear/quadratic rows)
                                                                       ▼
                                             Classifier ──► solver choice ──► adapter
                                                                       ▼
                                             Solve ──► verify against the IR ──► result
                                                                       ▼
                                             Explanation (sentence, review, why-not)
```

| stage | where it is |
|---|---|
| canonical model, contract | `docs/contracts/problem-ir.md`, `backend/app/ir/contract.json`, `backend/app/ir/models.py` |
| validation (server, the judge) | `backend/app/ir/validate.py` (`check_shape`, `check_against_domain`) |
| validation (browser, shape rules) | `frontend/src/ir/validate.ts`, pinned by `frontend/src/ir/parity.test.ts` |
| per-box explanation | `frontend/src/model/blockCheck.ts` |
| drafts, revisions, publish | `backend/app/api/drafts.py`, `frontend/src/model/draftStore.ts` |
| compiler | `backend/app/solve/compile.py` (`Compiled`, `Linear`, `Constraint`) |
| classification, solver choice | `backend/app/solve/classify.py`, `backend/app/solve/backends.py` |
| solver adapters | `backend/app/solve/{highs,cpsat,scip,ipopt,benders,…}.py` |
| answer verification | `backend/app/solve/verify.py` |
| model → equation, and back | `frontend/src/model/formula.ts` |
| model → sentence | `frontend/src/model/ruleSentence.ts` |

The key property is that **every arrow out of the canonical model is a pure
function of it**. The same model always compiles, prints and reads the same
way. The only arrows *into* it are edits, and every edit passes the same
validator.

---

## 2. The node and type system

### 2.1 Semantic types (what the brief calls node types)

The brief's list maps onto the IR as follows. "Proposed" means not in the
contract today. The mapping column says how it would enter without breaking
the rule that version 1 documents stay valid.

| brief | IR today | notes |
|---|---|---|
| CONSTANT | `{"const": n}` | finite number |
| PARAMETER | `{"par": name, "index": [...]}` | input data, declared in `parameters`, values frozen per run |
| DECISION_VARIABLE | `{"var": name, "index": [...]}` | declared in `variables` with `domain` and bounds |
| VARIABLE (bound index) | a string in an `index` list | `p` in `hours[p]`; must be bound by `forall` or a `sum` |
| COEFFICIENT | `{"mul": [{"const": c}, term]}` | a coefficient is a role, not a type: the constant factor of a product |
| ADD / SUBTRACT | `{"add": [...]}`, subtraction as `mul[-1, t]` | one n-ary add keeps the tree canonical |
| MULTIPLY | `{"mul": [a, b]}` | at most degree 2 in a rule or weighted goal |
| DIVIDE, POWER | proposed | division by a constant is `mul` by its reciprocal; by a decision it is nonlinear, entering as a catalogue function (§2.4) |
| SUM (aggregation) | `{"sum": term, "over": [binding…]}` | a binding is `{index, set, where?, via?}` |
| PRODUCT (aggregation) | proposed | only a log-sum reformulation keeps it tractable; enter as a function |
| FUNCTION | `{"fn": "log" \| "exp" \| "sqrt" \| "abs" …, "of": term}` | catalogue in `contract.json` with convexity, monotonicity, domain |
| piecewise | `{"pwl": {var…}, "points": [[x, y]…]}` | |
| prediction | `{"predict": name, "of": [term…]}` | trained tree ensemble, declared in `predictors` |
| attribute | `{"attr": {"of": i, "name": a}}` | a number stored on an item of a set |
| COMPARISON (≤, =, ≥) | a constraint's `left`, `relation`, `right` | strict `<`, `>` are refused on purpose: solvers cannot honour them |
| CONSTRAINT / RULE | an entry of `constraints` | `forall`, `severity` hard/soft, `weight`, `when`, `chance` |
| IF / THEN | `when: {var, index, is}` on a rule | the rule holds while a yes/no decision has a value |
| ELSE | a second rule with `when.is` negated | |
| AND, OR, NOT | proposed, §5.4 | a logical layer that lowers to rules and indicator variables |
| OBJECTIVE | `objective: {sense, mode, terms: [{id, weight, expression}]}` | weighted or lexicographic |
| SET | an entry of `sets` (an entity type name) | its members are the domain's records |
| DOMAIN | `variables[v].domain` + `lower`/`upper` | binary, integer, continuous, interval |
| UNITS | proposed, §8 | `parameter_def.unit` exists in the database, unchecked today |

### 2.2 The properties each node has

The brief asks for id, type, operator, value, children, parent, data type,
domain, units, semantic role, validation status, errors and metadata. Some of
these are **stored** in the canonical model, and some are **derived** by
whoever needs them.

* **Stored.** Type (the node's key: `var`, `sum`, …), operator (`relation`,
  `fn`), value (`const`), children (`add`, `mul`, `sum`, `of`, `over`), and
  metadata that means something (`note`, `id` on rules and goal terms).
* **Derived, never stored.** Parent, path, validation status and errors,
  semantic role, degree (0 constant, 1 linear, 2 quadratic, `degree()` in
  `terms.ts`), data type, and (proposed) unit.

Keeping derived facts out of the stored model is deliberate. A stored
"status: valid" can go stale, and two copies of the truth disagree. The
tree's structure *is* its identity: a node is addressed by its **path**
(`constraints/2/left/add/1/mul/0`), the same `loc` the server's refusals
carry. That is what lets a server error point at the exact box.

Rules and goal terms carry a stable `id` because people refer to them by
name. Inner nodes do not need one; if collaborative editing later needs
stable node ids (so that two people's edits merge), add an optional `nid`
that validators ignore.

### 2.3 The type rules (what may go where)

Every numeric slot takes any **numeric expression**. That is the whole
compatibility rule for arithmetic, and it is why the boxes' "Change…" menu
offers exactly the numeric node types (`ChangeMenu` in `NestedBlocks.tsx`).
The other rules are:

| node | children | rule |
|---|---|---|
| `const` | none | finite number |
| `var` | index cells | declared; not an `interval` (a time span is not a number); arity equals its declared index; each cell a name bound here |
| `par` | index cells | declared; arity; cells bound (a cell may itself be a parameter read, `next_day[d]`) |
| `attr` | none | `of` is bound here; `name` is an `integer`/`number` attribute of that set |
| `add` | ≥ 2 numeric | |
| `mul` | exactly 2 numeric | degree of the product ≤ 2 |
| `sum` | 1 numeric + ≥ 1 binding | each binding's set declared; each index name new in scope; the body sees the new names |
| `fn` | 1 numeric | name in the catalogue; the argument's domain respects the function's (`log` needs positive) |
| `predict` | n numeric | declared predictor; n equals its input count |
| comparison | 2 numeric + relation | relation ∈ {≤, =, ≥}; at least one side reads a decision (otherwise nothing the solver does can keep or break it) |
| rule | forall bindings + comparison, or a special body (scheduling, connected, route) | `when` only on a hard rule; `chance` only without `when`; a soft rule has a positive integer weight |
| goal | weighted terms | each term numeric and reads a decision; degree ≤ 2 in a weighted goal |
| model | sets, parameters, variables, constraints, objective | names unique; every name used is declared; version 1 or 2 |

Logical nodes (proposed, §5.4) would add a second slot type, **condition**.
A condition slot takes a comparison, AND/OR/NOT, or a yes/no decision. A
numeric slot never takes a condition, and a condition slot never takes a
number. This is the "logical operators should not accept arbitrary numeric
expressions" requirement, enforced by the slot type rather than by a later
check.

---

## 3. The JSON schema of the canonical representation

The authoritative schema is `backend/app/ir/contract.json` plus the Pydantic
models in `backend/app/ir/models.py`. Abridged, in the form a reader can
hold in their head:

```jsonc
{
  "version": 2,
  "sets": ["employee", "day"],                        // entity type names
  "parameters": { "demand": { "index": ["day"] } },   // data; values frozen per run
  "predictors": { "demand_model": { "inputs": 2 } },  // optional, v2
  "variables": {
    "assign":   { "index": ["employee", "day"], "domain": "binary" },
    "overtime": { "index": ["employee"], "domain": "continuous", "lower": 0, "upper": 20 }
  },
  "constraints": [
    {
      "id": "c_cover", "note": "each day is staffed",
      "forall": [{ "index": "d", "set": "day" }],
      "left":  { "sum": { "var": "assign", "index": ["e", "d"] },
                 "over": [{ "index": "e", "set": "employee",
                            "where": [{ "attr": "team", "op": "=", "value": "north" }] }] },
      "relation": ">=",
      "right": { "par": "demand", "index": ["d"] },
      "severity": "hard"                               // or "soft" with "weight"
      // "when":   { "var": "open", "index": [], "is": 1 }   (v2, conditional)
      // "chance": { "epsilon": 0.1 }                       (v2, stochastic)
    }
  ],
  "objective": {
    "sense": "minimize", "mode": "weighted",           // or "lex"
    "terms": [{ "id": "o_overtime", "weight": 1,
                "expression": { "sum": { "mul": [{ "const": 30 }, { "var": "overtime", "index": ["e"] }] },
                                "over": [{ "index": "e", "set": "employee" }] } }]
  }
}
```

The brief also asks the model to hold relationships, units and dependencies:

* **Relationships** are declared when a binding walks one
  (`via: {rel, from|to, depth}`). The editor offers only relationship types
  whose two ends are sets of this model.
* **Dependencies** are derived: which rules and goals read which decisions
  and data. The Visual Graph draws them (`frontend/src/lib/modelGraph.ts`)
  and the Review tab lists them. Storing them would duplicate the tree.
* **Units** are proposed; see §8.

---

## 4. The AST model

The IR *is* the AST, with one simplification that matters: **each node has
exactly one JSON key that says what it is**. `termKind()` in `terms.ts` reads
it, so a visitor is a single switch. Three consequences follow:

* **Canonical form.** Subtraction is `add` with a `mul[-1, x]` term.
  Addition is n-ary and never nested `add` in `add` unless the author put it
  there. So one meaning has one tree, and `parse(print(tree)) == tree`
  (`formula.ts` offers an equation line only when this round-trip holds,
  key-order-insensitive; `formula.test.ts` proves it over every template in
  `backend/tests/template_irs.json`).
* **Scope is structural.** A name bound by `forall` or a `sum`'s `over` is
  visible exactly inside that node. The checker and the parser carry a
  scope stack (`Parser.scope` in `formula.ts`, `bound` in `blockCheck.ts`,
  `check_term(… scope …)` in `validate.py`).
* **Edits are path rewrites.** Every box hands its children a "replace me"
  callback, so an edit deep in the tree rebuilds only the path above it
  (`TermBlock` in `NestedBlocks.tsx`, `PartBox` in `EquationDiagram.tsx`).
  The rest of the tree is shared, which is what makes undo cheap (§17).

---

## 5. The rectangle (container) model

### 5.1 One box per node

A box is the visual form of exactly one AST node. It has:

* a **header**: its kind in plain words (Decision, Data, Number, Add up,
  Multiply, Total, Function, Prediction, Compare, For each, Rule), its place
  in the parent ("left side", "term 2", "what is totalled"), a quiet problem
  marker, and a **Change…** menu;
* a **body**: the node's own fields (a name to choose, a number to type, a
  relation) and its **children as boxes inside it**.

### 5.2 Colour and shape by role

The same meaning always has the same colour. Containers are drawn with a
coloured border only, and leaves with a light fill, so nesting never stacks
fills into mud (dark mode included):

| role | colour | nodes |
|---|---|---|
| decision (what the solver chooses) | sky, filled | `var` |
| data (what is known) | emerald, filled | `par`, `attr` |
| number | neutral, filled | `const` |
| operation | violet border | `add`, `mul`, `fn`, `predict`, `pwl` |
| total over a set | indigo border | `sum` |
| comparison | amber border | a rule's left, relation and right |
| scope | teal border | `forall` ("For each") |
| rule, goal | neutral border | the root |
| problem | rose border and message | any node with its own problem |

Colour is never the only signal: every box also names its kind in words
(WCAG 1.4.1).

### 5.3 Parent–child compatibility

A box offers only what keeps the tree well formed:

* **Replace it with…** lists only the numeric kinds that are possible *here*.
  "Data of an item" appears only when a set with numeric attributes is bound
  around the box, "a total over a set" only when the model has sets, and "a
  trained model's prediction" only when the problem declares one.
* **Put it inside…** wraps the box: "… plus something", "… times something",
  "minus …", "a total of it over a set". This is how a person grows an
  expression without first deleting what is there.
* **Index pickers** list only the names bound around the box, with their
  set (`d (day)`).
* **Relations** are a three-way choice in words ("is at most", "is exactly",
  "is at least").

Anything the menus cannot produce, such as a strict inequality or an index
that is not in scope, simply has no control. The one thing a person can
still get wrong by hand is renaming a letter, and the checker catches that
at once (§6).

### 5.4 Logical layer (proposed)

Today a condition is `when` (a rule holds while a yes/no decision has a
value). General AND/OR/NOT/IF-THEN-ELSE would enter as a **condition** slot
type (§2.3) with nodes:

```jsonc
{ "and": [cond, cond, …] } | { "or": [cond, …] } | { "not": cond }
| { "is": {"var": "open_a", "index": []}, "value": 1 }     // yes/no decision
| { "holds": { "left": term, "relation": "<=", "right": term } }
```

and a rule form `{ "if": cond, "then": [rule…], "else": [rule…] }`. The
compiler would **lower** these deterministically to the constructs solvers
already take: indicator (`when`) rules, helper binaries with big-M from
declared bounds, and the standard linearizations of AND/OR over binaries.
The solver-facing contract stays small, and the logic stays readable in the
model. A condition whose lowering needs a bound the model does not declare is
refused, and the refusal names the bound that is missing.

---

## 6. The hierarchical validation engine

Validation runs bottom-up over the tree, in the brief's seven levels. Each
level only looks at its own node, assuming its children have already
reported:

| level | checks | examples of what it says |
|---|---|---|
| 1 primitive | a number is finite; a decision or data item exists, has the right number of indices, each index bound here; an attribute is a number of the bound item | "“q” is not bound here: add it to a “for each” or to a total" |
| 2 operation | `add` has ≥ 2 parts; `mul` degree ≤ 2; function known; prediction's inputs | "this multiplies more than two decisions together, which no solver here takes" |
| 3 aggregation / expression | a total runs over at least one declared set; its letters are new | "“d” already names something here; pick another letter" |
| 4 comparison / logic | relation allowed; at least one side reads a decision; (proposed) units agree; conditions are conditions | "neither side reads a decision, so nothing the solver chooses can keep or break this rule" |
| 5 rule | `forall` sets declared and letters distinct; `when` only on hard rules; `chance` placement; soft weight | contract codes `when_on_soft`, `chance_misplaced` |
| 6 objective | each term reads a decision; weighted goals linear or quadratic; lexicographic terms ordered | "the goal reads no decision, so no plan can make it better or worse" |
| 7 model | names unique and declared; sets exist in the domain; data present; the model's class is solvable here | server `check_against_domain`, then the classifier's "would solve with …" |

Levels 1–6 run in the browser on every edit (`blockCheck.ts`, and the shape
rules in `frontend/src/ir/validate.ts`). Level 7 needs the domain, so the
server runs it: the editor asks it on a debounce (`useDraftRefusal`) and
always at Publish.

**Determinism.** The checks are pure functions of the IR (and, at level 7,
of the domain's schema). No model call, no randomness, no clock. The same
tree always gives the same problems, in the same order.

---

## 7. Error propagation

A problem belongs to the **deepest node that has it**, and is reported with
its **path**. Each ancestor then derives two numbers, "own problems" and
"problems inside" (`problemsAt()` in `blockCheck.ts`), and shows:

* **own problems**: a rose border and the message, in the box;
* **problems inside**: a quiet "1 problem inside" in the header, with no
  red, so the path to the problem is visible from the top without the
  message being repeated at every level;
* **at the root**: a list, "2 things to fix", each item a path and a
  message: `left side › term 2 › factor 2: “x” is not bound here…`.

A parent is marked **partially valid**, not invalid, when only a child is
wrong. The model stays editable, the draft keeps saving, and only Publish is
held back. This matches how the server works: it refuses a *publication*,
never an *edit*.

---

## 8. Units and dimensional consistency (proposed)

The database already stores `parameter_def.unit` (for example "hours", "kg",
"EUR/h"). The proposal:

1. Declare a unit on each parameter, decision and attribute (optional;
   absent means "not checked", never "dimensionless").
2. Parse units into a vector of base dimensions with a scale
   (`EUR/h = money¹ · time⁻¹`); a small table covers money, time, mass,
   length, count and the common scales.
3. Infer bottom-up: `add` and comparison sides must have equal dimensions
   (and scales, or the checker proposes the conversion factor); `mul` adds
   exponents; `sum` keeps its body's unit; `fn` needs a dimensionless
   argument (`log(kg)` is refused); a constant takes the unit its sibling
   requires.
4. Report at level 4, with the path: "left side is in hours, right side is in
   minutes: multiply one by 60, or change a unit."

This is a check, not a transformation. The model is never silently
rescaled.

---

## 9. Variable and domain validation

* Every decision has a `domain` (binary, integer, continuous, interval) and,
  for numbers, bounds. The contract refuses a decision without one.
* A **decision** (`variables`) and **data** (`parameters`) are different
  keys in the IR and different colours in the boxes. The solver chooses one
  and is given the other. A term cannot mistake one for the other because
  the node type says which it is.
* A missing upper bound is allowed and made visible: the compiler stands in
  a guard, and an answer resting on that guard is reported as "the goal can
  improve without limit", not as an optimum (`default_upper` in
  `compile.py`).
* Level 7 checks the data exists: the frozen dataset has the parameter's
  values, or its default applies.

## 10. Objective, constraint and logical-rule validation

* **Objective**: sense is `minimize` or `maximize`; weights positive; every
  term reads a decision; `lex` terms are solved in order and each later term
  holds the earlier ones at their optimum; a weighted goal's degree is at
  most 2 (the solver classes that take quadratic goals are declared per
  backend).
* **Constraint**: a comparison of two numeric expressions, or a special body
  (scheduling, connected, route) validated by its own rules. Strict
  inequalities are refused; an equality between two continuous
  nonlinear sides is allowed but classified as nonconvex, and the classifier
  says so.
* **Logical rules** (proposed §5.4): conditions only in condition slots;
  every decision a condition reads is binary; every comparison inside a
  condition has declared bounds on both sides, so its lowering has a big-M.

---

## 11. Natural language → structured model (proposed)

**Principle:** language is an *input method for edits*, never a source of
truth, and never a generator of equations.

```
text ─► extraction (LLM, constrained) ─► a list of typed edit proposals
         │                               e.g. add_set("warehouse"),
         │                               add_decision("open", index=[warehouse], domain=binary),
         │                               add_rule(id, forall, left, relation, right)  ← as IR trees
         ▼
     each proposal: JSON-schema-validated → applied to a copy of the draft →
     levels 1–7 → shown as a diff in the Sentence and Boxes views →
     person accepts / edits / rejects each one
```

1. **Constrained output.** The extractor must answer in the edit schema:
   the IR's own JSON schema, restricted to additions and changes. Free text
   is never parsed as a formula.
2. **Grounding.** The extractor is given the domain's catalogue: the set,
   attribute, parameter and decision names that already exist. It must use
   those names, or propose new ones explicitly (`add_parameter`).
3. **Every proposal is validated like a human edit.** A proposal that fails
   level 1–6 is not shown as a formula. It is shown as a question (§12).
4. **Nothing is applied silently.** Proposals appear as a reviewable diff,
   each read back in plain words (§13) so the person checks the *meaning*,
   not the syntax.
5. **Provenance.** Accepted edits record that they came from text, and the
   sentence they came from, in the draft's history (§17).

## 12. Ambiguity and clarification

The extractor must return **explicit uncertainty** rather than a guess. Each
proposal carries the spans it came from, plus zero or more *open questions*
of a fixed set of kinds:

| kind | example |
|---|---|
| which set | "“per shift” — is a shift one of your *shift* records, or a time slot?" |
| which direction | "“at least 3 staff” — at least 3 in total, or at least 3 per day?" |
| hard or preferred | "Must this always hold, or is it a preference that may bend at a cost?" |
| missing data | "“capacity” is used but no data called capacity exists: add it, or pick an existing one" |
| missing bound | "How large can *overtime* get? A bound is needed to solve this." |
| goal | "Two things could be minimised (cost, overtime): which first, or how do they trade off?" |

The UI asks these one at a time, with the likely answers as buttons (from the
catalogue) and a free-text escape. It asks only what the validator needs:
if the model already validates, no question is asked. The level-7 validator
then decides whether the answers are enough.

## 13. Contradictions and redundancy

* **Contradictory rules** are found by solving, not by guessing. When a model
  has no answer, the platform already finds a *minimal* set of rules that
  cannot hold together (QuickXplain over the rules; `app/solve/whynot.py`,
  the run page's "Why there is no answer") and offers to soften one
  (make it preferred with a weight).
* **Before solving**, cheap checks catch the obvious cases: two rules with
  the same left side and incompatible constant right sides; a rule whose
  bounds the declared variable bounds already make impossible; an empty set
  after a filter (the classifier's `empty_ranges`).
* **Redundancy** (a rule implied by others or by bounds) is reported as a
  hint, never an error. Presolve detects it per instance, and the Review tab
  can list "never binding in the last N runs" from recorded slacks.

## 14. Explaining errors in plain language

Every message follows one pattern: **where** (the path in box names),
**what** (in the user's vocabulary, never the node type), and **how to fix
it** (an action the UI can do):

> left side › term 2 › factor 2: “x” is not bound here: add it to a “for
> each” or to a total.

The server's refusals are written the same way (they carry a `loc`, which the
editor maps to the box), and `formula.ts` suggests the nearest name for a
typo ("did you mean “hours”?").

---

## 15. Model → equation, → sentence, → solver

* **Equation.** `printRule`/`printTerm` in `formula.ts`: one line per rule,
  `for each d in day: sum(assign[e, d] for e in employee) >= demand[d]`.
  Offered only when it reads back to the same tree.
* **Sentence.** `ruleSentence`/`termSentence` in `ruleSentence.ts`: "For
  every day d, the total of assign of e, d, over every employee e, must be
  at least demand of d." Deterministic, and never guessed.
* **Solver.** `compile.py` expands `forall` and `sum` against the frozen
  dataset into rows of `Linear` forms (plus quadratic parts, indicator
  switches, piecewise and function definitions). `classify.py` names the
  model's class (LP, MILP, MIQP, NLP, CP…) and what it needs.
  `backends.py` picks a solver that provides it, and says why. Each adapter
  translates `Compiled` into its solver's API. `verify.py` then checks the
  answer against the *IR*, not the solver's model, so an adapter bug cannot
  pass as an answer. The IR never mentions a solver: that is **solver
  independence**.

## 16. Bidirectional synchronisation

There is one state, the draft IR, and every view renders it and writes to
it. There is no view-to-view sync:

* **Structured views** (sentence, boxes, diagram, form, Blockly, graph)
  write the node they show, immediately.
* **The equation line** is text, so it is *parsed on every keystroke* and
  shows the error in place, but writes only on Enter or blur, and only a
  text that parses cleanly (`EquationField.tsx`). Until then the model keeps
  its last good tree, so a half-typed equation never corrupts it.
* **Views that cannot show a node** say so and step aside. A rule with a
  scheduling body has no equation line, and the page says why rather than
  showing a lossy one. The Boxes view shows every arithmetic rule, including
  ones the equation line cannot write yet.
* **Round-trip tests** pin it: every template's rules print and parse back
  to the same tree (`formula.test.ts`); Blockly converts to IR and back
  (`lib/irBlocks/roundTrip.test.ts`).

## 17. Undo/redo and versioning

* **Draft history.** Every edit is a new immutable IR value (path
  rewrites share the rest of the tree). The draft store keeps the
  sequence, and **Undo edit / Redo** replay it (`DraftBar.tsx`,
  `draftStore.ts`). Presentation, such as card positions and which view is
  open, is kept apart and never enters undo.
* **Server draft.** `PUT /problems/{id}/draft` with `expected_revision`: a
  save built on a stale read is refused (409), so two tabs cannot overwrite
  each other (`drafts.py`).
* **Versions.** Publish validates the locked revision and writes an
  **immutable** `model_version` with its hash. Publishing is idempotent with
  an `Idempotency-Key`. Every run records the exact version and frozen
  dataset it solved, so any result can be traced to the model that produced
  it.

## 18. Serialization and persistence

The IR is plain JSON with a declared `version`. Version 1 documents are valid
version 2 documents; `upgrade_v1` only restamps. Documents are stored as
`jsonb`, hashed canonically, and never contain view state. Trained models
(`predictors`) are stored as `tree-ensemble/1` JSON, never pickles, because
a model is data, not code.

## 19. Extensibility: adding an operator

Adding a node kind is a checklist, and each step has a test that fails until
it is done:

1. `contract.json` + `docs/contracts/problem-ir.md` (and fixtures for
   accepted and refused forms);
2. `models.py` and `validate.py` (server), and `frontend/src/ir/validate.ts`,
   kept in step by `parity.test.ts`;
3. `terms.ts` (`Term` union, `termKind`, `degree`, `emptyTerm`) →
   `blockCheck.ts` (its level), `ruleSentence.ts` (its words), `formula.ts`
   (print and parse, or declare it unprintable), `NestedBlocks.tsx` (its
   box), `EquationDiagram.tsx`;
4. `compile.py` (how it lowers), `classify.py` (what it needs), and each
   backend's declared capabilities;
5. `verify.py` (how an answer is checked against it).

The `fn` catalogue shows the cheap path: a new function is one catalogue
entry with its convexity, monotonicity and domain, and every layer reads it
from there.

---

## 20. UX evaluation

**Is the nested-rectangle approach practical?** Yes, for **one rule or one
goal at a time**. That is where it is strongest: the containment *is* the
math (a total contains what it totals; a comparison contains its two
sides). It stops being practical as a picture of a whole model with
hundreds of rules. At that scale nesting hides relationships between rules,
and a graph or an outline is the right tool.

**Is it understandable for non-experts?** More than an equation line, with
three conditions: kinds are named in words (Decision, Data, Total), not in
symbols; every box is one sentence long (a name, "for", its item); and the
plain-language sentence is always one click away. The Sentence view is the
entry point; the boxes are where a person edits.

**Where it becomes confusing:**

* **Depth.** Past about four levels, people lose track of which box they
  are in. Mitigations: the problem path in words, headers naming the box's
  place ("term 2"), and collapsing (the Diagram view already folds; the
  Boxes view could add a per-box fold at depth ≥ 4).
* **Bound letters.** "e", "d" and "for every employee called e" are the
  hardest concept. Mitigation: pickers list only the names in scope, with
  their set, and renaming is the one place errors are expected, so the
  checker is loudest there.
* **Subtraction and coefficients.** `-1 × x` is honest but unfriendly. The
  sentence reads it as "minus x"; the boxes could show a "minus" box for
  `mul[-1, x]` as a further refinement.
* **Width.** Wide sums wrap. On a phone the boxes stack vertically.

**What to show, and what to hide:**

| always visible | behind "More options" / Advanced |
|---|---|
| the sentence; the boxes; problems with their path | the equation line; the raw IR |
| names, numbers, relations, "for each", "total over" | filters' full editor (`where`), walks along relationships (`via`) |
| hard vs preferred and its weight | conditions (`when`), chance, piecewise points |
| | model class, solver choice, compiled row counts |

**Tree, nested rectangles, graph, or hybrid?** A hybrid, chosen by the
question the person is asking:

| question | view |
|---|---|
| "What does this rule say?" | Sentence |
| "Change this part of this rule." | Boxes (nested rectangles) |
| "How is this long expression built?" | Diagram (collapsible tree) |
| "I know the math; let me type it." | Equation |
| "What reads what, across the model?" | Visual Graph (nodes and edges) |
| "Is the whole model sound?" | Review tab (outline with problems) |

**Navigating deep expressions:** a breadcrumb path in every problem message;
fold and unfold (Diagram, with Open all and Close all); the Diagram's ✎ edits
one box as a small equation with the surrounding letters in scope; keyboard
order follows the tree.

**Drag and drop.** Offer it where it is a real gain, which is reordering
terms and moving a part into a "total" or a "times", and always with a
keyboard and menu equivalent ("Put it inside…"). Blockly (the Blocks tab) is
the drag-first editor for people who prefer it. The Boxes view is
menu-first, because drag and drop is the least accessible and least precise
way to edit a small tree.

**Creating a child:** from the parent ("+ add a term", "+ another set") or
by wrapping the child ("Put it inside…"). A new node is created *filled in*
from context (`emptyTerm`), never as an empty shell.

**Preventing incompatible children:** by construction. A menu lists only the
kinds that fit the slot, and the scope and the model's declarations decide
the rest (§5.3). There is no "invalid drop" state to recover from.

**Distinguishing the kinds:** colour *and* a word label per role (§5.2);
decisions and data never share a colour; comparison and scope have their own
frames, and so does the rule itself.

**Showing validation without overwhelming:** nothing when it is right except
one quiet "✓ Complete" line; a rose border and one sentence only on the box
that is wrong; a neutral count on its ancestors; one list at the top. No
red on a parent whose only fault is a child's.

## 21. Scaling from one line to hundreds of rules

* **Small** ("maximize profit = revenue − cost"): one goal in the Sentence
  view; the boxes show `Add up [revenue] [minus cost]`.
* **Medium**: rules grouped in cards with names and "what it means"; the
  page-wide switch sets every card's view; one card can differ.
* **Large**: the IR stays *indexed*, with one rule over `forall` rather than
  hundreds of copies, so hundreds of variables are a handful of declared
  decisions. The outline and search list rules; the graph shows
  dependencies; the Review tab lists problems model-wide. Only the rule
  being edited is drawn as boxes.
* **Nonlinear, piecewise, predictions**: first-class boxes (Function, Curve,
  Prediction), with their special parameters under "More options".

---

## 22. Three worked examples

Each example shows the natural language, the concepts extracted from it,
the box structure, the canonical JSON, the equation, the validation
process, and what the solver receives.

### Example 1: simple (maximize profit)

**Natural language.** "We make chairs and tables. A chair sells for 45 and
costs 20 to make; a table sells for 120 and costs 70. We have 300 hours; a
chair takes 2 hours and a table 5. Maximize profit."

**Extracted concepts.**

| concept | kind |
|---|---|
| product: chair, table | set (`product`), records with attributes |
| price, unit cost, hours per unit | data (`attr` on product) |
| available hours = 300 | a number in the rule (a parameter always has at least one index, so a single figure is a constant) |
| how many to make | decision `make[product]`, integer, ≥ 0 |
| profit = revenue − cost | goal |
| hours used ≤ 300 | rule |

**Boxes.**

```
GOAL  maximize
┌ Total ─ every product p ───────────────────────────────┐
│ ┌ Multiply ─────────────────────────────────────────┐   │
│ │ ┌ Add up ───────────────────────┐   ┌ Decision ─┐ │   │
│ │ │ [Data price of p] + [minus    │ × │ make for p│ │   │
│ │ │  Data cost of p]              │   └───────────┘ │   │
│ │ └───────────────────────────────┘                  │   │
│ └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘

RULE  c_hours
┌ Compare ────────────────────────────────────────────────────────┐
│ ┌ Total ─ every product p ───────────────┐              ┌Number┐ │
│ │ [Data hours of p] × [Decision make p]  │  is at most  │ 300  │ │
│ └────────────────────────────────────────┘              └──────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**Canonical JSON.**

```json
{
  "version": 2,
  "sets": ["product"],
  "parameters": {},
  "variables": { "make": { "index": ["product"], "domain": "integer", "lower": 0, "upper": 1000 } },
  "constraints": [{
    "id": "c_hours", "severity": "hard",
    "left": { "sum": { "mul": [{ "attr": { "of": "p", "name": "hours_per_unit" } }, { "var": "make", "index": ["p"] }] },
              "over": [{ "index": "p", "set": "product" }] },
    "relation": "<=", "right": { "const": 300 }
  }],
  "objective": { "sense": "maximize", "terms": [{ "id": "o_profit", "weight": 1, "expression":
    { "sum": { "mul": [{ "add": [{ "attr": { "of": "p", "name": "price" } },
                                  { "mul": [{ "const": -1 }, { "attr": { "of": "p", "name": "unit_cost" } }] }] },
                       { "var": "make", "index": ["p"] }] },
      "over": [{ "index": "p", "set": "product" }] } }] }
}
```

**Equation.** maximize `sum((price[p] + -1 * unit_cost[p]) * make[p] for p in product)`
subject to `sum(hours_per_unit[p] * make[p] for p in product) <= 300`.

**Validation.** Level 1: `make` is declared, integer, and has one index
(`p`, bound by the total); the attributes are numbers of `product`. Level
2: each product is degree 1 (data × decision). Level 3: the total runs over
a declared set with a new letter. Level 4: the comparison reads a decision.
Level 6: the goal reads a decision and is linear. Level 7: the domain has
`product` records with those attributes. Result:
✓ Complete.

**Solver.** Compiled against the data (chair: 45, 20, 2; table: 120, 70,
5; hours 300): maximize `25·make_chair + 50·make_table` subject to
`2·make_chair + 5·make_table ≤ 300`, both integer in [0, 1000]. The class is
IP, which goes to CP-SAT or HiGHS. The answer is make_chair = 150,
make_table = 0 (profit 3750), and it is verified against the IR.

### Example 2: medium (staff allocation)

**Natural language.** "Each day needs at least its demand of staff from the
north team. No one may work more than 5 days a week, and overtime costs 30
an hour. Minimize overtime."

**Extracted concepts.** Sets `employee` and `day`; data `demand[day]`; the
number 5 (days a week); attribute `team` on employee (text, for a filter); decisions
`assign[employee, day]` (binary) and `overtime[employee]` (continuous,
0–20); rules "cover each day" and "at most 5 days"; goal "overtime cost".
**Open question** (§12): "overtime is in hours, but assignments count days.
How many hours is a day?" The person answers 8, which becomes the
constant in the rule.

**Boxes** (the cover rule; this is the Boxes screen as built):

```
RULE c_cover                                         ✓ Complete
┌ For each ─ every day called d ─────────────────────────────┐
└────────────────────────────────────────────────────────────┘
┌ Compare ────────────────────────────────────────────────────┐
│ ┌ Total ─ every employee called e, where team = north ┐     │
│ │   ┌ Decision ─ assign for e (employee), d (day) ┐   │ is  │ ┌ Data ─ demand for d ┐
│ │   └──────────────────────────────────────────────┘  │ at  │ └─────────────────────┘
│ └──────────────────────────────────────────────────────┘least│
└─────────────────────────────────────────────────────────────┘
```

**Canonical JSON** (abridged to the two rules and the goal):

```json
{
  "constraints": [
    { "id": "c_cover", "forall": [{ "index": "d", "set": "day" }],
      "left": { "sum": { "var": "assign", "index": ["e", "d"] },
                "over": [{ "index": "e", "set": "employee", "where": [{ "attr": "team", "op": "=", "value": "north" }] }] },
      "relation": ">=", "right": { "par": "demand", "index": ["d"] }, "severity": "hard" },
    { "id": "c_hours", "forall": [{ "index": "e", "set": "employee" }],
      "left": { "add": [{ "mul": [{ "const": 8 }, { "sum": { "var": "assign", "index": ["e", "d"] }, "over": [{ "index": "d", "set": "day" }] }] },
                        { "mul": [{ "const": -1 }, { "var": "overtime", "index": ["e"] }] }] },
      "relation": "<=", "right": { "const": 40 }, "severity": "hard" }
  ],
  "objective": { "sense": "minimize", "terms": [{ "id": "o_overtime", "weight": 1,
    "expression": { "sum": { "mul": [{ "const": 30 }, { "var": "overtime", "index": ["e"] }] }, "over": [{ "index": "e", "set": "employee" }] } }] }
}
```

**Equation.**
`for each d in day: sum(assign[e, d] for e in employee where team = "north") >= demand[d]`
and `for each e in employee: 8 * sum(assign[e, d] for d in day) - overtime[e] <= 40`,
minimize `sum(30 * overtime[e] for e in employee)`.

**Validation, including a mistake.** Suppose a person renames the total's
letter from `e` to `x` in the boxes. Level 1 then reports at the decision
box, "`e` is not bound here". The total and the comparison show "1 problem
inside", the top list reads `left side › what is totalled: “e” is not bound
here…`, and Publish is held until the name is fixed. Level 7 checks that
`team` exists on `employee` and is text, which is what a filter needs.

**Solver.** One cover row per day and one hours row per employee: a MILP
(binary assignments with continuous overtime), sent to HiGHS. With
alternatives asked for, the runs page lists next-best plans that differ in
at least N assignments.

### Example 3: complex (nested logical rules)

**Natural language.** "We may open warehouses A, B and C, at most two. A
warehouse that is open must ship at least 50 and at most its capacity; a
closed one ships nothing. If A opens, B must stay closed, unless demand in
the north exceeds 500, in which case both may open. Minimize fixed plus
shipping cost."

**Extracted concepts.** Set `warehouse`; decisions `open[w]` (binary) and
`ship[w]` (continuous, 0 to capacity); data `capacity` and `fixed_cost`
(attributes), `ship_cost[w]` and `north_demand`; an attribute `exclusive_pair` marking A
and B; rules: a cardinality rule
(at most two), a linking rule (IF open THEN 50 ≤ ship ≤ capacity ELSE ship
= 0), and an exclusion that depends on the data (IF north_demand ≤ 500 THEN
NOT(open_A AND open_B)). **Open question:** "“exceeds 500”: is north demand
fixed data, or does it depend on your decisions?" The person answers that
it is data, so the condition can be decided before solving.

**Boxes, with the proposed logical layer** (§5.4):

```
RULE r_link   (for each warehouse w)
┌ If ─ Decision open for w is yes ───────────────────────────────┐
│ Then ┌ Compare: Decision ship(w) is at least Number 50 ┐        │
│      ┌ Compare: Decision ship(w) is at most Data capacity of w ┐│
│ Else ┌ Compare: Decision ship(w) is exactly Number 0 ┐          │
└────────────────────────────────────────────────────────────────┘

RULE r_exclude
┌ If ─ Data north_demand is at most 500 ─────────────────────────┐
│ Then ┌ Not ┌ And ┌ open for A is yes ┐ ┌ open for B is yes ┐ ┐ ┐│
└────────────────────────────────────────────────────────────────┘
```

**Canonical JSON, as the model stores it today.** The logical layer is
proposed; in the contract as it stands, the same meaning is written with
`when` and linear forms. That is exactly what the logical layer would lower
to:

```json
{
  "constraints": [
    { "id": "c_at_most_two", "left": { "sum": { "var": "open", "index": ["w"] }, "over": [{ "index": "w", "set": "warehouse" }] },
      "relation": "<=", "right": { "const": 2 }, "severity": "hard" },
    { "id": "c_min_ship", "forall": [{ "index": "w", "set": "warehouse" }],
      "left": { "var": "ship", "index": ["w"] }, "relation": ">=", "right": { "const": 50 },
      "when": { "var": "open", "index": ["w"], "is": 1 }, "severity": "hard" },
    { "id": "c_max_ship", "forall": [{ "index": "w", "set": "warehouse" }],
      "left": { "var": "ship", "index": ["w"] }, "relation": "<=",
      "right": { "mul": [{ "attr": { "of": "w", "name": "capacity" } }, { "var": "open", "index": ["w"] }] }, "severity": "hard" },
    { "id": "c_exclude_ab",
      "left": { "sum": { "var": "open", "index": ["w"] },
                "over": [{ "index": "w", "set": "warehouse", "where": [{ "attr": "exclusive_pair", "op": "=", "value": 1 }] }] },
      "relation": "<=", "right": { "const": 1 }, "severity": "hard" }
  ]
}
```

The ELSE branch (`ship = 0` when closed) is `c_max_ship`: capacity × open
is 0 when closed. The data-dependent IF is decided **before** solving,
because north demand is data: the lowering keeps `c_exclude_ab` only when
`north_demand ≤ 500` in the frozen dataset, and records that choice in the
run. An index in the IR is always a bound letter, never a record's key, so
"A and B" is written as a filter: both records carry an attribute
`exclusive_pair = 1`, and the rule totals `open` over the warehouses that have
it. (Writing `open[A]` directly is refused with `index_not_bound`.)

**Equation.** `sum(open[w] for w in warehouse) <= 2`;
`for each w in warehouse: ship[w] >= 50, only while open[w] is yes`;
`for each w in warehouse: ship[w] <= capacity[w] * open[w]`;
`sum(open[w] for w in warehouse where exclusive_pair = 1) <= 1`.

**Validation.** Level 4 (logical, proposed): the IF's condition is a
comparison of data with a number, so it is decidable before solving; NOT
and AND take conditions only; `open` is binary, so it may stand as a
condition. Level 5: `when` sits on a hard rule, as the contract requires.
`c_max_ship` is data × decision, which is linear. Level 6: the goal
`sum(fixed_cost[w] * open[w] + ship_cost[w] * ship[w])` is linear. Level
7: capacity exists and is a number. If a person had also required both
of the pair to be open (the same total `>= 2`), the solver would report no answer, and the
why-not search would name the two rules that conflict, and offer to soften
one.

**Solver.** A MILP with one indicator row per warehouse (native indicator
constraints in HiGHS/SCIP, or big-M from `ship`'s declared upper bound), one
cardinality row, one linking row per warehouse and the exclusion row. If the
model had hundreds of warehouses and customers, the Benders lane (`open` in
the master, shipping in the subproblem) is available by name.

---

## 23. Recommended internal architecture and data model

1. **Keep the IR as the single canonical model.** It is already typed,
   versioned, hashed, validated on both sides with pinned parity, compiled
   to every solver, and verified against. Everything in the brief fits it:
   as it stands (arithmetic, totals, filters, walks, conditions, curves,
   functions, predictions), or as a versioned addition (units, the logical
   layer).
2. **Treat views as pure projections with local edits.** New views
   (Sentence and Boxes were added this way) need only a renderer, a checker
   hook and round-trip tests. They never need a new storage format.
3. **Add logic as a lowering, not as solver features.** Condition nodes in
   the IR, lowered by the compiler to indicator rules and linear forms, keep
   every backend unchanged and the explanation intact.
4. **Add units as a checker, not a transformer.** Declared per item,
   inferred bottom-up, reported with the path, and never converted silently.
5. **Put language models behind the edit API.** They propose typed edits,
   the validator judges them, a person accepts them, and history records
   them. The model never writes an equation, and nothing an extractor
   produces bypasses the checks a human edit meets.
6. **Keep validation deterministic and single-sourced.** The contract
   (`contract.json`) is the one list of rules. The server enforces it, the
   browser mirrors it with parity tests, and the per-box checker explains
   it in place.

These priorities follow from the brief:

* **Correctness** comes from one source of truth and verification against it.
* **Explainability** comes from paths, plain words and why-not.
* **Usability** comes from Sentence and Boxes for newcomers, with equation
  and graph for experts.
* **Determinism** comes from pure checks and printers.
* **Extensibility** comes from the per-kind checklist.
* **Solver independence** holds because the IR never names a solver.
* **Bidirectional transformation** is guaranteed by round-trip tests.
* **Maintainability** comes from every layer reading the same contract.
