"""Before-the-solve steps, measured end to end: is each worth having on by default? (9 October 2026)

    python -m bench.pipeline --time-limit 30 --workers 8 --out pipeline.json
    python -m bench.pipeline --report pipeline.json

The steps a run may take before its solver starts -- the rows an on/off limit implies (`app.solve.strengthen`),
racing the model as written against the strengthened one, and the fixed-charge start (`app.solve.fixed_charge`) --
each help some models and only cost time on others. This runs every instance once per arm, with the backend the
rules choose, timing the whole of it (the step's own time included), as a run would:

- `base`: the solver alone;
- `strengthen`: the implied rows, then the strengthened model alone on all threads;
- `race`: the implied rows, then both forms at once on half the threads each (what a run does today);
- `start`: the fixed-charge start, handed to the solver;
- `all`: the start, then the race;
- `escalate`: the solver alone for a fifth of the time (2 to 30 s, as `app.solve.service` does with
  `solve.probe_first`); settled there, that is the answer, otherwise `all` with what it found as the start and
  the time left.

An arm whose step does not apply to the instance is not run (it would be `base` again). Each row is scored as the
learnt choices score a run (`app.solve.choices._score`): seconds to a proof, or the time allowed times (2 + gap).
`--report` compares every arm with `base`: wins and losses (10% either way), the geometric mean of the score
ratio, and any answer that disagrees with another proven one on the same instance (`wrong`).

The instances are the benchmark's families where a run's steps can apply, and the models these steps were built
on (facility location with and without capacities, lot sizing, multi-item lot sizing, capacitated network design,
a network that chooses its places): the defaults are decided across all of them, not on the ones they were made for.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import replace
from statistics import median
from typing import Any

ARMS = ("base", "strengthen", "race", "start", "all", "escalate")


def _grid_network(k: int, seed: int, *, prize: bool):
    """A k x k grid of places; links with a cost and a capacity; one or two sources; demands -- or, with
    `prize`, places worth something when fed and a few that must be."""
    from tests.test_join import _capacitated, _model

    rnd = random.Random(seed)
    places = [f"p{i}_{j}" for i in range(k) for j in range(k)]
    links = []
    for i in range(k):
        for j in range(k):
            if i + 1 < k:
                links.append((f"h{i}_{j}", f"p{i}_{j}", f"p{i + 1}_{j}", rnd.randint(10, 60)))
            if j + 1 < k:
                links.append((f"v{i}_{j}", f"p{i}_{j}", f"p{i}_{j + 1}", rnd.randint(10, 60)))
    sources = {f"p{k // 2}_{k // 2}"} if prize else {f"p{k // 3}_{k // 3}", f"p{2 * k // 3}_{2 * k // 3}"}
    need = {p: rnd.randint(1, 6) for p in places if p not in sources}
    cap = {l: rnd.choice([60, 120, 240] if prize else [80, 160, 320]) for l, *_ in links}
    unit = {l: rnd.randint(1, 3) for l, *_ in links}
    ir, data = _capacitated(places, links, sources, need, cap, unit=unit)
    if prize:
        values = {p: rnd.choice([0, 0, 30, 80, 150]) for p in places}
        required = set(rnd.sample(places, 3)) - sources
        u_ir, u_data = _model(places, links, sources=sources, use=True, prize=values, required=required)
        ir["variables"]["serve"] = u_ir["variables"]["serve"]
        ir["constraints"][0]["join"]["use"] = {"var": "serve", "index": ["p"]}
        for name in ("prize", "required"):
            ir["parameters"][name] = u_ir["parameters"][name]
            data["parameters"][name] = u_data["parameters"][name]
        ir["objective"]["terms"].append(next(t for t in u_ir["objective"]["terms"] if t["id"] == "o_prize"))
        ir["constraints"].append(next(c for c in u_ir["constraints"] if c["id"] == "c_required"))
    return ir, data


def instances() -> list[tuple[str, dict, dict]]:
    """(name, ir, data) for every instance measured."""
    from bench.families import generate
    from tests.test_benders import _facility
    from tests.test_fixed_charge import _lot_sizing
    from tests.test_strengthen import _multi_item, _uncapacitated

    out: list[tuple[str, dict, dict]] = []
    for family, size, count in (("facility", "M", 2), ("facility", "L", 1), ("facility_regions", "M", 1),
                                ("knapsack", "M", 2), ("rota", "M", 1), ("rota_rates", "M", 1),
                                ("feed_blend", "M", 1), ("load_balance", "M", 1), ("knapsack_depots", "M", 1)):
        for i in range(count):
            inst = generate(family, size, i)
            out.append((f"{family}-{size}-{i}", inst.ir, inst.data))
    for seed in (1, 2):
        out.append((f"ufl-50x200-{seed}", _uncapacitated(seed, 50, 200), {}))
    out.append(("ufl-100x400-1", _uncapacitated(1, 100, 400), {}))
    for seed in (1, 2):
        out.append((f"cfl-tight-20x60-{seed}", _facility(seed, 20, 60, tight=True), {}))
    for seed in (1, 2):
        out.append((f"lot-sizing-36-{seed}", _lot_sizing(seed, periods=36), {}))
    out.append(("multi-item-12x24-1", _multi_item(1, items=12, periods=24), {}))
    out.append(("multi-item-20x30-2", _multi_item(2, items=20, periods=30), {}))
    out.append(("network-design-12-1", *_grid_network(12, 1, prize=False)))
    out.append(("network-design-16-2", *_grid_network(16, 2, prize=False)))
    out.append(("network-prize-10-1", *_grid_network(10, 1, prize=True)))
    return out


def _score(status: str, seconds: float, gap: float | None, limit: float) -> float:
    from app.solve.choices import _score

    return _score({"status": status, "seconds": seconds, "gap": gap, "limit": limit})


def measure(name: str, ir: dict, data: dict, *, time_limit: float, workers: int, arms: tuple[str, ...]) -> list[dict]:
    from app.solve import compile_model, fixed_charge, race, strengthen
    from app.solve.backends import by_name, choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import solve_compiled
    from app.solve.warm import HINTED

    compiled = compile_model(ir, data)
    backend, _ = choose(refine(classify(ir, data), compiled))
    rows: list[dict] = []
    strengthenable = backend.name in ("highs", "scip") and strengthen.applies(compiled) is None
    startable = backend.name in HINTED and fixed_charge.applies(compiled) is None

    def solve(model, limit, share, hint=None, stop=None):
        result, _ = solve_compiled(backend, model, time_limit=max(1.0, limit), seed=1, workers=share, hint=hint,
                                   should_stop=stop)
        return result

    def raced(plain, strong, limit, hint):
        outcomes, record = race._all_at_once(
            ["as written", "with implied rows"],
            lambda n, secs, share, stop_others: solve(plain if n == "as written" else strong, secs, share, hint,
                                                       stop_others),
            limit, workers, race.DECISIVE)
        won = min(outcomes, key=lambda n: race._key(outcomes[n], compiled.sense))
        return outcomes[won], won

    for arm in arms:
        if arm in ("strengthen", "race") and not strengthenable:
            continue
        if arm == "start" and not startable:
            continue
        if arm == "all" and not (strengthenable and startable):
            continue
        if arm == "escalate" and not (strengthenable or startable):
            continue
        began = time.monotonic()
        extra: dict[str, Any] = {}
        hint = None
        left = time_limit
        if arm == "escalate":
            from app.solve.service import PROBE_FIRST_MAX_S, PROBE_FIRST_MIN_S, PROBE_FIRST_SHARE

            probe_s = min(PROBE_FIRST_MAX_S, max(PROBE_FIRST_MIN_S, PROBE_FIRST_SHARE * time_limit))
            probed = solve(compiled, probe_s, workers)
            extra["probe_status"] = probed.status
            if probed.status in race.DECISIVE:
                rows.append(_row(name, backend.name, arm, probed, time.monotonic() - began, time_limit, extra))
                continue
            hint = dict(probed.assignments) or None
        if arm in ("start", "all") or (arm == "escalate" and startable):
            started, record = fixed_charge.start(compiled, seconds=min(fixed_charge.CEILING, fixed_charge.SHARE * time_limit))
            extra["start_objective"] = record.get("objective")
            left = time_limit - (time.monotonic() - began)
            hint = started or hint
        model = compiled
        if arm in ("strengthen", "race", "all") or (arm == "escalate" and strengthenable):
            model, record = strengthen.strengthen(compiled, seconds=min(strengthen.CEILING, strengthen.SHARE * time_limit))
            extra["rows_added"] = record.get("added")
            left = time_limit - (time.monotonic() - began)
        if arm in ("race", "all", "escalate") and model is not compiled:
            result, extra["won"] = raced(compiled, model, left, hint)
        else:
            result = solve(model, left, workers, hint)
        rows.append(_row(name, backend.name, arm, result, time.monotonic() - began, time_limit, extra))
    return rows


def _row(name: str, backend: str, arm: str, result, seconds: float, time_limit: float, extra: dict) -> dict:
    gap = None
    if result.objective is not None and result.best_bound is not None:
        gap = abs(float(result.objective) - float(result.best_bound)) / max(1e-9, abs(float(result.objective)))
    return {"instance": name, "backend": backend, "arm": arm, "status": result.status,
            "objective": None if result.objective is None else float(result.objective),
            "bound": None if result.best_bound is None else float(result.best_bound), "gap": gap,
            "seconds": round(seconds, 3), "limit": time_limit,
            "score": _score(result.status, seconds, gap, time_limit), **extra}


def report(rows: list[dict]) -> str:
    by: dict[str, dict[str, dict]] = {}
    failed = [r for r in rows if r.get("arm") == "error"]
    for r in rows:
        if r.get("arm") != "error":
            by.setdefault(r["instance"], {})[r["arm"]] = r
    lines = ["| instance | backend | " + " | ".join(ARMS) + " |", "|---|---|" + "---|" * len(ARMS)]
    for name, arms in by.items():
        cells = []
        for arm in ARMS:
            r = arms.get(arm)
            if r is None:
                cells.append("--")
            elif r["status"] == "optimal":
                cells.append(f"{r['seconds']:.1f} s")
            else:
                cells.append(f"{r['status']} gap {r['gap'] * 100:.1f}%" if r.get("gap") is not None else r["status"])
        lines.append(f"| {name} | {next(iter(arms.values()))['backend']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("| arm vs base | instances | faster (10%+) | slower (10%+) | geometric mean of score ratio | wrong |")
    lines.append("|---|---|---|---|---|---|")
    for arm in ARMS[1:]:
        pairs = [(a["base"], a[arm]) for a in by.values() if "base" in a and arm in a]
        if not pairs:
            continue
        ratios = [b2["score"] / max(1e-9, b1["score"]) for b1, b2 in pairs]
        faster = sum(1 for r in ratios if r < 0.9)
        slower = sum(1 for r in ratios if r > 1.1)
        geo = math.exp(sum(math.log(max(r, 1e-9)) for r in ratios) / len(ratios))
        wrong = 0
        for b1, b2 in pairs:
            if b1["status"] == b2["status"] == "optimal" and b1["objective"] is not None and b2["objective"] is not None:
                if abs(b1["objective"] - b2["objective"]) > 1e-6 * max(1.0, abs(b1["objective"])):
                    wrong += 1
        lines.append(f"| {arm} | {len(pairs)} | {faster} | {slower} | {geo:.3f} | {wrong} |")
    for r in failed:
        lines.append(f"\nFailed: {r['instance']}: {r['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--only", default="", help="comma-separated instance-name prefixes")
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--out", default="pipeline.json")
    parser.add_argument("--report", default="")
    args = parser.parse_args(argv)
    if args.report:
        with open(args.report) as handle:
            print(report([json.loads(line) for line in handle if line.strip()]))
        return 0
    arms = tuple(a for a in args.arms.split(",") if a)
    prefixes = [p for p in args.only.split(",") if p]
    with open(args.out, "a") as out:
        for name, ir, data in instances():
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            try:
                rows = measure(name, ir, data, time_limit=args.time_limit, workers=args.workers, arms=arms)
            except Exception as exc:  # noqa: BLE001 -- one instance failing does not end the bench
                rows = [{"instance": name, "arm": "error", "error": f"{type(exc).__name__}: {exc}"}]
            for row in rows:
                out.write(json.dumps(row) + "\n")
                out.flush()
            print(name, [(r.get("arm"), r.get("status"), r.get("seconds")) for r in rows], file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
