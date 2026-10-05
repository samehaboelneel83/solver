"""Smoke test of the evaluation harness with a scripted model and a fake platform."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eval.run_eval as ev  # noqa: E402

WS = {"kinds_of_record": [{"name": "order"}, {"name": "vehicle"}], "relationships": [{"name": "order_vehicle"}],
      "data_values": [], "map_data": [], "problems": []}
ev.describe_workspace = lambda d, t: WS
ev.validate_ir = lambda p, ir, t: {"ok": "sets" in ir}
IR = {"version": 2, "sets": ["order", "vehicle"], "relationships": ["order_vehicle"], "variables": {}, "parameters": {},
      "constraints": [], "objective": {"mode": "lex", "sense": "maximize",
                                       "terms": [{"id": "served"}, {"id": "cost"}]}}
replies = iter([
    {"content": "", "tool_calls": [{"name": "describe_workspace", "arguments": {}}]},
    {"content": "", "tool_calls": [{"name": "validate_ir", "arguments": {"problem_id": 1, "ir": IR}}]},
    {"content": "", "tool_calls": [{"name": "propose_plan", "arguments": {"summary": "s", "ir": IR}}]},
    {"content": "Model validated; waiting for your approval."}])
r = ev.run_case({"name": "t", "domain_id": 1, "problem_id": 1, "brief": "x", "expect_goal_order": ["served", "cost"]},
                lambda m, t: next(replies), "tok")
assert r["finished"] and r["valid_model"] and r["uses_data"] and r["goal_order"] and r["text_calls"] == 0, r
print("ok eval smoke")
