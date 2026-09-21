"""The validator, against the shared fixture set.

`ir_fixtures.json` is read here and by `frontend/src/ir/fixtures.test.ts`.
Both assert the `code` and `loc` written in the file -- never each
other's output -- for the same reason `expression_cross_check.json`
records: two implementations that agree with each other and disagree with
the contract prove nothing.

Three properties are asserted that a per-case assertion alone would not
give:

**Single fault.** Every invalid case is wrong in exactly one way. For a
`domain` case that is checkable directly: `check_shape` must find nothing
at all, which proves the fault is the domain rule and only that. For a
`shape` case the equivalent is that the case is built on one of the
valid fixtures' shapes, and `test_every_shape_case_differs_from_a_valid_one`
gets at it from the other side -- the case must become valid again once
the offending element is the only thing replaced.

**The refusal is the first one.** The validator returns one refusal, so
the order rules are applied in is part of the contract; the fixtures pin
it by being single-fault.

**The seed is the worked example.** `test_the_seeded_ir_is_the_workforce
_fixture` asserts `app.seed`'s IR *is* the fixture, so the demo cannot
drift from the contract it illustrates.
"""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.ir.contract import DOMAIN_RULES, MAX_DEPTH, MAX_IR_BYTES, MAX_TERMS, SHAPE_RULES
from app.ir.validate import check_against_domain, check_shape, validate_ir

FIXTURE_PATH = Path(__file__).with_name("ir_fixtures.json")
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
VALID = FIXTURES["valid"]
INVALID = FIXTURES["invalid"]


def build_generated(spec: dict) -> dict:
    """The four limit-case forms. Kept identical to `buildGenerated` in
    `frontend/src/ir/fixtures.test.ts`; an IR large enough to break a
    limit is not worth five hundred hand-written lines, and the shape it
    takes is still written down -- here and there."""
    kind, count = spec["kind"], spec["count"]
    note = None
    if kind == "nestedAdd":
        term: dict = {"const": 1}
        for _ in range(count):
            term = {"add": [term]}
    elif kind == "wideAdd":
        term = {"add": [{"const": 1} for _ in range(count)]}
    elif kind == "padNote":
        term = {"const": 0}
        note = "x" * count
    elif kind == "padNoteWide":
        # Two bytes per character in UTF-8, one character in Python and
        # one UTF-16 code unit in JavaScript: the padding that tells a
        # byte count from a character count.
        term = {"const": 0}
        note = "\u00e9" * count
    else:  # pragma: no cover -- a fixture naming a form neither side has
        raise AssertionError(f"unknown generator {kind!r}")
    constraint = {
        "id": "c_one",
        "left": term,
        "relation": "<=",
        "right": {"const": 1},
        "severity": "hard",
    }
    if note is not None:
        constraint["note"] = note
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": "binary"}},
        "constraints": [constraint],
    }


def case_ir(case: dict):
    return build_generated(case["generate"]) if "generate" in case else case["ir"]


def _id(case):
    return case["code"] if isinstance(case, dict) and "code" in case else case["name"]


SHAPE_CASES = [c for c in INVALID if c["code"] in SHAPE_RULES]
DOMAIN_CASES = [c for c in INVALID if c["code"] in DOMAIN_RULES]


# --------------------------------------------------------------------------
# the world the domain rules are judged against
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world():
    """The fixture file's `domain` block, built for real. Torn down by
    deleting the domain, which cascades to everything below it."""
    db = SessionLocal()
    name = f"ir-fixture-{uuid.uuid4().hex[:8]}"
    domain_id = db.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"), {"n": name}
    ).scalar_one()
    try:
        type_ids = {}
        for entity_type in FIXTURES["domain"]["entityTypes"]:
            type_ids[entity_type["name"]] = db.execute(
                text(
                    "INSERT INTO entity_type (domain_id, name, role) "
                    "VALUES (:d, :n, CAST(:r AS entity_role)) RETURNING id"
                ),
                {"d": domain_id, "n": entity_type["name"], "r": entity_type["role"]},
            ).scalar_one()
            for attribute in entity_type["attributes"]:
                db.execute(
                    text(
                        "INSERT INTO attribute_def "
                        "(entity_type_id, name, data_type, required, enum_values, default_value) "
                        "VALUES (:t, :n, CAST(:dt AS attr_type), :req, :ev, "
                        "CAST(:dv AS jsonb))"
                    ),
                    {
                        "t": type_ids[entity_type["name"]],
                        "n": attribute["name"],
                        "dt": attribute["data_type"],
                        "req": attribute.get("required", False),
                        "ev": attribute.get("enum_values"),
                        "dv": (
                            json.dumps(attribute["default_value"])
                            if "default_value" in attribute
                            else None
                        ),
                    },
                )
        for parameter in FIXTURES["domain"]["parameters"]:
            db.execute(
                text(
                    "INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value) "
                    "VALUES (:d, :n, :i, :v)"
                ),
                {
                    "d": domain_id,
                    "n": parameter["name"],
                    "i": [type_ids[s] for s in parameter["index"]],
                    "v": parameter["default_value"],
                },
            )
        for relationship in FIXTURES["domain"]["relationshipTypes"]:
            db.execute(
                text(
                    "INSERT INTO relationship_type "
                    "(domain_id, name, from_type_id, to_type_id, cardinality, is_hierarchy) "
                    "VALUES (:d, :n, :f, :t, :c, :h)"
                ),
                {
                    "d": domain_id,
                    "n": relationship["name"],
                    "f": type_ids[relationship["from"]],
                    "t": type_ids[relationship["to"]],
                    "c": relationship["cardinality"],
                    "h": relationship["is_hierarchy"],
                },
            )
        db.commit()
        yield db, domain_id
    finally:
        db.rollback()
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain_id})
        db.commit()
        db.close()


# --------------------------------------------------------------------------
# valid
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", VALID, ids=_id)
def test_a_valid_ir_is_accepted_without_a_database(case):
    assert check_shape(case["ir"]) is None


@pytest.mark.parametrize("case", VALID, ids=_id)
def test_a_valid_ir_is_accepted_against_the_domain(case, world):
    db, domain_id = world
    assert validate_ir(db, domain_id, case["ir"]) is None


def test_the_valid_set_covers_every_term_kind_and_both_variable_domains():
    """A fixture set that never uses a construct cannot prove the
    validator does not refuse it. This is the counterpart to the invalid
    cases: they say what is refused, these say what is expressed."""
    serialised = json.dumps(VALID)
    for kind in ("const", "par", "var", "attr", "sum", "add", "mul"):
        assert f'"{kind}"' in serialised, kind
    for domain in ("binary", "integer"):
        assert f'"{domain}"' in serialised, domain
    for severity in ("hard", "soft"):
        assert f'"{severity}"' in serialised, severity
    for relation in ("<=", ">="):
        assert f'"{relation}"' in serialised, relation


# --------------------------------------------------------------------------
# invalid
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", SHAPE_CASES, ids=_id)
def test_a_shape_rule_refuses_with_its_code_and_loc(case):
    refusal = check_shape(case_ir(case))
    assert refusal is not None, f"{case['code']} was accepted: {case['why']}"
    assert refusal.code == case["code"]
    assert refusal.loc == case["loc"]
    assert refusal.message.strip()


@pytest.mark.parametrize("case", DOMAIN_CASES, ids=_id)
def test_a_domain_rule_refuses_with_its_code_and_loc(case, world):
    db, domain_id = world
    refusal = validate_ir(db, domain_id, case_ir(case))
    assert refusal is not None, f"{case['code']} was accepted: {case['why']}"
    assert refusal.code == case["code"]
    assert refusal.loc == case["loc"]


@pytest.mark.parametrize("case", DOMAIN_CASES, ids=_id)
def test_a_domain_case_is_shape_valid(case):
    """Single fault, proven rather than asserted in a comment: if the
    shape half found anything, the case would be wrong in two ways and
    the domain rule it is meant to exercise would never be reached."""
    assert check_shape(case_ir(case)) is None


@pytest.mark.parametrize("case", SHAPE_CASES, ids=_id)
def test_a_shape_case_names_a_loc_that_exists_in_its_document(case):
    """`loc` has to point *into* the document, or a builder could not
    highlight what it names (Ruling 30). Walks the path and requires
    every step but a missing final key to resolve."""
    node = case_ir(case)
    for i, step in enumerate(case["loc"]):
        last = i == len(case["loc"]) - 1
        if isinstance(step, int):
            assert isinstance(node, list), case["code"]
            assert step < len(node), case["code"]
            node = node[step]
        else:
            assert isinstance(node, dict), case["code"]
            if step not in node:
                # The only legal miss is the last step naming the element
                # that is absent -- which is what "missing" refusals mean.
                assert last, f"{case['code']}: loc {case['loc']} goes through a missing key"
                return
            node = node[step]


def test_every_shape_case_is_wrong_in_exactly_one_way():
    """The single-fault property, from the other side: replace the one
    element the case's `loc` points at with what the nearest valid
    fixture has there, and the document must become valid. Only the cases
    whose loc names a replaceable element can be checked this way, so the
    test also asserts that it checked a decent number of them -- a
    rewrite that made every loc a root path would otherwise pass by
    checking nothing."""
    checked = 0
    for case in SHAPE_CASES:
        if "generate" in case or not case["loc"]:
            continue
        repaired = _repair(json.loads(json.dumps(case["ir"])), case["loc"])
        if repaired is None:
            continue
        refusal = check_shape(repaired)
        if refusal is not None and refusal.loc == case["loc"][: len(refusal.loc)]:
            # The element was REQUIRED, not merely wrong (`version`, a
            # parameter's `index`, the last member of one): deleting it
            # cannot repair the document, and the refusal still names it
            # or the container it emptied. That is not a second fault --
            # but it proves nothing either, so it is not counted.
            continue
        checked += 1
        assert refusal is None, (
            f"{case['code']}: removing the element at {case['loc']} left the document "
            f"refused for a DIFFERENT reason ({refusal.code if refusal else None} at "
            f"{refusal.loc if refusal else None}), so the case is wrong in more than one way"
        )
    # Twelve of the shape cases name an element that can simply be
    # dropped; the rest name one that is required (so dropping it is not
    # a repair) or a whole container. The floor is here so that a rewrite
    # which made every `loc` a root path would fail rather than pass by
    # checking nothing.
    assert checked >= 12, f"only {checked} cases were repairable; the check has gone hollow"


def _repair(ir, loc):
    """Delete the element `loc` names, when deleting it is enough to make
    a valid document. Returns None when it is not (a required key, an
    element of a list whose siblings then break arity, and so on)."""
    node = ir
    for step in loc[:-1]:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return None
    last = loc[-1]
    try:
        if isinstance(last, int):
            del node[last]
        elif last in node:
            del node[last]
        else:
            return None
    except (KeyError, IndexError, TypeError):
        return None
    return ir


# --------------------------------------------------------------------------
# the limits, named rather than only generated
# --------------------------------------------------------------------------


def test_the_limits_are_the_ones_the_generated_cases_were_built_for():
    """The three generated cases pick their sizes from these numbers. If
    a limit moves and the fixture's `count` does not, the case stops
    exercising the rule and starts passing for the wrong reason."""
    assert MAX_DEPTH == 12
    assert MAX_TERMS == 500
    assert MAX_IR_BYTES == 262144
    by_code = {c["code"]: c for c in INVALID}
    assert by_code["depth_exceeded"]["generate"]["count"] > MAX_DEPTH
    assert by_code["terms_exceeded"]["generate"]["count"] > MAX_TERMS
    assert by_code["ir_too_large"]["generate"]["count"] > MAX_IR_BYTES


def test_a_document_at_the_depth_limit_is_accepted():
    """The boundary, from the inside: one less nesting than the case that
    is refused must pass, or the limit is off by one."""
    ir = build_generated({"kind": "nestedAdd", "count": MAX_DEPTH - 1})
    assert check_shape(ir) is None


def test_the_byte_limit_is_measured_in_bytes_not_in_characters():
    """`padNoteWide` in the fixture file is the case; this asserts the
    NUMBER, which is what says which unit was counted. `len()` on the str
    would report a little over 200000 here and the document would be
    accepted by both validators for the wrong reason."""
    refusal = check_shape(build_generated({"kind": "padNoteWide", "count": 200_000}))
    assert refusal is not None
    assert refusal.code == "ir_too_large"
    assert 400_000 < int(refusal.message.split()[3]) < 500_000


def test_a_document_at_the_term_limit_is_accepted():
    # The `add` is a term and so is the constraint's `right`, so
    # MAX_TERMS - 2 summands make exactly MAX_TERMS.
    ir = build_generated({"kind": "wideAdd", "count": MAX_TERMS - 2})
    assert check_shape(ir) is None


# --------------------------------------------------------------------------
# the seed
# --------------------------------------------------------------------------


def test_the_seeded_ir_is_the_workforce_fixture():
    """The demo model and the worked example in the fixture file are one
    document. Asserted as equality rather than "the seed validates",
    because a seed that merely validated could quietly stop being the
    thing the contract document walks the reader through."""
    from app.seed import _IR

    workforce = next(case for case in VALID if case["name"] == "workforce")
    assert _IR == workforce["ir"]


def test_the_seeded_scenario_patches_a_constraint_the_seeded_ir_has():
    """Task 9's gap, at its source: the seed's own scenario must name a
    real constraint id, or the closing of that gap would make the seed
    unseedable."""
    from app.seed import _IR, _SCENARIO_PATCH

    ids = {constraint["id"] for constraint in _IR["constraints"]}
    patched = {
        *_SCENARIO_PATCH.get("disable", []),
        *_SCENARIO_PATCH.get("harden", []),
        *_SCENARIO_PATCH.get("soften", {}),
    }
    assert patched, "a patch that patches nothing proves nothing"
    assert patched <= ids
