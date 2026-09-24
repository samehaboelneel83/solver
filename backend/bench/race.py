"""The probe race against the rule choice, on the bench (queue 17b).

    python -m bench.race --sizes M,L --instances 3 --time-limit 30

For each instance with more than one admissible solver: the rule's choice
solved alone for the whole time allowed, against the race -- every
admissible solver probed at once, the best continued for the rest. Both
charged the time limit when they end without a proof. Reported: status,
seconds and gap each way; the enable rule is the harness's (bench.report).
"""

from __future__ import annotations

import argparse
import math
import time
from typing import Any

from bench.families import COMPARISON_ONLY, FAMILIES, generate


def _sgm(values: list[float], shift: float = 1.0) -> float:
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def measure(family: str, size: str, instance: int, time_limit: float) -> dict[str, Any] | None:
    from app.solve import compile_model
    from app.solve.backends import by_name, choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.fingerprint import fingerprint
    from app.solve.race import run_race, should_race
    from app.solve.service import _admissible, _rank_of, gap_of, solve_compiled

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    found = refine(classify(case.ir, case.data), compiled)
    rule = choose(found)[0].name
    candidates = sorted(_admissible(found), key=_rank_of)
    if should_race(fingerprint(compiled), candidates, time_limit) is not None:
        return None

    started = time.monotonic()
    alone, _ = solve_compiled(by_name(rule), compiled, time_limit=time_limit, seed=1)
    alone_s = time.monotonic() - started

    started = time.monotonic()

    def probe(name, seconds, share, should_stop):
        return solve_compiled(by_name(name), compiled, time_limit=seconds, seed=1, workers=share,
                              should_stop=should_stop)[0]

    raced = run_race(candidates, probe, workers=8, time_limit=time_limit, sense=compiled.sense, rule=rule)
    final = raced.answer
    if final is None:
        final, _ = solve_compiled(by_name(raced.winner), compiled, time_limit=max(1.0, time_limit - raced.probe_s), seed=1)
    race_s = time.monotonic() - started
    charge = lambda s, seconds: seconds if s.status == "optimal" else time_limit  # noqa: E731
    return {
        "family": family, "size": size, "instance": instance, "rule": rule, "winner": raced.winner,
        "rule_status": alone.status, "rule_s": charge(alone, alone_s), "rule_gap": gap_of(alone.objective, alone.best_bound),
        "race_status": final.status, "race_s": charge(final, race_s), "race_gap": gap_of(final.objective, final.best_bound),
        "agree": alone.status != "optimal" or final.status != "optimal"
        or abs(float(alone.objective) - float(final.objective)) <= 1e-6 * max(1.0, abs(float(alone.objective))),
    }


def report(rows: list[dict[str, Any]]) -> tuple[str, bool]:
    lines = ["| family | size | inst | rule | race winner | rule: status / s / gap | race: status / s / gap |",
             "|---|---|---|---|---|---|---|"]
    fmt = lambda g: "-" if g is None else f"{g * 100:.3g}%"  # noqa: E731
    for r in rows:
        lines.append(f"| {r['family']} | {r['size']} | {r['instance']} | {r['rule']} | {r['winner']} | "
                     f"{r['rule_status']} / {r['rule_s']:.2f} / {fmt(r['rule_gap'])} | {r['race_status']} / {r['race_s']:.2f} / {fmt(r['race_gap'])} |")
    lines += ["", "| family | runs | rule SGM s | race SGM s |", "|---|---|---|---|"]
    improved = []
    for family in dict.fromkeys(r["family"] for r in rows):
        mine = [r for r in rows if r["family"] == family]
        a, b = _sgm([r["rule_s"] for r in mine]), _sgm([r["race_s"] for r in mine])
        lines.append(f"| {family} | {len(mine)} | {a:.3f} | {b:.3f} |")
        if b <= 0.9 * a:
            improved.append(family)
    regressions = [f"{r['family']}-{r['size']}-{r['instance']}: {r['rule_s']:.2f}s -> {r['race_s']:.2f}s" for r in rows
                   if r["race_s"] > 2 * r["rule_s"] and r["race_s"] - r["rule_s"] > 0.5]
    wrong = sum(not r["agree"] for r in rows)
    enable = len(improved) >= 2 and not regressions and wrong == 0
    lines += ["", f"- families at least 10% faster: {', '.join(improved) or 'none'}",
              f"- instances at least 2x slower: {'; '.join(regressions) or 'none'}", f"- disagreeing optima: {wrong}",
              f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.race", description=__doc__.split("\n\n")[0])
    parser.add_argument("--sizes", default="M,L")
    parser.add_argument("--instances", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args(argv)
    rows = []
    for family in sorted(set(FAMILIES) - COMPARISON_ONLY):
        for size in args.sizes.split(","):
            for instance in range(args.instances):
                row = measure(family, size, instance, args.time_limit)
                if row:
                    rows.append(row)
                    print(report([row])[0].splitlines()[2], flush=True)
    print(report(rows)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
