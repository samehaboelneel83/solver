"""A learned solver selector, in shadow mode (queue R11, target roadmap Phase 17).

The rules choose a solver from a model's class and needs; which one is
*fastest* on a given model is an empirical question. This answers it from
evidence: the benchmark's families, each instance solved by every backend
that may take it, stored with the model's fingerprint
(`app.solve.fingerprint`) and which backend proved it first
(`selector_data.json`, written by `python -m bench.selector`).

**The model.** Nearest neighbours: a model's fingerprint, as shares and
logarithms so size and shape weigh alike, is compared with every stored one;
the `K` nearest vote for their fastest backend, among the backends the rules
admit for this model (nothing outside the rules is ever suggested). A
nearest-neighbour pick needs no dependency, no training step, and can say
*which* known models it resembles -- the honest method for the few hundred
examples the bench gives; the roadmap's gradient-boosted classifier waits
until `run_fact` holds enough real runs to train on.

**Shadow mode, and acting.** Every run records the selector's pick beside
the rules' -- agreeing or not, and how sure. By default it acts on nothing:
the rules' choice solves the model. With setting `solve.selector_acts` on
(migration 0088, Epic engine E-4) a *confident* pick -- `CONFIDENT` of the
vote -- solves it instead, after an explicit choice and the problem's own
history (`app.solve.memory`) and before the rules; `evidence` is the reason
the run records (`bench.selector` reports how often a confident pick beat
the rules').
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Neighbours consulted.
K = 5
#: The vote share a pick would need to act; recorded, never used to act (shadow mode).
CONFIDENT = 0.8
DATA = Path(__file__).with_name("selector_data.json")

#: Counts turned into shares of the whole, so a small and a large model of one shape look alike.
_SHARES_OF_VARIABLES = ("binary", "integer", "continuous", "auxiliary")
_SHARES_OF_ROWS = ("rows_partition", "rows_cover", "rows_packing", "rows_cardinality", "rows_knapsack", "rows_general",
                   "rows_quadratic", "rows_conditional", "rows_scheduling", "rows_connectivity")
_AS_IS = ("density", "coef_range_log10", "bounds_declared", "objective_degree")


def features(fingerprint: dict[str, Any]) -> list[float]:
    """The fingerprint as a vector: sizes as logarithms, counts as shares, flags as 0/1."""
    variables = max(1, float(fingerprint.get("variables", 0)))
    rows = max(1, float(fingerprint.get("rows", 0)))
    return [
        math.log10(variables),
        math.log10(rows),
        math.log10(max(1, float(fingerprint.get("nnz", 0)))),
        *(float(fingerprint.get(k, 0)) / variables for k in _SHARES_OF_VARIABLES),
        *(float(fingerprint.get(k, 0)) / rows for k in _SHARES_OF_ROWS),
        *(float(fingerprint.get(k, 0) or 0) for k in _AS_IS),
        1.0 if fingerprint.get("integral_data") else 0.0,
        math.log10(max(1, float(fingerprint.get("blocks", 1)))),
        1.0 if fingerprint.get("intervals") else 0.0,
        1.0 if fingerprint.get("soft_rules") else 0.0,
    ]


@lru_cache(maxsize=1)
def _stored() -> tuple[tuple[list[float], str, str], ...]:
    if not DATA.exists():
        return ()
    rows = json.loads(DATA.read_text(encoding="utf-8")).get("examples", [])
    return tuple((features(r["fingerprint"]), r["fastest"], r["family"]) for r in rows if r.get("fastest"))


def _scales(examples) -> list[float]:
    """Each feature's spread over the stored examples, so no one feature dominates the distance."""
    if not examples:
        return []
    columns = list(zip(*(vector for vector, _, _ in examples)))
    out = []
    for column in columns:
        mean = sum(column) / len(column)
        spread = math.sqrt(sum((v - mean) ** 2 for v in column) / len(column))
        out.append(spread or 1.0)
    return out


def predict(fingerprint: dict[str, Any] | None, admissible: list[str],
            examples=None, exclude_family: str | None = None) -> dict[str, Any] | None:
    """The selector's pick among `admissible`, with the vote share and the families it resembles;
    None when there is nothing to go on."""
    if not fingerprint or not admissible:
        return None
    pool = [e for e in (examples if examples is not None else _stored())
            if e[1] in admissible and e[2] != exclude_family]
    if not pool:
        return None
    scale = _scales(pool)
    target = features(fingerprint)
    nearest = sorted(pool, key=lambda e: math.sqrt(sum(((a - b) / s) ** 2 for a, b, s in zip(target, e[0], scale))))[:K]
    votes: dict[str, int] = {}
    for _, fastest, _ in nearest:
        votes[fastest] = votes.get(fastest, 0) + 1
    pick = max(sorted(votes), key=lambda name: votes[name])
    share = votes[pick] / len(nearest)
    return {"pick": pick, "confidence": round(share, 3), "confident": share >= CONFIDENT,
            "like": sorted({family for _, _, family in nearest})}


def evidence(record: dict[str, Any], rules_chose: str) -> str:
    """Why the selector's pick solved the run, in the words `why_solver` records."""
    share = round(record["confidence"] * 100)
    return (f"the learned selector picked {record['pick']}: {share}% of the {K} nearest known models "
            f"({', '.join(record['like'])}) were solved fastest by it; the rules would have chosen {rules_chose}")
