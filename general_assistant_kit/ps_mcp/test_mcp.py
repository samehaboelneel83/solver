"""End-to-end test with the official MCP Python SDK as the client (test machine only; the server needs no SDK).

A mock platform serves a FastAPI-style OpenAPI document and a few endpoints; the test checks
generated tools, path/query/body/multipart mapping, modes, generic tools, resources, prompts,
and both transports (stdio and Streamable HTTP).
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "ps_mcp_server.py")

SPEC = {
    "openapi": "3.1.0", "info": {"title": "mock", "version": "1"},
    "paths": {
        "/api/v1/entity-types": {"get": {"operationId": "list_entity_types_api_v1_entity_types_get", "summary": "List kinds of record",
                                         "parameters": [{"name": "domain_id", "in": "query", "required": True, "schema": {"type": "integer"}}]}},
        "/api/v1/problems/{problem_id}/versions/validate": {"post": {
            "operationId": "validate_version_api_v1_problems__problem_id__versions_validate_post", "summary": "Validate a model",
            "parameters": [{"name": "problem_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ValidateIn"}}}}}},
        "/api/v1/entities": {"post": {"operationId": "create_entity", "summary": "Create a record",
                                      "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Entity"}}}}}},
        "/api/v1/entities/{entity_id}": {"delete": {"operationId": "delete_entity", "summary": "Delete a record",
                                                    "parameters": [{"name": "entity_id", "in": "path", "required": True, "schema": {"type": "integer"}}]}},
        "/api/v1/gis/uploads": {"post": {"operationId": "upload_map_file", "summary": "Upload map data",
                                         "requestBody": {"content": {"multipart/form-data": {"schema": {"$ref": "#/components/schemas/Upload"}}}}}},
    },
    "components": {"schemas": {
        "ValidateIn": {"type": "object", "properties": {"ir": {"$ref": "#/components/schemas/IR"}}, "required": ["ir"]},
        "IR": {"type": "object", "properties": {"sets": {"type": "array", "items": {"type": "string"}},
                                                "children": {"type": "array", "items": {"$ref": "#/components/schemas/IR"}}}},
        "Entity": {"type": "object", "properties": {"key": {"type": "string"}, "entity_type_id": {"type": "integer"}}},
        "Upload": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}, "domain_id": {"type": "integer"}},
                   "required": ["file"]}}},
}
SEEN = []


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        SEEN.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == "/openapi.json":
            return self._send(200, SPEC)
        if self.path.startswith("/api/v1/entity-types"):
            return self._send(200, {"items": [{"id": 1, "name": "order"}], "query": self.path.split("?")[1]})
        self._send(404, {"detail": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        SEEN.append(("POST", self.path, self.headers.get("Content-Type", "")[:19]))
        if self.path.endswith("/versions/validate"):
            body = json.loads(raw)
            return self._send(200, {"ok": bool(body.get("ir", {}).get("sets"))} if body.get("ir", {}).get("sets") else
                              (422, None) and {"ok": False})
        if self.path == "/api/v1/gis/uploads":
            return self._send(200, {"received_bytes": len(raw), "multipart": b"filename=" in raw})
        if self.path == "/api/v1/entities":
            return self._send(201, {"id": 7, **json.loads(raw)})
        self._send(404, {"detail": "not found"})

    def do_DELETE(self):
        SEEN.append(("DELETE", self.path, None))
        self._send(200, {"deleted": True})


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


async def exercise(session, mode):
    init = await session.initialize()
    assert init.server_info.name == "problem-solver-mcp"
    tools = {t.name: t for t in (await session.list_tools()).tools}
    assert "ps_request" in tools and "ps_list_endpoints" in tools
    vt = next(n for n in tools if n.startswith("validate_version"))
    assert tools[vt].input_schema["properties"]["body"]["properties"]["ir"]["properties"]["sets"]["type"] == "array"
    assert "problem_id" in tools[vt].input_schema["required"]
    r = await session.call_tool("list_entity_types_entity_types_get" if "list_entity_types_entity_types_get" in tools
                                else next(n for n in tools if n.startswith("list_entity_types")), {"domain_id": 209})
    d = json.loads(r.content[0].text)
    assert d["status"] == 200 and d["data"]["query"] == "domain_id=209" and not r.is_error
    r = await session.call_tool(vt, {"problem_id": 5, "body": {"ir": {"sets": ["order"]}}})
    assert json.loads(r.content[0].text)["data"]["ok"] is True
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False); f.write(b"key,value\nA,1\n"); f.close()
    up = next((n for n in tools if n.startswith("upload_map_file")), None)
    if mode != "read":
        r = await session.call_tool(up, {"file": f.name, "domain_id": 3})
        dd = json.loads(r.content[0].text)["data"]
        assert dd["multipart"] and dd["received_bytes"] > 10
    else:
        assert up is None, "uploads are writes; read mode must hide them"
    assert ("delete_entity" in tools) == (mode == "all")
    r = await session.call_tool("ps_request", {"method": "DELETE", "path": "/api/v1/entities/9"})
    blocked = "not allowed" in r.content[0].text
    assert blocked == (mode != "all")
    r = await session.call_tool("ps_list_endpoints", {"filter": "entities"})
    assert any("entities" in e for e in json.loads(r.content[0].text)["endpoints"])
    res = await session.list_resources()
    assert res.resources[0].uri.__str__() == "ps://ir-reference"
    txt = (await session.read_resource("ps://ir-reference")).contents[0].text
    assert "Problem Solver modelling vocabulary" in txt
    pr = await session.get_prompt("solve_problem", {"problem": "assign 40 orders"})
    assert "assign 40 orders" in pr.messages[0].content.text
    return len(tools)


async def run_stdio(api, mode):
    params = StdioServerParameters(command=sys.executable, args=[SERVER, "--api", api, "--mode", mode],
                                   env={"PS_TOKEN": "test-token", "PATH": os.environ["PATH"]})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            return await exercise(s, mode)


async def run_http(api):
    port = free_port()
    p = subprocess.Popen([sys.executable, SERVER, "--api", api, "--http", "--port", str(port), "--mode", "write"],
                         env={"PS_TOKEN": "test-token", "PS_MCP_HTTP_TOKEN": "client-secret", "PATH": os.environ["PATH"]},
                         stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        async with create_mcp_http_client(headers={"Authorization": "Bearer client-secret"}) as hc:
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=hc) as streams:
                r, w = streams[0], streams[1]
                async with ClientSession(r, w) as s:
                    return await exercise(s, "write")
    finally:
        p.terminate()


def main():
    port = free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Mock)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{port}"
    for mode in ("read", "write", "all"):
        n = asyncio.run(run_stdio(api, mode))
        print(f"ok stdio mode={mode}: {n} tools")
    n = asyncio.run(run_http(api))
    print(f"ok streamable-http with client bearer: {n} tools")
    assert any(a == "test-token" or (a or "").endswith("test-token") for m, pth, a in SEEN if m == "GET" and pth.startswith("/api/"))
    print("ok platform calls carried the API key")


if __name__ == "__main__":
    main()
