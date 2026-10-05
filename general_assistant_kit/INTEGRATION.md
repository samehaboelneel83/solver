# General Assistant upgrade for Problem Solver (offline, problem-agnostic)

The flow stays your platform's own:

1. Data goes into Map data and records, relationships and data values.
2. The Assistant turns the user's words into rules and goals.
3. Your solvers solve it.

This kit makes the Assistant's part work. It contains no problem-specific code or data.

| File | What it does |
| --- | --- |
| `toolcall.py` | Runs tool calls the model printed as text, refuses duplicate-key or broken JSON, and flags unrun calls |
| `agent_loop.py` | Your chat loop with error feedback. A reply cannot claim "built" or "solved" unless a tool did it. Includes clients for Ollama and OpenAI-compatible servers (stdlib only) |
| `platform_tools.py` | `describe_workspace` (the vocabulary already in the workspace) and `validate_ir` (your validator, `POST /api/v1/problems/{id}/versions/validate`) |
| `sandbox.py` | `run_python`: a locked-down working folder where the model reads data, computes bounds, prepares imports and checks answers |
| `SYSTEM_PROMPT.md` | The working method: look first, ask little, size the problem, formulate in platform terms, validate, propose, check, report |
| `IR_REFERENCE.md` | Your IR vocabulary. Every construct was checked against your validator, plus 8 general modelling patterns |
| `eval/` | Measures the model on your own problems without changing anything in the platform |

## Install (no internet)

The code needs only Python 3.9+. `run_python` uses whatever libraries the server already has; numpy, pandas and OR-Tools are the most useful. Copy the folder to the server.

## Wire it in

1. **Prompt.** Use `SYSTEM_PROMPT.md` followed by `IR_REFERENCE.md` as the Assistant's system prompt, then your own tool notes.
2. **Tools.** Add `platform_tools.SCHEMAS` and `sandbox.SCHEMA` to the tools you already send, such as `place_file`, `read_file` and `propose_plan`. Route each call to its function, with one `run_python` work folder per conversation (`sandbox.new_workdir(id)`).
3. **Loop.** Replace the call-and-execute loop behind `/api/v1/agent/chat` with `agent_loop.run_turn(messages, call_model, execute, tools)`.
4. **Model server.** Set the reply length to 8192 tokens or more: Ollama `num_predict`, or `max_tokens`. With vLLM, enable tool parsing: `--enable-auto-tool-choice --tool-call-parser hermes`.
5. **Model output.** Let `propose_plan` accept the model's IR, and run `validate_ir` on it before showing the Approve button.

## Measure

```
PS_API=http://localhost:3010 PS_TOKEN=<api key> python eval/run_eval.py --model qwen3.5 --ollama http://localhost:11434
```

Add one case per problem type to `eval/cases.json`: a plain-language brief, plus the workspace whose data is already loaded. The report shows, per case:

- whether the model produced a valid model
- whether it used the existing data
- whether the goals were in the right order
- how many questions it asked and how many text tool calls it made

Run it after any change of prompt or model.

## Tests

`python tests/test_toolcall.py`, `python tests/test_loop_and_sandbox.py` and `python tests/test_eval_smoke.py` all run offline.

## MCP: every platform API as tools (`ps_mcp/`)

`ps_mcp/ps_mcp_server.py` is an MCP server with no dependencies beyond Python 3.9+, so it installs without internet.

### Where the tools come from

At start-up it reads your backend's OpenAPI document (FastAPI serves `/openapi.json`) and makes one tool per API operation. New endpoints appear on the next restart.

Two generic tools are always present, so no endpoint is out of reach:

- `ps_list_endpoints`
- `ps_request`, which takes a method, path, query, body or a file upload

If the OpenAPI document can't be reached, they work from the bundled catalog of the 134 endpoint paths found in your platform's web app, `endpoints_catalog.txt`.

### What else it serves

- **Resource:** `ps://ir-reference`.
- **Prompt:** `solve_problem`, the working method.
- **`--assistant-tools`:** also adds `describe_workspace`, `validate_ir` and `run_python`.

### Safety

- **`--mode read`:** GET requests plus checks and validators only.
- **`--mode write`:** the default. No deletes.
- **`--mode all`:** everything.

Every tool is marked read-only, destructive or idempotent for the client.

The HTTP transport listens on 127.0.0.1 by default. `PS_MCP_HTTP_TOKEN` makes clients send a bearer token, and browser origins are limited to localhost unless you list them in `PS_MCP_ALLOWED_ORIGINS`.

### Run

```
# stdio, for desktop or CLI MCP clients
PS_API=http://<backend-host>:<port> PS_TOKEN=<api key> python ps_mcp/ps_mcp_server.py --assistant-tools

# Streamable HTTP, for shared agents on the network
PS_API=... PS_TOKEN=... PS_MCP_HTTP_TOKEN=<client secret> python ps_mcp/ps_mcp_server.py --http --host 0.0.0.0 --port 8765 --assistant-tools
```

Point `PS_API` at the backend itself, where `/openapi.json` is served. Through the web front end at `:3010`, only `/api/...` is forwarded, so the server falls back to the catalog.

### MCP client config

```json
{"mcpServers": {"problem-solver": {"command": "python", "args": ["/opt/kit/ps_mcp/ps_mcp_server.py", "--assistant-tools"],
  "env": {"PS_API": "http://backend:8000", "PS_TOKEN": "<api key>", "PS_MCP_MODE": "write"}}}}
```

For HTTP clients, use the URL `http://<host>:8765/mcp` with the header `Authorization: Bearer <client secret>`.

### Inside your own Assistant loop, without an MCP client

```python
from ps_mcp.bridge import load
tools, execute = load(api, token, mode="write", include=r"entit|relationship|parameter|problem|run|scenario|gis")
final, trace = agent_loop.run_turn(messages, call_model, execute, tools)
```

Use `include` to keep the tool list short for a local model. The generic tools stay in either way.

### Test

`python ps_mcp/test_mcp.py` needs the official `mcp` Python SDK on a test machine only. It runs a mock platform and drives the server with the SDK client over stdio in all three modes and over Streamable HTTP.
