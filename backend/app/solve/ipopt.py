"""A local nonlinear lane: IPOPT, through casadi (queue R6, target roadmap Phase 16).

SCIP proves the global optimum of a nonlinear model by spatial branch and
bound -- and on a large nonconvex one may run out of time with no answer at
all. IPOPT is an interior-point method: it follows the slope from where it
starts to the best answer *nearby*, fast, on models of any size, but never
knows whether a better one exists elsewhere. So it registers as a backend
that proves `local` (the platform's standing rule: such an answer is shown
with a warning and never called optimal), ranked after SCIP so it is never
chosen over a global solver on its own: it is asked for by name, or takes
over when SCIP ends with nothing (setting `solve.local_fallback`).

**Multistart** (Epic engine, E-2). IPOPT's answer depends on where it
starts. With the whitelisted option `starts` (`ipopt.starts=8` in the setting
`solve.solver_params`, or a run's own solver options), the time is split
over that many starts: the first from the hint or the middle of each range
as before, the rest spread over the bounds by Latin hypercube sampling (seeded,
so a rerun repeats it). The best answer that keeps every rule wins. It is
still a local optimum -- the best of several nearby ones -- and says so; the
run records how many starts found an answer.

Continuous models only -- a whole-number decision has no slope. IPOPT's
"the problem is infeasible" is as local as its optimum (it found no way
downhill to feasibility from where it started), so it is reported as no
answer, never as a proof that none exists. casadi carries IPOPT in its wheel
(pinned in requirements.txt); no system library is needed.
"""

from __future__ import annotations

import time
from decimal import Decimal

from app.solve.compile import Compiled, Unsupported
from app.solve.lp import NotContinuous
from app.solve.result import Solution

#: IPOPT's return words that mean it reached a local optimum (to its tolerance, or an acceptable one).
_LOCAL_OPTIMUM = {"Solve_Succeeded", "Solved_To_Acceptable_Level"}
#: The words for stopping on a limit: whatever it holds may still be an answer.
_STOPPED = {"Maximum_CpuTime_Exceeded", "Maximum_WallTime_Exceeded", "Maximum_Iterations_Exceeded",
            "User_Requested_Stop"}
#: How far a rule may be broken and still count as kept.
FEASIBLE_TOLERANCE = 1e-6


def available() -> bool:
    """Found, not imported: casadi is large, and every choice of solver asks."""
    from importlib.util import find_spec

    return find_spec("casadi") is not None


def _check(compiled: Compiled) -> None:
    integral = next((key for key, var in compiled.variables.items() if var.is_integral), None)
    if integral is not None:
        raise NotContinuous(f"ipopt solves continuous models, and {integral[0]!r} takes whole numbers")
    if compiled.pwl:
        raise Unsupported("ipopt needs a smooth model; a piecewise curve has corners")
    if any(c.when is not None or c.schedule is not None for c in compiled.constraints):
        raise Unsupported("ipopt holds neither conditional rules nor scheduling rules")


def _bound(value: Decimal) -> float:
    number = float(value)
    return number if abs(number) < 1e19 else (float("inf") if number > 0 else float("-inf"))


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 1,
    should_stop=None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    import casadi as ca

    from app.solve.params import check as check_params

    _check(compiled)
    starts = int(check_params("ipopt", solver_params).get("starts", 1))
    started = time.monotonic()
    keys = list(compiled.variables)
    position = {key: i for i, key in enumerate(keys)}
    x = ca.SX.sym("x", len(keys))

    def linear(form) -> "ca.SX":
        total = ca.SX(float(form.const))
        for key, coeff in form.coeffs.items():
            total = total + float(coeff) * x[position[key]]
        return total

    def quadratic(pairs) -> "ca.SX":
        total = ca.SX(0)
        for (a, b), coeff in pairs.items():
            total = total + float(coeff) * x[position[a]] * x[position[b]]
        return total

    goal = linear(compiled.objective) + quadratic(compiled.objective_quadratic)
    if compiled.sense == "maximize":
        goal = -goal

    rows, lower_g, upper_g = [], [], []
    for rule in compiled.constraints:
        expression = linear(rule.left) - linear(rule.right) + quadratic(rule.quadratic)
        rows.append(expression)
        lower_g.append(0.0 if rule.relation in (">=", "=") else -ca.inf)
        upper_g.append(0.0 if rule.relation in ("<=", "=") else ca.inf)
    functions = {"exp": ca.exp, "log": ca.log, "sqrt": ca.sqrt, "abs": ca.fabs, "sin": ca.sin, "cos": ca.cos}
    for function in compiled.functions:
        # y = f(argument): the stand-in is held to the function exactly.
        rows.append(x[position[function.y]] - functions[function.name](linear(function.argument)))
        lower_g.append(0.0)
        upper_g.append(0.0)

    lower_x = [_bound(compiled.variables[key].lower) for key in keys]
    upper_x = [_bound(compiled.variables[key].upper) for key in keys]

    def start(i: int) -> float:
        key = keys[i]
        if hint and key in hint:
            value = float(hint[key])
        elif lower_x[i] > float("-inf") and upper_x[i] < float("inf"):
            value = (lower_x[i] + upper_x[i]) / 2
        else:
            value = 0.0
        return min(max(value, lower_x[i]), upper_x[i])

    per_start = max(0.1, float(time_limit) / starts)
    options = {"print_time": False, "ipopt.print_level": 0, "ipopt.sb": "yes",
               "ipopt.max_wall_time": per_start}
    problem = {"x": x, "f": goal}
    if rows:
        problem["g"] = ca.vertcat(*rows)
    solver = ca.nlpsol("platform", "ipopt", problem, options)
    points = [[start(i) for i in range(len(keys))]] + spread(lower_x, upper_x, starts - 1, seed)

    best = None  # (rank, objective, values): an optimum outranks a stopped answer
    found = 0
    for x0 in points:
        if should_stop is not None and should_stop():
            break
        if time.monotonic() - started > float(time_limit):
            break
        arguments = {"x0": x0, "lbx": lower_x, "ubx": upper_x}
        if rows:
            arguments.update(lbg=lower_g, ubg=upper_g)
        answer = solver(**arguments)
        said = solver.stats().get("return_status", "")
        values = [float(v) for v in ca.DM(answer["x"]).full().flatten()]
        breach = 0.0
        if rows:
            for g, lo, hi in zip((float(v) for v in ca.DM(answer["g"]).full().flatten()), lower_g, upper_g):
                breach = max(breach, lo - g, g - hi)
        within = all(lo - FEASIBLE_TOLERANCE <= v <= hi + FEASIBLE_TOLERANCE
                     for v, lo, hi in zip(values, lower_x, upper_x))
        kept = breach <= FEASIBLE_TOLERANCE and within
        if not kept or not (said in _LOCAL_OPTIMUM or said in _STOPPED):
            # Including "Infeasible_Problem_Detected": a local finding, not a proof.
            continue
        found += 1
        rank = 1 if said in _LOCAL_OPTIMUM else 0
        value = float(ca.DM(answer["f"]).full().flatten()[0])  # minimised: the sense is already folded in
        if best is None or (rank, -value) > (best[0], -best[1]):
            best = (rank, value, values)

    if best is None:
        status = "unknown"
    else:
        status = "optimal" if best[0] == 1 else "feasible"  # a local optimum: `proves="local"` says what it is worth
    assignments = {key: round(best[2][i], 6) for i, key in enumerate(keys)} if best is not None else {}
    objective = None
    if assignments:
        objective = float(compiled.objective.evaluated_at(assignments)) + sum(
            float(c) * assignments[a] * assignments[b] for (a, b), c in compiled.objective_quadratic.items())
        objective = round(objective, 6)
    name = f"ipopt (casadi {ca.__version__})"
    if starts > 1:
        name += f", best of {found} answers from {len(points)} starts"
    return Solution(
        status=status,
        optimal=status == "optimal",
        objective=objective,
        assignments=assignments,
        wall_seconds=round(time.monotonic() - started, 3),
        solver=name,
        best_bound=None,
    )


def spread(lower: list[float], upper: list[float], count: int, seed: int | None) -> list[list[float]]:
    """`count` starting points by Latin hypercube over the bounds: each
    variable's range cut into `count` slices, one point per slice, the slices
    shuffled per variable. An infinite side is replaced by a box of 1,000
    around the finite one (or around zero), which is where a model with no
    bound usually lives."""
    import random

    if count <= 0:
        return []
    chooser = random.Random(0 if seed is None else int(seed))
    columns = []
    for lo, hi in zip(lower, upper):
        if lo == float("-inf") and hi == float("inf"):
            lo, hi = -1000.0, 1000.0
        elif lo == float("-inf"):
            lo = hi - 1000.0
        elif hi == float("inf"):
            hi = lo + 1000.0
        slices = list(range(count))
        chooser.shuffle(slices)
        columns.append([lo + (hi - lo) * (s + chooser.random()) / count for s in slices])
    return [list(point) for point in zip(*columns)]
