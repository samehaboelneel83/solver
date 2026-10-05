import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent_loop import run_turn  # noqa: E402
from sandbox import run_python, SCHEMA as PY  # noqa: E402
from platform_tools import SCHEMAS  # noqa: E402

TOOLS = SCHEMAS + [PY, {"type": "function", "function": {"name": "propose_plan", "parameters": {"type": "object"}}}]


def scripted(replies):
    it = iter(replies)
    return lambda messages, tools: next(it)


def test_recovers_text_call_feeds_back_errors_and_blocks_false_claims():
    ran = []

    def execute(name, args):
        ran.append(name)
        if name == "validate_ir" and "bad" in args.get("ir", {}):
            return {"ok": False, "errors": [{"where": "constraints.0.id", "problem": "ids are ^[a-z][a-z0-9_]*$"}]}
        return {"ok": True}

    model = scripted([
        {"content": "I have built and solved the model."},                                    # false claim
        {"content": 'Looking first.\n<tool_call>{"name": "describe_workspace", "arguments": {}}</tool_call>'},  # text call
        {"content": '<tool_call>{"name": "validate_ir", "arguments": {"problem_id": 1, "ir": {"a": 1, "a": 2}}}</tool_call>'},  # dup keys
        {"content": "", "tool_calls": [{"name": "validate_ir", "arguments": {"problem_id": 1, "ir": {"bad": 1}}}]},
        {"content": "", "tool_calls": [{"name": "validate_ir", "arguments": {"problem_id": 1, "ir": {"ok": 1}}}]},
        {"content": "", "tool_calls": [{"name": "propose_plan", "arguments": {"summary": "s"}}]},
        {"content": "The model validated and the plan is waiting for your approval."},
    ])
    msgs = [{"role": "user", "content": "maximise served demand"}]
    final, trace = run_turn(msgs, model, execute, TOOLS)
    assert ran == ["describe_workspace", "validate_ir", "validate_ir", "propose_plan"], ran
    assert final.startswith("The model validated")
    joined = " ".join(m["content"] for m in msgs if m["role"] in ("tool", "user"))
    assert "duplicate key" in joined and "No tool succeeded" in joined


def test_sandbox_runs_code_keeps_files_and_times_out():
    wd = tempfile.mkdtemp()
    r = run_python("import json\nopen('rows.csv','w').write('key,value\\nA,1\\n')\nprint(json.dumps({'n': 1}))", wd)
    assert r["exit_code"] == 0 and '"n": 1' in r["stdout"] and "rows.csv" in r["files_written"]
    r2 = run_python("print(open('rows.csv').read().count('\\n'))", wd)
    assert r2["stdout"].strip() == "2"
    r3 = run_python("while True: pass", wd, timeout_s=2, cpu_s=5)
    assert r3["exit_code"] != 0
    r4 = run_python("raise ValueError('bad input')", wd)
    assert r4["exit_code"] != 0 and "bad input" in r4["stderr"]


if __name__ == "__main__":
    test_recovers_text_call_feeds_back_errors_and_blocks_false_claims(); print("ok loop")
    test_sandbox_runs_code_keeps_files_and_times_out(); print("ok sandbox")
