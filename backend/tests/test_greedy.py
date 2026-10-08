"""The greedy start for packing-shaped models (app.solve.greedy)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from bench.families import generate
from app.solve import greedy
from app.solve.compile import Linear
from app.solve.compile import compile_model
from app.solve.evolve import holds
from tests.test_compile_scaling import IR as LAYOUT, _data


def _knapsack(relation="<=", capacity=None, sense=None, domain=None):
    """The generated knapsack, with its capacity rule, goal or decisions changed for a test."""
    model = compile_model(*(lambda i: (i.ir, i.data))(generate("knapsack", "S", 0)))
    for c in model.constraints:
        c.relation = relation
        if capacity is not None:
            c.right = Linear({}, Decimal(capacity))
    if sense:
        model.sense = sense
    if domain:
        for key, v in list(model.variables.items()):
            model.variables[key] = replace(v, domain=domain, upper=Decimal(3))
    return model


def test_a_knapsack_gets_a_start_that_keeps_its_capacity():
    model = _knapsack()
    assert greedy.applies(model) is None
    hint, record = greedy.start(model)
    assert record["feasible"] and holds(model, hint)
    assert set(hint) == set(model.variables)
    assert record["chosen"] > 0


def test_whole_numbers_take_as_many_as_fit():
    model = _knapsack(domain="integer")
    hint, record = greedy.start(model)
    assert record["feasible"] and max(hint.values()) > 1


def test_a_layout_of_items_on_cells_gets_a_start_with_no_cell_used_twice():
    model = compile_model(LAYOUT, _data(3_000, 1_000))
    hint, record = greedy.start(model)
    assert record["feasible"] and record["chosen"] > 0


def test_only_packing_shaped_models_take_it():
    assert greedy.applies(_knapsack(relation="==")) == "some rule is an equation"
    assert greedy.applies(_knapsack(relation=">=")) == "some rule asks for a decision to be at least something"
    assert greedy.applies(_knapsack(capacity=-1)) == "some rule cannot hold with nothing chosen"


def test_a_goal_that_only_charges_chooses_nothing():
    hint, record = greedy.start(_knapsack(sense="minimize"))
    assert record["chosen"] == 0 and record["feasible"]
