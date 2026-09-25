"""Does any template's gap demand a decomposition? The roadmap's gate, measured (queue R12).

    python -m bench.decompose_gate --time-limit 30

The target roadmap (Phase 14) decides monolithic against decomposed so: a
model is decomposed only if (a) it is separable -- already split, `solve.separable`
-- or (b) the monolithic gap after the time budget is over 5% *and* its
linking rows are under 5% of its rows *and* a decomposition exists for its
template. This measures (b)'s first two parts on every bench family at its
largest two sizes: the rules' backend alone for the time allowed (sandboxed,
as a run), its final gap, and the linking share from `blocks.structure` (R4).
A family meeting both is a candidate for a template decomposition; none
meeting them means none is built.
"""

from __future__ import annotations

import argparse

FAMILIES = ("rota", "rota_rates", "rota_teams", "facility", "facility_regions", "knapsack", "knapsack_depots",
            "flow_shop_timed", "districting", "load_balance")
GAP, LINKING = 0.05, 0.05


def _row(family, size, time_limit):
    from app.solve import compile_model, sandbox
    from app.solve.backends import choose
    from app.solve.blocks import structure
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import gap_of
    from bench.families import generate

    case = generate(family, size, 0)
    compiled = compile_model(case.ir, case.data)
    found = refine(classify(case.ir, case.data), compiled)
    backend = choose(found)[0].name
    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1,
                              "workers": 8, "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
        status, gap = result.status, (0.0 if result.status == "optimal" else gap_of(result.objective, result.best_bound))
    except Exception as exc:  # noqa: BLE001 -- recorded as a row
        status, gap = f"failed: {str(exc)[:60]}", None
    split = structure(compiled)
    share = split["linking_rules"] / max(1, len(compiled.constraints))
    wide = gap is None or gap > GAP
    few = 0 < share < LINKING
    return {"family": family, "size": size, "backend": backend, "status": status, "gap": gap,
            "blocks": split["blocks"], "by": split["by"], "linking_share": round(share, 4),
            "candidate": wide and few}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.decompose_gate", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args(argv)
    fmt = lambda g: "-" if g is None else f"{g * 100:.3g}%"  # noqa: E731
    lines = ["| family | size | backend | status | gap | blocks (by) | linking rows | candidate |", "|---|---|---|---|---|---|---|---|"]
    for family in FAMILIES:
        for size in ("L", "XL"):
            r = _row(family, size, args.time_limit)
            lines.append(f"| {r['family']} | {r['size']} | {r['backend']} | {r['status']} | {fmt(r['gap'])} | "
                         f"{r['blocks']} ({r['by'] or '-'}) | {r['linking_share'] * 100:.2f}% | {'**yes**' if r['candidate'] else 'no'} |")
            print(lines[-1], flush=True)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
