"""The Pydantic IR models (app/ir/models.py) are bound to contract.json.

Two kinds of binding. **Vocabulary:** every closed list the models spell
out -- domains, relations, severities, senses, modes, depths, operators,
term kinds, versions, top-level keys, the name pattern -- equals the JSON.
**Behaviour:** the shared fixtures that `validate.py` and `validate.ts`
are held to are run through the models too: every valid document parses,
and every invalid one whose rule is structural is refused. Which rules
are structural is written down below, and every rule in the contract must
be in exactly one of the two lists, so a rule added to the contract has to
be placed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.ir import models
from app.ir.contract import CONTRACT, RULES
from app.ir.validate import check_shape

FIXTURES = json.loads((Path(__file__).parent / "ir_fixtures.json").read_text(encoding="utf-8"))

#: Rules a type can state: the models refuse every fixture that breaks one.
STRUCTURAL = frozenset({
    "ir_not_object", "version_missing", "version_unsupported", "key_missing", "key_unknown",
    "sets_not_array", "set_not_a_name",
    "parameters_not_object", "parameter_not_object", "parameter_not_a_name", "parameter_index_not_array",
    "variables_not_object", "variable_not_object", "variable_not_a_name", "variable_index_not_array",
    "variable_domain_missing", "variable_domain_unsupported",
    "constraints_not_array", "constraint_not_object", "constraint_id_not_a_name",
    "constraint_relation_unsupported", "constraint_severity_unsupported", "constraint_expression_missing",
    "objective_not_object", "objective_sense_unsupported", "objective_mode_unsupported",
    "objective_terms_invalid", "objective_term_malformed",
    "term_not_object", "term_kind_unknown", "term_kind_ambiguous", "const_not_a_number",
    "sum_malformed", "add_empty", "mul_arity",
    "binding_not_object", "bindings_invalid", "binding_index_not_a_name",
    "binding_via_not_object", "binding_via_depth_unsupported", "binding_via_anchor_invalid",
    "binding_via_steps_invalid", "binding_via_on_invalid", "where_group_malformed",
    "where_not_array", "where_filter_malformed", "where_operator_unknown",
    "relationships_not_array", "relationship_not_a_name",
    "when_malformed", "pwl_malformed", "fn_unknown", "fn_malformed",
    "interval_malformed", "scheduling_rule_malformed",
    "uncertainty_malformed", "connected_malformed", "route_malformed",
    # A stage is 1 or 2, and an interval has none: facts of the declaration itself.
    "stage_invalid",
    # A chance is {epsilon} with 0 < epsilon < 1: a fact of the object itself.
    "chance_malformed",
    # A predictors declaration is {name: {inputs: 1..32}}, and a predict carries a
    # non-empty `of`: facts of the objects themselves (Epic ML).
    "predictors_malformed", "predict_malformed",
})

#: Rules that need the whole document, the limits or the domain: validate.py's.
SEMANTIC = frozenset({
    "ir_too_large", "depth_exceeded", "terms_exceeded",
    "set_duplicated", "relationship_duplicated", "constraint_id_duplicated", "objective_term_id_duplicated",
    "binding_index_duplicated", "binding_set_not_declared", "binding_via_anchor_not_bound",
    "binding_via_rel_not_declared", "parameter_index_not_declared", "variable_index_not_declared",
    "reference_undeclared", "reference_index_arity", "index_not_bound", "index_set_mismatch",
    "mul_not_linear", "mul_not_quadratic", "constraint_weight_invalid", "variable_bounds_invalid",
    "variables_empty",
    "attribute_not_arithmetic", "attribute_not_declared", "binding_via_depth_not_transitive",
    "binding_via_both_not_self",
    "binding_via_endpoint_mismatch", "parameter_index_mismatch", "parameter_not_in_domain",
    "relationship_not_in_domain", "set_not_in_domain", "where_operator_not_offered",
    "where_value_not_of_type",
    # A when's version, variable, severity and linearity are facts about the
    # rest of the document.
    "when_needs_version_2", "when_not_binary", "when_on_soft", "when_on_product",
    "pwl_needs_version_2", "pwl_breakpoints_not_increasing",
    # A function's argument is linear by its degree, a fact of its terms.
    "fn_needs_version_2", "fn_argument_nonlinear",
    # Which variables an interval's parts are, and what a scheduling rule's
    # interval and amounts read, need the declarations.
    "interval_needs_version_2", "interval_part_invalid", "interval_size_invalid",
    "interval_read_as_number", "scheduling_needs_version_2", "scheduling_not_interval",
    "scheduling_rule_hard", "scheduling_amount_not_constant",
    "uncertainty_needs_version_2", "stage_needs_version_2",
    # Whether an `as` or an index names an edge, and whether that edge is a
    # path, are facts about the scope around it (queue R19).
    "edge_needs_version_2", "binding_via_as_invalid", "edge_not_an_index", "attr_along_invalid",
    # Which parameters hold entities, and of which set, is a fact of the
    # declarations around a term (queue R20b).
    "parameter_entity_invalid", "entity_parameter_read_as_number", "index_entry_invalid",
    "where_parameter_invalid", "parameter_entity_mismatch",
    # Whether the other index is bound, and over the same set, is a fact about the scope (benchmark, October 2026).
    "where_index_invalid",
    # Which parameter travel names, and over what, is a fact of the declarations (queue R15c).
    "route_travel_invalid",
    # Where a chance may be is a fact about the rest of the rule.
    "chance_needs_version_2", "chance_misplaced",
    # A connected rule's variable, its order, the relationship and its ends
    # are facts about the declarations and the domain.
    "connected_needs_version_2", "connected_not_binary", "connected_index_mismatch",
    "connected_via_invalid", "connected_on_soft", "connected_via_not_self", "connected_sources_invalid",
    # Likewise a route rule's variable, its order and its severity.
    "route_needs_version_2", "route_not_binary", "route_index_mismatch", "route_on_soft",
    # Which predictors a document declares, how many inputs each takes, and what
    # the domain holds are facts about the rest of the document (Epic ML).
    "predict_needs_version_2", "predict_unknown", "predict_arity", "predict_argument_nonlinear",
    "predictor_not_in_domain", "predictor_inputs_mismatch",
})


def test_every_rule_in_the_contract_is_placed_on_one_side():
    assert not (STRUCTURAL & SEMANTIC)
    assert STRUCTURAL | SEMANTIC == set(RULES), sorted(set(RULES) ^ (STRUCTURAL | SEMANTIC))


@pytest.mark.parametrize(
    "alias, key",
    [
        (models.VariableDomain, "variableDomains"),
        (models.Relation, "relations"),
        (models.TraversalDepth, "traversalDepths"),
        (models.Severity, "severities"),
        (models.Sense, "senses"),
        (models.ObjectiveMode, "objectiveModes"),
        (models.FilterOperator, "filterOperators"),
    ],
)
def test_each_closed_vocabulary_equals_the_contract(alias, key):
    assert sorted(get_args(alias)) == sorted(CONTRACT[key])


def test_the_function_names_are_the_contract_s_catalogue():
    assert sorted(get_args(models.FunctionName)) == sorted(CONTRACT["functions"])


def test_versions_term_kinds_keys_and_names_equal_the_contract():
    assert list(models.ACCEPTED_VERSIONS) == CONTRACT["acceptedVersions"]
    assert CONTRACT["version"] in models.ACCEPTED_VERSIONS
    assert sorted(models.TERM_KINDS) == sorted(CONTRACT["termKinds"])
    fields = models.ProblemIR.model_fields
    assert sorted(n for n, f in fields.items() if f.is_required()) == sorted(CONTRACT["topLevel"]["required"])
    assert sorted(n for n, f in fields.items() if not f.is_required()) == sorted(CONTRACT["topLevel"]["optional"])
    assert models.NAME_PATTERN == CONTRACT["namePattern"]
    assert models.MAX_INDICES == CONTRACT["limits"]["maxIndices"]


@pytest.mark.parametrize("case", FIXTURES["valid"], ids=lambda c: c["name"])
def test_every_valid_fixture_parses(case):
    assert check_shape(case["ir"]) is None  # the validator agrees it is valid
    models.parse(case["ir"])


STRUCTURAL_CASES = [c for c in FIXTURES["invalid"] if c["code"] in STRUCTURAL]


@pytest.mark.parametrize(
    "case", STRUCTURAL_CASES, ids=[f"{c['code']}-{i}" for i, c in enumerate(STRUCTURAL_CASES)]
)
def test_every_structural_fault_is_refused_by_the_models(case):
    with pytest.raises((ValidationError, ValueError)):
        models.parse(case["ir"])


def test_every_structural_rule_has_a_fixture():
    """A structural rule nobody exercises is one the models might not enforce."""
    exercised = {c["code"] for c in FIXTURES["invalid"]}
    assert STRUCTURAL <= exercised, sorted(STRUCTURAL - exercised)


def test_json_true_is_not_version_one():
    with pytest.raises(ValidationError):
        models.parse({"version": True, "sets": [], "parameters": {}, "variables": {}, "constraints": []})


def test_upgrade_v1_only_restamps():
    workforce = next(c for c in FIXTURES["valid"] if c["name"] == "workforce")["ir"]
    upgraded = models.upgrade_v1(workforce)
    assert upgraded == {**workforce, "version": 2}
    assert check_shape(upgraded) is None
    models.parse(upgraded)
    with pytest.raises(ValueError):
        models.upgrade_v1(upgraded)
