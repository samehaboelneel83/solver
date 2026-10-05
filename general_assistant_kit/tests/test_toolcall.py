import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from toolcall import extract_tool_calls, looks_like_unrun_call  # noqa: E402

KNOWN = {"propose_plan", "place_file", "read_file"}


def test_prose_then_call_is_recovered():
    # exact shape of the Assistant's failed turn
    text = ('I need to fix the spec - there are technical issues. Let me create a working version:\n\n'
            '<tool_call>\n{"name": "propose_plan", "arguments": {"summary": "Problem\\nAssign 40 orders", '
            '"spec": {"domain_id": 209}}}\n</tool_call>')
    calls, prose, errors = extract_tool_calls(text, KNOWN)
    assert errors == []
    assert calls == [{"name": "propose_plan", "arguments": {"summary": "Problem\nAssign 40 orders",
                                                            "spec": {"domain_id": 209}}}]
    assert prose.startswith("I need to fix the spec")


def test_duplicate_keys_are_refused():
    text = ('<tool_call>{"name": "propose_plan", "arguments": {"spec": {"seed": {'
            '"entities_from_file": [1], "entities_from_file": [2], "entities_from_file": [3]}}}}</tool_call>')
    calls, _, errors = extract_tool_calls(text, KNOWN)
    assert calls == []
    assert any('duplicate key "entities_from_file"' in e for e in errors)


def test_missing_close_tag_and_truncated_json_repaired():
    text = 'ok <tool_call>{"name": "read_file", "arguments": {"path": "orders.xlsx", "sheets": ["orders",'
    calls, _, errors = extract_tool_calls(text, KNOWN)
    assert calls == [{"name": "read_file", "arguments": {"path": "orders.xlsx", "sheets": ["orders"]}}]
    assert any("repaired" in e for e in errors)


def test_string_arguments_and_several_calls():
    text = ('<tool_call>{"name":"place_file","arguments":"{\\"epsg\\": 2318}"}</tool_call> then '
            '<tool_call>{"name":"read_file","arguments":{}}</tool_call>')
    calls, _, errors = extract_tool_calls(text, KNOWN)
    assert [c["name"] for c in calls] == ["place_file", "read_file"]
    assert calls[0]["arguments"] == {"epsg": 2318}
    assert errors == []


def test_qwen3_coder_xml_format():
    text = ('<function=propose_plan><parameter=mode>quick</parameter>'
            '<parameter=limits>{"depot_A": {"max_trucks": 4}}</parameter></function>')
    calls, _, errors = extract_tool_calls(text, KNOWN)
    assert calls == [{"name": "propose_plan", "arguments": {"mode": "quick",
                                                            "limits": {"depot_A": {"max_trucks": 4}}}}]


def test_unknown_tool_is_reported():
    calls, _, errors = extract_tool_calls('<tool_call>{"name":"build_it","arguments":{}}</tool_call>', KNOWN)
    assert calls == [] and "unknown tool" in errors[0]


def test_final_answer_guard():
    assert looks_like_unrun_call('Done.\n<tool_call>{"name":"x","arguments":{}}</tool_call>')
    assert not looks_like_unrun_call("Assigned 40 orders; the check passed.")


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
