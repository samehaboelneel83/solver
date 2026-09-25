"""Where does a metaheuristic find what the exact solvers do not? (queue R14)

    python -m bench.evolve --time-limit 60

Each case is solved sandboxed, as a run, by the backend the rules choose,
and by CMA-ES, particle swarm and the genetic algorithm (the continuous
searches on continuous models only), each for the same time. Cases: the
nonconvex `sines` and `bilinear` of the IPOPT bench (SCIP ends with a wide
bound on `sines`), and the integer families with the widest gaps or no
answer on the decomposition gate (2026-09-25): knapsack XL, flow_shop_timed
L and XL, districting L. The two verdict columns: an answer where the exact
solver had none, and a better answer than the exact solver's in the same
time. `solve.metaheuristic` (a fallback after an exact solver ends with
nothing) ships on only for the first.
"""

from __future__ import annotations

import argparse

CONTINUOUS = [("sines", 50), ("sines", 200), ("sines", 1000), ("bilinear", 200)]
INTEGER = [("knapsack", "XL"), ("flow_shop_timed", "L"), ("flow_shop_timed", "XL"), ("districting", "L")]


def _case(family, size):
    from app.solve import compile_model
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from bench import ipopt
    from bench.families import generate

    if family in ipopt.FAMILIES:
        ir, data = ipopt.FAMILIES[family](size), ipopt.NO_DATA
    else:
        case = generate(family, size, 0)
        ir, data = case.ir, case.data
    compiled = compile_model(ir, data)
    return compiled, refine(classify(ir, data), compiled)


def _solve(backend, compiled, time_limit):
    from app.solve import sandbox

    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1,
                              "workers": 8, "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
        return result.status, result.objective, result.best_bound
    except Exception as exc:  # noqa: BLE001 -- recorded as a row
        return f"failed: {str(exc)[:50]}", None, None


def main(argv=None) -> int:
    from app.solve.backends import choose

    parser = argparse.ArgumentParser(prog="python -m bench.evolve", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args(argv)
    print("| case | exact: backend / status / answer / bound | cma-es | pso | ga | answer where none | better answer |")
    print("|---|---|---|---|---|---|---|")
    for family, size in CONTINUOUS + INTEGER:
        compiled, found = _case(family, size)
        exact = choose(found)[0].name
        status, objective, bound = _solve(exact, compiled, args.time_limit)
        methods = ("cma-es", "pso", "ga") if (family, size) in CONTINUOUS else ("ga",)
        found_by = {m: _solve(m, compiled, args.time_limit) for m in methods}
        cells = []
        for m in ("cma-es", "pso", "ga"):
            s = found_by.get(m)
            cells.append("--" if s is None else (f"{s[1]:.6g}" if s[1] is not None else s[0]))
        answers = {m: float(s[1]) for m, s in found_by.items() if s[1] is not None}
        where_none = objective is None and bool(answers)
        sense = compiled.sense
        better = [m for m, v in answers.items() if objective is not None and
                  (v < float(objective) - 1e-6 * max(1, abs(float(objective))) if sense == "minimize"
                   else v > float(objective) + 1e-6 * max(1, abs(float(objective))))]
        shown = "--" if objective is None else f"{float(objective):.6g}"
        print(f"| {family} {size} | {exact} / {status} / {shown} / {bound if bound is None else f'{float(bound):.6g}'} "
              f"| {' | '.join(cells)} | {'yes' if where_none else 'no'} | {', '.join(better) or 'no'} |", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
