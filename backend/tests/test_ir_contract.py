"""The IR contract as an artefact: what must stay true of the files
themselves, with no database and no HTTP in sight.

The mechanism copied from the expression core (Ruling 37) is that one
file is the definition and everything else is pinned to it. Three pins
live here:

1. **Rules and fixtures are the same set.** A rule declared in
   `contract.json` with no invalid fixture is a rule nothing proves; a
   fixture whose code is not a declared rule is a refusal the contract
   does not admit. Both are failures, in both directions -- this is the
   IR's version of `test_expressions_catalogue.py`'s "the catalogue's
   function names are exactly the compiler's builder names".
2. **Every term kind has an implementation.** `_ShapeChecker` dispatches
   on `_term_<kind>`, so a kind added to the JSON without a handler --
   or a handler with no kind -- fails here rather than at request time.
3. **There is one operator vocabulary.** The contract's
   `filterOperators` is asserted to be a subset of the expression
   catalogue's `operators`, which is the whole reason a model's filters
   were not given a table of their own.

The fourth pin is in the browser: `frontend/src/ir/parity.test.ts` reads
`contract.json` off disk and deep-compares it with the TypeScript.
"""

import json
from pathlib import Path

import pytest

from app.api.validation import NAME_PATTERN
from app.expressions.catalogue import CATALOGUE as EXPRESSION_CATALOGUE
from app.ir import contract as contract_module
from app.ir.contract import (
    ALL_KEYS,
    CONTRACT,
    CONTRACT_PATH,
    DOMAIN_RULES,
    IR_VERSION,
    RULES,
    SHAPE_RULES,
    TERM_KINDS,
)
from app.ir.validate import _ShapeChecker

FIXTURE_PATH = Path(__file__).with_name("ir_fixtures.json")
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_the_contract_and_the_fixtures_declare_the_same_rules():
    declared = set(RULES)
    exercised = {case["code"] for case in FIXTURES["invalid"]}
    assert declared - exercised == set(), "rules with no invalid fixture"
    assert exercised - declared == set(), "fixtures for rules the contract does not declare"


def test_every_rule_is_either_shape_or_domain():
    assert SHAPE_RULES | DOMAIN_RULES == set(RULES)
    assert SHAPE_RULES & DOMAIN_RULES == set()
    assert DOMAIN_RULES, "if nothing needs the domain, the split is not earning its keep"


def test_rule_codes_are_unique_in_the_file():
    """`RULES` is a dict, so a duplicate would be silently swallowed by
    the loader and this is the only place that can see it."""
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    codes = [rule["code"] for rule in raw["rules"]]
    assert len(codes) == len(set(codes))


def test_every_rule_carries_a_readable_text():
    for code, rule in RULES.items():
        assert rule["text"].strip(), code
        assert not rule["text"].endswith("."), f"{code}: rule texts are clauses, not sentences"


def test_every_term_kind_has_an_implementation():
    handlers = {
        name.removeprefix("_term_") for name in dir(_ShapeChecker) if name.startswith("_term_")
    }
    assert handlers == set(TERM_KINDS)


def test_the_filter_vocabulary_is_the_expression_catalogue_s():
    """There is one operator table on this platform. `contract.py` raises
    at import time if this is ever false; this says so as a test, and
    says which names would be the problem."""
    catalogue = set(EXPRESSION_CATALOGUE["operators"])
    assert set(CONTRACT["filterOperators"]) <= catalogue
    # ... and every one of them is offered to at least one data type, or
    # it could never be used.
    offered = {op for ops in EXPRESSION_CATALOGUE["operatorsByType"].values() for op in ops}
    assert set(CONTRACT["filterOperators"]) <= offered


def test_the_filter_vocabulary_excludes_the_null_operators():
    """`is empty` / `is not empty` are the two operators `operators_for`
    adds for a nullable field, and they are deliberately not in the IR's
    filter vocabulary: a filter selects members of a set, and "the days
    whose `is_weekend` is absent" is a question about the domain's
    completeness rather than about the model.

    This is also what makes `check_against_domain` able to ask
    `operators_for(data_type, False)` -- with these two out, nullability
    cannot change which operators an attribute offers.
    """
    null_operators = set(EXPRESSION_CATALOGUE["nullOperators"])
    assert null_operators
    assert set(CONTRACT["filterOperators"]) & null_operators == set()


def test_names_follow_the_one_platform_name_rule():
    """`entity_type.name`, `attribute_def.name` and `parameter_def.name`
    all carry `^[a-z][a-z0-9_]*$` "because the names are used verbatim in
    IR expressions" (migration 0006). This is the IR end of that
    sentence: a second pattern here would make the claim false."""
    assert CONTRACT["namePattern"] == NAME_PATTERN


def test_the_document_carries_its_version_from_the_first_one():
    # Version 2 is what is written; version 1 documents are still read.
    assert IR_VERSION == 2
    assert CONTRACT["acceptedVersions"] == [1, 2]
    assert "version" in CONTRACT["topLevel"]["required"]


def test_the_top_level_keys_are_the_ones_the_validator_knows():
    assert ALL_KEYS == set(CONTRACT["topLevel"]["required"]) | set(
        CONTRACT["topLevel"]["optional"]
    )
    # `sets` and `parameters` are the two keys `snapshot_dataset()` reads.
    # They are required rather than optional so a frozen model always says
    # what data it draws on, even when the answer is "none".
    assert {"sets", "parameters"} <= set(CONTRACT["topLevel"]["required"])


def test_the_commentary_is_not_read_as_contract():
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert "//" in raw, "the file carries its own commentary; JSON has no comments"
    assert "//" not in CONTRACT


@pytest.mark.parametrize("name", ["maxDepth", "maxTerms", "maxIndices", "maxIrBytes"])
def test_every_limit_is_a_positive_integer(name):
    value = CONTRACT["limits"][name]
    assert isinstance(value, int) and not isinstance(value, bool) and value > 0


def test_the_contract_module_restates_nothing():
    """Everything the loader exports is read from the file. A constant
    typed into `contract.py` instead would survive an edit to the JSON,
    and the client's parity test would then be comparing against a lie."""
    source = Path(contract_module.__file__).read_text(encoding="utf-8")
    for literal in ('"binary"', '"minimize"', '"notIn"', '"<="'):
        assert literal not in source, f"{literal} is restated in contract.py"
