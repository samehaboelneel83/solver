"""General agent loop for the platform Assistant (no problem-specific code).

- native tool calls are used when the model server returns them
- tool calls printed as text are recovered and run (toolcall.py)
- malformed calls (bad JSON, duplicate keys, unknown tool) go back to the model as tool errors
- a final reply cannot contain unrun tool-call markup, nor claim work that no tool result shows

Plug in: call_model(messages, tools) -> {"content", "tool_calls": [{"name", "arguments"}]}
         execute(name, arguments)   -> dict   (your platform tools + run_python + describe_workspace + validate_ir)
"""
import json
import os
import re
import urllib.request

from toolcall import extract_tool_calls, looks_like_unrun_call

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT = open(os.path.join(HERE, "SYSTEM_PROMPT.md")).read() + "\n\n" + open(os.path.join(HERE, "IR_REFERENCE.md")).read()

_CLAIM = re.compile(r"\b(built|created|imported|solved|published|checked|verified|is now on the map)\b", re.I)
_DOERS = re.compile(r"^(propose_plan|build|publish|solve|import|place_file|attach|create|run_python|validate_ir)")


def run_turn(messages, call_model, execute, tools, max_steps=24, max_text_retries=2):
    names = {t["function"]["name"] for t in tools}
    trace, did_work, nudged = [], False, 0
    for _ in range(max_steps):
        resp = call_model(messages, tools)
        content = resp.get("content") or ""
        calls = list(resp.get("tool_calls") or [])
        errors = []
        if not calls:
            found, prose, errors = extract_tool_calls(content, names)
            if found or errors:
                calls, content = found, prose
                trace.append({"recovered_from_text": len(found), "errors": errors})
        messages.append({"role": "assistant", "content": content,
                         **({"tool_calls": [{"type": "function", "function": c} for c in calls]} if calls else {})})
        if errors and not calls:
            messages.append({"role": "tool", "content": json.dumps({"error": errors, "fix":
                             "Send the call again through the tool interface, with valid JSON and unique keys."})})
            continue
        if calls:
            for c in calls:
                try:
                    result = execute(c["name"], c["arguments"])
                    ok = not (isinstance(result, dict) and (result.get("error") or result.get("ok") is False
                                                            or result.get("exit_code") not in (None, 0)))
                except Exception as e:  # noqa: BLE001 - every failure is feedback for the model
                    result, ok = {"error": f"{type(e).__name__}: {e}"}, False
                did_work |= ok and bool(_DOERS.match(c["name"]))
                trace.append({"tool": c["name"], "ok": ok})
                messages.append({"role": "tool", "name": c["name"], "content": json.dumps(result, default=str)[:24000]})
            for e in errors:
                messages.append({"role": "tool", "content": json.dumps({"warning": e})})
            continue
        if looks_like_unrun_call(content) and nudged < max_text_retries:
            nudged += 1
            messages.append({"role": "user", "content": "That message contains a tool call as text; it did not run. "
                             "Call the tool through the tool interface."})
            continue
        if _CLAIM.search(content) and not did_work and nudged < max_text_retries:
            nudged += 1
            messages.append({"role": "user", "content": "No tool succeeded in this turn, so nothing was built, imported, "
                             "solved or checked. Run the tool now, or say plainly that nothing ran."})
            continue
        return content, trace
    return "I stopped after too many steps without finishing. Nothing further was changed.", trace


def ollama_call_model(base_url="http://localhost:11434", model="qwen3.5", num_ctx=65536, num_predict=8192):
    """Ollama /api/chat (stdlib only). Large num_predict so long plans are not cut mid-JSON."""
    def call(messages, tools):
        body = {"model": model, "stream": False, "tools": tools,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0.2}}
        req = urllib.request.Request(f"{base_url}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            m = json.loads(r.read())["message"]
        calls = []
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", tc)
            a = fn.get("arguments", {})
            calls.append({"name": fn["name"], "arguments": json.loads(a) if isinstance(a, str) else a})
        return {"content": m.get("content", ""), "tool_calls": calls}
    return call


def openai_compatible_call_model(base_url="http://localhost:8000/v1", model="qwen3.5", max_tokens=8192):
    """vLLM / llama.cpp server / any OpenAI-compatible endpoint inside the network (stdlib only)."""
    def call(messages, tools):
        body = {"model": model, "tools": tools, "max_tokens": max_tokens, "temperature": 0.2,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages}
        req = urllib.request.Request(f"{base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            m = json.loads(r.read())["choices"][0]["message"]
        calls = []
        for tc in m.get("tool_calls") or []:
            a = tc["function"].get("arguments") or "{}"
            calls.append({"name": tc["function"]["name"], "arguments": json.loads(a) if isinstance(a, str) else a})
        return {"content": m.get("content") or "", "tool_calls": calls}
    return call
