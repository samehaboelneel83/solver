"""The constructs library (app/agent/constructs; build-protocol plan, Phase 2): each is expanded into
ordinary rules, built and solved by the platform's own dry run with a trial, and reaches the hand-worked optimum."""

from __future__ import annotations

import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agent import constructs
from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _trial(headers, seed, ir):
    spec = {"domain_name": f"Idiom {uuid.uuid4().hex[:6]}", "problem_name": "T", "seed": seed, "ir": ir}
    expanded = copy.deepcopy(spec)
    notes = constructs.expand(expanded)
    got = TestClient(app).post("/api/v1/problems/from-spec", json={**expanded, "dry_run": True, "trial": True},
                               headers=headers)
    assert got.status_code == 200, got.text
    return got.json()["trial"], expanded, notes


def _kind(name, *attrs):
    return {"name": name, "attributes": [{"name": a, "data_type": "number"} for a in attrs]}


def test_carried_counts_the_starting_amount_in_the_first_period_only(tenants):
    """carried.EXAMPLE: demand 5, 7, 4; 3 on hand at the start; at most 6 made a period at 1 each; 2 to carry one
    over a period. Period 2 needs 7 > 6, so 1 is made early and carried: 13 made + 2 carrying = 15. Counting the 3
    in every period (the Nile Juice mistake) would make it 7 -- and the construct says so when a number is
    written among what comes in."""
    from app.agent.constructs import carried

    seed, ir = copy.deepcopy(carried.EXAMPLE["seed"]), copy.deepcopy(carried.EXAMPLE["ir"])
    trial, expanded, notes = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 15) < 1e-6, trial
    assert [c["id"] for c in expanded["ir"]["constraints"]] == ["c_balance"] and "c_balance_next" in expanded["ir"]["relationships"]
    assert notes == ['rule c_balance written as the idiom "carried" became c_balance']
    seed, ir = copy.deepcopy(carried.EXAMPLE["seed"]), copy.deepcopy(carried.EXAMPLE["ir"])
    ir["constraints"] = copy.deepcopy(carried.WRONG["constraints"])
    trial, expanded, notes = _trial(tenants["b"], seed, ir)
    assert abs(trial["objective"] - 7) < 1e-6 and any('counted in EVERY period' in n for n in notes), (trial, notes)


def test_largest_of_does_not_add_overlapping_effects(tenants):
    """largest_of.EXAMPLE: two options protect the same thing at 60 and 50, each costing 10: chosen both, the level
    is 60, not 110; the best is to choose the first only: 60 - 10 = 50."""
    from app.agent.constructs import largest_of

    seed, ir = copy.deepcopy(largest_of.EXAMPLE["seed"]), copy.deepcopy(largest_of.EXAMPLE["ir"])
    trial, expanded, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 50) < 1e-6, trial
    assert [c["id"] for c in expanded["ir"]["constraints"]] == ["c_level", "c_level_one", "c_level_chosen"]


def test_only_if_with_allowed_pairs_and_exactly_one(tenants):
    """one_per_group.EXAMPLE: each of two tasks goes to exactly one of two places, only the pairs the list allows;
    cheapest = 4 + 3."""
    from app.agent.constructs import one_per_group

    seed, ir = copy.deepcopy(one_per_group.EXAMPLE["seed"]), copy.deepcopy(one_per_group.EXAMPLE["ir"])
    trial, _, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 7) < 1e-6, trial


def test_only_if_carries_a_fixed_charge(tenants):
    """only_if.EXAMPLE: 6 units from two places, one cheap to open and dear a unit, the other the reverse: 15."""
    from app.agent.constructs import only_if

    seed, ir = copy.deepcopy(only_if.EXAMPLE["seed"]), copy.deepcopy(only_if.EXAMPLE["ir"])
    trial, expanded, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 15) < 1e-6, trial
    rule = next(c for c in expanded["ir"]["constraints"] if c["id"] == "c_open")
    assert rule["right"] == {"mul": [{"par": "needed", "index": []}, {"var": "open", "index": ["p"]}]}
    ir["constraints"] = [c for c in ir["constraints"] if c["id"] != "c_open"] + copy.deepcopy(only_if.WRONG["constraints"])
    with pytest.raises(constructs.ConstructRefused, match="declares no upper bound"):
        constructs.expand({"seed": seed, "ir": ir})


def test_an_idiom_written_wrong_is_refused_with_what_to_write():
    spec = {"seed": {"entities": []}, "ir": {"constraints": [{"id": "c_b", "carried": {"periods": {"index": "t"}}}]}}
    with pytest.raises(constructs.IdiomRefused, match=r'rule c_b \("carried"\): "periods" is'):
        constructs.expand(spec)
    spec = {"seed": {}, "ir": {"variables": {"x": {"index": [], "domain": "continuous"}},
                               "constraints": [{"id": "c_x", "only_if": {"amount": {"var": "x", "index": []},
                                                                         "chosen": {"var": "y", "index": []}}}]}}
    with pytest.raises(constructs.IdiomRefused, match="declares no upper bound"):
        constructs.expand(spec)


def test_the_plan_card_shows_what_each_parameter_holds_as_loaded():
    """Phase 1, supply chain L: every route was stored as open; the card said only "4500 cells given"."""
    from app.agent.readback import readback

    seed = {"parameters": [{"name": "is_open", "index": ["w", "c"], "default_value": 0},
                           {"name": "cost", "index": ["w", "c"], "default_value": 0}],
            "parameter_values": [{"parameter": "is_open", "entities": [["w", f"W{i}"], ["c", "C1"]], "value": 1} for i in range(6)]
            + [{"parameter": "cost", "entities": [["w", f"W{i}"], ["c", "C1"]], "value": 10 + i} for i in range(6)]}
    text = readback({"seed": seed, "ir": {}})
    assert "- is_open[w, c]: 6 cells given (value 1 in all 6), every other cell 0" in text
    assert "- cost[w, c]: 6 cells given (values from 10 to 15), every other cell 0" in text


def test_every_construct_is_described_and_refuses_a_body_that_is_not_an_object():
    """The registry: each construct names its keys, its fields and a neutral paragraph for the instructions; a
    body that is not an object is refused with what to write."""
    assert set(constructs.KEYS) == {"carried", "only_if", "allowed_pairs", "largest_of", "at_most_one", "exactly_one", "covering", "share_of_total", "used_only_where_given"}
    for module in constructs.MODULES:
        assert module.KEYS and module.FIELDS and len(module.DESCRIPTION) > 100, module.__name__
        assert isinstance(module.EXAMPLE["objective"], (int, float)) and module.WRONG["why"], module.__name__
        for key in module.KEYS:
            assert constructs.REGISTRY[key] is module
            spec = {"seed": {}, "ir": {"constraints": [{"id": "c_x", key: "not an object"}]}}
            with pytest.raises(constructs.ConstructRefused, match=rf'rule c_x \("{key}"\): write it as an object'):
                constructs.expand(spec)
    assert len(constructs.describe()) == len(constructs.MODULES)


def _pairs_case(partial_list: bool):
    """The construct's own example (allowed_pairs.EXAMPLE: three records, two options, each record takes exactly
    one option, a list naming a1 alone), or the same with a list naming every record."""
    from app.agent.constructs import allowed_pairs

    seed, ir = copy.deepcopy(allowed_pairs.EXAMPLE["seed"]), copy.deepcopy(allowed_pairs.EXAMPLE["ir"])
    if not partial_list:
        seed["parameter_values"] += [{"parameter": "allowed", "entities": [["record", r], ["option", o]], "value": 1}
                                     for r, o in (("a2", "o2"), ("a3", "o2"))]
    return seed, ir


def test_allowed_pairs_reads_a_partial_list_as_restricting_only_the_records_it_names(tenants):
    """The list names a1 alone (a1 -> o1): a1 is held to o1 at 5, a2 and a3 are free (2 + 1): 8. Read as a complete
    list it would leave a2 and a3 with no pair (infeasible); read on its default of 1 it would change nothing (4)."""
    from app.agent.constructs import allowed_pairs

    seed, ir = _pairs_case(partial_list=True)
    trial, expanded, notes = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - allowed_pairs.EXAMPLE["objective"]) < 1e-6, trial
    rule = next(c for c in expanded["ir"]["constraints"] if c["id"] == "c_pairs")
    assert "names 1 of 3 record" in rule["note"] and "(1 - listed + allowed)" in rule["note"]
    assert any(p["name"] == "c_pairs_listed" for p in expanded["seed"]["parameters"])
    assert next(p for p in expanded["seed"]["parameters"] if p["name"] == "allowed")["default_value"] == 0
    # The reading fixed by hand: complete, so a2 and a3 have no allowed option.
    seed, ir = _pairs_case(partial_list=True)
    ir["constraints"][0]["allowed_pairs"]["partial"] = False
    trial, _, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "infeasible", trial


def test_allowed_pairs_reads_a_complete_list_as_the_only_pairs(tenants):
    """The list names every record (a1 -> o1, a2 -> o2, a3 -> o2): 5 + 3 + 1 = 9, on a list typed with default 1."""
    seed, ir = _pairs_case(partial_list=False)
    trial, expanded, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 9) < 1e-6, trial
    rule = next(c for c in expanded["ir"]["constraints"] if c["id"] == "c_pairs")
    assert "names every record" in rule["note"] and "(1 - listed + allowed)" not in rule["note"]


def test_allowed_pairs_written_without_its_list_is_refused_with_what_to_write():
    seed, ir = _pairs_case(partial_list=True)
    seed["parameter_values"] = [v for v in seed["parameter_values"] if v["parameter"] != "allowed"]
    with pytest.raises(constructs.ConstructRefused, match=r'rule c_pairs \("allowed_pairs"\): the list "allowed" has no cells'):
        constructs.expand({"seed": seed, "ir": ir})
    seed, ir = _pairs_case(partial_list=True)
    ir["constraints"][0]["allowed_pairs"]["for"] = [{"index": "r", "set": "record"}]
    with pytest.raises(constructs.ConstructRefused, match='"for" is the pair'):
        constructs.expand({"seed": seed, "ir": ir})


def test_covering_chooses_the_cheapest_options_that_cover_every_requirement(tenants):
    """covering.EXAMPLE: o1 + o3 leave n3 uncovered, so o2 is in every cover; 7. The same with the cover given as
    a relationship from the option to what it covers, and with at_least 2 (every option: 10)."""
    from app.agent.constructs import covering

    seed, ir = copy.deepcopy(covering.EXAMPLE["seed"]), copy.deepcopy(covering.EXAMPLE["ir"])
    trial, expanded, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 7) < 1e-6, trial
    rule = expanded["ir"]["constraints"][0]
    assert rule["relation"] == ">=" and rule["right"] == {"const": 1} and "covers x chosen" in rule["note"]
    # The cover as links.
    seed, ir = copy.deepcopy(covering.EXAMPLE["seed"]), copy.deepcopy(covering.EXAMPLE["ir"])
    seed["relationship_types"] = [{"name": "covers_link", "from": "option", "to": "need", "cardinality": "many_to_many"}]
    seed["relationships"] = [{"type": "covers_link", "from": ["option", v["entities"][0][1]], "to": ["need", v["entities"][1][1]]}
                             for v in seed.pop("parameter_values")]
    seed["parameters"] = []
    ir["parameters"] = {}
    ir["relationships"] = ["covers_link"]
    ir["constraints"][0]["covering"]["covers"] = {"rel": "covers_link"}
    trial, expanded, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 7) < 1e-6, trial
    assert expanded["ir"]["constraints"][0]["left"]["over"][0]["via"] == {"rel": "covers_link", "to": "n"}
    # Two covering options for every requirement: n3 is covered by o2 alone, so it cannot be done.
    seed, ir = copy.deepcopy(covering.EXAMPLE["seed"]), copy.deepcopy(covering.EXAMPLE["ir"])
    ir["constraints"][0]["covering"]["at_least"] = 2
    trial, _, _ = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "infeasible", trial


def test_covering_written_wrong_is_refused_with_what_to_write():
    from app.agent.constructs import covering

    seed, ir = copy.deepcopy(covering.EXAMPLE["seed"]), copy.deepcopy(covering.EXAMPLE["ir"])
    ir["constraints"][0]["covering"]["covers"] = "covers"
    with pytest.raises(constructs.ConstructRefused, match=r'rule c_cover \("covering"\): "covers" is a 0/1 parameter'):
        constructs.expand({"seed": seed, "ir": ir})
    ir["constraints"][0]["covering"]["covers"] = {"rel": "nothing"}
    with pytest.raises(constructs.ConstructRefused, match='does not list in "relationships"'):
        constructs.expand({"seed": seed, "ir": ir})


def test_share_of_total_writes_the_linear_form(tenants):
    """share_of_total.EXAMPLE: the third part at least 30% of the whole, the first at most 50%: 44. The part named
    by its key in the construct's term is bound by the canonical pass after the expansion."""
    from app.agent import canon
    from app.agent.constructs import share_of_total

    spec = {"domain_name": f"Share {uuid.uuid4().hex[:6]}", "problem_name": "T",
            "seed": copy.deepcopy(share_of_total.EXAMPLE["seed"]), "ir": copy.deepcopy(share_of_total.EXAMPLE["ir"])}
    spec, notes = canon.canonical({"spec": spec}, load=lambda seed: seed)
    third = next(c for c in spec["ir"]["constraints"] if c["id"] == "c_third")
    assert third["relation"] == ">=" and third["right"]["mul"][0] == {"const": 0.3} and "sum" in third["right"]["mul"][1]
    assert third["forall"][0]["index"] == "k_p3"  # the key bound by the pass
    got = TestClient(app).post("/api/v1/problems/from-spec", json={**spec, "dry_run": True, "trial": True},
                               headers=tenants["b"])
    assert got.status_code == 200, got.text
    trial = got.json()["trial"]
    assert trial["status"] == "optimal" and abs(trial["objective"] - 44) < 1e-6, trial


def test_share_of_total_written_wrong_is_refused_with_what_to_write():
    from app.agent.constructs import share_of_total

    seed, ir = copy.deepcopy(share_of_total.EXAMPLE["seed"]), copy.deepcopy(share_of_total.EXAMPLE["ir"])
    ir["constraints"][1]["share_of_total"]["share"] = 30
    with pytest.raises(constructs.ConstructRefused, match=r'rule c_third \("share_of_total"\): "share" is a fraction'):
        constructs.expand({"seed": seed, "ir": ir})
    ir["constraints"][1]["share_of_total"]["share"] = 0.3
    ir["constraints"][1]["share_of_total"]["relation"] = "="
    with pytest.raises(constructs.ConstructRefused, match='"relation" is "<="'):
        constructs.expand({"seed": seed, "ir": ir})
    ir["constraints"][1]["share_of_total"]["relation"] = ">="
    ir["constraints"][1]["share_of_total"]["part"] = 3
    with pytest.raises(constructs.ConstructRefused, match='"part" is the part of the mix'):
        constructs.expand({"seed": seed, "ir": ir})


def test_used_only_where_given_keeps_the_amount_to_the_pairs_with_a_value(tenants):
    """used_only_where_given.EXAMPLE: two records, three options, a rate for four of the six pairs: 44. Without the
    rule the cheapest plan would use the pairs with no rate, at the default of 0."""
    from app.agent.constructs import used_only_where_given as given

    seed, ir = copy.deepcopy(given.EXAMPLE["seed"]), copy.deepcopy(given.EXAMPLE["ir"])
    trial, expanded, notes = _trial(tenants["b"], seed, ir)
    assert trial["status"] == "optimal" and abs(trial["objective"] - 44) < 1e-6, trial
    flag = next(p for p in expanded["seed"]["parameters"] if p["name"] == "c_given_given")
    assert flag["index"] == ["record", "option"] and flag["default_value"] == 0
    assert sum(1 for v in expanded["seed"]["parameter_values"] if v["parameter"] == "c_given_given") == 4
    rule = next(c for c in expanded["ir"]["constraints"] if c["id"] == "c_given")
    assert rule["right"] == {"mul": [{"const": 10}, {"par": "c_given_given", "index": ["r", "o"]}]}
    assert "1 for the 4 cell(s) rate has" in rule["note"]


def test_used_only_where_given_written_wrong_is_refused_with_what_to_write():
    from app.agent.constructs import used_only_where_given as given

    seed, ir = copy.deepcopy(given.EXAMPLE["seed"]), copy.deepcopy(given.EXAMPLE["ir"])
    ir["constraints"][2]["used_only_where_given"]["given"] = {"par": "rate"}
    with pytest.raises(constructs.ConstructRefused, match=r'rule c_given \("used_only_where_given"\): "given" is the parameter'):
        constructs.expand({"seed": seed, "ir": ir})
    ir["constraints"][2]["used_only_where_given"]["given"] = {"par": "rate", "index": ["r"]}
    with pytest.raises(constructs.ConstructRefused, match="declared over 2 kind"):
        constructs.expand({"seed": seed, "ir": ir})
    ir["constraints"][2]["used_only_where_given"]["given"] = {"par": "rate", "index": ["r", "o"]}
    seed["parameter_values"] = []
    with pytest.raises(constructs.ConstructRefused, match='"rate" has no cells'):
        constructs.expand({"seed": seed, "ir": ir})
