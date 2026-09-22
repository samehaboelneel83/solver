"""How long it takes to hand a model to GLOP or the MILP wrapper, three ways.

    python -m bench.build_speed [--repeat 3]

Target roadmap D7: rows and columns added one at a time cost Python time
that grows with the model. HiGHS moved to arrays and went from 2.0 s to
0.23 s on a 200,000-entry model. This measured the pywraplp backends'
(`lp.py`, `milp.py`) expression-object build against two alternatives
before either was changed -- the proto won and is what they use now
(`app/solve/pywraplp_model.py`) -- and still measures all three, on:

* `synthetic-lp-200k` -- 1,000 rows x 200 entries over 2,000 continuous
  variables, exactly 200,000 entries, seeded;
* `feed_blend-XL` (LP, ~122,000 entries) and `facility-XL` (MILP,
  ~320,000 entries), the bench families' largest.

The three ways, each timed from the `Compiled` model to a solver ready to
solve (the rearranging of every rule into `coeffs <= rhs` form included,
since each must do it):

* `expr` -- the build before 2026-09-23: `solver.Sum(var * coeff ...)`
  and `solver.Add(expr >= rhs)`;
* `coef` -- `solver.Constraint(lb, ub)` and one `SetCoefficient` per entry,
  no expression objects;
* `proto` -- the shipped loader: an `MPModelProto` whose rows are filled
  with two bulk `extend`s each, loaded with `LoadModelFromProto`.

Each model is then solved from every build and the objectives compared, so
a faster build that changed the model would show.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import time
from decimal import Decimal
from typing import Any, Callable

INF = math.inf


def synthetic_lp(rows: int = 1000, cols: int = 2000, per_row: int = 200, seed: int = 7):
    """max sum c.x s.t. A x <= b, 0 <= x <= 10, A > 0: feasible (x = 0) and bounded."""
    from app.solve.compile import Compiled, Constraint, Linear, Variable

    rng = random.Random(seed)
    keys = [("x", (str(j),)) for j in range(cols)]
    variables = {k: Variable(key=k, domain="continuous", lower=Decimal(0), upper=Decimal(10)) for k in keys}
    constraints = []
    for i in range(rows):
        chosen = rng.sample(keys, per_row)
        coeffs = {k: Decimal(rng.randint(1, 9)) for k in chosen}
        constraints.append(
            Constraint(
                id=f"r{i}", index={}, left=Linear(coeffs=coeffs), relation="<=",
                right=Linear(const=Decimal(rng.randint(50, 500))),
            )
        )
    objective = Linear(coeffs={k: Decimal(rng.randint(1, 5)) for k in keys})
    return Compiled(
        variables=variables, constraints=constraints, objective=objective, sense="maximize",
        var_index_sets={"x": [str(j) for j in range(cols)]},
    )


def rows_of(compiled) -> list[tuple[dict, str, float]]:
    """Every rule as (coeffs, relation, rhs) with the variables on the left."""
    out = []
    for c in compiled.constraints:
        coeffs = dict(c.left.coeffs)
        for key, coeff in c.right.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
        out.append((coeffs, c.relation, float(c.right.const - c.left.const)))
    return out


def bounds(relation: str, rhs: float) -> tuple[float, float]:
    return {
        ">=": (rhs, INF), "<=": (-INF, rhs), "=": (rhs, rhs), "==": (rhs, rhs),
        ">": (rhs + 1, INF), "<": (-INF, rhs - 1),
    }[relation]


def _var(solver, key, spec):
    name = f"{key[0]}[{','.join(key[1])}]"
    if spec.domain == "binary":
        return solver.BoolVar(name)
    if spec.domain == "integer":
        return solver.IntVar(float(spec.lower), float(spec.upper), name)
    return solver.NumVar(float(spec.lower), float(spec.upper), name)


def build_expr(solver, compiled) -> None:
    variables = {key: _var(solver, key, spec) for key, spec in compiled.variables.items()}
    for coeffs, relation, rhs in rows_of(compiled):
        expression = solver.Sum([variables[k] * float(v) for k, v in coeffs.items()])
        lo, hi = bounds(relation, rhs)
        if lo == hi:
            solver.Add(expression == lo)
        elif hi == INF:
            solver.Add(expression >= lo)
        else:
            solver.Add(expression <= hi)
    _objective_expr(solver, compiled, variables)


def _objective_expr(solver, compiled, variables) -> None:
    expression = solver.Sum([variables[k] * float(v) for k, v in compiled.objective.coeffs.items()])
    solver.Minimize(expression) if compiled.sense == "minimize" else solver.Maximize(expression)


def build_coef(solver, compiled) -> None:
    variables = {key: _var(solver, key, spec) for key, spec in compiled.variables.items()}
    for coeffs, relation, rhs in rows_of(compiled):
        lo, hi = bounds(relation, rhs)
        row = solver.Constraint(lo, hi)
        for key, coeff in coeffs.items():
            row.SetCoefficient(variables[key], float(coeff))
    objective = solver.Objective()
    for key, coeff in compiled.objective.coeffs.items():
        objective.SetCoefficient(variables[key], float(coeff))
    objective.SetMinimization() if compiled.sense == "minimize" else objective.SetMaximization()


def build_proto(solver, compiled) -> None:
    """What `lp.py` and `milp.py` now use: the shipped loader, measured as it is."""
    from app.solve.pywraplp_model import load

    load(solver, compiled)


BUILDERS: dict[str, Callable] = {"expr": build_expr, "coef": build_coef, "proto": build_proto}


def measure(compiled, engine: str, repeat: int) -> dict[str, Any]:
    from ortools.linear_solver import pywraplp

    out: dict[str, Any] = {}
    for name, build in BUILDERS.items():
        times = []
        for _ in range(repeat):
            solver = pywraplp.Solver.CreateSolver(engine)
            started = time.perf_counter()
            build(solver, compiled)
            times.append(time.perf_counter() - started)
        solver.SetTimeLimit(60_000)
        status = solver.Solve()
        out[name] = {
            "build_s": statistics.median(times),
            "status": status,
            "objective": solver.Objective().Value() if status in (0, 1) else None,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    from app.solve import compile_model
    from bench.families import generate

    parser = argparse.ArgumentParser(prog="python -m bench.build_speed")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args(argv)

    cases = [("synthetic-lp-200k", synthetic_lp(), ("GLOP", "SCIP"))]
    for family, engines in (("feed_blend", ("GLOP", "SCIP")), ("facility", ("SCIP",))):
        inst = generate(family, "XL", 0)
        cases.append((f"{family}-XL", compile_model(inst.ir, inst.data), engines))

    print("| model | entries | engine | expr (s) | coef (s) | proto (s) | same answer |")
    print("|---|---|---|---|---|---|---|")
    for label, compiled, engines in cases:
        entries = sum(len(c.left.coeffs) + len(c.right.coeffs) for c in compiled.constraints)
        for engine in engines:
            found = measure(compiled, engine, args.repeat)
            answers = [r["objective"] for r in found.values()]
            same = all(
                a is not None and abs(a - answers[0]) <= 1e-6 * max(1.0, abs(answers[0])) for a in answers
            )
            print(
                f"| {label} | {entries:,} | {engine} | {found['expr']['build_s']:.3f} "
                f"| {found['coef']['build_s']:.3f} | {found['proto']['build_s']:.3f} | {'yes' if same else 'NO'} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
