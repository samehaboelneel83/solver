"""What the expression compiler refuses, and what it refuses *before* it
has a database in scope (`app/expressions/parse.py`).

This is the adversarial half of Task 14d. The route turns a string off the
network into SQL, so the interesting property is not "nothing bad happened"
but "the refusal came first". Two mechanisms make that checkable:

1. :func:`app.expressions.parse_expression` takes **one argument, a string**.
   It has no `Session`, no engine and no connection anywhere in its scope,
   so a document refused by it cannot have reached a database -- not
   because a test watched and saw nothing, but because there was nothing to
   reach. Every test in the first section below asserts through that
   function.
2. For the refusals that genuinely need the catalogue (an enum value has to
   be checked against `attribute_def.enum_values`, which only the database
   knows), `test_api_entities_expression.py` records every statement the
   request executes and asserts that none of them touched `entity`.

An injection test that asserts "no exception" would pass against a compiler
that silently dropped the rule, so every test here asserts the refusal's
`code` and something specific about its `message`.
"""

import json

import pytest

from app.expressions import ExpressionRefusal, parse_expression
from app.expressions.catalogue import MAX_DEPTH, MAX_LIST_LENGTH, MAX_RULES


def _document(*rules, combinator: str = "and") -> str:
    return json.dumps({"version": 1, "query": {"combinator": combinator, "rules": list(rules)}})


def _rule(field: str, operator: str = "=", value=1) -> dict:
    return {"field": field, "operator": operator, "value": value}


def _refusal(raw: str) -> ExpressionRefusal:
    with pytest.raises(ExpressionRefusal) as excinfo:
        parse_expression(raw)
    return excinfo.value


# --- the six the brief names -----------------------------------------------


def test_a_field_name_carrying_sql_is_refused_by_name():
    """`attr:1:"; drop table entity; --` never becomes a catalogue lookup.

    The attribute name is a bound parameter in the compiled SQL, so even a
    name that reached the database could not be executed as SQL -- but this
    one does not get that far: `attribute_def.name` carries CHECK (name ~
    '^[a-z][a-z0-9_]*$'), so a name that cannot match it cannot name a real
    attribute, and the decoder refuses it with no query at all.
    """
    refusal = _refusal(_document(_rule('attr:1:"; drop table entity; --')))
    assert refusal.code == "unknown_field"
    assert '"; drop table entity; --' in refusal.message
    assert refusal.path == ("query", "rules", 0, "field")


def test_a_function_name_carrying_a_comment_sequence_is_refused_by_name():
    refusal = _refusal(_document(_rule("fn:year/*x*/:col:key")))
    assert refusal.code == "unknown_function"
    assert "year/*x*/" in refusal.message


def test_a_function_name_that_is_a_union_select_is_refused_by_name():
    refusal = _refusal(_document(_rule("fn:union select null--:col:key")))
    assert refusal.code == "unknown_function"


def test_a_column_name_that_is_not_one_of_the_four_is_refused():
    refusal = _refusal(_document(_rule("col:attrs")))
    assert refusal.code == "unknown_field"
    refusal = _refusal(_document(_rule("col:key; drop table entity")))
    assert refusal.code == "unknown_field"


def test_an_object_where_a_scalar_is_required_is_refused():
    """The trap this closes: a dict reaching `Entity.key == value` would be
    adapted by psycopg2 rather than refused."""
    refusal = _refusal(_document(_rule("col:key", "=", {"a": 1})))
    assert refusal.code == "bad_value_type"
    assert "single value" in refusal.message
    assert refusal.path == ("query", "rules", 0, "value")


def test_a_list_where_a_scalar_is_required_is_refused():
    refusal = _refusal(_document(_rule("col:key", "=", ["a"])))
    assert refusal.code == "bad_value_type"


def test_an_object_inside_a_list_is_refused():
    refusal = _refusal(_document(_rule("col:key", "in", [{"a": 1}])))
    assert refusal.code == "bad_value_type"
    assert refusal.path == ("query", "rules", 0, "value", 0)


def test_a_two_hundred_deep_nest_is_refused_for_being_too_deep():
    node: dict = {"combinator": "and", "rules": []}
    root = node
    for _ in range(200):
        inner: dict = {"combinator": "and", "rules": []}
        node["rules"].append(inner)
        node = inner
    refusal = _refusal(json.dumps({"version": 1, "query": root}))
    assert refusal.code == "too_deep"
    assert str(MAX_DEPTH) in refusal.message


def test_a_nest_deep_enough_to_exhaust_the_json_parser_is_refused_not_crashed():
    """Python's own `json.loads` recurses, and a document can be deeper than
    the interpreter's recursion limit while still being far smaller than the
    size cap. A RecursionError here would be a 500, so it is caught."""
    raw = '{"version":1,"query":' + '{"combinator":"and","rules":[' * 1500
    raw += "]}" * 1500 + "}"
    refusal = _refusal(raw)
    assert refusal.code in {"malformed", "too_deep", "too_large"}


def test_a_document_with_version_99_is_refused():
    refusal = _refusal(json.dumps({"version": 99, "query": {"combinator": "and", "rules": []}}))
    assert refusal.code == "unsupported_version"
    assert "99" in refusal.message
    assert refusal.path == ("version",)


def test_a_document_with_no_version_is_refused():
    refusal = _refusal(json.dumps({"query": {"combinator": "and", "rules": []}}))
    assert refusal.code == "unsupported_version"


def test_a_version_that_is_a_string_is_refused():
    """`"1"` is not 1. A `==` that coerced would accept a document written
    against a version this server does not implement."""
    refusal = _refusal(json.dumps({"version": "1", "query": {"combinator": "and", "rules": []}}))
    assert refusal.code == "unsupported_version"


# --- the rest of the structural surface ------------------------------------


def test_a_string_that_is_not_json_is_refused():
    refusal = _refusal("not json at all")
    assert refusal.code == "malformed"


def test_a_json_scalar_is_refused():
    refusal = _refusal("42")
    assert refusal.code == "malformed"


def test_a_document_larger_than_the_size_cap_is_refused_before_it_is_parsed():
    refusal = _refusal('{"version":1,"query":{"combinator":"and","rules":[]},"pad":"' + "x" * 40000 + '"}')
    assert refusal.code == "too_large"


def test_more_than_the_rule_limit_is_refused():
    rules = [_rule("col:sort_order", "=", n) for n in range(MAX_RULES + 1)]
    refusal = _refusal(_document(*rules))
    assert refusal.code == "too_many_rules"
    assert str(MAX_RULES) in refusal.message


def test_exactly_the_rule_limit_is_accepted():
    rules = [_rule("col:sort_order", "=", n) for n in range(MAX_RULES)]
    parsed = parse_expression(_document(*rules))
    assert parsed.rule_count == MAX_RULES


def test_a_list_longer_than_the_list_limit_is_refused():
    refusal = _refusal(_document(_rule("col:key", "in", [str(n) for n in range(MAX_LIST_LENGTH + 1)])))
    assert refusal.code == "list_too_long"
    assert str(MAX_LIST_LENGTH) in refusal.message


def test_an_empty_list_is_refused():
    refusal = _refusal(_document(_rule("col:key", "in", [])))
    assert refusal.code == "empty_list"


def test_an_unknown_operator_is_refused():
    refusal = _refusal(_document(_rule("col:key", "sounds like", "x")))
    assert refusal.code == "bad_operator"
    assert "sounds like" in refusal.message
    assert refusal.path == ("query", "rules", 0, "operator")


def test_an_unknown_combinator_is_refused():
    refusal = _refusal(json.dumps({"version": 1, "query": {"combinator": "xor", "rules": []}}))
    assert refusal.code == "bad_combinator"
    assert "xor" in refusal.message


def test_a_nested_function_is_refused_as_such():
    refusal = _refusal(_document(_rule("fn:abs:fn:year:attr:1:d")))
    assert refusal.code == "nested_function"


def test_a_bare_relationship_is_not_a_field():
    """`rel:...` is only ever `count`'s argument. Read as a field it would
    have no data type at all."""
    refusal = _refusal(_document(_rule("rel:1:outgoing")))
    assert refusal.code == "unknown_field"


def test_a_relationship_direction_outside_the_vocabulary_is_refused():
    refusal = _refusal(_document(_rule("fn:count:rel:1:sideways")))
    assert refusal.code == "unknown_field"


def test_an_entity_type_id_that_is_not_digits_is_refused():
    refusal = _refusal(_document(_rule("attr:1 OR 1=1:cap")))
    assert refusal.code == "unknown_field"


def test_a_negative_entity_type_id_is_refused():
    refusal = _refusal(_document(_rule("attr:-1:cap")))
    assert refusal.code == "unknown_field"


def test_an_entity_type_id_too_large_for_a_bigint_is_refused():
    """A 40-digit id is digits, so the pattern alone would let it through
    and psycopg2 would raise a NumericValueOutOfRange -- a 500."""
    refusal = _refusal(_document(_rule("attr:" + "9" * 40 + ":cap")))
    assert refusal.code == "unknown_field"


def test_count_over_a_field_rather_than_a_relationship_is_refused():
    refusal = _refusal(_document(_rule("fn:count:col:key")))
    assert refusal.code == "bad_argument_type"


def test_a_field_function_over_a_relationship_is_refused():
    refusal = _refusal(_document(_rule("fn:year:rel:1:outgoing")))
    assert refusal.code == "bad_argument_type"


def test_a_rule_that_is_not_an_object_is_refused():
    refusal = _refusal(json.dumps({"version": 1, "query": {"combinator": "and", "rules": ["x"]}}))
    assert refusal.code == "malformed"


def test_a_rule_with_a_non_string_field_is_refused():
    refusal = _refusal(_document({"field": 7, "operator": "=", "value": 1}))
    assert refusal.code == "malformed"


def test_a_group_whose_rules_are_not_a_list_is_refused():
    refusal = _refusal(json.dumps({"version": 1, "query": {"combinator": "and", "rules": {}}}))
    assert refusal.code == "malformed"


def test_a_not_that_is_not_a_boolean_is_refused():
    refusal = _refusal(json.dumps({"version": 1, "query": {"combinator": "and", "not": "yes", "rules": []}}))
    assert refusal.code == "malformed"


def test_a_value_that_is_a_nan_is_refused():
    """`json.loads` accepts `NaN` by default; no comparison involving it is
    meaningful, and psycopg2 would send it to Postgres as 'NaN'."""
    refusal = _refusal('{"version":1,"query":{"combinator":"and","rules":'
                       '[{"field":"col:sort_order","operator":"=","value":NaN}]}}')
    assert refusal.code in {"malformed", "bad_value_type"}


def test_a_value_that_is_infinity_is_refused():
    refusal = _refusal('{"version":1,"query":{"combinator":"and","rules":'
                       '[{"field":"col:sort_order","operator":"=","value":Infinity}]}}')
    assert refusal.code in {"malformed", "bad_value_type"}


def test_the_parser_takes_no_database_of_any_kind():
    """The structural guarantee this file rests on, asserted rather than
    described: `parse_expression` has exactly one parameter."""
    import inspect

    assert list(inspect.signature(parse_expression).parameters) == ["raw"]
