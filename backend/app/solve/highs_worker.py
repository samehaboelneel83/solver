"""Child interpreter that loads `highspy` and never loads `ortools`.

The two packages both ship `libHighs`. Importing both in one process
leaves the second with missing symbols. The parent starts this module
with `python -m app.solve.highs_worker` from a fresh interpreter.
"""

from __future__ import annotations

import pickle
import sys

from app.solve.nodump import forbid

# A new program: the sandbox's no-dump flag did not survive the exec.
forbid()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--probe"]:
        import highspy

        highspy.Highs()
        return 0

    req_path, out_path = args
    with open(req_path, "rb") as handle:
        payload = pickle.load(handle)

    from app.solve.highs import iis_in_process, solve_in_process

    if payload.get("mode") == "iis":
        result = iis_in_process(payload["compiled"], time_limit=payload["time_limit"])
        with open(out_path, "wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return 0

    if payload.get("mode") == "fixed_charge":
        from app.solve.fixed_charge import start_in_process as fixed_charge_in_process

        result = fixed_charge_in_process(payload["compiled"], seconds=payload["seconds"])
        with open(out_path, "wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return 0

    if payload.get("mode") == "benders":
        from app.solve.benders import solve_in_process as benders_in_process

        result = benders_in_process(
            payload["compiled"],
            time_limit=payload["time_limit"],
            workers=payload["workers"],
            seed=payload.get("seed"),
            gap_rel=payload.get("gap_rel", 0.0),
            progress=payload.get("progress", False),
            pareto=payload.get("pareto", False),
        )
        with open(out_path, "wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return 0

    if payload.get("mode") == "colgen":
        from app.solve.colgen import solve_in_process as colgen_in_process

        result = colgen_in_process(
            payload["compiled"],
            time_limit=payload["time_limit"],
            workers=payload["workers"],
            seed=payload.get("seed"),
            gap_rel=payload.get("gap_rel", 0.0),
            progress=payload.get("progress", False),
        )
        with open(out_path, "wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return 0

    result = solve_in_process(
        payload["compiled"],
        time_limit=payload["time_limit"],
        workers=payload["workers"],
        seed=payload.get("seed"),
        gap_rel=payload.get("gap_rel", 0.0),
        progress=payload.get("progress", False),
        hint=payload.get("hint"),
        options=payload.get("options"),
    )
    with open(out_path, "wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
