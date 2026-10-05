"""Recover tool calls that a model printed as text, and refuse malformed ones loudly.

Why: the platform Assistant (qwen3.5) wrote `propose_plan` as
    "I need to fix the spec ... <tool_call>{...}</tool_call>"
Short calls with no prose before them were parsed by the server; long calls with prose
before them were shown to the user as text and never ran. This module finds those calls
in the message text so the loop can run them, and turns broken ones into a tool error the
model must fix, instead of a silent failure.

Handles:
  * Hermes/Qwen blocks:   <tool_call>{"name": ..., "arguments": {...}}</tool_call>  (prose before/after,
                          several blocks, missing closing tag)
  * Qwen3-Coder XML:      <function=name><parameter=key>value</parameter></function>
  * fenced JSON:          ```json {"name": ..., "arguments": ...} ```
  * arguments given as a JSON string
It rejects duplicate keys (the Assistant's spec repeated "entities_from_file" 3 times;
a normal json.loads keeps only the last one, silently dropping two imports).
"""
import json
import re

_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_XMLFN = re.compile(r"<function=([\w\-\.]+)>(.*?)</function>", re.S)
_XMLPARAM = re.compile(r"<parameter=([\w\-\.]+)>\s*(.*?)\s*</parameter>", re.S)


class DuplicateKeyError(ValueError):
    pass


def _no_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise DuplicateKeyError(f'duplicate key "{k}" in the same object')
        seen[k] = v
    return seen


def strict_loads(s):
    return json.loads(s, object_pairs_hook=_no_dupes)


def _repair(s):
    """Light repair for truncated or sloppy JSON: drop trailing commas, close open brackets."""
    s = re.sub(r",\s*([}\]])", r"\1", s.strip())
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch in "{[": stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack: stack.pop()
    if in_str:
        s += '"'
    s = s + "".join(reversed(stack))
    return re.sub(r",\s*([}\]])", r"\1", s)


def _normalise(obj, known):
    if not isinstance(obj, dict) or "name" not in obj:
        raise ValueError('a tool call must be an object with "name" and "arguments"')
    name = obj["name"]
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        args = strict_loads(args) if args.strip() else {}
    if known is not None and name not in known:
        raise ValueError(f'unknown tool "{name}"; available: {", ".join(sorted(known))}')
    if not isinstance(args, dict):
        raise ValueError("arguments must be a JSON object")
    return {"name": name, "arguments": args}


def extract_tool_calls(text, known_tools=None):
    """Return (calls, prose, errors). `calls` are ready to execute; `errors` must go back to the model."""
    calls, errors, spans = [], [], []
    known = set(known_tools) if known_tools else None

    for m in _BLOCK.finditer(text or ""):
        spans.append(m.span())
        raw = m.group(1)
        try:
            try:
                obj = strict_loads(raw)
            except DuplicateKeyError:
                raise
            except json.JSONDecodeError:
                obj = strict_loads(_repair(raw))
                errors.append("note: the tool call JSON was incomplete and was repaired; check it is what you meant")
            calls.append(_normalise(obj, known))
        except Exception as e:  # noqa: BLE001 - every failure becomes feedback for the model
            errors.append(f"tool call not run: {e}")

    for m in _XMLFN.finditer(text or ""):
        spans.append(m.span())
        args = {}
        for k, v in _XMLPARAM.findall(m.group(2)):
            try:
                args[k] = strict_loads(v)
            except Exception:  # plain string value
                args[k] = v
        try:
            calls.append(_normalise({"name": m.group(1), "arguments": args}, known))
        except Exception as e:  # noqa: BLE001
            errors.append(f"tool call not run: {e}")

    if not calls and not errors:
        for m in _FENCE.finditer(text or ""):
            try:
                obj = strict_loads(m.group(1))
            except Exception:
                continue
            if isinstance(obj, dict) and "name" in obj and ("arguments" in obj or "parameters" in obj):
                spans.append(m.span())
                try:
                    calls.append(_normalise(obj, known))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"tool call not run: {e}")

    prose = text or ""
    for a, b in sorted(spans, reverse=True):
        prose = prose[:a] + prose[b:]
    return calls, prose.strip(), errors


def looks_like_unrun_call(text):
    """True when a final answer still contains tool-call markup: the turn must not end like that."""
    return bool(re.search(r"<tool_call>|<function=|\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\"", text or ""))
