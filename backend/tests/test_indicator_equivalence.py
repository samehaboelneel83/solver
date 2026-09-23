"""Conditional rules (`when`) mean what the IR says, on every backend that takes them.

The target roadmap's rule for any rewrite (§6.1): on tiny models, enumerate
every assignment and check the solvers agree with it. Here the meaning is
read straight off the IR -- a rule with a `when` must hold wherever its
switch has the stated value, and nothing else is asked of it -- by code
that shares nothing with the compiler or the adapters. Forty seeded random
models: two switches, two whole-number decisions in 0..3, three rules each
with a random relation, coefficients and (usually) a random switch.
"""

from __future__ import annotations

import itertools
import random
from decimal import Decimal

import pytest

from app.solve import compile_model
from app.solve.backends import NoBackend, by_name, choose
from app.solve.classify import classify
from app.solve.convexity import refine
from app.solve.service import solve_compiled

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}
SWITCHES = ("b1", "b2")
AMOUNTS = ("x1", "x2")


def _random_model(seed: int) -> dict:
    rnd = random.Random(seed)
    rules = []
    for i in range(3):
        terms = [{"mul": [{"const": rnd.randint(-3, 3)}, {"var": name, "index": []}]} for name in AMOUNTS]
        rule = {
            "id": f"r{i}",
            "left": {"add": terms},
            "relation": rnd.choice(["<=", ">=", "="]),
            "right": {"const": rnd.randint(-2, 4)},
            "severity": "hard",
        }
        if rnd.random() < 0.8:
            rule["when"] = {"var": rnd.choice(SWITCHES), "index": [], "is": rnd.choice([0, 1])}
        rules.append(rule)
    goal = [{"mul": [{"const": rnd.randint(-4, 4)}, {"var": name, "index": []}]} for name in SWITCHES + AMOUNTS]
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {
            **{b: {"index": [], "domain": "binary"} for b in SWITCHES},
            **{x: {"index": [], "domain": "integer", "lower": 0, "upper": 3} for x in AMOUNTS},
        },
        "constraints": rules,
        "objective": {"sense": rnd.choice(["minimize", "maximize"]),
                      "terms": [{"id": "o", "weight": 1, "expression": {"add": goal}}]},
    }


def _value(term: dict, at: dict) -> int:
    if "const" in term:
        return term["const"]
    if "var" in term:
        return at[term["var"]]
    if "add" in term:
        return sum(_value(t, at) for t in term["add"])
    if "mul" in term:
        a, b = term["mul"]
        return _value(a, at) * _value(b, at)
    raise AssertionError(term)


def _holds(rule: dict, at: dict) -> bool:
    when = rule.get("when")
    if when is not None and at[when["var"]] != when.get("is", 1):
        return True  # switched off: the rule asks nothing
    left, right = _value(rule["left"], at), _value(rule["right"], at)
    return {"<=": left <= right, ">=": left >= right, "=": left == right}[rule["relation"]]


def _brute_force(ir: dict) -> int | None:
    """The optimum by trying every assignment, or None when none holds."""
    best = None
    names = SWITCHES + AMOUNTS
    for values in itertools.product((0, 1), (0, 1), range(4), range(4)):
        at = dict(zip(names, values))
        if not all(_holds(rule, at) for rule in ir["constraints"]):
            continue
        score = _value(ir["objective"]["terms"][0]["expression"], at)
        if best is None or (score < best if ir["objective"]["sense"] == "minimize" else score > best):
            best = score
    return best


#: CP-SAT and SCIP hold a `when` natively; HiGHS and the MILP wrapper take it
#: as a big-M from the declared bounds (0..3 here), so all four must agree.
CASES = [(seed, backend) for seed in range(40) for backend in ("cp-sat", "scip", "highs", "milp")]


@pytest.mark.parametrize("seed, backend_name", CASES)
def test_the_solver_agrees_with_every_assignment_tried(seed, backend_name):
    ir = _random_model(seed)
    expected = _brute_force(ir)
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    # Declared bounds (0..3), so once compiled the need is the bounded one.
    assert found.needs & {"indicator", "indicator-bounded"} or not any("when" in r for r in ir["constraints"])
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    try:
        choose(found, backend_name)
    except NoBackend as exc:  # pragma: no cover -- both take an all-integer model
        pytest.fail(str(exc))

    result, _ = solve_compiled(backend, compiled, time_limit=10, seed=1)
    if expected is None:
        assert result.status == "infeasible", (seed, result.status)
    else:
        assert result.status == "optimal", (seed, result.status)
        assert Decimal(str(result.objective)) == Decimal(expected), (seed, result.objective, expected)


def test_the_models_are_not_all_the_same_case():
    """The generator exercises both outcomes and both kinds of switch."""
    irs = [_random_model(seed) for seed in range(40)]
    outcomes = {_brute_force(ir) is None for ir in irs}
    kinds = {r["when"]["is"] for ir in irs for r in ir["constraints"] if "when" in r}
    assert outcomes == {True, False}
    assert kinds == {0, 1}


def test_a_big_m_backend_is_refused_a_rule_over_a_guard_ceiling_and_told_which_variable():
    """x1 has no declared upper bound: an M from the compiler's guard ceiling
    would be a million nobody chose, so HiGHS and the MILP wrapper are
    refused, the refusal names x1, and a native backend still takes it."""
    ir = _random_model(0)
    del ir["variables"]["x1"]["upper"]
    for rule in ir["constraints"]:
        rule["when"] = {"var": "b1", "index": []}
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    assert "indicator" in found.needs
    for name in ("highs", "milp"):
        with pytest.raises(NoBackend, match="x1, which has no declared upper bound"):
            choose(found, name)
    with pytest.raises(NoBackend):
        choose(found, "glop")
    assert choose(found)[0].name == "cp-sat"


def test_glop_is_never_offered_a_conditional_rule():
    ir = _random_model(0)
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    with pytest.raises(NoBackend):
        choose(found, "glop")


def test_a_rule_switched_off_has_no_slack_to_report():
    """At the facility's optimum B is open, so "B ships nothing while closed"
    does not bind; A is closed, so "A ships nothing" binds, with no room."""
    from tests.test_golden import CONT, _facility
    from app.solve.compile import slack_by_constraint

    compiled = compile_model(_facility(CONT), NO_DATA)
    optimum = {("open_a", ()): 0, ("open_b", ()): 1, ("ship_a", ()): 0, ("ship_b", ()): 7}
    slacks = slack_by_constraint(compiled, optimum)
    assert "closed_b" not in slacks
    assert slacks["closed_a"] == 0
    assert slacks["demand"] == 0
