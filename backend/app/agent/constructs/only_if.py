"""only_if -- an amount only when chosen (build-protocol plan, construct 2.6).

    {"id": "c_x", "only_if": {"for": [bindings], "amount": {"var": ...}, "chosen": {"var"|"par": ...}, "most": term}}

amount <= most x chosen; `most` defaults to the amount's declared upper bound. With "chosen" a 0/1 parameter
(pairs a file allows), it keeps every pair the file does not allow at 0.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("only_if",)

FIELDS = {
    "for": "the indices the rule holds for (bindings; optional)",
    "amount": "the amount that is only there when chosen (a decision)",
    "chosen": "the yes/no decision, or a 0/1 parameter, that allows it",
    "most": "the largest the amount can be (a term; optional when the decision declares an upper bound)",
}

DESCRIPTION = (
    'only_if: an amount that is only there when something is chosen, or only where a 0/1 list allows it. Write '
    '{"id": ..., "only_if": {"for": [<the indices>], "amount": <the decision>, "chosen": <a yes/no decision or a '
    '0/1 parameter>, "most": <the largest the amount can be>}}. The platform writes amount <= most x chosen; '
    '"most" may be left out when the decision declares an upper bound. A fixed charge goes in the goal as the '
    'charge x chosen.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    amount = var(body.get("amount"), '"amount"')
    chosen = body.get("chosen")
    if not (isinstance(chosen, dict) and (isinstance(chosen.get("var"), str) or isinstance(chosen.get("par"), str))):
        raise ConstructRefused('"chosen" is a yes/no decision {"var": ...} or a 0/1 parameter {"par": ...}')
    most = body.get("most")
    if most is None:
        declared = (ir.get("variables") or {}).get(amount["var"]) or {}
        upper = 1 if declared.get("domain") == "binary" else declared.get("upper")
        if not isinstance(upper, (int, float)):
            raise ConstructRefused(f'"most" (the largest the amount can be) is needed: decision {amount["var"]} '
                                   "declares no upper bound")
        most = {"const": upper}
    note = rule.get("note") or "only if chosen"
    return [{"id": rid, "note": f"{note} (the idiom only_if: amount <= most x chosen)",
             **({"forall": bindings(body.get("for"), '"for"')} if body.get("for") else {}),
             "left": amount, "relation": "<=", "right": {"mul": [copy.deepcopy(most), copy.deepcopy(chosen)]}}]
