"""Piecewise-linear curves (`pwl`, IR version 2) mean what the IR says, on every backend that takes them.

A `pwl` term is f(x), the curve through its points by linear interpolation,
with x kept between the first and last point. CP-SAT holds it as a table,
SCIP as SOS2; HiGHS and the MILP wrapper get it rewritten
(app.solve.reformulate) -- an epigraph when the goal pushes a convex curve
down (or a concave one up) and nothing else touches it, else the
incremental formulation. GLOP takes only the epigraph.

The equivalence suite follows the roadmap's rule for any rewrite (§6.1):
seeded random models checked against an answer worked out by code that
shares nothing with the compiler -- here, exact fractions over every point
where the optimum can sit.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal
from fractions import Fraction

import pytest

from app.solve import compile_model
from app.solve.backends import NoBackend, by_name, choose
from app.solve.classify import classify
from app.solve.compile import Compiled, Linear, PwlDef, Variable
from app.solve.convexity import refine
from app.solve.reformulate import admit_pwl, pwl_rewrite
from app.solve.result import Solution
from app.solve.sandbox import explain_in_child
from app.solve.service import _assignments, _reduced_costs, solve_compiled

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}
X = ("x", ())
Y = ("__pwl", ("0",))


def _curve(points) -> PwlDef:
    return PwlDef(X, Y, tuple((Decimal(a), Decimal(b)) for a, b in points))


def _compiled(points, coeff, sense="minimize", rows=()) -> Compiled:
    curve = _curve(points)
    ys = [b for _, b in curve.points]
    return Compiled(
        variables={
            X: Variable(X, "continuous", Decimal(0), Decimal(10)),
            Y: Variable(Y, "continuous", min(ys), max(ys)),
        },
        constraints=list(rows),
        objective=Linear(coeffs={Y: Decimal(coeff)}),
        sense=sense,
        var_index_sets={"x": []},
        pwl=[curve],
    )


def _rows(compiled):
    return [
        ({k[0] + "".join(k[1]): float(v) for k, v in c.left.coeffs.items()}, c.relation, float(c.right.const))
        for c in compiled.constraints
    ]


# -- the rewrites, row by row ------------------------------------------------------


def test_a_convex_cost_pushed_down_is_its_tangent_lines():
    """Slopes 1 then 3: y >= x, and y >= 2 + 3(x - 2) = 3x - 4; x within 0..4."""
    rewritten, record = pwl_rewrite(_compiled([[0, 0], [2, 2], [4, 8]], 1))
    assert _rows(rewritten) == [
        ({"x": 1.0}, ">=", 0.0),
        ({"x": 1.0}, "<=", 4.0),
        ({"__pwl0": 1.0, "x": -1.0}, ">=", 0.0),
        ({"__pwl0": 1.0, "x": -3.0}, ">=", -4.0),
    ]
    assert rewritten.pwl == [] and set(rewritten.variables) == {X, Y}
    assert record == [{"kind": "pwl-epigraph", "x": "x", "segments": 2}]


def test_a_concave_gain_pushed_up_is_held_from_above():
    """Maximising a concave curve: y <= each line (slopes 3 then 1)."""
    rewritten, _ = pwl_rewrite(_compiled([[0, 0], [1, 3], [3, 5]], 1, sense="maximize"))
    assert _rows(rewritten)[2:] == [
        ({"__pwl0": 1.0, "x": -3.0}, "<=", 0.0),
        ({"__pwl0": 1.0, "x": -1.0}, "<=", 2.0),
    ]


def test_a_concave_cost_pushed_down_is_the_incremental_formulation():
    """x = 2 d0 + 2 d1, y = 10 d0 + 6 d1, and d1 <= z0 <= d0: the second
    segment is entered only once the first is full."""
    rewritten, record = pwl_rewrite(_compiled([[0, 0], [2, 10], [4, 16]], 1))
    assert _rows(rewritten) == [
        ({"x": 1.0, "__pwl_d00": -2.0, "__pwl_d01": -2.0}, "=", 0.0),
        ({"__pwl0": 1.0, "__pwl_d00": -10.0, "__pwl_d01": -6.0}, "=", 0.0),
        ({"__pwl_d01": 1.0, "__pwl_z00": -1.0}, "<=", 0.0),
        ({"__pwl_z00": 1.0, "__pwl_d00": -1.0}, "<=", 0.0),
    ]
    domains = {k[0] + "".join(k[1]): (v.domain, v.lower, v.upper) for k, v in rewritten.variables.items()}
    assert domains["__pwl_d00"] == ("continuous", 0, 1)
    assert domains["__pwl_z00"] == ("binary", 0, 1)
    assert record == [{"kind": "pwl-incremental", "x": "x", "segments": 2}]


def test_a_curve_a_rule_reads_is_never_an_epigraph():
    """Convex and pushed down, but a rule caps y: the epigraph would let y
    float above the curve to satisfy it, so the exact formulation is used."""
    from app.solve.compile import Constraint

    cap = Constraint("cap", {}, Linear(coeffs={Y: Decimal(1)}), "<=", Linear(const=Decimal(5)))
    _, record = pwl_rewrite(_compiled([[0, 0], [2, 2], [4, 8]], 1, rows=[cap]))
    assert record[0]["kind"] == "pwl-incremental"


def test_what_a_curve_needs_follows_its_shape():
    lp = classify(_ir("continuous", [[0, 0], [2, 2], [4, 8]], "minimize"), NO_DATA)
    assert lp.model_class == "LP" and "pwl" in lp.needs

    convex = refine(lp, compile_model(_ir("continuous", [[0, 0], [2, 2], [4, 8]], "minimize"), NO_DATA))
    assert convex.model_class == "LP" and "pwl-convex" in convex.needs and "pwl" not in convex.needs

    concave_ir = _ir("continuous", [[0, 0], [2, 10], [4, 16]], "minimize")
    concave = refine(classify(concave_ir, NO_DATA), compile_model(concave_ir, NO_DATA))
    assert concave.model_class == "MILP" and {"pwl", "integral"} <= concave.needs
    with pytest.raises(NoBackend):
        choose(concave, "glop")

    # A whole x on a curve that is not whole at x = 1 (0.5): y is
    # fractional, so the model is mixed and CP-SAT cannot take it.
    halves_ir = _ir("integer", [[0, 0], [2, 1]], "minimize")
    halves = refine(classify(halves_ir, NO_DATA), compile_model(halves_ir, NO_DATA))
    assert halves.model_class == "MILP" and "continuous" in halves.needs
    with pytest.raises(NoBackend):
        choose(halves, "cp-sat")


def test_admit_leaves_a_model_without_curves_alone():
    found = classify(_ir("continuous", None, "minimize"), NO_DATA)
    assert admit_pwl(found, compile_model(_ir("continuous", None, "minimize"), NO_DATA)) is found


def test_the_same_curve_of_the_same_x_is_one_variable():
    ir = _ir("integer", [[0, 0], [2, 10], [4, 16]], "minimize")
    term = ir["objective"]["terms"][0]["expression"]
    ir["objective"]["terms"][0]["expression"] = {"add": [term, term]}
    compiled = compile_model(ir, NO_DATA)
    assert len(compiled.pwl) == 1
    assert compiled.objective.coeffs[compiled.pwl[0].y] == 2


def test_the_curves_auxiliaries_are_not_reported_as_decisions():
    compiled = compile_model(_ir("integer", [[0, 0], [2, 10], [4, 16]], "minimize"), NO_DATA)
    result = Solution(
        status="optimal", optimal=True, objective=13, wall_seconds=0, solver="t",
        assignments={X: 3, Y: 13, ("__pwl_d", ("0", "0")): 1},
        reduced_costs={Y: 1.0, ("__pwl_z", ("0", "0")): 2.0},
    )
    assert _assignments(compiled, result) == {"x": [[]]}
    assert _reduced_costs(result) == {}


# -- hand-worked answers ---------------------------------------------------------------


def _ir(domain, points, sense, *, rules=(), extra_goal=None) -> dict:
    """x in 0..10 (or 0..6 whole) and the goal pwl(x) [+ extra]."""
    x = {"var": "x", "index": []}
    goal = {"pwl": x, "points": points} if points else x
    if extra_goal is not None:
        goal = {"add": [goal, extra_goal]}
    upper = 10 if domain == "continuous" else 6
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": domain, "lower": 0, "upper": upper}},
        "constraints": list(rules),
        "objective": {"sense": sense, "terms": [{"id": "o", "weight": 1, "expression": goal}]},
    }


def _at_least(name, left, value) -> dict:
    return {"id": name, "left": left, "relation": ">=", "right": {"const": value}, "severity": "hard"}


X_TERM = {"var": "x", "index": []}

HAND_WORKED = [
    # A volume discount (slopes 5, 3, 2 -- concave), at least 3 units, cost
    # minimised: f(3) = 10 + 3 = 13. The segment is a real choice here.
    ("volume_discount", _ir("integer", [[0, 0], [2, 10], [4, 16], [6, 20]], "minimize",
                            rules=[_at_least("need", X_TERM, 3)]), Decimal(13)),
    # The same curve over a fractional x: 13 still, but only the MILP
    # backends and SCIP take it -- no LP can hold a concave cost.
    ("volume_discount_fractional", _ir("continuous", [[0, 0], [2, 10], [4, 16], [6, 20]], "minimize",
                                       rules=[_at_least("need", X_TERM, 3)]), Decimal(13)),
    # A convex cost (slopes 1, 3, 4), x >= 3: f(3) = 2 + 3 = 5. An epigraph,
    # so GLOP takes it too.
    ("convex_cost", _ir("continuous", [[0, 0], [2, 2], [4, 8], [10, 32]], "minimize",
                        rules=[_at_least("need", X_TERM, 3)]), Decimal(5)),
    # Maximise f(x) - x, f concave (slopes 3, 1, 0): f - x climbs at 2, is
    # flat, then falls, so its best is on 1..3 at 3 - 1 = 2. x is capped at
    # 5 by the curve, not the declared 10.
    ("concave_gain", _ir("continuous", [[0, 0], [1, 3], [3, 5], [5, 5]], "maximize",
                         extra_goal={"mul": [{"const": -1}, X_TERM]}), Decimal(2)),
    # A budget on the curve, not the goal: maximise x with f(x) <= 12 on the
    # volume discount. f(2) = 10, f(3) = 13, so whole units stop at 2.
    ("budget_on_curve", {
        **_ir("integer", None, "maximize"),
        "constraints": [{"id": "budget", "left": {"pwl": X_TERM, "points": [[0, 0], [2, 10], [4, 16], [6, 20]]},
                         "relation": "<=", "right": {"const": 12}, "severity": "hard"}],
    }, Decimal(2)),
    # The curve keeps x within it: minimise -x on a curve from 1 to 4 that
    # nothing else reads... x may be 10, but the curve is 1..4 -- so -4.
    ("curve_bounds_x", _ir("continuous", [[1, 0], [4, 0]], "minimize",
                           extra_goal={"mul": [{"const": -1}, X_TERM]}), Decimal(-4)),
    # A whole x on a curve that is fractional between points: minimise with
    # x >= 1, f(1) = 0.5.
    ("fractional_curve_whole_x", _ir("integer", [[0, 0], [2, 1]], "minimize",
                                     rules=[_at_least("need", X_TERM, 1)]), Decimal("0.5")),
]

#: Who must take each: the claim is not only that the answer is right, but
#: that the right backends are offered it.
TAKERS = {
    "volume_discount": {"cp-sat", "scip", "highs", "milp"},
    "volume_discount_fractional": {"scip", "highs", "milp"},
    "convex_cost": {"glop", "scip", "highs", "milp"},
    "concave_gain": {"glop", "scip", "highs", "milp"},
    "budget_on_curve": {"cp-sat", "scip", "highs", "milp"},
    "curve_bounds_x": {"glop", "scip", "highs", "milp"},
    "fractional_curve_whole_x": {"scip", "highs", "milp"},
}
ALL = ("cp-sat", "glop", "scip", "highs", "milp")


@pytest.mark.parametrize(
    "name, ir, expected, backend_name",
    [pytest.param(n, ir, e, b, id=f"{n}-{b}") for n, ir, e in HAND_WORKED for b in ALL],
)
def test_hand_worked(name, ir, expected, backend_name):
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    try:
        choose(found, backend_name)
        taken = True
    except NoBackend:
        taken = False
    assert taken == (backend_name in TAKERS[name]), found
    backend = by_name(backend_name)
    if not taken:
        return
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    result, reason = solve_compiled(backend, compiled, time_limit=10, seed=1)
    assert result.status == "optimal", reason
    assert abs(Decimal(str(result.objective)) - expected) <= Decimal("1e-6"), result.objective
    # The answer's x lies on the curve's domain, and y on the curve.
    for curve in compiled.pwl:
        x = Decimal(str(result.assignments.get(curve.x, 0)))
        y = Decimal(str(result.assignments.get(curve.y, 0)))
        assert abs(y - curve.value_at(x)) <= Decimal("1e-6"), (x, y)


def test_a_whole_x_on_a_curve_between_whole_numbers_is_infeasible_everywhere():
    """0.2..0.8 covers no whole number: no answer, on every backend that
    takes it -- CP-SAT's table would be empty, which is not an error."""
    ir = _ir("integer", [[0.2, 0], [0.8, 1]], "minimize")
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    for name in ("cp-sat", "scip", "highs", "milp"):
        try:
            choose(found, name)
        except NoBackend:
            continue
        result, _ = solve_compiled(by_name(name), compiled, time_limit=10)
        assert result.status == "infeasible", (name, result.status)


# -- random models against exact arithmetic -----------------------------------------------


def _random(seed: int) -> dict:
    rnd = random.Random(seed)
    xs = sorted(rnd.sample(range(0, 7), rnd.randint(2, 4)))
    points = [[x, rnd.randint(-5, 10)] for x in xs]
    x = {"var": "x", "index": []}
    curve = {"pwl": x, "points": points}
    rules = []
    if rnd.random() < 0.6:
        rules.append({"id": "on_x", "left": x, "relation": rnd.choice(["<=", ">="]),
                      "right": {"const": rnd.randint(0, 6)}, "severity": "hard"})
    if rnd.random() < 0.5:
        rules.append({"id": "on_curve", "left": curve, "relation": rnd.choice(["<=", ">="]),
                      "right": {"const": rnd.randint(-3, 8)}, "severity": "hard"})
    k = rnd.choice([-2, -1, 1, 2])
    m = rnd.randint(-2, 2)
    goal = {"add": [{"mul": [{"const": k}, curve]}, {"mul": [{"const": m}, x]}]}
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": rnd.choice(["integer", "continuous"]), "lower": 0, "upper": 6}},
        "constraints": rules,
        "objective": {"sense": rnd.choice(["minimize", "maximize"]),
                      "terms": [{"id": "o", "weight": 1, "expression": goal}]},
    }


def _f(points, x: Fraction) -> Fraction:
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + Fraction(y1 - y0, x1 - x0) * (x - x0)
    raise AssertionError(x)


def _exact(ir: dict) -> Fraction | None:
    """The optimum, by trying every point where it can sit: on one variable
    with a piecewise-linear goal and rules, that is an end of some piece --
    a breakpoint, a rule's bound on x, or where the curve crosses a rule's
    bound on it. For a whole x, every whole x."""
    points = ir["objective"]["terms"][0]["expression"]["add"][0]["mul"][1]["points"]
    k = ir["objective"]["terms"][0]["expression"]["add"][0]["mul"][0]["const"]
    m = ir["objective"]["terms"][0]["expression"]["add"][1]["mul"][0]["const"]
    lo, hi = max(0, points[0][0]), min(6, points[-1][0])
    if ir["variables"]["x"]["domain"] == "integer":
        candidates = {Fraction(n) for n in range(math.ceil(lo), math.floor(hi) + 1)}
    else:
        candidates = {Fraction(p[0]) for p in points} | {Fraction(lo), Fraction(hi)}
        for rule in ir["constraints"]:
            b = Fraction(rule["right"]["const"])
            if rule["id"] == "on_x":
                candidates.add(b)
            else:
                for (x0, y0), (x1, y1) in zip(points, points[1:]):
                    if y0 != y1 and min(y0, y1) <= b <= max(y0, y1):
                        candidates.add(x0 + (b - y0) * Fraction(x1 - x0, y1 - y0))

    def holds(x: Fraction) -> bool:
        if not lo <= x <= hi:
            return False
        for rule in ir["constraints"]:
            left = x if rule["id"] == "on_x" else _f(points, x)
            b = rule["right"]["const"]
            if not (left <= b if rule["relation"] == "<=" else left >= b):
                return False
        return True

    values = [k * _f(points, x) + m * x for x in candidates if holds(x)]
    if not values:
        return None
    return min(values) if ir["objective"]["sense"] == "minimize" else max(values)


@pytest.mark.parametrize("seed, backend_name", [(s, b) for s in range(40) for b in ALL])
def test_the_solver_agrees_with_exact_arithmetic(seed, backend_name):
    ir = _random(seed)
    expected = _exact(ir)
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    try:
        choose(found, backend_name)
    except NoBackend:
        # Only CP-SAT (a fractional x or curve) and GLOP (anything but an
        # epigraph) may refuse; SCIP, HiGHS and the MILP wrapper take them all.
        assert backend_name in ("cp-sat", "glop"), found
        return
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    result, reason = solve_compiled(backend, compiled, time_limit=10, seed=1)
    if expected is None:
        assert result.status == "infeasible", (seed, result.status)
    else:
        assert result.status == "optimal", (seed, result.status, reason)
        assert abs(Fraction(str(result.objective)) - expected) <= Fraction(1, 10**6), (seed, result.objective, expected)


def test_the_random_suite_reaches_every_formulation():
    """So the agreement above is not agreement about one easy case."""
    kinds, natives = set(), set()
    for seed in range(40):
        ir = _random(seed)
        compiled = compile_model(ir, NO_DATA)
        kinds |= {r["kind"] for r in pwl_rewrite(compiled)[1]}
        found = refine(classify(ir, NO_DATA), compiled)
        for name in ("cp-sat", "glop"):
            try:
                choose(found, name)
                natives.add(name)
            except NoBackend:
                pass
    assert kinds == {"pwl-epigraph", "pwl-incremental"}
    assert natives == {"cp-sat", "glop"}


# -- an infeasible model's explanation names the rules, never the curve's rows ---------------


@pytest.mark.parametrize("backend_name", ["highs", "scip", "cp-sat"])
def test_a_conflict_is_among_the_models_own_rules(backend_name):
    """f(x) >= 25 on a curve that tops out at 20: `too_much` alone is the
    conflict; `need` holds and the curve's rows are no rule of the model's."""
    ir = _ir("integer", None, "minimize")
    ir["constraints"] = [
        _at_least("need", X_TERM, 1),
        _at_least("too_much", {"pwl": X_TERM, "points": [[0, 0], [2, 10], [4, 16], [6, 20]]}, 25),
    ]
    compiled = compile_model(ir, NO_DATA)
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    assert solve_compiled(backend, compiled, time_limit=10)[0].status == "infeasible"
    conflict = explain_in_child(
        backend=backend_name, compiled=compiled, probe_seconds=5, should_stop=None, on_progress=None
    )
    assert conflict.rules == ["too_much"] and conflict.minimal
