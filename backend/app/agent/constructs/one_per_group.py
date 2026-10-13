"""exactly_one / at_most_one -- one pick per group (build-protocol plan, construct 2.4).

    {"id": "c_one", "at_most_one" | "exactly_one": {"for": [bindings], "over": [bindings], "pick": {"var": ...}}}
"""

from __future__ import annotations

from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("at_most_one", "exactly_one")

FIELDS = {
    "for": "each group (bindings; optional: with none, one group of everything)",
    "over": 'the group\'s members: [{"index": "m", "set": ..., "via" or "where": ...}]',
    "pick": "whether a member is picked (a yes/no decision)",
}

DESCRIPTION = (
    'exactly_one / at_most_one: one pick per group. Write {"id": ..., "exactly_one": {"for": [<each group>], '
    '"over": [<the group\'s members>], "pick": <whether a member is picked>}} (or "at_most_one"). The platform '
    'writes the sum of the picks over the members = 1 (or <= 1) for every group.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    over = bindings(body.get("over"), '"over"')
    if not over:
        raise ConstructRefused('"over" names the group\'s members: [{"index": "m", "set": ..., "via" or "where": ...}]')
    pick = var(body.get("pick"), '"pick"')
    note = rule.get("note") or ("exactly one per group" if kind == "exactly_one" else "at most one per group")
    return [{"id": rid, "note": f"{note} (the idiom {kind})",
             **({"forall": bindings(body.get("for"), '"for"')} if body.get("for") else {}),
             "left": {"sum": pick, "over": over}, "relation": "=" if kind == "exactly_one" else "<=",
             "right": {"const": 1}}]
