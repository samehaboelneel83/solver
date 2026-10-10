"""Helpers shared by the hidden problems: a small MILP builder on scipy's HiGHS, the export text, the goal
regex, and finishing a case (the reference plan checked by the case's own checker)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from bench.phase1.common import write_case


def tol(x: float) -> float:
    return 1e-6 * max(1.0, abs(x))


class Model:
    def __init__(self) -> None:
        self.idx: dict = {}
        self.lo: list[float] = []
        self.hi: list[float] = []
        self.integ: list[int] = []
        self.c: list[float] = []
        self.ri: list[int] = []
        self.ci: list[int] = []
        self.vals: list[float] = []
        self.rl: list[float] = []
        self.rh: list[float] = []

    def var(self, key, lo=0.0, hi=math.inf, integer=False, cost=0.0):
        self.idx[key] = len(self.lo)
        self.lo.append(lo)
        self.hi.append(hi)
        self.integ.append(1 if integer else 0)
        self.c.append(float(cost))
        return key

    def add(self, terms, lo=-math.inf, hi=math.inf) -> None:
        r = len(self.rl)
        for k, a in terms:
            self.ri.append(r)
            self.ci.append(self.idx[k])
            self.vals.append(float(a))
        self.rl.append(lo)
        self.rh.append(hi)

    def solve(self, maximize: bool = False, seconds: float = 300):
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_array

        sign = -1.0 if maximize else 1.0
        c = np.array(self.c) * sign
        n = len(c)
        cons = []
        if self.rl:
            A = coo_array((np.array(self.vals, dtype=float), (np.array(self.ri, dtype=np.int32), np.array(self.ci, dtype=np.int32))),
                          shape=(len(self.rl), n)).tocsr()
            A.indices = A.indices.astype(np.int32)
            A.indptr = A.indptr.astype(np.int32)
            cons = [LinearConstraint(A, np.array(self.rl), np.array(self.rh))]
        r = milp(c, constraints=cons, integrality=np.array(self.integ, dtype=np.int32), bounds=Bounds(np.array(self.lo), np.array(self.hi)),
                 options={"time_limit": seconds, "disp": False, "mip_rel_gap": 1e-9})
        if r.x is None:
            return None
        x = {k: float(r.x[i]) for k, i in self.idx.items()}
        for k, i in self.idx.items():
            if self.integ[i]:
                x[k] = float(round(x[k]))
        obj = float(r.fun) * sign
        b = getattr(r, "mip_dual_bound", None)
        bound = obj if b is None or (isinstance(b, float) and math.isnan(b)) else float(b) * sign
        return {"x": x, "obj": obj, "bound": bound, "optimal": r.status == 0}


def fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-7:
        return str(int(round(v)))
    return f"{v:.9f}"


def export_text(rows: list[tuple[str, tuple, float]]) -> str:
    """rows: (decision, keys, value) -> the platform's export, one row per non-zero cell."""
    n = max((len(k) for _, k, _ in rows), default=1)
    lines = ["decision," + ",".join(f"key{i + 1}" for i in range(n)) + ",value"]
    for name, keys, v in rows:
        if abs(v) < 1e-9:
            continue
        lines.append(",".join([name, *[str(k) for k in keys], *[""] * (n - len(keys)), fmt(v)]))
    return "\n".join(lines) + "\n"


def num_re(v: float) -> str:
    """The goal as a person writes it, thousands separators optional: floored or rounded."""
    alts = sorted({f"{math.floor(abs(v) + 1e-9):,}", f"{round(abs(v)):,}"})
    return "(" + "|".join(a.replace(",", ",?") for a in alts) + ")"


OPEN = 'Please build this in a new workspace called "{{workspace}}". Call the problem "{name}". '
CLOSE = "Everything you need is here: please propose the model without further questions, then solve it."


def finish(folder: Path, problem: str, size: str, sense: str, ref: dict, seed: int,
           check: Callable[[Path, str], list[str]], message: str, report: list, files: list[str],
           **extra: Any) -> dict:
    out = check(folder, ref["export"])
    if len(out) != 1 or not out[-1].startswith("COST "):
        raise AssertionError(f"{problem} {size}: the reference plan fails its own check: {out[:6]}")
    val = float(out[-1].split()[1])
    if size == "S":
        assert len(message) < 4500, f"{problem} S message is {len(message)} characters"
        assert not files
    else:
        assert 2 <= len(files) <= 6
        for f in files:
            assert sum(1 for _ in (folder / f).open(encoding="utf-8")) - 1 < 5000, f
    assert message.startswith('Please build this in a new workspace called "{workspace}".') and message.rstrip().endswith(CLOSE)
    assert 4 <= len(report) <= 7
    exp = {"problem": problem, "size": size, "kind": "exact" if ref["optimal"] else "bounded",
           "goal": val if ref["optimal"] else None, "known_feasible": val,
           "bound": val if ref["optimal"] else ref["bound"], "sense": sense, "report": report, "files": files,
           "seed": seed, **extra}
    write_case(folder, message, exp)
    return exp


def search(make: Callable, solve: Callable, size: str, seed: int, seconds: float, tries: int = 40):
    """The first seed from `seed` on whose instance has a plan."""
    for s in range(seed, seed + tries):
        d = make(size, s)
        ref = solve(d, seconds)
        if ref is not None:
            return s, d, ref
    raise RuntimeError(f"no feasible instance for {size} from seed {seed}")
