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
