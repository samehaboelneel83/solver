"""Warm starts: the nearest earlier answer, offered to the solver as a hint.

A run of a problem that has been solved before -- the same model version,
or another version of the same problem -- often has an answer close to the
last one: a week's rota after one person's hours changed. Offering that
answer as a starting point lets a backend that takes hints (CP-SAT
`AddHint`, HiGHS `setSolution`, SCIP a partial solution) begin from a good
incumbent instead of none. It changes how fast an answer is found, never
which answer is proven (target roadmap Phase 12, setting
`solve.warm_start`, off until the bench says otherwise).

**What a stored answer can say.** `solution.assignments` records, per
variable, the index tuples that were not zero -- a roster, not a table of
values. So a binary is hinted exactly (listed: 1, unlisted: 0), and any
other variable only where it was zero (unlisted) and zero is within its
bounds now; a whole or fractional amount that was used has no recorded
value and is left to the solver. A variable the earlier model did not have
is not hinted at all.

Since queue R23 a run also keeps `solution.amounts` (the value of every used
whole or fractional decision), so an amount is hinted exactly too where the
earlier run kept it and it is within today's bounds.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.solve.compile import Compiled

#: The backends that take a hint; any other runs cold with the hint unused.
HINTED = frozenset({"cp-sat", "highs", "scip"})


def prior_run(db: Session, run_id: int) -> tuple[int, dict[str, Any], dict[str, Any] | None] | None:
    """The nearest earlier run of this run's problem that has an answer:
    the same model version first, then any other, newest first."""
    row = db.execute(
        text(
            "SELECT r.id, s.assignments, s.amounts"
            "  FROM run r"
            "  JOIN solution s ON s.run_id = r.id"
            "  JOIN scenario sc ON sc.id = r.scenario_id"
            "  JOIN run me ON me.id = :me"
            "  JOIN scenario msc ON msc.id = me.scenario_id"
            " WHERE sc.problem_id = msc.problem_id"
            "   AND r.status IN ('optimal', 'feasible')"
            "   AND r.id <> :me"
            # A why-not probe answers a question with cells forced: not a plan to start from.
            "   AND r.purpose = 'plan'"
            " ORDER BY (sc.model_version_id = msc.model_version_id) DESC, r.id DESC"
            " LIMIT 1"
        ),
        {"me": run_id},
    ).one_or_none()
    if row is None:
        return None
    return int(row[0]), row[1] or {}, row[2]


def hint_from(compiled: Compiled, roster: dict[str, list[list[str]]],
              amounts: dict[str, list[dict[str, Any]]] | None = None) -> dict[tuple, float]:
    """The values an earlier roster (and, where kept, its amounts) fixes for this model's variables."""
    used = {name: {tuple(index) for index in rows} for name, rows in roster.items()}
    took = {(name, tuple(cell["index"])): float(cell["value"])
            for name, cells in (amounts or {}).items() for cell in cells}
    hint: dict[tuple, float] = {}
    for key, spec in compiled.variables.items():
        name, index = key
        if name.startswith("__") or name not in used:
            continue
        if index in used[name]:
            if spec.domain == "binary":
                hint[key] = 1.0
            elif key in took and spec.lower <= took[key] <= spec.upper:
                hint[key] = took[key]
            # Used, with a value no longer kept or no longer allowed: no hint.
            continue
        if spec.lower <= 0 <= spec.upper:
            hint[key] = 0.0
    return hint
