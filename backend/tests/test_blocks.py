"""Separable blocks, found (app.solve.blocks): what links two decisions,
when a split is refused, and that the blocks together are the model.

Worked by hand: two knapsacks that share nothing. The first (weights 5, 4,
3; values 10, 7, 5; capacity 8) is best with 5 + 3: 15. The second
(weights 2, 2, 3; values 3, 3, 4; capacity 4) with 2 + 2: 6. Together, 21.
"""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.blocks import Block, blocks, refusal, split
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.service import solve_compiled

SACKS = {
    "a": {"capacity": 8, "items": {"a1": (5, 10), "a2": (4, 7), "a3": (3, 5)}},
    "b": {"capacity": 4, "items": {"b1": (2, 3), "b2": (2, 3), "b3": (3, 4)}},
}


def _knapsacks(sacks=SACKS, **objective):
    """One `forall sack` rule, each sack's items reached through `holds`:
    one rule in the document, one row per sack -- and the rows are the blocks."""
    items = [{"id": key, "weight": w, "value": v} for spec in sacks.values() for key, (w, v) in spec["items"].items()]
    ir = {
        "version": 2,
        "sets": ["sack", "item"],
        "relationships": ["holds"],
        "parameters": {},
        "variables": {"take": {"index": ["item"], "domain": "binary"}},
        "constraints": [{
            "id": "c_fits",
            "forall": [{"index": "s", "set": "sack"}],
            "left": {"sum": {"mul": [{"attr": {"of": "i", "name": "weight"}}, {"var": "take", "index": ["i"]}]},
                     "over": [{"index": "i", "set": "item", "via": {"rel": "holds", "from": "s"}}]},
            "relation": "<=",
            "right": {"attr": {"of": "s", "name": "capacity"}},
            "severity": "hard",
        }],
        "objective": {"sense": "maximize", **objective, "terms": [{"id": "o_value", "weight": 1, "expression": {
            "sum": {"mul": [{"attr": {"of": "i", "name": "value"}}, {"var": "take", "index": ["i"]}]},
            "over": [{"index": "i", "set": "item"}]}}]},
    }
    data = {
        "sets": {"sack": [{"id": s, "capacity": spec["capacity"]} for s, spec in sacks.items()], "item": items},
        "parameters": {}, "parameter_defaults": {},
        "relationships": {"holds": [{"from": s, "to": key} for s, spec in sacks.items() for key in spec["items"]]},
    }
    return ir, data


def _pieces_solved(compiled: Compiled, backend: str = "highs"):
    results = [solve_compiled(by_name(backend), piece, time_limit=10, seed=1)[0] for piece in split(compiled, blocks(compiled))]
    return results


def test_two_knapsacks_are_two_blocks_whose_optima_add_up():
    ir, data = _knapsacks()
    compiled = compile_model(ir, data)
    found = blocks(compiled)
    assert sorted(len(b.variables) for b in found) == [3, 3]
    assert sorted(len(b.rows) for b in found) == [1, 1]
    results = _pieces_solved(compiled)
    assert [r.status for r in results] == ["optimal", "optimal"]
    assert sorted(round(float(r.objective)) for r in results) == [6, 15]
    whole, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    assert round(float(whole.objective)) == 21 == sum(round(float(r.objective)) for r in results)


# -- what links ---------------------------------------------------------------------------------------


def _vars(*names, domain="integer", low=0, high=5):
    return {(n, ()): Variable((n, ()), domain, Decimal(low), Decimal(high)) for n in names}


def _row(id, coeffs, relation="<=", rhs=5, **extra):
    return Constraint(id, {}, Linear(coeffs={(k, ()): Decimal(c) for k, c in coeffs.items()}), relation,
                      Linear(const=Decimal(rhs)), **extra)


def _model(variables, rows, **extra):
    return Compiled(variables=variables, constraints=rows, objective=Linear(), sense="minimize",
                    var_index_sets={}, **extra)


def _groups(compiled):
    return sorted(sorted(k[0] for k in b.variables) for b in blocks(compiled))


def test_a_shared_decision_makes_one_block():
    compiled = _model(_vars("x", "y", "z"), [_row("c1", {"x": 1, "y": 1}), _row("c2", {"y": 1, "z": 1})])
    assert _groups(compiled) == [["x", "y", "z"]]


def test_a_decision_no_rule_reads_is_a_block_of_its_own():
    compiled = _model(_vars("x", "y", "z"), [_row("c1", {"x": 1, "y": 1})])
    assert _groups(compiled) == [["x", "y"], ["z"]]


@pytest.mark.parametrize(
    "extra, rows",
    [
        # A product in the goal.
        ({"objective_quadratic": {(("x", ()), ("z", ())): Decimal(1)}}, []),
        # A product in a rule.
        ({}, [_row("c", {}, quadratic={(("x", ()), ("z", ())): Decimal(1)})]),
        # A rule switched by one decision and reading the other.
        ({}, [_row("c", {"z": 1}, when=(("x", ()), 1))]),
    ],
    ids=["goal-product", "rule-product", "switch"],
)
def test_what_links_two_decisions(extra, rows):
    variables = _vars("x", "z")
    compiled = _model(variables, rows, **extra)
    assert _groups(compiled) == [["x", "z"]]


def test_a_curve_and_a_function_tie_their_argument_to_their_stand_in():
    from app.solve.compile import FnDef, PwlDef

    variables = _vars("x", "__pwl", "y", "__fn", domain="continuous")
    compiled = _model(
        variables, [],
        pwl=[PwlDef(("x", ()), ("__pwl", ()), ((Decimal(0), Decimal(0)), (Decimal(5), Decimal(5))))],
        functions=[FnDef("exp", Linear(coeffs={("y", ()): Decimal(1)}), ("__fn", ()))],
    )
    assert _groups(compiled) == [["__fn", "y"], ["__pwl", "x"]]


def test_intervals_in_one_scheduling_rule_are_one_block():
    ir = {
        "version": 2, "sets": [], "parameters": {},
        "variables": {
            **{f"{p}_{n}": {"index": [], "domain": "integer", "lower": 0, "upper": 20} for n in "ab" for p in ("s", "e")},
            **{f"t_{n}": {"index": [], "domain": "interval", "start": f"s_{n}", "end": f"e_{n}", "size": 3} for n in "ab"},
            "lone": {"index": [], "domain": "integer", "lower": 0, "upper": 1},
        },
        "constraints": [],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "e_a", "index": []}}]},
    }
    apart = compile_model(ir, {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}})
    # Each interval ties its own start and end; nothing ties the two.
    assert _groups(apart) == [["e_a", "s_a"], ["e_b", "s_b"], ["lone"]]
    # A no_overlap over both ties them into one block.
    from app.solve.compile import Schedule

    rule = Constraint("c_one_room", {}, Linear(), "<=", Linear(),
                      schedule=Schedule("no_overlap", ((("t_a", ()), 1), (("t_b", ()), 1))))
    together = replace(apart, constraints=[rule])
    assert _groups(together) == [["e_a", "e_b", "s_a", "s_b"], ["lone"]]
    assert [b.rows for b in blocks(together)][0] == (0,)


def test_a_rule_with_nothing_to_decide_goes_with_the_first_block():
    compiled = _model(_vars("x", "y"), [_row("c1", {"x": 1}), _row("c_never", {}, ">=", 1), _row("c2", {"y": 1})])
    found = blocks(compiled)
    assert len(found) == 2 and 1 in found[0].rows
    assert sum(len(b.rows) for b in found) == 3


# -- when a split is refused ----------------------------------------------------------------------------


def test_the_refusals_name_why():
    ir, data = _knapsacks()
    compiled = compile_model(ir, data)
    assert refusal(compiled) is None
    assert "lexicographic" in refusal(compile_model(*_knapsacks(mode="lex")))
    assert "trade-off" in refusal(compiled, pareto=True)
    assert "robust" in refusal(compiled, robust=True)
    soft_ir, soft_data = _knapsacks()
    soft_ir["constraints"][0]["severity"] = "soft"
    soft_ir["constraints"][0]["weight"] = 5
    assert "soft rules" in refusal(compile_model(soft_ir, soft_data))


def test_symmetry_rows_are_refused_only_when_they_would_be_added():
    compiled = _model(_vars("x", "y"), [], symmetry=[("item", ("a", "b"))])
    assert refusal(compiled) is None
    assert "symmetry" in refusal(compiled, symmetry=True)


# -- the blocks together are the model ------------------------------------------------------------------


def _random(seed: int) -> Compiled:
    """Two to four blocks of two or three whole-number decisions each."""
    rnd = random.Random(seed)
    variables, rows, goal = {}, [], {}
    for b in range(rnd.randint(2, 4)):
        keys = [(f"x{b}", (str(i),)) for i in range(rnd.randint(2, 3))]
        for key in keys:
            variables[key] = Variable(key, "integer", Decimal(rnd.choice([0, -1])), Decimal(rnd.randint(2, 4)))
            goal[key] = Decimal(rnd.randint(-3, 3))
        for r in range(2):
            coeffs = {key: Decimal(rnd.randint(-2, 3)) for key in rnd.sample(keys, 2)}
            rows.append(Constraint(f"r{b}_{r}", {}, Linear(coeffs=coeffs), rnd.choice(["<=", ">="]),
                                   Linear(const=Decimal(rnd.randint(-2, 5)))))
    rnd.shuffle(rows)
    return Compiled(variables=variables, constraints=rows, objective=Linear(coeffs=goal, const=Decimal(rnd.randint(0, 3))),
                    sense=rnd.choice(["minimize", "maximize"]), var_index_sets={})


@pytest.mark.parametrize("seed", range(40))
def test_the_pieces_are_the_model(seed):
    compiled = _random(seed)
    found = blocks(compiled)
    pieces = split(compiled, found)
    # Every decision and every row in exactly one piece; the goal shared out.
    assert sorted(k for p in pieces for k in p.variables) == sorted(compiled.variables)
    assert sorted(r.id for p in pieces for r in p.constraints) == sorted(r.id for r in compiled.constraints)
    assert sum(len(p.objective.coeffs) for p in pieces) == len(compiled.objective.coeffs)
    assert sum(p.objective.const for p in pieces) == compiled.objective.const
    # And their best answers add up to the model's -- or one piece has none.
    whole, _ = solve_compiled(by_name("cp-sat"), compiled, time_limit=10, seed=1)
    parts = [solve_compiled(by_name("cp-sat"), p, time_limit=10, seed=1)[0] for p in pieces]
    if whole.status == "infeasible":
        assert "infeasible" in {p.status for p in parts}, seed
    else:
        assert whole.status == "optimal" and all(p.status == "optimal" for p in parts), seed
        assert sum(Fraction(str(p.objective)) for p in parts) == Fraction(str(whole.objective)), seed


def test_the_random_models_split_and_are_not_one_easy_case():
    assert all(len(blocks(_random(seed))) >= 2 for seed in range(40))
    statuses = {solve_compiled(by_name("cp-sat"), _random(seed), time_limit=10, seed=1)[0].status for seed in range(40)}
    assert statuses == {"optimal", "infeasible"}


# -- solved: at once, and put together (14b) --------------------------------------------------------------

from app.solve.blocks import MAX_PARALLEL, grouped, merge, worth_splitting  # noqa: E402
from app.solve.blocks import solve as solve_blocks  # noqa: E402
from app.solve.result import Solution  # noqa: E402


def _answer(status, objective=None, bound=None, **extra):
    return Solution(status=status, optimal=status == "optimal", objective=objective,
                    assignments=extra.pop("assignments", {}), wall_seconds=extra.pop("wall", 1.0),
                    solver="s", best_bound=bound, **extra)


EMPTY = _model({}, [])


@pytest.mark.parametrize(
    "statuses, expected",
    [
        (["optimal", "infeasible", "unbounded"], "infeasible"),
        (["unbounded", "feasible"], "unbounded"),
        (["optimal", "unknown"], "unknown"),
        (["optimal", "feasible"], "feasible"),
        (["optimal", "optimal"], "optimal"),
    ],
)
def test_the_status_is_the_worst(statuses, expected):
    results = [_answer(s, 1 if s in ("optimal", "feasible") else None, 1) for s in statuses]
    merged = merge([EMPTY] * len(results), results, optimal_gap=1e-6)
    assert merged.status == expected
    if expected not in ("optimal", "feasible"):
        assert merged.objective is None and merged.assignments == {}


def test_goal_and_bound_add_up_and_the_bound_only_when_every_piece_has_one():
    a = _answer("optimal", 3, 3, assignments={("x", ()): 1}, wall=2.0)
    b = _answer("feasible", 4, 6, assignments={("y", ()): 2}, wall=5.0)
    merged = merge([EMPTY, EMPTY], [a, b], optimal_gap=1e-6)
    assert (merged.status, merged.objective, merged.best_bound, merged.wall_seconds) == ("feasible", 7, 9, 5.0)
    assert merged.assignments == {("x", ()): 1, ("y", ()): 2}
    # A piece found but not proven, with no bound of its own, leaves the whole without one ...
    assert merge([EMPTY, EMPTY], [a, _answer("feasible", 4, None)], optimal_gap=1e-6).best_bound is None
    # ... while a piece proven optimal is its own bound, given or not (a decision fixed by its own
    # rule has nothing in the goal and comes back without one: queue R15b's 156-piece route model).
    assert merge([EMPTY, EMPTY], [b, _answer("optimal", 4, None)], optimal_gap=1e-6).best_bound == 10


def test_a_piece_whose_goal_is_only_its_constant_counts_its_constant():
    constant = replace(EMPTY, objective=Linear(const=Decimal(5)))
    merged = merge([constant, EMPTY], [_answer("optimal", None, None), _answer("optimal", 2, 2)], optimal_gap=1e-6)
    assert merged.objective == 7


def test_optimal_pieces_whose_bounds_do_not_meet_are_not_called_optimal():
    merged = merge([EMPTY], [_answer("optimal", 100, 99)], optimal_gap=1e-6)
    assert merged.status == "feasible"


def test_blocks_beyond_the_limit_are_packed_largest_first_into_the_lightest_group():
    parts = [Block(frozenset({(f"b{i}", (str(j),)) for j in range(size)}), (i,)) for i, size in enumerate([5, 1, 4, 2, 3, 1])]
    packed = grouped(parts, 3)
    assert sorted(len(g.variables) for g in packed) == [5, 5, 6]
    assert sorted(r for g in packed for r in g.rows) == list(range(6))
    assert len(grouped(parts, 10)) == 6 and MAX_PARALLEL == 4


def _run_one(backend):
    def run(piece, workers, hint):
        return solve_compiled(by_name(backend), piece, time_limit=10, seed=1, workers=workers, hint=hint)
    return run


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("backend", ["cp-sat", "highs"])
def test_solved_at_once_is_the_monolithic_answer(seed, backend):
    compiled = _random(seed)
    whole, _ = solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)
    merged, _, record = solve_blocks(compiled, blocks(compiled), _run_one(backend), workers=8, optimal_gap=1e-6)
    assert merged.status == whole.status, seed
    if whole.status == "optimal":
        assert Fraction(str(merged.objective)) == Fraction(str(whole.objective)), seed
        # The answer is an answer to the whole model.
        from app.solve.compile import slack_by_constraint

        assert all(v >= 0 for v in slack_by_constraint(compiled, merged.assignments).values()), seed
    assert record["blocks"] == len(blocks(compiled)) and record["groups"] <= MAX_PARALLEL


def test_a_piece_the_solver_leaves_empty_keeps_a_start_that_holds_and_only_then():
    """Benchmark, October 2026: a routing start covered the route's block, the solver ran out of time
    on it, and the run ended "unknown" with no plan."""
    from app.solve.result import Solution

    ir, data = _knapsacks()
    compiled = compile_model(ir, data)
    parts = blocks(compiled)
    a_keys = {key for key in compiled.variables if key[1] and key[1][0].startswith("a")}

    def gives_up_on_a(piece, workers, hint):
        if set(piece.variables) & a_keys:
            return Solution("unknown", False, None, {}, 1.0, "cp-sat"), None
        return solve_compiled(by_name("cp-sat"), piece, time_limit=10, seed=1, workers=workers)

    start = {("take", ("a1",)): 1, ("take", ("a2",)): 0, ("take", ("a3",)): 1}  # 5 + 3 fits 8: worth 15
    merged, _, record = solve_blocks(compiled, parts, gives_up_on_a, workers=2, optimal_gap=1e-6, hint=start)
    assert merged.status == "feasible" and round(float(merged.objective)) == 21
    assert record["started_from"] and "optimal" not in record["statuses"][record["started_from"][0]]

    too_heavy = {**start, ("take", ("a2",)): 1}  # 12 does not fit 8: not an answer
    merged, _, record = solve_blocks(compiled, parts, gives_up_on_a, workers=2, optimal_gap=1e-6, hint=too_heavy)
    assert merged.status == "unknown" and "started_from" not in record


# -- through a run ---------------------------------------------------------------------------------------

from sqlalchemy import text  # noqa: E402

from app.solve.service import claim_next, enqueue_run, execute_run  # noqa: E402
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: E402, F401


def _two_parts(mode=None):
    """max x + y + z + w: x + 2y <= 4 (x = 4 best: 4) and z + w <= 3 (3): 7."""
    var = {"domain": "integer", "lower": 0, "upper": 4}
    v = lambda n: {"var": n, "index": []}  # noqa: E731
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {n: {"index": [], **var} for n in "xyzw"},
        "constraints": [
            {"id": "c_first", "left": {"add": [v("x"), {"mul": [{"const": 2}, v("y")]}]}, "relation": "<=",
             "right": {"const": 4}, "severity": "hard"},
            {"id": "c_second", "left": {"add": [v("z"), v("w")]}, "relation": "<=", "right": {"const": 3},
             "severity": "hard"},
        ],
        "objective": {"sense": "maximize", **({"mode": mode} if mode else {}), "terms": [
            {"id": "o_first", "weight": 1, "expression": {"add": [v("x"), v("y")]}},
            {"id": "o_second", "weight": 1, "expression": {"add": [v("z"), v("w")]}}]},
    }


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


@pytest.mark.parametrize(
    "on, mode, record",
    [
        (True, None, {"blocks": 2, "groups": 2, "sizes": [2, 2], "statuses": ["optimal", "optimal"]}),
        (True, "lex", {"solved_whole": "a lexicographic goal is solved one term at a time across the whole model"}),
        (False, None, None),
    ],
    ids=["on", "on-but-lex", "off"],
)
def test_a_run_solves_its_blocks_at_once_only_when_the_setting_says_so(db, empty_queue, on, mode, record):
    domain = make_domain(db, "separable")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _two_parts(mode))
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value)"
                    " VALUES ('problem', :p, 'solve.separable', CAST(:v AS jsonb))"), {"p": problem, "v": "true" if on else "false"})
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=10.0, solver="highs")
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
        # A lexicographic run reports its first term (x + y = 4); weighted, the sum.
        assert outcome.status == "optimal" and outcome.objective == (4 if mode == "lex" else 7)
        assert params["separable"] is on
        if record is None:
            assert "blocks" not in params
        else:
            assert {k: params["blocks"][k] for k in record} == record
        assignments = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
        assert set(assignments) == {"x", "y", "z", "w"}
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_a_stray_decision_is_not_worth_a_split():
    lone = _model(_vars("x", "y", "z"), [_row("c1", {"x": 1, "y": 1})])
    assert len(blocks(lone)) == 2 and not worth_splitting(blocks(lone))
    two = _model(_vars("x", "y"), [_row("c1", {"x": 1}), _row("c2", {"y": 1})])
    assert worth_splitting(blocks(two))
