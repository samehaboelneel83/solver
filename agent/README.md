# Solver Agent

An AI agent that operates the whole solver platform for you, powered by your own
Qwen model on vLLM (`http://10.125.18.189:8000`). It only uses Python's standard
library, so there's nothing to install.

## How it reaches everything

When it starts, it reads the backend's live `/openapi.json`, which lists all 265
operations today (domains, entity types, entities, relationships, parameters,
problems, model versions, scenarios, runs, maps/GIS, imports, suites,
IAM/users, API keys, settings, backups, audit and more). Any endpoint you add
later shows up automatically. For each request the model:

1. **search_endpoints**: finds the right endpoint by keywords
2. **describe_endpoint** / **describe_schema**: reads the exact parameters and body
3. **call_api**: calls it as your signed-in user (JSON, form, file upload, headers)
4. **read_doc**: reads `docs/` and `README.md` (e.g. the Problem IR) before building models
5. **wait**: pauses between polls while a solve run is queued or running

It can only do what your platform user (or API key) is allowed to do.

## Run it

```bat
cd D:\solver\agent
agent.bat --check          :: tests the LLM and the platform login
agent.bat                  :: chat in the terminal
agent-web.bat              :: chat in the browser at http://localhost:8020
agent.bat "list my problems and solve the newest scenario"   :: one-shot
```

Settings are in `agent\.env` (the platform URL, login or `sk_` API key, model,
and which actions need confirmation). By default it asks before any DELETE.
Set `AGENT_CONFIRM=write` to approve every change, or `none` to never ask, or
pass `--yes` for a single run.

Every session is logged to `agent\logs\session-*.jsonl`.

## Tool calling on vLLM

Tool calls work best when vLLM is started with:

    --enable-auto-tool-choice --tool-call-parser qwen3_coder

(or `hermes`, depending on your vLLM version and Qwen template). If those flags
aren't set, the agent detects it and switches to a text protocol based on
`<tool_call>` blocks, so it works either way. `--check` shows which mode it
is using.

## Example requests

- "What domains, problems and scenarios do I have?"
- "Create an entity type Truck with attributes capacity (number, required) and depot (text)."
- "Import samples/map-data/... as a GIS dataset."
- "Solve scenario 12 with a 60s limit, then explain which rules were fighting if it's infeasible."
- "Make an API key called nightly-job that can only read runs."
- "Show the last 20 audit events for user admin."
