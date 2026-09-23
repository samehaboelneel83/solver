"""Child interpreter that loads `highspy` and never loads `ortools`.

The two packages both ship `libHighs`. Importing both in one process
leaves the second with missing symbols. The parent starts this module
with `python -m app.solve.highs_worker` from a fresh interpreter.
"""

from __future__ import annotations

import pickle
import sys


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

    result = solve_in_process(
        payload["compiled"],
        time_limit=payload["time_limit"],
        workers=payload["workers"],
        seed=payload.get("seed"),
        gap_rel=payload.get("gap_rel", 0.0),
        progress=payload.get("progress", False),
        hint=payload.get("hint"),
    )
    with open(out_path, "wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
