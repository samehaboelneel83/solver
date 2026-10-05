#!/usr/bin/env python3
"""Solver platform agent — drives the whole platform through its own API,
using a local OpenAI-compatible LLM (vLLM / Qwen).

Standard library only. Python 3.9+.

    python solver_agent.py                 # interactive chat in the terminal
    python solver_agent.py "list my problems and solve the newest scenario"
    python solver_agent.py --web           # chat page on http://localhost:8020

How it reaches "everything": on start it reads the backend's live
/openapi.json, so every endpoint the platform has (and any you add later) is
available. The model finds endpoints with `search_endpoints`, reads their
exact parameters/body with `describe_endpoint`, then calls them with
`call_api`. It can also read the repo docs (docs/, README.md) to learn the
Problem IR before building models.

Configuration: environment variables, or agent/.env (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


# ----------------------------------------------------------------- config --
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(HERE / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


LLM_BASE_URL = env("LLM_BASE_URL", "http://10.125.18.189:8000/v1").rstrip("/")
LLM_MODEL = env("LLM_MODEL", "qwen3.5")
LLM_API_KEY = env("LLM_API_KEY", "EMPTY")
LLM_TEMPERATURE = float(env("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(env("LLM_MAX_TOKENS", "4096"))
LLM_CONTEXT = int(env("LLM_CONTEXT", "32768"))
# "on" / "off" / "" (server default). Qwen thinking costs context; off is faster.
LLM_THINKING = env("LLM_THINKING", "").lower()

SOLVER_URL = env("SOLVER_URL", "http://localhost:8010").rstrip("/")
SOLVER_API_KEY = env("SOLVER_API_KEY")
SOLVER_USERNAME = env("SOLVER_USERNAME", "admin")
SOLVER_PASSWORD = env("SOLVER_PASSWORD", "change-me-admin")

# Which calls need a human "yes": none | delete | write  (write = any non-GET)
CONFIRM = env("AGENT_CONFIRM", "delete").lower()
MAX_STEPS = int(env("AGENT_MAX_STEPS", "40"))
TOOL_RESULT_CHARS = int(env("AGENT_TOOL_RESULT_CHARS", "8000"))
WEB_PORT = int(env("AGENT_WEB_PORT", "8020"))
LOG_DIR = Path(env("AGENT_LOG_DIR", str(HERE / "logs")))


# ------------------------------------------------------------------- http --
class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def http(method: str, url: str, *, headers=None, data: bytes | None = None,
         timeout: float = 300) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----solveragent" + uuid.uuid4().hex
    out = bytearray()
    for k, v in (fields or {}).items():
        if not isinstance(v, str):
            v = json.dumps(v)
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()
    for k, p in (files or {}).items():
        path = Path(p)
        if not path.is_absolute():
            path = (REPO / path) if (REPO / path).exists() else Path.cwd() / path
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        out += path.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------- platform --
class Platform:
    """The solver backend: auth + OpenAPI index + raw calls."""

    def __init__(self) -> None:
        self.token: str | None = SOLVER_API_KEY or None
        self.spec: dict = {}
        self.ops: list[dict] = []

    # auth
    def login(self) -> None:
        if SOLVER_API_KEY:
            self.token = SOLVER_API_KEY
            return
        body = urllib.parse.urlencode(
            {"username": SOLVER_USERNAME, "password": SOLVER_PASSWORD}).encode()
        st, _, raw = http("POST", SOLVER_URL + "/api/auth/login", data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        if st != 200:
            raise RuntimeError(f"login to {SOLVER_URL} failed ({st}): {raw[:300]!r}")
        self.token = json.loads(raw)["access_token"]

    # spec
    def load_spec(self) -> None:
        st, _, raw = http("GET", SOLVER_URL + "/openapi.json", timeout=30)
        if st != 200:
            raise RuntimeError(f"could not read {SOLVER_URL}/openapi.json ({st})")
        self.spec = json.loads(raw)
        self.ops = []
        for path, item in self.spec.get("paths", {}).items():
            for method, op in item.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                self.ops.append({
                    "method": method.upper(), "path": path,
                    "summary": op.get("summary") or op.get("operationId") or "",
                    "tags": op.get("tags") or [],
                    "description": (op.get("description") or "").strip(),
                    "op": op, "item": item,
                })

    def tag_overview(self) -> str:
        counts: dict[str, int] = {}
        for o in self.ops:
            for t in (o["tags"] or ["untagged"]):
                counts[t] = counts.get(t, 0) + 1
        return ", ".join(f"{t} ({n})" for t, n in sorted(counts.items()))

    # search
    def search(self, query: str, method: str | None = None, limit: int = 25) -> list[dict]:
        words = [w for w in re.split(r"[\s/_\-]+", query.lower()) if w]
        scored = []
        for o in self.ops:
            if method and o["method"] != method.upper():
                continue
            hay_path = o["path"].lower()
            hay = " ".join([hay_path, o["summary"].lower(), " ".join(o["tags"]).lower(),
                            o["description"][:400].lower()])
            score = 0
            for w in words:
                stem = w.rstrip("s") if len(w) > 3 else w
                if stem in hay_path:
                    score += 3
                if stem in hay:
                    score += 1
            if not words:
                score = 1
            if score:
                scored.append((score, o))
        scored.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["method"]))
        return [{"method": o["method"], "path": o["path"], "summary": o["summary"],
                 "tags": o["tags"]} for _, o in scored[:limit]]

    def find(self, method: str, path: str) -> dict | None:
        for o in self.ops:
            if o["method"] == method.upper() and o["path"] == path:
                return o
        # allow concrete paths: /api/v1/runs/123 -> /api/v1/runs/{run_id}
        for o in self.ops:
            if o["method"] != method.upper():
                continue
            pat = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(o["path"])) + "$"
            if re.match(pat, path):
                return o
        return None

    def _resolve(self, schema, depth=0, seen=()):
        """Inline $refs so the model sees a self-contained schema.
        depth counts $ref hops only; recursive refs are cut."""
        if isinstance(schema, list):
            return [self._resolve(s, depth, seen) for s in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            ref = schema["$ref"]
            name = ref.split("/")[-1]
            if ref in seen or depth >= 5:
                return {"$ref_name": name, "note": "(see describe_schema '" + name + "')"}
            node = self.spec
            for part in ref.lstrip("#/").split("/"):
                node = node.get(part, {})
            return self._resolve(node, depth + 1, seen + (ref,))
        return {k: self._resolve(v, depth, seen) for k, v in schema.items() if k != "title"}

    def schema(self, name: str) -> dict:
        node = self.spec.get("components", {}).get("schemas", {}).get(name)
        return self._resolve(node) if node else {"error": f"no schema {name}"}

    def describe(self, method: str, path: str) -> dict:
        o = self.find(method, path)
        if not o:
            return {"error": f"no endpoint {method.upper()} {path}. Use search_endpoints."}
        op = o["op"]
        params = (o["item"].get("parameters") or []) + (op.get("parameters") or [])
        out = {
            "method": o["method"], "path": o["path"], "summary": o["summary"],
            "description": o["description"][:2500],
            "parameters": [{
                "name": p.get("name"), "in": p.get("in"), "required": p.get("required", False),
                "schema": self._resolve(p.get("schema", {})),
                "description": (p.get("description") or "")[:300],
            } for p in (self._resolve(x) for x in params)],
        }
        rb = op.get("requestBody")
        if rb:
            rb = self._resolve(rb)
            content = rb.get("content", {})
            ctype = next(iter(content), None)
            out["request_body"] = {
                "required": rb.get("required", False), "content_type": ctype,
                "schema": content.get(ctype, {}).get("schema") if ctype else None,
            }
        ok = next((v for k, v in (op.get("responses") or {}).items() if str(k).startswith("2")), None)
        if ok and "content" in ok:
            sch = next(iter(ok["content"].values()), {}).get("schema")
            if sch:
                out["response_schema"] = self._resolve(sch)
        return out

    # call
    def call(self, method: str, path: str, query=None, body=None, form=None, files=None,
             extra_headers=None) -> dict:
        method = method.upper()
        if not path.startswith("/"):
            path = "/" + path
        url = SOLVER_URL + path
        if query:
            q = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                 for k, v in query.items() if v is not None}
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q, doseq=True)
        headers = {"Accept": "application/json"}
        headers.update({str(k): str(v) for k, v in (extra_headers or {}).items()})
        data = None
        if files:
            data, ctype = _multipart(form or {}, files)
            headers["Content-Type"] = ctype
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(2):
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            st, h, raw = http(method, url, headers=headers, data=data)
            if st == 401 and attempt == 0 and not SOLVER_API_KEY:
                self.login()  # token expired: sign in again once
                continue
            break
        ctype = (h.get("content-type") or h.get("Content-Type") or "")
        if "json" in ctype:
            try:
                payload = json.loads(raw or b"null")
            except ValueError:
                payload = raw.decode("utf-8", "replace")
        elif ctype.startswith("text/") or not raw:
            payload = raw.decode("utf-8", "replace")
        else:
            saved = LOG_DIR / f"download-{int(time.time())}{_ext(ctype)}"
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
            payload = f"<{len(raw)} bytes of {ctype} saved to {saved}>"
        return {"status": st, "ok": 200 <= st < 300, "body": payload}


def _ext(ctype: str) -> str:
    for k, v in {"csv": ".csv", "zip": ".zip", "pdf": ".pdf", "spreadsheet": ".xlsx",
                 "geo+json": ".geojson", "png": ".png"}.items():
        if k in ctype:
            return v
    return ".bin"


# ------------------------------------------------------------------ tools --
TOOLS = [
    {"type": "function", "function": {
        "name": "search_endpoints",
        "description": "Find platform API endpoints by keywords (e.g. 'entity types', 'runs scenario', "
                       "'parameter values', 'api keys'). Returns method, path, summary. Always search "
                       "before calling an endpoint you have not described yet.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "keywords"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                       "description": "optional filter"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "describe_endpoint",
        "description": "Get the exact path/query parameters, request body schema and response schema of "
                       "one endpoint. Use before any POST/PUT/PATCH so the body is right.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string"}, "path": {"type": "string",
                                                   "description": "templated path as returned by search"},
        }, "required": ["method", "path"]}}},
    {"type": "function", "function": {
        "name": "call_api",
        "description": "Call any platform endpoint as the signed-in user. Fill path parameters into the "
                       "path yourself (e.g. /api/v1/scenarios/42/runs). Returns status and JSON body.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "path": {"type": "string"},
            "query": {"type": "object", "description": "query-string parameters"},
            "body": {"description": "JSON request body"},
            "form": {"type": "object", "description": "form fields (for form/multipart endpoints)"},
            "files": {"type": "object", "description": "multipart file fields: {field: local file path}"},
            "headers": {"type": "object", "description": "extra HTTP headers, e.g. Idempotency-Key"},
        }, "required": ["method", "path"]}}},
    {"type": "function", "function": {
        "name": "describe_schema",
        "description": "Expand a named schema that describe_endpoint shortened (deeply nested models).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                       "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "read_doc",
        "description": "Read a platform document from the repo, e.g. 'docs/contracts/problem-ir.md', "
                       "'README.md', 'docs/engine.md'. Pass a directory (e.g. 'docs') to list files. "
                       "Use this to learn the Problem IR before writing models.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "character offset for long files"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "wait",
        "description": "Sleep a few seconds (e.g. while a solve run is queued/running), then poll again.",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "integer", "minimum": 1, "maximum": 60}}, "required": ["seconds"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

DOC_ROOTS = ["docs", "README.md", "handover.md", "OAAS_PLATFORM_PROPOSAL.md",
             "OAAS_ENHANCEMENT_PLAN.md", "OAAS_UX_FORM_GRAPH_PLAN.md", "samples"]


def read_doc(path: str, offset: int = 0) -> str:
    rel = path.replace("\\", "/").lstrip("/")
    target = (REPO / rel).resolve()
    if not str(target).startswith(str(REPO.resolve())) or not any(
            rel == r or rel.startswith(r.rstrip("/") + "/") for r in DOC_ROOTS):
        return f"not allowed; readable roots: {', '.join(DOC_ROOTS)}"
    if target.is_dir():
        files = sorted(str(p.relative_to(REPO)).replace("\\", "/")
                       for p in target.rglob("*") if p.is_file() and p.suffix in
                       (".md", ".json", ".sql", ".csv", ".geojson", ".yaml", ".yml", ".txt"))
        return "\n".join(files[:300])
    if not target.exists():
        return "file not found"
    text = target.read_text(encoding="utf-8", errors="replace")
    chunk = text[offset: offset + TOOL_RESULT_CHARS]
    more = len(text) - (offset + len(chunk))
    if more > 0:
        chunk += f"\n...[{more} more chars; call read_doc with offset={offset + len(chunk)}]"
    return chunk


def clip(obj) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) <= TOOL_RESULT_CHARS:
        return s
    return (s[:TOOL_RESULT_CHARS] + f"\n...[truncated {len(s) - TOOL_RESULT_CHARS} chars — "
            "narrow the request with query filters/limit, or fetch a single item]")


# -------------------------------------------------------------------- llm --
class ToolModeChanged(Exception):
    """The server has no native tool calling; the caller must rebuild the prompt."""


class LLM:
    def __init__(self) -> None:
        # None = unknown; True = server does native tool calling; False = text protocol
        self.native_tools: bool | None = None if env("LLM_TOOL_MODE", "auto") == "auto" \
            else env("LLM_TOOL_MODE") == "native"

    def chat(self, messages: list[dict]) -> dict:
        payload = {"model": LLM_MODEL, "messages": messages,
                   "temperature": LLM_TEMPERATURE, "max_tokens": LLM_MAX_TOKENS}
        if LLM_THINKING in ("on", "off"):
            payload["chat_template_kwargs"] = {"enable_thinking": LLM_THINKING == "on"}
        if self.native_tools is not False:
            payload["tools"] = TOOLS
            payload["tool_choice"] = "auto"
        try:
            msg = self._post(payload)
            if self.native_tools is None:
                self.native_tools = True
            return msg
        except HttpError as e:
            if self.native_tools is None and e.status == 400 and "tool" in e.body.lower():
                # vLLM started without --enable-auto-tool-choice: switch to the text protocol.
                self.native_tools = False
                raise ToolModeChanged() from e
            raise

    def _post(self, payload: dict) -> dict:
        st, _, raw = http("POST", LLM_BASE_URL + "/chat/completions",
                          headers={"Content-Type": "application/json",
                                   "Authorization": f"Bearer {LLM_API_KEY}"},
                          data=json.dumps(payload).encode(), timeout=600)
        if st != 200:
            raise HttpError(st, raw.decode("utf-8", "replace"))
        return json.loads(raw)["choices"][0]["message"]


THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOLCALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def parse_text_tool_calls(content: str) -> list[dict]:
    """Qwen-style <tool_call>{...}</tool_call> blocks inside plain content."""
    calls = []
    for m in TOOLCALL_RE.finditer(content or ""):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        name = obj.get("name")
        if name in TOOL_NAMES:
            calls.append({"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                          "function": {"name": name,
                                       "arguments": json.dumps(obj.get("arguments", {}))}})
    return calls


TEXT_PROTOCOL = """
# Tools
You call tools by writing, on their own lines, one or more blocks exactly like:
<tool_call>
{"name": "<tool name>", "arguments": {...}}
</tool_call>
Then stop and wait: the results come back in a message starting with "TOOL RESULTS".
When you are done, answer normally with no <tool_call> block.
Available tools (JSON schema):
""" + json.dumps([t["function"] for t in TOOLS], indent=1)


def system_prompt(platform: Platform, native: bool) -> str:
    p = f"""You are the Solver Platform agent. You operate the user's optimization platform
(an "optimization as a service" product: domains, entity types, attributes, entities, relationships,
parameters, problems, model versions (Problem IR), scenarios, runs/solutions, maps/GIS, imports,
users/IAM, settings, ops) entirely through its HTTP API at {SOLVER_URL}, as the signed-in user.

Endpoint groups available (tag (count)): {platform.tag_overview()}

How to work:
1. Find the endpoint with search_endpoints, read it with describe_endpoint, then call_api.
   Never guess a request body — describe the endpoint first.
2. Prefer reading before writing: look up ids (domain, entity type, problem, scenario...) with GET calls.
3. Before writing a model/IR, read docs/contracts/problem-ir.md with read_doc.
4. Solving is asynchronous: POST /api/v1/scenarios/{{id}}/runs queues a run; poll the run with
   GET (use the wait tool between polls) until it finishes, then read solution / constraint results.
5. If a call fails (4xx), read the error detail, fix the request and retry. 422 names the bad field.
6. Do what the user asked fully, then reply with a short, clear summary of what you did and the
   key results (ids, numbers). Use tables for lists. Do not invent data you did not get from the API.
7. Destructive actions (DELETE, bulk removal, revoking keys, user changes) only when the user clearly asked.
Today is {time.strftime('%Y-%m-%d')}."""
    if not native:
        p += "\n" + TEXT_PROTOCOL
    return p


# ------------------------------------------------------------------ agent --
class Agent:
    def __init__(self, confirm_fn=None, event_fn=None) -> None:
        self.platform = Platform()
        self.llm = LLM()
        self.messages: list[dict] = []
        self.confirm_fn = confirm_fn or (lambda desc: True)
        self.event_fn = event_fn or (lambda kind, data: None)
        self.lock = threading.Lock()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOG_DIR / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    def connect(self) -> None:
        self.platform.load_spec()
        self.platform.login()

    def reset(self) -> None:
        self.messages = []

    def _log(self, rec: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _needs_confirm(self, method: str) -> bool:
        m = method.upper()
        return (CONFIRM == "write" and m != "GET") or (CONFIRM == "delete" and m == "DELETE")

    def run_tool(self, name: str, args: dict) -> str:
        try:
            if name == "search_endpoints":
                return clip(self.platform.search(args.get("query", ""), args.get("method")))
            if name == "describe_endpoint":
                return clip(self.platform.describe(args["method"], args["path"]))
            if name == "describe_schema":
                return clip(self.platform.schema(args["name"]))
            if name == "read_doc":
                return read_doc(args["path"], int(args.get("offset") or 0))
            if name == "wait":
                time.sleep(max(1, min(60, int(args.get("seconds", 3)))))
                return "ok"
            if name == "call_api":
                method, path = args["method"].upper(), args["path"]
                if self._needs_confirm(method):
                    desc = f"{method} {path}"
                    if args.get("body") is not None:
                        desc += "\n" + json.dumps(args["body"], ensure_ascii=False)[:600]
                    if not self.confirm_fn(desc):
                        return "The user declined this call. Do not retry it; ask what they want instead."
                res = self.platform.call(method, path, args.get("query"), args.get("body"),
                                         args.get("form"), args.get("files"), args.get("headers"))
                return clip(res)
            return f"unknown tool {name}"
        except Exception as e:  # report to the model so it can recover
            return f"tool error: {type(e).__name__}: {e}"

    def _fit_context(self) -> list[dict]:
        """Keep the request under the model's context: drop old turns, shrink old tool results."""
        # JSON tokenizes densely (~2.5 chars/token); reserve room for tool schemas + reply.
        budget = int((LLM_CONTEXT - LLM_MAX_TOKENS - 2500) * 2.5)
        msgs = [dict(m) for m in self.messages]
        size = lambda: sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)
        # 1) shrink old tool results first
        for m in msgs[1:-6]:
            if size() <= budget:
                break
            if m.get("role") == "tool" or (m.get("role") == "user" and
                                          str(m.get("content", "")).startswith("TOOL RESULTS")):
                if len(m["content"]) > 400:
                    m["content"] = m["content"][:400] + "...[older result shortened]"
        # 2) then drop whole old turns (keep system + current turn)
        while size() > budget and len(msgs) > 3:
            # drop from index 1 up to the next user message (a whole exchange)
            j = 2
            while j < len(msgs) and not (msgs[j]["role"] == "user" and
                                         not str(msgs[j].get("content", "")).startswith("TOOL RESULTS")):
                j += 1
            if j >= len(msgs) - 1:
                break
            del msgs[1:j]
        return msgs

    def ask(self, user_text: str) -> str:
        with self.lock:
            return self._ask(user_text)

    def _ask(self, user_text: str) -> str:
        sys_msg = {"role": "system", "content": system_prompt(self.platform, self.llm.native_tools is not False)}
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = sys_msg
        else:
            self.messages.insert(0, sys_msg)
        self.messages.append({"role": "user", "content": user_text})
        self._log({"role": "user", "content": user_text})

        for step in range(MAX_STEPS):
            try:
                msg = self.llm.chat(self._fit_context())
            except ToolModeChanged:
                self.messages[0] = {"role": "system", "content": system_prompt(self.platform, False)}
                msg = self.llm.chat(self._fit_context())

            content = THINK_RE.sub("", msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []
            if not calls:
                calls = parse_text_tool_calls(content)
                if calls:
                    content = TOOLCALL_RE.sub("", content).strip()

            if not calls:
                self.messages.append({"role": "assistant", "content": content})
                self._log({"role": "assistant", "content": content})
                return content

            if content:
                self.event_fn("thought", content)

            native = self.llm.native_tools is not False and bool(msg.get("tool_calls"))
            if native:
                self.messages.append({"role": "assistant", "content": content or None,
                                      "tool_calls": [{"id": c.get("id") or "call_" + uuid.uuid4().hex[:8],
                                                      "type": "function", "function": c["function"]}
                                                     for c in calls]})
                calls = self.messages[-1]["tool_calls"]
            else:
                raw = msg.get("content") or ""
                self.messages.append({"role": "assistant", "content": THINK_RE.sub("", raw).strip()})

            results = []
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except ValueError:
                    args = {}
                    result = "tool error: arguments were not valid JSON; resend the call."
                else:
                    self.event_fn("tool", {"name": name, "args": args})
                    result = self.run_tool(name, args)
                self.event_fn("result", {"name": name, "result": result[:600]})
                self._log({"role": "tool", "name": name, "args": args, "result": result[:4000]})
                if native:
                    self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
                else:
                    results.append(f"[{name}] {json.dumps(args, ensure_ascii=False)}\n{result}")
            if not native:
                self.messages.append({"role": "user", "content": "TOOL RESULTS\n\n" + "\n\n".join(results)})

        note = f"(Stopped after {MAX_STEPS} steps. Say 'continue' to let me keep going.)"
        self.messages.append({"role": "assistant", "content": note})
        return note


# -------------------------------------------------------------------- cli --
C = {"dim": "\033[2m", "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
     "red": "\033[31m", "bold": "\033[1m", "end": "\033[0m"}
if os.name == "nt":
    os.system("")  # enable ANSI colours in Windows consoles


def cli_events(kind, data):
    if kind == "tool":
        a = data["args"]
        if data["name"] == "call_api":
            s = f"{a.get('method')} {a.get('path')}"
            if a.get("query"):
                s += " " + json.dumps(a["query"])
        else:
            s = json.dumps(a, ensure_ascii=False)
        print(f"{C['cyan']}  → {data['name']}: {s[:200]}{C['end']}")
    elif kind == "result":
        r = data["result"].replace("\n", " ")
        print(f"{C['dim']}    {r[:160]}{C['end']}")
    elif kind == "thought":
        print(f"{C['dim']}  … {data[:300]}{C['end']}")


def cli_confirm(desc: str) -> bool:
    print(f"{C['yellow']}  ⚠ The agent wants to run:\n    {desc.replace(chr(10), chr(10) + '    ')}{C['end']}")
    return input("    Allow? [y/N] ").strip().lower() in ("y", "yes")


def run_cli(first: str | None, auto_yes: bool) -> None:
    agent = Agent(confirm_fn=(lambda d: True) if auto_yes else cli_confirm, event_fn=cli_events)
    print(f"{C['bold']}Solver agent{C['end']}  model={LLM_MODEL} @ {LLM_BASE_URL}  platform={SOLVER_URL}")
    try:
        agent.connect()
    except Exception as e:
        print(f"{C['red']}Could not connect to the platform: {e}{C['end']}")
        sys.exit(1)
    print(f"{C['dim']}{len(agent.platform.ops)} endpoints loaded. Commands: /reset  /exit{C['end']}\n")
    pending = first
    while True:
        if pending is None:
            try:
                pending = input(f"{C['green']}you ›{C['end']} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
        text, pending = pending, None
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return
        if text == "/reset":
            agent.reset()
            print("(conversation cleared)")
            continue
        try:
            answer = agent.ask(text)
        except KeyboardInterrupt:
            print("(interrupted)")
            continue
        except Exception as e:
            print(f"{C['red']}error: {e}{C['end']}")
            continue
        print(f"\n{C['bold']}agent ›{C['end']} {answer}\n")
        if first is not None and not sys.stdin.isatty():
            return


# -------------------------------------------------------------------- web --
WEB_PAGE = (HERE / "web.html")


class WebState:
    def __init__(self, auto_yes: bool):
        self.events: list[dict] = []
        self.cv = threading.Condition()
        self.pending_confirm: dict | None = None
        self.busy = False
        self.agent = Agent(confirm_fn=(lambda d: True) if auto_yes else self.confirm, event_fn=self.emit)

    def emit(self, kind, data):
        with self.cv:
            self.events.append({"i": len(self.events), "kind": kind, "data": data})
            self.cv.notify_all()

    def confirm(self, desc: str) -> bool:
        box = {"id": uuid.uuid4().hex[:8], "desc": desc, "answer": None}
        with self.cv:
            self.pending_confirm = box
        self.emit("confirm", {"id": box["id"], "desc": desc})
        deadline = time.time() + 600
        with self.cv:
            while box["answer"] is None and time.time() < deadline:
                self.cv.wait(1)
            self.pending_confirm = None
        return bool(box["answer"])

    def ask(self, text: str):
        def work():
            self.busy = True
            try:
                ans = self.agent.ask(text)
                self.emit("answer", ans)
            except Exception as e:
                self.emit("error", f"{type(e).__name__}: {e}")
                traceback.print_exc()
            finally:
                self.busy = False
                self.emit("idle", None)
        threading.Thread(target=work, daemon=True).start()


def run_web(auto_yes: bool) -> None:
    state = WebState(auto_yes)
    state.agent.connect()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/":
                b = WEB_PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/events":
                since = int(urllib.parse.parse_qs(u.query).get("since", ["0"])[0])
                with state.cv:
                    if len(state.events) <= since:
                        state.cv.wait(25)
                    ev = state.events[since:]
                self._json({"events": ev, "busy": state.busy})
            elif u.path == "/info":
                self._json({"model": LLM_MODEL, "llm": LLM_BASE_URL, "platform": SOLVER_URL,
                            "endpoints": len(state.agent.platform.ops), "confirm": CONFIRM,
                            "next": len(state.events)})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/ask":
                if state.busy:
                    return self._json({"error": "busy"}, 409)
                state.emit("user", data.get("text", ""))
                state.ask(data.get("text", ""))
                self._json({"ok": True})
            elif self.path == "/confirm":
                with state.cv:
                    box = state.pending_confirm
                    if box and box["id"] == data.get("id"):
                        box["answer"] = bool(data.get("allow"))
                        state.cv.notify_all()
                self._json({"ok": True})
            elif self.path == "/reset":
                state.agent.reset()
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)

    host = env("AGENT_WEB_HOST", "127.0.0.1")
    srv = ThreadingHTTPServer((host, WEB_PORT), H)
    print(f"Solver agent web chat on http://{'localhost' if host == '127.0.0.1' else host}:{WEB_PORT}"
          f"  (model {LLM_MODEL}, platform {SOLVER_URL}, {len(state.agent.platform.ops)} endpoints)")
    srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent that operates the solver platform via its API.")
    ap.add_argument("prompt", nargs="*", help="one-shot instruction (omit for interactive chat)")
    ap.add_argument("--web", action="store_true", help="serve a chat page instead of the terminal")
    ap.add_argument("--yes", action="store_true", help="never ask for confirmation")
    ap.add_argument("--check", action="store_true", help="test LLM + platform connectivity and exit")
    a = ap.parse_args()
    if a.check:
        ok = True
        try:
            st, _, raw = http("GET", LLM_BASE_URL + "/models", timeout=15,
                              headers={"Authorization": f"Bearer {LLM_API_KEY}"})
            print(f"LLM  {LLM_BASE_URL}: {st} {[m['id'] for m in json.loads(raw)['data']]}")
            llm = LLM()
            probe = [{"role": "user", "content": "Reply with the word READY."}]
            try:
                reply = llm.chat(probe)
            except ToolModeChanged:
                reply = llm.chat(probe)
            print(f"LLM  tool mode: {'native' if llm.native_tools is not False else 'text'}; reply: "
                  f"{THINK_RE.sub('', reply.get('content') or '').strip()[:80]!r}")
        except Exception as e:
            ok = False
            print(f"LLM  FAILED: {e}")
        try:
            p = Platform()
            p.load_spec()
            p.login()
            print(f"Platform {SOLVER_URL}: {len(p.ops)} endpoints, signed in OK")
        except Exception as e:
            ok = False
            print(f"Platform FAILED: {e}")
        sys.exit(0 if ok else 1)
    if a.web:
        run_web(a.yes)
    else:
        run_cli(" ".join(a.prompt) if a.prompt else None, a.yes)


if __name__ == "__main__":
    main()
