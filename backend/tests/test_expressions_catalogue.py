"""The server's half of the catalogue-parity mechanism.

The shared file is `app/expressions/catalogue.json`. The client is pinned
to it by `frontend/src/expressions/parity.test.ts`, which reads it off disk
and deep-compares it with the TypeScript modules. This file pins the
*server* to it, which the frontend test cannot: the JSON only describes the
functions, and describing one is not implementing it.

So the two halves together make each of these a failing test:

    added in TypeScript only       -> the vitest parity test fails
    added in the JSON only         -> `test_every_declared_function_has_a_builder` fails
    implemented in Python only     -> `test_every_builder_is_declared` fails
    an argument or return type
      changed on one side only     -> the vitest parity test fails

None of these needs Node, which the backend's test container does not have,
and none of them can degrade to a skip.
"""

import json

import pytest
import sqlalchemy as sa

from app.expressions import catalogue as cat
from app.expressions.compiler import _COLUMNS, _DIRECTIONS, _FUNCTIONS


def test_every_declared_function_has_a_builder():
    """An entry in the JSON with no Python behind it would be offered by
    the builder, accepted by the validator, and then fail at compile time
    with a KeyError -- a 500 for a field the app itself advertised."""
    assert sorted(cat.FUNCTIONS) == sorted([*_FUNCTIONS, "count"])


def test_every_builder_is_declared():
    for name in _FUNCTIONS:
        assert name in cat.FUNCTIONS, f"{name} is compiled but not declared in catalogue.json"


def test_count_is_the_only_entry_that_is_not_a_scalar_expression():
    """Task 14c flagged `count` as the one entry whose SQL is a correlated
    subquery; it is therefore the one entry `_FUNCTIONS` (which maps a
    scalar argument to a scalar result) cannot hold."""
    assert cat.FUNCTIONS["count"]["argument"] == "relationship"
    assert [n for n, d in cat.FUNCTIONS.items() if d["argument"] != "field"] == ["count"]


def test_every_declared_column_is_a_real_entity_column():
    for name in cat.COLUMNS:
        assert name in _COLUMNS
    assert sorted(_COLUMNS) == sorted(cat.COLUMNS)


def test_every_declared_direction_has_a_predicate():
    assert sorted(_DIRECTIONS) == sorted(cat.RELATIONSHIP_DIRECTIONS)


def test_every_declared_function_argument_type_is_a_real_data_type():
    for name, definition in cat.FUNCTIONS.items():
        for data_type in definition["argumentTypes"]:
            assert data_type in cat.DATA_TYPES, f"{name} takes an unknown type {data_type}"
        if definition["returns"] != "argument":
            assert definition["returns"] in cat.DATA_TYPES


def test_every_declared_operator_is_used_by_some_data_type():
    used = {name for names in cat.OPERATORS_BY_TYPE.values() for name in names}
    used.update(cat.NULL_OPERATORS)
    assert used == set(cat.OPERATORS)


def test_the_compiler_never_reads_the_catalogues_sql_strings():
    """The `sql` strings are documentation. Asserted, not assumed: nothing
    in the package subscripts that key, so a mistake in one cannot become a
    statement. Checked on the AST so a mention in a docstring does not
    count as a use."""
    import ast

    tree = ast.parse((cat.CATALOGUE_PATH.parent / "compiler.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            assert node.slice.value != "sql"
        if isinstance(node, ast.Attribute):
            assert node.attr != "sql"


def test_the_compiler_never_builds_sql_from_text():
    """`text()`, `literal_column()` and `DDL()` are the three doors through
    which a Python string becomes SQL rather than a parameter. None of them
    is opened here. On the AST, so the module docstring saying so is not
    what makes the test pass."""
    import ast

    forbidden = {"text", "literal_column", "literal", "DDL", "eval", "exec", "quoted_name"}
    for module in ("compiler.py", "parse.py", "fields.py", "catalogue.py"):
        tree = ast.parse((cat.CATALOGUE_PATH.parent / module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            assert name not in forbidden, f"{module} calls {name}()"


def test_the_three_limits_are_present_and_sane():
    assert cat.MAX_DEPTH >= 1
    assert cat.MAX_RULES >= 1
    assert cat.MAX_LIST_LENGTH >= 1
    assert cat.MAX_EXPRESSION_BYTES > cat.MAX_RULES * 64


def test_the_file_on_disk_is_valid_json_with_the_keys_the_client_compares():
    raw = json.loads(cat.CATALOGUE_PATH.read_text(encoding="utf-8"))
    assert {k for k in raw if not k.startswith("//")} == {
        "version",
        "limits",
        "relationshipDirections",
        "columns",
        "operators",
        "operatorsByType",
        "nullOperators",
        "functions",
    }


@pytest.mark.parametrize("data_type", sorted(cat.DATA_TYPES))
def test_every_data_type_can_read_a_value_out_of_attrs(data_type):
    """A data type in the operator table with no reader in the compiler
    would be a 500 the moment somebody declared an attribute of it."""
    from app.expressions.compiler import _attribute_value

    expression = _attribute_value("x", data_type)
    compiled = expression.compile(dialect=sa.dialects.postgresql.dialect())
    # The attribute name is a bound parameter, never rendered.
    assert "'x'" not in str(compiled)
    assert "x" in compiled.params.values()
