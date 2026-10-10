"""Self-test of hidden problems h01-h08: each checker against its own reference plan (no violations, COST equal to
expected known_feasible), and against a broken plan (one cell changed) which it must reject.

    python -m bench.hidden.selftest_a [h01 h02 ...]
"""

from __future__ import annotations

import importlib
import json
import sys

MODULES = ["h01_crops", "h02_capital", "h03_backhaul", "h04_timetable", "h05_site", "h06_clinics", "h07_harvest",
           "h08_shelf"]


def broken(export: str) -> str:
    """One cell changed: the first exported value raised by 1000 (beyond any capacity; not 0/1 on a yes/no)."""
    lines = export.strip().splitlines()
    cells = lines[1].split(",")
    cells[-1] = str(float(cells[-1]) + 1000)
    lines[1] = ",".join(cells)
    return "\n".join(lines) + "\n"


def main(which: list[str]) -> int:
    fails = 0
    for name in MODULES:
        if which and name[:3] not in which:
            continue
        p = importlib.import_module(f"bench.hidden.{name}")
        res = []
        rejected = True
        for size in p.SIZES:
            exp = json.loads((p.OUT / size / "expected.json").read_text())
            ref = p.solve(p.make(size, exp["seed"]), 280)
            out = p.check(p.OUT / size, ref["export"])
            cost = float(out[-1].split()[1])
            ok = len(out) == 1 and abs(cost - exp["known_feasible"]) <= 1e-6 * max(1.0, abs(exp["known_feasible"]))
            res.append(f"{size} {'ok' if ok else 'fail'}")
            if not ok:
                print(f"  {name} {size}: {out[:-1][:4]} {out[-1]} expected {exp['known_feasible']}")
                fails += 1
            bad = p.check(p.OUT / size, broken(ref["export"]))
            if len(bad) < 2:
                rejected = False
                print(f"  {name} {size}: broken plan accepted ({bad[-1]})")
            else:
                print(f"  {name} {size}: broken plan -> {bad[0]}")
        print(f"{name}.py: {', '.join(res)}, broken-plan rejected {'yes' if rejected else 'no'}", flush=True)
        fails += 0 if rejected else 1
    return fails


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:]) else 0)
