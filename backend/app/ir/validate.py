"""Judging a problem IR, in two halves that mirror the expression core.

:func:`check_shape` takes a decoded JSON document and returns the first
reason the contract refuses it, or ``None``. **It has no database in
scope, and that is the point** -- exactly as `app/expressions/parse.py`
records for its own half. Everything it can decide (the version, the
keys, the names, the arity of a subscript, whether an index is bound,
whether a product is linear) it decides with no query executed, so the
client can decide the same things in `frontend/src/ir/validate.ts` and
refuse before sending.

:func:`check_against_domain` is the other half, and it is the one that
closes a hole this platform has had since migration 0007: an IR naming a
set or a parameter the domain does not have is accepted by
``POST /problems/{id}/versions`` today and fails much later inside
``snapshot_dataset()``, as SQLSTATE P0001, which ``translate_db_error``
does not recognise -- i.e. as a 500 on whatever route eventually takes a
snapshot. The same judgement, made at submit time, is a 422 naming the
element (Rulings 19 and 30).

**One refusal, not all of them.** `parse.py` gives the reason: the client
validates the same document against the same contract before sending, so
a 422 from here is either a hand-written request or a contract the client
has not reloaded, and naming one thing precisely beats listing several.
The order the rules are applied in is therefore part of the contract, and
`backend/tests/ir_fixtures.json` pins it: every invalid fixture is wrong
in exactly one way, so the first refusal is the only refusal.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.expressions.catalogue import operators_for
from app.ir.contract import (
    ALL_KEYS,
    ARITHMETIC_ATTR_TYPES,
    CONNECTED_KEYS,
    ROUTE_KEYS,
    CONSTRAINT_KEYS,
    INTERVAL_KEYS,
    UNCERTAINTY_KINDS,
    SCHEDULING_KEYS,
    FILTER_OPERATORS,
    FUNCTIONS,
    ACCEPTED_VERSIONS,
    IR_VERSION,
    MAX_DEPTH,
    MAX_INDICES,
    MAX_IR_BYTES,
    MAX_TERMS,
    NAME_RE,
    RELATIONS,
    REQUIRED_KEYS,
    SENSES,
    OBJECTIVE_MODES,
    SEVERITIES,
    TERM_KINDS,
    TRAVERSAL_DEPTHS,
    VARIABLE_DOMAINS,
)
from app.models.v1_domain import (
    AttributeDef,
    EntityType,
    ParameterDef,
    RelationshipType,
)

Loc = list[str | int]

#: The keys each term kind may carry, beside the kind's own key.
_TERM_KEYS: dict[str, frozenset[str]] = {
    "const": frozenset(),
    "par": frozenset({"index"}),
    "var": frozenset({"index"}),
    "attr": frozenset(),
    "sum": frozenset({"over"}),
    "add": frozenset(),
    "mul": frozenset(),
    "pwl": frozenset({"points"}),
    "fn": frozenset({"of"}),
}
_LIST_OPERATORS = frozenset({"in", "notIn"})
_BINDING_KEYS = frozenset({"index", "set", "where", "via"})
#: A `via` names the relationship, where the *anchor* sits, and how far to
#: walk. `from` and `to` are the anchor's end, so the index being bound takes
#: the other one -- which is why exactly one of them appears and neither is
#: the new index's own name.
_VIA_KEYS = frozenset({"rel", "from", "to", "depth"})
_FILTER_KEYS = frozenset({"attr", "op", "value"})
_VARIABLE_KEYS = frozenset({"index", "domain", "lower", "upper", "stage"}) | INTERVAL_KEYS
_PARAMETER_KEYS = frozenset({"index", "uncertainty"})
_OBJECTIVE_KEYS = frozenset({"sense", "terms", "mode"})
_OBJECTIVE_TERM_KEYS = frozenset({"id", "weight", "expression"})


@dataclass(frozen=True)
class Refusal:
    """One reason an IR is not a model.

    `loc` is the path INSIDE the ir, so a router can prefix whatever it
    calls the field (`["body", "ir"]`) and a builder can highlight the
    element it names. `code` is the contract's rule code; no client
    branches on it, but the fixtures and the report do.
    """

    code: str
    loc: Loc
    message: str


def _is_int(value: Any) -> bool:
    """`bool` subclasses `int` in Python, and `True` is not a quantity."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """An integer or a finite decimal.

    `bool` is excluded for the reason above, and so are the IEEE specials:
    JSON cannot carry a NaN or an infinity, but a hand-built request can, and
    a coefficient of infinity is a model no solver answers usefully.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_name(value: Any) -> bool:
    return isinstance(value, str) and NAME_RE.fullmatch(value) is not None


def _unknown_key(node: dict[str, Any], allowed: frozenset[str], loc: Loc, what: str):
    for key in node:
        if key not in allowed:
            return Refusal(
                "key_unknown",
                [*loc, key],
                f"{json.dumps(key)} is not a key a {what} carries; this version reads "
                f"{', '.join(sorted(allowed))}",
            )
    return None


# --- the shape half --------------------------------------------------------


class _ShapeChecker:
    def __init__(self, ir: dict[str, Any]) -> None:
        self.ir = ir
        self.sets: set[str] = set()
        self.relationships: set[str] = set()
        self.parameters: dict[str, list[str]] = {}
        self.variables: dict[str, list[str]] = {}
        self.terms = 0

    # -- declarations --------------------------------------------------

    def check_sets(self):
        sets = self.ir["sets"]
        if not isinstance(sets, list):
            return Refusal(
                "sets_not_array",
                ["sets"],
                "sets must be an array of entity type names: snapshot_dataset() reads it "
                "with jsonb_array_elements_text and anything else reaches it as an error",
            )
        for i, name in enumerate(sets):
            if not _is_name(name):
                return Refusal(
                    "set_not_a_name",
                    ["sets", i],
                    f"{json.dumps(name)} is not an entity type name; entity_type.name is "
                    "^[a-z][a-z0-9_]*$",
                )
            if name in self.sets:
                return Refusal("set_duplicated", ["sets", i], f"the set {name!r} is named twice")
            self.sets.add(name)
        return None

    def check_relationships(self):
        """`relationships` declares which edge types the dataset must freeze.

        Optional, and absent means none -- which is every model written
        before traversal existed. It mirrors `sets` exactly, and for the same
        reason: `snapshot_dataset()` freezes what this names and nothing else,
        so a `via` that walked an undeclared type would reference data the
        frozen document does not carry.
        """
        relationships = self.ir.get("relationships")
        if relationships is None:
            return None
        if not isinstance(relationships, list):
            return Refusal(
                "relationships_not_array",
                ["relationships"],
                "relationships must be an array of relationship type names; omit the key "
                "entirely for a model that does not traverse",
            )
        for i, name in enumerate(relationships):
            if not _is_name(name):
                return Refusal(
                    "relationship_not_a_name",
                    ["relationships", i],
                    f"{json.dumps(name)} is not a relationship type name; "
                    "relationship_type.name is ^[a-z][a-z0-9_]*$",
                )
            if name in self.relationships:
                return Refusal(
                    "relationship_duplicated",
                    ["relationships", i],
                    f"the relationship {name!r} is named twice",
                )
            self.relationships.add(name)
        return None

    def check_parameters(self):
        parameters = self.ir["parameters"]
        if not isinstance(parameters, dict):
            return Refusal(
                "parameters_not_object",
                ["parameters"],
                "parameters must be an object keyed by parameter name: snapshot_dataset() "
                "reads it with jsonb_object_keys",
            )
        for name, declaration in parameters.items():
            at: Loc = ["parameters", name]
            if not _is_name(name):
                return Refusal(
                    "parameter_not_a_name",
                    at,
                    f"{json.dumps(name)} is not a parameter name; parameter_def.name is "
                    "^[a-z][a-z0-9_]*$",
                )
            if not isinstance(declaration, dict):
                return Refusal(
                    "parameter_not_object",
                    at,
                    f"the declaration of {name!r} must be an object carrying its index",
                )
            problem = _unknown_key(declaration, _PARAMETER_KEYS, at, "parameter declaration")
            if problem:
                return problem
            index = declaration.get("index")
            if (
                not isinstance(index, list)
                or not 1 <= len(index) <= MAX_INDICES
                or not all(isinstance(s, str) for s in index)
            ):
                return Refusal(
                    "parameter_index_not_array",
                    [*at, "index"],
                    f"{name!r} must declare index as an array of 1 to {MAX_INDICES} set names, "
                    "in the order parameter_def.index_type_ids holds them",
                )
            for j, set_name in enumerate(index):
                if set_name not in self.sets:
                    return Refusal(
                        "parameter_index_not_declared",
                        [*at, "index", j],
                        f"{name!r} is indexed by {set_name!r}, which this model does not "
                        "declare in sets, so no dataset would carry it",
                    )
            problem = self._check_uncertainty(name, declaration, at)
            if problem:
                return problem
            self.parameters[name] = list(index)
        return None

    def _check_uncertainty(self, name: str, declaration: dict[str, Any], at: Loc):
        """How a parameter's values may be wrong (version 2): within a range of
        each -- `deviation` a fraction of the value, `gamma` how many of a
        rule's cells may be off at once (Bertsimas-Sim's budget; all of them
        when absent) -- or by scenario. What the robust solve reads."""
        if "uncertainty" not in declaration:
            return None
        loc: Loc = [*at, "uncertainty"]
        if self.ir.get("version") == 1:
            return Refusal(
                "uncertainty_needs_version_2",
                loc,
                f"{name!r} declares an uncertainty, which version 1 does not have; publish it as "
                "version 2",
            )
        spec = declaration["uncertainty"]
        kind = spec.get("kind") if isinstance(spec, dict) else None
        if kind not in UNCERTAINTY_KINDS:
            return Refusal(
                "uncertainty_malformed",
                loc,
                f"an uncertainty names its kind: {' or '.join(sorted(UNCERTAINTY_KINDS))}",
            )
        allowed = {"kind", "deviation", "gamma"} if kind == "interval" else {"kind"}
        extra = sorted(set(spec) - allowed)
        if extra:
            return Refusal(
                "uncertainty_malformed",
                [*loc, extra[0]],
                f"a {kind} uncertainty carries no {extra[0]}",
            )
        if kind == "interval":
            for key in ("deviation", "gamma"):
                if key not in spec:
                    if key == "deviation":
                        return Refusal(
                            "uncertainty_malformed",
                            [*loc, key],
                            f"{name!r} is uncertain within a range, so it says how far: a "
                            "deviation, as a fraction of each value (0.1 for ten per cent)",
                        )
                    continue
                if not _is_number(spec[key]) or spec[key] < 0:
                    return Refusal(
                        "uncertainty_malformed",
                        [*loc, key],
                        f"{name!r}'s {key} is a non-negative number",
                    )
        return None

    def check_variables(self):
        variables = self.ir["variables"]
        if not isinstance(variables, dict):
            return Refusal(
                "variables_not_object", ["variables"], "variables must be an object keyed by name"
            )
        if not variables:
            return Refusal(
                "variables_empty",
                ["variables"],
                "a model declares at least one variable; there is nothing here to decide",
            )
        for name, declaration in variables.items():
            at: Loc = ["variables", name]
            if not _is_name(name):
                return Refusal(
                    "variable_not_a_name",
                    at,
                    f"{json.dumps(name)} is not a variable name; names on this platform are "
                    "^[a-z][a-z0-9_]*$",
                )
            if not isinstance(declaration, dict):
                return Refusal(
                    "variable_not_object",
                    at,
                    f"the declaration of {name!r} must be an object carrying its index and domain",
                )
            problem = _unknown_key(declaration, _VARIABLE_KEYS, at, "variable declaration")
            if problem:
                return problem
            index = declaration.get("index")
            if (
                not isinstance(index, list)
                or len(index) > MAX_INDICES
                or not all(isinstance(s, str) for s in index)
            ):
                return Refusal(
                    "variable_index_not_array",
                    [*at, "index"],
                    f"{name!r} must declare index as an array of up to {MAX_INDICES} set names; "
                    "a scalar variable declares an empty one",
                )
            for j, set_name in enumerate(index):
                if set_name not in self.sets:
                    return Refusal(
                        "variable_index_not_declared",
                        [*at, "index", j],
                        f"{name!r} is indexed by {set_name!r}, which this model does not "
                        "declare in sets, so nothing would size it",
                    )
            if "domain" not in declaration:
                return Refusal(
                    "variable_domain_missing",
                    [*at, "domain"],
                    f"{name!r} must declare a domain: it is what decides the model's class, "
                    "so nothing defaults it",
                )
            domain = declaration["domain"]
            if domain not in VARIABLE_DOMAINS:
                return Refusal(
                    "variable_domain_unsupported",
                    [*at, "domain"],
                    f"{json.dumps(domain)} is not a variable domain version {IR_VERSION} solves; "
                    f"it has {', '.join(sorted(VARIABLE_DOMAINS))}",
                )
            problem = self._check_interval_keys(name, declaration, at)
            if problem:
                return problem
            problem = self._check_bounds(name, declaration, at)
            if problem:
                return problem
            problem = self._check_stage(name, declaration, at)
            if problem:
                return problem
            self.variables[name] = list(index)
        for name, declaration in variables.items():
            if declaration["domain"] == "interval":
                problem = self._check_interval_parts(name, declaration, ["variables", name])
                if problem:
                    return problem
        return None

    def _check_interval_keys(self, name: str, declaration: dict[str, Any], at: Loc):
        """An interval (version 2) is not a number: it ties a start and an
        end variable together, `end = start + size`, and may be absent when
        its `presence` is 0. Only it carries those keys, and it carries no
        bounds -- its start's and end's own are the window."""
        if declaration["domain"] != "interval":
            stray = sorted(INTERVAL_KEYS & set(declaration))
            if stray:
                return Refusal(
                    "interval_malformed",
                    [*at, stray[0]],
                    f"{name!r} is {declaration['domain']}, and only an interval names a "
                    f"{stray[0]}",
                )
            return None
        if self.ir.get("version") == 1:
            return Refusal(
                "interval_needs_version_2",
                [*at, "domain"],
                f"{name!r} is an interval, which version 1 does not have; publish it as version 2",
            )
        for key in ("start", "end", "size"):
            if key not in declaration:
                return Refusal(
                    "interval_malformed",
                    [*at, key],
                    f"the interval {name!r} names no {key}; an interval is a start, an end and "
                    "the size between them",
                )
        for key in ("lower", "upper"):
            if key in declaration:
                return Refusal(
                    "interval_malformed",
                    [*at, key],
                    f"the interval {name!r} carries a {key} bound; its start and end variables "
                    "carry the window it may be placed in",
                )
        return None

    def _check_interval_parts(self, name: str, declaration: dict[str, Any], at: Loc):
        index = self.variables[name]
        declared = self.ir["variables"]
        for key, domain in (("start", "integer"), ("end", "integer"), ("presence", "binary")):
            if key not in declaration:
                continue
            part = declaration[key]
            spec = declared.get(part) if isinstance(part, str) else None
            if not isinstance(spec, dict) or spec.get("domain") != domain or self.variables.get(part) != index:
                return Refusal(
                    "interval_part_invalid",
                    [*at, key],
                    f"the {key} of the interval {name!r} must be {'an' if domain == 'integer' else 'a'} "
                    f"{domain} variable declared over [{', '.join(index)}], as the interval is; "
                    f"{json.dumps(part)} is not",
                )
        size = declaration["size"]
        if isinstance(size, str):
            if self.parameters.get(size) != index:
                return Refusal(
                    "interval_size_invalid",
                    [*at, "size"],
                    f"the size of the interval {name!r} names {json.dumps(size)}, which is not a "
                    f"parameter declared over [{', '.join(index)}], as the interval is",
                )
        elif not _is_int(size) or size < 0:
            return Refusal(
                "interval_size_invalid",
                [*at, "size"],
                f"the size of the interval {name!r} is {json.dumps(size)}; a size is a "
                "non-negative whole number, or a parameter",
            )
        return None

    def _check_stage(self, name: str, declaration: dict[str, Any], at: Loc):
        """When a decision is made (version 2): `1`, now -- the plan -- or `2`,
        once the uncertain data is known -- the recourse. What a two-stage
        stochastic solve reads; every other solve ignores it. An interval has
        none: its start and end carry the stage."""
        if "stage" not in declaration:
            return None
        loc: Loc = [*at, "stage"]
        if self.ir.get("version") == 1:
            return Refusal(
                "stage_needs_version_2",
                loc,
                f"{name!r} declares a stage, which version 1 does not have; publish it as version 2",
            )
        stage = declaration["stage"]
        if declaration["domain"] == "interval":
            return Refusal("stage_invalid", loc, f"{name!r} is an interval; its start and end carry the stage")
        if isinstance(stage, bool) or stage not in (1, 2):
            return Refusal(
                "stage_invalid",
                loc,
                f"{name!r}'s stage is 1 (decided now) or 2 (decided once the uncertain data is known), "
                f"not {json.dumps(stage)}",
            )
        return None

    def _check_bounds(self, name: str, declaration: dict[str, Any], at: Loc):
        if declaration["domain"] == "interval":
            return None
        for key in ("lower", "upper"):
            if key not in declaration:
                continue
            if declaration["domain"] == "binary":
                return Refusal(
                    "variable_bounds_invalid",
                    [*at, key],
                    f"{name!r} is binary, so its bounds are 0 and 1 and it carries none",
                )
            if not _is_number(declaration[key]):
                return Refusal(
                    "variable_bounds_invalid",
                    [*at, key],
                    f"{name!r}'s {key} bound must be a number",
                )
            if declaration["domain"] == "integer" and not _is_int(declaration[key]):
                return Refusal(
                    "variable_bounds_invalid",
                    [*at, key],
                    f"{name!r} is an integer variable, so its {key} bound is a whole number; "
                    f"{json.dumps(declaration[key])} would be rounded by every solver that "
                    "took it, and differently by some",
                )
        if "lower" in declaration and "upper" in declaration:
            if declaration["lower"] > declaration["upper"]:
                return Refusal(
                    "variable_bounds_invalid",
                    [*at, "upper"],
                    f"{name!r} has lower {declaration['lower']} above upper "
                    f"{declaration['upper']}, so it has no admissible value",
                )
        return None

    # -- constraints ----------------------------------------------------

    def check_constraints(self):
        constraints = self.ir["constraints"]
        if not isinstance(constraints, list):
            return Refusal(
                "constraints_not_array",
                ["constraints"],
                "constraints must be an array; they are ordered and addressed by id",
            )
        seen: set[str] = set()
        for i, constraint in enumerate(constraints):
            at: Loc = ["constraints", i]
            if not isinstance(constraint, dict):
                return Refusal("constraint_not_object", at, "each constraint must be an object")
            problem = _unknown_key(constraint, CONSTRAINT_KEYS, at, "constraint")
            if problem:
                return problem
            identifier = constraint.get("id")
            if not _is_name(identifier):
                return Refusal(
                    "constraint_id_not_a_name",
                    [*at, "id"],
                    f"{json.dumps(identifier)} is not a constraint id; ids travel into "
                    "scenario.patch and constraint_result.constraint_id, and are "
                    "^[a-z][a-z0-9_]*$",
                )
            if identifier in seen:
                return Refusal(
                    "constraint_id_duplicated",
                    [*at, "id"],
                    f"the constraint id {identifier!r} is used twice; constraint_result is "
                    "keyed by it, so two constraints with one id could not both report",
                )
            seen.add(identifier)

            scope: dict[str, str] = {}
            if "forall" in constraint:
                result = self.check_bindings(constraint["forall"], [*at, "forall"], scope)
                if isinstance(result, Refusal):
                    return result
                scope = result

            if "chance" in constraint and (
                "connected" in constraint or "route" in constraint
                or any(kind in constraint for kind in SCHEDULING_KEYS)
            ):
                problem = self._check_chance(constraint, at, identifier)
                if problem:
                    return problem
            if any(kind in constraint for kind in SCHEDULING_KEYS):
                problem = self._check_scheduling(constraint, at, scope, identifier)
                if problem:
                    return problem
                continue
            if "connected" in constraint:
                problem = self._check_connected(constraint, at, identifier)
                if problem:
                    return problem
                continue
            if "route" in constraint:
                problem = self._check_route(constraint, at, identifier)
                if problem:
                    return problem
                continue

            for key in ("left", "relation", "right"):
                if key not in constraint:
                    return Refusal(
                        "constraint_expression_missing",
                        [*at, key],
                        f"the constraint {identifier!r} has no {key}. A constraint that is "
                        "named but not expressed cannot be solved, classified or diffed; if "
                        "it is still being drafted, leave it out of the version",
                    )
            if constraint["relation"] not in RELATIONS:
                return Refusal(
                    "constraint_relation_unsupported",
                    [*at, "relation"],
                    f"{json.dumps(constraint['relation'])} is not a relation version "
                    f"{IR_VERSION} expresses; it has {', '.join(sorted(RELATIONS))}",
                )
            if constraint.get("severity") not in SEVERITIES:
                return Refusal(
                    "constraint_severity_unsupported",
                    [*at, "severity"],
                    f"{json.dumps(constraint.get('severity'))} is not a severity; a constraint "
                    f"is {' or '.join(sorted(SEVERITIES))}, and nothing defaults it",
                )
            problem = self._check_weight(constraint, at, identifier)
            if problem:
                return problem

            for key in ("left", "right"):
                problem = self.check_term(constraint[key], [*at, key], scope, 1)
                if problem:
                    return problem
            problem = self._check_when(constraint, at, scope, identifier)
            if problem:
                return problem
            problem = self._check_chance(constraint, at, identifier)
            if problem:
                return problem
        return None

    def _check_scheduling(self, constraint: dict[str, Any], at: Loc, scope: dict[str, str], identifier: str):
        """`no_overlap` (the intervals never run at once) and `cumulative`
        (at every moment the running intervals' demands stay within the
        capacity), each over the intervals an `over` ranges across, once per
        instance of the `forall` -- version 2, solved by CP-SAT."""
        kinds = [kind for kind in SCHEDULING_KEYS if kind in constraint]
        kind = kinds[0]
        if self.ir.get("version") == 1:
            # The rule as a whole: without it the document is version 1 again.
            return Refusal(
                "scheduling_needs_version_2",
                at,
                f"the constraint {identifier!r} is a {kind} rule, which version 1 does not have; "
                "publish it as version 2",
            )
        extra = kinds[1:] + [key for key in ("left", "relation", "right") if key in constraint]
        if extra:
            return Refusal(
                "scheduling_rule_malformed",
                [*at, extra[0]],
                f"the constraint {identifier!r} is a {kind} rule and also carries {extra[0]}; a "
                "constraint is one expression or one scheduling rule",
            )
        body = constraint[kind]
        loc: Loc = [*at, kind]
        if not isinstance(body, dict) or set(body) != SCHEDULING_KEYS[kind]:
            return Refusal(
                "scheduling_rule_malformed",
                loc,
                f"a {kind} carries exactly {', '.join(sorted(SCHEDULING_KEYS[kind]))}",
            )
        if constraint.get("severity") not in SEVERITIES:
            return Refusal(
                "constraint_severity_unsupported",
                [*at, "severity"],
                f"{json.dumps(constraint.get('severity'))} is not a severity; a constraint "
                f"is {' or '.join(sorted(SEVERITIES))}, and nothing defaults it",
            )
        for key in ("severity", "weight", "when"):
            if key in constraint and (key != "severity" or constraint[key] != "hard"):
                return Refusal(
                    "scheduling_rule_hard",
                    [*at, key],
                    f"the {kind} rule {identifier!r} is hard and unconditional; a scheduling "
                    "rule has no price for being broken and no switch",
                )
        inner = self.check_bindings(body["over"], [*loc, "over"], scope)
        if isinstance(inner, Refusal):
            return inner
        interval = body["interval"]
        if not isinstance(interval, dict) or set(interval) != {"var", "index"}:
            return Refusal(
                "scheduling_rule_malformed",
                [*loc, "interval"],
                'a scheduling rule names its intervals as {"var": "task", "index": [...]}',
            )
        problem = self._reference(interval, [*loc, "interval"], inner, "var", self.variables)
        if problem:
            return problem
        if self.ir["variables"][interval["var"]].get("domain") != "interval":
            return Refusal(
                "scheduling_not_interval",
                [*loc, "interval", "var"],
                f"{interval['var']!r} is {self.ir['variables'][interval['var']].get('domain')}; "
                f"a {kind} rule is over interval variables",
            )
        if kind == "cumulative":
            for key, where in (("demand", inner), ("capacity", scope)):
                problem = self.check_term(body[key], [*loc, key], where, 1)
                if problem:
                    return problem
                if _degree(body[key]) > 0:
                    return Refusal(
                        "scheduling_amount_not_constant",
                        [*loc, key],
                        f"the {key} of {identifier!r} reads a decision; it is a number the "
                        "data gives",
                    )
        return None

    def _check_connected(self, constraint: dict[str, Any], at: Loc, identifier: str):
        """`connected` (version 2): for every group, the units assigned to it
        form one piece over `via` -- a district is one contiguous area. The
        rule binds its own units and groups, so it stands outside any forall."""
        if self.ir.get("version") == 1:
            return Refusal(
                "connected_needs_version_2",
                at,
                f"the constraint {identifier!r} is a connected rule, which version 1 does not have; "
                "publish it as version 2",
            )
        body = constraint["connected"]
        loc: Loc = [*at, "connected"]
        beside = [key for key in ("left", "relation", "right", "forall", *SCHEDULING_KEYS) if key in constraint]
        if beside:
            return Refusal(
                "connected_malformed",
                [*at, beside[0]],
                f"the constraint {identifier!r} is a connected rule and also carries {beside[0]}; a "
                "connected rule is not also an expression, and binds its own indices",
            )
        if not isinstance(body, dict):
            return Refusal(
                "connected_malformed",
                loc,
                "a connected rule names assign, units, groups and via, and optionally empty",
            )
        odd = next((key for key in ("assign", "units", "groups", "via") if key not in body), None) or next(
            (key for key in body if key not in CONNECTED_KEYS), None
        )
        if odd is None and body.get("empty", "forbidden") not in ("forbidden", "allowed"):
            odd = "empty"
        if odd is not None:
            what = "missing" if odd not in body else "forbidden or allowed" if odd == "empty" else "not one of them"
            return Refusal(
                "connected_malformed",
                [*loc, odd],
                "a connected rule names assign, units, groups and via, and optionally empty "
                f"(forbidden or allowed); {odd!r} is {what}",
            )
        for key in ("severity", "weight", "when"):
            if key in constraint and (key != "severity" or constraint[key] != "hard"):
                return Refusal(
                    "connected_on_soft",
                    [*at, key],
                    f"the connected rule {identifier!r} is hard and unconditional; a piece that is "
                    "half connected has no price",
                )
        if constraint.get("severity") != "hard":
            return Refusal(
                "constraint_severity_unsupported",
                [*at, "severity"],
                f"{json.dumps(constraint.get('severity'))} is not a severity; a connected rule is hard",
            )
        scope: dict[str, str] = {}
        for part in ("units", "groups"):
            inner = self.check_bindings([body[part]], [*loc, part], scope)
            if isinstance(inner, Refusal):
                # One binding, addressed as the body's own key, not as a list.
                return Refusal(inner.code, [*loc, part, *inner.loc[len(loc) + 2 :]], inner.message)
            scope = inner
        assign = body["assign"]
        if not isinstance(assign, dict) or set(assign) != {"var", "index"}:
            return Refusal(
                "connected_malformed",
                [*loc, "assign"],
                'a connected rule names its variable as {"var": "assign", "index": [unit, group]}',
            )
        expected = [body["units"]["index"], body["groups"]["index"]]
        if assign["index"] != expected:
            return Refusal(
                "connected_index_mismatch",
                [*loc, "assign", "index"],
                f"{assign['var']!r} is read as [{', '.join(expected)}]: the units' index, then the "
                "groups' index",
            )
        problem = self._reference(assign, [*loc, "assign"], scope, "var", self.variables)
        if problem:
            return problem
        if self.ir["variables"][assign["var"]].get("domain") != "binary":
            return Refusal(
                "connected_not_binary",
                [*loc, "assign", "var"],
                f"{assign['var']!r} must be binary: a unit is in a group or it is not",
            )
        if body["via"] not in self.relationships:
            return Refusal(
                "connected_via_invalid",
                [*loc, "via"],
                f"{json.dumps(body['via'])} is not a relationship this model declares in "
                "relationships, so no dataset would carry its edges",
            )
        return None

    def _check_route(self, constraint: dict[str, Any], at: Loc, identifier: str):
        """`route` (version 2, queue R15b): every stop but the depot visited
        once, each vehicle leaving the depot at most once and coming back,
        with each vehicle's load within its capacity when both are named.
        `visit[vehicle, stop, next stop]` is yes or no. The rule binds its own
        vehicles and stops, so it stands outside any forall."""
        if self.ir.get("version") == 1:
            return Refusal(
                "route_needs_version_2",
                at,
                f"the constraint {identifier!r} is a route rule, which version 1 does not have; "
                "publish it as version 2",
            )
        body = constraint["route"]
        loc: Loc = [*at, "route"]
        beside = [key for key in ("left", "relation", "right", "forall", "connected", *SCHEDULING_KEYS)
                  if key in constraint]
        if beside:
            return Refusal(
                "route_malformed",
                [*at, beside[0]],
                f"the constraint {identifier!r} is a route rule and also carries {beside[0]}; a "
                "route rule is not also an expression, and binds its own indices",
            )
        if not isinstance(body, dict):
            return Refusal("route_malformed", loc,
                           "a route rule names visit, vehicles, stops and depot, and optionally demand and capacity")
        odd, what = None, ""
        for key in ("visit", "vehicles", "stops", "depot"):
            if key not in body:
                odd, what = key, "missing"
                break
        if odd is None:
            odd = next((key for key in body if key not in ROUTE_KEYS), None)
            what = "not one of them"
        if odd is None:
            odd = next((key for key in ("depot", "demand", "capacity")
                        if key in body and not (isinstance(body[key], str) and body[key])), None)
            what = "not a name"
        if odd is None and ("demand" in body) != ("capacity" in body):
            odd = "capacity" if "demand" in body else "demand"
            what = "missing: demand and capacity come together"
        if odd is not None:
            return Refusal(
                "route_malformed",
                [*loc, odd],
                "a route rule names visit, vehicles, stops and depot, and optionally demand and "
                f"capacity (both or neither); {odd!r} is {what}",
            )
        for key in ("severity", "weight", "when"):
            if key in constraint and (key != "severity" or constraint[key] != "hard"):
                return Refusal(
                    "route_on_soft",
                    [*at, key],
                    f"the route rule {identifier!r} is hard and unconditional; a stop half visited has no price",
                )
        if constraint.get("severity") != "hard":
            return Refusal(
                "constraint_severity_unsupported",
                [*at, "severity"],
                f"{json.dumps(constraint.get('severity'))} is not a severity; a route rule is hard",
            )
        scope: dict[str, str] = {}
        for part in ("vehicles", "stops"):
            inner = self.check_bindings([body[part]], [*loc, part], scope)
            if isinstance(inner, Refusal):
                return Refusal(inner.code, [*loc, part, *inner.loc[len(loc) + 2 :]], inner.message)
            scope = inner
        visit = body["visit"]
        if not isinstance(visit, dict) or set(visit) != {"var", "index"} or not isinstance(visit["index"], list):
            return Refusal(
                "route_malformed",
                [*loc, "visit"],
                'a route rule names its variable as {"var": "visit", "index": [vehicle, stop, next stop]}',
            )
        vehicle, stop = body["vehicles"]["index"], body["stops"]["index"]
        index = visit["index"]
        if (len(index) != 3 or index[:2] != [vehicle, stop] or not isinstance(index[2], str)
                or index[2] in (vehicle, stop)):
            return Refusal(
                "route_index_mismatch",
                [*loc, "visit", "index"],
                f"{visit['var']!r} is read as [{vehicle}, {stop}, <next stop>]: the vehicles' index, the "
                "stops' index, then a third name for the stop it goes to",
            )
        problem = self._reference(visit, [*loc, "visit"], {**scope, index[2]: body["stops"]["set"]}, "var",
                                  self.variables)
        if problem:
            return problem
        if self.ir["variables"][visit["var"]].get("domain") != "binary":
            return Refusal(
                "route_not_binary",
                [*loc, "visit", "var"],
                f"{visit['var']!r} must be binary: a vehicle goes from one stop to the next or it does not",
            )
        return None

    def _check_chance(self, constraint: dict[str, Any], at: Loc, identifier: str):
        """`chance` (version 2): the rule must hold in all but `epsilon` of the
        futures a stochastic solve samples -- one switch per future, at most
        that share switched off. Only a hard, linear expression rule with no
        `when` of its own: its switch is the chance's."""
        if "chance" not in constraint:
            return None
        loc: Loc = [*at, "chance"]
        if self.ir.get("version") == 1:
            return Refusal(
                "chance_needs_version_2",
                loc,
                f"the constraint {identifier!r} carries a chance, which version 1 does not have; "
                "publish it as version 2",
            )
        chance = constraint["chance"]
        epsilon = chance.get("epsilon") if isinstance(chance, dict) else None
        if not isinstance(chance, dict) or set(chance) != {"epsilon"} or not _is_number(epsilon) or not 0 < epsilon < 1:
            return Refusal(
                "chance_malformed",
                loc,
                "a chance is the share of futures the rule may fail in, strictly between 0 and 1: "
                '{"epsilon": 0.1} holds it in 90% of them',
            )
        if "connected" in constraint or "route" in constraint or any(kind in constraint for kind in SCHEDULING_KEYS):
            return Refusal("chance_misplaced", loc, f"the constraint {identifier!r} is a scheduling, connected or route rule; a chance is on an expression rule")
        if constraint.get("severity") == "soft":
            return Refusal("chance_misplaced", loc, f"the constraint {identifier!r} is soft; a rule that may bend at a cost needs no chance -- make it hard")
        if "when" in constraint:
            return Refusal("chance_misplaced", loc, f"the constraint {identifier!r} already has a when; a chance switches the rule itself")
        if _degree(constraint["left"]) > 1 or _degree(constraint["right"]) > 1:
            return Refusal("chance_misplaced", loc, f"the constraint {identifier!r} multiplies decisions; a chance rule is linear")
        return None

    def _check_when(self, constraint: dict[str, Any], at: Loc, scope: dict[str, str], identifier: str):
        """`when`: the rule holds only while a binary variable is `is` (1 by
        default) -- an implication, solved natively where a backend can
        (CP-SAT's enforcement literals, SCIP's indicator constraints)."""
        if "when" not in constraint:
            return None
        when = constraint["when"]
        loc: Loc = [*at, "when"]
        if self.ir.get("version") == 1:
            return Refusal(
                "when_needs_version_2",
                loc,
                f"the constraint {identifier!r} carries a when, which version 1 does not have; "
                "publish it as version 2",
            )
        if (
            not isinstance(when, dict)
            or not set(when) <= {"var", "index", "is"}
            or "var" not in when
            or "index" not in when
            or ("is" in when and (isinstance(when["is"], bool) or when["is"] not in (0, 1)))
        ):
            return Refusal(
                "when_malformed",
                loc,
                "a when names a binary variable and its index, and optionally the value it "
                'must have for the rule to hold: {"var": "open", "index": ["f"], "is": 1}',
            )
        problem = self.check_term({"var": when["var"], "index": when["index"]}, loc, scope, 1)
        if problem:
            return problem
        declared = self.ir["variables"].get(when["var"], {})
        if declared.get("domain") != "binary":
            return Refusal(
                "when_not_binary",
                [*loc, "var"],
                f"{when['var']!r} is {declared.get('domain')}; a when switches a rule on and off, "
                "so it names a yes-or-no decision",
            )
        if constraint.get("severity") == "soft":
            return Refusal(
                "when_on_soft",
                loc,
                f"the constraint {identifier!r} is soft and conditional; a rule that may be "
                "broken at a cost needs no switch -- make it hard, or drop the when",
            )
        if _degree(constraint["left"]) > 1 or _degree(constraint["right"]) > 1:
            return Refusal(
                "when_on_product",
                loc,
                f"the constraint {identifier!r} multiplies decisions and carries a when; a "
                "conditional rule is linear",
            )
        return None

    def _check_weight(self, constraint: dict[str, Any], at: Loc, identifier: str):
        weight = constraint.get("weight")
        if constraint["severity"] == "soft":
            if not _is_int(weight) or weight < 1:
                return Refusal(
                    "constraint_weight_invalid",
                    [*at, "weight"],
                    f"the soft constraint {identifier!r} must carry a positive integer weight; "
                    "a soft constraint with no penalty is one the solver may ignore for free",
                )
        elif "weight" in constraint:
            return Refusal(
                "constraint_weight_invalid",
                [*at, "weight"],
                f"the hard constraint {identifier!r} carries a weight; a hard constraint has "
                "no penalty, so soften it in a scenario instead",
            )
        return None

    # -- bindings and filters -------------------------------------------

    def check_bindings(self, bindings: Any, loc: Loc, outer: dict[str, str]):
        """Returns the scope the bindings add to `outer`, or a Refusal."""
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_INDICES:
            return Refusal(
                "bindings_invalid",
                loc,
                f"this must be an array binding between 1 and {MAX_INDICES} indices; omit the "
                "key entirely when there is nothing to range over",
            )
        scope = dict(outer)
        for j, binding in enumerate(bindings):
            at: Loc = [*loc, j]
            if not isinstance(binding, dict):
                return Refusal(
                    "binding_not_object",
                    at,
                    "a binding names an index and the set it ranges over",
                )
            problem = _unknown_key(binding, _BINDING_KEYS, at, "binding")
            if problem:
                return problem
            index = binding.get("index")
            if not _is_name(index):
                return Refusal(
                    "binding_index_not_a_name",
                    [*at, "index"],
                    f"{json.dumps(index)} is not an index name; names on this platform are "
                    "^[a-z][a-z0-9_]*$",
                )
            if index in scope:
                return Refusal(
                    "binding_index_duplicated",
                    [*at, "index"],
                    f"the index {index!r} is already bound here; shadowing would leave which "
                    "one a term meant to the reader",
                )
            set_name = binding.get("set")
            if set_name not in self.sets:
                return Refusal(
                    "binding_set_not_declared",
                    [*at, "set"],
                    f"{json.dumps(set_name)} is not a set this model declares, so no dataset "
                    "would carry it",
                )
            # Order matters here and is the whole reason `via` is a binding
            # rather than a term: the anchor must already be bound when the
            # traversal starts, so it is checked against `scope` BEFORE this
            # binding's own index joins it. Checking afterwards would let a
            # binding walk from itself.
            problem = self._check_via(binding, at, scope)
            if problem:
                return problem
            scope[index] = set_name
            problem = self._check_where(binding, at)
            if problem:
                return problem
        return scope

    def _check_via(self, binding: dict[str, Any], at: Loc, scope: dict[str, str]):
        if "via" not in binding:
            return None
        via = binding["via"]
        here: Loc = [*at, "via"]
        if not isinstance(via, dict):
            return Refusal(
                "binding_via_not_object",
                here,
                "a via names the relationship to walk and which end this binding starts from",
            )
        problem = _unknown_key(via, _VIA_KEYS, here, "via")
        if problem:
            return problem

        if via.get("rel") not in self.relationships:
            return Refusal(
                "binding_via_rel_not_declared",
                [*here, "rel"],
                f"{json.dumps(via.get('rel'))} is not a relationship this model declares in "
                "relationships, so no dataset would carry its edges",
            )

        ends = [end for end in ("from", "to") if end in via]
        if len(ends) != 1 or not _is_name(via[ends[0]]):
            return Refusal(
                "binding_via_anchor_invalid",
                here,
                "a via names exactly one of from or to, and it is the index the walk starts "
                "at; the end named is where that index sits, so this binding takes the other",
            )
        anchor = via[ends[0]]
        if anchor not in scope:
            return Refusal(
                "binding_via_anchor_not_bound",
                [*here, ends[0]],
                f"the index {anchor!r} is not bound where this traversal starts; bind it in "
                "an enclosing forall, or earlier in this same list",
            )
        if "depth" in via and via["depth"] not in TRAVERSAL_DEPTHS:
            return Refusal(
                "binding_via_depth_unsupported",
                [*here, "depth"],
                f"{json.dumps(via['depth'])} is not a depth version {IR_VERSION} walks; it "
                f"has {', '.join(sorted(TRAVERSAL_DEPTHS))}",
            )
        return None

    def _check_where(self, binding: dict[str, Any], at: Loc):
        if "where" not in binding:
            return None
        filters = binding["where"]
        if not isinstance(filters, list):
            return Refusal(
                "where_not_array",
                [*at, "where"],
                "where is an array of filters, combined with and; version "
                f"{IR_VERSION} has no groups and no or",
            )
        for k, entry in enumerate(filters):
            here: Loc = [*at, "where", k]
            if not isinstance(entry, dict):
                return Refusal("where_filter_malformed", here, "each filter must be an object")
            problem = _unknown_key(entry, _FILTER_KEYS, here, "filter")
            if problem:
                return problem
            if not _is_name(entry.get("attr")):
                return Refusal(
                    "where_filter_malformed",
                    [*here, "attr"],
                    "a filter names an attribute of the set its binding ranges over",
                )
            operator = entry.get("op")
            if not isinstance(operator, str):
                return Refusal(
                    "where_filter_malformed",
                    [*here, "op"],
                    "a filter names a comparison; version "
                    f"{IR_VERSION} has no unary filters, so op is never absent",
                )
            if operator not in FILTER_OPERATORS:
                return Refusal(
                    "where_operator_unknown",
                    [*here, "op"],
                    f"{json.dumps(operator)} is not a filter comparison; the vocabulary is the "
                    "expression catalogue's, narrowed to "
                    f"{', '.join(sorted(FILTER_OPERATORS))}",
                )
            if "value" not in entry:
                return Refusal(
                    "where_filter_malformed", [*here, "value"], "a filter carries a value"
                )
            value = entry["value"]
            if operator in _LIST_OPERATORS:
                ok = isinstance(value, list) and value and all(_is_scalar(v) for v in value)
            else:
                ok = _is_scalar(value)
            if not ok:
                return Refusal(
                    "where_filter_malformed",
                    [*here, "value"],
                    f"{json.dumps(operator)} takes "
                    + (
                        "a non-empty array of values"
                        if operator in _LIST_OPERATORS
                        else "a single value"
                    ),
                )
        return None

    # -- terms ------------------------------------------------------------

    def check_term(self, term: Any, loc: Loc, scope: dict[str, str], depth: int):
        if depth > MAX_DEPTH:
            return Refusal(
                "depth_exceeded",
                loc,
                f"this term nests deeper than {MAX_DEPTH}, which is past what a builder can "
                "render and a reader can check",
            )
        self.terms += 1
        if self.terms > MAX_TERMS:
            return Refusal(
                "terms_exceeded",
                loc,
                f"this model holds more than {MAX_TERMS} terms; this one took it past the limit",
            )
        if not isinstance(term, dict):
            return Refusal(
                "term_not_object",
                loc,
                "every term is an object naming its kind, so nothing has to be inferred",
            )
        kinds = [kind for kind in TERM_KINDS if kind in term]
        if not kinds:
            return Refusal(
                "term_kind_unknown",
                loc,
                f"a term names one of {', '.join(sorted(TERM_KINDS))}; this names none of them",
            )
        if len(kinds) > 1:
            return Refusal(
                "term_kind_ambiguous",
                loc,
                f"this term names {' and '.join(sorted(kinds))}; which one wins would be left "
                "to key order",
            )
        kind = kinds[0]
        problem = _unknown_key(term, _TERM_KEYS[kind] | {kind}, loc, f"{kind} term")
        if problem:
            return problem
        return getattr(self, f"_term_{kind}")(term, loc, scope, depth)

    def _term_const(self, term, loc, scope, depth):
        if not _is_number(term["const"]):
            return Refusal(
                "const_not_a_number",
                [*loc, "const"],
                f"{json.dumps(term['const'])} is not a number",
            )
        return None

    def _term_par(self, term, loc, scope, depth):
        return self._reference(term, loc, scope, "par", self.parameters)

    def _term_var(self, term, loc, scope, depth):
        problem = self._reference(term, loc, scope, "var", self.variables)
        if problem:
            return problem
        if self.ir["variables"][term["var"]].get("domain") == "interval":
            return Refusal(
                "interval_read_as_number",
                [*loc, "var"],
                f"{term['var']!r} is an interval, which is not a number; read its start or end "
                "variable instead",
            )
        return None

    def _reference(self, term, loc, scope, kind, declared):
        name = term[kind]
        what = "parameter" if kind == "par" else "variable"
        if not isinstance(name, str) or name not in declared:
            return Refusal(
                "reference_undeclared",
                [*loc, kind],
                f"{json.dumps(name)} is not a {what} this model declares",
            )
        index_types = declared[name]
        subscript = term.get("index")
        if not isinstance(subscript, list) or len(subscript) != len(index_types):
            return Refusal(
                "reference_index_arity",
                [*loc, "index"],
                f"{name!r} is declared over {len(index_types)} "
                f"{'set' if len(index_types) == 1 else 'sets'} "
                f"({', '.join(index_types) or 'none'}), so it is subscripted with that many "
                "indices",
            )
        for j, index in enumerate(subscript):
            if not isinstance(index, str) or index not in scope:
                return Refusal(
                    "index_not_bound",
                    [*loc, "index", j],
                    f"{json.dumps(index)} is not bound by any enclosing forall or over, so it "
                    "has no range",
                )
            if scope[index] != index_types[j]:
                return Refusal(
                    "index_set_mismatch",
                    [*loc, "index", j],
                    f"{name!r} is indexed by {index_types[j]!r} in position {j}, but "
                    f"{index!r} ranges over {scope[index]!r}",
                )
        return None

    def _term_attr(self, term, loc, scope, depth):
        reference = term["attr"]
        if not isinstance(reference, dict) or set(reference) != {"of", "name"}:
            return Refusal(
                "term_not_object",
                [*loc, "attr"],
                "an attr term is {\"of\": <index>, \"name\": <attribute>}",
            )
        if not isinstance(reference["of"], str) or reference["of"] not in scope:
            return Refusal(
                "index_not_bound",
                [*loc, "attr", "of"],
                f"{json.dumps(reference['of'])} is not bound by any enclosing forall or over",
            )
        if not _is_name(reference["name"]):
            return Refusal(
                "term_not_object",
                [*loc, "attr", "name"],
                f"{json.dumps(reference['name'])} is not an attribute name; "
                "attribute_def.name is ^[a-z][a-z0-9_]*$",
            )
        return None

    def _term_sum(self, term, loc, scope, depth):
        if "over" not in term:
            return Refusal(
                "sum_malformed",
                [*loc, "over"],
                "a sum ranges over something; without an over it is its own body under a "
                "misleading name",
            )
        result = self.check_bindings(term["over"], [*loc, "over"], scope)
        if isinstance(result, Refusal):
            return result
        return self.check_term(term["sum"], [*loc, "sum"], result, depth + 1)

    def _term_pwl(self, term, loc, scope, depth):
        """`{"pwl": {"var": "x", "index": [...]}, "points": [[x0, y0], ...]}`:
        f(x) by linear interpolation between the points, x kept within the
        first and last. A variable in its own right, so degree 1."""
        if self.ir.get("version") == 1:
            return Refusal(
                "pwl_needs_version_2",
                [*loc, "pwl"],
                "a piecewise-linear term is version 2; publish the model as version 2",
            )
        argument = term["pwl"]
        if not isinstance(argument, dict) or set(argument) != {"var", "index"}:
            return Refusal(
                "pwl_malformed",
                [*loc, "pwl"],
                'a pwl is a curve of one variable: {"var": "x", "index": [...]}',
            )
        problem = self.check_term(argument, [*loc, "pwl"], scope, depth + 1)
        if problem:
            return problem
        points = term.get("points")
        if (
            not isinstance(points, list)
            or len(points) < 2
            or not all(isinstance(p, list) and len(p) == 2 and all(_is_number(n) for n in p) for p in points)
        ):
            return Refusal(
                "pwl_malformed",
                [*loc, "points"],
                "a pwl's points are at least two [x, y] pairs of numbers",
            )
        xs = [p[0] for p in points]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            return Refusal(
                "pwl_breakpoints_not_increasing",
                [*loc, "points"],
                "a pwl's points are in strictly increasing x, so each x has one value",
            )
        return None

    def _term_fn(self, term, loc, scope, depth):
        """`{"fn": "log", "of": <term>}`: a function from the contract's
        catalogue, applied to a linear argument. Of degree 1 when the
        argument reads a decision (it stands for one), 0 when it is data."""
        if self.ir.get("version") == 1:
            return Refusal(
                "fn_needs_version_2",
                [*loc, "fn"],
                "a function term is version 2; publish the model as version 2",
            )
        name = term["fn"]
        if not isinstance(name, str) or name not in FUNCTIONS:
            return Refusal(
                "fn_unknown",
                [*loc, "fn"],
                f"{json.dumps(name)} is not a function this platform knows; it knows "
                f"{', '.join(sorted(FUNCTIONS))}",
            )
        if "of" not in term:
            return Refusal(
                "fn_malformed",
                [*loc, "of"],
                f"a function is applied to something: {name} needs its argument in `of`",
            )
        problem = self.check_term(term["of"], [*loc, "of"], scope, depth + 1)
        if problem:
            return problem
        if _degree(term["of"]) > 1:
            return Refusal(
                "fn_argument_nonlinear",
                [*loc, "of"],
                f"the argument of {name} multiplies decisions together; a function is applied "
                "to a linear argument",
            )
        return None

    def _term_add(self, term, loc, scope, depth):
        summands = term["add"]
        if not isinstance(summands, list) or not summands:
            return Refusal(
                "add_empty",
                [*loc, "add"],
                'add carries at least one summand; zero is written {"const": 0}',
            )
        for i, summand in enumerate(summands):
            problem = self.check_term(summand, [*loc, "add", i], scope, depth + 1)
            if problem:
                return problem
        return None

    def _term_mul(self, term, loc, scope, depth):
        factors = term["mul"]
        if not isinstance(factors, list) or len(factors) != 2:
            return Refusal(
                "mul_arity",
                [*loc, "mul"],
                "mul has exactly two factors, so linearity is a check on a pair",
            )
        for i, factor in enumerate(factors):
            problem = self.check_term(factor, [*loc, "mul", i], scope, depth + 1)
            if problem:
                return problem
        # Degree, not "how many factors mention a variable": a product of two
        # variables is allowed in a rule and in a weighted objective, and
        # x * (y * z) must still be refused there, which counting factors
        # cannot see.
        degree = _degree(term)
        if degree <= 1:
            return None
        if not self._quadratic_allowed(loc):
            return Refusal(
                "mul_not_linear",
                [*loc, "mul"],
                "both factors of this product contain a variable, which makes it quadratic; "
                + (
                    "a lexicographic objective is solved one term at a time, holding each at "
                    "its best, and holding a quadratic term would need a quadratic rule"
                    if loc[:1] == ["objective"]
                    else "only a rule or a weighted objective may be quadratic"
                ),
            )
        if degree > 2:
            return Refusal(
                "mul_not_quadratic",
                [*loc, "mul"],
                f"this product multiplies {degree} variables together; "
                f"{'a rule' if loc[:1] == ['constraints'] else 'an objective'} may be "
                "quadratic -- two variables at most -- and no higher",
            )
        return None

    def _quadratic_allowed(self, loc: Loc) -> bool:
        """A rule and a weighted objective's terms may be quadratic; a
        lexicographic objective stays linear (see `_term_mul`)."""
        if loc[:1] == ["constraints"]:
            return True
        if loc[:1] != ["objective"]:
            return False
        objective = self.ir.get("objective")
        mode = objective.get("mode", "weighted") if isinstance(objective, dict) else "weighted"
        return mode == "weighted"

    # -- objective ---------------------------------------------------------

    def check_objective(self):
        if "objective" not in self.ir:
            return None
        objective = self.ir["objective"]
        if not isinstance(objective, dict):
            return Refusal(
                "objective_not_object",
                ["objective"],
                "objective is an object; omit the key entirely for a feasibility problem",
            )
        problem = _unknown_key(objective, _OBJECTIVE_KEYS, ["objective"], "objective")
        if problem:
            return problem
        if objective.get("sense") not in SENSES:
            return Refusal(
                "objective_sense_unsupported",
                ["objective", "sense"],
                f"{json.dumps(objective.get('sense'))} is not a sense; an objective is "
                f"{' or '.join(sorted(SENSES))}",
            )
        mode = objective.get("mode", "weighted")
        if mode not in OBJECTIVE_MODES:
            return Refusal(
                "objective_mode_unsupported",
                ["objective", "mode"],
                f"{json.dumps(mode)} is not an objective mode; an objective is "
                f"{' or '.join(sorted(OBJECTIVE_MODES))}, or omit mode for a weighted sum",
            )
        terms = objective.get("terms")
        if not isinstance(terms, list) or not terms:
            return Refusal(
                "objective_terms_invalid",
                ["objective", "terms"],
                "an objective carries a non-empty terms array; omit the objective otherwise",
            )
        seen: set[str] = set()
        for i, term in enumerate(terms):
            at: Loc = ["objective", "terms", i]
            if not isinstance(term, dict):
                return Refusal("objective_term_malformed", at, "each objective term is an object")
            problem = _unknown_key(term, _OBJECTIVE_TERM_KEYS, at, "objective term")
            if problem:
                return problem
            if not _is_name(term.get("id")):
                return Refusal(
                    "objective_term_malformed",
                    [*at, "id"],
                    f"{json.dumps(term.get('id'))} is not a term id; ids are how a result says "
                    "which part of the objective cost what",
                )
            if term["id"] in seen:
                return Refusal(
                    "objective_term_id_duplicated",
                    [*at, "id"],
                    f"the objective term id {term['id']!r} is used twice",
                )
            seen.add(term["id"])
            if not _is_int(term.get("weight")):
                return Refusal(
                    "objective_term_malformed",
                    [*at, "weight"],
                    f"the term {term['id']!r} must carry an integer weight",
                )
            if "expression" not in term:
                return Refusal(
                    "objective_term_malformed",
                    [*at, "expression"],
                    f"the term {term['id']!r} has no expression, so it names a cost nothing "
                    "defines",
                )
            problem = self.check_term(term["expression"], [*at, "expression"], {}, 1)
            if problem:
                return problem
        return None


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _degree(term: Any) -> int:
    """How many variables multiply together in the worst part of a term: 0 for
    data, 1 for linear, 2 for quadratic. Only ever called on a term whose
    factors `check_term` has already accepted, so the shapes are known."""
    if not isinstance(term, dict):
        return 0
    if "var" in term or "pwl" in term:
        return 1
    if "fn" in term:
        # It stands for a decision of its own when its argument reads one.
        return 1 if _degree(term["of"]) else 0
    if "sum" in term:
        return _degree(term["sum"])
    if "add" in term:
        return max((_degree(child) for child in term["add"]), default=0)
    if "mul" in term:
        return sum(_degree(child) for child in term["mul"])
    return 0


def check_shape(ir: Any) -> Refusal | None:
    """The first reason the contract refuses this document, without a
    database. Returns None when the document is shape-valid."""
    # First, because every other rule walks the document.
    try:
        # `ensure_ascii=False` is load-bearing, not a preference: Python
        # escapes a non-ASCII character to a six-byte `\uXXXX` by default,
        # where `JSON.stringify` writes the character itself. With the
        # default the two validators disagree about the size of the same
        # document by a factor of three -- `padNoteWide` in
        # `ir_fixtures.json` is the case that found it.
        size = len(
            json.dumps(ir, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
        )
    except (TypeError, ValueError):  # pragma: no cover -- a decoded body is serialisable
        size = 0
    if size > MAX_IR_BYTES:
        return Refusal(
            "ir_too_large",
            [],
            f"this IR is {size} bytes; the limit is {MAX_IR_BYTES}",
        )
    if not isinstance(ir, dict):
        return Refusal("ir_not_object", [], "an IR is a JSON object")
    if "version" not in ir:
        return Refusal(
            "version_missing",
            ["version"],
            f"an IR carries its version; this platform expresses version {IR_VERSION}",
        )
    if isinstance(ir["version"], bool) or ir["version"] not in ACCEPTED_VERSIONS:
        return Refusal(
            "version_unsupported",
            ["version"],
            f"{json.dumps(ir['version'])} is not an IR version this platform expresses; it "
            f"expresses {' and '.join(str(v) for v in ACCEPTED_VERSIONS)}",
        )
    for key in REQUIRED_KEYS:
        if key not in ir:
            return Refusal(
                "key_missing",
                [key],
                f"an IR states its {key}, even when it has none",
            )
    problem = _unknown_key(ir, ALL_KEYS, [], "model")
    if problem:
        return problem

    checker = _ShapeChecker(ir)
    for step in (
        checker.check_sets,
        checker.check_relationships,
        checker.check_parameters,
        checker.check_variables,
        checker.check_constraints,
        checker.check_objective,
    ):
        problem = step()
        if problem:
            return problem
    return None


# --- the domain half -------------------------------------------------------


class _DomainWorld:
    """What one domain declares, in the shape the rules ask about."""

    def __init__(self, db: Session, domain_id: int) -> None:
        typed = db.execute(
            select(EntityType.id, EntityType.name, EntityType.inherited_from).where(EntityType.domain_id == domain_id)
        ).all()
        rows = [(type_id, name) for type_id, name, _ in typed]
        self.entity_type_ids = {name: type_id for type_id, name in rows}
        self.type_name_by_id = {type_id: name for type_id, name in rows}
        #: Migration 0066 (queue R18): each type's ancestors, nearest first.
        parent = {type_id: inherited for type_id, _, inherited in typed}
        self.ancestors: dict[str, list[str]] = {}
        for type_id, name in rows:
            chain, up = [], parent.get(type_id)
            while up is not None and up in self.type_name_by_id and len(chain) < 64:
                chain.append(self.type_name_by_id[up])
                up = parent.get(up)
            self.ancestors[name] = chain
        self.attributes: dict[tuple[str, str], dict[str, Any]] = {}
        if rows:
            for type_id, name, data_type, required, enum_values in db.execute(
                select(
                    AttributeDef.entity_type_id,
                    AttributeDef.name,
                    AttributeDef.data_type,
                    AttributeDef.required,
                    AttributeDef.enum_values,
                ).where(AttributeDef.entity_type_id.in_(self.type_name_by_id))
            ).all():
                self.attributes[(self.type_name_by_id[type_id], name)] = {
                    "data_type": data_type,
                    "required": required,
                    "enum_values": list(enum_values) if enum_values else [],
                }
        # An entity of a type has its ancestors' attributes too.
        for name, chain in self.ancestors.items():
            for ancestor in chain:
                for (owner, attribute), declared in list(self.attributes.items()):
                    if owner == ancestor:
                        self.attributes.setdefault((name, attribute), declared)
        self.parameter_index: dict[str, list[str]] = {}
        for name, index_type_ids in db.execute(
            select(ParameterDef.name, ParameterDef.index_type_ids).where(
                ParameterDef.domain_id == domain_id
            )
        ).all():
            self.parameter_index[name] = [
                self.type_name_by_id.get(type_id, f"#{type_id}") for type_id in index_type_ids
            ]
        #: name -> (from set name, to set name). The endpoint types are what
        #: makes a `via` checkable: walking `works_in` from a `unit` is a
        #: modelling mistake the domain can see and the document cannot.
        self.relationship_ends: dict[str, tuple[str, str]] = {}
        for name, from_id, to_id in db.execute(
            select(
                RelationshipType.name,
                RelationshipType.from_type_id,
                RelationshipType.to_type_id,
            ).where(RelationshipType.domain_id == domain_id)
        ).all():
            self.relationship_ends[name] = (
                self.type_name_by_id.get(from_id, f"#{from_id}"),
                self.type_name_by_id.get(to_id, f"#{to_id}"),
            )


    def is_a(self, set_name: str | None, ancestor: str) -> bool:
        """`set_name` is `ancestor` or inherits from it (queue R18)."""
        return set_name == ancestor or ancestor in self.ancestors.get(set_name or "", [])


def _value_is_of_type(value: Any, declared: dict[str, Any]) -> bool:
    data_type = declared["data_type"]
    if data_type == "integer":
        return _is_int(value)
    if data_type == "number":
        return _is_int(value) or isinstance(value, float)
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type == "enum":
        return isinstance(value, str) and value in declared["enum_values"]
    # text, date and time are all stored and compared as strings, exactly as
    # `entity_validate` checks them (`jsonb_typeof(v) = 'string'`).
    return isinstance(value, str)


class _DomainChecker:
    def __init__(self, ir: dict[str, Any], world: _DomainWorld) -> None:
        self.ir = ir
        self.world = world

    def check(self) -> Refusal | None:
        for i, name in enumerate(self.ir["sets"]):
            if name not in self.world.entity_type_ids:
                return Refusal(
                    "set_not_in_domain",
                    ["sets", i],
                    f"there is no entity type called {name!r} in this problem's domain, so "
                    "snapshot_dataset() could not freeze it",
                )
        for i, name in enumerate(self.ir.get("relationships") or []):
            if name not in self.world.relationship_ends:
                return Refusal(
                    "relationship_not_in_domain",
                    ["relationships", i],
                    f"there is no relationship type called {name!r} in this problem's domain, "
                    "so snapshot_dataset() could not freeze its edges",
                )
        for name, declaration in self.ir["parameters"].items():
            if name not in self.world.parameter_index:
                return Refusal(
                    "parameter_not_in_domain",
                    ["parameters", name],
                    f"there is no parameter called {name!r} in this problem's domain, so "
                    "snapshot_dataset() could not freeze it",
                )
            declared = self.world.parameter_index[name]
            if list(declaration["index"]) != declared:
                return Refusal(
                    "parameter_index_mismatch",
                    ["parameters", name, "index"],
                    f"{name!r} is indexed by [{', '.join(declared)}] in this domain, not "
                    f"[{', '.join(declaration['index'])}]; the order is the order its cells "
                    "are stored in",
                )
        for i, constraint in enumerate(self.ir["constraints"]):
            at: Loc = ["constraints", i]
            scope: dict[str, str] = {}
            if "forall" in constraint:
                problem = self._bindings(constraint["forall"], [*at, "forall"], scope)
                if problem:
                    return problem
            if "connected" in constraint:
                problem = self._connected(constraint["connected"], [*at, "connected"])
                if problem:
                    return problem
                continue
            if "route" in constraint:
                inner: dict[str, str] = {}
                for part in ("vehicles", "stops"):
                    problem = self._bindings([constraint["route"][part]], [*at, "route", part], inner)
                    if problem:
                        return Refusal(problem.code, [*at, "route", part, *problem.loc[len(at) + 3:]], problem.message)
                continue
            kind = next((k for k in SCHEDULING_KEYS if k in constraint), None)
            if kind is not None:
                body = constraint[kind]
                inner = dict(scope)
                problem = self._bindings(body["over"], [*at, kind, "over"], inner)
                if problem:
                    return problem
                for key, where in (("demand", inner), ("capacity", scope)):
                    if key in body:
                        problem = self._term(body[key], [*at, kind, key], where)
                        if problem:
                            return problem
                continue
            for key in ("left", "right"):
                problem = self._term(constraint[key], [*at, key], scope)
                if problem:
                    return problem
        objective = self.ir.get("objective")
        if isinstance(objective, dict):
            for i, term in enumerate(objective["terms"]):
                problem = self._term(term["expression"], ["objective", "terms", i, "expression"], {})
                if problem:
                    return problem
        return None

    def _connected(self, body: dict[str, Any], loc: Loc) -> Refusal | None:
        """The units and groups as bindings, and `via` joining the units'
        type to itself: one piece is a walk from unit to unit."""
        scope: dict[str, str] = {}
        for part in ("units", "groups"):
            problem = self._bindings([body[part]], [*loc, part], scope)
            if problem:
                return Refusal(problem.code, [*loc, part, *problem.loc[len(loc) + 2 :]], problem.message)
        units = body["units"]["set"]
        ends = self.world.relationship_ends[body["via"]]
        if not (self.world.is_a(units, ends[0]) and self.world.is_a(units, ends[1])):
            return Refusal(
                "connected_via_not_self",
                [*loc, "via"],
                f"{body['via']!r} joins {ends[0]} to {ends[1]}; a group of {units} is one piece "
                f"only over a relationship from {units} to {units}",
            )
        return None

    def _bindings(self, bindings: list[Any], loc: Loc, scope: dict[str, str]) -> Refusal | None:
        for j, binding in enumerate(bindings):
            # Before the index joins the scope, for the reason check_bindings
            # records: the anchor is whatever was bound *outside* this
            # binding, never this binding itself.
            problem = self._via(binding, [*loc, j], scope)
            if problem:
                return problem
            scope[binding["index"]] = binding["set"]
            for k, entry in enumerate(binding.get("where", [])):
                here: Loc = [*loc, j, "where", k]
                declared = self.world.attributes.get((binding["set"], entry["attr"]))
                if declared is None:
                    return Refusal(
                        "attribute_not_declared",
                        [*here, "attr"],
                        f"{binding['set']!r} declares no attribute {entry['attr']!r}, so no "
                        "snapshot row would carry one",
                    )
                # `nullable=False`: the IR's filter vocabulary is the
                # expression catalogue's MINUS the two null operators (a
                # test asserts the two sets are disjoint), and those are
                # the only operators `operators_for` adds for a nullable
                # field. Passing the attribute's real nullability would
                # therefore be a value that can never change the answer,
                # and unpinnable by any fixture.
                offered = operators_for(declared["data_type"], False)
                if entry["op"] not in offered:
                    return Refusal(
                        "where_operator_not_offered",
                        [*here, "op"],
                        f"a {declared['data_type']} attribute offers "
                        f"{', '.join(offered)}, not {entry['op']!r}",
                    )
                values = entry["value"] if isinstance(entry["value"], list) else [entry["value"]]
                for value in values:
                    if not _value_is_of_type(value, declared):
                        return Refusal(
                            "where_value_not_of_type",
                            [*here, "value"],
                            f"{json.dumps(value)} is not a value of "
                            f"{binding['set']}.{entry['attr']}, which is "
                            f"{declared['data_type']}",
                        )
        return None

    def _via(self, binding: dict[str, Any], at: Loc, scope: dict[str, str]) -> Refusal | None:
        """The half of a traversal only the domain can judge: that the two
        ends are the entity types the relationship actually joins."""
        via = binding.get("via")
        if via is None:
            return None
        here: Loc = [*at, "via"]
        name = via["rel"]
        if name not in self.world.relationship_ends:
            return Refusal(
                "relationship_not_in_domain",
                here + ["rel"],
                f"there is no relationship type called {name!r} in this problem's domain, so "
                "snapshot_dataset() could not freeze its edges",
            )
        from_set, to_set = self.world.relationship_ends[name]
        # `from` in the document means "the anchor sits at the from end", so
        # the index being bound takes the `to` end, and vice versa.
        anchor_end, bound_end = ("from", to_set) if "from" in via else ("to", from_set)
        anchor_set = from_set if anchor_end == "from" else to_set
        actual_anchor = scope.get(via[anchor_end])
        # A type that inherits from an end's type stands in for it (queue R18).
        if not self.world.is_a(actual_anchor, anchor_set) or not self.world.is_a(binding["set"], bound_end):
            return Refusal(
                "binding_via_endpoint_mismatch",
                here,
                f"{name!r} joins {from_set} to {to_set}; walking it with "
                f"{via[anchor_end]!r} at the {anchor_end} end needs that index bound to "
                f"{anchor_set} and this one to {bound_end}, not {actual_anchor} and "
                f"{binding['set']}",
            )
        if via.get("depth", "one") != "one" and from_set != to_set:
            return Refusal(
                "binding_via_depth_not_transitive",
                [*here, "depth"],
                f"{name!r} joins {from_set} to {to_set}, which are different, so walking it "
                "more than once lands nowhere; only a relationship whose two ends are the "
                f"same entity type has a {via['depth']!r} depth",
            )
        return None

    def _term(self, term: dict[str, Any], loc: Loc, scope: dict[str, str]) -> Refusal | None:
        if "attr" in term:
            set_name = scope[term["attr"]["of"]]
            name = term["attr"]["name"]
            declared = self.world.attributes.get((set_name, name))
            if declared is None:
                return Refusal(
                    "attribute_not_declared",
                    [*loc, "attr", "name"],
                    f"{set_name!r} declares no attribute {name!r}, so no snapshot row would "
                    "carry one",
                )
            if declared["data_type"] not in ARITHMETIC_ATTR_TYPES:
                return Refusal(
                    "attribute_not_arithmetic",
                    [*loc, "attr", "name"],
                    f"{set_name}.{name} is {declared['data_type']}; only "
                    f"{', '.join(sorted(ARITHMETIC_ATTR_TYPES))} attributes are numbers a "
                    f"version {IR_VERSION} model computes with",
                )
            return None
        if "sum" in term:
            inner = dict(scope)
            problem = self._bindings(term["over"], [*loc, "over"], inner)
            if problem:
                return problem
            return self._term(term["sum"], [*loc, "sum"], inner)
        for key in ("add", "mul"):
            if key in term:
                for i, child in enumerate(term[key]):
                    problem = self._term(child, [*loc, key, i], scope)
                    if problem:
                        return problem
        return None


def check_against_domain(db: Session, domain_id: int, ir: dict[str, Any]) -> Refusal | None:
    """The rules only the domain's own rows can decide. `ir` must already
    have passed :func:`check_shape`; this walks it assuming that."""
    return _DomainChecker(ir, _DomainWorld(db, domain_id)).check()


def validate_ir(db: Session, domain_id: int, ir: Any) -> Refusal | None:
    """Both halves, shape first. The one entry point a router wants."""
    return check_shape(ir) or check_against_domain(db, domain_id, ir)
