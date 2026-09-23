"""Intervals, `no_overlap` and `cumulative` (IR version 2) mean what the IR says, on CP-SAT.

An interval ties a start and an end variable, `end = start + size`, unless
its presence is 0 -- then it does not happen and ties nothing. `no_overlap`
keeps the intervals it ranges over apart; `cumulative` keeps the demands of
those running at any moment within a capacity. CP-SAT holds all three
natively; every other backend is refused with the reason.

The equivalence suite follows the roadmap's rule for any new construct
(§6.1): seeded random models checked against every placement tried, by code
that shares nothing with the compiler or the adapter.
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.solve import compile_model
from app.solve.backends import NoBackend, REGISTRY, by_name, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported, slack_by_constraint
from app.solve.convexity import refine
from app.solve.result import Solution
from app.solve.sandbox import explain_in_child
from app.solve.service import _assignments, patched, solve_compiled

JOB = [{"index": "j", "set": "job"}]


def _data(sizes: dict[str, int | float], **parameters) -> dict:
    rows = {"duration": [{"job": j, "value": v} for j, v in sizes.items()]}
    for name, values in parameters.items():
        rows[name] = [{"job": j, "value": v} for j, v in values.items()]
    return {
        "sets": {"job": [{"id": j} for j in sizes]},
        "parameters": rows,
        "parameter_defaults": {},
        "relationships": {},
    }


def _ir(rule: dict, *, horizon: int = 100, optional: bool = False, goal=None, rules=(), extra_parameters=()) -> dict:
    """Jobs on one resource, `finish[j] <= makespan`, minimise the makespan
    (or `goal`)."""
    job = {"index": ["job"]}
    variables = {
        "begin": {**job, "domain": "integer", "lower": 0, "upper": horizon},
        "finish": {**job, "domain": "integer", "lower": 0, "upper": horizon},
        "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": horizon},
        "task": {**job, "domain": "interval", "start": "begin", "end": "finish", "size": "duration"},
    }
    if optional:
        variables["done"] = {**job, "domain": "binary"}
        variables["task"]["presence"] = "done"
    return {
        "version": 2,
        "sets": ["job"],
        "parameters": {"duration": {"index": ["job"]}, **{p: {"index": ["job"]} for p in extra_parameters}},
        "variables": variables,
        "constraints": [
            {"id": "c_machine", **rule, "severity": "hard"},
            {"id": "c_makespan", "forall": JOB, "left": {"var": "finish", "index": ["j"]}, "relation": "<=",
             "right": {"var": "makespan", "index": []}, "severity": "hard"},
            *rules,
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1,
                                                      "expression": goal or {"var": "makespan", "index": []}}]},
    }


TASK = {"var": "task", "index": ["j"]}
NO_OVERLAP = {"no_overlap": {"interval": TASK, "over": JOB}}


def _cumulative(capacity: int, demand=None) -> dict:
    return {"cumulative": {"interval": TASK, "over": JOB, "demand": demand or {"const": 1},
                           "capacity": {"const": capacity}}}


def _solve(ir, data, backend="cp-sat"):
    compiled = compile_model(ir, data)
    found = refine(classify(ir, data), compiled)
    choose(found, backend)
    return solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)[0], compiled


# -- hand-worked -----------------------------------------------------------------


def test_two_jobs_on_one_machine_end_at_the_sum_of_their_sizes():
    """Sizes 3 and 4 may not overlap: one after the other, 7."""
    result, _ = _solve(_ir(NO_OVERLAP), _data({"a": 3, "b": 4}))
    assert (result.status, result.objective) == ("optimal", 7)
    a = (result.assignments[("begin", ("a",))], result.assignments[("finish", ("a",))])
    b = (result.assignments[("begin", ("b",))], result.assignments[("finish", ("b",))])
    assert a[1] - a[0] == 3 and b[1] - b[0] == 4
    assert a[1] <= b[0] or b[1] <= a[0]


def test_a_crew_of_two_runs_three_unit_jobs_in_two_rounds():
    """Three jobs of size 2, each needing 1 of a capacity of 2: two run at
    once, the third after -- 4, not 2 (all at once) nor 6 (one at a time)."""
    result, _ = _solve(_ir(_cumulative(2)), _data({"a": 2, "b": 2, "c": 2}))
    assert (result.status, result.objective) == ("optimal", 4)


def test_a_demand_read_from_the_data():
    """Capacity 3; a needs 2, b and c need 2 and 1, all size 2: a with c
    (3), then b -- 4. b with c would also be 3; a and b together are 4, too
    many, so no order finishes in 2."""
    ir = _ir(_cumulative(3, {"par": "crew", "index": ["j"]}), extra_parameters=["crew"])
    result, _ = _solve(ir, _data({"a": 2, "b": 2, "c": 2}, crew={"a": 2, "b": 2, "c": 1}))
    assert (result.status, result.objective) == ("optimal", 4)


def test_an_optional_job_is_dropped_when_it_costs_more_than_it_earns():
    """Makespan - 10 done[a] - 3 done[b], sizes 3 and 4 on one machine:
    both done is 7 - 13 = -6; a alone is 3 - 10 = -7; b alone 4 - 3 = 1;
    neither 0. So a alone, -7 -- b's 3 does not pay for its 4."""
    goal = {"add": [
        {"var": "makespan", "index": []},
        {"sum": {"mul": [{"const": -1}, {"mul": [{"par": "reward", "index": ["j"]}, {"var": "done", "index": ["j"]}]}]},
         "over": JOB},
    ]}
    ir = _ir(NO_OVERLAP, optional=True, goal=goal, extra_parameters=["reward"])
    result, _ = _solve(ir, _data({"a": 3, "b": 4}, reward={"a": 10, "b": 3}))
    assert (result.status, result.objective) == ("optimal", -7)
    assert result.chosen("done") == [("a",)]


def test_an_absent_job_ties_nothing():
    """Horizon 5 cannot hold 3 + 4 in sequence; with b optional the model
    is feasible (b absent), without it infeasible."""
    goal = {"sum": {"mul": [{"const": -1}, {"var": "done", "index": ["j"]}]}, "over": JOB}
    result, _ = _solve(_ir(NO_OVERLAP, horizon=5, optional=True, goal=goal), _data({"a": 3, "b": 4}))
    assert (result.status, result.objective) == ("optimal", -1)
    result, _ = _solve(_ir(NO_OVERLAP, horizon=5), _data({"a": 3, "b": 4}))
    assert result.status == "infeasible"


def test_a_conflict_names_the_scheduling_rule():
    """3 + 4 in a horizon of 5 on one machine: `c_machine` alone cannot
    hold -- the makespan rule is not part of it."""
    ir = _ir(NO_OVERLAP, horizon=5)
    compiled = compile_model(ir, _data({"a": 3, "b": 4}))
    conflict = explain_in_child(backend="cp-sat", compiled=compiled, probe_seconds=5, should_stop=None, on_progress=None)
    assert conflict.rules == ["c_machine"] and conflict.minimal


def test_a_rule_per_instance_of_its_forall():
    """Jobs of 3, 4 and 5 each go to one of two machines (task[j, m] is
    present where assign[j, m]); forall m, no_overlap over the jobs. The
    best split is {5} and {3, 4}: 7 -- {4}{3, 5} is 8, {3}{4, 5} 9."""
    both = ["job", "machine"]
    jm = ["j", "m"]
    ir = {
        "version": 2,
        "sets": both,
        "parameters": {"duration": {"index": both}},
        "variables": {
            "begin": {"index": both, "domain": "integer", "lower": 0, "upper": 50},
            "finish": {"index": both, "domain": "integer", "lower": 0, "upper": 50},
            "assign": {"index": both, "domain": "binary"},
            "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": 50},
            "task": {"index": both, "domain": "interval", "start": "begin", "end": "finish",
                     "size": "duration", "presence": "assign"},
        },
        "constraints": [
            {"id": "c_machine", "forall": [{"index": "m", "set": "machine"}],
             "no_overlap": {"interval": {"var": "task", "index": jm}, "over": JOB}, "severity": "hard"},
            {"id": "c_one_machine", "forall": JOB,
             "left": {"sum": {"var": "assign", "index": jm}, "over": [{"index": "m", "set": "machine"}]},
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_makespan", "forall": [*JOB, {"index": "m", "set": "machine"}],
             "left": {"var": "finish", "index": jm}, "relation": "<=",
             "right": {"var": "makespan", "index": []}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "makespan", "index": []}}]},
    }
    sizes = {"a": 3, "b": 4, "c": 5}
    data = {
        "sets": {"job": [{"id": j} for j in sizes], "machine": [{"id": "m1"}, {"id": "m2"}]},
        "parameters": {"duration": [{"job": j, "machine": m, "value": v} for j, v in sizes.items() for m in ("m1", "m2")]},
        "parameter_defaults": {},
        "relationships": {},
    }
    result, compiled = _solve(ir, data)
    assert (result.status, result.objective) == ("optimal", 7)
    rules = [(c.id, c.index, len(c.schedule.members)) for c in compiled.constraints if c.schedule]
    assert rules == [("c_machine", {"m": "m1"}, 3), ("c_machine", {"m": "m2"}, 3)]
    alone = [j for j, m in result.chosen("assign") if [m2 for j2, m2 in result.chosen("assign") if m2 == m] == [m]]
    assert alone == ["c"]


def test_a_filter_narrows_which_intervals_a_rule_is_over():
    """Two rules filtered by the job's machine attribute: a and b (3, 4)
    share m1 and finish at 7; c (5) is alone on m2 -- 7, not 12."""
    ir = _ir(NO_OVERLAP)
    ir["constraints"][0] = {"id": "c_m1", "no_overlap": {"interval": TASK, "over": [
        {"index": "j", "set": "job", "where": [{"attr": "machine", "op": "=", "value": "m1"}]}]}, "severity": "hard"}
    ir["constraints"].append({"id": "c_m2", "no_overlap": {"interval": TASK, "over": [
        {"index": "j", "set": "job", "where": [{"attr": "machine", "op": "=", "value": "m2"}]}]}, "severity": "hard"})
    data = _data({"a": 3, "b": 4, "c": 5})
    for row, machine in zip(data["sets"]["job"], ("m1", "m1", "m2")):
        row["machine"] = machine
    result, compiled = _solve(ir, data)
    assert (result.status, result.objective) == ("optimal", 7)
    assert [(c.id, len(c.schedule.members)) for c in compiled.constraints if c.schedule] == [("c_m1", 2), ("c_m2", 1)]


# -- what is refused, and where ---------------------------------------------------------


def test_every_other_backend_is_refused_with_the_reason():
    ir = _ir(NO_OVERLAP)
    data = _data({"a": 3, "b": 4})
    compiled = compile_model(ir, data)
    found = refine(classify(ir, data), compiled)
    assert "scheduling" in found.needs and found.model_class == "IP"
    assert choose(found)[0].name == "cp-sat"
    for backend in REGISTRY:
        if backend.name == "cp-sat":
            continue
        with pytest.raises(NoBackend, match="solved by CP-SAT"):
            choose(found, backend.name)
        # And were one forced through, it would say so rather than answer as
        # if the rule were not there.
        if backend.is_available():
            with pytest.raises(Unsupported, match="holds no scheduling rule"):
                solve_compiled(backend, compiled, time_limit=5)


def test_an_interval_with_no_rule_still_needs_cp_sat():
    ir = _ir(NO_OVERLAP)
    ir["constraints"] = ir["constraints"][1:]
    compiled = compile_model(ir, _data({"a": 3, "b": 4}))
    found = refine(classify(ir, _data({"a": 3, "b": 4})), compiled)
    assert "scheduling" in found.needs
    result, _ = solve_compiled(by_name("cp-sat"), compiled, time_limit=5)
    # Both run at once from 0: the longer, 4.
    assert (result.status, result.objective) == ("optimal", 4)


def test_a_softened_scheduling_rule_is_refused_not_ignored():
    ir = patched(_ir(NO_OVERLAP), {"soften": {"c_machine": 5}})
    with pytest.raises(Unsupported, match="can only be kept or disabled"):
        compile_model(ir, _data({"a": 3, "b": 4}))


def test_a_disabled_scheduling_rule_lets_the_jobs_overlap():
    ir = patched(_ir(NO_OVERLAP), {"disable": ["c_machine"]})
    result, _ = _solve(ir, _data({"a": 3, "b": 4}))
    assert result.objective == 4


def test_a_fractional_size_is_refused_by_name():
    with pytest.raises(Unsupported, match=r"task\[a\] is 2.5"):
        compile_model(_ir(NO_OVERLAP), _data({"a": 2.5, "b": 4}))


def test_a_fractional_demand_is_refused_by_name():
    ir = _ir(_cumulative(3, {"par": "crew", "index": ["j"]}), extra_parameters=["crew"])
    with pytest.raises(Unsupported, match="demand of 'c_machine' comes to 1.5"):
        compile_model(ir, _data({"a": 2, "b": 2}, crew={"a": 1.5, "b": 1}))


def test_intervals_are_not_reported_as_decisions_and_have_no_slack():
    compiled = compile_model(_ir(NO_OVERLAP), _data({"a": 3, "b": 4}))
    assert "task" not in compiled.var_index_sets
    result = Solution(status="optimal", optimal=True, objective=7, wall_seconds=0, solver="t",
                      assignments={("begin", ("b",)): 3, ("finish", ("a",)): 3, ("finish", ("b",)): 7,
                                   ("makespan", ()): 7})
    assert _assignments(compiled, result) == {"begin": [["b"]], "finish": [["a"], ["b"]], "makespan": [[]]}
    assert set(slack_by_constraint(compiled, result.assignments)) == {"c_makespan"}


# -- random models against every placement ----------------------------------------------------

JOBS = ("a", "b", "c")


def _random(seed: int):
    rnd = random.Random(seed)
    horizon = rnd.randint(4, 7)
    sizes = {j: rnd.randint(1, 3) for j in JOBS}
    weights = {j: rnd.randint(0, 3) for j in JOBS}
    rewards = {j: rnd.randint(0, 8) for j in JOBS}
    optional = rnd.random() < 0.5
    if rnd.random() < 0.5:
        rule = NO_OVERLAP
        demands, capacity = {j: 1 for j in JOBS}, 1
    else:
        demands = {j: rnd.randint(1, 2) for j in JOBS}
        capacity = rnd.randint(2, 3)
        rule = _cumulative(capacity, {"par": "crew", "index": ["j"]})
    precedence = rnd.random() < 0.5
    goal = {"sum": {"mul": [{"par": "weight", "index": ["j"]}, {"var": "finish", "index": ["j"]}]}, "over": JOB}
    if optional:
        goal = {"add": [goal, {"sum": {"mul": [{"const": -1}, {"mul": [
            {"par": "reward", "index": ["j"]}, {"var": "done", "index": ["j"]}]}]}, "over": JOB}]}
    rules = []
    if precedence:
        # a before b: finish[a] <= begin[b] -- through the start and end
        # variables, as any linear rule reads an interval.
        rules.append({"id": "c_a_first", "left": {"sum": {"mul": [{"par": "is_a", "index": ["j"]},
                                                                 {"var": "finish", "index": ["j"]}]}, "over": JOB},
                      "relation": "<=",
                      "right": {"sum": {"mul": [{"par": "is_b", "index": ["j"]},
                                                {"var": "begin", "index": ["j"]}]}, "over": JOB},
                      "severity": "hard"})
    ir = _ir(rule, horizon=horizon, optional=optional, goal=goal, rules=rules,
             extra_parameters=["crew", "weight", "reward", "is_a", "is_b"])
    ir["constraints"] = [c for c in ir["constraints"] if c["id"] != "c_makespan"]
    del ir["variables"]["makespan"]
    data = _data(sizes, crew=demands, weight=weights, reward=rewards,
                 is_a={"a": 1, "b": 0, "c": 0}, is_b={"a": 0, "b": 1, "c": 0})
    facts = dict(horizon=horizon, sizes=sizes, weights=weights, rewards=rewards, optional=optional,
                 demands=demands, capacity=capacity, precedence=precedence)
    return ir, data, facts


def _best(f) -> int | None:
    """Every start of every job, every presence, checked directly: the
    intervals hold, the resource is never over its capacity at any moment,
    and a before b when asked. An absent job's start and finish are free,
    so its finish costs nothing (weights are >= 0) -- but its variables must
    still fit the horizon, which 0 always does."""
    h = f["horizon"]
    best = None
    presences = itertools.product((0, 1), repeat=3) if f["optional"] else [(1, 1, 1)]
    for present in presences:
        ranges = [range(0, h - f["sizes"][j] + 1) if on else [None] for j, on in zip(JOBS, present)]
        for starts in itertools.product(*ranges):
            placed = {j: s for j, s in zip(JOBS, starts) if s is not None}
            if any(sum(f["demands"][j] for j, s in placed.items() if s <= t < s + f["sizes"][j]) > f["capacity"]
                   for t in range(h)):
                continue
            if f["precedence"]:
                # An absent a or b is free: begin[b] may be h, finish[a] 0.
                a_end = placed["a"] + f["sizes"]["a"] if "a" in placed else 0
                b_start = placed["b"] if "b" in placed else h
                if a_end > b_start:
                    continue
            score = sum(f["weights"][j] * (s + f["sizes"][j]) for j, s in placed.items())
            if f["optional"]:
                score -= sum(f["rewards"][j] for j in placed)
            if best is None or score < best:
                best = score
    return best


@pytest.mark.parametrize("seed", range(40))
def test_cp_sat_agrees_with_every_placement_tried(seed):
    ir, data, facts = _random(seed)
    expected = _best(facts)
    result, _ = _solve(ir, data)
    if expected is None:
        assert result.status == "infeasible", seed
    else:
        assert (result.status, result.objective) == ("optimal", expected), (seed, facts)


def test_the_random_suite_is_not_one_easy_case():
    kinds, optional, infeasible = set(), set(), 0
    for seed in range(40):
        ir, _, facts = _random(seed)
        kinds.add(next(k for k in ("no_overlap", "cumulative") if k in ir["constraints"][0]))
        optional.add(facts["optional"])
        infeasible += _best(facts) is None
    assert kinds == {"no_overlap", "cumulative"} and optional == {True, False}
    assert 0 < infeasible < 40
