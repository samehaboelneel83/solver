"""A sum over the records a relationship reaches costs what it reaches, not the whole set per anchor (the camp
test, October 2026: 54,468 candidate positions over 7,670 cells compiled for hours -- every cell scanned every
candidate; now 26 s, linear)."""
from __future__ import annotations

import time

from app.solve.compile import compile_model

IR = {"version": 2, "sets": ["item", "cell"], "parameters": {}, "relationships": ["occupies"],
      "variables": {"place": {"index": ["item"], "domain": "binary"}},
      "constraints": [{"id": "one_per_cell", "severity": "hard", "forall": [{"set": "cell", "index": "k"}],
                       "left": {"sum": {"var": "place", "index": ["j"]},
                                "over": [{"set": "item", "index": "j", "via": {"rel": "occupies", "to": "k"}}]},
                       "relation": "<=", "right": {"const": 1}}],
      "objective": {"sense": "maximize", "terms": [{"id": "n", "weight": 1, "expression": {
          "sum": {"var": "place", "index": ["i"]}, "over": [{"set": "item", "index": "i"}]}}]}}


def _data(items: int, cells: int, per_item: int = 3) -> dict:
    return {"sets": {"item": [{"id": f"i{n}"} for n in range(items)], "cell": [{"id": f"c{n}"} for n in range(cells)]},
            "relationships": {"occupies": [{"from": f"i{n}", "to": f"c{(n + k) % cells}"}
                                           for n in range(items) for k in range(per_item)]},
            "parameters": {}, "parameter_defaults": {}}


def test_a_via_sum_compiles_in_linear_time():
    started = time.monotonic()
    model = compile_model(IR, _data(20_000, 4_000))
    took = time.monotonic() - started
    assert len(model.constraints) == 4_000
    assert sum(len(c.left.coeffs) for c in model.constraints) == 60_000
    # Linear: about a second here. Scanning every item per cell (80 million checks) took minutes.
    assert took < 8, took


def test_the_rows_reached_keep_the_sets_order():
    model = compile_model(IR, _data(6, 2, per_item=1))
    first = next(c for c in model.constraints if c.index == {"k": "c0"})
    assert [k[1][0] for k in first.left.coeffs] == ["i0", "i2", "i4"]
