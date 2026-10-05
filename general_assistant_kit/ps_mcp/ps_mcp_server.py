#!/usr/bin/env python3
"""Problem Solver MCP server: every platform REST API as MCP tools. Python 3.9+ standard library only.

Tools come from the platform's own OpenAPI document (one tool per operation, generated at start-up),
so new endpoints appear without code changes. Two generic tools are always present:
    ps_list_endpoints   what the platform offers (from OpenAPI, or the bundled catalog)
    ps_request          call any endpoint by method + path (the fallback that covers "all APIs")
Optional assistant tools (--assistant-tools): describe_workspace, validate_ir, run_python.
Resources: the IR reference. Prompts: the solving method.

Transports:  stdio (default)                 python ps_mcp_server.py
             Streamable HTTP at /mcp         python ps_mcp_server.py --http --port 8765

Safety: --mode read (GET + validators/checks only), write (no deletes), all. Default: write.
Config (env or flags): PS_API (platform base URL), PS_TOKEN (API key), PS_OPENAPI_URL, PS_MCP_MODE,
PS_MCP_HTTP_TOKEN (bearer clients must send to the HTTP transport), PS_MCP_ALLOWED_ORIGINS.
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SERVER_INFO = {"name": "problem-solver-mcp", "version": "1.0.0"}
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
METHODS = ("get", "post", "put", "patch", "delete")
READ_SAFE_POST = re.compile(r"/(validate|check|checks|preflight|classify|readiness|candidates|propose|preview|"
                            r"conformance|compare|why-not|eta)(/|$)")
MAX_TEXT = 60000


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- platform HTTP client
class Platform:
    def __init__(self, base, token=None, timeout=120):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def request(self, method, path, query=None, body=None, files=None, auth=True):
        url = self.base + path
        if query:
            q = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in query.items() if v is not None}
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q, doseq=True)
        headers = {"Accept": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if files:
            boundary = uuid.uuid4().hex
            parts = []
            for k, v in (body or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for field, p in files.items():
                with open(p, "rb") as f:
                    content = f.read()
                ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                             f'filename="{os.path.basename(p)}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
            data = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read()
        except urllib.error.URLError as e:
            return 0, "text/plain", f"cannot reach the platform at {self.base}: {e.reason}".encode()


def _decode(ctype, raw):
    if "json" in (ctype or ""):
        try:
            return json.loads(raw or b"null")
        except ValueError:
            pass
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    if "ndjson" in (ctype or "") or "event-stream" in (ctype or ""):
        return {"stream": text[-MAX_TEXT:]}
    if ctype and not ctype.startswith(("text/", "application/xml")) and "json" not in ctype:
        return {"binary": True, "content_type": ctype, "bytes": len(raw)}
    return text


# ----------------------------------------------------------------------------- OpenAPI -> tools
def _resolve(schema, spec, depth=0, seen=()):
    if not isinstance(schema, dict) or depth > 8:
        return schema if isinstance(schema, dict) else {}
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            return {"type": "object", "description": f"recursive {ref.split('/')[-1]}"}
        node = spec
        for part in ref.lstrip("#/").split("/"):
            node = node.get(part, {})
        return _resolve(node, spec, depth + 1, seen + (ref,))
    out = {}
    for k, v in schema.items():
        if k in ("properties", "patternProperties") and isinstance(v, dict):
            out[k] = {pk: _resolve(pv, spec, depth + 1, seen) for pk, pv in v.items()}
        elif k in ("items", "additionalProperties", "not") and isinstance(v, dict):
            out[k] = _resolve(v, spec, depth + 1, seen)
        elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
            out[k] = [_resolve(x, spec, depth + 1, seen) for x in v]
        elif k not in ("example", "examples", "xml", "externalDocs", "discriminator"):
            out[k] = v
    return out


def _tool_name(op, method, path, used):
    raw = op.get("operationId") or f"{method}_{path}"
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    name = re.sub(r"_api_v1_|^api_v1_|_api_", "_", name).strip("_")[:60] or f"{method}_op"
    base, k = name, 2
    while name in used:
        name = f"{base[:57]}_{k}"; k += 1
    used.add(name)
    return name


def allowed(mode, method, path):
    m = method.lower()
    if mode == "all":
        return True
    if mode == "write":
        return m != "delete" and not re.search(r"/delete(/|$)", path)
    return m == "get" or (m == "post" and bool(READ_SAFE_POST.search(path)))   # read


def tools_from_openapi(spec, mode):
    tools, used = {}, set()
    for path, item in (spec.get("paths") or {}).items():
        common = item.get("parameters", [])
        for method in METHODS:
            op = item.get(method)
            if not op or not allowed(mode, method, path):
                continue
            props, required, where = {}, [], {}
            for p in common + op.get("parameters", []):
                p = _resolve(p, spec)
                if p.get("in") not in ("path", "query", "header") or p.get("in") == "header":
                    continue
                s = _resolve(p.get("schema", {}), spec)
                if p.get("description"):
                    s = dict(s, description=p["description"])
                props[p["name"]] = s
                where[p["name"]] = p["in"]
                if p.get("required") or p.get("in") == "path":
                    required.append(p["name"])
            multipart = None
            rb = _resolve(op.get("requestBody", {}), spec)
            content = rb.get("content", {})
            if "application/json" in content:
                props["body"] = _resolve(content["application/json"].get("schema", {}), spec)
                props["body"].setdefault("description", "JSON request body")
                if rb.get("required"):
                    required.append("body")
            elif "multipart/form-data" in content or "application/x-www-form-urlencoded" in content:
                ms = _resolve((content.get("multipart/form-data") or content.get("application/x-www-form-urlencoded"))
                              .get("schema", {}), spec)
                multipart = []
                for fname, fs in (ms.get("properties") or {}).items():
                    is_file = fs.get("format") == "binary" or fs.get("contentMediaType") or \
                        (fs.get("type") == "array" and (fs.get("items") or {}).get("format") == "binary")
                    props[fname] = ({"type": "string", "description": "path of a file on the MCP server to upload"}
                                    if is_file else fs)
                    where[fname] = "file" if is_file else "form"
                    multipart.append(fname)
                required += [r for r in ms.get("required", []) if r in props]
            name = _tool_name(op, method, path, used)
            summary = (op.get("summary") or "").strip()
            desc = (op.get("description") or "").strip()
            text = f"{method.upper()} {path}" + (f" - {summary}" if summary else "") + (f"\n{desc[:900]}" if desc else "")
            tools[name] = {
                "def": {"name": name, "description": text,
                        "inputSchema": {"type": "object", "properties": props, "required": sorted(set(required))},
                        "annotations": {"title": summary or f"{method.upper()} {path}",
                                        "readOnlyHint": method == "get",
                                        "destructiveHint": method == "delete" or "/delete" in path,
                                        "idempotentHint": method in ("get", "put", "delete"),
                                        "openWorldHint": False}},
                "method": method, "path": path, "where": where, "multipart": multipart}
    return tools


def load_catalog():
    p = os.path.join(HERE, "endpoints_catalog.txt")
    if not os.path.exists(p):
        return []
    return [x.replace("~/", "/api/v1/") for x in open(p).read().split()]


# ----------------------------------------------------------------------------- MCP server
class Server:
    def __init__(self, platform, mode="write", openapi_url=None, assistant_tools=False):
        self.platform, self.mode = platform, mode
        self.spec, self.tools, self.source = None, {}, "catalog"
        self._load_openapi(openapi_url)
        self.extra = {}
        if assistant_tools:
            self._load_assistant_tools()

    def _load_openapi(self, url):
        cands = [url] if url else []
        cands += [self.platform.base + p for p in ("/openapi.json", "/api/openapi.json", "/api/v1/openapi.json")]
        for u in cands:
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"Accept": "application/json"}), timeout=20) as r:
                    spec = json.loads(r.read())
                if isinstance(spec, dict) and spec.get("paths"):
                    self.spec, self.source = spec, u
                    self.tools = tools_from_openapi(spec, self.mode)
                    log(f"[ps-mcp] {len(self.tools)} tools from {u} (mode={self.mode})")
                    return
            except Exception as e:  # noqa: BLE001
                log(f"[ps-mcp] no OpenAPI at {u}: {e}")
        log("[ps-mcp] OpenAPI not found: serving ps_request + ps_list_endpoints over the bundled catalog")

    def _load_assistant_tools(self):
        sys.path.insert(0, KIT)
        try:
            import platform_tools as PT
            import sandbox as SB
        except ImportError as e:
            log(f"[ps-mcp] assistant tools not available: {e}")
            return
        tok = self.platform.token
        self.extra = {
            "describe_workspace": ({"name": "describe_workspace",
                                    "description": PT.SCHEMAS[0]["function"]["description"] + " Pass domain_id.",
                                    "inputSchema": {"type": "object", "properties": {"domain_id": {"type": "integer"}},
                                                    "required": ["domain_id"]},
                                    "annotations": {"readOnlyHint": True}},
                                   lambda a: PT.describe_workspace(a["domain_id"], tok)),
            "validate_ir": ({"name": "validate_ir", "description": PT.SCHEMAS[1]["function"]["description"],
                             "inputSchema": PT.SCHEMAS[1]["function"]["parameters"], "annotations": {"readOnlyHint": True}},
                            lambda a: PT.validate_ir(a["problem_id"], a["ir"], tok)),
            "run_python": ({"name": "run_python", "description": SB.SCHEMA["function"]["description"] +
                            " Pass session to keep one working folder per conversation.",
                            "inputSchema": {"type": "object", "properties": dict(
                                SB.SCHEMA["function"]["parameters"]["properties"], session={"type": "string"}),
                                "required": ["code"]}},
                           lambda a: SB.run_python(a["code"], SB.new_workdir(a.get("session", "default")),
                                                   timeout_s=min(int(a.get("timeout_s", 120)), 900))),
        }
        os.environ.setdefault("PS_API", self.platform.base)

    # --- generic tools
    def _generic_defs(self):
        return [
            {"name": "ps_list_endpoints",
             "description": "List the platform's API endpoints (method, path, summary). Filter by a word, e.g. 'runs'.",
             "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}}},
             "annotations": {"readOnlyHint": True}},
            {"name": "ps_request",
             "description": "Call any platform endpoint. path starts with /api/... ; query and body are JSON objects; "
                            "file_field + file_path upload a local file as multipart. Mode '" + self.mode + "' applies.",
             "inputSchema": {"type": "object", "properties": {
                 "method": {"type": "string", "enum": [m.upper() for m in METHODS]},
                 "path": {"type": "string"}, "query": {"type": "object"}, "body": {},
                 "file_field": {"type": "string"}, "file_path": {"type": "string"}},
                 "required": ["method", "path"]},
             "annotations": {"readOnlyHint": self.mode == "read", "destructiveHint": self.mode == "all"}},
        ]

    def list_tools(self):
        return [t["def"] for t in self.tools.values()] + self._generic_defs() + [d for d, _ in self.extra.values()]

    def call_tool(self, name, args):
        args = args or {}
        if name in self.extra:
            return self.extra[name][1](args)
        if name == "ps_list_endpoints":
            f = (args.get("filter") or "").lower()
            if self.spec:
                rows = [f"{m.upper()} {p}  {(o.get('summary') or '')}".strip()
                        for p, it in self.spec["paths"].items() for m, o in it.items() if m in METHODS]
            else:
                rows = load_catalog()
            return {"source": self.source, "endpoints": [r for r in rows if f in r.lower()]}
        if name == "ps_request":
            method, path = args["method"].upper(), args["path"]
            if not path.startswith("/"):
                path = "/" + path
            if not allowed(self.mode, method, path):
                return {"error": f"{method} {path} is not allowed in mode '{self.mode}'"}
            files = {args["file_field"]: args["file_path"]} if args.get("file_field") and args.get("file_path") else None
            body = args.get("body")
            st, ct, raw = self.platform.request(method, path, args.get("query"), body if not files else (body or {}), files)
            return {"status": st, "data": _decode(ct, raw)}
        t = self.tools.get(name)
        if not t:
            raise KeyError(f"unknown tool {name}")
        path, query, form, files = t["path"], {}, {}, {}
        for k, v in args.items():
            w = t["where"].get(k)
            if w == "path":
                path = path.replace("{" + k + "}", urllib.parse.quote(str(v), safe=""))
            elif w == "query":
                query[k] = v
            elif w == "file":
                files[k] = v
            elif w == "form":
                form[k] = v
        missing = re.findall(r"\{([^}]+)\}", path)
        if missing:
            return {"error": f"missing path parameter(s): {', '.join(missing)}"}
        body = args.get("body") if not t["multipart"] else form
        st, ct, raw = self.platform.request(t["method"], path, query, body, files or None)
        return {"status": st, "data": _decode(ct, raw)}

    # --- JSON-RPC
    def handle(self, msg):
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:          # notification
            return None

        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def err(code, text):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}
        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                           "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {}},
                           "serverInfo": SERVER_INFO,
                           "instructions": "Problem Solver platform APIs. Look first (ps_list_endpoints, GET tools), "
                                           "validate models before publishing, never delete without the user's yes."})
            if method == "ping":
                return ok({})
            if method == "tools/list":
                return ok({"tools": self.list_tools()})
            if method == "tools/call":
                try:
                    res = self.call_tool(params.get("name"), params.get("arguments"))
                except KeyError as e:
                    return err(-32602, str(e))
                except Exception as e:  # noqa: BLE001
                    res = {"error": f"{type(e).__name__}: {e}"}
                is_err = isinstance(res, dict) and (bool(res.get("error")) or (isinstance(res.get("status"), int)
                                                                               and (res["status"] >= 400 or res["status"] == 0)))
                text = json.dumps(res, ensure_ascii=False, default=str)
                out = {"content": [{"type": "text", "text": text[:MAX_TEXT] + ("...[cut]" if len(text) > MAX_TEXT else "")}],
                       "isError": is_err}
                if isinstance(res, dict) and len(text) <= MAX_TEXT:
                    out["structuredContent"] = res
                return ok(out)
            if method == "resources/list":
                return ok({"resources": [{"uri": "ps://ir-reference", "name": "IR reference", "mimeType": "text/markdown",
                                          "description": "The platform's modelling vocabulary and general patterns"}]})
            if method == "resources/read":
                if params.get("uri") != "ps://ir-reference":
                    return err(-32602, "unknown resource")
                p = os.path.join(KIT, "IR_REFERENCE.md")
                text = open(p).read() if os.path.exists(p) else "IR_REFERENCE.md not found next to the server"
                return ok({"contents": [{"uri": "ps://ir-reference", "mimeType": "text/markdown", "text": text}]})
            if method == "prompts/list":
                return ok({"prompts": [{"name": "solve_problem", "description": "Method for turning a plain-language "
                                        "problem into platform data, rules and goals, then solving it",
                                        "arguments": [{"name": "problem", "required": True}]}]})
            if method == "prompts/get":
                p = os.path.join(KIT, "SYSTEM_PROMPT.md")
                method_text = open(p).read() if os.path.exists(p) else ""
                return ok({"messages": [{"role": "user", "content": {"type": "text", "text":
                           method_text + "\n\nProblem:\n" + (params.get("arguments") or {}).get("problem", "")}}]})
            return err(-32601, f"method not found: {method}")
        except Exception as e:  # noqa: BLE001
            return err(-32603, f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------------- transports
def serve_stdio(server):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        msgs = msg if isinstance(msg, list) else [msg]
        out = [r for r in (server.handle(m) for m in msgs) if r is not None]
        if out:
            sys.stdout.write(json.dumps(out if isinstance(msg, list) else out[0]) + "\n")
            sys.stdout.flush()


def serve_http(server, host, port, token=None, origins=None):
    sessions = set()
    lock = threading.Lock()
    origins = set(origins or [])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _deny(self, code, text):
            self.send_response(code); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(text.encode())

        def _guard(self):
            if self.path.split("?")[0] != "/mcp":
                self._deny(404, "not found"); return False
            o = self.headers.get("Origin")
            if o and not (o in origins or re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", o)):
                self._deny(403, "origin not allowed"); return False
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                self._deny(401, "unauthorized"); return False
            return True

        def do_POST(self):
            if not self._guard():
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                msg = json.loads(raw)
            except ValueError:
                return self._deny(400, "parse error")
            msgs = msg if isinstance(msg, list) else [msg]
            sid = self.headers.get("Mcp-Session-Id")
            is_init = any(m.get("method") == "initialize" for m in msgs)
            if not is_init and sid and sid not in sessions:
                return self._deny(404, "unknown session")
            out = [r for r in (server.handle(m) for m in msgs) if r is not None]
            if not out:
                self.send_response(202); self.end_headers(); return
            body = json.dumps(out if isinstance(msg, list) else out[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if is_init:
                sid = uuid.uuid4().hex
                with lock:
                    sessions.add(sid)
                self.send_header("Mcp-Session-Id", sid)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self._guard():
                self.send_response(405); self.send_header("Allow", "POST, DELETE"); self.end_headers()

        def do_DELETE(self):
            if self._guard():
                with lock:
                    sessions.discard(self.headers.get("Mcp-Session-Id"))
                self.send_response(200); self.end_headers()

    httpd = ThreadingHTTPServer((host, port), H)
    log(f"[ps-mcp] Streamable HTTP on http://{host}:{port}/mcp")
    httpd.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("PS_API", "http://localhost:3010"))
    ap.add_argument("--token", default=os.environ.get("PS_TOKEN"))
    ap.add_argument("--openapi", default=os.environ.get("PS_OPENAPI_URL"))
    ap.add_argument("--mode", default=os.environ.get("PS_MCP_MODE", "write"), choices=["read", "write", "all"])
    ap.add_argument("--assistant-tools", action="store_true")
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    server = Server(Platform(a.api, a.token), a.mode, a.openapi, a.assistant_tools)
    if a.http:
        origins = [o for o in os.environ.get("PS_MCP_ALLOWED_ORIGINS", "").split(",") if o]
        serve_http(server, a.host, a.port, os.environ.get("PS_MCP_HTTP_TOKEN"), origins)
    else:
        serve_stdio(server)


if __name__ == "__main__":
    main()
