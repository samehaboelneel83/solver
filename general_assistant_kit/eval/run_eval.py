"""Measure how well the local model turns plain words into a valid platform model.

For each case it runs the real loop against your model server with the real read-only tools
(describe_workspace, validate_ir, run_python). propose_plan is replaced by a recorder, so nothing in
the platform changes. Approve and solve the recorded plan yourself when you want the solver's answer.

Score per case:
  finished        the turn ended with a reply, not a step limit
  valid_model     the last model it produced passes the platform validator
  uses_data       every set and relationship in the model exists in the workspace
  goal_order      goal ids appear in the expected order (lexicographic cases)
  questions       question marks in its replies (fewer is better once data answers them)
  text_calls      tool calls it printed as text (recovered by the loop, but a sign of format drift)

Usage:  PS_API=http://localhost:3010 PS_TOKEN=... python eval/run_eval.py --model qwen3.5 [--ollama http://localhost:11434]
"""
import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent_loop import run_turn, ollama_call_model, openai_compatible_call_model  # noqa: E402
from platform_tools import describe_workspace, validate_ir, SCHEMAS  # noqa: E402
from sandbox import run_python, SCHEMA as PY  # noqa: E402

PROPOSE = {"type": "function", "function": {
    "name": "propose_plan",
    "description": "Propose the model to the user for approval. Arguments: summary (plain words) and ir (the model).",
    "parameters": {"type": "object", "properties": {"summary": {"type": "string"}, "ir": {"type": "object"}},
                   "required": ["summary", "ir"]}}}


def run_case(case, call_model, token):
    recorded = {}
    wd = tempfile.mkdtemp(prefix="eval_")
    files = {os.path.basename(p): p for p in case.get("files", [])}

    def execute(name, a):
        if name == "describe_workspace":
            return describe_workspace(case["domain_id"], token)
        if name == "validate_ir":
            return validate_ir(case["problem_id"], a["ir"], token)
        if name == "run_python":
            return run_python(a["code"], wd, files, a.get("timeout_s", 120))
        if name == "propose_plan":
            recorded["ir"] = a.get("ir")
            return {"status": "waiting for the user's approval"}
        return {"error": f"tool {name} is not available in the evaluation"}

    tools = SCHEMAS + [PY, PROPOSE]
    msgs = [{"role": "user", "content": case["brief"]}]
    for follow in [None] + case.get("follow_ups", []):
        if follow:
            msgs.append({"role": "user", "content": follow})
        t0 = time.time()
        final, trace = run_turn(msgs, call_model, execute, tools)
    ws = describe_workspace(case["domain_id"], token)
    kinds = {k["name"] for k in ws["kinds_of_record"]}
    rels = {r["name"] for r in ws["relationships"]}
    ir = recorded.get("ir") or {}
    v = validate_ir(case["problem_id"], ir, token) if ir else {"ok": False, "errors": ["no model proposed"]}
    goal_ids = [t.get("id") for t in (ir.get("objective") or {}).get("terms", [])]
    exp = case.get("expect_goal_order", [])
    replies = [m["content"] for m in msgs if m["role"] == "assistant" and m.get("content")]
    return {
        "case": case["name"],
        "finished": not final.startswith("I stopped"),
        "valid_model": v.get("ok", False),
        "validator_errors": v.get("errors", [])[:5],
        "uses_data": bool(ir) and set(ir.get("sets", [])) <= kinds and set(ir.get("relationships", [])) <= rels,
        "goal_order": (not exp) or [g for g in goal_ids if g in exp] == exp,
        "questions": sum(r.count("?") for r in replies),
        "text_calls": sum(t.get("recovered_from_text", 0) for t in trace),
        "tool_errors": sum(1 for t in trace if t.get("ok") is False),
        "seconds": round(time.time() - t0),
        "final_reply": final[:600],
        "model_ir": ir,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=os.path.join(os.path.dirname(__file__), "cases.json"))
    ap.add_argument("--model", default="qwen3.5")
    ap.add_argument("--ollama", default=None, help="Ollama base URL, e.g. http://localhost:11434")
    ap.add_argument("--openai", default=None, help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1")
    ap.add_argument("--out", default="eval_results.json")
    a = ap.parse_args()
    token = os.environ["PS_TOKEN"]
    call = (openai_compatible_call_model(a.openai, a.model) if a.openai
            else ollama_call_model(a.ollama or "http://localhost:11434", a.model))
    results = [run_case(c, call, token) for c in json.load(open(a.cases)) if c.get("domain_id")]
    json.dump(results, open(a.out, "w"), indent=1)
    for r in results:
        print(f"{r['case']:<28} valid={r['valid_model']!s:<5} data={r['uses_data']!s:<5} goals={r['goal_order']!s:<5} "
              f"q={r['questions']:<2} text_calls={r['text_calls']} errors={r['tool_errors']} {r['seconds']}s")
    print(f"valid models: {sum(r['valid_model'] for r in results)}/{len(results)}")


if __name__ == "__main__":
    main()
