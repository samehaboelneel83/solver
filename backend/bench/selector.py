"""The learned selector's evidence and its score (queue R11).

    python -m bench.selector --time-limit 10 --write

For every bench family, sizes M and L, instances 0-2: the model's fingerprint
and every backend the rules admit for it, each solved in a sandboxed child;
the fastest to prove the optimum is the example's answer (none when nobody
proves it). `--write` stores the examples as `app/solve/selector_data.json`,
which the selector reads.

Scored as it would be used -- on families it has not seen: each family's
examples are predicted from the others' only (leave one family out). Reported:
how often the rules' pick is the fastest, how often the selector's is, how
often a *confident* pick is right, and the time each loses against the best
possible pick (regret). Shadow mode keeps the rules acting either way; this
says whether the selector would ever deserve to.
"""

from __future__ import annotations

import argparse
import json
import math
import time

FAMILIES = ("rota", "rota_rates", "rota_teams", "facility", "facility_regions", "knapsack", "knapsack_depots",
            "flow_shop_timed", "districting", "feed_blend", "load_balance")


def _time(backend, compiled, time_limit):
    from app.solve import sandbox

    started = time.monotonic()
    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1,
                              "workers": 8, "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
    except Exception:  # noqa: BLE001 -- a backend that fails proves nothing
        return None
    return round(time.monotonic() - started, 3) if result.status == "optimal" else None


def collect(time_limit: float) -> list[dict]:
    from app.solve import compile_model
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.fingerprint import fingerprint
    from app.solve.service import _admissible
    from bench.families import generate

    examples = []
    for family in FAMILIES:
        for size in ("M", "L"):
            for instance in range(3):
                case = generate(family, size, instance)
                compiled = compile_model(case.ir, case.data)
                found = refine(classify(case.ir, case.data), compiled)
                admissible = sorted(_admissible(found))
                if len(admissible) < 2:
                    continue
                times = {b: _time(b, compiled, time_limit) for b in admissible}
                proved = {b: t for b, t in times.items() if t is not None}
                examples.append({"family": family, "size": size, "instance": instance,
                                 "fingerprint": fingerprint(compiled), "admissible": admissible,
                                 "rules": choose(found)[0].name, "times": times,
                                 "fastest": min(proved, key=proved.get) if proved else None})
                print(family, size, instance, times, flush=True)
    return examples


def score(examples: list[dict], time_limit: float) -> tuple[str, dict]:
    from app.solve import selector

    stored = [(selector.features(e["fingerprint"]), e["fastest"], e["family"]) for e in examples if e["fastest"]]
    rows, cost = [], {"rules": [], "selector": [], "best": []}
    right = {"rules": 0, "selector": 0, "confident": 0, "confident_right": 0}
    judged = 0
    for e in examples:
        if not e["fastest"]:
            continue
        judged += 1
        guess = selector.predict(e["fingerprint"], e["admissible"], examples=stored, exclude_family=e["family"])
        pick = guess["pick"] if guess else e["rules"]
        charge = lambda b: e["times"].get(b) if e["times"].get(b) is not None else time_limit  # noqa: E731
        cost["rules"].append(charge(e["rules"]))
        cost["selector"].append(charge(pick))
        cost["best"].append(charge(e["fastest"]))
        right["rules"] += e["rules"] == e["fastest"]
        right["selector"] += pick == e["fastest"]
        if guess and guess["confident"]:
            right["confident"] += 1
            right["confident_right"] += pick == e["fastest"]
        rows.append((e["family"], e["size"], e["instance"], e["rules"], pick, guess["confidence"] if guess else None, e["fastest"]))
    sgm = lambda xs: math.exp(sum(math.log(x + 1) for x in xs) / len(xs)) - 1  # noqa: E731
    summary = {"judged": judged, **right, **{f"sgm_{k}": round(sgm(v), 3) for k, v in cost.items() if v}}
    lines = ["| family | size | inst | rules' pick | selector's pick (confidence) | fastest |", "|---|---|---|---|---|---|"]
    lines += [f"| {f} | {s} | {i} | {r} | {p} ({c}) | {b} |" for f, s, i, r, p, c, b in rows]
    lines += ["", f"- examples judged (someone proved the optimum): {judged}",
              f"- the rules' pick was fastest: {right['rules']} ({right['rules'] / max(1, judged):.0%})",
              f"- the selector's pick was fastest: {right['selector']} ({right['selector'] / max(1, judged):.0%})",
              f"- confident picks (vote >= {selector.CONFIDENT:.0%}): {right['confident']}, right {right['confident_right']}",
              f"- SGM seconds: rules {summary.get('sgm_rules')}, selector {summary.get('sgm_selector')}, best possible {summary.get('sgm_best')}"]
    return "\n".join(lines) + "\n", summary


def main(argv=None) -> int:
    from app.solve import selector

    parser = argparse.ArgumentParser(prog="python -m bench.selector", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    examples = collect(args.time_limit)
    if args.write:
        selector.DATA.write_text(json.dumps({"//": "python -m bench.selector --write; queue R11",
                                             "time_limit": args.time_limit, "examples": examples}, indent=1) + "\n",
                                 encoding="utf-8")
    print(score(examples, args.time_limit)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
