"""Equal-budget comparison helper (no solvers required)."""

from bench.equal_budget import compare, report_md


def test_compare_counts_wins_and_wrong():
    rows = [
        {"family": "rota", "size": "S", "instance": "rota-S-0", "seed": 1, "technique": "workers", "value": 8, "solve_s": 2.0, "wrong": False},
        {"family": "rota", "size": "S", "instance": "rota-S-0", "seed": 1, "technique": "workers", "value": 4, "solve_s": 1.0, "wrong": False},
        {"family": "rota", "size": "S", "instance": "rota-S-1", "seed": 1, "technique": "workers", "value": 8, "solve_s": 1.0, "wrong": False},
        {"family": "rota", "size": "S", "instance": "rota-S-1", "seed": 1, "technique": "workers", "value": 4, "solve_s": 2.0, "wrong": True},
    ]
    summary = compare(rows, baseline_label="8", challenger_label="4")
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["wrong"] == 1
    text = report_md(summary)
    assert "Equal-budget" in text.lower() or "Equal-budget" in text
    assert "wins" in text
