"""Self-test of hidden problems h09-h16: the reference plan passes its checker at the expected cost, the small
message is short enough, and a plan with one changed cell is rejected.

    python -m bench.hidden.selftest_b [h09 h10 ...]
"""

from __future__ import annotations

import importlib
import json
import sys

MODULES = {"h09": "h09_fleet", "h10": "h10_berth", "h11": "h11_water", "h12": "h12_media",
           "h13": "h13_purchasing", "h14": "h14_inspections", "h15": "h15_chemicals", "h16": "h16_conference"}


def _rows(export: str) -> tuple[str, list[list[str]]]:
    lines = [ln for ln in export.strip().splitlines()]
    return lines[0], [ln.split(",") for ln in lines[1:]]


def _join(head: str, rows: list[list[str]]) -> str:
    return "\n".join([head] + [",".join(r) for r in rows]) + "\n"


def broken(code: str, export: str) -> str:
    """One changed cell that must break a hard rule."""
    head, rows = _rows(export)
    if code in ("h09", "h10", "h16"):  # an assignment set to 0: something is no longer assigned exactly once
        rows[0][-1] = "0"
    elif code == "h11":  # a delivery into a zone set to 0: that zone misses its demand
        i = next(i for i, r in enumerate(rows) if r[2].startswith("ZONE") and float(r[-1]) > 1e-3)
        rows[i][-1] = "0"
    elif code == "h12":  # a spend above every tier
        rows[0][-1] = "100000"
    elif code == "h13":  # a fractional quantity
        rows[0][-1] = str(float(rows[0][-1]) + 0.5)
    elif code == "h14":  # half an inspection
        rows[0][-1] = "0.5"
    elif code == "h15":  # far above every market and resource
        rows[0][-1] = str(float(rows[0][-1]) * 10 + 100000)
    return _join(head, rows)


def main(codes: list[str]) -> int:
    failed = 0
    for code in codes:
        mod = importlib.import_module(f"bench.hidden.{MODULES[code]}")
        for size in mod.SIZES:
            case = mod.OUT / size
            exp = json.loads((case / "expected.json").read_text(encoding="utf-8"))
            _, ref = mod.instance(size)
            out = mod.check(case, ref["export"])
            cost = float(out[-1].split()[1])
            kf = float(exp["known_feasible"])
            tol = 1e-6 * max(1.0, abs(kf))
            # Also against the solver's own objective: the checker must compute the same goal independently.
            ok_plan = len(out) == 1 and abs(cost - kf) <= tol and abs(cost - float(ref["goal"])) <= tol
            ok_plan = ok_plan and float(exp["bound"]) == kf if exp["kind"] == "exact" else ok_plan
            msg = (case / "message.txt").read_text(encoding="utf-8")
            ok_msg = len(msg) < 4500 if size == "S" else True
            ok_head = msg.startswith('Please build this in a new workspace called "{workspace}". Call the problem "') \
                and msg.rstrip().endswith("please propose the model without further questions, then solve it.")
            bad = mod.check(case, broken(code, ref["export"]))
            ok_broken = len(bad) > 1 or not bad[-1].startswith("COST")
            ok = ok_plan and ok_msg and ok_head and ok_broken
            failed += not ok
            print(f"{MODULES[code]}.py {size}: plan {'ok' if ok_plan else 'FAIL'}, message "
                  f"{'ok' if ok_msg and ok_head else 'FAIL'} ({len(msg)} chars), broken plan "
                  f"{'rejected' if ok_broken else 'ACCEPTED'}, kind {exp['kind']}")
            if not ok_plan:
                print("   ", out[:5], kf)
    print("ALL OK" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or list(MODULES)))
