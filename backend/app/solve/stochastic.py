"""Two-stage stochastic programming by sample-average approximation (queue R7, roadmap Phase 15).

Some decisions are made **now**, before the uncertain data is known (stage 1:
how much to order, whom to roster); others **once it is known** (stage 2:
how much to sell, whom to call in). The best plan is the one whose cost,
averaged over the futures the data may bring, is least -- not the one that
is best for the average future.

**Where the futures come from.** A parameter declared uncertain within a range
(`uncertainty: {kind: interval, deviation}`) takes, in each sampled future,
each of its values times `1 + u * deviation`, `u` uniform in [-1, 1] and
drawn per value from a seeded generator: the same run draws the same
futures. (`{kind: scenarios}` asks for values per scenario, which nothing
stores yet, and is refused by name.)

**The extensive form.** Each future is the model compiled with its own values
(the compiler is linear in values, and deterministic in everything else).
Stage-1 decisions appear once, shared by every future; every other variable
-- stage-2 decisions, and the compiler's own auxiliaries -- is copied per
future; each future's rules read its own copies; a rule that reads only
stage-1 decisions and is the same in every future is kept once. The goal is
the average of the futures' goals. Its optimum is the best plan **for these
futures** -- an estimate of the true one, so the run claims `approximate`,
never proven best.

**Chance rules** (queue R8). A rule with `chance: {epsilon}` may fail in at
most that share of the futures: in the extensive form each of its instances
gets one switch per future (the rule holds while it is off -- a `when`, so a
backend without indicators writes it as a big-M from the declared bounds),
and at most `floor(in_sample(epsilon, N) * N)` of an instance's switches may
be on -- a share held below the asked one, so the plan keeps its promise on
fresh futures rather than only on the sampled ones (queue R8c). A chance
rule makes a model two-stage by itself: the plan must keep it in enough of
the futures, even with nothing decided later. Out of sample, how often each
chance rule actually held is recorded beside what was asked.

**Out of sample.** The plan is then held fixed and costed on fresh futures
(each solved for its best recourse): the mean and a 95% confidence interval
say what it is likely to cost, and how many futures it cannot meet at all.
"""

from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.solve.compile import Compiled, Constraint, Linear, Variable, VarKey, compile_model

#: Futures in the extensive form when a run asks for none in particular; the roadmap's ceiling.
MAX_SAMPLES = 50
#: Fresh futures the plan is costed on, at least.
OUT_OF_SAMPLE_MIN = 20
#: The share of the time the extensive form gets; the rest costs the plan out of sample.
EXTENSIVE_SHARE = 0.6
_SAMPLE = "#s"
_SWITCH = "__chance"
#: How many standard errors the in-sample share is held below the asked one (one-sided 95%).
CHANCE_MARGIN = 1.645


def in_sample(epsilon: float, futures: int) -> float:
    """The share a chance rule may fail in *among the sampled futures*, so that it fails in no more than
    `epsilon` of fresh ones: the asked share less CHANCE_MARGIN standard errors of a share estimated from
    `futures` draws (queue R8c). Solving at `epsilon` itself missed it: at 20 or 50 futures the rule held
    in 86-88% of fresh futures against 90% asked, and met it in 4 of 12 samples; held below, 96% and 12 of
    12 at 50 futures."""
    return max(0.0, epsilon - CHANCE_MARGIN * math.sqrt(epsilon * (1 - epsilon) / futures))


class NotStochastic(ValueError):
    """Why this model cannot be solved as a two-stage stochastic program, named."""


def second_stage(ir: dict[str, Any]) -> set[str]:
    return {name for name, spec in (ir.get("variables") or {}).items() if isinstance(spec, dict) and spec.get("stage") == 2}


def chance_rules(ir: dict[str, Any]) -> dict[str, float]:
    """rule id -> epsilon, for every rule with a chance."""
    return {c["id"]: float(c["chance"]["epsilon"]) for c in (ir.get("constraints") or [])
            if isinstance(c, dict) and isinstance(c.get("chance"), dict)}


def wanted(ir: dict[str, Any]) -> bool:
    """A two-stage question is asked: a decision waits for the data, or a rule may fail by chance."""
    return bool(second_stage(ir)) or bool(chance_rules(ir))


def uncertain(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: spec["uncertainty"] for name, spec in (ir.get("parameters") or {}).items()
            if isinstance(spec, dict) and isinstance(spec.get("uncertainty"), dict)}


def refusal(ir: dict[str, Any], compiled: Compiled) -> str | None:
    """None when the model is a two-stage program this solves, else why not."""
    if not wanted(ir):
        return "no decision waits for the data: mark the recourse decisions stage 2, or give a rule a chance"
    kinds = uncertain(ir)
    if not kinds:
        return "no data is uncertain: declare a parameter's range (uncertainty within a range)"
    by_scenario = sorted(n for n, spec in kinds.items() if spec.get("kind") == "scenarios")
    if by_scenario:
        return f"{', '.join(by_scenario)} varies by scenario, and no values per scenario are stored yet: declare a range"
    if compiled.objective_mode != "weighted":
        return "a goal in order of importance has no single expected value"
    if compiled.objective_quadratic or compiled.pwl or compiled.functions or compiled.intervals:
        return "the stochastic solve takes linear models: no products, curves, functions or intervals"
    if compiled.penalty_of or compiled.violations:
        return "soft rules in a stochastic model are not supported yet"
    for rule in compiled.constraints:
        if rule.chance is None:
            continue
        for key in (*rule.left.coeffs, *rule.right.coeffs):
            var = compiled.variables.get(key)
            if var is not None and var.default_upper:
                return (f"the chance rule {rule.id!r} reads {key[0]}, which has no declared upper bound: a rule "
                        "switched off by chance needs one, to know how far it may be broken")
    return None


def sample(data: dict[str, Any], ir: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """One future: each value of each parameter uncertain within a range, times `1 + u * deviation`."""
    drawn = copy.deepcopy(data)
    for name, spec in uncertain(ir).items():
        share = float(spec.get("deviation", 0))
        for row in drawn.get("parameters", {}).get(name, []):
            row["value"] = float(row["value"]) * (1 + rng.uniform(-1, 1) * share)
        if name in drawn.get("parameter_defaults", {}):
            drawn["parameter_defaults"][name] = float(drawn["parameter_defaults"][name]) * (1 + rng.uniform(-1, 1) * share)
    return drawn


def futures(ir: dict[str, Any], data: dict[str, Any], count: int, seed: int | str) -> list[Compiled]:
    return [compile_model(ir, sample(data, ir, random.Random(f"{seed}-{k}"))) for k in range(count)]


def _stage_one(compiled: Compiled, recourse: set[str]) -> set[VarKey]:
    return {key for key in compiled.variables if key[0] not in recourse and not key[0].startswith("__")}


def _renamed(form: Linear, rename: Callable[[VarKey], VarKey], scale: Decimal = Decimal(1)) -> Linear:
    return Linear(coeffs={rename(k): c * scale for k, c in form.coeffs.items()}, const=form.const * scale)


def extensive(samples: list[Compiled], recourse: set[str]) -> tuple[Compiled, set[VarKey]]:
    """The sampled futures as one model: stage 1 shared, the rest copied per future, the goal averaged."""
    first = samples[0]
    shared = _stage_one(first, recourse)
    weight = Decimal(1) / Decimal(len(samples))
    variables: dict[VarKey, Any] = {key: first.variables[key] for key in shared}
    constraints: list[Constraint] = []
    seen: set[tuple] = set()
    switches: dict[tuple, list[VarKey]] = {}
    coeffs: dict[VarKey, Decimal] = {}
    const = Decimal(0)
    for k, future in enumerate(samples):
        def rename(key: VarKey, k=k) -> VarKey:
            return key if key in shared else (key[0], (*key[1], f"{_SAMPLE}{k}"))

        for key, var in future.variables.items():
            if key not in shared:
                variables[rename(key)] = replace(var, key=rename(key))
        for rule in future.constraints:
            keys = {*rule.left.coeffs, *rule.right.coeffs}
            if rule.chance is not None:
                # One switch per instance per future: the rule holds while it is off.
                instance = (rule.id, tuple(sorted(rule.index.items())))
                switch: VarKey = (_SWITCH, (rule.id, *(v for _, v in instance[1]), f"{_SAMPLE}{k}"))
                variables[switch] = Variable(switch, "binary", Decimal(0), Decimal(1))
                switches.setdefault(instance, []).append(switch)
                constraints.append(replace(rule, left=_renamed(rule.left, rename), right=_renamed(rule.right, rename),
                                           index={**rule.index, "future": str(k)}, when=(switch, 0)))
                continue
            if keys <= shared:
                # The same in every future: kept once.
                signature = (rule.id, tuple(sorted(rule.index.items())), rule.relation,
                             tuple(sorted(rule.left.coeffs.items())), rule.left.const,
                             tuple(sorted(rule.right.coeffs.items())), rule.right.const)
                if signature in seen:
                    continue
                seen.add(signature)
            constraints.append(replace(rule, left=_renamed(rule.left, rename), right=_renamed(rule.right, rename),
                                       index={**rule.index, "future": str(k)}))
        goal = _renamed(future.objective, rename, weight)
        for key, c in goal.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) + c
        const += goal.const
    for (rule_id, index), keys in switches.items():
        epsilon = next(c.chance for c in first.constraints if c.id == rule_id)
        allowed = Decimal(math.floor(in_sample(float(epsilon), len(samples)) * len(samples) + 1e-9))
        constraints.append(Constraint(f"_chance_{rule_id}", dict(index), Linear(coeffs={key: Decimal(1) for key in keys}),
                                      "<=", Linear(const=allowed)))
    objective = Linear(coeffs=coeffs, const=const)
    return replace(first, variables=variables, constraints=constraints, objective=objective,
                   objective_terms=[objective], symmetry=[], empty_ranges=[]), shared


def _holds(rule: Constraint, values: dict[VarKey, Any]) -> bool:
    gap = float(rule.left.evaluated_at(values) - rule.right.evaluated_at(values))
    slack = 1e-6 * max(1.0, abs(float(rule.right.evaluated_at(values))))
    return {"<=": gap <= slack, ">=": gap >= -slack}.get(rule.relation, abs(gap) <= slack)


def fixed(future: Compiled, plan: dict[VarKey, Any], shared: set[VarKey]) -> Compiled:
    """A future with the plan's stage-1 decisions held at their values."""
    variables = dict(future.variables)
    for key in shared:
        if key in plan and key in variables:
            value = Decimal(str(plan[key]))
            variables[key] = replace(variables[key], lower=value, upper=value)
    return replace(future, variables=variables)


@dataclass
class Stochastic:
    solution: Any
    record: dict[str, Any]


def solve(ir: dict[str, Any], data: dict[str, Any], compiled: Compiled, run: Callable[[Compiled, float], Any], *,
          samples: int, time_limit: float, seed: int | None = None,
          should_stop: Callable[[], bool] | None = None) -> Stochastic:
    """`run(model, seconds) -> Solution` solves with the chosen backend. Raises `NotStochastic`."""
    why = refusal(ir, compiled)
    if why is not None:
        raise NotStochastic(why)
    started = time.monotonic()
    count = max(2, min(MAX_SAMPLES, int(samples)))
    recourse = second_stage(ir)
    base = seed if seed is not None else 0
    model, shared = extensive(futures(ir, data, count, f"in-{base}"), recourse)
    solved = run(model, max(1.0, EXTENSIVE_SHARE * time_limit))
    record: dict[str, Any] = {"samples": count, "stage_two": sorted(recourse), "expected": solved.objective,
                              "status": solved.status}
    if solved.objective is None:
        return Stochastic(solved, record)
    plan = {key: value for key, value in solved.assignments.items() if key in shared}

    fresh = futures(ir, data, max(OUT_OF_SAMPLE_MIN, count), f"out-{base}")
    each = max(0.2, (1 - EXTENSIVE_SHARE) * time_limit / len(fresh))
    costs, unmet = [], 0
    held: dict[str, int] = {rule_id: 0 for rule_id in chance_rules(ir)}
    for future in fresh:
        if should_stop and should_stop():
            break
        # A chance rule is what the plan is judged by here, not what it must meet.
        loose = replace(future, constraints=[c for c in future.constraints if c.chance is None])
        answer = run(fixed(loose, plan, shared), each)
        if answer.objective is None:
            unmet += 1
            continue
        costs.append(float(answer.objective))
        values = {**plan, **answer.assignments}
        for rule_id in held:
            rows = [c for c in future.constraints if c.id == rule_id]
            if all(_holds(c, values) for c in rows):
                held[rule_id] += 1
    if costs:
        mean = sum(costs) / len(costs)
        sd = math.sqrt(sum((c - mean) ** 2 for c in costs) / (len(costs) - 1)) if len(costs) > 1 else 0.0
        record["out_of_sample"] = {"futures": len(costs) + unmet, "mean": round(mean, 6),
                                   "ci95": round(1.96 * sd / math.sqrt(len(costs)), 6), "unmet": unmet}
    else:
        record["out_of_sample"] = {"futures": unmet, "mean": None, "ci95": None, "unmet": unmet}
    # The plan is the answer: what to decide now. Recourse is decided later, per future.
    if held:
        judged = max(1, len(costs))
        record["chance"] = {rule_id: {"asked": round(1 - epsilon, 6), "held": round(held[rule_id] / judged, 6),
                                      "held_in_sample": round(1 - in_sample(epsilon, count), 6)}
                            for rule_id, epsilon in chance_rules(ir).items()}
    # The run's time is the whole of it: the extensive form and the plan costed out of sample.
    return Stochastic(replace(solved, assignments=plan, best_bound=None,
                              wall_seconds=round(time.monotonic() - started, 3)), record)
