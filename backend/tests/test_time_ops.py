"""Time as data for rosters (improvement plan 5.2): which slots are too close for one person."""
from __future__ import annotations

from app.api.time_ops import TooCloseBody, hours_of, slots, too_close


def test_times_read_as_hours():
    assert hours_of("06:30") == 6.5 and hours_of(14) == 14.0 and hours_of("22") == 22.0
    assert hours_of("soon") is None and hours_of(None) is None


def _row(i, key, **attrs):
    return {"id": i, "key": key, "attrs": attrs}


def test_twelve_hour_shifts_with_ten_hours_rest():
    body = TooCloseBody(name="too_close", type_id=1, start_field="start", end_field="end", day_field="day", min_gap_hours=10)
    rows = [_row(1, "d1-day", day="2026-10-10", start="06:00", end="18:00"),
            _row(2, "d1-night", day="2026-10-10", start="18:00", end="06:00"),   # runs past midnight
            _row(3, "d2-day", day="2026-10-11", start="06:00", end="18:00"),
            _row(4, "d2-night", day="2026-10-11", start="18:00", end="06:00"),
            _row(5, "broken", day="2026-10-11", start="later", end="06:00")]
    items, unread = slots(rows, body)
    assert unread == ["broken"]
    pairs = {(a, b): gap for a, b, gap in too_close(items, 10)}
    # Back to back (gap 0) is too close; a day shift after a night leaves 0 h; night then next night leaves 12 h.
    assert pairs == {(1, 2): 0.0, (2, 3): 0.0, (3, 4): 0.0}


def test_slots_from_a_day_number_and_a_duration():
    body = TooCloseBody(name="clash", type_id=1, start_field="start_hour", duration_field="hours", day_field="day",
                        min_gap_hours=0.01)
    rows = [_row(1, "D1B1", day=1, start_hour=0, hours=12), _row(2, "D1B2", day=1, start_hour=12, hours=12),
            _row(3, "D1X", day=1, start_hour=6, hours=4)]
    items, _ = slots(rows, body)
    assert sorted((a, b) for a, b, _ in too_close(items, 0.01)) == [(1, 2), (1, 3)]


def test_a_rest_rule_over_too_close_links_compiles_and_holds():
    """The `rest_between` shape's IR (frontend model/shapes.ts) on the solver: three blocks, the first
    two too close; each operator must work two blocks, so nobody may take both of the first two."""
    from app.solve import compile_model
    from app.solve.backends import by_name
    from app.solve.service import solve_compiled

    work = lambda o, b: {"var": "work", "index": [o, b]}  # noqa: E731
    ir = {
        "version": 2, "sets": ["operator", "time_block"], "parameters": {}, "relationships": ["too_close"],
        "variables": {"work": {"index": ["operator", "time_block"], "domain": "binary"}},
        "constraints": [
            {"id": "c_rest", "severity": "hard", "relation": "<=", "right": {"const": 1},
             "forall": [{"index": "o", "set": "operator"}, {"index": "t", "set": "time_block"},
                        {"index": "t2", "set": "time_block", "via": {"rel": "too_close", "from": "t"}}],
             "left": {"add": [work("o", "t"), work("o", "t2")]}},
            {"id": "c_two", "severity": "hard", "relation": ">=", "right": {"const": 2},
             "forall": [{"index": "o", "set": "operator"}],
             "left": {"sum": work("o", "b"), "over": [{"index": "b", "set": "time_block"}]}},
        ],
        "objective": {"sense": "minimize", "terms": []},
    }
    data = {"sets": {"operator": [{"id": "op1"}], "time_block": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]},
            "parameters": {}, "parameter_defaults": {},
            "relationships": {"too_close": [{"from": "B1", "to": "B2", "attrs": {"gap_h": 0}}]}}
    result, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "optimal"
    on = {key[1][1] for key, value in result.assignments.items() if key[0] == "work" and round(float(value)) == 1}
    assert len(on) == 2 and not {"B1", "B2"} <= on
