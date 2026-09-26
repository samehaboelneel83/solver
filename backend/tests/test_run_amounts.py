"""Every run keeps its values (queue R23): amounts reach a warm start, and a huge answer is capped."""

from __future__ import annotations

from decimal import Decimal

from app.solve import service
from app.solve.compile import Compiled, Linear, Variable
from app.solve.warm import hint_from


def _var(name, domain, lower=0, upper=1, index=()):
    key = (name, tuple(index))
    return key, Variable(key, domain, Decimal(lower), Decimal(upper))


def _compiled(*pairs) -> Compiled:
    return Compiled(variables=dict(pairs), constraints=[], objective=Linear(), sense="minimize", var_index_sets={})


def test_a_stored_amount_is_hinted_exactly():
    compiled = _compiled(
        _var("kg", "continuous", 0, 100, index=["maize"]),
        _var("kg", "continuous", 0, 100, index=["soy"]),
        _var("trucks", "integer", 0, 9, index=["mon"]),
        _var("open", "binary", index=["a"]),
    )
    roster = {"kg": [["maize"]], "trucks": [["mon"]], "open": [["a"]]}
    amounts = {"kg": [{"index": ["maize"], "value": 62.5}], "trucks": [{"index": ["mon"], "value": 3}]}

    assert hint_from(compiled, roster, amounts) == {
        ("kg", ("maize",)): 62.5,
        ("kg", ("soy",)): 0.0,
        ("trucks", ("mon",)): 3.0,
        ("open", ("a",)): 1.0,
    }


def test_an_amount_outside_todays_bounds_is_not_hinted():
    compiled = _compiled(_var("kg", "continuous", 0, 50, index=["maize"]))
    hint = hint_from(compiled, {"kg": [["maize"]]}, {"kg": [{"index": ["maize"], "value": 62.5}]})
    assert hint == {}


def test_without_amounts_a_used_amount_is_left_to_the_solver():
    compiled = _compiled(_var("kg", "continuous", 0, 100, index=["maize"]))
    assert hint_from(compiled, {"kg": [["maize"]]}, None) == {}


def test_a_huge_answer_keeps_no_amounts_and_says_how_many(monkeypatch):
    monkeypatch.setattr(service, "AMOUNT_CELLS", 3)
    compiled = _compiled(*[_var("kg", "continuous", 0, 9, index=[str(i)]) for i in range(5)])

    class Result:
        assignments = {("kg", (str(i),)): 1.0 for i in range(5)}

    amounts, kept = service._kept_amounts(compiled, Result())
    assert amounts is None and kept == {"amounts_truncated": 5}
    monkeypatch.setattr(service, "AMOUNT_CELLS", 5)
    amounts, kept = service._kept_amounts(compiled, Result())
    assert len(amounts["kg"]) == 5 and kept == {}
