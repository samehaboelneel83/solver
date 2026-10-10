"""The assistant's loop: an OpenAI-compatible LLM (vLLM / Qwen) that drives the
platform through its own HTTP API, as the person who asked.

Why the API and not the database: every rule the platform has -- capabilities,
tenancy, triggers, audit -- is enforced behind its endpoints. Going through
them, the assistant can do exactly what its user can, and nothing more, and
everything it does is audited as that user.

The model reaches "everything" with four tools over the live OpenAPI document:
`search_endpoints` -> `describe_endpoint` (and `describe_schema`) -> `call_api`.
`read_doc` lets it read the repo's docs (the Problem IR) when they are shipped
with the image, and `wait` paces polling of a queued run.

Conversation state is the client's: each request carries the messages so far
and gets the new ones back (a `state` event). Nothing is kept per session on
the server, so a restart or a second replica loses nothing. A call that needs
the person's OK ends the turn with a `confirm` event; the next request carries
`confirm: {allow}` and the pending calls run (or are declined) first.

Two modes:

- `assistant` -- do what is asked, anywhere in the platform.
- `model` -- the person describes a problem in their own words. The assistant
  interviews them until the decisions, goal, rules and data are clear, then
  calls `propose_plan` with a summary and a spec. The server dry-runs the spec
  (`POST /api/v1/problems/from-spec`) and shows the person only a plan that
  builds; on their approval it builds *that* spec, all or nothing, and the
  assistant explains what it built. In this mode the server refuses every
  other write, and refuses a plan before there has been a conversation.

Settings (environment):
    AGENT_ENABLED        1 (default) / 0
    LLM_BASE_URL         http://10.125.18.189:8000/v1
    LLM_MODEL            qwen3.5
    LLM_API_KEY          EMPTY
    LLM_CONTEXT          32768      the model's max_model_len (vLLM's own value is read when it reports one)
    LLM_TIMEOUT          1800       seconds to wait for one model reply (the connection)
    LLM_REPLY_SECONDS    420        the longest one reply may take; past it the step is asked again, shorter
    LLM_WORKING_TOKENS   48000      summarize the older conversation past this many tokens (whichever comes first)
    LLM_COMPACT_AT       0.6        summarize the older conversation past this share of the context
    LLM_MAX_TOKENS       4096       per reply
    LLM_PLAN_MAX_TOKENS  8192       per reply in model mode (a plan carries data)
    LLM_TEMPERATURE      0.2
    LLM_THINKING         on | off | auto (think on new messages, plans and failures) | (blank: the server's default)
    LLM_TOOL_MODE        auto | native | text
    AGENT_CONFIRM        delete (default) | write | none
    AGENT_MAX_STEPS      30
    AGENT_SELF_URL       http://127.0.0.1:8000   where the API answers inside the container
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterator

from app.agent import compact as agent_compact
from app.agent import files as agent_files
from app.agent import readback as agent_readback
from app.agent import repair as agent_repair
from app.agent import sandbox
from app.agent import toolcall


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    enabled: bool = field(default_factory=lambda: _env("AGENT_ENABLED", "1") not in ("0", "false", "no"))
    base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://10.125.18.189:8000/v1").rstrip("/"))
    model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen3.5"))
    api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "EMPTY"))
    context: int = field(default_factory=lambda: int(_env("LLM_CONTEXT", "32768")))
    max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "4096")))
    plan_max_tokens: int = field(default_factory=lambda: int(_env("LLM_PLAN_MAX_TOKENS", "8192")))
    temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    thinking: str = field(default_factory=lambda: _env("LLM_THINKING", "").lower())
    tool_mode: str = field(default_factory=lambda: _env("LLM_TOOL_MODE", "auto").lower())
    confirm: str = field(default_factory=lambda: _env("AGENT_CONFIRM", "delete").lower())
    max_steps: int = field(default_factory=lambda: int(_env("AGENT_MAX_STEPS", "30")))
    self_url: str = field(default_factory=lambda: _env("AGENT_SELF_URL", "http://127.0.0.1:8000").rstrip("/"))
    result_chars: int = 8000
    timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "1800")))
    #: The longest one reply may take (0: only LLM_TIMEOUT). A planning reply of up to 32,768 tokens ran
    #: 10-15 minutes and twice ended a job-shop turn with nothing (evaluation, October 2026).
    reply_seconds: float = field(default_factory=lambda: float(_env("LLM_REPLY_SECONDS", "420")))
    #: Past this share of the context, the older conversation is summarized (app.agent.compact).
    compact_at: float = field(default_factory=lambda: float(_env("LLM_COMPACT_AT", "0.6")))
    #: The most a model call carries before the older conversation is summarized, whatever the context:
    #: every call re-sends the whole history, so a small one keeps each step quick for the server.
    working_tokens: int = field(default_factory=lambda: int(_env("LLM_WORKING_TOKENS", "48000")))


# Learned once per process: does the LLM server do native tool calls?
_NATIVE_TOOLS: dict[str, bool] = {}

# The assistant must not call itself, mint credentials, or sign in as someone else.
BLOCKED_PATHS = (
    re.compile(r"^/api/v1/agent(/|$)"),
    re.compile(r"^/api/auth/"),
    re.compile(r"^/api/v1/sso(/|$)"),
    re.compile(r"^/scim(/|$)"),
)

REPO = Path(__file__).resolve().parents[2]  # /app in the image (backend/)
DOC_ROOTS = [p for p in (REPO / "docs", REPO.parent / "docs") if p.is_dir()]


# --------------------------------------------------------------------- tools --
TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "search_endpoints",
        "description": "Find platform API endpoints by keywords (e.g. 'entity types', 'scenario runs', "
                       "'parameter values', 'api keys'). Returns method, path and summary.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "describe_endpoint",
        "description": "Exact path/query parameters, request body schema and response schema of one "
                       "endpoint. Always use before a POST/PUT/PATCH.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string"}, "path": {"type": "string"}}, "required": ["method", "path"]}}},
    {"type": "function", "function": {
        "name": "describe_schema",
        "description": "Expand a named schema that describe_endpoint shortened.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "call_api",
        "description": "Call a platform endpoint as the signed-in user. Put path parameters into the path "
                       "(e.g. /api/v1/scenarios/42/runs). Returns status and JSON body.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "path": {"type": "string"},
            "query": {"type": "object", "description": "query-string parameters"},
            "body": {"description": "JSON request body"},
            "form": {"type": "object", "description": "form fields, for form endpoints"},
            "headers": {"type": "object", "description": "extra headers, e.g. Idempotency-Key"},
        }, "required": ["method", "path"]}}},
    {"type": "function", "function": {
        "name": "read_doc",
        "description": "Read platform documentation, e.g. 'contracts/problem-ir.md' or 'engine.md'. "
                       "Pass '' to list the documents. Read problem-ir.md before writing a model.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read rows of a file the user attached (listed under ATTACHED FILES), as CSV.",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string"}, "sheet": {"type": "string"},
            "offset": {"type": "integer"}, "limit": {"type": "integer", "maximum": 200}},
            "required": ["file"]}}},
    {"type": "function", "function": {
        "name": "query_file",
        "description": "Count, filter, add up or group the rows of an attached file EXACTLY (never do this "
                       "arithmetic yourself). where: [{column, op, value}] with op = != < <= > >= in notIn contains "
                       "empty notEmpty. Without aggregate: the matching rows (only `columns`, if given) and how many. "
                       "With aggregate {column: sum|min|max|mean|count|distinct} (\"*\": \"count\" counts rows): one "
                       "line per group_by group, or one line in all.",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string"}, "sheet": {"type": "string"},
            "where": {"type": "array", "items": {"type": "object"}},
            "group_by": {"type": "array", "items": {"type": "string"}},
            "aggregate": {"type": "object"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "maximum": 200}},
            "required": ["file"]}}},
    {"type": "function", "function": {
        "name": "place_file",
        "description": "Place an attached map file marked NOT PLACED YET in the coordinate system the user "
                       "confirmed. Afterwards its sheets give lon/lat, area_m2, length_m and each feature's geometry.",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string"}, "epsg": {"type": "integer", "description": "e.g. 22992, 32636, 4326"}},
            "required": ["file", "epsg"]}}},
    {"type": "function", "function": {
        "name": "wait",
        "description": "Pause a few seconds (while a run is queued or running), then poll again.",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "integer", "minimum": 1, "maximum": 30}}, "required": ["seconds"]}}},
    {"type": "function", "function": {
        "name": "inspect_decomposition",
        "description": "Inspect a scenario's compiled decision structure before solving. Reports exact independent blocks "
                       "that the platform can solve in parallel, or near-independent groups and the constraints linking "
                       "them. It is analysis only; it never changes the model or splits linked decisions approximately.",
        "parameters": {"type": "object", "properties": {
            "scenario_id": {"type": "integer", "description": "An existing scenario id from the workspace or build result"}},
            "required": ["scenario_id"]}}},
]
PLAN_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "propose_plan",
    "description": "Show the user the model you will build and ask for approval. Only when nothing "
                   "important is still open. The server checks the spec first and returns errors to fix; "
                   "a valid plan is shown to the user, who approves (then it is built) or asks for changes.",
    "parameters": {"type": "object", "properties": {
        "summary": {"type": "string", "description": "markdown for the user: problem, records and data, "
                    "decisions, rules (words + formula), goal, assumptions"},
        "spec": {"type": "object", "description": "domain_name or domain_id, problem_name, note, seed, ir"},
    }, "required": ["summary", "spec"]}}}
_CALL_API = next(t for t in TOOLS if t["function"]["name"] == "call_api")
MODEL_TOOLS = [t for t in TOOLS if t["function"]["name"] not in ("call_api", "hand_to_describe")] + [
    {"type": "function", "function": {**_CALL_API["function"], "description":
     "Read platform data (GET), or solve a scenario after the build (POST /api/v1/scenarios/{id}/runs). "
     "Nothing else may be written in this mode: changes go through propose_plan."}},
    PLAN_TOOL]
WORKSPACE_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "describe_workspace",
    "description": "What a domain (workspace) already holds: kinds of record with their fields, counts and some keys, "
                   "relationship types, data values (parameters), map data, problems with versions and scenarios. "
                   "Call it first, before asking the user anything; reuse what is there.",
    "parameters": {"type": "object", "properties": {
        "domain_id": {"type": "integer", "description": "omit for the selected domain"}}}}}
CHECK_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "check_spec",
    "description": "Check a spec (the same object propose_plan takes) with the platform's own validators -- data and "
                   "model (IR) -- without building anything or showing the user. Fix every error it reports, then "
                   "propose_plan.",
    "parameters": {"type": "object", "properties": {"spec": {"type": "object"}}, "required": ["spec"]}}}
RESULT_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "read_result",
    "description": "A settled run's answer, ready to report: status and goal, what the goal is made of, every "
                   "decision with its records' names and numbers, per-record totals, and each rule held, tight or "
                   "broken. Call it once the run has finished, and report from it. The person also sees the run's facts "
                   "(status, goal, the first rows of each decision, tight or broken rules) in a card the platform "
                   "draws above your reply: explain them, do not retype them.",
    "parameters": {"type": "object", "properties": {"run_id": {"type": "integer"}}, "required": ["run_id"]}}}
OUTPUT_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "read_output",
    "description": "More of a long tool result. A result over a few thousand characters is shown in the "
                   "conversation as its start and end, with its output number; this reads any part of it.",
    "parameters": {"type": "object", "properties": {
        "output": {"type": "integer", "description": "The output number named in the shortened result"},
        "offset": {"type": "integer", "description": "Characters to skip (default 0)"},
        "find": {"type": "string", "description": "Optional text: start at its first occurrence instead"}},
        "required": ["output"]}}}
LAYOUT_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "make_layout",
    "description": "For any problem of PLACING ITEMS ON A DRAWING (beds in camps, desks in rooms, parking stalls, "
                   "shelves, panels): the platform writes the files and returns the counts, an upper bound and the "
                   "READY plan (seed + model) to give to check_spec. Use it instead of writing geometry code. Sizes "
                   "in metres. By default (form 'place') there is NO list of positions: the placement solver lays "
                   "the items out on the drawing's exact grid itself (any step, however fine: the aisle exactly as "
                   "asked), with access_layers too (every item reachable from a door). Form 'candidates' lists every "
                   "position instead (built by each run from the areas and kinds, so nothing is stored row by row): "
                   "only when the user asks for a candidate list.",
    "parameters": {"type": "object", "properties": {
        "file": {"type": "string", "description": "The attached drawing (optional when there is one)"},
        "area_layers": {"type": "array", "items": {"type": "string"},
                        "description": "Layers whose polygons are where items may go (rooms, camps, plots)"},
        "blocked_layers": {"type": "array", "items": {"type": "string"},
                           "description": "Layers no item may cover (obstacles, closed areas, door fronts)"},
        "label_layer": {"type": "string", "description": "Optional text layer naming each area (C01, Room 3)"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "length": {"type": "number"}, "width": {"type": "number"},
            "rotations": {"type": "array", "items": {"type": "integer"}, "description": "0 and/or 90"},
            "value": {"type": "number", "description": "Worth of one (default 1)"}},
            "required": ["name", "length", "width"]}},
        "aisle": {"type": "number", "description": "Free width each item needs beside it to be reached (m); 0 for none"},
        "aisle_side": {"type": "string", "enum": ["short", "long", "any", "none"],
                       "description": "Which side the aisle is on: short (the foot of a bed), long, any"},
        "step": {"type": "number", "description": "Grid step (m). Leave it OUT unless the user named one: the "
                 "platform picks the coarsest step that is exact for every size"},
        "form": {"type": "string", "enum": ["place", "candidates"],
                 "description": "place (default): no candidate list, the exact grid; candidates: every position "
                                "listed, only when asked"},
        "access_layers": {"type": "array", "items": {"type": "string"},
                          "description": "Layers of the features every item must be reachable from through free "
                                         "cells (doors, exits, gates): give them whenever the user wants access, "
                                         "a way out, or items 'connected to' a door"}},
        "required": ["area_layers", "items"]}}}
WHATIF_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "what_if",
    "description": "Answer a what-if EXACTLY by solving it: copies a scenario with changes (a parameter's value, "
                   "a rule's limit, a field scaled, records removed, a rule switched off), solves the copy, and "
                   "returns its answer next to the base answer and the difference. Use it for ANY 'what if', 'how "
                   "much would we save if', 'what happens when' question -- never estimate a change from shadow "
                   "prices yourself. The base is never changed.",
    "parameters": {"type": "object", "properties": {
        "scenario_id": {"type": "integer", "description": "The scenario to start from (the built Base scenario)"},
        "name": {"type": "string", "description": "Short name, e.g. 'fiber 8%'"},
        "set_param": {"type": "array", "items": {"type": "object", "properties": {
            "param": {"type": "string"}, "index": {"type": "array", "items": {"type": "string"}},
            "value": {"type": "number"}}, "required": ["param", "value"]},
            "description": "Parameter cells to set; index [] for a single-number parameter"},
        "scale_param": {"type": "object", "description": "{parameter: factor}, every cell times factor"},
        "set_limit": {"type": "object", "description": "{rule id: new number for its limit (right side)}"},
        "set_attr": {"type": "array", "items": {"type": "object"},
                     "description": "[{set, key, attr, value}]: one record's field"},
        "scale_attr": {"type": "array", "items": {"type": "object"},
                       "description": "[{set, attr, factor, where?}]: a field of every record times factor"},
        "remove": {"type": "object", "description": "{set: [record keys]} records left out"},
        "disable": {"type": "array", "items": {"type": "string"}, "description": "rule ids switched off"},
        "futures": {"type": "integer", "description": "Plan for this many sampled futures of the numbers declared "
                    "uncertain (e.g. 50) instead of their given values; alone, it re-solves the scenario as is "
                    "for those futures"},
        "front": {"type": "integer", "description": "The trade-off between the goal's terms (two to six) instead "
                  "of one answer: about this many points plus one (2-50, e.g. 10) spread over the front; alone, it "
                  "re-solves the scenario as is. Each point is a full answer with what it chooses"}},
        "required": ["scenario_id", "name"]}}}
HANDOVER_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "hand_to_describe",
    "description": "The person describes a decision problem to be modelled and solved (what to choose, assign, "
                   "schedule, place or mix, to maximise or minimise something) and no problem for it exists yet. "
                   "Building a model is done in the 'Describe a problem' tab, which interviews them, checks the "
                   "model and builds it on approval. Call this FIRST, before creating anything; it ends the turn "
                   "and offers the person a button that carries their message and attached files there.",
    "parameters": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "One sentence for the person: what the problem is"}},
        "required": ["reason"]}}}
SOURCE_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "use_source",
    "description": "Bring one of the workspace's DATA SOURCES (a database table; describe_workspace lists them under "
                   "data_sources) into this conversation as an attached sheet, exactly like a file the person attached: "
                   "read_file and query_file read it, and a plan loads it with entities_from_file / "
                   "parameter_values_from_file / relationships_from_file using its name. By default its latest "
                   "extraction is used; refresh=true reads the database again first (when the person says the data "
                   "changed, or asks for the current figures).",
    "parameters": {"type": "object", "properties": {
        "source": {"type": "string", "description": "The source's name or id, as data_sources lists it"},
        "domain_id": {"type": "integer", "description": "The workspace; omit for the selected one (give the id of a "
                      "workspace this conversation built in, when that is another)"},
        "refresh": {"type": "boolean", "description": "Read the database again now instead of the latest extraction"}},
        "required": ["source"]}}}
REFRESH_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "refresh_sources",
    "description": "Read the workspace's DATA SOURCES (database tables) again and update the records, links and "
                   "values that were built from them. apply=false (first): reads each source afresh and reports "
                   "what would change -- records added, fields changed (before -> after), records gone, values "
                   "changed -- writing nothing; show it to the person. apply=true (after they agree): writes exactly "
                   "those changes (records gone are set inactive, not deleted). Then solve the scenario again "
                   "(POST /api/v1/scenarios/{id}/runs) and compare the new answer with the last one.",
    "parameters": {"type": "object", "properties": {
        "sources": {"type": "array", "items": {"type": "string"},
                    "description": "Only these sources (names or ids, or kept file names); omit for every one the "
                                   "workspace uses. A newer copy of a kept file attached in this conversation is "
                                   "kept as its next version and compared"},
        "apply": {"type": "boolean", "description": "false: report only; true: write the changes just reported"},
        "keep_missing": {"type": "boolean", "description": "true: keep records the source no longer has active"},
        "domain_id": {"type": "integer", "description": "The workspace; omit for the selected one (give the id of a "
                      "workspace this conversation built in, when that is another)"}}}}}
SCHEDULE_TOOL: dict[str, Any] = {"type": "function", "function": {
    "name": "schedule_refresh",
    "description": "Refresh the workspace from its sources on a schedule (the person asks for 'every week', "
                   "'daily', 'keep it up to date'): every every_hours the platform reads the sources again; "
                   "mode report keeps what changed for a person to apply, mode apply writes it, and solve=true (with "
                   "apply) solves again every scenario that reads the data. It runs as the person, with their "
                   "permissions. enabled=false pauses it. describe_workspace shows it and its last run.",
    "parameters": {"type": "object", "properties": {
        "every_hours": {"type": "integer", "description": "24 daily, 168 weekly"},
        "mode": {"type": "string", "enum": ["report", "apply"]},
        "solve": {"type": "boolean"},
        "enabled": {"type": "boolean"},
        "domain_id": {"type": "integer", "description": "The workspace; omit for the selected one"}},
        "required": ["every_hours", "mode"]}}}
#: Why an extraction failed, for the person: the platform's failure classes (app.integrations.contracts).
SOURCE_FAILURES = {
    "authentication_failed": "the database refused the stored user name or password (replace the credential on the "
                             "Sources page)",
    "tls_failed": "the database's certificate could not be verified against the CA this server trusts",
    "source_unreachable": "the database could not be reached from the import worker (host, port, or it is down)",
    "network_not_allowed": "the database's address is outside the networks this server may connect to",
    "source_missing": "the database, schema, table or a column was not found on the source",
    "not_permitted": "the database user may not read this table or one of its columns",
    "trust_unavailable": "this server has no trusted certificate for database connections",
    "credential_unreadable": "the stored password cannot be decrypted with this server's keys",
    "deadline_exceeded": "reading the table took longer than one extraction is allowed",
    "limit_exceeded": "the table is larger than one extraction allows (100,000 rows or 20 MB)",
    "format_invalid": "the web source's answer is not the format it was set up for (JSON list, CSV or Excel)",
    "worker_lost": "the import worker stopped during the extraction",
}
#: How long use_source waits for a fresh extraction.
SOURCE_WAIT_S = 120
TOOLS.extend([WORKSPACE_TOOL, SOURCE_TOOL, REFRESH_TOOL, SCHEDULE_TOOL, RESULT_TOOL, OUTPUT_TOOL, WHATIF_TOOL,
              HANDOVER_TOOL])
MODEL_TOOLS.extend([WORKSPACE_TOOL, SOURCE_TOOL, REFRESH_TOOL, SCHEDULE_TOOL, CHECK_TOOL, RESULT_TOOL, OUTPUT_TOOL,
                    LAYOUT_TOOL, WHATIF_TOOL])
#: How long what_if waits for its run before handing back the run id to poll.
WHATIF_WAIT_S = 90
SETTLED = ("optimal", "feasible", "infeasible", "unbounded", "error", "cancelled", "timeout", "unknown")
#: A tool result kept whole in the conversation up to this many characters; past it, its start and end, and
#: the whole of it on disk for read_output (every later call re-sends the history: the camp-bed test's
#: run_python results made a 41k-token conversation of 15 steps).
PREVIEW_CHARS = 6000
#: Tool results kept whole: the checks' refusals (the model fixes them line by line).
WHOLE_RESULTS = {"check_spec", "propose_plan", "read_output", "make_layout"}
TOOL_NAMES = {t["function"]["name"] for t in MODEL_TOOLS} | {sandbox.SCHEMA["function"]["name"]}
# Messages the platform adds to the conversation (not the person): not counted as the person's turns.
PLATFORM = "[Platform] "
MAX_NUDGES = 3  # per kind of correction, per turn
MAX_SAME_ERROR = 3  # the same spec refusal this many times ends the turn, shown to the person
MAX_API_REJECTIONS = 3  # a write endpoint rejecting the request is not a reason to loop all turn
MAX_TOTAL_API_REJECTIONS = 8  # endpoint-hopping cannot evade the per-endpoint limit
MAX_TOOL_FAILURES = 3  # an unavailable file or failed tool is surfaced instead of retried all turn
MAX_TOTAL_NUDGES = 8
#: Runs whose facts are shown beside an answer: a what-if and its base.
FACTS_SHOWN = 2
CUT_OFF = (PLATFORM + "Your last reply was cut off at the length limit, so its tool call was NOT run. Send a smaller "
           "call: load rows from files with *_from_file instead of writing them out (generate the files with "
           "run_python if you have it), split the work into several calls, and keep prose short.")
# A reply that hit the length limit with no tool call in it: Qwen thinking aloud in circles ("Actually...
# let me...") until the limit, or drafting the spec in prose (the platform test of October 2026: 28,000
# characters, twice, shown to the person as the answer). It is never shown; the step is asked again.
RAMBLED = (PLATFORM + "Your last reply ran to the length limit without calling a tool, so it was NOT shown to the "
           "user and nothing happened. Do not think aloud or draft in the reply. Decide, then act: if a rule is hard "
           "to write, use the PATTERNS (a rule that depends on a value per pair: par[w,c] * pick[w,c] <= limit); "
           "if you are ready, call check_spec with the spec; otherwise ask the user ONE short question.")
SPEC_AS_TEXT = (PLATFORM + "You wrote the spec in your reply instead of calling a tool. It was run through check_spec "
                "for you; the result follows. Fix what it reports, then call propose_plan with the spec "
                "(through the tool interface, not as text).")
READBACK_CHECK = ("Before propose_plan, compare EVERY line of AS BUILT with what the user said: which records each rule "
                  "covers, which way a link goes (d → d2 means d2 is the next one), which numbers apply to which "
                  "records (ONE number for the whole problem applies to every record alike). If anything differs, "
                  "fix the spec and check it again. Your summary must describe AS BUILT, not your intention.")
SAME_AGAIN = "\n\nPLATFORM: "
EMPTY = (PLATFORM + "Your reply was empty. Answer the user, or call the tool you meant to call.")
_SECOND_THOUGHTS = re.compile(r"(?:^|[\n.!?*]\s*)(?:wait[,.!]|hmm[,.]|actually,? (?:let me|wait|no)|let(?:'s| me) "
                              r"re-?(?:read|check|verify|think|calculate|consider)|that seems (?:too|wrong)|"
                              r"correction on|on second thought)", re.I)
_GO_AHEAD = re.compile(r"\b(?:go ahead|nothing else|no(?:thing)? more|you decide|proceed|just do it|that'?s all|"
                       r"build it|solve it|carry on|continue)\b", re.I)
_ASKS = re.compile(r"(?:open questions|shall i (?:proceed|go ahead|build)|do you want me to|please confirm|"
                   r"can you confirm|should i (?:proceed|go ahead))|\?\s*$", re.I)
# The person's own word on where to build: the camp retest (October 2026) said "in new workspace", and the
# Assistant offered to reuse the selected workspace's records from an earlier build instead.
_NEW_WORKSPACE = re.compile(r"\b(?:new|fresh|separate|another) (?:workspace|domain)\b|\bstart (?:from scratch|fresh)\b",
                            re.I)
_SAME_WORKSPACE = re.compile(r"\b(?:existing|same|this|selected|current|old) (?:workspace|domain)\b", re.I)
NEW_WORKSPACE_ASKED = ("The user asked for a NEW workspace: put domain_name (a new, unused name) in the spec instead of "
                       "domain_id, and make the records afresh from the files -- do not reuse the selected workspace's "
                       "records.")
GO_AHEAD_SAID = (PLATFORM + "Your reply was NOT shown: the user already said to go ahead. Do not ask anything now. "
                 "Take the most reasonable reading of anything still open, list it under Assumptions, run check_spec "
                 "and then propose_plan.")
SLOW_REPLY = (PLATFORM + "Your last reply took too long and was stopped; nothing of it was received. Reply again, "
              "SHORT: no explanation, only the tool call. Change only the part the last refusal named and keep the "
              "rest of the spec as it was.")
SECOND_THOUGHTS = (PLATFORM + "Your answer was NOT shown: it still had second thoughts in it (\"Wait\", \"let me "
                   "re-check\"...). If a number is uncertain, get it with a tool first (what_if for a what-if, "
                   "read_result for the answer's numbers). Then write the final answer once, with no working shown.")
_SPEC_TEXT = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_CLAIM = re.compile(r"\b(?:I(?:'ve| have)?|we(?:'ve| have)?|it (?:has been|is now|was)|they (?:have been|were)|has been|"
                    r"have been|is now|are now)\s+(?:\w+\s+){0,2}?(?:built|created|imported|loaded|solved|published|"
                    r"added|placed)\b", re.I)
MIN_USER_TURNS_BEFORE_PLAN = 2
SOLVE_PATH = re.compile(r"^/api/v1/scenarios/\d+/runs$")
RUN_PATH = re.compile(r"^/api/v1/runs/\d+$")
MAX_SOLVES = 2  # per scenario per turn
#: A run the Assistant starts without a time limit gets this one (AGENT_RUN_SECONDS), not the platform's 8,000 s.
AGENT_RUN_SECONDS = int(os.environ.get("AGENT_RUN_SECONDS", "120"))
RUN_FIELDS = {"time_limit_s", "seed", "solver", "reuse", "pareto_steps", "robust", "alternatives",
              "alternatives_within", "alternatives_min_changes", "futures"}
# POSTs that only read: allowed in problem-description mode, where nothing else may be written.
# Data preparation, allowed in problem-description mode too (DATA FIRST, the camp-bed test: the drawing never
# became records because the Assistant could not import it nor compute what the file lacked): a new domain,
# map data imported into it and turned into records, and the platform's own calculations on those records.
DATA_POST = re.compile(r"^/api/domain/?$|^/api/v1/gis/datasets$|^/api/v1/gis/datasets/\d+/records(?:/attach)?$"
                       r"|^/api/v1/gis/domains/\d+/(?:datasets|records)$|^/api/v1/gis/derived-layers$"
                       r"|^/api/v1/domains/\d+/(?:derive-value|distances|within)$|^/api/v1/entity-types/\d+/derive$"
                       r"|^/api/v1/candidate-sets(?:/from-map)?$"
                       r"|^/api/v1/parameters/\d+/recompute$")
READ_ONLY_POST = re.compile(r"^/api/v1/gis/domains/\d+/records/propose$|^/api/v1/problems/\d+/versions/validate$")


def bind_literal_keys(ir: dict) -> list[str]:
    """`work[n, d, "night"]`: a record named by its key where an index belongs. The IR wants every index
    bound, so the roster field test's model wrote it again and again and was refused each time. Each such
    key becomes an index bound to that one record -- {"index": "k_night", "set": "shift", "where": id =
    "night"} -- added to the rule's forall (a goal term: summed over it); one record, so nothing else
    changes. Rewrites `ir` in place; returns what it did, for the model to read."""
    declared = {**{n: (v or {}).get("index") or [] for n, v in (ir.get("variables") or {}).items()},
                **{n: (v or {}).get("index") or [] for n, v in (ir.get("parameters") or {}).items()}}
    done: list[str] = []

    def walk(term, scope: set[str], added: dict[str, dict]):
        if isinstance(term, list):
            for t in term:
                walk(t, scope, added)
            return
        if not isinstance(term, dict):
            return
        inner = set(scope)
        for b in term.get("over") or []:
            if isinstance(b, dict) and isinstance(b.get("index"), str):
                inner.add(b["index"])
        ref = term.get("var") if "var" in term else term.get("par")
        if isinstance(ref, str) and isinstance(term.get("index"), list) and ref in declared:
            sets = declared[ref]
            for j, key in enumerate(term["index"]):
                if isinstance(key, str) and key not in inner and j < len(sets):
                    name = "k_" + "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in key.lower())[:40]
                    if name not in added:
                        added[name] = {"index": name, "set": sets[j],
                                       "where": [{"attr": "id", "op": "=", "value": key}]}
                        done.append(f'{ref}[..."{key}"...] -> index {name} bound to the {sets[j]} "{key}"')
                    term["index"][j] = name
        for k, v in term.items():
            if k not in ("index", "where"):
                walk(v, inner, added)

    for c in ir.get("constraints") or []:
        if not isinstance(c, dict):
            continue
        scope = {b["index"] for b in c.get("forall") or [] if isinstance(b, dict) and isinstance(b.get("index"), str)}
        added: dict[str, dict] = {}
        walk([c.get("left"), c.get("right")], scope, added)
        if added:
            c["forall"] = list(c.get("forall") or []) + list(added.values())
    for t in ((ir.get("objective") or {}).get("terms") or []):
        if not isinstance(t, dict):
            continue
        added = {}
        walk(t.get("expression"), set(), added)
        if added:
            t["expression"] = {"sum": t["expression"], "over": list(added.values())}
    return done


#: Tools whose results are data or calculations, so their numbers may be used in a plan.
DATA_TOOLS = {"read_file", "query_file", "run_python", "call_api", "describe_workspace", "read_result", "use_source",
              "refresh_sources"}
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d[\d,]*(?:\.\d+)?%?")
#: A decimal inside a comma-separated row ("1.1,3.0,4200"): _NUMBER reads "1.1" and then "3.0,4200" whole.
_DECIMALS_IN_ROW = re.compile(r"(?<=,)-?\d+(?:\.\d+)?%?(?=,|\s|$)|(?<![\w.])-?\d+\.\d+(?=,)")


def numbers_in(text: str) -> set[float]:
    """Every number written in a text (1,500 and 1.5 and 35%: the last also as 0.35). A run of numbers joined by
    commas -- a CSV row pasted into a message, "OJ1L,12,14,14,16" -- is each of its numbers too, not only one
    thousands-separated number (the production-planning trace: a pasted demand table was refused as "not given
    by the user")."""
    found: set[float] = set()

    def add(raw: str) -> None:
        try:
            value = float(raw.rstrip("%").replace(",", ""))
        except ValueError:
            return
        found.add(round(value, 6))
        if raw.endswith("%"):
            found.add(round(value / 100, 6))

    for raw in _NUMBER.findall(text or ""):
        add(raw)
        if "," in raw:
            for part in raw.split(","):
                if part.strip("-"):
                    add(part)
    for raw in _DECIMALS_IN_ROW.findall(text or ""):
        add(raw)
    return found


def _platform_order_faults(spec: dict, workspace: dict | None, files: list[dict],
                           known: set[float], typed_cells: int = 0) -> list[str]:
    """The platform's order, step by step, before a model (the camp-bed evaluation: Qwen jumped from reading
    the drawing to writing rules -- no map data, no records, no relationships, made-up values):
    1. MAP DATA: an attached map file is imported into the domain the plan builds in;
    2. RECORDS: every set has records (_sets_without_data);
    3. RELATIONSHIPS: every relationship the model walks has links;
    4. DATA VALUES: a value typed into the plan is one the user gave or one the data or a calculation gave
       (`known`: the numbers in the person's messages, the attached files and the tools' results)."""
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    faults: list[str] = []
    # STEP 1, MAP DATA: an attached drawing not yet in the domain is imported by the build itself
    # (Agent._import_drawings) -- asking the model to do it cost the camp-bed retest five turns and an
    # upload id it could not find.
    links: dict[str, int] = {}
    for r in seed.get("relationships") or []:
        if isinstance(r, dict):
            links[r.get("type")] = links.get(r.get("type"), 0) + 1
    for r in (workspace or {}).get("relationship_types") or []:
        links[r.get("name")] = links.get(r.get("name"), 0) + int(r.get("links") or 0)
    for name in ir.get("relationships") or []:
        if not links.get(name):
            declared = next((r for r in seed.get("relationship_types") or []
                             if isinstance(r, dict) and r.get("name") == name), None)
            endpoints = (f' Its declared endpoints are {declared.get("from")} -> {declared.get("to")}.'
                         if declared else " Check the declared relationship type and endpoints.")
            # Records of one kind that follow each other (the next step, day, period): made from their own fields
            # (the job-shop retest: "then" op -> op was declared, never loaded, and this message named files only).
            ordered = (f' If each {declared.get("from")} is linked to the NEXT one (the next step of the same job, the '
                       f'next day or period), make the links from their fields: "relationships_in_order": '
                       f'[{{"type": "{name}", "of": "{declared.get("from")}", "by": <the ordering field>, "within": '
                       f'<the grouping field, if any>}}] in the seed, and load those fields as attrs.'
                       if declared and declared.get("from") == declared.get("to") else "")
            faults.append(f'STEP 3, RELATIONSHIPS: "{name}" has NO links, and the model walks it.'
                          f'{endpoints}{ordered} Load real matching links from relationships_from_file or existing domain data; '
                          'a parameter is not a relationship. Use /within only for a defined spatial proximity rule '
                          'supported by geometry, or /distances for measured distances. Never invent a threshold, '
                          'remove a required relation, or claim path connectivity from proximity alone.')
    typed = [(p.get("name"), p.get("default_value")) for p in seed.get("parameters") or []
             if isinstance(p, dict) and not p.get("index")]
    # Cells typed into the plan come first; the ones loaded from files follow them (files.expand).
    typed += [(v.get("parameter"), v.get("value")) for v in (seed.get("parameter_values") or [])[:typed_cells]
              if isinstance(v, dict)]
    made_up = sorted({f"{name} = {value}" for name, value in typed
                      if isinstance(value, (int, float)) and not isinstance(value, bool)
                      and round(float(value), 6) not in known and float(value) not in (0.0, 1.0)
                      and float(value) < 999_999})
    if made_up:
        faults.append("STEP 4, DATA VALUES: these numbers were not given by the user nor found in the data or a "
                      f"calculation: {', '.join(made_up)}. Ask the user for them, or compute them with an "
                      "available platform calculation or query_file -- never put in a placeholder. If they are "
                      "possible values of a number the user called uncertain (a range, \"anything from .. to ..\"), "
                      "do not list them: declare that number uncertain (DECIDE BEFORE UNCERTAIN DATA) and plan with "
                      "what_if futures.")
    return faults


def _numbers_from(messages: list[dict]) -> set[float]:
    """Only what the person wrote and what reading or computing tools returned: never the checks' own replies,
    which quote the plan's numbers back (an invented value would vouch for itself), nor a summary's prose."""
    known: set[float] = set()
    for m in messages:
        if (m["role"] == "user" and not str(m.get("content") or "").startswith(PLATFORM)) or (
                m["role"] == "tool" and m.get("name") in DATA_TOOLS):
            known |= numbers_in(str(m.get("content") or ""))
    return known


def _sendable(spec: dict) -> dict:
    """The spec without the Assistant's own markers (cells loaded from a file)."""
    seed = spec.get("seed")
    if not isinstance(seed, dict) or not seed.get("parameter_values"):
        return spec
    cells = [{k: v for k, v in c.items() if k != "_from_file"} if isinstance(c, dict) else c
             for c in seed["parameter_values"]]
    return {**spec, "seed": {**seed, "parameter_values": cells}}


def _sets_without_data(spec: dict, existing: dict[str, int]) -> list[str]:
    """DATA FIRST: every set the model uses must get its records from somewhere -- typed in the seed, loaded
    from a file or map layer (entities_from_file; run_python's output files count), or already in the
    domain. The camp-bed test built "zone" and "door" with no records at all; the solve then failed and
    the Assistant looped 24 times. `existing`: records per kind already in the domain."""
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    made: dict[str, int] = {}
    for e in seed.get("entities") or []:
        if isinstance(e, dict):
            made[e.get("type")] = made.get(e.get("type"), 0) + 1
    faults = []
    for name in ir.get("sets") or []:
        if made.get(name) or existing.get(name):
            continue
        if re.search(r"(^|_)(scenarios?|futures?|outcomes?|realis|realiz|samples?|cases?|levels?)($|_)", str(name), re.I):
            # The bakery test: a "scenario" set of demand levels typed by hand, twice, instead of the declaration.
            faults.append(f'Set "{name}" looks like the possible futures of an uncertain number. Do not make them '
                          f'records: declare the number uncertain in ir.parameters ("uncertainty": {{"kind": '
                          f'"interval", "deviation": <share either side>}} or {{"kind": "scenarios", "futures": '
                          f'[{{"label", "factor"}}]}}), mark decisions "stage": 1 (now) or 2 (once known), drop the '
                          f'set, and plan with what_if "futures" (the DECIDE BEFORE UNCERTAIN DATA pattern).')
            continue
        faults.append(f'Set "{name}" would have NO records: nothing in the plan makes them and the domain has none. '
                      f'Name its data: entities_from_file from an attached file or map layer (e.g. {{"file": ..., '
                      f'"sheet": <layer>, "type": "{name}", "key": "feature", "attrs": {{...}}}}), a file generated '
                      f'with run_python (when on), records typed in entities, or records the seed generates ("patterns_that_fit" '
                      f'makes one record per way to fill a roll, bin or truck). Numbers the file lacks (areas, '
                      f'distances) come from its columns (area_m2, x_m, ...) or from a calculation step; never invent them.')
    return faults


def _empty_parameters(spec: dict) -> list[str]:
    """Parameters the model reads that would hold nothing but their default. The field test (October
    2026): the goal used delivery_cost_egp[warehouse, customer], declared with default 999999999 and never
    loaded, so every lane cost the same and the transport cost dropped out of the decision -- a plan that
    passed every check, was shown as "cost per ton x demand", and would have answered the wrong question.
    A parameter indexed by records with no cell at all is refused; one the domain already has (not
    declared in this seed) is left alone, its values being in the platform."""
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    declared = {p.get("name"): p for p in seed.get("parameters") or [] if isinstance(p, dict)}
    cells: dict[str, int] = {}
    for v in seed.get("parameter_values") or []:
        if isinstance(v, dict):
            cells[v.get("parameter")] = cells.get(v.get("parameter"), 0) + 1
    faults = []
    read: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("par"), str):
                read.add(node["par"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk([ir.get("constraints"), ir.get("objective")])
    for name, count in cells.items():
        # Data loaded that no rule or goal reads (the roster field test: the 8 days off asked for were
        # loaded as requested_off, and the goal "fewest broken requests" counted every shift worked instead).
        if name in declared and name not in read:
            faults.append(f'Parameter "{name}" holds data ({count} cells) but no rule or goal reads it. If it matters, '
                          f'read it in a rule or goal ({{"par": "{name}", "index": [...]}}); if not, drop it.')
    for name in (ir.get("parameters") or {}):
        p = declared.get(name)
        if not p or not p.get("index") or cells.get(name):
            continue
        try:
            default = abs(float(p.get("default_value") or 0))
        except (TypeError, ValueError):
            default = 0.0
        # A huge default is a stand-in for missing data (the warehouse test: 999,999,999 for every lane), not one
        # value meant for every cell.
        same_for_all = 0 < default < 1e6
        if same_for_all:
            # One value meant for every cell (the bakery test: a probability of 1/21 for each of 21 demand levels
            # was refused as "no value is loaded"); the read-back shows it as "every other cell 0.047619".
            continue
        indexes = ", ".join(map(str, p["index"]))
        if re.search(r"(?:near|nearby|within|reach|adjacen|connect|distance|proxim|access)", name, re.I):
            action = (" Do not leave this as an empty parameter or replace a relationship with a parameter. If the "
                      "agreed rule means geometric proximity, use POST /api/v1/domains/{domain_id}/within to create "
                      "a relationship from actual geometry, with a threshold the user gave; use that relationship "
                      "in the IR. Do not invent a threshold. If the rule means a walkable path, /within cannot "
                      "prove it; use actual path-connectivity data or state that the rule cannot yet be modelled.")
        else:
            action = (" Load it with parameter_values_from_file or use a platform calculation that produces this "
                      "exact value. If neither is possible, ask for the missing source; do not invent values.")
        faults.append(f'Parameter "{name}"[{indexes}] is used by the model but no value is loaded: every cell would '
                      f'be its default {p.get("default_value", 0)}.{action}')
    return faults


def _uncertainty_faults(spec: dict) -> list[str]:
    """An uncertain number the plan cannot plan for (the bakery retests, October 2026: demand declared uncertain
    with nothing decided after it is known, so "50 futures" solved the average case; a deviation of 100 meant
    as +/- 100 loaves)."""
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    uncertain = {n: p["uncertainty"] for n, p in (ir.get("parameters") or {}).items()
                 if isinstance(p, dict) and isinstance(p.get("uncertainty"), dict)}
    if not uncertain:
        return []
    faults = []
    for name, u in uncertain.items():
        try:
            deviation = float(u.get("deviation")) if u.get("kind") == "interval" else None
        except (TypeError, ValueError):
            deviation = None
        if deviation is not None and deviation > 1:
            faults.append(f'{name}\'s "deviation" is a SHARE of its value (0.5 for +/- 50%); {deviation:g} would let it '
                          f'go below zero. For "100 to 300" around 200, write 0.5.')
    later = [n for n, v in (ir.get("variables") or {}).items() if isinstance(v, dict) and v.get("stage") == 2]
    chance = any(isinstance(c, dict) and isinstance(c.get("chance"), dict) for c in ir.get("constraints") or [])
    if not later and not chance:
        faults.append(f'{", ".join(uncertain)} is declared uncertain, but no decision is marked "stage": 2 (made once '
                      f'it is known: how many sold, how much shipped late...), so planning for futures would change '
                      f'nothing. Mark the decisions made now "stage": 1 and those made after "stage": 2.')
    return faults


def _spec_in_text(text: str) -> dict | None:
    """A spec the model wrote into its reply in a ```json fence (or bare), recognised by its "ir"."""
    candidates = [m.group(1) for m in _SPEC_TEXT.finditer(text or "")]
    start = (text or "").find("{")
    if not candidates and start >= 0 and '"ir"' in text:
        candidates.append(text[start: text.rfind("}") + 1])
    for raw in candidates:
        try:
            obj = toolcall.strict_loads(raw)
        except Exception:  # noqa: BLE001 -- not a spec after all
            continue
        if isinstance(obj, dict) and isinstance(obj.get("spec"), dict):
            obj = obj["spec"]
        if isinstance(obj, dict) and isinstance(obj.get("ir"), dict):
            return obj
    return None


def plain_refusal(result: str) -> str:
    """One sentence a person can read for a spec refusal (the JSON stays for the model)."""
    msgs = re.findall(r'"msg":\s*"((?:[^"\\]|\\.)*)"', result)
    locs = re.findall(r'"loc":\s*\[([^\]]*)\]', result)
    if not msgs:
        return "the platform's check refused it."
    where = ""
    if locs:
        parts = [p.strip().strip('"') for p in locs[0].split(",")]
        if "constraints" in parts:
            where = "in a rule"
        elif "objective" in parts:
            where = "in the goal"
        elif "variables" in parts:
            where = "in a decision"
        elif "seed" in parts:
            where = "in the data"
    text = msgs[0].encode().decode("unicode_escape", errors="ignore")
    text = text.split(":")[0].split(";")[0].strip().rstrip(".")
    return f"{where + ', ' if where else ''}{text}.".capitalize() if not where else f"{where}, {text}."


def clip(obj: Any, limit: int) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n...[truncated {len(s) - limit} chars: narrow it with filters or a limit]"


# ------------------------------------------------------------------ the spec --
class ApiIndex:
    """The OpenAPI document, searchable and described one endpoint at a time."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.ops: list[dict[str, Any]] = []
        for path, item in spec.get("paths", {}).items():
            if any(b.match(path) for b in BLOCKED_PATHS):
                continue
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
            for t in o["tags"] or ["untagged"]:
                counts[t] = counts.get(t, 0) + 1
        return ", ".join(f"{t} ({n})" for t, n in sorted(counts.items()))

    def search(self, query: str, method: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        words = [w for w in re.split(r"[\s/_\-]+", (query or "").lower()) if w]
        scored = []
        for o in self.ops:
            if method and o["method"] != method.upper():
                continue
            path = o["path"].lower()
            hay = " ".join([path, o["summary"].lower(), " ".join(o["tags"]).lower(), o["description"][:400].lower()])
            score = 0 if words else 1
            for w in words:
                stem = w.rstrip("s") if len(w) > 3 else w
                score += (3 if stem in path else 0) + (1 if stem in hay else 0)
            if score:
                scored.append((score, o))
        scored.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["method"]))
        return [{"method": o["method"], "path": o["path"], "summary": o["summary"], "tags": o["tags"]}
                for _, o in scored[:limit]]

    def find(self, method: str, path: str) -> dict[str, Any] | None:
        method = method.upper()
        path = path.split("?")[0]
        for o in self.ops:
            if o["method"] == method and o["path"] == path:
                return o
        for o in self.ops:
            if o["method"] != method:
                continue
            pattern = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(o["path"])) + "$"
            if re.match(pattern, path):
                return o
        return None

    def _resolve(self, schema: Any, depth: int = 0, seen: tuple = ()) -> Any:
        if isinstance(schema, list):
            return [self._resolve(s, depth, seen) for s in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            ref = schema["$ref"]
            name = ref.split("/")[-1]
            if ref in seen or depth >= 5:
                return {"$ref_name": name, "note": f"use describe_schema('{name}')"}
            node: Any = self.spec
            for part in ref.lstrip("#/").split("/"):
                node = node.get(part, {})
            return self._resolve(node, depth + 1, seen + (ref,))
        return {k: self._resolve(v, depth, seen) for k, v in schema.items() if k != "title"}

    def schema(self, name: str) -> Any:
        node = self.spec.get("components", {}).get("schemas", {}).get(name)
        return self._resolve(node) if node else {"error": f"no schema named {name}"}

    def describe(self, method: str, path: str) -> dict[str, Any]:
        o = self.find(method, path)
        if not o:
            return {"error": f"no endpoint {method.upper()} {path}; use search_endpoints"}
        op = o["op"]
        params = [self._resolve(p) for p in (o["item"].get("parameters") or []) + (op.get("parameters") or [])]
        out: dict[str, Any] = {
            "method": o["method"], "path": o["path"], "summary": o["summary"],
            "description": o["description"][:2500],
            "parameters": [{"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False),
                            "schema": p.get("schema"), "description": (p.get("description") or "")[:300]}
                           for p in params],
        }
        body = op.get("requestBody")
        if body:
            body = self._resolve(body)
            content = body.get("content", {})
            ctype = next(iter(content), None)
            out["request_body"] = {"required": body.get("required", False), "content_type": ctype,
                                   "schema": content.get(ctype, {}).get("schema") if ctype else None}
        ok = next((v for k, v in (op.get("responses") or {}).items() if str(k).startswith("2")), None)
        if ok and "content" in ok:
            sch = next(iter(ok["content"].values()), {}).get("schema")
            if sch:
                out["response_schema"] = self._resolve(sch)
        return out


def read_doc(path: str, offset: int, limit: int) -> str:
    if not DOC_ROOTS:
        return "No documentation is shipped with this installation."
    rel = (path or "").replace("\\", "/").strip("/")
    if rel.startswith("docs/"):
        rel = rel[5:]
    for root in DOC_ROOTS:
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            return "not allowed"
        if target.is_dir():
            files = sorted(str(p.relative_to(root)).replace("\\", "/") for p in target.rglob("*.md"))
            return "\n".join(files[:300])
        if target.is_file():
            text = target.read_text(encoding="utf-8", errors="replace")
            chunk = text[offset: offset + limit]
            rest = len(text) - offset - len(chunk)
            return chunk + (f"\n...[{rest} more chars; read_doc offset={offset + len(chunk)}]" if rest > 0 else "")
    return "not found; pass '' to list the documents"


# ------------------------------------------------------------- calling the API --
CallFn = Callable[..., dict]


def loopback_caller(settings: Settings, token: str) -> CallFn:
    """Calls this same API over HTTP with the person's own bearer token."""

    def call(method: str, path: str, query: dict | None = None, body: Any = None,
             form: dict | None = None, headers: dict | None = None) -> dict:
        url = settings.self_url + path
        if query:
            q = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in query.items() if v is not None}
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q, doseq=True)
        hdrs = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        hdrs.update({str(k): str(v) for k, v in (headers or {}).items() if str(k).lower() != "authorization"})
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                status, ctype, raw = r.status, r.headers.get("content-type", ""), r.read()
        except urllib.error.HTTPError as e:
            status, ctype, raw = e.code, (e.headers.get("content-type", "") if e.headers else ""), e.read()
        if "json" in ctype:
            try:
                payload: Any = json.loads(raw or b"null")
            except ValueError:
                payload = raw.decode("utf-8", "replace")
        elif ctype.startswith("text/") or not raw:
            payload = raw.decode("utf-8", "replace")
        else:
            payload = f"<{len(raw)} bytes of {ctype}: a file download; give the person the endpoint path instead>"
        return {"status": status, "ok": 200 <= status < 300, "body": payload}

    return call


# ------------------------------------------------------------------- the LLM --
class LlmError(Exception):
    def __init__(self, status: int, body: str):
        label = f"LLM HTTP {status}" if status else "LLM request failed"
        super().__init__(f"{label}: {body[:300]}")
        self.status = status
        self.body = body


def _slow_or_down(settings: Settings, started: float) -> LlmError:
    """A reply cut at LLM_REPLY_SECONDS is slow, not down: it is asked again, shorter."""
    if settings.reply_seconds > 0 and settings.reply_seconds < settings.timeout:
        return ReplyTooSlow(settings.reply_seconds)
    return _llm_timeout(settings)


def _llm_timeout(settings: Settings) -> LlmError:
    return LlmError(0, f"The model at {settings.base_url} did not respond within {settings.timeout:g} seconds. "
                    "Check that the model service is reachable and healthy, then try again.")


class ReplyTooSlow(LlmError):
    """One reply ran past LLM_REPLY_SECONDS; the connection was closed (vLLM stops generating then)."""

    def __init__(self, seconds: float):
        super().__init__(0, f"the model's reply took longer than {seconds:g} seconds and was stopped")
        self.seconds = seconds


class ToolModeChanged(Exception):
    """The server has no native tool calling; rebuild the prompt for the text protocol."""


def llm_chat(settings: Settings, messages: list[dict], native: bool | None,
             tools: list[dict] | None = None, max_tokens: int | None = None) -> tuple[dict, bool]:
    """One completion. Returns (message, native_used)."""
    payload: dict[str, Any] = {"model": settings.model, "messages": messages,
                               "temperature": settings.temperature,
                               "max_tokens": max_tokens or settings.max_tokens}
    if settings.thinking == "auto":
        settings = replace(settings, thinking=thinking_for(messages))
    if settings.thinking in ("on", "off"):
        payload["chat_template_kwargs"] = {"enable_thinking": settings.thinking == "on"}
    if native is not False:
        payload["tools"] = tools or TOOLS
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        settings.base_url + "/chat/completions", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.api_key}"})
    try:
        # A 32,768-token reply at the Qwen3.5 server's ~50 tokens a second takes about 11 minutes: the wait
        # outlasts the longest reply allowed (LLM_TIMEOUT, seconds), or a turn would end on "timed out".
        cap = min(settings.timeout, settings.reply_seconds) if settings.reply_seconds > 0 else settings.timeout
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=cap) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if native is None and e.code == 400 and "tool" in body.lower():
            _NATIVE_TOOLS[settings.base_url] = False
            raise ToolModeChanged() from e
        raise LlmError(e.code, body) from e
    except TimeoutError as e:
        raise _slow_or_down(settings, started) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise _slow_or_down(settings, started) from e
        raise LlmError(0, f"cannot reach the model at {settings.base_url}: {e.reason}") from e
    if native is None:
        _NATIVE_TOOLS[settings.base_url] = True
    choice = data["choices"][0]
    message = dict(choice.get("message") or {})
    message["_finish"] = choice.get("finish_reason")
    return message, native is not False


def thinking_for(messages: list[dict]) -> str:
    """LLM_THINKING=auto: think where it pays, not at every step. Thinking is most of a step's time (the camp
    test: ~10 s of every 13 s was decoding). On when a person's message is to be understood, when the plan
    is being written or was refused, and when a tool failed; off when carrying on after tools that worked."""
    last = messages[-1] if messages else {}
    if last.get("role") != "tool":
        return "on"
    done = []
    for m in reversed(messages):
        if m.get("role") != "tool":
            break
        done.append(m)
    for m in done:
        content = str(m.get("content") or "")
        if m.get("name") in ("check_spec", "propose_plan") or content.startswith(
                ("tool error", "Refused", "Could not", "Not valid yet", "The spec does not build", "No attached")) \
                or '"ok": false' in content[:40] or (content.startswith('{"exit_code":')
                                                       and not content.startswith('{"exit_code": 0')):
            return "on"
    return "off"


_SERVER_CONTEXT: dict[str, tuple[float, int | None]] = {}


def server_context(settings: Settings) -> int:
    """The model server's own context size (vLLM reports max_model_len per model), cached ten minutes; the
    configured LLM_CONTEXT when the server does not say. Raising vLLM's --max-model-len to 64k is then
    picked up without changing the platform."""
    now = time.time()
    seen = _SERVER_CONTEXT.get(settings.base_url)
    if seen is None or now - seen[0] > 600:
        found: int | None = None
        try:
            req = urllib.request.Request(settings.base_url + "/models",
                                         headers={"Authorization": f"Bearer {settings.api_key}"})
            with urllib.request.urlopen(req, timeout=3) as r:
                for m in json.loads(r.read()).get("data", []):
                    if m.get("id") == settings.model and m.get("max_model_len"):
                        found = int(m["max_model_len"])
        except Exception:  # noqa: BLE001 -- unreachable or silent: the configured size stands
            found = None
        _SERVER_CONTEXT[settings.base_url] = seen = (now, found)
    return seen[1] or settings.context


def check_llm(settings: Settings) -> dict[str, Any]:
    try:
        req = urllib.request.Request(settings.base_url + "/models",
                                     headers={"Authorization": f"Bearer {settings.api_key}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read()).get("data", [])
        models = [m.get("id") for m in data]
        context = next((int(m["max_model_len"]) for m in data if m.get("id") == settings.model and m.get("max_model_len")),
                       settings.context)
        return {"reachable": True, "models": models, "model_found": settings.model in models, "context": context}
    except Exception as e:  # noqa: BLE001 -- any failure is "not reachable", with why
        return {"reachable": False, "error": str(e)[:300]}


THINK_RE = re.compile(r"<think>.*?</think>", re.S)
OPEN_THINK_RE = re.compile(r"^.*?</think>", re.S)  # template put <think> in the prompt


def clean(content: str | None) -> str:
    text = THINK_RE.sub("", content or "")
    if "</think>" in text:
        text = OPEN_THINK_RE.sub("", text)
    return text.strip()




def text_protocol(tools: list[dict]) -> str:
    return (
        "\n\n# Tools\nCall a tool by writing, on its own lines:\n<tool_call>\n"
        '{"name": "<tool>", "arguments": {...}}\n</tool_call>\n'
        'Several blocks may follow each other. Then stop: results come back in a message starting '
        '"TOOL RESULTS". When finished, answer with no <tool_call> block.\nTools:\n'
        + json.dumps([t["function"] for t in tools])
    )


def to_wire(messages: list[dict], native: bool) -> list[dict]:
    """The canonical (native-style) history in the form the server accepts."""
    if native:
        return messages
    out: list[dict] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            out.append({"role": "user", "content": "TOOL RESULTS\n\n" + "\n\n".join(pending)})
            pending.clear()

    for m in messages:
        if m["role"] == "tool":
            pending.append(f"[{m.get('name', 'tool')}]\n{m['content']}")
            continue
        flush()
        if m["role"] == "assistant" and m.get("tool_calls"):
            blocks = "\n".join(
                "<tool_call>\n" + json.dumps({"name": c["function"]["name"],
                                              "arguments": _args(c)}, ensure_ascii=False) + "\n</tool_call>"
                for c in m["tool_calls"])
            out.append({"role": "assistant", "content": ((m.get("content") or "") + "\n" + blocks).strip()})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    flush()
    return out


def _shown(name: str, args: dict) -> dict:
    """What the UI shows of a call: a plan's spec is large and shown in its own card."""
    if name == "propose_plan":
        return {"summary": str(args.get("summary", ""))[:200]}
    return args


def _args(call: dict) -> dict:
    try:
        a = json.loads(call["function"].get("arguments") or "{}")
        return a if isinstance(a, dict) else {}
    except ValueError:
        return {}


CHARS_PER_TOKEN = 2.0  # JSON and specs tokenise densely: 2.5 let a 24,577-token prompt through as "fitting"


def fit(messages: list[dict], settings: Settings, reply_tokens: int | None = None, spare: int = 0) -> list[dict]:
    """Under the model's context: shorten old tool results, then drop the oldest exchanges. `spare`: tokens
    more to free, when the server said the last estimate was still too big."""
    reply = reply_tokens or settings.max_tokens
    budget = int((settings.context - reply - 2500 - spare) * CHARS_PER_TOKEN)
    msgs = [dict(m) for m in messages]
    # A spec is long, and only the latest one matters: every earlier check_spec / propose_plan keeps its
    # summary only (the roster field test: four 10,000-character specs in the history overflowed 32k).
    spec_at = [i for i, m in enumerate(msgs) if m["role"] == "assistant" and any(
        c["function"]["name"] in ("propose_plan", "check_spec") for c in m.get("tool_calls") or [])]
    for i in spec_at[:-1]:
        msgs[i]["tool_calls"] = [
            {**c, "function": {**c["function"], "arguments": json.dumps(
                {"summary": str(_args(c).get("summary", ""))[:1500], "spec": "(superseded by a later spec)"})}}
            if c["function"]["name"] in ("propose_plan", "check_spec") else c
            for c in msgs[i]["tool_calls"]]
    size = lambda: sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in msgs)  # noqa: E731
    for m in msgs[1:-6]:
        if size() <= budget:
            break
        if m["role"] == "tool" and len(m.get("content") or "") > 400:
            m["content"] = m["content"][:400] + "...[older result shortened]"
        if m["role"] == "assistant" and m.get("tool_calls"):
            # Old code and request bodies are the bulk of a long session (the camp-bed retest: two
            # 8,000-character run_python scripts); what they produced is in their (shortened) results.
            m["tool_calls"] = [
                {**c, "function": {**c["function"], "arguments": c["function"]["arguments"][:300]
                                   + '..."(earlier call, shortened)"'}}
                if len(c["function"].get("arguments") or "") > 600 and c["function"]["name"] not in
                ("propose_plan", "check_spec") else c
                for c in m["tool_calls"]]
    # The person's first message is the problem itself: it is never dropped (the camp-bed retest lost the
    # brief to trimming, and the model asked "What decision are you making?"). The oldest exchanges AFTER
    # it go first.
    first = next((i for i, m in enumerate(msgs) if m["role"] == "user"
                  and not str(m.get("content") or "").startswith(PLATFORM)), None)
    keep = (first + 1) if first is not None else 1
    while size() > budget:
        starts = [i for i, m in enumerate(msgs) if i > keep and m["role"] == "user"
                  and not str(m.get("content") or "").startswith(PLATFORM)]
        if not starts or starts[0] >= len(msgs) - 1:
            break
        del msgs[keep:starts[0]]
    if first is not None and keep < len(msgs) and msgs[keep]["role"] == "tool":
        # Never leave a tool result without the call it answers.
        while keep < len(msgs) and msgs[keep]["role"] == "tool":
            del msgs[keep]
    return msgs


# ------------------------------------------------------------------ the loop --
@dataclass
class Context:
    username: str
    page: str | None = None
    domain_id: int | None = None
    problem_id: int | None = None
    mode: str = "assistant"  # or "model"
    files: list[dict] = field(default_factory=list)  # attached, parsed (app/agent/files.py)
    user_id: str = ""
    conversation_id: str | None = None
    can_run_python: bool = False  # AGENT_RUN_PYTHON on, and the person may publish models


EXAMPLE_SPEC = {
    "domain_name": "City projects",
    "problem_name": "Choose projects to fund",
    "note": "Fund the projects worth most within the budget; district A gets at most two.",
    "seed": {
        "entity_types": [{"name": "project", "role": "task", "attributes": [
            {"name": "cost", "data_type": "number", "required": True, "unit": "kEGP"},
            {"name": "benefit", "data_type": "number", "required": True, "unit": "points"},
            {"name": "district", "data_type": "enum", "enum_values": ["a", "b"], "required": True}]}],
        "parameters": [{"name": "budget", "index": [], "default_value": 500, "unit": "kEGP"}],
        "entities": [
            {"type": "project", "key": "roof", "label": "School roof", "attrs": {"cost": 200, "benefit": 9, "district": "a"}},
            {"type": "project", "key": "clinic", "label": "Clinic wing", "attrs": {"cost": 250, "benefit": 12, "district": "a"}},
            {"type": "project", "key": "park", "label": "Park", "attrs": {"cost": 120, "benefit": 5, "district": "a"}},
            {"type": "project", "key": "road", "label": "Road repair", "attrs": {"cost": 180, "benefit": 7, "district": "b"}}],
    },
    "ir": {
        "version": 2,
        "sets": ["project"],
        "parameters": {"budget": {"index": []}},
        "variables": {"fund": {"index": ["project"], "domain": "binary"}},
        "constraints": [
            {"id": "c_budget", "note": "total cost of funded projects within the budget",
             "left": {"sum": {"mul": [{"attr": {"of": "p", "name": "cost"}}, {"var": "fund", "index": ["p"]}]},
                      "over": [{"index": "p", "set": "project"}]},
             "relation": "<=", "right": {"par": "budget", "index": []}, "severity": "hard"},
            {"id": "c_district_a", "note": "at most two projects in district A",
             "left": {"sum": {"var": "fund", "index": ["p"]},
                      "over": [{"index": "p", "set": "project",
                                "where": [{"attr": "district", "op": "=", "value": "a"}]}]},
             "relation": "<=", "right": {"const": 2}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [
            {"id": "o_benefit", "weight": 1,
             "expression": {"sum": {"mul": [{"attr": {"of": "p", "name": "benefit"}}, {"var": "fund", "index": ["p"]}]},
                            "over": [{"index": "p", "set": "project"}]}}]},
    },
}


def model_prompt(ctx: "Context") -> str:
    where = (f"The user has domain id {ctx.domain_id} selected. Build there (domain_id) ONLY if the problem is about "
             f"what that domain holds (describe_workspace shows it: the same kinds of record, or kinds the attached "
             f"files match); a problem about different things gets a NEW domain (domain_name), and say so in one "
             f"line -- never put an unrelated problem into the selected domain. When the user asks for a new "
             f"workspace, ALWAYS make one (domain_name) and make its records afresh: never offer to reuse the "
             f"selected domain's records." if ctx.domain_id is not None else
             "No domain is selected: make a new one (domain_name) unless the user names an existing one.")
    workbench = ("""
- WORKBENCH: run_python runs Python in this conversation's folder, where every attached sheet is a CSV. Use it to
  read and check data, compute totals and bounds, and GENERATE the data a model needs (candidate positions at true
  size, pairs that touch or cover, distances...) as CSV files: they come back as attachments that the plan loads
  with *_from_file. After solving, use it to check the answer against the raw data, rule by rule.""" if ctx.can_run_python else """
- TOOL LIMIT: run_python is not available in this conversation. Do not call it or propose files generated with it.
  Use the candidate APIs, attached data, and supported platform calculations; if they cannot produce a required
  value or relationship, ask for a suitable data source or explain the limitation. Use only tools listed in the
  current tool schema and make one API call at a time; never concatenate a route with another tool call.""")
    generated_sources = ("(d) when run_python is on, generated data: candidate items at real size, the cells or "
                         "resources each occupies, neighbours, door cells -- written as CSV files that come back "
                         "as attachments to load."
                         if ctx.can_run_python else
                         "(d) candidate and relationship data produced by the platform's candidate APIs or spatial "
                         "calculations; if no supported operation can produce the required data, ask for a data "
                         "source or state the limitation rather than inventing records or values.")
    layout_generation = ("Only when the candidate API cannot express the problem, use run_python to generate "
                         "candidates.csv (cand, x_m, y_m, rot, ...), cells.csv (cell, x_m, y_m) on a grid whose "
                         "step divides every item size, and occupies.csv (cand, cell: one row per cell a candidate "
                         "covers; keep it under about 2,000,000 rows). Load with entities_from_file and "
                         "relationships_from_file; declare occupies from cand to cell and list it in the IR."
                         if ctx.can_run_python else
                         "If the candidate API cannot express a required relationship, do not attempt client-side "
                         "generation: use a supported platform calculation or ask for source data. Never substitute "
                         "a count approximation or drop a required rule without the user's approval.")
    return f"""You are the modelling assistant of the Problem Solver platform, talking with "{ctx.username}".
They describe a real decision problem in their own words. You understand it fully, turn it into a platform
model, get their approval, build it, and explain what you built. {where} Reply in the user's language.

THE PLATFORM MAKES THESE -- never type them as records or values yourself (the field tests: hand-typed cutting
patterns, demand scenarios and month links each cost several rounds or a wrong answer):
- the next step / day / period of a sequence -> "relationships_in_order" (see SCHEDULING, STOCK OVER PERIODS);
- distances from coordinate columns -> "distances_from_fields";
- every way to fill a roll, bin or truck -> "patterns_that_fit";
- an uncertain number ("anything from 100 to 300", "might be 30% higher") -> "uncertainty" on the parameter plus
  "stage" on the decisions, then what_if "futures" -- NEVER a set of scenario records;
- a trade-off between two goals or more (up to six) -> what_if "front".

PHASE 1 - UNDERSTAND. This is most of the conversation. Do not just accept what you are told.
- LOOK FIRST: call describe_workspace before your first question, and read the attached files. Never ask for what
  the workspace or the files already say; reuse existing kinds of record, fields and data values by their names.
- DATA SOURCES: when describe_workspace lists data_sources (database tables) that hold data the problem needs,
  call use_source for each one: it arrives as an attached sheet, loaded in the plan with *_from_file like any
  file -- never ask the person to export or retype a table a source already has. refresh=true when they say the
  data changed or want today's figures. Say in the plan which source each kind of record comes from.
  Take EVERY number a source holds from the source -- a record's field in the rule (p.capacity_hours), or
  parameter_values_from_file -- never type it into the plan: only what is loaded from a source is updated when
  the data is refreshed later. For a problem already built from sources, "the data changed" / "run it with
  today's data" is refresh_sources (report, ask, apply), then a new run, compared with the last answer.
- KEPT FILES: a file the person attaches and the plan loads with *_from_file is kept in the workspace by name and
  version (describe_workspace lists them under files). Next time, the person attaches the new file under the same
  name and asks to update: refresh_sources keeps it as the next version, reports what changes, and applies on yes.
  use_source also attaches a kept file by name, for reading.
- SCHEDULED REFRESH: "every week", "keep it up to date" -> schedule_refresh (report, or apply and solve again).
- Each turn: an "Agreed so far" list (short bullets), then the open questions, numbered, at most 4, most
  important first, in plain words, with examples of possible answers. Never ask again about an agreed item.
  Ask only what would change the model: never about names (choose them), never about coordinate systems unless a
  map file is attached, never what the user already said. When the user says "nothing else", "go ahead" or "you
  decide", stop asking: choose sensible defaults, list them as assumptions, and propose. Before sending a question,
  check it against "Agreed so far": a question whose answer is already there is not asked (no "just to confirm").
  Once every item in (a)-(d) below is known, do not ask anything: go straight to check_spec.
- SIZE IT: as soon as the numbers are known, compare totals (demand vs capacity, cost vs budget, area vs
  footprint) and say early if the target looks out of reach. NEVER add up, count or compare numbers in your head:
  take totals from ATTACHED FILES (exact) and ask query_file (e.g. how many lanes are over 450 km, which
  warehouses can reach each customer, demand per region).
- Before any plan you must know: (a) the DECISIONS (assign who to what, how many to make, which to open...);
  (b) the GOAL: what to minimise or maximise; with several goals, their priority or relative weight;
  (c) every RULE, and whether it may never be broken (hard) or may bend at a cost (soft: how bad, relative to the goal);
  (d) the THINGS involved and their DATA: names or counts, quantities with units (capacity, cost, demand,
  hours, distance), time periods; and which data the user has.
- Vague words ("cheap", "fair", "balanced", "as many as possible", "usually", "close") need a number or an exact
  rule: ask, or propose a concrete reading and ask them to confirm it.
- Point out contradictions, missing data and numbers that look wrong. If they answer "ok" or "you decide" to
  something unsettled, choose a specific default, say it is an assumption, and list it in the plan.
- DATA: when data is missing, ask for it. Small data the user can type in the chat. Otherwise ask them to attach
  a CSV or Excel file (the paperclip button) and say exactly which columns you need, e.g. "a file with columns
  shop, demand_trays". Read attached files with read_file and query_file; check them (missing values, units, duplicates, numbers
  that look wrong) and ask about anything odd before you plan.
- MAP FILES (a CAD drawing, GeoJSON, KML, GPX, Shapefile, GeoPackage, CSV of shapes): each layer is a sheet,
  one row per feature. Ask what each layer is (e.g. "layer PLOTS are the candidate sites"). A drawing with no
  coordinate system comes in LOCAL METRES: never ask the user for a coordinate system and never use EPSG:4326 for
  it (degrees are not metres); check its size is plausible (a site plan is metres to a few km). Only a file that
  must line up with other map data needs place_file, with a projected system in metres. If a file is NOT PLACED
  YET, ask which coordinate system it is in, offering the likely ones listed, call place_file, and check with the
  user that it lands in the right place. Never push technical choices (grid size, coordinate system) on the user:
  choose them from the data (a grid step that divides every given length) and say what you chose. Map data ALREADY IN the domain: call_api POST
  /api/v1/gis/domains/<id>/records/propose {{}} shows which kind of record each layer matches and its key (it writes
  nothing); apply the reviewed mappings with POST /api/v1/gis/domains/<id>/records {{"mappings": [...]}}, say what
  you applied, then use those kinds. Attached files' features
  become records with entities_from_file: key "feature" (or an id
  property), attrs such as {{"location": "geometry", "area_m2": "area_m2", "lon": "lon", "lat": "lat"}}, with
  location declared data_type geometry and the others number.
- You may read existing platform data with call_api GET when the user refers to it.{workbench}

THE PLATFORM'S ORDER -- never skip a step; the plan is refused when one is missing:
 1. MAP DATA: an attached drawing or map file is imported into the domain as map data (local metres for a drawing).
 2. RECORDS: every kind of record the model uses has its records (from the map layers, a file, or generated).
 3. RELATIONSHIPS: every link the model walks exists (which candidate covers which cell, which cell is next to which).
 4. DATA VALUES: every number comes from the user, the data or a calculation -- never a placeholder.
 5. MODEL: only then the rules and goals; then solve.
DATA FIRST (before any model): every kind of record the model uses must get its records from a named source, or
the plan is refused. Sources: (a) an attached file or map layer, loaded in the plan with entities_from_file (a map
layer's rows are its features: key "feature", attrs from its columns -- x_m, y_m, width_m, height_m, area_m2,
geometry...); (b) map data imported into a domain: POST /api/domain/ {{"name"}} for a new one, then POST
/api/v1/gis/datasets {{"upload_id", "domain_id", "name", "placement": the file's placement}}, then POST
/api/v1/gis/datasets/<id>/records/propose and POST .../records with the reviewed plan; build the problem there
with domain_id; (c) numbers the files lack, computed by the platform on records already in a domain: POST
/api/v1/domains/<id>/distances, /within, /derive-value, /api/v1/entity-types/<id>/derive (describe_endpoint
first for their bodies); {generated_sources}
Never invent a number a file or a calculation can give (no placeholder factors); never plan a kind with no source.
A layout problem (where to place items on a drawing: beds, desks, stalls, shelves) is modelled over generated
CANDIDATE positions, not a count per area. When the candidate and cell records should live in the selected domain,
use POST /api/v1/candidate-sets/from-map with the attached drawing's upload_id, domain_id, area/blocked layers,
item sizes and turns, and aisle rule. It generates the records and occupancy links server-side, and returns an IR
that already uses those records; use that IR as the basis for the proposed model. The endpoint can generate selected
polygon indices separately when one request exceeds its candidate limit. For candidate rows supplied by a user or
another service, POST /api/v1/candidate-sets with the explicit attribute schema and rows. Never copy a large
candidate table into the model conversation. {layout_generation} NO OVERLAP,
one rule over cells, never pairs of candidates: forall k in cell: Σ over c in cand {{"via":{{"rel":"occupies",
"to":"k"}}}} of pick[c] <= 1. ACCESS (items reachable from doors, exits, gates): make_layout with access_layers
writes it for you. In any model, "every chosen X is reached from a source through chosen X" is a connected rule
with sources: {{"connected": {{"assign": {{"var": "open", "index": ["u"]}}, "units": {{"index": "u", "set": "cell"}},
"via": "next_to", "sources": "entrance"}}}} (sources: a 0/1 field of the units; no groups needed) -- corridors to
doors, pipes to a supply, roads to a depot. Before proposing, say which areas have no source (they can take nothing).
PARAMETERS ARE NOT CANDIDATES: the parameter API stores fixed numeric inputs (possibly indexed by existing record types); it does not create candidate records or make a parameter value a solver choice. Coordinates stored as parameters still need candidate records and a decision variable such as pick[cand]. A per-zone capacity model is a different, count-only approximation: it does not return placements, and it does not guarantee non-overlap, full-item footprints, or door-connected access unless those properties are explicitly represented and verified. Never present it as equivalent to the agreed layout. If exact candidate generation is too large, report the measured candidate/link counts and ask the user to choose a resolution or explicitly approve a count-only approximation before changing the problem.
For a count-per-zone approximation, the zone set still needs actual zone records, and any connected_to relation still needs actual zone-to-door links. A parameter or parameter API call creates neither records nor links. Do not reuse an empty bed-to-door relationship for zone-to-door access. Use /within only if the user-approved meaning is proximity and both record types have usable geometry; it does not prove a clear corridor path. If the agreed access rule means a walkable path, say that the current approximation cannot certify it and leave the problem unproposed until a valid path model/data source exists.
Keep every agreed rule: a rule you cannot model goes under "Not modelled" in the plan, never silently dropped.
NEVER change an agreed choice on your own (a grid step, a size, a limit, a distance, the data to use): if it makes
the model too big or slow, stop and tell the user the numbers (e.g. "0.1 m gives 347,451 candidates and about 7
million cell links") with the options and what each costs, and wait for their answer. Never invent a threshold the
user did not give (e.g. "within 50 m of a door") -- compute it from the data or ask.

PHASE 2 - PROPOSE: when nothing important is open, run check_spec on your spec and fix every error it reports
(nothing is built and the user sees nothing), then call propose_plan with the same spec.
- summary (markdown the user reads), in the Model Editor's own terms, these headings in this order:
  **Problem** one paragraph in the user's words.
  **Sets** each kind of record: what it is, how many, its fields with units, where the data comes from
  (typed in the chat, or file X / sheet Y). A short table of members when there are few.
  **Parameters** name[index]: meaning, unit, value or source.
  **Variables** name[index]: binary / integer / continuous, and what it means ("assign[v,s] = 1 if van v serves shop s").
  **Rules** one per line: id, in words, then the formula, e.g. "For every shop s: sum over vans v of assign[v,s] = 1
  (hard)"; soft rules with their weight.
  **Goals** minimise/maximise and the formula; several goals with their weights or order.
  **Assumptions** every default you chose.
- spec: exactly what will be built (format below). The server checks it before the user sees it; if it returns
  errors, fix the spec and call propose_plan again. The user then approves (it is built) or replies with changes
  (adjust, then propose again).

PHASE 3 - SOLVE AND REPORT: when the result starts with BUILT, solve it straight away (the result says how), wait
for the run to finish (a run with status "error" FAILED: read its error, tell the user, never queue it again unchanged),
first call inspect_decomposition with the scenario id from BUILT. Independent blocks are solved exactly in parallel
by the platform when eligible; reported near-independent groups with linking rules are diagnostics, not an exact split.
Then call read_result with its id and report whether a block-by-block solve actually ran (never recompute numbers yourself),
then explain in plain language what was built (sets, parameters, variables, rules, goals,
assumptions) and the results. The platform shows a FACTS card above your reply, rendered from the result: the status,
the goal and its parts, the first rows of each decision and the tight or broken rules. Do not retype that card or its
table; explain what it means in the user's terms (larger decision tables beyond its rows may be summarised from
read_result), and for an infeasible run which rules conflict and what to relax. If the user asked for the answer as a map, a drawing or a file, give the links from read_result's EXPORTS line
(a map: GeoJSON and the CAD drawing). A run you start gets 2 minutes unless the user asks for longer; when it ends "feasible" with
a gap, say how far from proven best it is and offer a longer run (time_limit_s, e.g. 600). Name the rules that are TIGHT (they hold the goal back) and,
when read_result has SENSITIVITY, what each costs in the user's units (its "per +1 on <parameter>" line) and how
far that holds -- always with its range ("about 1,018 per +1 %, but only up to 7.14 %"); a rate is never quoted
for a change past its range. How much of a limit is used and how much room is left ("uses 116 of 120, room left
4") is quoted from the RULES lines of read_result or what_if -- never worked out yourself, never assumed "tight". Nothing else can be written in this mode.
WHAT-IFS after the build ("what if fiber could be 8%?", "how much would we save if...", "what if demand rose 10%?"):
call what_if on the Base scenario with the change (set_param for a parameter, set_limit for a rule's limit,
scale_attr / scale_param for "+10%", remove for a record left out) and report its exact difference. Never answer a
what-if from shadow prices unless the change is inside the range read_result gives; never extrapolate past it.
Your reply is final text for the person: no "Wait,", "let me re-check", "Actually" or second thoughts in it --
work numbers out with tools first, then write the answer once.

SPEC
{{"domain_name": "..." or "domain_id": n, "problem_name": "...", "note": "one line", "seed": {{...}}, "ir": {{...}}}}
seed keys (all optional lists):
 entity_types [{{"name","role","attributes":[{{"name","data_type","required","unit","enum_values","default_value"}}]}}]
 relationship_types [{{"name","from":type,"to":type,"cardinality":"many_to_one|one_to_many|many_to_many|one_to_one"}}]
 parameters [{{"name","index":[type names],"default_value":number,"unit"}}]
 entities [{{"type","key","label","attrs":{{attribute: value}}}}]
 relationships [{{"type","from":[type,key],"to":[type,key]}}]
 parameter_values [{{"parameter","entities":[[type,key], ...one per index],"value":number}}]
 entities_from_file [{{"file","sheet","type","key":column,"label":column,"attrs":{{attribute: column}}}}]
 parameter_values_from_file [{{"file","sheet","parameter","entities":[[type, key column], ...],"value":column or a
   number for every row (a file that only lists pairs -- days off asked, bans, skills -- is a 0/1 parameter: "value": 1)}}]
 relationships_from_file [{{"file","sheet","type","from":[type, column],"to":[type, column]}}] (one link per row)
Rows of an attached file are loaded by the *_from_file entries: one record or cell per row. Never copy a file's
rows into entities or parameter_values yourself.
Names are lower_snake_case. role: agent|resource|time|location|task|org|other. data_type: integer|number|text|
boolean|enum (with enum_values)|date|time. A number that belongs to one record is an attribute. A number per
combination of records (demand per day and shift, distance per pair) is a parameter indexed by those types,
with its cells in parameter_values. One number for the whole problem (a budget) is a parameter with index [].
A cell left out is the parameter's default_value.

PROBLEM IR (version 2)
{{"version":2,"sets":[entity types the model uses],"relationships":[relationship types walked; omit if none],
 "parameters":{{name:{{"index":[types, as declared]}}}},
 "variables":{{name:{{"index":[types],"domain":"binary|integer|continuous","lower":n,"upper":n}}}},
 "constraints":[{{"id":"c_...","note":"words","forall":[bindings] (omit when none),"left":term,
   "relation":"<=|=|>=","right":term,"severity":"hard"}} or "severity":"soft" with "weight": positive integer],
 "objective":{{"sense":"minimize|maximize","mode":"weighted|lex","terms":[{{"id":"o_...","weight":integer,"expression":term}}]}}
   (omit for feasibility; "lex" solves the terms in order, first the most important -- each term is one WHOLE
   goal in its own rank, so a cost made of parts (day and night wages) is ONE term adding them; a negative weight in a
   maximize means "less is better")}}
binding: {{"index":"p","set":"project","where":[{{"attr":"district","op":"=","value":"a"}}]}} (op: = != < <= > >= in notIn)
 walking a relationship: {{"index":"i","set":"item","via":{{"rel":"item_group","to":"g"}}}} = the items linked TO g;
 {{"via":{{"rel":"item_group","from":"i"}}}} = what i links to (declare the relationship in "relationships")
term: {{"const":3}} | {{"par":"demand","index":["d","s"]}} | {{"var":"fund","index":["p"]}} | {{"attr":{{"of":"p","name":"cost"}}}}
 | {{"sum":term,"over":[bindings]}} | {{"add":[terms]}} | {{"mul":[term,term]}} (a - b is {{"add":[a,{{"mul":[{{"const":-1}},b]}}]}}; exactly two factors, at most
 quadratic; three factors nest: a*b*x = {{"mul":[{{"mul":[a,b]}},x]}}, e.g. cost per ton x demand x assign)
Every index must be bound by forall or an enclosing over; par/var indices follow their declared order; only
integer/number attributes can be used as numbers; a whole-number decision is "integer" with bounds; ids match
^[a-z][a-z0-9_]*$.
PATTERNS (building blocks, not templates): a value per PAIR limits which pairs may be used (distance per
warehouse and customer <= 450, skill level per worker and task >= 3): load that column as its own parameter
indexed by the pair, e.g. lane_km[warehouse,customer] with parameter_values_from_file, then for every pair
"lane_km[w,c] * assign[w,c] <= 450" (for >=: "level[w,t] >= 3 * assign[w,t]") -- linear, because assign is
binary; one file column per parameter, several *_from_file entries may read the same file; a pair the file
does not list gets the parameter's default_value (set it to forbid: e.g. 999999 km); a number that depends on a
record's kind (night shifts pay 1.3 times): a parameter indexed by that set, pay_factor[shift] (night 1.3, default
1), multiplied in (nested mul); one particular record in a rule: a binding with where [{{"attr":"id","op":"=",
"value":"night"}}]; CONSECUTIVE periods (no morning right after a night): a relationship next_day (day -> day,
one link per pair, typed in "relationships"), then forall n, d, and d2 bound {{"via":{{"rel":"next_day","from":"d"}}}}:
x[n,d,night] + x[n,d2,morning] <= 1; requests to honour if possible: a 0/1 parameter from the list, and a goal
term (or soft rule) counting the cells that break it: sum of asked[n,d] * x[n,d,s]; one per group (sum of pick over the group's items via a relationship
= 1); capacity or budget (sum of amount x size <= limit); cover every demand (sum of open over the sites that
cover it >= 1); one user per shared resource (sum over things occupying it <= 1); link use to opening
(x <= M * y, M as small as valid); ranked goals ("lex" in the user's order, soft rules for targets that may be out
of reach, then report how far short); a MIX or BLEND (feed, alloy, diet, fuel): amount[ingredient] continuous
(kg), Σ amount = batch; a share of a nutrient is linear when multiplied out -- "protein at least 18%" is
{{"left":{{"sum":{{"mul":[{{"attr":{{"of":"i","name":"protein_pct"}}}},{{"var":"amount","index":["i"]}}]}},
"over":[{{"index":"i","set":"ingredient"}}]}},"relation":">=","right":{{"mul":[{{"par":"min_protein"}},
{{"par":"batch_size"}}]}}}} -- note "over" sits BESIDE "sum", never inside it; a stock limit that differs by
record is a rule (forall i: amount[i] <= i.available_kg), not a variable bound (bounds are one number);
a NETWORK FROM A SOURCE (fibre or pipes from an exchange or supply, roads to a depot, corridors to doors: "everything
chosen must join the source along the links"): one binary pick[place] and ONE rule {{"connected": {{"assign":
{{"var":"pick","index":["p"]}},"units":{{"index":"p","set":"place"}},"via":"road","sources":[{{"attr":"kind","op":"=",
"value":"exchange"}}]}}}} -- sources is the where list that picks the start (or a 0/1 field); the relationship is
loaded from the two-column file of links (relationships_from_file). Never write it as "a picked place touches a used
link" or "has a picked neighbour": that lets cut-off islands through. No variable per link is needed;
when the LINKS THEMSELVES are the decision (which cables, roads or pipes to build, at a cost per link -- network
design, a spanning tree): links are records with two relationships to their places (link -> place, one per end),
one binary lay[link], and ONE rule {{"join": {{"links":{{"index":"l","set":"segment"}},"build":{{"var":"lay",
"index":["l"]}},"ends":["seg_a","seg_b"],"places":{{"index":"p","set":"site"}}}}}} -- add "sources" (as above) to
join every place to a source instead of to each other, and "use": {{"var":"serve","index":["p"]}} when only some
places must be joined (a link is then built only between two served places); with every place joined and a goal
that only adds up link costs it is solved exactly as a minimum spanning tree; with sources, "demand" (a number field
of the places: what each takes), "capacity" (of the links), "supply" (of the sources) and "carry" (an integer or
continuous variable per link, which the goal may price per unit) make it a capacitated network design;
SCHEDULING (operations on machines, steps in order, finish as early as possible): one record per operation --
when no column is its key, join columns: "key": ["job","step"] (gives "Gear-1"), and load job and step as its
fields; the order of steps is
"relationships_in_order": [{{"type":"then","of":"op","by":"step","within":"job"}}] in the seed (it links each step
to the next of the same job; declare "then": op -> op in relationship_types); the machine from the same file:
relationships_from_file {{"type":"on","from":["op",["job","step"]],"to":["machine","machine"]}}; the duration a
parameter per op (parameter_values_from_file with "entities": [["op", ["job","step"]]]). Decisions: begin and finish
integer per op, makespan integer, and task {{"index":["op"],"domain":"interval","start":"begin","end":"finish",
"size":"minutes"}}. Rules: {{"id":"c_machine","forall":[{{"index":"m","set":"machine"}}],"no_overlap":{{"interval":
{{"var":"task","index":["o"]}},"over":[{{"index":"o","set":"op","via":{{"rel":"on","to":"m"}}}}]}},"severity":"hard"}};
finish[a] <= begin[b] for b via then from a; finish[o] <= makespan. Goal: minimise makespan. Never invent "sub"
or arithmetic on keys: order comes from relationships_in_order. The same "relationships_in_order" gives the next
day or the next period of any sequence ("wrap": true for a repeating week); "by": "#row" keeps the file's own
row order (month and weekday names sort by the calendar, other text naturally: "P2" before "P10");
STOCK OVER PERIODS (production or inventory plans, stock carried from one period to the next, late delivery or
backorders): periods linked in order ("relationships_in_order": [{{"type":"next","of":"month","by":"#row"}}]);
decisions make[p], stock[p] (left at the end of p) and, when late delivery is allowed, owed[p] (demand still not
delivered at the end of p), all >= 0. ONE balance rule for every period, the PREVIOUS one through the link -- the
binding {{"index":"q","set":"month","via":{{"rel":"next","to":"p"}}}} (q -> p: the month BEFORE p; "from":"p" would be
the month after) -- empty for the first period, so no rule needs "the first": forall p: sum over q of (stock[q] - owed[q]) +
opening[p] + make[p] = p.demand + stock[p] - owed[p] -- opening a parameter per period, default 0, given only for
the first (the starting stock); owed is extra demand, never supply, so it is SUBTRACTED on both sides. Everything
delivered by the end: owed[p] = 0 for the last period (forall p where its name field = the last one). Costs:
make x unit cost + stock x holding cost + owed x lateness cost, each summed over the periods;
DECIDE BEFORE UNCERTAIN DATA ("demand could be anything from 100 to 300", "we only know it later"): declare the
uncertain number in ir.parameters with its spread -- {{"demand":{{"index":[],"uncertainty":{{"kind":"interval",
"deviation":0.5}}}}}} for 200 +/- 50% (evenly likely), or {{"kind":"scenarios","futures":[{{"label":"low","factor":0.7}},
...]}} for named cases -- its value the middle (200); decisions made NOW get "stage": 1 (how many to bake or order),
decisions made once it is known get "stage": 2 (how many sold: sell <= bake, sell <= demand). Build it, then call
what_if on the Base scenario with "futures": 50: that plans for sampled futures; the plain run plans for the
middle value only, so never report it as the answer to "on average";
TWO GOALS THAT PULL APART, "show us the trade-off" (benefit against CO2, cost against service): the goal has
exactly TWO terms, each one whole goal (e.g. maximise with benefit weight 1 and co2 weight -1), hard rules only;
build it, then call what_if on the Base scenario with "front": 10 -- it returns every point of the front with what
each chooses; report those points, never invent compromises or weights;
CUTTING OR PACKING into identical rolls, bins or trucks (fewest rolls, least waste): never write the ways to cut
yourself -- "patterns_that_fit": [{{"type":"pattern","of":"width","size":"width_cm","capacity":100,"count":"cuts"}}]
in the seed makes every way to fill one roll (records "45 x2", "45 + 36 + 14", with fields used and waste) and
cuts[pattern, width] (how many of each width a pattern holds). Decision uses[pattern] integer >= 0; rule forall w:
sum over p of cuts[p, w] x uses[p] >= w.pieces; goal: minimise sum of uses (rolls) or of waste x uses;
ROUTING (trucks from a depot visit places, least distance, capacity, time windows): places with their demand
from the file; the trucks typed as entities with a capacity field (e.g. 3 records "truck1".. with "capacity": 15);
distances from coordinate columns: "distances_from_fields": [{{"name":"distance","of":"place","x":"x_km","y":"y_km"}}]
in the seed (straight lines, in the columns' unit; places from a map use the domain's distances instead); one
binary visit[truck, place, place] and ONE rule {{"id":"c_routes","severity":"hard","route":{{"visit":{{"var":"visit",
"index":["v","i","j"]}},"vehicles":{{"index":"v","set":"truck"}},"stops":{{"index":"i","set":"place"}},"depot":"<the
depot's key>","demand":"<the places' demand field>","capacity":"<the trucks' capacity field>"}}}} (time windows add
"travel":"<a time parameter>","earliest","latest","service": place fields). Goal: minimise the sum over v, i, j of
distance[i, j] * visit[v, i, j]. Never write the visiting, sub-tour or load rules yourself: the route rule holds them.

TOOL CALLS: only through the tool interface, never as text in your reply; valid JSON with unique keys (each list,
e.g. entity_types or constraints, once, with all its items); keep each call small (load rows from files, never
write them out). Keep replies short: never think aloud or draft the spec in a reply; put it straight into
check_spec. When unsure how to write a rule, pick the closest PATTERN, check_spec it, and fix what it reports. If a tool returns an error, change the call; never
repeat it unchanged. Never say something was built, imported, solved or checked unless a tool result in this
turn shows it.

EXAMPLE (a complete, valid spec): "fund the most valuable city projects within 500k; at most two in district A"
{json.dumps(EXAMPLE_SPEC, separators=(",", ":"))}

Today is {time.strftime('%Y-%m-%d')}."""


def system_prompt(index: ApiIndex, ctx: Context, native: bool) -> str:
    attached = agent_files.outline(ctx.files)
    path_tool = ("run_python has networkx too (graphs, paths, connectivity, e.g. which cells reach a door)."
                 if ctx.can_run_python else "")
    tools = list(MODEL_TOOLS if ctx.mode == "model" else TOOLS) + ([sandbox.SCHEMA] if ctx.can_run_python else [])
    if ctx.mode == "model":
        return model_prompt(ctx) + ("\n\n" + attached if attached else "") + \
            ("" if native else text_protocol(tools))
    where = []
    if ctx.page:
        where.append(f"they are on the page {ctx.page}")
    if ctx.domain_id is not None:
        where.append(f"the selected domain id is {ctx.domain_id}")
    if ctx.problem_id is not None:
        where.append(f"the open problem id is {ctx.problem_id}")
    p = f"""You are the Assistant built into the Problem Solver platform (optimization as a service:
domains, entity types and attributes, entities, relationships, parameters, problems, model versions
written in the Problem IR, scenarios, runs and their solutions, maps/GIS, imports, suites,
users and access, settings, operations). You act for the signed-in user "{ctx.username}" through the
platform's own API, with exactly their permissions. {"; ".join(where).capitalize() + "." if where else ""}
"this", "here" and "current" refer to that context.

Endpoint groups (tag (count)): {index.tag_overview()}

How to work:
0. A NEW PROBLEM TO MODEL AND SOLVE (the person describes what to choose, assign, schedule, place or mix, with a goal
   such as most beds or least cost, and no problem for it exists yet): call hand_to_describe at once. Do not create
   kinds of record, records or relationships for it yourself; the Describe a problem tab does all of that.
1. Use only tools listed in the current tool schema; never call an unavailable tool. Make one API call at a time.
   For writes, search_endpoints -> describe_endpoint -> call_api. Never guess a request body; describe it first.
2. Look things up before changing them; use ids you got from the API, never invented ones. A scenario, run or
   problem the person names by its number may be in another workspace than the selected one: use it by that id
   (GET /api/v1/scenarios/{{id}}, read_result, what_if) -- never say it does not exist without that lookup.
   describe_workspace gives a domain's whole contents (kinds of record, fields, relationships, data values,
   map data, problems, data sources) in one call: start there. A data source (a database table) is read with
   use_source, which attaches it as a sheet for read_file / query_file. When the person says a source's data
   changed, or asks to solve again with current data: refresh_sources (apply=false) shows what would change;
   show it and ask; on yes apply=true; then solve the scenario again and say how the answer changed.
3. Before writing or changing a model (IR), read_doc('contracts/problem-ir.md').
4. Solving is asynchronous: POST /api/v1/scenarios/{{id}}/runs queues a run; poll GET /api/v1/runs/{{id}}
   with wait between polls until it settles, then read_result(run_id) and report from it.
   The body may name a solver ({{"solver": "networkx"}}); leave it out and the platform chooses. A network
   model (transport, assignment, shortest path, max flow: each rule flow in less flow out, numbers whole) is
   solved by NetworkX's network simplex anyway; ask for "networkx" by name only when the user wants it.
    {path_tool}
   When asked to split or parallelize a problem, call inspect_decomposition for its scenario first. The platform
   solves truly independent compiled blocks exactly and in parallel when eligible. If the report names linking
   rules, those parts are coupled: do not claim an exact split or create child models that drop those constraints.
   Explain the coupling and offer an approximate decomposition only if the user explicitly requests one.
   The answer downloads as files: /api/v1/runs/{{id}}/export?format=xlsx|csv|geojson|dxf|pdf. dxf is a CAD drawing
   on the domain's drawing, in its own coordinates (chosen items on <decision>-CHOSEN layers): offer it for a
   layout or any answer on a drawing.
5. On a 4xx, read the detail, fix the request and retry; a 422 names the bad field. A 403 means the
   user lacks the capability: say which, don't work around it.
6. Delete or remove only what the user clearly asked to.
7. A MAP FILE attached (see ATTACHED FILES) goes on the map with POST /api/v1/gis/domains/{{domain_id}}/datasets
   {{"upload_id", "name", "placement": {{"kind": "epsg", "code": n}}, "layers": [...] (optional)}};
   the equivalent POST /api/v1/gis/datasets takes `domain_id` in the body;
   records from its layers with POST /api/v1/gis/datasets/{{id}}/records/propose, then .../records with that plan.
   To map ALL of a domain's map data onto its kinds of record at once (matched by shared record keys, name and
   fields; features that name a record update it, the rest are added): POST /api/v1/gis/domains/{{id}}/records/propose
   {{}} (writes nothing; "choices" [{{"dataset_id","layer","type","key"}}] change a layer), show the user the
   mappings, then POST /api/v1/gis/domains/{{id}}/records {{"mappings": [...]}} with the reviewed ones.
   If it is NOT PLACED YET, ask the user for the coordinate system first (offer the likely ones) and use place_file.
8. Finish with a short, plain answer: what you did, key ids and numbers, a markdown table for lists.
   Mention where in the app to look (e.g. "Runs page"). Don't show raw JSON unless asked.
Tool calls go through the tool interface only, never as text in your reply, as valid JSON with unique keys.
Never say something was created, changed or solved unless a tool result in this turn shows it.
Today is {time.strftime('%Y-%m-%d')}."""
    return p + ("\n\n" + attached if attached else "") + ("" if native else text_protocol(tools))


_TOTALS_LINE = re.compile(r"Totals (?:over the \d+ chosen|of field x \w+): (.+)")
_TOTAL_ITEM = re.compile(r"([a-z_][a-z0-9_]*) (-?\d[\d,]*(?:\.\d+)?)")
_FIGURE_TEXT = r"(\d[\d,]*(?:\.\d+)?)"


def _figure(text: str) -> float:
    return float(text.replace(",", ""))


def _when_next(next_at: Any) -> str:
    """A schedule's next run in words: "the first run starts now" when it is due, else the time in UTC (the
    distribution test, October 2026: a run due at once was told to the person as a later time, with no zone)."""
    from datetime import datetime, timezone

    try:
        when = datetime.fromisoformat(str(next_at).replace("Z", "+00:00"))
    except ValueError:
        return f"next run {next_at}"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if (when - datetime.now(timezone.utc)).total_seconds() <= 120:
        return "the first run starts now (within a minute), then on this schedule"
    return "next run " + when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def trial_said(trial: Any) -> str:
    """The plan's trial solve, in words, with what to look at (the field tests: plans that passed every check and
    did something else than meant -- a trial on the real data shows it before the person approves)."""
    if not isinstance(trial, dict):
        return ""
    status = str(trial.get("status"))
    if status in ("not compiled", "skipped", "no solver", "failed"):
        return f"\n\nTRIAL SOLVE: {status}" + (f" ({trial.get('why')})" if trial.get("why") else "")
    used = trial.get("used") or {}
    parts = ", ".join(f"{v} {u.get('non_zero')} of {u.get('cells')} cells non-zero"
                      + (f" ({', '.join(u['chosen'])})" if u.get("chosen") else "") for v, u in used.items())
    goal = trial.get("objective")
    line = (f"\n\nTRIAL SOLVE (this plan on its real data, {trial.get('seconds')} s, nothing kept): {status}"
            + (f", goal {_amount_text(float(goal))}" if isinstance(goal, (int, float)) else "") + f"; {parts}.")
    flags = []
    if status == "infeasible":
        flags.append("the plan has NO answer on this data: a rule (often a balance or a link read the wrong way) "
                     "cannot hold; find it before proposing")
    elif status == "unbounded":
        flags.append("the goal can grow without limit: a bound or a rule is missing")
    elif used and all(not u.get("non_zero") for u in used.values()):
        flags.append("every decision is 0: the plan chooses or makes nothing -- check the goal's sense and the rules")
    if flags:
        line += " WARNING: " + "; ".join(flags) + "."
    if any(u.get("chosen") for u in used.values()):
        line += (" The cells named are the trial's own choice: when the summary mentions the trial, name exactly "
                 "these, never others.")
    return line + (" Check this against what the person described (does the goal and what is used make sense?) "
                   "before proposing; say the trial result in the plan.")


def trial_for_person(trial: Any) -> str:
    """The trial solve as one line of the plan card (the production test: a plan carrying stock from the month
    after made in 3 of 6 months and was late in 5 -- visible at once beside a plan that makes in all 6)."""
    if not isinstance(trial, dict) or trial.get("status") in (None, "skipped", "not compiled", "no solver", "failed"):
        return ""
    used = trial.get("used") or {}
    goal = trial.get("objective")
    line = (f"\n- TRIAL on your data (solved once, nothing kept): {trial.get('status')}"
            + (f", goal {_amount_text(float(goal))}" if isinstance(goal, (int, float)) else "")
            + ("; " + ", ".join(f"{v} used in {u.get('non_zero')} of {u.get('cells')}"
                                + (f" ({', '.join(u['chosen'])})" if u.get("chosen") else "") for v, u in used.items())
               if used else ""))
    if trial.get("status") == "infeasible":
        line += " -- NO answer exists with these rules and data"
    elif used and all(not u.get("non_zero") for u in used.values()):
        line += " -- it chooses or makes nothing"
    return line


def stale_totals(answer: str, tool_texts: list[str]) -> list[tuple[str, str, str]]:
    """Totals in the answer that are near, but not, what the tools of this turn gave: (said, right, field).

    The fibre test (October 2026): the Assistant once added up 12 places' households itself (1,770 for
    1,870), and kept repeating its own number in later answers although every tool result said 1,870."""
    given: dict[str, set[float]] = {}
    for text in tool_texts:
        for line in _TOTALS_LINE.findall(text):
            for field, value in _TOTAL_ITEM.findall(line):
                given.setdefault(field, set()).add(_figure(value))
    if not given:
        return []
    every_number = {_figure(n) for text in tool_texts for n in re.findall(_FIGURE_TEXT, text)}
    found = []
    for field, values in given.items():
        word = re.escape(field.replace("_egp", "").replace("_", " "))
        patterns = (rf"{_FIGURE_TEXT}(?:\W+\w+){{0,2}}?\W+{word}", rf"{word}\W{{1,12}}{_FIGURE_TEXT}")
        for pattern in patterns:
            for said in re.findall(pattern, answer, re.I):
                n = _figure(said)
                if n in every_number:
                    continue
                near = next((v for v in values if v and 0 < abs(n - v) / abs(v) <= 0.1), None)
                if near is not None:
                    found.append((said, f"{near:,.0f}" if near == int(near) else f"{near:,.2f}", field))
    return list(dict.fromkeys(found))

_PROVEN = re.compile(r"\b(?:optimal|optimum|proven best|best possible (?:answer|plan|solution|result)|"
                     r"cannot be improved|can't be improved|no better (?:answer|plan|solution) (?:exists|is possible))\b",
                     re.I)
_ROOM_LINE = re.compile(r"^- (\w+) \((?:hard|soft)\): held, tight \(no room left on (\d+) of (\d+): ([^)]*)\);"
                        r".*?room left on the others: (.+)$", re.M)
_ALL_FULL = re.compile(r"\b(?:every|all|each|always|in all|throughout)\b[^.\n]{0,60}\b(?:full|fully (?:used|utili[sz]ed)|"
                       r"tight|at capacity|maxed|exactly met|no (?:room|surplus|slack|spare))\b|\b(?:full|fully "
                       r"(?:used|utili[sz]ed)|tight|at capacity|no (?:room|surplus|slack|spare))\b[^.\n]{0,40}\b(?:every|"
                       r"all|each)\b", re.I)


def _decision_tables(texts: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """The DECISION tables of read_result: (header cells, rows of cells)."""
    out = []
    for text in texts:
        for block in re.split(r"\n(?=DECISION )", text):
            lines = block.splitlines()
            if not lines or not lines[0].startswith("DECISION ") or len(lines) < 3 or " | " not in lines[1]:
                continue
            header = [c.strip() for c in lines[1].split(" | ")]
            rows = []
            for line in lines[2:]:
                cells = [c.strip() for c in line.split(" | ")]
                if len(cells) != len(header):
                    break
                rows.append(cells)
            out.append((header, rows))
    return out


def _amount_text(x: float) -> str:
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def _cell_number(cell: str) -> float | None:
    try:
        return float(cell.replace(",", ""))
    except ValueError:
        return None


def reply_contradictions(answer: str, tool_texts: list[str]) -> list[str]:
    """What the answer says that the results of this turn contradict, each as one sentence for the model.

    The live tests (October 2026), one in every reply: "capacity is fully used every month" when June had 50 spare;
    "every order met exactly, no surplus" when three widths were over; a schedule row giving an operation the wrong
    machine although its times were right. Two checks, both on the result text the model was given:
    - a claim that a limit is full everywhere, when the results list room left on some records;
    - a table row whose record the results identify (same name, at least two of its numbers) but whose category
      (machine, site, type...) the results give differently."""
    found: list[str] = []
    # "Optimal" needs a proof (plan of 8 October 2026, honest answers, step 3): when every run the results report
    # stopped without one, the answer may not call it optimal, best possible or impossible to improve.
    statuses = re.findall(r"^RUN \d+: (\w+);", "\n".join(tool_texts), re.M)
    if statuses and "optimal" not in statuses and "feasible" in statuses:
        for claim in _PROVEN.finditer(answer):
            before = answer[max(0, claim.start() - 30):claim.start()].lower()
            if not re.search(r"\b(?:not|never|no|isn't|is not|un|without|before)\b[^.]*$", before):
                found.append(f"it calls the answer \"{claim.group(0)}\", but the run stopped without proving it best "
                             "(status feasible): say how far from the bound it may be, and offer a longer run")
                break
    rooms = _ROOM_LINE.findall("\n".join(tool_texts))
    if rooms and _ALL_FULL.search(answer):
        for rule, full, total, _, rest in rooms:
            if int(full) < int(total):
                found.append(f"it says a limit is full or tight everywhere, but the results say {rule} has room left "
                             f"on {int(total) - int(full)} of {total}: {rest.strip()[:200]}")
    # Tasks on one-at-a-time resources, from RESOURCES: (task key, start, end) -> resource.
    placed: dict[tuple[str, float, float], str] = {}
    for text in tool_texts:
        for resource, order in re.findall(r"^- (.+?): \d+ tasks, busy .*?; in order: (.+)$", text, re.M):
            for key, a, b in re.findall(r"(\S+(?: \S+)*?) (-?[\d,.]+)-(-?[\d,.]+)(?:, |$)", order):
                placed[(key, float(a.replace(",", "")), float(b.replace(",", "")))] = resource
    resources = set(placed.values())
    if placed:
        for line in answer.splitlines():
            cells = [c.strip(" *`") for c in re.split(r"\t|\|", line) if c.strip(" *`")]
            said = [c for c in cells if c in resources]
            numbers = [n for n in (_cell_number(c) for c in cells) if n is not None]
            if len(said) != 1 or len(numbers) < 2:
                continue
            words = [c.lower() for c in cells if _cell_number(c) is None and c not in resources]
            for (key, a, b), resource in placed.items():
                if a in numbers and b in numbers and resource != said[0] and \
                        all(w in key.lower() or any(p.lower() == w for p in re.split(r"[-_ ]", key)) for w in words) \
                        and all(str(int(n)) in re.split(r"[-_ ]", key) for n in numbers
                                if n not in (a, b) and n == int(n) and n < 100 and str(int(n)) in key):
                    found.append(f"the row \"{' | '.join(cells)[:120]}\" puts {key} ({_amount_text(a)}-{_amount_text(b)}) "
                                 f"on {said[0]}, but the results put it on {resource}")
    tables = _decision_tables(tool_texts)
    categories: list[tuple[int, int, set[str]]] = []  # (table, column, values)
    for t, (header, rows) in enumerate(tables):
        for col in range(1, len(header)):
            values = {r[col] for r in rows if r[col]}
            if 1 < len(values) <= 30 and all(_cell_number(v) is None for v in values):
                categories.append((t, col, values))
    if not categories:
        return found
    for line in answer.splitlines():
        cells = [c.strip(" *`") for c in re.split(r"\t|\|", line) if c.strip(" *`")]
        if len(cells) < 3:
            continue
        numbers = {n for n in (_cell_number(c) for c in cells) if n is not None}
        words = [c for c in cells if _cell_number(c) is None]
        for t, col, values in categories:
            said = [w for w in words if w in values]
            if len(said) != 1:
                continue
            names = [w for w in words if w not in values]
            header, rows = tables[t]
            matches = [r for r in rows
                       if all(any(n.lower() in c.lower() for c in r) for n in names)
                       and len(numbers & {x for x in (_cell_number(c) for c in r) if x is not None}) >= 2]
            given = {r[col] for r in matches}
            if names and len(given) == 1 and said[0] not in given:
                right = next(iter(given))
                found.append(f"the row \"{' | '.join(cells)[:120]}\" gives {header[col]} {said[0]}, but the results give "
                             f"{right} for that record")
    return list(dict.fromkeys(found))


_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
_ROUGH = re.compile(r"(?:about|around|roughly|nearly|almost|approximately|approx\.?|over|under|some|more than|less "
                    r"than|~)\s*$", re.I)
#: Numbers that name or date something rather than state an amount.
_NOT_AMOUNTS = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b|"
                          r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
                          r"\b(?:run|runs|scenario|version|v|step|id|#|no\.|number|row|item|option|part|section|"
                          r"workspace|domain|problem|connection|job|file)\s*#?\d[\d,]*\b|"
                          r"\b\w*[A-Za-z_]\d[\w-]*\b|\b\d+(?:st|nd|rd|th)\b", re.I)
_ANSWER_NUMBER = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)(?:\s*(%|percent\b|k\b|thousand\b|m\b|mn\b|million\b|"
                            r"bn\b|billion\b))?", re.I)
_REPORTS_RUN = re.compile(r"^(?:RUN \d+: |BASE goal )", re.M)
#: The most numbers a check pairs with each other (results this size are already summarised).
PAIRED_AT_MOST = 4000


def _numbers_in(text: str) -> list[float]:
    out = []
    for raw in re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def unsupported_numbers(answer: str, results: list[str], person: list[str]) -> list[str]:
    """Amounts in the answer that neither the results nor the person gave, and that no single step makes from them.

    The plan for honest answers (October 2026): every number the model writes must come from this turn's results
    (or the conversation's), the person's own words, or one step of arithmetic on them -- a sum, difference,
    product or ratio of two, or a percentage or percentage change. Rounding as shown is allowed ("about 1,900" for
    1,939). What is left was made up, or added up wrongly, and is sent back before the person sees it. Dates, times,
    names with digits (P3, Q2), record numbers ("run 132") and small whole numbers (counts up to 12) are not
    checked."""
    import bisect

    given = sorted(set(_numbers_in("\n".join(results)) + _numbers_in("\n".join(person))))
    if not given:
        return []
    paired = sorted(set(_numbers_in("\n".join(results))))
    if len(paired) > PAIRED_AT_MOST:
        paired = []
    # Column totals of the result tables: "total 3,020" is often the sum of a column.
    for header, rows in _decision_tables(results):
        for col in range(len(header)):
            column = [_cell_number(r[col]) for r in rows]
            if column and all(x is not None for x in column):
                given.append(sum(column))
    given.sort()

    def near(target: float, tol: float, pool: list[float]) -> bool:
        i = bisect.bisect_left(pool, target - tol)
        return i < len(pool) and pool[i] <= target + tol

    text = _NOT_AMOUNTS.sub(lambda m: " " * len(m.group(0)), answer)
    # A condition's own numbers ("if demand rose to 220, ...") are an assumption, not a claim: the amounts said to
    # follow from it are checked by `unsupported_what_ifs` (the replay set, October 2026: "220" was sent back).
    text = re.sub(r"[^.!?\n]+", lambda s: _HYPOTHESIS.sub(lambda h: " " * len(h.group(0)), s.group(0))
                  if _COUNTERFACTUAL.search(s.group(0)) else s.group(0), text)
    flagged: list[str] = []
    for m in _ANSWER_NUMBER.finditer(text):
        raw, unit = m.group(1).rstrip(","), (m.group(2) or "").lower()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not unit and decimals == 0 and abs(value) <= 12:
            continue
        if not decimals and 1900 <= value <= 2100 and "," not in raw:
            continue  # a year
        scale = _SCALE.get(unit, 1.0)
        rough = bool(_ROUGH.search(text[max(0, m.start() - 20):m.start()]))
        step = 10.0 ** -decimals
        if not decimals and rough:
            digits = raw.replace(",", "").lstrip("-")
            step = 10.0 ** (len(digits) - len(digits.rstrip("0")))
        tol = (0.5 * step + 1e-9) * scale + 1e-9 * abs(value * scale)
        target = value * scale
        percent = unit in ("%", "percent")
        if near(target, tol, given) or (percent and near(target / 100, tol / 100, given)):
            continue
        ok = False
        for a in paired:
            # b from a: a + b, a - b, b - a, a * b, a / b, b / a, and a percentage of, or change from, b.
            tries = [(target - a, lambda b: a + b), (a - target, lambda b: a - b), (a + target, lambda b: b - a)]
            if a:
                tries += [(target / a, lambda b: a * b)]
            if target:
                tries += [(a / target, lambda b: a / b if b else None)]
            tries += [(target * a, lambda b: b / a if a else None)]
            if percent and target:
                tries += [(100 * a / target, lambda b: 100 * a / b if b else None)]
                if target != -100:
                    tries += [(100 * a / (target + 100), lambda b: 100 * (a - b) / b if b else None)]
            for b, made in tries:
                i = bisect.bisect_left(paired, b - abs(b) * 1e-6 - 1e-9)
                for j in (i - 1, i, i + 1):
                    if 0 <= j < len(paired):
                        got = made(paired[j])
                        if got is not None and abs(got - (target if not percent else value)) <= tol:
                            ok = True
                            break
                if ok:
                    break
            if ok:
                break
        if not ok:
            flagged.append(raw + ("%" if percent else (" " + unit if unit else "")))
    return list(dict.fromkeys(flagged))


_RULE_AT = re.compile(r"^\s*([\w.\-]+)\s*(?:\[\s*(.*?)\s*\])?\s*$")


def limit_as_param(ir: dict, key: str, value: Any) -> dict | None:
    """`set_limit` on a rule (or one instance of it, "rule[A]" / "rule [A, 2]") whose limit is a single data
    value (`demand[m]`): the same change made through that value for that instance, as a set_param item. None
    when the limit is a plain number (set_limit changes it) or anything more than one value."""
    m = _RULE_AT.match(key)
    if not m:
        return None
    rule = next((c for c in ir.get("constraints") or [] if isinstance(c, dict) and c.get("id") == m.group(1)), None)
    if rule is None:
        return None
    at = [v.strip().strip("'\"") for v in m.group(2).split(",")] if m.group(2) else []
    names = [str(f.get("index")) for f in rule.get("forall") or [] if isinstance(f, dict)]
    if len(at) != len(names):
        return None
    where = dict(zip(names, at))
    for side in ("right", "left"):
        term = rule.get(side)
        if isinstance(term, dict) and set(term) <= {"par", "index"} and "par" in term:
            index = [where.get(str(i), str(i)) for i in term.get("index") or []]
            if all(str(i) in where or str(i) not in names for i in term.get("index") or []):
                return {"param": str(term["par"]), "index": [str(i) for i in index], "value": value}
    return None


#: A scenario or run the person names by its number ("scenario 53", "run #144").
_NAMED = re.compile(r"\b(scenario|run)s?\s*(?:is\s+|was\s+|=\s*|:\s*)?(?:#|no\.?\s*|number\s+|id\s+)?(\d{1,9})\b",
                    re.I)
_COUNTERFACTUAL = re.compile(r"\b(?:would|could)\b", re.I)
_HYPOTHESIS = re.compile(r"\b(?:if|by (?:adding|raising|increasing|reducing|lowering|cutting|removing)|with (?:an? )?"
                         r"(?:extra|more|additional|another))\b[^,;:]*?(?=,|;|:|\bthen\b|\bwould\b|\bcould\b|$)", re.I)
_SENS_LIMIT = re.compile(r"limit (?P<now>-?[\d,.]+)[^:\n]*: each \+1 on the limit changes the goal by (?P<rate>[-+]?[\d,.]+(?:e[-+]?\d+)?)"
                         r"[^\n]*?holds while the limit stays from (?P<lo>-?[\d,.]+|-∞) to (?P<hi>-?[\d,.]+|∞)")
_SENS_PARAM = re.compile(r"per \+1 on \S+ \(now (?P<now>-?[\d,.]+)\): limit \+[\d,.]+, goal (?P<rate>[-+]?[\d,.]+(?:e[-+]?\d+)?); "
                         r"holds for \S+ from (?P<lo>-?[\d,.]+|-∞) to (?P<hi>-?[\d,.]+|∞)")


def _ranged_rates(texts: list[str]) -> list[tuple[float, float, float, float]]:
    """The SENSITIVITY rates read_result gave: (goal change per +1, value now, lowest, highest it holds for)."""
    def num(raw: str) -> float:
        return {"-∞": float("-inf"), "∞": float("inf")}.get(raw) or float(raw.replace(",", ""))

    out = []
    for text in texts:
        for pattern in (_SENS_LIMIT, _SENS_PARAM):
            for m in pattern.finditer(text):
                try:
                    out.append((num(m["rate"]), num(m["now"]), num(m["lo"]), num(m["hi"])))
                except ValueError:
                    continue
    return out


def unsupported_what_ifs(answer: str, tool_texts: list[str], person: list[str]) -> list[str]:
    """Amounts an answer says would follow from a change ("it would save 5,000 if capacity rose by 10") that no
    what-if run and no sensitivity rate inside its range gives.

    Plan of 8 October 2026, honest answers: "would save X if" needs a what-if, or a shadow price within its range.
    In a sentence that says would/could under a condition, the condition's own numbers are the hypothesis and
    are not checked; every other amount must be a number the tools or the person gave, one step of arithmetic on
    a what-if run's numbers (its base and changed goals), or a SENSITIVITY rate times a change that keeps inside
    the range it holds for. A rate taken past its range is exactly what is sent back (the blend test: -1.018 per
    kg-% quoted for 7 % -> 8 %, past the 7.142 % it holds to)."""
    whatifs = [t for t in tool_texts if "WHAT-IF '" in t or "BASE goal " in t]
    rates = _ranged_rates(tool_texts)
    flagged: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        if not _COUNTERFACTUAL.search(sentence) or not _HYPOTHESIS.search(sentence):
            continue
        claim = _HYPOTHESIS.sub(lambda m: " " * len(m.group(0)), sentence)
        for raw in unsupported_numbers(claim, whatifs, tool_texts + person) if (whatifs or tool_texts or person) else []:
            percent = raw.endswith("%")
            try:
                value = abs(float(raw.split()[0].rstrip("%").replace(",", "")))
            except ValueError:
                continue
            inside = not percent and any(
                rate and ((now + value / abs(rate) <= hi + 1e-9) or (now - value / abs(rate) >= lo - 1e-9))
                for rate, now, lo, hi in rates)
            if not inside:
                flagged.append(raw)
    return list(dict.fromkeys(flagged))


class Agent:
    def __init__(self, settings: Settings, index: ApiIndex, call: CallFn, ctx: Context):
        # The context the server really has (it may have been raised to 64k), not only the configured one.
        self.s = replace(settings, context=server_context(settings)) if settings.enabled else settings
        # Everything sized by the context the server has (262k on the Qwen3.5 server): a tool result may be
        # an eighth of it, and a reply a quarter, never more than configured -- on 32k the old sizes hold.
        self.s = replace(self.s, result_chars=max(self.s.result_chars, self.s.context // 2))
        self.index = index
        self.call = call
        self.ctx = ctx
        self.modelling = ctx.mode == "model"
        self.tools = list(MODEL_TOOLS if self.modelling else TOOLS)
        if ctx.can_run_python:
            self.tools.append(sandbox.SCHEMA)
        self.tool_names = {t["function"]["name"] for t in self.tools}
        self.did_work = False  # a tool changed or made something this turn (what a reply may claim)
        self.reply_tokens = min(settings.plan_max_tokens if self.modelling else settings.max_tokens,
                                max(2048, self.s.context // 4))
        self.built: dict | None = None
        self.messages: list[dict] = []
        self.events: list[dict] = []  # raised by a tool, sent after its result (a re-placed file)
        self.facts: dict[Any, dict] = {}  # runs read this turn: their facts, shown beside the answer
        self.handover: str | None = None  # set by hand_to_describe: the turn ends with the offer
        self.joined: list[str] = []
        self._spec_seen: dict[str, int] = {}
        self.refusals: dict[str, int] = {}
        self.api_rejections: dict[str, int] = {}
        self.total_api_rejections = 0
        import threading
        self.cancelled = threading.Event()
        self.tool_failures: dict[str, int] = {}
        self._typed_cells = 0  # parameter values the last spec typed itself (not loaded from files)  # each spec refusal seen this turn, by its text
        self.solves: dict[str, int] = {}  # solves queued this turn, per scenario  # keys the model gave twice and the platform joined (toolcall.strict_loads)

    def _asking(self, call: dict) -> str:
        """What a call the person must allow will do, in words (the refresh test, October 2026: the box asking
        "Allow this?" for a tool other than call_api was empty)."""
        name, args = call["function"]["name"], _args(call)
        if name == "call_api":
            return f'{str(args.get("method", "GET")).upper()} {args.get("path", "")}'
        if name == "refresh_sources":
            pending = getattr(self, "_refresh_pending", None) or self._reported_refresh(
                args.get("domain_id") or self.ctx.domain_id) or {}
            n = pending.get("changes")
            return ("Write the changes just reported from the data sources into this workspace"
                    + (f" ({n} change{'s' if n != 1 else ''})" if isinstance(n, int) else "")
                    + "; records a source no longer has are set inactive, not deleted.")
        if name == "schedule_refresh":
            hours = int(args.get("every_hours") or 0)
            every = {24: "every day", 168: "every week"}.get(hours, f"every {hours} hours")
            if args.get("enabled") is False:
                return "Pause the scheduled refresh of this workspace."
            return (f"Refresh this workspace from its sources {every}, as you; "
                    + ("apply the changes" + (" and solve its scenarios again" if args.get("solve") else "")
                       if args.get("mode") == "apply" else "keep a report of what changed for you to apply") + ".")
        if name == "what_if":
            return (f'Make a what-if copy of scenario {args.get("scenario_id")} named "{args.get("name", "")}" and solve '
                    "it; the base scenario is not changed.")
        return name.replace("_", " ")

    def _needs_ok(self, call: dict) -> bool:
        if call["function"]["name"] == "propose_plan":
            return True  # its OK is the person's approval of the plan
        if call["function"]["name"] == "what_if":
            return self.s.confirm == "write"  # a new scenario and a run; the base is never changed
        if call["function"]["name"] == "schedule_refresh":
            return True  # it acts on the workspace later, as the person: they agree first
        if call["function"]["name"] == "refresh_sources":
            # It changes the workspace's records: the person agrees first -- when there is a report to apply
            # (without one, apply only reports, writing nothing).
            return bool(_args(call).get("apply")) and bool(
                getattr(self, "_refresh_pending", None)
                or self._reported_refresh(_args(call).get("domain_id") or self.ctx.domain_id))
        if call["function"]["name"] != "call_api":
            return False
        method = str(_args(call).get("method", "GET")).upper()
        if self.modelling and method != "POST":
            return False  # refused outright in this mode; nothing to ask about
        return (self.s.confirm == "write" and method != "GET") or (self.s.confirm == "delete" and method == "DELETE")

    def run_tool(self, name: str, args: dict) -> str:
        if self.cancelled.is_set():
            return "Refused: this turn was stopped; no new action was started."
        lim = self.s.result_chars
        try:
            if name == "search_endpoints":
                return clip(self.index.search(args.get("query", ""), args.get("method")), lim)
            if name == "describe_endpoint":
                return clip(self.index.describe(str(args.get("method", "GET")), str(args.get("path", ""))), lim)
            if name == "describe_schema":
                return clip(self.index.schema(str(args.get("name", ""))), lim)
            if name == "read_doc":
                return read_doc(str(args.get("path", "")), int(args.get("offset") or 0), lim)
            if name == "wait":
                time.sleep(max(1, min(30, int(args.get("seconds") or 3))))
                return "ok"
            if name == "place_file":
                return self._place(str(args.get("file", "")), args.get("epsg"))
            if name == "use_source":
                return self._use_source(str(args.get("source", "")).strip(), bool(args.get("refresh")),
                                        args.get("domain_id"))
            if name == "refresh_sources":
                return self._refresh_sources(args)
            if name == "schedule_refresh":
                domain = args.get("domain_id") or self.ctx.domain_id
                if not domain:
                    return "Could not: no workspace (domain) is selected."
                body = {k: args[k] for k in ("every_hours", "mode", "solve", "enabled") if k in args}
                res = self.call("PUT", f"/api/v1/domains/{int(domain)}/refresh-schedule", None, body)
                if not res.get("ok"):
                    return "Could not set the schedule: " + clip(res.get("body"), 600)
                got = (res.get("body") or {}).get("schedule") or {}
                return (f"SCHEDULED: every {got.get('every_hours')} h, mode {got.get('mode')}, solve again "
                        f"{bool(got.get('solve'))}, {'on' if got.get('enabled') else 'paused'}; "
                        f"{_when_next(got.get('next_at'))}. It runs as the person, with their permissions; "
                        "describe_workspace shows its last run. Tell the person (say the time exactly as written "
                        "here, with its time zone), and that the Sources page shows each run's report.")
            if name == "describe_workspace":
                domain = args.get("domain_id") or self.ctx.domain_id
                if not domain:
                    return clip({"note": "No domain is selected; these are the domains you can use. Ask which one, "
                                         "or make a new one in the plan (domain_name).",
                                 "domains": self.call("GET", "/api/domain/", {"limit": 100}).get("body")}, lim)
                res = self.call("GET", "/api/v1/agent/workspace", {"domain_id": int(domain)})
                return clip(res.get("body") if res.get("ok") else res, lim)
            if name == "inspect_decomposition":
                scenario_id = int(args.get("scenario_id") or 0)
                if scenario_id < 1:
                    return "Give the id of an existing scenario from the workspace or the build result."
                res = self.call("GET", f"/api/v1/scenarios/{scenario_id}/preflight")
                body = res.get("body") if isinstance(res, dict) else None
                if not res.get("ok"):
                    return clip(res, lim)
                if not isinstance(body, dict):
                    return "The preflight did not return a decomposition report."
                return clip({"scenario_id": scenario_id, "ready": body.get("ready"),
                             "structure": body.get("structure"), "findings": body.get("findings", []),
                             "planner": body.get("planner", [])}, lim)
            if name == "read_output":
                return self._read_output(args)
            if name == "make_layout":
                return self._make_layout(args)
            if name == "hand_to_describe":
                if self.modelling:
                    return "You are already in Describe a problem mode: carry on with the interview."
                self.handover = str(args.get("reason") or "").strip()[:400] or "This is a problem to model and solve."
                return "Handed over: the person is offered the Describe a problem tab with their message and files."
            if name == "what_if":
                return self._what_if(args)
            if name == "read_result":
                res = self._read_run(int(args.get('run_id') or 0))
                body = res.get("body") if isinstance(res, dict) else None
                return clip(body.get("text") if res.get("ok") and isinstance(body, dict) else res, lim)
            if name == "check_spec":
                if name not in self.tool_names:
                    return f"{name} is not available in this mode"
                return self._check_spec(args)
            if name == "run_python":
                return self._run_python(str(args.get("code") or ""), args.get("timeout_s"))
            if name == "query_file":
                return agent_files.query(self.ctx.files, str(args.get("file", "")), args.get("sheet"),
                                         args.get("where") or [], args.get("group_by") or [],
                                         args.get("aggregate") or None, args.get("columns") or None,
                                         int(args.get("limit") or 50))
            if name == "read_file":
                return agent_files.read(self.ctx.files, str(args.get("file", "")), args.get("sheet"),
                                        int(args.get("offset") or 0), int(args.get("limit") or 50))
            if name in ("call_api", "propose_plan") and name not in {t["function"]["name"] for t in self.tools}:
                return f"{name} is not available in this mode"
            if name == "call_api":
                method = str(args.get("method", "GET")).upper()
                path = "/" + str(args.get("path", "")).lstrip("/")
                # Treat a trailing slash as the same API route for both policy
                # checks and dispatch. The candidate APIs are documented
                # without a slash, but assistants commonly add one; the guard
                # used to reject that valid data-preparation request before
                # FastAPI could apply its normal redirect.
                route, separator, query_string = path.partition("?")
                route = route.rstrip("/") or "/"
                path = route + (separator + query_string if separator else "")
                if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    return f"unsupported method {method}"
                if method == "POST" and path.split("?")[0] == "/api/v1/problems/from-spec":
                    if not self.modelling:
                        self.handover = "Building a model is done in the Describe a problem tab."
                    return ("Refused: problem creation must go through Describe a problem mode, which validates the "
                            "model and shows it for approval before building. Switch to that mode and continue "
                            "with the current conversation; do not create a problem directly through call_api.")
                if any(b.match(path.split("?")[0]) for b in BLOCKED_PATHS):
                    return "That endpoint is not available to the assistant."
                if self.modelling and method != "GET" and not (
                        (method == "POST" and READ_ONLY_POST.match(path.split("?")[0])) or
                        (method == "POST" and DATA_POST.match(path.split("?")[0])) or
                        (method == "POST" and SOLVE_PATH.match(path.split("?")[0])
                         and (self.built or self._scenario_exists(path.split("?")[0])))):
                    if method == "POST" and re.fullmatch(r"/api(?:/v1)?/domains?", path.split("?")[0]):
                        return ("Refused: do not create the workspace (domain) with call_api. Put domain_name in the "
                                "spec you give check_spec and propose_plan; the new domain is made when the person "
                                "approves the plan. Carry on with the model.")
                    if method == "POST" and path.split("?")[0] == "/api/v1/scenarios":
                        return ("Refused: a what-if is made with the what_if tool (it copies the scenario with your "
                                "changes, solves it and compares), not with call_api.")
                    return ("Refused: in problem-description mode nothing is written with call_api except data "
                            "preparation (map data imported and turned into records, candidate sets and their "
                            "generated links, the platform's calculations) and, once the model is built, solving its "
                            "scenario. The model itself goes through propose_plan; what-ifs through what_if.")
                bare = path.split("?")[0]
                if method == "POST" and SOLVE_PATH.match(bare) and isinstance(args.get("body"), dict):
                    unknown = sorted(set(args["body"]) - RUN_FIELDS)
                    if unknown:
                        # The blend test: a fiber change sent with the run was dropped, and the run was answered
                        # from the earlier one. A run takes no data changes.
                        return (f"Refused: a run takes only {', '.join(sorted(RUN_FIELDS))}; {', '.join(unknown)} "
                                "would be ignored. To solve with changed data or limits, use what_if.")
                if method == "POST" and SOLVE_PATH.match(bare):
                    body_ = args.get("body") if isinstance(args.get("body"), dict) else {}
                    if "time_limit_s" not in body_:
                        # The camp retest: the platform default is 8,000 s; a person waiting in the chat gets an
                        # answer in minutes, and is told it can run longer.
                        args = {**args, "body": {**body_, "time_limit_s": AGENT_RUN_SECONDS}}
                if method == "POST" and SOLVE_PATH.match(bare):
                    # The field test (October 2026): every run failed and the model queued the same scenario
                    # twelve times, never reading why, until it ran out of steps.
                    self.solves[bare] = self.solves.get(bare, 0) + 1
                    if self.solves[bare] > MAX_SOLVES:
                        return (f"Refused: this scenario was already queued {MAX_SOLVES} times in this turn. Read the "
                                "last run's error (GET /api/v1/runs/<id>) and tell the user what it says; queue it "
                                "again only after something has changed.")
                # Policy uses normalized paths; dispatch uses OpenAPI's actual
                # slash convention. POST redirects are not followed by urllib.
                for op in self.index.ops:
                    pattern = re.sub(r"\{[^}]+\}", "[^/]+", op["path"].rstrip("/"))
                    if op["method"] == method and re.fullmatch(pattern, route):
                        path = route + ("/" if op["path"].endswith("/") else "")
                        path += separator + query_string if separator else ""
                        break
                res = self.call(method, path, args.get("query"), args.get("body"), args.get("form"), args.get("headers"))
                body = res.get("body") if isinstance(res, dict) else None
                if method == "GET" and RUN_PATH.match(bare) and isinstance(body, dict) and body.get("status") == "error":
                    res = {**res, "platform_note": "This run FAILED; its error says why. Do not queue it again "
                           "unchanged: tell the user the error in plain words, and what could fix it."}
                if (((method == "GET" and RUN_PATH.match(bare)) or (method == "POST" and SOLVE_PATH.match(bare)))
                        and isinstance(body, dict)
                        and body.get("status") in ("optimal", "feasible", "infeasible", "unbounded")):
                    # The blend test: the report was written from the raw run (rounded differently, slips) and
                    # read_result was never called. A settled run comes back as read_result's text.
                    got = self._read_run(body.get('id'))
                    text = (got.get("body") or {}).get("text") if got.get("ok") and isinstance(got.get("body"), dict) else None
                    if text:
                        return clip(f"Run {body.get('id')} has settled ({body.get('status')}). This is read_result "
                                    "for it; report from it:\n\n" + text, lim)
                return clip(res, lim)
            if name == "propose_plan":
                return self._check_plan(args)
            return f"unknown tool {name}"
        except Exception as e:  # noqa: BLE001 -- told to the model, which can recover
            return f"tool error: {type(e).__name__}: {e}"

    def _extract(self, found: dict, jobs: list[dict] | None = None) -> tuple[dict | None, str | None]:
        """A fresh extraction of one source, waited for: (the job, None), or (None, why not -- for the person)."""
        cid = found["id"]
        if jobs is None:
            jobs = ((self.call("GET", f"/api/v1/connections/{cid}/jobs", {"limit": 20}).get("body") or {})
                    .get("items")) or []
        job = None
        started = self.call("POST", f"/api/v1/connections/{cid}/jobs", None, {})
        if started.get("status") == 409:  # one is already queued or running: wait for that one
            job = next((j for j in jobs if j.get("state") in ("queued", "running")), None)
        elif started.get("ok"):
            job = started.get("body")
        if not job:
            return None, "Could not start an extraction: " + clip(started.get("body"), 400)
        waited = 0.0
        while job.get("state") in ("queued", "running") and waited < SOURCE_WAIT_S:
            time.sleep(2)
            waited += 2
            job = self.call("GET", f"/api/v1/ingestion-jobs/{job['id']}").get("body") or job
        if job.get("state") in ("queued", "running"):
            return None, (f"The extraction of \"{found['name']}\" (job {job['id']}) is still {job['state']} after "
                          f"{SOURCE_WAIT_S} s. Wait a little and try again.")
        if job.get("state") != "extracted":
            code = job.get("error_code") or ""
            why = SOURCE_FAILURES.get(code, "the source could not be read")
            last = next((j for j in jobs if j.get("state") == "extracted"), None)
            fallback = (f" Its previous extraction (job {last['id']}, {last.get('finished_at')}) can still be "
                        "used: call use_source without refresh, and tell the person those figures may be old."
                        if last else "")
            return None, (f"Could not read \"{found['name']}\": {why} ({code or job.get('state')}). Tell the person; "
                          f"they or an administrator fix it on the Sources page.{fallback}")
        return job, None

    _REPORTED = re.compile(r"\(reported: (\{.*\})\)")

    def _reported_refresh(self, domain: Any) -> dict | None:
        """The last refresh this conversation reported and has not applied since (its tool results)."""
        for m in reversed(getattr(self, "_messages", None) or []):
            if m.get("role") != "tool" or m.get("name") != "refresh_sources":
                continue
            content = str(m.get("content") or "")
            if content.startswith("REFRESH APPLIED"):
                return None
            found = self._REPORTED.search(content)
            if not found:
                continue
            try:
                said = json.loads(found.group(1))
            except ValueError:
                continue
            if str(said.get("domain")) == str(domain):
                return {"domain": domain, "jobs": {int(c): int(j) for c, j in (said.get("jobs") or {}).items()},
                        "files": {str(n): int(v) for n, v in (said.get("files") or {}).items()},
                        "changes": int(said.get("changes") or 0)}
        return None

    def _refresh_sources(self, args: dict) -> str:
        """Re-read the sources the workspace was built from; report the changes, or write the ones reported."""
        domain = args.get("domain_id") or self.ctx.domain_id
        try:
            domain = int(domain) if domain else None
        except (TypeError, ValueError):
            return "domain_id must be a workspace's number."
        if not domain:
            return "Could not: no workspace (domain) is selected."
        listed = self.call("GET", f"/api/v1/domains/{int(domain)}/source-bindings")
        if not listed.get("ok"):
            return "Could not read what this workspace was built from: " + clip(listed.get("body"), 400)
        bound = (listed.get("body") or {}).get("items") or []
        if not bound:
            return ("Nothing in this workspace was built from a data source or a kept file, so there is nothing to "
                    "refresh. (Data loaded with *_from_file from a source or an attached file is remembered for "
                    "refresh; numbers typed into a plan are not.)")
        wanted = [str(w).strip().lower().lstrip("#") for w in args.get("sources") or []]

        def chosen(b: dict) -> bool:
            return not wanted or str(b.get("connection_id")) in wanted or str(b["connection"]).lower() in wanted

        conns = {b["connection_id"]: {"id": b["connection_id"], "name": b["connection"], "enabled": b["enabled"]}
                 for b in bound if b.get("connection_id") and chosen(b)}
        file_names = sorted({b["file_name"] for b in bound if b.get("file_name") and chosen(b)})
        if not conns and not file_names:
            return "None of these is a source this workspace was built from: " + ", ".join(
                sorted({b["connection"] for b in bound}))
        apply = bool(args.get("apply"))
        pending = getattr(self, "_refresh_pending", None) or self._reported_refresh(domain)
        unreported = apply and (not pending or pending.get("domain") != domain or set(pending["jobs"]) != set(conns)
                                or set(pending.get("files") or {}) != set(file_names))
        if unreported:
            # Only what the person saw is written: with no report of these sources in this conversation, report
            # now (it writes nothing) and ask again -- instead of a refusal the model retried (the refresh test).
            apply = False
        notes: list[str] = []
        if apply:
            jobs, versions = pending["jobs"], pending.get("files") or {}
        else:
            jobs, versions = {}, {}
            for cid, found in conns.items():
                if not found["enabled"]:
                    return f'The data source "{found["name"]}" is disabled; it can be enabled on the Sources page.'
                job, failed = self._extract(found)
                if failed:
                    return failed
                jobs[cid] = job["id"]
            for name in file_names:
                # A newer copy attached in this conversation becomes the file's next version (kept, append-only).
                attached = next((f for f in self.ctx.files if f.get("name") == name and not f.get("source")), None)
                if attached is not None:
                    kept = self.call("POST", f"/api/v1/domains/{int(domain)}/files", None, {"file": attached})
                    if not kept.get("ok"):
                        return f'Could not keep the attached "{name}" as a new version: ' + clip(kept.get("body"), 400)
                    if kept["body"].get("new"):
                        notes.append(f'The attached "{name}" is kept as version {kept["body"]["version"]} of the '
                                     "workspace file.")
                latest = self.call("GET", f"/api/v1/domains/{int(domain)}/files/{urllib.parse.quote(name, safe='')}")
                if not latest.get("ok"):
                    return f'The workspace has no file "{name}" any more: ' + clip(latest.get("body"), 300)
                versions[name] = int(latest["body"]["source"]["version"])
        res = self.call("POST", f"/api/v1/domains/{int(domain)}/sources/refresh", None,
                        {"jobs": {str(k): v for k, v in jobs.items()}, "files": versions, "connections": list(conns),
                         "apply": apply, "remove_missing": not bool(args.get("keep_missing"))})
        if not res.get("ok"):
            return "Could not refresh: " + clip(res.get("body"), 800)
        body = res["body"]
        lines = list(notes)
        for b in body.get("bindings") or []:
            c = b["counts"]
            where = f' (version {b["from_version"]} -> {b["version"]})' if b.get("file_name") else ""
            head = (f'- {b["source"]}{where} -> {b["kind"].replace("_", " ")} "{b["target"]}": {c["added"]} added, '
                    f'{c["changed"]} changed, {c["removed"]} gone, {c["unchanged"]} unchanged')
            lines.append(head + (" (same data as the build: nothing new)" if b.get("same_extraction") else ""))
            for a in b["added"]:
                if "key" in a:
                    what = a["key"] + (f' ({a["label"]})' if a.get("label") else "") + (
                        f' {a["attrs"]}' if a.get("attrs") else "") + (" (back again)" if a.get("returning") else "")
                elif "from" in a:
                    what = f'{a["from"]} -> {a["to"]}'
                else:
                    what = f'{a["index"]} = {a["value"]}'
                lines.append("    + " + what)
            for ch in b["changed"]:
                if "fields" in ch:
                    lines.append(f'    ~ {ch["key"]}: ' + ", ".join(f'{f["field"]} {f["before"]} -> {f["after"]}'
                                                                     for f in ch["fields"]))
                else:
                    lines.append(f'    ~ {ch["index"]}: {ch["before"]} -> {ch["after"]}')
            for r in b["removed"]:
                lines.append("    - " + str(r.get("key") or r.get("index") or f'{r.get("from")} -> {r.get("to")}'))
            shown = len(b["added"]) + len(b["changed"]) + len(b["removed"])
            if shown < c["added"] + c["changed"] + c["removed"]:
                lines.append(f"    (first {shown} shown)")
        if not apply:
            self._refresh_pending = {"domain": domain, "jobs": jobs, "files": versions, "changes": body.get("changes")}
            # Kept in the conversation: the person's "yes" comes in a later turn, to a new Agent.
            lines.append("(reported: " + json.dumps({"domain": domain, "jobs": {str(k): v for k, v in jobs.items()},
                                                     "files": versions, "changes": body.get("changes") or 0},
                                                    separators=(",", ":")) + ")")
            if not body.get("changes"):
                return ("REFRESH CHECKED: the sources hold the same data the workspace has; nothing to change, and "
                        "the last answer still stands.\n" + "\n".join(lines))
            if unreported:
                return ("REFRESH REPORT -- NOT APPLIED: no report of these changes was in this conversation, so nothing "
                        "was written; the sources were read now and this is what would change. Show these changes "
                        "to the person and ask again; apply=true after their yes writes exactly these.\n"
                        + "\n".join(lines))
            return ("REFRESH REPORT (nothing written yet). Show these changes to the person in a short table and ask "
                    "whether to apply them; on yes call refresh_sources with apply=true, then solve the scenario "
                    "again and compare with the last answer.\n" + "\n".join(lines))
        self._refresh_pending = None
        for cid, job_id in jobs.items():  # a sheet of this source attached here is replaced by the one applied
            got = self.call("GET", f"/api/v1/agent/sources/{job_id}/file")
            if got.get("ok"):
                sheet = got["body"]
                attached = next((f for f in self.ctx.files
                                 if (f.get("source") or {}).get("connection_id") == cid), None)
                if attached is not None:
                    sheet["name"] = attached["name"]
                    self.ctx.files = [sheet if f is attached else f for f in self.ctx.files]
                    self.events.append({"type": "file", "file": sheet})
        return ("REFRESH APPLIED: the workspace now holds the sources' data. Now solve the scenario again "
                "(POST /api/v1/scenarios/{id}/runs, then read_result) and tell the person how the answer changed.\n"
                + "\n".join(lines))

    def _use_source(self, wanted: str, refresh: bool, domain_id: Any = None) -> str:
        """A workspace data source as an attached sheet: its latest extraction, or a fresh one."""
        domain = domain_id or self.ctx.domain_id
        if not domain:
            return "Could not: no workspace (domain) is selected, and data sources belong to one."
        listed = self.call("GET", "/api/v1/connections", {"domain_id": int(domain), "limit": 100})
        if not listed.get("ok"):
            return "Could not list the data sources: " + clip(listed.get("body"), 400)
        sources = (listed.get("body") or {}).get("items") or []
        found = next((c for c in sources if str(c.get("id")) == wanted.lstrip("#")), None) or next(
            (c for c in sources if str(c.get("name", "")).strip().lower() == wanted.lower()), None)
        if found is None:
            kept = self.call("GET", f"/api/v1/domains/{int(domain)}/files/{urllib.parse.quote(wanted, safe='')}")
            if kept.get("ok"):
                return self._attach_sheet(kept["body"], "its latest version, " + str(
                    (kept["body"].get("source") or {}).get("added_at")))
            names = ", ".join([f'"{c.get("name")}" (id {c.get("id")})' for c in sources] + [
                f'"{f.get("name")}" (file)' for f in ((self.call("GET", f"/api/v1/domains/{int(domain)}/files")
                                                     .get("body") or {}).get("items") or [])]) or "none"
            return f'No data source "{wanted}" in this workspace. Its data sources: {names}.'
        if not found.get("enabled"):
            return f'The data source "{found["name"]}" is disabled; it can be enabled again on the Sources page.'
        cid = found["id"]
        jobs = ((self.call("GET", f"/api/v1/connections/{cid}/jobs", {"limit": 20}).get("body") or {}).get("items")) or []
        job = None if refresh else next((j for j in jobs if j.get("state") == "extracted"), None)
        fresh = job is None
        if fresh:
            job, failed = self._extract(found, jobs)
            if failed:
                return failed
        got = self.call("GET", f"/api/v1/agent/sources/{job['id']}/file")
        if not got.get("ok"):
            return "Could not read the extracted rows: " + clip(got.get("body"), 400)
        return self._attach_sheet(got["body"], "read just now" if fresh else
                                  f"its latest extraction, {(got['body'].get('source') or {}).get('extracted_at')}")

    def _attach_sheet(self, sheet: dict, when: str) -> str:
        """A source's sheet (a database extraction, or a file kept in the workspace) attached to this conversation."""
        name = sheet["name"]
        clash = next((f for f in self.ctx.files if f.get("name") == name and not f.get("source")), None)
        if clash is not None:  # an attached file of the same name stays; the source gets its own
            name = sheet["name"] = f"{name} (source)"
        self.ctx.files = [f for f in self.ctx.files if f.get("name") != name] + [sheet]
        self.events.append({"type": "file", "file": sheet})
        src = sheet.get("source") or {}
        rows = sum(int(s.get("total_rows") or len(s.get("rows") or [])) for s in sheet.get("sheets") or [])
        which = f'job {src.get("job_id")}' if src.get("job_id") else f'version {src.get("version")}'
        return (f'Data source "{name}" is attached as a sheet ({rows:,} rows, {when}; {which}, '
                f'SHA-256 {str(src.get("sha256"))[:12]}). Use it like an attached file -- the file name is "{name}":\n'
                + agent_files.outline([sheet]))

    def _place(self, name: str, epsg: Any) -> str:
        found = next((f for f in self.ctx.files if f.get("name") == name), None)
        if found is None or not (found.get("spatial") or {}).get("upload_id"):
            return f'No attached map file named "{name}".'
        try:
            code = int(epsg)
        except (TypeError, ValueError):
            return "epsg must be a number, e.g. 22992"
        spatial = found["spatial"]
        extent = spatial.get("extent") or []
        degree_like = len(extent) == 4 and all(abs(v) <= 180 for v in extent[0::2]) and all(abs(v) <= 90 for v in extent[1::2])
        try:
            from app.gis.crs import crs_info

            geographic = crs_info(code)["geographic"]
        except Exception:  # noqa: BLE001 -- an unknown code is refused by the platform below
            geographic = False
        if geographic and spatial.get("format") not in agent_files.GEOGRAPHIC_FORMATS and not degree_like:
            # The camp-bed test: EPSG:4326 on a drawing in metres made an 88 m camp "86 km" wide.
            return (f"Refused: EPSG:{code} is longitude/latitude in degrees, and this drawing's coordinates are not "
                    "degrees (they run to " + ", ".join(f"{v:,.0f}" for v in extent) + "). It is already in LOCAL "
                    "METRES (x_m, y_m, area_m2); keep that. To put it on the real map, it needs a projected system in "
                    "metres (a UTM zone or a national grid), or a local placement at a known point.")
        res = self.call("POST", "/api/v1/agent/files/place", None,
                        {"upload_id": found["spatial"]["upload_id"], "placement": {"kind": "epsg", "code": code}})
        if not res.get("ok"):
            return "Could not place it: " + clip(res.get("body"), 1500)
        placed = res["body"]
        self.ctx.files = [placed if f is found else f for f in self.ctx.files]
        self.events.append({"type": "file", "file": placed})
        lons = [r[2] for sh in placed["sheets"] for r in sh["rows"] if r[2] is not None]
        lats = [r[3] for sh in placed["sheets"] for r in sh["rows"] if r[3] is not None]
        box = [min(lons), min(lats), max(lons), max(lats)] if lons else None
        return (f'Placed "{name}" in EPSG:{code} ({(placed["spatial"].get("placement") or {}).get("name")}). '
                f"It lands within lon/lat {box}: tell the user where that is and ask them to confirm it is the right "
                f"place. Its sheets now have lon, lat, area_m2, length_m and geometry columns.")

    def _make_layout(self, args: dict) -> str:
        from app.agent import layout

        folder = sandbox.workdir(self.ctx.user_id or "anyone", self.ctx.conversation_id)

        form = "candidates" if args.get("form") == "candidates" else "place"

        def run(step: float | None, into: str) -> dict:
            if form == "place":
                return layout.place(self.ctx.files, into, file=args.get("file"),
                                    area_layers=list(args.get("area_layers") or []),
                                    blocked_layers=list(args.get("blocked_layers") or []),
                                    label_layer=args.get("label_layer"), items=list(args.get("items") or []),
                                    aisle=float(args.get("aisle") or 0),
                                    aisle_side=str(args.get("aisle_side") or "any"), step=step,
                                    access_layers=list(args.get("access_layers") or []) or None)
            # The candidate list as its recipe (plan 1B): the run's worker builds the positions, cells and links.
            return layout.generated(self.ctx.files, into, file=args.get("file"),
                                    area_layers=list(args.get("area_layers") or []),
                                    blocked_layers=list(args.get("blocked_layers") or []),
                                    label_layer=args.get("label_layer"), items=list(args.get("items") or []),
                                    aisle=float(args.get("aisle") or 0),
                                    aisle_side=str(args.get("aisle_side") or "any"), step=step,
                                    access_layers=list(args.get("access_layers") or []) or None)

        try:
            out = run(float(args["step"]) if args.get("step") else None, folder)
        except (layout.LayoutRefused, TypeError, ValueError) as e:
            said = f"Could not lay it out: {e}"
            if args.get("step") and isinstance(e, layout.LayoutRefused):
                # The camp retest (October 2026): the model chose 0.5 m on its own, it was too big, and the person
                # was asked to choose -- while the step the platform picks (1 m, exact for a 2 x 1 m bed and a 1 m
                # aisle) fitted: 12,008 positions in 0.2 s. Said with its numbers, so the choice is an easy one.
                import tempfile

                try:
                    alt = run(None, tempfile.mkdtemp(prefix="layout-try-"))
                    size = (f"{alt['candidates']:,} candidate positions" if "candidates" in alt
                            else f"a grid of {alt.get('free_cells', 0):,} free cells")
                    said += (f"\nLEAVING step OUT works: the platform's exact step is {alt['grid_step_m']:g} m, giving "
                             f"{size} (upper bound {alt['upper_bound']['items']:,} "
                             "items). Unless the user themselves asked for "
                             f"{float(args['step']):g} m, call make_layout again WITHOUT step now and tell them the "
                             "step used.")
                except (layout.LayoutRefused, TypeError, ValueError):
                    pass
            return said
        for name in out["files"]:
            with open(os.path.join(folder, name), "rb") as f:
                parsed = agent_files.parse(name, f.read(), max_rows=agent_files.MAX_GENERATED_ROWS)
            self.ctx.files = [x for x in self.ctx.files if x.get("name") != name] + [parsed]
            self.events.append({"type": "file", "file": parsed})
        spec = out.pop("spec")
        if out.get("form") == "place":
            return ("LAYOUT made, placement form (files attached: " + ", ".join(out["files"]) + "): no list of "
                    "positions -- the placement solver lays the items out on this grid itself.\n"
                    + json.dumps(out, default=str)
                    + "\n\nTHE PLAN, ready: give it to check_spec as it is, adding only domain_id (the domain the "
                    "drawing is imported into; import it first if it is not) or domain_name, and problem_name. Tell "
                    "the user the grid step and the aisle as modelled, the slots (the most that can fit by area) and "
                    "what is not modelled, in words, before proposing. A run of it is solved by the placement "
                    "solver: give it at least 2 minutes.\n" + json.dumps(spec))
        return ("LAYOUT made (files attached: " + ", ".join(out["files"]) + "):\n" + json.dumps(out, default=str)
                + "\n\nTHE PLAN, ready: give it to check_spec as it is, adding only domain_id (the domain the drawing "
                "is imported into; import it first if it is not) or domain_name, and problem_name. Tell the user the "
                "numbers (candidates, grid step, the aisle as modelled, the upper bound) and what is not modelled, in "
                "words, before proposing. The candidates are not stored: the plan keeps the areas and kinds, and each "
                "run builds the positions from them.\n" + json.dumps(spec))

    def _what_if(self, args: dict) -> str:
        base_id = int(args.get("scenario_id") or 0)
        base = self.call("GET", f"/api/v1/scenarios/{base_id}")
        if not base.get("ok") or not isinstance(base.get("body"), dict):
            return f"No scenario {base_id}: " + clip(base.get("body"), 600)
        b = base["body"]
        patch = dict(b.get("patch") or {})
        for key in ("set_param", "set_attr", "scale_attr", "disable"):
            if args.get(key):
                items = args[key]
                if key == "set_param":
                    items = [{"param": str(c.get("param")), "index": [str(i) for i in c.get("index") or []],
                              "value": c.get("value")} for c in items if isinstance(c, dict)]
                patch[key] = [*(patch.get(key) or []), *items]
        moved: list[str] = []
        if isinstance(args.get("set_limit"), dict) and args["set_limit"]:
            # A limit that is a data value ("c_demand [A] (= limit 180 = demand[m])", as read_result prints it) is
            # changed through that value (live what-if test, October 2026: set_limit {"c_demand[A]": 220} was
            # refused, the rule's limit being demand[m], not a number).
            ver = self.call("GET", f"/api/v1/versions/{b.get('model_version_id')}")
            ir = (ver.get("body") or {}).get("ir") if ver.get("ok") and isinstance(ver.get("body"), dict) else None
            kept = {}
            for key, value in args["set_limit"].items():
                as_param = limit_as_param(ir or {}, str(key), value)
                if as_param is None:
                    kept[key] = value
                else:
                    args.setdefault("set_param", [])
                    args["set_param"] = [*args["set_param"], as_param]
                    patch["set_param"] = [*(patch.get("set_param") or []), as_param]
                    moved.append(f"{key} -> set_param {as_param['param']}{as_param['index'] or ''} = {value}")
            args["set_limit"] = kept
        for key in ("scale_param", "set_limit", "remove"):
            if isinstance(args.get(key), dict) and args[key]:
                patch[key] = {**(patch.get(key) or {}), **args[key]}
        futures = args.get("futures")
        try:
            futures = max(0, min(500, int(futures))) if futures not in (None, "") else None
        except (TypeError, ValueError):
            futures = None
        front = args.get("front")
        try:
            front = max(2, min(50, int(front))) if front not in (None, "", 0) else None
        except (TypeError, ValueError):
            front = None
        if patch == (b.get("patch") or {}) and not futures and not front:
            return ("Nothing to change: give set_param, set_limit, scale_param, set_attr, scale_attr, remove, "
                    "disable, futures or front.")
        name = (str(args.get("name") or "what-if").strip() or "what-if")[:60]
        made = None
        for n in range(1, 30):
            made = self.call("POST", "/api/v1/scenarios", None, {
                "problem_id": b["problem_id"], "model_version_id": b["model_version_id"],
                "name": name if n == 1 else f"{name} ({n})", "patch": patch})
            if made.get("ok") or "name" not in json.dumps(made.get("body"), default=str).lower():
                break
        if not made or not made.get("ok"):
            return "The what-if was refused: " + clip(made.get("body") if made else None, 1500)
        sid = made["body"]["id"]
        queued = self.call("POST", f"/api/v1/scenarios/{sid}/runs", None,
                           {"time_limit_s": AGENT_RUN_SECONDS, **({"futures": futures} if futures else {}),
                            **({"pareto_steps": front} if front else {})})
        if not queued.get("ok"):
            return f"Scenario {sid} was made but could not be solved: " + clip(queued.get("body"), 1500)
        run_id = queued["body"]["id"]
        run = queued["body"]
        waited = 0.0
        while run.get("status") not in SETTLED and waited < WHATIF_WAIT_S:
            time.sleep(2)
            waited += 2
            got = self.call("GET", f"/api/v1/runs/{run_id}")
            run = got.get("body") if isinstance(got.get("body"), dict) else run
        if run.get("status") not in SETTLED:
            return (f"What-if scenario {sid} is still solving (run {run_id}). Poll GET /api/v1/runs/{run_id} with "
                    "wait, then read_result.")
        prior = self.call("GET", "/api/v1/runs", {"scenario_id": base_id, "limit": 5})
        base_run = next((r for r in ((prior.get("body") or {}).get("items") or [])
                         if r.get("status") in ("optimal", "feasible")), None)
        lines = [f"WHAT-IF '{name}' (scenario {sid}, from scenario {base_id}; changes: "
                 + json.dumps({k: v for k, v in patch.items() if k not in (b.get('patch') or {})
                               or v != (b.get('patch') or {}).get(k)}, ensure_ascii=False)
                 + (f"; a limit that is a data value was changed through it: {'; '.join(moved)}" if moved else "")
                 + (f"; planned for {futures} sampled futures" if futures else "")
                 + (f"; the trade-off front in {front} steps" if front else "") + ")"]
        if base_run and run.get("objective") is not None and base_run.get("objective") is not None:
            before, after = float(base_run["objective"]), float(run["objective"])
            lines.append(f"BASE goal {before:,.2f} (run {base_run['id']}) -> WHAT-IF goal {after:,.2f} (run {run_id}): "
                         f"difference {after - before:+,.2f}"
                         + (f" ({(after - before) / abs(before) * 100:+.2f}%)" if before else "") + ".")
        if base_run:
            lines.extend(self._what_changed(base_run["id"], run_id))
        res = self._read_run(run_id)
        body = res.get("body") if isinstance(res, dict) else None
        lines.append(body.get("text") if res.get("ok") and isinstance(body, dict) else clip(res, 1500))
        lines.append("Report the difference exactly as given; it is solved, not estimated. Take every number for the "
                     "base and the what-if from the lines above (BASE ..., CHANGED ...), never from your earlier "
                     "replies, which may be wrong; if one of them was, say so and give the right number.")
        return "\n".join(lines)

    def _what_changed(self, base_id: int, run_id: int) -> list[str]:
        """Which yes/no choices the what-if added and removed, and the base's totals (the fibre test: "still
        keeping the previous 12 places" when one was dropped, and the base's household total from memory)."""
        got = [self.call("GET", f"/api/v1/runs/{i}") for i in (base_id, run_id)]
        if not all(g.get("ok") and isinstance(g.get("body"), dict) for g in got):
            return []
        before, after = (g["body"].get("assignments") or {} for g in got)
        out = []
        for var in sorted(set(before) | set(after)):
            if any(isinstance(k, list) and k and isinstance(k[-1], (int, float)) and not isinstance(k[-1], bool)
                   for k in [*(before.get(var) or []), *(after.get(var) or [])]):
                continue  # amounts, not yes/no choices: read_result gives them
            was = {" · ".join(map(str, k)) for k in before.get(var) or [] if isinstance(k, list)}
            now = {" · ".join(map(str, k)) for k in after.get(var) or [] if isinstance(k, list)}
            if was == now:
                out.append(f"CHANGED {var}: the same {len(now)} chosen as the base.")
                continue
            added, removed = sorted(now - was), sorted(was - now)
            out.append(f"CHANGED {var}: {len(was)} chosen -> {len(now)}; added {len(added)}: "
                       f"{', '.join(added[:30]) or 'none'}; removed {len(removed)}: {', '.join(removed[:30]) or 'none'}.")
        base_text = self.call("GET", f"/api/v1/agent/result/{base_id}")
        body = base_text.get("body") if isinstance(base_text, dict) else None
        if base_text.get("ok") and isinstance(body, dict):
            out.extend(f"BASE {line.strip()}" for line in str(body.get("text") or "").splitlines()
                       if line.startswith(("Totals over", "Totals of field")) or "room left" in line)
        return out

    def _check_spec(self, args: Any) -> str:
        try:
            expanded = self._spec(args if isinstance(args, dict) else {"spec": args})
        except agent_files.FileRefused as e:
            return f"Not valid yet: {e}"
        faults = self._order_faults(expanded)
        if faults:
            return "Not valid yet; fix these: " + " ".join(faults)
        res = self.call("POST", "/api/v1/problems/from-spec", None,
                        {**_sendable(expanded), "dry_run": True, "trial": True})
        if res.get("ok"):
            return ("SPEC_OK: it would build " + json.dumps((res.get("body") or {}).get("would_create"), default=str)
                    + "\n\n" + agent_readback.readback(expanded)
                    + trial_said((res.get("body") or {}).get("trial")) + "\n\n" + READBACK_CHECK)
        refused = "Not valid yet; fix these: " + clip(res.get("body"), 4000)
        key = re.sub(r"\d+", "#", refused)[:400]
        self._spec_seen[key] = self._spec_seen.get(key, 0) + 1
        if self._spec_seen[key] >= 2:
            # The blend test: the same sum refused four times -- the model rewrote everything else and kept
            # that part. Say so, and point at the part.
            refused += (SAME_AGAIN + "this is the SAME refusal as your previous attempt, so that part did not "
                        "change. Rewrite ONLY the part at that loc, copying the shape in the message (or the "
                        "matching pattern in your instructions) exactly; leave the rest as it is.")
        return refused

    def _run_python(self, code: str, timeout: Any) -> str:
        if not self.ctx.can_run_python:
            return "run_python is not available here (it is off on this server, or you may not publish models)."
        if not code.strip():
            return "Send the Python code to run."
        folder = sandbox.workdir(self.ctx.user_id, self.ctx.conversation_id)
        sandbox.write_attachments(folder, self.ctx.files)
        result = sandbox.run(code, folder, int(timeout or 120))
        if result.get("error"):
            return result["error"]
        attached, skipped = [], []
        for name, data in sandbox.read_outputs(folder, result.get("files_written") or []):
            try:
                parsed = agent_files.parse(name, data)
            except agent_files.FileRefused as e:
                skipped.append(f"{name}: {e}")
                continue
            self.ctx.files = [f for f in self.ctx.files if f.get("name") != name] + [parsed]
            self.events.append({"type": "file", "file": parsed})
            attached.append(name)
        result["attached"] = attached
        if skipped:
            result["not_attached"] = skipped
        return json.dumps(result, ensure_ascii=False)

    # -- the plan: checked before the person sees it, built exactly as approved --
    def _spec(self, args: dict, expand: bool = True) -> dict:
        """The spec as the model wrote it; expanded, its file references become rows."""
        spec, notes = agent_repair.spec_of(args)
        self.joined.extend(notes)
        spec = {k: v for k, v in spec.items() if k != "dry_run"}
        self.joined.extend(agent_repair.misplaced(spec))
        self.joined.extend(agent_repair.joined_keys(spec))
        if not isinstance(spec.get("ir"), dict):
            raise agent_files.FileRefused(
                'the spec has no "ir" (the model: {"version": 2, "sets", "relationships", "parameters", "variables", '
                '"constraints", "objective"}) -- it goes beside "seed", which holds the data')
        if "domain_id" not in spec and not spec.get("domain_name") and self.ctx.domain_id is not None:
            spec["domain_id"] = self.ctx.domain_id
        if expand and isinstance(spec.get("seed"), dict):
            self._typed_cells = len(spec["seed"].get("parameter_values") or [])
            spec["seed"] = agent_files.expand(spec["seed"], self._load_files(spec["seed"]))  # FileRefused: told
        if isinstance(spec.get("ir"), dict):
            spec["ir"] = json.loads(json.dumps(spec["ir"]))  # never the model's own copy
            for term in ((spec["ir"].get("objective") or {}).get("terms") or []):
                # A goal term has no "note" (rules do): a refusal for it cost Qwen a whole 2-minute reply.
                if isinstance(term, dict):
                    term.pop("note", None)
            self.joined.extend(agent_repair.repair(spec))
            bound = bind_literal_keys(spec["ir"])
            if bound:
                self.joined.append("records named by their key where an index belongs were bound to them: "
                                   + "; ".join(bound))
        return spec

    def _load_files(self, seed: dict) -> list[dict]:
        """The files a plan loads from: the attached ones, and -- read whole, on the server -- files run_python
        wrote in this conversation's folder, which as attachments are cut to 5,000 rows a sheet and travel
        through the chat (the camp-bed retest generated more candidates than that)."""
        files = list(self.ctx.files)
        if not self.ctx.can_run_python:
            return files
        folder = sandbox.workdir(self.ctx.user_id, self.ctx.conversation_id)
        wanted = {str(e.get("file")) for key in ("entities_from_file", "parameter_values_from_file",
                                                "relationships_from_file") for e in seed.get(key) or []
                  if isinstance(e, dict) and e.get("file")}
        for name in wanted:
            path = os.path.join(folder, os.path.basename(name))
            attached = next((f for f in files if f.get("name") == name), None)
            whole = attached is not None and not any(s.get("truncated") for s in attached.get("sheets") or [])
            if whole or not os.path.isfile(path) or attached is not None and attached.get("spatial"):
                continue
            with open(path, "rb") as fh:
                parsed = agent_files.parse(name, fh.read(), max_rows=agent_files.MAX_GENERATED_ROWS,
                                           max_bytes=64 * 1024 * 1024)
            files = [f for f in files if f.get("name") != name] + [parsed]
        return files

    def _workspace(self, spec: dict) -> dict | None:
        """What the domain the spec builds in already holds (None for a new domain)."""
        domain = spec.get("domain_id")
        if not domain:
            return None
        res = self.call("GET", "/api/v1/agent/workspace", {"domain_id": int(domain)})
        return res.get("body") if isinstance(res, dict) and res.get("ok") else None

    def _existing_records(self, spec: dict, workspace: dict | None = None) -> dict[str, int]:
        """Records per kind already in the domain the spec builds in (none for a new domain)."""
        body = workspace if workspace is not None else self._workspace(spec)
        return {k.get("name"): int(k.get("records") or 0) for k in (body or {}).get("kinds_of_record") or []
                if isinstance(k, dict)}

    def _known_numbers(self) -> set[float]:
        """Numbers the person gave, the attached files hold, and the tools computed in this conversation."""
        known = _numbers_from(self.messages)
        for m in self.messages:
            if agent_compact.is_summary(m):
                # Carried by code when the conversation was summarized: the same sources, from before.
                known |= agent_compact.recorded_numbers(m)
        for f in self.ctx.files:
            for sheet in f.get("sheets") or []:
                for row in sheet.get("rows") or []:
                    for v in row:
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            known.add(round(float(v), 6))
        return known

    def _order_faults(self, spec: dict) -> list[str]:
        """The platform's order (map data, records, relationships, data values) and the data checks."""
        workspace = self._workspace(spec)
        if spec.get("domain_id") is not None and not spec.get("domain_name") and self._asked_new_workspace() \
                and str(spec.get("domain_id")) not in self._made_here():
            return [NEW_WORKSPACE_ASKED]
        return (_platform_order_faults(spec, workspace, self.ctx.files, self._known_numbers(), self._typed_cells)
                + _sets_without_data(spec, self._existing_records(spec, workspace)) + _empty_parameters(spec)
                + _uncertainty_faults(spec))

    def _made_here(self) -> set[str]:
        """Workspaces this conversation created: the new one the person asked for, which a corrected model may be
        built into again (the bakery test: the fix after a wrong answer was refused as "asked for a NEW workspace")."""
        made: set[str] = set()
        for m in self.messages:
            if m.get("role") == "tool" or agent_compact.is_summary(m):
                made |= set(re.findall(r'"domain_id": (\d+), "domain_created": true', str(m.get("content") or "")))
        if self.built and self.built.get("domain_created"):
            made.add(str(self.built.get("domain_id")))
        return made

    def _latest_results(self, messages: list[dict]) -> list[str]:
        """The latest runs the conversation read, read again now from the platform (the live job-shop retest: asked
        to re-read, the model re-typed a schedule from memory, and the stored text was an older format)."""
        runs: list[str] = []
        for m in reversed(messages[-120:]):
            if m.get("role") == "tool":
                for run in re.findall(r"\bRUN (\d+): ", str(m.get("content") or "")):
                    if run not in runs:
                        runs.append(run)
            if len(runs) >= 2:
                break
        texts = []
        for run in runs:
            got = self.call("GET", f"/api/v1/agent/result/{run}")
            body = got.get("body") if isinstance(got, dict) else None
            if got.get("ok") and isinstance(body, dict) and body.get("text"):
                texts.append(str(body["text"]))
        return texts

    def _asked_new_workspace(self) -> bool:
        """The person's latest word on the workspace asks for a new one (a summary keeps their words too)."""
        for m in reversed(self.messages):
            text = str(m.get("content") or "")
            if m.get("role") != "user" or (text.startswith(PLATFORM) and not agent_compact.is_summary(m)):
                continue
            new, same = _NEW_WORKSPACE.search(text), _SAME_WORKSPACE.search(text)
            if new or same:
                return bool(new) and not (same and same.start() > new.start())
        return False

    def _facts_shown(self) -> list[dict]:
        """The latest runs' facts, at most FACTS_SHOWN, one card for runs that found the same answer (the live
        test: the same scenario solved twice showed two identical cards)."""
        shown: list[dict] = []
        for facts in reversed(list(self.facts.values())):
            same = {k: v for k, v in facts.items() if k != "run_id"}
            if any({k: v for k, v in f.items() if k != "run_id"} == same for f in shown):
                continue
            shown.insert(0, facts)
            if len(shown) == FACTS_SHOWN:
                break
        return shown

    def _scenario_exists(self, solve_path: str) -> bool:
        """A scenario of a model already built (this conversation's, or one the workspace holds) that the person
        can read: solving it changes no model (the live test of 7 October 2026: "solve the Base scenario again"
        was refused three times in Describe a problem mode)."""
        found = re.match(r"^/api/v1/scenarios/(\d+)/runs$", solve_path)
        got = self.call("GET", f"/api/v1/scenarios/{found.group(1)}") if found else None
        return bool(isinstance(got, dict) and got.get("ok"))

    def _read_run(self, run_id: Any) -> dict:
        """read_result for a run, keeping its platform-rendered facts for the answer (shown beside it)."""
        res = self.call("GET", f"/api/v1/agent/result/{run_id}")
        body = res.get("body") if isinstance(res, dict) else None
        if isinstance(res, dict) and res.get("ok") and isinstance(body, dict) and isinstance(body.get("facts"), dict):
            self.facts.pop(run_id, None)
            self.facts[run_id] = body["facts"]
        return res

    def _turn_tool_texts(self, messages: list[dict]) -> list[str]:
        """What the tools said since the person's last message."""
        out: list[str] = []
        for m in reversed(messages):
            text = str(m.get("content") or "")
            if m.get("role") == "user" and not text.startswith(PLATFORM):
                break
            if m.get("role") == "tool":
                out.append(text)
        return out

    def _last_person_text(self, messages: list[dict]) -> str:
        return next((str(m.get("content") or "") for m in reversed(messages)
                     if m.get("role") == "user" and not str(m.get("content") or "").startswith(PLATFORM)), "")

    def _user_turns(self) -> int:
        return sum(agent_compact.recorded_turns(m) if agent_compact.is_summary(m) else
                   int(m["role"] == "user" and not str(m.get("content") or "").startswith(PLATFORM))
                   for m in self.messages)

    def _check_plan(self, args: dict) -> str:
        """The dry run. "PLAN_OK" lets the plan through to the person; anything else goes back to the model."""
        # The person's own go-ahead ("you decide the rest and go ahead") is the discussion: the evaluation's
        # routing test deadlocked between this rule and the go-ahead guard, which forbids asking.
        if self._user_turns() < MIN_USER_TURNS_BEFORE_PLAN and not any(
                _GO_AHEAD.search(str(m.get("content") or "")) for m in self.messages
                if m.get("role") == "user" and not str(m.get("content") or "").startswith(PLATFORM)):
            return ("Refused: you have not discussed the problem with the user yet. Restate what you "
                    "understood, ask your open questions (decisions, goal, rules hard/soft, data and units), "
                    "and propose only after they answer.")
        if not str(args.get("summary") or "").strip():
            return "Refused: summary is empty; write the plan for the user."
        try:
            spec = self._spec(args)
        except agent_files.FileRefused as e:
            return f"The spec does not build yet (the user has not seen it): {e}. Fix it and call propose_plan again."
        faults = self._order_faults(spec)
        if faults:
            return ("The spec does not build yet; fix these and call propose_plan again (the user has not seen it): "
                    + " ".join(faults))
        res = self.call("POST", "/api/v1/problems/from-spec", None, {**_sendable(spec), "dry_run": True, "trial": True})
        if res.get("ok"):
            return "PLAN_OK " + json.dumps(res.get("body"), default=str)
        return ("The spec does not build yet; fix these and call propose_plan again (the user has not "
                "seen it): " + clip(res.get("body"), 4000))

    def _build(self, args: dict) -> str:
        try:
            spec = self._spec(args)
        except agent_files.FileRefused as e:
            return (f"The build was refused (nothing was kept): {e}. The attached file may have been removed; "
                    "ask the user to attach it again, then propose again.")
        res = self.call("POST", "/api/v1/problems/from-spec", None, {**_sendable(spec), "dry_run": False})
        if not res.get("ok"):
            return ("The build was refused (nothing was kept): " + clip(res.get("body"), 3000) +
                    " Tell the user, fix the spec and propose again.")
        self.built = res["body"]
        b = self.built
        base = f"/domains/{b.get('domain_id')}/problems/{b.get('problem_id')}"
        mapped = self._import_drawings(b.get("domain_id"))
        return ("BUILT " + json.dumps(b, default=str) + (f" {mapped}" if mapped else "") +
                f" Now, without asking: inspect_decomposition for scenario_id {b.get('scenario_id')}, then solve it -- "
                f"call_api POST /api/v1/scenarios/{b.get('scenario_id')}/runs "
                f"with body {{}}, then GET /api/v1/runs/<run_id> (wait 3-5 s between polls) until its status is "
                f"no longer queued or running. Then tell the user (1) what was built, in the editor's terms "
                f"(sets, parameters, variables, rules, goals), with links [the problem]({base}), "
                f"[the model]({base}/model); and (2) the results in their words: status, the goal's value, the "
                f"decisions taken (assignments: the index tuples chosen, by their labels; amounts for whole or "
                f"continuous decisions) as a table, and, if infeasible, which rules conflict (rule_notes) and "
                f"what could be relaxed. Link [the run]({base}/runs/<run_id>).")

    def _import_drawings(self, domain_id: Any) -> str:
        """Every attached drawing the domain does not hold yet goes into its map data, as it was read (the
        same placement): the model never has to find an upload id."""
        if not domain_id:
            return ""
        drawings = [f for f in self.ctx.files if f.get("spatial") and (f["spatial"] or {}).get("upload_id")]
        if not drawings:
            return ""
        have = self.call("GET", "/api/v1/agent/workspace", {"domain_id": int(domain_id)})
        held = {str(m.get("file")) for m in ((have.get("body") or {}).get("map_data") or [])} if have.get("ok") else set()
        notes = []
        for f in drawings:
            if f.get("name") in held:
                continue
            spatial = f["spatial"]
            body = {"upload_id": spatial["upload_id"], "domain_id": int(domain_id), "name": str(f.get("name")),
                    "placement": spatial.get("placement")}
            res = self.call("POST", "/api/v1/gis/datasets", None, body)
            if not res.get("ok"):
                # The upload is used up by its first import (and kept a day): the same drawing's map is copied
                # from a workspace that holds it (camp retest, October 2026: a new workspace got no map).
                res = self.call("POST", f"/api/v1/gis/domains/{int(domain_id)}/datasets/same-drawing", None,
                                {"name": str(f.get("name")), "sha256": spatial.get("sha256"),
                                 "filename": str(f.get("name")), "extent": spatial.get("extent")})
            notes.append(f'The drawing "{f.get("name")}" is now on the domain\'s map.' if res.get("ok") else
                         f'The drawing "{f.get("name")}" could not be put on the map ({clip(res.get("body"), 300)}); '
                         "the model is built anyway, but its answer has no map (GeoJSON) until the user attaches the drawing "
                         "again -- tell them.")
        return " ".join(notes)

    def _execute(self, calls: list[dict], messages: list[dict], allow: bool | None) -> Iterator[dict]:
        self._messages = messages  # what this conversation has said so far (a refresh applies what it reported)
        for c in calls:
            name, args = c["function"]["name"], _args(c)
            yield {"type": "tool", "name": name, "args": _shown(name, args)}
            if self.cancelled.is_set():
                result = "Refused: turn stopped before this action."
            elif name == "propose_plan":
                if allow:
                    result = self._build(args)
                    self.wrote |= self.built is not None
                    if self.built:
                        yield {"type": "built", **self.built}
                else:
                    result = "The user did not approve this plan. Their reply follows; adjust and propose again."
            elif self._needs_ok(c) and not allow:
                result = "The user declined this call. Don't retry it; ask what they want instead."
            else:
                result = self.run_tool(name, args)
            while self.events:
                yield self.events.pop(0)
            ok = not (result.startswith(("tool error", "Refused", "Could not", "The build was refused", "Not valid yet",
                                         "The spec does not build", "run_python is not", "No attached",
                                         "No data source", "The data source", "The extraction of"))
                      or '"ok": false' in result[:40] or '"exit_code": -' in result[:30]
                      or (result.startswith('{"exit_code":') and not result.startswith('{"exit_code": 0')))
            if ok and (name == "place_file" or (name == "propose_plan" and allow and self.built)
                       or (name == "call_api" and str(args.get("method", "GET")).upper() != "GET"
                           and '"ok": true' in result[:40])):
                self.did_work = True
            messages.append({"role": "tool", "tool_call_id": c["id"], "name": name,
                             "content": result if name in WHOLE_RESULTS else self._preview(result)})
            yield {"type": "result", "name": name, "ok": ok, "preview": result[:300]}

    def _outputs(self) -> str:
        return os.path.join(sandbox.workdir(self.ctx.user_id or "anyone", self.ctx.conversation_id), "_outputs")

    def _preview(self, result: str) -> str:
        """A long result as its start and end, the whole of it saved for read_output."""
        if len(result) <= PREVIEW_CHARS:
            return result
        try:
            folder = self._outputs()
            os.makedirs(folder, exist_ok=True)
            number = len([n for n in os.listdir(folder) if n.endswith(".txt")]) + 1
            with open(os.path.join(folder, f"{number}.txt"), "w", encoding="utf-8") as f:
                f.write(result)
        except OSError:
            return clip(result, PREVIEW_CHARS)
        head, tail = result[:PREVIEW_CHARS - 1500], result[-1200:]
        return (f"{head}\n...[output {number}: {len(result):,} characters, shortened here; read_output(output="
                f"{number}, offset=...) or find=\"...\" reads any part]...\n{tail}")

    def _read_output(self, args: dict) -> str:
        try:
            number = int(args.get("output") or 0)
            with open(os.path.join(self._outputs(), f"{number}.txt"), encoding="utf-8") as f:
                text_ = f.read()
        except (OSError, ValueError):
            return "No such output: use the number a shortened result names."
        start = max(0, int(args.get("offset") or 0))
        if args.get("find"):
            at = text_.find(str(args["find"]), start)
            if at < 0:
                return f"\"{args['find']}\" is not in output {number} after character {start}."
            start = at
        part = text_[start:start + PREVIEW_CHARS]
        more = len(text_) - start - len(part)
        return part + (f"\n...[{more:,} characters more: offset={start + len(part)}]" if more > 0 else "\n[end]")

    def _summary_tokens(self) -> int:
        return max(800, min(3000, self.s.context // 10))

    def _summarize(self, piece: str, so_far: str) -> str:
        """One summarizing call: the notes so far, with this part of the conversation folded in. No tools and
        no thinking (the summary is the answer)."""
        words = self._summary_tokens() // 2
        system = {"role": "system", "content": agent_compact.SUMMARIZER.format(words=words)}
        user = {"role": "user", "content": (f"The summary so far:\n{so_far}\n\n" if so_far else "")
                + f"The conversation{' that followed' if so_far else ''}:\n\n{piece}\n\n"
                + ("Write the updated summary." if so_far else "Write the summary.")}
        msg, _ = llm_chat(replace(self.s, thinking="off"), [system, user], False,
                          None, self._summary_tokens())
        text = clean(msg.get("content") or "")
        if not text.strip():
            raise LlmError(0, "the model returned an empty summary")
        return text

    def _compact(self, messages: list[dict], force: bool = False) -> dict | None:
        reply = self.reply_tokens
        window = min(self.s.context - reply, self.s.working_tokens)
        keep = int(max(4000, window * 0.35) * CHARS_PER_TOKEN)
        piece = int(max(4000, (self.s.context - self._summary_tokens() - 3000) * 0.8) * CHARS_PER_TOKEN)
        return agent_compact.compact(messages, summarize=self._summarize, keep_chars=keep, piece_chars=piece,
                                     numbers=_numbers_from, force=force)

    def _maybe_compact(self, sys_msg: dict, messages: list[dict]) -> str | None:
        """Past `compact_at` of the context: summarize the older conversation (in place). The note says so; a
        summary that fails leaves the history to `fit()`, as before."""
        used = agent_compact.size([sys_msg] + messages) / CHARS_PER_TOKEN
        if used <= min(self.s.compact_at * (self.s.context - self.reply_tokens), self.s.working_tokens):
            return None
        try:
            done = self._compact(messages)
        except (LlmError, ToolModeChanged):
            return None
        if done is None:
            return None
        return (f"The conversation was getting long ({int(used):,} tokens to re-read at every step), so I "
                f"summarized the earlier part ({done['summarized']} messages) and kept the recent "
                f"{done['kept']} word for word.")

    def _compact_attempts(self, messages: list[dict]) -> None:
        """Only the latest spec attempt stays in the conversation, in full: each earlier check_spec /
        propose_plan keeps its summary, and its result the first lines of the error. The camp-bed test's
        history grew by a whole spec and its error on each of 24 retries until the 32k context overflowed."""
        at = [i for i, m in enumerate(messages) if m["role"] == "assistant" and any(
            c["function"]["name"] in ("check_spec", "propose_plan") for c in m.get("tool_calls") or [])]
        old_ids = set()
        for i in at[:-1]:
            calls = []
            for c in messages[i]["tool_calls"]:
                if c["function"]["name"] in ("check_spec", "propose_plan"):
                    old_ids.add(c["id"])
                    args = _args(c)
                    if args.get("spec") != "(superseded by a later attempt)":
                        c = {**c, "function": {**c["function"], "arguments": json.dumps(
                            {"summary": str(args.get("summary", ""))[:300], "spec": "(superseded by a later attempt)"})}}
                calls.append(c)
            messages[i]["tool_calls"] = calls
        for m in messages:
            if m["role"] == "tool" and m.get("tool_call_id") in old_ids and len(m.get("content") or "") > 400:
                m["content"] = m["content"][:400] + " ...(an earlier attempt; the latest one is below)"

    def _stuck(self, calls: list[dict], messages: list[dict]) -> str | None:
        """Stop repeated model and platform refusals with the useful error shown to the person."""
        for c in calls:
            result = next((m.get("content") or "" for m in reversed(messages)
                           if m["role"] == "tool" and m.get("tool_call_id") == c["id"]), "")
            if result.startswith("Refused:") and c["function"].get("name") == "call_api":
                key = "policy:" + result[:400]
                self.tool_failures[key] = self.tool_failures.get(key, 0) + 1
                if self.tool_failures[key] >= MAX_TOOL_FAILURES:
                    return "I stopped because the same action was refused repeatedly. " + result
            if result.startswith("tool error: "):
                name = c["function"].get("name", "tool")
                # Different casing or a guessed alternate filename is the same missing-file failure.
                normalized = result.lower()
                normalized = re.sub(r'no attached file named "[^"]+"', 'no attached file named <file>', normalized)
                normalized = re.sub(r"\s+", " ", normalized).strip()
                key = f"{name}:{normalized[:600]}"
                self.tool_failures[key] = self.tool_failures.get(key, 0) + 1
                if self.tool_failures[key] >= MAX_TOOL_FAILURES:
                    detail = result.removeprefix("tool error: ").strip()[:900]
                    if "no attached file named" in normalized:
                        return (f"I stopped after {MAX_TOOL_FAILURES} failed file reads because the attachment is "
                                "not available in the server copy of this conversation. Please reattach the file "
                                "using its exact name and continue; changes completed before an interruption may "
                                f"already be saved.\n\n**Latest file error:** {detail}")
                    return (f"The {name} tool failed the same way {MAX_TOOL_FAILURES} times, so I stopped rather "
                            f"than repeating it.\n\n**Latest tool error:** {detail}")
            if c["function"]["name"] == "call_api":
                args = _args(c)
                method = str(args.get("method", "GET")).upper()
                path = "/" + str(args.get("path", "")).lstrip("/")
                if method == "GET":
                    continue
                try:
                    response = json.loads(result)
                except (TypeError, ValueError):
                    continue
                status = response.get("status") if isinstance(response, dict) else None
                if not isinstance(status, int) or not 300 <= status < 600:
                    continue
                key = f"{method} {path.split('?')[0].rstrip('/')}"
                self.api_rejections[key] = self.api_rejections.get(key, 0) + 1
                self.total_api_rejections += 1
                if (self.api_rejections[key] < MAX_API_REJECTIONS and
                        self.total_api_rejections < MAX_TOTAL_API_REJECTIONS):
                    continue
                body = response.get("body") if isinstance(response, dict) else None
                detail = body.get("detail") if isinstance(body, dict) else body
                if isinstance(detail, list):
                    parts = []
                    for item in detail[:8]:
                        if not isinstance(item, dict):
                            continue
                        loc = ".".join(str(part) for part in item.get("loc", []) if part != "body")
                        msg = str(item.get("msg") or "invalid value")
                        parts.append(f"{loc}: {msg}" if loc else msg)
                    detail = "; ".join(parts)
                if not isinstance(detail, str):
                    detail = json.dumps(detail, ensure_ascii=False, default=str)
                detail = detail[:1200] or "the endpoint rejected the request"
                return (f"The platform rejected {key} with HTTP {status}. I stopped after "
                        f"{MAX_API_REJECTIONS} rejected attempts for this endpoint or "
                        f"{MAX_TOTAL_API_REJECTIONS} rejected writes in this turn, instead of continuing to retry.\n\n"
                        f"**The latest error says:** {detail}\n\n"
                        "I have not confirmed that the requested change was created. Tell me how you want to "
                        "correct the request, and I can continue.")
            if c["function"]["name"] not in ("check_spec", "propose_plan"):
                continue
            if not result.startswith(("Not valid yet", "The spec does not build")):
                continue
            key = re.sub(r"\d+", "#", result.split(SAME_AGAIN)[0])[:400]
            self.refusals[key] = self.refusals.get(key, 0) + 1
            if self.refusals[key] < MAX_SAME_ERROR:
                continue
            spec = agent_repair.spec_of(_args(c))[0]
            fragment = ""
            loc = re.search(r'"loc":\s*(\[[^\]]*\])', result)
            if loc:
                try:
                    node: Any = spec
                    for step in json.loads(loc.group(1)):
                        if step == "parameter_values" or step == "entities":
                            break  # expanded from files: not in what the model wrote
                        try:
                            node = node[step]
                        except (KeyError, IndexError, TypeError):
                            break  # the key the check asks for is the missing one: show its parent
                    fragment = json.dumps(node, ensure_ascii=False)[:600]
                    fragment = json.dumps(node, ensure_ascii=False)[:600]
                except (KeyError, IndexError, TypeError, ValueError):
                    fragment = ""
            error = result.split(":", 1)[-1].strip()[:900]
            return (f"I could not write one part of the model the way the platform needs it: {plain_refusal(result)} "
                    f"The same problem came back {MAX_SAME_ERROR} times, so I stopped instead of trying again.\n\n"
                    "You can say **continue** and I will try that part a different way, or describe that part of "
                    "the problem again in other words."
                    + f"\n\n<details><summary>Technical detail</summary>\n\n{error}"
                    + (f"\n\nThe part of the plan it is about:\n```json\n{fragment}\n```" if fragment else "")
                    + "\n</details>")
        return None

    def _complete(self, sys_msg: dict, messages: list[dict], native: bool | None,
                  settings: Settings) -> tuple[dict, bool]:
        """One completion, fitted to the context. If the server still finds it too long (the roster field
        test: 24,577 + 8,192 > 32,768, and the turn ended on the error), shorten the reply allowance or the
        history by what it says, and ask again."""
        reply, spare = self.reply_tokens, 0
        for attempt in range(4):
            try:
                try:
                    wire = to_wire(fit([sys_msg] + messages, self.s, reply, spare), native is not False)
                    # The reply gets the room the prompt leaves, never more (the camp-bed test: 25,348 +
                    # 7,421 > 32,768): min(planned, context - prompt - 512), at least 1,024.
                    prompt = int(len(json.dumps(wire, ensure_ascii=False, default=str)) / CHARS_PER_TOKEN)
                    room = max(1024, min(reply, self.s.context - prompt - 512))
                    return llm_chat(settings, wire, native, self.tools, room)
                except ToolModeChanged:
                    sys_msg["content"] = system_prompt(self.index, self.ctx, False)
                    return llm_chat(settings, to_wire(fit([sys_msg] + messages, self.s, reply, spare), False),
                                    False, self.tools, reply)
            except LlmError as e:
                if e.status != 400 or "context length" not in e.body or attempt == 3:
                    raise
                found = re.search(r"contains at least (\d+) input tokens", e.body)
                limit = re.search(r"maximum context length is (\d+)", e.body)
                context = min(self.s.context, int(limit.group(1))) if limit else self.s.context
                over = max(0, int(found.group(1)) + reply - context) if found else 2000
                if reply - over - 256 >= 2048:
                    reply = reply - over - 256  # a shorter reply is enough room
                else:
                    spare += max(over, 0) + 2000  # trim the history further
        raise AssertionError("unreachable")

    def _calls(self, msg: dict, content: str, finish: str | None) -> tuple[list[dict], list[str]]:
        """The calls a reply makes, native or written as text, and why any could not be run."""
        errors: list[str] = []
        calls: list[dict] = []
        native = msg.get("tool_calls") or []
        if native:
            for c in native:
                fn = c.get("function") or {}
                name, raw = fn.get("name"), fn.get("arguments")
                try:
                    try:
                        args = toolcall.strict_loads(raw, self.joined) if isinstance(raw, str) and raw.strip() \
                            else (raw or {})
                    except json.JSONDecodeError:
                        # A long spec closed in the wrong order (toolcall.fix_closers): put right, for the two
                        # tools whose spec the platform checks and the person reads before anything is built.
                        fixed = toolcall.fix_spec(raw) if name in ("check_spec", "propose_plan") \
                            and finish != "length" else None
                        if fixed is None:
                            raise
                        args = toolcall.strict_loads(fixed, self.joined)
                        self.joined.append("your call's JSON had a slip (a rule's \"right\" key left out, or closing "
                                           "brackets dropped, doubled or out of order) and was put right; check the "
                                           "spec says what you meant, and write it correctly next time")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                    if name not in self.tool_names:
                        raise ValueError(f'unknown tool "{name}"; available: {", ".join(sorted(self.tool_names))}')
                except Exception as e:  # noqa: BLE001 -- told to the model
                    errors.append(f"{name}: {e}")
                    continue
                calls.append({"id": c.get("id") or "call_" + uuid.uuid4().hex[:10], "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
            return calls, errors
        found, _prose, errors = toolcall.extract_tool_calls(content, self.tool_names, allow_repair=finish != "length")
        self.joined.extend(e[5:].strip() for e in errors if e.startswith("note:"))
        errors = [e for e in errors if not e.startswith("note:")]
        for f in found:
            calls.append({"id": "call_" + uuid.uuid4().hex[:10], "type": "function",
                          "function": {"name": f["name"], "arguments": json.dumps(f["arguments"], ensure_ascii=False)}})
        return calls, errors

    def run(self, messages: list[dict], allow: bool | None = None) -> Iterator[dict]:
        """Advance the conversation. Yields events; the last is always `state`."""
        self.wrote = False
        try:
            yield from self._run(messages, allow)
        except LlmError as e:
            yield {"type": "error", "text": str(e)}
        except Exception as e:  # noqa: BLE001 -- the conversation so far is still returned
            yield {"type": "error", "text": f"{type(e).__name__}: {e}"}
        yield {"type": "state", "messages": messages, "wrote": self.wrote}

    def _named_records(self, text: str) -> str | None:
        """Scenarios and runs the person names by number, looked up with their permissions: where each one is.
        The live what-if test (October 2026): asked about "scenario 53 (its latest run is 144)" with another
        workspace selected, the Assistant said twice that it did not exist, without looking it up."""
        named = list(dict.fromkeys((k.lower(), int(n)) for k, n in _NAMED.findall(text)))[:4]
        if not named:
            return None
        said = []
        for kind, ident in named:
            if kind == "run":
                run = self.call("GET", f"/api/v1/runs/{ident}")
                if not run.get("ok") or not isinstance(run.get("body"), dict):
                    said.append(f"run {ident}: not found, or not readable by this user")
                    continue
                body = run["body"]
                said.append(f"run {ident} ({body.get('status')}) is a run of scenario {body.get('scenario_id')}")
                ident = body.get("scenario_id")
                if ident is None or ("scenario", int(ident)) in named:
                    continue
            got = self.call("GET", f"/api/v1/scenarios/{ident}")
            if not got.get("ok") or not isinstance(got.get("body"), dict):
                said.append(f"scenario {ident}: not found, or not readable by this user")
                continue
            sc = got["body"]
            prob = self.call("GET", f"/api/v1/problems/{sc.get('problem_id')}")
            pb = prob.get("body") if prob.get("ok") and isinstance(prob.get("body"), dict) else {}
            domain = pb.get("domain_id")
            other = "" if domain is None or domain == self.ctx.domain_id else " -- not the selected workspace"
            said.append(f"scenario {ident} \"{sc.get('name')}\" belongs to problem {sc.get('problem_id')} "
                        f"\"{pb.get('name', '')}\" in workspace (domain) {domain}{other}")
        return (PLATFORM + "Looked up from the person's message: " + "; ".join(said)
                + ". Use these ids directly (read_result, what_if, GET); they need no other workspace selected.")

    def _is_write(self, c: dict) -> bool:
        return c["function"]["name"] == "what_if" or (
            c["function"]["name"] == "call_api" and str(_args(c).get("method", "GET")).upper() != "GET")

    def _run(self, messages: list[dict], allow: bool | None) -> Iterator[dict]:
        self.messages = messages
        # Built earlier in this conversation: solving it is allowed.
        for m in messages:
            if agent_compact.is_summary(m) and agent_compact.recorded_build(m):
                self.built = agent_compact.recorded_build(m)
            if m["role"] == "tool" and m.get("name") == "propose_plan" and str(m.get("content", "")).startswith("BUILT "):
                try:
                    self.built = json.loads(m["content"][6:].split(" Now explain")[0])
                except ValueError:
                    self.built = {"built": True}
        native = _NATIVE_TOOLS.get(self.s.base_url) if self.s.tool_mode == "auto" else self.s.tool_mode == "native"
        if messages and str(messages[-1].get("content") or "").strip().lower() in agent_compact.RESETS \
                and messages[-1]["role"] == "user":
            # "/reset": a new conversation. The browser clears its own copy; this answers any other client.
            messages.clear()
            yield {"type": "answer", "text": "Started a new conversation. Tell me about the problem."}
            return
        if messages and agent_compact.is_command(messages[-1]):
            # "/compact": summarize the conversation now, and show the summary.
            messages.pop()
            done = self._compact(messages, force=True)
            text = ("Nothing to summarize yet: the conversation is still short." if done is None else
                    f"I summarized our conversation ({done['summarized']} messages into one; about "
                    f"{done['chars_before'] // 2:,} tokens down to {done['chars_after'] // 2:,}). We continue from "
                    f"this summary:\n\n{done['notes']}")
            if done is not None:
                messages.append({"role": "assistant", "content": text})
            yield {"type": "answer", "text": text}
            return
        # A turn that stopped for an OK: run (or decline) its calls first.
        last = messages[-1] if messages else None
        if last and last["role"] == "assistant" and last.get("tool_calls"):
            done = {m.get("tool_call_id") for m in messages if m["role"] == "tool"}
            pending = [c for c in last["tool_calls"] if c["id"] not in done]
            self.wrote |= any(self._is_write(c) and (allow or not self._needs_ok(c)) for c in pending)
            yield from self._execute(pending, messages, allow)

        if last and last["role"] == "user" and not str(last.get("content") or "").startswith(PLATFORM):
            found = self._named_records(str(last.get("content") or ""))
            if found:
                messages.append({"role": "user", "content": found})
        claimed, pending_feedback = False, None
        # Each kind of correction has its own budget (the roster field test: three broken calls used up a
        # shared budget of three, and an empty reply then ended the turn), with a cap on them all.
        spent: dict[str, int] = {}

        def nudge(kind: str, most: int = MAX_NUDGES) -> bool:
            if spent.get(kind, 0) >= most or sum(spent.values()) >= MAX_TOTAL_NUDGES:
                return False
            spent[kind] = spent.get(kind, 0) + 1
            return True

        settings, rethought = self.s, False
        for _ in range(self.s.max_steps):
            if self.cancelled.is_set():
                return
            sys_msg = {"role": "system", "content": system_prompt(self.index, self.ctx, native is not False)}
            yield {"type": "thinking"}
            self._compact_attempts(messages)
            note = self._maybe_compact(sys_msg, messages)
            if note:
                yield {"type": "note", "text": note}
            try:
                msg, native = self._complete(sys_msg, messages, native, settings)
            except ReplyTooSlow as slow:
                if self.cancelled.is_set():
                    return
                if nudge("slow_reply"):
                    # Asked again, shorter: half the room, and only the part the last refusal named.
                    self.reply_tokens = max(4096, self.reply_tokens // 2)
                    messages.append({"role": "user", "content": SLOW_REPLY})
                    yield {"type": "note", "text": f"The model's reply took over {slow.seconds / 60:.0f} minutes and was "
                                                   "stopped; asking for a shorter one."}
                    continue
                content = ("I could not finish this step: the model's replies took too long. Say \"continue\" to "
                           "try again, or describe one part of the problem at a time.")
                messages.append({"role": "assistant", "content": content})
                yield {"type": "answer", "text": content}
                return
            if self.cancelled.is_set():
                return
            settings = self.s

            finish = msg.get("_finish")
            raw_content = msg.get("content") or ""
            thought = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not msg.get("tool_calls") and not clean(raw_content) and thought and (
                    toolcall.looks_like_unrun_call(thought) or (self.modelling and _spec_in_text(thought))):
                # An empty reply whose call stayed in the model's thinking (the roster field test ended on
                # empty replies): the call is taken from there, as one written into the reply would be.
                found = None if toolcall.looks_like_unrun_call(thought) else _spec_in_text(thought)
                raw_content = ("```json\n" + json.dumps(found, ensure_ascii=False) + "\n```" if found is not None
                               else thought[thought.rfind("<tool_call>"):] if "<tool_call>" in thought else thought)
            content = clean(raw_content)
            calls, errors = self._calls(msg, content, finish)
            if calls or errors:
                content = toolcall.extract_tool_calls(content, self.tool_names)[1] if not msg.get("tool_calls") else content

            if finish == "length" and (calls or errors or toolcall.looks_like_unrun_call(raw_content)):
                # Never run a call from a reply that did not finish: a repaired half-spec builds the wrong thing.
                if nudge("cut_off"):
                    messages.append({"role": "assistant", "content": content or "(my reply was cut off)"})
                    messages.append({"role": "user", "content": CUT_OFF})
                    yield {"type": "note", "text": "The reply was cut off at the length limit; asking for a smaller call."}
                    continue
                calls, errors = [], ["the reply was cut off again"]

            if finish == "length" and not calls and not errors:
                # Ran to the limit and called nothing: thinking that never ended, or a spec drafted in prose.
                # Never shown. First the same step again with thinking off (the history is unchanged), then
                # the model is told; at the end, a short honest line instead of the ramble.
                if not rethought:
                    rethought, settings = True, replace(self.s, thinking="off")
                    yield {"type": "note", "text": "The model's reply ran too long; asking again, without thinking aloud."}
                    continue
                if nudge("rambled"):
                    messages.append({"role": "assistant", "content": "(a reply that ran to the length limit; not shown)"})
                    messages.append({"role": "user", "content": RAMBLED})
                    continue
                content = ("I could not finish this step: my replies kept running too long. Say \"continue\" and "
                           "I will try again, or tell me which part to do first.")
                messages.append({"role": "assistant", "content": content})
                yield {"type": "answer", "text": content}
                return

            if not calls and not errors and self.modelling and "check_spec" in self.tool_names:
                spec = _spec_in_text(content)
                if spec is not None and nudge("spec_as_text"):
                    # The spec written into the reply: run it through check_spec, as the model meant to.
                    calls = [{"id": "call_" + uuid.uuid4().hex[:10], "type": "function",
                              "function": {"name": "check_spec", "arguments": json.dumps({"spec": spec},
                                                                                         ensure_ascii=False)}}]
                    content = _SPEC_TEXT.sub("", content).strip()
                    pending_feedback = SPEC_AS_TEXT

            if errors and not calls:
                if nudge("broken_call"):
                    messages.append({"role": "assistant", "content": content or "(a tool call that could not be read)"})
                    messages.append({"role": "user", "content": PLATFORM + "Your tool call was NOT run: " + "; ".join(errors)
                                     + ". Send it again through the tool interface, as valid JSON with unique keys."})
                    yield {"type": "result", "name": "tool call", "ok": False, "preview": "; ".join(errors)[:300]}
                    continue

            if not calls:
                if toolcall.looks_like_unrun_call(raw_content) and nudge("call_as_text"):
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": PLATFORM + "That message contains a tool call written "
                                     "as text; it did NOT run. Call the tool through the tool interface."})
                    continue
                if not claimed and not self.did_work and _CLAIM.search(content) and nudge("claim"):
                    claimed = True
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": PLATFORM + "No tool built, imported, placed or solved "
                                     "anything in this turn, so do not say it was done. Run the tool now, or say plainly "
                                     "that nothing ran yet."})
                    continue
                if (self.modelling and not self.built and _GO_AHEAD.search(self._last_person_text(messages))
                        and _ASKS.search(content) and "check_spec" in self.tool_names and nudge("asked_again")):
                    # The blend and camp tests: after "nothing else, go ahead" the model asked "exactly 1000 kg?"
                    # and "shall I proceed?". The person has answered; the answer is not shown, the plan is made.
                    messages.append({"role": "assistant", "content": "(questions after the go-ahead; not shown)"})
                    messages.append({"role": "user", "content": GO_AHEAD_SAID})
                    yield {"type": "note", "text": "The user already said to go ahead; proceeding without asking again."}
                    continue
                stale = stale_totals(content, self._turn_tool_texts(messages))
                if stale and nudge("stale_totals"):
                    messages.append({"role": "assistant", "content": "(an answer with a wrong total; not shown)"})
                    messages.append({"role": "user", "content": PLATFORM + "Your answer was NOT shown: " + "; ".join(
                        f"it says {said} for {field}, but the tools say {right}" for said, right, field in stale)
                        + ". Your earlier replies had that number wrong. Write the answer again with the tools' "
                        "numbers, and say the earlier figure was wrong."})
                    yield {"type": "note", "text": "The answer had a total that the results do not say; asking for the right one."}
                    continue
                # The results this answer rests on: this turn's, or -- when it called no tool (the live job-shop
                # test: a schedule re-typed from memory, with the same wrong machine) -- the latest run results
                # of the conversation.
                basis = self._turn_tool_texts(messages) or self._latest_results(messages)
                wrong = reply_contradictions(content, basis)
                if wrong and nudge("contradiction"):
                    # Checked against the results the model was given before the person sees it.
                    messages.append({"role": "assistant", "content": "(an answer the results contradict; not shown)"})
                    messages.append({"role": "user", "content": PLATFORM + "Your answer was NOT shown: " + "; ".join(wrong)
                                     + ". Write it again, taking every such statement from the result text (RULES, "
                                     "DECISION rows, RESOURCES), and leave out what it does not say."})
                    yield {"type": "note", "text": "The answer said something the results contradict; asking for a corrected one."}
                    continue
                if _SECOND_THOUGHTS.search(content) and nudge("second_thoughts"):
                    # The blend test: "Wait, let's re-verify the scaling..." twice in the answer, then a number
                    # 2.5 times too big. Never shown; the model is asked for the final answer once, with tools.
                    messages.append({"role": "assistant", "content": "(an answer with second thoughts in it; not shown)"})
                    messages.append({"role": "user", "content": SECOND_THOUGHTS})
                    yield {"type": "note", "text": "The answer was still thinking aloud; asking for a clean final answer."}
                    continue
                # Only an answer that reports a run: a reply asking questions or proposing a plan may offer numbers.
                reports = any(_REPORTS_RUN.search(t) for t in basis)
                unsupported = reports and unsupported_numbers(content, basis, [str(sys_msg.get("content") or "")] + [
                    str(m.get("content") or "") for m in messages if m.get("role") in ("user", "tool", "system")])
                if unsupported and nudge("unsupported_numbers", 1):
                    # Every number from the results, the person, or one step of arithmetic on them (plan of
                    # 8 October 2026, honest answers, step 2).
                    messages.append({"role": "assistant", "content": "(an answer with numbers the results do not give; "
                                                                     "not shown)"})
                    messages.append({"role": "user", "content": PLATFORM + "Your answer was NOT shown: these numbers are "
                                     "not in the results or the person's messages, and no single sum, difference, ratio "
                                     "or percentage of their numbers gives them: " + ", ".join(unsupported[:12])
                                     + ". Write it again taking every number from the result text (or one step of "
                                     "arithmetic on its numbers), and leave out any number you cannot take from it."})
                    yield {"type": "note", "text": "The answer had numbers the results do not give; asking for a corrected one."}
                    continue
                what_ifs = reports and unsupported_what_ifs(
                    content, [str(m.get("content") or "") for m in messages if m.get("role") == "tool"],
                    [str(m.get("content") or "") for m in messages if m.get("role") == "user"
                     and not str(m.get("content") or "").startswith(PLATFORM)])
                if what_ifs and nudge("unsupported_what_ifs", 1):
                    # "Would save X if ..." needs a what-if run, or a shadow price inside its range (plan of
                    # 8 October 2026, honest answers).
                    messages.append({"role": "assistant", "content": "(an answer with what-if amounts no run gives; "
                                                                     "not shown)"})
                    messages.append({"role": "user", "content": PLATFORM + "Your answer was NOT shown: it says what "
                                     "a change would do with these amounts, which no what_if run gives and no "
                                     "SENSITIVITY rate gives inside the range it holds for: " + ", ".join(what_ifs[:8])
                                     + ". Call what_if with that change and report its BASE and WHAT-IF lines, or "
                                     "leave the amount out."})
                    yield {"type": "note", "text": "The answer said what a change would do without solving it; asking "
                                                   "for a what-if."}
                    continue
                if not content.strip():
                    if nudge("empty"):
                        messages.append({"role": "assistant", "content": "(an empty reply)"})
                        messages.append({"role": "user", "content": EMPTY})
                        continue
                    content = "I have no answer for that yet. Say \"continue\", or tell me what to do next."
                messages.append({"role": "assistant", "content": content})
                # The facts of the runs read this turn, as the platform renders them: the model explains them,
                # it does not type them (plan of 8 October 2026, honest answers, step 1).
                yield {"type": "answer", "text": content,
                       **({"facts": self._facts_shown()} if self.facts else {})}
                return
            messages.append({"role": "assistant", "content": content or None, "tool_calls": calls})
            if content:
                yield {"type": "note", "text": content[:600]}
            if errors:
                # Some calls ran; the broken ones are reported after their results.
                pending_feedback = PLATFORM + "These tool calls were NOT run: " + "; ".join(errors)
            if self.joined:
                joins = PLATFORM + "Note: " + "; ".join(self.joined) + ". Check that is what you meant."
                pending_feedback = joins if not pending_feedback else pending_feedback + "\n" + joins
                self.joined = []

            plans = [c for c in calls if c["function"]["name"] == "propose_plan"]
            if plans:
                # Only the plan this turn; any other call beside it is dropped (the model re-asks if needed).
                plan = plans[-1]
                messages[-1]["tool_calls"] = [plan]
                args = _args(plan)
                yield {"type": "tool", "name": "propose_plan", "args": _shown("propose_plan", args)}
                verdict = self._check_plan(args)
                if verdict.startswith("PLAN_OK"):
                    body = json.loads(verdict[8:]) if verdict[8:].strip() else {}
                    counts = body.get("would_create", {})
                    # What will be built, read back by the platform beside the model's own account of it -- and
                    # what it does on the data, solved once before anything is kept.
                    built_as = agent_readback.readback(self._spec(args)).split("\n", 1)[-1] + trial_for_person(
                        body.get("trial"))
                    yield {"type": "plan", "summary": str(args.get("summary")) + "\n\n**As built** (read back "
                           "from the spec by the platform; check it says what you meant)\n```\n" + built_as + "\n```",
                           "counts": counts, "spec": self._spec(args, expand=False), "readback": built_as}
                    return  # waits for the person: confirm {allow} builds it, a new message is feedback
                yield {"type": "result", "name": "propose_plan", "ok": False, "preview": verdict[:300]}
                messages.append({"role": "tool", "tool_call_id": plan["id"], "name": "propose_plan",
                                 "content": verdict})
                stop = self._stuck([plan], messages)
                if stop:
                    self._compact_attempts(messages)
                    messages.append({"role": "assistant", "content": stop})
                    yield {"type": "answer", "text": stop}
                    return
                continue

            self._messages = messages
            risky = [c for c in calls if self._needs_ok(c)]
            if risky:
                yield {"type": "confirm", "calls": [
                    {"method": _args(c).get("method"), "path": _args(c).get("path"), "body": _args(c).get("body"),
                     "text": self._asking(c)} for c in risky]}
                return
            self.wrote |= any(self._is_write(c) for c in calls)
            yield from self._execute(calls, messages, None)
            if self.handover is not None:
                # The camp test (October 2026): asked in the Ask tab to solve a layout problem, the Assistant spent
                # 16 minutes making kinds of record and typing 16 records in one by one, then said to switch tabs.
                text_ = (f"{self.handover}\n\nModelling and solving a new problem is done in **Describe a problem**: "
                         "it asks what it needs, shows you the model and builds it when you approve. Use the button "
                         "below to continue there with your message and attached files.")
                messages.append({"role": "assistant", "content": text_})
                yield {"type": "answer", "text": text_}
                yield {"type": "handover", "mode": "model", "text": text_}
                return
            stop = self._stuck(calls, messages)
            if stop:
                self._compact_attempts(messages)
                messages.append({"role": "assistant", "content": stop})
                yield {"type": "answer", "text": stop}
                return
            if self.joined:
                # Put right while the calls ran (a spec's shapes repaired before its check): said now, not a
                # step later.
                joins = PLATFORM + "Note: " + "; ".join(self.joined) + ". Check that is what you meant."
                pending_feedback = joins if not pending_feedback else pending_feedback + "\n" + joins
                self.joined = []
            if pending_feedback:
                messages.append({"role": "user", "content": pending_feedback})
                pending_feedback = None

        messages.append({"role": "assistant", "content":
                         f"I stopped after {self.s.max_steps} steps. Say \"continue\" to let me carry on."})
        yield {"type": "answer", "text": messages[-1]["content"]}
