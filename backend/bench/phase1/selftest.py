"""Each problem's checker against its own reference: the reference plan must pass with the reference's goal.

    python -m bench.phase1.selftest p08_cyber S M
"""

from __future__ import annotations

import importlib
import json
import sys


def main(module: str, sizes: list[str]) -> None:
    p = importlib.import_module(f"bench.phase1.{module}")
    for size in sizes:
        exp = json.loads((p.OUT / size / "expected.json").read_text())
        if module == "p08_cyber":
            for seed in range(8, 60):
                d = p.make(size, seed)
                ref = p.solve(d)
                if "goal" in ref:
                    break
            rows = "decision,key1,value\n" + "".join(f"pick,{c},{1 if c in ref['chosen'] else 0}\n" for c in d["C"])
        elif module == "p09_cloud":
            plan = [line.split(",") for line in (p.OUT / size / "reference_plan.csv").read_text().splitlines()[1:]]
            rows = "decision,key1,key2,value\n" + "".join(f"place,{w},{s},1\n" for w, s in plan)
        elif module == "p05_ambulance":
            rows = p.solve(p.make(size), 60)["export"]
        elif module == "p07_grid":
            rows = p.solve(p.make(size), 120)["export"]
        else:
            raise SystemExit(f"no self-test for {module}")
        out = p.check(p.OUT / size, rows)
        print(size, out[-1], "violations", out[:-1][:3], "expected", exp["known_feasible"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
