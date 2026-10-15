"""The practice-case checkers read a plan the way the model wrote it (15 Oct scoring fixes; 16 Oct mission, Phase A):
a right plan must not be scored wrong for how its decisions are named or keyed."""

from __future__ import annotations

from bench.phase1.common import decision_over


def _rows(*rows):
    return [dict(zip(("decision", "key1", "key2", "value"), r)) for r in rows]


def test_a_decision_keyed_by_a_joined_pair_is_read_as_the_pair():
    """p02, R3 run 2: shipments keyed "W01-C001" for the pair (W01, C001) -- the goal was the reference, and the
    checker found no decision over (warehouse, customer)."""
    rows = [{"decision": "shipment", "key1": "W01-C001", "value": "25.0"},
            {"decision": "shipment", "key1": "W02-C002", "value": "2.0"}]
    name, values = decision_over(rows, {"W01", "W02"}, {"C001", "C002"})
    assert name == "shipment" and values == {("W01", "C001"): 25.0, ("W02", "C002"): 2.0}


def test_a_decision_keyed_in_another_order_is_read_in_the_sets_order():
    """p04, step 8 run 1: keyed (machine, product, shift) where the checker read (product, machine, shift)."""
    rows = _rows(("produce", "M1", "P1", "3"), ("produce", "M2", "P2", "4"))
    for r, shift in zip(rows, ("S1", "S2")):
        r["key3"] = shift
    name, values = decision_over(rows, {"P1", "P2"}, {"M1", "M2"}, {"S1", "S2"})
    assert values == {("P1", "M1", "S1"): 3.0, ("P2", "M2", "S2"): 4.0}


def test_a_joined_key_whose_parts_are_not_in_the_sets_is_not_taken():
    rows = [{"decision": "x", "key1": "A-B", "value": "1"}]
    assert decision_over(rows, {"W01"}, {"C001"}) == ("", {})


def test_the_generators_output_is_not_mistaken_for_their_on_off():
    """p07, R3 run 2: "gen_on" matched "gen" before "gen_output" did, and a plan with the reference goal was scored
    with 69 violations."""
    from bench.phase1.p07_grid import _by_word

    rows = _rows(("gen_on", "G1", "H001", "1"), ("gen_output", "G1", "H001", "101.5"),
                 ("gen_start", "G1", "H001", "1"))
    dec = _by_word(rows, {"H001"}, {"G1"})
    assert dec["p"] == {("G1", "H001"): 101.5}
    assert dec["on"] == {("G1", "H001"): 1.0}
