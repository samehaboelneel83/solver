"""Recover tool calls that a model printed as text, and refuse malformed ones loudly.

From general_assistant_kit/toolcall.py (the audit's "General assistant" plan), unchanged but for
`extract_tool_calls` taking `allow_repair`: a reply cut off at the length limit is not repaired
(app/agent/core.py tells the model to send a smaller call instead).


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


def _no_dupes(pairs, notes=None):
    """A key given twice. Two lists under it are joined and two objects with no key in common merged: a
    model writing a long spec splits a list over two same-named keys (the platform test of October 2026
    sent "entity_types" twice, three times in a row, and gave up), and joining them is what it meant. The
    join is reported back (`notes`), and the plan is checked and shown to the person before anything is
    built. Two different values that cannot be joined are refused, as before: picking one would drop data."""
    seen = {}
    for k, v in pairs:
        if k in seen:
            a = seen[k]
            if isinstance(a, list) and isinstance(v, list):
                seen[k] = a + v
                if notes is not None:
                    notes.append(f'"{k}" was given twice; its two lists were joined ({len(a)} + {len(v)} items)')
                continue
            if isinstance(a, dict) and isinstance(v, dict) and not set(a) & set(v):
                seen[k] = {**a, **v}
                if notes is not None:
                    notes.append(f'"{k}" was given twice; its two objects were merged')
                continue
            if a == v:
                continue
            raise DuplicateKeyError(f'duplicate key "{k}" in the same object, with two different values '
                                    f'({_brief(a)} and {_brief(v)}); give it once')
        seen[k] = v
    return seen


def _brief(v):
    text = json.dumps(v, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def strict_loads(s, notes=None):
    """json.loads that never silently drops a repeated key (see _no_dupes); `notes` collects the joins."""
    try:
        return json.loads(s, object_pairs_hook=lambda pairs: _no_dupes(pairs, notes))
    except json.JSONDecodeError as e:
        # Where it broke, so the model can see what it sent (it does not get its broken call back).
        near = s[max(0, e.pos - 60): e.pos + 30].replace("\n", " ")
        raise json.JSONDecodeError(f"{e.msg}; near: ...{near}...", e.doc, e.pos) from None


_BARE_NAME = re.compile(r'^(\s*\{\s*"name"\s*:\s*)([A-Za-z_][\w\-.]*)(\s*[,}])')


def _extra_closers(s):
    """The call's own JSON when all that follows a whole object is stray closing brackets; else None."""
    text = s.strip()
    try:
        _, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    rest = text[end:]
    return text[:end] if rest and set(rest) <= set("}] \n\t\r") else None


def _loads_or_none(s, notes):
    try:
        return strict_loads(s, list(notes)) is not None
    except Exception:  # noqa: BLE001
        return False


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


_SPEC_CALL = re.compile(r'"name"\s*:\s*"(?:check_spec|propose_plan)"')
_NO_RIGHT = __import__("re").compile(r'("relation"\s*:\s*"(?:<=|>=|==|=|<|>)"\s*,\s*)(?=[{\[])')


def fix_spec(s):
    """The slips Qwen makes writing a long spec, each put right only where it can mean one thing:
    a rule's "right": key left out ("relation": "<=", {"mul": ...} -- the roster field test, twice), and
    the closing brackets at the end in the wrong order (fix_closers). None when neither applies."""
    fixed = _NO_RIGHT.sub(r'\1"right": ', s or "")
    try:
        json.loads(fixed)
        return fixed if fixed != s else None
    except json.JSONDecodeError:
        pass
    quoted = escape_inner_quotes(fixed)
    if quoted is not None:
        return quoted
    closed = fix_closers(fixed)
    if closed is not None and _error_at(closed) > len(closed):
        return closed
    return mend_brackets(fixed)


def _error_at(text):
    """Where `text` first fails to parse (its length + 1 when it parses)."""
    try:
        json.loads(text)
        return len(text) + 1
    except json.JSONDecodeError as e:
        return e.pos


def mend_brackets(s, limit=12):
    """A bracket dropped or doubled in the middle of a long spec: `{"attr": {"of": "p", "name": "rate"}, {"var": ...`
    (the production-planning trace, 10 October 2026: qwen3.5 lost six specs of 12-15 KB to one brace each, ten
    minutes a try). At each place the parse fails, the smallest edits are tried -- a `}` or `]` put in at one of
    the last few commas before it or at the place itself, or one of the last few closers taken out -- and the one
    that lets the parse go furthest is kept; up to `limit` edits. None when that does not make valid JSON. The
    result is valid JSON, not necessarily what was meant: the platform checks the spec and the person reads it."""
    text = s or ""
    for _ in range(limit):
        at = _error_at(text)
        if at > len(text):
            return text if text != s else None
        # The last few commas and closers before the failure: a dropped closer belongs before one of the commas,
        # a doubled one is one of the closers.
        commas, closers, i, in_str = [], [], 0, False
        while i < at:
            ch = text[i]
            if in_str:
                if ch == "\\":
                    i += 1
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == ",":
                commas.append(i)
            elif ch in "}]":
                closers.append(i)
            i += 1
        candidates = [text[:at] + closer + text[at:] for closer in "}]"]
        for c in commas[-4:]:
            candidates += [text[:c] + closer + text[c:] for closer in "}]"]
        candidates += [text[:c] + text[c + 1:] for c in closers[-4:]]
        best, best_at = None, at
        for candidate in candidates:
            reach = _error_at(candidate)
            if reach > best_at:
                best, best_at = candidate, reach
        if best is None:
            return None
        text = best
    return text if _error_at(text) > len(text) else None


_AFTER_STRING = re.compile(r'\s*[,:}\]]')


def escape_inner_quotes(s, limit=60):
    """Quotes inside a text value left unescaped: 'The "keeps_free" cells...'. The camp retest (October 2026): a
    plan's summary was refused twice for it ("Expecting ',' delimiter") and Qwen rewrote the whole plan each time,
    7 minutes. A quote that ends a string where no , : } ] follows cannot be the string's end, so it is escaped,
    and the next one with it; None when that does not make valid JSON."""
    text = s or ""
    for _ in range(limit):
        try:
            json.loads(text)
            return text if text != s else None
        except json.JSONDecodeError as e:
            if not e.msg.startswith(("Expecting ',' delimiter", "Expecting ':' delimiter")):
                return None
            quote = text.rfind('"', 0, e.pos)
            if quote <= 0 or text[quote - 1] == "\\" or _AFTER_STRING.match(text, quote + 1):
                return None
            text = text[:quote] + '\\"' + text[quote + 1:]
    return None


def fix_closers(s):
    """The closing brackets at the very end of a long call, put back in the order the opening ones need.

    The field test (October 2026): Qwen wrote a 10,000-character spec right up to its last characters and
    then closed it "}]}}]}}}}}}" -- the right brackets in the wrong order -- three times in a row. Only that
    final run of closers is rebuilt, from what the text before it left open; anything wrong earlier is left
    alone (None). Used for check_spec and propose_plan only, whose spec is then checked by the platform and
    read by the person before anything is built."""
    s = (s or "").rstrip()
    end = len(s)
    while end > 0 and s[end - 1] in "]} \n\r\t":
        end -= 1
    stack, in_str, esc = [], False, False
    for ch in s[:end]:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return None
    if in_str or not stack:
        return None
    fixed = s[:end] + "".join(reversed(stack))
    return None if fixed == s else fixed


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


def extract_tool_calls(text, known_tools=None, allow_repair=True):
    """Return (calls, prose, errors). `calls` are ready to execute; `errors` must go back to the model."""
    calls, errors, spans = [], [], []
    joined = []  # keys given twice and joined (strict_loads): told to the model as notes
    known = set(known_tools) if known_tools else None

    for m in _BLOCK.finditer(text or ""):
        spans.append(m.span())
        raw = m.group(1)
        try:
            try:
                obj = strict_loads(raw, joined)
            except DuplicateKeyError:
                raise
            except json.JSONDecodeError:
                # A spec's slips (fix_spec), for the spec tools only, as for native calls (the retest: Qwen
                # wrote its check_spec call as text, and the dropped "right" key went uncorrected).
                fixed = fix_spec(raw) if allow_repair and _SPEC_CALL.search(raw) else None
                if fixed is not None:
                    obj = strict_loads(fixed, joined)
                    errors.append("note: your call's JSON had a slip (a rule's \"right\" key left out, or closing "
                                  "brackets dropped, doubled or out of order) and was put right; check the spec says what you "
                                  "meant, and write it correctly next time")
                elif _extra_closers(raw) is not None:
                    # One closing bracket too many after a whole call (live what-if test, October 2026: the
                    # what_if call was lost to "Extra data"): the call is the object before them.
                    obj = strict_loads(_extra_closers(raw), joined)
                    errors.append("note: the call had closing brackets left over after it; they were dropped")
                elif _BARE_NAME.search(raw) and _loads_or_none(_BARE_NAME.sub(r'\1"\2"\3', raw, count=1), joined):
                    # The tool's name written without quotes ({"name": describe_workspace, ...}): the live what-if
                    # test of October 2026 lost the call to it, and the model then answered without looking.
                    obj = strict_loads(_BARE_NAME.sub(r'\1"\2"\3', raw, count=1), joined)
                    errors.append("note: the tool's name was written without quotes and was put right; quote it next time")
                else:
                    if not allow_repair:
                        raise
                    obj = strict_loads(_repair(raw), joined)
                    errors.append("note: the tool call JSON was incomplete and was repaired; check it is what you meant")
            calls.append(_normalise(obj, known))
        except Exception as e:  # noqa: BLE001 - every failure becomes feedback for the model
            errors.append(f"tool call not run: {e}")

    for m in _XMLFN.finditer(text or ""):
        spans.append(m.span())
        args = {}
        bad = None
        spec_tool = m.group(1) in ("check_spec", "propose_plan")
        for k, v in _XMLPARAM.findall(m.group(2)):
            try:
                args[k] = strict_loads(v, joined)
            except DuplicateKeyError as e:  # JSON, but with a key that cannot be joined: not a string
                bad = e
            except Exception as e:  # plain string value -- unless it is a spec that does not parse
                if spec_tool and k == "spec" and v.lstrip().startswith("{"):
                    fixed = fix_spec(v) if allow_repair else None
                    if fixed is None:
                        bad = e
                        continue
                    args[k] = strict_loads(fixed, joined)
                    joined.append('the spec\'s JSON had a slip (a rule\'s "right" key left out, or the closing '
                                  "brackets out of order) and was put right")
                else:
                    args[k] = v
        if bad is not None:
            errors.append(f"tool call not run: {bad}")
            continue
        try:
            calls.append(_normalise({"name": m.group(1), "arguments": args}, known))
        except Exception as e:  # noqa: BLE001
            errors.append(f"tool call not run: {e}")

    if not calls and not errors:
        for m in _FENCE.finditer(text or ""):
            try:
                mine = []
                obj = strict_loads(m.group(1), mine)
            except Exception:
                continue
            if isinstance(obj, dict) and "name" in obj and ("arguments" in obj or "parameters" in obj):
                joined.extend(mine)
                spans.append(m.span())
                try:
                    calls.append(_normalise(obj, known))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"tool call not run: {e}")

    errors.extend("note: " + j for j in joined)
    prose = text or ""
    for a, b in sorted(spans, reverse=True):
        prose = prose[:a] + prose[b:]
    return calls, prose.strip(), errors


def looks_like_unrun_call(text):
    """True when a final answer still contains tool-call markup: the turn must not end like that."""
    return bool(re.search(r"<tool_call>|<function=|\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\"", text or ""))
