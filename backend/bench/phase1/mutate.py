"""Mutation checks (build-protocol plan, Phase 0.3): from each gold model, known-wrong variants; for each, do the
platform's checks warn? A table mutation x check, counts only -- safe over the hidden golds.

    python -m bench.phase1.mutate [S] [case ...]        (test image: no model, no database)

Mutations (each applied alone to the gold):
  drop_rule       one hard rule left out (each hard rule in turn; the worst case reported)
  reverse_goal    the goal's sense reversed
  drop_values     one parameter's given cells removed (its default applies everywhere)
  list_default    a 0/1 parameter's default set to 1 (a list that changes nothing)
Checks consulted (the platform's own, as the plan card would show them):
  trial           infeasible / unbounded / does nothing / used where no data (app.api.model_spec, app.agent.core)
  shape           never helps / idle (app.solve.lint.never_helps on the compiled model)
  numbers         a number of the request the model does not hold (app.agent.core.unused_numbers)
A mutation counts as CAUGHT when any check says something it did not say on the gold itself, or when the
variant's goal still equals the reference (then nothing was lost: the rule was redundant), reported as "same".
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def _signals(ir: dict, data: dict, request: str) -> tuple[set[str], float | None, str]:
    """What the checks say of (ir, data): a set of signal names, the goal, the status."""
    from app.agent.core import idle_decisions, unused_numbers
    from app.api.model_spec import used_without_data
    from app.solve import lint, sandbox
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.compile import compile_model
    from app.solve.convexity import refine

    out: set[str] = set()
    try:
        compiled = compile_model(ir, data)
    except Exception as exc:  # noqa: BLE001
        return {f"refused:{type(exc).__name__}"}, None, "refused"
    for f in lint.never_helps(compiled):
        out.add(f"shape:{f.get('kind')}")
    try:
        found = refine(classify(ir, data), compiled)
        backend, _ = choose(found)
        result, _reason = sandbox.run("app.solve.sandbox:solve_in_child",
                                      {"backend": backend.name, "compiled": compiled, "time_limit": 60.0,
                                       "seed": 0, "workers": 1, "gap_rel": 0.0}, time_limit=65.0)
    except Exception as exc:  # noqa: BLE001 -- a mutation no solver takes is refused: that is a catch
        return out | {f"refused:{type(exc).__name__}"}, None, "refused"
    if result is None:
        return out | {"trial:no answer"}, None, "no answer"
    status = str(result.status)
    if status in ("infeasible", "unbounded"):
        out.add(f"trial:{status}")
    used: dict[str, dict] = {}
    for key in compiled.variables:
        if not str(key[0]).startswith("__"):
            used.setdefault(str(key[0]), {"non_zero": 0, "cells": 0})["cells"] += 1
    for key, value in (result.assignments or {}).items():
        if str(key[0]) in used and abs(float(value)) > 1e-9:
            used[str(key[0])]["non_zero"] += 1
    if used and all(not u["non_zero"] for u in used.values()):
        out.add("trial:nothing")
    elif idle_decisions(used):
        out.add("trial:does nothing")
    if used_without_data(ir, data, result.assignments or {}):
        out.add("trial:no data")
    # The Assistant's own order check refuses a parameter the model reads with no value loaded; the same here.
    from app.solve.lint import _names_read

    attrs: set[str] = set()
    pars: set[str] = set()
    _names_read({k: v for k, v in ir.items() if k != "parameters"}, attrs, pars)
    for name, spec in (ir.get("parameters") or {}).items():
        if isinstance(spec, dict) and spec.get("index") and name in pars and not (data.get("parameters") or {}).get(name):
            out.add("data:empty")
    if request:
        seed_like = {**data, "entities": [{"type": s, "key": str(r.get("id"))} for s, rows in (data.get("sets") or {}).items()
                                           for r in rows if isinstance(r, dict)]}
        if unused_numbers([{"role": "user", "content": request}], {"seed": seed_like, "ir": ir}):
            out.add("numbers:unused")
        from app.agent.core import goal_sense_for_person

        if goal_sense_for_person([{"role": "user", "content": request}], ir):
            out.add("numbers:goal sense")
    return out, result.objective, status


def _mutations(gold: dict):
    ir, data = gold["ir"], gold["data"]
    hard = [i for i, c in enumerate(ir.get("constraints") or []) if isinstance(c, dict) and c.get("severity", "hard") == "hard"]
    for i in hard:
        m = copy.deepcopy(ir)
        dropped = m["constraints"].pop(i)
        yield f"drop_rule:{dropped.get('id')}", m, data
    sense = (ir.get("objective") or {}).get("sense")
    if sense in ("minimize", "maximize"):
        m = copy.deepcopy(ir)
        m["objective"]["sense"] = "maximize" if sense == "minimize" else "minimize"
        yield "reverse_goal", m, data
    for name, rows in (data.get("parameters") or {}).items():
        if rows:
            d = copy.deepcopy(data)
            d["parameters"][name] = []
            yield f"drop_values:{name}", ir, d
            values = {float(r.get("value") or 0) for r in rows if isinstance(r, dict)}
            if values <= {0.0, 1.0} and 1.0 in values:
                d = copy.deepcopy(data)
                d.setdefault("parameter_defaults", {})[name] = 1
                yield f"list_default:{name}", ir, d


def main(size: str, cases: list[str]) -> int:
    roots = [HERE / "gold", HERE.parent / "hidden" / "gold"]
    paths = sorted(p for r in roots if r.exists() for p in r.glob(f"*-{size}.json"))
    gaps = 0
    totals = {"caught": 0, "same": 0, "missed": 0}
    for path in paths:
        gold = json.loads(path.read_text(encoding="utf-8"))
        if cases and gold["case"] not in cases:
            continue
        case_root = HERE.parent / "hidden" / "cases" if gold["case"].startswith("h") else HERE / "cases"
        request = (case_root / gold["case"] / gold["size"] / "message.txt").read_text(encoding="utf-8", errors="replace") \
            if (case_root / gold["case"] / gold["size"] / "message.txt").exists() else ""
        base, goal, _ = _signals(gold["ir"], gold["data"], request)
        print(f"{gold['case']}-{gold['size']}: gold says {sorted(base) or 'nothing'}, goal {goal}")
        for name, ir, data in _mutations(gold):
            got, obj, status = _signals(ir, data, request)
            new = got - base
            same = obj is not None and goal is not None and abs(float(obj) - float(goal)) <= 1e-6 * max(1.0, abs(float(goal)))
            verdict = "caught" if new else ("same" if same else "MISSED")
            totals["caught" if new else ("same" if same else "missed")] += 1
            gaps += verdict == "MISSED"
            kind = name.split(":")[0]
            print(f"   {kind:13} {verdict:7} {('by ' + ', '.join(sorted(new))) if new else ('goal ' + str(obj) + ' ' + status)}")
    print(f"\ncaught {totals['caught']}, same goal {totals['same']}, missed {totals['missed']}")
    return gaps


if __name__ == "__main__":
    size = sys.argv[1] if len(sys.argv) > 1 and len(sys.argv[1]) == 1 else "S"
    sys.exit(1 if main(size, [a for a in sys.argv[1:] if len(a) != 1]) else 0)
