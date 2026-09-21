# Building out the solving platform — roadmap

**Written for:** whoever picks this up next, including a future session of this
project. It assumes the schema-v1 migration (merged at `aefc84c`) as its
starting point and does not re-explain it.

**Status:** Phase 0 is **done** (merged at `7c283a1`); the rest is proposed.
The phases are ordered by dependency, not by appetite.

Update, 2026-09-20: the checking infrastructure is merged too (`f30f1b6`) —
`bash scripts/check.sh` runs both suites the one correct way.

---

## 1. Where the platform actually is

Facts, not impressions:

| | state |
|---|---|
| Schema | 16 v1 tables, migrations `0006`–`0010`, live at `0010` |
| Domain modelling | entity types, typed attributes, entities, relationship types, relationships, indexed parameters — **complete and usable** |
| Problem modelling | `problem`, `model_version` (immutable, hashed), `scenario` (a patch over a version) exist as **tables**; `model_version.ir` is opaque `jsonb` |
| Run subsystem | `dataset`, `run`, `solution`, `constraint_result` exist as tables with immutability triggers and a `snapshot_dataset()` that works. **No API, no worker, no queue, no UI** |
| Solver | **absent.** Not in this repository |
| Tests | 754 backend, 1268 frontend, axe 0 across 59 states |

**The gap that matters:** a user can model a domain completely and cannot
express a single constraint. There is no route in the product to create a model
version, because nothing knows what belongs inside one.

## 2. The blocker, stated plainly

`model_version.ir` is a JSON document whose shape is defined by a solver
(`ProblemIR`, `psp/data.py`) that is **not in this repository**. Everything
downstream inherits that uncertainty:

- no expression editor can be built, because nothing defines what a valid
  expression is;
- `snapshot_dataset()` already reads `ir.sets` and `ir.parameters` and will
  raise on anything else — so the contract is already half-committed, by
  accident rather than by design;
- `scenario.patch` references constraint ids that nothing validates;
- solver selection cannot classify a model it cannot parse.

**Phase 0 exists to end this.** Every later phase depends on it, and no amount
of UI work substitutes for it.

## 3. Design principles

These are the "dynamic and flexible" requirement made concrete. Each one is a
test you can apply to a proposed change.

1. **Model structure is data, not code.** A new kind of constraint is a row,
   not a deployment. The domain half already works this way — attributes are
   `attribute_def` rows, not columns — and the problem half should match.
2. **The database is the last line of defence, the UI is the first.** Every
   rule that matters gets a CHECK or trigger; routers shadow it for a good
   message. This is already the established pattern (Rulings 16, 32) and it is
   what let the seed be trusted.
3. **One definition, many consumers.** The expression catalogue is shared
   between TypeScript and Python through one file, with a parity test that
   fails if they drift (Ruling 37). Solver capabilities must work the same way.
4. **Reproducibility is a property of the schema.** A run already points at an
   immutable version *and* an immutable dataset, both content-hashed. Keep
   that: a result nobody can reproduce is not a result.
5. **Refusals name the field and say what to do next.** One 422 shape, `kind`
   present exactly when the database judged (Rulings 19, 30).

---

## Phase 0 — The model contract — **DONE** (`7c283a1`)

Delivered: `docs/contracts/problem-ir.md` (the contract, with worked examples),
one shared artefact both languages read, a validator on each side with a parity
test, shared fixtures, enforcement at `POST /versions` (an invalid IR is now a
422 naming the path, where an unknown set used to be a 500 inside
`snapshot_dataset()`), patch ids validated against their version, and the
seeded model rewritten so its constraints carry mathematics instead of prose.

**Three decisions it took, which the rest of this roadmap now inherits:**

1. **v1 admits `binary` and `integer` variables and refuses `continuous` by
   name.** The reasoning is worth keeping: there is no solver to run a
   continuous model, and admitting one would make the contract promise what
   the platform cannot keep. It also closed a back door — entity attributes
   include `number`, so arithmetic over a `number` attribute would have let
   fractional coefficients in while parameters stayed integral, and nobody
   would have decided that. Arithmetic is restricted to `integer` attributes;
   `number` attributes remain usable in filters.
2. **No unexpressed constraint is admitted**, so the seed was rewritten rather
   than the contract weakened.
3. **Traversal is not expressible** — and this one is a *consequence*, not a
   choice. `snapshot_dataset()` freezes entities and parameters but **no
   relationships**, so the frozen input a solver reads contains no edges. The
   spec's own example (`unit.descendants`) therefore cannot be written today.
   See "The traversal gap" below; it is the most consequential thing Phase 0
   surfaced.

Read §9 of the contract first: it separates what was **derived** from existing
code (changing it contradicts something real) from what was **invented** here
(a later reader, or your solver, may reopen it).

---

## The traversal gap — decide before Phase 1

A hierarchy is the reason `relationship` exists, and a planner's first
interesting constraint usually crosses one: *staffing for a region, counting
its sub-units*; *nobody reports to someone in another division*. None of that
is expressible, because the dataset a run is frozen against carries no
relationships at all.

Three ways out, in increasing order of cost:

1. **Freeze the edges too.** Extend `snapshot_dataset()` to emit relationships
   per type, and give the term algebra a traversal form. Reproducibility is
   preserved because the edges are frozen with everything else.
2. **Precompute closures.** Emit `entity_descendants()` output for hierarchy
   types as derived sets. Cheaper to express, less general.
3. **Leave it.** Constraints stay flat; hierarchy is presentational only.

This is a schema-and-contract change, so it belongs before model authoring
rather than after — an editor built on a term algebra that cannot traverse
will need reworking when traversal arrives.

## Phase 1 — Model authoring — **DONE via (a), the document** (`90eef1e`, `349a863`, `c4b76a6`)

The choice below was taken: the editor reads and writes the IR document
directly, with the contract's validator as its safety net. Sets, parameters
and variables are declared in the product; constraints and objectives are
built with react-querybuilder over the same expression catalogue; versions
are started from nothing or from any earlier one; scenarios ask the same
model a different question.

**(b), promotion to rows, remains open and should stay open** until a
concrete need appears -- diffing two versions rule by rule, reusing a
constraint across problems, or per-constraint permissions. The record below
is the design for when it does.

**Goal:** a user can build a model in the product, and what they build is
inspectable, diffable and reusable.

**First, a question Phase 0 reopened.** This section was written when the IR
was opaque; it no longer is. There are now two defensible designs, and the
choice should be deliberate:

- **(a) Author the document.** The IR is already validated on both sides, with
  a `loc`-shaped refusal per rule. An editor could read and write the document
  directly, with the validator as its safety net. One source of truth, no
  compile step, and the editor is honest by construction because it cannot
  save what the contract refuses.
- **(b) Promote to rows,** as sketched below, and compile a version from them.
  Better for diffing two versions, for reusing a constraint across problems,
  for per-constraint permissions, and for querying ("which models use this
  parameter?"). Costs a second representation to keep in step with the
  contract.

**Recommendation: (a) first, (b) when a concrete need appears.** The
contract's refusals are already field-shaped, so (a) gets a usable editor much
sooner; the rows in (b) pay for themselves only once versions are being
compared and constraints reused, which nothing does yet. Revisit at the first
of those needs — not before.

**Schema, if (b).** Promote the model's parts from opaque JSON to first-class
rows, while keeping the compiled IR as the immutable artefact:

```
variable_def       (problem_id, name, index_type_ids[], domain: binary|integer|continuous,
                    lower, upper, unit)
constraint_def     (problem_id, name, kind, expression jsonb, relation, rhs,
                    scope_type_ids[], severity: hard|soft, penalty_weight)
objective_def      (problem_id, name, sense: min|max, terms jsonb, weight)
```

Rationale: this is the same move that made the domain half work. `attribute_def`
rows are why an entity form can be generated; `constraint_def` rows are why a
model editor can be generated, why two versions can be diffed meaningfully, and
why a solver adapter can classify a model without parsing free text.

`model_version.ir` stays: it is the **compiled, frozen** form. Authoring edits
the rows; publishing a version compiles them into the IR and hashes it. That
preserves immutability and reproducibility while making authoring editable.

**Expressions.** Extend the existing expression core rather than inventing a
second one. Today it produces boolean condition trees (`14c`/`14d`); a model
needs *arithmetic*: `sum over set`, coefficients, products of a variable and a
parameter, comparison to a bound. Two shapes, one catalogue, one validator,
one parity mechanism.

**UI.** Three editors following the established page conventions, plus a model
overview that shows a version's variables, constraints and objectives, and a
diff between two versions. This finally makes the "Model versions" screen
honest — today it advertises a workflow that does not exist.

**Watch:** `scenario.patch` (`disable`/`harden`/`soften`) must line up with
`constraint_def` ids once they exist. Today it references ids nothing
validates.

---

## Phase 2 — Solver selection for linear and nonlinear problems — **DONE for the classes v1 expresses** (`24c894e`, `aeb5a6e`)

Two backends (CP-SAT and branch-and-cut MILP), capabilities as data in a
registry, and a policy recorded on every run: an explicit choice wins or is
refused, otherwise the highest-ranked backend that fits, with the reason in
`run.params.why_solver`. The test that gives it meaning is that both
backends reach the same optimum on the same model -- with one backend, a
wrong policy would have been invisible.

**Still open**, and honestly so: the continuous classes (LP, QP, NLP, MINLP)
in the table below. The contract admits only `binary` and `integer`
variables (§7), so there is nothing yet to hand IPOPT or Bonmin. The
schema decision named at the end of this section -- integer-only parameters
-- is the thing that blocks them, and it should be taken before an adapter
is written, not after.

**Goal:** the platform picks an appropriate technique, explains its choice, and
lets a user override it.

**Classify the model, from the rows Phase 1 created:**

| class | detection |
|---|---|
| LP | continuous variables only; all expressions linear |
| MILP | as LP with integer or binary variables |
| QP / QCQP | quadratic objective or constraints, otherwise linear |
| NLP | continuous, any nonlinear expression |
| MINLP | discrete variables and nonlinear expressions |
| CP / scheduling | discrete, with combinatorial structure (all-different, no-overlap, precedence) |

Classification is a pure function of the model, so it is testable without a
solver and belongs in the shared catalogue.

**A solver registry, capabilities as data:**

```
solver_backend  (name, version, classes[], supports_indicator, supports_sos,
                 supports_nonconvex, supports_warm_start, licence, is_available)
```

Candidate adapters, roughly in order of usefulness here: **CP-SAT** (the
schema's integer-only design is already aimed at it), **HiGHS** (LP/MILP,
permissive licence), **IPOPT** (continuous NLP), **Bonmin/Couenne** (MINLP),
with a commercial adapter (Gurobi/CPLEX) as a licence-gated option. Adapters
are processes behind one interface, not libraries linked into the API.

**Selection policy**, in this order, and visible to the user:
1. an explicit choice on the problem or scenario wins;
2. otherwise the highest-ranked available backend whose capabilities cover the
   model class;
3. record *why* on the run (`chosen_backend`, `classified_as`, `reason`);
4. a portfolio mode may race two backends and keep the first result, for the
   cases where classification is ambiguous.

**Nonlinear needs an explicit honesty rule:** convexity is not decidable in
general. Where the platform cannot prove convexity it must say the result is a
*local* optimum, not a global one. A silent local optimum presented as the
answer is the worst failure mode this feature can have.

**Note the existing constraint:** `parameter_value.value` and
`parameter_def.default_value` are `int`, deliberately, for CP-SAT (spec §2).
Continuous solvers need rational or float parameters, so Phase 2 must either
add a numeric type to parameters or restrict continuous models to
non-parameter coefficients. **This is a schema decision, not an adapter
detail.**

---

## Phase 3 — Runs — **DONE** (`dac2f03`, `aeb5a6e`)

A database-backed queue claimed with `FOR UPDATE SKIP LOCKED`, a worker
service, snapshot-on-submit, full provenance on the run, and a UI that
follows a run until it settles and then stops asking. Stale runs from a
dead worker are reclaimed at start-up.

**Still open:** cancellation and a heartbeat. A run can only be waited out
today, and the 30-minute reclaim is a coarse substitute for a worker that
says it is still alive.

**Goal:** press solve, watch it, get a result you can trust and reproduce.

The tables exist and are immutable; what is missing is everything around them.

- **Queue and worker.** A run is queued, claimed by a worker, and reports
  progress. Prefer a database-backed queue over adding a broker until the load
  justifies one — `run` already has the status enum and the timestamps.
- **API:** create a run from (version, scenario, dataset), poll it, cancel it,
  stream its log.
- **Snapshot on submit:** `snapshot_dataset()` already produces the frozen
  input and dedupes identical snapshots by hash. Wire it in.
- **Record provenance:** solver name and version, model hash, data hash, seed,
  time limit, gap. Two runs of the same triple must be comparable.
- **UI:** a run list, a run detail with live status, and the result.

---

## Phase 4 — Results, and why they are what they are — **mostly DONE** (`9dafbd1`, `f89c152`, `edff8ad`)

- **Solution viewer in domain language** -- done. Migration 0012 freezes
  display names into the snapshot, so a run reads back in the names that
  were current when it was asked rather than today's.
- **Infeasibility diagnosis** -- done, by deletion filtering, reported into
  `run.conflict` per instance. `run.conflict_minimal` says whether the set
  was proven irreducible, so the UI promises "relax any one of these" only
  when that is true.
- **Scenario comparison** -- done, with the caveat attached: the comparison
  states what the two runs differ by and whether the patch is the only
  difference, because crediting a rule for a change the data caused is a
  wrong answer dressed as an insight.
- **Sensitivity** -- **not done.** Shadow prices and reduced costs need an
  LP relaxation the contract cannot express yet (see Phase 2). Slack per
  constraint is available today and is the useful half: it names the rule
  with no room left, which is the one to relax next. `constraint_result`
  has no column for it, so this is a migration, not a read.

A number is not an answer. The value of this phase is that it turns the tool
from a calculator into something a planner can argue with.

- **Solution viewer** mapped back to domain language — entities by name, not
  variable indices.
- **Infeasibility diagnosis.** When there is no solution, say which constraints
  conflict (an irreducible infeasible set where the backend supports it,
  otherwise a relaxation search over soft constraints). `constraint_result`
  exists for exactly this.
- **Sensitivity** where the class supports it: shadow prices and reduced costs
  for LP, slack per constraint generally.
- **Scenario comparison:** two runs side by side, differing only by their
  patch, with the objective and the changed assignments highlighted.

---

## Phase 5 — Roles and configuration — **two of three DONE** (`671fac8`, `237049c`)

- **Capabilities** -- done. Migration 0013 makes them rows granted to
  roles, enforced by one dependency, and reported by `GET /api/v1/me` so
  a screen and the server cannot disagree. The split that matters holds:
  a planner may solve without being able to change the model.
- **Settings at three levels** -- done. Migration 0014; problem beats
  domain beats platform beats the built-in default, every resolved value
  says which level supplied it, and a run records it too.
- **Templates** -- **not done.** The `template` table is still unused.

**Also still open:** the UI reflects capabilities on the Runs and Settings
screens only. The domain-editing screens still offer actions a viewer
cannot take; the API refuses them with a readable reason, so nothing is
silently broken, but the roadmap's standard is *absent*, not *refused*.

**Goal:** the flexible configuration the request asks for, for roles as well as
for model parts.

- **Permissions are currently nominal.** `iam` has users, roles and
  memberships, and every authenticated user can do everything. Introduce
  capabilities (`domain.edit`, `model.publish`, `run.submit`,
  `solver.configure`) granted to roles, enforced in one dependency in the API
  and reflected in the UI so unavailable actions are absent, not broken.
- **Settings as data, at three levels** — platform, domain, problem — each
  overriding the last: default solver, time limit, optimality gap, thread
  count, whether nonconvex problems may run at all.
- **Templates.** The `template` table exists and is unused. A template is a
  starting model plus a domain seed: "weekly rota", "shift coverage". This is
  what makes the platform teachable, and it is cheap once Phase 1 exists.

---

## Cross-cutting, and existing debt worth paying

Carried from the migration's ledger; none of it blocks, all of it compounds:

- **Parameter re-index race** — two ordinary API calls can leave a cell whose
  coordinates no longer match its parameter, and `snapshot_dataset()` will then
  emit it keyed by two type names. One `FOR SHARE` clause. **Fix before the
  solver consumes datasets in anger.**
- **No keyboard route to create or delete a relationship** (WCAG 2.1.1, Level
  A). Less severe since the relationships screens landed, still a gap.
- **`translate_db_error` discards a trigger's own message on 23503**, so the
  actionable half of a refusal reaches the logs and not the user.
- **Unbounded payloads** on the graph read and parameter values.
- **Five string-detail 422s** in the generic CRUD layer, inconsistent with the
  platform's one-shape rule.
- **The checks script** (branch `checks`) should land; nothing currently runs
  either suite automatically, which is how a smoke test rotted into a script
  that would have destroyed the live database.
- **Lint** was measured and deliberately left out: a stock config reports 260
  problems, a reduced one still 34. Revisit deliberately, not by accident.

---

## Decisions needed before Phase 0 can finish

1. ~~Is the solver's IR available?~~ **Answered by events.** It was not
   supplied, so the contract was defined here and the solver becomes the
   consumer that adapts. If the real `ProblemIR` turns up, reconcile it
   against §9's invented list — those are the points most likely to differ.
2. **Integer-only, or continuous too?** Deferred, not settled: v1 refuses
   `continuous` **by name**, so the refusal is visible and reversible. Genuine
   LP and NLP still need a numeric parameter type, which is a schema change
   (`parameter_value.value`, `parameter_def.default_value`, `run.objective`)
   plus relaxing the `integer`-attributes-only rule. Decide when a continuous
   solver is actually in reach; until then the current refusal is honest.
3. **The traversal gap** (above) — freeze edges, precompute closures, or leave
   hierarchy presentational. Blocks nothing today, shapes the term algebra
   tomorrow.
4. **Where do solvers run?** In-process, as sidecar containers, or on a remote
   worker pool. This determines the queue design in Phase 3 and the licence
   handling in Phase 2.
5. **How much does the platform promise?** Specifically: may it run a nonconvex
   model and present a local optimum, with a warning, or should it refuse?
6. **Who is the user?** If planners self-serve, Phase 5's permissions and Phase
   4's explanations matter more than raw solver coverage. If a modelling team
   drives it, invert that.

## Sequencing

```
Phase 0  ── blocks everything
   └── Phase 1 ── model authoring
          ├── Phase 2 ── solver selection      (needs the model to classify)
          │      └── Phase 3 ── runs           (needs something to run)
          │             └── Phase 4 ── results
          └── Phase 5 ── roles and settings    (can start in parallel with 2)
```

Phase 5's permission work is the one piece that can proceed without Phase 0,
and it is the right thing to hand to a second pair of hands.
