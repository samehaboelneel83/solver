"""The golden suite: small models whose answers are known, on every backend.

Phase 6.1 of the target roadmap. Each model below has its status and its
objective worked out by hand, in the comment beside it. The suite solves it
through `solve_compiled` -- the path a run takes, including the check for an
answer resting on a ceiling nobody set -- on EVERY available backend whose
declared capabilities take it, and asserts they all agree with the known
answer to 1e-6 relative.

That last part is the point. A backend that mis-maps a status, drops a term
or loses a sign disagrees with the others on at least one of these, and
"zero wrong answers" -- the rule every future technique must pass before it
is enabled by default -- starts here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.solve import compile_model, evolve, network
from app.solve.backends import REGISTRY, SEARCHES, NoBackend, by_name, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported
from app.solve.convexity import refine
from app.solve.scaling import admit
from app.solve.service import solve_compiled

NO_DATA: dict[str, Any] = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def v(name: str) -> dict:
    return {"var": name, "index": []}


def c(value) -> dict:
    return {"const": value}


def mul(a, b) -> dict:
    return {"mul": [a, b]}


def add(*terms) -> dict:
    return {"add": list(terms)}


def rule(rid: str, left, relation: str, right, **extra) -> dict:
    return {"id": rid, "left": left, "relation": relation, "right": right, "severity": "hard", **extra}


def model(variables: dict, rules: list, sense: str | None = None, terms: list | None = None, mode: str | None = None, version: int = 1) -> dict:
    ir: dict[str, Any] = {
        "version": version,
        "sets": [],
        "parameters": {},
        "variables": {name: {"index": [], **spec} for name, spec in variables.items()},
        "constraints": rules,
    }
    if sense is not None:
        ir["objective"] = {
            "sense": sense,
            "terms": [{"id": f"o{i}", "weight": 1, "expression": t} for i, t in enumerate(terms or [])],
            **({"mode": mode} if mode else {}),
        }
    return ir


CONT = {"domain": "continuous", "lower": 0, "upper": 10}
INT = {"domain": "integer", "lower": 0, "upper": 10}
BIN = {"domain": "binary"}

def _facility(shipment: dict) -> dict:
    return model(
        {"open_a": BIN, "open_b": BIN, "ship_a": shipment, "ship_b": shipment},
        [
            rule("demand", add(v("ship_a"), v("ship_b")), ">=", c(7)),
            rule("closed_a", v("ship_a"), "<=", c(0), when={"var": "open_a", "index": [], "is": 0}),
            rule("closed_b", v("ship_b"), "<=", c(0), when={"var": "open_b", "index": [], "is": 0}),
            rule("cap_a", v("ship_a"), "<=", c(5)),
        ],
        "minimize",
        [mul(c(20), v("open_a")), mul(c(30), v("open_b")), v("ship_a"), mul(c(2), v("ship_b"))],
        version=2,
    )


GOLDEN: list[tuple[str, dict, str, Decimal | None]] = [
    # max 5x + 4y, 6x + 4y <= 24, x + 2y <= 6: the vertex (3, 1.5), 21.
    (
        "lp_vertex",
        model(
            {"x": CONT, "y": CONT},
            [
                rule("c1", add(mul(c(6), v("x")), mul(c(4), v("y"))), "<=", c(24)),
                rule("c2", add(v("x"), mul(c(2), v("y"))), "<=", c(6)),
            ],
            "maximize",
            [mul(c(5), v("x")), mul(c(4), v("y"))],
        ),
        "optimal",
        Decimal("21"),
    ),
    # Weights 5, 4, 3, 2, values 10, 7, 5, 3, capacity 9: a and b, 17.
    (
        "ip_knapsack",
        model(
            {"a": BIN, "b": BIN, "c": BIN, "d": BIN},
            [
                rule(
                    "cap",
                    add(mul(c(5), v("a")), mul(c(4), v("b")), mul(c(3), v("c")), mul(c(2), v("d"))),
                    "<=",
                    c(9),
                )
            ],
            "maximize",
            [mul(c(10), v("a")), mul(c(7), v("b")), mul(c(5), v("c")), mul(c(3), v("d"))],
        ),
        "optimal",
        Decimal("17"),
    ),
    # max x + 5n, x + 3n <= 10.5, x <= 2, n whole: n = 3, x = 1.5, 16.5.
    (
        "milp_mixed",
        model(
            {"x": {"domain": "continuous", "lower": 0, "upper": 2}, "n": INT},
            [rule("c", add(v("x"), mul(c(3), v("n"))), "<=", c(10.5))],
            "maximize",
            [v("x"), mul(c(5), v("n"))],
        ),
        "optimal",
        Decimal("16.5"),
    ),
    # x >= 6 and x <= 4 cannot both hold.
    (
        "infeasible",
        model({"x": INT}, [rule("lo", v("x"), ">=", c(6)), rule("hi", v("x"), "<=", c(4))], "minimize", [v("x")]),
        "infeasible",
        None,
    ),
    # Maximise a quantity nothing limits: the default ceiling must not pass
    # for an optimum.
    (
        "unbounded_lp",
        model({"x": {"domain": "continuous"}}, [rule("lo", v("x"), ">=", c(1))], "maximize", [v("x")]),
        "unbounded",
        None,
    ),
    (
        "unbounded_ip",
        model({"n": {"domain": "integer"}}, [rule("lo", v("n"), ">=", c(1))], "maximize", [v("n")]),
        "unbounded",
        None,
    ),
    # The same, held back by a rule at exactly the ceiling's height: the
    # answer touches the default ceiling, raising it changes nothing, and
    # the optimum stands.
    (
        "ceiling_incidental",
        model(
            {"x": {"domain": "continuous"}},
            [rule("hi", v("x"), "<=", c(1_000_000))],
            "maximize",
            [v("x")],
        ),
        "optimal",
        Decimal("1000000"),
    ),
    # max 2x + 2y, with x + y <= 1 soft at 3 per unit: both on pays 4 - 3, one
    # on pays 2. The penalty is part of the objective: 2.
    (
        "soft_rule",
        model(
            {"x": BIN, "y": BIN},
            [rule("cap", add(v("x"), v("y")), "<=", c(1), severity="soft", weight=3)],
            "maximize",
            [mul(c(2), v("x")), mul(c(2), v("y"))],
        ),
        "optimal",
        Decimal("2"),
    ),
    # a + b first, then c, with a + b + c <= 2: a + b = 2 wins, c = 0. The
    # reported objective is the first term, 2.
    (
        "lex",
        model(
            {"a": BIN, "b": BIN, "c": BIN},
            [rule("cap", add(v("a"), v("b"), v("c")), "<=", c(2))],
            "maximize",
            [add(v("a"), v("b")), v("c")],
            mode="lex",
        ),
        "optimal",
        Decimal("2"),
    ),
    # min x^2 + y^2, x + y = 10: 5 and 5, 50.
    (
        "qp_convex",
        model(
            {"x": CONT, "y": CONT},
            [rule("sum", add(v("x"), v("y")), "=", c(10))],
            "minimize",
            [mul(v("x"), v("x")), mul(v("y"), v("y"))],
        ),
        "optimal",
        Decimal("50"),
    ),
    # max x^2 + y^2, x + y = 10: everything on one, 100.
    (
        "qp_nonconvex",
        model(
            {"x": CONT, "y": CONT},
            [rule("sum", add(v("x"), v("y")), "=", c(10))],
            "maximize",
            [mul(v("x"), v("x")), mul(v("y"), v("y"))],
        ),
        "optimal",
        Decimal("100"),
    ),
    # max x + y, x * y <= 4 on [0, 10]^2: a corner, 10.4.
    (
        "qcqp_hyperbola",
        model({"x": CONT, "y": CONT}, [rule("h", mul(v("x"), v("y")), "<=", c(4))], "maximize", [v("x"), v("y")]),
        "optimal",
        Decimal("10.4"),
    ),
    # min x + y, x * y >= 12, whole numbers: 3 x 4, 7.
    (
        "miqcqp_whole",
        model({"x": INT, "y": INT}, [rule("a", mul(v("x"), v("y")), ">=", c(12))], "minimize", [v("x"), v("y")]),
        "optimal",
        Decimal("7"),
    ),
    # A rule with nothing left to decide that cannot hold -- what `sum of
    # x[e] >= 1` becomes when e ranges over nobody. HiGHS once dropped such a
    # row and answered a model that has no answer.
    (
        "constant_false_rule",
        model({"x": BIN}, [rule("never", c(0), ">=", c(1))], "maximize", [v("x")]),
        "infeasible",
        None,
    ),
    # Whole decisions, fractional numbers (migration 0039): CP-SAT takes these
    # only scaled, and must agree with the backends that take the fractions.
    # max 2.25x + 1.5y, 7.5x + 5y <= 40, x, y whole in [0, 10]. The rule is
    # 2.5 (3x + 2y) <= 40, i.e. 3x + 2y <= 16, and the goal is 0.75 (3x + 2y),
    # so the best is 0.75 x 16 = 12 (x = 0, y = 8 reaches it).
    (
        "scaled_shift_hours",
        model(
            {"x": INT, "y": INT},
            [rule("hours", add(mul(c(7.5), v("x")), mul(c(5), v("y"))), "<=", c(40))],
            "maximize",
            [mul(c(2.25), v("x")), mul(c(1.5), v("y"))],
        ),
        "optimal",
        Decimal("12"),
    ),
    # Knapsack to the cent: weights 2.4, 3.1, 1.7 under 5; values 3.5, 4.25,
    # 2.1. a+b weighs 5.5, too much; a+c 4.1 is worth 5.6; b+c 4.8 is worth
    # 6.35; all three weigh 7.2. So 6.35.
    (
        "scaled_knapsack",
        model(
            {"a": BIN, "b": BIN, "d": BIN},
            [
                rule(
                    "cap",
                    add(mul(c(2.4), v("a")), mul(c(3.1), v("b")), mul(c(1.7), v("d"))),
                    "<=",
                    c(5),
                )
            ],
            "maximize",
            [mul(c(3.5), v("a")), mul(c(4.25), v("b")), mul(c(2.1), v("d"))],
        ),
        "optimal",
        Decimal("6.35"),
    ),
    # Five decimal places: past what is scaled, so CP-SAT is never offered it
    # (`test_scaling_admits_only_what_it_can_make_whole` pins that); the
    # others answer. 0.12345 x <= 1 lets x = 1.
    (
        "five_decimals",
        model({"x": BIN}, [rule("w", mul(c(0.12345), v("x")), "<=", c(1))], "maximize", [v("x")]),
        "optimal",
        Decimal("1"),
    ),
    # Conditional rules (IR version 2, `when`). Two sites; A costs 20 to open
    # and ships at 1 a unit, B costs 30 and ships at 2; demand is 7 and A can
    # ship at most 5; a closed site ships nothing. A alone cannot meet 7; B
    # alone is 30 + 2 x 7 = 44; both is 20 + 30 + 5 + 2 x 2 = 59. So 44, with
    # only B open. Whole shipments go to CP-SAT and SCIP; shipments that may
    # be fractional only SCIP can take, and the answer is the same.
    ("facility_when_whole", _facility(INT), "optimal", Decimal("44")),
    ("facility_when_fractional", _facility(CONT), "optimal", Decimal("44")),
    # `is` 1: the rule binds only while the switch is on. max x, x <= 3 when
    # y, y costs 5 and x earns 2: y off leaves x free to 10, 20; y on caps x
    # at 3 and costs 5, 1. So 20, with y off.
    (
        "switch_on_caps",
        model(
            {"x": INT, "y": BIN},
            [rule("cap", v("x"), "<=", c(3), when={"var": "y", "index": []})],
            "maximize",
            [mul(c(2), v("x")), mul(c(-5), v("y"))],
            version=2,
        ),
        "optimal",
        Decimal("20"),
    ),
    # A conditional rule that can never hold forces its switch off: x >= 11
    # when y, x at most 10, and y is required... y >= 1: infeasible.
    (
        "impossible_when_forces_off",
        model(
            {"x": INT, "y": BIN},
            [
                rule("never", v("x"), ">=", c(11), when={"var": "y", "index": []}),
                rule("need_y", v("y"), ">=", c(1)),
            ],
            version=2,
        ),
        "infeasible",
        None,
    ),
    # A transport: sources of 3 and 2, sinks wanting 2 and 3, costs 4 6 / 5 3. 2 + 1 from the first,
    # 2 to the second sink from the second: 8 + 6 + 6 = 20. A network, so `networkx` takes it.
    (
        "transport_network",
        model(
            {"x11": INT, "x12": INT, "x21": INT, "x22": INT},
            [
                rule("s1", add(v("x11"), v("x12")), "<=", c(3)),
                rule("s2", add(v("x21"), v("x22")), "<=", c(2)),
                rule("d1", add(v("x11"), v("x21")), ">=", c(2)),
                rule("d2", add(v("x12"), v("x22")), ">=", c(3)),
            ],
            "minimize",
            [mul(c(4), v("x11")), mul(c(6), v("x12")), mul(c(5), v("x21")), mul(c(3), v("x22"))],
        ),
        "optimal",
        Decimal("20"),
    ),
    # No objective: any answer that holds is optimal, and there is no value.
    ("feasibility", model({"x": BIN}, [rule("on", v("x"), ">=", c(1))]), "optimal", None),
]


def _cases():
    for name, ir, status, objective in GOLDEN:
        compiled = compile_model(ir, NO_DATA)
        found = refine(classify(ir, NO_DATA), compiled)
        # As a run sees it with `solve.cpsat_scaling` off, and on: a backend
        # that takes the model either way must give the known answer.
        either = [found, admit(found, compiled)]
        takers = []
        for backend in REGISTRY:
            if not backend.is_available():
                continue
            if not any(_takes(backend, considered) for considered in either):
                continue
            takers.append(backend)
        assert takers, f"{name}: no backend takes it"
        for backend in takers:
            yield pytest.param(ir, backend, status, objective, id=f"{name}-{backend.name}")


def _takes(backend, found) -> bool:
    try:
        choose(found, backend.name)
    except NoBackend:
        return False
    return True


@pytest.mark.parametrize("ir, backend, status, objective", list(_cases()))
def test_golden(ir, backend, status, objective):
    if backend.name in SEARCHES:
        _search_golden(ir, backend, status, objective)
        return
    if backend.name == "qubo-anneal":
        # The model as a QUBO, annealed (app.solve.qubo): a model a QUBO cannot hold is refused by name;
        # otherwise held to what a search is held to.
        try:
            compile_model(ir, NO_DATA)
            from app.solve.qubo import to_qubo

            to_qubo(compile_model(ir, NO_DATA))
        except Exception as exc:  # noqa: BLE001
            with pytest.raises(Unsupported, match="qubo-anneal takes a model written as a QUBO"):
                solve_compiled(backend, compile_model(ir, NO_DATA), time_limit=2, seed=1)
            assert str(exc)
            return
        _search_golden(ir, backend, status, objective)
        return
    if backend.name == "networkx" and network.applies(compile_model(ir, NO_DATA), ceilings=True) is not None:
        # Its class fits, its shape does not: refused with the reason, never answered as something else.
        with pytest.raises(Unsupported, match="networkx solves a network"):
            solve_compiled(backend, compile_model(ir, NO_DATA), time_limit=20, seed=1)
        return
    result, reason = solve_compiled(backend, compile_model(ir, NO_DATA), time_limit=20, seed=1)

    assert result.status == status, reason
    if objective is None:
        assert result.objective is None
    elif backend.proves == "local":
        # A local solver's optimum is the best nearby (queue R6): never better
        # than the global one, and on a convex model the same.
        got = Decimal(str(result.objective))
        slack = Decimal("1e-6") * max(Decimal(1), abs(objective))
        assert (got >= objective - slack) if ir["objective"]["sense"] == "minimize" else (got <= objective + slack), got
    else:
        got = Decimal(str(result.objective))
        assert abs(got - objective) <= Decimal("1e-6") * max(Decimal(1), abs(objective)), got
    if status == "unbounded":
        assert reason and "without limit" in reason
        assert result.assignments == {}


def _search_golden(ir, backend, status, objective):
    """A search (queue R14) proves nothing: on a model with a known optimum it answers with one that keeps
    every rule and is never better, or with none; it never says infeasible, and a model with no finite
    bound on a decision is refused, since there is no box to search."""
    compiled = compile_model(ir, NO_DATA)
    if status == "unbounded":
        with pytest.raises(Unsupported, match="no finite bound"):
            solve_compiled(backend, compiled, time_limit=2, seed=1)
        return
    try:
        result, _ = solve_compiled(backend, compiled, time_limit=2, seed=1)
    except Unsupported as exc:
        assert "no finite bound" in str(exc), exc
        return
    assert result.status in ("feasible", "unknown") and not result.optimal and result.best_bound is None
    if status != "optimal" or result.status == "unknown":
        assert result.status == "unknown" and result.objective is None
        return
    assert evolve.holds(compiled, result.assignments)
    if objective is not None:
        got = Decimal(str(result.objective))
        # A search holds a rule to 1e-6 of its size (`evolve.TOLERANCE`), as the solvers do, and an equality
        # held that closely moves a goal by more: 49.9999 against 50 on `qp_convex`.
        slack = Decimal("1e-4") * max(Decimal(1), abs(objective))
        assert (got >= objective - slack) if ir["objective"]["sense"] == "minimize" else (got <= objective + slack), got


def test_scaling_admits_only_what_it_can_make_whole():
    """CP-SAT takes the two scaled models, and never the five-decimal one."""
    takers = {case.id for case in _cases()}
    assert "scaled_shift_hours-cp-sat" in takers
    assert "scaled_knapsack-cp-sat" in takers
    assert "five_decimals-cp-sat" not in takers
    assert "five_decimals-highs" in takers or "five_decimals-milp" in takers


def test_networkx_answers_the_network_golden_case():
    """Refusing every model would pass the golden suite; it must also answer the one network there."""
    ir = next(ir for name, ir, _, _ in GOLDEN if name == "transport_network")
    result, _ = solve_compiled(by_name("networkx"), compile_model(ir, NO_DATA), time_limit=20, seed=1)
    assert result.status == "optimal" and Decimal(str(result.objective)) == 20
    assert result.solver.startswith("network (min-cost flow, NetworkX")


def test_every_backend_is_exercised_by_the_golden_suite():
    covered = {case.values[1].name for case in _cases()}
    # The placement solver takes only a place rule, which needs a drawing's areas and slots as data: its known
    # answers (a room filled to its proven bound, shared aisles, the camp) are in tests/test_placement.py.
    assert covered | {"layout"} == {b.name for b in REGISTRY if b.is_available()}
