"""A command-line solver for the reference adapter (queue R41): read MPS, solve with HiGHS,
write a `sol` file -- `# Status = ...` then `name value` per column.

    python3 highs_cli.py MODEL.mps SOLUTION.sol TIME_LIMIT [GAP] [THREADS]
"""

import sys

import highspy


def main(argv: list[str]) -> int:
    model, solution, limit = argv[1], argv[2], float(argv[3])
    gap = float(argv[4]) if len(argv) > 4 else 0.0
    threads = int(argv[5]) if len(argv) > 5 else 1
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", limit)
    h.setOptionValue("mip_rel_gap", gap)
    h.setOptionValue("threads", threads)
    h.readModel(model)
    h.run()
    status = h.getModelStatus()
    info = h.getInfo()
    named = {
        highspy.HighsModelStatus.kOptimal: "optimal",
        highspy.HighsModelStatus.kInfeasible: "infeasible",
        highspy.HighsModelStatus.kUnbounded: "unbounded",
    }.get(status)
    has_values = info.primal_solution_status == 2  # feasible
    if named is None:
        # Stopped (a time limit): an answer it has not proven, or none at all.
        named = "feasible" if has_values else "unknown"
    with open(solution, "w", encoding="utf-8") as out:
        if named is not None:
            out.write(f"# Status = {named}\n")
        if named in ("optimal", "feasible"):
            names = h.getLp().col_names_
            for name, value in zip(names, h.getSolution().col_value):
                out.write(f"{name} {value!r}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
