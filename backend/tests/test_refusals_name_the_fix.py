"""Refusals that name the fix (build-protocol plan, Phase 1.3): every refusal kind the tuning runs' `causes`
tables recorded (bench.phase1.causes over base, step2, step4-7: five kinds in all) carries the canonical
spelling in its message -- a "write it as" clause, or for the order check, what to load. A model that is refused
reads what to write, not only what was wrong.
"""

from __future__ import annotations

import re

from app.ir.validate import check_shape

FIX = re.compile(r"write it as |Load it with ")


def _ir(**parts) -> dict:
    base = {"version": 2, "sets": ["a"], "relationships": [], "parameters": {},
            "variables": {"x": {"index": ["a"], "domain": "continuous", "lower": 0}},
            "constraints": [], "objective": {"sense": "minimize", "terms": []}}
    return {**base, **parts}


def _rule(**parts) -> dict:
    return {"id": "c", "forall": [{"index": "i", "set": "a"}], "left": {"var": "x", "index": ["i"]},
            "relation": "<=", "right": {"const": 1}, "severity": "hard", **parts}


def _refusal(ir: dict, code: str):
    refusal = check_shape(ir)
    assert refusal is not None and refusal.code == code, refusal
    assert FIX.search(refusal.message), refusal.message
    return refusal.message


def test_a_null_index_name_names_the_binding_to_write():
    """3 refusals in the runs: {"index": null, "set": ...}."""
    said = _refusal(_ir(constraints=[_rule(forall=[{"index": None, "set": "a"}])]), "binding_index_not_a_name")
    assert '{"index": "i", "set": "a"}' in said


def test_an_unknown_key_names_the_nodes_shape():
    """A key a rule does not carry ("over" beside a rule, "note" on a goal term before the pass dropped it)."""
    said = _refusal(_ir(constraints=[_rule(over=[{"index": "j", "set": "a"}])]), "key_unknown")
    assert '"left": <term>' in said and "forall" in said
    said = _refusal(_ir(constraints=[_rule(left={"var": "x", "index": ["i"], "over": []})]), "key_unknown")
    assert '{"sum": <term>, "over": [...]}' in said
    said = _refusal(_ir(objective={"sense": "minimize", "terms": [{"id": "o", "weight": 1, "note": "n",
                                                                    "expression": {"const": 1}}]}), "key_unknown")
    assert '"expression": <term>' in said


def test_a_wrong_subscript_count_names_the_reference_to_write():
    """'x is declared over 1 set (a), so it is subscripted with that many indices' -- and now, how."""
    said = _refusal(_ir(constraints=[_rule(left={"var": "x", "index": []})]), "reference_index_arity")
    assert '"var": "x", "index": [<an index over a>]' in said
    ir = _ir(parameters={"p": {"index": []}}, constraints=[_rule(right={"par": "p", "index": ["i"]})])
    said = _refusal(ir, "reference_index_arity")
    assert '"par": "p", "index": []' in said


def test_an_undeclared_relationship_names_those_declared():
    binding = {"index": "j", "set": "a", "via": {"rel": "next", "from": "i"}}
    rule = _rule(forall=[{"index": "i", "set": "a"}, binding])
    said = _refusal(_ir(relationships=["adjacent", "before"], constraints=[rule]), "binding_via_rel_not_declared")
    assert 'write it as one of "adjacent", "before"' in said
    said = _refusal(_ir(constraints=[rule]), "binding_via_rel_not_declared")
    assert 'write its name in "relationships" first' in said


def test_the_order_check_says_what_to_load():
    """'Parameter p[a] is used by the model but no value is loaded' carries the load to write."""
    from app.agent import core

    spec = {"seed": {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}],
                     "parameters": [{"name": "p", "index": ["a"]}]},
            "ir": _ir(parameters={"p": {"index": ["a"]}}, constraints=[_rule(right={"par": "p", "index": ["i"]})])}
    said = next(f for f in core._empty_parameters(spec) if "no value is loaded" in f)
    assert FIX.search(said) and "parameter_values_from_file" in said
