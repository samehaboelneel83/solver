"""Does a connected, balanced start help the exact flow past 200 cells? (queue R13)

    python -m bench.connected_start --time-limit 120

Districting at every size, two instances, CP-SAT and HiGHS (the two that found
answers at M on 2026-09-24), each solved sandboxed as a run twice: from
nothing, and from `app.solve.partition`'s start (its time taken from the
solver's). The start's own objective is shown beside the answers. What
decides `solve.connected_start`'s default: an answer where there was none,
and no size where the start makes the answer worse.
"""

from __future__ import annotations

import argparse
import time


def _row(size, instance, backend, time_limit, with_start):
    from app.solve import compile_model, partition, sandbox
    from app.solve.service import gap_of
    from bench.families import generate

    case = generate("districting", size, instance)
    compiled = compile_model(case.ir, case.data)
    hint, record, left = None, None, time_limit
    if with_start:
        began = time.monotonic()
        hint, record = partition.start(case.ir, case.data, compiled,
                                       seconds=min(partition.CEILING, partition.SHARE * time_limit))
        left = time_limit - (time.monotonic() - began)
    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": left, "seed": 1,
                              "workers": 8, "gap_rel": 0.0, "hint": hint}, time_limit=left, workers=8)[0]
        status, objective, bound = result.status, result.objective, result.best_bound
    except Exception as exc:  # noqa: BLE001 -- recorded as a row
        status, objective, bound = f"failed: {str(exc)[:60]}", None, None
    gap = 0.0 if status == "optimal" else (gap_of(objective, bound) if objective is not None else None)
    return {"size": size, "instance": instance, "backend": backend, "start": "yes" if with_start else "no",
            "start_objective": record and (record["objective"] if record["feasible"] else f"infeasible ({record['breach']})"),
            "status": status, "objective": objective, "gap": gap}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.connected_start", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--sizes", default="S,M,L,XL")
    parser.add_argument("--backends", default="cp-sat,highs")
    args = parser.parse_args(argv)
    fmt = lambda v: "--" if v is None else (f"{v * 100:.3g}%" if isinstance(v, float) and v < 1 else str(v))  # noqa: E731
    print("| size | instance | backend | start | start objective | status | objective | gap |")
    print("|---|---|---|---|---|---|---|---|")
    for size in args.sizes.split(","):
        for instance in (0, 1):
            for backend in args.backends.split(","):
                for with_start in (False, True):
                    r = _row(size, instance, backend, args.time_limit, with_start)
                    obj = "--" if r["objective"] is None else f"{float(r['objective']):g}"
                    gap = "--" if r["gap"] is None else f"{r['gap'] * 100:.3g}%"
                    print(f"| {size} | {size}-{instance} | {backend} | {r['start']} | {r['start_objective'] or '--'} "
                          f"| {r['status']} | {obj} | {gap} |", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
