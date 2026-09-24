"""Per-problem memory against the rule choice, replayed on the bench (queue 17a).

    python -m bench.memory --sizes S,M --instances 5 --time-limit 20

Each family's instances stand for one problem's successive runs: new data,
the same shape. Every admissible solver solves every instance once; then,
instance by instance, the rule's pick (`choose`) is compared with memory's
(`app.solve.memory.recall` over the earlier instances' proven solves). A
solve that did not prove its answer is charged the time limit.

What it assumes, said plainly: that the problem's history holds proven runs
by more than one solver (a planner who tried another, or probes from 17b).
With only the rule's own runs to remember, memory picks the rule's solver
again and costs nothing -- so this measures what memory is worth when it
has evidence, and the enable rule is the harness's own (bench.report).
"""

from __future__ import annotations

import argparse
import math
from typing import Any

from bench.families import COMPARISON_ONLY, FAMILIES, generate
from bench.run import run


def _sgm(values: list[float], shift: float = 1.0) -> float:
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def replay(sizes: list[str], instances: int, time_limit: float) -> list[dict[str, Any]]:
    from app.solve import compile_model
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.memory import recall

    families = sorted(set(FAMILIES) - COMPARISON_ONLY)
    rows = run(families, sizes, count=instances, time_limit=time_limit)
    charged = lambda r: r["solve_s"] if r["status"] == "optimal" else time_limit  # noqa: E731
    out = []
    for family in families:
        for size in sizes:
            mine = [r for r in rows if r["family"] == family and r["size"] == size]
            names = sorted({r["instance"] for r in mine}, key=lambda n: int(n.rsplit("-", 1)[1]))
            history: list[tuple[str, float]] = []
            for name in names:
                case = generate(family, size, int(name.rsplit("-", 1)[1]))
                found = refine(classify(case.ir, case.data), compile_model(case.ir, case.data))
                rule = choose(found)[0].name
                by_backend = {r["backend"]: r for r in mine if r["instance"] == name}
                recalled = recall(history, set(by_backend))
                memory = recalled.solver if recalled else rule
                if rule in by_backend and memory in by_backend:
                    out.append({
                        "family": family, "size": size, "instance": name, "rule": rule, "memory": memory,
                        "rule_s": charged(by_backend[rule]), "memory_s": charged(by_backend[memory]),
                        "wrong": bool(by_backend[memory].get("wrong")),
                    })
                # What this run adds to the problem's history: every proven solve, newest first.
                history = [(b, r["solve_s"]) for b, r in sorted(by_backend.items()) if r["status"] == "optimal"] + history
    return out


def report(rows: list[dict[str, Any]]) -> tuple[str, bool]:
    lines = ["| family | size | instance | rule | memory | rule s | memory s |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['family']} | {r['size']} | {r['instance']} | {r['rule']} | {r['memory']} | {r['rule_s']:.3f} | {r['memory_s']:.3f} |" for r in rows]
    lines += ["", "| family | runs | memory differs | rule SGM s | memory SGM s |", "|---|---|---|---|---|"]
    improved, regressions = [], []
    for family in dict.fromkeys(r["family"] for r in rows):
        mine = [r for r in rows if r["family"] == family]
        a, b = _sgm([r["rule_s"] for r in mine]), _sgm([r["memory_s"] for r in mine])
        lines.append(f"| {family} | {len(mine)} | {sum(r['rule'] != r['memory'] for r in mine)} | {a:.3f} | {b:.3f} |")
        if b <= 0.9 * a:
            improved.append(family)
    regressions = [f"{r['instance']}: {r['rule_s']:.3f}s -> {r['memory_s']:.3f}s" for r in rows
                   if r["memory_s"] > 2 * r["rule_s"] and r["memory_s"] - r["rule_s"] > 0.05]
    wrong = sum(r["wrong"] for r in rows)
    enable = len(improved) >= 2 and not regressions and wrong == 0
    lines += ["", f"- families at least 10% faster: {', '.join(improved) or 'none'}",
              f"- instances at least 2x slower: {'; '.join(regressions) or 'none'}", f"- wrong answers: {wrong}",
              f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.memory", description=__doc__.split("\n\n")[0])
    parser.add_argument("--sizes", default="S,M")
    parser.add_argument("--instances", type=int, default=5)
    parser.add_argument("--time-limit", type=float, default=20.0)
    args = parser.parse_args(argv)
    text, _ = report(replay(args.sizes.split(","), args.instances, args.time_limit))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
