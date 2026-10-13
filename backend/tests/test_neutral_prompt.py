"""What the Assistant reads names no domain (neutrality plan, step 2, docs/plans/2026-10-10-neutrality-plan.md).

The modelling idioms, the worked example and the messages are written in terms of records, decisions, rules and
goals. A word from a particular field in the instructions tunes the Assistant to that field; this test fails when
one comes back. A contract key in quotes (the route rule's "depot") is the platform's own name, not an example.
"""

from __future__ import annotations

import re

import pytest

from app.agent import core
from app.main import app

DOMAIN_WORDS = [
    "project", "district", "warehouse", "customer", "nurse", "roster", "shift", "bed", "beds", "desk", "stall",
    "shelf", "shelves", "camp", "school", "clinic", "park", "road", "roads", "feed", "diet", "alloy", "fuel", "fibre",
    "fiber", "pipe", "pipes", "exchange", "depot", "truck", "trucks", "van", "vans", "shop", "shops", "tray", "lane",
    "lanes", "wage", "wages", "machine", "machines", "gear", "job", "jobs", "protein", "nutrient", "ingredient",
    "cable", "cables", "roll", "rolls", "plot", "plots", "door", "doors", "corridor", "corridors", "gate", "gates",
    "month", "months", "morning", "night", "worker", "workers", "skill", "skills", "ton", "tons", "patient",
    "hospital", "factory", "bakery", "furniture", "juice", "crop", "shipment", "kg",
]
#: Contract keys the instructions must spell as they are.
CONTRACT_KEYS = {'"depot"'}


@pytest.mark.parametrize("mode", ["model", "assistant"])
def test_the_instructions_name_no_domain(mode):
    text = core.system_prompt(core.ApiIndex(app.openapi()), core.Context(username="u", mode=mode), True)
    for key in CONTRACT_KEYS:
        text = text.replace(key, "")
    found = {w: text[max(0, m.start() - 60): m.end() + 40].replace("\n", " ")
             for w in DOMAIN_WORDS for m in [re.search(rf"\b{w}\b", text, re.I)] if m}
    assert not found, found


def test_the_worked_example_is_neutral_and_valid():
    spec = core.EXAMPLE_SPEC
    assert spec["seed"]["entity_types"][0]["name"] == "item" and spec["ir"]["sets"] == ["item"]


def _domain_words_in(text: str) -> dict[str, str]:
    for key in CONTRACT_KEYS:
        text = text.replace(key, "")
    return {w: text[max(0, m.start() - 60): m.end() + 40].replace("\n", " ")
            for w in DOMAIN_WORDS for m in [re.search(rf"\b{w}\b", text, re.I)] if m}


def test_the_platforms_own_messages_name_no_domain():
    """Every message constant the platform sends to the person or the model (UPPER_CASE strings of the Assistant's
    and the checks' modules), and the messages built at run time, rendered on neutral inputs: a check or a repair
    found on one problem must speak in model terms, never in that problem's."""
    import inspect

    from app.agent import canon, constructs, files
    from app.solve import lint

    texts: dict[str, str] = {}
    for module in (core, files, canon, constructs, lint):
        for name, value in vars(module).items():
            if name.isupper() and isinstance(value, str) and not name.startswith("EXAMPLE"):
                texts[f"{module.__name__}.{name}"] = value
    seed = {"parameters": [{"name": "allowed", "index": ["a", "b"], "default_value": 1},
                           {"name": "between", "index": ["a", "a"], "default_value": 0}],
            "parameter_values": [{"parameter": "allowed", "entities": [["a", "a1"], ["b", "b1"]], "value": 1}]
            + [{"parameter": "between", "entities": [["a", x], ["a", y]], "value": 2} for x, y in (("a1", "a2"), ("a1", "a3"))]}
    texts["lint.as_default"] = " ".join(f["said"] for f in lint.as_default(seed))
    texts["lint.one_way"] = " ".join(f["said"] for f in lint.one_way(seed))
    texts["lint.unread"] = " ".join(f["said"] for f in lint.unread({}, seed))
    used = {"open": {"non_zero": 0, "cells": 3}, "amount": {"non_zero": 0, "cells": 9}, "left": {"non_zero": 5, "cells": 9}}
    texts["trial.card"] = core.trial_for_person({"status": "optimal", "objective": 1, "used": used}) \
        + core.trial_for_person({"status": "optimal", "used": {"x": {"non_zero": 0, "cells": 2}}}) \
        + core.trial_for_person({"status": "infeasible", "used": used})
    nd = [{"var": "amount", "parameter": "rate", "cells": 1, "default": 0, "examples": ["a1 · b2"]}]
    texts["trial.no_data"] = core.trial_for_person({"status": "optimal", "used": used, "no_data": nd})         + core.trial_said({"status": "optimal", "used": used, "no_data": nd, "seconds": 1})
    texts["trial.model"] = core.trial_said({"status": "optimal", "objective": 1, "used": used, "seconds": 1}) \
        + core.trial_said({"status": "infeasible", "used": used, "seconds": 1})
    texts["trial.sent_back"] = core.trial_sent_back({"status": "infeasible", "used": used}) \
        + core.trial_sent_back({"status": "unbounded"}) \
        + core.trial_sent_back({"status": "optimal", "used": used})
    texts["shape.sent_back"] = core.shape_sent_back([{"kind": "unread", "said": "x is given and no rule reads it"}])
    texts["goal.sense"] = core.goal_sense_for_person([{"role": "user", "content": "Goal: the lowest cost."}],
                                                     {"objective": {"sense": "maximize"}})
    sw = {"term": "o_a", "share": 0.95, "others": ["o_b"]}
    texts["trial.swamped"] = core.trial_for_person({"status": "optimal", "used": used, "swamped": sw})         + core.trial_said({"status": "optimal", "used": used, "swamped": sw, "seconds": 1})
    texts["numbers.card"] = core.numbers_for_person([{"role": "user", "content": "at most 70 and 15%"}], {"seed": {}, "ir": {}})
    spec = {"seed": {"parameters": [{"name": "rate", "default_value": 2}, {"name": "allowed", "index": ["a"], "default_value": 1}],
                     "parameter_values": [{"parameter": "allowed", "entities": [["a", "a1"]], "value": 1}]},
            "ir": {"version": 2, "constraints": [{"id": "c", "left": {"par": "rate"}, "relation": "<=", "right": {"const": 1}}]}}
    texts["canon.notes"] = " ".join(canon.repair(spec))
    texts["constructs.described"] = " ".join(constructs.describe())
    for module in constructs.MODULES:
        texts[f"{module.__name__}.FIELDS"] = " ".join(module.FIELDS.values())
    sheet = {"name": "s", "columns": ["a", "b", "v"], "rows": [["a1", "b1", "yes"], ["a2", None, "3 units"]], "total_rows": 2}
    report: list[str] = []
    files.expand({"parameters": [{"name": "allowed", "index": ["a", "b"], "default_value": 1}],
                  "parameter_values_from_file": [{"file": "f.csv", "parameter": "allowed", "value": 1,
                                                  "entities": [["a", "a"], ["b", "b"]], "where": [{"column": "v", "value": "yes"}]}]},
                 [{"name": "f.csv", "sheets": [sheet]}], report)
    texts["files.load_line"] = " ".join(report)
    found = {where: hit for where, text in texts.items() for hit in [_domain_words_in(text)] if hit}
    assert not found, found
