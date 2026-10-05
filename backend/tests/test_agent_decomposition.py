"""The assistant can inspect whether a scenario admits an exact block split."""

from __future__ import annotations

import json

from app.agent import core, result as agent_result


def test_inspect_decomposition_uses_the_scenario_preflight():
    calls = []

    def call(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "body": {"ready": True,
                "structure": {"blocks": 4, "linking_rules": 0, "linking": [], "by": None,
                              "largest_share": 0.25},
                "findings": [], "planner": ["four independent blocks"]}}

    agent = core.Agent(core.Settings(), None, call, core.Context(username="planner"))
    report = json.loads(agent.run_tool("inspect_decomposition", {"scenario_id": 42}))
    assert calls[0][0][0:2] == ("GET", "/api/v1/scenarios/42/preflight")
    assert report["structure"]["blocks"] == 4 and report["ready"] is True


def _record(params):
    return {"id": 7, "status": "optimal", "objective": 10, "solver": "cp-sat", "params": params,
            "ir": {"objective": {"sense": "maximize"}}, "assignments": {}, "amounts": {},
            "data": {}, "results": []}


def test_assistant_report_says_when_exact_blocks_were_really_solved():
    structure = {"blocks": 4, "linking_rules": 0, "linking": [], "by": None, "largest_share": 0.25}
    exact = agent_result.summary(_record({"structure": structure,
                                           "blocks": {"blocks": 4, "groups": 4, "statuses": ["optimal"] * 4}}))
    assert "solved as 4 independent blocks" in exact and "4 parallel solves" in exact

    coupled = agent_result.summary(_record({"structure": {"blocks": 4, "linking_rules": 2,
                                                            "linking": ["c_cover"], "by": "person",
                                                            "largest_share": 0.4}}))
    assert "near-independent groups" in coupled and "this was not an exact split" in coupled
