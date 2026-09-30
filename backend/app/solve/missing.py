"""Which values a model reads from records, and which records lack them.

A model that reads `hours_per_week of e` as a number cannot be solved while
any employee has no `hours_per_week`: the compiler refuses rather than read
zero (app.solve.compile). This finds every such gap before the compiler
meets the first one, so a planner can fill them all in one place -- the
preflight and the problem's readiness both show them as a table to type
into.
"""

from __future__ import annotations

from typing import Any


def attribute_reads(ir: dict[str, Any]) -> set[tuple[str, str]]:
    """(set, attribute) for every `attr` term that reads an item of a set
    (not a walk's link, whose numbers live on the relationship)."""
    reads: set[tuple[str, str]] = set()

    def bind(bindings: Any, scope: dict[str, str | None]) -> dict[str, str | None]:
        inner = dict(scope)
        for binding in bindings if isinstance(bindings, list) else []:
            if not isinstance(binding, dict):
                continue
            if isinstance(binding.get("index"), str) and isinstance(binding.get("set"), str):
                inner[binding["index"]] = binding["set"]
            via = binding.get("via")
            if isinstance(via, dict) and isinstance(via.get("as"), str):
                inner[via["as"]] = None  # a link, not an item
        return inner

    def walk(node: Any, scope: dict[str, str | None]) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, scope)
            return
        if not isinstance(node, dict):
            return
        local = scope
        if "forall" in node:
            local = bind(node["forall"], local)
        if "sum" in node and "over" in node:
            local = bind(node["over"], local)
        attr = node.get("attr")
        if isinstance(attr, dict) and isinstance(attr.get("of"), str) and isinstance(attr.get("name"), str):
            set_name = local.get(attr["of"])
            if set_name:
                reads.add((set_name, attr["name"]))
        for key, value in node.items():
            if key in ("forall", "over", "where", "via", "attr"):
                continue
            walk(value, local)

    walk(ir.get("constraints") or [], {})
    walk((ir.get("objective") or {}).get("terms") or [], {})
    return reads


def missing_values(ir: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """Each attribute the model reads that some records lack: the set, the
    attribute and the keys without a value, in the dataset's order."""
    out = []
    for set_name, attribute in sorted(attribute_reads(ir)):
        rows = (data.get("sets") or {}).get(set_name) or []
        lacking = [row["id"] for row in rows if row.get(attribute) is None]
        if lacking:
            out.append({"set": set_name, "attribute": attribute, "records": lacking})
    return out
