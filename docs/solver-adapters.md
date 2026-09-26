# Adding a solver

Any native solver can join the platform without changing its code. Examples are Gurobi, Xpress,
CPLEX, COPT, a research code, or your own heuristic. You write a folder with an `adapter.toml`,
and the solver becomes one more backend. The same rules choose it, it runs in the same sandbox,
and runs record it the same way.

**The platform ships and buys nothing.** The solver and its licence are yours. They come in your own
image, or in a volume mounted at `/opt/solver/adapters`.

## Where adapters live

`SOLVER_ADAPTERS_DIR` lists folders, separated by `:`. Each holds one folder per adapter. The
default, set in `docker-compose.yml` for the api and the worker alike, is:

```
/app/adapters/reference:/opt/solver/adapters
```

The first folder holds the reference adapters shipped in the image. The second is for yours: mount
it read-only. Adapters are read when a process starts, so restart the api and the worker after
adding one.

`GET /api/v1/solvers` lists every solver:
- `origin`: `built-in` or `adapter`;
- `available`: whether the solver's library or program is here;
- `automatic`: whether the rules may choose it unasked.

It also lists under `skipped` every manifest that was not loaded, and why. A broken manifest never
stops the platform.

## Until an adapter is verified, it runs only when named

An added solver is never chosen automatically, raced, or benched unasked, until the conformance kit
has passed it (queue R43). Until then you ask for it by name: `POST /scenarios/{id}/runs`
`{"solver": "cbc"}`, by an account allowed to choose solvers. The run records the adapter:
`cbc 2.10 (ortools) (adapter): cbc (ortools 9.15…)`.

## The manifest

```toml
name = "my-solver"        # lower-case letters, digits, - and _; not a built-in's name
kind = "ortools-engine"   # or "command-line", or "python"
version = "1.0"
proves = "global"         # what its `optimal` means: global | local | approximate
classes = ["IP", "LP", "MILP", "trivial"]  # optional; the kind's ceiling if left out
provides = ["linear", "integral"]          # optional; likewise; never beyond the ceiling
rank = 50                 # optional; the built-ins are 0-7
note = "one line for the Solvers page"

[environment]             # optional: set for each solve
GUROBI_HOME = "/opt/gurobi"
```

`proves` is required on purpose. A solver whose `optimal` means "best nearby" must say `local`,
or its answers would be shown as proven best.

What a manifest may claim is bounded by its kind:
- The two linear kinds carry exactly what the built-in `milp` backend's translation carries: linear
  rules, whole and fractional decisions, soft rules, conditional rules written with bounds, and
  curves and products of yes-or-no decisions written as linear rows.
- A `python` adapter may claim anything some built-in provides.

A claim beyond the ceiling is refused with its reason.

## Kind 1: `ortools-engine` (a manifest only)

The model goes through the same translation as the built-in `milp` backend, to an engine that
OR-Tools loads at run time from the vendor's own library. This is the shortest way to add Gurobi,
Xpress or CPLEX.

```toml
[engine]
engine = "CBC"            # CBC, SCIP, GUROBI, XPRESS, CPLEX
options = ""              # optional: the engine's own parameter text
```

### Gurobi, Xpress and CPLEX (untested here, for want of a licence)

These manifests follow OR-Tools' documented loading of each vendor's library. They are marked
untested until a customer with a licence runs the conformance kit with them.

```toml
# /opt/solver/adapters/gurobi/adapter.toml
name = "gurobi"
kind = "ortools-engine"
version = "12"
proves = "global"
[engine]
engine = "GUROBI"
[environment]
GUROBI_HOME = "/opt/gurobi1200/linux64"
GRB_LICENSE_FILE = "/opt/gurobi/gurobi.lic"
```

```toml
# /opt/solver/adapters/xpress/adapter.toml
name = "xpress"
kind = "ortools-engine"
version = "9"
proves = "global"
[engine]
engine = "XPRESS"
[environment]
XPRESSDIR = "/opt/xpressmp"
XPAUTH_PATH = "/opt/xpressmp/bin/xpauth.xpr"
```

```toml
# /opt/solver/adapters/cplex/adapter.toml
name = "cplex"
kind = "ortools-engine"
version = "22"
proves = "global"
[engine]
engine = "CPLEX"
[environment]
CPLEX_STUDIO_DIR = "/opt/ibm/ILOG/CPLEX_Studio2211"
```

The vendor's library itself must be in the image or the mounted volume. Where a licence belongs to
one organization rather than the whole platform, queue R42 stores it per organization, encrypted,
and hands it only to that organization's solves.

## Kind 2: `command-line` (any program)

The platform writes the model as a free-format MPS file:
- columns are `v0, v1, …` and rows `r0, r1, …`, in the model's own order;
- the goal row is `obj`, and its constant is left out.

It then runs your program and reads back the solution file it writes. The objective is worked out
by the platform from the values, never read from the program.

```toml
[command]
executable = "cbc"                # on PATH, or a path; `{adapter_dir}` is this folder
args = ["{model}", "sec", "{time_limit}", "threads", "{threads}", "solve", "solu", "{solution}"]
solution = "sol"                  # the file's format
infeasible_exit_codes = []        # optional
unbounded_exit_codes = []         # optional
```

**Placeholders:** `{model}`, `{solution}`, `{time_limit}`, `{threads}`, `{gap}`, `{seed}` and
`{adapter_dir}`.

**The `sol` format** is Gurobi's, and most solvers can write it:
- one `name value` per line;
- `#` starts a comment;
- a `# Status = optimal` (or `feasible`, `infeasible`, `unbounded`) comment is the solver's own
  claim;
- names not listed are 0.

**A program that does not state a status.** Its answer is `feasible`, never `optimal`: the platform
does not claim a proof the solver did not make.

**Stopping.** The program is stopped when a run is cancelled, and killed 5 s after its time limit
(the run is then `unknown`).

## Kind 3: `python` (full control)

A file in the adapter's folder with a function taking the built-ins' arguments and returning an
`app.solve.result.Solution`:

```python
def solve(compiled, *, time_limit, workers, should_stop=None, seed=None, gap_rel=0.0,
          on_progress=None, **_):
    ...
```

```toml
[python]
module = "adapter.py"
function = "solve"
```

A vendor's Python API (`gurobipy`, `xpress`) goes this way when you want callbacks, native
conflict analysis or anything the linear translation does not carry.

## The reference adapters

`backend/adapters/reference/` has one adapter of each kind. Each is tested against the golden
suite's known answers (`tests/test_adapters.py`).

| Adapter | Kind | Stands in for |
|---|---|---|
| `cbc` | ortools-engine | Gurobi / Xpress / CPLEX through OR-Tools |
| `highs-cli` | command-line | any solver's own program (a script around HiGHS) |
| `python-cpsat` | python | a vendor's Python API |
