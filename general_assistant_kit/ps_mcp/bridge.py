"""Give a non-MCP agent loop (e.g. the platform Assistant) the same tools, in-process.

    from ps_mcp.bridge import load
    tools, execute = load(api="http://localhost:3010", token=KEY, mode="write", include=r"entit|relationship|parameter|problem|run|scenario|gis")
    final, trace = agent_loop.run_turn(messages, call_model, execute, tools)

`include` keeps the tool list short for a local model (a regex on tool name + path); the generic
ps_request / ps_list_endpoints tools are always kept, so nothing is out of reach.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ps_mcp_server import Platform, Server  # noqa: E402


def load(api, token, mode="write", include=None, openapi=None, assistant_tools=True):
    srv = Server(Platform(api, token), mode, openapi, assistant_tools)
    keep = re.compile(include, re.I) if include else None
    tools = []
    for d in srv.list_tools():
        meta = srv.tools.get(d["name"])
        text = d["name"] + " " + (meta["path"] if meta else "")
        if keep and meta and not keep.search(text):
            continue
        tools.append({"type": "function", "function": {"name": d["name"], "description": d["description"][:1000],
                                                       "parameters": d["inputSchema"]}})
    return tools, srv.call_tool
